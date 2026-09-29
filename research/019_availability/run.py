"""R&D 019 — how accurate is the availability the app works with?

010, 017 and 018 all point the same way: the value is in knowing who plays, not in the form blend.
The app takes availability from the game (prob_play / is_injured -> 1, 0.5 or 0 for the player's
game, `avail_game`) and scales the player's xFPT for the round with it. How right is it?

For every game already played, the last predictions snapshot before its tip-off (the committed
data/public/predictions.json history on main) is compared with the box score:
  played    on the box score with minutes > 0
  dnp       on the box score, 0 minutes (coach's decision)
  out       not on the box score

  calibration   share who played, per availability (1 / 0.5 / 0)
  surprises     availability 1, relevant (full xFPT >= 8), did not play: points the app counted on
  missed        availability 0 but played: the points left on the table
  proposals     the squad proposed from scratch (best_team) and the owner's suggested lineup:
                how many of their players did not play

python research/019_availability/run.py -> result.json   (needs the git history of main)
"""
import json
import subprocess
import sys
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT))
from elf import history  # noqa: E402
from elf.config import CURRENT_SEASON  # noqa: E402

REF = "origin/main"
FILE = "data/public/predictions.json"
RELEVANT = 8.0


def git(*args) -> str:
    return subprocess.run(["git", "-C", str(ROOT), *args], capture_output=True, text=True, check=True).stdout


def snapshots() -> list[tuple[pd.Timestamp, str]]:
    """(time of the data, commit) of every committed predictions.json, oldest first."""
    out = []
    for line in git("log", REF, "--format=%H %cI", "--", FILE).splitlines():
        h, t = line.split()
        out.append((pd.Timestamp(t).tz_convert("UTC"), h))
    return sorted(out)


def load(commit: str) -> dict:
    return json.loads(git("show", f"{commit}:{FILE}"))


def _lineup(lu) -> list:
    """The owner's suggested lineup: a list of players (older snapshots: {"team": [...]})."""
    return lu if isinstance(lu, list) else (lu or {}).get("team") or []


def news_names(snaps) -> dict:
    """News statuses (out / doubtful / questionable) in every committed summary: how many reached a
    roster player with the old key (exact word order) and how many with the order-free one."""
    from elf.run import _key, _pkey
    seen, old, new, total = set(), 0, 0, 0
    for _, h in snaps:
        try:
            dig = json.loads(git("show", f"{h}:data/public/news.json")).get("digest") or {}
        except Exception:  # noqa: BLE001 - an early commit without news.json
            continue
        names = [p.get("name") for p in load(h)["players"]]
        ko, kn = {_key(n) for n in names}, {_pkey(n) for n in names}
        for a in dig.get("availability") or []:
            if a.get("status") == "available":
                continue
            name = str(a.get("player", "")).split(" (")[0]
            if (name, a.get("status")) in seen:
                continue
            seen.add((name, a.get("status")))
            total += 1
            old += _key(name) in ko
            new += _pkey(name) in kn
    return {"statuses": total, "applied_before": old, "applied_now": new}


