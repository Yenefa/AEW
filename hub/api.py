"""Hub HTTP API — the 8 endpoints, served over stdlib http.server.

Deliberately NOT FastAPI: AEW is zero-dependency, and eight JSON endpoints don't
need a web framework. `HubApp.handle` is a pure function of (method, path, body,
headers) -> (status, payload), so it is testable without opening a socket.

Endpoints:
    GET  /health
    GET  /snapshot
    GET  /tasks
    GET  /tasks/mine?user=<name>
    POST /refresh
    POST /tasks/{id}/claim      body {"user": ...}
    POST /tasks/{id}/release    body {"user": ...}
    POST /tasks/{id}/done       body {"user": ...}

Auth: a shared Bearer token (AEW_HUB_TOKEN). When no token is configured, auth is
disabled — appropriate only behind a Tailscale private network.
"""

from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Dict, Tuple
from urllib.parse import parse_qs, urlparse

from .coordinator import Coordinator


class HubApp:
    def __init__(self, coordinator: Coordinator, token: str = ""):
        self.coord = coordinator
        self.token = token or ""

    def _authorized(self, headers: Dict[str, str]) -> bool:
        if not self.token:
            return True
        auth = headers.get("Authorization", "")
        return auth == f"Bearer {self.token}"

    def handle(self, method: str, path: str, body: bytes,
               headers: Dict[str, str]) -> Tuple[int, dict]:
        if not self._authorized(headers):
            return 401, {"ok": False, "error": "unauthorized"}

        parsed = urlparse(path)
        route = parsed.path.rstrip("/") or "/"
        qs = parse_qs(parsed.query)
        try:
            payload = json.loads(body.decode("utf-8")) if body else {}
        except Exception:
            payload = {}
        if not isinstance(payload, dict):
            payload = {}

        if method == "GET":
            if route == "/health":
                return 200, {"ok": True, "service": "aew-hub",
                             "task_count": len(self.coord.store.list_tasks())}
            if route == "/snapshot":
                return 200, {"ok": True, **self.coord.snapshot()}
            if route == "/tasks":
                return 200, {"ok": True, "tasks": self.coord.tasks()}
            if route == "/tasks/mine":
                user = (qs.get("user") or [payload.get("user", "")])[0]
                return 200, {"ok": True, "tasks": self.coord.mine(user)}

        if method == "POST":
            if route == "/refresh":
                return 200, {"ok": True, **self.coord.refresh()}
            parts = [p for p in route.split("/") if p]
            if len(parts) == 3 and parts[0] == "tasks":
                task_id, action = parts[1], parts[2]
                user = str(payload.get("user", "")).strip()
                if not user:
                    return 400, {"ok": False, "error": "missing user"}
                if action not in ("claim", "release", "done"):
                    return 404, {"ok": False, "error": "unknown action"}
                result = getattr(self.coord, action)(task_id, user)
                status = 200 if result.get("ok") else 409
                return status, result

        return 404, {"ok": False, "error": "not found"}


class _Handler(BaseHTTPRequestHandler):
    def _dispatch(self, method: str) -> None:
        length = int(self.headers.get("Content-Length", 0) or 0)
        body = self.rfile.read(length) if length else b""
        status, payload = self.server.app.handle(  # type: ignore[attr-defined]
            method, self.path, body, dict(self.headers))
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self) -> None:    # noqa: N802
        self._dispatch("GET")

    def do_POST(self) -> None:   # noqa: N802
        self._dispatch("POST")

    def log_message(self, *args) -> None:  # silence default stderr logging
        pass


def serve(coordinator: Coordinator, host: str = "0.0.0.0", port: int = 8765,
          token: str = "") -> None:
    app = HubApp(coordinator, token)
    server = ThreadingHTTPServer((host, port), _Handler)
    server.app = app  # type: ignore[attr-defined]
    print(f"AEW Hub listening on http://{host}:{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
