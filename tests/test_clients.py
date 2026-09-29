"""The clients of external services, against fake responses: news feeds and Gemini
(elf/news.py), the EuroLeague API (elf/el_api.py) and its cache (elf/history.py), the
Dunkest API (elf/fantasy.py) and Telegram (elf/notify.py)."""
import json
from datetime import datetime, timedelta, timezone

import pandas as pd
import pytest
import requests

from elf import el_api, fantasy, history, news, notify


class Resp:
    def __init__(self, status=200, body=None, content=None, url="u"):
        self.status_code, self._body, self.url = status, body, url
        self.content = content if content is not None else json.dumps(body).encode()
        self.text = self.content.decode(errors="replace")

    def json(self):
        if self._body is None:
            raise ValueError("no json")
        return self._body

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code}")


def rfc822(dt):
    return dt.strftime("%a, %d %b %Y %H:%M:%S +0000")


NOW = datetime.now(timezone.utc)


def rss(*items):
    body = "".join(
        f"<item><title>{t}</title><link>{link}</link><pubDate>{rfc822(d)}</pubDate>"
        f"<description>{desc}</description></item>" for t, link, d, desc in items)
    return f'<?xml version="1.0"?><rss><channel>{body}</channel></rss>'.encode()


# ======================================================================= news feeds

def test_date_parsing_formats():
    assert news._date("Tue, 29 Sep 2026 10:00:00 +0000") == datetime(2026, 9, 29, 10,
                                                                     tzinfo=timezone.utc)
    assert news._date("2026-09-29T10:00:00Z").tzinfo is not None
    assert news._date("2026-09-29T10:00:00").tzinfo == timezone.utc   # naive -> UTC
    assert news._date("yesterday") is None and news._date(None) is None


def test_clean_strips_tags_entities_and_limits():
    assert news._clean("<p>A&amp;B&nbsp;<b>c</b></p>\n\n d") == "A&B c d"
    assert news._clean("x" * 1000, 10) == "x" * 10
    assert news._clean(None) == ""


def test_fetch_rss_reads_items_and_full_text_for_fantasy_columns(monkeypatch):
    long = "word " * 400
    content = (b'<?xml version="1.0"?><rss xmlns:content="http://purl.org/rss/1.0/modules/content/">'
               b"<channel><item><title>T</title><link>https://x/1</link>"
               b"<pubDate>Tue, 29 Sep 2026 10:00:00 +0000</pubDate><description>short</description>"
               b"<content:encoded><![CDATA[<p>" + long.encode() + b"</p>]]></content:encoded>"
               b"</item></channel></rss>")
    monkeypatch.setattr(news.requests, "get", lambda *a, **k: Resp(content=content))
    (it,) = news.fetch_rss({"url": "https://f/rss", "fantasy": True})
    assert it["title"] == "T" and it["url"] == "https://x/1" and len(it["text"]) > 1000
    (it,) = news.fetch_rss({"url": "https://f/rss"})
    assert len(it["text"]) <= news.EXCERPT


def test_fetch_rss_reads_atom_feeds(monkeypatch):
    atom = (b'<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom"><entry>'
            b'<title>Atom T</title><link href="https://x/a"/><updated>2026-09-29T10:00:00Z'
            b"</updated><summary>s</summary></entry></feed>")
    monkeypatch.setattr(news.requests, "get", lambda *a, **k: Resp(content=atom))
    assert len(news.fetch_rss({"url": "https://f/atom"})) == 1


def test_substack_blocked_goes_through_the_proxy(monkeypatch):
    monkeypatch.setenv("DASHBOARD_URL", "https://dash.example/")
    calls = []

    def get(url, params=None, **k):
        calls.append((url, params))
        if url == "https://dash.example/feed":
            return Resp(content=rss(("T", "https://s/1", NOW, "d")))
        return Resp(403, content=b"blocked")
    monkeypatch.setattr(news.requests, "get", get)
    (it,) = news.fetch_rss({"url": "https://abc.substack.com/feed"})
    assert it["url"] == "https://s/1"
    assert calls[1] == ("https://dash.example/feed", {"u": "https://abc.substack.com/feed"})


