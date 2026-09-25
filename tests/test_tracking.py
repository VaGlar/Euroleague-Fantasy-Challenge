"""This-season tracking: predictions frozen at tip-off, graded against box scores."""
import json
from datetime import datetime, timedelta, timezone

import pandas as pd
import pytest

from elf import history, tracking

NOW = datetime(2026, 10, 1, 12, tzinfo=timezone.utc)


def ctx_rows(x, when):
    return pd.DataFrame({
        "round": [2, 2, 2], "gamecode": [11, 11, 12], "person_id": ["A", "B", "C"],
        "name": ["A", "B", "C"], "team": ["T1", "T2", "T3"], "position": ["Guard"] * 3,
        "utc": [when] * 3, "xpir": x, "season_pir": [10.0, None, 8.0], "prev_pir": [12.0, 6.0, 7.0]})


@pytest.fixture
def pub(public):
    return public


def test_predictions_freeze_at_tipoff(pub):
    tracking.log_predictions(ctx_rows([20.0, 10.0, 8.0], NOW + timedelta(hours=5)), now=NOW)
    # later run: game 11 started (no longer logged), game 12 still future -> updated
    later = NOW + timedelta(hours=6)
    c = ctx_rows([99.0, 99.0, 9.5], NOW + timedelta(hours=5))
    c.loc[c["gamecode"] == 12, "utc"] = NOW + timedelta(hours=8)
    tracking.log_predictions(c, now=later)
    log = pd.read_csv(pub / "pred_log.csv", dtype={"person_id": str}).set_index("person_id")
    assert log.loc["A", "x_pred"] == 20.0 and log.loc["B", "x_pred"] == 10.0, "πάγωσε στο τζάμπολ"
    assert log.loc["C", "x_pred"] == 9.5
    assert log.loc["B", "naive"] == pytest.approx(6.0 * 1.05), "χωρίς φετινό -> περσινό"


def test_evaluate_grades_against_box_scores(pub, monkeypatch):
    pd.DataFrame({"round": [2] * 4, "gamecode": [11, 11, 11, 11], "person_id": ["A", "B", "C", "D"],
                  "name": list("ABCD"), "team": ["H", "H", "V", "V"], "x_pred": [20.0, 10.0, 8.0, 2.0],
                  "naive": [15.0, 10.0, 8.0, 2.0], "logged_at": "x"}).to_csv(pub / "pred_log.csv", index=False)
    games = pd.DataFrame({"gamecode": [11], "round": [2], "played": [True], "home": ["H"], "away": ["V"],
                          "home_score": [90], "away_score": [80], "utc": ["2026-10-01T18:00:00Z"]})
    box = pd.DataFrame({"gamecode": [11, 11], "team": ["H", "V"], "person_id": ["A", "C"], "pir": [20, 4]})
    monkeypatch.setattr(history, "load", lambda kind, season: games if kind == "games" else box)
    res = tracking.evaluate(2026)
    r, = res["rounds"]
    # A: 20*1.1=22 (win), B: DNP -> 0, C: 4 (loss); D below MIN_XPRED is not graded
    assert r["n"] == 3
    assert r["mae_model"] == pytest.approx((2 + 10 + 4) / 3, abs=0.01)
    assert r["mae_naive"] == pytest.approx((7 + 10 + 4) / 3, abs=0.01)
    assert res["total"]["n"] == 3


def test_lineup_scores_use_real_points(pub, monkeypatch):
    games = pd.DataFrame({"gamecode": [11], "round": [2], "played": [True], "home": ["H"], "away": ["V"],
                          "home_score": [90], "away_score": [75], "utc": ["2026-10-01T18:00:00Z"]})
    box = pd.DataFrame({"gamecode": [11, 11], "team": ["H", "H"], "person_id": ["A", "B"], "pir": [10, 20]})
    monkeypatch.setattr(history, "load", lambda kind, season: games if kind == "games" else box)
    mk = lambda pid, role, cap=False, pos="Guard": {"id": 1, "person_id": pid, "team": "H",  # noqa: E731
                                                     "position": pos, "role": role, "captain": cap}
    (pub / "lineup_log.json").write_text(json.dumps({"2": {
        "suggested": [mk("A", "5άδα", True), mk("B", "πάγκος"), mk("K", "coach", pos="Head Coach")],
        "actual": [mk("B", "5άδα", True), mk("A", "πάγκος"), mk("K", "coach", pos="Head Coach")]}}))
    lu, = tracking.evaluate(2026)["lineups"]
    # suggested: A 11*2 + B 22*0.5 + coach (+15 -> 20) = 53 ; actual: B 22*2 + A 11*0.5 + 20 = 69.5
    assert (lu["suggested"], lu["actual"], lu["diff"]) == (53.0, 69.5, 16.5)


def test_experts_graded_only_for_finished_rounds(pub, monkeypatch):
    games = pd.DataFrame({"gamecode": [11, 12], "round": [2, 2], "played": [True, False], "home": ["H", "X"],
                          "away": ["V", "Y"], "home_score": [90, 0], "away_score": [80, 0], "utc": ["x", "y"]})
    box = pd.DataFrame({"gamecode": [11], "team": ["H"], "person_id": ["A"], "pir": [20]})
    monkeypatch.setattr(history, "load", lambda kind, season: games if kind == "games" else box)
    pd.DataFrame({"round": [2], "source": ["S"], "stance": ["pick"], "person_id": ["A"], "name": ["A"],
                  "team": ["H"], "model_xpts": [15.0]}).to_csv(pub / "expert_log.csv", index=False)
    assert tracking.evaluate(2026)["experts"] == [], "η αγωνιστική δεν έχει τελειώσει"
    games.loc[1, "played"] = True
    ex, = tracking.evaluate(2026)["experts"]
    assert (ex["actual"], ex["model"], ex["diff"]) == (22.0, 15.0, 7.0)
