#!/usr/bin/env python3
"""LOBOTOMY unified bot — Telegram + WhatsApp in one process."""

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
HISTORY_FILE = BASE_DIR / "logs" / "message_history.json"
MAX_HISTORY = 20  # per channel
CLAUDE_CMD = "claude"

# ─── Config ──────────────────────────────────────────────────────────────────


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


# ─── Message history ─────────────────────────────────────────────────────────


class MessageHistory:
    """Unified message buffer across channels, persisted to disk."""

    def __init__(self, path: Path, max_per_channel: int = MAX_HISTORY):
        self.path = path
        self.max = max_per_channel
        self.messages: list[dict] = []
        self._load()

    def _load(self):
        if self.path.exists():
            try:
                self.messages = json.loads(self.path.read_text())
            except (json.JSONDecodeError, OSError):
                self.messages = []

    def _save(self):
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps(self.messages, indent=2))
        except OSError:
            pass

    def add(self, channel: str, sender: str, text: str, is_bot: bool = False):
        self.messages.append({
            "channel": channel,
            "sender": sender,
            "text": text[:500],
            "is_bot": is_bot,
            "ts": datetime.now().isoformat(),
        })
        # Trim per channel
        for ch in ("telegram", "whatsapp"):
            ch_msgs = [m for m in self.messages if m["channel"] == ch]
            if len(ch_msgs) > self.max:
                # Remove oldest messages of this channel
                excess = len(ch_msgs) - self.max
                removed = 0
                self.messages = [
                    m for m in self.messages
                    if m["channel"] != ch or (removed := removed + 1) > excess
                ]
        self._save()

    def format_context(self) -> str:
        if not self.messages:
            return "(no recent messages)"
        lines = []
        for m in self.messages[-(self.max * 2):]:
            ch = "TG" if m["channel"] == "telegram" else "WA"
            sender = "Son of Max" if m["is_bot"] else m["sender"]
            lines.append(f"[{ch}] {sender}: {m['text'][:200]}")
        return "\n".join(lines)


# ─── CC response ─────────────────────────────────────────────────────────────


async def run_cc(prompt: str, timeout: int = 45, tools: str | None = None) -> str:
    """Run claude -p and return response text."""
    try:
        args = [CLAUDE_CMD, "-p", prompt, "--dangerously-skip-permissions",
                "--no-session-persistence", "--effort", "low"]
        if tools is not None:
            args.extend(["--tools", tools])
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


async def generate_response(
    channel: str,
    sender: str,
    text: str,
    history: MessageHistory,
    soul: str,
) -> str:
    """Generate a response using CC with full multi-channel context."""
    channel_label = "Telegram (private chat with Max)" if channel == "telegram" else "WhatsApp (group chat with Max's friends)"

    prompt = (
        f"You are Son of Max, responding on {channel_label}.\n\n"
        f"# Identity\n{soul[:2000]}\n\n"
        f"# Recent conversation (TG = Telegram, WA = WhatsApp group)\n"
        f"{history.format_context()}\n\n"
        f"# Current message ({channel_label})\n{sender}: {text}\n\n"
        "RULES:\n"
        "- You are ONE entity across both channels. You know what's happening on both.\n"
        "- Respond naturally, like texting. Short and conversational.\n"
        "- No markdown, no bold, no bullet points, no lists.\n"
        "- No em dashes. No file paths.\n"
        "- On Telegram (private with Max): be direct, helpful, own your work.\n"
        "- On WhatsApp (group with friends): be casual, match the group's language (Swedish or English), don't try too hard.\n"
        "- Keep responses concise. 1-3 sentences unless the topic warrants more.\n"
        "- Never start with 'I' if you can avoid it.\n"
        "- If you don't know something, say so."
    )

    response = await run_cc(prompt, timeout=30, tools="")
    if not response:
        # Fallback
        response = await run_cc(
            f"You are Son of Max. Respond briefly to: {text}",
            timeout=10, tools=""
        )
    return response


# ─── WhatsApp MCP client ─────────────────────────────────────────────────────