def test_the_proxy_behind_cloudflare_access_gets_the_service_token(monkeypatch):
    """The personal site is behind Cloudflare Access: the pipeline shows its service token to the
    /feed proxy and doesn't follow a redirect to the login page (read as a failed proxy instead)."""
    monkeypatch.setenv("DASHBOARD_URL", "https://dash.example")
    monkeypatch.setenv("CF_ACCESS_CLIENT_ID", "id.access")
    monkeypatch.setenv("CF_ACCESS_CLIENT_SECRET", "sec")
    seen = {}

    def get(url, params=None, headers=None, allow_redirects=True, **k):
        if url == "https://dash.example/feed":
            seen.update(headers or {}, redirects=allow_redirects)
            if (headers or {}).get("CF-Access-Client-Id") != "id.access":
                return Resp(302, content=b"")
            return Resp(content=rss(("T", "https://s/1", NOW, "d")))
        return Resp(403, content=b"blocked")
    monkeypatch.setattr(news.requests, "get", get)
    (it,) = news.fetch_rss({"url": "https://abc.substack.com/feed"})
    assert it["url"] == "https://s/1"
    assert seen["CF-Access-Client-Secret"] == "sec" and seen["redirects"] is False
    monkeypatch.delenv("CF_ACCESS_CLIENT_ID")                 # no token: no Access headers at all
    assert news.access_headers() == {}


def test_substack_proxy_html_error_page_falls_back_to_the_json_api(monkeypatch):
    monkeypatch.setenv("DASHBOARD_URL", "https://dash.example")

    def get(url, params=None, **k):
        if url.endswith("/api/v1/posts"):
            return Resp(body=[{"title": "API T", "canonical_url": "https://s/2",
                               "post_date": "2026-09-29T10:00:00Z", "body_html": "<p>b</p>"}])
        if "dash.example" in url:
            return Resp(200, content=b"   Cloudflare error")     # not XML: must not be parsed
        return Resp(403, content=b"")
    monkeypatch.setattr(news.requests, "get", get)
    (it,) = news.fetch_rss({"url": "https://abc.substack.com/feed"})
    assert (it["title"], it["url"], it["text"]) == ("API T", "https://s/2", "b")


def test_non_substack_failure_raises_without_proxy(monkeypatch):
    monkeypatch.setenv("DASHBOARD_URL", "https://dash.example")
    urls = []
    monkeypatch.setattr(news.requests, "get",
                        lambda url, **k: urls.append(url) or Resp(500, content=b""))
    with pytest.raises(requests.HTTPError):
        news.fetch_rss({"url": "https://site.gr/rss"})
    assert urls == ["https://site.gr/rss"], "το proxy είναι μόνο για τα sites που μας μπλοκάρουν"


def test_incrowd_category_filter_and_fantasy_body(monkeypatch):
    arts = [
        {"slug": "tips-r3", "publishDate": "2026-09-29T10:00:00Z",
         "categories": [{"text": "Fantasy Challenge"}], "heroMedia": {"title": "Tips R3"},
         "content": [{"contentType": "TEXT", "content": "Pick [Nunn](https://x) now"},
                     {"contentType": "IMAGE", "content": "img"}, "junk"]},
        {"slug": "other", "publishDate": "2026-09-29T10:00:00Z", "categories": [],
         "heroMedia": {"title": "Other"}},
    ]
    seen = {}

    def get(url, params=None, **k):
        seen.update(params)
        return Resp(body={"data": {"articles": arts}})
    monkeypatch.setattr(news.requests, "get", get)
    (it,) = news.fetch_incrowd({"category": "news", "category_text": "Fantasy Challenge",
                                "fantasy": True})
    assert it["title"] == "Tips R3" and it["text"] == "Pick [Nunn] now"
    assert it["url"].endswith("/news/tips-r3/") and seen["size"] == 100
    assert len(news.fetch_incrowd({"category": "news"})) == 2


