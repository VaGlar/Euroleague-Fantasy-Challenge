"""The Cloudflare Worker (worker/src/index.js): owner-only bot commands, the confirm-once
lineup buttons and the hourly schedule in Athens time. Runs in node with fetch and the clock
faked (tests/worker_runner.mjs); nothing leaves the machine."""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

node = shutil.which("node")
pytestmark = pytest.mark.skipif(not node, reason="node not installed")
RUNNER = Path(__file__).with_name("worker_runner.mjs")

OWNER, STRANGER = 42, 777
ENV = {"DATA_URL": "https://data.example", "TELEGRAM_CHAT_ID": str(OWNER),
       "TELEGRAM_BOT_TOKEN": "bt", "WEBHOOK_SECRET": "s3cret", "GH_DISPATCH_TOKEN": "ghp",
       "GH_REPO": "o/r", "GH_REF": "main", "DASHBOARD_URL": "https://dash.example"}
DAY = "2026-10-01"          # Athens is UTC+3 (summer time) on this date


def data(first_tip="20:00", games=("PAN-OLY 20:00", "RMB-BAR 21:30"), generated=None,
         msg_date=DAY):
    return {
        "report.json": {"generated": generated or f"{DAY}T04:10:00Z",
                        "messages": [{"date": msg_date, "turn": 1, "text": "REPORT T1"}]},
        "predictions.json": {
            "generated": f"{DAY}T04:10:00Z", "round": 3, "fantasy_ok": True, "health": [],
            "turns": [{"turn": 1, "date": DAY, "first_tip": first_tip, "games": list(games)}],
            "players": [{"name": "A, B", "team": "PAN", "position": "Guard", "x_now": 20.5,
                         "price": 12}]},
    }


def run(*cases):
    cases = [{"env": ENV, "data": data(), **c} for c in cases]
    out = subprocess.run([node, str(RUNNER)], input=json.dumps(cases), capture_output=True,
                         text=True, check=True)
    return json.loads(out.stdout)


def one(**case):
    res = run(case)[0]
    assert res["error"] is None, res["error"]
    return res


def tg(res, method="sendMessage"):
    out = [c["body"] for c in res["calls"] if c["kind"] == "tg" and c["method"] == method]
    for b in out:          # the splitter ends every chunk with a newline
        if "text" in b:
            b["text"] = b["text"].rstrip("\n")
    return out


def dispatches(res):
    return [(c["workflow"], c["inputs"]) for c in res["calls"] if c["kind"] == "dispatch"]


def msg(text, chat=OWNER):
    return {"kind": "fetch", "headers": {"X-Telegram-Bot-Api-Secret-Token": "s3cret"},
            "body": {"update_id": 1, "message": {"text": text, "chat": {"id": chat}}}}


def button(data_, chat=OWNER):
    return {"kind": "fetch", "headers": {"X-Telegram-Bot-Api-Secret-Token": "s3cret"},
            "body": {"update_id": 1, "callback_query": {
                "id": "cq1", "data": data_, "message": {"message_id": 9, "chat": {"id": chat}}}}}


# ------------------------------------------------------------------ webhook security

@pytest.mark.parametrize("headers", [{}, {"X-Telegram-Bot-Api-Secret-Token": "wrong"}])
def test_webhook_without_the_secret_is_forbidden_and_does_nothing(headers):
    ev = {**msg("/update"), "headers": headers}
    res = one(event=ev)
    assert res["status"] == 403 and res["calls"] == []


def test_webhook_secret_unset_still_rejects_requests_without_header():
    res = one(env={**ENV, "WEBHOOK_SECRET": ""}, event={**msg("/update"), "headers": {}})
    assert res["status"] == 403 and res["calls"] == []


def test_other_paths_and_get_are_a_harmless_ping():
    res = one(event={"kind": "fetch", "method": "GET", "path": "/"})
    assert (res["status"], res["body"], res["calls"]) == (200, "elf bot ok", [])


def test_anyone_can_learn_their_chat_id_but_nothing_else():
    res = one(event=msg("/id", chat=STRANGER))
    (sent,) = tg(res)
    assert sent["chat_id"] == str(STRANGER) and f"<code>{STRANGER}</code>" in sent["text"]
    for cmd in ("/report", "/top", "/lineup", "/update", "/health", "/whatever"):
        res = one(event=msg(cmd, chat=STRANGER))
        assert res["calls"] == [], f"{cmd} από ξένο chat δεν πρέπει να κάνει τίποτα"


