"""Collect news/expert articles and turn them into player-level signals.

1. fetch every source in sources.yaml (RSS or EuroLeague CMS)
2. keep recent, EuroLeague-relevant items
3. ask Gemini (free tier) for a structured digest: availability per player,
   expert picks/fades, and a short Greek summary.
Without GEMINI_API_KEY the raw headlines are still published.
"""
from __future__ import annotations

import html
import json
import os
import re
import time
import unicodedata
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

import requests
import yaml

from .config import ROOT

UA = {"User-Agent": "Mozilla/5.0 (elf-fantasy-helper; personal use)"}
INCROWD = "https://article-cms-api.incrowdsports.com/v2/articles"

# Greek/English stems that mark an article as EuroLeague-related.
KEYWORDS = [
    "euroleague", "ευρωλιγκ", "ευρωλίγκ", "παναθηναικ", "ολυμπιακ", "ρεαλ", "μπαρτσελον",
    "φενερ", "εφες", "παρτιζαν", "ερυθρος", "ζαλγκιρ", "μακαμπι", "χαποελ", "μοναχο", "μονακο",
    "μπαγερν", "βιλερμπαν", "βιρτους", "αρματι", "αρμανι", "μπασκονι", "βαλενθι", "ντουμπαι",
    "παρι ", "fantasy",
]


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFD", s.lower())
    return "".join(c for c in s if unicodedata.category(c) != "Mn")


def _clean(text: str, limit: int = 600) -> str:
    text = re.sub(r"<[^>]+>", " ", html.unescape(text or ""))
    return re.sub(r"\s+", " ", text).strip()[:limit]


def _date(s: str | None):
    if not s:
        return None
    try:
        d = parsedate_to_datetime(s)
    except (TypeError, ValueError):
        try:
            d = datetime.fromisoformat(s.replace("Z", "+00:00"))
        except ValueError:
            return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


FULL_TEXT = 8000   # fantasy columns: keep (almost) the whole article
EXCERPT = 600


BROWSER = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                         "(KHTML, like Gecko) Chrome/128.0 Safari/537.36",
           "Accept": "application/rss+xml, application/xml, text/xml, */*"}


def access_headers() -> dict:
    """The personal site (and its /feed proxy) sits behind Cloudflare Access: a service token gets in.
    Without the secrets (no Access yet) nothing extra is sent."""
    cid, sec = os.environ.get("CF_ACCESS_CLIENT_ID"), os.environ.get("CF_ACCESS_CLIENT_SECRET")
    return {"CF-Access-Client-Id": cid, "CF-Access-Client-Secret": sec} if cid and sec else {}


PROXIED = (".substack.com", "basketnews.com")   # hosts that block GitHub Actions' IPs (see functions/feed.js)


def _via_proxy(url: str, errors: list[str]) -> bytes | None:
    """Our Pages Function /feed fetches from Cloudflare instead; None if it can't (not allowed, down)."""
    dash = os.environ.get("DASHBOARD_URL", "").rstrip("/")
    if not dash or not any(h in url for h in PROXIED):
        return None
    p = requests.get(f"{dash}/feed", params={"u": url}, headers={**BROWSER, **access_headers()},
                     timeout=30, allow_redirects=False)     # Access sends a login page via a redirect
    if p.status_code == 200 and p.content.lstrip().startswith(b"<"):
        return p.content
    errors.append(f"proxy {p.status_code}")
    return None


def _get_feed(url: str) -> bytes:
    """Direct, then (blocking hosts only) our Pages Function proxy.
    Substack blocks GitHub Actions' IPs; the proxy fetches from Cloudflare instead."""
    errors = []
    r = requests.get(url, headers=BROWSER, timeout=30)
    if r.status_code == 200:
        return r.content
    errors.append(f"direct {r.status_code}")
    content = _via_proxy(url, errors)
    if content is not None:
        return content
    raise requests.HTTPError(", ".join(errors))


def _substack_api(src: dict) -> list[dict]:
    base = src["url"].rsplit("/feed", 1)[0]
    r = requests.get(f"{base}/api/v1/posts", params={"limit": 10}, headers=BROWSER, timeout=30)
    r.raise_for_status()
    return [{"title": _clean(p.get("title"), 200), "url": p.get("canonical_url"),
             "date": _date(p.get("post_date")),
             "text": _clean(p.get("body_html") or p.get("description"),
                            FULL_TEXT if src.get("fantasy") else EXCERPT)} for p in r.json()]


