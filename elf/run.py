"""Daily pipeline: data -> predictions -> fantasy team advice -> report JSON.

python -m elf.run            full update (what CI runs)
python -m elf.run --offline  skip network except what is cached (debug)
"""
from __future__ import annotations

import argparse
import json
import os
import unicodedata
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import yaml

from . import el_api, fantasy, history, model, news
from .config import BUDGET, CURRENT_SEASON, PUBLIC, ROOT, TIMEZONE

ATH = ZoneInfo(TIMEZONE)
HORIZON = 3  # rounds used for transfer value
DAYS_EL = ["Δευτέρα", "Τρίτη", "Τετάρτη", "Πέμπτη", "Παρασκευή", "Σάββατο", "Κυριακή"]


def _key(s: str) -> str:
    s = unicodedata.normalize("NFD", str(s).lower())
    return "".join(c for c in s if c.isalnum() and unicodedata.category(c) != "Mn")


def _clean(o):
    """NaN/inf -> None recursively: browsers reject NaN in JSON."""
    if isinstance(o, float) and not np.isfinite(o):
        return None
    if isinstance(o, dict):
        return {k: _clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_clean(v) for v in o]
    if isinstance(o, (np.floating,)):
        return _clean(float(o))
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.bool_,)):
        return bool(o)
    return o


def _write(name: str, obj) -> None:
    PUBLIC.mkdir(parents=True, exist_ok=True)
    (PUBLIC / name).write_text(json.dumps(_clean(obj), ensure_ascii=False, indent=1,
                                          default=str, allow_nan=False))


# ------------------------------------------------------------ predictions

def predictions(season: int):
    games = history.load("games", season)
    games["utc"] = pd.to_datetime(games["utc"], utc=True)
    cur_p, cur_t = history.load("players", season), history.load("teams", season)
    prev_p, prev_t = history.load("players", season - 1), history.load("teams", season - 1)
    people = history.load("people", season)
    roster = people[(people["type"] == "player") & people["active"]] \
        .rename(columns={"club": "team"})[["person_id", "name", "team", "position"]]

    p = model.params()
    codes = sorted(set(games["home"]) | set(games["away"]))
    ratings = model.team_ratings(cur_t, prev_t, codes, p)
    pos_map = dict(zip(roster["person_id"], roster["position"]))
    for s in (season - 1,):
        pp = history.load("people", s)
        if not pp.empty:
            for k, v in zip(pp["person_id"], pp["position"]):
                pos_map.setdefault(k, v)
    pdev = model.position_allowed(cur_p, prev_p, pos_map, p)
    base = model.player_base(cur_p, prev_p, p)

    upcoming = games[~games["played"]].sort_values("utc")
    if upcoming.empty:
        return None
    first = int(upcoming["round"].iloc[0])
    fx = upcoming[upcoming["round"].between(first, first + HORIZON - 1)]
    ctx = model.context_rows(fx, roster, ratings, pdev)
    ctx = ctx.merge(base[["base", "last3_pir", "season_pir", "prev_pir", "games", "season_min",
                          "prev_min"]] if "prev_min" in base else base,
                    left_on="person_id", right_index=True, how="left")
    ctx = ctx.merge(roster[["person_id", "name"]], on="person_id", how="left")
    ctx["no_data"] = ctx["base"].isna()
    ctx["base"] = ctx["base"].fillna(0)
    ctx["xpir"] = model.xpir(ctx, p).clip(lower=0)
    ctx["xpir"] = model.fantasy_points(ctx["xpir"], ctx["margin"])  # +10% win bonus
    coaches = coach_rows(fx, people, ratings)
    return {"round": first, "fixtures": fx, "ctx": ctx, "ratings": ratings, "roster": roster,
            "params": p, "coaches": coaches}