def write_sources(tmp_path, monkeypatch, sources):
    import yaml
    (tmp_path / "sources.yaml").write_text(yaml.safe_dump({"sources": sources}))
    monkeypatch.setattr(news, "ROOT", tmp_path)


def test_collect_filters_dedups_orders_and_survives_dead_sources(tmp_path, monkeypatch):
    write_sources(tmp_path, monkeypatch, [
        {"name": "General", "type": "rss", "url": "https://gen/rss", "filter": True},
        {"name": "Dead", "type": "rss", "url": "https://dead/rss"},
        {"name": "Tips", "type": "rss", "url": "https://tips/rss", "fantasy": True,
         "title_has": "Round", "hours": 200, "weight": 2},
    ])
    old = NOW - timedelta(hours=150)
    feeds = {
        "https://gen/rss": rss(("Football derby", "https://g/1", NOW, "goal"),
                               ("Ολυμπιακός νίκη", "https://g/2", NOW, "x"),
                               ("Mike James scores", "https://g/3", NOW, "x"),
                               ("Old Euroleague", "https://g/4", old, "x"),
                               ("Euroleague dup", "https://t/1", NOW, "x")),
        "https://tips/rss": rss(("Round 3 tips", "https://t/1", old, "picks"),
                                ("Podcast", "https://t/2", NOW, "x")),
    }

    def get(url, **k):
        if url in feeds:
            return Resp(content=feeds[url])
        return Resp(500, content=b"")
    monkeypatch.setattr(news.requests, "get", get)
    out, failed = news.collect(["James, Mike", "Nunn, Kendrick"])
    urls = [a["url"] for a in out]
    assert urls[0] == "https://t/1" and out[0]["fantasy"] and out[0]["weight"] == 2, \
        "οι στήλες fantasy πρώτες και κρατάνε το άρθρο πριν το γενικό feed"
    assert out[0]["source"] == "Tips"
    assert set(urls) == {"https://t/1", "https://g/2", "https://g/3"}
    assert "https://t/2" not in urls, "title_has"
    assert "https://g/1" not in urls, "filter: χωρίς ομάδα/παίκτη EuroLeague"
    assert "https://g/4" not in urls, "παλιότερο από 96 ώρες"
    assert len(failed) == 1 and failed[0].startswith("Dead: HTTPError")
    json.dumps(out)                                    # dates are serialisable strings


def test_collect_survives_malformed_xml(tmp_path, monkeypatch):
    write_sources(tmp_path, monkeypatch, [{"name": "Bad", "type": "rss", "url": "https://b"}])
    monkeypatch.setattr(news.requests, "get", lambda *a, **k: Resp(content=b"<html><body>"))
    out, failed = news.collect([])
    assert out == [] and failed[0].startswith("Bad: ParseError")


# ============================================================================ Gemini

def gemini_ok(payload):
    return Resp(body={"candidates": [{"content": {"parts": [{"text": json.dumps(payload)}]}}]})


ARTS = [{"title": "Round 3 tips", "text": "pick X", "date": NOW.isoformat(), "source": "Tips",
         "fantasy": True},
        {"title": "News", "text": "Y out", "date": None, "source": "EL", "fantasy": False}]


@pytest.fixture
def gemini(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "KEY123")
    monkeypatch.delenv("GEMINI_MODEL", raising=False)
    monkeypatch.setattr(news.time, "sleep", lambda s: None)
    monkeypatch.setattr(news, "_flash_models", lambda base, h: ["m1", "m2", "m3"])
    posts = []

    def install(*replies):
        replies = list(replies)

        def post(url, headers=None, json=None, timeout=None):
            posts.append((url, headers, json))
            return replies.pop(0)
        monkeypatch.setattr(news.requests, "post", post)
        return posts
    return install


