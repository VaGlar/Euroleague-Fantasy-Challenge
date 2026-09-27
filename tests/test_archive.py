"""The article archive: every article kept for the season, deduplicated, never fatal."""
import json

from elf import archive


def arts(*rows):
    return [{"url": u, "title": t, "date": d, "source": "S", "fantasy": False, "text": x} for u, t, d, x in rows]


def test_add_articles_dedups_and_keeps_longest_text(tmp_path):
    assert archive.add_articles(arts(("u1", "A", "2026-10-01", "short"), ("u2", "B", "2026-10-02", "x")), tmp_path) == 2
    assert archive.add_articles(arts(("u1", "A", "2026-10-01", "a much longer text"), ("u3", "C", "2026-09-30", "y")),
                                tmp_path) == 1
    rows = [json.loads(line) for line in (tmp_path / "articles.jsonl").read_text().splitlines()]
    assert [r["url"] for r in rows] == ["u3", "u1", "u2"]                 # by date
    assert rows[1]["text"] == "a much longer text" and rows[1]["seen"]


def test_torn_line_is_skipped(tmp_path):
    (tmp_path / "articles.jsonl").write_text('{"url": "u1", "text": "ok"}\n{"url": "u2", "te\n')
    assert archive.add_articles(arts(("u9", "Z", "2026-10-03", "z")), tmp_path) == 1
    urls = [json.loads(line)["url"] for line in (tmp_path / "articles.jsonl").read_text().splitlines()]
    assert urls == ["u1", "u9"]


def test_digest_log(tmp_path):
    archive.add_digest(None, tmp_path)
    assert not (tmp_path / "digests.jsonl").exists()
    archive.add_digest({"availability": [{"player": "X", "status": "out"}], "summary_el": "..."}, tmp_path)
    row = json.loads((tmp_path / "digests.jsonl").read_text())
    assert row["availability"][0]["player"] == "X" and "summary_el" not in row


def test_archive_is_not_published():
    from elf import publish
    assert all("archive" not in name for name in publish.PUBLIC_FILES)
