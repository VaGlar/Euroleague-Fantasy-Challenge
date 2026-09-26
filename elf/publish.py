"""Public edition: a sanitized copy of the shared outputs, with nothing personal in it.

python -m elf.publish <out_dir>   -> writes <out_dir>/data/*.json for the public site

One engine run feeds both editions. The personal edition deploys data/public as is;
the public one gets only what is listed in PUBLIC_FILES, stripped of personal fields
(my team, lineup logs, operational health notes). Anything not listed is never copied,
so a new personal file cannot leak by accident.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from .config import PUBLIC

# file -> function returning the sanitized content (None = copy unchanged)
PUBLIC_FILES = {
    "predictions.json": lambda d: {**d, "my_team": None, "health": [], "price_model": None,
                                   "edition": "public"},
    "report_public.json": None,     # published as report.json
    "players.json": None,
    "news.json": None,
    "model_params.json": None,
    "clubs.json": None,
    "tracking.json": lambda d: {**d, "lineups": []},
}
RENAME = {"report_public.json": "report.json"}


def bundle(out: Path, src: Path | None = None) -> list[str]:
    src = src or PUBLIC
    dst = Path(out) / "data"
    dst.mkdir(parents=True, exist_ok=True)
    written = []
    for name, clean in PUBLIC_FILES.items():
        f = src / name
        if not f.exists():
            continue
        data = json.loads(f.read_text())
        if clean:
            data = clean(data)
        target = RENAME.get(name, name)
        (dst / target).write_text(json.dumps(data, ensure_ascii=False, allow_nan=False))
        written.append(target)
    return written


if __name__ == "__main__":
    print(bundle(Path(sys.argv[1] if len(sys.argv) > 1 else "site_public")))
