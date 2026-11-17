"""The page's trades (web/opt.js, PR 70) on the real pool: the beam may now go over the budget for a
step, when a later cheaper swap pays for it. What it proposes must still keep every rule of the game
and of the dashboard. Expected values: the game's rules (100 credits, squad shape, at most
MAX_PER_CLUB per club, 4 trades), `keep`/`avoid` (opt.js docstring) and the exact optimizer
(elf/optimize.py) for the case the change was made for."""
import json
import random
from collections import Counter
from pathlib import Path

import pytest

from elf import optimize

from test_js_optimizer import js, node  # noqa: F401
from conftest import player

pytestmark = pytest.mark.skipif(not node, reason="node not installed")
FIX = json.loads((Path(__file__).parent / "ui" / "fixtures" / "predictions.json").read_text())
POOL = [{"id": int(p["fantasy_id"]), "position": p["position"], "team": p["team"], "price": float(p["price"]),
         "x_h": float(p.get("x_h") or 0), "x_now": float(p.get("x_now") or 0)}
        for p in FIX["players"]
        if p.get("fantasy_id") is not None and p.get("price") is not None and p["position"] in optimize.SQUAD]


def squads(n, seed, bank_max=6.0):
    rnd = random.Random(seed)
    by = {pos: sorted((p for p in POOL if p["position"] == pos), key=lambda p: -p["x_h"])[:40] for pos in optimize.SQUAD}
    out = []
    while len(out) < n:
        sq = [p for pos, k in optimize.SQUAD.items() for p in rnd.sample(by[pos], k)]
        cost = sum(p["price"] for p in sq)
        if cost <= 100 and Counter(p["team"] for p in sq).most_common(1)[0][1] <= optimize.MAX_PER_CLUB:
            out.append((sq, round(min(100 - cost, bank_max), 1)))
    return out


def test_every_proposal_keeps_the_rules_on_a_real_pool():
    rnd = random.Random(7)
    cases = []
    for sq, bank in squads(16, 3):
        court = [p for p in sq if p["position"] != "Head Coach"]
        keep = [p["id"] for p in rnd.sample(court, 2)]
        owned = {p["id"] for p in sq}
        best_free = sorted((p for p in POOL if p["id"] not in owned), key=lambda p: -p["x_h"])
        avoid = [p["id"] for p in best_free[:3]]             # the buys it would want most
        cases.append({"kind": "transfers", "squad": sq, "pool": POOL, "bank": bank, "maxTrades": 4,
                      "minGain": 1.6, "keep": keep, "avoid": avoid})
    traded = 0
    for c, j in zip(cases, js(cases)):
        before = {p["id"]: p for p in c["squad"]}
        after = {p["id"]: p for p in j["squad"]}
        sold, bought = set(before) - set(after), set(after) - set(before)
        traded += bool(sold)
        assert len(sold) == len(bought) == j["n"] <= 4
        assert sum(p["price"] for p in j["squad"]) <= sum(p["price"] for p in c["squad"]) + c["bank"] + 1e-6
        assert j["bankAfter"] >= -1e-6
        assert Counter(p["position"] for p in j["squad"]) == Counter(optimize.SQUAD)
        assert max(Counter(p["team"] for p in j["squad"]).values()) <= optimize.MAX_PER_CLUB
        assert not set(c["keep"]) & sold, "sold a kept player"
        assert not set(c["avoid"]) & bought, "bought an avoided player"
        assert j["gain"] >= 1.6 * j["n"] - 1e-6               # each trade has to pay its way
    assert traded >= len(cases) // 2                          # so the checks above saw real trades


def test_a_dear_buy_paid_for_by_a_cheap_swap_is_found():
    """The 17/11 case, shrunk: buying the 17.7 Center fits only if the other Center is swapped for a
    4.8 one, a swap that alone makes the team worse. The exact optimizer makes both trades."""
    sq, pid = [], 1
    for pos, k in (("Guard", 4), ("Forward", 4), ("Head Coach", 1)):
        for _ in range(k):
            sq.append(player(pid, pos, 10.0, 1, price=8.0)); pid += 1
    sq.append(player(pid, "Center", 10.0, 1, price=9.0)); c_mid = pid; pid += 1
    sq.append(player(pid, "Center", 12.0, 1, price=11.4)); c_dear = pid; pid += 1
    for i, p in enumerate(sq):
        p["team"] = f"T{i % 9}"
        p["x_h"] = 2 * p["x_now"]
    star = {**player(100, "Center", 30.0, 1, price=17.7), "team": "S1"}; star["x_h"] = 60.0
    filler = {**player(101, "Center", 9.0, 1, price=4.8), "team": "S2"}; filler["x_h"] = 18.0   # worse than both owned
    # many small upgrades elsewhere: they fill the beam, so a step that makes the team worse on its
    # own (the cheap Center swap) has to survive among them (17/11: it didn't)
    extra = []
    for i in range(60):
        pos = "Guard" if i % 2 else "Forward"
        q = {**player(200 + i, pos, 10.5 + i / 100, 1, price=8.0), "team": f"X{i % 20}"}
        q["x_h"] = 2 * q["x_now"]
        extra.append(q)
    pool = sq + [star, filler] + extra
    bank = round(100 - sum(p["price"] for p in sq), 1)
    bank = 2.5 if bank > 2.5 else bank                    # dear swap alone (+8.7) can't fit
    assert 17.7 - 9.0 > bank and (17.7 - 9.0) - (11.4 - 4.8) <= bank
    py = optimize.transfers(sq, pool, bank, max_trades=4, min_gain_per_trade=1.6)
    assert py and {100, 101} <= {p["id"] for p in py["in"]}       # the reference: both trades
    j = js([{"kind": "transfers", "squad": sq, "pool": pool, "bank": bank, "maxTrades": 4, "minGain": 1.6}])[0]
    bought = {p["id"] for p in j["squad"]} - {p["id"] for p in sq}
    assert {100, 101} <= bought
    assert sum(p["price"] for p in j["squad"]) <= sum(p["price"] for p in sq) + bank + 1e-6
