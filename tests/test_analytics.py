"""Daily Web Analytics report: parsing Cloudflare's GraphQL answer into the Telegram message."""
from datetime import date

import pytest

from elf import analytics

DAY = date(2026, 10, 1)


def grp(d, host, visits, views):
    return {"count": views, "sum": {"visits": visits}, "dimensions": {"date": d, "requestHost": host}}


DATA = {
    "host": "hoopslab-beta.pages.dev",
    "days": [grp("2026-10-01", "hoopslab-beta.pages.dev", 120, 300),
             grp("2026-09-28", "hoopslab-beta.pages.dev", 80, 150),
             grp("2026-09-20", "hoopslab-beta.pages.dev", 100, 200),     # the week before
             grp("2026-10-01", "elf-dashboard.pages.dev", 3, 9),
             grp("2026-10-02", "hoopslab-beta.pages.dev", 4, 6)],                # today so far
    "countries": [{"sum": {"visits": 100}, "dimensions": {"countryName": "GR"}},
                  {"sum": {"visits": 20}, "dimensions": {"countryName": "CY"}}],
    "devices": [{"sum": {"visits": 90}, "dimensions": {"deviceType": "mobile"}}],
    "referers": [{"sum": {"visits": 70}, "dimensions": {"refererHost": ""}},
                 {"sum": {"visits": 50}, "dimensions": {"refererHost": "instagram.com"}}],
}


def test_message_per_site_week_trend_and_sources():
    text = analytics.message(DATA, DAY)
    assert text.index("HoopsLab") < text.index("elf-dashboard")          # the product first
    assert "χθες: <b>120</b> επισκέψεις · 300 προβολές" in text
    assert "σήμερα ως τώρα: <b>4</b> επισκέψεις" in text
    assert "7 μέρες: <b>200</b> επισκέψεις (▲100%)" in text               # 200 vs 100 the week before
    assert "GR 100 · CY 20" in text and "mobile 90" in text
    assert "απευθείας 70 · instagram.com 50" in text


def test_message_without_data():
    assert "Καμία επίσκεψη" in analytics.message({"host": "", "days": []}, DAY)


def test_main_reports_errors_to_the_owner(monkeypatch):
    sent = []
    monkeypatch.setattr(analytics.notify, "send", lambda text, buttons=None: sent.append(text))
    monkeypatch.delenv("CF_ANALYTICS_TOKEN", raising=False)
    monkeypatch.delenv("CLOUDFLARE_API_TOKEN", raising=False)
    analytics.main()
    assert sent and "δεν διαβάστηκαν" in sent[0] and "CF_ANALYTICS_TOKEN" in sent[0]


def test_fetch_sends_query_and_raises_on_graphql_error(monkeypatch):
    calls = []

    class R:
        status_code = 200
        headers = {"content-type": "application/json"}
        text = ""

        def __init__(self, body):
            self.body = body

        def json(self):
            return self.body

    monkeypatch.setenv("CF_ANALYTICS_TOKEN", "t")
    monkeypatch.setenv("CLOUDFLARE_ACCOUNT_ID", "acc")
    monkeypatch.setenv("PUBLIC_URL", "https://hoopslab-beta.pages.dev")
    monkeypatch.setattr(analytics.requests, "post", lambda url, **kw: calls.append(kw) or R(
        {"data": {"viewer": {"accounts": [{"days": []}]}}}))
    out = analytics.fetch(DAY)
    assert out["host"] == "hoopslab-beta.pages.dev"
    assert calls[0]["variables" if "variables" in calls[0] else "json"]["variables"]["since"] == "2026-09-18" and calls[0]["json"]["variables"]["until"] == "2026-10-02"
    monkeypatch.setattr(analytics.requests, "post", lambda url, **kw: R({"errors": [{"message": "not authorized"}]}))
    with pytest.raises(RuntimeError, match="not authorized"):
        analytics.fetch(DAY)