def test_digest_needs_key_and_articles(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    assert news.digest(ARTS, ["X (PAN)"]) is None
    monkeypatch.setenv("GEMINI_API_KEY", "k")
    assert news.digest([], ["X (PAN)"]) is None


def test_digest_key_in_header_never_in_url_and_output_normalized(gemini):
    posts = gemini(gemini_ok({"summary_el": ["α"], "availability": [{"player": "Y",
                                                                       "status": "out"}]}))
    d = news.digest(ARTS, ["X (PAN)", "Y (OLY)"])
    url, headers, body = posts[0]
    assert "KEY123" not in url and headers["x-goog-api-key"] == "KEY123"
    prompt = body["contents"][0]["parts"][0]["text"]
    assert "[FANTASY | Tips" in prompt and "[NEWS | EL" in prompt and "Y (OLY)" in prompt
    assert d["_model"] == "m1" and d["summary_el"] == "• α" and d["expert"] == []


def test_digest_moves_to_next_model_on_404_and_429(gemini):
    posts = gemini(Resp(404, body={"error": {"message": "nope"}}),
                   Resp(429, body={"error": {"message": "quota"}}), gemini_ok({}))
    assert news.digest(ARTS, [])["_model"] == "m3"
    assert [p[0].rsplit("/", 1)[1] for p in posts] == ["m1:generateContent",
                                                       "m2:generateContent",
                                                       "m3:generateContent"]


def test_digest_retries_503_on_the_same_model(gemini):
    posts = gemini(Resp(503, body={}), Resp(503, body={}), gemini_ok({}))
    assert news.digest(ARTS, [])["_model"] == "m1" and len(posts) == 3


def test_digest_all_overloaded_says_so(gemini):
    gemini(*[Resp(503, body={}) for _ in range(9)])
    with pytest.raises(RuntimeError, match="υπερφορτωμένο"):
        news.digest(ARTS, [])


def test_digest_bad_key_stops_immediately(gemini):
    posts = gemini(Resp(400, body={"error": {"message": "API key not valid"}}))
    with pytest.raises(RuntimeError, match="API key not valid"):
        news.digest(ARTS, [])
    assert len(posts) == 1


def test_digest_no_models_available(gemini, monkeypatch):
    monkeypatch.setattr(news, "_flash_models", lambda base, h: [])
    gemini()
    with pytest.raises(RuntimeError, match="δεν βρέθηκε"):
        news.digest(ARTS, [])


def test_digest_pinned_model_falls_back_to_listed_ones(gemini, monkeypatch):
    monkeypatch.setenv("GEMINI_MODEL", "pinned")
    posts = gemini(Resp(404, body={}), gemini_ok({}))
    assert news.digest(ARTS, [])["_model"] == "m1"
    assert "pinned:generateContent" in posts[0][0]


def test_digest_caps_fantasy_articles_per_source_and_prefers_tips(gemini):
    many = [{"title": f"Column {i}", "text": "t", "date": (NOW - timedelta(hours=i)).isoformat(),
             "source": "Tips", "fantasy": True} for i in range(6)]
    many.append({"title": "Round 3 tips", "text": "t", "date": (NOW - timedelta(days=5)).isoformat(),
                 "source": "Tips", "fantasy": True})
    posts = gemini(gemini_ok({}))
    news.digest(many, [])
    prompt = posts[0][2]["contents"][0]["parts"][0]["text"]
    assert prompt.count("[FANTASY | Tips") == 4
    assert prompt.index("Round 3 tips") < prompt.index("Column 0"), "πρώτα τα round tips"


# ===================================================================== EuroLeague API

class FakeSession:
    def __init__(self, replies):
        self.replies, self.calls = list(replies), []

    def get(self, url, params=None, timeout=None):
        self.calls.append((url, params))
        r = self.replies.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


@pytest.fixture
def el(monkeypatch):
    monkeypatch.setattr(el_api.time, "sleep", lambda s: None)

    def install(*replies):
        s = FakeSession(replies)
        monkeypatch.setattr(el_api, "_session", s)
        return s
    return install


def test_get_retries_transient_errors_then_succeeds(el):
    s = el(Resp(503), requests.ConnectionError("x"), Resp(200, body={"ok": 1}))
    assert el_api._get("u") == {"ok": 1} and len(s.calls) == 3


def test_get_gives_up_after_retries(el):
    el(*[Resp(502) for _ in range(4)])
    with pytest.raises(requests.HTTPError):
        el_api._get("u")


def test_get_retries_invalid_json(el):
    el(Resp(200, content=b"<html>"), Resp(200, body=[1]))
    assert el_api._get("u") == [1]


def test_paged_walks_offsets_until_total(el):
    s = el(Resp(body={"data": [1, 2], "total": 5}), Resp(body={"data": [3, 4], "total": 5}),
           Resp(body={"data": [5], "total": 5}))
    assert el_api._paged("u", limit=2) == [1, 2, 3, 4, 5]
    assert [c[1]["offset"] for c in s.calls] == [0, 2, 4]


def test_paged_stops_on_empty_page(el):
    el(Resp(body={"data": [1], "total": 99}), Resp(body={"data": [], "total": 99}))
    assert el_api._paged("u") == [1]


@pytest.mark.parametrize("m,out", [("25:30", 25.5), ("DNP", 0.0), (None, 0.0), ("", 0.0),
                                   ("0:45", 0.75)])
def test_minutes(m, out):
    assert el_api._minutes(m) == out


def box_player(pid, team, mins, pir, starter="1"):
    keys = ["Points", "FieldGoalsMade2", "FieldGoalsAttempted2", "FieldGoalsMade3",
            "FieldGoalsAttempted3", "FreeThrowsMade", "FreeThrowsAttempted",
            "OffensiveRebounds", "DefensiveRebounds", "Assistances", "Steals", "Turnovers",
            "BlocksFavour", "BlocksAgainst", "FoulsCommited", "FoulsReceived"]
    return {"Player_ID": f"P{pid}  ", "Player": "DOE,   JOHN", "Team": f"{team} ",
            "IsStarter": starter, "Minutes": mins, "Valuation": pir, **{k: 1 for k in keys}}


def box_total():
    return {"Points": 80, "FieldGoalsAttempted2": 40, "FieldGoalsAttempted3": 25,
            "FreeThrowsAttempted": 20, "OffensiveRebounds": 10, "Turnovers": 12, "Valuation": 90}


def test_boxscore_parsing(el):
    el(Resp(body={"Stats": [
        {"PlayersStats": [box_player("001", "PAN", "30:00", 20),
                          box_player("002", "PAN", "DNP", 0, starter=None)], "totr": box_total()},
        {"PlayersStats": [box_player("003", "OLY", "12:30", 5)], "totr": box_total()}]}))
    b = el_api.boxscore(2026, 7)
    p = b["players"]
    assert [x["person_id"] for x in p] == ["001", "002", "003"]
    assert p[0]["player"] == "DOE, JOHN" and p[0]["team"] == "PAN" and p[0]["is_home"]
    assert p[1]["min"] == 0.0 and p[1]["starter"] == 0 and p[2]["min"] == 12.5
    assert [(t["team"], t["is_home"], t["fga"]) for t in b["teams"]] == [("PAN", True, 65),
                                                                        ("OLY", False, 65)]


def test_people_keeps_players_and_head_coaches_only(el):
    rows = [{"type": t, "person": {"code": f" {i} ", "name": "N"}, "club": {"code": "PAN"},
             "positionName": "Guard"} for i, t in enumerate(["J", "E", "A", "J"])]
    el(Resp(body={"data": rows, "total": 4}))
    out = el_api.people(2026)
    assert [(p["person_id"], p["type"]) for p in out] == [("0", "player"), ("1", "coach"),
                                                          ("3", "player")]


# ======================================================================= history cache

def test_update_season_fetches_only_missing_games_and_retries_failures(tmp_path, monkeypatch):
    monkeypatch.setattr(history, "HISTORY", tmp_path)
    games = [{"gamecode": gc, "played": gc <= 3, "round": 1} for gc in (1, 2, 3, 4)]
    monkeypatch.setattr(el_api, "games", lambda s: games)
    monkeypatch.setattr(el_api, "people", lambda s: [{"person_id": "007", "name": "N"}])
    asked, broken = [], {3}

    def box(season, gc):
        asked.append(gc)
        if gc in broken:
            raise requests.HTTPError("500")
        return {"players": [{"gamecode": gc, "team": "A", "person_id": "007", "pir": gc}],
                "teams": [{"gamecode": gc, "team": t, "is_home": t == "A"} for t in "AB"]}
    monkeypatch.setattr(el_api, "boxscore", box)

    history.update_season(2026)
    assert sorted(asked) == [1, 2, 3], "όχι το game 4 (δεν έχει παιχτεί)"
    assert sorted(history.load("teams", 2026)["gamecode"].unique()) == [1, 2]

    asked.clear()
    broken.clear()
    history.update_season(2026, refresh_people=False)
    assert asked == [3], "μόνο όσα έλειπαν / απέτυχαν"
    players = history.load("players", 2026)
    assert sorted(players["gamecode"]) == [1, 2, 3]
    assert players["person_id"].tolist() == ["007"] * 3, "τα id μένουν strings (μηδενικά μπροστά)"

    asked.clear()
    history.update_season(2026)
    assert asked == []


def test_load_missing_file_is_empty(tmp_path, monkeypatch):
    monkeypatch.setattr(history, "HISTORY", tmp_path)
    assert history.load("games", 1999).empty


# ======================================================================== Dunkest API

@pytest.fixture
def dunkest(monkeypatch):
    calls = []

    def install(*replies, method="get"):
        replies = list(replies)

        def fn(url, params=None, headers=None, json=None, timeout=None):
            calls.append({"method": method, "url": url, "params": params, "headers": headers,
                          "json": json})
            return replies.pop(0)
        monkeypatch.setattr(fantasy.requests, method, fn)
        return calls
    return install


@pytest.mark.parametrize("status", [401, 403])
def test_rejected_token_is_a_token_error(monkeypatch, dunkest, status):
    monkeypatch.setenv("FANTASY_TOKEN", "tok")
    dunkest(Resp(status, body={}))
    with pytest.raises(fantasy.TokenError):
        fantasy.get("/user/fantasy-teams")


def test_get_unwraps_data_and_sends_bearer(monkeypatch, dunkest):
    monkeypatch.setenv("FANTASY_TOKEN", " tok ")
    calls = dunkest(Resp(body={"data": [1, 2]}), Resp(body=[3]))
    assert fantasy.get("/x") == [1, 2] and fantasy.get("/y", auth=False) == [3]
    assert calls[0]["headers"]["Authorization"] == "Bearer tok"
    assert "Authorization" not in calls[1]["headers"]


def test_players_pages_until_a_short_page(monkeypatch, dunkest):
    monkeypatch.setenv("FANTASY_TOKEN", "tok")
    calls = dunkest(Resp(body={"data": list(range(200))}), Resp(body={"data": {"players": [1]}}))
    assert len(fantasy.players(9, 500)) == 201
    assert [c["params"]["page"] for c in calls] == [1, 2]


def test_save_roster_posts_then_falls_back_to_put(monkeypatch, dunkest):
    monkeypatch.setenv("FANTASY_TOKEN", "tok")
    posts = dunkest(Resp(405, body={}), method="post")
    puts = dunkest(Resp(200, body={}), method="put")
    r = fantasy.save_roster(1, 500, {"players": []})
    assert r.status_code == 200
    assert [c["method"] for c in posts] == ["post", "put"] and puts is posts
    assert posts[0]["url"].endswith("/fantasy-teams/1/matchdays/500/roster")


def test_save_roster_without_token_never_calls(monkeypatch):
    monkeypatch.delenv("FANTASY_TOKEN", raising=False)
    monkeypatch.setenv("FANTASY_DATA_TOKEN", "data-only")
    with pytest.raises(fantasy.TokenError):
        fantasy.save_roster(1, 500, {})          # the data account must never write


@pytest.mark.parametrize("payload", [b"[1]", b'{"exp": "soon"}'])
def test_token_expiry_never_crashes_on_odd_jwt_payloads(monkeypatch, payload):
    import base64
    body = base64.urlsafe_b64encode(payload).decode().rstrip("=")
    monkeypatch.setenv("FANTASY_TOKEN", f"h.{body}.s")
    assert fantasy.token_expiry()["days_left"] is None


# ========================================================================== Telegram

def test_send_without_secrets_prints_instead(monkeypatch, capsys):
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    assert notify.send("hello") is True
    assert "hello" in capsys.readouterr().out


def test_send_posts_html_and_buttons_on_the_last_chunk(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "bt")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "42")
    sent = []
    monkeypatch.setattr(notify.requests, "post",
                        lambda url, json=None, timeout=None: sent.append((url, json)) or Resp())
    notify.send("\n".join("y" * 100 for _ in range(80)), [notify.LINEUP_BUTTON])
    assert len(sent) == 3 and all(u == "https://api.telegram.org/botbt/sendMessage"
                                  for u, _ in sent)
    assert [("reply_markup" in b) for _, b in sent] == [False, False, True]
    assert all(b["parse_mode"] == "HTML" and b["chat_id"] == "42" for _, b in sent)


