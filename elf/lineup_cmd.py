"""Telegram /lineup: propose the best five / sixth man / captain, apply on confirmation.

python -m elf.lineup_cmd preview          -> sends the proposal with ✅/❌ buttons
python -m elf.lineup_cmd apply <nonce>    -> re-computes, checks it is the same proposal,
                                             writes it, reads the roster back to verify

Safety rails (any failure = nothing is written, you get a message saying why):
  * only lineup/captain are written, never trades
  * the proposal is recomputed at apply time and must match the confirmed one (nonce)
  * current roster must decode consistently: its five matches its formation_id and its
    court slots are ordered Guard -> Forward -> Center (our assumption about the layout)
  * players who already played are only moved in ways the game allows
  * after writing, the roster is read back and compared field by field
"""
from __future__ import annotations

import hashlib
import json
import os
import sys

import requests

from . import fantasy, optimize
from .config import PUBLIC

POS = {"Guard": 0, "Forward": 1, "Center": 2}
LETTER = {"Guard": "G", "Forward": "F", "Center": "C"}


# ------------------------------------------------------------------ telegram

def tg(method: str, **body):
    tok, chat = os.environ.get("TELEGRAM_BOT_TOKEN"), os.environ.get("TELEGRAM_CHAT_ID")
    if not tok or not chat:
        print(body.get("text", ""))
        return None
    body.setdefault("chat_id", chat)
    return requests.post(f"https://api.telegram.org/bot{tok}/{method}", json=body, timeout=30)


def say(text: str, buttons: list | None = None):
    body = {"text": text, "parse_mode": "HTML", "disable_web_page_preview": True}
    if buttons:
        body["reply_markup"] = {"inline_keyboard": [buttons]}
    tg("sendMessage", **body)


class Abort(RuntimeError):
    pass


# --------------------------------------------------------------------- state

def load_state():
    cfg = fantasy.config()
    md = cfg["current_matchday"]
    teams = fantasy.my_teams()
    if not teams:
        raise Abort("δεν βρέθηκε ομάδα Classic")
    team = teams[0]
    raw = fantasy.roster(team["id"], md["id"])
    players = raw.get("players") or []
    if len(players) != 11:
        raise Abort(f"το ρόστερ έχει {len(players)} παίκτες αντί για 11")

    pred = json.loads((PUBLIC / "predictions.json").read_text())
    xnow = {p.get("fantasy_id"): p.get("x_now") for p in pred.get("players", [])
            if p.get("fantasy_id") is not None}

    court = sorted([p for p in players if p["position"]["name"] in POS],
                   key=lambda p: p["court_position"])
    coach = [p for p in players if p["position"]["name"] not in POS]
    if len(court) != 10 or len(coach) != 1:
        raise Abort("μη αναμενόμενη σύνθεση ρόστερ (10 παίκτες + coach)")
    roles = {p["id"]: ("5άδα" if i < 5 else "6ος" if i == 5 else "πάγκος")
             for i, p in enumerate(court)}

    # --- sanity: our reading of court_position must agree with the game's formation
    forms = fantasy.formations(raw.get("formation_id"))
    five = court[:5]
    name = "-".join(str(sum(p["position"]["name"] == pos for p in five)) for pos in POS)
    if forms.get(name) != raw.get("formation_id"):
        raise Abort(f"η πεντάδα που διαβάζω ({name}) δεν ταιριάζει με το formation της ομάδας "
                    f"(id {raw.get('formation_id')}) — δεν αλλάζω τίποτα")
    # slot order inside the five: learn it from the current roster (the game uses C->F->G)
    seq = [POS[p["position"]["name"]] for p in five]
    if seq == sorted(seq, reverse=True):
        direction = -1   # Center, Forward, Guard
    elif seq == sorted(seq):
        direction = 1    # Guard, Forward, Center
    else:
        order = "".join(LETTER[p["position"]["name"]] for p in five)
        raise Abort(f"άγνωστη διάταξη θέσεων στην πεντάδα ({order}) — δεν αλλάζω τίποτα")

    squad = []
    for p in players:
        played = bool(p.get("match_played"))
        pos = p["position"]["name"]
        squad.append({
            "id": p["id"], "position": pos if pos in POS else "Head Coach", "price": 0.0,
            "name": p.get("last_name", ""), "played": played,
            "x_now": float(p.get("pts") or 0) if played else float(xnow.get(p["id"]) or 0),
            "cur_role": roles.get(p["id"], "coach"), "cur_captain": bool(p.get("is_captain")),
            "court_position": p["court_position"],
            "turn": (p.get("round") or {}).get("number"),
        })
    return {"team": team, "md": md, "raw": raw, "squad": squad, "forms": forms,
            "slots": [p["court_position"] for p in court], "direction": direction,
            "coach": coach[0]}


