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

from math import erf, exp, pi, sqrt

import pulp

from .config import BENCH_MULTIPLIER, BUDGET

SQUAD = {"Guard": 4, "Forward": 4, "Center": 2, "Head Coach": 1}
COURT = ("Guard", "Forward", "Center")


def _model(players: list[dict], value: str, now: str, budget: float,
           owned: set | None = None, max_trades: int | None = None,
           fixed: set | None = None, keep: set | None = None,
           bench_bonus: dict | None = None):
    """Build and solve. players: dicts with id, position, price, <value>, <now>."""
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

    def role(i):
        if players[i]["position"] == "Head Coach":
            return "coach"
        return "5άδα" if five[i].value() > .5 else "6ος" if six[i].value() > .5 else "πάγκος"

    team = [{**players[i], "role": role(i), "captain": cap[i].value() > .5}
            for i in ids if pick[i].value() > .5]
    return {"team": team, "objective": round(pulp.value(m.objective), 1),
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
                  bench_bonus=bonus)


def transfers(squad: list[dict], pool: list[dict], bank: float, max_trades: int = 4,
              min_gain_per_trade: float = 3.0, value="x_h", now="x_now",
              keep: set | None = None):
    """Best set of at most `max_trades` swaps.

    A trade is only worth it if it adds at least `min_gain_per_trade` expected
    points over the horizon (trades are scarce: 4 per round)."""
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
