"""17/11: on the real pool (~360 players) the page's trades (web/opt.js) were ~13 weighted xFPT worse than
Telegram's (elf/optimize.py) in every squad tried, and never the same. The beam dropped «sell for a cheap
one» (worse on its own) and couldn't afford the dear buy it pays for; the cheap useful players weren't
candidates either. Checked on the frozen UI fixtures (a real round's pool), against the exact optimizer."""
import json
import random
from pathlib import Path

import pytest

from elf import optimize

from test_js_optimizer import js, node  # noqa: F401  (node: the skip below)

pytestmark = pytest.mark.skipif(not node, reason="node not installed")
FIX = json.loads((Path(__file__).parent / "ui" / "fixtures" / "predictions.json").read_text())
POOL = [{"id": int(p["fantasy_id"]), "position": p["position"], "team": p["team"], "price": float(p["price"]),
         "x_h": float(p.get("x_h") or 0), "x_now": float(p.get("x_now") or 0)}
        for p in FIX["players"]
        if p.get("fantasy_id") is not None and p.get("price") is not None and p["position"] in optimize.SQUAD]


def squads(n, seed):
    """Plausible squads: 11 among the 40 best at each position, within 100 credits."""
    rnd = random.Random(seed)
    by = {pos: sorted((p for p in POOL if p["position"] == pos), key=lambda p: -p["x_h"])[:40] for pos in optimize.SQUAD}
    out = []
    while len(out) < n:
        sq = [p for pos, k in optimize.SQUAD.items() for p in rnd.sample(by[pos], k)]
        cost = sum(p["price"] for p in sq)
        if cost <= 100:
            out.append((sq, round(100 - cost, 1)))
    return out


def test_the_page_finds_what_telegram_finds_on_a_real_pool():
    cases, pys = [], []
    for sq, bank in squads(12, 1):
        cases.append({"kind": "transfers", "squad": sq, "pool": POOL, "bank": bank, "maxTrades": 4, "minGain": 1.6})
        pys.append(optimize.transfers(sq, POOL, bank, max_trades=4, min_gain_per_trade=1.6))
    same = 0
    for c, p, j in zip(cases, pys, js(cases)):
        assert sum(q["price"] for q in j["squad"]) <= sum(q["price"] for q in c["squad"]) + c["bank"] + 1e-6
        assert j["gain"] >= (p["gain"] if p else 0) - 1.0, (j["gain"], p["gain"])
        owned = {q["id"] for q in c["squad"]}
        same += sorted(q["id"] for q in j["squad"] if q["id"] not in owned) == sorted(q["id"] for q in p["in"])
    assert same >= len(cases) * 2 // 3, f"the same trades in only {same} of {len(cases)}"


def test_the_fast_squad_value_equals_trying_every_five():
    rnd = random.Random(2)
    cases = []
    for _ in range(300):
        sq, pid = [], 1
        for pos, k in optimize.SQUAD.items():
            for _ in range(k):
                sq.append({"id": pid, "position": pos, "x_h": round(rnd.uniform(-5, 40), 1),
                           "x_now": round(rnd.uniform(-3, 30), 1)})
                pid += 1
        cases.append({"kind": "squadValue", "squad": sq})
    for fast, every in js(cases):
        assert fast == pytest.approx(every, abs=1e-9)
