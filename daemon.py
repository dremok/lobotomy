#!/usr/bin/env python3
"""LOBOTOMY daemon — orchestrator loop for autonomous Claude Code sessions."""

import fcntl
import json
import logging
import os
import re
import signal
import subprocess
import sys
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path

import yaml

BASE_DIR = Path(__file__).parent.resolve()
QUEUE_DIR = BASE_DIR / "queue"
WAKE_FILE = QUEUE_DIR / ".wake"
PID_FILE = BASE_DIR / "logs" / "daemon.pid"

# Patterns for detecting issues in CC output
AUTH_ERRORS = [
    "oauth token has expired",
    "authentication_error",
    "please obtain a new token",
    "token expired",
]
RATE_LIMITS = [
    "rate limit exceeded",
    "too many requests",
    "rate_limit_error",
    "throttled",
]

# Claude Opus 4.6 pricing (USD per million tokens)
TOKEN_PRICING = {
    "input": 5.0,
    "output": 25.0,
    "cache_creation": 6.25,
    "cache_read": 0.50,
}

# Track active subprocess for clean shutdown
_active_process: subprocess.Popen | None = None


def deep_merge(base: dict, override: dict) -> dict:
    """Recursively merge override into base, preserving nested dict keys."""
    result = base.copy()
    for k, v in override.items():
        if k in result and isinstance(result[k], dict) and isinstance(v, dict):
            result[k] = deep_merge(result[k], v)
        else:
            result[k] = v
    return result


def load_config() -> dict:
    defaults = {
        "base_cooldown": 300,
        "urgent_cooldown": 30,
        "background_cooldown": 3600,
        "max_cooldown": 1800,
        "backoff_multiplier": 2,
        "session_timeout": 900,
        "health_check_hours": 24,
        "claude_command": "claude",
        "laptop": {"enabled": False, "hostname": "maxs-laptop", "user": "lobotomy", "ssh_key": "~/.ssh/laptop_key"},
        "telegram": {"enabled": False, "token": "", "chat_id": ""},
    }
    cfg = BASE_DIR / "config.yaml"
    if cfg.exists():
        with open(cfg) as f:
            user = yaml.safe_load(f) or {}
        defaults = deep_merge(defaults, user)
    return defaults


def read_file(path: Path) -> str:
    """Read a file, returning empty string if missing or unreadable."""
    try:
        return path.read_text() if path.exists() else ""
    except OSError:
        return ""


def detect_issue(output: str, check_rate_limit: bool = True) -> str | None:
    """Check CC output for auth or rate limit issues."""
    lower = output.lower()
    for p in AUTH_ERRORS:
        if p in lower:
            return "auth"
    if check_rate_limit:
        for p in RATE_LIMITS:
            if p in lower:
                return "rate_limit"
    return None


def extract_usage(output_lines: list[str]) -> dict:
    """Sum token usage across all assistant message events in the stream."""
    totals = {
        "input_tokens": 0,
        "output_tokens": 0,
        "cache_creation_input_tokens": 0,
        "cache_read_input_tokens": 0,
    }
    for line in output_lines:
        stripped = line.strip()
        if not stripped:
            continue
        try:
            event = json.loads(stripped)
            usage = event.get("message", {}).get("usage")
            if not usage:
                continue
            for key in totals:
                totals[key] += usage.get(key, 0)
        except (json.JSONDecodeError, KeyError, TypeError):
            continue
    return totals


def estimate_cost_usd(usage: dict) -> float:
    """Estimate cost in USD from token usage dict."""
    cost = 0.0
    cost += usage.get("input_tokens", 0) * TOKEN_PRICING["input"] / 1_000_000
    cost += usage.get("output_tokens", 0) * TOKEN_PRICING["output"] / 1_000_000
    cost += usage.get("cache_creation_input_tokens", 0) * TOKEN_PRICING["cache_creation"] / 1_000_000
    cost += usage.get("cache_read_input_tokens", 0) * TOKEN_PRICING["cache_read"] / 1_000_000
    return cost