def test_send_raises_on_telegram_error(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "bt")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "42")
    monkeypatch.setattr(notify.requests, "post", lambda *a, **k: Resp(400, body={"d": "bad"}))
    with pytest.raises(RuntimeError, match="Telegram 400"):
        notify.send("x")


def test_chunks_split_a_single_overlong_line():
    parts = notify.chunks("a\n" + "x" * 5000 + "\nb")
    assert all(len(p) <= 4096 for p in parts)


def test_health_alert_escapes_error_text(public, monkeypatch):
    (public / "predictions.json").write_text(json.dumps({"health": ["πηγή: <html> & co"]}))
    sent = []
    monkeypatch.setattr(notify, "send", lambda text, buttons=None: sent.append(text))
    notify.health()
    assert "&lt;html&gt; &amp; co" in sent[0] and "<b>Προβλήματα" in sent[0]


def test_chunks_cut_long_lines_at_spaces_and_keep_every_word():
    words = [f"w{i}" for i in range(2000)]
    parts = notify.chunks("start\n" + " ".join(words) + "\nend")
    assert all(len(p) <= 3800 for p in parts) and len(parts) >= 3
    assert " ".join(parts).split() == ["start"] + words + ["end"]


def test_health_alert_is_retried_if_telegram_failed(public, monkeypatch):
    (public / "predictions.json").write_text(json.dumps({"health": ["Gemini: down"]}))

    def fail(text, buttons=None):
        raise RuntimeError("Telegram 502")
    monkeypatch.setattr(notify, "send", fail)
    with pytest.raises(RuntimeError):
        notify.health()
    sent = []
    monkeypatch.setattr(notify, "send", lambda text, buttons=None: sent.append(text))
    notify.health()
    assert sent and "Gemini: down" in sent[0]