def coach_rows(fx: pd.DataFrame, people: pd.DataFrame, ratings: pd.DataFrame) -> pd.DataFrame:
    """Expected coach score per fixture from the expected margin distribution."""
    heads = people[(people["type"] == "coach") & people["active"]] \
        .drop_duplicates("club", keep="last").set_index("club")
    rows = []
    for f in fx.itertuples():
        for team, opp, home in ((f.home, f.away, True), (f.away, f.home, False)):
            if team not in ratings.index or opp not in ratings.index or team not in heads.index:
                continue
            rt, ro = ratings.loc[team], ratings.loc[opp]
            pace = (rt["pace"] + ro["pace"]) / 2
            m = (rt["net"] - ro["net"] + (rt["hca"] if home else -ro["hca"])) * pace / 100
            rows.append({"round": f.round, "person_id": heads.loc[team, "person_id"],
                         "name": heads.loc[team, "name"], "team": team, "opp": opp,
                         "is_home": home, "margin": m, "xpir": model.coach_points(m),
                         "position": "Head Coach", "pos_dev": np.nan, "base": np.nan,
                         "no_data": False, "win_prob": model.win_prob(m)})
    return pd.DataFrame(rows)


# --------------------------------------------------------------- fantasy

SUFFIXES = ("jr", "sr", "ii", "iii", "iv")


def _surname(s: str) -> str:
    k = _key(s)
    for suf in SUFFIXES:
        if k.endswith(suf) and len(k) > len(suf) + 2:
            k = k[: -len(suf)]
    return k


def match_people(fp: pd.DataFrame, roster: pd.DataFrame) -> pd.Series:
    """Fantasy player -> EuroLeague person_id: exact surname+team, then fuzzy within team."""
    import difflib

    r = roster.assign(sur=roster["name"].str.split(",").str[0].map(_surname),
                      first=roster["name"].str.split(",").str[1].fillna("").map(_key))
    by_team = {t: g for t, g in r.groupby("team")}
    ids = []
    for p in fp.itertuples():
        g = by_team.get(p.team)
        pid = None
        if g is not None:
            sur = _surname(p.last_name)
            hit = g[g["sur"] == sur]
            if hit.empty:
                close = difflib.get_close_matches(sur, g["sur"].tolist(), n=1, cutoff=0.8)
                hit = g[g["sur"] == close[0]] if close else hit
            if len(hit) > 1:  # same surname in a team: disambiguate by first name
                narrowed = hit[hit["first"].str.startswith(_key(p.first_name)[:3])]
                hit = narrowed if len(narrowed) else hit
            if len(hit):
                pid = hit["person_id"].iloc[0]
        ids.append(pid)
    return pd.Series(ids, index=fp.index)


def fantasy_state(clubs: pd.DataFrame, roster: pd.DataFrame) -> dict:
    """Prices + my team. Never raises: returns {'error': ...} instead."""
    out = {"ok": False}
    try:
        cfg = fantasy.config()
        out["config"] = {k: cfg.get(k) for k in ("current_matchday", "current_round",
                                                   "current_players_list_id")}
        md = cfg["current_matchday"]
        raw = fantasy.players(cfg["current_players_list_id"], md["id"])
        fp = pd.DataFrame([fantasy.normalize_player(x) for x in raw])
        tv2code = dict(zip(clubs["tv"], clubs["code"]))
        fp["team"] = fp["team"].map(lambda t: tv2code.get(t, t))
        fp["person_id"] = match_people(fp, roster)
        out["players"] = fp
        out["unmatched"] = int(fp.loc[fp["position"] != "Head Coach", "person_id"].isna().sum())

        # price history (append one snapshot per matchday)
        hist_path = PUBLIC / "prices.csv"
        snap = fp[["fantasy_id", "person_id", "first_name", "last_name", "team", "position",
                   "price"]].assign(matchday=md["number"])
        if hist_path.exists():
            old = pd.read_csv(hist_path, dtype={"person_id": str})
            old = old[old["matchday"] != md["number"]]
            snap = pd.concat([old, snap], ignore_index=True)
        snap.to_csv(hist_path, index=False)

        out["ok"] = True
    except fantasy.TokenError as e:
        out["error"] = f"token: {e}"
        return out
    except Exception as e:  # noqa: BLE001 - report, never crash the pipeline
        out["error"] = f"τιμές: {type(e).__name__}: {e}"
        return out

    # my team is a separate step: prices stay usable even if this fails
    out["my_teams"] = []
    try:
        for t in fantasy.my_teams():
            ros = fantasy.roster(t["id"], md["id"])
            out["my_teams"].append({"id": t["id"], "name": t.get("name"), "raw": ros})
            _write("roster_shape.json", _shape(ros))  # structure only, for debugging
    except fantasy.TokenError as e:
        out["error"] = f"token: {e}"
    except Exception as e:  # noqa: BLE001
        out["team_error"] = f"ομάδα: {type(e).__name__}: {e}"
    return out


