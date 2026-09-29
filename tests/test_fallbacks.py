"""The fallback paths: they only run when something already went wrong, so nobody sees them
break until the day they are needed. Gemini overloaded -> the previous digest; the optimizer
failing -> the greedy trades; the fantasy API down -> my_team.yaml; the round under way ->
points already scored and a lineup that follows the in-round rules."""
import json
from datetime import datetime, timedelta, timezone

import pandas as pd
import pytest

from elf import history, optimize, run
from elf.config import COACH_POINTS

from conftest import block_network, use_public
from test_pipeline import _run

NOW = datetime.now(timezone.utc)
PREV = {"summary_el": "• προηγούμενη σύνοψη", "availability": [], "expert": []}


# ------------------------------------------------------------------ previous digest

def write_news(public, digest=PREV, at=None):
    (public / "news.json").write_text(json.dumps(
        {"digest": digest, "digest_at": at if at is not None else (NOW - timedelta(hours=2)).isoformat()}))


def test_previous_digest_is_kept_while_recent(public):
    write_news(public)
    dig, at = run.previous_digest()
    assert dig == PREV and at


@pytest.mark.parametrize("case", ["old", "no_digest", "naive_time", "garbage_time", "missing"])
def test_previous_digest_gives_up_cleanly(public, case):
    if case == "old":
        write_news(public, at=(NOW - timedelta(hours=40)).isoformat())
    elif case == "no_digest":
        write_news(public, digest=None)
    elif case == "naive_time":
        write_news(public, at="2026-09-29T08:00:00")
    elif case == "garbage_time":
        write_news(public, at="χθες")
    assert run.previous_digest() == (None, None)


# ------------------------------------------------------------------ points so far

def test_actual_points_win_bonus_coach_margin_and_not_yet_played(monkeypatch):
    fx = pd.DataFrame([
        {"round": 3, "played": True, "gamecode": 1, "home": "PAN", "away": "OLY",
         "home_score": 90, "away_score": 78},                      # PAN +12, OLY -12
        {"round": 3, "played": False, "gamecode": 2, "home": "MAD", "away": "BAR",
         "home_score": None, "away_score": None},
        {"round": 2, "played": True, "gamecode": 9, "home": "MAD", "away": "PAN",
         "home_score": 99, "away_score": 60},                      # another round: ignored
    ])
    box = pd.DataFrame({"gamecode": [1, 1, 9], "person_id": ["001", "002", "003"],
                        "pir": [20, 10, 50]})
    monkeypatch.setattr(history, "load", lambda kind, season: box)
    table = pd.DataFrame([
        {"team": "PAN", "position": "Guard", "person_id": "001"},        # won: +10%
        {"team": "OLY", "position": "Center", "person_id": "002"},       # lost
        {"team": "PAN", "position": "Head Coach", "person_id": None},    # +12 -> 20
        {"team": "OLY", "position": "Head Coach", "person_id": None},    # -12 -> -10
        {"team": "MAD", "position": "Forward", "person_id": "003"},      # not played yet
        {"team": "PAN", "position": "Forward", "person_id": "999"},      # not in the box score
    ])
    pts = run.actual_points(fx, 3, table).tolist()
    assert pts[:4] == [pytest.approx(22.0), 10, 20, -10]
    assert pd.isna(pts[4]) and pd.isna(pts[5])


def test_actual_points_before_any_game_is_all_nan():
    fx = pd.DataFrame([{"round": 3, "played": False, "gamecode": 1, "home": "A", "away": "B",
                        "home_score": None, "away_score": None}])
    table = pd.DataFrame([{"team": "A", "position": "Guard", "person_id": "1"}])
    assert run.actual_points(fx, 3, table).isna().all()


@pytest.mark.parametrize("margin", [-60, -21, -20, -11, -1, 1, 10, 11, 20, 21, 60])
def test_coach_points_cover_every_margin(margin):
    assert sum(lo < margin <= hi for lo, hi, _ in COACH_POINTS) == 1


# ------------------------------------------------------------------ my_team.yaml

def test_manual_team_matches_surname_team_and_accents(tmp_path, monkeypatch):
    (tmp_path / "my_team.yaml").write_text(
        "name: Χειροκίνητη\nplayers:\n  - Sloukas (PAN)\n  - Papapetrou (OLY)\n  - Nobody (XXX)\n  - Doncic\n")
    monkeypatch.setattr(run, "ROOT", tmp_path)
    table = pd.DataFrame([
        {"name": "SLOUKAS, KOSTAS", "team": "PAN", "x_now": 10.0, "price": float("nan")},
        {"name": "PAPAPETROU, IOANNIS", "team": "PAN", "x_now": 12.0},   # wrong team
        {"name": "PAPAPETROU, IOANNIS", "team": "OLY", "x_now": 11.0},
        {"name": "DONČIĆ, LUKA", "team": "RMB", "x_now": 30.0},
    ])
    my = run.manual_team(table)
    assert my["manual"] and my["name"] == "Χειροκίνητη" and my["parsed_players"] == 3
    assert [(p["name"], p["team"]) for p in my["players"]] == [
        ("DONČIĆ, LUKA", "RMB"), ("PAPAPETROU, IOANNIS", "OLY"), ("SLOUKAS, KOSTAS", "PAN")]
    assert my["players"][2]["price"] is None, "NaN -> None, το JSON μένει έγκυρο"
    assert my["transfers"] == [] and my["bank"] is None


