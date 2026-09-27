"""R&D 002 — does machine learning (gradient boosting) beat the current model?

Is any gain the algorithm's or the features' (minutes played)? Test: predict 2025-26
rounds 20-38, trained only on what was known before them (2024-25 + 2025-26 rounds 1-19),
same walk-forward features. Also checks the loss: a model trained on absolute error
predicts the median, which lowers MAE but under-states expected fantasy points.

pip install -r research/requirements.txt
python research/002_ml_gradient_boosting/run.py   (~5 min) -> result.json
"""
import copy
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.linear_model import Ridge

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1]))
from elf import backtest as bt, history, model  # noqa: E402
from elf.config import MODEL  # noqa: E402

P = copy.deepcopy(MODEL)
P.update(w_last3=0.1, w_season=0.35, w_prev=0.5)   # the live form weights


def walk(season):
    """backtest.walk_forward + minutes features known before each round."""
    games = history.load("games", season)
    players = history.load("players", season)
    teams = history.load("teams", season)
    prev_players, prev_teams = history.load("players", season - 1), history.load("teams", season - 1)
    pos_map = bt.pos_map_for(season)
    rs = games[(games["phase"] == "RS") & games["played"]].copy()
    rs["utc"] = pd.to_datetime(rs["utc"]); games["utc"] = pd.to_datetime(games["utc"])
    codes = sorted(set(rs["home"]) | set(rs["away"]))
    pm = prev_players.groupby("person_id")["min"].mean().rename("prev_min")
    out = []
    for r in sorted(rs["round"].unique()):
        fx = rs[rs["round"] == r]
        before = set(games.loc[games["played"] & (games["utc"] < fx["utc"].min()), "gamecode"])
        cp = players[players["gamecode"].isin(before)].sort_values("gamecode")
        ct = teams[teams["gamecode"].isin(before)]
        ratings = model.team_ratings(ct, prev_teams, codes, P)
        pdev = model.position_allowed(cp, prev_players, pos_map, P)
        base = model.player_base(cp, prev_players, P)
        g = cp.groupby("person_id")["min"]
        mins = pd.DataFrame({"season_min": g.mean(), "last3_min": g.apply(lambda s: s.tail(3).mean()),
                             "last_min": g.last()}).join(pm, how="outer")
        actual = players[players["gamecode"].isin(fx["gamecode"])]
        roster = actual[["person_id", "team"]].drop_duplicates()
        roster = roster.assign(position=roster["person_id"].map(pos_map))
        ctx = model.context_rows(fx, roster, ratings, pdev)
        ctx = ctx.merge(actual[["gamecode", "person_id", "pir"]], on=["gamecode", "person_id"])
        ctx = ctx.merge(base[["base", "last3_pir", "season_pir", "prev_pir", "games"]],
                        left_on="person_id", right_index=True, how="left")
        ctx = ctx.merge(mins, left_on="person_id", right_index=True, how="left")
        ctx["season"] = season
        out.append(ctx)
    df = pd.concat(out, ignore_index=True)
    for c in ["base", "last3_pir", "season_pir", "prev_pir", "games", "pir", "pos_dev", "pace_dev", "margin",
              "season_min", "last3_min", "last_min", "prev_min"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    return df.dropna(subset=["base"])


d = pd.concat([walk(2024), walk(2025)], ignore_index=True)
d["home"] = d["is_home"].astype(float)
for pos in ("Guard", "Forward", "Center"):
    d["is_" + pos] = (d["position"] == pos).astype(float)
test = (d["season"] == 2025) & (d["round"] > 19)
train = ~test & ~((d["season"] == 2025) & (d["round"] > 19))
tr, te = d[train], d[test]
res = {"n_train": int(len(tr)), "n_test": int(len(te))}

# current model: form blend + context, coefficients fitted on the training rows (ridge)
p = copy.deepcopy(P); p["coef"] = bt.fit(tr)
res["current_model"] = bt.metrics(te, model.xpir(te, p))
res["form_only"] = bt.metrics(te, te["base"])

BASIC = ["base", "last3_pir", "season_pir", "prev_pir", "games", "pos_dev", "pace_dev", "margin", "home",
         "is_Guard", "is_Forward", "is_Center"]
MINS = BASIC + ["season_min", "last3_min", "last_min", "prev_min"]


def gbm(cols, seed=0):
    m = HistGradientBoostingRegressor(loss="absolute_error", max_iter=400, learning_rate=0.04,
                                      max_leaf_nodes=15, min_samples_leaf=80, l2_regularization=1.0,
                                      random_state=seed)
    m.fit(tr[cols], tr["pir"])
    return pd.Series(m.predict(te[cols]), index=te.index).clip(lower=0)


def lin(cols):
    X = tr[cols].fillna(0); m = Ridge(alpha=10.0).fit(X, tr["pir"])
    return pd.Series(m.predict(te[cols].fillna(0)), index=te.index).clip(lower=0)


res["gbm_same_features"] = bt.metrics(te, gbm(BASIC))
res["gbm_plus_minutes"] = bt.metrics(te, gbm(MINS))
res["linear_plus_minutes"] = bt.metrics(te, lin(MINS))
res["gbm_plus_minutes_seed_spread"] = [bt.metrics(te, gbm(MINS, s))["mae"] for s in (1, 2)]


def gbm_loss(cols, loss):
    m = HistGradientBoostingRegressor(loss=loss, max_iter=400, learning_rate=0.04, max_leaf_nodes=15,
                                      min_samples_leaf=80, l2_regularization=1.0, random_state=0)
    m.fit(tr[cols], tr["pir"])
    return pd.Series(m.predict(te[cols]), index=te.index).clip(lower=0)


def extra(pred):
    """mean level (bias), RMSE, and the top-20 per round: what the model promised vs what they scored"""
    e = te["pir"] - pred
    top = pd.concat([x.nlargest(20, "pred") for _, x in te.assign(pred=pred).groupby("round")])
    return {"mean_pred": round(float(pred.mean()), 2), "mean_actual": round(float(te["pir"].mean()), 2),
            "rmse": round(float(np.sqrt((e ** 2).mean())), 3),
            "top20_pred": round(float(top["pred"].mean()), 2), "top20_actual": round(float(top["pir"].mean()), 2)}


checks = {"current_model": model.xpir(te, p), "gbm_minutes_squared_loss": gbm_loss(MINS, "squared_error"),
          "gbm_minutes_absolute_loss": gbm_loss(MINS, "absolute_error"), "linear_minutes": lin(MINS)}
res["loss_and_calibration"] = {k: {**bt.metrics(te, v), **extra(v)} for k, v in checks.items()}
(HERE / "result.json").write_text(json.dumps(res, indent=1))
print(json.dumps(res, indent=1))
