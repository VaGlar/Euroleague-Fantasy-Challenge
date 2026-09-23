"""Read-only client for the EuroLeague Fantasy Challenge (Dunkest) API.

Only GET requests are ever made. Authenticated endpoints need FANTASY_TOKEN
(the Bearer token of a logged-in browser session). Response shapes of the
authenticated endpoints are parsed defensively because they are undocumented;
run `python -m elf.fantasy dump` to print what the API returns.
"""
from __future__ import annotations

import json
import os
import sys

import requests

from .config import FANTASY_API, FANTASY_LEAGUE_ID


class TokenError(RuntimeError):
    """Token missing or rejected: the bot tells the user to refresh it."""


def _token() -> str | None:
    return os.environ.get("FANTASY_TOKEN", "").strip() or None


def get(path: str, params: dict | None = None, auth: bool = True):
    headers = {"Accept": "application/json", "User-Agent": "elf-fantasy-helper/1.0"}
    if auth:
        tok = _token()
        if not tok:
            raise TokenError("FANTASY_TOKEN is not set")
        headers["Authorization"] = f"Bearer {tok}"
    r = requests.get(f"{FANTASY_API}{path}", params=params, headers=headers, timeout=30)
    if r.status_code in (401, 403):
        raise TokenError(f"fantasy API rejected the token ({r.status_code})")
    r.raise_for_status()
    body = r.json()
    return body.get("data", body) if isinstance(body, dict) else body


def config() -> dict:
    """Public: current matchday/round, deadlines, teams, squad rules."""
    return get(f"/leagues/{FANTASY_LEAGUE_ID}/config", auth=False)


def players(players_list_id: int, matchday_id: int) -> list[dict]:
    """All players with price (quotation) for a matchday."""
    out, page = [], 1
    while True:
        data = get(f"/players-lists/{players_list_id}/matchdays/{matchday_id}/players",
                   {"per_page": 200, "page": page, "sort_by": "quotation", "sort_order": "desc"})
        rows = data if isinstance(data, list) else data.get("players") or data.get("data") or []
        out += rows
        if len(rows) < 200:
            return out
        page += 1


def my_teams() -> list[dict]:
    data = get("/user/fantasy-teams")
    return data if isinstance(data, list) else data.get("fantasy_teams", [])


def roster(fantasy_team_id: int, matchday_id: int) -> dict:
    return get(f"/fantasy-teams/{fantasy_team_id}/matchdays/{matchday_id}/roster")


def _pick(d: dict, *keys, default=None):
    for k in keys:
        if isinstance(d, dict) and d.get(k) is not None:
            return d[k]
    return default


def normalize_player(p: dict) -> dict:
    """Map a Dunkest player object to our flat schema (tolerant to variants)."""
    team = _pick(p, "team", default={}) or {}
    pos = _pick(p, "position", "role", default={})
    return {
        "fantasy_id": _pick(p, "id", "player_id"),
        "first_name": _pick(p, "first_name", default=""),
        "last_name": _pick(p, "last_name", default=""),
        "team": _pick(team, "abbreviation", "code") if isinstance(team, dict) else team,
        "position": _pick(pos, "name") if isinstance(pos, dict) else pos,
        "price": _pick(p, "quotation", "price", "credits"),
        "avg_pts": _pick(p, "avg_points", "avg_pts", "fantasy_avg"),
        "status": _pick(p, "status", "injury_status"),
        "popularity": _pick(p, "popularity"),
    }


if __name__ == "__main__":
    # Debug helper: show the raw shape of every endpoint we rely on.
    cfg = config()
    print("config keys:", list(cfg))
    if len(sys.argv) > 1 and sys.argv[1] == "dump":
        md = cfg["current_matchday"]["id"]
        pl = players(cfg["current_players_list_id"], md)
        print(f"players: {len(pl)}; first:\n{json.dumps(pl[:1], indent=1)[:2500]}")
        teams = my_teams()
        print(f"my teams: {json.dumps(teams, indent=1)[:2500]}")
        if teams:
            print(json.dumps(roster(teams[0]["id"], md), indent=1)[:4000])
