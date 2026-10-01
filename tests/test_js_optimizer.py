"""The dashboard's in-browser optimizer (web/opt.js) must agree with elf/optimize.py."""
import json
from collections import Counter
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


def test_transfers_keep_never_sells_kept_players():
    rnd = random.Random(5)
    cases, pys = [], []
    for i in range(8):
        pool = rand_squad(rnd, 1000) + rand_squad(rnd, 2000) + rand_squad(rnd, 3000)
        sq = rand_squad(rnd, 1)
        # keep the two weakest court players: the ones a plain run would sell first
        keep = [q["id"] for q in sorted((q for q in sq if q["position"] != "Head Coach"), key=lambda q: q["x_h"])[:2]]
        cases.append({"kind": "transfers", "squad": sq, "pool": pool, "bank": 3.0, "maxTrades": 4,
                      "minGain": 2.0, "keep": keep})
        pys.append(optimize.transfers(sq, pool, 3.0, max_trades=4, min_gain_per_trade=2.0, keep=set(keep)))
    for c, p, j in zip(cases, pys, js(cases)):
        ids = {q["id"] for q in j["squad"]}
        assert set(c["keep"]) <= ids
        assert j["gain"] >= 0.95 * (p["gain"] or 0) - 0.5, (j["gain"], p["gain"])


def test_transfers_keep_the_per_club_limit():
    """5 already from one club and the best buys all from it: at most 6 after the trades."""
    rnd = random.Random(9)
    cases = []
    for i in range(6):
        pool = rand_squad(rnd, 1000) + rand_squad(rnd, 2000)
        for q in pool:
            q["team"] = "PAN" if q["x_h"] / q["price"] > 1.6 else f"T{q['id'] % 7}"
        sq = rand_squad(rnd, 1)
        for n, q in enumerate(sq):
            q["team"] = "PAN" if n < 5 else f"S{n}"
        cases.append({"kind": "transfers", "squad": sq, "pool": pool, "bank": 5.0, "maxTrades": 4, "minGain": 2.0})
    for j in js(cases):
        assert sum(q.get("team") == "PAN" for q in j["squad"]) <= optimize.MAX_PER_CLUB


def test_a_cheap_zero_is_sold_even_when_the_best_at_his_position_are_all_dear():
    """Dessert (5.3, 0 xFPT, not on the roster) wasn't sold: the 16 best Centers by xFPT all cost 8.5+,
    so the candidates had nothing he could be swapped for. The best per credit are candidates too."""
    rnd = random.Random(11)
    sq = rand_squad(rnd, 1)
    centers = [q for q in sq if q["position"] == "Center"]
    centers[0].update(x_now=0.0, x_h=0.0, price=5.3)
    pool = [player(5000 + i, "Center", 20 + i * 0.1, 1, price=12 + i * 0.1) for i in range(20)]
    for q in pool:
        q["x_h"] = q["x_now"] * 2
    pool += [player(6000 + i, "Center", 6, 1, price=5.0) for i in range(3)]
    for q in pool[-3:]:
        q["x_h"] = 18.0                          # 3.6 per credit: among the best per credit
    bank = 0.0
    j = js([{"kind": "transfers", "squad": sq, "pool": pool, "bank": bank, "maxTrades": 4, "minGain": 2.0}])[0]
    assert centers[0]["id"] not in {q["id"] for q in j["squad"]}


def test_club_limit_binding_everywhere_js_and_python_agree():
    """One club's players are far better value, so without the limit both optimizers would load up
    on it: both keep at most 6 from every club, the budget and the squad shape, and the JS gain stays
    close to Python's."""
    rnd = random.Random(21)
    clubs = ("PAN", "OLY", "MAD", "BAR")
    cases, pys = [], []
    for i in range(10):
        pool = rand_squad(rnd, 1000) + rand_squad(rnd, 2000) + rand_squad(rnd, 3000)
        for q in pool:
            q["team"] = "PAN" if rnd.random() < 0.5 else rnd.choice(clubs[1:])
            if q["team"] == "PAN":
                q["x_h"] = round(q["x_h"] * 2.0, 1)
                q["x_now"] = round(q["x_now"] * 2.0, 1)
        sq = rand_squad(rnd, 1)
        for n, q in enumerate(sq):
            q["team"] = "PAN" if n < 4 else clubs[1 + n % 3]
        bank = round(rnd.uniform(2, 8), 1)
        k = 4 if i % 2 else 11
        cases.append({"kind": "transfers", "squad": sq, "pool": pool, "bank": bank, "maxTrades": k,
                      "minGain": 2.0})
        pys.append(optimize.transfers(sq, pool, bank, max_trades=k, min_gain_per_trade=2.0))
    binding = 0
    for c, p, j in zip(cases, pys, js(cases)):
        team_of = {q["id"]: q["team"] for q in c["pool"] + c["squad"]}
        js_clubs = Counter(team_of[q["id"]] for q in j["squad"])
        assert max(js_clubs.values()) <= optimize.MAX_PER_CLUB, js_clubs
        binding += js_clubs["PAN"] == optimize.MAX_PER_CLUB
        if p:
            py_clubs = Counter(q["team"] for q in p["result"]["team"])
            assert max(py_clubs.values()) <= optimize.MAX_PER_CLUB, py_clubs
        budget = sum(q["price"] for q in c["squad"]) + c["bank"]
        assert sum(q["price"] for q in j["squad"]) <= budget + 1e-6
        assert {pos: sum(q["position"] == pos for q in j["squad"]) for pos in optimize.SQUAD} == optimize.SQUAD
        assert j["gain"] >= 0.95 * ((p or {}).get("gain") or 0) - 0.5, (j["gain"], (p or {}).get("gain"))
    assert binding >= 5, "the limit must actually bind in most cases, or this test proves nothing"
