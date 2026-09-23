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


def fetch_rss(src: dict) -> list[dict]:
    r = requests.get(src["url"], headers=UA, timeout=30)
    r.raise_for_status()
    root = ET.fromstring(r.content)
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
    return items


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
            items = fetch_incrowd(src) if src["type"] == "incrowd" else fetch_rss(src)
        except Exception as e:  # a dead source must not kill the run
            failed.append(f"{src['name']}: {type(e).__name__}")
            continue
        since = now - timedelta(hours=src.get("hours", hours))
        for it in items:
            if not it["url"] or it["url"] in seen or (it["date"] and it["date"] < since):
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
                        "fantasy": bool(src.get("fantasy"))})
    # fantasy columns first (they carry the picks), then news by date
    out.sort(key=lambda x: (not x["fantasy"], -(datetime.fromisoformat(x["date"]).timestamp()
                                                 if x["date"] else 0)))
    return out, failed


PROMPT = """You are a EuroLeague Fantasy Challenge analyst. Below are recent articles
(title + excerpt) and the list of valid player names (Surname, Name) with team.
Greek articles write names in Greek: map them to the exact roster name.

Return ONLY JSON with this schema:
{
 "availability": [{"player": "<exact roster name>", "status": "out|doubtful|questionable|available",
                   "note": "<short, Greek>", "source": "<source name>"}],
 "expert": [{"player": "<exact roster name>", "stance": "pick|avoid|captain",
             "note": "<short, Greek>", "source": "<source name>"}],
 "round": <EuroLeague round the fantasy tips refer to, integer or null>,
 "summary_el": "<5-8 bullet points in Greek, formal-neutral, most fantasy-relevant first>"
}
Only include players explicitly discussed. Do not guess injuries that are not stated.
"expert": from articles marked FANTASY only, list EVERY player (and head coach) the
author recommends (stance "pick"), suggests as captain ("captain"), or advises against
("avoid"). One entry per player per source; use the article's source name exactly.

ROSTER:
{roster}

ARTICLES:
{articles}
"""


def digest(articles: list[dict], roster: list[str]) -> dict | None:
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
    rest = [a for a in articles if not a.get("fantasy")][:60]
    arts = "\n\n".join(
        [f"[FANTASY | {a['source']} | {a['date']}] {a['title']}\n{a['text']}" for a in fan]
        + [f"[NEWS | {a['source']} | {a['date']}] {a['title']}\n{a['text'][:500]}" for a in rest])
    body = {
        "contents": [{"parts": [{"text": PROMPT.replace("{roster}", "\n".join(roster))
                                 .replace("{articles}", arts)}]}],
        "generationConfig": {"responseMimeType": "application/json", "temperature": 0.2},
    }
    headers = {"x-goog-api-key": key}  # header, never in the URL (URLs end up in logs)
    base = "https://generativelanguage.googleapis.com/v1beta"
    tried, errors = [], []
    candidates = [m for m in [os.environ.get("GEMINI_MODEL")] if m] or []
    listed = False
    while True:
        if not candidates and not listed:  # ask the API which stable flash models exist
            candidates, listed = _flash_models(base, headers), True
        candidates = [c for c in candidates if c not in tried]
        if not candidates or len(tried) >= 4:
            break
        model_name = candidates.pop(0)
        tried.append(model_name)
        for wait in (0, 20, 45):  # 503 "high demand" is usually over within a minute
            time.sleep(wait)
            r = requests.post(f"{base}/models/{model_name}:generateContent", headers=headers,
                              json=body, timeout=120)
            if r.status_code not in (500, 503):
                break
        if r.status_code == 200:
            text = r.json()["candidates"][0]["content"]["parts"][0]["text"]
            out = _normalize(json.loads(text))
            out["_model"] = model_name
            return out
        try:
            msg = r.json().get("error", {}).get("message", "")[:120]
        except ValueError:
            msg = r.text[:120]
        errors.append(f"{r.status_code} {model_name}: {msg}")
        if r.status_code not in (404, 429, 500, 503):  # bad key etc.: no point retrying
            break
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


AVAILABILITY_FACTOR = {"out": 0.0, "doubtful": 0.4, "questionable": 0.8, "available": 1.0}
