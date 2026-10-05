"""Public edition: a sanitized copy of the shared outputs, with nothing personal in it.

python -m elf.publish <out_dir>   -> the public site in <out_dir>: the web app (renamed to
                                     the product name) + data/*.json
python -m elf.publish --repo      -> data/public rewritten in place for the public GitHub repo:
                                     the same sanitized files, private-only files deleted
                                     (their full versions live in the private data repo)

One engine run feeds both editions. The personal edition deploys data/public as is;
the public one gets only what is listed in PUBLIC_FILES, stripped of personal fields
(my team, lineup logs, operational health notes). Anything not listed is never copied,
so a new personal file cannot leak by accident.
"""
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

from .config import PUBLIC, ROOT

PRODUCT = "HoopsLab"

# file -> function returning the sanitized content (None = copy unchanged)
PUBLIC_FILES = {
    "predictions.json": lambda d: {**d, "my_team": None, "health": [], "price_model": None,
                                   "edition": "public"},
    "report_public.json": None,     # published as report.json
    "players.json": None,
    # titles, sources and links only: the articles' text belongs to their publishers (it is
    # read for the summary during the run and kept in the private archive, never published)
    "news.json": lambda d: {**d, "articles": [{k: v for k, v in a.items() if k != "text"}
                                              for a in d.get("articles", [])]},
    "model_params.json": None,
    "clubs.json": None,
    "tracking.json": lambda d: {**d, "lineups": []},
    # the autopilot is public; the owner's own points are not
    "autopilot.json": lambda d: {**d, "rounds": [{k: v for k, v in r.items() if k not in ("my_pts", "my_rank")}
                                                 for r in d.get("rounds", [])]},
}
RENAME = {"report_public.json": "report.json"}

# In the public repo these exist only in the private data repo: the owner's report and lineups,
# debugging shapes and alert state. Files kept but sanitized are the PUBLIC_FILES above; the
# rest of data/public (prices, prediction logs, expert log) has nothing personal in it.
PRIVATE_ONLY = ("report.json", "lineup_log.json", "roster_shape.json", "health_last.json")


def sanitize_repo(src: Path | None = None) -> list[str]:
    """Rewrite data/public in place for the public repo (the full files were saved to the private
    data repo first). Returns what it changed."""
    src = src or PUBLIC
    done = []
    for name, clean in PUBLIC_FILES.items():
        f = src / name
        if clean and f.exists():
            f.write_text(json.dumps(clean(json.loads(f.read_text())), ensure_ascii=False,
                                    indent=1, allow_nan=False))
            done.append(name)
    for name in PRIVATE_ONLY:
        if (src / name).exists():
            (src / name).unlink()
            done.append(f"-{name}")
    return done


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


def site(out: Path, src: Path | None = None) -> list[str]:
    """Web app with the product's name (no EuroLeague branding) + the sanitized data."""
    out = Path(out)
    shutil.copytree(ROOT / "web", out, dirs_exist_ok=True)
    index = out / "index.html"
    html = index.read_text()
    for old, new in (('<meta name="apple-mobile-web-app-title" content="ELF">',
                      f'<meta name="apple-mobile-web-app-title" content="{PRODUCT}">'),
                     ("<title>ELF Dashboard</title>", f"<title>{PRODUCT}</title>"),
                     ("<h1>🏀 EuroLeague Fantasy — ", f'<h1>🏀 {PRODUCT} <small class="muted">beta</small> — ')):
        if old not in html:
            raise RuntimeError(f"publish: δεν βρέθηκε στο index.html: {old}")
        html = html.replace(old, new)
    index.write_text(html)
    manifest = json.loads((out / "manifest.json").read_text())
    manifest.update(name=PRODUCT, short_name=PRODUCT)
    (out / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=1))
    return bundle(out, src)


if __name__ == "__main__":
    if sys.argv[1:] == ["--repo"]:
        print(sanitize_repo())
    else:
        print(site(Path(sys.argv[1] if len(sys.argv) > 1 else "site_public")))
