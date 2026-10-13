"""elf/validate.py: the data check between the pipeline and the commit. It must pass the real data
the repo holds and stop on each kind of broken output (an API that changed shape, NaN, a stale or
half-written file, an empty report)."""
import json
from datetime import datetime, timedelta, timezone

import pytest

from elf import notify, validate

from conftest import seed_public

FILES = ("predictions.json", "report.json", "news.json", "players.json", "clubs.json")
NOW = datetime.now(timezone.utc).isoformat()


@pytest.fixture
def pub(public):
    """Today's real data, as if the pipeline had just written it."""
    seed_public(public, *FILES)
    if not (public / "report.json").exists():      # the public repo keeps only the public report
        seed_public(public, "report_public.json")
        (public / "report_public.json").rename(public / "report.json")
    for name in ("predictions.json", "report.json"):
        d = json.loads((public / name).read_text())
        d["generated"] = NOW
        (public / name).write_text(json.dumps(d))
    return public


def edit(pub, name, fn):
    d = json.loads((pub / name).read_text())
    fn(d)
    (pub / name).write_text(json.dumps(d))


def problems(pub):
    return validate.check()[0]


def test_real_data_passes(pub):
    assert validate.check() == ([], [])
    assert validate.main() == 0


@pytest.mark.parametrize("name", FILES)
def test_missing_or_broken_file_stops(pub, name):
    (pub / name).write_text('{"players": [1, 2')
    assert any(name in p and "JSON" in p for p in problems(pub))
    (pub / name).unlink()
    assert any(name in p and "λείπει" in p for p in problems(pub))


def test_nan_in_a_file_stops(pub):
    text = (pub / "players.json").read_text()
    (pub / "players.json").write_text(text.replace("{", '{"x": NaN, ', 1))
    assert any("players.json" in p and "NaN" in p for p in problems(pub)), "λέει τι βρήκε"


def test_stale_predictions_stop(pub):
    edit(pub, "predictions.json", lambda d: d.update(
        generated=(datetime.now(timezone.utc) - timedelta(hours=7)).isoformat()))
    assert any("δεν γράφτηκε" in p for p in problems(pub))


def test_off_season_run_keeps_old_predictions(pub):
    """No game ahead: the pipeline writes an empty report and leaves predictions.json as it was."""
    edit(pub, "predictions.json", lambda d: d.update(generated="2026-05-30T10:00:00+00:00"))
    edit(pub, "report.json", lambda d: d.update(messages=[]))
    assert problems(pub) == []


def test_too_few_players_stops(pub):
    edit(pub, "predictions.json", lambda d: d.update(players=d["players"][:120]))
    assert any("μόνο 120 παίκτες" in p for p in problems(pub))