def propose(st: dict) -> dict:
    res = optimize.lineup_in_round(st["squad"])
    if not res:
        raise Abort("ο βελτιστοποιητής δεν βρήκε έγκυρη πεντάδα")
    res["team"], res["plan"] = optimize.defer_later_turns(res["team"])
    new = {p["id"]: p for p in res["team"]}
    changes = [p for p in st["squad"] if p["position"] != "Head Coach"
               and (new[p["id"]]["role"] != p["cur_role"]
                    or new[p["id"]]["captain"] != p["cur_captain"])]
    for p in changes:  # the game forbids moving a player who already played onto the court
        if p["played"] and new[p["id"]]["role"] != "πάγκος" and p["cur_role"] == "πάγκος":
            raise Abort(f"ο {p['name']} έχει ήδη παίξει από τον πάγκο")
        if p["played"] and new[p["id"]]["captain"] and not p["cur_captain"]:
            raise Abort(f"ο {p['name']} έχει ήδη παίξει και δεν μπορεί να γίνει αρχηγός")

    # body: five in the first 5 slots grouped like the game does (learned direction),
    # sixth man next, then the bench; coach keeps its slot
    d = st["direction"]
    order = lambda r: sorted((p for p in res["team"] if p["role"] == r),  # noqa: E731
                             key=lambda p: (d * POS[p["position"]], p["id"]))
    seq = order("5άδα") + order("6ος") + order("πάγκος")
    five = order("5άδα")
    fname = "-".join(str(sum(p["position"] == pos for p in five)) for pos in POS)
    if fname not in st["forms"]:
        raise Abort(f"το formation {fname} δεν υπάρχει στο παιχνίδι")
    body = {"formation_id": st["forms"][fname], "players": [
        {"id": p["id"], "court_position": slot, "is_captain": bool(p["captain"])}
        for p, slot in zip(seq, st["slots"])] + [
        {"id": st["coach"]["id"], "court_position": st["coach"]["court_position"],
         "is_captain": False}]}
    key = json.dumps(body, sort_keys=True)
    nonce = hashlib.sha1(key.encode()).hexdigest()[:12]
    return {"res": res, "changes": changes, "body": body, "nonce": nonce, "formation": fname,
            "new": new}


def describe(st: dict, pr: dict) -> str:
    new = pr["new"]
    lab = lambda p: f"{p['name']} ({LETTER.get(p['position'], 'HC')})"  # noqa: E731
    five = [p for p in pr["res"]["team"] if p["role"] == "5άδα"]
    six = [p for p in pr["res"]["team"] if p["role"] == "6ος"]
    cap = next(p for p in pr["res"]["team"] if p["captain"])
    lines = [f"👥 <b>Πρόταση πεντάδας</b> ({pr['formation']})",
             ", ".join(lab(p) for p in five), f"6ος: {', '.join(lab(p) for p in six)}",
             f"★ Αρχηγός: {cap['name']}", ""]
    for pl in pr["res"].get("plan") or []:
        lines.append(f"🕐 Πριν το T{pl['bench'].get('turn')}: αν ο {pl['start']['name']} φέρει "
                     f"κάτω από {pl['bench']['x_now']:.0f}, βάλε τον {pl['bench']['name']} "
                     "(στείλε ξανά /lineup μετά το προηγούμενο Turn).")
    if pr["res"].get("plan"):
        lines.append("")
    if not pr["changes"]:
        lines.append("✅ Η ομάδα σου είναι ήδη έτσι — τίποτα να αλλάξει.")
        return "\n".join(lines)
    lines.append("<b>Αλλαγές:</b>")
    for p in pr["changes"]:
        n = new[p["id"]]
        if n["role"] != p["cur_role"]:
            lines.append(f"• {p['name']}: {p['cur_role']} → {n['role']}")
        if n["captain"] and not p["cur_captain"]:
            lines.append(f"• ★ αρχηγός: {p['name']}")
    return "\n".join(lines)


# ------------------------------------------------------------------ commands

def preview():
    st = load_state()
    pr = propose(st)
    text = describe(st, pr)
    if pr["changes"]:
        say(text + "\n\nΝα εφαρμοστεί στο παιχνίδι;",
            [{"text": "✅ Εφάρμοσε", "callback_data": f"lu:apply:{pr['nonce']}"},
             {"text": "❌ Άκυρο", "callback_data": "lu:cancel"}])
    else:
        say(text)


def apply(nonce: str):
    st = load_state()
    pr = propose(st)
    if pr["nonce"] != nonce:
        raise Abort("η πρόταση άλλαξε από τότε που την είδες (νέα δεδομένα ή αλλαγή στο "
                    "παιχνίδι). Στείλε ξανά /lineup.")
    if not pr["changes"]:
        say("✅ Τίποτα να αλλάξει — η ομάδα είναι ήδη έτσι.")
        return
    r = fantasy.save_roster(st["team"]["id"], st["md"]["id"], pr["body"])
    if r.status_code >= 400:
        raise Abort(f"το παιχνίδι απέρριψε την αλλαγή ({r.status_code}): {r.text[:200]}")
    # read back and verify
    after = fantasy.roster(st["team"]["id"], st["md"]["id"]).get("players") or []
    got = {p["id"]: (p["court_position"], bool(p.get("is_captain"))) for p in after}
    want = {p["id"]: (p["court_position"], p["is_captain"]) for p in pr["body"]["players"]}
    bad = [i for i in want if got.get(i) != want[i]]
    if bad:
        raise Abort(f"η αποθήκευση απάντησε OK αλλά {len(bad)} παίκτες δεν έχουν τη θέση που "
                    "στάλθηκε — έλεγξε την ομάδα στο παιχνίδι.")
    say("✅ <b>Η πεντάδα εφαρμόστηκε</b> και επιβεβαιώθηκε στο παιχνίδι.\n\n"
        + describe(st, pr).split("\n\n<b>Αλλαγές:</b>")[0])


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "preview"
    try:
        if mode == "apply":
            apply(sys.argv[2])
        else:
            preview()
    except (Abort, fantasy.TokenError) as e:
        say(f"⛔ /lineup: {e}")
        sys.exit(0 if isinstance(e, Abort) else 1)
