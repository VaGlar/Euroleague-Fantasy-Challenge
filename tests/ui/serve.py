"""Static server for the UI tests: both editions built from the frozen fixtures.

/personal/  web/ + tests/ui/fixtures (as the personal dashboard deploys data/public)
/public/    python -m elf.publish on the same fixtures (the HoopsLab edition)
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


def build() -> Path:
    out = Path(tempfile.mkdtemp(prefix="elf-ui-"))
    shutil.copytree(ROOT / "web", out / "personal")
    shutil.copytree(FIX, out / "personal" / "data")
    publish.site(out / "public", src=FIX)
    return out


class Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *a):
        pass


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8799
    root = build()
    http.server.ThreadingHTTPServer(("127.0.0.1", port), functools.partial(Quiet, directory=str(root))).serve_forever()
