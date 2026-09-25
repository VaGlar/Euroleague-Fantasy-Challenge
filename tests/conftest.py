"""Shared fixtures. Tests never touch the network or the committed data/public files."""
from __future__ import annotations

import copy
import json
import shutil
from pathlib import Path

import pytest
import requests

from elf import config, fantasy, lineup_cmd, model, notify, prices, run

REPO = Path(__file__).resolve().parent.parent
FORMS = {"2-2-1": 27, "2-1-2": 28, "1-2-2": 29, "1-3-1": 30, "3-1-1": 31}
POS = ("Guard", "Forward", "Center")


def block_network(mp):
    """Any real HTTP call fails the test: every external API must be mocked."""
    def boom(*a, **k):
        raise AssertionError(f"network call in a test: {a[:2]}")
    for name in ("get", "post", "put"):
        mp.setattr(requests, name, boom)
    mp.setattr(requests.Session, "request", boom)


def use_public(mp, pub: Path) -> Path:
    """Point every module that reads/writes data/public at a private folder."""
    pub.mkdir(parents=True, exist_ok=True)
    for mod in (config, run, prices, lineup_cmd, model, notify):
        if hasattr(mod, "PUBLIC"):
            mp.setattr(mod, "PUBLIC", pub)
    return pub


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    block_network(monkeypatch)


@pytest.fixture
def public(tmp_path, monkeypatch):
    return use_public(monkeypatch, tmp_path / "public")


def seed_public(pub: Path, *names: str):
    for n in names:
        src = REPO / "data" / "public" / n
        if src.exists():
            shutil.copy(src, pub / n)


# --------------------------------------------------------------- squads

def player(pid, pos, x, turn=1, price=5.0, **kw):
    return {"id": pid, "position": pos, "price": price, "x_now": x, "x_h": x * 1.95,
            "turn": turn, "name": f"P{pid}", **kw}


def squad_t1_t2():
    """10 court players + coach. Exactly 6 play in turn 1 (1 Center among them); the
    strongest turn-2 players would win a turn-blind lineup."""
    return [
        player(1, "Guard", 20, 1), player(2, "Guard", 12, 1),
        player(3, "Guard", 15, 2), player(4, "Guard", 3, 2),
        player(5, "Forward", 18, 1), player(6, "Forward", 10, 1),
        player(7, "Forward", 4, 1), player(8, "Forward", 16, 2),
        player(9, "Center", 6, 1), player(10, "Center", 17, 2),
        player(11, "Head Coach", 5, 1),
    ]


# ---------------------------------------------------------- fake Dunkest

class FakeGame:
    """In-memory stand-in for the Dunkest fantasy API (roster read/write)."""

    def __init__(self, squad, roles, captain, played=None, persist=True, status=200,
                 league_status=1, reply="ok"):
        self.squad = {p["id"]: p for p in squad}
        self.played = played or {}          # id -> real points
        self.persist, self.status = persist, status
        self.league_status, self.reply = league_status, reply
        self.saved = []
        order = {"Center": 0, "Forward": 1, "Guard": 2}   # the game's slot order: C -> F -> G
        rank = {"5άδα": 0, "6ος": 1, "πάγκος": 2}
        court = sorted((p for p in squad if p["position"] != "Head Coach"),
                       key=lambda p: (rank[roles[p["id"]]], order[p["position"]], p["id"]))
        coach = [p for p in squad if p["position"] == "Head Coach"]
        self.state = {"players": [self._raw(p, i, p["id"] == captain)
                                  for i, p in enumerate(court + coach, 1)]}
        five = court[:5]
        name = "-".join(str(sum(q["position"] == pos for q in five)) for pos in POS)
        self.state["formation_id"] = FORMS[name]

    def _raw(self, p, slot, cap):
        played = p["id"] in self.played
        return {"id": p["id"], "first_name": "F", "last_name": p["name"],
                "position": {"name": p["position"]}, "team": {"abbreviation": "AAA"},
                "quotation": p["price"], "court_position": slot, "is_captain": cap,
                "match_played": played, "pts": self.played.get(p["id"], 0),
                "round": {"id": 1, "number": p["turn"]}, "is_injured": False,
                "probability_of_playing": 100}

    # API surface used by elf.lineup_cmd / elf.run
    def config(self):
        return {"status_id": self.league_status,
                "current_matchday": {"id": 500, "number": 1}, "current_round": {"number": 1},
                "current_players_list_id": 9}

    def my_teams(self, *a, **k):
        return [{"id": 1, "name": "TEST"}]

    def roster(self, *a, **k):
        return copy.deepcopy(self.state)

    def formations(self, current_id=None):
        return dict(FORMS)

    def illegal(self, body):
        """The game's in-round rule: a played player may leave the starting six only
        for the bench; a played bench player stays; the armband only to the unplayed."""
        court = sorted(p["court_position"] for p in self.state["players"]
                       if p["position"]["name"] in POS)
        start = set(court[:6])
        new = {b["id"]: b for b in body["players"]}
        for p in self.state["players"]:
            if not p["match_played"] or p["position"]["name"] not in POS:
                continue
            old_s, new_s = p["court_position"], new[p["id"]]["court_position"]
            if new_s in start and new_s != old_s:
                return True
            if new[p["id"]]["is_captain"] and not p["is_captain"]:
                return True
        return False

    def save_roster(self, tid, md, body):
        self.saved.append(body)
        if self.status < 400 and self.illegal(body):
            class Bad:
                status_code = 422
                text = ('{"code":"VALIDATION_ERROR","message":"Illegal moves: at least one '
                        'team has already played."}')
            return Bad()
        if self.status < 400 and self.persist:
            for b in body["players"]:
                for p in self.state["players"]:
                    if p["id"] == b["id"]:
                        p["court_position"], p["is_captain"] = b["court_position"], b["is_captain"]
            self.state["formation_id"] = body["formation_id"]

        class R:
            status_code = self.status
            text = self.reply
        return R()

    def install(self, monkeypatch):
        for n in ("config", "my_teams", "roster", "formations", "save_roster"):
            monkeypatch.setattr(fantasy, n, getattr(self, n))
        return self

    def lineup(self):
        """Current roles/captain as the game would show them."""
        court = sorted((p for p in self.state["players"] if p["position"]["name"] in POS),
                       key=lambda p: p["court_position"])
        roles = {p["id"]: ("5άδα" if i < 5 else "6ος" if i == 5 else "πάγκος")
                 for i, p in enumerate(court)}
        cap = next(p["id"] for p in self.state["players"] if p["is_captain"])
        return roles, cap


def write_predictions(pub: Path, squad):
    (pub / "predictions.json").write_text(json.dumps(
        {"players": [{"fantasy_id": p["id"], "x_now": p["x_now"]} for p in squad]}))
