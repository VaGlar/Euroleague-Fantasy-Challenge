"""The code findings of the tester's report of 14/10 (docs/test-reports/2026-10-14-…, section 2):
a sync code typed on a Greek keyboard, only the page's own roles in a synced team, nosniff on the sync's
answers, one «the game is over» for the update's checks and /lineup, the Access JWT of /api/watch
checked, the errors table cleaned. The JS runs in node (tests/review_fixes_runner.mjs)."""
import json
import shutil
import subprocess
from datetime import date, timedelta
from pathlib import Path

import pytest

from elf import checks, lineup_cmd

from conftest import FakeGame, squad_t1_t2

node = shutil.which("node")
RUNNER = Path(__file__).with_name("review_fixes_runner.mjs")
ROLES_OK = {"1": "5άδα", "2": "6ος", "3": "πάγκος", "11": "coach"}
PLAYERS = [{"id": i} for i in range(1, 12)]


@pytest.fixture(scope="module")
def js():
    if not node:
        pytest.skip("node not installed")
    case = {
        "codes": ["ΑΒΕΗ-ΚΜΝΡ-ΤΥΧΖ", "αβεη-κμνρ-τυχζ", "ABCD-EFGH-JKMN", "άβέή", "ΓΔΘΛ"],
        "teams": [{"players": PLAYERS, "roles": ROLES_OK},
                  {"players": PLAYERS},
                  {"players": PLAYERS, "roles": {"1": "<img src=x onerror=alert(1)>"}},
                  {"players": PLAYERS, "roles": ["5άδα"]},
                  {"players": PLAYERS, "roles": {"1": 5}}],
    }
    out = subprocess.run([node, str(RUNNER)], input=json.dumps(case), capture_output=True, text=True, check=True)
    return json.loads(out.stdout)


def test_a_code_typed_with_greek_capitals_is_read_as_latin(js):
    # the look-alikes (Α Β Ε Η Κ Μ Ν Ρ Τ Υ Χ Ζ) are the Latin letters; lower case and accents too
    assert js["codes"][:3] == ["ABEHKMNPTYXZ", "ABEHKMNPTYXZ", "ABCDEFGHJKMN"]
    assert js["codes"][3] == "ABEH"
    assert js["codes"][4] == ""                  # Γ Δ Θ Λ have no Latin twin: not part of a code


def test_the_page_maps_the_same_letters():
    # web/team.js keeps its own copy of the map (the page doesn't load the Function's module)
    page = (Path(__file__).parents[1] / "web" / "team.js").read_text()
    fn = (Path(__file__).parents[1] / "functions" / "api" / "sync" / "[[path]].js").read_text()
    line = 'const GREEK_LATIN = { Α: "A", Β: "B", Ε: "E", Ζ: "Z", Η: "H", Ι: "I", Κ: "K", Μ: "M", Ν: "N", Ο: "O", Ρ: "P", Τ: "T", Υ: "Y", Χ: "X" };'
    assert line in page and line.replace("const", "export const") in fn
    assert "const code = syncCode(raw);" in page


def test_a_synced_team_carries_only_the_pages_roles(js):
    assert js["teams"] == [True, True, False, False, False]


def test_role_labels_are_escaped_on_the_page():
    page = (Path(__file__).parents[1] / "web" / "team.js").read_text()
    assert "${ROLE_LABEL[role] || role}" not in page
    assert page.count("esc(ROLE_LABEL[role] || role)") == 2


def test_sync_answers_carry_nosniff(js):
    assert js["nosniff"] == "nosniff"


def test_the_first_error_of_a_day_deletes_the_old_days(js):
    assert js["errorsStatus"] == 204
    old = (date.today() - timedelta(days=js["keepDays"])).isoformat()
    stmts = dict(js["errorsDeletes"])
    assert stmts.get("DELETE FROM errors WHERE day < ?") in (old, (date.today() - timedelta(days=js["keepDays"] + 1)).isoformat())
    assert "DELETE FROM hits WHERE until < ?" in stmts


def test_access_jwt_is_checked(js):
    v = js["verify"]
    assert v["valid"] is True
    for k in ("wrong_aud", "wrong_iss", "expired", "unknown_kid", "alg_none", "tampered", "garbage"):
        assert v[k] is False, k


def test_watch_endpoint_checks_the_jwt_when_configured(js):
    e = js["endpoint"]
    assert e["valid"] == 202
    assert e["forged"] == 403 and e["expired"] == 403
    assert e["no_config"] == 202                 # without ACCESS_* only the header's presence, as before


# ---------------------------------------------------------------- one «the game is over»

def test_done_teams_counts_a_closed_turn_even_if_the_fixture_is_not_marked():
    pred = {"round": 5, "fixtures": [{"round": 5, "home": "AAA", "away": "BBB", "played": False}],
            "turns": [{"turn": 1, "done": True, "teams": ["AAA", "BBB"]}]}
    assert checks.done_teams(pred) == {"AAA", "BBB"}


def test_lineup_reads_a_closed_turn_as_played(monkeypatch, public):
    """The tester's case: the turn is closed but `played` of its fixture is late. /lineup must still see
    the turn-1 players as played (a DNP is 0 and can't get the armband), as the update's checks do."""
    monkeypatch.setattr(lineup_cmd, "say", lambda *a, **k: None)
    sq = squad_t1_t2()
    team = {p["id"]: ("AAA" if p["turn"] == 1 else "CCC") for p in sq}
    (public / "predictions.json").write_text(json.dumps({
        "round": 5,
        "players": [{"fantasy_id": p["id"], "x_now": p["x_now"], "team": team[p["id"]]} for p in sq],
        "fixtures": [{"round": 5, "home": "AAA", "away": "BBB", "played": False}],
        "turns": [{"turn": 1, "done": True, "teams": ["AAA", "BBB"]}]}))
    roles = {1: "5άδα", 2: "5άδα", 5: "5άδα", 6: "5άδα", 9: "5άδα", 7: "6ος",
             3: "πάγκος", 4: "πάγκος", 8: "πάγκος", 10: "πάγκος"}
    FakeGame(sq, roles, captain=1).install(monkeypatch)
    st = lineup_cmd.load_state()
    played = {p["id"]: p["played"] for p in st["squad"]}
    assert all(played[p["id"]] for p in sq if p["turn"] == 1)
    assert not any(played[p["id"]] for p in sq if p["turn"] == 2)
