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
    assert r3b == r3                                              # untouched
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
    (pub / "autopilot.json").write_text(json.dumps({"rounds": [{"round": 3, "pts": 150.0, "my_pts": 170.0}]}))
    publish.bundle(tmp_path / "site", src=pub)
    out = json.loads((tmp_path / "site" / "data" / "autopilot.json").read_text())
    assert out["rounds"] == [{"round": 3, "pts": 150.0}]
