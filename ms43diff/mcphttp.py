# -*- coding: utf-8 -*-
"""
MCP over HTTP ("Streamable HTTP" transport) for Claude Code.

The stdio server (mcpserver.serve) is started by the AI client itself, so the
program cannot start or stop it. This one lives inside the window process
instead: Start/Stop buttons really start and stop it, and Claude Code connects
to it by URL:

    claude mcp add --transport http --scope user ms43 http://127.0.0.1:8743/mcp \\
        --header "Authorization: Bearer <token>"

Only JSON responses are used (no event stream): every tool answers at once.
Security: bound to 127.0.0.1 only; every request must carry the bearer token;
requests from web pages (an Origin header other than localhost) are refused,
which also blocks DNS-rebinding tricks.

Several servers can run at once (e.g. ms43_stock and ms43_tune), each on its
own port with its own firmware and answer language. The firmware is resolved
on every request, so choosing another file in the window takes effect at once.
"""

from __future__ import annotations

import hmac
import json
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Callable, Dict, List, Optional, Tuple

from . import mcpserver
from .i18n import lang_override, reset_lang_override

Resolver = Callable[[], Tuple[str, str]]   # -> (xdf path, bin path)


class McpHttpServer:
    def __init__(self, name: str, port: int, token: str, resolver: Resolver,
                 lang: Optional[str] = None):
        self.name = name
        self.port = port
        self.token = token
        self.resolver = resolver
        self.lang = lang
        self.requests = 0
        self.last_error = ""
        self._httpd: Optional[ThreadingHTTPServer] = None
        self._fw: Optional[mcpserver.Firmware] = None
        self._fw_key: Optional[tuple] = None
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}/mcp"

    @property
    def running(self) -> bool:
        return self._httpd is not None

    def start(self) -> None:
        if self._httpd is not None:
            return
        owner = self

        class Handler(_Handler):
            server_owner = owner

        httpd = ThreadingHTTPServer(("127.0.0.1", self.port), Handler)
        httpd.daemon_threads = True
        self._httpd = httpd
        threading.Thread(target=httpd.serve_forever, name=f"mcp-{self.name}",
                         daemon=True).start()

    def stop(self) -> None:
        httpd, self._httpd = self._httpd, None
        if httpd is not None:
            httpd.shutdown()
            httpd.server_close()

    # ------------------------------------------------------------------
    def firmware(self) -> mcpserver.Firmware:
        """The firmware for this request; reloaded when the files change."""
        xdf, binf = self.resolver()
        key = (xdf, binf, _mtime(xdf), _mtime(binf))
        with self._lock:
            if self._fw is None or key != self._fw_key:
                self._fw = mcpserver.Firmware(xdf or None, binf or None)
                self._fw_key = key
            return self._fw

    def handle(self, message: Dict) -> Optional[Dict]:
        fw_token = mcpserver.CURRENT.set(self.firmware())
        lang_token = lang_override(self.lang)
        try:
            return mcpserver.handle(message)
        finally:
            reset_lang_override(lang_token)
            mcpserver.CURRENT.reset(fw_token)


def _mtime(path: str) -> float:
    try:
        return os.path.getmtime(path) if path else 0.0
    except OSError:
        return 0.0


class _Handler(BaseHTTPRequestHandler):
    server_owner: McpHttpServer
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):  # no console in the window build
        pass

    def _send(self, code: int, body: bytes = b"", ctype: str = "application/json") -> None:
        self.send_response(code)
        if body:
            self.send_header("Content-Type", ctype + "; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        try:
            if body:
                self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _allowed(self) -> bool:
        origin = self.headers.get("Origin")
        if origin and not origin.startswith(("http://127.0.0.1", "http://localhost")):
            return False
        auth = self.headers.get("Authorization", "")
        expected = "Bearer " + self.server_owner.token
        return hmac.compare_digest(auth.encode(), expected.encode())

    def do_GET(self) -> None:  # noqa: N802 - no server-initiated stream
        self._send(405 if self._allowed() else 401)

    def do_DELETE(self) -> None:  # noqa: N802
        self._send(405 if self._allowed() else 401)

    def do_POST(self) -> None:  # noqa: N802
        if self.path.split("?", 1)[0].rstrip("/") != "/mcp":
            return self._send(404)
        if not self._allowed():
            return self._send(401, json.dumps({"error": "unauthorized"}).encode())
        owner = self.server_owner
        length = int(self.headers.get("Content-Length") or 0)
        try:
            payload = json.loads(self.rfile.read(length) or b"null")
        except ValueError:
            return self._send(400, json.dumps(
                {"jsonrpc": "2.0", "id": None,
                 "error": {"code": -32700, "message": "parse error"}}).encode())
        messages: List[Any] = payload if isinstance(payload, list) else [payload]
        answers = []
        for message in messages:
            if not isinstance(message, dict):
                continue
            owner.requests += 1
            try:
                answer = owner.handle(message)
            except Exception as exc:  # noqa: BLE001 - reported to the client
                owner.last_error = str(exc)
                answer = {"jsonrpc": "2.0", "id": message.get("id"),
                          "error": {"code": -32603, "message": str(exc)}}
            if answer is not None:
                answers.append(answer)
        if not answers:
            return self._send(202)
        body = answers if isinstance(payload, list) else answers[0]
        self._send(200, json.dumps(body, ensure_ascii=False).encode("utf-8"))


def call(url: str, token: str, messages: List[Dict], timeout: float = 30) -> List[Dict]:
    """Send JSON-RPC messages to an HTTP MCP server (used by "Check")."""
    import urllib.request

    answers = []
    for message in messages:
        req = urllib.request.Request(
            url, data=json.dumps(message).encode("utf-8"), method="POST",
            headers={"Content-Type": "application/json", "Authorization": "Bearer " + token,
                     "Accept": "application/json, text/event-stream"})
        with urllib.request.urlopen(req, timeout=timeout) as res:
            text = res.read().decode("utf-8")
        if text:
            answers.append(json.loads(text))
    return answers
