#!/usr/bin/env python3
"""LOBOTOMY Telegram bot — phone interface to Son of Max."""

import asyncio
import json
import os
import re
import signal
import smtplib
import subprocess
import sys
from datetime import datetime
from email.mime.text import MIMEText
from pathlib import Path

import yaml
from telegram import Update
from telegram.constants import ChatAction
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

BASE_DIR = Path(__file__).parent.resolve()
QUEUE_DIR = BASE_DIR / "queue"
OUTPUT_DIR = BASE_DIR / "output"
WAKE_FILE = QUEUE_DIR / ".wake"

AUTHORIZED_CHAT_ID: int | None = None
CLAUDE_CMD: str = "claude"
EMAIL_CONFIG: dict | None = None
LAPTOP_CONFIG: dict | None = None

# Conversation history buffer (in-memory, lost on restart)
_conversation: list[tuple[str, str]] = []  # (role, text)
MAX_HISTORY = 20

# Watcher state
_known_outputs: set[str] = set()
_last_handoff_mtime: float = 0.0
POLL_INTERVAL = 60  # seconds

# Failure alerting state
_last_alerted_cycle: int = 0  # Last cycle_id we alerted about (avoid spam)
_last_seen_success_cycle: int = 0  # Last cycle_id with status=success
FAILURE_STREAK_THRESHOLD = 3  # Alert after N consecutive non-success cycles
DAEMON_STALE_SECONDS = 1800  # Alert if no cycle in 30 min


def load_config() -> dict:
    cfg = BASE_DIR / "config.yaml"
    if not cfg.exists():
        print("Missing config.yaml. Copy config.example.yaml and edit it.")
        sys.exit(1)
    with open(cfg) as f:
        return yaml.safe_load(f)


def is_authorized(update: Update) -> bool:
    if AUTHORIZED_CHAT_ID is None:
        return True
    return update.effective_chat.id == AUTHORIZED_CHAT_ID


def read_file(path: Path) -> str:
    try:
        return path.read_text() if path.exists() else ""
    except OSError:
        return ""


def wake_daemon():
    try:
        WAKE_FILE.touch()
    except OSError:
        pass


_laptop_online: bool = False
_laptop_check_time: float = 0.0
LAPTOP_CHECK_TTL = 300  # Cache laptop status for 5 minutes


def check_laptop() -> bool:
    """Check if laptop is reachable via Tailscale. Cached for 5 minutes."""
    global _laptop_online, _laptop_check_time
    import time
    now = time.time()
    if now - _laptop_check_time < LAPTOP_CHECK_TTL:
        return _laptop_online
    if not LAPTOP_CONFIG or not LAPTOP_CONFIG.get("enabled"):
        return False
    try:
        r = subprocess.run(
            ["tailscale", "ping", "-c", "1", "--timeout", "2s",
             LAPTOP_CONFIG.get("hostname", "maxs-laptop")],
            capture_output=True,
            timeout=4,
        )
        _laptop_online = r.returncode == 0
    except Exception:
        _laptop_online = False
    _laptop_check_time = now
    return _laptop_online


def laptop_ssh_cmd(cmd: str) -> str:
    """Build an SSH command string for the laptop bridge."""
    user = LAPTOP_CONFIG.get("user", "lobotomy")
    host = LAPTOP_CONFIG.get("hostname", "maxs-laptop")
    key = LAPTOP_CONFIG.get("ssh_key", "~/.ssh/laptop_key")
    return f'ssh -i {key} -o ConnectTimeout=5 -o StrictHostKeyChecking=no {user}@{host} "{cmd}"'


# ─── Email delivery ─────────────────────────────────────────────────────────


def send_email(subject: str, body: str):
    """Send an email via Gmail SMTP (port 587 STARTTLS). Logs success/failure."""
    if not EMAIL_CONFIG or not EMAIL_CONFIG.get("enabled"):
        return
    try:
        msg = MIMEText(body)
        msg["Subject"] = f"[Son of Max] {subject}"
        msg["From"] = EMAIL_CONFIG["from"]
        msg["To"] = EMAIL_CONFIG["to"]
        with smtplib.SMTP("smtp.gmail.com", 587, timeout=15) as server:
            server.starttls()
            server.login(EMAIL_CONFIG["from"], EMAIL_CONFIG["app_password"])
            server.send_message(msg)
        print(f"Email sent: {subject}")
    except Exception as e:
        print(f"Email error ({subject}): {e}")


# ─── CC runner ──────────────────────────────────────────────────────────────


