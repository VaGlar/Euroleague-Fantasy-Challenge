"""Integer-programming squad tools (PuLP + CBC, free).

Scoring model mirrored from the game rules:
  - starting five + sixth man score 100%, the other 4 players 50%, coach 100%
  - the captain (from the starting five) scores double
  - the starting five needs at least one Guard, one Forward and one Center
  - squad: 4 G, 4 F, 2 C, 1 head coach, within the credit budget

`value` is the multi-round expectation (xPTS over the horizon) used to pick
players; `now` is this round's expectation, used for the captain bonus.
"""
from __future__ import annotations

import pulp

from .config import BENCH_MULTIPLIER, BUDGET

SQUAD = {"Guard": 4, "Forward": 4, "Center": 2, "Head Coach": 1}
COURT = ("Guard", "Forward", "Center")
LATER_PENALTY = 1000.0
# Start only players of the current turn (later-turn players on the bench). The game
# freezes every player whose team has played (422 "Illegal moves: at least one team has
# already played"), so a benched later-turn player can only replace a starter who has
# not played either: this rule gives no second chance, see README.
START_CURRENT_TURN_ONLY = True


def later_turn_ids(squad: list[dict]) -> set:
    """Unplayed court players whose game is after the current turn (the earliest turn
    among unplayed court players). Empty when START_CURRENT_TURN_ONLY is off."""
    if not START_CURRENT_TURN_ONLY:
        return set()
    court = [p for p in squad if p["position"] != "Head Coach" and not p.get("played")]
    turns = [p["turn"] for p in court if p.get("turn")]
    if not turns:
        return set()
    first = min(turns)
    return {p["id"] for p in court if (p.get("turn") or first) > first}


def _model(players: list[dict], value: str, now: str, budget: float,
           owned: set | None = None, max_trades: int | None = None,
           fixed: set | None = None, keep: set | None = None,
           bench_bonus: dict | None = None, bench_only: set | None = None,
           no_captain: set | None = None, later: set | None = None,
           pinned: dict | None = None):
    """Build and solve. players: dicts with id, position, price, <value>, <now>.
    `later`: players whose game is in a later turn; they start (five / sixth man) only
    if the lineup is impossible otherwise (big penalty per such starter).
    `pinned`: {id: (role, captain)} players that must keep role and armband as they are."""
    m = pulp.LpProblem("elf", pulp.LpMaximize)
    ids = range(len(players))
    pick = {i: pulp.LpVariable(f"p{i}", cat="Binary") for i in ids}
    five = {i: pulp.LpVariable(f"f{i}", cat="Binary") for i in ids}
    six = {i: pulp.LpVariable(f"s{i}", cat="Binary") for i in ids}
    cap = {i: pulp.LpVariable(f"c{i}", cat="Binary") for i in ids}
    obj = []
    for i, p in enumerate(players):
        v = float(p.get(value) or 0)
        if p["position"] == "Head Coach":
            obj.append(v * pick[i])
            m += five[i] + six[i] + cap[i] == 0
            continue
        full = five[i] + six[i]
        bb = (bench_bonus or {}).get(p["id"], 0.0)  # option value of a later-turn bench player
        obj += [v * full, (BENCH_MULTIPLIER * v + bb) * (pick[i] - full),
                float(p.get(now) or 0) * cap[i]]
        m += full <= pick[i]
        m += cap[i] <= five[i]
        if bench_only and p["id"] in bench_only:   # already played from the bench: locked
            m += full == 0
        if no_captain and p["id"] in no_captain:   # already played: can't take the armband
            m += cap[i] == 0
        if later and p["id"] in later:
            obj.append(-LATER_PENALTY * full)
        if pinned and p["id"] in pinned:
            r, c = pinned[p["id"]]
            m += five[i] == int(r == "5άδα")
            m += six[i] == int(r == "6ος")
            m += cap[i] == int(bool(c))
    m += pulp.lpSum(obj)
    m += pulp.lpSum(float(players[i]["price"]) * pick[i] for i in ids) <= budget + 1e-6
    for pos, n in SQUAD.items():
        m += pulp.lpSum(pick[i] for i in ids if players[i]["position"] == pos) == n
    m += pulp.lpSum(five.values()) == 5
    m += pulp.lpSum(six.values()) == 1
    m += pulp.lpSum(cap.values()) == 1
    for pos in COURT:
        m += pulp.lpSum(five[i] for i in ids if players[i]["position"] == pos) >= 1
    if fixed is not None:  # lineup only: squad is given
        for i, p in enumerate(players):
            m += pick[i] == (1 if p["id"] in fixed else 0)
    for i, p in enumerate(players):  # user-locked players stay
        if keep and p["id"] in keep:
            m += pick[i] == 1
    if owned is not None and max_trades is not None:
        m += pulp.lpSum(pick[i] for i, p in enumerate(players) if p["id"] in owned) \
            >= len(owned) - max_trades
    status = m.solve(pulp.PULP_CBC_CMD(msg=0, timeLimit=30))
    if pulp.LpStatus[status] != "Optimal":
        return None
    n_later = sum(1 for i, p in enumerate(players) if later and p["id"] in later
                  and five[i].value() + six[i].value() > .5)

    def role(i):
        if players[i]["position"] == "Head Coach":
            return "coach"
        return "5άδα" if five[i].value() > .5 else "6ος" if six[i].value() > .5 else "πάγκος"

    team = [{**players[i], "role": role(i), "captain": cap[i].value() > .5}
            for i in ids if pick[i].value() > .5]
    return {"team": team, "objective": round(pulp.value(m.objective) + LATER_PENALTY * n_later, 1),
            "cost": round(sum(float(p["price"]) for p in team), 1)}


