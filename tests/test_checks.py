"""The proposals' rules (elf/checks.py), checked on every update."""
from elf import checks


def squad(**over):
    """A legal squad: 4 G, 4 F, 2 C, 1 HC, 10 cr each (100), five G G F F C, sixth F, captain id 1."""
    pos = ["Guard"] * 4 + ["Forward"] * 4 + ["Center"] * 2 + ["Head Coach"]
    roles = ["5άδα", "5άδα", "πάγκος", "πάγκος", "5άδα", "5άδα", "6ος", "πάγκος", "5άδα", "πάγκος", "coach"]
    team = [{"id": i + 1, "position": p, "price": 9.0 if p != "Head Coach" else 10.0, "team": f"T{i % 5}",
             "role": r, "captain": i == 0, "name": f"P{i + 1}"} for i, (p, r) in enumerate(zip(pos, roles))]
    for i, ch in over.items():
        team[int(i[1:]) - 1].update(ch)
    return team


def test_a_legal_squad_and_lineup_pass():
    assert checks.squad_issues(squad()) == []
    assert checks.lineup_issues(squad(), set(), {}) == []


def test_squad_rules():
    two_coaches = squad(p11={"position": "Head Coach"}, p10={"position": "Head Coach"})
    assert any("σύνθεση" in w for w in checks.squad_issues(two_coaches))
    seven = squad(**{f"p{i}": {"team": "OLY"} for i in range(1, 8)})
    assert any("OLY" in w for w in checks.squad_issues(seven))
    dear = squad(p1={"price": 20.0})
    assert any("κοστίζει" in w for w in checks.squad_issues(dear))
    assert checks.squad_issues(dear, budget=None) == []


def test_lineup_rules():
    no_center = squad(p9={"role": "πάγκος"}, p10={"role": "5άδα", "position": "Forward"})
    assert any("χωρίς Center" in w for w in checks.lineup_issues(no_center, set(), {}))
    bench_cap = squad(p1={"captain": False}, p3={"captain": True})
    assert any("δεν είναι στο Starting five" in w for w in checks.lineup_issues(bench_cap, set(), {}))
    two_caps = squad(p2={"captain": True})
    assert any("2 Captains" in w for w in checks.lineup_issues(two_caps, set(), {}))
    out = checks.lineup_issues(squad(), set(), {1: {"avail_game": 0}})
    assert any("εκτός αγώνα" in w for w in out)


def test_a_captain_whose_game_is_over_is_flagged_unless_he_had_the_armband():
    """14/10: a turn-1 DNP proposed as captain."""
    team = squad()                                   # captain id 1, club T0
    assert any("έχει τελειώσει" in w for w in checks.lineup_issues(team, {"T0"}, {}))
    assert checks.lineup_issues(team, {"T0"}, {}, cur_captain=1) == []


def test_run_names_no_player_of_the_owners_team():
    pred = {"round": 5, "turns": [{"turn": 1, "done": True, "teams": ["T0"]}], "players": [],
            "best_team": {"team": squad()},
            "my_team": {"lineup": squad(), "actual_lineup": [{"fantasy_id": 2, "captain": True}]}}
    ws = checks.run(pred, {"rounds": [{"round": 5, "squad": squad()}]})
    mine = [w for w in ws if "η ομάδα σου" in w]
    assert mine and all("P1" not in w for w in mine)          # the log is public
    assert all("καλύτερη ομάδα" not in w for w in ws)          # the best team's captain played nothing