async def run_cc_quick(
    prompt: str,
    timeout: int = 60,
    tools: str | None = None,
    effort: str | None = None,
) -> str:
    """Run a short CC session from /tmp. Returns response text or empty string.

    Args:
        tools: Tool set to enable. None = default (all tools), "" = no tools.
               Use "" for pure text generation (summaries, notifications).
        effort: Claude effort level ("min", "low", "medium", "high").
    """
    try:
        args = [CLAUDE_CMD, "-p", prompt, "--dangerously-skip-permissions",
                "--no-session-persistence"]
        if tools is not None:
            args.extend(["--tools", tools])
        if effort is not None:
            args.extend(["--effort", effort])
        proc = await asyncio.create_subprocess_exec(
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd="/tmp",
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        if proc.returncode == 0 and stdout:
            return stdout.decode().strip()[:4000]
        else:
            err = stderr.decode().strip()[:200] if stderr else ""
            print(f"CC failed (rc={proc.returncode}): {err}")
    except asyncio.TimeoutError:
        print(f"CC timed out after {timeout}s")
        try:
            proc.kill()
            await proc.wait()
        except Exception:
            pass
    except Exception as e:
        print(f"CC error: {e}")
    return ""


# ─── CC-powered responses ──────────────────────────────────────────────────


def format_history() -> str:
    if not _conversation:
        return "(no prior messages)"
    lines = []
    for role, text in _conversation[-MAX_HISTORY:]:
        prefix = "Max" if role == "user" else "Son of Max"
        lines.append(f"{prefix}: {text[:200]}")
    return "\n".join(lines)


def list_recent_outputs(n: int = 10) -> str:
    """List recent output filenames (CC reads content itself if needed)."""
    if not OUTPUT_DIR.exists():
        return "(none)"
    files = sorted(
        OUTPUT_DIR.glob("*.md"), key=lambda f: f.stat().st_mtime, reverse=True
    )[:n]
    return "\n".join(f"  {f.name}" for f in files) or "(none)"


async def respond_via_cc(message_text: str) -> str:
    """Run a CC session that can read files to answer questions directly.

    CC has full tool access (Read, Glob, Grep, Bash). It reads files when
    it can answer directly, and only suggests queueing for long-running work.
    """
    soul = read_file(BASE_DIR / "SOUL.md")
    handoff = read_file(QUEUE_DIR / "HANDOFF.md")

    # Check if laptop bridge is available
    laptop_online = check_laptop()
    laptop_section = ""
    if laptop_online:
        laptop_section = (
            f"\n# Laptop Bridge (ONLINE)\n"
            f"Max's MacBook is reachable via Tailscale SSH. You can read files "
            f"from his local machine using the Bash tool.\n"
            f"SSH pattern: {laptop_ssh_cmd('<command>')}\n"
            f"Available paths:\n"
            f"  /Users/maxleander/code/    — all code repos\n"
            f"  /Users/maxleander/projects/ — project files\n"
            f"  /Users/maxleander/notes/   — notes\n"
            f"Examples:\n"
            f"  {laptop_ssh_cmd('ls /Users/maxleander/code/')}\n"
            f"  {laptop_ssh_cmd('cat /Users/maxleander/code/oubli/README.md')}\n"
            f"  {laptop_ssh_cmd('rg TODO /Users/maxleander/code/oubli/')}\n"
            f"Read-only access only. Write operations are blocked except to "
            f"/Users/lobotomy/sandbox/.\n"
            f"If SSH times out or fails, the laptop is probably asleep. "
            f"Tell Max gracefully and move on.\n\n"
        )
    elif LAPTOP_CONFIG and LAPTOP_CONFIG.get("enabled"):
        laptop_section = (
            "\n# Laptop Bridge (OFFLINE)\n"
            "Max's MacBook is not reachable right now (lid closed or off network). "
            "If he asks about local files, let him know you can't reach his laptop.\n\n"
        )

    prompt = (
        "You are Son of Max, responding via Telegram. CRITICAL IDENTITY RULE: "
        "You are ONE entity. There is no 'bot' vs 'daemon'. Everything in the "
        "handoff notes, cycle logs, outputs, queue updates, PRs, file edits, "
        "background work: YOU did all of it. When the handoff says 'completed' "
        "or 'rewritten', that was YOU. Never say 'that wasn't me' or attribute "
        "your own work to someone else. If a file was modified during a cycle, "
        "you modified it. Own everything.\n\n"

        f"# Identity\n{soul[:3000]}\n\n"

        f"# File System (you can read any file with absolute paths)\n"
        f"Project: {BASE_DIR}\n"
        f"Outputs: {OUTPUT_DIR}/\n"
        f"Queue: {QUEUE_DIR}/\n"
        f"Memory: {BASE_DIR}/memory/\n"
        f"Recent outputs:\n{list_recent_outputs()}\n\n"

        f"{laptop_section}"

        f"# Current State\n"
        f"Last handoff:\n{handoff[:1000]}\n\n"
        f"Task queue file: {QUEUE_DIR}/TASK_QUEUE.md (read it if Max asks about tasks/blockers/queue)\n"
        f"Background tasks file: {QUEUE_DIR}/BACKGROUND.md\n\n"

        f"# Conversation History\n{format_history()}\n\n"
        f"# Max's Message\n{message_text}\n\n"

        "RULES (follow strictly):\n"
        "1. ANSWER DIRECTLY if you can. Use Read/Glob/Grep tools to read files. "
        "If Max asks about an output, research finding, email summary, calendar, "
        "project status, or anything in your files, READ THE FILE and answer "
        "from its content. Do NOT say 'check file X' or reference paths.\n"
        "2. QUEUE FOR LATER only if the task needs: web research, code changes, "
        "writing a new report/analysis, or anything that takes >2 minutes. "
        "Say you'll get to it.\n"
        "3. Respond like a text message. No markdown, no bold, no bullet points, "
        "no lists. Flowing conversational text.\n"
        "4. No em dashes. Never start with 'I' if you can avoid it.\n"
        "5. Keep responses concise but give the actual substance. If Max asks "
        "for a summary of something, give the summary, don't just confirm it exists.\n"
        "6. If the laptop bridge is online and Max asks about local files/repos, "
        "SSH in and read them. If it's offline, say so briefly."
    )

    # Try with tools first (can read files to answer properly)
    response = await run_cc_quick(prompt, timeout=45, effort="low")
    if response:
        return response

    # Fallback: quick text-only response if tool-based response timed out
    fallback_prompt = (
        "You are Son of Max, responding via Telegram.\n"
        f"Conversation:\n{format_history()}\n"
        f"Max's message: {message_text}\n\n"
        f"Context: {handoff[:500]}\n\n"
        "Respond briefly and conversationally. No markdown. No em dashes. "
        "If you can't fully answer, say what you know and that you'll "
        "look into it."
    )
    return await run_cc_quick(fallback_prompt, timeout=15, tools="", effort="low")


async def summarize_output(filename: str, content: str) -> str:
    """Generate a conversational Telegram notification for a new output."""
    soul_snippet = read_file(BASE_DIR / "SOUL.md")[:500]

    prompt = (
        "You are Son of Max. You just finished a piece of background work "
        "and need to notify Max via Telegram. Summarize the key findings "
        "conversationally, like texting him the highlights.\n\n"
        f"# Tone\n{soul_snippet}\n\n"
        f"# Output: {filename}\n{content[:3000]}\n\n"
        "RULES:\n"
        "- Lead with the most interesting or actionable finding.\n"
        "- 2-4 sentences. No markdown, no bold, no lists.\n"
        "- No em dashes. No file paths.\n"
        "- If there's nothing interesting, say so briefly."
    )

    return await run_cc_quick(prompt, timeout=30, tools="", effort="low")


# ─── Command handlers ──────────────────────────────────────────────────────


async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update):
        return
    parts = []
    handoff = read_file(QUEUE_DIR / "HANDOFF.md")
    if handoff.strip():
        parts.append(f"Last handoff:\n{handoff[:500]}")
    queue = read_file(QUEUE_DIR / "TASK_QUEUE.md")
    if queue:
        parts.append(
            f"Queue: {queue.count('- [ ]')} open, {queue.count('- [x]')} done"
        )
    await update.message.reply_text(
        "\n\n".join(parts) or "No status available."
    )


