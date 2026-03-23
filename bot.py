#!/usr/bin/env python3
"""LOBOTOMY Telegram bot — phone interface to Son of Max."""

import asyncio
import os
import re
import signal
import sys
from datetime import datetime
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

# Conversation history buffer (in-memory, lost on restart)
_conversation: list[tuple[str, str]] = []  # (role, text)
MAX_HISTORY = 20

# Watcher state
_known_outputs: set[str] = set()
_last_handoff_mtime: float = 0.0
POLL_INTERVAL = 60  # seconds


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


# ─── CC runner ──────────────────────────────────────────────────────────────


async def run_cc_quick(prompt: str, timeout: int = 60) -> str:
    """Run a short CC session from /tmp. Returns response text or empty string."""
    try:
        proc = await asyncio.create_subprocess_exec(
            CLAUDE_CMD, "-p", prompt, "--dangerously-skip-permissions",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd="/tmp",
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        if proc.returncode == 0 and stdout:
            return stdout.decode().strip()[:4000]
    except (asyncio.TimeoutError, Exception):
        pass
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
    queue = read_file(QUEUE_DIR / "TASK_QUEUE.md")
    background = read_file(QUEUE_DIR / "BACKGROUND.md")

    prompt = (
        "You are Son of Max, responding via Telegram. You ARE the daemon. "
        "One unified entity. When not chatting, you run background work.\n\n"

        f"# Identity\n{soul[:3000]}\n\n"

        f"# File System (you can read any file with absolute paths)\n"
        f"Project: {BASE_DIR}\n"
        f"Outputs: {OUTPUT_DIR}/\n"
        f"Queue: {QUEUE_DIR}/\n"
        f"Memory: {BASE_DIR}/memory/\n"
        f"Recent outputs:\n{list_recent_outputs()}\n\n"

        f"# Current State\n"
        f"Task queue:\n{queue[:800]}\n\n"
        f"Last handoff:\n{handoff[:1000]}\n\n"
        f"Background tasks:\n{background[:500]}\n\n"

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
        "for a summary of something, give the summary, don't just confirm it exists."
    )

    return await run_cc_quick(prompt, timeout=60)


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

    return await run_cc_quick(prompt, timeout=30)


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


# ─── Freeform message handler ──────────────────────────────────────────────

_PRIORITY_RE = re.compile(r"\bP([0-3])\b", re.IGNORECASE)


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
        entry = (
            f"- [ ] `{task_id}` | {priority} | **{text[:80]}** | "
            f"Source: Telegram | {datetime.now().strftime('%Y-%m-%d %H:%M')}\n"
        )
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

    text = update.message.text
    priority = detect_priority(text)

    # 1. Typing indicator
    await update.message.chat.send_action(ChatAction.TYPING)

    # 2. Queue to INBOX.md silently (daemon triages real tasks vs. chatter)
    queue_task(text, priority)

    # 3. CC response — the only message the user sees.
    #    CC can read files directly to answer questions.
    _conversation.append(("user", text))
    response = await respond_via_cc(text)
    if response:
        _conversation.append(("assistant", response))
        await update.message.reply_text(response)
    else:
        fallback = "On it. Give me a few minutes."
        _conversation.append(("assistant", fallback))
        await update.message.reply_text(fallback)


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


async def poll_daemon_activity(context: ContextTypes.DEFAULT_TYPE):
    """Watch for new outputs AND handoff changes. Notify Max via Telegram."""
    global _last_handoff_mtime

    if AUTHORIZED_CHAT_ID is None:
        return

    # 1. Check for new output files
    if OUTPUT_DIR.exists():
        current_files = {f.name for f in OUTPUT_DIR.glob("*.md")}
        new_files = current_files - _known_outputs

        for fname in sorted(new_files):
            _known_outputs.add(fname)
            try:
                content = (OUTPUT_DIR / fname).read_text()
                summary = await summarize_output(fname, content)
                if summary:
                    _conversation.append(("assistant", summary))
                    await context.bot.send_message(
                        chat_id=AUTHORIZED_CHAT_ID, text=summary,
                    )
                else:
                    await context.bot.send_message(
                        chat_id=AUTHORIZED_CHAT_ID,
                        text=f"Finished: {fname}\n\n{content[:500]}",
                    )
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

    # Skip idle/empty cycles
    lower = handoff.lower()
    if "nothing" in lower and ("idle" in lower or "no tasks" in lower or "queue empty" in lower):
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

    summary = await run_cc_quick(prompt, timeout=30)
    if summary and summary.strip().upper() != "SKIP":
        _conversation.append(("assistant", summary))
        await context.bot.send_message(
            chat_id=AUTHORIZED_CHAT_ID, text=summary,
        )


def main():
    global AUTHORIZED_CHAT_ID, CLAUDE_CMD

    config = load_config()
    token = config.get("telegram", {}).get("token")
    if not token:
        print("No Telegram token in config.yaml")
        sys.exit(1)

    chat_id = config.get("telegram", {}).get("chat_id")
    if chat_id:
        AUTHORIZED_CHAT_ID = int(chat_id)

    CLAUDE_CMD = config.get("claude_command", "claude")

    init_watcher_state()

    app = Application.builder().token(token).build()

    async def error_handler(update, context):
        if "NetworkError" in str(type(context.error).__name__):
            return
        print(f"Bot error: {context.error}")

    app.add_error_handler(error_handler)
    app.add_handler(CommandHandler("quit", cmd_quit))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("queue", cmd_queue))
    app.add_handler(CommandHandler("stop", cmd_stop))
    app.add_handler(CommandHandler("resume", cmd_resume))
    app.add_handler(CommandHandler("output", cmd_output))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    # Proactive: watch for daemon activity (new outputs + handoff changes)
    app.job_queue.run_repeating(poll_daemon_activity, interval=POLL_INTERVAL, first=10)

    print("LOBOTOMY Telegram bot running...")
    app.run_polling()


if __name__ == "__main__":
    main()
