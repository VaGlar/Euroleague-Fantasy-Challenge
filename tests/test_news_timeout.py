"""18-22/10: Gemini's first model timed out (ReadTimeout) on every run and the digest was lost with it,
so the news page showed only the article links. A model that doesn't answer in time gives way to the
next one (elf/news.py digest)."""
import pytest
import requests

from elf import news

from test_clients import ARTS, gemini_ok


@pytest.fixture
def models(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "KEY123")
    monkeypatch.delenv("GEMINI_MODEL", raising=False)
    monkeypatch.setattr(news.time, "sleep", lambda s: None)
    monkeypatch.setattr(news, "_flash_models", lambda base, h: ["m1", "m2", "m3", "m4", "m5"])
    asked = []

    def install(*replies):
        replies = list(replies)

        def post(url, headers=None, json=None, timeout=None):
            asked.append((url.split("/models/")[1].split(":")[0], timeout))
            r = replies.pop(0)
            if isinstance(r, Exception):
                raise r
            return r
        monkeypatch.setattr(news.requests, "post", post)
        return asked
    return install


def test_a_timed_out_model_gives_way_to_the_next(models):
    asked = models(requests.ReadTimeout("slow"), gemini_ok({"summary_el": "Σύνοψη.", "expert": []}))
    out = news.digest(ARTS, [])
    assert out["_model"] == "m2" and out["summary_el"] == "Σύνοψη."
    assert [m for m, _ in asked] == ["m1", "m2"]          # m1 is not asked again after its timeout
    assert all(t == news.REQUEST_TIMEOUT_S for _, t in asked)


def test_all_timed_out_says_so(models):
    models(*[requests.ReadTimeout("slow") for _ in range(4)])
    with pytest.raises(RuntimeError, match="δεν απάντησε"):
        news.digest(ARTS, [])


def test_a_connection_error_counts_as_a_timeout(models):
    models(requests.ConnectionError("reset"), gemini_ok({"summary_el": "Σύνοψη.", "expert": []}))
    assert news.digest(ARTS, [])["_model"] == "m2"


def test_no_new_model_after_the_time_budget(models, monkeypatch):
    clock = iter([0, 0, 0, news.DIGEST_BUDGET_S + 1])        # start, before m1, m1 post, before m2
    monkeypatch.setattr(news.time, "monotonic", lambda: next(clock))
    asked = models(requests.ReadTimeout("slow"), gemini_ok({"summary_el": "x", "expert": []}))
    with pytest.raises(RuntimeError):
        news.digest(ARTS, [])
    assert [m for m, _ in asked] == ["m1"]


def test_the_digest_records_how_long_the_answer_took(models, monkeypatch):
    clock = iter([0, 0, 100.0, 137.25])                 # start, budget check, before the post, after it
    monkeypatch.setattr(news.time, "monotonic", lambda: next(clock))
    models(gemini_ok({"summary_el": "Σύνοψη.", "expert": []}))
    out = news.digest(ARTS, [])
    assert out["_model"] == "m1" and out["_seconds"] == 37.2
