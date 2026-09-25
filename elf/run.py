"""Daily pipeline: data -> predictions -> fantasy team advice -> report JSON.

python -m elf.run            full update (what CI runs)
python -m elf.run --offline  skip network except what is cached (debug)
"""
from __future__ import annotations

import argparse
import json
import os
import unicodedata
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import yaml

from . import el_api, fantasy, history, model, news, optimize, prices
from .config import BUDGET, COACH_POINTS, CURRENT_SEASON, PUBLIC, ROOT, TIMEZONE, WIN_BONUS

ATH = ZoneInfo(TIMEZONE)
HORIZON = 3  # rounds used for transfer value
# weight of each round in x_h: later rounds are less certain and can still be fixed
# with the next rounds' trades, so the next round counts as much as the other two
HORIZON_WEIGHTS = (1.0, 0.6, 0.35)
UNLIMITED_AFTER = {6, 13, 18, 23, 28, 34}  # trades unlimited before the next round
MIN_GAIN_PER_TRADE = 2.0  # weighted xPTS a trade must add over the full 3-round horizon


def horizon_weights(rnd: int) -> list[float]:
    """Weights of rounds rnd, rnd+1, ... in x_h. A squad only lasts until the next
    unlimited-trades window (after rounds in UNLIMITED_AFTER the whole team can be
    rebuilt), so rounds after that window count 0: in round 5 only rounds 5-6 count,
    in round 6 only round 6."""
    end = min((r for r in UNLIMITED_AFTER if r >= rnd), default=10 ** 6)
    return [w if rnd + k <= end else 0.0 for k, w in enumerate(HORIZON_WEIGHTS)]
DAYS_EL = ["Δευτέρα", "Τρίτη", "Τετάρτη", "Πέμπτη", "Παρασκευή", "Σάββατο", "Κυριακή"]


def _key(s: str) -> str:
    s = unicodedata.normalize("NFD", str(s).lower())
    return "".join(c for c in s if c.isalnum() and unicodedata.category(c) != "Mn")


def _clean(o):
    """NaN/inf -> None recursively: browsers reject NaN in JSON."""
    if isinstance(o, float) and not np.isfinite(o):
        return None
    if isinstance(o, dict):
        return {k: _clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_clean(v) for v in o]
    if isinstance(o, (np.floating,)):
        return _clean(float(o))
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.bool_,)):
        return bool(o)
    return o


def _write(name: str, obj) -> None:
    PUBLIC.mkdir(parents=True, exist_ok=True)
    (PUBLIC / name).write_text(json.dumps(_clean(obj), ensure_ascii=False, indent=1,
                                          default=str, allow_nan=False))


# ------------------------------------------------------------ predictions

def predictions(season: int, extra: pd.DataFrame | None = None):
    games = history.load("games", season)
    games["utc"] = pd.to_datetime(games["utc"], utc=True)
    cur_p, cur_t = history.load("players", season), history.load("teams", season)
    prev_p, prev_t = history.load("players", season - 1), history.load("teams", season - 1)
    people = history.load("people", season)
    roster = people[(people["type"] == "player") & people["active"]] \
        .rename(columns={"club": "team"})[["person_id", "name", "team", "position"]]
    if extra is not None and len(extra):  # fantasy players missing from EuroLeague rosters
        roster = pd.concat([roster, extra[~extra["person_id"].isin(roster["person_id"])]],
                           ignore_index=True)

    p = model.params()
    codes = sorted(set(games["home"]) | set(games["away"]))
    ratings = model.team_ratings(cur_t, prev_t, codes, p)
    pos_map = dict(zip(roster["person_id"], roster["position"]))
    for s in (season - 1,):
        pp = history.load("people", s)
        if not pp.empty:
            for k, v in zip(pp["person_id"], pp["position"]):
                pos_map.setdefault(k, v)
    pdev = model.position_allowed(cur_p, prev_p, pos_map, p)
    base = model.player_base(cur_p, prev_p, p)

    upcoming = games[~games["played"]].sort_values("utc")
    if upcoming.empty:
        return None
    first = int(upcoming["round"].iloc[0])
    # whole current round (incl. turns already played, so the squad stays complete)
    # one extra round: once the current round is under way, trades target the next one
    fx = games[games["round"].between(first, first + HORIZON)
               & (games["phase"] == upcoming["phase"].iloc[0])]
    ctx = model.context_rows(fx, roster, ratings, pdev)
    ctx = ctx.merge(base[["base", "last3_pir", "season_pir", "prev_pir", "games", "season_min",
                          "prev_min"]] if "prev_min" in base else base,
                    left_on="person_id", right_index=True, how="left")
    ctx = ctx.merge(roster[["person_id", "name"]], on="person_id", how="left")
    ctx["no_data"] = ctx["base"].isna()
    ctx["base"] = ctx["base"].fillna(0)
    ctx["xpir"] = model.xpir(ctx, p).clip(lower=0)
    ctx["xpir"] = model.fantasy_points(ctx["xpir"], ctx["margin"])  # +10% win bonus
    coaches = coach_rows(fx, people, ratings)
    return {"round": first, "fixtures": fx, "ctx": ctx, "ratings": ratings, "roster": roster,
            "params": p, "coaches": coaches}


def coach_rows(fx: pd.DataFrame, people: pd.DataFrame, ratings: pd.DataFrame) -> pd.DataFrame:
    """Expected coach score per fixture from the expected margin distribution."""
    heads = people[(people["type"] == "coach") & people["active"]] \
        .drop_duplicates("club", keep="last").set_index("club")
    rows = []
    for f in fx.itertuples():
        for team, opp, home in ((f.home, f.away, True), (f.away, f.home, False)):
            if team not in ratings.index or opp not in ratings.index or team not in heads.index:
                continue
            rt, ro = ratings.loc[team], ratings.loc[opp]
            pace = (rt["pace"] + ro["pace"]) / 2
            m = (rt["net"] - ro["net"] + (rt["hca"] if home else -ro["hca"])) * pace / 100
            rows.append({"round": f.round, "gamecode": f.gamecode, "utc": getattr(f, "utc", None),
                         "person_id": heads.loc[team, "person_id"],
                         "name": heads.loc[team, "name"], "team": team, "opp": opp,
                         "is_home": home, "margin": m, "xpir": model.coach_points(m),
                         "position": "Head Coach", "pos_dev": np.nan, "base": np.nan,
                         "no_data": False, "win_prob": model.win_prob(m)})
    return pd.DataFrame(rows)


# --------------------------------------------------------------- fantasy

SUFFIXES = ("jr", "sr", "ii", "iii", "iv")


def _surname(s: str) -> str:
    k = _key(s)
    for suf in SUFFIXES:
        if k.endswith(suf) and len(k) > len(suf) + 2:
            k = k[: -len(suf)]
    return k


