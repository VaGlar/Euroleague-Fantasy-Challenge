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

import hashlib
import json
from datetime import datetime, timezone

import pandas as pd

from . import fantasy, history, optimize
from .config import BENCH_MULTIPLIER, BUDGET, CAPTAIN_MULTIPLIER, PUBLIC
from .tracking import _coach_points, actual_points

def _path():
    return PUBLIC / "autopilot.json"      # at call time: tests point PUBLIC elsewhere


def _seed_path():
    """The decisions of the rounds before the autopilot existed, rebuilt once from the proposals the app
    made before each of those rounds (`python -m elf.autopilot seed`). Never rewritten by the pipeline."""
    return PUBLIC.parent / "autopilot_seed.json"


def _seed() -> list[dict]:
    try:
        return json.loads(_seed_path().read_text())["rounds"]
    except (OSError, ValueError, KeyError):
        return []


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


def between_turns(entry: dict, rows: list[dict], turn: int) -> None:
    """Before a later turn of the round: the changes the app proposes for a squad (as for the owner's
    team, optimize.lineup_in_round): a player who already played can only drop to the bench, the armband
    moves only to one who hasn't. rows: this round's optimizer rows (turn, xFPT, real points so far).
    The squad's roles become the new ones (the game scores the final roles); entry["moves"][turn] keeps
    what changed. Rewritten on every run until that turn starts, like the round's own decision."""
    by_id = {p["id"]: p for p in rows}
    sq = []
    for p in entry["squad"]:
        r = by_id.get(p["id"]) or {}
        t = r.get("turn")
        played = p["position"] != "Head Coach" and t is not None and t < turn
        sq.append({"id": p["id"], "position": p["position"], "price": 0.0, "turn": t, "played": played,
                   "x_now": float(r.get("actual") or 0.0) if played else float(r.get("x_now") or 0.0),
                   "cur_role": p["role"], "cur_captain": bool(p["captain"])})
    court = [q for q in sq if q["position"] != "Head Coach"]
    if not any(q["played"] for q in court) or all(q["played"] for q in court):
        return
    res = optimize.lineup_in_round(sq)
    if not res:
        return
    new = {q["id"]: q for q in res["team"]}
    start = ("5άδα", "6ος")
    ins = [p["id"] for p in entry["squad"] if p["role"] == "πάγκος" and new[p["id"]]["role"] in start]
    outs = [p["id"] for p in entry["squad"] if p["role"] in start and new[p["id"]]["role"] == "πάγκος"]
    cap_old = next((p["id"] for p in entry["squad"] if p["captain"]), None)
    cap_new = next((q["id"] for q in res["team"] if q["captain"]), None)
    moves = entry.setdefault("moves", {})
    if not ins and not outs and cap_new == cap_old:
        return
    for p in entry["squad"]:
        p["role"], p["captain"] = new[p["id"]]["role"], bool(new[p["id"]]["captain"])
    moves[str(turn)] = {"in": ins, "out": outs, "captain": cap_new if cap_new != cap_old else None}


def _upcoming_turn(rows: list[dict], played_teams: set) -> int | None:
    """The next turn of the round under way: the earliest turn of a team that hasn't played it yet."""
    todo = [r["turn"] for r in rows if r.get("turn") and r.get("team") not in played_teams]
    return min(todo) if todo else None


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


def _rank(done: list[dict], overall: dict) -> None:
    """The position the autopilot's season total would have in the game's general classification after
    the round just finished (overall: {id, teams, matchday_id, round, my_total} of that round), and the
    owner's for comparison (my_rank: personal edition only). Once per round; the game's standings of a
    past matchday are fixed, so an earlier round is never ranked again."""
    total = 0.0
    for e in done:
        total += e["pts"]
        if e["round"] != overall.get("round") or e.get("rank") is not None:
            continue
        try:
            e["rank"] = fantasy.rank_of(total, overall["id"], overall["matchday_id"], overall["teams"])
            e["teams"] = overall["teams"]
            if overall.get("my_total") is not None:
                e["my_rank"] = fantasy.rank_of(overall["my_total"], overall["id"], overall["matchday_id"],
                                               overall["teams"])
        except Exception:  # noqa: BLE001 - the rank is an extra; next run tries again
            e.pop("rank", None)


