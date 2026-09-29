"""R&D 017 — two minutes ideas: fouls, and a coaching change.

  A  fouls. A player who fouls a lot plays fewer minutes, but that is already in his history (his
     minutes and his PIR, which subtracts the fouls). What his history does not know is tonight's
     opponent: a team that draws many fouls (high pfd) should put the foul-prone in trouble.
       opp_pfd     opponent's fouls drawn per game vs the league (main effect, everyone)
       foul_x_opp  (his fouls per minute / league - 1) x opp_pfd x his minutes x his PIR per minute
       fouled_out  he fouled out (5 fouls) in his last game (is foul trouble persistent?)
     Fitted on the model's error (PIR and, apart, minutes) over the first half of 2025-26, judged out
     of sample on its second half and on all of 2024-25; then the squad test of 010.

  C  coaching change. After a new coach (or interim) the old history describes another rotation.
     Change dates come from the data (a club's coach whose start is after the season began). For
     the teams with a change, the season average becomes a mix of the average since the change and
     the old one: w = n_since / (n_since + k), k chosen on one season and judged on the other.
     First a diagnostic: do minutes move more around a change than around any other point?

python research/017_fouls_and_coaches/run.py -> result.json
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
K_FOUL = 150.0                      # minutes of shrinkage of a player's foul rate to the league's
KS = [0, 2, 4, 8, 16]               # coaching change: weight of the games since the change
WINDOW = 10                         # a change counts for the team's next 10 games


def box(season: int) -> tuple[pd.DataFrame, pd.DataFrame]:
    games = history.load("games", season)
    games["utc"] = pd.to_datetime(games["utc"])
    pl = history.load("players", season).merge(games[["gamecode", "utc"]], on="gamecode")
    pl["person_id"] = pl["person_id"].astype(str)
    return games, pl.sort_values("utc")


def round_starts(games: pd.DataFrame) -> dict:
    rs = games[(games["phase"] == "RS") & games["played"]]
    return rs.groupby("round")["utc"].min().to_dict()


def base_frame(season: int) -> pd.DataFrame:
    df = _lib.build(season, P)
    df["person_id"] = df["person_id"].astype(str)
    d = df.assign(base=model.blend(df, P).fillna(0.0))
    df["xpir"] = model.xpir(d, P).clip(lower=0)
    df["fpred"] = _lib.predict(df, P)
    return df


# ------------------------------------------------------------------------------------------ A: fouls

def foul_features(df: pd.DataFrame, season: int) -> pd.DataFrame:
    games, pl = box(season)
    starts = round_starts(games)
    out = []
    for r, g in df.groupby("round"):
        cp = pl[pl["utc"] < starts[r]]
        played = cp[cp["min"] > 0]
        lg_rate = played["pf"].sum() / played["min"].sum()
        s = played.groupby("person_id").agg(pf=("pf", "sum"), mins=("min", "sum"), n=("min", "size"),
                                            pir=("pir", "sum"))
        s["avg_min"] = s["mins"] / s["n"]
        s["rate_rel"] = ((s["pf"] + K_FOUL * lg_rate) / (s["mins"] + K_FOUL)) / lg_rate - 1
        s["ppm"] = (s["pir"] / s["mins"].replace(0, np.nan)).fillna(0).clip(0, 1.5)
        s["fouled_out"] = (played.groupby("person_id")["pf"].last() >= 5).astype(float)
        drawn = cp.groupby(["gamecode", "team"])["pfd"].sum().groupby("team").mean()
        opp_dev = drawn / drawn.mean() - 1
        g = g.join(s[["avg_min", "rate_rel", "ppm", "fouled_out"]], on="person_id")
        g[["avg_min", "rate_rel", "ppm", "fouled_out"]] = g[["avg_min", "rate_rel", "ppm", "fouled_out"]].fillna(0)
        g["opp_pfd"] = g["opp"].map(opp_dev).fillna(0)
        g["foul_x_opp"] = g["rate_rel"] * g["opp_pfd"] * g["avg_min"] * g["ppm"]
        g["foul_x_opp_min"] = g["rate_rel"] * g["opp_pfd"] * g["avg_min"]       # the same, in minutes
        out.append(g)
    return pd.concat(out)


SETS = {"opp_pfd": ["opp_pfd"], "foul_x_opp": ["foul_x_opp"], "fouled_out": ["fouled_out"],
        "all": ["opp_pfd", "foul_x_opp", "fouled_out"]}


def fit(d, cols, target):
    X = np.column_stack([np.ones(len(d))] + [d[c].to_numpy() for c in cols])
    y = target(d).to_numpy()
    beta, *_ = np.linalg.lstsq(X, y, rcond=None)
    res = y - X @ beta
    se = np.sqrt(np.diag(res @ res / (len(y) - X.shape[1]) * np.linalg.inv(X.T @ X)))
    return beta, se


def adjusted(d, cols, beta):
    X = np.column_stack([np.ones(len(d))] + [d[c].to_numpy() for c in cols])
    return pd.Series(d["xpir"].to_numpy() + X @ beta, index=d.index).clip(lower=0)


def mae(y, pred):
    return round(float((y - pred).abs().mean()), 3)


def part_a(frames: dict) -> dict:
    d25 = frames[2025]
    mid = d25["round"].median()
    train = d25[(d25["round"] <= mid) & d25["dressed"]]
    tests = {"2025 second half": d25[(d25["round"] > mid) & d25["dressed"]],
             "2024 all": frames[2024][frames[2024]["dressed"]]}
    pir_err = lambda d: d["pir"] - d["xpir"]                                   # noqa: E731
    min_err = lambda d: d["min"].fillna(0) - d["avg_min"]                      # noqa: E731
    res = {"train_rows": len(train), "share_fouled_out_last": round(float(train["fouled_out"].mean()), 3),
           "opp_pfd_range": [round(float(train["opp_pfd"].min()), 3), round(float(train["opp_pfd"].max()), 3)]}
    # the user's hypothesis, directly: do foul-prone players lose minutes against foul-drawing teams?
    b, se = fit(train, ["opp_pfd", "foul_x_opp_min", "fouled_out"], min_err)
    res["minutes"] = {c: [round(float(x), 3), round(float(s), 3)]
                      for c, x, s in zip(["const", "opp_pfd", "foul_x_opp_min", "fouled_out"], b, se)}
    b0, _ = fit(train, [], pir_err)
    for name, cols in SETS.items():
        beta, se = fit(train, cols, pir_err)
        r = {"coef": {c: [round(float(x), 3), round(float(s), 3)] for c, x, s in zip(["const"] + cols, beta, se)}}
        for tn, te in tests.items():
            base, new = mae(te["pir"], adjusted(te, [], b0)), mae(te["pir"], adjusted(te, cols, beta))
            r[tn] = {"baseline": base, "with": new, "mae_change": round(new - base, 3)}
        res[name] = r
    squad = {}
    for s, d in frames.items():                       # second half of each season, absences known
        m = d["round"].median()
        beta, _ = fit(d[(d["round"] <= m) & d["dressed"]], SETS["all"], pir_err)
        te = d[d["round"] > m]
        bonus = (te["fpred"] / te["xpir"].replace(0, np.nan)).fillna(1.0)
        known = te["fpred"].where(te["dressed"], 0.0)
        withsig = (adjusted(te, SETS["all"], beta) * bonus).where(te["dressed"], 0.0)
        diff = np.array([_lib.squad_points(g, withsig[g.index]) - _lib.squad_points(g, known[g.index])
                         for _, g in te.groupby("round")])
        squad[s] = {"diff_per_round": round(float(diff.mean()), 1),
                    "diff_se": round(float(diff.std(ddof=1) / np.sqrt(len(diff))), 1)}
    res["squad_points_second_half"] = squad
    return res


# ------------------------------------------------------------------------------ C: coaching change

def changes(season: int, games: pd.DataFrame) -> dict:
    """{club: [dates of a new coach during the season]} from the people list."""
    p = history.load("people", season)
    c = p[p["type"] == "coach"].copy()
    c["start"] = pd.to_datetime(c["start"], utc=True)
    first = games.loc[games["played"], "utc"].min()
    c = c[c["start"] > first + pd.Timedelta(days=7)]
    return {club: sorted(g["start"]) for club, g in c.groupby("club")}


def minutes_shift(season: int) -> dict:
    """Mean |change| of a regular's minutes, 5 games before vs 5 after: at a coaching change vs
    at every other point of the same teams' seasons (the baseline of how much minutes wander)."""
    games, pl = box(season)
    ch = changes(season, games)
    at, other = [], []
    for team, tp in pl.groupby("team"):
        codes = tp.drop_duplicates("gamecode").sort_values("utc")[["gamecode", "utc"]].reset_index(drop=True)
        mins = tp.pivot_table(index="gamecode", columns="person_id", values="min", aggfunc="sum").reindex(
            codes["gamecode"]).fillna(0)
        cut_at = {int((codes["utc"] < d).sum()) for d in ch.get(team, [])}
        for i in range(5, len(codes) - 5):
            before, after = mins.iloc[i - 5:i].mean(), mins.iloc[i:i + 5].mean()
            reg = before >= 10
            if reg.sum() == 0:
                continue
            v = float((after[reg] - before[reg]).abs().mean())
            (at if i in cut_at else other).append(v)
    return {"changes": sum(len(v) for v in ch.values()), "points_at_change": len(at),
            "min_shift_at_change": round(float(np.mean(at)), 2) if at else None,
            "min_shift_elsewhere": round(float(np.mean(other)), 2),
            "elsewhere_p90": round(float(np.percentile(other, 90)), 2)}


