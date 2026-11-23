"""A local HTTP server standing in for Baleia's BI gateway."""

from __future__ import annotations

import base64
import json
import threading
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, urlsplit

import pytest

Reply = tuple[int, dict[str, str], Any]


@dataclass
class FakeGateway:
    url: str = ""
    routes: dict[str, Callable[[dict[str, str]], Reply]] = field(default_factory=dict)
    requests: list[tuple[str, dict[str, str], str | None]] = field(default_factory=list)

    def route(self, path: str, handler: Callable[[dict[str, str]], Reply]) -> None:
        self.routes[path] = handler

    def json(self, path: str, body: Any, status: int = 200) -> None:
        self.routes[path] = lambda _params: (status, {}, body)


@pytest.fixture
def gateway() -> Iterator[FakeGateway]:
    fake = FakeGateway()

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            parts = urlsplit(self.path)
            params = {k: v[0] for k, v in parse_qs(parts.query).items()}
            auth = self.headers.get("Authorization")
            decoded = base64.b64decode(auth.split(" ", 1)[1]).decode() if auth else None
            fake.requests.append((parts.path, params, decoded))
            handler = fake.routes.get(parts.path)
            status, headers, body = (
                handler(params) if handler else (404, {}, {"error": "not found"})
            )
            payload = body if isinstance(body, bytes) else json.dumps(body).encode()
            self.send_response(status)
            for name, value in headers.items():
                self.send_header(name, value)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, *_: Any) -> None:
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    fake.url = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        yield fake
    finally:
        server.shutdown()
        server.server_close()