ATOM = "{http://www.w3.org/2005/Atom}"


def fetch_rss(src: dict) -> list[dict]:
    try:
        content = _get_feed(src["url"])
    except requests.RequestException as e:
        if ".substack.com" in src["url"]:
            try:
                return _substack_api(src)
            except requests.RequestException as e2:
                raise requests.HTTPError(f"{e}; api {e2}") from e2
        raise
    root = ET.fromstring(content)
    limit = FULL_TEXT if src.get("fantasy") else EXCERPT
    items = []
    for it in root.iter("item"):
        items.append({
            "title": _clean(it.findtext("title"), 200),
            "url": it.findtext("link"),
            "date": _date(it.findtext("pubDate")),
            "text": _clean(it.findtext("{http://purl.org/rss/1.0/modules/content/}encoded")
                           or it.findtext("description"), limit),
        })
    for it in root.iter(f"{ATOM}entry"):
        links = it.findall(f"{ATOM}link")
        link = next((x for x in links if x.get("rel", "alternate") == "alternate"),
                    links[0] if links else None)
        items.append({
            "title": _clean(it.findtext(f"{ATOM}title"), 200),
            "url": link.get("href") if link is not None else None,
            "date": _date(it.findtext(f"{ATOM}published") or it.findtext(f"{ATOM}updated")),
            "text": _clean(it.findtext(f"{ATOM}content") or it.findtext(f"{ATOM}summary"), limit),
        })
    return items


REPORT_TEXT = 12000   # a whole injury table (every team) still fits


def fetch_page(src: dict) -> list[dict]:
    """A page that is rewritten in place (e.g. an injury report «updated daily»): one item, its text
    from the `start` marker on (the table, not menus and ads), dated by its last modification."""
    page = _get_feed(src["url"]).decode("utf-8", errors="replace")
    body = re.sub(r"<script.*?</script>|<style.*?</style>", " ", page, flags=re.S | re.I)
    i = body.find(src["start"]) if src.get("start") else -1
    if src.get("start") and i < 0:
        # the page was redesigned: fail as a source (shown in health) rather than pass menus and ads
        # to the summary as a trusted injury report
        raise ValueError(f"δεν βρέθηκε το «{src['start']}» στη σελίδα — άλλαξε η μορφή της;")
    part = body[i:] if i >= 0 else body
    j = part.find(src["end"]) if src.get("end") else -1
    part = part[:j] if j > 0 else part
    text = re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " | ", part)))
    text = re.sub(r"(\|\s*)+", "| ", text).strip(" |")[:REPORT_TEXT]
    modified = re.search(r'"dateModified"\s*:\s*"([^"]+)"', page)
    title = re.search(r'<meta property="og:title" content="([^"]+)"', page)
    date = _date(re.sub(r"([+-]\d\d)(\d\d)$", r"\1:\2", modified.group(1))) if modified else None
    return [{"title": _clean(title.group(1) if title else src["name"], 200), "url": src["url"],
             "date": date or datetime.now(timezone.utc), "text": text}]


def fetch_incrowd(src: dict) -> list[dict]:
    r = requests.get(INCROWD, headers=UA, timeout=30, params={
        "clientId": "EUROLEAGUE", "categorySlug": src.get("category", "news"),
        "size": 100 if src.get("category_text") else 40})
    r.raise_for_status()
    items = []
    for a in r.json()["data"]["articles"]:
        cats = {c.get("text") for c in a.get("categories") or []}
        if src.get("category_text") and src["category_text"] not in cats:
            continue
        meta = a.get("articleMetadata") or {}
        if src.get("fantasy"):  # full body from the article's text blocks
            body = " ".join(str(b.get("content") or "") for b in a.get("content") or []
                            if isinstance(b, dict) and b.get("contentType") == "TEXT")
            text = _clean(re.sub(r"\]\([^)]*\)", "]", body), FULL_TEXT)
        else:
            text = _clean(a.get("heroMedia", {}).get("summary") or meta.get("description"))
        items.append({
            "title": _clean(a.get("heroMedia", {}).get("title") or meta.get("title"), 200),
            "url": f"https://www.euroleaguebasketball.net/en/euroleague/news/{a['slug']}/",
            "date": _date(a.get("publishDate")),
            "text": text,
        })
    return items


