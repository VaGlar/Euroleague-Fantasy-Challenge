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
                    "probability_of_playing": 100, "popularity": 0.25} for r in pr.itertuples()]
    squad = [{"id": int(r["fantasy_id"]), "position": r["position"], "price": r["price"],
              "name": r["last_name"], "turn": 1, "x_now": 0} for r in my_squad(pr)]
    court = [p for p in squad if p["position"] != "Head Coach"]
    five = [next(p for p in court if p["position"] == pos) for pos in ("Guard", "Forward", "Center")]
    five += [p for p in court if p not in five][:2]
    roles = {p["id"]: "5άδα" if p in five else "πάγκος" for p in court}
    roles[next(p["id"] for p in court if p not in five)] = "6ος"
    game = FakeGame(squad, roles, captain=five[0]["id"]).install(monkeypatch)
    monkeypatch.setattr(fantasy, "players", lambda *a, **k: raw_players)
    monkeypatch.setattr(fantasy, "team_matchday", lambda *a, **k: {"credits": 3.4, "total_plus": 1.2, "trades": 0})
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
            "game": game, "details": load("players.json")}


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
    # preferences go to the dashboard as ids (its own re-plan honours them); never to the public edition
    assert set(my["prefs"]) == {"keep", "avoid"} and all(isinstance(i, int) for i in my["prefs"]["keep"])


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


def test_player_details_for_the_popup(pipeline):
    det, players = pipeline["details"], pipeline["pred"]["players"]
    with_x = [p for p in players if p["x_now"] is not None and p["position"] != "Head Coach"]
    assert all(p["person_id"] in det for p in with_x)
    vez = next(d for pid, d in det.items() if d["stats"] and d["last"])   # someone with history
    assert {"season", "g", "pts", "reb", "ast", "pir", "fg3"} <= set(vez["stats"][0])
    assert 1 <= len(vez["last"]) <= 3 and {"opp", "pir", "fp", "score"} <= set(vez["last"][0])
    season = pipeline["pred"]["season"]
    assert all(g["season"] == season for d in det.values() for g in d["last"]), "όχι περσινά"
    nxt = [d for d in det.values() if d["next"]]
    assert nxt and all(len(d["next"]) <= 3 for d in nxt)
    assert all(0 <= g["win"] <= 100 for d in nxt for g in d["next"])
    assert all({"margin", "pos_dev"} <= set(g) for d in nxt for g in d["next"])
    rounds = [g["round"] for g in nxt[0]["next"]]
    assert rounds == sorted(rounds), "επόμενα με χρονολογική σειρά"


def test_coach_next_games_are_future_and_ordered(pipeline):
    det, players = pipeline["details"], pipeline["pred"]["players"]
    coaches = [p for p in players if p["position"] == "Head Coach" and p["person_id"] in det]
    assert coaches
    for c in coaches:
        nxt = det[c["person_id"]]["next"]
        assert [g["round"] for g in nxt] == sorted(g["round"] for g in nxt)
        assert all(g["date"] for g in nxt), "ο coach χρειάζεται ημερομηνία αγώνα"


def test_teams_tab_data(pipeline):
    pred = pipeline["pred"]
    teams = {t["team"] for t in pred["team_ratings"]}
    assert {t["team"] for t in pred["pos_allowed"]} == teams
    assert all(-1 < t[pos] < 1 for t in pred["pos_allowed"] for pos in ("Guard", "Forward", "Center"))
    assert set(pred["clubs"]) >= teams
    assert all(len(v) <= 5 for v in pred["team_form"].values())
    assert all("played" in f for f in pred["fixtures"])


def test_tracking_written(pipeline):
    pub = run.PUBLIC
    tr = json.loads((pub / "tracking.json").read_text())
    assert {"rounds", "total", "experts", "lineups"} <= set(tr)
    log = pd.read_csv(pub / "pred_log.csv", dtype={"person_id": str})
    assert len(log) and log["x_pred"].notna().all(), "προβλέψεις για αγώνες που δεν έχουν αρχίσει"


def test_public_edition_has_nothing_personal(pipeline, tmp_path):
    from elf import publish
    pub = run.PUBLIC
    assert json.loads((pub / "predictions.json").read_text())["my_team"]["name"] == "TEST"  # personal has it
    written = publish.bundle(tmp_path, src=pub)
    files = {p.name: p.read_text() for p in (tmp_path / "data").iterdir()}
    assert set(files) == set(written)
    assert not {"lineup_log.json", "sent.json", "roster_shape.json", "api_shapes.json", "report_public.json"} & set(files)
    pred = json.loads(files["predictions.json"])
    assert pred["my_team"] is None and pred["health"] == []
    assert all('"TEST"' not in txt for txt in files.values()), "το όνομα της ομάδας διέρρευσε"
    report = json.loads(files["report.json"])
    text = "\n".join(m["text"] for m in report["messages"])
    assert report["messages"] and "Προτεινόμενη πεντάδα" not in text and "Προτεινόμενες αλλαγές" not in text
    assert "⚠️" not in text, "λειτουργικές σημειώσεις (token κ.λπ.) δεν πάνε στο κοινό"
    if "tracking.json" in files:
        assert json.loads(files["tracking.json"])["lineups"] == []


def test_public_site_is_renamed(pipeline, tmp_path):
    from elf import publish
    publish.site(tmp_path, src=run.PUBLIC)
    html = (tmp_path / "index.html").read_text()
    assert "<title>HoopsLab</title>" in html and 'content="HoopsLab"' in html
    assert "EuroLeague Fantasy —" not in html
    assert json.loads((tmp_path / "manifest.json").read_text())["name"] == "HoopsLab"
    assert (tmp_path / "data" / "predictions.json").exists() and (tmp_path / "opt.js").exists()
    assert "EuroLeague Fantasy —" in (publish.ROOT / "web" / "index.html").read_text(), "το προσωπικό μένει ίδιο"


def test_game_credits_gain_and_popularity(pipeline):
    my = pipeline["pred"]["my_team"]
    assert my["bank"] == 3.4 and my["gain"] == 1.2          # from the team's matchday endpoint
    pops = {p.get("popularity") for p in pipeline["pred"]["players"] if p.get("fantasy_id") is not None}
    assert pops == {25.0}                                    # 0-1 from the API -> percent
