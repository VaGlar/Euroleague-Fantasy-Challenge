"""R&D 024 — the total PIR a defence allows (all positions together): does it add to the model?

The model already has, for the opponent: the PIR it allows to the player's position (pos_dev), the pace
of the game and the expected margin. The total allowed is mostly the sum of the positions, so it may add
nothing. Tested as a 7th context term (× base, like the others), shrunk to last season like pos_dev:
fitted on the first half of a season, judged on the second; two seasons (walk-forward, dressed players).

python research/024_total_defense/run.py   -> result.json
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
from elf import backtest as bt, history, model  # noqa: E402
from elf.config import MODEL  # noqa: E402

LIVE = json.loads((_lib.ROOT / "data/public/model_params.json").read_text())["params"]
P = {**MODEL, **{k: LIVE[k] for k in ("w_last3", "w_season", "w_prev", "coef")}}
K = MODEL["pos_shrink_k"]


def allowed(box: pd.DataFrame) -> pd.Series:
    """PIR per game a team's opponents scored against it, by team."""
    per = box.groupby(["gamecode", "team"])["pir"].sum().reset_index()
    opp = per.merge(per, on="gamecode", suffixes=("", "_o"))
    opp = opp[opp["team"] != opp["team_o"]]
    return opp.groupby("team")["pir_o"].agg(["mean", "size"])


def total_dev(season: int, df: pd.DataFrame) -> pd.Series:
    """For each row: the opponent's total PIR allowed vs the league, known before the round, shrunk
    to half of last season's (as pos_dev)."""
    games = history.load("games", season)
    games["utc"] = pd.to_datetime(games["utc"])
    box = history.load("players", season)
    prev = allowed(history.load("players", season - 1))
    out = pd.Series(0.0, index=df.index)
    for r, g in df.groupby("round"):
        start = games.loc[games["round"] == r, "utc"].min()
        before = set(games.loc[games["played"] & (games["utc"] < start), "gamecode"])
        cur = allowed(box[box["gamecode"].isin(before)]) if before else prev.iloc[:0]
        lg = pd.concat([cur["mean"], prev["mean"]]).mean()
        dev = {}
        for t in set(g["opp"]):
            prior = (prev.loc[t, "mean"] / lg - 1) * 0.5 if t in prev.index else 0.0
            if t in cur.index:
                n, d = cur.loc[t, "size"], cur.loc[t, "mean"] / lg - 1
                dev[t] = (n * d + K * prior) / (n + K)
            else:
                dev[t] = prior
        out.loc[g.index] = g["opp"].map(dev).astype(float)
    return out


def fit7(df: pd.DataFrame, ridge: float = 50.0) -> np.ndarray:
    X = np.column_stack([model.design(df), df["tot_dev"].to_numpy() * df["base"].to_numpy()])
    y = (df["pir"] - df["base"]).to_numpy()
    return np.linalg.solve(X.T @ X + ridge * np.eye(X.shape[1]), X.T @ y)


def run(season: int) -> dict:
    df = bt.walk_forward(season, copy.deepcopy(P))
    df["base"] = model.blend(df, P)
    df = df.dropna(subset=["base"]).copy()
    df["tot_dev"] = total_dev(season, df)
    mid = df["round"].median()
    tr, te = df[df["round"] <= mid], df[df["round"] > mid]
    p6 = copy.deepcopy(P)
    p6["coef"] = bt.fit(tr)
    c7 = fit7(tr)
    pred7 = te["base"] + np.column_stack([model.design(te), te["tot_dev"] * te["base"]]) @ c7
    team = df.drop_duplicates(["round", "opp"])
    pos_mean = df.groupby(["round", "opp"])["pos_dev"].mean()
    return {"season": season, "n_test": int(len(te)),
            "corr_tot_vs_mean_pos_dev": round(float(np.corrcoef(
                team.set_index(["round", "opp"])["tot_dev"], pos_mean.loc[team.set_index(["round", "opp"]).index])[0, 1]), 3),
            "corr_tot_vs_pace": round(float(np.corrcoef(team["tot_dev"], team["pace_dev"])[0, 1]), 3),
            "current_6_terms": bt.metrics(te, model.xpir(te, p6)),
            "with_total_7_terms": {**bt.metrics(te, pd.Series(pred7, index=te.index)),
                                   "coef_total": round(float(c7[-1]), 3), "coef_pos": round(float(c7[1]), 3)}}


if __name__ == "__main__":
    res = [run(s) for s in (2024, 2025)]
    (HERE / "result.json").write_text(json.dumps(res, ensure_ascii=False, indent=1))
    print(json.dumps(res, ensure_ascii=False, indent=1))
