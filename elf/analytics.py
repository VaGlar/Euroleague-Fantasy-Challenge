"""Daily Cloudflare Web Analytics report to the owner's Telegram.

Reads the Web Analytics (RUM) data of the account through Cloudflare's GraphQL API and
sends yesterday's numbers per site, the week against the week before, and for the public
site where visitors come from (country, device, referrer).

Env: CF_ANALYTICS_TOKEN (API token with "Account Analytics: Read"; falls back to
CLOUDFLARE_API_TOKEN), CLOUDFLARE_ACCOUNT_ID, PUBLIC_URL or PUBLIC_PROJECT (the product's site),
TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID (without them the message is printed).
"""
from __future__ import annotations

import os
from datetime import date, datetime, timedelta
from html import escape
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

import requests

from . import notify
from .config import TIMEZONE

API = "https://api.cloudflare.com/client/v4/graphql"
DAYS = ["Δευ", "Τρι", "Τετ", "Πεμ", "Παρ", "Σαβ", "Κυρ"]

QUERY = """
query ($acc: String!, $since: Date!, $until: Date!, $day: Date!, $host: String!) {
  viewer { accounts(filter: {accountTag: $acc}) {
    days: rumPageloadEventsAdaptiveGroups(limit: 1000, filter: {date_geq: $since, date_leq: $until},
        orderBy: [date_ASC]) {
      count sum { visits } dimensions { date requestHost } }
    countries: rumPageloadEventsAdaptiveGroups(limit: 6, filter: {date: $day, requestHost: $host},
        orderBy: [sum_visits_DESC]) {
      sum { visits } dimensions { countryName } }
    devices: rumPageloadEventsAdaptiveGroups(limit: 5, filter: {date: $day, requestHost: $host},
        orderBy: [sum_visits_DESC]) {
      sum { visits } dimensions { deviceType } }
    referers: rumPageloadEventsAdaptiveGroups(limit: 6, filter: {date: $day, requestHost: $host},
        orderBy: [sum_visits_DESC]) {
      sum { visits } dimensions { refererHost } }
  } }
}"""


def fetch(day: date) -> dict:
    tok = os.environ.get("CF_ANALYTICS_TOKEN") or os.environ.get("CLOUDFLARE_API_TOKEN")
    acc = os.environ.get("CLOUDFLARE_ACCOUNT_ID")
    if not tok or not acc:
        raise RuntimeError("λείπει CF_ANALYTICS_TOKEN ή CLOUDFLARE_ACCOUNT_ID")
    host = urlparse(os.environ.get("PUBLIC_URL") or "").netloc
    if not host and os.environ.get("PUBLIC_PROJECT"):
        host = os.environ["PUBLIC_PROJECT"].lower() + ".pages.dev"
    variables = {"acc": acc, "since": (day - timedelta(days=13)).isoformat(), "until": (day + timedelta(days=1)).isoformat(),
                 "day": day.isoformat(), "host": host}
    r = requests.post(API, json={"query": QUERY, "variables": variables},
                      headers={"Authorization": f"Bearer {tok}"}, timeout=30)
    body = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
    if r.status_code != 200 or body.get("errors"):
        err = (body.get("errors") or [{}])[0].get("message") or r.text[:200]
        raise RuntimeError(f"Cloudflare {r.status_code}: {err}")
    accounts = (body.get("data") or {}).get("viewer", {}).get("accounts") or []
    return {**(accounts[0] if accounts else {}), "host": host}


def _pct(a: float, b: float) -> str:
    if not b:
        return ""
    d = round((a - b) / b * 100)
    return f" ({'▲' if d >= 0 else '▼'}{abs(d)}%)"


def message(data: dict, day: date) -> str:
    host = data.get("host") or ""
    per: dict[str, dict] = {}
    for g in data.get("days") or []:
        dm = g["dimensions"]
        s = per.setdefault(dm["requestHost"], {"t": [0, 0], "y": [0, 0], "w": [0, 0], "pw": [0, 0]})
        age = (day - date.fromisoformat(dm["date"])).days
        v, pv = g["sum"]["visits"], g["count"]
        for key, hit in (("t", age == -1), ("y", age == 0), ("w", 0 <= age < 7), ("pw", 7 <= age < 14)):
            if hit:
                s[key][0] += v
                s[key][1] += pv
    lines = [f"📈 <b>Analytics — {DAYS[day.weekday()]} {day.day}/{day.month}</b>"]
    if not per:
        lines.append("Καμία επίσκεψη τις τελευταίες 14 μέρες. Αν ξέρεις ότι μπήκε κόσμος: είναι ενεργό το Web Analytics "
                     "στο Pages project, και το token έχει «Account Analytics: Read» στον σωστό λογαριασμό;")
        return "\n".join(lines)
    for h in sorted(per, key=lambda h: (h != host, -per[h]["w"][0])):
        s = per[h]
        name = "HoopsLab" if h == host else h.split(".")[0]
        lines.append(f"\n<b>{escape(name)}</b> <i>{escape(h)}</i>\n"
                     f"χθες: <b>{s['y'][0]}</b> επισκέψεις · {s['y'][1]} προβολές\n"
                     f"σήμερα ως τώρα: <b>{s['t'][0]}</b> επισκέψεις · {s['t'][1]} προβολές\n"
                     f"7 μέρες: <b>{s['w'][0]}</b> επισκέψεις{_pct(s['w'][0], s['pw'][0])} · {s['w'][1]} προβολές")
    if host and host in per:
        def top(key: str, dim: str, blank: str) -> str:
            rows = [(g["dimensions"][dim] or blank, g["sum"]["visits"]) for g in data.get(key) or []]
            return " · ".join(f"{escape(str(k))} {v}" for k, v in rows if v) or "–"
        lines.append(f"\n<b>HoopsLab χθες</b>\nΧώρες: {top('countries', 'countryName', '?')}\n"
                     f"Συσκευές: {top('devices', 'deviceType', '?')}\n"
                     f"Από: {top('referers', 'refererHost', 'απευθείας')}")
    return "\n".join(lines)


def main() -> None:
    day = datetime.now(ZoneInfo(TIMEZONE)).date() - timedelta(days=1)
    try:
        text = message(fetch(day), day)
    except Exception as e:  # noqa: BLE001 - tell the owner instead of failing silently
        text = f"📈 Analytics: δεν διαβάστηκαν — {escape(str(e))}"
    notify.send(text)


if __name__ == "__main__":
    main()
