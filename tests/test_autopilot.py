"""The autopilot: a team that only follows the proposals, scored like a real manager."""
import json

import pandas as pd
import pytest

from elf import autopilot, publish
from tests.conftest import use_public

POS = ["Guard"] * 8 + ["Forward"] * 8 + ["Center"] * 4 + ["Head Coach"] * 2


def pool(boost: dict | None = None):
    """22 players (ids 1..22): price 4..~13, xFPT rising with the id (boost: id -> extra xFPT)."""
    rows = []
    for i, pos in enumerate(POS, start=1):
        x = i * 0.8 + (boost or {}).get(i, 0.0)
        rows.append({"id": i, "position": pos, "price": round(4 + i * 0.4, 1), "x_h": x * 2, "x_now": x,
                     "name": f"P{i}", "team": "AAA" if i % 2 else "BBB", "turn": 1})
    table = pd.DataFrame([{"fantasy_id": r["id"], "person_id": f"p{r['id']}", "name": r["name"],
                           "team": r["team"], "position": r["position"]} for r in rows])
    return rows, table


@pytest.fixture
def pub(monkeypatch, tmp_path):
    return use_public(monkeypatch, tmp_path / "public")


def test_decides_frozen_rounds_and_trades(pub, monkeypatch):
    monkeypatch.setattr(autopilot, "actual_points", lambda s: (pd.DataFrame(columns=["round", "gamecode", "person_id", "fp"]), None))
    monkeypatch.setattr(autopilot.history, "load", lambda *a, **k: pd.DataFrame())
    rows, table = pool()
    s = autopilot.update(2026, rnd=3, trade_rnd=3, rows=rows, table=table, max_trades=4, min_gain=0.5)
    r3 = s["rounds"][0]
    assert r3["round"] == 3 and len(r3["squad"]) == 11 and r3["bank"] >= 0
    assert sum(p["price"] for p in r3["squad"]) + r3["bank"] <= 100 + 1e-6
    assert sum(p["captain"] for p in r3["squad"]) == 1
    assert s["start_round"] == 3

    # round 3 under way: its decision is frozen; round 4 starts from it, with at most 4 trades
    rows2, _ = pool(boost={1: 30.0, 2: 30.0})                     # two cheap guards become great
    s = autopilot.update(2026, rnd=3, trade_rnd=4, rows=rows2, table=table, max_trades=4, min_gain=0.5)
    r3b, r4 = s["rounds"]
    assert r3b == r3                                              # untouched (its time too: the last run before tip-off)
    assert r3["decided_at"] and r4["decided_at"] >= r3["decided_at"]
    ids3, ids4 = {p["id"] for p in r3["squad"]}, {p["id"] for p in r4["squad"]}
    assert r4["trades"] == len(ids4 - ids3) <= 4 and {1, 2} <= ids4
    assert json.loads((pub / "autopilot.json").read_text())["rounds"][1]["round"] == 4


def test_score_uses_the_game_rules():
    e = {"round": 5, "squad": [
        {"person_id": "a", "position": "Guard", "team": "X", "role": "5άδα", "captain": True},
        {"person_id": "b", "position": "Forward", "team": "X", "role": "πάγκος", "captain": False},
        {"person_id": "c", "position": "Center", "team": "X", "role": "6ος", "captain": False},
        {"person_id": None, "position": "Head Coach", "team": "X", "role": "coach", "captain": False}]}
    fp = pd.Series({(5, "a"): 10.0, (5, "b"): 8.0, (5, "c"): 5.0})
    game, raw = autopilot.score(e, fp, {"X": 12})                  # coach: won by 12 -> 20
    assert raw == 10 + 8 + 5 + 20
    assert game == 10 * 2 + 8 * 0.5 + 5 + 20


