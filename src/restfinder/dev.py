"""Serve the frontend from source with generated data from .site."""

from __future__ import annotations

import argparse
import os
import signal
import socket
import subprocess
import time
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit


class DevelopmentHandler(SimpleHTTPRequestHandler):
    source_root = Path.cwd().resolve()

    def end_headers(self) -> None:
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def translate_path(self, path: str) -> str:
        request_path = urlsplit(path).path
        if request_path in {"/", "/index.html"}:
            return str(self.source_root / "index.html")
        if request_path in {"/cities.json", "/manifest.webmanifest", "/service-worker.js"}:
            return str(self.source_root / request_path.lstrip("/"))
        if request_path.startswith("/assets/"):
            assets_root = (self.source_root / "assets").resolve()
            candidate = (self.source_root / request_path.lstrip("/")).resolve()
            if candidate.is_relative_to(assets_root):
                return str(candidate)
        return super().translate_path(path)


def port_is_available(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            probe.bind(("", port))
        except OSError:
            return False
    return True


def listener_pids(port: int) -> list[int]:
    try:
        result = subprocess.run(
            ["lsof", "-nP", f"-iTCP:{port}", "-sTCP:LISTEN", "-t"],
            check=False,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError:
        return []
    return sorted({int(value) for value in result.stdout.split() if value.isdigit()})


def process_descriptions(pids: list[int]) -> str:
    if not pids:
        return ""
    result = subprocess.run(
        ["ps", "-p", ",".join(str(pid) for pid in pids), "-o", "pid=,command="],
        check=False,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip() or ", ".join(f"PID {pid}" for pid in pids)


def ensure_port_available(port: int) -> None:
    if port_is_available(port):
        return

    pids = listener_pids(port)
    if not pids:
        raise SystemExit(
            f"Port {port} is in use, but its listening process could not be identified."
        )

    print(f"Port {port} is already in use by:\n{process_descriptions(pids)}")
    try:
        answer = input("Kill this process and continue? [y/N] ").strip().lower()
    except EOFError:
        answer = ""
    if answer not in {"y", "yes"}:
        raise SystemExit("Development server not started.")

    for pid in pids:
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        except PermissionError as error:
            raise SystemExit(f"Could not stop PID {pid}: permission denied.") from error

    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        if port_is_available(port):
            return
        time.sleep(0.1)
    raise SystemExit(f"Port {port} is still in use after stopping {', '.join(map(str, pids))}.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument(
        "--ensure-port",
        action="store_true",
        help="resolve a port conflict interactively, then exit",
    )
    args = parser.parse_args()
    ensure_port_available(args.port)
    if args.ensure_port:
        return
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
