"""«Round» (PR 65): «Νέα» and «Report» are no longer tabs; their content is on «Round» (id `today`).

Every way into a tab, written in the page's source (top tabs, bottom bar, «Περισσότερα», in-page
buttons, showTab calls), must lead to a <section> that exists, and none to the gone `news`/`report`.
A source check runs in the fast suite; tests/ui/round.spec.mjs checks the same on the rendered page.
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HTML = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
JS = {p.name: p.read_text(encoding="utf-8") for p in (ROOT / "web").glob("*.js")}
GONE = {"news", "report"}


def sections():
    return set(re.findall(r'<section id="([\w-]+)"', HTML))


def more_tabs():
    block = re.search(r"const MORE_TABS = \[(.*?)\];", HTML, re.S).group(1)
    return re.findall(r'\[\s*"([\w-]+)"\s*,', block)


def targets():
    """(where, tab) for every literal way into a tab."""
    out = [("html", t) for t in re.findall(r'data-(?:t|go|tab)="([\w-]+)"', HTML)]
    out += [("MORE_TABS", t) for t in more_tabs()]
    for name, src in [("index.html", HTML), *JS.items()]:
        out += [(name, t) for t in re.findall(r"""showTab\(\s*["']([\w-]+)["']""", src)]
    return out


def test_the_page_still_has_its_tabs():
    # a sanity floor, so an empty parse can't pass the tests below
    assert {"today", "team", "players", "teams", "compare", "model", "about"} <= sections()
    assert len(targets()) >= 15
    assert more_tabs() == ["compare", "model", "about"]


def test_no_section_and_no_way_into_news_or_report():
    assert not GONE & sections()
    assert [(w, t) for w, t in targets() if t in GONE] == []
    # nor a selector that renders into them
    for name, src in [("index.html", HTML), *JS.items()]:
        assert not re.search(r"""[$]\(\s*["']#(news|report)\b""", src), name
        assert not re.search(r"""getElementById\(\s*["'](news|report)["']""", src), name


def test_every_way_into_a_tab_leads_to_a_section():
    have = sections() | {"more"}            # «more» opens the sheet, not a section
    assert [(w, t) for w, t in targets() if t not in have] == []


def test_an_unknown_saved_tab_falls_back_to_round():
    # a last tab saved as news/report (before PR 65) must not leave a blank page
    body = re.search(r"function showTab\(t\) \{(.*?)\n\}", HTML, re.S).group(1)
    assert re.search(r'if \(!document\.getElementById\(t\)\) t = "today";', body)
