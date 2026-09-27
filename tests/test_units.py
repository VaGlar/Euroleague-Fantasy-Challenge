"""Small pure functions across the pipeline."""
import base64
import json
import time

import numpy as np
import pandas as pd
import pytest

from elf import fantasy, model, news, prices, run


# ------------------------------------------------------------------ model

def test_win_prob_and_bonus():
    assert model.win_prob(0) == pytest.approx(0.5)
    assert model.win_prob(10) > model.win_prob(0) > model.win_prob(-10)
    x = model.fantasy_points(pd.Series([10.0, 10.0]), pd.Series([30.0, -30.0]))
    assert 10.9 < x[0] <= 11.0 and 10.0 <= x[1] < 10.1     # +10% only for a win


def test_coach_points_monotone_and_bounded():
    vals = [model.coach_points(m) for m in range(-40, 41, 5)]
    assert all(b >= a for a, b in zip(vals, vals[1:]))
    assert -20 <= min(vals) and max(vals) <= 25


# --------------------------------------------------------------- horizon

@pytest.mark.parametrize("rnd,expected", [
    (1, [1.0, 0.6, 0.35]), (4, [1.0, 0.6, 0.35]), (5, [1.0, 0.6, 0.0]),
    (6, [1.0, 0.0, 0.0]), (7, [1.0, 0.6, 0.35]), (12, [1.0, 0.6, 0.0]),
    (13, [1.0, 0.0, 0.0]), (34, [1.0, 0.0, 0.0])])
def test_horizon_weights(rnd, expected):
    assert run.horizon_weights(rnd) == expected


# ---------------------------------------------------------------- fantasy

def test_normalize_player():
    p = fantasy.normalize_player({"id": 7, "first_name": "A", "last_name": "B",
                                  "team": {"abbreviation": "PAN"}, "position": {"name": "Guard"},
                                  "quotation": 12.5, "is_injured": True,
                                  "probability_of_playing": 50})
    assert (p["fantasy_id"], p["team"], p["position"], p["price"]) == (7, "PAN", "Guard", 12.5)
    assert p["is_injured"] is True and p["prob_play"] == 0.5


@pytest.mark.parametrize("v,out", [(100, 1.0), (50, 0.5), (0.8, 0.8), (None, None),
                                   ("x", None), (250, 1.0)])
def test_prob(v, out):
    assert fantasy._prob(v) == out


def test_availability_handles_nan_from_pandas():
    assert fantasy.availability({"prob_play": np.nan, "is_injured": True}) == 0.0
    assert fantasy.availability({"prob_play": np.nan, "is_injured": False}) == 1.0
    assert fantasy.availability({"prob_play": 0.4, "is_injured": True}) == 0.4


def test_token_expiry(monkeypatch):
    monkeypatch.delenv("FANTASY_TOKEN", raising=False)
    assert fantasy.token_expiry()["kind"] == "missing"
    monkeypatch.setenv("FANTASY_TOKEN", "opaque-token")
    assert fantasy.token_expiry() == {"kind": "opaque", "days_left": None}
    body = base64.urlsafe_b64encode(json.dumps({"exp": time.time() + 2 * 86400}).encode())
    monkeypatch.setenv("FANTASY_TOKEN", f"h.{body.decode().rstrip('=')}.s")
    t = fantasy.token_expiry()
    assert t["kind"] == "jwt" and 1.9 < t["days_left"] <= 2.0


def test_formations_found_in_another_game(monkeypatch):
    games = {7: [{"name": "2-2-1", "id": 1}], 3: [{"name": "2-2-1", "id": 27},
                                                  {"name": "3-1-1", "id": 31}]}
    monkeypatch.setattr(fantasy, "get", lambda path, auth=True: {
        "formations": games.get(int(path.split("/")[2]), [])})
    assert fantasy.formations(27) == {"2-2-1": 27, "3-1-1": 31}
    assert fantasy.formations(None) == {"2-2-1": 1}


def test_fantasy_get_without_token_raises(monkeypatch):
    monkeypatch.delenv("FANTASY_TOKEN", raising=False)
    with pytest.raises(fantasy.TokenError):
        fantasy.get("/user/fantasy-teams")


# ------------------------------------------------------------------- news

def test_normalize_llm_output():
    d = news._normalize({"summary_el": ["- α", "β", ""], "availability": [
        {"player": "X", "status": "out"}, {"status": "out"}, "junk"], "expert": None})
    assert d["summary_el"] == "• α\n• β"
    assert d["availability"] == [{"player": "X", "status": "out"}]
    assert d["expert"] == []
    assert news._normalize(None) == {"summary_el": "", "availability": [], "expert": []}