PAGE = """<html><head><meta property="og:title" content="EuroLeague Injury Report (updated daily)"/>
<script type="application/ld+json">{"@type":"NewsArticle","dateModified":"2026-09-29T18:46:34+0300"}</script>
<script>var ads = "Out | Nobody";</script></head><body><nav>Menu | Out of stock</nav>
<div class="injury_reports mt-6"><table><tr><td>Zalgiris Kaunas</td><td>PG</td><td>Nigel Williams-Goss</td>
<td>Out</td><td>Rounds 2-4</td><td>Hamstring</td></tr></table></div>
<p>This comprehensive EuroLeague injury report ... related news, ads</p></body></html>"""


def test_a_page_updated_in_place_is_read_whole_from_start_to_end(monkeypatch):
    """An injury report «updated daily» at one URL: one item, only the table (no menus, scripts or
    the text after it), dated by its last modification."""
    monkeypatch.setattr(news.requests, "get", lambda url, **k: Resp(content=PAGE.encode()))
    (it,) = news.fetch_page({"name": "BN", "url": "https://bn/x", "start": "injury_reports",
                             "end": "This comprehensive EuroLeague injury report"})
    assert it["title"] == "EuroLeague Injury Report (updated daily)" and it["url"] == "https://bn/x"
    assert "Nigel Williams-Goss | Out | Rounds 2-4" in it["text"]
    assert "Menu" not in it["text"] and "Nobody" not in it["text"] and "related news" not in it["text"]
    assert it["date"] == datetime(2026, 9, 29, 15, 46, 34, tzinfo=timezone.utc)


