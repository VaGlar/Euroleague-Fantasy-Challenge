"""R&D 020 — participation: how often is a player on the team sheet at all?

A player left out of the twelve is not on the box score, so the model never sees that game: his form
is his appearances only, and last season's average is per appearance (Dessert: 4.9 PIR in 19 of ~38
games; 0 appearances this season, still 4.9 xFPT). By minutes, players under 8 min bring 49-60% of
their prediction, 8-12 min 76-82%, but ~0.9-1.06 when dressed: the gap is being left out, not playing
worse. A per-player participation factor multiplies the xFPT:

  p = (appearances + k * p_pos) / (available team games + k)
  available = the team's games since he joined it, minus absence streaks of >= S games
              (a streak is almost always an injury/illness: known live from the game's list and the news,
               so it must not count as "left out"; short injuries are misread as rotation - the test says
               whether that matters)
  seasons: this one, or this one + last one (with last season's games counted only if same team)

Honest test (as live): absences inside a streak of >= S games are known (predicted 0, no error);
single/short absences of a fit player are NOT known (predicted with the factor, actual 0).
Choose (S, k, seasons) on one season by MAE, judge on the other on MAE, MAE >= 12 and squad points.

python research/020_participation/run.py -> result.json
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
from elf import history  # noqa: E402
from elf.config import MODEL  # noqa: E402

LIVE = json.loads((_lib.ROOT / "data/public/model_params.json").read_text())["params"]
P = {**copy.deepcopy(MODEL), **{k: LIVE[k] for k in ("w_last3", "w_season", "w_prev", "coef")}}
STREAKS = [3]
KS = [6]
P0S = [0.95]
CAPS = [None, 5.0, 5.5, 6.0]   # the factor only for players priced below (None = everyone)      # the shrinkage target: the position's rate, or "no evidence = on the sheet"
MODES = ["this"]
FAR = pd.Timestamp("2100-01-01", tz="UTC")


def sheets(season: int):
    """Per team, its played games in order; per player, the set of games he was on the sheet of."""
    games = history.load("games", season)
    games["utc"] = pd.to_datetime(games["utc"])
    g = games[games["played"]]
    tg = pd.concat([g[["gamecode", "utc", "home"]].rename(columns={"home": "team"}),
                    g[["gamecode", "utc", "away"]].rename(columns={"away": "team"})]).sort_values("utc")
    box = history.load("players", season)
    box["person_id"] = box["person_id"].astype(str)
    return games, tg, box


def timelines(tg, box) -> dict:
    """(person, team) -> [(gamecode, utc, on_sheet)] for the team's games since his first appearance
    with it, in time order."""
    utc = tg.set_index(["gamecode", "team"])["utc"]
    out = {}
    for (pid, team), g in box.groupby(["person_id", "team"]):
        on = set(g["gamecode"])
        codes = tg[tg["team"] == team]
        first = min(utc.get((c, team), FAR) for c in on)
        codes = codes[codes["utc"] >= first]
        out[(pid, team)] = list(zip(codes["gamecode"], codes["utc"], codes["gamecode"].isin(on)))
    return out


def runs(tl) -> dict:
    """gamecode -> length of the absence run it belongs to (whole season: hindsight)."""
    out, cur = {}, []
    for code, _, on in tl + [(None, None, True)]:
        if on:
            for c in cur:
                out[c] = len(cur)
            cur = []
        else:
            cur.append(code)
    return out


def counts(tl, before, streak: int) -> tuple[int, int]:
    """(appearances, available games) before a time, from the past only: an absence run already of
    >= streak games counts as an injury (not available); shorter ones as left out."""
    past = [x for x in tl if x[1] < before]
    app = sum(1 for x in past if x[2])
    injured, cur = 0, 0
    for _, _, on in past:          # as live: only a run that ended with him back is an injury
        if on:
            injured += cur if cur >= streak else 0
            cur = 0
        else:
            cur += 1
    return app, len(past) - injured


def participation(df: pd.DataFrame, season: int) -> dict:
    """{S: DataFrame(round, person_id, app, avail, prev_app, prev_avail, same_team, injury_out)}.
    injury_out: his absence from this round's game belongs to a run of >= S games (hindsight): an
    injury, which the live app knows from the game's list and the news."""
    games, tg, box = sheets(season)
    _, ptg, pbox = sheets(season - 1)
    tl, ptl = timelines(tg, box), timelines(ptg, pbox)
    prev_team = pbox.merge(ptg[["gamecode", "team", "utc"]], on=["gamecode", "team"]).sort_values("utc") \
        .groupby("person_id")["team"].last()
    rs = games[(games["phase"] == "RS") & games["played"]]
    starts = rs.groupby("round")["utc"].min()
    run = {k: runs(v) for k, v in tl.items()}
    res = {}
    for s in STREAKS:
        rows = []
        for r in df.itertuples():
            key = (r.person_id, r.team)
            t = tl.get(key, [])
            app, avail = counts(t, starts[r.round], s)
            pt = prev_team.get(r.person_id)
            papp, pavail = counts(ptl.get((r.person_id, pt), []), FAR, s) if pt else (0, 0)
            rows.append({"idx": r.Index, "app": app, "avail": avail, "prev_app": papp, "prev_avail": pavail,
                         "same_team": pt == r.team,
                         "injury_out": run.get(key, {}).get(r.gamecode, 0) >= s})
        res[s] = pd.DataFrame(rows).set_index("idx")
    return res