def _shape(o, depth: int = 0):
    """Keys and types of a JSON payload without its values (safe to publish)."""
    if depth > 5:
        return "…"
    if isinstance(o, dict):
        return {k: _shape(v, depth + 1) for k, v in o.items()}
    if isinstance(o, list):
        return [_shape(o[0], depth + 1), f"×{len(o)}"] if o else []
    return type(o).__name__


def parse_my_roster(raw: dict) -> tuple[list[int], dict]:
    """Extract fantasy player ids (+ captain, bank) from an undocumented roster payload."""
    ids, meta = [], {}

    def walk(o):
        if isinstance(o, dict):
            # a roster slot: {"id", "court_position", "is_captain", ...} or {"player": {...}}
            if isinstance(o.get("player"), dict) and "id" in o["player"]:
                pid = o["player"]["id"]
                ids.append(pid)
                if o.get("is_captain") or o["player"].get("is_captain"):
                    meta["captain"] = pid
                return
            if "id" in o and ("court_position" in o or "quotation" in o or "is_captain" in o):
                ids.append(o["id"])
                if o.get("is_captain"):
                    meta["captain"] = o["id"]
                return
            for k in ("credits", "remaining_credits", "bank", "budget_left"):
                if isinstance(o.get(k), (int, float)) and "bank" not in meta:
                    meta["bank"] = float(o[k])
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)
    walk(raw)
    return list(dict.fromkeys(ids)), meta


def suggest_transfers(team: pd.DataFrame, pool: pd.DataFrame, bank: float, max_trades: int = 4,
                      min_gain: float = 3.0) -> list[dict]:
    """Greedy same-position swaps maximising xPIR over the horizon within budget."""
    team, moves = team.copy(), []
    for _ in range(max_trades):
        best = None
        owned = set(team["fantasy_id"])
        for out in team.itertuples():
            cands = pool[(pool["position"] == out.position) & ~pool["fantasy_id"].isin(owned)
                         & (pool["price"] <= out.price + bank)]
            if cands.empty:
                continue
            c = cands.loc[cands["x_h"].idxmax()]
            gain = c["x_h"] - out.x_h
            if best is None or gain > best[0]:
                best = (gain, out, c)
        if not best or best[0] < min_gain:
            break
        gain, out, c = best
        bank += out.price - c["price"]
        moves.append({"out": out.label, "in": c["label"], "gain": round(float(gain), 1),
                      "price_out": out.price, "price_in": float(c["price"]),
                      "bank_after": round(bank, 1)})
        team = pd.concat([team[team["fantasy_id"] != out.fantasy_id], c.to_frame().T])
    return moves


def previous_digest(max_hours: int = 36):
    """Last successful Gemini digest if recent enough (Gemini is often overloaded)."""
    try:
        old = json.loads((PUBLIC / "news.json").read_text())
        at = datetime.fromisoformat(old["digest_at"])
        if old.get("digest") and datetime.now(timezone.utc) - at < pd.Timedelta(hours=max_hours):
            return old["digest"], old["digest_at"]
    except (OSError, KeyError, TypeError, ValueError):
        pass
    return None, None


def manual_team(table: pd.DataFrame) -> dict | None:
    """Fallback when the fantasy API is unavailable: my_team.yaml lists the squad.

    No prices -> no transfer suggestions, but lineup/captain advice still works.
    """
    path = ROOT / "my_team.yaml"
    if not path.exists():
        return None
    cfg = yaml.safe_load(path.read_text()) or {}
    wanted = [(_key(p.split("(")[0]), p.split("(")[1].strip(" )").upper() if "(" in p else None)
              for p in cfg.get("players", [])]
    t = table.assign(sk=table["name"].str.split(",").str[0].map(_key))
    rows = [t[(t["sk"] == k) & ((t["team"] == tm) if tm else True)].head(1) for k, tm in wanted]
    mine = pd.concat(rows) if rows else t.head(0)
    return {"name": cfg.get("name", "Η ομάδα μου (χειροκίνητα)"), "manual": True,
            "players": mine.drop(columns="sk").sort_values("x_now", ascending=False)
            .replace({np.nan: None}).to_dict("records"),
            "bank": None, "captain_id": None, "transfers": [], "parsed_players": len(mine)}