def test_command_with_bot_suffix_and_arguments():
    res = one(event=msg("  /lineup@elf_bot now "))
    assert dispatches(res) == [("lineup.yml", {"mode": "preview", "nonce": ""})]


# ------------------------------------------------------------------ owner commands

def test_update_dispatches_with_notify_and_confirms():
    res = one(event=msg("/update"))
    assert dispatches(res) == [("update.yml", {"notify": "true"})]
    (sent,) = tg(res)
    assert "ξεκίνησε" in sent["text"]
    assert all(c["auth"] == "Bearer ghp" and c["ref"] == "main"
               for c in res["calls"] if c["kind"] == "dispatch")


def test_update_reports_github_error_text():
    res = one(event=msg("/update"), dispatchStatus=401)
    (sent,) = tg(res)
    assert "GitHub 401" in sent["text"]


def test_update_without_dispatch_token_explains():
    res = one(env={**ENV, "GH_DISPATCH_TOKEN": ""}, event=msg("/update"))
    assert dispatches(res) == [] and "GH_DISPATCH_TOKEN" in tg(res)[0]["text"]


def test_report_picks_today_else_next_and_has_lineup_button():
    res = one(now=f"{DAY}T12:00:00Z", event=msg("/report"))
    (sent,) = tg(res)
    assert sent["text"] == "REPORT T1"
    assert sent["reply_markup"]["inline_keyboard"][0][0]["callback_data"] == "lu:preview"
    res = one(now="2026-09-30T12:00:00Z", event=msg("/report"))      # the day before
    assert tg(res)[0]["text"] == "REPORT T1"


def test_report_when_there_is_none_yet():
    d = data()
    d["report.json"]["messages"] = []
    (sent,) = tg(one(data=d, event=msg("/report")))
    assert "Δεν υπάρχει report" in sent["text"] and "reply_markup" not in sent


def test_top_lists_players():
    (sent,) = tg(one(event=msg("/top")))
    assert "Round 3" in sent["text"] and "<b>20.5</b>" in sent["text"] and "12cr" in sent["text"]


def test_data_error_is_told_to_the_owner_not_swallowed():
    res = one(data={}, event=msg("/report"))
    (sent,) = tg(res)
    assert sent["text"].startswith("⚠️") and "404" in sent["text"]
    assert res["status"] == 200, "Telegram πρέπει να πάρει 200 αλλιώς ξαναστέλνει το update"


def test_unknown_command_shows_help_with_dashboard_link():
    (sent,) = tg(one(event=msg("hello")))
    assert "/lineup" in sent["text"] and "https://dash.example" in sent["text"]


def test_long_message_is_split_and_button_goes_on_the_last_part():
    d = data()
    d["report.json"]["messages"][0]["text"] = "\n".join("x" * 100 for _ in range(100))
    sent = tg(one(data=d, event=msg("/report")))
    assert len(sent) >= 3 and all(len(s["text"]) <= 4096 for s in sent)
    assert [("reply_markup" in s) for s in sent] == [False] * (len(sent) - 1) + [True]
    assert "".join(s["text"] for s in sent).count("x") == 100 * 100


# ------------------------------------------------------------------ lineup buttons

def test_button_from_another_chat_is_ignored():
    res = one(event=button("lu:apply:0123456789ab", chat=STRANGER))
    assert dispatches(res) == [] and tg(res, "editMessageReplyMarkup") == []
    assert len(tg(res, "answerCallbackQuery")) == 1          # the spinner still stops


def test_apply_removes_buttons_then_dispatches_with_the_nonce():
    res = one(event=button("lu:apply:0123456789ab"))
    (edit,) = tg(res, "editMessageReplyMarkup")
    assert edit["reply_markup"] == {"inline_keyboard": []} and edit["message_id"] == 9
    assert dispatches(res) == [("lineup.yml", {"mode": "apply", "nonce": "0123456789ab"})]
    order = [c.get("method") or c["kind"] for c in res["calls"]]
    assert order.index("editMessageReplyMarkup") < order.index("dispatch"), \
        "τα κουμπιά φεύγουν πριν την εφαρμογή (επιβεβαίωση μόνο μία φορά)"


@pytest.mark.parametrize("nonce", ["", "0123456789AB", "0123456789a", "0123456789abc",
                                   "../../etc/pa"])
def test_apply_with_malformed_nonce_never_dispatches(nonce):
    res = one(event=button(f"lu:apply:{nonce}"))
    assert dispatches(res) == []


