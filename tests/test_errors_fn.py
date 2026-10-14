"""The pages' JavaScript errors (functions/api/errors.js): counted, the first of a day to Telegram,
nothing personal, limited per IP. Runs in node with stand-ins for D1 and Telegram."""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

node = shutil.which("node")
pytestmark = pytest.mark.skipif(not node, reason="node not installed")
RUNNER = Path(__file__).with_name("errors_fn_runner.mjs")
TG = {"SYNC_DB": True, "TELEGRAM_BOT_TOKEN": "t0ken", "TELEGRAM_CHAT_ID": "1"}
ERR = {"msg": "TypeError: x is undefined", "src": "team.js", "line": 42, "tab": "team", "edition": "public"}


def run(*cases):
    out = subprocess.run([node, str(RUNNER)], input=json.dumps(list(cases)), capture_output=True, text=True, check=True)
    return json.loads(out.stdout)


def test_the_first_of_an_error_goes_to_telegram_the_repeats_are_only_counted():
    r, = run({"env": TG, "posts": [{"body": ERR}, {"body": ERR}, {"body": {**ERR, "msg": "other"}}]})
    assert r["status"] == [204, 204, 204]
    assert len(r["sent"]) == 2                                   # two different errors, each once
    text = r["sent"][0]["body"]["text"]
    assert "TypeError: x is undefined" in text and "team.js:42" in text and "Coach Dime" in text
    assert "t0ken" not in json.dumps(r["sent"])


def test_bad_input_limits_and_no_database():
    big = {**ERR, "msg": "x" * 3000}
    r, = run({"env": TG, "posts": [{"body": "not json"}, {"body": {"src": "a"}}, {"body": big}]})
    assert r["status"] == [400, 400, 413] and r["sent"] == []
    many, = run({"env": TG, "posts": [{"body": {**ERR, "msg": f"e{i}"}} for i in range(31)]})
    assert many["status"][-1] == 429 and many["status"][:30] == [204] * 30
    assert len(many["sent"]) == 20                               # MAX_ALERTS a day
    off, = run({"env": {}, "posts": [{"body": ERR}]})
    assert off["status"] == [204] and off["sent"] == []          # the personal site: nowhere to count
    quiet, = run({"env": {"SYNC_DB": True}, "posts": [{"body": ERR}]})
    assert quiet["status"] == [204] and quiet["sent"] == []      # no Telegram secrets: only counted
