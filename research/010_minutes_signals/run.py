"""R&D 010 — where do the minutes go? Three signals the model does not use yet.

  a  teammate absence: a regular (15+ min a game) is not on the box score; his minutes go to
     the others - mostly the same position, some to the rest.
       a_pos  = absent minutes of the same position x the player's share of that position's
                minutes x his PIR per minute (plus the same for other positions, fitted apart)
       a_all  = the same, ignoring positions (share of all the team's minutes)
  b  role change: started both of his last 2 games after starting < 40% before (up), or
     the reverse (down); and his minutes trend (last 2 vs season) x PIR per minute
  e  rotation depth: players averaging 10+ min on his team, for fringe players (< 15 min)

Each signal is fitted on the model's error (actual PIR - predicted) over the first half of
2025-26 and judged out of sample on its second half and on all of 2024-25 (players who played).
Then a squad test: predictions that already know who is out (absent players -> 0, as the live
pipeline does from the game and the news) with and without the teammate-absence signal.

Caveat: absences come from the box score (hindsight). Most are known before tip-off (injury
lists), some are late calls, so the gain measured for (a) is an upper bound.

python research/010_minutes_signals/run.py   (~5 min) -> result.json
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
from elf import history, model  # noqa: E402
from elf.config import MODEL  # noqa: E402

LIVE = json.loads((_lib.ROOT / "data/public/model_params.json").read_text())["params"]
P = {**copy.deepcopy(MODEL), **{k: LIVE[k] for k in ("w_last3", "w_season", "w_prev", "coef")}}
REGULAR_MIN = 15.0


def features(season):
    df = _lib.build(season, P)
    d = df.assign(base=model.blend(df, P).fillna(0.0))
    df["xpir"] = model.xpir(d, P).clip(lower=0)
    df["fpred"] = _lib.predict(df, P)
    games = history.load("games", season)
    games["utc"] = pd.to_datetime(games["utc"])
    pl = history.load("players", season).merge(games[["gamecode", "utc"]], on="gamecode").sort_values("utc")
    rs = games[(games["phase"] == "RS") & games["played"]]
    rows = []
    for r, g in df.groupby("round"):
        t0 = rs.loc[rs["round"] == r, "utc"].min()
        cp = pl[pl["utc"] < t0]
        s = cp.groupby("person_id").agg(avg_min=("min", "mean"), n=("min", "size"), pir_sum=("pir", "sum"),
                                        mins=("min", "sum"), starts=("starter", "mean"))
        s["ppm"] = (s["pir_sum"] / s["mins"].replace(0, np.nan)).fillna(0).clip(0, 1.5)
        last2 = cp.groupby("person_id").tail(2).groupby("person_id").agg(l2_start=("starter", "sum"), l2_min=("min", "mean"))
        prev = cp.groupby("person_id").apply(lambda x: x.iloc[:-2]["starter"].mean() if len(x) > 2 else np.nan,
                                             include_groups=False).rename("start_before")
        s = s.join(last2).join(prev).drop(columns=["pir_sum", "mins"])
        g = g.join(s, on="person_id")
        g[["avg_min", "ppm", "n"]] = g[["avg_min", "ppm", "n"]].fillna(0)
        reg = (g["avg_min"] >= REGULAR_MIN) & (g["n"] >= 3)
        for team, tg in g.groupby("team"):
            dressed = tg[tg["dressed"]]
            absent = tg[~tg["dressed"] & reg[tg.index]]
            tot_all = dressed["avg_min"].sum()
            depth = int(((tg["avg_min"] >= 10) & (tg["n"] >= 3)).sum())
            for i, x in dressed.iterrows():
                same = dressed[dressed["position"] == x.position]["avg_min"].sum()
                a_same = absent.loc[absent["position"] == x.position, "avg_min"].sum()
                a_other = absent.loc[absent["position"] != x.position, "avg_min"].sum()
                sh_same = x.avg_min / same if same > 0 else 0
                sh_all = x.avg_min / tot_all if tot_all > 0 else 0
                up = (x.l2_start == 2) and (x.start_before < 0.4) if pd.notna(x.start_before) else False
                down = (x.l2_start == 0) and (x.start_before > 0.6) if pd.notna(x.start_before) else False
                trend = (x.l2_min - x.avg_min) if pd.notna(x.l2_min) else 0.0
                rows.append({"idx": i, "a_pos_same": a_same * sh_same * x.ppm, "a_pos_other": a_other * sh_all * x.ppm,
                             "a_all": (a_same + a_other) * sh_all * x.ppm, "n_absent": len(absent),
                             "b_up": float(up), "b_down": float(down), "b_trend": trend * x.ppm,
                             "depth": depth, "fringe": float(x.avg_min < REGULAR_MIN)})
    f = pd.DataFrame(rows).set_index("idx")
    df = df.join(f)
    df["e_depth"] = (df["depth"] - df["depth"].mean()) * df["fringe"]
    return df


SETS = {
    "a_position": ["a_pos_same", "a_pos_other"],
    "a_no_position": ["a_all"],
    "b_role": ["b_up", "b_down", "b_trend"],
    "e_depth": ["e_depth"],
    "a+b+e": ["a_pos_same", "a_pos_other", "b_up", "b_down", "b_trend", "e_depth"],
}


def fit(d, cols):
    X = np.column_stack([np.ones(len(d))] + [d[c].fillna(0).to_numpy() for c in cols])
    y = (d["pir"] - d["xpir"]).to_numpy()
    beta, *_ = np.linalg.lstsq(X, y, rcond=None)
    res = y - X @ beta
    s2 = res @ res / (len(y) - X.shape[1])
    se = np.sqrt(np.diag(s2 * np.linalg.inv(X.T @ X)))
    return beta, se


def adjusted(d, cols, beta):
    X = np.column_stack([np.ones(len(d))] + [d[c].fillna(0).to_numpy() for c in cols])
    return pd.Series(d["xpir"].to_numpy() + X @ beta, index=d.index).clip(lower=0)


def err(y, pred):
    e = y - pred
    return {"mae": round(float(e.abs().mean()), 3), "rmse": round(float(np.sqrt((e ** 2).mean())), 3)}


data = {s: features(s) for s in (2025, 2024)}
d25 = data[2025]
mid = d25["round"].median()
train = d25[(d25["round"] <= mid) & d25["dressed"]]
tests = {"2025 second half": d25[(d25["round"] > mid) & d25["dressed"]], "2024 all": data[2024][data[2024]["dressed"]]}
out = {"train_rows": len(train), "share_rows_with_absent_teammate": round(float((train["n_absent"] > 0).mean()), 3),
       "share_role_up": round(float(train["b_up"].mean()), 3), "share_role_down": round(float(train["b_down"].mean()), 3)}
b0, _ = fit(train, [])
for name, cols in SETS.items():
    beta, se = fit(train, cols)
    r = {"coef": {c: [round(float(b), 3), round(float(s), 3)] for c, b, s in zip(["const"] + cols, beta, se)}}
    for tn, te in tests.items():
        base_err = err(te["pir"], adjusted(te, [], b0))
        new_err = err(te["pir"], adjusted(te, cols, beta))
        r[tn] = {"baseline": base_err, "with": new_err, "mae_change": round(new_err["mae"] - base_err["mae"], 3)}
    out[name] = r

# squad test on the second half of each season: absences known in both, (a+b+e) only in one
squad = {}
for s, d in data.items():
    m = d["round"].median()
    tr = d[(d["round"] <= m) & d["dressed"]]
    te = d[d["round"] > m]
    beta, _ = fit(tr, SETS["a+b+e"])
    bonus = (te["fpred"] / te["xpir"].replace(0, np.nan)).fillna(1.0)
    known = te["fpred"].where(te["dressed"], 0.0)                     # who is out is known
    withsig = (adjusted(te, SETS["a+b+e"], beta) * bonus).where(te["dressed"], 0.0)
    pk, ps = [], []
    for _, g in te.groupby("round"):
        pk.append(_lib.squad_points(g, known[g.index]))
        ps.append(_lib.squad_points(g, withsig[g.index]))
    diff = np.array(ps) - np.array(pk)
    squad[s] = {"absences_known": round(float(np.mean(pk)), 1), "plus_minutes_signals": round(float(np.mean(ps)), 1),
                "diff_per_round": round(float(diff.mean()), 1), "diff_se": round(float(diff.std(ddof=1) / np.sqrt(len(diff))), 1)}
out["squad_points_second_half"] = squad
(HERE / "result.json").write_text(json.dumps(out, indent=1))
print(json.dumps(out, indent=1))