def test_cancel_and_foreign_namespaces():
    res = one(event=button("lu:cancel"))
    assert dispatches(res) == [] and "Ακυρώθηκε" in tg(res)[0]["text"]
    res = one(event=button("xx:apply:0123456789ab"))
    assert dispatches(res) == [] and tg(res, "editMessageReplyMarkup") == []


def test_preview_button_keeps_the_keyboard():
    res = one(event=button("lu:preview"))
    assert tg(res, "editMessageReplyMarkup") == []
    assert dispatches(res) == [("lineup.yml", {"mode": "preview", "nonce": ""})]


# ------------------------------------------------------------------ hourly schedule

def at(utc, **kw):
    return one(now=utc, event={"kind": "scheduled"}, **kw)


def test_0705_athens_update_in_summer_and_in_winter():
    assert dispatches(at(f"{DAY}T04:05:00Z")) == [("update.yml", {})]          # UTC+3
    assert dispatches(at(f"{DAY}T05:05:00Z")) == []                            # 08:05
    winter = data()
    winter["predictions.json"]["turns"] = []
    assert dispatches(at("2026-12-03T05:05:00Z", data=winter)) == [("update.yml", {})]  # UTC+2
    assert dispatches(at("2026-12-03T04:05:00Z", data=winter)) == []


def test_0905_analytics():
    assert dispatches(at(f"{DAY}T06:05:00Z")) == [("analytics.yml", {})]


def test_1005_game_day_report_only_on_game_days():
    (sent,) = tg(at(f"{DAY}T07:05:00Z"))
    assert sent["chat_id"] == str(OWNER) and sent["text"] == "REPORT T1"
    assert sent["reply_markup"]["inline_keyboard"][0][0]["callback_data"] == "lu:preview"
    assert tg(at(f"{DAY}T07:05:00Z", data=data(msg_date="2026-10-02"))) == []


def test_stale_report_carries_a_warning():
    (sent,) = tg(at(f"{DAY}T07:05:00Z", data=data(generated="2026-09-30T05:00:00Z")))
    assert "ώρες παλιά" in sent["text"]


def test_pre_deadline_update_then_check():
    assert dispatches(at(f"{DAY}T14:05:00Z")) == [("update.yml", {})]             # 17:05
    assert dispatches(at(f"{DAY}T15:05:00Z")) == [("lineup.yml", {"mode": "check",
                                                                    "nonce": ""})]  # 18:05
    assert dispatches(at(f"{DAY}T12:05:00Z")) == []                               # 15:05


def test_morning_tip_off_does_not_update_twice_at_seven():
    d = data(first_tip="10:00", games=("PAN-OLY 10:00",))
    assert dispatches(at(f"{DAY}T04:05:00Z", data=d)) == [("update.yml", {})]
    assert dispatches(at(f"{DAY}T05:05:00Z", data=d)) == [("lineup.yml", {"mode": "check",
                                                                           "nonce": ""})]


def test_results_update_once_after_the_last_game_even_past_midnight():
    # last tip 21:30 + 2h30 = 00:00 Athens on the next day
    assert dispatches(at(f"{DAY}T20:05:00Z")) == []                               # 23:05
    assert dispatches(at(f"{DAY}T21:05:00Z")) == [("update.yml", {})]             # 00:05
    assert dispatches(at(f"{DAY}T22:05:00Z")) == []                               # 01:05


def test_no_dispatch_token_means_no_dispatches_but_report_still_sent():
    env = {**ENV, "GH_DISPATCH_TOKEN": ""}
    for t in ("04:05", "06:05", "14:05", "15:05", "21:05"):
        assert dispatches(at(f"{DAY}T{t}:00Z", env=env)) == []
    assert tg(at(f"{DAY}T07:05:00Z", env=env))[0]["text"] == "REPORT T1"


def test_failed_scheduled_update_is_reported():
    res = at(f"{DAY}T04:05:00Z", dispatchStatus=401)
    (sent,) = tg(res)
    assert "δεν ξεκίνησε" in sent["text"] and "401" in sent["text"]


def test_schedule_error_is_reported_only_at_seven_and_ten():
    res = at(f"{DAY}T07:05:00Z", data={})                                          # 10:05
    (sent,) = tg(res)
    assert "Πρόβλημα στο πρόγραμμα" in sent["text"]
    assert tg(at(f"{DAY}T12:05:00Z", data={})) == [], "όχι spam κάθε ώρα"