def test_average_manager_from_pop(pub):
    pd.DataFrame([
        {"matchday": 5, "person_id": "a", "team": "X", "position": "Guard", "popularity": 60.0},
        {"matchday": 5, "person_id": "b", "team": "X", "position": "Forward", "popularity": 20.0},
        {"matchday": 5, "person_id": "k", "team": "X", "position": "Head Coach", "popularity": 20.0},
        {"matchday": 4, "person_id": "a", "team": "X", "position": "Guard", "popularity": 99.0},
    ]).to_csv(pub / "prices.csv", index=False)
    fp = pd.Series({(5, "a"): 10.0, (5, "b"): 20.0})
    # 11 x (60x10 + 20x20 + 20x20[coach, won by 12]) / 100
    assert autopilot.average_manager(5, fp, {"X": 12}) == pytest.approx(11 * (600 + 400 + 400) / 100)
    assert autopilot.average_manager(7, fp, {}) is None             # no POP for that matchday


def test_public_edition_drops_the_owners_points(pub, tmp_path):
    (pub / "autopilot.json").write_text(json.dumps({"rounds": [{"round": 3, "pts": 150.0, "my_pts": 170.0,
                                                                 "rank": 900, "teams": 1000, "my_rank": 12}]}))
    publish.bundle(tmp_path / "site", src=pub)
    out = json.loads((tmp_path / "site" / "data" / "autopilot.json").read_text())
    assert out["rounds"] == [{"round": 3, "pts": 150.0, "rank": 900, "teams": 1000}]


def test_starts_from_the_seed_of_the_rounds_before_it(pub, monkeypatch):
    """The rounds before the autopilot existed come from the proposals made before each of them (the
    seed file): it plays from round 1 like a real manager, and a later start is replaced by the seed."""
    monkeypatch.setattr(autopilot, "actual_points", lambda s: (pd.DataFrame(columns=["round", "gamecode", "person_id", "fp"]), None))
    monkeypatch.setattr(autopilot.history, "load", lambda *a, **k: pd.DataFrame())
    rows, table = pool()
    first = [1, 2, 3, 4, 9, 10, 11, 12, 17, 18, 21]                # 4 guards, 4 forwards, 2 centers, coach
    best = {"cost": 60.0, "team": [{"id": r["id"], "price": r["price"], "position": r["position"], "x_now": r["x_now"],
                                    "role": "5άδα", "captain": r["id"] == 3} for r in rows if r["id"] in first]}
    pred = {"players": [{**r, "fantasy_id": r["id"], "person_id": f"p{r['id']}"} for r in rows], "best_team": best}
    r1, r2 = autopilot.seed_rounds([(1, pred), (2, pred)], max_trades=4, min_gain=0.5)
    assert r1["bank"] == 40.0 and [p["id"] for p in r1["squad"]] == first
    assert r1["squad"][0]["person_id"] == "p1"
    five = [q for q in r1["squad"] if q["role"] == "5άδα"]                 # the lineup by the game's rules
    assert len(five) == 5 and {q["position"] for q in five} == {"Guard", "Forward", "Center"}
    assert [q["captain"] for q in r1["squad"]].count(True) == 1 and any(q["captain"] for q in five)
    assert 0 < r2["trades"] <= 4                                   # better players were affordable
    (pub.parent / "autopilot_seed.json").write_text(json.dumps({"rounds": [r1, r2]}))

    autopilot.update(2026, rnd=3, trade_rnd=3, rows=rows, table=table, max_trades=4, min_gain=0.5)
    s = json.loads((pub / "autopilot.json").read_text())
    assert [e["round"] for e in s["rounds"]] == [1, 2, 3] and s["start_round"] == 1
    assert s["rounds"][:2] == [r1, r2]
    assert s["rounds"][2]["trades"] <= 4                           # round 3 goes on from the seed's squad