def detect_auth_from_events(output_lines: list[str]) -> bool:
    """Check for auth errors only in system-level output, not agent text.

    The old approach scanned the entire raw output for auth error strings,
    which caused false positives when the agent *discussed* auth errors in
    its response (e.g., "I fixed the authentication_error"). This version
    only checks:
    - Non-JSON lines (raw CLI errors, stderr)
    - JSON events that are NOT assistant content (system, result with is_error)
    """
    # Event types whose text content should be ignored for auth detection.
    # "assistant" and content_block_* contain the agent's own words.
    # "user" events contain tool results (file contents, command output) which
    # can reference auth errors without meaning one actually occurred.
    # "result" events contain the agent's final response text (unless is_error).
    # "rate_limit_event" is informational, not an auth signal.
    skip_types = {
        "assistant", "content_block_delta", "content_block_start", "content_block_stop",
        "user", "rate_limit_event",
    }

    for line in output_lines:
        stripped = line.strip()
        if not stripped:
            continue
        try:
            event = json.loads(stripped)
            evt_type = event.get("type")
            # Skip agent content and informational events
            if evt_type in skip_types:
                continue
            # Result events: only check if is_error (real API error).
            # Non-error results contain the agent's own text.
            if evt_type == "result" and not event.get("is_error"):
                continue
            check_str = stripped.lower()
        except (json.JSONDecodeError, ValueError):
            # Non-JSON line (raw CLI output) — always check
            check_str = stripped.lower()

        for p in AUTH_ERRORS:
            if p in check_str:
                return True

    return False


def _kill_process_group(proc: subprocess.Popen) -> None:
    """Kill a process and its entire process group reliably.

    Uses SIGTERM first (graceful), then SIGKILL if needed. Targets the
    process group (start_new_session=True) so child processes are also killed.
    """
    pgid = None
    try:
        pgid = os.getpgid(proc.pid)
    except (ProcessLookupError, OSError):
        pass

    # Try SIGTERM to the group first
    if pgid is not None:
        try:
            os.killpg(pgid, signal.SIGTERM)
        except (ProcessLookupError, OSError):
            pass
    else:
        try:
            proc.terminate()
        except OSError:
            pass

    try:
        proc.wait(timeout=10)
        return
    except subprocess.TimeoutExpired:
        pass

    # SIGKILL the group
    if pgid is not None:
        try:
            os.killpg(pgid, signal.SIGKILL)
        except (ProcessLookupError, OSError):
            pass
    else:
        try:
            proc.kill()
        except OSError:
            pass

    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        pass  # Give up; process is truly stuck


