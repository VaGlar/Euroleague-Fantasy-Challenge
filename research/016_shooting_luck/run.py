"""R&D 016 — shooting luck: is a hot (or cold) shooting stretch inflating the form?

PIR pays for every make: a made 2 is +3 against a miss (2 points, one missed shot fewer), a 3 is +4,
a free throw +2. Shooting percentages regress to the mean, so a player shooting well above his usual
level over a few games is probably over-rated by the form blend (and a cold shooter under-rated).

Luck-adjusted PIR of a game: the makes are replaced by the expected makes at the player's shrunk
percentage, per shot type t (2P, 3P, FT):
    p_hat_t = (M_t + k * p0_t) / (A_t + k)          M, A: his makes/attempts this season before the round
    pir_adj = pir - sum_t (m_t - a_t * p_hat_t) * value_t      value = 3 (2P), 4 (3P), 2 (FT)
Prior p0: his last-season percentage shrunk to the league's (100 attempts), else the league's.
k = 0 is the model as it is (no adjustment); large k = full regression to the prior.

The adjusted season / last-3 averages replace the plain ones in the form blend; the rest of the model
is unchanged. Walk-forward (only what was known before each round), k chosen on one season and judged
on the other, as in 003/004/015.

  mae       mean abs. error of fantasy points (everyone in the pool)
  mae_top   the same for the players the model rates >= 12 (the ones that matter for picks)
  squad     fantasy points of the best squad under the budget, summed over the season

python research/016_shooting_luck/run.py -> result.json
"""
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import _lib  # noqa: E402
from elf import history, model  # noqa: E402

P = model.params()
TYPES = {"2": ("fgm2", "fga2", 3.0), "3": ("fgm3", "fga3", 4.0), "ft": ("ftm", "fta", 2.0)}
KS = [0, 25, 50, 100, 200, 400, 1e9]


def priors(season: int) -> tuple[dict, pd.DataFrame]:
    """League percentage per shot type last season, and each player's last-season % shrunk to it."""
    prev = history.load("players", season - 1)
    league = {t: prev[m].sum() / prev[a].sum() for t, (m, a, _) in TYPES.items()}
    g = prev.groupby("person_id")[[c for m, a, _ in TYPES.values() for c in (m, a)]].sum()
    per = pd.DataFrame({t: (g[m] + 100 * league[t]) / (g[a] + 100) for t, (m, a, _) in TYPES.items()})
    return league, per


def adjusted_form(season: int, ks: list[float]) -> dict:
    """{k: DataFrame(round, person_id, season_adj, last3_adj)}: the form with luck-adjusted PIR."""
    games, box = history.load("games", season), history.load("players", season)
    league, per = priors(season)
    games = games.copy()
    games["utc"] = pd.to_datetime(games["utc"])
    rs = games[(games["phase"] == "RS") & games["played"]]
    out = {k: [] for k in ks}
    for r in sorted(rs["round"].unique()):
        if r < _lib.MIN_ROUND:
            continue
        start = rs.loc[rs["round"] == r, "utc"].min()
        before = set(games.loc[games["played"] & (games["utc"] < start), "gamecode"])
        cp = box[box["gamecode"].isin(before)].sort_values("gamecode")
        if cp.empty:
            continue
        tot = cp.groupby("person_id")[[c for m, a, _ in TYPES.values() for c in (m, a)]].sum()
        for k in ks:
            adj = cp["pir"].astype(float).copy()
            for t, (m, a, val) in TYPES.items():
                p0 = cp["person_id"].map(per[t]).fillna(league[t]) if t in per else league[t]
                M, A = cp["person_id"].map(tot[m]), cp["person_id"].map(tot[a])
                p_hat = (M + k * p0) / (A + k) if k < 1e8 else p0
                p_hat = p_hat.where(A + k > 0, league[t])
                adj = adj - (cp[m] - cp[a] * p_hat) * val
            d = cp.assign(adj=adj).groupby("person_id")["adj"]
            out[k].append(pd.DataFrame({"round": r, "season_adj": d.mean(),
                                        "last3_adj": d.apply(lambda s: s.tail(3).mean())}).reset_index())
    return {k: pd.concat(v, ignore_index=True) for k, v in out.items()}


def predict(df: pd.DataFrame, form: pd.DataFrame) -> pd.Series:
    d = df.merge(form, on=["round", "person_id"], how="left")
    d.index = df.index
    d["season_pir"] = d["season_adj"].fillna(d["season_pir"])
    d["last3_pir"] = d["last3_adj"].fillna(d["last3_pir"])
    return _lib.predict(d, P)


def metrics(df: pd.DataFrame, pred: pd.Series) -> dict:
    err = (pred - df["fpts"]).abs()
    top = pred >= 12
    squad = sum(_lib.squad_points(g, pred.loc[g.index]) for _, g in df.groupby("round"))
    return {"mae": round(float(err.mean()), 4), "mae_top": round(float(err[top].mean()), 4),
            "squad": round(float(squad), 1)}


def main():
    res = {"seasons": {}}
    for s in (2024, 2025):
        df = _lib.build(s, P)
        df["person_id"] = df["person_id"].astype(str)
        forms = adjusted_form(s, KS)
        base = _lib.predict(df, P)
        res["seasons"][s] = {"baseline": metrics(df, base)}
        for k, f in forms.items():
            f["person_id"] = f["person_id"].astype(str)
            res["seasons"][s][str(int(k) if k < 1e8 else "inf")] = metrics(df, predict(df, f))
        print(s, json.dumps(res["seasons"][s], indent=1))
    # choose k on one season (squad points, the decision that matters), judge it on the other
    res["out_of_sample"] = {}
    for train, test in ((2024, 2025), (2025, 2024)):
        cand = {k: v for k, v in res["seasons"][train].items() if k not in ("baseline", "0")}
        best = max(cand, key=lambda k: cand[k]["squad"])
        res["out_of_sample"][test] = {"k_from": train, "k": best, "baseline": res["seasons"][test]["baseline"],
                                      "adjusted": res["seasons"][test][best]}
    (HERE / "result.json").write_text(json.dumps(res, indent=1))
    print(json.dumps(res["out_of_sample"], indent=1))


if __name__ == "__main__":
    main()
