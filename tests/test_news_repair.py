"""14/10: the LLM wrote the Greek of the summary as «α%u03bd%u03b1μένεται» and some words mixed Latin into
Greek («καλόs»). The escapes are decoded, a broken column note is dropped, and an answer still broken is
not published: the next model is asked (elf/news.py repair / garbled / digest)."""
import pytest

from elf import news

from test_clients import ARTS, Resp, gemini, gemini_ok  # noqa: F401  (gemini is a fixture)

ESCAPED = "Ο Jean Montero σ%u03c5%u03bd%u03b5%u03c7%u03af%u03b6%u03b5%u03b9 με ανοδική πορεία."


def test_escapes_are_decoded():
    d = news.repair({"summary_el": ESCAPED, "availability": [], "expert": []})
    assert d["summary_el"] == "Ο Jean Montero συνεχίζει με ανοδική πορεία."


def test_a_broken_note_is_dropped_the_pick_stays():
    d = news.repair({"summary_el": "", "availability": [], "expert": [
        {"player": "A", "stance": "pick", "note": "Εξαιρετική κατάσταση και καλόs captain."},
        {"player": "B", "stance": "avoid", "note": "Χαμηλ% απ%δοσης."},
        {"player": "C", "stance": "pick", "note": "Εύκολο πρόγραμμα και καλή τιμή."}]})
    assert [e.get("note") for e in d["expert"]] == [None, None, "Εύκολο πρόγραμμα και καλή τιμή."]
    assert [e["player"] for e in d["expert"]] == ["A", "B", "C"]


def test_latin_names_and_numbers_in_greek_text_are_fine():
    ok = {"summary_el": "Ο Vezenkov έφερε 25 PIR στο R5· ο Olympiacos κέρδισε την Real Madrid.",
          "availability": [], "expert": []}
    assert not news.garbled(news.repair(ok))


def test_many_broken_words_make_the_answer_garbled():
    bad = {"summary_el": "καλόs ματσs πρόγραμμαa ομάδαs Χαμηλ% απ%δοσης", "availability": [], "expert": []}
    assert news.garbled(bad)


def test_digest_asks_the_next_model_when_the_answer_is_garbled(gemini):  # noqa: F811
    broken = {"summary_el": "καλόs ματσs πρόγραμμαa ομάδαs Χαμηλ% απ%δοσης", "expert": []}
    posts = gemini(gemini_ok(broken), gemini_ok({"summary_el": ESCAPED, "expert": []}))
    out = news.digest(ARTS, [])
    assert out["_model"] == "m2" and len(posts) == 2
    assert out["summary_el"].startswith("Ο Jean Montero συνεχίζει")


def test_digest_all_garbled_publishes_nothing(gemini):  # noqa: F811
    broken = {"summary_el": "καλόs ματσs πρόγραμμαa ομάδαs Χαμηλ% απ%δοσης", "expert": []}
    gemini(*[gemini_ok(broken) for _ in range(4)])
    with pytest.raises(RuntimeError, match="αλλοιωμένο"):
        news.digest(ARTS, [])