def fake_standings(monkeypatch, totals):
    """The game's standings endpoint over a list of totals (sorted high to low), paged by the base64
    cursor as the app does; records the requests."""
    import base64
    calls = []

    def get(path, params=None, **k):
        calls.append((path, dict(params or {})))
        assert path == "/tournaments/7/standings" and params["matchday"] == 55
        pos = json.loads(base64.b64decode(params["cursor"]))["tms.position"] if "cursor" in params else 0
        return [{"position": i + 1, "total_pts": totals[i], "name": "x", "user": {"first_name": "y"}}
                for i in range(pos, min(pos + 25, len(totals)))]
    monkeypatch.setattr(autopilot.fantasy, "get", get)
    return calls


def test_rank_is_found_by_binary_search_over_the_cursor(monkeypatch):
    totals = [300.0 - i * 0.01 for i in range(20000)]              # 300.00, 299.99, ...
    calls = fake_standings(monkeypatch, totals)
    assert autopilot.fantasy.rank_of(250.005, 7, 55, 20000) == 5001     # 300.00 .. 250.01: 5000 teams above
    assert len(calls) <= 12                                          # log2(20000/25) + 1, not 800 pages
    assert autopilot.fantasy.rank_of(999.0, 7, 55, 20000) == 1
    assert autopilot.fantasy.rank_of(0.0, 7, 55, 20000) == 20001


def test_ranks_the_round_just_finished_once(monkeypatch):
    totals = [300.0 - i for i in range(300)]
    calls = fake_standings(monkeypatch, totals)
    done = [{"round": 1, "pts": 100.0}, {"round": 2, "pts": 150.5}]
    ov = {"id": 7, "teams": 300, "matchday_id": 55, "round": 2, "my_total": 280.0}
    autopilot._rank(done, ov)
    assert "rank" not in done[0]                                     # only the round just finished
    assert done[1]["rank"] == 51 and done[1]["teams"] == 300         # 250.5: 50 teams above (300..251)
    assert done[1]["my_rank"] == 21
    n = len(calls)
    autopilot._rank(done, ov)
    assert len(calls) == n                                           # never ranked again


def test_between_turns_swaps_a_flop_for_a_later_player_and_moves_the_armband():
    """T1 -> T2 as for the owner's team: a T1 starter who flopped drops to the bench for a T2 bench
    player; the armband moves only to a player who hasn't played; the played can't come back in."""
    sq = [("G1", "Guard", "5άδα", True, 1), ("G2", "Guard", "5άδα", False, 1), ("F1", "Forward", "5άδα", False, 1),
          ("C1", "Center", "5άδα", False, 1), ("F2", "Forward", "5άδα", False, 1), ("G3", "Guard", "6ος", False, 1),
          ("F3", "Forward", "πάγκος", False, 2), ("G4", "Guard", "πάγκος", False, 2), ("F4", "Forward", "πάγκος", False, 1),
          ("C2", "Center", "πάγκος", False, 2), ("HC", "Head Coach", "coach", False, 2)]
    entry = {"round": 4, "squad": [{"id": i, "name": n, "position": pos, "role": role, "captain": cap, "price": 5.0}
                                   for i, (n, pos, role, cap, _) in enumerate(sq)]}
    actual = {"G1": 2.0, "G2": 15.0, "F1": 12.0, "C1": 10.0, "F2": 9.0, "G3": 8.0, "F4": 30.0}
    xnow = {"F3": 25.0, "G4": 6.0, "C2": 5.0, "HC": 8.0}
    rows = [{"id": i, "turn": t, "team": "T", "x_now": xnow.get(n, 0.0), "actual": actual.get(n)}
            for i, (n, _, _, _, t) in enumerate(sq)]
    autopilot.between_turns(entry, rows, turn=2)
    role = {p["name"]: p["role"] for p in entry["squad"]}
    cap = [p["name"] for p in entry["squad"] if p["captain"]]
    assert role["F3"] in ("5άδα", "6ος") and role["G1"] == "πάγκος"     # 2 points out, 25 xFPT in
    assert role["F4"] == "πάγκος"                                          # played on the bench: stays there
    assert cap == ["F3"]                                                   # the armband to an unplayed player
    names = {p["id"]: p["name"] for p in entry["squad"]}
    m = entry["moves"]["2"]
    assert [names[i] for i in m["in"]] == ["F3"] and names[m["captain"]] == "F3"
    before = json.dumps(entry)
    autopilot.between_turns(entry, rows, turn=2)                          # nothing left to change
    assert json.dumps(entry) == before