def best_squad(pool: list[dict], budget: float = BUDGET, value="x_h", now="x_now"):
    return _model(pool, value, now, budget)


def lineup(squad: list[dict], now="x_now"):
    """Best five / sixth man / captain for this round from the owned squad."""
    return _model(squad, now, now, budget=1e9, fixed={p["id"] for p in squad},
                  later=later_turn_ids(squad))


def transfers(squad: list[dict], pool: list[dict], bank: float, max_trades: int = 4,
              min_gain_per_trade: float = 2.0, value="x_h", now="x_now",
              keep: set | None = None):
    """Best set of at most `max_trades` swaps.

    A trade is only worth it if it adds at least `min_gain_per_trade` expected
    points over the weighted horizon (~2 rounds; trades are scarce: 4 per round)."""
    owned = {p["id"] for p in squad}
    budget = sum(float(p["price"]) for p in squad) + bank
    universe = {p["id"]: p for p in pool}
    universe.update({p["id"]: p for p in squad})  # owned players always selectable
    players = list(universe.values())
    keep = (keep or set()) & owned
    base = _model(players, value, now, budget, owned=owned, max_trades=0)
    best, best_k = base, 0
    for k in range(1, max_trades + 1):
        res = _model(players, value, now, budget, owned=owned, max_trades=k, keep=keep)
        if res and base and res["objective"] - base["objective"] >= min_gain_per_trade * k \
                and (best is None or res["objective"] - best["objective"]
                     >= min_gain_per_trade * (k - best_k)):
            best, best_k = res, k
    if not best:
        return None
    new_ids = {p["id"] for p in best["team"]}
    out = [p for p in squad if p["id"] not in new_ids]
    inn = [p for p in best["team"] if p["id"] not in owned]
    return {"out": out, "in": inn, "gain": round(best["objective"] - base["objective"], 1)
            if base else None, "result": best, "bank_after": round(budget - best["cost"], 1)}


def lineup_in_round(squad: list[dict], now="x_now"):
    """Lineup during a round. The game freezes every player whose team has already
    played: same role, same armband (it answers 422 "Illegal moves" otherwise). Only
    players who have not played can be rearranged, and the armband can only move
    between them (if the captain himself has not played)."""
    pinned = {p["id"]: (p.get("cur_role"), bool(p.get("cur_captain")))
              for p in squad if p.get("played") and p["position"] != "Head Coach"}
    return _model(squad, now, now, budget=1e9, fixed={p["id"] for p in squad},
                  pinned=pinned, later=later_turn_ids(squad))


def defer_later_turns(team: list[dict]) -> tuple[list[dict], list[dict]]:
    """Safety net for START_CURRENT_TURN_ONLY: a later-turn starter left by an
    infeasible lineup goes to the bench when an earlier-turn bench player can take his
    slot (the five keeps >= 1 Guard, Forward and Center). Players who already played
    are never moved. Returns (team, plan); plan is always empty: the game does not
    allow bringing a later player in for one who already played."""
    team = [dict(p) for p in team]
    court = [p for p in team if p["role"] in ("5άδα", "6ος", "πάγκος")]
    turns = [p.get("turn") for p in court if p.get("turn") and not p.get("played")]
    if not turns or not START_CURRENT_TURN_ONLY:
        return team, []
    first = min(turns)
    turn = lambda p: p.get("turn") or first  # noqa: E731

    def five_ok(five):
        return all(any(q["position"] == pos for q in five) for pos in COURT)

    def fits(out, inn):  # can `inn` take the slot of `out`?
        if out["role"] != "5άδα":
            return True
        return five_ok([q for q in court if q["role"] == "5άδα" and q is not out] + [inn])

    for lp in sorted((p for p in court if p["role"] in ("5άδα", "6ος") and not p.get("played")
                      and turn(p) > first), key=lambda p: -(p.get("x_now") or 0)):
        cands = [e for e in court if e["role"] == "πάγκος" and not e.get("played")
                 and turn(e) < turn(lp) and fits(lp, e)]
        if cands:
            e = max(cands, key=lambda q: q.get("x_now") or 0)
            e["role"], lp["role"] = lp["role"], "πάγκος"
    cap = next((p for p in team if p.get("captain")), None)
    if cap is not None and cap["role"] != "5άδα" and not cap.get("played"):
        cap["captain"] = False
        best = max((p for p in team if p["role"] == "5άδα"), key=lambda p: p.get("x_now") or 0)
        best["captain"] = True
    return team, []