def collect(names: list[str], hours: int = 96) -> tuple[list[dict], list[str]]:
    """Recent relevant items from all sources, plus a list of failed sources."""
    cfg = yaml.safe_load((ROOT / "sources.yaml").read_text())
    now = datetime.now(timezone.utc)
    name_keys = {_norm(n.split(",")[0]) for n in names if n and len(n.split(",")[0]) > 3}
    out, failed, seen = [], [], set()
    # fantasy columns first so they claim their articles before a general feed does
    for src in sorted(cfg["sources"], key=lambda x: not x.get("fantasy")):
        try:
            items = (fetch_incrowd(src) if src["type"] == "incrowd" else fetch_page(src)
                     if src["type"] == "page" else fetch_rss(src))
        except Exception as e:  # a dead source must not kill the run
            failed.append(f"{src['name']}: {type(e).__name__} {str(e)[:80]}")
            continue
        since = now - timedelta(hours=src.get("hours", hours))
        for it in items:
            # only web links: a feed's «javascript:» or «data:» link would run in the dashboard
            if not re.match(r"https?://", it["url"] or "", re.I) or it["url"] in seen or (it["date"] and it["date"] < since):
                continue
            if src.get("title_has") and src["title_has"].lower() not in it["title"].lower():
                continue
            blob = _norm(f"{it['title']} {it['text']}")
            if src.get("filter") and not (any(k in blob for k in KEYWORDS)
                                          or any(k in blob for k in name_keys)):
                continue
            seen.add(it["url"])
            out.append({**it, "date": it["date"].isoformat() if it["date"] else None,
                        "source": src["name"], "weight": src.get("weight", 1),
                        "fantasy": bool(src.get("fantasy")), "report": bool(src.get("report"))})
    # fantasy columns first (they carry the picks), then news by date
    out.sort(key=lambda x: (not x["fantasy"], -(datetime.fromisoformat(x["date"]).timestamp()
                                                 if x["date"] else 0)))
    return out, failed


PROMPT = """You are a EuroLeague Fantasy Challenge analyst. Below are recent articles
(title + excerpt) and the list of valid player names (Surname, Name) with team.
Greek articles write names in Greek: map them to the exact roster name.
Every "player" value is copied EXACTLY from ROSTER, in Latin letters ("SURNAME, NAME"), without the
team; never write a name in Greek, even when the article is Greek.

Return ONLY JSON with this schema:
{
 "availability": [{"player": "<exact roster name>", "status": "out|doubtful|questionable|available",
                   "note": "<short, Greek>", "source": "<source name>"}],
 "expert": [{"player": "<exact roster name>", "stance": "pick|avoid|captain",
             "note": "<short, Greek>", "source": "<source name>"}],
 "round": <EuroLeague round the fantasy tips refer to, integer or null>,
 "summary_el": "<5-8 bullet points in Greek, formal-neutral, most fantasy-relevant first>"
}
In summary_el the text is Greek, but every player is written in Latin letters as Name Surname from
ROSTER (e.g. Jean Montero, not Γιαν Μοντέρο), and every club by its name in TEAMS (e.g. Crvena Zvezda);
never translate or transliterate a name, and no quotation marks around names.
Only include players explicitly discussed. Do not guess injuries that are not stated.
Items marked INJURY REPORT are a table: team | position | player | status | round(s) | comment.
Map status: Out -> "out", Doubtful -> "doubtful", Questionable / Game-time / Uncertain -> "questionable",
Expected / Ready -> "available" (Uncertain is often a coach's decision for a bench player);
use it only if the round(s) include the upcoming round («Indefinitely» does). It is newer and more
complete than the news: when they disagree about the same player, prefer the report.
"expert": from articles marked FANTASY only, list EVERY player (and head coach) the
author recommends (stance "pick"), suggests as captain ("captain"), or advises against
("avoid"). One entry per player per source; use the article's source name exactly.

ROSTER:
{roster}

TEAMS (code = name):
{teams}

ARTICLES:
{articles}
"""