def match_people(fp: pd.DataFrame, roster: pd.DataFrame) -> pd.Series:
    """Fantasy player -> EuroLeague person_id: exact surname+team, then fuzzy within team."""
    import difflib

    r = roster.assign(sur=roster["name"].str.split(",").str[0].map(_surname),
                      first=roster["name"].str.split(",").str[1].fillna("").map(_key))
    by_team = {t: g for t, g in r.groupby("team")}
    ids = []
    for p in fp.itertuples():
        g = by_team.get(p.team)
        pid = None
        if g is not None:
            sur = _surname(p.last_name)
            hit = g[g["sur"] == sur]
            if hit.empty:
                close = difflib.get_close_matches(sur, g["sur"].tolist(), n=1, cutoff=0.8)
                hit = g[g["sur"] == close[0]] if close else hit
            if len(hit) > 1:  # same surname in a team: disambiguate by first name
                narrowed = hit[hit["first"].str.startswith(_key(p.first_name)[:3])]
                hit = narrowed if len(narrowed) else hit
            if len(hit):
                pid = hit["person_id"].iloc[0]
        ids.append(pid)
    return pd.Series(ids, index=fp.index)


def resolve_missing(fp: pd.DataFrame, season: int) -> pd.DataFrame:
    """Fantasy players absent from this season's EuroLeague roster (late signings,
    youngsters): find them in past box scores by name, else give a placeholder id.
    Returns roster rows (person_id, name, team, position) for them."""
    miss = fp[fp["person_id"].isna() & (fp["position"] != "Head Coach")]
    if miss.empty:
        return pd.DataFrame(columns=["person_id", "name", "team", "position"])
    hist = pd.concat([history.load("players", s)[["person_id", "player"]]
                      for s in (season - 1, season - 2)]).drop_duplicates("person_id")
    hist = hist.assign(sur=hist["player"].str.split(",").str[0].map(_surname),
                       first=hist["player"].str.split(",").str[1].fillna("").map(_key))
    rows = []
    for i, p in miss.iterrows():
        h = hist[(hist["sur"] == _surname(p.last_name))
                 & hist["first"].str.startswith(_key(p.first_name)[:3])]
        pid = h["person_id"].iloc[0] if len(h) else f"F{int(p.fantasy_id)}"
        fp.at[i, "person_id"] = pid
        rows.append({"person_id": pid, "name": f"{p.last_name.upper()}, {p.first_name.upper()}",
                     "team": p.team, "position": p.position})
    return pd.DataFrame(rows)


def fantasy_state(clubs: pd.DataFrame, roster: pd.DataFrame, season: int) -> dict:
    """Prices + my team. Never raises: returns {'error': ...} instead."""
    out = {"ok": False}
    try:
        cfg = fantasy.config()
        out["config"] = {k: cfg.get(k) for k in ("current_matchday", "current_round",
                                                   "current_players_list_id")}
        md = cfg["current_matchday"]
        raw = fantasy.players(cfg["current_players_list_id"], md["id"])
        fp = pd.DataFrame([fantasy.normalize_player(x) for x in raw])
        tv2code = dict(zip(clubs["tv"], clubs["code"]))
        fp["team"] = fp["team"].map(lambda t: tv2code.get(t, t))
        fp["person_id"] = match_people(fp, roster)
        out["extra_roster"] = resolve_missing(fp, season)
        out["players"] = fp
        out["unmatched"] = int(fp.loc[fp["position"] != "Head Coach", "person_id"]
                               .astype(str).str.startswith("F").sum())

        # price history (append one snapshot per matchday)
        hist_path = PUBLIC / "prices.csv"
        snap = fp[["fantasy_id", "person_id", "first_name", "last_name", "team", "position",
                   "price", "is_injured", "prob_play", "fantasy_avg"]].assign(matchday=md["number"])
        if hist_path.exists():
            old = pd.read_csv(hist_path, dtype={"person_id": str})
            old = old[old["matchday"] != md["number"]]
            snap = pd.concat([old, snap], ignore_index=True)
        snap.to_csv(hist_path, index=False)

        out["ok"] = True
    except fantasy.TokenError as e:
        out["error"] = f"token: {e}"
        return out
    except Exception as e:  # noqa: BLE001 - report, never crash the pipeline
        out["error"] = f"τιμές: {type(e).__name__}: {e}"
        return out

    # my team is a separate step: prices stay usable even if this fails
    out["my_teams"] = []
    try:
        for t in fantasy.my_teams():
            ros = fantasy.roster(t["id"], md["id"])
            out["my_teams"].append({"id": t["id"], "name": t.get("name"), "raw": ros})
            _write("roster_shape.json", _shape(ros))  # structure only, for debugging
    except fantasy.TokenError as e:
        out["error"] = f"token: {e}"
    except Exception as e:  # noqa: BLE001
        out["team_error"] = f"ομάδα: {type(e).__name__}: {e}"
    return out


def _shape(o, depth: int = 0):
    """Keys and types of a JSON payload without its values (safe to publish)."""
    if depth > 5:
        return "…"
    if isinstance(o, dict):
        return {k: _shape(v, depth + 1) for k, v in o.items()}
    if isinstance(o, list):
        return [_shape(o[0], depth + 1), f"×{len(o)}"] if o else []
    return type(o).__name__


def parse_my_roster(raw: dict) -> tuple[list[int], dict]:
    """Extract fantasy player ids (+ captain, bank) from an undocumented roster payload."""
    ids, meta = [], {}

    def walk(o):
        if isinstance(o, dict):
            # a roster slot: {"id", "court_position", "is_captain", ...} or {"player": {...}}
            if isinstance(o.get("player"), dict) and "id" in o["player"]:
                pid = o["player"]["id"]
                ids.append(pid)
                if o.get("is_captain") or o["player"].get("is_captain"):
                    meta["captain"] = pid
                return
            if "id" in o and ("court_position" in o or "quotation" in o or "is_captain" in o):
                ids.append(o["id"])
                if o.get("is_captain"):
                    meta["captain"] = o["id"]
                return
            for k in ("credits", "remaining_credits", "bank", "budget_left"):
                if isinstance(o.get(k), (int, float)) and "bank" not in meta:
                    meta["bank"] = float(o[k])
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)
    walk(raw)
    return list(dict.fromkeys(ids)), meta


def _prefs() -> dict:
    """preferences.yaml: surnames to keep (never sell) / avoid (never buy)."""
    try:
        cfg = yaml.safe_load((ROOT / "preferences.yaml").read_text()) or {}
    except OSError:
        cfg = {}
    return {k: {_key(x) for x in (cfg.get(k) or [])} for k in ("keep", "avoid")}


POS_ORDER = {"Guard": 0, "Forward": 1, "Center": 2, "Head Coach": 3}


