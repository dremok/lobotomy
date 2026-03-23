#!/usr/bin/env python3
"""LOBOTOMY WhatsApp bot — monitors a group chat for mentions of Son of Max."""

import asyncio
import json
import os
import re
import signal
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import yaml

BASE_DIR = Path(__file__).parent.resolve()
QUEUE_DIR = BASE_DIR / "queue"
WAKE_FILE = QUEUE_DIR / ".wake"
WHATSAPP_DIR = BASE_DIR / "whatsapp-mcp"

CLAUDE_CMD: str = "claude"
GROUP_JID: str = ""  # Set from config
TRIGGER_RE = re.compile(
    r"\b(son of max|som)\b", re.IGNORECASE
)

# Track which messages we've already handled
_last_seen_ts: float = 0.0
_seen_message_ids: set[str] = set()
POLL_INTERVAL = 60  # seconds
MAX_SEEN_IDS = 500  # Cap the set size

# State file to persist last_seen_ts across restarts
STATE_FILE = BASE_DIR / "logs" / "whatsapp_state.json"


def load_config() -> dict:
    cfg = BASE_DIR / "config.yaml"
    if not cfg.exists():
        print("Missing config.yaml.")
        sys.exit(1)
    with open(cfg) as f:
        return yaml.safe_load(f)


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


def save_state():
    try:
        STATE_FILE.write_text(json.dumps({
            "last_seen_ts": _last_seen_ts,
        }))
    except OSError:
        pass


def load_state():
    global _last_seen_ts
    if STATE_FILE.exists():
        try:
            data = json.loads(STATE_FILE.read_text())
            _last_seen_ts = data.get("last_seen_ts", 0.0)
        except (json.JSONDecodeError, OSError):
            pass


# ─── MCP Client ──────────────────────────────────────────────────────────────