def run_cc(
    prompt: str,
    workdir: str,
    timeout: int,
    cmd: str = "claude",
    resume_session_id: str | None = None,
    cycle_id: int | None = None,
    fallback_model: str | None = None,
    effort: str | None = None,
    tools: str | None = None,
    max_budget_usd: float | None = None,
    append_system_prompt: str | None = None,
    name: str | None = None,
) -> dict:
    """Run a claude -p session. Streams output to logs/cycle_<id>.jsonl in real time.

    If resume_session_id is provided, uses --resume to continue the daemon's
    own session (not --continue, which grabs the most recent session in the
    directory and could pick up an interactive CC session instead).
    """
    global _active_process

    args = [cmd]
    if resume_session_id:
        args.extend(["--resume", resume_session_id])
    args.extend(["-p", prompt, "--dangerously-skip-permissions",
                 "--output-format", "stream-json", "--verbose"])
    if fallback_model:
        args.extend(["--fallback-model", fallback_model])
    if effort:
        args.extend(["--effort", effort])
    if tools is not None:
        args.extend(["--tools", tools])
    if max_budget_usd is not None:
        args.extend(["--max-budget-usd", str(max_budget_usd)])
    if append_system_prompt:
        args.extend(["--append-system-prompt", append_system_prompt])
    if name:
        args.extend(["--name", name])

    # Per-cycle log file: logs/2026-03-20/cycle_042_1200.log
    log_path = None
    if cycle_id is not None:
        now = datetime.now()
        day_dir = BASE_DIR / "logs" / now.strftime("%Y-%m-%d")
        day_dir.mkdir(exist_ok=True)
        log_path = day_dir / f"cycle_{cycle_id:04d}_{now.strftime('%H%M')}.jsonl"

    start = time.monotonic()
    try:
        proc = subprocess.Popen(
            args,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,  # Merge stderr into stdout
            text=True,
            cwd=workdir,
            start_new_session=True,  # Own process group for clean killpg
        )
        _active_process = proc

        # Stream output to log file in a reader thread
        output_lines: list[str] = []
        log_f = open(log_path, "w") if log_path else None
        auth_detected = threading.Event()

        # Event types containing agent/tool text (not system errors)
        _skip_types = {
            "assistant", "content_block_delta", "content_block_start",
            "content_block_stop", "user", "rate_limit_event",
        }

        def reader():
            for line in proc.stdout:
                output_lines.append(line)
                if log_f:
                    log_f.write(line)
                    log_f.flush()
                # Real-time auth error detection in stream
                if auth_detected.is_set():
                    continue
                stripped = line.strip()
                if not stripped:
                    continue
                check_str = None
                try:
                    event = json.loads(stripped)
                    evt_type = event.get("type")
                    if evt_type not in _skip_types:
                        if not (evt_type == "result" and not event.get("is_error")):
                            check_str = stripped.lower()
                except (json.JSONDecodeError, ValueError):
                    check_str = stripped.lower()
                if check_str:
                    for p in AUTH_ERRORS:
                        if p in check_str:
                            auth_detected.set()
                            break

        t = threading.Thread(target=reader, daemon=True)
        t.start()

        # Wait for process, with early termination on auth errors
        timed_out = False
        deadline = time.monotonic() + timeout
        while proc.poll() is None:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                timed_out = True
                _kill_process_group(proc)
                break
            if auth_detected.wait(timeout=min(5, remaining)):
                # Auth error in stream — kill early instead of waiting
                _kill_process_group(proc)
                break

        t.join(timeout=10)
        _active_process = None
        if log_f:
            if timed_out:
                log_f.write("\n=== TIMEOUT ===\n")
            elif auth_detected.is_set():
                log_f.write("\n=== EARLY AUTH TERMINATION ===\n")
            log_f.close()

        if timed_out:
            return {"status": "timeout", "output": "", "duration": time.monotonic() - start}

        dur = time.monotonic() - start
        raw = "".join(output_lines)

        # Parse stream-json: find the result event
        result_text = ""
        for line in reversed(output_lines):
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
                if event.get("type") == "result":
                    result_text = event.get("result", "")
                    if event.get("is_error"):
                        return {"status": "error", "output": result_text, "duration": dur}
                    break
            except (json.JSONDecodeError, KeyError):
                continue

        # Check for auth errors in system-level output only (not agent text,
        # which can discuss auth errors without meaning one actually occurred)
        if detect_auth_from_events(output_lines):
            return {"status": "auth", "output": raw, "duration": dur}

        # Check for actual rate limit via result event
        for line in reversed(output_lines):
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
                if event.get("type") == "rate_limit_event":
                    if event.get("rate_limit_info", {}).get("status") != "allowed":
                        return {"status": "rate_limit", "output": raw, "duration": dur}
                    break
            except (json.JSONDecodeError, KeyError):
                continue

        if proc.returncode != 0:
            return {"status": "error", "output": raw, "duration": dur}

        # Extract session_id for --resume on next cycle
        session_id = None
        for line in output_lines:
            try:
                event = json.loads(line.strip())
                if event.get("type") == "result" and "session_id" in event:
                    session_id = event["session_id"]
                    break
            except (json.JSONDecodeError, KeyError):
                continue

        usage = extract_usage(output_lines)
        return {"status": "success", "output": result_text, "duration": dur,
                "session_id": session_id, "usage": usage,
                "cost_usd": estimate_cost_usd(usage)}
    except Exception:
        _active_process = None
        return {"status": "error", "output": "", "duration": time.monotonic() - start}


