"""Team ratings and expected PIR (xPIR).

xPIR = base * (1 + calib + pos*pos_dev + pace*pace_dev + margin*m/10
               + blowout*|m|/10 + home*h)

base     blend of last-3 / season / previous-season PIR per game (DNP = 0)
pos_dev  opponent's PIR allowed to the player's position vs league average
pace_dev expected possessions of the game vs league average
m        expected point margin for the player's team (ratings + home court)
h        +1 home, -1 away
"""
from __future__ import annotations

import copy
import json
from math import erf, sqrt

import numpy as np
import pandas as pd

from .config import COACH_POINTS, MARGIN_SD, MODEL, PUBLIC, WIN_BONUS


def params() -> dict:
    """Config priors, with context coefficients from the last backtest fit."""
    p = copy.deepcopy(MODEL)
    fitted = PUBLIC / "model_params.json"
    if fitted.exists():
        p.update(json.loads(fitted.read_text()).get("params", {}))
    return p


# ---------------------------------------------------------------- teams

def team_games(teams: pd.DataFrame) -> pd.DataFrame:
    """One row per team per game with own/opponent points and possessions."""
    if teams.empty:
        return pd.DataFrame(columns=["gamecode", "team", "opp", "is_home", "pts", "opp_pts", "poss"])
    t = teams.copy()
    t["poss_raw"] = t["fga"] + 0.44 * t["fta"] - t["oreb"] + t["tov"]
    o = t[["gamecode", "team", "pts", "poss_raw"]].rename(
        columns={"team": "opp", "pts": "opp_pts", "poss_raw": "opp_poss"})
    m = t.merge(o, on="gamecode")
    m = m[m["team"] != m["opp"]]
    m["poss"] = (m["poss_raw"] + m["opp_poss"]) / 2
    return m[["gamecode", "team", "opp", "is_home", "pts", "opp_pts", "poss"]]


def _raw_ratings(tg: pd.DataFrame) -> pd.DataFrame:
    if tg.empty:
        return pd.DataFrame(columns=["net", "pace", "n"])
    g = tg.groupby("team")
    r = pd.DataFrame({
        "ortg": 100 * g["pts"].sum() / g["poss"].sum(),
        "drtg": 100 * g["opp_pts"].sum() / g["poss"].sum(),
        "pace": g["poss"].mean(),
        "n": g.size(),
    })
    r["net"] = r["ortg"] - r["drtg"]
    return r


def team_ratings(cur_teams: pd.DataFrame, prev_teams: pd.DataFrame,
                 codes: list[str], p: dict | None = None) -> pd.DataFrame:
    """Net rating (per 100 poss), pace and team-specific home-court advantage."""
    p = p or params()
    cur_tg, prev_tg = team_games(cur_teams), team_games(prev_teams)
    cur, prev = _raw_ratings(cur_tg), _raw_ratings(prev_tg)
    both = pd.concat([x for x in (cur_tg, prev_tg) if not x.empty]) \
        if not (cur_tg.empty and prev_tg.empty) else cur_tg
    both = both.astype({"is_home": bool})
    league_pace = both["poss"].mean() if not both.empty else 72.0

    # home-court advantage: half the home/away net-rating gap, shrunk to league
    hca_raw, hca_n = {}, {}
    for team, g in both.groupby("team"):
        h, a = g[g["is_home"]], g[~g["is_home"]]
        if len(h) and len(a):
            nh = 100 * (h["pts"].sum() - h["opp_pts"].sum()) / h["poss"].sum()
            na = 100 * (a["pts"].sum() - a["opp_pts"].sum()) / a["poss"].sum()
            hca_raw[team], hca_n[team] = (nh - na) / 2, min(len(h), len(a))
    league_hca = float(np.mean(list(hca_raw.values()))) if hca_raw else 3.5
    k_h, k, reg = p["hca_shrink_k"], p["team_blend_k"], p["team_prev_regress"]

    rows = []
    for team in codes:
        prior_net = prev["net"].get(team, 0.0) * reg if team in prev.index else 0.0
        prior_pace = (prev["pace"].get(team, league_pace) + league_pace) / 2 \
            if team in prev.index else league_pace
        n = int(cur["n"].get(team, 0)) if team in cur.index else 0
        net = (n * cur["net"].get(team, 0.0) + k * prior_net) / (n + k) if n else prior_net
        pace = (n * cur["pace"].get(team, league_pace) + k * prior_pace) / (n + k) if n else prior_pace
        hn = hca_n.get(team, 0)
        hca = (hn * hca_raw.get(team, league_hca) + k_h * league_hca) / (hn + k_h)
        rows.append({"team": team, "net": net, "pace": pace, "hca": hca, "games": n})
    out = pd.DataFrame(rows).set_index("team")
    out.attrs["league_pace"] = league_pace
    out.attrs["league_hca"] = league_hca
    return out