def _opt_rows(df: pd.DataFrame) -> list[dict]:
    """Rows for the optimizer: fantasy id, position, price, horizon/round xPTS."""
    d = df.dropna(subset=["price", "fantasy_id"])
    d = d[d["position"].isin(POS_ORDER)]
    return [{"id": int(r["fantasy_id"]), "position": r["position"], "price": float(r["price"]),
             "x_h": float(r["x_h"]) if r["x_h"] == r["x_h"] else 0.0,
             "x_now": float(r["x_now"]) if r["x_now"] == r["x_now"] else 0.0,
             "name": r["name"], "team": r["team"], "label": r.get("label") or r["name"],
             "opp": r.get("opp"), "home": r.get("home"),
             "turn": int(r["turn"]) if r.get("turn") == r.get("turn") and r.get("turn") else None,
             "price_trend": r.get("price_trend"),
             "actual": r.get("actual") if r.get("actual") == r.get("actual") else None}
            for r in d.to_dict("records")]


def _pair_trades(tr: dict) -> list[dict]:
    """Present the optimal swap set as out->in pairs, matched by position."""
    outs = sorted(tr["out"], key=lambda p: (POS_ORDER[p["position"]], -p["price"]))
    ins = sorted(tr["in"], key=lambda p: (POS_ORDER[p["position"]], -p["price"]))
    return [{"out": o["label"], "in": i["label"], "gain": round(i["x_h"] - o["x_h"], 1),
             "price_out": o["price"], "price_in": i["price"], "out_id": o["id"], "in_id": i["id"]}
            for o, i in zip(outs, ins)]


def actual_lineup(raw: dict) -> list[dict]:
    """The lineup as set in the game: court_position orders the squad
    (starters first, then sixth man, then bench; the app keeps them sorted by it)."""
    rows = []
    for p in (raw or {}).get("players", []) if isinstance(raw, dict) else []:
        pos = (p.get("position") or {}).get("name")
        rows.append({"fantasy_id": p.get("id"), "court_position": p.get("court_position"),
                     "captain": bool(p.get("is_captain")), "pts": p.get("pts"),
                     "played": bool(p.get("match_played")), "position": pos,
                     "turn": (p.get("round") or {}).get("number"),
                     "name": f"{p.get('last_name', '')}".strip()})
    court = sorted([r for r in rows if r["position"] != "Head Coach"
                    and r["court_position"] is not None], key=lambda r: r["court_position"])
    for i, r in enumerate(court):
        r["role"] = "5άδα" if i < 5 else "6ος" if i == 5 else "πάγκος"
    for r in rows:
        r.setdefault("role", "coach" if r["position"] == "Head Coach" else None)
    return rows


def suggest_transfers(team: pd.DataFrame, pool: pd.DataFrame, bank: float, max_trades: int = 4,
                      min_gain: float = 3.0) -> list[dict]:
    """Greedy same-position swaps maximising xPIR over the horizon within budget."""
    team, moves = team.copy(), []
    for _ in range(max_trades):
        best = None
        owned = set(team["fantasy_id"])
        for out in team.itertuples():
            cands = pool[(pool["position"] == out.position) & ~pool["fantasy_id"].isin(owned)
                         & (pool["price"] <= out.price + bank)]
            if cands.empty:
                continue
            c = cands.loc[cands["x_h"].idxmax()]
            gain = c["x_h"] - out.x_h
            if best is None or gain > best[0]:
                best = (gain, out, c)
        if not best or best[0] < min_gain:
            break
        gain, out, c = best
        bank += out.price - c["price"]
        moves.append({"out": out.label, "in": c["label"], "gain": round(float(gain), 1),
                      "price_out": out.price, "price_in": float(c["price"]),
                      "bank_after": round(bank, 1)})
        team = pd.concat([team[team["fantasy_id"] != out.fantasy_id], c.to_frame().T])
    return moves


def n_fantasy_sources() -> int:
    try:
        return sum(1 for x in yaml.safe_load((ROOT / "sources.yaml").read_text())["sources"]
                   if x.get("fantasy")) or 1
    except (OSError, KeyError, TypeError):
        return 1


EXPERT_PICK = 0.05     # +5% per fantasy column recommending the player (max 2 counted)
EXPERT_CAPTAIN = 0.03  # +3% if at least one suggests him as captain
EXPERT_AVOID = 0.08    # -8% if a column advises against him
EXPERT_CAP = (0.85, 1.13)


def expert_votes(dig: dict | None) -> dict:
    """{player key: {"pick": {sources}, "captain": {...}, "avoid": {...}}} from fantasy columns."""
    out = {}
    for e in (dig or {}).get("expert", []):
        name = str(e.get("player", "")).split(" (")[0]
        stance = e.get("stance")
        if stance not in ("pick", "captain", "avoid") or not name:
            continue
        d = out.setdefault(_key(name), {"pick": set(), "captain": set(), "avoid": set()})
        d[stance].add(e.get("source", "?"))
        if stance == "captain":
            d["pick"].add(e.get("source", "?"))
    return out


def expert_factor(v: dict | None) -> float:
    """Deliberately small and capped: columns mostly see the same data as the model;
    their edge is roles/minutes/new signings. Re-weight once expert_log.csv shows
    whether their picks beat the model's expectation."""
    if not v:
        return 1.0
    f = 1 + EXPERT_PICK * min(len(v["pick"]), 2) + EXPERT_CAPTAIN * bool(v["captain"]) \
        - EXPERT_AVOID * bool(v["avoid"])
    return min(max(f, EXPERT_CAP[0]), EXPERT_CAP[1])


def log_experts(dig: dict, rnd: int, cur: pd.DataFrame) -> None:
    """Append this round's column picks with the model's own expectation, so their
    hit rate can be measured later (actual vs xPTS for picked vs not picked)."""
    path = PUBLIC / "expert_log.csv"
    by_key = {_key(n): r for n, r in zip(cur["name"], cur.to_dict("records"))}
    rows = []
    for e in dig.get("expert", []):
        r = by_key.get(_key(str(e.get("player", "")).split(" (")[0]))
        if r is None:
            continue
        rows.append({"round": rnd, "source": e.get("source"), "stance": e.get("stance"),
                     "person_id": r["person_id"], "name": r["name"], "team": r["team"],
                     "model_xpts": round(float(r["xpir"]), 2)})
    if not rows:
        return
    new = pd.DataFrame(rows)
    if path.exists():
        old = pd.read_csv(path, dtype={"person_id": str})
        old = old[old["round"] != rnd]  # latest view of this round's picks wins
        new = pd.concat([old, new], ignore_index=True)
    new.drop_duplicates(["round", "source", "stance", "person_id"]).to_csv(path, index=False)


