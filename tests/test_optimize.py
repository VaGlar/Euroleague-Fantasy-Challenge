"""Game rules the optimizer must never break."""
import random

import pytest

from elf import optimize
from elf.config import BUDGET

from conftest import player, squad_t1_t2


def roles(team, r):
    return {p["id"] for p in team if p["role"] == r}


def check_lineup(team):
    five = [p for p in team if p["role"] == "5άδα"]
    assert len(five) == 5
    assert len(roles(team, "6ος")) == 1
    assert {p["position"] for p in five} >= {"Guard", "Forward", "Center"}, "5άδα χωρίς G/F/C"
    caps = [p for p in team if p["captain"]]
    assert len(caps) == 1 and caps[0]["role"] == "5άδα", "ο αρχηγός πρέπει να είναι στην πεντάδα"
    coach = [p for p in team if p["position"] == "Head Coach"]
    assert len(coach) == 1 and coach[0]["role"] == "coach" and not coach[0]["captain"]


def cheapest_squad(pl):
    """The cheapest legal squad: weak, so there is room to improve with trades."""
    out = []
    for pos, n in optimize.SQUAD.items():
        out += sorted((p for p in pl if p["position"] == pos), key=lambda p: p["price"])[:n]
    return out


def pool(n_per_pos=12, seed=1):
    rnd = random.Random(seed)
    out, pid = [], 100
    for pos, n in (("Guard", n_per_pos), ("Forward", n_per_pos), ("Center", n_per_pos // 2),
                   ("Head Coach", 4)):
        for _ in range(n):
            price = round(rnd.uniform(4, 17), 1)
            x = price * rnd.uniform(0.8, 1.4)
            out.append(player(pid, pos, x, rnd.choice([1, 2]), price=price))
            pid += 1
    return out


# ------------------------------------------------------------------ squad

def test_best_squad_composition_and_budget():
    res = optimize.best_squad(pool())
    team = res["team"]
    counts = {pos: sum(p["position"] == pos for p in team) for pos in optimize.SQUAD}
    assert counts == optimize.SQUAD
    assert res["cost"] <= BUDGET + 1e-6
    check_lineup(team)


def test_five_needs_guard_forward_center_even_when_centers_are_weak():
    sq = [player(i, "Guard", 20) for i in range(1, 5)] + \
         [player(i, "Forward", 20) for i in range(5, 9)] + \
         [player(9, "Center", 1), player(10, "Center", 0.5), player(11, "Head Coach", 1)]
    team = optimize.lineup(sq)["team"]
    check_lineup(team)
    assert 9 in roles(team, "5άδα")


# ------------------------------------------------------------------ turns

def test_later_turn_ids():
    assert optimize.later_turn_ids(squad_t1_t2()) == {3, 4, 8, 10}
    sq = squad_t1_t2()
    for p in sq:
        if p["turn"] == 1:
            p["played"] = True
    assert optimize.later_turn_ids(sq) == set(), "όταν έπαιξε το T1, το T2 είναι το τρέχον"


def test_lineup_starts_only_current_turn_players():
    team = optimize.lineup(squad_t1_t2())["team"]
    check_lineup(team)
    assert roles(team, "5άδα") == {1, 2, 5, 6, 9}
    assert roles(team, "6ος") == {7}
    assert next(p["id"] for p in team if p["captain"]) == 1


def test_lineup_falls_back_to_one_later_player_when_no_turn1_center():
    sq = squad_t1_t2()
    for p in sq:
        if p["id"] == 9:
            p["turn"] = 2          # now no Center plays in turn 1
    team = optimize.lineup(sq)["team"]
    check_lineup(team)
    later = [p for p in team if p["role"] in ("5άδα", "6ος") and p["turn"] == 2]
    assert [p["position"] for p in later] == ["Center"], "μόνο ο αναγκαίος C από το T2"


def test_swap_plan_pairs_later_players_with_weakest_compatible_starter():
    team, plan = optimize.defer_later_turns(optimize.lineup(squad_t1_t2())["team"])
    pairs = {(pl["bench"]["id"], pl["start"]["id"]) for pl in plan}
    # C 10 -> sixth man 7 (weakest); F 8 cannot take the only T1 Center's slot -> F 6;
    # G 3 -> G 2; G 4 (xPTS 3) is below PLAN_MIN_X -> no plan
    assert pairs == {(10, 7), (8, 6), (3, 2)}
    check_lineup(team)


def test_in_round_turn2_morning():
    sq = squad_t1_t2()
    pts = {1: 30, 2: 2, 5: 25, 6: 3, 7: 1, 9: 0}
    cur = {1: "5άδα", 2: "5άδα", 5: "5άδα", 6: "5άδα", 9: "5άδα", 7: "6ος"}
    for p in sq:
        p["cur_role"] = cur.get(p["id"], "πάγκος")
        p["cur_captain"] = p["id"] == 1
        if p["id"] in pts:
            p["played"], p["x_now"] = True, pts[p["id"]]
    team = optimize.lineup_in_round(sq)["team"]
    check_lineup(team)
    assert {3, 8, 10} <= roles(team, "5άδα"), "οι παίκτες του T2 μπαίνουν το πρωί του T2"
    assert next(p["id"] for p in team if p["captain"]) == 1, "30 πραγματικοί > 17 αναμενόμενοι"


def test_in_round_played_bench_player_stays_and_played_player_cannot_take_armband():
    sq = squad_t1_t2()
    for p in sq:
        p["cur_role"], p["cur_captain"] = "πάγκος", p["id"] == 3
        if p["id"] == 7:
            p.update(played=True, x_now=60)       # huge score, but from the bench
        if p["id"] == 5:
            p.update(played=True, x_now=50, cur_role="5άδα")
    team = optimize.lineup_in_round(sq)["team"]
    assert 7 in roles(team, "πάγκος")
    cap = next(p for p in team if p["captain"])
    assert cap["id"] != 5, "όποιος έπαιξε δεν γίνεται αρχηγός"


# -------------------------------------------------------------- transfers

def test_transfers_respect_limits_budget_and_keep():
    pl = pool(seed=3)
    squad = cheapest_squad(pl)
    keep = {squad[0]["id"]}
    bank = BUDGET - sum(p["price"] for p in squad)
    tr = optimize.transfers(squad, pl, bank=bank, max_trades=4, keep=keep)
    assert tr["out"], "ένα αδύναμο ρόστερ πρέπει να πάρει προτάσεις"
    assert len(tr["out"]) == len(tr["in"]) <= 4
    assert tr["bank_after"] >= -1e-6
    assert keep <= {p["id"] for p in tr["result"]["team"]}
    counts = {pos: sum(p["position"] == pos for p in tr["result"]["team"])
              for pos in optimize.SQUAD}
    assert counts == optimize.SQUAD
    assert tr["gain"] >= 2.0 * len(tr["out"]) - 1e-6


def test_no_transfer_when_nothing_better():
    sq = squad_t1_t2()
    worse = [player(200 + i, p["position"], 0.5, price=p["price"])  # worse than anyone owned
             for i, p in enumerate(sq)]
    tr = optimize.transfers(sq, worse, bank=0)
    assert tr["out"] == [] and tr["in"] == []


@pytest.mark.parametrize("max_trades", [0, 1, 2])
def test_trade_cap(max_trades):
    pl = pool(seed=5)
    squad = cheapest_squad(pl)
    tr = optimize.transfers(squad, pl, bank=BUDGET - sum(p["price"] for p in squad),
                            max_trades=max_trades)
    assert len(tr["out"]) <= max_trades
