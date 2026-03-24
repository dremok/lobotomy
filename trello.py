"""Trello API helper for LOBOTOMY morning brief.

Fetches cards from Max's "Dagens TODO" board.
Requires TRELLO_KEY and TRELLO_TOKEN in config.yaml under trello: section.
"""

import json
import urllib.request
import urllib.error
from pathlib import Path

import yaml

BASE_URL = "https://api.trello.com/1"


def load_trello_config() -> dict | None:
    """Load Trello credentials from config.yaml."""
    cfg = Path(__file__).parent / "config.yaml"
    if not cfg.exists():
        return None
    with open(cfg) as f:
        config = yaml.safe_load(f) or {}
    trello = config.get("trello", {})
    if not trello.get("key") or not trello.get("token"):
        return None
    return trello


def _get(endpoint: str, key: str, token: str, params: dict | None = None) -> dict | list:
    """Make an authenticated GET request to Trello API."""
    url = f"{BASE_URL}{endpoint}?key={key}&token={token}"
    if params:
        for k, v in params.items():
            url += f"&{k}={v}"
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read())


def find_board(key: str, token: str, board_name: str = "Dagens TODO") -> str | None:
    """Find a board by name. Returns board ID or None."""
    boards = _get("/members/me/boards", key, token, {"fields": "name"})
    for b in boards:
        if b["name"].lower() == board_name.lower():
            return b["id"]
    return None


def get_board_cards(key: str, token: str, board_id: str) -> list[dict]:
    """Get all cards on a board, grouped by list."""
    lists = _get(f"/boards/{board_id}/lists", key, token, {"fields": "name"})
    result = []
    for lst in lists:
        cards = _get(f"/lists/{lst['id']}/cards", key, token,
                     {"fields": "name,due,labels"})
        if cards:
            result.append({
                "list": lst["name"],
                "cards": [{"name": c["name"], "due": c.get("due")} for c in cards],
            })
    return result


def format_board_summary(board_data: list[dict]) -> str:
    """Format board cards as readable text for the morning brief."""
    if not board_data:
        return "(no cards)"
    lines = []
    for lst in board_data:
        lines.append(f"**{lst['list']}**")
        for card in lst["cards"]:
            due = f" (due: {card['due'][:10]})" if card.get("due") else ""
            lines.append(f"  - {card['name']}{due}")
    return "\n".join(lines)


def get_dagens_todo() -> str | None:
    """Fetch and format the Dagens TODO board. Returns formatted text or None."""
    config = load_trello_config()
    if not config:
        return None
    try:
        board_id = config.get("board_id")
        if not board_id:
            board_id = find_board(config["key"], config["token"])
            if not board_id:
                return "(Dagens TODO board not found)"
        cards = get_board_cards(config["key"], config["token"], board_id)
        return format_board_summary(cards)
    except (urllib.error.URLError, json.JSONDecodeError, KeyError) as e:
        return f"(Trello error: {e})"


if __name__ == "__main__":
    result = get_dagens_todo()
    if result:
        print(result)
    else:
        print("No Trello config found. Add trello.key and trello.token to config.yaml")