REQUEST_TIMEOUT_S = 90    # one model's answer; a slow one gives way to the next
DIGEST_BUDGET_S = 360     # no new model is asked after this (the update must not hang on Gemini)


def digest(articles: list[dict], roster: list[str], teams: dict | None = None) -> dict | None:
    key = os.environ.get("GEMINI_API_KEY")
    if not key or not articles:
        return None
    # per fantasy source: up to 4 newest, round-tips articles first
    fan, per = [], {}
    for a in sorted((a for a in articles if a.get("fantasy")),
                    key=lambda a: ("round" not in a["title"].lower() and "tips" not in
                                   a["title"].lower(), -(datetime.fromisoformat(a["date"])
                                                         .timestamp() if a["date"] else 0))):
        if per.get(a["source"], 0) < 4:
            per[a["source"]] = per.get(a["source"], 0) + 1
            fan.append(a)
    # injury reports go in whole (a table of every team); news are cut to an excerpt
    reports = [a for a in articles if a.get("report")]
    rest = [a for a in articles if not a.get("fantasy") and not a.get("report")][:60]
    arts = "\n\n".join(
        [f"[INJURY REPORT | {a['source']} | {a['date']}] {a['title']}\n{a['text']}" for a in reports]
        + [f"[FANTASY | {a['source']} | {a['date']}] {a['title']}\n{a['text']}" for a in fan]
        + [f"[NEWS | {a['source']} | {a['date']}] {a['title']}\n{a['text'][:500]}" for a in rest])
    body = {
        "contents": [{"parts": [{"text": PROMPT.replace("{roster}", "\n".join(roster))
                                 .replace("{teams}", "\n".join(f"{c} = {n}" for c, n in (teams or {}).items()))
                                 .replace("{articles}", arts)}]}],
        "generationConfig": {"responseMimeType": "application/json", "temperature": 0.2},
    }
    headers = {"x-goog-api-key": key}  # header, never in the URL (URLs end up in logs)
    base = "https://generativelanguage.googleapis.com/v1beta"
    tried, errors = [], []
    candidates = [m for m in [os.environ.get("GEMINI_MODEL")] if m] or []
    listed = False
    start = time.monotonic()
    while True:
        if not candidates and not listed:  # ask the API which stable flash models exist
            candidates, listed = _flash_models(base, headers), True
        candidates = [c for c in candidates if c not in tried]
        # 18-22/10: every run's first model timed out and the whole digest went with it
        if not candidates or len(tried) >= 4 or time.monotonic() - start > DIGEST_BUDGET_S:
            break
        model_name = candidates.pop(0)
        tried.append(model_name)
        r = None
        for wait in (0, 20, 45):  # 503 "high demand" is usually over within a minute
            time.sleep(wait)
            try:
                r = requests.post(f"{base}/models/{model_name}:generateContent", headers=headers,
                                  json=body, timeout=REQUEST_TIMEOUT_S)
            except (requests.Timeout, requests.ConnectionError) as e:
                r = None   # a model that doesn't answer in time: the next one, not the same again
                errors.append(f"timeout {model_name}: {type(e).__name__}")
                break
            if r.status_code not in (500, 503):
                break
        if r is None:
            continue
        if r.status_code == 200:
            text = r.json()["candidates"][0]["content"]["parts"][0]["text"]
            out = repair(_normalize(json.loads(text)))
            if garbled(out):    # 14/10: «α%u03bd%u03b1…», «καλόs» — the next model, not the page
                errors.append(f"200 {model_name}: αλλοιωμένο κείμενο")
                continue
            out["_model"] = model_name
            return out
        try:
            msg = r.json().get("error", {}).get("message", "")[:120]
        except ValueError:
            msg = r.text[:120]
        errors.append(f"{r.status_code} {model_name}: {msg}")
        if r.status_code not in (404, 429, 500, 503):  # bad key etc.: no point retrying
            break
    if errors and all(e.startswith("timeout") for e in errors):
        raise RuntimeError(f"Gemini δεν απάντησε σε {REQUEST_TIMEOUT_S}s ({', '.join(tried)})")
    if errors and all(e.startswith(("503", "500")) for e in errors):
        raise RuntimeError(f"Gemini υπερφορτωμένο ({', '.join(tried)}) — δοκίμασε /update αργότερα")
    raise RuntimeError("Gemini " + (" | ".join(errors[-2:]) or "δεν βρέθηκε διαθέσιμο μοντέλο"))