def previous_digest(max_hours: int = 36):
    """Last successful Gemini digest if recent enough (Gemini is often overloaded)."""
    try:
        old = json.loads((PUBLIC / "news.json").read_text())
        at = datetime.fromisoformat(old["digest_at"])
        if old.get("digest") and datetime.now(timezone.utc) - at < pd.Timedelta(hours=max_hours):
            return old["digest"], old["digest_at"]
    except (OSError, KeyError, TypeError, ValueError):
        pass
    return None, None


def manual_team(table: pd.DataFrame) -> dict | None:
    """Fallback when the fantasy API is unavailable: my_team.yaml lists the squad.

    No prices -> no transfer suggestions, but lineup/captain advice still works.
    """
    path = ROOT / "my_team.yaml"
    if not path.exists():
        return None
    cfg = yaml.safe_load(path.read_text()) or {}
    wanted = [(_key(p.split("(")[0]), p.split("(")[1].strip(" )").upper() if "(" in p else None)
              for p in cfg.get("players", [])]
    t = table.assign(sk=table["name"].str.split(",").str[0].map(_key))
    rows = [t[(t["sk"] == k) & ((t["team"] == tm) if tm else True)].head(1) for k, tm in wanted]
    mine = pd.concat(rows) if rows else t.head(0)
    return {"name": cfg.get("name", "Η ομάδα μου (χειροκίνητα)"), "manual": True,
            "players": mine.drop(columns="sk").sort_values("x_now", ascending=False)
            .replace({np.nan: None}).to_dict("records"),
            "bank": None, "captain_id": None, "transfers": [], "parsed_players": len(mine)}


# ---------------------------------------------------------------- report

def actual_points(fx: pd.DataFrame, rnd: int, table: pd.DataFrame) -> pd.Series:
    """Fantasy points already scored this round (PIR, +10% on a win; coach by margin)."""
    played = fx[(fx["round"] == rnd) & fx["played"]]
    if played.empty:
        return pd.Series(np.nan, index=table.index)
    box = history.load("players", CURRENT_SEASON)
    box = box[box["gamecode"].isin(played["gamecode"])]
    margin = {}
    for g in played.itertuples():
        margin[g.home] = g.home_score - g.away_score
        margin[g.away] = g.away_score - g.home_score
    pir = dict(zip(box["person_id"], box["pir"]))

    def pts(r):
        m = margin.get(r["team"])
        if m is None:
            return np.nan
        if r["position"] == "Head Coach":
            return next(p for lo, hi, p in COACH_POINTS if lo < m <= hi)
        v = pir.get(r["person_id"])
        return np.nan if v is None else v * (1 + WIN_BONUS * (m > 0))
    return table.apply(pts, axis=1)


def turns(fx: pd.DataFrame, rnd: int) -> list[dict]:
    g = fx[fx["round"] == rnd].copy()
    g["local"] = g["utc"].dt.tz_convert(ATH)
    g["day"] = g["local"].dt.date
    out = []
    for i, (day, d) in enumerate(sorted(g.groupby("day"), key=lambda x: x[0]), 1):
        out.append({"turn": i, "date": str(day), "first_tip": d["local"].min().strftime("%H:%M"),
                    "done": bool(d["played"].all()),
                    "teams": sorted(set(d["home"]) | set(d["away"])),
                    "games": [f"{a.home}-{a.away} {a.local:%H:%M}" for a in d.itertuples()]})
    return out


def _pct(m, a):
    return round(100 * m / a, 1) if a else None


def player_details(season: int, ctx: pd.DataFrame, fixtures: pd.DataFrame,
                   ids: set) -> dict:
    """Per player, for the dashboard popup: season stats (this and last season), the
    last 3 games played and the next 3 with their xPTS. Keyed by person_id."""
    box, games = [], []
    for s in (season - 1, season):
        b, g = history.load("players", s), history.load("games", s)
        if not b.empty and not g.empty:
            box.append(b.assign(season=s))
            games.append(g.assign(season=s))
    out = {pid: {"stats": [], "last": [], "next": []} for pid in ids}
    if box:
        b = pd.concat(box, ignore_index=True)
        b = b[b["person_id"].isin(ids)]
        g = pd.concat(games, ignore_index=True)[["season", "gamecode", "round", "utc", "home",
                                                   "away", "home_score", "away_score"]]
        g["utc"] = pd.to_datetime(g["utc"], utc=True)
        b = b.merge(g, on=["season", "gamecode"], how="left")
        b["opp"] = np.where(b["team"] == b["home"], b["away"], b["home"])
        mine = np.where(b["team"] == b["home"], b["home_score"], b["away_score"])
        theirs = np.where(b["team"] == b["home"], b["away_score"], b["home_score"])
        b["won"] = mine > theirs
        b["reb"] = b["oreb"] + b["dreb"]
        b["fp"] = b["pir"] * np.where(b["won"], 1 + WIN_BONUS, 1.0)
        for (pid, s), d in b.groupby(["person_id", "season"]):
            n = len(d)
            out[pid]["stats"].append({
                "season": int(s), "g": n, **{k: round(float(d[k].mean()), 1) for k in
                                             ("min", "pts", "reb", "ast", "stl", "blk", "tov", "pir")},
                "fg2": _pct(d["fgm2"].sum(), d["fga2"].sum()),
                "fg3": _pct(d["fgm3"].sum(), d["fga3"].sum()),
                "ft": _pct(d["ftm"].sum(), d["fta"].sum())})
        b = b.sort_values("utc", ascending=False)
        for pid, d in b.groupby("person_id", sort=False):
            out[pid]["last"] = [{
                "season": int(r.season), "round": int(r.round),
                "date": r.utc.tz_convert(ATH).strftime("%d/%m/%y") if pd.notna(r.utc) else None,
                "opp": r.opp, "home": bool(r.team == r.home), "won": bool(r.won),
                "score": f"{int(r.home_score)}-{int(r.away_score)}", "min": round(float(r.min)),
                "pts": int(r.pts), "reb": int(r.reb), "ast": int(r.ast), "pir": int(r.pir),
                "fp": round(float(r.fp), 1)} for r in d.head(3).itertuples()]
    played = set(fixtures.loc[fixtures["played"], "gamecode"])
    nxt = ctx[ctx["person_id"].isin(ids) & ~ctx["gamecode"].isin(played)].copy()
    nxt["utc"] = pd.to_datetime(nxt["utc"], utc=True)
    nxt = nxt.sort_values(["round", "utc"], kind="stable")
    for pid, d in nxt.groupby("person_id"):
        out[pid]["next"] = [{
            "round": int(r.round), "opp": r.opp, "home": bool(r.is_home),
            "date": r.utc.tz_convert(ATH).strftime("%d/%m %H:%M") if pd.notna(r.utc) else None,
            "win": round(100 * model.win_prob(r.margin)), "x": round(float(r.xpir), 1)}
            for r in d.head(3).itertuples()]
    form = ctx.drop_duplicates("person_id").set_index("person_id")
    for pid in ids:
        if pid in form.index:
            f = form.loc[pid]
            out[pid]["form"] = {k: (None if pd.isna(f.get(k)) else round(float(f.get(k)), 1))
                                for k in ("last3_pir", "season_pir", "prev_pir", "base")}
            out[pid]["news_avail"] = None if pd.isna(f.get("avail")) else float(f.get("avail"))
    return out


