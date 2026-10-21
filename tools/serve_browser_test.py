"""Serve only the synthetic browser harness and public frontend assets."""

from http.server import BaseHTTPRequestHandler, HTTPServer
import mimetypes
from pathlib import Path
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "custom_components/tv_voice_bridge/frontend"


class Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        path = unquote(urlsplit(self.path).path)
        if path == "/":
            file = ROOT / "tests/browser/index.html"
        elif path.startswith("/frontend/"):
            file = (FRONTEND / path.removeprefix("/frontend/")).resolve()
            if not file.is_relative_to(FRONTEND.resolve()):
                self.send_error(404)
                return
        else:
            self.send_error(404)
            return
        if not file.is_file():
            self.send_error(404)
            return
        content = file.read_bytes()
        self.send_response(200)
        self.send_header(
            "Content-Type", mimetypes.guess_type(file.name)[0] or "application/octet-stream"
        )
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(content)


if __name__ == "__main__":
    print("Synthetic browser test: http://127.0.0.1:8869", flush=True)
    HTTPServer(("127.0.0.1", 8869), Handler).serve_forever()