def test_flash_models_skip_previews_and_interleave_lite(monkeypatch):
    names = ["gemini-2.5-flash", "gemini-2.5-flash-lite", "gemini-3-flash-preview",
             "gemini-2.0-flash", "gemini-2.0-flash-lite", "gemini-omni-flash", "gemini-2.5-pro"]

    class R:
        status_code = 200

        def json(self):
            return {"models": [{"name": f"models/{n}",
                                "supportedGenerationMethods": ["generateContent"]} for n in names]}
    monkeypatch.setattr(news.requests, "get", lambda *a, **k: R())
    assert news._flash_models("u", {}) == ["gemini-2.5-flash", "gemini-2.5-flash-lite",
                                           "gemini-2.0-flash", "gemini-2.0-flash-lite"]


# ------------------------------------------------------------------ prices

def test_price_proxy_flags_cheap_overperformers(public):
    rng = np.random.default_rng(0)
    price = rng.uniform(4, 17, 60)
    t = pd.DataFrame({"price": price, "x_now": price * 1.1, "position": "Guard",
                      "avail_game": 1.0, "no_data": False})
    t.loc[0, ["price", "x_now"]] = [5.0, 14.0]          # cheap and scoring big
    t.loc[1, ["price", "x_now", "avail_game"]] = [5.0, 14.0, 0.0]   # same, but injured
    t.loc[2, ["price", "x_now", "position"]] = [5.0, 14.0, "Head Coach"]
    t.loc[3, ["price", "x_now"]] = [16.0, 5.0]          # expensive, scoring little
    out, info = prices.annotate(t)
    assert info["method"] == "proxy"
    assert out.loc[0, "price_trend"] == "up"
    assert out.loc[1, "price_trend"] != "up" and out.loc[2, "price_trend"] is None
    assert out.loc[3, "price_trend"] == "down"
    assert (out["price_trend"] == "up").sum() <= 3


def test_price_model_needs_two_matchdays(public):
    pd.DataFrame({"fantasy_id": [1], "person_id": ["1"], "price": [5.0],
                  "matchday": [1]}).to_csv(public / "prices.csv", index=False)
    assert prices.fit_price_model() is None


# --------------------------------------------------------------------- run

def test_clean_and_write_never_emit_nan(public):
    obj = {"a": float("nan"), "b": [np.float64("inf"), np.int64(3), np.bool_(True)],
           "c": {"d": np.float32(1.5)}}
    run._write("x.json", obj)
    back = json.loads((public / "x.json").read_text(),
                      parse_constant=lambda c: pytest.fail(f"{c} in JSON"))
    assert back == {"a": None, "b": [None, 3, True], "c": {"d": 1.5}}


def test_key_strips_accents_and_case():
    assert run._key("Dončić, Luka") == run._key("DONCIC LUKA")


def test_parse_my_roster_and_actual_lineup():
    raw = {"formation_id": 27, "credits": 1.5, "players": [
        {"id": i, "court_position": i, "is_captain": i == 3, "last_name": f"P{i}",
         "position": {"name": "Head Coach" if i == 11 else "Guard"},
         "match_played": i == 1, "pts": 12 if i == 1 else 0, "round": {"number": 1 + (i > 5)}}
        for i in range(1, 12)]}
    ids, meta = run.parse_my_roster(raw)
    assert ids == list(range(1, 12)) and meta == {"bank": 1.5, "captain": 3}
    lu = {r["fantasy_id"]: r for r in run.actual_lineup(raw)}
    assert [lu[i]["role"] for i in (1, 5, 6, 7, 11)] == ["5άδα", "5άδα", "6ος", "πάγκος", "coach"]
    assert lu[3]["captain"] and lu[1]["played"] and lu[6]["turn"] == 2


def test_expert_votes_and_capped_factor():
    dig = {"expert": [{"player": "Vezenkov (OLY)", "stance": "captain", "source": "A"},
                      {"player": "Vezenkov", "stance": "pick", "source": "B"},
                      {"player": "Vezenkov", "stance": "pick", "source": "C"},
                      {"player": "Nunn", "stance": "avoid", "source": "A"},
                      {"player": "X", "stance": "maybe", "source": "A"}]}
    v = run.expert_votes(dig)
    assert set(v) == {run._key("Vezenkov"), run._key("Nunn")}
    f_pick = run.expert_factor(v[run._key("Vezenkov")])
    f_avoid = run.expert_factor(v[run._key("Nunn")])
    lo, hi = run.EXPERT_CAP
    assert 1 < f_pick <= hi and lo <= f_avoid < 1
    assert run.expert_factor(None) == 1.0