def test_manual_team_without_file_or_players(tmp_path, monkeypatch):
    monkeypatch.setattr(run, "ROOT", tmp_path)
    table = pd.DataFrame([{"name": "A, B", "team": "PAN", "x_now": 1.0}])
    assert run.manual_team(table) is None
    (tmp_path / "my_team.yaml").write_text("")
    assert run.manual_team(table)["players"] == []


# ------------------------------------------------------------------ greedy trades

def squad_df(rows):
    return pd.DataFrame([{"fantasy_id": i, "position": pos, "price": price, "x_h": x,
                          "label": f"P{i}"} for i, pos, price, x in rows])


def test_greedy_trades_same_position_within_budget_and_limits():
    team = squad_df([(1, "Guard", 10.0, 10.0), (2, "Center", 8.0, 30.0)])
    pool = squad_df([(1, "Guard", 10.0, 10.0), (2, "Center", 8.0, 30.0),
                     (3, "Guard", 13.0, 40.0),     # best, but 3 over the budget with bank 2
                     (4, "Guard", 11.5, 25.0),     # affordable: +15
                     (5, "Forward", 5.0, 99.0)])   # other position
    moves = run.suggest_transfers(team, pool, bank=2.0)
    assert [(m["out"], m["in"]) for m in moves] == [("P1", "P4")]
    assert moves[0]["gain"] == 15.0 and moves[0]["bank_after"] == pytest.approx(0.5)
    assert run.suggest_transfers(team, pool, bank=2.0, min_gain=20) == []
    assert len(run.suggest_transfers(team, pool, bank=10.0, max_trades=1)) == 1


# ------------------------------------------------------------------ the whole bad day

@pytest.fixture(scope="module")
def bad_day(tmp_path_factory):
    """Gemini down, the optimizer failing, and the sixth man and the bench already played."""
    with pytest.MonkeyPatch.context() as mp:
        block_network(mp)
        public = use_public(mp, tmp_path_factory.mktemp("bad_day") / "public")

        def gemini_down(arts, roster):
            # the last good digest, as the previous run left it (written here because the
            # runner seeds an older news.json first)
            write_news(public)
            raise RuntimeError("Gemini υπερφορτωμένο (m1) — δοκίμασε /update αργότερα")

        def broken(*a, **k):
            raise RuntimeError("solver crashed")
        mp.setattr(optimize, "transfers", broken)
        played = {}

        def sixth_and_bench_played(squad):
            # the runner's five: the first G, F and C, then the next two; then the sixth and
            # the bench. With all of those already played, a turn-blind proposal would pull
            # one of them into the five, which the game forbids.
            court = [p for p in squad if p["position"] != "Head Coach"]
            five = [next(p for p in court if p["position"] == pos)
                    for pos in ("Guard", "Forward", "Center")]
            five += [p for p in court if p not in five][:2]
            rest = [p for p in court if p not in five]
            played.update({p["id"]: 25 + i for i, p in enumerate(rest)})
            return dict(played)
        res = _run(mp, public, digest=gemini_down, played=sixth_and_bench_played)
        res["played"] = played
        yield res


def test_bad_day_keeps_the_previous_digest(bad_day):
    pred, rep = bad_day["pred"], bad_day["report"]
    assert any("υπερφορτωμένο" in h and "προηγούμενη σύνοψη" in h for h in pred["health"])
    turn1 = [m for m in rep["messages"] if m["turn"] == 1]
    assert all("προηγούμενη σύνοψη" in m["text"] for m in turn1)


def test_bad_day_falls_back_to_greedy_trades(bad_day):
    my = bad_day["pred"]["my_team"]
    assert any(h.startswith("βελτιστοποίηση ομάδας: RuntimeError") for h in bad_day["pred"]["health"])
    for t in my["transfers"]:
        assert t["bank_after"] >= 0 and t["price_in"] <= t["price_out"] + my["bank"] + 1e-9
    assert len(my["transfers"]) <= 4


def test_bad_day_lineup_follows_in_round_rules(bad_day):
    my, played = bad_day["pred"]["my_team"], bad_day["played"]
    real = {r["fantasy_id"]: r for r in my["actual_lineup"]}
    assert {i for i, r in real.items() if r["played"]} == set(played)
    lu = {p["id"]: p for p in my["lineup"]}
    assert my["lineup_plan"] == []
    for pid in played:
        was, now = real[pid]["role"], lu[pid]["role"]
        assert now == was or now == "πάγκος", f"{pid}: {was} -> {now}"
    cap = next(p for p in my["lineup"] if p["captain"])
    assert cap["id"] not in played or real[cap["id"]]["captain"], \
        "το x2 μόνο σε όποιον δεν έχει παίξει (ή ήταν ήδη αρχηγός)"
