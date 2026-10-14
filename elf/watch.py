"""The owner's watchlist (personal edition) and its Telegram alerts.

The ⭐ list lives in the owner's browser; the personal site sends it (functions/api/watch.js) to the
watch workflow, which saves it in the private data repo as data/public/watch.json. Each update then
tells the owner on Telegram when something happens to a watched player: a price rise is expected,
he is out or doubtful, available again, or his xFPT3 went up a lot since he was added.
Only changes are sent (the last state is in watch_state.json), never the same news twice.

python -m elf.watch save <path>   -> the list from the WATCH variable (JSON), checked, into <path>
python -m elf.watch notify        -> the alerts of this update, to Telegram

Both files are private (elf/publish.py PRIVATE_ONLY). Standard library only for `save`: the
workflow runs it without installing anything.
"""
from __future__ import annotations

import json
import math
import os
import re
import sys
from datetime import datetime, timezone
from html import escape
from pathlib import Path

MAX_PLAYERS = 60
PID_RE = re.compile(r"^\d{1,10}$")          # EuroLeague person ids are digits ("003469")
X3_JUMP = 3.0                                 # «xFPT3 +3 since added» is news; less is noise


def _num(v):
    try:
        v = float(v)
    except (TypeError, ValueError):
        return None
    return round(v, 2) if math.isfinite(v) else None


def _iso(v):
    try:
        return datetime.fromisoformat(str(v).replace("Z", "+00:00")).isoformat()
    except ValueError:
        return None


def clean(raw) -> dict:
    """The list as sent by the browser, rebuilt from the fields we know: anything else is dropped,
    so nothing but player ids, dates and numbers reaches the private repo."""
    if not isinstance(raw, dict):
        raise ValueError("η watchlist πρέπει να είναι αντικείμενο")
    out = {}
    for pid, e in raw.items():
        if not PID_RE.match(str(pid)) or not isinstance(e, dict):
            continue
        out[str(pid)] = {"at": _iso(e.get("at")), "price": _num(e.get("price")),
                         "x3": _num(e.get("x3")), "inj": bool(e.get("inj"))}
        if len(out) >= MAX_PLAYERS:
            break
    return out


def save(path: Path, text: str) -> dict:
    players = clean(json.loads(text or "{}"))
    data = {"updated": datetime.now(timezone.utc).isoformat(), "players": players}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=1))
    return data


def _out(p: dict) -> bool:
    """Out or doubtful for his next game (as the dashboard's 🚑 / 📋)."""
    a = p.get("avail_game")
    return bool(p.get("injured") or p.get("unregistered") or (a is not None and a < 1))


def _name(p: dict) -> str:
    n = str(p.get("name") or "")
    last, _, first = n.partition(",")
    return f"{first.strip()[:1]}. {last.strip().title()}" if first.strip() else n.title()


def alerts(players: list[dict], watch: dict, state: dict) -> tuple[list[str], dict]:
    """The news since the last update for each watched player, and the new state.
    state: {pid: {"up": price rise expected, "out": out/doubtful, "hot": xFPT3 jump told}}"""
    by = {str(p.get("person_id")): p for p in players if p.get("person_id")}
    lines, new = [], {}
    for pid, w in watch.items():
        p = by.get(pid)
        if p is None:                       # left the game's list: nothing to say
            continue
        x3 = p.get("x3", p.get("x_h"))
        now = {"up": p.get("price_trend") == "up", "out": _out(p),
               "hot": x3 is not None and w.get("x3") is not None and x3 - w["x3"] >= X3_JUMP}
        before = state.get(pid) or {"up": False, "out": bool(w.get("inj")), "hot": False}
        who = escape(_name(p), quote=False)
        price = p.get("price")
        if now["up"] and not before.get("up"):
            lines.append(f"💰 <b>{who}</b>: αναμένεται άνοδος price" + (f" (τώρα {price:.1f} cr)" if price else ""))
        if now["out"] and not before.get("out"):
            lines.append(f"🚑 <b>{who}</b>: εκτός ή αμφίβολος για τον επόμενο αγώνα")
        if before.get("out") and not now["out"]:
            lines.append(f"✅ <b>{who}</b>: διαθέσιμος ξανά")
        if now["hot"] and not before.get("hot"):
            lines.append(f"📈 <b>{who}</b>: xFPT3 {x3:.1f} (+{x3 - w['x3']:.1f} από τότε που τον πρόσθεσες)")
        new[pid] = now
    return lines, new


def notify(public: Path | None = None) -> str | None:
    """Send this update's watchlist news. The state is written only once delivered."""
    from .config import PUBLIC
    from .notify import send

    public = public or PUBLIC
    wf, sf = public / "watch.json", public / "watch_state.json"
    if not wf.exists():
        return None
    watch = clean(json.loads(wf.read_text()).get("players") or {})
    state = json.loads(sf.read_text()) if sf.exists() else {}
    pred = json.loads((public / "predictions.json").read_text())
    lines, new = alerts(pred.get("players") or [], watch, state)
    text = None
    if lines:
        text = "⭐ <b>Watchlist</b>\n" + "\n".join(lines)
        send(text)
    sf.write_text(json.dumps(new, ensure_ascii=False))
    print(f"watchlist: {len(watch)} players, {len(lines)} alert(s)")   # counts only: the log is public
    return text


if __name__ == "__main__":
    cmd = (sys.argv[1:] or ["notify"])[0]
    if cmd == "save":
        d = save(Path(sys.argv[2]), os.environ.get("WATCH", "{}"))
        print(f"watchlist: {len(d['players'])} players saved")
    elif cmd == "notify":
        notify()