def coach_form(df: pd.DataFrame, season: int, ch: dict | None = None) -> pd.DataFrame:
    """Per row: games of his team since its last change (within WINDOW), and his PIR mean since."""
    games, pl = box(season)
    starts = round_starts(games)
    ch = changes(season, games) if ch is None else ch
    out = []
    for r, g in df.groupby("round"):
        cp = pl[pl["utc"] < starts[r]]
        g = g.assign(n_since=0, since_pir=np.nan)
        for team, dates in ch.items():
            past = [d for d in dates if d < starts[r]]
            if not past:
                continue
            tg = cp[cp["team"] == team]
            post = tg[tg["utc"] >= past[-1]]
            n = post["gamecode"].nunique()
            if n == 0 or n > WINDOW:
                continue
            # a DNP after the change is a 0, as in the form (the pool is who was on a box score)
            per = post.groupby("person_id")["pir"].sum() / n
            idx = g.index[g["team"] == team]
            g.loc[idx, "n_since"] = n
            g.loc[idx, "since_pir"] = g.loc[idx, "person_id"].map(per).fillna(0.0).to_numpy()
        out.append(g)
    return pd.concat(out)


def predict_k(df: pd.DataFrame, k: float) -> pd.Series:
    d = df.copy()
    hit = d["n_since"] > 0
    w = d["n_since"] / (d["n_since"] + k)
    d.loc[hit, "season_pir"] = (w * d["since_pir"] + (1 - w) * d["season_pir"].fillna(d["since_pir"]))[hit]
    return _lib.predict(d, P)