def build(offline: bool = False) -> dict:
    season = CURRENT_SEASON
    if not offline:
        history.update_season(season - 1, refresh_people=False)
        history.update_season(season)
    clubs = pd.DataFrame(el_api.clubs(season))
    _write("clubs.json", clubs.to_dict("records"))
    ppl = history.load("people", season)
    people_all = ppl[ppl["active"]].rename(columns={"club": "team"})[["person_id", "name", "team"]]
    fs = {"ok": False, "error": "offline"} if offline else fantasy_state(clubs, people_all, season)
    pr = predictions(season, fs.get("extra_roster"))
    if pr is None:
        _write("report.json", {"generated": datetime.now(timezone.utc).isoformat(), "messages": []})
        return {}
    ctx, rnd = pr["ctx"], pr["round"]
    health = []

    # --- news & availability
    names = sorted(ctx["name"].dropna().unique())
    team_of = dict(zip(ctx["name"], ctx["team"]))
    arts, failed = ([], []) if offline else news.collect(names)
    health += [f"πηγή εκτός: {f}" for f in failed]
    dig, dig_at = None, None
    try:
        dig = news.digest(arts, [f"{n} ({team_of.get(n)})" for n in names])
        dig_at = datetime.now(timezone.utc).isoformat() if dig else None
    except Exception as e:  # noqa: BLE001
        dig, dig_at = previous_digest()
        note = " — κρατήθηκε η προηγούμενη σύνοψη" if dig else ""
        health.append((f"{e}" if isinstance(e, RuntimeError)
                       else f"Gemini: {type(e).__name__}") + note)
    avail = {}
    for a in (dig or {}).get("availability", []):
        f = news.AVAILABILITY_FACTOR.get(a.get("status"), 1.0)
        avail[_key(a.get("player", "").split(" (")[0])] = (f, a)
    ctx["avail"] = ctx["name"].map(lambda n: avail.get(_key(n), (1.0, None))[0])
    ctx["xpir"] = ctx["xpir"] * ctx["avail"]
    _write("news.json", {"articles": arts[:120], "digest": dig, "digest_at": dig_at,
                         "failed": failed})

    # --- per-player tables (coaches ride along with position "Head Coach")
    if not pr["coaches"].empty:
        ctx = pd.concat([ctx, pr["coaches"]], ignore_index=True)

    # --- fantasy columns: small, capped nudge for this round only (see expert_factor)
    ex = expert_votes(dig)
    if ex:
        log_experts(dig, rnd, ctx[ctx["round"] == rnd])  # model's own view, before the nudge
        k = ctx["name"].map(_key)
        f_ex = k.map(lambda x: expert_factor(ex.get(x)))
        cur = ctx["round"] == rnd
        ctx.loc[cur, "xpir"] = ctx.loc[cur, "xpir"] * f_ex[cur]
        ctx["expert_pick"] = k.map(lambda x: len(ex.get(x, {}).get("pick", ())))
        ctx["expert_cap"] = k.map(lambda x: len(ex.get(x, {}).get("captain", ())))
        ctx["expert_avoid"] = k.map(lambda x: len(ex.get(x, {}).get("avoid", ())))
    # trades: before the round starts they count from this round; once a game of it has
    # been played, the squad is locked until the next round, so they count from there
    fxr = pr["fixtures"]
    started = bool(fxr.loc[fxr["round"] == rnd, "played"].any())
    trade_rnd = rnd + 1 if started else rnd
    hw = horizon_weights(trade_rnd)
    ctx["xpir_w"] = ctx["xpir"] * (ctx["round"] - trade_rnd).map(
        lambda k: hw[k] if 0 <= k < len(hw) else 0.0)
    ctx["xpir_first"] = ctx["xpir"].where(ctx["round"] == trade_rnd, 0.0)
    now_round = ctx[ctx["round"] == rnd]
    for col in ("expert_pick", "expert_cap", "expert_avoid"):
        if col not in ctx:
            ctx[col] = 0
    agg = ctx.groupby("person_id").agg(
        expert_pick=("expert_pick", "first"), expert_cap=("expert_cap", "first"),
        expert_avoid=("expert_avoid", "first"),
        name=("name", "first"), team=("team", "first"), position=("position", "first"),
        x_h=("xpir_w", "sum"), x_first=("xpir_first", "sum"),
        base=("base", "first"), no_data=("no_data", "first"),
        season_pir=("season_pir", "first"), prev_pir=("prev_pir", "first"),
        season_min=("season_min", "first"))
    nr = now_round.groupby("person_id").agg(x_now=("xpir", "sum"), opp=("opp", "first"),
                                            home=("is_home", "first"), margin=("margin", "first"),
                                            pos_dev=("pos_dev", "first"))
    table = agg.join(nr, how="left").reset_index()
    trn = turns(pr["fixtures"], rnd)
    team_turn = {tm: tu["turn"] for tu in trn for tm in tu["teams"]}
    table["turn"] = table["team"].map(team_turn)
    table["actual"] = actual_points(pr["fixtures"], rnd, table)

    # --- fantasy prices / my team
    my, best = None, None
    price_info = {"method": "none"}
    if fs.get("ok"):
        fp = fs["players"]
        table = table.merge(fp.dropna(subset=["person_id"]).drop_duplicates("person_id")
                            [["person_id", "fantasy_id", "price", "status", "position"]]
                            .rename(columns={"position": "f_position"}), on="person_id", how="left")
        # squad slots follow the fantasy game's position, not the EuroLeague listing
        table["position"] = table["f_position"].fillna(table["position"])
        # injuries straight from the game: scale this round fully, the horizon only for it
        avail = fp.dropna(subset=["person_id"]).drop_duplicates("person_id").set_index("person_id")
        f_game = table["person_id"].map(lambda pid: fantasy.availability(avail.loc[pid])
                                        if pid in avail.index else 1.0)
        table["avail_game"] = f_game
        table["injured"] = table["person_id"].map(
            lambda pid: bool(avail.loc[pid, "is_injured"]) if pid in avail.index else False)
        lost_now = table["x_now"].fillna(0) * (1 - f_game)
        table["x_h"] = table["x_h"] - table["x_first"].fillna(0) * (1 - f_game)
        table["x_now"] = table["x_now"] - lost_now
        # no history (new to EuroLeague): the game's price is the market's estimate.
        # Map price -> xPTS per position from players with data, discounted 20% for
        # the extra uncertainty, instead of leaving them at 0.
        known = table[~table["no_data"].fillna(False) & table["price"].notna()
                      & (table["x_now"] > 0) & (table["position"] != "Head Coach")]
        nd = table["no_data"].fillna(False) & table["price"].notna() \
            & (table["position"] != "Head Coach")
        table["prior"] = None
        for pos, g in known.groupby("position"):
            if len(g) < 10:
                continue
            slope, icpt = np.polyfit(g["price"], g["x_now"], 1)
            m = nd & (table["position"] == pos)
            est = (0.8 * (slope * table.loc[m, "price"] + icpt)).clip(lower=0)
            table.loc[m, "x_now"] = est * f_game[m]
            table.loc[m, "x_h"] = est * sum(horizon_weights(trade_rnd))
            table.loc[m, "prior"] = "τιμή"
        table, price_info = prices.annotate(table)  # $ = likely price rise
        n_inj = int((f_game < 1).sum())
        if n_inj == 0:
            health.append("fantasy: το παιχνίδι δεν έδωσε κανέναν τραυματία/αμφίβολο (έλεγχος πεδίων)")
        table["value"] = table["x_h"] / table["price"]
        if fs["unmatched"] > 40:  # a handful of unregistered bench players is normal
            health.append(f"{fs['unmatched']} παίκτες του fantasy λείπουν από τα ρόστερ EuroLeague")
        pool = table.dropna(subset=["price", "fantasy_id"]).copy()
        pool["label"] = pool["name"] + " (" + pool["team"] + ")"
        prefs = _prefs()
        sur = pool["name"].str.split(",").str[0].map(_key)
        avoid_ids = set(pool.loc[sur.isin(prefs["avoid"]), "fantasy_id"])
        keep_ids = set(pool.loc[sur.isin(prefs["keep"]), "fantasy_id"])
        try:
            best = optimize.best_squad(_opt_rows(pool))
        except Exception as e:  # noqa: BLE001
            health.append(f"βελτιστοποίηση: {type(e).__name__}")
        max_trades = 11 if trade_rnd == 1 or (trade_rnd - 1) in UNLIMITED_AFTER else 4
        for t in fs["my_teams"][:1]:
            ids, meta = parse_my_roster(t["raw"])
            mine = table[table["fantasy_id"].isin(ids)].copy()
            mine["label"] = mine["name"] + " (" + mine["team"] + ")"
            bank = meta.get("bank", max(0.0, BUDGET - mine["price"].sum()))
            my = {"name": t["name"], "players": mine.sort_values("x_now", ascending=False)
                  .to_dict("records"), "bank": bank, "captain_id": meta.get("captain"),
                  "parsed_players": len(ids), "max_trades": max_trades, "trade_round": trade_rnd,
                  "actual_lineup": actual_lineup(t["raw"])}
            five = [r for r in my["actual_lineup"] if r["role"] == "5άδα"]
            if five and not {"Guard", "Forward", "Center"} <= {r["position"] for r in five}:
                health.append("ομάδα: η πεντάδα που διάβασα δεν έχει G/F/C — έλεγχος court_position")
            try:
                sq = _opt_rows(mine)
                lu = optimize.lineup(sq) if len(sq) == 11 else None
                if lu:
                    team_lu, plan = optimize.defer_later_turns(lu["team"])
                    my["lineup"] = team_lu
                    my["lineup_plan"] = [{"start": p["start"]["name"], "bench": p["bench"]["name"],
                                          "bench_x": round(p["bench"]["x_now"], 1),
                                          "bench_turn": p["bench"].get("turn")} for p in plan]
                else:
                    my["lineup"] = None
                # round under way: the proposal must follow the in-round rules (like /lineup)
                if any(r.get("played") for r in my["actual_lineup"]):
                    live = optimize.lineup_in_round(in_round_squad(my))
                    if live:
                        rows = {p["id"]: p for p in sq}
                        my["lineup"] = [{**rows.get(p["id"], p), "role": p["role"],
                                         "captain": p["captain"]} for p in live["team"]]
                        my["lineup_plan"] = []
                tr = optimize.transfers(sq, _opt_rows(pool[~pool["fantasy_id"].isin(avoid_ids)]),
                                        bank, max_trades=max_trades,
                                        min_gain_per_trade=MIN_GAIN_PER_TRADE
                                        * sum(horizon_weights(trade_rnd)) / sum(HORIZON_WEIGHTS),
                                        keep={int(i) for i in keep_ids})
                my["transfers"] = _pair_trades(tr) if tr else []
                my["transfer_gain"] = tr["gain"] if tr else 0
                my["bank_after"] = tr["bank_after"] if tr else bank
            except Exception as e:  # noqa: BLE001 - fall back to the greedy heuristic
                health.append(f"βελτιστοποίηση ομάδας: {type(e).__name__}: {e}")
                my["transfers"] = suggest_transfers(mine, pool, bank)
            if len(ids) < 10:
                health.append(f"ομάδα: βρέθηκαν {len(ids)}/10 παίκτες — έλεγχος parser")
    elif fs.get("error"):
        health.append(f"fantasy: {fs['error']}")
    if fs.get("team_error"):
        health.append(f"fantasy {fs['team_error']}")
    elif fs.get("ok") and not fs.get("my_teams"):
        health.append("fantasy: δεν βρέθηκε ομάδα Classic στον λογαριασμό")
    if os.environ.get("CI") and not os.environ.get("GEMINI_API_KEY"):
        health.append("GEMINI_API_KEY κενό — χωρίς σύνοψη νέων")
    tok = fantasy.token_expiry()
    if tok["days_left"] is not None and tok["days_left"] < 3:
        health.insert(0, "🔑 Το FANTASY_TOKEN λήγει σε "
                      f"{max(tok['days_left'], 0):.1f} μέρες — ανανέωσέ το")
    if my is None:
        my = manual_team(table)

    table = table.sort_values("x_now", ascending=False)
    try:
        _write("players.json", player_details(
            CURRENT_SEASON, ctx, pr["fixtures"], set(table.loc[table["x_now"].notna(), "person_id"])))
    except Exception as e:  # noqa: BLE001 - the popup is a nice-to-have
        health.append(f"λεπτομέρειες παικτών: {type(e).__name__}: {e}")
    ratings = pr["ratings"].sort_values("net", ascending=False).reset_index()
    _write("predictions.json", {
        "generated": datetime.now(timezone.utc).isoformat(), "season": CURRENT_SEASON,
        "round": rnd, "turns": trn,
        "players": table.replace({np.nan: None}).to_dict("records"),
        "team_ratings": ratings.round(2).to_dict("records"),
        "fixtures": [{"round": int(f.round), "home": f.home, "away": f.away,
                      "utc": f.utc.isoformat()} for f in pr["fixtures"].itertuples()],
        "my_team": my, "best_team": best, "health": health, "fantasy_ok": fs.get("ok", False),
        "price_model": price_info,
    })
    msgs = messages(rnd, trn, table, my, dig, health)
    _write("report.json", {"generated": datetime.now(timezone.utc).isoformat(),
                           "round": rnd, "messages": msgs})
    return {"round": rnd, "messages": msgs}