def recent_cycles(n: int = 5) -> str:
    """Summary of last N cycles for inclusion in the prompt."""
    log_path = BASE_DIR / "logs" / "cycles.jsonl"
    if not log_path.exists():
        return "(no previous cycles)"
    lines = log_path.read_text().strip().splitlines()
    entries = []
    for line in lines[-n:]:
        try:
            c = json.loads(line)
            cost_str = f", ${c['cost_usd']:.3f}" if "cost_usd" in c else ""
            entries.append(
                f"  #{c['cycle_id']} {c['timestamp']} — {c['status']} ({c['duration_seconds']}s{cost_str})"
            )
        except (json.JSONDecodeError, KeyError):
            continue
    return "\n".join(entries) if entries else "(no previous cycles)"


def cost_summary() -> str:
    """One-line cost summary for the cycle prompt."""
    log_path = BASE_DIR / "logs" / "cycles.jsonl"
    if not log_path.exists():
        return ""
    today = datetime.now().strftime("%Y-%m-%d")
    today_cost = 0.0
    total_cost = 0.0
    for line in log_path.read_text().strip().splitlines():
        try:
            c = json.loads(line)
            cost = c.get("cost_usd", 0)
            total_cost += cost
            if c.get("timestamp", "")[:10] == today:
                today_cost += cost
        except (json.JSONDecodeError, KeyError):
            continue
    if total_cost == 0:
        return ""
    return f"COST: ~${today_cost:.2f} today, ~${total_cost:.2f} all time (API-equivalent estimate, actual billing via Max subscription)"


def build_prompt(
    cycle_id: int,
    laptop_online: bool | None = None,
    laptop_config: dict | None = None,
    continued: bool = False,
) -> str:
    """Build the cycle prompt passed to claude -p."""
    now = datetime.now()
    lines = [
        f"CYCLE #{cycle_id}",
        f"TIME: {now.strftime('%Y-%m-%d %H:%M:%S')} ({now.strftime('%A')})",
    ]
    if continued:
        lines.append(
            "SESSION: continued (you have context from previous cycles; "
            "re-read queue files for external changes)"
        )
    else:
        lines.append(
            "SESSION: fresh (no prior context; SOUL.md is in your system "
            "prompt, read CLAUDE.md and all queue files)"
        )
    interrupt_content = read_file(QUEUE_DIR / "INTERRUPT.md")
    if interrupt_content.strip() and "PAUSE" not in interrupt_content.upper():
        lines.append("STATUS: P0 INTERRUPT in queue/INTERRUPT.md — handle first.")
    inbox_content = read_file(QUEUE_DIR / "INBOX.md")
    if inbox_content.strip():
        lines.append("INBOX: New tasks in queue/INBOX.md — integrate into queue.")
    if laptop_online is not None:
        if laptop_online and laptop_config:
            user = laptop_config.get("user", "lobotomy")
            host = laptop_config.get("hostname", "maxs-laptop")
            key = laptop_config.get("ssh_key", "~/.ssh/laptop_key")
            ssh_prefix = f"ssh -i {key} -o ConnectTimeout=5 -o StrictHostKeyChecking=no {user}@{host}"
            lines.append(
                f"LAPTOP: online (read-only SSH via: {ssh_prefix} \"<cmd>\")\n"
                f"  Paths: /Users/maxleander/code/, /Users/maxleander/projects/, /Users/maxleander/notes/\n"
                f"  Allowed: cat, ls, find, head, tail, rg, grep, git log/status/diff, tree, du\n"
                f"  If SSH fails, laptop went to sleep. Note it in HANDOFF.md."
            )
        else:
            lines.append("LAPTOP: offline")
    cost_line = cost_summary()
    if cost_line:
        lines.append(cost_line)
    lines.append(f"RECENT ACTIVITY:\n{recent_cycles()}")
    lines.append(
        "Execute your cycle protocol. "
        "Do one unit of work, write queue/HANDOFF.md, then exit."
    )
    return "\n".join(lines)


