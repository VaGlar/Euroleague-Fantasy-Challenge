"""R&D 012(c) — players coming back (from an injury, or into the rotation).

015 saw it on the side: players with a past season but only a few games mid-season are overestimated
(14.8 -> 7.4 in 2024, 15.5 -> 9.8 in 2025). The form blend averages the games a player *did* play,
so after weeks out he is predicted at his healthy level, while on his return he usually plays less.

Feature, known before the round: how many of his team's last 3 games he sat out (not on the floor:
no box score line, or 0 minutes) -> miss3 = 0..3.

Fair test: the live app knows who is out (the game's availability flag zeroes him); history doesn't.
So both the baseline and the correction get the same oracle: a player not dressed in the round is
predicted 0. What is left to learn is only "he plays, but how much".

  diag      prediction vs actual for players who played, by miss3 (and for the good ones, pred >= 10)
  correct   base x c[miss3], c fitted on one season (ratio of means), judged on the other:
            MAE (players who played) and fantasy points of the best squad under the budget.

python research/012_injury_return/run.py -> result.json
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


def miss3(season: int, df: pd.DataFrame) -> pd.Series:
    """For each row (round, player, team): of the team's last 3 games before the round, how many the
    player was not on the floor for."""
    games = history.load("games", season)
    players = history.load("players", season)
    games = games[games["played"]].copy()
    games["utc"] = pd.to_datetime(games["utc"])
    on_floor = set(zip(players.loc[players["min"] > 0, "gamecode"], players.loc[players["min"] > 0, "person_id"]))
    team_games = {}                                    # team -> [(utc, gamecode)] sorted
    for g in games.itertuples():
        for t in (g.home, g.away):
            team_games.setdefault(t, []).append((g.utc, g.gamecode))
    for t in team_games:
        team_games[t].sort()
    start = df.groupby("round")["utc"].transform("min")
    start = pd.to_datetime(start)
    out = []
    for team, pid, t0 in zip(df["team"], df["person_id"], start):
        last = [gc for u, gc in team_games.get(team, []) if u < t0][-3:]
        out.append(sum((gc, pid) not in on_floor for gc in last) if len(last) == 3 else np.nan)
    return pd.Series(out, index=df.index)


def predict(df: pd.DataFrame, c: dict | None = None) -> pd.Series:
    base = model.blend(df, P)
    if c:
        base = base * df["miss3"].map(c).fillna(1.0)
    d = df.assign(base=base.fillna(0.0))
    pred = model.fantasy_points(model.xpir(d, P).clip(lower=0), d["margin"])
    return pred.where(df["dressed"], 0.0)           # the availability oracle, for both


def diag(df: pd.DataFrame, pred: pd.Series) -> dict:
    out = {}
    played = df["dressed"]
    for m in (0, 1, 2, 3):
        for label, extra in (("all", True), ("good", pred >= 10)):
            s = played & (df["miss3"] == m) & extra
            if s.sum():
                out[f"miss{m}_{label}"] = {"n": int(s.sum()), "pred": round(float(pred[s].mean()), 2),
                                           "actual": round(float(df.loc[s, "fpts"].mean()), 2)}
    return out


def fit(df: pd.DataFrame, pred: pd.Series) -> dict:
    """c[m] = mean actual / mean predicted, players who played with miss3 = m (m = 0 stays 1)."""
    c = {0: 1.0}
    for m in (1, 2, 3):
        s = df["dressed"] & (df["miss3"] == m) & (pred > 0)
        c[m] = round(float(df.loc[s, "fpts"].sum() / pred[s].sum()), 3) if s.sum() >= 30 else 1.0
    return c


def metrics(df: pd.DataFrame, pred: pd.Series) -> dict:
    played = df["dressed"]
    err = (pred - df["fpts"]).abs()
    back = played & (df["miss3"] >= 1)
    squad = sum(_lib.squad_points(g, pred.loc[g.index]) for _, g in df.groupby("round"))
    return {"mae_played": round(float(err[played].mean()), 3),
            "mae_back": round(float(err[back].mean()), 3), "n_back": int(back.sum()),
            "squad": round(float(squad), 1)}


def main():
    data = {}
    for s in (2024, 2025):
        df = _lib.build(s, P)
        df["miss3"] = miss3(s, df)
        data[s] = df
    base = {s: predict(d) for s, d in data.items()}
    out = {"diag": {s: diag(data[s], base[s]) for s in data}, "fitted": {}, "judged": {}}
    for train, test in ((2024, 2025), (2025, 2024)):
        c = fit(data[train], base[train])
        out["fitted"][train] = c
        out["judged"][test] = {"baseline": metrics(data[test], base[test]),
                               "corrected": metrics(data[test], predict(data[test], c)),
                               "c_from": train}
    (HERE / "result.json").write_text(json.dumps(out, indent=1, default=str))
    print(json.dumps(out, indent=1, default=str))


if __name__ == "__main__":
    main()
