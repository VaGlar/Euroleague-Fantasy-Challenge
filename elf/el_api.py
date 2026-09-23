"""Thin client for the public (unofficial) EuroLeague APIs."""
from __future__ import annotations

import time

import requests

V2 = "https://api-live.euroleague.net/v2/competitions/E/seasons/E{season}"
LIVE = "https://live.euroleague.net/api"

_session = requests.Session()
_session.headers["User-Agent"] = "elf-fantasy-helper/1.0 (personal use)"


def _get(url: str, params: dict | None = None, retries: int = 4):
    for attempt in range(retries):
        try:
            r = _session.get(url, params=params, timeout=30)
            if r.status_code == 200:
                return r.json()
            if r.status_code in (429, 500, 502, 503, 504):
                raise requests.HTTPError(f"{r.status_code} for {r.url}")
            r.raise_for_status()
        except (requests.RequestException, ValueError):
            if attempt == retries - 1:
                raise
            time.sleep(2 ** (attempt + 1))
    return None


def _paged(url: str, limit: int = 500) -> list[dict]:
    """v2 list endpoints cap each response (500) and report `total`: walk offsets."""
    out, offset = [], 0
    while True:
        body = _get(url, {"offset": offset, "limit": limit})
        rows = body.get("data", [])
        out += rows
        offset += len(rows)
        if not rows or offset >= body.get("total", 0):
            return out


def games(season: int) -> list[dict]:
    """All games of a season (played and scheduled), flattened."""
    out = []
    for g in _paged(f"{V2.format(season=season)}/games"):
        out.append({
            "season": season,
            "gamecode": g["gameCode"],
            "phase": g["phaseType"]["code"],
            "round": g["round"],
            "utc": g["utcDate"],
            "played": bool(g["played"]),
            "home": g["local"]["club"]["code"],
            "away": g["road"]["club"]["code"],
            "home_score": g["local"]["score"],
            "away_score": g["road"]["score"],
        })
    return out


def clubs(season: int) -> list[dict]:
    return [
        {"code": c["code"], "tv": c.get("tvCode"), "name": c["name"], "short": c["abbreviatedName"],
         "crest": c.get("images", {}).get("crest")}
        for c in _get(f"{V2.format(season=season)}/clubs")["data"]
    ]


def people(season: int) -> list[dict]:
    """Players and head coaches registered in a season, with position."""
    out = []
    for p in _paged(f"{V2.format(season=season)}/people"):
        if p["type"] not in ("J", "E"):  # J = player, E = head coach
            continue
        out.append({
            "person_id": p["person"]["code"].strip(),
            "name": p["person"]["name"],
            "type": "player" if p["type"] == "J" else "coach",
            "position": p.get("positionName"),
            "club": p["club"]["code"],
            "active": p.get("active", True),
            "start": p.get("startDate"),
        })
    return out


def _minutes(m) -> float:
    if not m or m == "DNP" or ":" not in str(m):
        return 0.0
    mm, ss = str(m).split(":")
    return int(mm) + int(ss) / 60


def boxscore(season: int, gamecode: int) -> dict:
    """Player lines plus team totals for one game."""
    data = _get(f"{LIVE}/Boxscore", {"gamecode": gamecode, "seasoncode": f"E{season}"})
    players, teams = [], []
    for side, block in zip(("home", "away"), data["Stats"]):
        team = None
        for p in block["PlayersStats"]:
            team = p["Team"].strip()
            players.append({
                "season": season, "gamecode": gamecode, "team": team,
                "is_home": side == "home",
                "person_id": p["Player_ID"].strip().lstrip("P"),
                "player": " ".join(p["Player"].split()),
                "starter": int(p["IsStarter"] or 0),
                "min": round(_minutes(p["Minutes"]), 2),
                "pts": p["Points"], "fgm2": p["FieldGoalsMade2"], "fga2": p["FieldGoalsAttempted2"],
                "fgm3": p["FieldGoalsMade3"], "fga3": p["FieldGoalsAttempted3"],
                "ftm": p["FreeThrowsMade"], "fta": p["FreeThrowsAttempted"],
                "oreb": p["OffensiveRebounds"], "dreb": p["DefensiveRebounds"],
                "ast": p["Assistances"], "stl": p["Steals"], "tov": p["Turnovers"],
                "blk": p["BlocksFavour"], "blka": p["BlocksAgainst"],
                "pf": p["FoulsCommited"], "pfd": p["FoulsReceived"],
                "pir": p["Valuation"],
            })
        t = block["totr"]
        teams.append({
            "season": season, "gamecode": gamecode, "team": team, "is_home": side == "home",
            "pts": t["Points"],
            "fga": t["FieldGoalsAttempted2"] + t["FieldGoalsAttempted3"],
            "fta": t["FreeThrowsAttempted"], "oreb": t["OffensiveRebounds"],
            "tov": t["Turnovers"], "pir": t["Valuation"],
        })
    return {"players": players, "teams": teams}