def update(season: int, rnd: int, trade_rnd: int, rows: list[dict], table: pd.DataFrame,
           max_trades: int, min_gain: float, my_points: dict | None = None, overall: dict | None = None) -> dict:
    """Decide the coming round (until its tip-off), score the finished ones."""
    state = load()
    seed = _seed()
    sid = hashlib.sha1(json.dumps(seed, sort_keys=True).encode()).hexdigest()[:12] if seed else None
    if seed and (not state["rounds"] or state["rounds"][0]["round"] > seed[0]["round"]
                 or state.get("seed_id") != sid):
        # start from round 1, as a real manager; a rebuilt seed replaces its rounds (scored again)
        last = seed[-1]["round"]
        state = {"rounds": [dict(e) for e in seed] + [e for e in state["rounds"] if e["round"] > last]}
    if sid:
        state["seed_id"] = sid
    kept = [r for r in state["rounds"] if r["round"] < trade_rnd]      # frozen: already under way or done
    state["rounds"] = kept
    entry = decide(state, trade_rnd, rows, table, max_trades, min_gain)
    if entry:
        state["rounds"].append(entry)
    state.setdefault("start_round", state["rounds"][0]["round"] if state["rounds"] else None)

    pts, _ = actual_points(season)
    games = history.load("games", season)
    fp = pts.groupby(["round", "person_id"])["fp"].sum() if not pts.empty else pd.Series(dtype=float)
    cur = next((e for e in state["rounds"] if e["round"] == rnd and rnd < trade_rnd and e.get("pts") is None), None)
    if cur is not None and not games.empty:                           # the round under way: T1 -> T2 ...
        rg = games[games["round"] == rnd]
        done = set(rg.loc[rg["played"], "home"]) | set(rg.loc[rg["played"], "away"])
        turn = _upcoming_turn(rows, done)
        tt = {r["team"] for r in rows if r.get("turn") == turn}
        first = pd.to_datetime(rg.loc[rg["home"].isin(tt) | rg["away"].isin(tt), "utc"], utc=True).min()
        if turn and pd.notna(first) and first > pd.Timestamp.now(tz="UTC"):    # frozen once it starts
            between_turns(cur, rows, turn)
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
    if overall:
        _rank(done, overall)
    state["total"] = {"rounds": len(done), "pts": round(sum(e["pts"] for e in done), 1),
                      "raw": round(sum(e["raw"] for e in done), 1),
                      "avg_raw": round(sum(e["avg_raw"] for e in done if e.get("avg_raw") is not None), 1)
                      if any(e.get("avg_raw") is not None for e in done) else None}
    _save(state)
    return state


# ------------------------------------------------------------------ seed: the rounds before it existed

def _rows(pred: dict) -> tuple[list[dict], pd.DataFrame]:
    """Optimizer rows and the players table from a saved predictions.json (as run.py builds them)."""
    t = pd.DataFrame(pred["players"]).dropna(subset=["price", "fantasy_id"])
    t = t[t["position"].isin(["Guard", "Forward", "Center", "Head Coach"])]
    num = lambda v: float(v) if v == v and v is not None else 0.0          # noqa: E731
    rows = [{"id": int(r["fantasy_id"]), "position": r["position"], "price": float(r["price"]),
             "x_h": num(r["x_h"]), "x_now": num(r["x_now"]), "team": r["team"],
             "turn": int(r["turn"]) if r.get("turn") == r.get("turn") and r.get("turn") else None,
             "actual": r.get("actual") if r.get("actual") == r.get("actual") else None}
            for r in t.to_dict("records")]
    return rows, t


def seed_rounds(snapshots: list[tuple], max_trades: int = 4, min_gain: float = 2.0) -> list[dict]:
    """The autopilot's decisions for past rounds from the app's last predictions before each of them:
    the first is the proposed squad from scratch (`best_team`, as shown), the rest are decide().
    A snapshot (round, predictions, turn) is the last one before a later turn: its changes."""
    state = {"rounds": []}
    for rnd, pred, *turn in snapshots:
        rows, table = _rows(pred)
        if turn and turn[0]:
            between_turns(next(e for e in state["rounds"] if e["round"] == rnd), rows, turn[0])
            continue
        if not state["rounds"]:
            # the proposed squad; its lineup by the game's rules, as for every later round: a T1 five
            # (>= 1 per position, the best xFPT), later-turn players on the bench, captain x2
            # (the saved proposal of round 1 predates the turn-aware lineup)
            info, bt = _info(table), pred["best_team"]
            by_id = {p["id"]: p for p in rows}
            lu = optimize.lineup([{**p, **{k: v for k, v in by_id.get(p["id"], {}).items()
                                            if k in ("turn", "x_now", "x_h")}} for p in bt["team"]])
            role = {p["id"]: (p["role"], bool(p["captain"])) for p in (lu or bt)["team"]}
            squad = [{"id": p["id"], "price": p["price"], "position": p["position"],
                      **{k: info.get(p["id"], {}).get(k) for k in ("person_id", "name", "team")},
                      "role": role[p["id"]][0], "captain": role[p["id"]][1], "x_now": round(p["x_now"], 1)}
                     for p in bt["team"]]
            x = sum(p["x_now"] * (BENCH_MULTIPLIER if p["role"] == "πάγκος" else 1.0)
                    * (CAPTAIN_MULTIPLIER if p["captain"] else 1) for p in squad)
            entry = {"round": rnd, "trades": 0, "bank": round(BUDGET - float(bt["cost"]), 1),
                     "squad": squad, "x_total": round(x, 1)}
        else:
            entry = decide(state, rnd, rows, table, max_trades, min_gain)
        if not entry:
            raise ValueError(f"no decision for round {rnd}")
        state["rounds"].append(entry)
    return state["rounds"]


def main(args: list[str]) -> dict:
    """python -m elf.autopilot seed 1:<predictions before round 1> 1.2:<... before its turn 2> 2:<...> ..."""
    snaps = []
    for a in args:
        key, path = a.split(":", 1)
        rnd, _, turn = key.partition(".")
        snaps.append((int(rnd), json.loads(open(path).read()), int(turn) if turn else None))
    out = {"note": "decisions from the app's last predictions before each round (see autopilot._seed_path)",
           "rounds": seed_rounds(snaps)}
    _seed_path().write_text(json.dumps(out, ensure_ascii=False, indent=1))
    print([(e["round"], e["trades"], e["bank"], e["x_total"]) for e in out["rounds"]])
    return out


if __name__ == "__main__":
    import sys
    main(sys.argv[2:])