# ---------------------------------------------------------------- report

def turns(fx: pd.DataFrame, rnd: int) -> list[dict]:
    g = fx[fx["round"] == rnd].copy()
    g["local"] = g["utc"].dt.tz_convert(ATH)
    g["day"] = g["local"].dt.date
    out = []
    for i, (day, d) in enumerate(sorted(g.groupby("day"), key=lambda x: x[0]), 1):
        out.append({"turn": i, "date": str(day), "first_tip": d["local"].min().strftime("%H:%M"),
                    "teams": sorted(set(d["home"]) | set(d["away"])),
                    "games": [f"{a.home}-{a.away} {a.local:%H:%M}" for a in d.itertuples()]})
    return out


def build(offline: bool = False) -> dict:
    season = CURRENT_SEASON
    if not offline:
        history.update_season(season - 1, refresh_people=False)
        history.update_season(season)
    clubs = pd.DataFrame(el_api.clubs(season))
    _write("clubs.json", clubs.to_dict("records"))
    pr = predictions(season)
    if pr is None:
        _write("report.json", {"generated": datetime.now(timezone.utc).isoformat(), "messages": []})
        return {}
    ctx, rnd = pr["ctx"], pr["round"]
    health = []

    # --- news & availability
    names = sorted(ctx["name"].dropna().unique())
    team_of = dict(zip(ctx["name"], ctx["team"]))
    arts, failed = ([], []) if offline else news.collect(names)
    health += [f"πηγή εκτός: {f}" for f in failed]
    dig, dig_at = None, None
    try:
        dig = news.digest(arts, [f"{n} ({team_of.get(n)})" for n in names])
        dig_at = datetime.now(timezone.utc).isoformat() if dig else None
    except Exception as e:  # noqa: BLE001
        dig, dig_at = previous_digest()
        note = " — κρατήθηκε η προηγούμενη σύνοψη" if dig else ""
        health.append((f"{e}" if isinstance(e, RuntimeError)
                       else f"Gemini: {type(e).__name__}") + note)
    avail = {}
    for a in (dig or {}).get("availability", []):
        f = news.AVAILABILITY_FACTOR.get(a.get("status"), 1.0)
        avail[_key(a.get("player", "").split(" (")[0])] = (f, a)
    ctx["avail"] = ctx["name"].map(lambda n: avail.get(_key(n), (1.0, None))[0])
    ctx["xpir"] = ctx["xpir"] * ctx["avail"]
    _write("news.json", {"articles": arts[:120], "digest": dig, "digest_at": dig_at,
                         "failed": failed})

    # --- per-player tables (coaches ride along with position "Head Coach")
    if not pr["coaches"].empty:
        ctx = pd.concat([ctx, pr["coaches"]], ignore_index=True)
    now_round = ctx[ctx["round"] == rnd]
    agg = ctx.groupby("person_id").agg(
        name=("name", "first"), team=("team", "first"), position=("position", "first"),
        x_h=("xpir", "sum"), base=("base", "first"), no_data=("no_data", "first"),
        season_pir=("season_pir", "first"), prev_pir=("prev_pir", "first"),
        season_min=("season_min", "first"))
    nr = now_round.groupby("person_id").agg(x_now=("xpir", "sum"), opp=("opp", "first"),
                                            home=("is_home", "first"), margin=("margin", "first"),
                                            pos_dev=("pos_dev", "first"))
    table = agg.join(nr, how="left").reset_index()

    # --- fantasy prices / my team
    people_all = pd.concat([pr["roster"], pr["coaches"][["person_id", "name", "team"]]
                            .drop_duplicates("person_id")], ignore_index=True)
    fs = {"ok": False, "error": "offline"} if offline else fantasy_state(clubs, people_all)
    my = None
    if fs.get("ok"):
        fp = fs["players"]
        table = table.merge(fp.dropna(subset=["person_id"]).drop_duplicates("person_id")
                            [["person_id", "fantasy_id", "price", "status", "position"]]
                            .rename(columns={"position": "f_position"}), on="person_id", how="left")
        # squad slots follow the fantasy game's position, not the EuroLeague listing
        table["position"] = table["f_position"].fillna(table["position"])
        table["value"] = table["x_h"] / table["price"]
        if fs["unmatched"] > 40:  # a handful of unregistered bench players is normal
            health.append(f"{fs['unmatched']} παίκτες του fantasy λείπουν από τα ρόστερ EuroLeague")
        for t in fs["my_teams"][:1]:
            ids, meta = parse_my_roster(t["raw"])
            mine = table[table["fantasy_id"].isin(ids)].copy()
            pool = table.dropna(subset=["price", "fantasy_id"]).copy()
            for d in (mine, pool):
                d["label"] = d["name"] + " (" + d["team"] + ")"
            bank = meta.get("bank", max(0.0, BUDGET - mine["price"].sum()))
            my = {"name": t["name"], "players": mine.sort_values("x_now", ascending=False)
                  .to_dict("records"), "bank": bank, "captain_id": meta.get("captain"),
                  "transfers": suggest_transfers(mine, pool, bank),
                  "parsed_players": len(ids)}
            if len(ids) < 10:
                health.append(f"ομάδα: βρέθηκαν {len(ids)}/10 παίκτες — έλεγχος parser")
    elif fs.get("error"):
        health.append(f"fantasy: {fs['error']}")
    if fs.get("team_error"):
        health.append(f"fantasy {fs['team_error']}")
    elif fs.get("ok") and not fs.get("my_teams"):
        health.append("fantasy: δεν βρέθηκε ομάδα Classic στον λογαριασμό")
    if os.environ.get("CI") and not os.environ.get("GEMINI_API_KEY"):
        health.append("GEMINI_API_KEY κενό — χωρίς σύνοψη νέων")
    tok = fantasy.token_expiry()
    if tok["days_left"] is not None and tok["days_left"] < 3:
        health.insert(0, "🔑 Το FANTASY_TOKEN λήγει σε "
                      f"{max(tok['days_left'], 0):.1f} μέρες — ανανέωσέ το")
    if my is None:
        my = manual_team(table)

    table = table.sort_values("x_now", ascending=False)
    trn = turns(pr["fixtures"], rnd)
    ratings = pr["ratings"].sort_values("net", ascending=False).reset_index()
    _write("predictions.json", {
        "generated": datetime.now(timezone.utc).isoformat(), "round": rnd, "turns": trn,
        "players": table.replace({np.nan: None}).to_dict("records"),
        "team_ratings": ratings.round(2).to_dict("records"),
        "fixtures": [{"round": int(f.round), "home": f.home, "away": f.away,
                      "utc": f.utc.isoformat()} for f in pr["fixtures"].itertuples()],
        "my_team": my, "health": health, "fantasy_ok": fs.get("ok", False),
    })
    msgs = messages(rnd, trn, table, my, dig, health)
    _write("report.json", {"generated": datetime.now(timezone.utc).isoformat(),
                           "round": rnd, "messages": msgs})
    return {"round": rnd, "messages": msgs}