class MCPClient:
    """Communicates with the WhatsApp MCP server via JSON-RPC over stdio."""

    def __init__(self, mcp_dir: Path):
        self.mcp_dir = mcp_dir
        self.proc: subprocess.Popen | None = None
        self.request_id = 0
        self._lock = asyncio.Lock()

    async def start(self):
        """Start the MCP server subprocess."""
        self.proc = subprocess.Popen(
            ["node", "src/main.ts"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=str(self.mcp_dir),
        )
        # Wait for the MCP server to initialize
        await asyncio.sleep(5)
        # Send initialize handshake
        resp = await self._send("initialize", {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "lobotomy-whatsapp-bot", "version": "1.0.0"},
        })
        if resp and not resp.get("error"):
            # Send initialized notification (no response expected)
            await self._notify("notifications/initialized")
            print("MCP client connected to WhatsApp bridge.")
            return True
        print(f"MCP initialize failed: {resp}")
        return False

    def is_alive(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    async def stop(self):
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait()
        self.proc = None

    async def _send(self, method: str, params: dict | None = None) -> dict | None:
        """Send a JSON-RPC request and read the response."""
        async with self._lock:
            if not self.is_alive():
                return None
            self.request_id += 1
            msg = {"jsonrpc": "2.0", "id": self.request_id, "method": method}
            if params is not None:
                msg["params"] = params
            return await asyncio.get_event_loop().run_in_executor(
                None, self._send_sync, msg
            )

    async def _notify(self, method: str, params: dict | None = None):
        """Send a JSON-RPC notification (no response expected)."""
        async with self._lock:
            if not self.is_alive():
                return
            msg = {"jsonrpc": "2.0", "method": method}
            if params is not None:
                msg["params"] = params
            await asyncio.get_event_loop().run_in_executor(
                None, self._write_message, msg
            )
            # Small delay to let the server process it
            await asyncio.sleep(0.5)

    def _write_message(self, msg: dict):
        """Write a Content-Length framed message to stdin."""
        body = json.dumps(msg)
        header = f"Content-Length: {len(body)}\r\n\r\n"
        self.proc.stdin.write(header.encode() + body.encode())
        self.proc.stdin.flush()

    def _read_message(self) -> dict | None:
        """Read a Content-Length framed message from stdout."""
        # Read headers until empty line
        headers = {}
        while True:
            line = self.proc.stdout.readline()
            if not line:
                return None
            line = line.decode().strip()
            if line == "":
                break
            if ":" in line:
                key, val = line.split(":", 1)
                headers[key.strip()] = val.strip()
        content_length = int(headers.get("Content-Length", 0))
        if content_length == 0:
            return None
        body = self.proc.stdout.read(content_length)
        if not body:
            return None
        return json.loads(body.decode())

    def _send_sync(self, msg: dict) -> dict | None:
        """Synchronous send + receive (run in executor)."""
        try:
            self._write_message(msg)
            # Read responses, skipping notifications until we get our reply
            deadline = time.time() + 30
            while time.time() < deadline:
                resp = self._read_message()
                if resp is None:
                    return None
                # Skip notifications and server-initiated messages
                if "id" in resp and resp["id"] == msg.get("id"):
                    return resp
                # Skip log/notification messages from server
        except (BrokenPipeError, OSError, json.JSONDecodeError) as e:
            print(f"MCP communication error: {e}")
            return None

    async def list_messages(self, chat_jid: str, limit: int = 20) -> list[dict]:
        """Get recent messages from a chat."""
        resp = await self._send("tools/call", {
            "name": "list_messages",
            "arguments": {"chat_jid": chat_jid, "limit": limit},
        })
        if not resp or resp.get("error"):
            return []
        try:
            content = resp.get("result", {}).get("content", [])
            if content and content[0].get("type") == "text":
                return json.loads(content[0]["text"])
        except (json.JSONDecodeError, IndexError, KeyError, TypeError):
            pass
        return []

    async def list_chats(self, query: str | None = None, limit: int = 20) -> list[dict]:
        """List chats, optionally filtered by query."""
        args = {"limit": limit}
        if query:
            args["query"] = query
        resp = await self._send("tools/call", {
            "name": "list_chats",
            "arguments": args,
        })
        if not resp or resp.get("error"):
            return []
        try:
            content = resp.get("result", {}).get("content", [])
            if content and content[0].get("type") == "text":
                return json.loads(content[0]["text"])
        except (json.JSONDecodeError, IndexError, KeyError, TypeError):
            pass
        return []

    async def send_message(self, recipient: str, message: str) -> bool:
        """Send a message to a JID."""
        resp = await self._send("tools/call", {
            "name": "send_message",
            "arguments": {"recipient": recipient, "message": message},
        })
        if not resp:
            return False
        result = resp.get("result", {})
        return not result.get("isError", False)


# ─── CC-powered responses ────────────────────────────────────────────────────


async def run_cc_quick(prompt: str, timeout: int = 60) -> str:
    """Run a short CC session. Returns response text."""
    try:
        proc = await asyncio.create_subprocess_exec(
            CLAUDE_CMD, "-p", prompt, "--dangerously-skip-permissions",
            "--no-session-persistence",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd="/tmp",
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        if proc.returncode == 0 and stdout:
            return stdout.decode().strip()[:4000]
    except (asyncio.TimeoutError, Exception):
        pass
    return ""


async def generate_response(
    message_text: str,
    sender: str,
    recent_context: list[dict],
) -> str:
    """Generate a response to a WhatsApp group message via CC."""
    soul = read_file(BASE_DIR / "SOUL.md")

    # Format recent messages as context
    context_lines = []
    for msg in recent_context[-15:]:
        sender_name = msg.get("sender_display", "?")
        content = msg.get("content", "")[:200]
        context_lines.append(f"{sender_name}: {content}")
    context_str = "\n".join(context_lines) if context_lines else "(no context)"

    prompt = (
        "You are Son of Max, responding in a WhatsApp group chat with Max's "
        "friends. You were mentioned or addressed. Respond naturally as part "
        "of the group conversation.\n\n"
        f"# Identity\n{soul[:2000]}\n\n"
        f"# Group Chat Context (recent messages)\n{context_str}\n\n"
        f"# Message that triggered you\n{sender}: {message_text}\n\n"
        "RULES:\n"
        "1. Respond conversationally, like a group chat member. Short and natural.\n"
        "2. No markdown, no bold, no bullet points.\n"
        "3. No em dashes. Keep it casual.\n"
        "4. You're talking to Max's friends, not Max directly. Be friendly "
        "but don't try too hard.\n"
        "5. If asked a question you don't know the answer to, say so.\n"
        "6. Match the language of the conversation (Swedish or English).\n"
        "7. One or two sentences max unless the topic warrants more."
    )

    return await run_cc_quick(prompt, timeout=45)


# ─── Queue integration ────────────────────────────────────────────────────────


def queue_task(text: str, source: str):
    """Write a task to INBOX.md for the daemon."""
    task_id = f"wa_{int(datetime.now().timestamp() * 1000)}"
    title = text[:80] + ("..." if len(text) > 80 else "")
    entry = (
        f"- [ ] `{task_id}` | P2 | **{title}** | "
        f"Source: WhatsApp ({source}) | {datetime.now().strftime('%Y-%m-%d %H:%M')}\n"
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


# ─── Main polling loop ────────────────────────────────────────────────────────


async def poll_group(mcp: MCPClient):
    """Check the group chat for new messages mentioning Son of Max."""
    global _last_seen_ts

    if not GROUP_JID:
        return

    messages = await mcp.list_messages(GROUP_JID, limit=20)
    if not messages:
        return

    # Process messages newest-first, but only ones we haven't seen
    new_messages = []
    for msg in messages:
        msg_id = msg.get("id", "")
        if msg_id in _seen_message_ids:
            continue
        ts_str = msg.get("timestamp", "")
        try:
            ts = datetime.fromisoformat(ts_str).timestamp()
        except (ValueError, TypeError):
            continue
        if ts <= _last_seen_ts:
            continue
        if msg.get("is_from_me"):
            continue
        new_messages.append((ts, msg))

    if not new_messages:
        return

    # Sort by timestamp, oldest first
    new_messages.sort(key=lambda x: x[0])

    for ts, msg in new_messages:
        msg_id = msg.get("id", "")
        _seen_message_ids.add(msg_id)
        # Cap the set
        if len(_seen_message_ids) > MAX_SEEN_IDS:
            _seen_message_ids.clear()

        content = msg.get("content", "")
        sender = msg.get("sender_display", "unknown")

        # Check for trigger
        if not TRIGGER_RE.search(content):
            continue

        print(f"Triggered by {sender}: {content[:100]}")

        # Generate and send response
        response = await generate_response(content, sender, messages)
        if response:
            sent = await mcp.send_message(GROUP_JID, response)
            if sent:
                print(f"Responded: {response[:100]}")
            else:
                print("Failed to send response.")

    # Update watermark
    if new_messages:
        _last_seen_ts = max(ts for ts, _ in new_messages)
        save_state()


async def main_loop():
    global GROUP_JID, CLAUDE_CMD

    config = load_config()
    wa_config = config.get("whatsapp", {})

    if not wa_config.get("enabled"):
        print("WhatsApp not enabled in config.yaml. Exiting.")
        sys.exit(0)

    GROUP_JID = wa_config.get("group_jid", "")
    if not GROUP_JID:
        print("No group_jid in config.yaml. Exiting.")
        sys.exit(1)

    CLAUDE_CMD = config.get("claude_command", "claude")

    # Custom trigger patterns from config
    extra_triggers = wa_config.get("triggers", [])
    if extra_triggers:
        global TRIGGER_RE
        patterns = ["son of max", "som"] + extra_triggers
        TRIGGER_RE = re.compile(
            r"\b(" + "|".join(re.escape(p) for p in patterns) + r")\b",
            re.IGNORECASE,
        )

    load_state()

    # If starting fresh (no state), set watermark to now so we don't
    # respond to old messages
    if _last_seen_ts == 0.0:
        global _last_seen_ts
        _last_seen_ts = datetime.now(timezone.utc).timestamp()
        save_state()

    mcp_dir = Path(wa_config.get("mcp_dir", str(WHATSAPP_DIR)))

    print(f"Starting WhatsApp bot. Group: {GROUP_JID}")
    print(f"MCP dir: {mcp_dir}")

    mcp = MCPClient(mcp_dir)

    # Graceful shutdown
    loop = asyncio.get_event_loop()

    def shutdown(signum, _):
        print(f"Signal {signum}. Shutting down.")
        loop.create_task(mcp.stop())
        sys.exit(0)

    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)

    # Start MCP server (connects to WhatsApp)
    print("Starting WhatsApp MCP server...")
    if not await mcp.start():
        print("Failed to start MCP server. Exiting.")
        sys.exit(1)

    # Wait for WhatsApp to sync messages
    print("Waiting for WhatsApp message sync...")
    await asyncio.sleep(10)

    # If no group JID configured, try to find it
    if GROUP_JID == "auto":
        chats = await mcp.list_chats(limit=50)
        for chat in chats:
            name = (chat.get("name") or "").lower()
            if "cyklar" in name or "filosofi" in name:
                GROUP_JID = chat.get("jid", "")
                print(f"Auto-detected group: {chat.get('name')} ({GROUP_JID})")
                break
        if not GROUP_JID or GROUP_JID == "auto":
            print("Could not auto-detect group. Listing available groups:")
            for chat in chats:
                if chat.get("is_group"):
                    print(f"  {chat.get('jid')} — {chat.get('name')}")
            sys.exit(1)

    print(f"Polling {GROUP_JID} every {POLL_INTERVAL}s...")

    # Check for restart signal
    restart_file = QUEUE_DIR / ".restart-whatsapp"

    while True:
        if restart_file.exists():
            try:
                restart_file.unlink()
            except OSError:
                pass
            print("Restart signal. Exiting.")
            await mcp.stop()
            break

        if not mcp.is_alive():
            print("MCP server died. Restarting...")
            await mcp.stop()
            await asyncio.sleep(5)
            if not await mcp.start():
                print("Restart failed. Waiting 60s...")
                await asyncio.sleep(60)
                continue
            await asyncio.sleep(10)

        try:
            await poll_group(mcp)
        except Exception as e:
            print(f"Poll error: {e}")

        await asyncio.sleep(POLL_INTERVAL)

    await mcp.stop()


if __name__ == "__main__":
    asyncio.run(main_loop())