def factor(d: pd.DataFrame, k: float, mode: str, pos_rate: dict, p0_fixed: float | None = None) -> pd.Series:
    app, avail = d["app"].astype(float), d["avail"].astype(float)
    if mode == "both":
        same = d["same_team"].fillna(False)
        app = app + d["prev_app"].fillna(0).where(same, 0)
        avail = avail + d["prev_avail"].fillna(0).where(same, 0)
    p0 = d["position"].map(pos_rate).fillna(0.85) if p0_fixed is None else p0_fixed
    return ((app + k * p0) / (avail + k)).clip(0, 1)


def metrics(df: pd.DataFrame, pred: pd.Series) -> dict:
    """As live: an absence inside an injury-like streak is known (0, no error); any other is not."""
    known_out = ~df["dressed"] & df["injury_out"].fillna(False)
    live = pred.where(~known_out, 0.0)
    ev = ~known_out
    err = (live[ev] - df.loc[ev, "fpts"]).abs()
    top = live[ev] >= 12
    squad = sum(_lib.squad_points(g, live.loc[g.index]) for _, g in df.groupby("round"))
    return {"mae": round(float(err.mean()), 4), "mae_top": round(float(err[top].mean()), 4),
            "squad": round(float(squad), 1)}


def main():
    res = {"seasons": {}}
    for season in (2024, 2025):
        df = _lib.build(season, P)
        df["person_id"] = df["person_id"].astype(str)
        base = _lib.predict(df, P)
        parts = participation(df, season)
        r = {}
        for s, part in parts.items():
            d = df.join(part)
            r[f"S{s}_baseline"] = metrics(d, base)
            # the position's rate of this season so far (shrinkage target)
            for mode in MODES:
                for k in KS:
                    rate = {pos: float(g["app"].sum() / max(g["avail"].sum(), 1))
                            for pos, g in d.groupby("position")}
                    for p0 in P0S:
                        f = factor(d, k, mode, rate, p0).fillna(1.0)
                        for cap in CAPS:
                            ff = f if cap is None else f.where(d["price"] < cap, 1.0)
                            r[f"S{s}_{mode}_k{k}_p{p0 or 'pos'}_cap{cap or 'all'}"] = metrics(d, base * ff)
        res["seasons"][season] = r
        print(season, json.dumps(r, indent=1))
    res["out_of_sample"] = {}
    for train, test in ((2024, 2025), (2025, 2024)):
        tr = res["seasons"][train]
        cand = {k: v for k, v in tr.items() if "baseline" not in k}
        best = min(cand, key=lambda k: cand[k]["mae"] - tr[k.split("_")[0] + "_baseline"]["mae"])
        te = res["seasons"][test]
        res["out_of_sample"][test] = {"chosen_on": train, "variant": best,
                                      "baseline": te[best.split("_")[0] + "_baseline"], "with": te[best]}
    (HERE / "result.json").write_text(json.dumps(res, indent=1))
    print(json.dumps(res["out_of_sample"], indent=1))


if __name__ == "__main__":
    main()
