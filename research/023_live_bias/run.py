"""R&D 023 — this season's live predictions: the high ones run high. Why, and does a correction help?

The autopilot scores ~20 points/round under its own xFPT (R1–R4). The live log shows why: overall the
predictions are unbiased (−0.3), but players predicted 15+ bring 2–8 points less. 003 found no stable
overestimation in the backtest (+4% / −2%); the live pipeline has more than the backtest (participation,
the price «memory», the return factor, availability), so:

  A  live bias by level (x_pred at tip-off vs real points), and the plain average for the same rows:
     does the plain average overestimate them too (regression to the mean) or only the model?
  B  the backtest model (form × context, no live extras) on this season's rounds: same pattern?
  C  a correction fitted on rounds 1–3 and judged on rounds 4–5: error, bias of the top, and squad
     points with the real prices of that round (a fresh squad per round, as in 003/004)
  D  this season's rounds in the coefficients: last season alone vs last season + rounds ≤3
     (weighted), judged on rounds 4–5

python research/023_live_bias/run.py   -> result.json (prints a summary)
"""
import copy
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import _lib  # noqa: E402
from elf import backtest as bt, model, tracking  # noqa: E402
from elf.config import MODEL  # noqa: E402

SEASON = 2026
LIVE = json.loads((_lib.ROOT / "data/public/model_params.json").read_text())["params"]
P = {**MODEL, **{k: LIVE[k] for k in ("w_last3", "w_season", "w_prev", "coef")}}
EDGES = [0, 5, 10, 15, 20, 60]
TRAIN_MAX = 3          # fit on rounds <= 3, judge on the later ones


def by_level(d: pd.DataFrame, pred: str, act: str = "fp") -> list[dict]:
    b = pd.cut(d[pred], EDGES)
    g = d.assign(err=d[act] - d[pred]).groupby(b, observed=True)
    return [{"level": str(k), "n": int(len(x)), "pred": round(float(x[pred].mean()), 2),
             "actual": round(float(x[act].mean()), 2), "bias": round(float(x["err"].mean()), 2)}
            for k, x in g]


# ------------------------------------------------------------------ A: the live log
def live() -> pd.DataFrame:
    pts, games = tracking.actual_points(SEASON)
    log = pd.read_csv(_lib.ROOT / "data/public/pred_log.csv", dtype={"person_id": str})
    log = log[log["gamecode"].isin(games["gamecode"])]
    d = log.merge(pts[["gamecode", "person_id", "fp"]], on=["gamecode", "person_id"], how="left")
    d["dnp"] = d["fp"].isna()
    d["fp"] = d["fp"].fillna(0.0)
    pr = pd.read_csv(_lib.ROOT / "data/public/prices.csv", dtype={"person_id": str})
    pr = pr.rename(columns={"matchday": "round"})[["round", "person_id", "position", "price"]]
    return d.merge(pr, on=["round", "person_id"], how="left")


def part_a(d: pd.DataFrame) -> dict:
    top = pd.concat([g.nlargest(20, "x_pred") for _, g in d.groupby("round")])
    return {"n": int(len(d)), "rounds": sorted(int(r) for r in d["round"].unique()),
            "bias_all": round(float((d["fp"] - d["x_pred"]).mean()), 2),
            "model_by_level": by_level(d, "x_pred"),
            # the same rows (grouped by the model's level), measured against the plain average
            "naive_same_rows": [{"level": str(k), "naive": round(float(x["naive"].mean()), 2),
                                 "bias_naive": round(float((x["fp"] - x["naive"]).mean()), 2)}
                                for k, x in d.groupby(pd.cut(d["x_pred"], EDGES), observed=True)],
            "top20_per_round": {"pred": round(float(top["x_pred"].mean()), 2),
                                "actual": round(float(top["fp"].mean()), 2),
                                "naive": round(float(top["naive"].mean()), 2),
                                "dnp": round(float(top["dnp"].mean()), 3)}}


# ------------------------------------------------------------------ B: the backtest model, this season
def part_b() -> dict:
    df = _lib.build(SEASON)
    df["pred"] = _lib.predict(df, P)
    dressed = df[df["dressed"]]
    return {"rounds": sorted(int(r) for r in df["round"].unique()),
            "all_pool": by_level(df, "pred", "fpts"), "dressed_only": by_level(dressed, "pred", "fpts"),
            "bias_all": round(float((df["fpts"] - df["pred"]).mean()), 2)}


# ------------------------------------------------------------------ C: a correction, fit early, judged late
def squad(rnd: pd.DataFrame, pred: pd.Series) -> float:
    r = rnd.dropna(subset=["position", "price"]).rename(columns={"fp": "fpts"})
    r = r[r["position"] != "Head Coach"]
    return _lib.squad_points(r, pred.loc[r.index])


