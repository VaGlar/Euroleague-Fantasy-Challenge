"""The whole pipeline (elf.run.build) on the committed history, with every external
API faked: EuroLeague clubs, Dunkest (prices + my team), news, Gemini."""
import json

import pandas as pd
import pytest

from elf import el_api, fantasy, history, news, optimize, run
from elf.config import BUDGET

from conftest import REPO, FakeGame, block_network, seed_public, use_public


def my_squad(prices_df):
    """A legal squad from the price list: mid-priced players, within budget."""
    out = []
    for pos, n in optimize.SQUAD.items():
        g = prices_df[prices_df["position"] == pos].sort_values("price")
        out += g.iloc[len(g) // 3: len(g) // 3 + n].to_dict("records")
    return out


@pytest.fixture(scope="module")
def pipeline(tmp_path_factory):
    """Runs the pipeline once for all tests in this file."""
    with pytest.MonkeyPatch.context() as mp:
        block_network(mp)
        public = use_public(mp, tmp_path_factory.mktemp("pipeline") / "public")
        yield _run(mp, public)


def _run(monkeypatch, public):
    seed_public(public, "prices.csv", "model_params.json", "news.json")
    pr = pd.read_csv(REPO / "data/public/prices.csv", dtype={"person_id": str})
    pr = pr[pr["matchday"] == pr["matchday"].max()]
    raw_players = [{"id": int(r.fantasy_id), "first_name": r.first_name, "last_name": r.last_name,
                    "team": {"abbreviation": r.team}, "position": {"name": r.position},
                    "quotation": float(r.price), "is_injured": bool(r.is_injured),
                    "probability_of_playing": 100} for r in pr.itertuples()]
    squad = [{"id": int(r["fantasy_id"]), "position": r["position"], "price": r["price"],
              "name": r["last_name"], "turn": 1, "x_now": 0} for r in my_squad(pr)]
    court = [p for p in squad if p["position"] != "Head Coach"]
    five = [next(p for p in court if p["position"] == pos) for pos in ("Guard", "Forward", "Center")]
    five += [p for p in court if p not in five][:2]
    roles = {p["id"]: "5άδα" if p in five else "πάγκος" for p in court}
    roles[next(p["id"] for p in court if p not in five)] = "6ος"
    game = FakeGame(squad, roles, captain=five[0]["id"]).install(monkeypatch)
    monkeypatch.setattr(fantasy, "players", lambda *a, **k: raw_players)
    monkeypatch.setattr(el_api, "clubs", lambda season: json.loads(
        (REPO / "data/public/clubs.json").read_text()))
    monkeypatch.setattr(history, "update_season", lambda *a, **k: None)
    monkeypatch.setattr(news, "collect", lambda names, **k: ([], []))

    def digest(arts, roster):  # a Gemini-like answer naming real players
        a, b = roster[0].split(" (")[0], roster[1].split(" (")[0]
        return {"summary_el": "• δοκιμή", "availability": [{"player": a, "status": "out"}],
                "expert": [{"player": b, "stance": "captain", "source": "Test"}]}
    monkeypatch.setattr(news, "digest", digest)
    res = run.build(offline=False)
    if not res:
        pytest.skip("κανένας επόμενος αγώνας στα δεδομένα (εκτός σεζόν)")
    load = lambda n: json.loads((public / n).read_text(),  # noqa: E731
                                parse_constant=lambda c: pytest.fail(f"{c} in {n}"))
    return {"res": res, "pred": load("predictions.json"), "report": load("report.json"),
            "game": game}


def test_outputs_are_valid_and_complete(pipeline):
    pred, rep = pipeline["pred"], pipeline["report"]
    assert pred["fantasy_ok"] is True
    assert len(pred["players"]) > 200 and rep["messages"]
    assert all(m["text"].strip() for m in rep["messages"])
    crash = [h for h in pred["health"] if "βελτιστοποίηση" in h or "Error" in h]
    assert not crash, crash


def test_my_team_lineup_obeys_rules(pipeline):
    lu = pipeline["pred"]["my_team"]["lineup"]
    assert len(lu) == 11
    five = [p for p in lu if p["role"] == "5άδα"]
    assert len(five) == 5 and {p["position"] for p in five} >= {"Guard", "Forward", "Center"}
    assert sum(p["role"] == "6ος" for p in lu) == 1
    cap = [p for p in lu if p["captain"]]
    assert len(cap) == 1 and cap[0]["role"] == "5άδα"
    # starters come from the earliest turn whenever that turn can field a legal lineup
    court = [p for p in lu if p["position"] != "Head Coach" and p.get("turn")]
    first = min(p["turn"] for p in court)
    early = [p for p in court if p["turn"] == first]
    if len(early) >= 6 and {p["position"] for p in early} >= {"Guard", "Forward", "Center"}:
        assert all(p["turn"] == first for p in lu if p["role"] in ("5άδα", "6ος"))


def test_transfers_are_legal(pipeline):
    my = pipeline["pred"]["my_team"]
    assert len(my["transfers"]) <= my["max_trades"]
    assert my["bank_after"] >= -1e-6


def test_best_squad_is_legal(pipeline):
    best = pipeline["pred"]["best_team"]
    counts = {pos: sum(p["position"] == pos for p in best["team"]) for pos in optimize.SQUAD}
    assert counts == optimize.SQUAD and best["cost"] <= BUDGET + 1e-6


def test_news_digest_reaches_the_model(pipeline):
    players = pipeline["pred"]["players"]
    assert any(p.get("expert_cap") for p in players), "η πρόταση της στήλης χάθηκε"


def test_trades_target_next_round_once_the_round_started(pipeline):
    pred, my = pipeline["pred"], pipeline["pred"]["my_team"]
    rnd = pred["round"]
    games = pd.read_csv(REPO / "data/history/games_2026.csv.gz")
    started = bool(games.loc[games["round"] == rnd, "played"].any())
    assert my["trade_round"] == (rnd + 1 if started else rnd)
    expected = 11 if my["trade_round"] == 1 or (my["trade_round"] - 1) in run.UNLIMITED_AFTER else 4
    assert my["max_trades"] == expected
