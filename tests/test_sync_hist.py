"""The synced team's Undo steps (`hist`) are checked like the team: an Undo restores a step's snap as the
team, so a step with a made-up role or player list would bring it back unchecked
(functions/api/sync validTeam)."""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

node = shutil.which("node")
pytestmark = pytest.mark.skipif(not node, reason="node not installed")
FN = Path(__file__).parents[1] / "functions" / "api" / "sync" / "[[path]].js"
P = [{"id": i} for i in range(1, 12)]
STEP = {"round": 12, "at": 1, "snap": {"players": P, "roles": {"1": "5άδα", "2": "πάγκος"}, "bank": 1.5,
                                        "captain": 1, "confirmed": True, "used": None}}


def valid(teams):
    code = ("const m = await import(process.argv[1]);"
            "let b='';process.stdin.on('data',d=>b+=d).on('end',()=>"
            "process.stdout.write(JSON.stringify(JSON.parse(b).map(m.validTeam))));")
    out = subprocess.run([node, "--input-type=module", "-e", code, FN.resolve().as_uri()],
                         input=json.dumps(teams), capture_output=True, text=True, check=True)
    return json.loads(out.stdout)


def test_the_pages_own_steps_pass():
    page_like = {"round": 12, "snap": {"players": None, "roles": None, "bank": None}}   # snapOf: null for a missing key
    assert valid([{"players": P, "hist": []}, {"players": P, "hist": [STEP, page_like]},
                  {"players": P, "hist": [STEP] * 60}]) == [True, True, True]


def test_a_step_with_a_made_up_role_or_bad_players_is_refused():
    bad = [{"players": P, "hist": [{**STEP, "snap": {**STEP["snap"], "roles": {"1": "<img src=x onerror=alert(1)>"}}}]},
           {"players": P, "hist": [{**STEP, "snap": {**STEP["snap"], "players": [{"id": "x"}]}}]},
           {"players": P, "hist": [{**STEP, "snap": {**STEP["snap"], "players": [{"id": 1}] * 16}}]},
           {"players": P, "hist": [{"round": 12}]},
           {"players": P, "hist": [[1, 2]]},
           {"players": P, "hist": "x"},
           {"players": P, "hist": [STEP] * 61}]
    assert valid(bad) == [False] * len(bad)