def part_c(d: pd.DataFrame) -> dict:
    tr, te = d[d["round"] <= TRAIN_MAX], d[d["round"] > TRAIN_MAX]
    b, a = np.polyfit(tr["x_pred"], tr["fp"], 1)
    # «shrink the top»: above k, only a share s of the excess counts (fit k, s on the early rounds)
    best = None
    for k in (8, 10, 12, 15):
        for s in (0.5, 0.6, 0.7, 0.8, 0.9, 1.0):
            x = np.where(tr["x_pred"] > k, k + s * (tr["x_pred"] - k), tr["x_pred"])
            e = float(np.abs(tr["fp"] - x).mean())
            if best is None or e < best[0]:
                best = (e, k, s)
    _, k, s = best
    cands = {"raw": te["x_pred"], "linear": a + b * te["x_pred"],
             "shrink_top": pd.Series(np.where(te["x_pred"] > k, k + s * (te["x_pred"] - k), te["x_pred"]),
                                     index=te.index)}
    out = {"fit": {"linear": {"a": round(float(a), 2), "b": round(float(b), 3)}, "shrink_top": {"k": k, "s": s}},
           "test_rounds": sorted(int(r) for r in te["round"].unique())}
    for name, x in cands.items():
        t = te.assign(xc=x)
        top = pd.concat([g.nlargest(20, "xc") for _, g in t.groupby("round")])
        out[name] = {"mae": round(float((t["fp"] - t["xc"]).abs().mean()), 3),
                     "top20_bias": round(float((top["fp"] - top["xc"]).mean()), 2),
                     "squad_points": {int(r): round(squad(g, g["xc"]), 1) for r, g in t.groupby("round")}}
    return out


# ------------------------------------------------------------------ D: this season in the coefficients
def part_d() -> dict:
    prev = bt.walk_forward(SEASON - 1, copy.deepcopy(P))
    cur = bt.walk_forward(SEASON, copy.deepcopy(P))
    for df in (prev, cur):
        df["base"] = model.blend(df, P)
    prev, cur = prev.dropna(subset=["base"]), cur.dropna(subset=["base"])
    tr, te = cur[cur["round"] <= TRAIN_MAX], cur[cur["round"] > TRAIN_MAX]
    out = {"test_rounds": sorted(int(r) for r in te["round"].unique()), "n_test": int(len(te)),
           "live_coef": bt.metrics(te, model.xpir(te, P)), "form_only": bt.metrics(te, te["base"])}
    for w in (1, 3, 5):
        both = pd.concat([prev] + [tr] * w, ignore_index=True)
        p = copy.deepcopy(P)
        p["coef"] = bt.fit(both)
        out[f"prev+cur_x{w}"] = {**bt.metrics(te, model.xpir(te, p)),
                                 "coef": {k: round(v, 3) for k, v in p["coef"].items()}}
    return out


# ------------------------------------------------------------------ E: how fast last season fades
def part_e(early: int = 8) -> dict:
    """The blend already fades last season with this season's games (w_prev · k / (k + games)). Early in a
    season, is it fading too fast? Rounds <= `early` of three seasons; the top 20 per round matter most."""
    out = {}
    for season in (SEASON - 2, SEASON - 1, SEASON):
        raw = bt.walk_forward(season, copy.deepcopy(P))
        raw = raw[raw["round"] <= early]
        rows = {}
        for k in (2, 4, 6, 10, 15, 25):
            p = copy.deepcopy(P)
            p["prev_decay_k"] = k
            df = raw.assign(base=model.blend(raw, p)).dropna(subset=["base"])
            pred = model.xpir(df, p)
            top = pd.concat([g.nlargest(20, "pred") for _, g in df.assign(pred=pred).groupby("round")])
            rows[k] = {**bt.metrics(df, pred), "top20_bias": round(float((top["pir"] - top["pred"]).mean()), 2)}
        out[season] = rows
    return out


# ------------------------------------------------------------------ F: an early-season correction, judged on squads
def _shrink(x, k, s):
    return np.where(x > k, k + s * (x - k), x)


def part_f(early: int = 8) -> dict:
    """Shrink the predictions above k by a share s (fewer points for the top) in rounds <= `early` only.
    Fitted on one past season's early rounds (min error of the dressed), judged on the other: error and
    squad points with a budget (the whole pool, absences score 0)."""
    data = {}
    for season in (SEASON - 2, SEASON - 1):
        df = _lib.build(season)
        df = df[df["round"] <= early].copy()
        df["pred"] = _lib.predict(df, P)
        data[season] = df
    grid = [(k, s) for k in (8, 10, 12, 15) for s in (0.5, 0.6, 0.7, 0.8, 0.9, 1.0)]
    out = {}
    for fit_s, test_s in ((SEASON - 2, SEASON - 1), (SEASON - 1, SEASON - 2)):
        tr = data[fit_s][data[fit_s]["dressed"]]
        k, s = min(grid, key=lambda g: float(np.abs(tr["fpts"] - _shrink(tr["pred"], *g)).mean()))
        te = data[test_s]
        rows = {}
        for name, (kk, ss) in (("raw", (0, 1.0)), ("shrink", (k, s))):
            x = pd.Series(_shrink(te["pred"], kk, ss), index=te.index)
            sq = [_lib.squad_points(g, x.loc[g.index]) for _, g in te.groupby("round")]
            dressed = te["dressed"]
            rows[name] = {"mae_dressed": round(float((te.loc[dressed, "fpts"] - x[dressed]).abs().mean()), 3),
                          "squad_per_round": round(float(np.nanmean(sq)), 1), "rounds": len(sq)}
        rows["squad_diff"] = round(rows["shrink"]["squad_per_round"] - rows["raw"]["squad_per_round"], 1)
        out[f"fit{fit_s}_test{test_s}"] = {"k": k, "s": s, **rows}
    return out


if __name__ == "__main__":
    d = live()
    res = {"A_live": part_a(d), "B_backtest_model": part_b(), "C_correction": part_c(d), "D_refit": part_d(),
           "E_prev_decay": part_e(), "F_early_shrink": part_f()}
    (HERE / "result.json").write_text(json.dumps(res, ensure_ascii=False, indent=1))
    print(json.dumps(res, ensure_ascii=False, indent=1))
