"""The dashboard's in-browser optimizer (web/opt.js) must agree with elf/optimize.py."""
import json
import random
import shutil
import subprocess
from pathlib import Path

import pytest

from elf import optimize

from conftest import player, squad_t1_t2

node = shutil.which("node")
pytestmark = pytest.mark.skipif(not node, reason="node not installed")
RUNNER = Path(__file__).with_name("js_runner.js")


def js(cases):
    out = subprocess.run([node, str(RUNNER)], input=json.dumps(cases), capture_output=True,
                         text=True, check=True)
    return json.loads(out.stdout)


def rand_squad(rnd, pid0=1, turns=(1, 2)):
    sq = []
    for pos, n in optimize.SQUAD.items():
        for _ in range(n):
            x = round(rnd.uniform(0, 25), 1)
            sq.append(player(pid0, pos, x, rnd.choice(turns), price=round(rnd.uniform(4, 17), 1)))
            sq[-1]["x_h"] = round(x * rnd.uniform(1.2, 2.2), 1)
            pid0 += 1
    return sq


def py_obj(team, value="x_now"):
    tot = 0.0
    for p in team:
        v = p.get(value) or 0
        if p["role"] == "coach":
            tot += v
        else:
            tot += v if p["role"] in ("5άδα", "6ος") else 0.5 * v
            tot += (p.get("x_now") or 0) if p["captain"] else 0
    return tot


def test_lineup_matches_python_on_random_squads():
    rnd = random.Random(7)
    cases, pys = [], []
    for _ in range(60):
        sq = rand_squad(rnd)
        cases.append({"kind": "lineup", "squad": sq, "inRound": False})
        pys.append(optimize.lineup(sq))
    for c, p, j in zip(cases, pys, js(cases)):
        later = optimize.later_turn_ids(c["squad"])
        n_later_py = sum(1 for q in p["team"] if q["role"] in ("5άδα", "6ος") and q["id"] in later)
        n_later_js = sum(1 for q in j["team"] if q["role"] in ("5άδα", "6ος") and q["id"] in later)
        assert n_later_js == n_later_py
        assert j["objective"] == pytest.approx(py_obj(p["team"]), abs=1e-6)


def test_in_round_lineup_matches_python():
    rnd = random.Random(11)
    cases, pys = [], []
    for _ in range(60):
        sq = rand_squad(rnd)
        base = optimize.lineup(sq)["team"]
        roles = {p["id"]: p["role"] for p in base}
        cap = next(p["id"] for p in base if p["captain"])
        for p in sq:                                   # turn 1 has been played
            p["cur_role"], p["cur_captain"] = roles[p["id"]], p["id"] == cap
            if p["turn"] == 1 and p["position"] != "Head Coach":
                p["played"], p["x_now"] = True, float(rnd.randint(-3, 35))
        cases.append({"kind": "lineup", "squad": sq, "inRound": True})
        pys.append(optimize.lineup_in_round(sq))
    for c, p, j in zip(cases, pys, js(cases)):
        assert (p is None) == (j is None)
        if p:
            assert j["objective"] == pytest.approx(py_obj(p["team"]), abs=1e-6)
            cur = {q["id"]: q for q in c["squad"]}
            for q in j["team"]:                        # the game's rules hold
                o = cur[q["id"]]
                if o.get("played") and o["position"] != "Head Coach":
                    assert q["role"] in (o["cur_role"], "πάγκος")
                    assert not (q["captain"] and not o["cur_captain"])


def test_plan_matches_python():
    team = optimize.lineup(squad_t1_t2())["team"]
    py = {(p["bench"]["id"], p["start"]["id"]) for p in optimize.defer_later_turns(team)[1]}
    assert {tuple(x) for x in js([{"kind": "plan", "team": team}])[0]} == py


def test_transfers_close_to_python_and_legal():
    rnd = random.Random(3)
    cases, pys = [], []
    for i in range(12):
        pool = rand_squad(rnd, 1000) + rand_squad(rnd, 2000) + rand_squad(rnd, 3000)
        sq = rand_squad(rnd, 1)
        bank = round(rnd.uniform(0, 8), 1)
        k = 4 if i % 3 else 11
        cases.append({"kind": "transfers", "squad": sq, "pool": pool, "bank": bank, "maxTrades": k,
                      "minGain": 2.0})
        pys.append(optimize.transfers(sq, pool, bank, max_trades=k, min_gain_per_trade=2.0))
    for c, p, j in zip(cases, pys, js(cases)):
        budget = sum(q["price"] for q in c["squad"]) + c["bank"]
        assert sum(q["price"] for q in j["squad"]) <= budget + 1e-6
        counts = {pos: sum(q["position"] == pos for q in j["squad"]) for pos in optimize.SQUAD}
        assert counts == optimize.SQUAD and j["n"] <= c["maxTrades"]
        assert j["gain"] >= 0.95 * (p["gain"] or 0) - 0.5, (j["gain"], p["gain"])
