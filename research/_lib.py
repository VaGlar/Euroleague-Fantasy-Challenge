"""Shared data for the decision experiments (003, 004).

Builds, for every regular-season round of a past season, a candidate pool that looks like
the real game: everyone who was on a team's box score earlier in the season (so players
who then sit out or are injured score 0, not missing), with the model's features known
before the round, an estimated price, and the fantasy points they really scored.

Past prices are not published, so they are estimated: this season's opening prices were
set by the game from last season's output (r = 0.92), and the same mapping (price ~ PIR per
game, by position) is applied one season back. Prices stay fixed for the whole season.
"""
from __future__ import annotations

import copy
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from elf import backtest as bt, history, model, optimize  # noqa: E402
from elf.config import MODEL  # noqa: E402

COACH_PRICE = 7.0          # median coach price (2026-27 opening); the budget left for players
MIN_ROUND = 3              # the first rounds have too little of the season to build a pool


def season_stats(season: int) -> pd.DataFrame:
    """PIR per game (a DNP counts as 0, as in the game) and games, per player."""
    pl = history.load("players", season)
    g = pl.groupby("person_id")
    return pd.DataFrame({"pir_pg": g["pir"].mean(), "games": g.size()})


def price_mapping():
    """Fit price = a + b * last season's PIR per game, per position, on 2026-27 opening prices."""
    p = pd.read_csv(ROOT / "data/public/prices.csv", dtype={"person_id": str})
    p = p[(p["matchday"] == 1) & (p["position"] != "Head Coach")]
    s = season_stats(2025)
    d = p.merge(s, left_on="person_id", right_index=True, how="left")
    fits, fallback = {}, {}
    for pos, g in d.groupby("position"):
        k = g[g["games"] >= 5]
        b, a = np.polyfit(k["pir_pg"], k["price"], 1)
        fits[pos] = (a, b, float(np.corrcoef(k["pir_pg"], k["price"])[0, 1]))
        fallback[pos] = float(g.loc[g["games"].isna(), "price"].median())  # no EuroLeague history
    return fits, fallback


def estimated_prices(season: int, pos_map: dict) -> dict:
    """Last season's PIR per game through the price mapping. Players with no (or < 5 games of)
    EuroLeague history last season - youngsters at 4 credits and imports at 9-12 in the real game -
    are priced from their first 5 games of this season instead: a small look-ahead, in the price
    only (the model never sees it), so that cheap and expensive newcomers are told apart."""
    fits, fallback = price_mapping()
    prev = season_stats(season - 1)
    cur = history.load("players", season).sort_values("gamecode")
    first5 = cur.groupby("person_id")["pir"].apply(lambda s: s.head(5).mean())
    out = {}
    for pid, pos in pos_map.items():
        if pos not in fits:
            continue
        a, b, _ = fits[pos]
        if pid in prev.index and prev.loc[pid, "games"] >= 5:
            x = prev.loc[pid, "pir_pg"]
        elif pid in first5.index:
            x = first5[pid]
        else:
            out[pid] = fallback[pos]
            continue
        out[pid] = float(np.clip(a + b * x, 4.0, 17.6))
    return out


def build(season: int, p: dict | None = None) -> pd.DataFrame:
    """One row per (round, player in the pool) with features, price and actual fantasy points."""
    p = copy.deepcopy(p or MODEL)
    games = history.load("games", season)
    players = history.load("players", season)
    teams = history.load("teams", season)
    prev_players, prev_teams = history.load("players", season - 1), history.load("teams", season - 1)
    pos_map = bt.pos_map_for(season)
    price = estimated_prices(season, pos_map)
    rs = games[(games["phase"] == "RS") & games["played"]].copy()
    rs["utc"] = pd.to_datetime(rs["utc"])
    games["utc"] = pd.to_datetime(games["utc"])
    won = {}
    for g in rs.itertuples():
        won[(g.gamecode, g.home)] = g.home_score > g.away_score
        won[(g.gamecode, g.away)] = g.away_score > g.home_score
    codes = sorted(set(rs["home"]) | set(rs["away"]))
    out = []
    for r in sorted(rs["round"].unique()):
        if r < MIN_ROUND:
            continue
        fx = rs[rs["round"] == r]
        before = set(games.loc[games["played"] & (games["utc"] < fx["utc"].min()), "gamecode"])
        cp = players[players["gamecode"].isin(before)].sort_values("gamecode")
        ct = teams[teams["gamecode"].isin(before)]
        ratings = model.team_ratings(ct, prev_teams, codes, p)
        pdev = model.position_allowed(cp, prev_players, pos_map, p)
        base = model.player_base(cp, prev_players, p)
        # the pool: on a box score this season before the round, with his latest team
        roster = cp.groupby("person_id")["team"].last().reset_index()
        roster = roster.assign(position=roster["person_id"].map(pos_map)).dropna(subset=["position"])
        ctx = model.context_rows(fx, roster, ratings, pdev)
        act = players[players["gamecode"].isin(fx["gamecode"])][["gamecode", "person_id", "team", "pir", "min"]]
        ctx = ctx.merge(act, on=["gamecode", "person_id", "team"], how="left")
        ctx["dressed"] = ctx["pir"].notna()
        ctx["pir"] = ctx["pir"].fillna(0.0)                       # not in the box score: 0 points
        ctx["won"] = [won.get((g, t), False) for g, t in zip(ctx["gamecode"], ctx["team"])]
        ctx["fpts"] = ctx["pir"] * np.where(ctx["won"], 1.1, 1.0)
        ctx = ctx.merge(base[["last3_pir", "season_pir", "prev_pir", "games"]], left_on="person_id",
                        right_index=True, how="left")
        ctx["price"] = ctx["person_id"].map(price)
        out.append(ctx.dropna(subset=["price"]))
    df = pd.concat(out, ignore_index=True)
    for c in ["last3_pir", "season_pir", "prev_pir", "games", "pir", "fpts", "pos_dev", "pace_dev", "margin", "price"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    return df


def predict(df: pd.DataFrame, p: dict) -> pd.Series:
    """Expected fantasy points with parameters p (form blend x context x win bonus)."""
    d = df.assign(base=model.blend(df, p).fillna(0.0))
    return model.fantasy_points(model.xpir(d, p).clip(lower=0), d["margin"])


def squad_points(rnd: pd.DataFrame, pred: pd.Series) -> float:
    """Best squad under the budget by the predictions; returns the fantasy points it really scored
    (five + sixth 100%, bench 50%, captain x2). A fresh squad every round: a test of choices,
    not of the transfer plan."""
    pool = [{"id": i, "position": r.position, "price": r.price, "x_h": float(pred[i]), "x_now": float(pred[i])}
            for i, r in rnd.iterrows()]
    pool.append({"id": -1, "position": "Head Coach", "price": 0.0, "x_h": 0.0, "x_now": 0.0})
    res = optimize.best_squad(pool, budget=100.0 - COACH_PRICE)
    if not res:
        return float("nan")
    tot = 0.0
    for q in res["team"]:
        if q["id"] == -1:
            continue
        a = float(rnd.at[q["id"], "fpts"])
        tot += a * (0.5 if q["role"] == "πάγκος" else 1.0) * (2.0 if q["captain"] else 1.0)
    return tot
