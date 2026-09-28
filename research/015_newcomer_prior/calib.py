"""R&D 015, part 2 — is there a bias, and can a fitted regression to the mean fix it?

Calibration: for newcomers (no EuroLeague last season) with g = 1, 2, 3, 4-5 games so far,
mean predicted vs mean actual fantasy points, by predicted level. Then a fitted correction,
    pred_new = a_g + b_g * pred,   fitted per games bucket on one season, applied to the other,
judged by the error on newcomers and the points of the best squad (rounds 2-8).
"""
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import _lib  # noqa: E402
from elf import model  # noqa: E402

_lib.MIN_ROUND = 2
P = model.params()


def bucket(g):
    return np.select([g <= 1, g == 2, g == 3, g <= 5], ["1", "2", "3", "4-5"], "6+")


def main():
    out = {"calibration": {}, "fit": {}, "out_of_sample": {}}
    data = {}
    for s in (2024, 2025):
        df = _lib.build(s, P)
        df["pred"] = _lib.predict(df, P)
        df["new"] = df["prev_pir"].isna()
        df["gb"] = bucket(df["games"].fillna(0))
        data[s] = df
        cal = {}
        for (new, gb), g in df.groupby(["new", "gb"]):
            hi = g[g["pred"] >= 12]
            cal[f"{'new' if new else 'returning'}_g{gb}"] = {
                "n": int(len(g)), "pred": round(g["pred"].mean(), 2), "actual": round(g["fpts"].mean(), 2),
                "n_pred12+": int(len(hi)), "pred12+": round(hi["pred"].mean(), 2) if len(hi) else None,
                "actual12+": round(hi["fpts"].mean(), 2) if len(hi) else None}
        out["calibration"][s] = cal
    # fitted correction for newcomers with <= 5 games, per bucket
    for train, test in ((2024, 2025), (2025, 2024)):
        tr, te = data[train], data[test].copy()
        fits = {}
        for gb in ("1", "2", "3", "4-5"):
            m = tr["new"] & (tr["gb"] == gb)
            b, a = np.polyfit(tr.loc[m, "pred"], tr.loc[m, "fpts"], 1)
            fits[gb] = (round(float(a), 3), round(float(b), 3))
        out["fit"][f"on_{train}"] = fits
        adj = te["pred"].copy()
        for gb, (a, b) in fits.items():
            m = te["new"] & (te["gb"] == gb)
            adj[m] = (a + b * te.loc[m, "pred"]).clip(lower=0)
        early = te["round"] <= 8
        newe = early & te["new"] & (te["gb"] != "6+")
        res = {}
        for name, pr in (("current", te["pred"]), ("corrected", adj)):
            err = (pr - te["fpts"]).abs()
            squad = sum(_lib.squad_points(g, pr.loc[g.index]) for _, g in te[early].groupby("round"))
            res[name] = {"mae_new_few_games": round(float(err[newe].mean()), 3),
                         "bias_new_few_games": round(float((pr - te["fpts"])[newe].mean()), 3),
                         "mae_all_early": round(float(err[early].mean()), 3),
                         "squad_early": round(float(squad), 1)}
        out["out_of_sample"][f"fit_{train}_test_{test}"] = res
    (HERE / "result_calibration.json").write_text(json.dumps(out, indent=1))
    print(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
