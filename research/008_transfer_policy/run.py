"""R&D 008 — the transfer policy, tested over whole seasons.

The optimizer's settings were set by reasoning, not by data:
  horizon weights (1, .6, .35)   how much the next rounds count in a trade
  minimum gain 2.0 per trade     a trade must add this many weighted points
  up to 4 trades per round       (the game's limit; unlimited after rounds 6, 13, 18, 23, 28, 34)

Each policy plays a whole season from round 3: a best squad under the budget at the start,
then every round the transfers it would propose (same optimizer as the live pipeline), the
best five / sixth man / captain, and the fantasy points really scored (a player who did not
play scores 0). Predictions use only what was known before each round.

python research/008_transfer_policy/run.py   (~30-40 min) -> result.json
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
from elf import optimize  # noqa: E402
from elf.config import MODEL  # noqa: E402

LIVE = json.loads((_lib.ROOT / "data/public/model_params.json").read_text())["params"]
P = {**copy.deepcopy(MODEL), **{k: LIVE[k] for k in ("w_last3", "w_season", "w_prev", "coef")}}
UNLIMITED_AFTER = {6, 13, 18, 23, 28, 34}
BUDGET = 100.0 - _lib.COACH_PRICE
COACH = {"id": "coach", "position": "Head Coach", "price": 0.0, "x_h": 0.0, "x_now": 0.0}

POLICIES = {
    "current (1/.6/.35, gain 2, 4 trades)": dict(w=(1, .6, .35), gain=2.0, trades=4),
    "myopic: next round only": dict(w=(1, 0, 0), gain=2.0, trades=4),
    "flat: 3 rounds equal": dict(w=(1, 1, 1), gain=2.0, trades=4),
    "longer: 1/.8/.6": dict(w=(1, .8, .6), gain=2.0, trades=4),
    "min gain 0": dict(w=(1, .6, .35), gain=0.0, trades=4),
    "min gain 4": dict(w=(1, .6, .35), gain=4.0, trades=4),
    "min gain 6": dict(w=(1, .6, .35), gain=6.0, trades=4),
    "at most 2 trades": dict(w=(1, .6, .35), gain=2.0, trades=2),
    "no trades (windows only)": dict(w=(1, .6, .35), gain=2.0, trades=0),
}


def weights(w, r):
    end = min((u for u in UNLIMITED_AFTER if u >= r), default=10 ** 6)
    return [x if r + k <= end else 0.0 for k, x in enumerate(w)]


def rows_at(h, r, w):
    """Candidate rows at decision round r: x_now = this round, x_h = weighted horizon."""
    d = h[h["dec_round"] == r]
    hw = weights(w, r)
    d = d.assign(k=d["round"] - r)
    d = d.assign(wx=d["pred"] * d["k"].map(lambda k: hw[k] if 0 <= k < len(hw) else 0.0))
    g = d.groupby("person_id").agg(position=("position", "first"), price=("price", "first"), x_h=("wx", "sum"))
    now = d[d["k"] == 0].set_index("person_id")
    g["x_now"] = now["pred"].reindex(g.index).fillna(0.0)
    g["fpts"] = now["fpts"].reindex(g.index).fillna(0.0)   # no game this round / not in the pool: 0
    return g


def play(h, pol):
    rounds = sorted(h["dec_round"].unique())
    squad, total, per_round, n_trades = None, 0.0, {}, 0
    for r in rounds:
        g = rows_at(h, r, pol["w"])
        pool = [{"id": pid, "position": x.position, "price": float(x.price), "x_h": float(x.x_h), "x_now": float(x.x_now)}
                for pid, x in g.iterrows()]
        if squad is None:  # the season starts with a free squad
            res = optimize.best_squad(pool + [COACH], budget=BUDGET)
            squad = [q["id"] for q in res["team"] if q["id"] != "coach"]
        else:
            unlimited = (r - 1) in UNLIMITED_AFTER
            mine = [q for q in pool if q["id"] in squad]
            missing = [pid for pid in squad if pid not in g.index]   # left the pool: keep, worth 0
            mine += [{"id": pid, "position": pos, "price": price, "x_h": 0.0, "x_now": 0.0} for pid, pos, price in missing]
            bank = BUDGET - sum(q["price"] for q in mine)
            hw = weights(pol["w"], r)
            k = 11 if unlimited else pol["trades"]
            if k > 0:
                tr = optimize.transfers(mine + [COACH], pool + [COACH], bank, max_trades=k,
                                        min_gain_per_trade=pol["gain"] * sum(hw) / sum(pol["w"]))
                if tr and tr["in"]:
                    out = {q["id"] for q in tr["out"]}
                    squad = [pid for pid in squad if pid not in out] + [q["id"] for q in tr["in"]]
                    n_trades += 0 if unlimited else len(tr["in"])
        mine = [q for q in pool if q["id"] in squad] + [
            {"id": pid, "position": _pos(h, pid), "price": 0.0, "x_h": 0.0, "x_now": 0.0} for pid in squad if pid not in g.index]
        lu = optimize.lineup(mine + [COACH], now="x_now")
        pts = 0.0
        for q in lu["team"]:
            if q["id"] == "coach":
                continue
            a = float(g["fpts"].get(q["id"], 0.0))
            pts += a * (0.5 if q["role"] == "πάγκος" else 1.0) * (2.0 if q["captain"] else 1.0)
        per_round[int(r)] = round(pts, 1)
        total += pts
    return {"total": round(total, 1), "per_round": per_round, "trades_used": n_trades}


def _pos(h, pid):
    return h.loc[h["person_id"] == pid, "position"].iloc[0]


out = {}
for season in (2025, 2024):
    h = _lib.build_horizon(season, P)
    res = {name: play(h, pol) for name, pol in POLICIES.items()}
    ref = res["current (1/.6/.35, gain 2, 4 trades)"]["per_round"]
    for name, r in res.items():
        d = np.array([r["per_round"][k] - ref[k] for k in ref])
        r["vs_current"] = round(float(d.sum()), 1)
        r["vs_current_se"] = round(float(d.std(ddof=1) * np.sqrt(len(d))), 1) if d.any() else 0.0
    out[season] = {"rounds": f"{min(ref)}-{max(ref)}", **{k: {x: v for x, v in r.items() if x != "per_round"} for k, r in res.items()}}
    print(season, json.dumps(out[season], indent=1), flush=True)
(HERE / "result.json").write_text(json.dumps(out, indent=1))
