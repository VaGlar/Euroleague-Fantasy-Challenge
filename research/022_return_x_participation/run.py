"""R&D 022 — a player back from an absence: the return factor (012c, ×0.8) on top of participation (020).

Live, a player whose last 3 team games were all missed gets ×0.8 (returning) AND a participation factor
that counts that still-running absence as «left out of the twelve» (only a run that ended with him back
counts as an injury), e.g. 2 games then 3 out: (2 + 6·0.95) / (5 + 6) = 0.70. Together ≈ ×0.56–0.61, at
the moment he is worth buying. 012c fitted 0.8 before participation existed; 020 tested participation
without the return factor. This tests them together, as live (same rules as 020: an absence inside a
run of >= 3 games is known, predicted 0, no error; any other absence is not).

  A  participation only (020 as tested)
  B  live today: participation × 0.8 if returning
  C  participation that leaves a still-running absence of >= 3 games out (neither played nor
     available) × 0.8 if returning
  D/E  return factor refitted (0.5–1.0) with each participation

python research/022_return_x_participation/run.py -> result.json
"""
import importlib.util
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import _lib  # noqa: E402

spec = importlib.util.spec_from_file_location("r020", HERE.parent / "020_participation" / "run.py")
r020 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(r020)
P, K, P0, S = r020.P, 6.0, 0.95, 3


def features(df: pd.DataFrame, season: int) -> pd.DataFrame:
    games, tg, box = r020.sheets(season)
    tl = r020.timelines(tg, box)
    run = {k: r020.runs(v) for k, v in tl.items()}
    starts = games[(games["phase"] == "RS") & games["played"]].groupby("round")["utc"].min()
    rows = []
    for r in df.itertuples():
        t = tl.get((r.person_id, r.team), [])
        before = starts[r.round]
        past = [x for x in t if x[1] < before]
        app, avail = r020.counts(t, before, S)                      # live: a running absence = left out
        tail = 0
        for _, _, on in reversed(past):
            if on:
                break
            tail += 1
        neutral = avail - tail if tail >= S else avail              # a running absence of >= S: unknown
        rows.append({"idx": r.Index, "app": app, "avail": avail, "avail_n": neutral,
                     "returning": len(past) >= 3 and tail >= 3,
                     "injury_out": run.get((r.person_id, r.team), {}).get(r.gamecode, 0) >= S})
    d = df.join(pd.DataFrame(rows).set_index("idx"))
    d["released"] = r020.released(d, season)
    return d


def factor(app, avail):
    return ((app + K * P0) / (avail + K)).clip(0, 1)


def score(d: pd.DataFrame, pred: pd.Series) -> dict:
    m = r020.metrics(d, pred)
    known_out = (~d["dressed"] & d["injury_out"].fillna(False)) | d["released"].fillna(False)
    back = d["returning"] & ~known_out & d["dressed"]                # his first games back, on the sheet
    e = pred[back] - d.loc[back, "fpts"]
    top = back & (d["_base"] >= 10)                                 # the ones worth buying
    et = pred[top] - d.loc[top, "fpts"]
    return {**m, "n_back": int(back.sum()), "mae_back": round(float(e.abs().mean()), 3),
            "bias_back": round(float(e.mean()), 3), "n_back_top": int(top.sum()),
            "mae_back_top": round(float(et.abs().mean()), 3), "bias_back_top": round(float(et.mean()), 3)}


def main():
    res = {}
    for season in (2024, 2025):
        df = _lib.build(season, P)
        df["person_id"] = df["person_id"].astype(str)
        d = features(df, season)
        base = _lib.predict(d, P)
        d["_base"] = base
        f_live, f_neut = factor(d["app"], d["avail"]).fillna(1.0), factor(d["app"], d["avail_n"]).fillna(1.0)
        ret = d["returning"]
        r = {"A_participation_only": score(d, base * f_live),
             "B_live_x0.8": score(d, base * f_live * np.where(ret, 0.8, 1.0)),
             "C_neutral_run_x0.8": score(d, base * f_neut * np.where(ret, 0.8, 1.0))}
        for rf in (0.5, 0.6, 0.7, 0.8, 0.9, 1.0):
            r[f"D_live_rf{rf}"] = score(d, base * f_live * np.where(ret, rf, 1.0))
            r[f"E_neutral_rf{rf}"] = score(d, base * f_neut * np.where(ret, rf, 1.0))
        back = ret & d["dressed"]
        r["_effective_factor_on_returning"] = {
            "live": round(float((f_live * 0.8)[back].mean()), 3),
            "neutral": round(float((f_neut * 0.8)[back].mean()), 3),
            "actual_over_base": round(float(d.loc[back, "fpts"].sum() / base[back].sum()), 3)}
        res[season] = r
        print(season, json.dumps(r, indent=1))
    (HERE / "result.json").write_text(json.dumps(res, indent=1))


if __name__ == "__main__":
    main()
