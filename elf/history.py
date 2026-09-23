"""Incrementally download and cache public EuroLeague data under data/history.

Files (all gzip CSV, committed so CI runs are fast and reproducible):
  games_{season}.csv.gz     schedule + results
  players_{season}.csv.gz   one row per player per game (incl. DNP)
  teams_{season}.csv.gz     team totals per game
  people_{season}.csv.gz    roster with positions
"""
from __future__ import annotations

import sys
from concurrent.futures import ThreadPoolExecutor

import pandas as pd

from . import el_api
from .config import HISTORY


def _path(kind: str, season: int):
    return HISTORY / f"{kind}_{season}.csv.gz"


def load(kind: str, season: int) -> pd.DataFrame:
    p = _path(kind, season)
    if not p.exists():
        return pd.DataFrame()
    return pd.read_csv(p, dtype={"person_id": str})


def _save(df: pd.DataFrame, kind: str, season: int) -> None:
    HISTORY.mkdir(parents=True, exist_ok=True)
    df.to_csv(_path(kind, season), index=False, compression="gzip")


def update_season(season: int, refresh_people: bool = True) -> None:
    games = pd.DataFrame(el_api.games(season))
    _save(games, "games", season)

    if refresh_people or not _path("people", season).exists():
        _save(pd.DataFrame(el_api.people(season)), "people", season)

    players, teams = load("players", season), load("teams", season)
    have = set(teams["gamecode"]) if not teams.empty else set()
    todo = sorted(set(games.loc[games["played"], "gamecode"]) - have)
    if not todo:
        print(f"E{season}: up to date ({len(have)} games)")
        return

    print(f"E{season}: fetching {len(todo)} boxscores ...", flush=True)
    new_p, new_t, failed = [], [], []

    def fetch(gc):
        try:
            return gc, el_api.boxscore(season, int(gc))
        except Exception as e:  # keep going; retry next run
            return gc, e

    with ThreadPoolExecutor(max_workers=4) as ex:
        for i, (gc, res) in enumerate(ex.map(fetch, todo), 1):
            if isinstance(res, Exception):
                failed.append(gc)
                continue
            new_p += res["players"]
            new_t += res["teams"]
            if i % 50 == 0:
                print(f"  {i}/{len(todo)}", flush=True)

    if new_t:
        players = pd.concat([players, pd.DataFrame(new_p)], ignore_index=True)
        teams = pd.concat([teams, pd.DataFrame(new_t)], ignore_index=True)
        _save(players.sort_values(["gamecode", "team"]), "players", season)
        _save(teams.sort_values(["gamecode", "is_home"]), "teams", season)
    print(f"E{season}: +{len(new_t) // 2} games, {len(failed)} failed", flush=True)
    if failed:
        print(f"  failed gamecodes: {failed}", file=sys.stderr)


if __name__ == "__main__":
    for s in (int(a) for a in sys.argv[1:]):
        update_season(s)
