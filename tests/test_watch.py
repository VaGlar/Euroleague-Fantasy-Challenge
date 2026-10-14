"""The owner's watchlist (elf/watch.py, functions/api/watch.js): only ids and numbers are kept, and
each piece of news about a watched player reaches Telegram once."""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from elf import publish, watch

RUNNER = Path(__file__).with_name("watch_fn_runner.mjs")
node = shutil.which("node")


def entry(**kw):
    return {"at": "2026-10-13T10:00:00Z", "price": 10.0, "x3": 20.0, "inj": False, **kw}


def player(pid, **kw):
    return {"person_id": pid, "name": "DOE, JOHN", "price": 10.0, "x3": 20.0, "price_trend": None,
            "injured": False, "avail_game": 1.0, **kw}


# ------------------------------------------------------------------ the list

def test_clean_keeps_only_player_ids_and_known_fields():
    raw = {"003469": {**entry(), "note": "<script>", "price": "11.5"}, "abc": entry(), "../x": entry(),
           "012345": "not an object"}
    out = watch.clean(raw)
    assert list(out) == ["003469"]
    assert out["003469"] == {"at": "2026-10-13T10:00:00+00:00", "price": 11.5, "x3": 20.0, "inj": False}


def test_clean_caps_the_list_and_rejects_non_objects():
    assert len(watch.clean({str(i): entry() for i in range(100)})) == watch.MAX_PLAYERS
    with pytest.raises(ValueError):
        watch.clean(["003469"])
    assert watch.clean({"1": {"price": float("nan"), "at": "yesterday"}})["1"] == \
        {"at": None, "price": None, "x3": None, "inj": False}


def test_save_writes_the_cleaned_list(tmp_path):
    f = tmp_path / "public" / "watch.json"
    watch.save(f, json.dumps({"003469": entry(), "x": entry()}))
    d = json.loads(f.read_text())
    assert list(d["players"]) == ["003469"] and d["updated"]


def test_the_watch_files_are_private():
    assert {"watch.json", "watch_state.json"} <= set(publish.PRIVATE_ONLY)


# ------------------------------------------------------------------ alerts

def test_each_change_is_told_once():
    w = {"1": entry(), "2": entry(inj=True), "3": entry()}
    players = [player("1", price_trend="up"), player("2"), player("3", injured=True)]
    lines, state = watch.alerts(players, w, {})
    text = "\n".join(lines)
    assert "J. Doe" in text and "άνοδος price" in text          # 1: rise expected
    assert "διαθέσιμος ξανά" in text                              # 2: was out when added, plays now
    assert "εκτός ή αμφίβολος" in text                            # 3: out now
    assert len(lines) == 3
    again, _ = watch.alerts(players, w, state)                    # the next update: nothing new
    assert again == []


def test_xfpt3_jump_since_added():
    w = {"1": entry(x3=20.0)}
    assert watch.alerts([player("1", x3=22.9)], w, {})[0] == []
    lines, state = watch.alerts([player("1", x3=23.5)], w, {})
    assert len(lines) == 1 and "+3.5" in lines[0]
    assert watch.alerts([player("1", x3=24.0)], w, state)[0] == []


def test_a_player_no_longer_in_the_game_is_skipped():
    assert watch.alerts([], {"1": entry()}, {}) == ([], {})


def test_notify_sends_then_keeps_the_state(tmp_path, monkeypatch):
    sent = []
    monkeypatch.setattr("elf.notify.send", lambda text, buttons=None: sent.append(text) or True)
    (tmp_path / "watch.json").write_text(json.dumps({"updated": "x", "players": {"1": entry()}}))
    (tmp_path / "predictions.json").write_text(json.dumps({"players": [player("1", price_trend="up")]}))
    assert watch.notify(tmp_path) and len(sent) == 1 and sent[0].startswith("⭐")
    assert watch.notify(tmp_path) is None and len(sent) == 1     # the state remembers it was told
    assert json.loads((tmp_path / "watch_state.json").read_text())["1"]["up"] is True


def test_notify_without_a_list_does_nothing(tmp_path):
    assert watch.notify(tmp_path) is None


# ------------------------------------------------------------------ the personal site's endpoint

def fn(*cases):
    out = subprocess.run([node, str(RUNNER)], input=json.dumps(list(cases)), capture_output=True,
                         text=True, check=True)
    return json.loads(out.stdout)


ACCESS = {"Cf-Access-Jwt-Assertion": "jwt"}
ENV = {"GH_DISPATCH_TOKEN": "t0ken", "GH_REPO": "o/r"}


@pytest.mark.skipif(not node, reason="node not installed")
def test_endpoint_dispatches_the_cleaned_list():
    body = json.dumps({"watch": {"003469": {**entry(), "extra": "x"}, "bad id": entry()}})
    r = fn({"env": ENV, "headers": ACCESS, "body": body})[0]
    assert r["status"] == 202 and r["nosniff"] == "nosniff"
    assert r["sent"][0]["url"].endswith("/repos/o/r/actions/workflows/watch.yml/dispatches")
    sent = json.loads(r["sent"][0]["body"]["inputs"]["watch"])
    assert list(sent) == ["003469"] and "extra" not in sent["003469"]
    assert "t0ken" not in json.dumps(r["body"])


@pytest.mark.skipif(not node, reason="node not installed")
def test_endpoint_refuses_outside_the_personal_site():
    body = json.dumps({"watch": {}})
    hoopslab, no_access, bad, big, github_down = fn(
        {"env": {}, "headers": ACCESS, "body": body},               # no token: HoopsLab
        {"env": ENV, "body": body},                                  # not through Cloudflare Access
        {"env": ENV, "headers": ACCESS, "body": "{not json"},
        {"env": ENV, "headers": ACCESS, "body": "x" * 30_000},
        {"env": ENV, "headers": ACCESS, "body": body, "github": 401})
    assert hoopslab["status"] == 404 and no_access["status"] == 403
    assert bad["status"] == 400 and big["status"] == 413
    assert github_down["status"] == 502 and github_down["body"] == {"error": "dispatch failed"}
    assert all(not r["sent"] for r in (hoopslab, no_access, bad, big))


# ------------------------------------------------------------------ the workflow's command (watch.yml)

def save_cli(tmp_path, watch_json):
    """As watch.yml runs it: `python3 -m elf.watch save <path>` with the list in WATCH. -S: no
    site-packages, as the docstring promises (the workflow installs nothing)."""
    import os
    import sys
    out = tmp_path / "watch.json"
    r = subprocess.run([sys.executable, "-S", "-m", "elf.watch", "save", str(out)], cwd=Path(__file__).parents[1],
                       env={"PATH": os.environ.get("PATH", ""), "WATCH": watch_json}, capture_output=True, text=True)
    return r, out


def test_the_workflow_command_saves_only_ids_and_numbers(tmp_path):
    r, out = save_cli(tmp_path, json.dumps({"003469": {**entry(), "note": "<script>"}, "../x": entry()}))
    assert r.returncode == 0, r.stderr
    players = json.loads(out.read_text())["players"]
    assert list(players) == ["003469"] and "note" not in players["003469"]
    assert "1 players saved" in r.stdout and "003469" not in r.stdout, "the log is public: counts only"


def test_the_workflow_command_fails_on_a_broken_list_and_writes_nothing(tmp_path):
    r, out = save_cli(tmp_path, "{not json")
    assert r.returncode != 0 and not out.exists()
