"""Article archive: every article the news step sees, kept for the season.

The feeds only hold the last few days, so anything not stored here is gone. One JSON
line per article in data/archive/articles.jsonl (private: outside data/public, which is
deployed). Deduplicated by URL (the longest text wins); the digest's availability
findings go to data/archive/digests.jsonl, one line per run.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from .config import DATA

ARCHIVE = DATA / "archive"


def _read(f: Path) -> list[dict]:
    if not f.exists():
        return []
    out = []
    for line in f.read_text().splitlines():
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:   # a torn line never breaks the pipeline
            continue
    return out


def add_articles(articles: list[dict], root: Path | None = None) -> int:
    """Merge articles into the archive; returns how many are new."""
    f = (root or ARCHIVE) / "articles.jsonl"
    f.parent.mkdir(parents=True, exist_ok=True)
    rows = {r["url"]: r for r in _read(f) if r.get("url")}
    new = 0
    seen = datetime.now(timezone.utc).isoformat(timespec="seconds")
    for a in articles:
        url = a.get("url")
        if not url:
            continue
        keep = {k: a.get(k) for k in ("url", "title", "date", "source", "fantasy", "text")}
        old = rows.get(url)
        if old is None:
            new += 1
            rows[url] = {**keep, "seen": seen}
        elif len(keep.get("text") or "") > len(old.get("text") or ""):
            rows[url] = {**keep, "seen": old.get("seen", seen)}
    ordered = sorted(rows.values(), key=lambda r: (r.get("date") or "", r["url"]))
    f.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in ordered))
    return new


def add_digest(digest: dict | None, root: Path | None = None) -> None:
    if not digest:
        return
    f = (root or ARCHIVE) / "digests.jsonl"
    f.parent.mkdir(parents=True, exist_ok=True)
    row = {"at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
           "availability": digest.get("availability") or [], "expert": digest.get("expert") or []}
    with f.open("a") as fh:
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")
