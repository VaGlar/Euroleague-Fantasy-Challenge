"""Rules the app's proposals must never break, checked on every update (elf/validate.py).

A broken rule doesn't stop the update: it becomes a health warning, so the owner hears of it on
Telegram (`notify health`) before a user does. Checked: the best squad of the round, the
autopilot's squad of the round, and the proposal for the owner's own team.

The log of the update is public: a warning about the owner's team names no player.
"""
from __future__ import annotations

COURT = ("Guard", "Forward", "Center")
SQUAD = {"Guard": 4, "Forward": 4, "Center": 2, "Head Coach": 1}
BUDGET = 100.0
MAX_PER_CLUB = 6


def done_teams(pred: dict) -> set:
    """Teams whose game of the round is over (a fixture marked played, or a done turn)."""
    rnd = pred.get("round")
    out = {t for f in pred.get("fixtures") or [] if f.get("round") == rnd and f.get("played")
           for t in (f.get("home"), f.get("away"))}
    return out | {t for tu in pred.get("turns") or [] if tu.get("done") for t in tu.get("teams") or []}


def squad_issues(team: list[dict], budget: float | None = BUDGET) -> list[str]:
    """11 players as the game wants them: 4 G, 4 F, 2 C, 1 HC; at most 6 of a club; within the budget."""
    out = []
    counts = {pos: sum(p.get("position") == pos for p in team) for pos in SQUAD}
    if counts != SQUAD:
        out.append("σύνθεση " + " ".join(f"{n}{pos[0]}" for pos, n in counts.items()) + " (θέλει 4G 4F 2C 1H)")
    clubs = {}
    for p in team:
        if p.get("team"):
            clubs[p["team"]] = clubs.get(p["team"], 0) + 1
    over = [c for c, n in clubs.items() if n > MAX_PER_CLUB]
    if over:
        out.append(f"πάνω από {MAX_PER_CLUB} παίκτες από {', '.join(over)}")
    if budget is not None:
        cost = sum(float(p.get("price") or 0) for p in team)
        if cost > budget + 0.05:
            out.append(f"κοστίζει {cost:.1f} cr (> {budget:.0f})")
    return out


def lineup_issues(team: list[dict], done: set, players: dict, cur_captain=None, names: bool = True) -> list[str]:
    """Five / sixth / bench and the armband as the game allows. players: id -> predictions row
    (avail_game, unregistered). done: teams whose game is over. cur_captain: the armband now (in-round)."""
    out = []
    court = [p for p in team if p.get("position") != "Head Coach"]
    five = [p for p in court if p.get("role") == "5άδα"]
    if len(five) != 5 or sum(p.get("role") == "6ος" for p in court) != 1:
        out.append(f"{len(five)} στο Starting five και {sum(p.get('role') == '6ος' for p in court)} Sixth man")
    missing = [pos for pos in COURT if not any(p.get("position") == pos for p in five)]
    if five and missing:
        out.append(f"Starting five χωρίς {'/'.join(missing)}")
    caps = [p for p in team if p.get("captain")]
    if len(caps) != 1:
        out.append(f"{len(caps)} Captains")
        return out
    cap = caps[0]
    who = f" ({cap.get('name')})" if names and cap.get("name") else ""
    if cap.get("role") != "5άδα":
        out.append(f"ο Captain{who} δεν είναι στο Starting five")
    if cap.get("team") in done and cap.get("id") != cur_captain:
        out.append(f"Captain{who} που ο αγώνας του έχει τελειώσει")
    row = players.get(cap.get("id")) or {}
    if row.get("unregistered") or row.get("avail_game") == 0:
        out.append(f"Captain{who} εκτός αγώνα ή εκτός ρόστερ")
    return out


def run(pred: dict, autopilot: dict | None) -> list[str]:
    """The warnings of this update's proposals (empty when all is well)."""
    warnings = []
    done = done_teams(pred)
    players = {p.get("fantasy_id"): p for p in pred.get("players") or [] if p.get("fantasy_id") is not None}
    best = (pred.get("best_team") or {}).get("team")
    if best:
        for w in squad_issues(best) + lineup_issues(best, set(), players):
            warnings.append(f"έλεγχος προτάσεων · καλύτερη ομάδα: {w}")
    rounds = (autopilot or {}).get("rounds") or []
    cur = next((r for r in rounds if r.get("round") == pred.get("round")), None)
    if cur and cur.get("squad"):
        for w in squad_issues(cur["squad"], budget=None):
            warnings.append(f"έλεγχος προτάσεων · autopilot R{cur['round']}: {w}")
    my = pred.get("my_team") or {}
    if my.get("lineup"):
        cur_cap = next((r.get("fantasy_id") for r in my.get("actual_lineup") or [] if r.get("captain")), None)
        # the owner's team: no names (the update's log is public)
        for w in lineup_issues(my["lineup"], done, players, cur_cap, names=False):
            warnings.append(f"έλεγχος προτάσεων · η ομάδα σου: {w}")
    return warnings