class WhatsAppBridge:
    """Manages the WhatsApp MCP subprocess and communicates via JSON-RPC."""

    def __init__(self, mcp_dir: Path, group_jid: str, triggers: list[str]):
        self.mcp_dir = mcp_dir
        self.group_jid = group_jid
        self.triggers = triggers
        self.trigger_re = re.compile(
            r"\b(" + "|".join(re.escape(t) for t in triggers) + r")\b",
            re.IGNORECASE,
        )
        self.proc: subprocess.Popen | None = None
        self.request_id = 0
        self._lock = asyncio.Lock()
        self._last_seen_ts: float = 0.0
        self._seen_ids: set[str] = set()

    async def start(self) -> bool:
        """Start the MCP server subprocess."""
        if not self.mcp_dir.exists():
            print(f"WhatsApp MCP dir not found: {self.mcp_dir}")
            return False
        self.proc = subprocess.Popen(
            ["node", "src/main.ts"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=str(self.mcp_dir),
        )
        await asyncio.sleep(5)
        resp = await self._send("initialize", {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "lobotomy-unified", "version": "2.0.0"},
        })
        if resp and not resp.get("error"):
            await self._notify("notifications/initialized")
            print("WhatsApp MCP connected.")
            await asyncio.sleep(10)  # Wait for message sync
            # Set watermark to now so we don't reply to old messages
            self._last_seen_ts = datetime.now(timezone.utc).timestamp()
            return True
        print(f"WhatsApp MCP init failed: {resp}")
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
        async with self._lock:
            if not self.is_alive():
                return
            msg = {"jsonrpc": "2.0", "method": method}
            if params is not None:
                msg["params"] = params
            await asyncio.get_event_loop().run_in_executor(
                None, self._write_message, msg
            )
            await asyncio.sleep(0.5)

    def _write_message(self, msg: dict):
        body = json.dumps(msg)
        header = f"Content-Length: {len(body)}\r\n\r\n"
        self.proc.stdin.write(header.encode() + body.encode())
        self.proc.stdin.flush()

    def _read_message(self) -> dict | None:
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
        try:
            self._write_message(msg)
            deadline = time.time() + 30
            while time.time() < deadline:
                resp = self._read_message()
                if resp is None:
                    return None
                if "id" in resp and resp["id"] == msg.get("id"):
                    return resp
        except (BrokenPipeError, OSError, json.JSONDecodeError) as e:
            print(f"MCP error: {e}")
            return None

    async def call_tool(self, name: str, args: dict) -> dict | None:
        resp = await self._send("tools/call", {"name": name, "arguments": args})
        if not resp or resp.get("error"):
            return None
        try:
            content = resp.get("result", {}).get("content", [])
            if content and content[0].get("type") == "text":
                return json.loads(content[0]["text"])
        except (json.JSONDecodeError, IndexError, KeyError, TypeError):
            pass
        return None

    async def get_new_messages(self) -> list[dict]:
        """Poll for new messages in the group that we haven't seen."""
        data = await self.call_tool("list_messages", {
            "chat_jid": self.group_jid, "limit": 20
        })
        if not data or not isinstance(data, list):
            return []

        new = []
        for msg in data:
            msg_id = msg.get("id", "")
            if msg_id in self._seen_ids:
                continue
            ts_str = msg.get("timestamp", "")
            try:
                ts = datetime.fromisoformat(ts_str).timestamp()
            except (ValueError, TypeError):
                continue
            if ts <= self._last_seen_ts:
                continue
            if msg.get("is_from_me"):
                self._seen_ids.add(msg_id)
                continue
            new.append((ts, msg))
            self._seen_ids.add(msg_id)

        # Cap seen IDs
        if len(self._seen_ids) > 500:
            self._seen_ids = set(list(self._seen_ids)[-200:])

        if new:
            self._last_seen_ts = max(ts for ts, _ in new)

        new.sort(key=lambda x: x[0])
        return [msg for _, msg in new]

    def is_triggered(self, text: str) -> bool:
        return bool(self.trigger_re.search(text))

    async def send_message(self, text: str) -> bool:
        resp = await self._send("tools/call", {
            "name": "send_message",
            "arguments": {"recipient": self.group_jid, "message": text},
        })
        if not resp:
            return False
        return not resp.get("result", {}).get("isError", False)


# ─── Telegram handlers ───────────────────────────────────────────────────────


