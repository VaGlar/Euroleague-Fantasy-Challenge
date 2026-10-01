"""Check what the pipeline just wrote to data/public, before it is committed and deployed.

The unit tests run the code on fake API answers; this runs on the real data of the day, so it
catches what they can't: an API that changed shape (prices or positions gone), a half-written or
NaN file, an empty report. Problems that make the data unusable stop the update (exit 1): nothing
is committed or deployed, the sites keep the last good data and the owner is told on Telegram.
Smaller oddities only go to the run's health list (the owner's usual alert).

python -m elf.validate
"""
from __future__ import annotations

import json
import math
import os
import sys
from datetime import datetime, timedelta, timezone
from html import escape

from .config import PUBLIC

POSITIONS = {"Guard", "Forward", "Center", "Head Coach"}
FRESH = timedelta(hours=3)         # the pipeline writes predictions.json on every run


def _load(name: str, problems: list[str]):
    try:
        return json.loads((PUBLIC / name).read_text(),
                          parse_constant=lambda c: (_ for _ in ()).throw(ValueError(f"{c} στο αρχείο")))
    except FileNotFoundError:
        problems.append(f"{name}: λείπει")
    except ValueError as e:
        problems.append(f"{name}: δεν είναι έγκυρο JSON ({str(e)[:80]})")
    return None


def _num(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def _age(ts) -> timedelta | None:
    try:
        t = datetime.fromisoformat(str(ts))
    except ValueError:
        return None
    if t.tzinfo is None:
        return None
    return datetime.now(timezone.utc) - t


def check() -> tuple[list[str], list[str]]:
    """(problems that stop the update, warnings for health)."""
    problems: list[str] = []
    warnings: list[str] = []
    pred = _load("predictions.json", problems)
    rep = _load("report.json", problems)
    for name in ("news.json", "players.json", "clubs.json"):
        _load(name, problems)
    if pred is None or rep is None:
        return problems, warnings

    # a run with no game ahead (off-season) writes an empty report and keeps the old predictions
    off_season = not rep.get("messages") and (_age(rep.get("generated")) or FRESH) < FRESH
    age = _age(pred.get("generated"))
    if not off_season and (age is None or age > FRESH):
        problems.append(f"predictions.json: δεν γράφτηκε σε αυτό το run (generated {pred.get('generated')})")

    players = pred.get("players")
    if not isinstance(players, list):
        problems.append("predictions.json: λείπει η λίστα παικτών")
        players = []
    elif len(players) < 200:
        problems.append(f"predictions.json: μόνο {len(players)} παίκτες (περίμενα 300+)")

    if players:
        pos = [p.get("position") for p in players]
        odd = sorted({str(x) for x in pos if x not in POSITIONS})
        if odd:
            problems.append(f"θέσεις που δεν ξέρω: {', '.join(odd[:5])} — άλλαξαν τα δεδομένα του παιχνιδιού;")
        for want, least in (("Guard", 40), ("Forward", 40), ("Center", 20), ("Head Coach", 15)):
            n = pos.count(want)
            if n < least:
                problems.append(f"μόνο {n} παίκτες στη θέση {want} (περίμενα {least}+)")
        teams = {p.get("team") for p in players if p.get("team")}
        if not 16 <= len(teams) <= 22:
            problems.append(f"{len(teams)} ομάδες στους παίκτες (περίμενα 18-20)")
        bad_x = [p for p in players if p.get("x_now") is not None and not _num(p.get("x_now"))]
        if bad_x:
            problems.append(f"{len(bad_x)} παίκτες με xFPT που δεν είναι αριθμός")
        no_x = sum(p.get("x_now") is None for p in players)
        if no_x > 0.1 * len(players):
            problems.append(f"{no_x}/{len(players)} παίκτες χωρίς xFPT")
        if pred.get("fantasy_ok"):
            priced = [p.get("price") for p in players if _num(p.get("price"))]
            if len(priced) < 0.9 * len(players):
                problems.append(f"μόνο {len(priced)}/{len(players)} παίκτες με τιμή, ενώ το παιχνίδι απάντησε — "
                                "άλλαξε η μορφή του API;")
            elif priced and sum(not 1 <= x <= 40 for x in priced) > 0.05 * len(priced):
                problems.append("τιμές εκτός 1-40 credits — άλλαξε η μορφή του API;")

    rnd = pred.get("round")
    if not (isinstance(rnd, int) and 1 <= rnd <= 40):
        problems.append(f"predictions.json: αγωνιστική {rnd!r}")
    if not isinstance(pred.get("turns"), list):
        problems.append("predictions.json: λείπουν τα turns")

    msgs = rep.get("messages")
    if not isinstance(msgs, list):
        problems.append("report.json: λείπουν τα μηνύματα")
    else:
        for m in msgs:
            if not (isinstance(m, dict) and m.get("date") and str(m.get("text") or "").strip()):
                problems.append("report.json: μήνυμα χωρίς ημερομηνία ή κείμενο")
                break
        if not msgs and not off_season:
            warnings.append("έλεγχος δεδομένων: το report δεν έχει μηνύματα")
    return problems, warnings


def _add_health(warnings: list[str]) -> None:
    path = PUBLIC / "predictions.json"
    pred = json.loads(path.read_text())
    health = pred.get("health") or []
    pred["health"] = health + [w for w in warnings if w not in health]
    path.write_text(json.dumps(pred, ensure_ascii=False))


def main() -> int:
    problems, warnings = check()
    if warnings and not problems:
        _add_health(warnings)
    for w in warnings:
        print(f"warning: {w}")
    if not problems:
        print("data check: OK")
        return 0
    print("data check FAILED:\n" + "\n".join(f"- {p}" for p in problems), file=sys.stderr)
    if os.environ.get("TELEGRAM_BOT_TOKEN"):
        from .notify import send
        url = os.environ.get("RUN_URL")
        send("⛔ <b>Το update σταμάτησε στον έλεγχο δεδομένων</b> — δεν έγινε commit ούτε deploy, "
             "οι σελίδες κρατούν τα τελευταία καλά δεδομένα:\n"
             + "\n".join(f"• {escape(p, quote=False)}" for p in problems) + (f"\n{url}" if url else ""))
    return 1


if __name__ == "__main__":
    sys.exit(main())