# ------------------------------------------------------------ positions

def position_allowed(cur_players: pd.DataFrame, prev_players: pd.DataFrame,
                     pos_map: dict, p: dict | None = None) -> dict:
    """{(team, position): deviation of PIR allowed to that position vs league}."""
    p = p or params()

    def table(pl):
        if pl.empty:
            return pd.DataFrame(columns=["opp", "position", "pir", "n"])
        d = pl.assign(position=pl["person_id"].map(pos_map)).dropna(subset=["position"])
        per_game = d.groupby(["gamecode", "team", "position"])["pir"].sum().reset_index()
        opp = d[["gamecode", "team"]].drop_duplicates().rename(columns={"team": "opp"})
        per_game = per_game.merge(opp, on="gamecode")
        per_game = per_game[per_game["team"] != per_game["opp"]]
        return per_game.groupby(["opp", "position"])["pir"].agg(["mean", "size"]) \
            .rename(columns={"mean": "pir", "size": "n"}).reset_index()

    cur, prev = table(cur_players), table(prev_players)
    league = pd.concat([cur, prev]).groupby("position")["pir"].mean()
    k = p["pos_shrink_k"]
    out = {}
    keys = set(zip(cur["opp"], cur["position"])) | set(zip(prev["opp"], prev["position"]))
    ci = cur.set_index(["opp", "position"])
    pi = prev.set_index(["opp", "position"])
    for key in keys:
        lg = league.get(key[1])
        if not lg:
            continue
        prior = (pi.loc[key, "pir"] / lg - 1) * 0.5 if key in pi.index else 0.0
        if key in ci.index:
            n, dev = ci.loc[key, "n"], ci.loc[key, "pir"] / lg - 1
            out[key] = (n * dev + k * prior) / (n + k)
        else:
            out[key] = prior
    return out


# -------------------------------------------------------------- players

def absent_last3(cur_players: pd.DataFrame) -> pd.Series:
    """Per player: of his current team's last 3 games, how many he wasn't on the floor for
    (no minutes). NaN while the team has played fewer than 3."""
    if cur_players.empty:
        return pd.Series(dtype=float)
    c = cur_players.sort_values("gamecode")
    last3 = c.groupby("team")["gamecode"].apply(lambda s: list(dict.fromkeys(s))[-3:])
    played = c[c["min"] > 0]
    on_floor = set(zip(played["gamecode"], played["person_id"]))
    team_now = c.groupby("person_id")["team"].last()
    return pd.Series({pid: (sum((g, pid) not in on_floor for g in last3[t]) if t in last3 and len(last3[t]) == 3
                            else np.nan) for pid, t in team_now.items()}, dtype=float)


