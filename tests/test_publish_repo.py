"""The public repo's copy of data/public (python -m elf.publish --repo): the full files go to the
private data repo, this copy must hold nothing personal and none of the publishers' text."""
import json

import pytest

from elf import publish

from conftest import seed_public


def write(pub, name, obj):
    (pub / name).write_text(json.dumps(obj))


def full_outputs(pub):
    write(pub, "predictions.json", {"players": [{"name": "A"}], "my_team": {"name": "Nunn like Osman"},
                                    "health": ["🔑 token"], "price_model": {"a": 1}, "round": 3})
    write(pub, "news.json", {"articles": [{"title": "T", "url": "https://x", "source": "S",
                                           "text": "the whole article " * 50}], "digest": {"summary_el": "σ"}})
    write(pub, "tracking.json", {"rounds": [1], "lineups": [{"round": 1}]})
    write(pub, "autopilot.json", {"rounds": [{"round": 1, "pts": 500, "my_pts": 480, "my_rank": 12}]})
    write(pub, "report_public.json", {"messages": [{"date": "d", "text": "public"}]})
    for name in publish.PRIVATE_ONLY:
        write(pub, name, {"personal": True})
    (pub / "prices.csv").write_text("fantasy_id,price\n1,10\n")


def test_sanitize_repo_leaves_nothing_personal_or_copyrighted(public):
    full_outputs(public)
    publish.sanitize_repo(public)
    pred = json.loads((public / "predictions.json").read_text())
    assert pred["my_team"] is None and pred["health"] == [] and pred["price_model"] is None
    assert pred["players"] == [{"name": "A"}] and pred["round"] == 3
    news = json.loads((public / "news.json").read_text())
    assert news["articles"] == [{"title": "T", "url": "https://x", "source": "S"}]
    assert news["digest"] == {"summary_el": "σ"}, "η σύνοψη μένει (τη χρειάζεται και το επόμενο run)"
    assert json.loads((public / "tracking.json").read_text())["lineups"] == []
    assert json.loads((public / "autopilot.json").read_text())["rounds"] == [{"round": 1, "pts": 500}]
    for name in publish.PRIVATE_ONLY:
        assert not (public / name).exists(), name
    assert (public / "report_public.json").exists() and (public / "prices.csv").exists()
    text = "".join(f.read_text() for f in public.iterdir())
    assert "Nunn like Osman" not in text and "the whole article" not in text


def test_sanitize_repo_is_idempotent_and_tolerates_missing_files(public):
    full_outputs(public)
    publish.sanitize_repo(public)
    once = {f.name: f.read_text() for f in public.iterdir()}
    publish.sanitize_repo(public)
    assert {f.name: f.read_text() for f in public.iterdir()} == once
    for f in public.iterdir():
        f.unlink()
    assert publish.sanitize_repo(public) == []


def test_public_site_news_has_no_article_text(public, tmp_path):
    full_outputs(public)
    publish.bundle(tmp_path / "site", public)
    news = json.loads((tmp_path / "site" / "data" / "news.json").read_text())
    assert all("text" not in a for a in news["articles"])


def test_the_repos_own_data_passes_through(public):
    """Whatever data/public holds today sanitizes cleanly (no NaN, valid JSON)."""
    seed_public(public, *publish.PUBLIC_FILES)     # the private-only files are not in this repo
    publish.sanitize_repo(public)
    for f in public.glob("*.json"):
        json.loads(f.read_text(), parse_constant=lambda c: (_ for _ in ()).throw(ValueError(c)))


def test_the_workflow_call_without_arguments_cleans_data_public(public, tmp_path):
    """update.yml runs `python -m elf.publish --repo`: no folder given, so data/public itself."""
    full_outputs(public)
    done = publish.sanitize_repo()
    assert "predictions.json" in done and "news.json" in done
    assert {f"-{n}" for n in publish.PRIVATE_ONLY} <= set(done), "λέει τι έσβησε (φαίνεται στο log)"
    assert json.loads((public / "predictions.json").read_text())["my_team"] is None
    assert publish.bundle(tmp_path / "site") == publish.bundle(tmp_path / "site", public), \
        "χωρίς src διαβάζει data/public· και ξανά στον ίδιο φάκελο δεν σκάει"


def test_site_reads_the_folder_it_is_given(public, tmp_path):
    other = tmp_path / "other"
    other.mkdir()
    write(other, "players.json", {"from": "other"})
    out = tmp_path / "site"
    assert publish.site(out, other) == ["players.json"]
    assert json.loads((out / "data" / "players.json").read_text()) == {"from": "other"}
    manifest = json.loads((out / "manifest.json").read_text())
    assert manifest["short_name"] == publish.PRODUCT, "το όνομα κάτω από το εικονίδιο στο κινητό"


def test_nan_never_reaches_the_public_files(public, tmp_path):
    """A NaN would make the file invalid JSON for the browser: stop instead of writing it."""
    (public / "predictions.json").write_text('{"players": [{"x_now": NaN}]}')
    with pytest.raises(ValueError):
        publish.sanitize_repo(public)
    with pytest.raises(ValueError):
        publish.bundle(tmp_path / "site", public)