def is_paused() -> bool:
    """Check if a PAUSE signal exists in INTERRUPT.md."""
    content = read_file(QUEUE_DIR / "INTERRUPT.md")
    return "PAUSE" in content.upper()


def has_urgent_tasks() -> bool:
    """Check if P0 or P1 tasks exist."""
    interrupt = read_file(QUEUE_DIR / "INTERRUPT.md")
    if interrupt.strip() and "PAUSE" not in interrupt.upper():
        return True
    inbox = read_file(QUEUE_DIR / "INBOX.md")
    if inbox.strip():
        return True  # New tasks from Telegram = worth waking up for
    content = read_file(QUEUE_DIR / "TASK_QUEUE.md")
    in_p1 = False
    for line in content.splitlines():
        if "### P1" in line:
            in_p1 = True
        elif line.startswith("###"):
            in_p1 = False
        elif in_p1 and "- [ ]" in line:
            if "BLOCKED" not in line.upper():
                return True
    return False


def has_queued_tasks() -> bool:
    """Check if any actionable P1-P2 tasks exist.

    Excludes P3 (recurring, always unchecked) and BLOCKED tasks.
    P3 timing is handled by seconds_until_next_schedule().
    """
    content = read_file(QUEUE_DIR / "TASK_QUEUE.md")
    in_task_section = False
    for line in content.splitlines():
        if "### P1" in line or "### P2" in line:
            in_task_section = True
        elif line.startswith("###"):
            in_task_section = False
        elif in_task_section and "- [ ]" in line:
            if "BLOCKED" not in line.upper():
                return True
    return False


def seconds_until_next_schedule() -> float | None:
    """Parse P3 cron specs from TASK_QUEUE.md and return seconds until the next one.

    Supports: "Cron: HH:MM daily", "Cron: <Day> HH:MM",
              "Cron: <Day>+<Day> HH:MM"
    Returns None if no schedules found or all are unparseable.
    """
    content = read_file(QUEUE_DIR / "TASK_QUEUE.md")
    now = datetime.now()
    day_names = {
        "monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3,
        "friday": 4, "saturday": 5, "sunday": 6,
    }

    nearest = None
    for line in content.splitlines():
        if "- [ ]" not in line or "Cron:" not in line:
            continue
        # Extract the cron spec after "Cron:"
        match = re.search(r"Cron:\s*(.+?)(?:\s*$|\|)", line)
        if not match:
            continue
        spec = match.group(1).strip().lower()

        # Parse time (HH:MM)
        time_match = re.search(r"(\d{1,2}):(\d{2})", spec)
        if not time_match:
            continue
        hour, minute = int(time_match.group(1)), int(time_match.group(2))

        # Determine which days this fires
        if "daily" in spec:
            target_days = list(range(7))
        else:
            target_days = []
            for part in re.split(r"[+,&]", spec):
                part = part.strip().rstrip("s")  # "wednesdays" -> "wednesday"
                for name, num in day_names.items():
                    if name.startswith(part):
                        target_days.append(num)

        if not target_days:
            continue

        # Find the next occurrence
        for days_ahead in range(8):  # Check up to a week ahead
            candidate = now.replace(
                hour=hour, minute=minute, second=0, microsecond=0
            )
            candidate = candidate + timedelta(days=days_ahead)
            if candidate.weekday() in target_days and candidate > now:
                delta = (candidate - now).total_seconds()
                if nearest is None or delta < nearest:
                    nearest = delta
                break

    return nearest


def get_next_cycle_id() -> int:
    """Read last cycle ID from log, tolerating corrupt lines."""
    log_path = BASE_DIR / "logs" / "cycles.jsonl"
    if log_path.exists():
        lines = log_path.read_text().strip().splitlines()
        for line in reversed(lines):
            try:
                return json.loads(line).get("cycle_id", 0) + 1
            except (json.JSONDecodeError, KeyError):
                continue
    return 1


