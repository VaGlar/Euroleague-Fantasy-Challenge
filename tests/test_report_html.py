"""The Telegram report is sent with parse_mode=HTML: any stray '<' makes Telegram reject the
whole message ("can't parse entities") and the day's report never arrives."""
import re

import pandas as pd
import pytest

from elf import run

ALLOWED = re.compile(r'</?(b|i|u|s|code|pre)>|<a href="[^"<>]*">|</a>')


def telegram_html_ok(text: str) -> bool:
    return not re.search(r"[<>]", ALLOWED.sub("", text))


def table():
    rows = [("Nunn, Kendrick", "PAN", "Guard", 22.0, 1), ("Vezenkov, Sasha", "OLY", "Forward", 20.0, 2),
            ("Hezonja, Mario", "MAD", "Forward", 18.0, 3), ("Tavares, Edy", "MAD", "Center", 17.0, 4),
            ("Ataman, Ergin", "PAN", "Head Coach", 9.0, 5)]
    return pd.DataFrame([{"name": n, "team": t, "position": p, "x_now": x, "fantasy_id": i,
                          "price": 10.0, "home": t == "PAN", "opp": "OLY"} for n, t, p, x, i in rows])


TURNS = [{"turn": 1, "date": "2026-10-01", "first_tip": "20:00", "teams": ["PAN", "OLY"],
          "games": ["PAN-OLY 20:00"]},
         {"turn": 2, "date": "2026-10-02", "first_tip": "21:00", "teams": ["MAD"],
          "games": ["MAD-XXX 21:00"]}]


def texts(dig, health):
    return [m["text"] for m in run.messages(3, TURNS, table(), None, dig, health,
                                            dash="https://dash.example")]


def test_normal_report_is_valid_telegram_html():
    dig = {"summary_el": "• Ο Nunn σε φόρμα", "availability": [
        {"player": "Vezenkov, Sasha", "status": "doubtful", "note": "γόνατο"}], "expert": []}
    out = texts(dig, ["πηγή εκτός: X: HTTPError 403"])
    assert len(out) == 2
    for t in out:
        assert telegram_html_ok(t), t


@pytest.mark.xfail(strict=True, reason="BUG: σύνοψη/σημειώσεις Gemini και μηνύματα σφαλμάτων "
                   "(health) μπαίνουν στο report χωρίς html.escape — ένα '<' σκοτώνει όλο το μήνυμα")
@pytest.mark.parametrize("where", ["summary", "note", "health"])
def test_free_text_is_escaped(where):
    bad = "παίζει <20 λεπτά"
    dig = {"summary_el": bad if where == "summary" else "ok",
           "availability": [{"player": "Vezenkov, Sasha", "status": "out",
                             "note": bad if where == "note" else "ok"}], "expert": []}
    health = ["βελτιστοποίηση ομάδας: KeyError: <NA>"] if where == "health" else []
    assert all(telegram_html_ok(t) for t in texts(dig, health))
