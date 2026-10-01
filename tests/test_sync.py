"""Devices kept in step (functions/api/sync/[[path]].js): a new code, read, write, a write from a
device that missed the other's change (409 with the stored copy), bad input. Runs in node against an
in-memory stand-in for D1 (tests/sync_runner.mjs); nothing leaves the machine."""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

node = shutil.which("node")
pytestmark = pytest.mark.skipif(not node, reason="node not installed")
RUNNER = Path(__file__).with_name("sync_runner.mjs")
TEAM = {"players": [{"id": i, "price": 8.0} for i in range(1, 12)], "bank": 12.0}


def run(*requests, db=True):
    case = {"requests": list(requests), **({} if db else {"db": False})}
    out = subprocess.run([node, str(RUNNER)], input=json.dumps([case]), capture_output=True,
                         text=True, check=True)
    return json.loads(out.stdout)[0]


def test_new_code_read_write_and_a_stale_device():
    new, get, put, dashed, stale, after, unknown = run(
        {"method": "POST", "path": "/api/sync", "body": {"data": TEAM}},
        {"method": "GET", "path": "/api/sync/{code}"},
        {"method": "PUT", "path": "/api/sync/{code}", "body": {"data": {**TEAM, "bank": 3.5}, "rev": 1}},
        {"method": "GET", "path": "/api/sync/{dashed}"},          # «abcd-efgh-jkmn» as a person types it
        {"method": "PUT", "path": "/api/sync/{code}", "body": {"data": {**TEAM, "bank": 9.0}, "rev": 1}},
        {"method": "GET", "path": "/api/sync/{code}"},
        {"method": "GET", "path": "/api/sync/AAAAAAAAAAAA"})
    code = new["body"]["code"]
    assert new["status"] == 201 and len(code) == 12 and new["body"]["rev"] == 1
    assert not set(code) & set("01OIL")                           # nothing to misread
    assert get["status"] == 200 and get["body"]["data"] == TEAM and get["body"]["rev"] == 1
    assert put["status"] == 200 and put["body"]["rev"] == 2
    assert dashed["status"] == 200 and dashed["body"]["data"]["bank"] == 3.5
    # the other device still thinks rev 1: refused, with the stored copy to decide from
    assert stale["status"] == 409 and stale["body"]["rev"] == 2 and stale["body"]["data"]["bank"] == 3.5
    assert after["body"]["data"]["bank"] == 3.5 and after["body"]["rev"] == 2   # the refused write changed nothing
    assert unknown["status"] == 404


def test_bad_input_and_no_database():
    res = run({"method": "POST", "path": "/api/sync", "body": "not json"},
              {"method": "POST", "path": "/api/sync", "body": {"data": {"players": "x"}}},
              {"method": "POST", "path": "/api/sync", "body": {"data": {"players": [{"id": i} for i in range(20)]}}},
              {"method": "GET", "path": "/api/sync/short"},
              {"method": "PUT", "path": "/api/sync", "body": {"data": TEAM}},
              {"method": "POST", "path": "/api/sync", "body": {"data": {**TEAM, "pad": "x" * 210_000}}},
              {"method": "PUT", "path": "/api/sync/AAAAAAAAAAAA", "body": {"data": TEAM, "rev": 1}})
    assert [r["status"] for r in res] == [400, 400, 400, 400, 405, 413, 404]
    assert run({"method": "GET", "path": "/api/sync/AAAAAAAAAAAA"}, db=False)[0]["status"] == 503