def _fmt(r) -> str:
    ha = "🏠" if r.get("home") else "✈️"
    return f"{r['name'].split(',')[0].title()} ({r['team']}) {ha} vs {r.get('opp')} — <b>{r['x_now']:.1f}</b>"


def messages(rnd, trn, table, my, dig, health) -> list[dict]:
    dash = os.environ.get("DASHBOARD_URL", "")
    t_all = table.dropna(subset=["x_now"])
    coaches = t_all[t_all["position"] == "Head Coach"]
    t = t_all[t_all["position"] != "Head Coach"]
    msgs = []
    for tu in trn:
        day = datetime.fromisoformat(tu["date"])
        playing = t[t["team"].isin(tu["teams"])]
        later = t[~t["team"].isin(sum([x["teams"] for x in trn if x["turn"] <= tu["turn"]], []))]
        lines = [f"🏀 <b>Αγωνιστική {rnd} — Turn {tu['turn']}</b> "
                 f"({DAYS_EL[day.weekday()]} {day:%d/%m}, 1ο τζάμπολ {tu['first_tip']})", ""]
        lines += ["📅 " + " · ".join(tu["games"]), ""]
        if tu["turn"] == 1:
            lines.append("⭐ <b>Αρχηγός</b>")
            best = t.iloc[0] if len(t) else None
            best_now = playing.iloc[0] if len(playing) else None
            if best_now is not None and best is not None:
                lines.append(f"Turn 1: {_fmt(best_now)}")
                if len(later):
                    lines.append(f"Plan B (Turn 2+): {_fmt(later.iloc[0])}")
                lines.append("<i>Βάλε αρχηγό στο Turn 1· αν δεν φτάσει το xPTS του plan B, "
                             "μεταφέρεις το x2 πριν το Turn 2.</i>")
            if my and my["transfers"]:
                lines += ["", "🔁 <b>Προτεινόμενες αλλαγές</b> (xPTS 3 αγωνιστικών)"]
                for m in my["transfers"]:
                    lines.append(f"• {m['out']} ➜ {m['in']}  (+{m['gain']}, "
                                 f"{m['price_out']}→{m['price_in']})")
            elif my:
                lines += ["", "🔁 Καμία αλλαγή δεν αξίζει αυτή την εβδομάδα."]
        else:
            nxt = playing.head(3)
            lines.append("⭐ <b>Έλεγχος αρχηγού</b>")
            lines.append("Κράτα τον αρχηγό σου αν έφερε ≥ ×1 του καλύτερου διαθέσιμου σήμερα:")
            lines += [f"• {_fmt(r)}" for r in nxt.to_dict("records")]
        if tu["turn"] == 1 and len(coaches):
            c = coaches.sort_values("x_now", ascending=False).iloc[0]
            line = (f"🧑‍💼 <b>Coach</b>: {c['name'].split(',')[0].title()} ({c['team']}) "
                    f"{'🏠' if c.get('home') else '✈️'} vs {c.get('opp')} — <b>{c['x_now']:.1f}</b>")
            if c.get("price") == c.get("price") and c.get("price") is not None:
                line += f" · {c['price']}cr"
            lines += ["", line]
        lines += ["", f"📈 <b>Top xPTS {'σήμερα' if tu['turn'] > 1 else 'αγωνιστικής'}</b>"]
        src = playing if tu["turn"] > 1 else t
        lines += [f"{i}. {_fmt(r)}" for i, r in enumerate(src.head(8).to_dict("records"), 1)]
        if "value" in t and tu["turn"] == 1:
            v = t.dropna(subset=["value"]).sort_values("value", ascending=False).head(5)
            lines += ["", "💰 <b>Value (xPTS/credit, 3 αγων.)</b>"]
            lines += [f"• {r['name'].split(',')[0].title()} ({r['team']}) {r['price']}cr — "
                      f"{r['value']:.2f}" for r in v.to_dict("records")]
        if dig:
            inj = [a for a in dig.get("availability", []) if a.get("status") != "available"]
            if inj:
                lines += ["", "🏥 <b>Διαθεσιμότητα</b>"]
                lines += [f"• {a['player']}: {a['status']} — {a.get('note', '')}" for a in inj[:8]]
            if dig.get("summary_el") and tu["turn"] == 1:
                lines += ["", "📰 <b>Ειδικοί & νέα</b>", dig["summary_el"]]
        if health:
            lines += ["", "⚠️ " + " | ".join(health[:4])]
        if dash:
            lines += ["", f'🔗 <a href="{dash}">Dashboard</a>']
        msgs.append({"date": tu["date"], "turn": tu["turn"], "text": "\n".join(lines)})
    return msgs


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--offline", action="store_true")
    a = ap.parse_args()
    res = build(a.offline)
    for m in res.get("messages", []):
        print(f"--- {m['date']} (turn {m['turn']})\n{m['text']}\n")
