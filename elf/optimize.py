"""Integer-programming squad tools (PuLP + CBC, free).

Scoring model mirrored from the game rules:
  - starting five + sixth man score 100%, the other 4 players 50%, coach 100%
  - the captain (from the starting five) scores double
  - the starting five needs at least one Guard, one Forward and one Center
  - squad: 4 G, 4 F, 2 C, 1 head coach, within the credit budget

`value` is the multi-round expectation (xFPT over the horizon) used to pick
players; `now` is this round's expectation, used for the captain bonus.
"""
from __future__ import annotations

from math import erf, exp, pi, sqrt

import pulp

from .config import BENCH_MULTIPLIER, BUDGET

SQUAD = {"Guard": 4, "Forward": 4, "Center": 2, "Head Coach": 1}
COURT = ("Guard", "Forward", "Center")
MAX_PER_CLUB = 6   # the game's rule: up to 6 players from the same EuroLeague club (coach counted too, to be safe)
LATER_PENALTY = 1000.0   # per later-turn starter, per turn he plays after the current one
# the armband on a later-turn player (per turn): only when no earlier starter can take it. Less than
# LATER_PENALTY, so it never pulls one more later player into the five; more than any xFPT gap. An
# earlier captain always dominates: if he flops, the armband moves to the later player before his game.
CAP_LATER_PENALTY = 100.0
PLAN_MIN_X = 5.0  # a later-turn bench player below this is not worth a swap plan


def later_turn_steps(squad: list[dict]) -> dict:
    """{id: how many turns after the current one} for unplayed court players whose game is
    after the current turn (the earliest turn among unplayed court players). Rule: the lineup
    for a turn is built from players of that turn; later-turn players wait on the bench and
    come in if needed. With 3 turns a T3 player is later than a T2 one (2 steps vs 1)."""
    court = [p for p in squad if p["position"] != "Head Coach" and not p.get("played")]
    turns = [p["turn"] for p in court if p.get("turn")]
    if not turns:
        return {}
    first = min(turns)
    out = {}
    for p in court:
        d = (p.get("turn") or first) - first
        # a player with nothing expected (out of the roster, injured) is no option to keep in the five
        # either: he starts only if nobody else can, like a later-turn player
        if d > 0 or float(p.get("x_now") or 0) <= 0:
            out[p["id"]] = max(1, d)
    return out


def later_turn_ids(squad: list[dict]) -> set:
    return set(later_turn_steps(squad))


def _model(players: list[dict], value: str, now: str, budget: float,
           owned: set | None = None, max_trades: int | None = None,
           fixed: set | None = None, keep: set | None = None,
           bench_bonus: dict | None = None, bench_only: set | None = None,
           no_captain: set | None = None, later: dict | None = None,
           stay_or_bench: dict | None = None):
    """Build and solve. players: dicts with id, position, price, <value>, <now>.
    `later`: {id: turns after the current one} (`later_turn_steps`); they start (five / sixth
    man) only if the lineup is impossible otherwise (big penalty per such starter and turn),
    and take the armband only if no earlier starter can.
    `stay_or_bench`: {id: role} played starters: keep that role or go to the bench."""
    m = pulp.LpProblem("elf", pulp.LpMaximize)
    ids = range(len(players))
    pick = {i: pulp.LpVariable(f"p{i}", cat="Binary") for i in ids}
    five = {i: pulp.LpVariable(f"f{i}", cat="Binary") for i in ids}
    six = {i: pulp.LpVariable(f"s{i}", cat="Binary") for i in ids}
    cap = {i: pulp.LpVariable(f"c{i}", cat="Binary") for i in ids}
    later = later if isinstance(later, dict) else dict.fromkeys(later or (), 1)
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
        if p["id"] in later:
            obj += [-LATER_PENALTY * later[p["id"]] * full, -CAP_LATER_PENALTY * later[p["id"]] * cap[i]]
        if stay_or_bench and p["id"] in stay_or_bench:
            m += (six if stay_or_bench[p["id"]] == "5άδα" else five)[i] == 0
    m += pulp.lpSum(obj)
    m += pulp.lpSum(float(players[i]["price"]) * pick[i] for i in ids) <= budget + 1e-6
    for pos, n in SQUAD.items():
        m += pulp.lpSum(pick[i] for i in ids if players[i]["position"] == pos) == n
    m += pulp.lpSum(five.values()) == 5
    m += pulp.lpSum(six.values()) == 1
    m += pulp.lpSum(cap.values()) == 1
    for pos in COURT:
        m += pulp.lpSum(five[i] for i in ids if players[i]["position"] == pos) >= 1
    if fixed is None:      # squad choice: the game's per-club limit (never below what is already owned)
        clubs = {}
        for i, p in enumerate(players):
            if p.get("team"):
                clubs.setdefault(p["team"], []).append(i)
        for club, idx in clubs.items():
            have = sum(1 for i in idx if owned and players[i]["id"] in owned)
            m += pulp.lpSum(pick[i] for i in idx) <= max(MAX_PER_CLUB, have)
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
    pen = sum(later[p["id"]] * (LATER_PENALTY * (five[i].value() + six[i].value())
                                + CAP_LATER_PENALTY * cap[i].value())
              for i, p in enumerate(players) if p["id"] in later)

    def role(i):
        if players[i]["position"] == "Head Coach":
            return "coach"
        return "5άδα" if five[i].value() > .5 else "6ος" if six[i].value() > .5 else "πάγκος"

    team = [{**players[i], "role": role(i), "captain": cap[i].value() > .5}
            for i in ids if pick[i].value() > .5]
    return {"team": team, "objective": round(pulp.value(m.objective) + pen, 1),
            "cost": round(sum(float(p["price"]) for p in team), 1)}


