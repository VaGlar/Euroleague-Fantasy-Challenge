"""Static server for the UI tests: both editions built from the frozen fixtures.

/personal/  web/ + tests/ui/fixtures (as the personal dashboard deploys data/public)
/public/    python -m elf.publish on the same fixtures (the HoopsLab edition)

Every response carries the headers of web/_headers (as Cloudflare Pages sends them), so a security
rule that breaks the page shows up as a console error and fails the tests.
"""
import functools
import http.server
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from elf import publish  # noqa: E402

FIX = Path(__file__).resolve().parent / "fixtures"


def site_headers(path: Path = ROOT / "web" / "_headers") -> list[tuple[str, str]]:
    """The «/*» rules of a Cloudflare Pages _headers file."""
    out, on = [], False
    for line in path.read_text().splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if not line[0].isspace():
            on = line.strip() == "/*"
        elif on and ":" in line:
            name, value = line.strip().split(":", 1)
            out.append((name.strip(), value.strip()))
    return out


HEADERS = site_headers()


def build() -> Path:
    out = Path(tempfile.mkdtemp(prefix="elf-ui-"))
    shutil.copytree(ROOT / "web", out / "personal")
    shutil.copytree(FIX, out / "personal" / "data")
    publish.site(out / "public", src=FIX)
    return out


class Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def end_headers(self):
        for name, value in HEADERS:
            self.send_header(name, value)
        super().end_headers()


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8799
    root = build()
    http.server.ThreadingHTTPServer(("127.0.0.1", port), functools.partial(Quiet, directory=str(root))).serve_forever()
