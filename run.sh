#!/usr/bin/env bash
# Process supervisor for daemon and bot.
# Both restart automatically on exit (self-improvement, crash, etc.)
# Crash loop protection backs off if a process restarts too often.
# Ctrl-C stops everything cleanly.

set -euo pipefail
cd "$(dirname "$0")"

DAEMON_PID=""
BOT_PID=""
WA_PID=""

# Crash loop detection: track restart timestamps in files.
# If more than MAX_RESTARTS occur within WINDOW seconds, back off.
MAX_RESTARTS=5
WINDOW=300  # 5 minutes
DAEMON_BACKOFF=3
BOT_BACKOFF=3
WA_BACKOFF=3

LOG_DIR="logs"
mkdir -p "$LOG_DIR"

# Crash loop state files (timestamps, one per line)
DAEMON_RESTART_LOG="$LOG_DIR/.daemon_restarts"
BOT_RESTART_LOG="$LOG_DIR/.bot_restarts"
WA_RESTART_LOG="$LOG_DIR/.wa_restarts"
: > "$DAEMON_RESTART_LOG"
: > "$BOT_RESTART_LOG"
: > "$WA_RESTART_LOG"

# ── Venv ────────────────────────────────────────────────────────────────

setup_venv() {
    if [[ ! -d ".venv" ]]; then
        echo "[$(date)] Creating virtual environment..."
        if command -v uv &>/dev/null; then
            uv venv .venv
        else
            python3 -m venv .venv
        fi
    fi
    # shellcheck disable=SC1091
    source .venv/bin/activate
    # Install deps if needed (fast no-op if already installed)
    if command -v uv &>/dev/null; then
        uv pip install -q -r requirements.txt 2>/dev/null || true
    else
        pip install -q -r requirements.txt 2>/dev/null || true
    fi
    echo "[$(date)] Venv active: $(python3 --version), $(which python3)"
}

# ── Stale process cleanup ──────────────────────────────────────────────

kill_stale() {
    local stale
    stale=$(pgrep -f "python3 daemon\.py" 2>/dev/null || true)
    if [[ -n "$stale" ]]; then
        echo "[$(date)] Killing stale daemon PIDs: $stale"
        kill $stale 2>/dev/null || true
        sleep 1
    fi
    stale=$(pgrep -f "python3 bot\.py" 2>/dev/null || true)
    if [[ -n "$stale" ]]; then
        echo "[$(date)] Killing stale bot PIDs: $stale"
        kill $stale 2>/dev/null || true
        sleep 1
    fi
    stale=$(pgrep -f "python3 whatsapp_bot\.py" 2>/dev/null || true)
    if [[ -n "$stale" ]]; then
        echo "[$(date)] Killing stale whatsapp_bot PIDs: $stale"
        kill $stale 2>/dev/null || true
        sleep 1
    fi
    rm -f logs/daemon.pid
}

# ── Crash loop detection ───────────────────────────────────────────────

# Count recent restarts (within WINDOW) from a log file.
# Prunes old entries in place.
count_recent_restarts() {
    local logfile="$1"
    local now cutoff count
    now=$(date +%s)
    cutoff=$((now - WINDOW))
    count=0
    local tmp="${logfile}.tmp"
    : > "$tmp"
    while IFS= read -r ts; do
        if [[ -n "$ts" ]] && (( ts > cutoff )); then
            echo "$ts" >> "$tmp"
            count=$((count + 1))
        fi
    done < "$logfile"
    mv "$tmp" "$logfile"
    echo "$count"
}

record_restart() {
    local logfile="$1"
    date +%s >> "$logfile"
}

# ── Process management ─────────────────────────────────────────────────

start_daemon() {
    local today
    today=$(date +%Y-%m-%d)
    mkdir -p "$LOG_DIR/$today"
    # Clear restart signal before launch so daemon doesn't immediately exit
    rm -f queue/.restart
    python3 daemon.py >> "$LOG_DIR/$today/daemon.log" 2>&1 &
    DAEMON_PID=$!
    echo "[$(date)] Daemon started (PID: $DAEMON_PID, log: $LOG_DIR/$today/daemon.log)"
}

start_bot() {
    local today
    today=$(date +%Y-%m-%d)
    mkdir -p "$LOG_DIR/$today"
    python3 bot.py >> "$LOG_DIR/$today/bot.log" 2>&1 &
    BOT_PID=$!
    echo "[$(date)] Bot started (PID: $BOT_PID, log: $LOG_DIR/$today/bot.log)"
}

