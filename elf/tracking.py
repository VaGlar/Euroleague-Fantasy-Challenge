"""This season's accuracy, measured honestly: every pipeline run logs the prediction
for each game that has not started yet (the last one before tip-off wins), and once
the box score is in, it is compared with what really happened.

Files (data/public):
  pred_log.csv      round, gamecode, person_id, name, team, x_pred, naive, logged_at
  lineup_log.json   {matchday: {"suggested": {...}, "actual": {...}}} for my team
  tracking.json     the evaluation shown in the dashboard's Model tab
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

import numpy as np
import pandas as pd

from . import history
from .config import BENCH_MULTIPLIER, CAPTAIN_MULTIPLIER, COACH_POINTS, PUBLIC, WIN_BONUS

MIN_XPRED = 5.0  # evaluate fantasy-relevant players only (deep bench would flatter the MAE)
KEY = ["round", "gamecode", "person_id"]


def log_predictions(ctx: pd.DataFrame, now: datetime | None = None) -> None:
    """Upsert predictions for games that have not started yet (players, not coaches)."""
    now = now or datetime.now(timezone.utc)
    c = ctx[ctx["position"] != "Head Coach"].copy()
    c["utc"] = pd.to_datetime(c["utc"], utc=True)
    c = c[c["utc"] > now]
    if c.empty:
        return
    season = c["season_pir"] if "season_pir" in c else pd.Series(np.nan, index=c.index)
    prev = c["prev_pir"] if "prev_pir" in c else pd.Series(np.nan, index=c.index)
    new = pd.DataFrame({
        "round": c["round"].astype(int), "gamecode": c["gamecode"].astype(int),
        "person_id": c["person_id"].astype(str), "name": c["name"], "team": c["team"],
        "x_pred": c["xpir"].round(2),
        # the "no model" guess: this season's average so far, else last season's (+ avg win bonus)
        "naive": (season.fillna(prev).fillna(0) * (1 + WIN_BONUS / 2)).round(2),
        "logged_at": now.isoformat()})
    path = PUBLIC / "pred_log.csv"
    if path.exists():
        old = pd.read_csv(path, dtype={"person_id": str})
        old = old.merge(new[KEY], on=KEY, how="left", indicator=True)
        old = old[old["_merge"] == "left_only"].drop(columns="_merge")
        new = pd.concat([old, new], ignore_index=True)
    new.sort_values(KEY).to_csv(path, index=False)


def log_lineups(my: dict | None, rnd: int, md_number: int | None, started: bool) -> None:
    """Suggested lineup (frozen when the round starts) and the lineup actually set."""
    if not my or md_number is None:
        return
    path = PUBLIC / "lineup_log.json"
    log = json.loads(path.read_text()) if path.exists() else {}
    pid = {int(p["fantasy_id"]): (str(p["person_id"]), p["team"], p["position"])
           for p in my.get("players", []) if p.get("fantasy_id") == p.get("fantasy_id")}

    def snap(rows, key):
        return [{"id": int(r[key]), "person_id": pid.get(int(r[key]), (None,))[0],
                 "team": pid.get(int(r[key]), (None, None))[1], "position": r.get("position"),
                 "role": r["role"], "captain": bool(r["captain"])} for r in rows if r.get("role")]

    entry = log.setdefault(str(md_number), {})
    if my.get("lineup") and not started and int(md_number) == int(rnd):
        entry["suggested"] = snap(my["lineup"], "id")
    if my.get("actual_lineup"):
        entry["actual"] = snap(my["actual_lineup"], "fantasy_id")
    path.write_text(json.dumps(log, ensure_ascii=False, indent=1))


def actual_points(season: int) -> tuple[pd.DataFrame, pd.DataFrame]:
    """(players: round, gamecode, person_id, fp) and (games: played games of the season)."""
    games, box = history.load("games", season), history.load("players", season)
    if games.empty:
        return pd.DataFrame(columns=["round", "gamecode", "person_id", "fp"]), games
    games = games[games["played"]]
    if box.empty:
        return pd.DataFrame(columns=["round", "gamecode", "person_id", "fp"]), games
    b = box.merge(games[["gamecode", "round", "home", "home_score", "away_score"]], on="gamecode")
    won = np.where(b["team"] == b["home"], b["home_score"] > b["away_score"],
                   b["away_score"] > b["home_score"])
    b["fp"] = b["pir"] * np.where(won, 1 + WIN_BONUS, 1.0)
    b["person_id"] = b["person_id"].astype(str)
    return b[["round", "gamecode", "person_id", "fp"]], games


def _coach_points(margin: float) -> float:
    return next((pts for lo, hi, pts in COACH_POINTS if lo < margin <= hi), 0.0)


def _rank_corr(a: pd.Series, b: pd.Series) -> float | None:
    if len(a) < 3:
        return None
    return float(np.corrcoef(a.rank(), b.rank())[0, 1])


def _metrics(d: pd.DataFrame) -> dict:
    top = min(20, len(d))
    hit = len(set(d.nlargest(top, "x_pred").index) & set(d.nlargest(top, "fp").index)) / top \
        if top else None
    return {"n": int(len(d)),
            "mae_model": round(float((d["x_pred"] - d["fp"]).abs().mean()), 2),
            "mae_naive": round(float((d["naive"] - d["fp"]).abs().mean()), 2),
            "spearman": None if (r := _rank_corr(d["x_pred"], d["fp"])) is None else round(r, 3),
            "top20": None if hit is None else round(hit, 3)}


def evaluate(season: int) -> dict:
    out = {"generated": datetime.now(timezone.utc).isoformat(), "rounds": [], "total": None,
           "experts": [], "lineups": [], "min_xpred": MIN_XPRED}
    pts, games = actual_points(season)
    path = PUBLIC / "pred_log.csv"
    if path.exists() and not games.empty:
        log = pd.read_csv(path, dtype={"person_id": str})
        log = log[log["gamecode"].isin(games["gamecode"])]
        d = log.merge(pts[["gamecode", "person_id", "fp"]], on=["gamecode", "person_id"], how="left")
        d["fp"] = d["fp"].fillna(0.0)          # did not play = 0 fantasy points
        d = d[d["x_pred"] >= MIN_XPRED]
        for rnd, g in d.groupby("round"):
            out["rounds"].append({"round": int(rnd), **_metrics(g.reset_index(drop=True))})
        if len(d):
            out["total"] = _metrics(d.reset_index(drop=True))
    # fantasy columns: picked players' real points vs what the model expected for them
    ex_path = PUBLIC / "expert_log.csv"
    if ex_path.exists() and not pts.empty:
        ex = pd.read_csv(ex_path, dtype={"person_id": str})
        ex = ex[ex["stance"].isin(["pick", "captain"])]
        per_round = pts.groupby(["round", "person_id"], as_index=False)["fp"].sum()
        allg = history.load("games", season)
        done_rounds = {r for r, g in allg.groupby("round") if g["played"].all()}
        ex = ex[ex["round"].isin(done_rounds)].merge(per_round, on=["round", "person_id"], how="left")
        ex["fp"] = ex["fp"].fillna(0.0)
        for src, g in ex.groupby("source"):
            out["experts"].append({"source": src, "n": int(len(g)),
                                   "actual": round(float(g["fp"].mean()), 1),
                                   "model": round(float(g["model_xpts"].mean()), 1),
                                   "diff": round(float((g["fp"] - g["model_xpts"]).mean()), 1)})
    # my team: suggested lineup vs the lineup actually played, scored with real points
    lu_path = PUBLIC / "lineup_log.json"
    if lu_path.exists() and not games.empty:
        all_games = history.load("games", season)
        per_round = pts.groupby(["round", "person_id"])["fp"].sum()
        for md, e in sorted(json.loads(lu_path.read_text()).items(), key=lambda x: int(x[0])):
            rnd = int(md)
            rg = all_games[all_games["round"] == rnd]
            if rg.empty or not rg["played"].all() or "suggested" not in e or "actual" not in e:
                continue
            margin = {}
            for gm in rg.itertuples():
                margin[gm.home] = gm.home_score - gm.away_score
                margin[gm.away] = gm.away_score - gm.home_score

            def score(team):
                tot = 0.0
                for p in team:
                    if p["position"] == "Head Coach":
                        tot += _coach_points(margin.get(p["team"], 0))
                        continue
                    fp = float(per_round.get((rnd, p["person_id"]), 0.0))
                    mult = BENCH_MULTIPLIER if p["role"] == "πάγκος" else 1.0
                    tot += fp * mult * (CAPTAIN_MULTIPLIER if p["captain"] else 1)
                return round(tot, 1)
            s, a = score(e["suggested"]), score(e["actual"])
            out["lineups"].append({"round": rnd, "suggested": s, "actual": a,
                                   "diff": round(a - s, 1)})
    return out


def update(ctx: pd.DataFrame, season: int, my: dict | None, rnd: int,
           md_number: int | None, started: bool) -> dict:
    log_predictions(ctx)
    log_lineups(my, rnd, md_number, started)
    res = evaluate(season)
    (PUBLIC / "tracking.json").write_text(json.dumps(res, ensure_ascii=False, indent=1,
                                                     allow_nan=False))
    return res

