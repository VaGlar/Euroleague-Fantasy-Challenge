"""R&D 003 — are the model's numbers too high for the players it rates best?

Experiment 002 found the top-20 per round predicted ~7% above what they scored (the
winner's curse: picking the highest predictions also picks the luckiest over-estimates).
Measured on players who were dressed: the live pipeline already handles injuries and
absences from the news and the game, the backtest cannot, so absences are left out here.

Fits on the first half of a season, judged on the second half:
  linear    xPTS' = a + b * xPTS         (display only: it cannot change a squad choice)
  isotonic  a monotone curve per level   (can change choices: checked with squad points)

pip install -r research/requirements.txt
python research/003_calibration/run.py   (~3 min) -> result.json
"""
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.isotonic import IsotonicRegression

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import _lib  # noqa: E402
from elf.config import MODEL  # noqa: E402

LIVE = json.loads((_lib.ROOT / "data/public/model_params.json").read_text())["params"]
P = {**MODEL, **{k: LIVE[k] for k in ("w_last3", "w_season", "w_prev", "coef")}}


def buckets(pred, act):
    q = pd.qcut(pred, 10, labels=False, duplicates="drop")
    t = pd.DataFrame({"pred": pred, "act": act, "q": q}).groupby("q").mean().round(2)
    return t.reset_index().to_dict("records")


def top20(d, pred):
    t = pd.concat([g.nlargest(20, "pred") for _, g in d.assign(pred=pred).groupby("round")])
    return {"pred": round(float(t["pred"].mean()), 2), "actual": round(float(t["fpts"].mean()), 2)}


def run(season):
    df = _lib.build(season)
    df["pred"] = _lib.predict(df, P)
    mid = df["round"].median()
    tr = df[(df["round"] <= mid) & df["dressed"]]
    te_all = df[df["round"] > mid]
    te = te_all[te_all["dressed"]]
    b, a = np.polyfit(tr["pred"], tr["fpts"], 1)
    iso = IsotonicRegression(out_of_bounds="clip").fit(tr["pred"], tr["fpts"])
    lin = a + b * te["pred"]
    isot = pd.Series(iso.predict(te["pred"]), index=te.index)
    out = {"season": season, "linear_fit": {"a": round(float(a), 2), "b": round(float(b), 3)}}
    for name, pred in (("raw", te["pred"]), ("linear", lin), ("isotonic", isot)):
        out[name] = {"top20": top20(te, pred), "mean_pred": round(float(pred.mean()), 2),
                     "mean_actual": round(float(te["fpts"].mean()), 2),
                     "rmse": round(float(np.sqrt(((te["fpts"] - pred) ** 2).mean())), 3),
                     "deciles": buckets(pred, te["fpts"])}
    # does the isotonic curve change squad choices for the better? (whole pool, absences score 0)
    raw_pts, iso_pts = [], []
    for _, g in te_all.groupby("round"):
        raw_pts.append(_lib.squad_points(g, g["pred"]))
        iso_pts.append(_lib.squad_points(g, pd.Series(iso.predict(g["pred"]), index=g.index)))
    d = np.array(iso_pts) - np.array(raw_pts)
    out["squad_points_per_round"] = {"raw": round(float(np.mean(raw_pts)), 1), "isotonic": round(float(np.mean(iso_pts)), 1),
                                     "diff": round(float(d.mean()), 1), "diff_se": round(float(d.std(ddof=1) / np.sqrt(len(d))), 1)}
    return out


res = [run(2025), run(2024)]
(HERE / "result.json").write_text(json.dumps(res, indent=1))
print(json.dumps(res, indent=1))
