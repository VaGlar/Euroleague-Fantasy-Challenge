"""functions/feed.js: the pipeline's proxy for Substack / BasketNews feeds. It is deployed on both sites, the
public one without Cloudflare Access, so anyone can call it. Runs in node with a stand-in for fetch."""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

node = shutil.which("node")
pytestmark = pytest.mark.skipif(not node, reason="node not installed")
RUNNER = Path(__file__).with_name("feed_fn_runner.mjs")


def run(*cases):
    out = subprocess.run([node, str(RUNNER)], input=json.dumps(list(cases)), capture_output=True, text=True, check=True)
    return json.loads(out.stdout)


def test_only_https_on_the_allowed_hosts():
    ok, sub, other, http, lookalike, bad, none = run(
        {"u": "https://www.basketnews.com/rss"}, {"u": "https://x.substack.com/feed"},
        {"u": "https://example.com/feed"}, {"u": "http://x.substack.com/feed"},
        {"u": "https://substack.com.evil.example/feed"}, {"u": "not a url"}, {"u": None})
    assert ok["status"] == 200 and sub["status"] == 200 and ok["asked"] == ["https://www.basketnews.com/rss"]
    assert [r["status"] for r in (other, http, lookalike)] == [403, 403, 403] and not other["asked"]
    assert bad["status"] == 400 and none["status"] == 400


# Workers' fetch follows redirects (a Substack with a custom domain redirects there), so the host is checked
# again where it ended; the answer is always text/plain with nosniff and «content-security-policy: sandbox»,
# so a page from outside the list can't run its script on the site (tester 15/10).
def test_a_redirect_off_the_list_is_refused():
    r, = run({"u": "https://x.substack.com/p/post", "upstream": {"url": "https://attacker.example/p/post",
                                                                  "type": "text/html", "body": "<script>x</script>"}})
    assert r["status"] == 403


def test_the_answer_is_never_a_page_of_our_site():
    r, = run({"u": "https://x.substack.com/p/post", "upstream": {"type": "text/html", "body": "<html>…</html>"}})
    assert not r["type"].startswith("text/html")
    assert r["nosniff"] == "nosniff" and "sandbox" in (r["csp"] or "")
