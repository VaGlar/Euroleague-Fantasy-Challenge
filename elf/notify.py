"""Telegram delivery from GitHub Actions.

python -m elf.notify report   -> today's game-day report, with a /lineup button
python -m elf.notify health   -> the run's problems (Gemini down, a source failing, token...)
                                 to the owner on Telegram, only when they change; the public
                                 edition never shows them
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from html import escape
from zoneinfo import ZoneInfo

import requests

from .config import PUBLIC, TIMEZONE

LINEUP_BUTTON = {"text": "👥 Πρόταση πεντάδας (/lineup)", "callback_data": "lu:preview"}


def today() -> str:
    return datetime.now(ZoneInfo(TIMEZONE)).date().isoformat()


def _pieces(line: str, limit: int):
    """A line longer than the limit, cut at spaces where possible."""
    while len(line) > limit:
        cut = line.rfind(" ", 0, limit)
        cut = cut if cut > 0 else limit
        yield line[:cut]
        line = line[cut:].lstrip(" ")
    yield line


def chunks(text: str, limit: int = 3800) -> list[str]:
    """Telegram allows 4096 chars per message: split on line boundaries (and inside a
    line only when that line alone is too long)."""
    out, cur = [], ""
    for raw in text.split("\n"):
        for line in _pieces(raw, limit - 1):
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


def health() -> str | None:
    """Tell the owner about new problems (and when they clear). Returns what was sent."""
    pred = json.loads((PUBLIC / "predictions.json").read_text())
    now = sorted(set(pred.get("health") or []))
    path = PUBLIC / "health_last.json"
    before = sorted(set(json.loads(path.read_text()))) if path.exists() else []
    if now == before:
        return None
    new = [h for h in now if h not in before]
    if now:
        text = "⚠️ <b>Προβλήματα στο update</b> (δεν φαίνονται στη δημόσια έκδοση):\n" + \
            "\n".join(f"• {escape(h, quote=False)}" for h in now)
        if not new:
            text = "✅ Λύθηκαν κάποια προβλήματα. Απομένουν:\n" + \
                "\n".join(f"• {escape(h, quote=False)}" for h in now)
    else:
        text = "✅ Όλα λειτουργούν ξανά κανονικά."
    send(text)
    # only once it was delivered: if Telegram failed, the next run tries again
    path.write_text(json.dumps(now, ensure_ascii=False))
    return text


if __name__ == "__main__":
    cmd = (sys.argv[1:] or ["report"])[0]
    if cmd == "report":
        report()
    elif cmd == "health":
        health()
