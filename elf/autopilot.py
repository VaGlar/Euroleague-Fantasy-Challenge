"""Autopilot: a team that only ever does what the app proposes, to measure it like a real manager.

It starts with 100 credits and the best squad from scratch. Before every round it makes the trades the
app would propose (4, or unlimited where the game allows), and picks the five, sixth man and captain.
Its decision for a round is the last one before the round's first tip-off (the file is rewritten on
every run until then), exactly as for a user. After the round, it is scored with the real points and
the game's rules (bench 50%, captain x2, coach by margin).

Next to it, per round:
  avg_raw   the average manager's roster points, from POP (share of managers who own each player):
            11 x sum(pop x points) / sum(pop). Exact for "who they own"; no bench/captain, so it is
            compared with the autopilot's raw roster points (raw), not its game points.
  my_pts    the owner's real game points (personal edition only; publish.py drops it).

File: data/public/autopilot.json
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

import pandas as pd

from . import history, optimize
from .config import BENCH_MULTIPLIER, BUDGET, CAPTAIN_MULTIPLIER, PUBLIC
from .tracking import _coach_points, actual_points

def _path():
    return PUBLIC / "autopilot.json"      # at call time: tests point PUBLIC elsewhere


def load() -> dict:
    try:
        return json.loads(_path().read_text())
    except (OSError, ValueError):
        return {"rounds": []}


def _save(state: dict) -> None:
    state["generated"] = datetime.now(timezone.utc).isoformat()
    _path().write_text(json.dumps(state, ensure_ascii=False, indent=1, allow_nan=False))


def _info(table: pd.DataFrame) -> dict:
    """fantasy id -> what the log keeps about a player."""
    t = table.dropna(subset=["fantasy_id"])
    return {int(r["fantasy_id"]): {"person_id": str(r["person_id"]), "name": r["name"], "team": r["team"],
                                   "position": r["position"]} for r in t.to_dict("records")}


def decide(state: dict, rnd: int, rows: list[dict], table: pd.DataFrame, max_trades: int,
           min_gain: float) -> dict | None:
    """The autopilot's squad and lineup for round `rnd` (rows: optimizer rows of the whole pool)."""
    prev = [r for r in state["rounds"] if r["round"] < rnd]
    by_id = {p["id"]: p for p in rows}
    info = _info(table)
    if not prev:                                            # day one: best squad from scratch
        res = optimize.best_squad(rows, budget=BUDGET)
        if not res:
            return None
        squad_ids, trades = [p["id"] for p in res["team"]], 0
        bank = round(BUDGET - res["cost"], 1)
    else:
        last = prev[-1]
        # today's prices; a player gone from the game list stays at his last price, worth nothing
        squad = [by_id.get(p["id"]) or {**p, "x_h": 0.0, "x_now": 0.0} for p in last["squad"]]
        tr = optimize.transfers(squad, rows, float(last["bank"]), max_trades=max_trades,
                                min_gain_per_trade=min_gain)
        if tr:
            squad_ids = [p["id"] for p in tr["result"]["team"]]
            trades, bank = len(tr["in"]), tr["bank_after"]
        else:
            squad_ids, trades, bank = [p["id"] for p in squad], 0, last["bank"]
    squad = [by_id[i] for i in squad_ids if i in by_id]
    if len(squad) != len(squad_ids):
        return None
    lu = optimize.lineup(squad)
    if not lu:
        return None
    role = {p["id"]: (p["role"], bool(p.get("captain"))) for p in lu["team"]}
    return {
        "round": rnd, "trades": trades, "bank": round(float(bank), 1),
        "squad": [{"id": p["id"], "price": p["price"], "position": p["position"],
                   **{k: info.get(p["id"], {}).get(k) for k in ("person_id", "name", "team")},
                   "role": role.get(p["id"], (None, False))[0], "captain": role.get(p["id"], (None, False))[1],
                   "x_now": round(p["x_now"], 1)} for p in squad],
        "x_total": round(lu.get("objective", 0.0), 1),
    }


def score(entry: dict, fp: pd.Series, margin: dict) -> tuple[float, float]:
    """(game points with the game's rules, raw roster points) of a squad for its round."""
    rnd, game, raw = entry["round"], 0.0, 0.0
    for p in entry["squad"]:
        if p["position"] == "Head Coach":
            pts = _coach_points(margin.get(p["team"], 0))
            game, raw = game + pts, raw + pts
            continue
        pts = float(fp.get((rnd, p["person_id"]), 0.0))
        raw += pts
        game += pts * (BENCH_MULTIPLIER if p["role"] == "πάγκος" else 1.0) * (CAPTAIN_MULTIPLIER if p["captain"] else 1)
    return round(game, 1), round(raw, 1)


def average_manager(rnd: int, fp: pd.Series, margin: dict) -> float | None:
    """The average manager's raw roster points for a round, from the POP snapshot of that matchday."""
    path = PUBLIC / "prices.csv"
    if not path.exists():
        return None
    pr = pd.read_csv(path, dtype={"person_id": str})
    if "popularity" not in pr:
        return None
    pr = pr[(pr["matchday"] == rnd) & pr["popularity"].notna() & pr["person_id"].notna()]
    if pr.empty or pr["popularity"].sum() <= 0:
        return None
    pts = [(_coach_points(margin.get(r["team"], 0)) if r["position"] == "Head Coach"
            else float(fp.get((rnd, r["person_id"]), 0.0))) for r in pr.to_dict("records")]
    return round(11 * float((pr["popularity"] * pts).sum()) / float(pr["popularity"].sum()), 1)


def update(season: int, rnd: int, trade_rnd: int, rows: list[dict], table: pd.DataFrame,
           max_trades: int, min_gain: float, my_points: dict | None = None) -> dict:
    """Decide the coming round (until its tip-off), score the finished ones."""
    state = load()
    kept = [r for r in state["rounds"] if r["round"] < trade_rnd]      # frozen: already under way or done
    state["rounds"] = kept
    entry = decide(state, trade_rnd, rows, table, max_trades, min_gain)
    if entry:
        state["rounds"].append(entry)
    state.setdefault("start_round", state["rounds"][0]["round"] if state["rounds"] else None)

    pts, _ = actual_points(season)
    games = history.load("games", season)
    fp = pts.groupby(["round", "person_id"])["fp"].sum() if not pts.empty else pd.Series(dtype=float)
    for e in state["rounds"]:
        rg = games[games["round"] == e["round"]] if not games.empty else games
        if e.get("pts") is not None or rg.empty or not rg["played"].all():
            continue
        margin = {}
        for g in rg.itertuples():
            margin[g.home], margin[g.away] = g.home_score - g.away_score, g.away_score - g.home_score
        e["pts"], e["raw"] = score(e, fp, margin)
        e["avg_raw"] = average_manager(e["round"], fp, margin)
    for e in state["rounds"]:
        if my_points and str(e["round"]) in my_points:
            e["my_pts"] = my_points[str(e["round"])]
    done = [e for e in state["rounds"] if e.get("pts") is not None]
    state["total"] = {"rounds": len(done), "pts": round(sum(e["pts"] for e in done), 1),
                      "raw": round(sum(e["raw"] for e in done), 1),
                      "avg_raw": round(sum(e["avg_raw"] for e in done if e.get("avg_raw") is not None), 1)
                      if any(e.get("avg_raw") is not None for e in done) else None}
    _save(state)
    return state