def test_prices_gone_while_the_game_answered_stops(pub):
    """The fantasy API answered (fantasy_ok) but the prices didn't come through: its shape changed."""
    def drop(d):
        d["fantasy_ok"] = True
        for p in d["players"][: len(d["players"]) // 2]:
            p["price"] = None
    edit(pub, "predictions.json", drop)
    assert any("τιμή" in p and "API" in p for p in problems(pub))


def test_prices_in_another_unit_stop(pub):
    def cents(d):
        d["fantasy_ok"] = True
        for p in d["players"]:
            if p.get("price") is not None:
                p["price"] = p["price"] * 100
    edit(pub, "predictions.json", cents)
    assert any("1-40" in p for p in problems(pub))


def test_no_prices_is_fine_when_the_game_was_down(pub):
    def down(d):
        d["fantasy_ok"] = False
        for p in d["players"]:
            p["price"] = None
    edit(pub, "predictions.json", down)
    assert problems(pub) == [], "το παιχνίδι εκτός το λέει ήδη το health· τα xFPT μένουν χρήσιμα"


def test_unknown_or_missing_positions_stop(pub):
    def rename(d):
        for p in d["players"]:
            if p["position"] == "Center":
                p["position"] = "C"
    edit(pub, "predictions.json", rename)
    out = problems(pub)
    assert any("θέσεις που δεν ξέρω: C" in p for p in out)
    assert any("θέση Center" in p for p in out)


def test_nan_or_missing_xfpt_stops(pub):
    def no_x(d):
        for p in d["players"][:100]:
            p["x_now"] = None
    edit(pub, "predictions.json", no_x)
    out = problems(pub)
    assert any("χωρίς xFPT" in p for p in out)
    assert not any("δεν είναι αριθμός" in p for p in out), "χωρίς xFPT δεν σημαίνει λάθος τύπος"
    edit(pub, "predictions.json", lambda d: d["players"][0].update(x_now="12.3"))
    assert any(p.startswith("1 παίκτες με xFPT που δεν είναι αριθμός") for p in problems(pub))


def test_teams_and_round(pub):
    def one_team(d):
        for p in d["players"]:
            p["team"] = "PAN"
        d["round"] = 0
    edit(pub, "predictions.json", one_team)
    out = problems(pub)
    assert any("1 ομάδες" in p for p in out) and any("αγωνιστική 0" in p for p in out)


def test_broken_report_message_stops(pub):
    edit(pub, "report.json", lambda d: d["messages"].append({"date": "2026-10-02", "text": "  "}))
    assert any("report.json" in p for p in problems(pub))


def test_failure_is_told_on_telegram_escaped(pub, monkeypatch):
    def odd(d):
        d["players"][0]["position"] = "<script>"
    edit(pub, "predictions.json", odd)
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "bt")
    monkeypatch.setenv("RUN_URL", "https://github.com/run/1")
    sent = []
    monkeypatch.setattr(notify, "send", lambda text, buttons=None: sent.append(text))
    assert validate.main() == 1
    (text,) = sent
    assert text.count("\n• ") == 1
    assert "<b>Το update σταμάτησε" in text and "&lt;script&gt;" in text and "<script>" not in text
    assert text.endswith("https://github.com/run/1")
    monkeypatch.delenv("RUN_URL")
    validate.main()
    assert sent[-1].endswith("&lt;script&gt; — άλλαξαν τα δεδομένα του παιχνιδιού;"), "χωρίς link, τίποτα στο τέλος"


def test_empty_report_with_a_game_ahead_is_only_a_warning(pub):
    edit(pub, "report.json", lambda d: d.update(messages=[], generated="2026-01-01T00:00:00+00:00"))
    probs, warns = validate.check()
    assert probs == [] and any("report" in w for w in warns)
    assert validate.main() == 0
    health = json.loads((pub / "predictions.json").read_text())["health"]
    assert any("report" in h for h in health), "η προειδοποίηση φτάνει στο health"


def test_a_warning_keeps_the_runs_earlier_health_notes(pub):
    edit(pub, "predictions.json", lambda d: d.update(health=["🔑 token λήγει"]))
    edit(pub, "report.json", lambda d: d.update(messages=[], generated="2026-01-01T00:00:00+00:00"))
    validate.main()
    validate.main()
    health = json.loads((pub / "predictions.json").read_text())["health"]
    assert health[0] == "🔑 token λήγει" and len(health) == 2, "προστίθεται μία φορά, δεν σβήνει τα άλλα"
    assert "🔑" in (pub / "predictions.json").read_text(), "γράφεται όπως είναι (όχι \\u-escapes)"


# ------------------------------------------------------------------ found by mutation testing

def test_a_few_odd_players_do_not_stop_the_update(pub):
    """The limits are «more than 10% without xFPT» and «more than 5% of prices outside 1-40»:
    one newcomer without a prediction or one odd price is normal, not a broken API."""
    def one_each(d):
        d["fantasy_ok"] = True
        d["players"][0]["x_now"] = None
        d["players"][1]["price"] = 45.0
    edit(pub, "predictions.json", one_each)
    assert problems(pub) == []


def test_report_message_without_text_stops(pub):
    edit(pub, "report.json", lambda d: d["messages"].append({"date": "2026-10-02"}))
    assert any("χωρίς ημερομηνία ή κείμενο" in p for p in problems(pub))