def participation(cur_players: pd.DataFrame, prev_players: pd.DataFrame, cur_games: pd.DataFrame,
                  prev_games: pd.DataFrame, team_now: pd.Series, p: dict | None = None) -> pd.Series:
    """Per player: the chance he is on the team sheet at all (R&D 020). A player left out of the twelve
    isn't on the box score, so his form only sees his appearances (Dessert: 4.9 PIR a game in 19 of
    ~38 games, then 0 of 1 this season). Shrunk towards the league's rate:

        p = (appearances + k * p0) / (available games + k)        k = 6, p0 = 0.95

    available = his team's games this season (since his first appearance with it; all of them if he
    hasn't appeared yet) minus absence runs of >= `part_streak` games (an injury: known live from the
    game's list and the news, so not "left out"). p0 = 0.95: no evidence of being left out = on the
    sheet (a league-wide rate would cut every newcomer ~18%). This season only (last season's rate
    didn't help, 020), except for a player with no appearance yet: then last season at the same team
    is all there is. team_now: person_id -> current team."""
    p = p or params()
    streak, k, p0 = int(p.get("part_streak", 3)), float(p.get("part_k", 6)), float(p.get("part_p0", 0.95))

    def sheet(games, box):
        if games.empty or box.empty:
            return None
        g = games[games["played"]].copy()
        g["utc"] = pd.to_datetime(g["utc"], utc=True)
        tg = pd.concat([g[["gamecode", "utc", "home"]].rename(columns={"home": "team"}),
                        g[["gamecode", "utc", "away"]].rename(columns={"away": "team"})]).sort_values("utc")
        b = box.assign(person_id=box["person_id"].astype(str))
        on = set(zip(b["person_id"], b["team"], b["gamecode"]))
        when = dict(zip(zip(tg["gamecode"], tg["team"]), tg["utc"]))
        first = {}
        for pid, team, code in on:
            t = when.get((code, team))
            if t is None:
                continue
            if (pid, team) not in first or t < first[(pid, team)]:
                first[(pid, team)] = t
        return tg, on, first, b.sort_values("gamecode").groupby("person_id")["team"].last()

    def counts(sh, pid, team, whole: bool) -> tuple[int, int]:
        tg, on, first, _ = sh
        codes = tg[tg["team"] == team]
        f = first.get((pid, team))
        if f is not None:
            codes = codes[codes["utc"] >= f]
        elif not whole:
            return 0, 0
        flags = [(pid, team, c) in on for c in codes["gamecode"]]
        # an injury is a run of missed games that ended with him back; a run still going on counts
        # as left out (if he is hurt now, the game's own list already sets him to 0)
        injured, run = 0, 0
        for x in flags:
            if x:
                injured += run if run >= streak else 0
                run = 0
            else:
                run += 1
        return sum(flags), len(flags) - injured

    cur, prev = sheet(cur_games, cur_players), sheet(prev_games, prev_players)
    rows = {}
    for pid, team in team_now.items():
        pid = str(pid)
        a, n = counts(cur, pid, team, whole=True) if cur else (0, 0)
        if a == 0 and prev is not None and prev[3].get(pid) == team:
            pa, pn = counts(prev, pid, team, whole=False)
            a, n = a + pa, n + pn
        rows[pid] = (a, n)
    return pd.Series({pid: min(1.0, (a + k * p0) / (n + k)) for pid, (a, n) in rows.items()}, dtype=float)


def player_base(cur_players: pd.DataFrame, prev_players: pd.DataFrame,
                p: dict | None = None) -> pd.DataFrame:
    """Per-player form blend. DNP rows count as 0 (that's what the game scores)."""
    p = p or params()
    frames = []
    if not cur_players.empty:
        c = cur_players.sort_values("gamecode")
        g = c.groupby("person_id")
        frames.append(pd.DataFrame({
            "season_pir": g["pir"].mean(),
            "last3_pir": g["pir"].apply(lambda s: s.tail(3).mean()),
            "season_min": g["min"].mean(),
            "games": g.size(),
            "team_now": g["team"].last(),
            "name": g["player"].last(),
        }))
    if not prev_players.empty:
        g = prev_players.groupby("person_id")
        frames.append(pd.DataFrame({
            "prev_pir": g["pir"].mean(), "prev_min": g["min"].mean(),
            "prev_games": g.size(), "prev_team": g["team"].last(),
            "prev_name": g["player"].last(),
        }))
    if not frames:
        return pd.DataFrame(columns=["base", "last3_pir", "season_pir", "prev_pir", "games",
                                     "season_min", "prev_min", "team_now", "name"])
    b = pd.concat(frames, axis=1)
    for col in ("season_pir", "last3_pir", "games", "season_min", "team_now", "name"):
        if col not in b:
            b[col] = np.nan
    b["games"] = b["games"].fillna(0)
    b["name"] = b["name"].fillna(b.get("prev_name"))

    for col in ("prev_pir", "prev_min"):
        if col not in b:
            b[col] = np.nan
    # back after sitting out the team's last 3 games: he plays, but less (R&D 012c)
    b["miss3"] = absent_last3(cur_players) if not cur_players.empty else np.nan
    b["returning"] = b["miss3"].fillna(0) >= 3
    b["base"] = blend(b, p) * np.where(b["returning"], p.get("return_factor", 1.0), 1.0)
    return b