start_whatsapp() {
    # Only start if whatsapp-mcp directory exists
    if [[ ! -d "whatsapp-mcp" ]]; then
        echo "[$(date)] whatsapp-mcp/ not found, skipping WhatsApp bot"
        WA_PID=""
        return
    fi
    local today
    today=$(date +%Y-%m-%d)
    mkdir -p "$LOG_DIR/$today"
    rm -f queue/.restart-whatsapp
    python3 whatsapp_bot.py >> "$LOG_DIR/$today/whatsapp.log" 2>&1 &
    WA_PID=$!
    echo "[$(date)] WhatsApp bot started (PID: $WA_PID, log: $LOG_DIR/$today/whatsapp.log)"
}

cleanup() {
    echo "[$(date)] Shutting down..."
    [[ -n "$DAEMON_PID" ]] && kill "$DAEMON_PID" 2>/dev/null || true
    [[ -n "$BOT_PID" ]] && kill "$BOT_PID" 2>/dev/null || true
    [[ -n "$WA_PID" ]] && kill "$WA_PID" 2>/dev/null || true
    wait 2>/dev/null || true
    rm -f logs/daemon.pid "$DAEMON_RESTART_LOG" "$BOT_RESTART_LOG" "$WA_RESTART_LOG"
    echo "[$(date)] Done."
    exit 0
}
trap cleanup SIGINT SIGTERM

# ── Main ───────────────────────────────────────────────────────────────

setup_venv
kill_stale
start_daemon
start_bot
start_whatsapp

echo "LOBOTOMY running (daemon PID: $DAEMON_PID, bot PID: $BOT_PID, wa PID: ${WA_PID:-none})"
echo "Ctrl-C to stop."

while true; do
    sleep 5

    # Daemon restart with crash loop protection
    if ! kill -0 "$DAEMON_PID" 2>/dev/null; then
        record_restart "$DAEMON_RESTART_LOG"
        count=$(count_recent_restarts "$DAEMON_RESTART_LOG")
        if (( count > MAX_RESTARTS )); then
            DAEMON_BACKOFF=$(( DAEMON_BACKOFF * 2 ))
            if (( DAEMON_BACKOFF > 300 )); then DAEMON_BACKOFF=300; fi
            echo "[$(date)] Daemon crash loop ($count restarts in ${WINDOW}s). Backing off ${DAEMON_BACKOFF}s."
        else
            DAEMON_BACKOFF=3
        fi
        echo "[$(date)] Daemon exited. Restarting in ${DAEMON_BACKOFF}s..."
        sleep "$DAEMON_BACKOFF"
        start_daemon
    fi

    # Bot restart with crash loop protection
    if ! kill -0 "$BOT_PID" 2>/dev/null; then
        record_restart "$BOT_RESTART_LOG"
        count=$(count_recent_restarts "$BOT_RESTART_LOG")
        if (( count > MAX_RESTARTS )); then
            BOT_BACKOFF=$(( BOT_BACKOFF * 2 ))
            if (( BOT_BACKOFF > 300 )); then BOT_BACKOFF=300; fi
            echo "[$(date)] Bot crash loop ($count restarts in ${WINDOW}s). Backing off ${BOT_BACKOFF}s."
        else
            BOT_BACKOFF=3
        fi
        echo "[$(date)] Bot exited. Restarting in ${BOT_BACKOFF}s..."
        sleep "$BOT_BACKOFF"
        start_bot
    fi

    # WhatsApp bot restart with crash loop protection
    if [[ -n "$WA_PID" ]] && ! kill -0 "$WA_PID" 2>/dev/null; then
        record_restart "$WA_RESTART_LOG"
        count=$(count_recent_restarts "$WA_RESTART_LOG")
        if (( count > MAX_RESTARTS )); then
            WA_BACKOFF=$(( WA_BACKOFF * 2 ))
            if (( WA_BACKOFF > 300 )); then WA_BACKOFF=300; fi
            echo "[$(date)] WhatsApp bot crash loop ($count restarts in ${WINDOW}s). Backing off ${WA_BACKOFF}s."
        else
            WA_BACKOFF=3
        fi
        echo "[$(date)] WhatsApp bot exited. Restarting in ${WA_BACKOFF}s..."
        sleep "$WA_BACKOFF"
        start_whatsapp
    fi
done
