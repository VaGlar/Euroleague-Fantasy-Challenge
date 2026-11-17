"""The English page: the same Gemini call writes the summary and the notes in English too
(summary_en, note_en), with the same clean-up as the Greek (elf/news.py)."""
from elf import news


def test_the_prompt_asks_for_english_in_the_same_call():
    assert '"summary_en"' in news.PROMPT and '"note_en"' in news.PROMPT


def test_an_english_summary_as_a_list_becomes_bullets():
    d = news._normalize({"summary_el": ["α"], "summary_en": ["- one", "two", ""]})
    assert d["summary_en"] == "• one\n• two"


def test_an_answer_without_english_stays_as_it_was():
    assert "summary_en" not in news._normalize({"summary_el": "α"})


def test_escapes_in_the_english_summary_are_decoded():
    d = news.repair({"summary_el": "", "summary_en": "Montero is in good form%u0021", "availability": [], "expert": []})
    assert d["summary_en"] == "Montero is in good form!"


def test_a_broken_english_note_is_dropped_the_greek_one_stays():
    d = news.repair({"summary_el": "", "availability": [], "expert": [
        {"player": "A", "stance": "pick", "note": "Καλό πρόγραμμα.", "note_en": "Good schedυle."}]})
    assert d["expert"][0]["note"] == "Καλό πρόγραμμα." and "note_en" not in d["expert"][0]


def test_greek_names_in_the_english_summary_go_back_to_latin():
    d = news.resolve_names({"summary_el": "", "summary_en": "«Jean Montero» is fit.", "availability": [], "expert": []},
                           ["MONTERO, JEAN"])
    assert d["summary_en"] == "Jean Montero is fit."
