"""PR 69: the English summary comes from the same call and gets «the same clean-up as the Greek».
`garbled()` decides that an answer is broken (and the next model is tried); it reads summary_el and the
notes, but not summary_en, so a broken English summary reaches the English page as it is."""
import pytest

from elf import news

GREEK = "Ο Montero είναι σε φόρμα και παίζει απόψε απέναντι στη Fenerbahce με καλό πρόγραμμα. " * 3
BROKEN_EN = "Mοntero is in gοod fοrm and plays tοnight against Fenerbahce%x with a gοod schedule."  # Greek ο in Latin words

EN_GAP = pytest.mark.xfail(strict=True, reason="KNOWN GAP: garbled() ignores summary_en (report 2026-11-17, §2.1)")


def test_the_broken_words_are_seen_as_broken():
    # the check itself: these words count as broken when they are in the Greek summary
    assert news.garbled({"summary_el": BROKEN_EN, "availability": [], "expert": []})


@EN_GAP
def test_a_broken_english_summary_makes_the_answer_broken():
    assert news.garbled({"summary_el": GREEK, "summary_en": BROKEN_EN, "availability": [], "expert": []})


def test_a_clean_english_summary_does_not():
    en = "Montero is in good form and plays tonight against Fenerbahce, 48% from three."
    assert not news.garbled({"summary_el": GREEK, "summary_en": en, "availability": [], "expert": []})
