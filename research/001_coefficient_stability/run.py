"""R&D 001 — are the model's parameters stable?

(1) the 2024-25 backtest against 2025-26, (2) the parameters fitted on each third of
2025-26, (3) does adding 2024-25 help predict the second half of 2025-26 out of sample?

python research/001_coefficient_stability/run.py   (needs data/history 2023-2025; ~5 min)
writes result.json next to this file.
"""
import copy
import itertools
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1]))
from elf import backtest as bt, model  # noqa: E402
from elf.config import MODEL  # noqa: E402

GRID = [(a, b, c) for a, b, c in itertools.product([0.0, 0.1, 0.2, 0.35, 0.5], [0.2, 0.35, 0.5],
                                                   [0.1, 0.2, 0.35, 0.5, 0.75, 1.0, 1.5])]


def best_form(raw):
    best = None
    for w3, ws, wp in GRID:
        p = copy.deepcopy(MODEL)
        p.update(w_last3=w3, w_season=ws, w_prev=wp)
        df = raw.assign(base=model.blend(raw, p)).dropna(subset=["base"])
        m = bt.metrics(df, df["base"])
        if best is None or m["mae"] < best[0]["mae"]:
            best = (m, p, df)
    return best


def norm(w):  # weights as shares, to compare
    s = w["w_last3"] + w["w_season"] + w["w_prev"]
    return {k: round(w[k] / s, 2) for k in ("w_last3", "w_season", "w_prev")}


def coefs(c):
    return {k: round(v, 3) for k, v in c.items()}


out = {}
raw = {s: bt.walk_forward(s, copy.deepcopy(MODEL)) for s in (2024, 2025)}
for s in (2024, 2025):
    m, p, df = best_form(raw[s])
    c = bt.fit(df)
    p2 = copy.deepcopy(p); p2["coef"] = c
    out[s] = {"n": len(df), "rounds": int(df["round"].nunique()), "form": norm(p), "form_mae": m["mae"],
              "coef": coefs(c), "ctx_mae_insample": bt.metrics(df, model.xpir(df, p2))["mae"],
              "season_avg_mae": bt.metrics(df, df["season_pir"].fillna(df["prev_pir"]).fillna(0))["mae"]}
    out[s]["_p"], out[s]["_df"] = p, df

# (2) thirds of 2025: form weights and context coefficients per third
df25, p25 = out[2025]["_df"], out[2025]["_p"]
r = sorted(df25["round"].unique())
cuts = np.array_split(r, 3)
thirds = []
for i, rr in enumerate(cuts):
    sub_raw = raw[2025][raw[2025]["round"].isin(rr)]
    m, p, sub = best_form(sub_raw)
    sub_fixed = df25[df25["round"].isin(rr)]
    thirds.append({"rounds": f"{rr[0]}-{rr[-1]}", "n": len(sub_fixed), "form": norm(p),
                   "coef": coefs(bt.fit(sub_fixed))})
out["thirds_2025"] = thirds

# (3) out of sample on 2025 second half: coefficients from (a) 2025 first half, (b) 2024 only,
# (c) 2024 + 2025 first half pooled, (d) none (form blend only)
mid = df25["round"].median()
tr, te = df25[df25["round"] <= mid], df25[df25["round"] > mid]
df24 = out[2024]["_df"]
res = {}
for name, fit_df in (("fit_2025_first_half", tr), ("fit_2024_only", df24),
                     ("fit_2024_plus_2025_first_half", pd.concat([df24, tr]))):
    p = copy.deepcopy(p25); p["coef"] = bt.fit(fit_df)
    res[name] = {**bt.metrics(te, model.xpir(te, p)), "coef": coefs(p["coef"])}
res["form_blend_only"] = bt.metrics(te, te["base"])
# the whole of 2025 predicted with 2024's fit vs 2025's own (in-sample) fit
p = copy.deepcopy(p25); p["coef"] = bt.fit(df24)
res["all_2025_with_2024_fit"] = bt.metrics(df25, model.xpir(df25, p))
out["oos_2025_second_half"] = res

for s in (2024, 2025):
    del out[s]["_p"], out[s]["_df"]
(HERE / "result.json").write_text(json.dumps(out, indent=1, default=str))
print(json.dumps(out, indent=1, default=str))