def log_cycle(cycle_id: int, result: dict, cooldown: float):
    entry = {
        "cycle_id": cycle_id,
        "timestamp": datetime.now().isoformat(),
        "status": result["status"],
        "duration_seconds": round(result.get("duration", 0), 1),
        "cooldown": round(cooldown),
    }
    if "usage" in result:
        entry["usage"] = result["usage"]
        entry["cost_usd"] = round(result.get("cost_usd", 0), 4)
    log_path = BASE_DIR / "logs" / "cycles.jsonl"
    try:
        # Guard against duplicate cycle IDs (from past multi-daemon bugs)
        if log_path.exists():
            for line in reversed(log_path.read_text().strip().splitlines()[-5:]):
                try:
                    if json.loads(line).get("cycle_id") == cycle_id:
                        return  # Already logged
                except (json.JSONDecodeError, KeyError):
                    continue
        with open(log_path, "a") as f:
            f.write(json.dumps(entry) + "\n")
    except OSError:
        pass


def check_laptop(config: dict) -> bool | None:
    """Check if laptop is reachable on Tailscale. None if bridge disabled."""
    laptop = config.get("laptop", {})
    if not laptop.get("enabled"):
        return None
    try:
        r = subprocess.run(
            ["tailscale", "ping", "-c", "1", "--timeout", "3s",
             laptop.get("hostname", "maxs-laptop")],
            capture_output=True,
            timeout=5,
        )
        return r.returncode == 0
    except Exception:
        return False


def run_health_check(cmd: str = "claude"):
    report = {"timestamp": datetime.now().isoformat()}
    try:
        r = subprocess.run(
            [cmd, "--version"], capture_output=True, text=True, timeout=10
        )
        report["cc_version"] = r.stdout.strip()
    except Exception:
        report["cc_version"] = "unknown"
    try:
        r = subprocess.run(
            ["df", "-h", str(BASE_DIR)], capture_output=True, text=True
        )
        report["disk"] = r.stdout.strip()
    except Exception:
        pass
    try:
        with open(BASE_DIR / "logs" / "health.jsonl", "a") as f:
            f.write(json.dumps(report) + "\n")
    except OSError:
        pass


def interruptible_sleep(seconds: float) -> bool:
    """Sleep in 5-second chunks. Returns True if woken early by wake file."""
    end_time = time.time() + seconds
    while time.time() < end_time:
        if WAKE_FILE.exists():
            try:
                WAKE_FILE.unlink()
            except OSError:
                pass
            return True
        time.sleep(min(5, max(0, end_time - time.time())))
    return False


def ensure_dirs():
    for d in ["queue", "workspaces", "output", "logs", "memory"]:
        (BASE_DIR / d).mkdir(exist_ok=True)
    for name in ["HANDOFF.md", "INTERRUPT.md", "INBOX.md"]:
        path = QUEUE_DIR / name
        if not path.exists():
            path.write_text("")