def test_a_rebuilt_seed_replaces_its_rounds_once(pub, monkeypatch):
    """A new seed (e.g. with the T1 -> T2 changes) replaces the rounds it covers, which are scored
    again; later rounds stay. The same seed never resets them again (live changes are kept)."""
    monkeypatch.setattr(autopilot, "actual_points", lambda s: (pd.DataFrame(columns=["round", "gamecode", "person_id", "fp"]), None))
    monkeypatch.setattr(autopilot.history, "load", lambda *a, **k: pd.DataFrame())
    rows, table = pool()
    r1 = {"round": 1, "trades": 0, "bank": 1.0, "x_total": 1.0,
          "squad": [{**{k: r[k] for k in ("id", "price", "position", "name", "team")}, "person_id": f"p{r['id']}",
                     "role": "5άδα", "captain": False, "x_now": 1.0}
                    for r in rows if r["id"] in (1, 2, 3, 4, 9, 10, 11, 12, 17, 18, 21)]}
    old = {**r1, "pts": 115.2, "rank": 214928}
    (pub / "autopilot.json").write_text(json.dumps({"rounds": [old], "start_round": 1}))   # built from an old seed
    (pub.parent / "autopilot_seed.json").write_text(json.dumps({"rounds": [{**r1, "moves": {"2": {"in": [1], "out": [2], "captain": None}}}]}))
    s = autopilot.update(2026, rnd=2, trade_rnd=2, rows=rows, table=table, max_trades=4, min_gain=0.5)
    assert s["rounds"][0].get("pts") is None and "rank" not in s["rounds"][0]      # to be scored again
    assert s["rounds"][0]["moves"] and [e["round"] for e in s["rounds"]] == [1, 2]
    s["rounds"][1]["moves"] = {"2": "live"}                                          # a live change of round 2
    (pub / "autopilot.json").write_text(json.dumps(s))
    s = autopilot.update(2026, rnd=2, trade_rnd=3, rows=rows, table=table, max_trades=4, min_gain=0.5)
    assert s["rounds"][1]["moves"] == {"2": "live"}                                   # same seed: kept


def test_the_seed_lineup_starts_t1_players_and_benches_t2(pub):
    """Round 1 of the seed: the proposed squad, but its lineup by the game's rules: the five from
    T1 players (the best xFPT, >= 1 per position), T2 players wait on the bench."""
    rows, _ = pool()
    first = [1, 2, 3, 4, 9, 10, 11, 12, 17, 18, 21]
    t2 = {3, 4, 12}                                                      # two guards and a forward play T2
    rows = [{**r, "turn": 2 if r["id"] in t2 else 1} for r in rows]
    best = {"cost": 60.0, "team": [{"id": r["id"], "price": r["price"], "position": r["position"], "x_now": r["x_now"],
                                    "role": "5άδα" if r["id"] in t2 else "πάγκος", "captain": r["id"] == 4}
                                   for r in rows if r["id"] in first]}
    pred = {"players": [{**r, "fantasy_id": r["id"], "person_id": f"p{r['id']}"} for r in rows], "best_team": best}
    (r1,) = autopilot.seed_rounds([(1, pred)])
    role = {q["id"]: q["role"] for q in r1["squad"]}
    assert all(role[i] == "πάγκος" for i in t2)                          # T2 players wait
    assert sum(role[i] == "5άδα" for i in first if i not in t2) == 5