def _fmt(r) -> str:
    ha = "🏠" if r.get("home") else "✈️"
    dollar = " $" if r.get("price_trend") == "up" else ""
    return (f"{r['name'].split(',')[0].title()} ({r['team']}) {ha} vs {r.get('opp')} — "
            f"<b>{r['x_now']:.1f}</b>{dollar}")


def _short(r) -> str:
    return f"{str(r['name']).split(',')[0].title()} ({r['team']})"


def in_round_squad(my: dict | None) -> list[dict]:
    """The squad as set in the game, for optimize.lineup_in_round: players who already
    played carry their real points."""
    real = {r["fantasy_id"]: r for r in ((my or {}).get("actual_lineup") or []) if r.get("role")}
    sq = []
    for r in (my or {}).get("players", []):
        fid = r.get("fantasy_id")
        a = real.get(int(fid)) if fid == fid and fid is not None else None
        if a is None:
            continue
        played = bool(a["played"])
        sq.append({"id": int(fid), "position": r["position"], "price": 0.0, "name": r["name"],
                   "team": r["team"], "turn": a.get("turn"), "played": played,
                   "x_now": float(a["pts"] or 0) if played else float(r.get("x_now") or 0),
                   "cur_role": a["role"], "cur_captain": bool(a["captain"])})
    return sq


