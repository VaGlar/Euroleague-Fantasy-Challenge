"""Telegram delivery from GitHub Actions.

python -m elf.notify report   -> today's game-day report (right after a fresh update),
                                 with a /lineup button; marks it sent in sent.json so the
                                 bot's 11:00 fallback does not send it twice
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import requests

from .config import PUBLIC, TIMEZONE

LINEUP_BUTTON = {"text": "👥 Πρόταση πεντάδας (/lineup)", "callback_data": "lu:preview"}


def today() -> str:
    return datetime.now(ZoneInfo(TIMEZONE)).date().isoformat()


def chunks(text: str, limit: int = 3800) -> list[str]:
    """Telegram allows 4096 chars per message: split on line boundaries."""
    out, cur = [], ""
    for line in text.split("\n"):
        if cur and len(cur) + len(line) + 1 > limit:
            out.append(cur)
            cur = ""
        cur += line + "\n"
    if cur.strip():
        out.append(cur)
    return out


def send(text: str, buttons: list | None = None) -> bool:
    """Send (buttons on the last chunk). Without Telegram secrets, print instead."""
    tok, chat = os.environ.get("TELEGRAM_BOT_TOKEN"), os.environ.get("TELEGRAM_CHAT_ID")
    parts = chunks(text)
    for i, part in enumerate(parts):
        body = {"chat_id": chat, "text": part, "parse_mode": "HTML",
                "disable_web_page_preview": True}
        if buttons and i == len(parts) - 1:
            body["reply_markup"] = {"inline_keyboard": [buttons]}
        if not tok or not chat:
            print(part, body.get("reply_markup", ""))
            continue
        r = requests.post(f"https://api.telegram.org/bot{tok}/sendMessage", json=body, timeout=30)
        if r.status_code != 200:
            raise RuntimeError(f"Telegram {r.status_code}: {r.text[:200]}")
    return bool(parts)


def report() -> bool:
    """Send today's report if today is a game day. Returns True if something was sent."""
    rep = json.loads((PUBLIC / "report.json").read_text())
    d = today()
    msg = next((m for m in rep.get("messages", []) if m.get("date") == d), None)
    if not msg:
        print(f"{d}: δεν υπάρχουν αγώνες σήμερα — τίποτα να σταλεί")
        return False
    send(msg["text"], [LINEUP_BUTTON])
    (PUBLIC / "sent.json").write_text(json.dumps(
        {"date": d, "at": datetime.now(timezone.utc).isoformat()}))
    return True


if __name__ == "__main__":
    if (sys.argv[1:] or ["report"])[0] == "report":
        report()