def main():
    global _active_process

    ensure_dirs()

    # Single-instance guard: fcntl.flock() for atomic mutual exclusion.
    # The PID file approach had race conditions; flock is kernel-level.
    lock_file = BASE_DIR / "logs" / "daemon.lock"
    lock_fd = open(lock_file, "w")
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        # Another daemon holds the lock
        print("Another daemon instance is already running (flock held). Exiting.")
        lock_fd.close()
        sys.exit(1)
    # Lock acquired. Write PID for observability (not for locking).
    my_pid = os.getpid()
    PID_FILE.write_text(str(my_pid))

    # Kill stale daemon processes from before the lockfile era.
    # The flock guarantees we're the only legitimate instance, so any
    # other daemon.py process is a zombie from a pre-lockfile launch.
    try:
        r = subprocess.run(
            ["pgrep", "-f", "python3 daemon.py"],
            capture_output=True, text=True, timeout=5,
        )
        for pid_str in r.stdout.strip().splitlines():
            try:
                pid = int(pid_str.strip())
                if pid != my_pid:
                    os.kill(pid, signal.SIGTERM)
                    print(f"Killed stale daemon PID {pid}")
            except (ValueError, ProcessLookupError, PermissionError):
                pass
    except Exception:
        pass

    config = load_config()
    run_once = "--once" in sys.argv

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[
            logging.FileHandler(BASE_DIR / "logs" / "daemon.log"),
            logging.StreamHandler(),
        ],
    )
    log = logging.getLogger("lobotomy")

    def shutdown(signum, _):
        log.info(f"Signal {signum}. Cleaning up.")
        if _active_process and _active_process.poll() is None:
            _kill_process_group(_active_process)
        PID_FILE.unlink(missing_ok=True)
        fcntl.flock(lock_fd, fcntl.LOCK_UN)
        lock_fd.close()
        sys.exit(0)

    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)

    cooldown = config["base_cooldown"]
    auth_valid = True
    last_health = None
    cycle_id = get_next_cycle_id()

    # Persist session ID across restarts
    session_file = BASE_DIR / "logs" / "session_id"
    daemon_session_id: str | None = None
    session_cycle_count = 0
    session_reset_interval = config.get("session_reset_interval", 15)
    if session_file.exists():
        sid = session_file.read_text().strip()
        if sid:
            daemon_session_id = sid
            log.info(f"Restored session {sid[:8]}...")

    # Load SOUL.md once for injection via --append-system-prompt
    soul_path = BASE_DIR / "SOUL.md"
    soul_content = read_file(soul_path) if soul_path.exists() else ""

    log.info(f"LOBOTOMY starting at cycle #{cycle_id}")

    while True:
        # Pause handling
        if is_paused():
            log.info("Paused. Checking every 60s.")
            time.sleep(60)
            continue

        # Auth recovery
        if not auth_valid:
            log.warning("Auth invalid. Testing...")
            test = run_cc(
                "respond with OK", str(BASE_DIR), 30, config["claude_command"],
                tools="",
            )
            if test["status"] == "success":
                auth_valid = True
                log.info("Auth restored.")
            else:
                log.info("Auth still invalid. Sleeping 300s (interruptible).")
                interruptible_sleep(300)
                continue

        # Daily health check
        now = datetime.now()
        health_interval = config["health_check_hours"] * 3600
        if last_health is None or (now - last_health).total_seconds() > health_interval:
            log.info("Running health check")
            run_health_check(config["claude_command"])
            last_health = now

        # Periodic session reset to prevent context bloat.
        # Accumulated conversation history grows cache writes each cycle.
        # Resetting every N cycles brings costs back down.
        if daemon_session_id and session_cycle_count >= session_reset_interval:
            log.info(
                f"Session reset after {session_cycle_count} cycles "
                f"(interval: {session_reset_interval})"
            )
            daemon_session_id = None
            session_file.unlink(missing_ok=True)
            session_cycle_count = 0

        # Run cycle
        laptop = check_laptop(config)
        resuming = daemon_session_id is not None
        laptop_cfg = config.get("laptop")
        prompt = build_prompt(cycle_id, laptop, laptop_config=laptop_cfg, continued=resuming)

        mode = f"resume {daemon_session_id[:8]}..." if resuming else "fresh"
        log.info(f"Cycle #{cycle_id} starting ({mode})")

        fallback = config.get("fallback_model")
        urgent = has_urgent_tasks()
        effort = "high" if urgent else config.get("background_effort", "medium")
        budget = config.get("max_budget_usd")
        timeout = config["session_timeout"] if urgent else config.get("background_timeout", config["session_timeout"])
        result = run_cc(
            prompt,
            str(BASE_DIR),
            timeout,
            config["claude_command"],
            resume_session_id=daemon_session_id,
            cycle_id=cycle_id,
            fallback_model=fallback,
            effort=effort,
            max_budget_usd=budget,
            append_system_prompt=soul_content if soul_content else None,
            name="lobotomy-daemon",
        )

        # If --resume failed, retry as fresh session. Skip retry for
        # timeouts on background work (no urgent tasks) to avoid wasting
        # another 900s on work that will likely timeout again.
        if resuming and result["status"] in ("error", "timeout"):
            should_retry = result["status"] == "error" or has_urgent_tasks()
            if should_retry:
                log.warning("Resumed session failed. Retrying fresh.")
                daemon_session_id = None
                session_file.unlink(missing_ok=True)
                prompt = build_prompt(cycle_id, laptop, laptop_config=laptop_cfg, continued=False)
                result = run_cc(
                    prompt,
                    str(BASE_DIR),
                    config["session_timeout"],
                    config["claude_command"],
                    resume_session_id=None,
                    cycle_id=cycle_id,
                    fallback_model=fallback,
                    effort=effort,
                    max_budget_usd=budget,
                    append_system_prompt=soul_content if soul_content else None,
                    name="lobotomy-daemon",
                )
            else:
                log.warning("Resumed session timed out on background work. Skipping fresh retry.")
                daemon_session_id = None
                session_file.unlink(missing_ok=True)

        log.info(
            f"Cycle #{cycle_id}: {result['status']} "
            f"({result.get('duration', 0):.0f}s)"
        )

        # Determine cooldown based on result and queue state
        if result["status"] == "auth":
            auth_valid = False
            daemon_session_id = None
            session_file.unlink(missing_ok=True)
            session_cycle_count = 0
            cooldown = 300
            log.error("Auth failure detected")
            # Write handoff so bot can alert Max via Telegram
            handoff = QUEUE_DIR / "HANDOFF.md"
            handoff.write_text(
                f"# Auth Failure — {datetime.now().strftime('%Y-%m-%d %H:%M')}\n\n"
                "CC authentication expired. Daemon is paused until re-auth.\n\n"
                "## BLOCKED: needs Max\n\n"
                "To fix: `ssh -L 7776:localhost:7776 max@204.168.180.135` "
                "then run `claude /login` on the VPS.\n"
            )
        elif result["status"] == "rate_limit":
            cooldown = min(
                cooldown * config["backoff_multiplier"], config["max_cooldown"]
            )
            log.warning(f"Rate limited. Cooldown: {cooldown}s")
        elif result["status"] in ("error", "timeout"):
            daemon_session_id = None
            session_file.unlink(missing_ok=True)
            session_cycle_count = 0
            cooldown = min(cooldown * 1.5, config["max_cooldown"])
            log.warning(f"Cycle failed: {result['status']}")
        else:
            # Capture session ID for --resume on next cycle (persisted to file)
            if result.get("session_id"):
                daemon_session_id = result["session_id"]
                session_cycle_count += 1
                try:
                    session_file.write_text(daemon_session_id)
                except OSError:
                    pass
            if has_urgent_tasks():
                cooldown = config["urgent_cooldown"]
            elif has_queued_tasks():
                cooldown = config["base_cooldown"]
            else:
                cooldown = config["background_cooldown"]

        # Cap cooldown so we don't sleep past a scheduled task
        next_sched = seconds_until_next_schedule()
        if next_sched is not None and next_sched < cooldown:
            cooldown = max(next_sched, config["urgent_cooldown"])
            log.info(f"Next scheduled task in {next_sched:.0f}s, capping cooldown")

        log_cycle(cycle_id, result, cooldown)
        cycle_id += 1

        # Check for restart signal (self-improvement modified code)
        restart_file = QUEUE_DIR / ".restart"
        if restart_file.exists():
            try:
                restart_file.unlink()
            except OSError:
                pass
            log.info("Restart signal detected. Exiting for restart.")
            break

        if run_once:
            log.info("--once flag set. Exiting after single cycle.")
            break

        log.info(f"Sleeping {cooldown:.0f}s (wake file interrupts)")
        woken = interruptible_sleep(cooldown)
        if woken:
            log.info("Woken early by wake signal")


if __name__ == "__main__":
    main()
