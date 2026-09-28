"""R&D 015 — players new to the EuroLeague: one game is not a level.

The form blend (last 3 / this season / last season) leans on last season. A player with no
EuroLeague last season has only this season's games, so after round 1 his "level" is one game
(Crowder: 25 PIR in round 1 -> expected 25 every round). Idea: shrink newcomers toward a prior,
    base = (g * blend + k * prior) / (g + k),   g = games played this season so far.

Prior without look-ahead: the mean PIR per game of the *other* season's newcomers, by position
(the live version would use the player's price, which carries more information, so the gain
measured here is a floor). k is chosen on one season and judged on the other (out of sample).

Judged from round 2 (the pool builder normally starts at 3):
  mae_new_early   mean abs. error of fantasy points, newcomers, rounds 2-8
  mae_all_early   everyone, rounds 2-8
  mae_all         everyone, whole season
  squad_early     fantasy points of the best squad under the budget, rounds 2-8 (sum)

python research/015_newcomer_prior/run.py -> result.json
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
from elf import model  # noqa: E402

_lib.MIN_ROUND = 2
P = model.params()
KS = [0, 1, 2, 3, 5, 8, 12]
EARLY = 8


def newcomer_prior(df: pd.DataFrame) -> dict:
    """Mean PIR per game (DNP = 0) of a season's newcomers over the whole season, by position."""
    last = df.sort_values("round").groupby("person_id").tail(1)
    new = df[df["prev_pir"].isna()]
    per_player = new.groupby(["person_id", "position"])["pir"].mean().reset_index()
    return per_player.groupby("position")["pir"].mean().to_dict()


def predict(df: pd.DataFrame, prior: dict, k: float) -> pd.Series:
    base = model.blend(df, P)
    if k > 0:
        g = df["games"].fillna(0)
        pr = df["position"].map(prior)
        new = df["prev_pir"].isna() & pr.notna()
        shr = (g * base.fillna(pr) + k * pr) / (g + k)
        base = base.where(~new, shr)
    d = df.assign(base=base.fillna(0.0))
    return model.fantasy_points(model.xpir(d, P).clip(lower=0), d["margin"])


def metrics(df, pred):
    err = (pred - df["fpts"]).abs()
    early = df["round"] <= EARLY
    new = df["prev_pir"].isna()
    squad = sum(_lib.squad_points(g.set_index(g.index), pred.loc[g.index])
                for _, g in df[early].groupby("round"))
    return {"mae_new_early": round(float(err[early & new].mean()), 3),
            "mae_all_early": round(float(err[early].mean()), 3),
            "mae_all": round(float(err.mean()), 3),
            "squad_early": round(float(squad), 1),
            "n_new_early": int((early & new).sum())}


def main():
    data = {s: _lib.build(s, P) for s in (2024, 2025)}
    priors = {s: newcomer_prior(d) for s, d in data.items()}
    out = {"priors": {s: {k: round(v, 2) for k, v in p.items()} for s, p in priors.items()}, "seasons": {}}
    for s, other in ((2024, 2025), (2025, 2024)):
        df = data[s]
        # the prior comes from the other season: nothing about this season leaks into it
        out["seasons"][s] = {str(k): metrics(df, predict(df, priors[other], k)) for k in KS}
    # choose k on one season by squad points early (the decision that matters), judge on the other
    pick = {}
    for train, test in ((2024, 2025), (2025, 2024)):
        res = out["seasons"][train]
        k = max(KS, key=lambda k: res[str(k)]["squad_early"])
        pick[f"train_{train}_test_{test}"] = {"k": k, "test": out["seasons"][test][str(k)],
                                              "test_current": out["seasons"][test]["0"]}
    out["out_of_sample"] = pick
    (HERE / "result.json").write_text(json.dumps(out, indent=1))
    print(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