def _normalize(d) -> dict:
    """LLM output is loosely typed: coerce to the schema the report expects."""
    if not isinstance(d, dict):
        d = {}
    summ = d.get("summary_el", "")
    if isinstance(summ, list):
        summ = "\n".join(f"• {str(x).lstrip('•-* ').strip()}" for x in summ if str(x).strip())
    d["summary_el"] = str(summ or "")
    for key in ("availability", "expert"):
        items = d.get(key) if isinstance(d.get(key), list) else []
        d[key] = [{k: str(v) for k, v in it.items() if v is not None}
                  for it in items if isinstance(it, dict) and it.get("player")]
    return d


# 14/10 the model wrote Greek as «α%u03bd%u03b1μένεται» and words mixed Latin into Greek («καλόs»,
# «επιστροͯdής»): the escapes are decoded; text still broken after that is not published.
_PCT_U = re.compile(r"%u([0-9a-fA-F]{4})")
_MIXED = re.compile(r"[A-Za-z][\u0370-\u03ff\u1f00-\u1fff]|[\u0370-\u03ff\u1f00-\u1fff][A-Za-z]")
_COMBINING = re.compile(r"[\u0300-\u036f]")


def _strings(d: dict):
    yield d.get("summary_el", "")
    for key in ("availability", "expert"):
        for it in d.get(key) or []:
            yield from (v for v in it.values() if isinstance(v, str))


def _bad(word: str) -> bool:
    # a «%» next to a letter is broken («Χαμηλ%», «απ%δοσης»); after a number it is a percentage («48%»)
    return bool(re.search(r"[^\W\d_]%|%[^\W\d_]", word)) or bool(_MIXED.search(word)) or bool(_COMBINING.search(unicodedata.normalize("NFC", word)))


def repair(d: dict) -> dict:
    """%uXXXX escapes in the LLM's strings back to the letters; a column's note that is still broken
    is dropped (the pick itself stays)."""
    fix = lambda s: _PCT_U.sub(lambda m: chr(int(m.group(1), 16)), s)
    d["summary_el"] = fix(d.get("summary_el", ""))
    for key in ("availability", "expert"):
        d[key] = [{k: fix(v) if isinstance(v, str) else v for k, v in it.items()} for it in d.get(key) or []]
        for it in d[key]:
            if isinstance(it.get("note"), str) and any(_bad(w) for w in it["note"].split()):
                del it["note"]
    return d


def garbled(d: dict, share: float = 0.02) -> bool:
    """Words with a «%», Latin and Greek letters mixed, or a stray combining mark: a few are a slip,
    more than `share` of the words (and at least 3) is a broken answer."""
    words = [w for s in _strings(d) for w in s.split()]
    bad = sum(1 for w in words if _bad(w))
    return bad >= 3 and bad > share * len(words)


_UNSTABLE = ("preview", "exp", "omni", "live", "audio", "image", "tts", "thinking", "embedding")


def _flash_models(base: str, headers: dict) -> list[str]:
    """Stable (free-tier friendly) flash models, newest first; lite variants last."""
    r = requests.get(f"{base}/models", headers=headers, params={"pageSize": 200}, timeout=30)
    if r.status_code != 200:
        return []
    names = [m["name"].split("/", 1)[1] for m in r.json().get("models", [])
             if "generateContent" in m.get("supportedGenerationMethods", [])]
    stable = [n for n in names if "flash" in n and not any(u in n for u in _UNSTABLE)]

    def rank(n: str):
        ver = re.search(r"(\d+(?:\.\d+)?)", n)
        return ("lite" in n, "latest" in n, -float(ver.group(1)) if ver else 0.0, n)

    ordered = sorted(stable, key=rank)
    full = [n for n in ordered if "lite" not in n]
    lite = [n for n in ordered if "lite" in n]
    # interleave: newest flash, newest lite, next flash... (lite is usually less overloaded)
    return [m for pair in zip(full + [None] * len(lite), lite + [None] * len(full))
            for m in pair if m]


