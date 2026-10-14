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


# ------------------------------------------------------------------ tester, 14/10 (after PR 48)
# Known bug: _bad() counts every word with a «%» as broken, so ordinary percentages («48% στα δίποντα»)
# make a normal summary «garbled» and drop a column's note. Pinned as strict xfail: the fix must remove
# the marks. Suggested fix: a «%» counts only next to a letter (r"[^\W\d_]%|%[^\W\d_]").
PCT_BUG = pytest.mark.xfail(strict=True, reason="news._bad: every «%» counts as broken (tester report 14/10)")
STATS = ("Ο Vezenkov έχει 48% στα δίποντα και 41% στα τρίποντα στις τελευταίες 3 αγωνιστικές. "
         "Ο Nunn είναι επιλογή στο 35% των ομάδων, ενώ ο Mattisseck μόλις στο 4%. "
         "Η Fenerbahce κερδίζει το 70% των εντός έδρας αγώνων της.")


@PCT_BUG
def test_percentages_in_a_normal_summary_are_not_garbled():
    assert not news.garbled(news.repair({"summary_el": STATS, "availability": [], "expert": []}))


@PCT_BUG
def test_a_note_with_a_percentage_is_kept():
    d = news.repair({"summary_el": "", "availability": [], "expert": [
        {"player": "A", "stance": "pick", "note": "Σουτάρει 45% από τα τρία, σταθερός."}]})
    assert d["expert"][0].get("note") == "Σουτάρει 45% από τα τρία, σταθερός."


def test_a_percent_sign_inside_a_word_is_still_broken():
    """The other side of the fix: «Χαμηλ%» / «απ%δοσης» stay broken (this passes today and after the fix)."""
    assert news._bad("απ%δοσης") and news._bad("Χαμηλ%")