def test_update_makes_the_turn_2_changes_then_scores_and_ranks_the_round(pub, monkeypatch):
    """Live flow: round 3 decided; T1 played (its starters flopped) and T2 still to come -> the T2
    changes; then the round is over -> scored with the final roles, ranked, owner's points attached."""
    now = pd.Timestamp.now(tz="UTC")
    rows, table = pool()
    rows = [{**r, "turn": 1 if r["team"] == "AAA" else 2} for r in rows]
    games = pd.DataFrame([
        {"round": 3, "gamecode": 1, "home": "AAA", "away": "X1", "played": True,
         "utc": (now - pd.Timedelta(days=1)).isoformat(), "home_score": 80, "away_score": 70},
        {"round": 3, "gamecode": 2, "home": "BBB", "away": "X2", "played": False,
         "utc": (now + pd.Timedelta(days=1)).isoformat(), "home_score": 0, "away_score": 0}])
    empty = pd.DataFrame(columns=["round", "gamecode", "person_id", "fp"])
    monkeypatch.setattr(autopilot, "actual_points", lambda s: (empty, None))
    monkeypatch.setattr(autopilot.history, "load", lambda *a, **k: games.copy())
    autopilot.update(2026, rnd=3, trade_rnd=3, rows=rows, table=table, max_trades=4, min_gain=0.5)

    # T1 done: every AAA player scored 0, BBB (T2) players still have their xFPT
    live = [{**r, "actual": 0.0 if r["team"] == "AAA" else None} for r in rows]
    s = autopilot.update(2026, rnd=3, trade_rnd=4, rows=live, table=table, max_trades=4, min_gain=0.5)
    r3 = next(e for e in s["rounds"] if e["round"] == 3)
    assert "2" in r3.get("moves", {}) and r3["moves"]["2"]["in"]         # T2 players came in for the flops
    starters = [p for p in r3["squad"] if p["role"] in ("5άδα", "6ος")]
    assert sum(p["captain"] for p in r3["squad"]) == 1 and len(starters) == 6

    # the round is over: scored with the final roles, the owner's points, the rank in the standings
    games.loc[1, ["played", "home_score", "away_score"]] = [True, 75, 70]
    fp = pd.DataFrame([{"round": 3, "gamecode": 1 if p["team"] == "AAA" else 2, "person_id": p["person_id"],
                        "fp": 10.0} for p in r3["squad"] if p["person_id"]])
    monkeypatch.setattr(autopilot, "actual_points", lambda s: (fp, None))
    monkeypatch.setattr(autopilot.fantasy, "rank_of", lambda total, *a: 1234)
    s = autopilot.update(2026, rnd=4, trade_rnd=4, rows=rows, table=table, max_trades=4, min_gain=0.5,
                         my_points={"3": 150.0},
                         overall={"id": 7, "teams": 5000, "matchday_id": 55, "round": 3, "my_total": 150.0})
    r3 = next(e for e in s["rounds"] if e["round"] == 3)
    assert r3["pts"] > 0 and r3["my_pts"] == 150.0 and r3["rank"] == 1234 and r3["my_rank"] == 1234
    assert s["total"]["rounds"] == 1 and s["total"]["pts"] == r3["pts"]


def test_seed_command_writes_the_seed_file(pub, tmp_path, monkeypatch):
    """python -m elf.autopilot seed 1:<predictions> ...: the seed file from saved predictions."""
    rows, _ = pool()
    first = [1, 2, 3, 4, 9, 10, 11, 12, 17, 18, 21]
    best = {"cost": 60.0, "team": [{"id": r["id"], "price": r["price"], "position": r["position"], "x_now": r["x_now"],
                                    "role": "5άδα", "captain": False} for r in rows if r["id"] in first]}
    pred = {"players": [{**r, "fantasy_id": r["id"], "person_id": f"p{r['id']}"} for r in rows], "best_team": best}
    f = tmp_path / "pred.json"
    f.write_text(json.dumps(pred))
    autopilot.main([f"1:{f}", f"1.2:{f}", f"2:{f}"])
    seed = json.loads((pub.parent / "autopilot_seed.json").read_text())
    assert [e["round"] for e in seed["rounds"]] == [1, 2]