def main():
    games = history.load("games", CURRENT_SEASON)
    games["utc"] = pd.to_datetime(games["utc"], utc=True)
    box = history.load("players", CURRENT_SEASON)
    box["person_id"] = box["person_id"].astype(str)
    done = games[games["played"]]
    snaps = snapshots()
    cache = {}
    rows = []
    proposals = []
    for g in done.itertuples():
        before = [s for s in snaps if s[0] < g.utc]
        if not before:
            continue
        t, h = before[-1]
        pred = cache.get(h) or cache.setdefault(h, load(h))
        gt = pd.Timestamp(pred.get("generated") or t)
        gt = gt.tz_localize("UTC") if gt.tzinfo is None else gt.tz_convert("UTC")
        if gt >= g.utc:                                   # data made after tip-off: not a forecast
            continue
        b = box[box["gamecode"] == g.gamecode]
        mins = b.set_index("person_id")["min"]
        for p in pred["players"]:
            if p.get("team") not in (g.home, g.away) or p.get("position") == "Head Coach":
                continue
            pid = str(p.get("person_id"))
            a = p.get("avail_game")
            a = 1.0 if a is None else float(a)
            x = float(p.get("x_now") or 0.0)
            full = x / a if a > 0 else float(p.get("base") or 0.0) * 1.05   # xFPT had he been fit
            status = "played" if pid in mins.index and mins[pid] > 0 else "dnp" if pid in mins.index else "out"
            rows.append({"round": g.round, "gamecode": g.gamecode, "hours_before": round((g.utc - gt).total_seconds() / 3600, 1),
                         "person_id": pid, "name": p.get("name"), "team": p.get("team"), "avail": a,
                         "x_now": x, "x_full": full, "status": status})
        # proposals made in that snapshot, for this game's players
        for kind, team in (("best_team", (pred.get("best_team") or {}).get("team") or []),
                           ("my_lineup", _lineup((pred.get("my_team") or {}).get("lineup")))):
            for q in team:
                if q.get("position") == "Head Coach" or q.get("team") not in (g.home, g.away):
                    continue
                pid = next((str(p.get("person_id")) for p in pred["players"]
                            if p.get("fantasy_id") == q.get("id")), None)
                if pid is None:
                    continue
                st = "played" if pid in mins.index and mins[pid] > 0 else "dnp" if pid in mins.index else "out"
                proposals.append({"kind": kind, "round": g.round, "name": q.get("name"), "role": q.get("role"),
                                  "x_now": q.get("x_now"), "status": st})
    df = pd.DataFrame(rows)
    pr = pd.DataFrame(proposals)
    res = {"games": int(df["gamecode"].nunique()), "rows": len(df),
           "hours_before_median": float(df.drop_duplicates("gamecode")["hours_before"].median())}
    cal = {}
    for a, g in df.groupby("avail"):
        rel = g[g["x_full"] >= RELEVANT]
        cal[str(a)] = {"n": len(g), "played": round(float((g["status"] == "played").mean()), 3),
                       "n_relevant": len(rel),
                       "played_relevant": round(float((rel["status"] == "played").mean()), 3) if len(rel) else None}
    res["calibration"] = cal
    sur = df[(df["avail"] == 1) & (df["x_full"] >= RELEVANT) & (df["status"] != "played")]
    res["surprises"] = {"n": len(sur), "of_relevant_fit": int(((df["avail"] == 1) & (df["x_full"] >= RELEVANT)).sum()),
                        "xfpt_counted": round(float(sur["x_now"].sum()), 1),
                        "list": sur[["round", "name", "team", "x_now", "status", "hours_before"]].round(1).to_dict("records")}
    act = box.assign(fp=box["pir"]).set_index(["gamecode", "person_id"])["fp"]
    mis = df[(df["avail"] == 0) & (df["status"] == "played")]
    res["missed"] = {"n": len(mis), "of_out": int((df["avail"] == 0).sum()),
                     "list": [{"round": r.round, "name": r.name, "team": r.team,
                               "pir": float(act.get((r.gamecode, r.person_id), 0.0))} for r in mis.itertuples()]}
    half = df[df["avail"] == 0.5]
    res["half"] = {"n": len(half), "list": half[["round", "name", "team", "x_full", "status"]].round(1).to_dict("records")}
    res["proposals"] = {k: {"n": len(g), "not_played": int((g["status"] != "played").sum()),
                            "list": g[g["status"] != "played"][["round", "name", "role", "status"]].to_dict("records")}
                        for k, g in pr.groupby("kind")} if not pr.empty else {}
    res["news_names"] = news_names(snaps)
    (HERE / "result.json").write_text(json.dumps(res, ensure_ascii=False, indent=1, default=str))
    print(json.dumps(res, ensure_ascii=False, indent=1, default=str))


if __name__ == "__main__":
    main()
