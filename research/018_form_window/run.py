"""R&D 018 — a form window: does a mid-length recent average (8-10 games) help the form blend?

Side finding of 017: replacing the season average by the average since a date (<= 10 team games)
cut the error by ~0.15-0.19 for every team. But that average counted a game the player missed as 0,
while the model's season average only counts the games he was on the box score. So two effects are
mixed up, and they are tested apart:

  a  recent form     mean PIR of his last N appearances (N = 8, 10), a 4th term of the blend
  b  absences as 0   the same over his team's last N games (missed = 0), a 4th term of the blend

The catch for (b): in the live app who is out is known (injury list, news) and set to 0. So the test
that matters is with absences known: players not on the box score predicted 0, errors on the rest.
Weights: the 4th term's weight w from a grid, chosen on one season by MAE (004: choosing by squad
points overfits), judged on the other on MAE, MAE of the players who matter and squad points.

python research/018_form_window/run.py -> result.json
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
NS = [8, 10]
WS = [0.0, 0.1, 0.2, 0.35, 0.5, 0.75]


def windows(df: pd.DataFrame, season: int) -> pd.DataFrame:
    """Per (round, person_id): app_N (last N appearances) and team_N (last N team games, missed = 0)."""
    games = history.load("games", season)
    games["utc"] = pd.to_datetime(games["utc"])
    pl = history.load("players", season).merge(games[["gamecode", "utc"]], on="gamecode").sort_values("utc")
    pl["person_id"] = pl["person_id"].astype(str)
    rs = games[(games["phase"] == "RS") & games["played"]]
    starts = rs.groupby("round")["utc"].min()
    team_games = pd.concat([games[["gamecode", "utc", "home"]].rename(columns={"home": "team"}),
                            games[["gamecode", "utc", "away"]].rename(columns={"away": "team"})])
    team_games = team_games[games.set_index("gamecode").loc[team_games["gamecode"], "played"].to_numpy()]
    out = []
    for r in sorted(df["round"].unique()):
        cp = pl[pl["utc"] < starts[r]]
        tg = team_games[team_games["utc"] < starts[r]].sort_values("utc")
        g = cp.groupby("person_id")
        f = pd.DataFrame({f"app_{n}": g["pir"].apply(lambda s, n=n: s.tail(n).mean()) for n in NS})
        # team games since he joined his current team (missed = 0)
        team = g["team"].last()
        first = cp.groupby(["person_id", "team"])["utc"].min()
        pir = cp.set_index(["person_id", "gamecode"])["pir"]
        rows = {n: {} for n in NS}
        for pid, t in team.items():
            codes = tg.loc[(tg["team"] == t) & (tg["utc"] >= first[(pid, t)]), "gamecode"].tolist()
            for n in NS:
                last = codes[-n:]
                rows[n][pid] = sum(float(pir.get((pid, c), 0.0)) for c in last) / len(last) if last else np.nan
        for n in NS:
            f[f"team_{n}"] = pd.Series(rows[n])
        out.append(f.assign(round=r).reset_index())
    return pd.concat(out, ignore_index=True)


def predict(df: pd.DataFrame, col: str | None, w: float) -> pd.Series:
    """The live blend plus a 4th term `col` with weight w (renormalised like the others)."""
    if not col or w == 0:
        return _lib.predict(df, P)
    wp_eff = P["w_prev"] * P["prev_decay_k"] / (P["prev_decay_k"] + df["games"].fillna(0))
    parts = [(P["w_last3"], df["last3_pir"]), (P["w_season"], df["season_pir"]), (wp_eff, df["prev_pir"]),
             (w, df[col])]
    num = sum(wt * v.fillna(0) for wt, v in parts)
    den = sum(wt * v.notna() for wt, v in parts)
    d = df.assign(base=(num / den.replace(0, np.nan)).fillna(0.0))
    return model.fantasy_points(model.xpir(d, P).clip(lower=0), d["margin"])


def metrics(df: pd.DataFrame, pred: pd.Series) -> dict:
    """Absences known, as live: the absent are predicted 0 (no error there); errors on the dressed."""
    known = pred.where(df["dressed"], 0.0)
    d = df["dressed"]
    err = (pred[d] - df.loc[d, "fpts"]).abs()
    top = pred[d] >= 12
    squad = sum(_lib.squad_points(g, known.loc[g.index]) for _, g in df.groupby("round"))
    return {"mae": round(float(err.mean()), 4), "mae_top": round(float(err[top].mean()), 4),
            "squad": round(float(squad), 1)}


def main():
    res = {"seasons": {}}
    for s in (2024, 2025):
        df = _lib.build(s, P)
        df["person_id"] = df["person_id"].astype(str)
        df = df.merge(windows(df, s), on=["round", "person_id"], how="left").set_index(df.index)
        r = {"baseline": metrics(df, predict(df, None, 0))}
        for kind in ("app", "team"):
            for n in NS:
                for w in WS[1:]:
                    r[f"{kind}_{n}_w{w}"] = metrics(df, predict(df, f"{kind}_{n}", w))
        res["seasons"][s] = r
        print(s, json.dumps(r, indent=1))
    res["out_of_sample"] = {}
    for train, test in ((2024, 2025), (2025, 2024)):
        for kind in ("app", "team"):
            cand = {k: v for k, v in res["seasons"][train].items() if k.startswith(kind + "_")}
            best = min(cand, key=lambda k: cand[k]["mae"])
            res["out_of_sample"][f"{test}_{kind}"] = {"chosen_on": train, "variant": best,
                                                     "baseline": res["seasons"][test]["baseline"],
                                                     "with": res["seasons"][test][best]}
    (HERE / "result.json").write_text(json.dumps(res, indent=1))
    print(json.dumps(res["out_of_sample"], indent=1))


if __name__ == "__main__":
    main()