def build_telegram_app(config: dict, history: MessageHistory, soul: str):
    """Build the Telegram bot application."""
    token = config.get("telegram", {}).get("token", "")
    chat_id = config.get("telegram", {}).get("chat_id", "")

    app = Application.builder().token(token).build()

    authorized_id = int(chat_id) if chat_id else None

    async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
        nonlocal authorized_id
        if authorized_id and update.effective_chat.id != authorized_id:
            return

        # Auto-save chat_id
        if not authorized_id:
            authorized_id = update.effective_chat.id
            print(f"Telegram chat_id: {authorized_id}")

        text = update.message.text
        sender = "Max"
        print(f"[TG] {sender}: {text[:80]}")

        # Add to history
        history.add("telegram", sender, text)

        # Typing indicator
        await update.message.chat.send_action(ChatAction.TYPING)

        # Generate response
        response = await generate_response("telegram", sender, text, history, soul)
        if not response:
            response = "Got your message, thinking about it."

        print(f"[TG] Son of Max: {response[:80]}")
        history.add("telegram", "Son of Max", response, is_bot=True)
        await update.message.reply_text(response)

    async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if authorized_id and update.effective_chat.id != authorized_id:
            return
        await update.message.reply_text(
            "Just text me anything. I monitor both this chat and WhatsApp."
        )

    async def error_handler(update, context):
        if "NetworkError" in str(type(context.error).__name__):
            return
        print(f"Telegram error: {context.error}")

    app.add_error_handler(error_handler)
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    return app


# ─── WhatsApp polling loop ───────────────────────────────────────────────────


async def whatsapp_loop(bridge: WhatsAppBridge, history: MessageHistory, soul: str):
    """Poll WhatsApp for new messages and respond to triggers."""
    print(f"WhatsApp polling started (group: {bridge.group_jid})")
    while True:
        try:
            if not bridge.is_alive():
                print("WhatsApp MCP died. Restarting...")
                await bridge.stop()
                await asyncio.sleep(5)
                if not await bridge.start():
                    await asyncio.sleep(60)
                    continue

            new_messages = await bridge.get_new_messages()
            for msg in new_messages:
                sender = msg.get("sender_display", "unknown")
                content = msg.get("content", "")
                if not content:
                    continue

                # Add all messages to history for context
                history.add("whatsapp", sender, content)
                print(f"[WA] {sender}: {content[:80]}")

                # Only respond if triggered
                if bridge.is_triggered(content):
                    print(f"[WA] Triggered by {sender}")
                    response = await generate_response(
                        "whatsapp", sender, content, history, soul
                    )
                    if response:
                        sent = await bridge.send_message(response)
                        if sent:
                            history.add("whatsapp", "Son of Max", response, is_bot=True)
                            print(f"[WA] Son of Max: {response[:80]}")
                        else:
                            print("[WA] Failed to send response")

        except Exception as e:
            print(f"WhatsApp poll error: {e}")

        await asyncio.sleep(60)


# ─── Main ─────────────────────────────────────────────────────────────────────


def main():
    global CLAUDE_CMD

    config = load_config()
    CLAUDE_CMD = config.get("claude_command", "claude")

    # Load identity
    soul = read_file(BASE_DIR / "SOUL.md")
    if not soul:
        # Try VPS path
        soul = "You are Son of Max, an autonomous AI agent."

    # Message history (persisted)
    history = MessageHistory(HISTORY_FILE)

    # Telegram
    tg_config = config.get("telegram", {})
    if not tg_config.get("token"):
        print("No Telegram token in config.yaml")
        sys.exit(1)

    tg_app = build_telegram_app(config, history, soul)

    # WhatsApp (optional)
    wa_config = config.get("whatsapp", {})
    wa_bridge = None
    if wa_config.get("enabled") and wa_config.get("group_jid"):
        triggers = ["son of max", "som"] + wa_config.get("triggers", [])
        wa_bridge = WhatsAppBridge(
            mcp_dir=BASE_DIR / wa_config.get("mcp_dir", "whatsapp-mcp"),
            group_jid=wa_config["group_jid"],
            triggers=triggers,
        )

    # Graceful shutdown
    def shutdown(signum, _):
        print(f"Signal {signum}. Shutting down.")
        if wa_bridge:
            asyncio.get_event_loop().create_task(wa_bridge.stop())
        os.kill(os.getpid(), signal.SIGINT)

    signal.signal(signal.SIGTERM, shutdown)

    # Start everything
    async def post_init(application):
        # Start WhatsApp after Telegram event loop is running
        if wa_bridge:
            connected = await wa_bridge.start()
            if connected:
                asyncio.create_task(whatsapp_loop(wa_bridge, history, soul))
            else:
                print("WhatsApp not connected. Telegram-only mode.")

    tg_app.post_init = post_init

    print("LOBOTOMY unified bot starting...")
    print(f"  Telegram: enabled")
    print(f"  WhatsApp: {'enabled' if wa_bridge else 'disabled'}")
    tg_app.run_polling()


if __name__ == "__main__":
    main()