def blend(b: pd.DataFrame, p: dict) -> pd.Series:
    """Weighted form blend; missing components drop out and weights renormalise."""
    wp_eff = p["w_prev"] * p["prev_decay_k"] / (p["prev_decay_k"] + b["games"].fillna(0))
    parts = [(p["w_last3"], b["last3_pir"]), (p["w_season"], b["season_pir"]),
             (wp_eff, b["prev_pir"])]
    num = sum(w * v.fillna(0) for w, v in parts)
    den = sum(w * v.notna() for w, v in parts)
    return num / den.replace(0, np.nan)


# ------------------------------------------------------------- fixtures

def context_rows(fixtures: pd.DataFrame, roster: pd.DataFrame, ratings: pd.DataFrame,
                 pos_dev: dict) -> pd.DataFrame:
    """Expand fixtures (home, away, ...) x roster (person_id, team, position)."""
    rows = []
    lp = ratings.attrs["league_pace"]
    for f in fixtures.itertuples():
        for team, opp, home in ((f.home, f.away, True), (f.away, f.home, False)):
            if team not in ratings.index or opp not in ratings.index:
                continue
            rt, ro = ratings.loc[team], ratings.loc[opp]
            pace = (rt["pace"] + ro["pace"]) / 2
            hca = rt["hca"] if home else -ro["hca"]
            margin = (rt["net"] - ro["net"] + hca) * pace / 100
            for pl in roster[roster["team"] == team].itertuples():
                rows.append({
                    "gamecode": f.gamecode, "round": f.round, "utc": getattr(f, "utc", None),
                    "person_id": pl.person_id, "team": team, "opp": opp,
                    "is_home": home, "position": pl.position,
                    "pos_dev": pos_dev.get((opp, pl.position), 0.0),
                    "pace_dev": pace / lp - 1,
                    "margin": margin,
                })
    return pd.DataFrame(rows)


def design(df: pd.DataFrame) -> np.ndarray:
    """Context design matrix, each column scaled by base (multiplicative model)."""
    h = np.where(df["is_home"], 1.0, -1.0)
    cols = [np.ones(len(df)), df["pos_dev"], df["pace_dev"],
            df["margin"] / 10, df["margin"].abs() / 10, h]
    return np.column_stack(cols) * df["base"].to_numpy()[:, None]


COEF_ORDER = ["calib", "pos", "pace", "margin", "blowout", "home"]


def xpir(df: pd.DataFrame, p: dict | None = None) -> pd.Series:
    p = p or params()
    c = np.array([p["coef"][k] for k in COEF_ORDER])
    return df["base"] + design(df) @ c


# ------------------------------------------------------- fantasy scoring

def _cdf(x: float) -> float:
    return 0.5 * (1 + erf(x / (MARGIN_SD * sqrt(2))))


def win_prob(margin: float) -> float:
    return _cdf(margin)


def fantasy_points(xpir: pd.Series, margin: pd.Series) -> pd.Series:
    """Player fantasy score = PIR, +10% if the team wins (official rules)."""
    return xpir * (1 + WIN_BONUS * margin.map(win_prob))


def coach_points(margin: float) -> float:
    """Expected coach score for a game with this expected margin."""
    return sum(pts * (_cdf(hi - margin) - _cdf(lo - margin)) for lo, hi, pts in COACH_POINTS)