# ------------------------------------------------------------ names back to the roster
# The LLM sometimes writes the names in Greek («ΛΕΣΟΡ, ΜΑΘΙΑΣ»): nothing matched, so the news' injuries
# and the columns' picks were silently ignored. Both sides go to a rough sound-alike Latin skeleton and the
# closest roster name wins, only when it is clearly the closest.
_GR2 = [("μπ", "b"), ("ντ", "d"), ("γκ", "g"), ("γγ", "ng"), ("ου", "u"), ("αι", "e"), ("ει", "i"),
        ("οι", "i"), ("τζ", "tz"), ("τσ", "ts"), ("αυ", "av"), ("ευ", "ev")]
_GR1 = dict(zip("αβγδεζηθικλμνξοπρσςτυφχψω",
                ["a", "v", "g", "d", "e", "z", "i", "t", "i", "k", "l", "m", "n", "ks", "o", "p", "r", "s",
                 "s", "t", "i", "f", "h", "ps", "o"]))
_LAT = [("sch", "s"), ("sh", "s"), ("ch", "ts"), ("ph", "f"), ("th", "t"), ("ck", "k"), ("dj", "tz"),
        ("j", "tz"), ("c", "k"), ("q", "k"), ("x", "ks"), ("w", "u"), ("y", "i"), ("oo", "u"), ("ou", "u"),
        ("ee", "i"), ("ai", "e"), ("ay", "ei"), ("ei", "i"), ("nd", "nt")]


def _skel(s: str, medial_nt: bool = True) -> str:
    s = unicodedata.normalize("NFD", str(s).lower())
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    greek = any("α" <= c <= "ω" for c in s)
    if greek:
        if medial_nt:   # Μοντέρο: Montero; but Μαντάρ: Madar (the other reading); an initial ντ is a d: Ντέιβις
            s = re.sub(r"(?<=[α-ω])ντ", "nt", s)
        for a, b in _GR2:
            s = s.replace(a, b)
        s = "".join(_GR1.get(c, c) for c in s)
    else:
        for a, b in _LAT:
            s = s.replace(a, b)
    s = re.sub(r"[^a-z ,]", "", s).replace("h", "").replace("v", "b")
    return re.sub(r"(.)\1+", r"\1", s).strip()


def _finder(roster: list[str]):
    """name (roster's «SURNAME, NAME», «Name Surname», Greek or Latin letters) -> the roster name, or None
    when no name is clearly the closest."""
    import difflib
    exact = {n.upper(): n for n in roster}
    # «SURNAME, NAME» as the roster writes it, or «Name Surname» (Marcus Bingham Jr. vs BINGHAM, MARCUS)
    words = lambda x, nt=True: _skel(re.sub(r"\b(jr|sr|ii|iii)\b\.?", " ", str(x), flags=re.I), nt).replace(",", " ").split()
    skel = [(n, " ".join(words(n))) for n in roster]
    cache = {}

    def find(raw: str):
        name = str(raw).split(" (")[0].strip()
        if name.upper() in exact:
            return exact[name.upper()]
        if name not in cache:
            ks = set()
            for w in (words(name), words(name, False)):        # a Greek medial ντ read as nt and as d
                ks |= {" ".join(w)} | ({" ".join(w[-1:] + w[:-1])} if "," not in name else set())
            sc = sorted(((max(difflib.SequenceMatcher(None, k, s).ratio() for k in ks), n) for n, s in skel), reverse=True)
            ok = sc and sc[0][0] >= 0.75 and (len(sc) < 2 or sc[0][0] - sc[1][0] >= 0.04)
            cache[name] = sc[0][1] if ok else None
        return cache[name]
    return find


# a run of 2-3 capitalised Greek words: a name the LLM wrote in Greek («Γιαν Μοντέρο»)
_GREEK_NAME = re.compile(r"[Α-ΩΆΈΉΊΌΎΏ][α-ωάέήίόύώϊϋΐΰς]+(?:[ -][Α-ΩΆΈΉΊΌΎΏ][α-ωάέήίόύώϊϋΐΰς]+){1,2}")


def _display(roster_name: str) -> str:
    last, _, first = roster_name.partition(",")
    return f"{first.strip().title()} {last.strip().title()}".strip()


