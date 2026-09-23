"""Price-change forecast ($ = likely to rise after this round).

Official rule: the change depends on the round score and the starting price (for the
same score a cheap player gains more). The exact formula is not published, so:

  * once prices.csv holds 2+ matchdays, we fit it from data:
        delta_price ~ b0 + b1 * points + b2 * price + b3 * points / price
    (points = the round's fantasy points from the box scores) and predict the change
    for this round from xPTS;
  * before that, a proxy: xPTS minus the xPTS the market "prices in" (a price -> xPTS
    line fitted across players). Well above the line = likely to rise.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from . import history
from .config import CURRENT_SEASON, PUBLIC, WIN_BONUS

RISE_CR = 0.3        # fitted model: flag if predicted change >= +0.3 cr
FALL_CR = -0.3
RISE_RESID = 3.0     # proxy: flag if xPTS beats the price line by 3+ points ...
RISE_REL = 0.30      # ... and by 30%+ of what the price implies (cheap players move more)
FALL_RESID = -3.0


def round_points(season: int = CURRENT_SEASON) -> pd.DataFrame:
    """Fantasy points per player per round from the box scores (PIR, +10% on a win)."""
    games = history.load("games", season)
    box = history.load("players", season)
    if games.empty or box.empty:
        return pd.DataFrame(columns=["person_id", "round", "points"])
    g = games[games["played"]]
    win = {}
    for r in g.itertuples():
        win[(r.gamecode, r.home)] = r.home_score > r.away_score
        win[(r.gamecode, r.away)] = r.away_score > r.home_score
    box = box.merge(g[["gamecode", "round"]], on="gamecode")
    box["points"] = box["pir"] * (1 + WIN_BONUS * box.apply(
        lambda r: win.get((r["gamecode"], r["team"]), False), axis=1))
    return box.groupby(["person_id", "round"], as_index=False)["points"].sum()


def fit_price_model():
    """Coefficients of delta_price ~ [1, pts, price, pts/price], or None if too little data."""
    path = PUBLIC / "prices.csv"
    if not path.exists():
        return None
    p = pd.read_csv(path, dtype={"person_id": str})
    if p["matchday"].nunique() < 2:
        return None
    p = p.sort_values("matchday")
    p["next_price"] = p.groupby("fantasy_id")["price"].shift(-1)
    p = p.dropna(subset=["next_price", "person_id"])
    pts = round_points()
    # prices of matchday m are set before round m is played; round number == matchday
    d = p.merge(pts, left_on=["person_id", "matchday"], right_on=["person_id", "round"],
                how="left")
    d["points"] = d["points"].fillna(0)  # did not play -> 0
    d = d[d["price"] > 0]
    if len(d) < 60:
        return None
    X = np.column_stack([np.ones(len(d)), d["points"], d["price"], d["points"] / d["price"]])
    y = (d["next_price"] - d["price"]).to_numpy()
    coef, *_ = np.linalg.lstsq(X, y, rcond=None)
    resid = y - X @ coef
    return {"coef": coef.tolist(), "n": int(len(d)), "rmse": float(np.sqrt(np.mean(resid ** 2)))}


def annotate(table: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    """Add price_delta (credits, fitted model only), price_resid (proxy) and
    price_trend ("up"/"down"/None). Returns (table, info about the method used)."""
    t = table.copy()
    t["price_delta"] = np.nan
    t["price_resid"] = np.nan
    t["price_trend"] = None
    ok = t["price"].notna() & t["x_now"].notna() & (t["position"] != "Head Coach")
    healthy = t.get("avail_game", pd.Series(1.0, index=t.index)).fillna(1.0) >= 1
    model = fit_price_model()
    if model:
        b = np.array(model["coef"])
        pr, x = t.loc[ok, "price"], t.loc[ok, "x_now"]
        t.loc[ok, "price_delta"] = b[0] + b[1] * x + b[2] * pr + b[3] * x / pr
        t.loc[ok & (t["price_delta"] >= RISE_CR) & healthy, "price_trend"] = "up"
        t.loc[ok & (t["price_delta"] <= FALL_CR), "price_trend"] = "down"
        return t, {"method": "fitted", **model}
    # proxy: residual vs the market's price -> xPTS line (players with data only)
    known = ok & ~t.get("no_data", pd.Series(False, index=t.index)).fillna(False) \
        & (t["x_now"] > 0)
    if known.sum() < 30:
        return t, {"method": "none"}
    slope, icpt = np.polyfit(t.loc[known, "price"], t.loc[known, "x_now"], 1)
    implied = (slope * t.loc[ok, "price"] + icpt).clip(lower=1.0)
    t.loc[ok, "price_resid"] = t.loc[ok, "x_now"] - implied
    rel = t["price_resid"] / (slope * t["price"] + icpt).clip(lower=1.0)
    t.loc[ok & (t["price_resid"] >= RISE_RESID) & (rel >= RISE_REL) & healthy
          & (t["x_now"] >= 5), "price_trend"] = "up"
    t.loc[ok & (t["price_resid"] <= FALL_RESID), "price_trend"] = "down"
    return t, {"method": "proxy", "slope": float(slope), "intercept": float(icpt)}