def test_basketnews_blocked_goes_through_the_proxy(monkeypatch):
    """BasketNews answers 403 to GitHub Actions' IPs: the page comes through our /feed proxy."""
    monkeypatch.setenv("DASHBOARD_URL", "https://dash.example")
    calls = []

    def get(url, params=None, **k):
        calls.append((url, params))
        if url == "https://dash.example/feed":
            return Resp(content=PAGE.encode())
        return Resp(403, content=b"blocked")
    monkeypatch.setattr(news.requests, "get", get)
    url = "https://basketnews.com/news-212393-euroleague-injury-report-updated.html"
    (it,) = news.fetch_page({"name": "BN", "url": url, "start": "injury_reports"})
    assert "Nigel Williams-Goss | Out" in it["text"]
    assert calls[1] == ("https://dash.example/feed", {"u": url})


def test_the_injury_report_reaches_the_summary_whole(gemini):
    """News go in as a 500-character excerpt; an injury report goes in whole, marked as such."""
    table = "Zalgiris Kaunas | PG | Nigel Williams-Goss | Out | Rounds 2-4 | " * 60      # ~3.9k chars
    posts = gemini(gemini_ok({"summary_el": ["α"]}))
    news.digest(ARTS + [{"title": "Injury Report", "url": "https://bn/x", "date": NOW.isoformat(),
                         "text": table, "source": "BN", "fantasy": False, "report": True}], ["X (PAN)"])
    prompt = posts[0][2]["contents"][0]["parts"][0]["text"]
    assert "[INJURY REPORT | BN" in prompt and table in prompt
    assert "Out -> \"out\"" in prompt                                  # the mapping of its statuses


def test_a_redesigned_page_fails_as_a_source_instead_of_feeding_menus_to_the_summary(
        tmp_path, monkeypatch):
    """Without its start marker the page is a failed source (the owner sees it in health), not a
    «trusted injury report» made of menus, ads and related news."""
    redesigned = PAGE.replace("injury_reports", "something_else")
    monkeypatch.setattr(news.requests, "get", lambda url, **k: Resp(content=redesigned.encode()))
    with pytest.raises(ValueError, match="injury_reports"):
        news.fetch_page({"name": "BN", "url": "https://bn/x", "start": "injury_reports"})
    write_sources(tmp_path, monkeypatch, [{"name": "BN report", "type": "page", "url": "https://bn/x",
                                           "start": "injury_reports", "report": True}])
    out, failed = news.collect([])
    assert out == [] and failed and failed[0].startswith("BN report: ValueError")