# the clubs as Greek writes them (any case ending): the summary gets the clubs' own names
CLUBS_GR = {
    "RED": r"Ερυθρ[όοού]\w* Αστέρ\w*", "OLY": r"Ολυμπιακ(?:ός|ού|ό|έ)\b", "PAN": r"Παναθηναϊκ(?:ός|ού|ό|έ)\b", "PAR": r"Παρτίζαν",
    "IST": r"(?:Αναντολο[υύ] )?Εφ[εέ]ς", "ULK": r"Φενερμπαχτσ[εέ]\w*", "BES": r"Μπεσ[ιί]κτα[ςσ]",
    "MIL": r"(?:Αρμάνι |Ολίμπια )*Μιλάνο|Αρμάνι", "DUB": r"Ντουμπ[αά]ι", "BAR": r"Μπαρτσελ[οό]ν\w*",
    "MUN": r"Μπ[αά]γερν(?: Μονάχου)?", "HTA": r"Χ[αά]ποελ(?: Τελ Αβ[ιί]β)?", "BAS": r"Μπασκ[οό]νι\w*",
    "ASV": r"Βιλερμπ[αά]ν\w*|Ασβ[εέ]λ", "TEL": r"Μακ[αά]μπι(?: Τελ Αβ[ιί]β)?", "PRS": r"Παρ[ιί](?= |$|[.,;·])",
    "MAD": r"Ρε[αά]λ(?: Μαδρίτης)?", "PAM": r"Βαλ[εέ]ν[θσ]ι\w*", "VIR": r"Β[ιί]ρτους(?: Μπολ[οό]νια\w*)?",
    "ZAL": r"Ζ[αά]λγκιρι[ςσ]",
}


def latin_clubs(text: str, teams: dict | None) -> str:
    """Greek club names (Ολυμπιακού, τη Βαλένθια) -> the clubs' names (teams: code -> name)."""
    if not text or not teams:
        return text
    for code, pat in CLUBS_GR.items():
        if teams.get(code):
            text = re.sub(rf"(?<![\w]){pat}", teams[code], text)
    return text


def latin_names(text: str, roster: list[str], teams: dict | None = None) -> str:
    """Player names written in Greek in the summary, back to the roster's Latin «Name Surname»; clubs too
    (teams: code -> name)."""
    text = latin_clubs(text, teams)
    if not text or not roster:
        return unquote(text, list((teams or {}).values()))
    import difflib
    find = _finder(roster)
    # fallback, the surname alone (the LLM gets first names wrong: «Μακί Μαντάρ» for Yam Madar): only when
    # exactly one roster player has a surname that close, so a common surname is never guessed
    sur = [(n, _skel(n.split(",")[0])) for n in roster]

    def by_surname(raw):
        best = set()
        for nt in (True, False):
            k = _skel(raw.split()[-1], nt)
            best |= {n for n, s in sur if difflib.SequenceMatcher(None, k, s).ratio() >= 0.85}
        return best.pop() if len(best) == 1 else None

    def sub(m):
        n = find(m.group(0)) or by_surname(m.group(0))
        return _display(n) if n else m.group(0)
    return unquote(_GREEK_NAME.sub(sub, text), [_display(n) for n in roster] + list((teams or {}).values()))


def unquote(text: str, names: list[str]) -> str:
    """«Jean Montero» -> Jean Montero: no quotation marks around a player's or a club's name."""
    names = sorted({n for n in names if n}, key=len, reverse=True)
    if not text or not names:
        return text
    alt = "|".join(re.escape(n) for n in names)
    return re.sub(rf"[«\"“]({alt})[»\"”]", r"\1", text)


def resolve_names(d: dict | None, roster: list[str], teams: dict | None = None) -> dict | None:
    """Each availability / expert "player" set to the exact roster name; the unmatched are dropped;
    the summary's player names in Latin letters."""
    if not d:
        return d
    find = _finder(roster)
    d["summary_el"] = latin_names(d.get("summary_el", ""), roster, teams)
    for key in ("availability", "expert"):
        out = []
        for it in d.get(key) or []:
            n = find(it.get("player", ""))
            if n:
                out.append({**it, "player": n})
        d[key] = out
    return d


AVAILABILITY_FACTOR = {"out": 0.0, "doubtful": 0.4, "questionable": 0.8, "available": 1.0}
