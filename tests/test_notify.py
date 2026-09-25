"""Morning report delivery and the pre-deadline check."""
import json

import pytest

from elf import lineup_cmd, notify

from conftest import FakeGame, squad_t1_t2, write_predictions

TODAY = "2026-10-01"


@pytest.fixture
def sent(monkeypatch):
    out = []
    monkeypatch.setattr(notify, "today", lambda: TODAY)
    monkeypatch.setattr(notify, "send", lambda text, buttons=None: out.append((text, buttons)))
    return out


def test_chunks_respect_telegram_limit():
    text = "\n".join("x" * 100 for _ in range(100))
    parts = notify.chunks(text)
    assert len(parts) > 1 and all(len(p) <= 3800 for p in parts)
    assert "".join(parts).count("x") == 100 * 100


def test_report_sent_on_game_day_with_lineup_button(public, sent):
    (public / "report.json").write_text(json.dumps({"messages": [
        {"date": TODAY, "turn": 1, "text": "report T1"}, {"date": "2026-10-02", "text": "T2"}]}))
    assert notify.report() is True
    assert sent == [("report T1", [notify.LINEUP_BUTTON])]
    assert json.loads((public / "sent.json").read_text())["date"] == TODAY


def test_no_report_on_a_day_without_games(public, sent):
    (public / "report.json").write_text(json.dumps({"messages": [{"date": "2026-10-02",
                                                                  "text": "T2"}]}))
    assert notify.report() is False and sent == []
    assert not (public / "sent.json").exists()


GOOD = {1: "5άδα", 2: "5άδα", 5: "5άδα", 6: "5άδα", 9: "5άδα", 7: "6ος",
        3: "πάγκος", 4: "πάγκος", 8: "πάγκος", 10: "πάγκος"}
BAD = {10: "5άδα", 5: "5άδα", 8: "5άδα", 1: "5άδα", 3: "5άδα", 2: "6ος",
       6: "πάγκος", 7: "πάγκος", 9: "πάγκος", 4: "πάγκος"}


def setup_check(monkeypatch, public, roles, transfers=()):
    sq = squad_t1_t2()
    write_predictions(public, sq)
    pred = json.loads((public / "predictions.json").read_text())
    pred["turns"] = [{"turn": 1, "date": TODAY, "first_tip": "19:00"}]
    pred["my_team"] = {"transfers": list(transfers)}
    (public / "predictions.json").write_text(json.dumps(pred))
    FakeGame(sq, roles, captain=1 if roles is GOOD else 10).install(monkeypatch)
    said = []
    monkeypatch.setattr(lineup_cmd, "say", lambda text, buttons=None: said.append((text, buttons)))
    return said


def test_check_is_silent_when_all_is_set(monkeypatch, public, sent):
    said = setup_check(monkeypatch, public, GOOD)
    lineup_cmd.check()
    assert said == []


def test_check_reminds_about_lineup_with_apply_buttons(monkeypatch, public, sent):
    said = setup_check(monkeypatch, public, BAD)
    lineup_cmd.check()
    (text, buttons), = said
    assert "⏰" in text and "19:00" in text
    assert buttons[0]["callback_data"].startswith("lu:apply:")


def test_check_reminds_about_pending_trades(monkeypatch, public, sent):
    tr = [{"out": "P4 (X)", "in": "NEW (Y)", "out_id": 4, "in_id": 99},
          {"out": "GONE (Z)", "in": "DONE (W)", "out_id": 555, "in_id": 98}]
    said = setup_check(monkeypatch, public, GOOD, tr)
    lineup_cmd.check()
    (text, buttons), = said
    assert "P4 (X) ➜ NEW (Y)" in text and "GONE" not in text, "μόνο όσες δεν έγιναν"
    assert buttons is None
