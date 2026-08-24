"""Serve the frontend from source with generated data from .site."""

from __future__ import annotations

import argparse
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit


class DevelopmentHandler(SimpleHTTPRequestHandler):
    source_root = Path.cwd().resolve()

    def translate_path(self, path: str) -> str:
        request_path = urlsplit(path).path
        if request_path in {"/", "/index.html"}:
            return str(self.source_root / "index.html")
        if request_path == "/cities.json":
            return str(self.source_root / "cities.json")
        if request_path.startswith("/assets/"):
            assets_root = (self.source_root / "assets").resolve()
            candidate = (self.source_root / request_path.lstrip("/")).resolve()
            if candidate.is_relative_to(assets_root):
                return str(candidate)
        return super().translate_path(path)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8080)
    args = parser.parse_args()
    handler = lambda *handler_args, **kwargs: DevelopmentHandler(
        *handler_args,
        directory=".site",
        **kwargs,
    )
    server = ThreadingHTTPServer(("", args.port), handler)
    print(f"Serving http://localhost:{args.port} (refresh to see frontend changes)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
