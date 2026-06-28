"""Read-only observability server for loop state.

Serves the dashboard HTML plus a tiny JSON API so the viewer can load live state
instead of drag-and-drop:

  GET /                -> dashboard/index.html
  GET /api/state       -> the JSON state file
  GET /api/runlog      -> the JSONL run log as a JSON array
  GET /api/health      -> {"ok": true}

Routing is a pure function (``route``) so it's unit-tested without binding a
socket. The server is read-only by construction — there are no mutating routes.
"""

from __future__ import annotations

import json
from pathlib import Path

from .state import StateStore


def _dashboard_html() -> bytes:
    # repo root: .../Strive_Engineering ; this file: loopengine/loopengine/dashboard_api.py
    html = Path(__file__).resolve().parents[2] / "dashboard" / "index.html"
    if html.exists():
        return html.read_bytes()
    return b"<!doctype html><p>dashboard/index.html not found</p>"


def route(path: str, state: StateStore) -> tuple[int, str, bytes]:
    """Map a GET path to (status, content_type, body). Pure — no I/O beyond reads."""
    # strip a query string if any
    path = path.split("?", 1)[0]
    if path in ("/", "/index.html"):
        return 200, "text/html; charset=utf-8", _dashboard_html()
    if path == "/api/health":
        return 200, "application/json", b'{"ok": true}'
    if path == "/api/state":
        data = json.loads(state.path.read_text(encoding="utf-8")) if state.path.exists() else {"loops": {}}
        return 200, "application/json", json.dumps(data).encode("utf-8")
    if path == "/api/runlog":
        rows = []
        if state.runlog_path.exists():
            for line in state.runlog_path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line:
                    rows.append(json.loads(line))
        return 200, "application/json", json.dumps(rows).encode("utf-8")
    return 404, "application/json", b'{"error": "not found"}'


def serve(state_path: str, port: int = 8765, host: str = "127.0.0.1") -> None:  # pragma: no cover - I/O loop
    """Run the blocking read-only HTTP server (stdlib only)."""
    from http.server import BaseHTTPRequestHandler, HTTPServer

    store = StateStore(state_path)

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802 - stdlib signature
            status, ctype, body = route(self.path, store)
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):  # silence default stderr logging
            pass

    httpd = HTTPServer((host, port), Handler)
    print(f"loopengine dashboard on http://{host}:{port}  (state: {state_path})")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        httpd.server_close()