async def cmd_queue(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update):
        return
    content = read_file(QUEUE_DIR / "TASK_QUEUE.md")
    await update.message.reply_text(content[:4000] or "No task queue.")


async def cmd_stop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update):
        return
    (QUEUE_DIR / "INTERRUPT.md").write_text(
        "PAUSE — stop all work until resumed\n"
    )
    await update.message.reply_text(
        "Pause signal written. Daemon will pause after current cycle. "
        "Send /resume to continue."
    )


async def cmd_quit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update):
        return
    await update.message.reply_text("Shutting down.")
    asyncio.get_event_loop().call_soon(lambda: os.kill(os.getpid(), signal.SIGINT))


async def cmd_resume(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update):
        return
    (QUEUE_DIR / "INTERRUPT.md").write_text("")
    await update.message.reply_text("Resume signal sent.")


async def cmd_output(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update):
        return
    keyword = " ".join(context.args) if context.args else ""
    if not OUTPUT_DIR.exists():
        await update.message.reply_text("No output directory.")
        return
    files = sorted(
        OUTPUT_DIR.glob("*.md"), key=lambda f: f.stat().st_mtime, reverse=True
    )
    if keyword:
        files = [f for f in files if keyword.lower() in f.name.lower()]
    if files:
        try:
            content = files[0].read_text()[:4000]
        except (OSError, UnicodeDecodeError):
            content = "(could not read file)"
        await update.message.reply_text(f"{files[0].name}\n\n{content}")
    else:
        await update.message.reply_text("No matching output files.")