def best_squad(pool: list[dict], budget: float = BUDGET, value="x_h", now="x_now"):
    return _model(pool, value, now, budget)


SCORE_SD = 7.0  # sd of a single-game fantasy score around its expectation


def _expected_shortfall(mu_bench: float, mu_starter: float, sd: float = SCORE_SD) -> float:
    """E[max(0, mu_bench - X)], X ~ N(mu_starter, sd): how much a bench player beats a
    starter who already played, in the cases where you would swap them."""
    d = (mu_bench - mu_starter) / sd
    pdf = exp(-d * d / 2) / sqrt(2 * pi)
    cdf = 0.5 * (1 + erf(d / sqrt(2)))
    return sd * (pdf + d * cdf)


def lineup(squad: list[dict], now="x_now"):
    """Best five / sixth man / captain for this round from the owned squad.

    Turn-aware: a bench player whose game is in a later turn than the starters'
    can still come in if a starter flops (a bench player who already played is
    locked at 50%). That option is worth (1 - bench share) x expected shortfall,
    so later-turn bench players get that bonus."""
    turns = [p.get("turn") for p in squad if p.get("turn") and p["position"] != "Head Coach"]
    first = min(turns) if turns else None
    court = sorted((float(p.get(now) or 0) for p in squad if p["position"] != "Head Coach"),
                   reverse=True)
    typical_starter = sum(court[:6]) / max(1, len(court[:6]))
    bonus = {}
    if first is not None:
        for p in squad:
            if p["position"] != "Head Coach" and (p.get("turn") or first) > first:
                bonus[p["id"]] = (1 - BENCH_MULTIPLIER) * _expected_shortfall(
                    float(p.get(now) or 0), typical_starter)
    return _model(squad, now, now, budget=1e9, fixed={p["id"] for p in squad},
                  bench_bonus=bonus, later=later_turn_steps(squad))


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
    """Lineup during a round (game rules, confirmed by its 422 "Illegal moves"):
      * a player who already played can only leave the starting six for the bench:
        he cannot move five <-> sixth man, and a played bench player cannot enter;
      * the armband can move, but only to a player who has not played yet.
    Players who played carry their real points in `now`."""
    played = {p["id"]: p for p in squad if p.get("played") and p["position"] != "Head Coach"}
    stay_or_bench = {i: p.get("cur_role") for i, p in played.items()
                     if p.get("cur_role") in ("5άδα", "6ος")}
    bench_only = {i for i, p in played.items() if p.get("cur_role") == "πάγκος"}
    no_cap = {i for i, p in played.items() if not p.get("cur_captain")}
    return _model(squad, now, now, budget=1e9, fixed={p["id"] for p in squad},
                  bench_only=bench_only, no_captain=no_cap, stay_or_bench=stay_or_bench,
                  later=later_turn_steps(squad))


def defer_later_turns(team: list[dict]) -> tuple[list[dict], list[dict]]:
    """Swap plan for the later turns.

    The lineup starts only current-turn players (see `later_turn_ids`); each later-turn
    bench player is paired with the weakest current-turn starter he could replace
    (the five must keep >= 1 Guard, Forward and Center). Before the later turn: if the
    early starter scored less than the later player's xFPT, swap them.
    If a later-turn player still starts (no valid lineup otherwise), he is moved to the
    bench when an earlier-turn bench player can take his slot. Players who already
    played are never moved. Returns (team, plan [{"start": early, "bench": later}])."""
    team = [dict(p) for p in team]
    court = [p for p in team if p["role"] in ("5άδα", "6ος", "πάγκος")]
    turns = [p.get("turn") for p in court if p.get("turn") and not p.get("played")]
    if not turns:
        return team, []
    first = min(turns)
    turn = lambda p: p.get("turn") or first  # noqa: E731

    def five_ok(five):
        return all(any(q["position"] == pos for q in five) for pos in COURT)

    def fits(out, inn):  # can `inn` take the slot of `out`?
        if out["role"] != "5άδα":
            return True
        return five_ok([q for q in court if q["role"] == "5άδα" and q is not out] + [inn])

    # safety net: a later-turn starter left by an infeasible lineup
    for lp in sorted((p for p in court if p["role"] in ("5άδα", "6ος") and not p.get("played")
                      and turn(p) > first), key=lambda p: -(p.get("x_now") or 0)):
        cands = [e for e in court if e["role"] == "πάγκος" and not e.get("played")
                 and turn(e) < turn(lp) and fits(lp, e)]
        if cands:
            e = max(cands, key=lambda q: q.get("x_now") or 0)
            e["role"], lp["role"] = lp["role"], "πάγκος"

    plan, used = [], set()
    for lp in sorted((p for p in court if p["role"] == "πάγκος" and not p.get("played")
                      and turn(p) > first and (p.get("x_now") or 0) >= PLAN_MIN_X), key=lambda p: -(p.get("x_now") or 0)):
        cands = [e for e in court if e["role"] in ("5άδα", "6ος") and id(e) not in used
                 and turn(e) < turn(lp) and fits(e, lp)]
        if not cands:
            continue
        e = min(cands, key=lambda q: q.get("x_now") or 0)
        used.add(id(e))
        plan.append({"start": e, "bench": lp})
    # the armband must stay on a starter
    cap = next((p for p in team if p.get("captain")), None)
    if cap is not None and cap["role"] != "5άδα":
        cap["captain"] = False
        best = max((p for p in team if p["role"] == "5άδα"), key=lambda p: p.get("x_now") or 0)
        best["captain"] = True
    return team, plan
