"""Read-only client for the EuroLeague Fantasy Challenge (Dunkest) API.

Only GET requests are ever made. Authenticated endpoints need FANTASY_TOKEN
(the Bearer token of a logged-in browser session). Response shapes of the
authenticated endpoints are parsed defensively because they are undocumented;
run `python -m elf.fantasy dump` to print what the API returns.
"""
from __future__ import annotations

import base64
import json
import os
import sys
import time

import requests

from .config import FANTASY_API, FANTASY_LEAGUE_ID


class TokenError(RuntimeError):
    """Token missing or rejected: the bot tells the user to refresh it."""


def _token(data: bool = False) -> str | None:
    """Personal token (my team, /lineup). With data=True: the dedicated data account's
    token (FANTASY_DATA_TOKEN) used for market-wide reads like prices, falling back to
    the personal one while the data account is not set up."""
    if data:
        tok = os.environ.get("FANTASY_DATA_TOKEN", "").strip()
        if tok:
            return tok
    return os.environ.get("FANTASY_TOKEN", "").strip() or None


def token_expiry(data: bool = False) -> dict:
    """Decode the token's expiry if it is a JWT (no signature check, read-only).

    Returns {"kind": "jwt"|"opaque"|"missing", "days_left": float|None}.
    Opaque (e.g. Laravel Sanctum) tokens carry no expiry: we only learn it
    from a 401, which the pipeline reports.
    """
    tok = _token(data)
    if not tok:
        return {"kind": "missing", "days_left": None}
    parts = tok.split(".")
    if len(parts) != 3:
        return {"kind": "opaque", "days_left": None}
    try:
        pad = parts[1] + "=" * (-len(parts[1]) % 4)
        exp = json.loads(base64.urlsafe_b64decode(pad)).get("exp")
    except (ValueError, json.JSONDecodeError):
        return {"kind": "opaque", "days_left": None}
    days = None if exp is None else round((exp - time.time()) / 86400, 2)
    return {"kind": "jwt", "days_left": days}


def get(path: str, params: dict | None = None, auth: bool = True, data: bool = False):
    headers = {"Accept": "application/json", "User-Agent": "elf-fantasy-helper/1.0"}
    if auth:
        tok = _token(data)
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
                   {"per_page": 200, "page": page, "sort_by": "quotation", "sort_order": "desc"},
                   data=True)
        rows = data if isinstance(data, list) else data.get("players") or data.get("data") or []
        out += rows
        if len(rows) < 200:
            return out
        page += 1


def my_teams(game_mode: int = 1) -> list[dict]:
    """The user's teams in this league; game_mode 1 = Classic."""
    data = get("/user/fantasy-teams", {"league": FANTASY_LEAGUE_ID, "game_mode": game_mode})
    return data if isinstance(data, list) else data.get("fantasy_teams", [])


def team_matchday(fantasy_team_id: int, matchday_id: int) -> dict:
    """The team's state for a matchday: credits (bank), total_plus (value gained), trades..."""
    return get(f"/fantasy-teams/{fantasy_team_id}/matchdays/{matchday_id}")


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
        # the game's own availability info (shown as the injury badge in the app)
        "is_injured": bool(_pick(p, "is_injured", default=False)),
        "prob_play": _prob(_pick(p, "probability_of_playing")),
        "from_bench": _pick(p, "started_from_bench"),
        "fantasy_avg": _pick(p, "avg_fantasy_pts"),
    }


def _prob(v) -> float | None:
    """probability_of_playing -> 0..1 (the API may send 0-1 or 0-100)."""
    try:
        v = float(v)
    except (TypeError, ValueError):
        return None
    return max(0.0, min(1.0, v / 100 if v > 1 else v))


def availability(row) -> float:
    """Game-provided availability factor: probability if given, else injured -> 0."""
    p = row.get("prob_play")
    if p is not None and p == p:  # p == p is False for NaN (pandas turns None into NaN)
        return float(p)
    return 0.0 if row.get("is_injured") is True or row.get("is_injured") == 1 else 1.0


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


GAME_ID = 7  # EuroLeague Fantasy Challenge in Dunkest's /games/{id}/config (formations 27-31)


def formations(current_id: int | None = None) -> dict[str, int]:
    """Basketball formations {"2-2-1": id, ...} (G-F-C). The ids differ per game, so if
    the team's current formation id isn't in the expected game, look it up."""
    def load(gid):
        try:
            data = get(f"/games/{gid}/config", auth=False)
        except requests.RequestException:
            return {}
        return {f["name"]: f["id"] for f in data.get("formations", [])}

    forms = load(GAME_ID)
    if current_id is None or current_id in forms.values():
        return forms
    for gid in range(1, 40):
        f = load(gid)
        if current_id in f.values() and "2-2-1" in f:
            return f
    return forms


def save_roster(fantasy_team_id: int, matchday_id: int, body: dict) -> requests.Response:
    """The only write in this project: lineup/captain (no trades). POST, PUT fallback."""
    tok = _token()
    if not tok:
        raise TokenError("FANTASY_TOKEN is not set")
    url = f"{FANTASY_API}/fantasy-teams/{fantasy_team_id}/matchdays/{matchday_id}/roster"
    headers = {"Accept": "application/json", "Authorization": f"Bearer {tok}",
               "User-Agent": "elf-fantasy-helper/1.0"}
    r = requests.post(url, json=body, headers=headers, timeout=30)
    if r.status_code == 405:
        r = requests.put(url, json=body, headers=headers, timeout=30)
    return r