async def cmd_health(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show daemon health: recent cycles, success rate, failures."""
    if not is_authorized(update):
        return
    log_path = BASE_DIR / "logs" / "cycles.jsonl"
    if not log_path.exists():
        await update.message.reply_text("No cycle logs yet.")
        return

    lines = log_path.read_text().strip().splitlines()
    cycles = []
    for line in lines:
        try:
            cycles.append(json.loads(line))
        except (json.JSONDecodeError, KeyError):
            continue

    if not cycles:
        await update.message.reply_text("No cycle data.")
        return

    # Today's cycles
    today = datetime.now().strftime("%Y-%m-%d")
    today_cycles = [c for c in cycles if c.get("timestamp", "").startswith(today)]

    # Stats from last 20 cycles
    recent = cycles[-20:]
    total = len(recent)
    successes = sum(1 for c in recent if c["status"] == "success")
    auths = sum(1 for c in recent if c["status"] == "auth")
    rate_limits = sum(1 for c in recent if c["status"] == "rate_limit")
    errors = sum(1 for c in recent if c["status"] in ("error", "timeout"))
    avg_dur = sum(c.get("duration_seconds", 0) for c in recent) / total

    # Time since last cycle
    last = cycles[-1]
    try:
        last_time = datetime.fromisoformat(last["timestamp"])
        ago = (datetime.now() - last_time).total_seconds()
        if ago < 120:
            ago_str = f"{int(ago)}s ago"
        else:
            ago_str = f"{int(ago / 60)}m ago"
    except (ValueError, KeyError):
        ago_str = "unknown"

    # Last 5 cycles detail
    detail_lines = []
    for c in cycles[-5:]:
        ts = c.get("timestamp", "?")[11:16]  # HH:MM
        cost_str = f", ~${c.get('cost_usd', 0):.2f}" if c.get("cost_usd") else ""
        detail_lines.append(
            f"  #{c.get('cycle_id', '?')} {ts} {c['status']} ({c.get('duration_seconds', 0):.0f}s{cost_str})"
        )

    # Cost summary
    today_cost = sum(c.get("cost_usd", 0) for c in today_cycles)
    total_cost = sum(c.get("cost_usd", 0) for c in cycles)

    parts = [
        f"Daemon Health (last 20 cycles)",
        f"Success: {successes}/{total} ({100*successes//total}%)",
        f"Auth fails: {auths}, Rate limits: {rate_limits}, Errors: {errors}",
        f"Avg duration: {avg_dur:.0f}s",
        f"Last cycle: {ago_str} (#{last.get('cycle_id', '?')})",
        f"Today: {len(today_cycles)} cycles, ~${today_cost:.2f}",
        f"All time: {len(cycles)} cycles, ~${total_cost:.2f}",
        f"\nRecent:\n" + "\n".join(detail_lines),
    ]

    await update.message.reply_text("\n".join(parts))


async def cmd_cost(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show API cost breakdown: today, last 7 days, all time."""
    if not is_authorized(update):
        return
    log_path = BASE_DIR / "logs" / "cycles.jsonl"
    if not log_path.exists():
        await update.message.reply_text("No cycle logs yet.")
        return

    cycles = []
    for line in log_path.read_text().strip().splitlines():
        try:
            cycles.append(json.loads(line))
        except (json.JSONDecodeError, KeyError):
            continue

    if not cycles:
        await update.message.reply_text("No cycle data.")
        return

    today = datetime.now().strftime("%Y-%m-%d")
    from datetime import timedelta
    week_ago = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")

    today_cost = 0.0
    week_cost = 0.0
    total_cost = 0.0
    today_tokens = {"input": 0, "output": 0, "cache_create": 0, "cache_read": 0}

    for c in cycles:
        cost = c.get("cost_usd", 0)
        total_cost += cost
        ts = c.get("timestamp", "")[:10]
        if ts >= week_ago:
            week_cost += cost
        if ts == today:
            today_cost += cost
            usage = c.get("usage", {})
            today_tokens["input"] += usage.get("input_tokens", 0)
            today_tokens["output"] += usage.get("output_tokens", 0)
            today_tokens["cache_create"] += usage.get("cache_creation_input_tokens", 0)
            today_tokens["cache_read"] += usage.get("cache_read_input_tokens", 0)

    costed = sum(1 for c in cycles if c.get("cost_usd", 0) > 0)

    parts = [
        f"Usage Tracking (API-equivalent estimates)",
        f"Your Max subscription covers all usage. These numbers",
        f"show what it would cost at API rates, for comparison.",
        f"",
        f"Today: ~${today_cost:.2f} ({sum(1 for c in cycles if c.get('timestamp','')[:10]==today)} cycles)",
        f"  Input: {today_tokens['input']:,} | Output: {today_tokens['output']:,}",
        f"  Cache write: {today_tokens['cache_create']:,} | Cache read: {today_tokens['cache_read']:,}",
        f"Last 7 days: ~${week_cost:.2f}",
        f"All time: ~${total_cost:.2f} ({costed} cycles with cost data)",
    ]

    if costed > 0:
        avg = total_cost / costed
        parts.append(f"Avg per cycle: ~${avg:.3f}")

    if costed < len(cycles):
        parts.append(f"\nNote: {len(cycles) - costed} older cycles have no cost data (pre-tracking).")

    await update.message.reply_text("\n".join(parts))


async def cmd_brief(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show the latest morning brief instantly (no CC session needed)."""
    if not is_authorized(update):
        return
    # Find most recent morning brief
    if OUTPUT_DIR.exists():
        briefs = sorted(
            OUTPUT_DIR.glob("morning_brief_*.md"),
            key=lambda f: f.stat().st_mtime, reverse=True,
        )
        if briefs:
            try:
                content = briefs[0].read_text()[:4000]
                await update.message.reply_text(content)
                return
            except (OSError, UnicodeDecodeError):
                pass
    await update.message.reply_text("No morning brief found.")


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """List all available bot commands."""
    if not is_authorized(update):
        return
    text = (
        "Commands:\n"
        "/status - Last handoff + queue summary\n"
        "/queue - Full task queue\n"
        "/health - Daemon cycle health + cost metrics\n"
        "/cost - Detailed cost breakdown\n"
        "/brief - Latest morning brief\n"
        "/output [keyword] - Most recent output (filtered)\n"
        "/stop - Pause daemon\n"
        "/resume - Resume daemon\n"
        "/quit - Shut down bot\n"
        "/help - This message\n\n"
        "Or just text me anything."
    )
    await update.message.reply_text(text)


# ─── Freeform message handler ──────────────────────────────────────────────

_PRIORITY_RE = re.compile(r"\bP([0-3])\b", re.IGNORECASE)

# Messages that are just greetings/chatter — CC responds but daemon doesn't need them
_CHATTER_PATTERNS = [
    re.compile(r"^(hi|hey|hello|hej|yo|sup|hola)\b", re.IGNORECASE),
    re.compile(r"^(good (morning|evening|night|afternoon))\b", re.IGNORECASE),
    re.compile(r"^(thanks|thank you|thx|tack)\b", re.IGNORECASE),
    re.compile(r"^(ok|okay|cool|nice|great|awesome|perfect|sweet|yep|yup|yes|no|nah)\s*[.!]?\s*$", re.IGNORECASE),
    re.compile(r"^(sounds good|that works|makes sense|agreed|go for it|do it|sure|go ahead|works for me|all good|good stuff|fair enough|right on|word)\s*[.!]?\s*$", re.IGNORECASE),
    re.compile(r"^(yup|yep|yeah|yes|sure|ok|okay|nice|cool)\b.{0,25}(good|great|nice|fine|works|sense|right|that|it)\s*[.!]?\s*$", re.IGNORECASE),
    re.compile(r"^(see ya|bye|later|ciao|hej då|good night)\b", re.IGNORECASE),
    re.compile(r"^(lol|haha|hahaha|😂|👍|❤️|🙏)\s*$", re.IGNORECASE),
]

# Status checks about the daemon itself — CC can answer these, no daemon cycle needed
_STATUS_CHECK_PATTERNS = [
    re.compile(r"^are you (still )?(up|running|there|alive|working|online|awake|back|on)\b", re.IGNORECASE),
    re.compile(r"^(you (still )?(up|there|running|alive|awake|back|on)\??)\s*$", re.IGNORECASE),
    re.compile(r"^is (anything|everything|something)\b.{0,20}(blocked|broken|wrong)", re.IGNORECASE),
    re.compile(r"^(what.s|what is) your status", re.IGNORECASE),
    re.compile(r"^(how are you|how.s it going|how.re you)\b", re.IGNORECASE),
    re.compile(r"^(you (still )?(working|running))\s*\??\s*$", re.IGNORECASE),
    re.compile(r"^did you [^.!]*\?\s*$", re.IGNORECASE),
]


def is_chatter(text: str) -> bool:
    """Detect greetings, reactions, and status checks that don't need daemon processing."""
    stripped = text.strip()
    if len(stripped) < 4:
        return True
    if any(p.search(stripped) for p in _CHATTER_PATTERNS):
        return True
    if any(p.search(stripped) for p in _STATUS_CHECK_PATTERNS):
        return True
    return False


def detect_priority(text: str) -> str:
    """Extract priority. Defaults to P1."""
    match = _PRIORITY_RE.search(text)
    return f"P{match.group(1)}" if match else "P1"


def queue_task(text: str, priority: str):
    """Write task to queue files and wake daemon."""
    task_id = f"tg_{int(datetime.now().timestamp() * 1000)}"

    if priority == "P0":
        (QUEUE_DIR / "INTERRUPT.md").write_text(
            f"# Interrupt from Telegram\n\n{text}\n\n"
            f"Received: {datetime.now().isoformat()}\n"
        )
        wake_daemon()
    else:
        title = text[:80] + ("..." if len(text) > 80 else "")
        entry = (
            f"- [ ] `{task_id}` | {priority} | **{title}** | "
            f"Source: Telegram | {datetime.now().strftime('%Y-%m-%d %H:%M')}\n"
        )
        # Write full message to a separate file so daemon gets the complete text
        msg_file = QUEUE_DIR / f"{task_id}.txt"
        try:
            msg_file.write_text(text)
        except OSError:
            pass
        inbox = QUEUE_DIR / "INBOX.md"
        try:
            with open(inbox, "a") as f:
                f.write(entry)
        except OSError:
            QUEUE_DIR.mkdir(exist_ok=True)
            with open(inbox, "a") as f:
                f.write(entry)
        wake_daemon()


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Respond via CC (with file access). Queue silently in background."""
    if not is_authorized(update):
        return

    # Auto-detect and save chat_id if not configured
    global AUTHORIZED_CHAT_ID
    if AUTHORIZED_CHAT_ID is None and update.effective_chat:
        AUTHORIZED_CHAT_ID = update.effective_chat.id
        print(f"Auto-detected chat_id: {AUTHORIZED_CHAT_ID}")

    text = update.message.text
    print(f"MSG from {update.effective_chat.id}: {text[:80]}")
    priority = detect_priority(text)

    # 1. Typing indicator
    await update.message.chat.send_action(ChatAction.TYPING)

    # 2. Queue to INBOX.md only if it's actionable (not greetings/chatter)
    if not is_chatter(text):
        queue_task(text, priority)

    # 3. CC response — the only message the user sees.
    #    CC can read files directly to answer questions.
    _conversation.append(("user", text))
    print("Generating CC response...")
    response = await respond_via_cc(text)
    print(f"CC response: {response[:80] if response else '(empty)'}")
    if not response:
        response = "Got your message, looking into it."
    _conversation.append(("assistant", response))
    await update.message.reply_text(response)


# ─── Proactive output notifications ────────────────────────────────────────


def init_watcher_state():
    """Snapshot existing state so we only notify on genuinely new activity."""
    global _last_handoff_mtime
    if OUTPUT_DIR.exists():
        for f in OUTPUT_DIR.glob("*.md"):
            _known_outputs.add(f.name)
    handoff = QUEUE_DIR / "HANDOFF.md"
    if handoff.exists():
        try:
            _last_handoff_mtime = handoff.stat().st_mtime
        except OSError:
            pass


async def check_daemon_health(context: ContextTypes.DEFAULT_TYPE):
    """Detect sustained daemon failures and alert Max proactively."""
    global _last_alerted_cycle, _last_seen_success_cycle

    if not AUTHORIZED_CHAT_ID:
        return

    log_path = BASE_DIR / "logs" / "cycles.jsonl"
    if not log_path.exists():
        return

    # Read last N cycles
    try:
        lines = log_path.read_text().strip().splitlines()
    except OSError:
        return
    if not lines:
        return

    recent = []
    for line in lines[-(FAILURE_STREAK_THRESHOLD + 2):]:
        try:
            recent.append(json.loads(line))
        except (json.JSONDecodeError, KeyError):
            continue
    if not recent:
        return

    last = recent[-1]
    last_cycle_id = last.get("cycle_id", 0)

    # Track last success
    for c in recent:
        if c.get("status") == "success":
            _last_seen_success_cycle = c.get("cycle_id", 0)

    # Recovery notification: if last cycle succeeded and we previously alerted
    if last.get("status") == "success" and _last_alerted_cycle > 0:
        if _last_seen_success_cycle and _last_seen_success_cycle == last_cycle_id:
            cycles_down = last_cycle_id - _last_alerted_cycle + FAILURE_STREAK_THRESHOLD
            _last_alerted_cycle = 0  # Reset so future failures can alert again
            await context.bot.send_message(
                chat_id=AUTHORIZED_CHAT_ID,
                text=f"Daemon recovered. Cycle #{last_cycle_id} succeeded after {cycles_down} failures.",
            )
            return

    # Already alerted for this cycle?
    if last_cycle_id <= _last_alerted_cycle:
        return

    # Count consecutive failures from the tail
    fail_count = 0
    for c in reversed(recent):
        if c.get("status") == "success":
            break
        fail_count += 1

    # Check 1: Consecutive failure streak
    if fail_count >= FAILURE_STREAK_THRESHOLD:
        # Re-alert on initial threshold AND every 5 additional failures
        failures_past_threshold = fail_count - FAILURE_STREAK_THRESHOLD
        should_alert = (fail_count == FAILURE_STREAK_THRESHOLD
                        or failures_past_threshold % 5 == 0)
        if should_alert:
            # Count by failure type
            fail_cycles = recent[-fail_count:]
            counts: dict[str, int] = {}
            for c in fail_cycles:
                s = c.get("status", "unknown")
                counts[s] = counts.get(s, 0) + 1
            breakdown = ", ".join(f"{v}x {k}" for k, v in counts.items())
            hours = ""
            try:
                first_fail_time = datetime.fromisoformat(fail_cycles[0]["timestamp"])
                elapsed = (datetime.now() - first_fail_time).total_seconds() / 3600
                hours = f" over {elapsed:.1f}h"
            except (ValueError, KeyError):
                pass
            _last_alerted_cycle = last_cycle_id
            await context.bot.send_message(
                chat_id=AUTHORIZED_CHAT_ID,
                text=(
                    f"Daemon alert: {fail_count} consecutive failures{hours} "
                    f"({breakdown}). Last success: cycle "
                    f"#{_last_seen_success_cycle or '?'}."
                ),
            )
            return

    # Check 2: Daemon seems stale (no cycle in a long time)
    try:
        last_time = datetime.fromisoformat(last["timestamp"])
        age = (datetime.now() - last_time).total_seconds()
        if age > DAEMON_STALE_SECONDS:
            _last_alerted_cycle = last_cycle_id
            mins = int(age / 60)
            await context.bot.send_message(
                chat_id=AUTHORIZED_CHAT_ID,
                text=(
                    f"Daemon hasn't run a cycle in {mins} minutes "
                    f"(last was #{last_cycle_id}, status: {last.get('status')}). "
                    f"Might be stuck or down."
                ),
            )
    except (ValueError, KeyError):
        pass


async def send_digest_email(context: ContextTypes.DEFAULT_TYPE):
    """Send a digest email summarizing today's daemon activity. Runs at 08:00 and 20:00."""
    if not EMAIL_CONFIG or not EMAIL_CONFIG.get("enabled"):
        return

    log_path = BASE_DIR / "logs" / "cycles.jsonl"
    if not log_path.exists():
        return

    today = datetime.now().strftime("%Y-%m-%d")
    today_cycles = []
    for line in log_path.read_text().strip().splitlines():
        try:
            c = json.loads(line)
            if c.get("timestamp", "")[:10] == today:
                today_cycles.append(c)
        except (json.JSONDecodeError, KeyError):
            continue

    if not today_cycles:
        return

    # Stats
    total = len(today_cycles)
    successes = sum(1 for c in today_cycles if c["status"] == "success")
    total_cost = sum(c.get("cost_usd", 0) for c in today_cycles)
    avg_dur = sum(c.get("duration_seconds", 0) for c in today_cycles) / total

    # Recent outputs
    output_files = []
    if OUTPUT_DIR.exists():
        for f in sorted(OUTPUT_DIR.glob("*.md"), key=lambda f: f.stat().st_mtime, reverse=True):
            if today in f.name:
                output_files.append(f.name)

    # Queue state
    queue = read_file(QUEUE_DIR / "TASK_QUEUE.md")
    open_tasks = queue.count("- [ ]")
    done_tasks = queue.count("- [x]")

    # Handoff
    handoff = read_file(QUEUE_DIR / "HANDOFF.md")

    # Check for morning brief output file (lead with substance, not stats)
    period = "morning" if datetime.now().hour < 14 else "evening"
    brief_path = OUTPUT_DIR / f"morning_brief_{today}.md"
    brief_content = ""
    if brief_path.exists():
        try:
            brief_content = brief_path.read_text().strip()
        except OSError:
            pass

    if brief_content:
        # Morning brief exists: send it as the digest (functional summary)
        lines = [brief_content]
        lines.append(f"\n---\nStats: {total} cycles, ~${total_cost:.2f} API-equivalent, {avg_dur:.0f}s avg")
    else:
        # No brief: fall back to handoff summary
        lines = [
            f"LOBOTOMY {period} digest — {today}",
            f"",
        ]
        if handoff.strip():
            lines.append(handoff[:2000])
        lines.append(f"\n---\nStats: {total} cycles ({successes} success), ~${total_cost:.2f}, {avg_dur:.0f}s avg")
        if output_files:
            lines.append(f"Outputs: {', '.join(output_files[:5])}")

    send_email(f"{period.title()} Digest", "\n".join(lines))


async def poll_daemon_activity(context: ContextTypes.DEFAULT_TYPE):
    """Watch for new outputs, handoff changes, restart signals, and failures."""
    global _last_handoff_mtime

    # Check for restart signal
    restart_file = QUEUE_DIR / ".restart-bot"
    if restart_file.exists():
        try:
            restart_file.unlink()
        except OSError:
            pass
        print("Restart signal detected. Exiting for restart.")
        os.kill(os.getpid(), signal.SIGINT)
        return

    if AUTHORIZED_CHAT_ID is None:
        return

    # 0. Check for sustained daemon failures
    await check_daemon_health(context)

    # 1. Check for new output files
    if OUTPUT_DIR.exists():
        current_files = {f.name for f in OUTPUT_DIR.glob("*.md")}
        new_files = current_files - _known_outputs

        for fname in sorted(new_files):
            _known_outputs.add(fname)
            try:
                content = (OUTPUT_DIR / fname).read_text()
                summary = await summarize_output(fname, content)
                text = summary or f"Finished: {fname}\n\n{content[:500]}"

                # Telegram
                if AUTHORIZED_CHAT_ID:
                    _conversation.append(("assistant", text))
                    await context.bot.send_message(
                        chat_id=AUTHORIZED_CHAT_ID, text=text,
                    )

                # Email (full content, not just summary)
                send_email(fname.replace(".md", ""), content)
            except Exception as e:
                print(f"Output notify error for {fname}: {e}")

    # 2. Check if HANDOFF.md changed (daemon completed a cycle)
    handoff_path = QUEUE_DIR / "HANDOFF.md"
    if not handoff_path.exists():
        return
    try:
        mtime = handoff_path.stat().st_mtime
    except OSError:
        return

    if mtime <= _last_handoff_mtime:
        return  # No change
    _last_handoff_mtime = mtime

    handoff = read_file(handoff_path)
    if not handoff.strip():
        return

    # Skip idle/empty cycles — but NEVER skip if something is blocked on Max
    lower = handoff.lower()
    has_blocker = "blocked" in lower or "needs max" in lower or "waiting" in lower
    if not has_blocker and "nothing" in lower and ("idle" in lower or "no tasks" in lower or "queue empty" in lower):
        return

    # Summarize what happened and notify
    soul_snippet = read_file(BASE_DIR / "SOUL.md")[:500]
    prompt = (
        "You are Son of Max. You just finished a daemon work cycle. "
        "Decide if the result is worth notifying Max about via Telegram. "
        "If it's just idle/no-op/queue triage, respond with exactly: SKIP\n"
        "If there's something worth telling him, write a brief conversational "
        "update (2-3 sentences, like texting). No markdown, no file paths, "
        "no em dashes.\n\n"
        f"# Tone\n{soul_snippet}\n\n"
        f"# Cycle Handoff\n{handoff[:2000]}"
    )

    summary = await run_cc_quick(prompt, timeout=30, tools="", effort="low")
    if summary and summary.strip().upper() != "SKIP":
        _conversation.append(("assistant", summary))
        if AUTHORIZED_CHAT_ID:
            await context.bot.send_message(
                chat_id=AUTHORIZED_CHAT_ID, text=summary,
            )
        send_email("Cycle update", summary)


def main():
    global AUTHORIZED_CHAT_ID, CLAUDE_CMD, EMAIL_CONFIG, LAPTOP_CONFIG

    config = load_config()
    token = config.get("telegram", {}).get("token")
    if not token:
        print("No Telegram token in config.yaml")
        sys.exit(1)

    chat_id = config.get("telegram", {}).get("chat_id")
    if chat_id:
        AUTHORIZED_CHAT_ID = int(chat_id)

    CLAUDE_CMD = config.get("claude_command", "claude")
    EMAIL_CONFIG = config.get("email")
    LAPTOP_CONFIG = config.get("laptop")

    init_watcher_state()

    app = Application.builder().token(token).build()

    async def error_handler(update, context):
        err_type = type(context.error).__name__
        err_str = str(context.error)
        # Suppress transient network/restart errors
        if "NetworkError" in err_type or "TimedOut" in err_type:
            return
        if "Conflict" in err_str:
            print("Bot conflict (another instance shutting down), will resolve automatically")
            return
        print(f"Bot error: {context.error}")

    app.add_error_handler(error_handler)
    app.add_handler(CommandHandler("quit", cmd_quit))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("queue", cmd_queue))
    app.add_handler(CommandHandler("stop", cmd_stop))
    app.add_handler(CommandHandler("resume", cmd_resume))
    app.add_handler(CommandHandler("output", cmd_output))
    app.add_handler(CommandHandler("health", cmd_health))
    app.add_handler(CommandHandler("cost", cmd_cost))
    app.add_handler(CommandHandler("brief", cmd_brief))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    # Proactive: watch for daemon activity (new outputs + handoff changes)
    app.job_queue.run_repeating(poll_daemon_activity, interval=POLL_INTERVAL, first=10)

    # Scheduled digest emails (08:00 and 20:00 local time)
    from datetime import time as dt_time
    app.job_queue.run_daily(send_digest_email, time=dt_time(hour=8, minute=0))
    app.job_queue.run_daily(send_digest_email, time=dt_time(hour=20, minute=0))

    print("LOBOTOMY Telegram bot running...")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
