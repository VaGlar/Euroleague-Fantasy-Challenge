"""Walk-forward backtest of xPIR on a past season, and fit of context weights.

For every regular-season round r of `season`, the model only sees games played
before round r (plus the whole previous season), predicts every player who
appeared in round r, and is scored against the real PIR.

Usage: python -m elf.backtest 2025 [--save]
"""
from __future__ import annotations

import argparse
import copy
import itertools
import json
from datetime import datetime, timezone

import numpy as np
import pandas as pd

from . import history, model
from .config import MODEL, PUBLIC


def pos_map_for(season: int) -> dict:
    m = {}
    for s in (season - 1, season):  # later season wins
        ppl = history.load("people", s)
        if not ppl.empty:
            ppl = ppl[ppl["type"] == "player"].dropna(subset=["position"])
            m.update(dict(zip(ppl["person_id"], ppl["position"])))
    return m


def walk_forward(season: int, p: dict) -> pd.DataFrame:
    games = history.load("games", season)
    players = history.load("players", season)
    teams = history.load("teams", season)
    prev_players = history.load("players", season - 1)
    prev_teams = history.load("teams", season - 1)
    pos_map = pos_map_for(season)

    rs = games[(games["phase"] == "RS") & games["played"]].copy()
    rs["utc"] = pd.to_datetime(rs["utc"])
    games["utc"] = pd.to_datetime(games["utc"])
    codes = sorted(set(rs["home"]) | set(rs["away"]))
    out = []
    for r in sorted(rs["round"].unique()):
        fx = rs[rs["round"] == r]
        before = set(games.loc[games["played"] & (games["utc"] < fx["utc"].min()), "gamecode"])
        cp = players[players["gamecode"].isin(before)]
        ct = teams[teams["gamecode"].isin(before)]

        ratings = model.team_ratings(ct, prev_teams, codes, p)
        pdev = model.position_allowed(cp, prev_players, pos_map, p)
        base = model.player_base(cp, prev_players, p)

        actual = players[players["gamecode"].isin(fx["gamecode"])]
        roster = actual[["person_id", "team"]].drop_duplicates()
        roster = roster.assign(position=roster["person_id"].map(pos_map))
        ctx = model.context_rows(fx, roster, ratings, pdev)
        ctx = ctx.merge(actual[["gamecode", "person_id", "pir", "min", "player"]],
                        on=["gamecode", "person_id"])
        ctx = ctx.merge(base[["base", "last3_pir", "season_pir", "prev_pir", "games"]],
                        left_on="person_id", right_index=True, how="left")
        out.append(ctx)
    df = pd.concat(out, ignore_index=True)
    num = ["base", "last3_pir", "season_pir", "prev_pir", "games", "pir", "min",
           "pos_dev", "pace_dev", "margin"]
    df[num] = df[num].apply(pd.to_numeric, errors="coerce")
    return df


def fit(df: pd.DataFrame, ridge: float = 50.0) -> dict:
    X = model.design(df)
    y = (df["pir"] - df["base"]).to_numpy()
    A = X.T @ X + ridge * np.eye(X.shape[1])
    c = np.linalg.solve(A, X.T @ y)
    return dict(zip(model.COEF_ORDER, map(float, c)))


def metrics(df: pd.DataFrame, pred: pd.Series) -> dict:
    err = (df["pir"] - pred).abs()
    # ranking quality inside each round: Spearman between predicted and actual
    rho = []
    for _, g in df.assign(pred=pred).groupby("round"):
        if len(g) > 20:
            rho.append(g["pred"].rank().corr(g["pir"].rank()))
    # of the model's top-20 per round, how many finished in the actual top-20
    hits = []
    for _, g in df.assign(pred=pred).groupby("round"):
        top_p = set(g.nlargest(20, "pred").index)
        top_a = set(g.nlargest(20, "pir").index)
        hits.append(len(top_p & top_a) / 20)
    return {"mae": round(float(err.mean()), 3), "spearman": round(float(np.mean(rho)), 3),
            "top20_hit": round(float(np.mean(hits)), 3), "n": int(len(df))}


def run(season: int, save: bool = False) -> dict:
    report = {"season": season, "generated": datetime.now(timezone.utc).isoformat()}

    # 1) choose the form blend weights (grid), context off
    best = None
    grid = [(a, b, c) for a, b, c in itertools.product([0.0, 0.1, 0.2, 0.35, 0.5], [0.2, 0.35, 0.5],
                                                       [0.1, 0.2, 0.35, 0.5, 0.75, 1.0, 1.5])]
    raw = walk_forward(season, copy.deepcopy(MODEL))
    for w3, ws, wp in grid:
        p = copy.deepcopy(MODEL)
        p.update(w_last3=w3, w_season=ws, w_prev=wp)
        df = raw.assign(base=model.blend(raw, p)).dropna(subset=["base"])
        m = metrics(df, df["base"])
        if best is None or m["mae"] < best[0]["mae"]:
            best = (m, p, df)
    m_base, p, df = best
    report["form_weights"] = {k: p[k] for k in ("w_last3", "w_season", "w_prev")}

    # 2) baselines
    naive_season = df["season_pir"].fillna(df["prev_pir"])
    report["baseline_season_avg"] = metrics(df, naive_season.fillna(0))
    report["baseline_prev_season"] = metrics(df, df["prev_pir"].fillna(df["season_pir"]).fillna(0))
    report["form_blend"] = m_base
    report["prior_context"] = metrics(df, model.xpir(df, p))

    # 3) honest out-of-sample check: fit on first half, test on second half
    mid = df["round"].median()
    tr, te = df[df["round"] <= mid], df[df["round"] > mid]
    p_half = copy.deepcopy(p)
    p_half["coef"] = fit(tr)
    report["oos_second_half"] = {
        "form_blend": metrics(te, te["base"]),
        "fitted_context": metrics(te, model.xpir(te, p_half)),
    }

    # 4) final coefficients on the full season (used for live predictions)
    p["coef"] = fit(df)
    report["fitted_context_insample"] = metrics(df, model.xpir(df, p))
    report["params"] = {k: p[k] for k in ("w_last3", "w_season", "w_prev", "coef")}

    if save:
        PUBLIC.mkdir(parents=True, exist_ok=True)
        (PUBLIC / "model_params.json").write_text(json.dumps(report, indent=2))
    return report


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("season", type=int)
    ap.add_argument("--save", action="store_true")
    a = ap.parse_args()
    print(json.dumps(run(a.season, a.save), indent=2))
