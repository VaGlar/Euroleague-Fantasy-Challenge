"""A shared coachdime.com link shows a title, a description and a picture (Viber, WhatsApp, Facebook, X),
and search engines get a snippet: the public build only (elf/publish.py SHARE_TAGS, web/og.png)."""
import re
import struct
from pathlib import Path

from elf import publish

WEB = Path(__file__).parents[1] / "web"


def test_the_public_page_has_a_description_and_a_preview_image(tmp_path):
    publish.site(tmp_path)
    html = (tmp_path / "index.html").read_text()
    head = html[:html.index("</head>")]
    meta = dict(re.findall(r'<meta (?:name|property)="([^"]+)" content="([^"]*)">', head))
    assert 50 <= len(meta["description"]) <= 200 and "unofficial" in meta["description"]
    assert meta["og:description"] == meta["description"]
    assert meta["og:url"] == publish.HOME
    assert meta["og:image"] == publish.HOME + "og.png" and (tmp_path / "og.png").exists()
    assert meta["twitter:card"] == "summary_large_image"
    assert head.count('property="og:title"') == 1


def test_the_preview_image_is_the_size_the_tags_say():
    png = (WEB / "og.png").read_bytes()
    assert png[:8] == b"\x89PNG\r\n\x1a\n"
    w, h = struct.unpack(">II", png[16:24])
    assert (w, h) == (1200, 630)
    assert len(png) < 300_000          # small enough for every messenger's preview


def test_the_personal_page_announces_nothing():
    head = (WEB / "index.html").read_text().split("</head>")[0]
    assert 'property="og:' not in head and 'name="description"' not in head