def placebo(d: pd.DataFrame, season: int) -> dict:
    """The same recipe at the same dates on the teams that did NOT change coach: if it helps them as
    much, the gain is plain recency (the form's weights), not the new coach."""
    games, _ = box(season)
    real = changes(season, games)
    teams = sorted(set(d["team"]) - set(real))
    gains = {k: [] for k in (0, 2)}
    base = _lib.predict(d, P)
    for dates in real.values():
        for dt in dates:
            f = coach_form(d.drop(columns=["n_since", "since_pir"]), season, {t: [dt] for t in teams})
            hit = f["n_since"] > 0
            if not hit.any():
                continue
            for k in gains:
                gains[k].append(mae(f.loc[hit, "fpts"], predict_k(f, k)[hit]) - mae(f.loc[hit, "fpts"], base[hit]))
    return {str(k): round(float(np.mean(v)), 3) for k, v in gains.items()}


def part_c(frames: dict) -> dict:
    res = {"diagnostic": {s: minutes_shift(s) for s in frames}, "seasons": {}}
    res["placebo_mae_change"] = {s: placebo(d, s) for s, d in frames.items()}
    print("placebo", res["placebo_mae_change"])
    for s, d in frames.items():
        hit = d["n_since"] > 0
        base = _lib.predict(d, P)
        top = hit & (base >= 12)
        r = {"rows_after_change": int(hit.sum()), "baseline": {
            "mae_affected": mae(d.loc[hit, "fpts"], base[hit]), "mae_top_affected": mae(d.loc[top, "fpts"], base[top]),
            "mae_all": mae(d["fpts"], base)}}
        squad_base = {rn: _lib.squad_points(g, base[g.index]) for rn, g in d.groupby("round")}
        rounds = sorted(d.loc[hit, "round"].unique())
        r["baseline"]["squad_rounds_affected"] = round(sum(squad_base[x] for x in rounds), 1)
        for k in KS:
            pr = predict_k(d, k)
            sq = sum(_lib.squad_points(d[d["round"] == x], pr[d["round"] == x]) for x in rounds)
            r[str(k)] = {"mae_affected": mae(d.loc[hit, "fpts"], pr[hit]), "mae_top_affected": mae(d.loc[top, "fpts"], pr[top]),
                         "mae_all": mae(d["fpts"], pr),
                         "squad_rounds_affected": round(float(sq), 1)}
        res["seasons"][s] = r
        print("C", s, json.dumps(r))
    res["out_of_sample"] = {}
    for train, test in ((2024, 2025), (2025, 2024)):
        t = res["seasons"][train]
        best = min((str(k) for k in KS), key=lambda k: t[k]["mae_affected"])
        res["out_of_sample"][test] = {"k_from": train, "k": best, "baseline": res["seasons"][test]["baseline"],
                                      "adjusted": res["seasons"][test][best]}
    return res


def main():
    frames = {}
    for s in (2025, 2024):
        df = base_frame(s)
        frames[s] = coach_form(foul_features(df, s), s)
    out = {"A_fouls": part_a(frames)}
    print(json.dumps(out, indent=1))
    out["C_coach"] = part_c(frames)
    (HERE / "result.json").write_text(json.dumps(out, indent=1, default=str))
    print(json.dumps(out["C_coach"], indent=1, default=str))


if __name__ == "__main__":
    main()
