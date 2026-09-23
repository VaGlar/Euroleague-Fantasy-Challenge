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
import unicodedata
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

import requests
import yaml

from .config import ROOT

UA = {"User-Agent": "Mozilla/5.0 (elf-fantasy-helper; personal use)"}
INCROWD = "https://article-cms-api.incrowdsports.com/v2/articles"
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")

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


def fetch_rss(src: dict) -> list[dict]:
    r = requests.get(src["url"], headers=UA, timeout=30)
    r.raise_for_status()
    root = ET.fromstring(r.content)
    items = []
    for it in root.iter("item"):
        items.append({
            "title": _clean(it.findtext("title"), 200),
            "url": it.findtext("link"),
            "date": _date(it.findtext("pubDate")),
            "text": _clean(it.findtext("{http://purl.org/rss/1.0/modules/content/}encoded")
                           or it.findtext("description")),
        })
    return items


def fetch_incrowd(src: dict) -> list[dict]:
    r = requests.get(INCROWD, headers=UA, timeout=30, params={
        "clientId": "EUROLEAGUE", "categorySlug": src.get("category", "news"), "size": 40})
    r.raise_for_status()
    items = []
    for a in r.json()["data"]["articles"]:
        meta = a.get("articleMetadata") or {}
        items.append({
            "title": _clean(a.get("heroMedia", {}).get("title") or meta.get("title"), 200),
            "url": f"https://www.euroleaguebasketball.net/en/euroleague/news/{a['slug']}/",
            "date": _date(a.get("publishDate")),
            "text": _clean(a.get("heroMedia", {}).get("summary") or meta.get("description")),
        })
    return items


def collect(names: list[str], hours: int = 96) -> tuple[list[dict], list[str]]:
    """Recent relevant items from all sources, plus a list of failed sources."""
    cfg = yaml.safe_load((ROOT / "sources.yaml").read_text())
    since = datetime.now(timezone.utc) - timedelta(hours=hours)
    name_keys = {_norm(n.split(",")[0]) for n in names if n and len(n.split(",")[0]) > 3}
    out, failed, seen = [], [], set()
    for src in cfg["sources"]:
        try:
            items = fetch_incrowd(src) if src["type"] == "incrowd" else fetch_rss(src)
        except Exception as e:  # a dead source must not kill the run
            failed.append(f"{src['name']}: {type(e).__name__}")
            continue
        for it in items:
            if not it["url"] or it["url"] in seen or (it["date"] and it["date"] < since):
                continue
            blob = _norm(f"{it['title']} {it['text']}")
            if src.get("filter") and not (any(k in blob for k in KEYWORDS)
                                          or any(k in blob for k in name_keys)):
                continue
            seen.add(it["url"])
            out.append({**it, "date": it["date"].isoformat() if it["date"] else None,
                        "source": src["name"], "weight": src.get("weight", 1)})
    out.sort(key=lambda x: x["date"] or "", reverse=True)
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
 "summary_el": "<5-8 bullet points in Greek, formal-neutral, most fantasy-relevant first>"
}
Only include players explicitly discussed. Do not guess injuries that are not stated.

ROSTER:
{roster}

ARTICLES:
{articles}
"""


def digest(articles: list[dict], roster: list[str]) -> dict | None:
    key = os.environ.get("GEMINI_API_KEY")
    if not key or not articles:
        return None
    arts = "\n\n".join(
        f"[{a['source']} | w={a['weight']} | {a['date']}] {a['title']}\n{a['text'][:500]}"
        for a in articles[:80])
    body = {
        "contents": [{"parts": [{"text": PROMPT.replace("{roster}", "\n".join(roster))
                                 .replace("{articles}", arts)}]}],
        "generationConfig": {"responseMimeType": "application/json", "temperature": 0.2},
    }
    headers = {"x-goog-api-key": key}  # header, never in the URL (URLs end up in logs)
    base = "https://generativelanguage.googleapis.com/v1beta"
    models = [GEMINI_MODEL]
    last = None
    for attempt in range(3):
        if attempt == len(models):  # configured model unknown: ask the API what exists
            models += _flash_models(base, headers)
            if attempt == len(models):
                break
        model_name = models[attempt]
        r = requests.post(f"{base}/models/{model_name}:generateContent", headers=headers,
                          json=body, timeout=120)
        if r.status_code == 200:
            text = r.json()["candidates"][0]["content"]["parts"][0]["text"]
            return json.loads(text)
        try:
            msg = r.json().get("error", {}).get("message", "")[:160]
        except ValueError:
            msg = r.text[:160]
        last = f"{r.status_code} {model_name}: {msg}"
        if r.status_code != 404:
            break
    raise RuntimeError(f"Gemini {last}")


def _flash_models(base: str, headers: dict) -> list[str]:
    r = requests.get(f"{base}/models", headers=headers, timeout=30)
    if r.status_code != 200:
        return []
    names = [m["name"].split("/", 1)[1] for m in r.json().get("models", [])
             if "generateContent" in m.get("supportedGenerationMethods", [])
             and "flash" in m["name"] and "image" not in m["name"] and "tts" not in m["name"]]
    return sorted(names, reverse=True)[:2]


AVAILABILITY_FACTOR = {"out": 0.0, "doubtful": 0.4, "questionable": 0.8, "available": 1.0}