def turn_check(tu: dict, table: pd.DataFrame, my: dict | None) -> list[str]:
    """Before a later turn: the best legal lineup given what already happened, from the
    same optimizer as /lineup (a played starter can only go to the bench, the armband
    only to a player who has not played)."""
    lines = ["⭐ <b>Αρχηγός & αλλαγές πριν το Turn " f"{tu['turn']}</b>"]
    sq = in_round_squad(my)
    res = optimize.lineup_in_round(sq) if len(sq) == 11 else None
    if not res:
        today = table[table["team"].isin(tu["teams"]) & (table["position"] != "Head Coach")]
        lines.append("Οι καλύτεροι σήμερα:")
        return lines + [f"• {_fmt(r)}" for r in today.head(3).to_dict("records")]
    nm = lambda p: p["name"].split(",")[0].title()  # noqa: E731
    done = sorted((p for p in sq if p["played"] and p["position"] != "Head Coach"),
                  key=lambda p: -p["x_now"])
    if not done:
        lines.append("<i>Κανείς σου δεν έχει παίξει ακόμα — η πρόταση του Turn 1 ισχύει.</i>")
    else:
        lines.append("Έφεραν ήδη: " + ", ".join(f"{nm(p)} <b>{p['x_now']:.0f}</b>" for p in done))
    new = {p["id"]: p for p in res["team"]}
    start = ("5άδα", "6ος")
    ins = [p for p in sq if not p["played"] and p["cur_role"] == "πάγκος"
           and new[p["id"]]["role"] in start]
    outs = [p for p in sq if p["cur_role"] in start and new[p["id"]]["role"] == "πάγκος"]
    cap_new = next(p for p in res["team"] if p["captain"])
    cap_cur = next((p for p in sq if p["cur_captain"]), None)
    if ins:
        lines.append("🔄 <b>Αλλαγή</b>: μπαίνει " + ", ".join(
            f"{nm(p)} (xPTS {p['x_now']:.1f})" for p in ins) + " — βγαίνει " + ", ".join(
            f"{nm(p)} ({'έφερε' if p['played'] else 'xPTS'} {p['x_now']:.1f})" for p in outs))
    if cap_cur is None or cap_new["id"] != cap_cur["id"]:
        lines.append(f"👉 <b>Αρχηγός</b>: {nm(cap_new)} (xPTS {cap_new['x_now']:.1f})")
    if ins or cap_cur is None or cap_new["id"] != cap_cur["id"]:
        lines.append("<i>Το /lineup το εφαρμόζει.</i>")
    else:
        lines.append("✅ Καμία αλλαγή: η ομάδα σου είναι ήδη η καλύτερη δυνατή για σήμερα.")
    return lines


