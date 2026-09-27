"""R&D 009 — is the remaining error noise, or signal the model is missing?

Three diagnostics on 2025-26 (train: rounds 1-19, test: rounds 20-38), MAE and RMSE:

1. train vs test error: equal and high -> bias / missing information, not overfitting.
2. learning curve: the context fit on 10%..100% of the training rows. Flat -> more data of
   the same kind will not help.
3. ceilings with hindsight (not usable for predictions; they bound what is possible):
   a. each player's real average over the whole season  -> the best "player level" guess
   b. his real PIR per minute x the minutes he really played -> what knowing minutes is worth
   The gap current -> (a) is the room for estimating a player's level better; the gap
   (a) -> (b) is what only game-specific information (minutes, role, fouls...) can give.

python research/009_bias_or_noise/run.py   (~3 min) -> result.json
"""
import copy
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1]))
from elf import backtest as bt, history, model  # noqa: E402
from elf.config import MODEL  # noqa: E402

LIVE = json.loads((HERE.parents[1] / "data/public/model_params.json").read_text())["params"]
P = copy.deepcopy(MODEL)
P.update({k: LIVE[k] for k in ("w_last3", "w_season", "w_prev")})


def err(y, pred):
    e = y - pred
    return {"mae": round(float(e.abs().mean()), 3), "rmse": round(float(np.sqrt((e ** 2).mean())), 3)}


raw = bt.walk_forward(2025, copy.deepcopy(P))
df = raw.assign(base=model.blend(raw, P)).dropna(subset=["base"]).reset_index(drop=True)
tr, te = df[df["round"] <= 19], df[df["round"] > 19]
res = {"n_train": len(tr), "n_test": len(te)}

# 1. train vs test
p = copy.deepcopy(P); p["coef"] = bt.fit(tr)
res["train_vs_test"] = {"train": err(tr["pir"], model.xpir(tr, p)), "test": err(te["pir"], model.xpir(te, p)),
                        "test_form_only": err(te["pir"], te["base"])}

# 2. learning curve (5 random subsets per size)
rng = np.random.default_rng(0)
curve = {}
for frac in (0.05, 0.1, 0.25, 0.5, 1.0):
    maes = []
    for _ in range(5 if frac < 1 else 1):
        sub = tr.sample(frac=frac, random_state=int(rng.integers(1e9)))
        q = copy.deepcopy(P); q["coef"] = bt.fit(sub)
        maes.append(err(te["pir"], model.xpir(te, q))["mae"])
    curve[f"{int(frac * 100)}%"] = {"rows": int(len(tr) * frac), "test_mae": round(float(np.mean(maes)), 3)}
res["learning_curve"] = curve

# 3. hindsight ceilings on the test rounds
pl = history.load("players", 2025)
season_avg = pl.groupby("person_id")["pir"].mean()
tot = pl.groupby("person_id")[["pir", "min"]].sum()
per_min = (tot["pir"] / tot["min"].replace(0, np.nan)).fillna(0)
te = te.assign(true_avg=te["person_id"].map(season_avg), rate=te["person_id"].map(per_min))
res["ceilings_test"] = {
    "current_model": res["train_vs_test"]["test"],
    "a_true_season_average": err(te["pir"], te["true_avg"]),
    "b_true_rate_x_true_minutes": err(te["pir"], te["rate"] * te["min"]),
}
# spread of a player around his own season average (what no level estimate can remove)
res["within_player_sd"] = round(float((te["pir"] - te["true_avg"]).std()), 2)
res["between_player_sd"] = round(float(te["true_avg"].std()), 2)
(HERE / "result.json").write_text(json.dumps(res, indent=1))
print(json.dumps(res, indent=1))
