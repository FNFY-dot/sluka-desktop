# SPDX-License-Identifier: LicenseRef-Sluka
# Copyright (c) 2026 Sluka. Part of Sluka Desktop; see LICENSE.txt.
"""A local HTTP front for the host: Windows, tests, and any system without WebKitGTK.

On Linux the desktop app does not use this -- its pages reach the host through
a custom URL scheme inside the web view, with no socket opened.  On Windows,
whether the windows are the app's own (WebView2) or a browser's, this is how
its pages are served.

It listens on the loopback address only, and takes three kinds of care that a
web page elsewhere cannot reach it through the user's browser: a request whose
Host header is not that address is refused (DNS tricks), so is one the browser
itself marks as coming from another site, and the host refuses API calls from
another origin.  Nothing is said that would let another origin read an answer.
"""

from __future__ import annotations

import logging
import os
import socket
import socketserver
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .host import Host, Request, Response, parse_query

log = logging.getLogger("sluka.httpd")

#: How long a held-open call (the mpv bridge's poll) may take before the
#: server answers it empty and the page asks again.
DEFERRED_SECONDS = 90
#: Uploads above this are streamed to the host instead of read into memory.
STREAM_ABOVE = 8 * 1024 * 1024
#: The calls that write to the disk: finished before the app ends (``Server.drain``).
WRITING_CALLS = ("/__sluka__/api/storage", "/__sluka__/api/download")


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "SlukaDesktop"

    def log_message(self, fmt, *args):  # quiet: the host logs what matters
        log.debug("%s %s", self.address_string(), fmt % args)

    def _allowed_host(self) -> bool:
        host = (self.headers.get("Host") or "").strip().lower()
        return host in self.server.allowed_hosts

    def _foreign(self) -> bool:
        """Whether the browser says this request was made by a page of another site."""
        return (self.headers.get("Sec-Fetch-Site") or "").strip().lower() in ("cross-site", "same-site")

    def _serve(self):
        if not self._allowed_host() or self._foreign():
            self.send_error(403, "Forbidden")
            return
        url = urllib.parse.urlsplit(self.path)
        length = int(self.headers.get("Content-Length") or 0)
        body, reader = b"", None
        if length > STREAM_ABOVE:
            remaining = [length]

            def reader(n: int) -> bytes:
                if remaining[0] <= 0:
                    return b""
                chunk = self.rfile.read(min(n, remaining[0]))
                remaining[0] -= len(chunk)
                return chunk
        elif length:
            body = self.rfile.read(length)

        req = Request(
            method=self.command,
            path=urllib.parse.unquote(url.path),
            query=parse_query(url.query),
            headers={k.lower(): v for k, v in self.headers.items()},
            body=body,
            body_reader=reader,
            origin=self.server.origin,
            # Which of the app's windows asked, where the window says (winshell names each of its views).
            view=(self.headers.get("X-Sluka-View") or "").strip()[:40] or None,
        )
        done = threading.Event()
        box: list[Response] = []

        def respond(resp: Response) -> None:
            if not box:
                box.append(resp)
                done.set()

        writing = self.command == "POST" and req.path.startswith(WRITING_CALLS)
        if writing:
            self.server.writes(+1)
        try:
            self.server.host.handle(req, respond)
            if not done.wait(DEFERRED_SECONDS):
                respond(Response(status=204))
        finally:
            if writing:
                self.server.writes(-1)
        self._write(box[0])

    def _write(self, resp: Response) -> None:
        try:
            self.send_response(resp.status)
            self.send_header("Content-Type", resp.content_type)
            self.send_header("Content-Length", str(resp.length))
            for name, value in resp.headers.items():
                self.send_header(name, value)
            # No page of another origin may so much as embed what is served here.
            self.send_header("Cross-Origin-Resource-Policy", "same-origin")
            self.end_headers()
            if self.command == "HEAD":
                return
            if resp.file:
                path, offset, length = resp.file
                with open(path, "rb") as handle:
                    handle.seek(offset)
                    left = length
                    while left > 0:
                        chunk = handle.read(min(256 * 1024, left))
                        if not chunk:
                            break
                        self.wfile.write(chunk)
                        left -= len(chunk)
            else:
                self.wfile.write(resp.body)
        except ConnectionError:  # the page went away before its answer did (a window closed)
            pass

    do_GET = _serve
    do_HEAD = _serve
    do_POST = _serve


class Server(ThreadingHTTPServer):
    daemon_threads = True
    # On Windows "reuse" means a second program may take a port that is in use, which is the last thing wanted.
    allow_reuse_address = os.name != "nt"

    def server_bind(self):
        if os.name == "nt" and hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        # Not HTTPServer's own: that asks the system for this computer's name, which on some networks takes seconds.
        socketserver.TCPServer.server_bind(self)
        self.server_name, self.server_port = "127.0.0.1", self.server_address[1]

    def __init__(self, host: Host, port: int = 0):
        super().__init__(("127.0.0.1", port), _Handler)
        self.host = host
        port = self.server_address[1]
        self.origin = f"http://127.0.0.1:{port}"
        self.allowed_hosts = {f"127.0.0.1:{port}", f"localhost:{port}"}
        self._writing = 0
        self._written = threading.Condition()

    def writes(self, change: int) -> None:
        with self._written:
            self._writing += change
            self._written.notify_all()

    def drain(self, timeout: float = 5.0) -> bool:
        """Wait (a while) for the writes under way: a window closed right after a word was graded."""
        with self._written:
            return self._written.wait_for(lambda: self._writing <= 0, timeout)

    def handle_error(self, request, client_address):
        # A browser dropping a connection it no longer wants is not an error.
        import sys
        if isinstance(sys.exc_info()[1], (ConnectionError, TimeoutError)):
            return
        log.exception("request from %s failed", client_address)

    def start(self) -> threading.Thread:
        thread = threading.Thread(target=self.serve_forever, name="sluka-httpd", daemon=True)
        thread.start()
        return thread
