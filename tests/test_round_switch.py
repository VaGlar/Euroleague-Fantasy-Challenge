"""19-21/11: the game keeps a finished round as «current» until hours before the next deadline. Our prices,
the owner's credits and the autopilot's rank lagged a round: proposals at the old prices (Thiemann 10.6),
credits 3.2 here and 0.3 in the app, «θέση μετά το R12» after round 13. Now:
- the bot runs an update as soon as the game opens a new round (worker/src/index.js);
- the credits come from the game's own prices of the team (elf/run.py roster_value);
- a finished round is ranked from the game's current matchday, again until the final standings
  (elf/run.py fantasy_results, elf/autopilot.py _rank);
- the page and Telegram say when the prices are still the last round's."""
import pytest
from pathlib import Path

import pandas as pd

from elf import autopilot, run

from test_worker import ENV, data, dispatches, run as run_worker

WEB = Path(__file__).parents[1] / "web"


def fixtures(played13=True):
    return pd.DataFrame([{"round": 13, "played": played13}, {"round": 13, "played": True},
                         {"round": 14, "played": False}])


FS = {"my_points": {"12": 150.0}, "my_points_cur": {"13": 121.0},
      "overall": {"id": 9, "teams": 1000, "matchday_id": 1539, "round": 12, "my_total": 1500.0, "final": True},
      "overall_cur": {"id": 9, "teams": 1000, "matchday_id": 1540, "round": 13, "my_total": 1621.0, "final": False}}


def test_a_finished_round_is_ranked_before_the_game_moves_on():
    pts, ov = run.fantasy_results(FS, fixtures())
    assert ov["round"] == 13 and ov["matchday_id"] == 1540 and ov["final"] is False
    assert pts == {"12": 150.0, "13": 121.0}


def test_a_round_still_under_way_keeps_the_previous_standings():
    pts, ov = run.fantasy_results(FS, fixtures(played13=False))
    assert ov["round"] == 12 and pts == {"12": 150.0}


def test_no_current_standings_keeps_the_previous_ones():
    pts, ov = run.fantasy_results({"my_points": {"12": 1.0}, "overall": FS["overall"]}, fixtures())
    assert ov["round"] == 12 and pts == {"12": 1.0}


def test_a_provisional_rank_is_redone_until_the_final_one(monkeypatch):
    asked = []
    monkeypatch.setattr(autopilot.fantasy, "rank_of", lambda total, *a: asked.append(a[1]) or int(total))
    done = [{"round": 12, "pts": 100.0, "rank": 5, "teams": 1000}, {"round": 13, "pts": 50.0}]
    cur = {**FS["overall_cur"], "my_total": None}                  # the autopilot's rank only
    autopilot._rank(done, cur)                                     # games over, game not moved on
    assert done[1]["rank"] == 150 and done[1]["rank_final"] is False
    autopilot._rank(done, cur)                                     # next run: asked again
    autopilot._rank(done, {**cur, "final": True})                  # the final one
    autopilot._rank(done, {**cur, "final": True})                  # then never again
    assert asked == [1540, 1540, 1540] and done[1]["rank_final"] is True
    assert done[0]["rank"] == 5                                    # an earlier round is left alone


def test_the_credits_come_from_the_games_own_prices():
    raw = {"players": [{"id": i, "quotation": q} for i, q in enumerate([19.2, 15.0, 13.1, 11.0, 10.0, 7.7, 8.3,
                                                                         6.3, 6.1, 5.9, 6.0])]}
    assert run.roster_value(raw) == 108.6                           # 108.9 credits -> 0.3 left, as the app shows
    assert run.roster_value({"players": raw["players"][:10]}) is None   # not the whole team: ours are used
    assert run.roster_value({"players": [{**p, "quotation": None} for p in raw["players"]]}) is None
    assert run.roster_value(None) is None


def test_the_page_says_when_the_prices_are_the_last_rounds():
    js = (WEB / "team.js").read_text()
    assert "staleNote(pl.ti)" in js and "P.prices_round" in js


NOW = "2026-10-01T12:05:00Z"          # 15:05 in Athens: no scheduled update this hour
OLD = "2026-10-01T09:00:00Z"


def bot(**kw):
    d = data()
    d["predictions.json"] = {**d["predictions.json"], "generated": kw.pop("generated", OLD), "prices_round": 13}
    return run_worker({"now": kw.pop("now", NOW), "env": ENV, "data": d, **kw})[0]


def test_the_bot_updates_when_the_game_opens_a_new_round():
    res = bot(game={"current_matchday": {"number": 14}})
    assert res["error"] is None and dispatches(res) == [("update.yml", {})]


def test_the_bot_waits_while_the_game_is_on_the_same_round():
    assert dispatches(bot(game={"current_matchday": {"number": 13}})) == []


def test_not_again_right_after_an_update():
    assert dispatches(bot(game={"current_matchday": {"number": 14}}, generated="2026-10-01T11:40:00Z")) == []


def test_a_game_that_doesnt_answer_changes_nothing():
    res = bot(game=None)
    assert res["error"] is None and dispatches(res) == []


def test_one_update_an_hour_even_when_two_reasons_meet():
    # 07:05 in Athens: the scheduled update; the new round asks for one too
    res = bot(game={"current_matchday": {"number": 14}}, now="2026-10-01T04:05:00Z", generated="2026-09-30T20:00:00Z")
    assert dispatches(res).count(("update.yml", {})) == 1


def test_the_update_says_which_rounds_prices_and_counts_the_games_credits(tmp_path_factory):
    import test_pipeline as tp
    with pytest.MonkeyPatch.context() as mp:
        tp.block_network(mp)
        public = tp.use_public(mp, tmp_path_factory.mktemp("switch") / "public")
        out = tp._run(mp, public)
    pred = out["pred"]
    assert isinstance(pred["prices_round"], (int, float))
    assert pred["my_team"]["prices_round"] == pred["prices_round"]