def messages(rnd, trn, table, my, dig, health) -> list[dict]:
    dash = os.environ.get("DASHBOARD_URL", "")
    t_all = table.dropna(subset=["x_now"])
    coaches = t_all[t_all["position"] == "Head Coach"]
    t = t_all[t_all["position"] != "Head Coach"]
    msgs = []
    for tu in trn:
        if tu.get("done"):
            continue
        day = datetime.fromisoformat(tu["date"])
        playing = t[t["team"].isin(tu["teams"])]
        lines = [f"🏀 <b>Αγωνιστική {rnd} — Turn {tu['turn']}</b> "
                 f"({DAYS_EL[day.weekday()]} {day:%d/%m}, 1ο τζάμπολ {tu['first_tip']})", ""]
        lines += ["📅 " + " · ".join(tu["games"]), ""]
        # captain candidates: my starting five if known, else the whole league
        lu = (my or {}).get("lineup")
        if lu:
            five_ids = {p["id"] for p in lu if p["role"] == "5άδα"}
            cand = t[t["fantasy_id"].isin(five_ids)]
        else:
            cand = t
        cand_now = cand[cand["team"].isin(tu["teams"])]
        cand_later = cand[cand["team"].isin(sum([x["teams"] for x in trn
                                                if x["turn"] > tu["turn"]], []))]
        if tu["turn"] == 1:
            if my and my.get("transfers"):
                lim = "απεριόριστες" if my.get("max_trades", 4) > 4 else "έως 4"
                tr_r = my.get("trade_round", rnd)
                lines += [f"🔁 <b>Προτεινόμενες αλλαγές</b> ({lim}· +{my.get('transfer_gain', 0)} "
                          f"σταθμισμένα xPTS R{tr_r}–R{tr_r + sum(w > 0 for w in horizon_weights(tr_r)) - 1})"]
                for m in my["transfers"]:
                    lines.append(f"• {m['out']} ➜ {m['in']}  ({m['price_out']}→{m['price_in']}cr)")
                lines.append("")
            elif my:
                lines += ["🔁 Καμία αλλαγή δεν αξίζει αυτή την αγωνιστική.", ""]
            if lu:
                role = lambda r: [p for p in lu if p["role"] == r]  # noqa: E731
                nm_ = lambda p: (f"{p['name'].split(',')[0].title()} ({p['position'][0]}"  # noqa: E731
                                 + (f", T{p['turn']}" if p.get("turn") else "") + ")")
                lines.append("👥 <b>Προτεινόμενη πεντάδα</b> (με την τωρινή ομάδα)")
                lines.append(", ".join(nm_(p) for p in role("5άδα")))
                lines.append("6ος: " + ", ".join(nm_(p) for p in role("6ος")))
                lines.append("Πάγκος: " + ", ".join(nm_(p) for p in role("πάγκος")))
                for pl in my.get("lineup_plan") or []:
                    lines.append(f"🕐 <b>Πριν το T{pl['bench_turn']}</b>: αν ο "
                                 f"{pl['start'].split(',')[0].title()} φέρει κάτω από "
                                 f"{pl['bench_x']:.0f}, βάλε τον {pl['bench'].split(',')[0].title()} "
                                 "στη θέση του (/lineup το κάνει).")
                real = {r["fantasy_id"]: r for r in (my.get("actual_lineup") or [])}
                if real:
                    diff = []
                    for p in lu:
                        r = real.get(p["id"])
                        if not r or r["role"] == p["role"] or p["role"] == "coach":
                            continue
                        if p["role"] in ("5άδα", "6ος") and r["role"] == "πάγκος":
                            diff.append(f"βάλε τον {p['name'].split(',')[0].title()} {p['role']}")
                        elif p["role"] == "5άδα" and r["role"] == "6ος":
                            diff.append(f"ο {p['name'].split(',')[0].title()} στην πεντάδα")
                    cap_s = next((p for p in lu if p["captain"]), None)
                    cap_r = next((r for r in real.values() if r["captain"]), None)
                    if cap_s and cap_r and cap_s["id"] != cap_r["fantasy_id"]:
                        diff.append(f"αρχηγός ο {cap_s['name'].split(',')[0].title()} "
                                    f"(τώρα: {cap_r['name'].title()})")
                    lines.append("✅ Η ομάδα σου στο παιχνίδι είναι ήδη έτσι." if not diff else
                                 "✏️ <b>Στο παιχνίδι</b>: " + "; ".join(diff) + ".")
                lines.append("")
            lines.append("⭐ <b>Αρχηγός</b>" + (" (από την πεντάδα σου)" if lu else ""))
            if len(cand_now):
                lines.append(f"Turn 1: {_fmt(cand_now.iloc[0])}")
            if len(cand_later):
                lines.append(f"Plan B (Turn 2+): {_fmt(cand_later.iloc[0])}")
            lines.append("<i>Βάλε αρχηγό στο Turn 1· αν δεν φτάσει το xPTS του plan B, "
                         "μεταφέρεις το x2 σε παίκτη του Turn 2 (όχι σε κάποιον που έπαιξε).</i>")
        else:
            lines += turn_check(tu, table, my)
        if tu["turn"] == 1 and len(coaches):
            c = coaches.sort_values("x_now", ascending=False).iloc[0]
            line = (f"🧑‍💼 <b>Καλύτερος coach αγωνιστικής</b>: {c['name'].split(',')[0].title()} ({c['team']}) "
                    f"{'🏠' if c.get('home') else '✈️'} vs {c.get('opp')} — <b>{c['x_now']:.1f}</b>")
            if c.get("price") == c.get("price") and c.get("price") is not None:
                line += f" · {c['price']}cr"
            lines += ["", line]
        lines += ["", f"📈 <b>Top xPTS {'σήμερα' if tu['turn'] > 1 else 'αγωνιστικής'}</b>"]
        src = playing if tu["turn"] > 1 else t
        lines += [f"{i}. {_fmt(r)}" for i, r in enumerate(src.head(8).to_dict("records"), 1)]
        if "value" in t and tu["turn"] == 1:
            v = t.dropna(subset=["value"]).sort_values("value", ascending=False).head(5)
            lines += ["", "💰 <b>Value (σταθμισμένα xPTS/credit)</b>"]
            lines += [f"• {r['name'].split(',')[0].title()} ({r['team']}) {r['price']}cr — "
                      f"{r['value']:.2f}" for r in v.to_dict("records")]
        if tu["turn"] == 1 and "avail_game" in t:
            out_now = t_all[(t_all["avail_game"] < 1) & (t_all["base"].fillna(0) >= 8)] \
                .sort_values("base", ascending=False).head(10)
            if len(out_now):
                lines += ["", "🚑 <b>Τραυματίες/αμφίβολοι (από το παιχνίδι)</b>"]
                for r in out_now.to_dict("records"):
                    a = r["avail_game"]
                    state = "εκτός" if a == 0 else f"{a:.0%} να παίξει"
                    lines.append(f"• {r['name'].split(',')[0].title()} ({r['team']}) — {state}")
        if tu["turn"] == 1 and "expert_pick" in t_all:
            cons = t_all[t_all["expert_pick"] > 0].sort_values(["expert_pick", "x_now"],
                                                               ascending=False).head(8)
            if len(cons):
                lines += ["", "🗣️ <b>Προτάσεις στηλών fantasy</b> (πηγές που τον προτείνουν)"]
                for r in cons.to_dict("records"):
                    extra = " · ★ αρχηγός" if r.get("expert_cap") else ""
                    dollar = " $" if r.get("price_trend") == "up" else ""
                    price = f" · {r['price']}cr" if r.get("price") == r.get("price") and r.get("price") else ""
                    lines.append(f"• {r['name'].split(',')[0].title()} ({r['team']}, "
                                 f"{str(r['position'])[:1]}{price}) — "
                                 f"{int(r['expert_pick'])}/{n_fantasy_sources()}{extra} · "
                                 f"xPTS {r['x_now']:.1f}{dollar}")
        if dig:
            inj = [a for a in dig.get("availability", []) if a.get("status") != "available"]
            if inj:
                lines += ["", "🏥 <b>Διαθεσιμότητα</b>"]
                lines += [f"• {a['player']}: {a['status']} — {a.get('note', '')}" for a in inj[:8]]
            if dig.get("summary_el") and tu["turn"] == 1:
                lines += ["", "📰 <b>Ειδικοί & νέα</b>", dig["summary_el"]]
        if health:
            lines += ["", "⚠️ " + " | ".join(health[:4])]
        if dash:
            lines += ["", f'🔗 <a href="{dash}">Dashboard</a>']
        msgs.append({"date": tu["date"], "turn": tu["turn"],
                     "text": "\n".join(str(x) for x in lines)})
    return msgs


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--offline", action="store_true")
    a = ap.parse_args()
    res = build(a.offline)
    for m in res.get("messages", []):
        print(f"--- {m['date']} (turn {m['turn']})\n{m['text']}\n")