def test_pair_trades_matches_positions():
    mk = lambda i, pos, price, x: {"id": i, "label": f"P{i}", "position": pos,  # noqa: E731
                                   "price": price, "x_h": x}
    tr = {"out": [mk(1, "Center", 5, 3), mk(2, "Guard", 6, 4)],
          "in": [mk(3, "Guard", 8, 10), mk(4, "Center", 4, 6)]}
    pairs = {(p["out"], p["in"]) for p in run._pair_trades(tr)}
    assert pairs == {("P2", "P3"), ("P1", "P4")}


def test_turns_split_by_athens_day():
    utc = pd.to_datetime(["2026-09-24 16:00", "2026-09-24 18:30", "2026-09-25 17:00"], utc=True)
    fx = pd.DataFrame({"round": 1, "utc": utc, "home": ["A", "C", "E"], "away": ["B", "D", "F"],
                       "played": [True, True, False]})
    t = run.turns(fx, 1)
    assert [x["turn"] for x in t] == [1, 2]
    assert t[0]["teams"] == ["A", "B", "C", "D"] and t[0]["done"] and not t[1]["done"]


def test_turn2_message_follows_the_game_rules():
    from conftest import squad_t1_t2
    sq = squad_t1_t2()
    pts = {1: 30, 2: 2, 5: 25, 6: 3, 7: 1, 9: 0}
    roles = {1: "5άδα", 2: "5άδα", 5: "5άδα", 6: "5άδα", 9: "5άδα", 4: "6ος",
             3: "πάγκος", 7: "πάγκος", 8: "πάγκος", 10: "πάγκος", 11: "coach"}
    players = [{"fantasy_id": p["id"], "position": p["position"], "name": f"P{p['id']}, X",
                "team": "T2" if p["turn"] == 2 else "T1", "x_now": p["x_now"]} for p in sq]
    actual = [{"fantasy_id": p["id"], "role": roles[p["id"]], "captain": p["id"] == 1,
               "played": p["id"] in pts, "pts": pts.get(p["id"]), "turn": p["turn"]} for p in sq]
    lines = run.turn_check({"turn": 2, "teams": ["T2"]}, pd.DataFrame(players),
                           {"players": players, "actual_lineup": actual})
    text = "\n".join(lines)
    swap = next(line for line in lines if "μπαίνει" in line)
    assert all(f"P{i} " in swap.split("βγαίνει")[0] for i in (3, 8, 10))   # T2 players in
    assert all(f"P{i} " in swap.split("βγαίνει")[1] for i in (2, 6, 9))    # T1 flops out
    assert "P7 " not in swap, "όποιος έπαιξε από τον πάγκο μένει εκεί"
    assert "👉" not in text, "ο αρχηγός έφερε 30: μένει"


def test_data_token_used_for_market_reads_only(monkeypatch):
    monkeypatch.setenv("FANTASY_TOKEN", "personal")
    monkeypatch.delenv("FANTASY_DATA_TOKEN", raising=False)
    assert fantasy._token() == "personal" and fantasy._token(data=True) == "personal"  # fallback
    monkeypatch.setenv("FANTASY_DATA_TOKEN", "data-account")
    assert fantasy._token() == "personal", "η ομάδα μου / το /lineup μένουν στον προσωπικό λογαριασμό"
    assert fantasy._token(data=True) == "data-account"
    seen = {}

    class R:
        status_code = 200

        def raise_for_status(self):
            pass

        def json(self):
            return {"data": []}
    monkeypatch.setattr(fantasy.requests, "get",
                        lambda url, params=None, headers=None, timeout=None: seen.update(h=headers) or R())
    fantasy.players(1, 2)
    assert seen["h"]["Authorization"] == "Bearer data-account"


def test_standings_wins_then_point_difference(monkeypatch):
    import pandas as pd
    from elf import run
    games = pd.DataFrame([
        {"phase": "RS", "played": True, "home": "A", "away": "B", "home_score": 90, "away_score": 70},
        {"phase": "RS", "played": True, "home": "C", "away": "D", "home_score": 80, "away_score": 78},
        {"phase": "RS", "played": True, "home": "B", "away": "C", "home_score": 85, "away_score": 60},
        {"phase": "RS", "played": False, "home": "A", "away": "C", "home_score": None, "away_score": None},
        {"phase": "PO", "played": True, "home": "D", "away": "A", "home_score": 99, "away_score": 50},
    ])
    monkeypatch.setattr(run.history, "load", lambda kind, season: games)
    table = run.standings(2026, ["A", "B", "C", "D", "E"])
    # A 1-0; B and C 1-1 split by difference (+5 vs -23); E 0-0 before D 0-1; play-offs and unplayed ignored
    assert [r["team"] for r in table] == ["A", "B", "C", "E", "D"]
    b = next(r for r in table if r["team"] == "B")
    assert (b["gp"], b["w"], b["l"], b["diff"]) == (2, 1, 1, 5)
    e = table[3]
    assert (e["team"], e["gp"], e["pos"]) == ("E", 0, 4)
