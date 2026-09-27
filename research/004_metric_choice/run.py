"""R&D 004 — are we choosing the model with the right yardstick?

The backtest picks the form weights by the lowest mean absolute error over every player.
Fantasy decisions care about something else: picking, under a 100-credit budget, the
players who score - stars and cheap fillers who actually play. Here the form weights are
chosen on the first half of a season by four yardsticks, then judged on the second half by
the fantasy points of the squads they would have picked.

  mae       mean absolute error (today's choice)
  rmse      squared error: rewards getting the mean (the upside) right
  tier_rho  ranking inside price tiers (4-6, 6-8, 8-10.5, 10.5+ credits)
  points    fantasy points of the best squad under the budget, every round

python research/004_metric_choice/run.py   (~15 min) -> result.json
"""
import copy
import itertools
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import _lib  # noqa: E402
from elf.config import MODEL  # noqa: E402

LIVE = json.loads((_lib.ROOT / "data/public/model_params.json").read_text())["params"]
GRID = [(a, b, c) for a, b, c in itertools.product([0.0, 0.1, 0.2, 0.35, 0.5], [0.2, 0.35, 0.5],
                                                   [0.1, 0.2, 0.35, 0.5, 0.75, 1.0, 1.5])]
TIERS = [4, 6, 8, 10.5, 99]


def params(w):
    p = copy.deepcopy(MODEL)
    p.update(w_last3=w[0], w_season=w[1], w_prev=w[2], coef=LIVE["coef"])
    return p


def tier_rho(d, pred):
    rho = []
    for _, g in d.assign(pred=pred, tier=pd.cut(d["price"], TIERS, right=False)).groupby(["round", "tier"], observed=True):
        if len(g) >= 15:
            rho.append(g["pred"].rank().corr(g["fpts"].rank()))
    return float(np.nanmean(rho))


def points_by_round(d, pred):
    return {int(r): _lib.squad_points(g, pred[g.index]) for r, g in d.groupby("round")}


def run(season):
    df = _lib.build(season)
    mid = df["round"].median()
    tr, te = df[df["round"] <= mid], df[df["round"] > mid]
    scores = []
    for w in GRID:
        pred = _lib.predict(tr, params(w))
        e = tr["fpts"] - pred
        pts = points_by_round(tr, pred)
        scores.append({"w": w, "mae": float(e.abs().mean()), "rmse": float(np.sqrt((e ** 2).mean())),
                       "tier_rho": tier_rho(tr, pred), "points": float(np.mean(list(pts.values())))})
    s = pd.DataFrame(scores)
    chosen = {"mae": s.loc[s["mae"].idxmin(), "w"], "rmse": s.loc[s["rmse"].idxmin(), "w"],
              "tier_rho": s.loc[s["tier_rho"].idxmax(), "w"], "points": s.loc[s["points"].idxmax(), "w"],
              "live (today)": (LIVE["w_last3"], LIVE["w_season"], LIVE["w_prev"])}
    ref = points_by_round(te, _lib.predict(te, params(chosen["live (today)"])))
    out = {"season": season, "rounds_train": f"{int(tr['round'].min())}-{int(mid)}",
           "rounds_test": f"{int(te['round'].min())}-{int(te['round'].max())}", "pool_per_round": round(len(df) / df["round"].nunique())}
    test = {}
    for name, w in chosen.items():
        pred = _lib.predict(te, params(w))
        pts = points_by_round(te, pred)
        diff = np.array([pts[r] - ref[r] for r in pts])
        e = te["fpts"] - pred
        test[name] = {"weights": [round(x, 2) for x in w], "points_per_round": round(float(np.mean(list(pts.values()))), 1),
                      "vs_live": round(float(diff.mean()), 1), "vs_live_se": round(float(diff.std(ddof=1) / np.sqrt(len(diff))), 1),
                      "mae": round(float(e.abs().mean()), 3), "rmse": round(float(np.sqrt((e ** 2).mean())), 3),
                      "tier_rho": round(tier_rho(te, pred), 3)}
    naive = te["season_pir"].fillna(te["prev_pir"]).fillna(0) * 1.05
    test["baseline: season average"] = {"points_per_round": round(float(np.mean(list(points_by_round(te, naive).values()))), 1)}
    test["hindsight (the best possible)"] = {"points_per_round": round(float(np.mean(list(points_by_round(te, te["fpts"]).values()))), 1)}
    out["test_second_half"] = test
    return out


res = {"price_fit": {k: [round(float(x), 2) for x in v] for k, v in _lib.price_mapping()[0].items()},
       "seasons": [run(2025), run(2024)]}
(HERE / "result.json").write_text(json.dumps(res, indent=1))
print(json.dumps(res, indent=1))
