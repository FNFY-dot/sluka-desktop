# SPDX-License-Identifier: LicenseRef-Sluka
# Copyright (c) 2026 Sluka. Part of Sluka Desktop; see LICENSE.txt.
"""A few words with the browser that shows the app's windows, over its own debugging protocol.

Used for two things (``browsershell``): to make the one page nobody sees, in
which Sluka's background worker can run without belonging to a window, and to
know when the last window has been closed.  The browser is started with
``--remote-debugging-port=0`` for it and writes the port it chose into its
profile folder; that port listens on this computer only.

The protocol is JSON over a WebSocket, of which this speaks just enough: text
messages both ways, with the pings and continuations a server may send.
"""

from __future__ import annotations

import base64
import json
import logging
import os
import socket
import struct
import threading
import time
from pathlib import Path

log = logging.getLogger("sluka.shell")

#: The file a Chromium browser writes into its profile folder: the port, then the path of the browser's own channel.
PORT_FILE = "DevToolsActivePort"


class Closed(Exception):
    pass


def read_port_file(profile: Path) -> tuple[int, str] | None:
    try:
        lines = (profile / PORT_FILE).read_text(encoding="utf-8", errors="replace").split()
    except OSError:
        return None
    if len(lines) >= 2 and lines[0].isdigit() and lines[1].startswith("/"):
        return int(lines[0]), lines[1]
    return None


def forget_port_file(profile: Path) -> None:
    """Before the browser is started: what a run before this one left there says nothing about this one."""
    try:
        os.unlink(profile / PORT_FILE)
    except OSError:
        pass


class Channel:
    """One WebSocket to the browser, with calls answered by number."""

    def __init__(self, port: int, path: str, timeout: float = 5.0):
        self.sock = socket.create_connection(("127.0.0.1", port), timeout=timeout)
        self._lock = threading.Lock()
        self._serial = 0
        self._answers: dict[int, dict] = {}
        self._got = threading.Condition()
        self.open = True
        self.on_event = None
        key = base64.b64encode(os.urandom(16)).decode("ascii")
        # No Origin line: the browser takes a program's word, and refuses a web page's.
        request = (f"GET {path} HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
                   f"Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n")
        self.sock.sendall(request.encode("ascii"))
        head = b""
        while b"\r\n\r\n" not in head:
            chunk = self.sock.recv(4096)
            if not chunk:
                raise Closed("the browser closed the connection as it was made")
            head += chunk
            if len(head) > 65536:
                raise Closed("the browser's answer was not a WebSocket's")
        status, rest = head.split(b"\r\n\r\n", 1)
        if b" 101 " not in status.split(b"\r\n", 1)[0]:
            raise Closed("the browser refused: " + status.split(b"\r\n", 1)[0].decode("ascii", "replace"))
        self._buffer = rest
        self.sock.settimeout(None)
        self._thread = threading.Thread(target=self._read, name="sluka-cdp", daemon=True)
        self._thread.start()

    # ---- frames

    def _take(self, n: int) -> bytes:
        while len(self._buffer) < n:
            chunk = self.sock.recv(65536)
            if not chunk:
                raise Closed("closed")
            self._buffer += chunk
        out, self._buffer = self._buffer[:n], self._buffer[n:]
        return out

    def _frame(self) -> tuple[int, bool, bytes]:
        first, second = self._take(2)
        length = second & 0x7F
        if length == 126:
            (length,) = struct.unpack(">H", self._take(2))
        elif length == 127:
            (length,) = struct.unpack(">Q", self._take(8))
        mask = self._take(4) if second & 0x80 else b""
        data = self._take(length)
        if mask:
            data = bytes(b ^ mask[i % 4] for i, b in enumerate(data))
        return first & 0x0F, bool(first & 0x80), data

    def _write(self, opcode: int, data: bytes) -> None:
        mask = os.urandom(4)
        head = bytes([0x80 | opcode])
        if len(data) < 126:
            head += bytes([0x80 | len(data)])
        elif len(data) < 65536:
            head += bytes([0x80 | 126]) + struct.pack(">H", len(data))
        else:
            head += bytes([0x80 | 127]) + struct.pack(">Q", len(data))
        # XOR with the mask, four bytes at a time repeated: done in one go on whole integers.
        n = len(data)
        key = int.from_bytes((mask * (n // 4 + 1))[:n], "big") if n else 0
        masked = (int.from_bytes(data, "big") ^ key).to_bytes(n, "big") if n else b""
        with self._lock:
            self.sock.sendall(head + mask + masked)

    def _read(self) -> None:
        text = b""
        try:
            while True:
                opcode, final, data = self._frame()
                if opcode == 0x8:
                    break
                if opcode == 0x9:
                    self._write(0xA, data)
                    continue
                if opcode in (0x1, 0x0):
                    text += data
                    if not final:
                        continue
                    whole, text = text, b""
                    try:
                        message = json.loads(whole.decode("utf-8", "replace"))
                    except ValueError:
                        continue
                    if "id" in message:
                        with self._got:
                            self._answers[message["id"]] = message
                            self._got.notify_all()
                    elif self.on_event:
                        try:
                            self.on_event(message)
                        except Exception:
                            log.exception("an event from the browser could not be taken in")
        except (OSError, Closed, struct.error):
            pass
        finally:
            self.open = False
            with self._got:
                self._got.notify_all()

    # ---- calls

    def call(self, method: str, params: dict | None = None, session: str = "", timeout: float = 8.0) -> dict:
        """The result of one command; ``Closed`` or ``RuntimeError`` (the browser's own words) if there is none."""
        with self._got:
            self._serial += 1
            number = self._serial
        message = {"id": number, "method": method, "params": params or {}}
        if session:
            message["sessionId"] = session
        try:
            self._write(0x1, json.dumps(message).encode("utf-8"))
        except OSError as err:
            self.open = False
            raise Closed(str(err)) from err
        end = time.monotonic() + timeout
        with self._got:
            while number not in self._answers:
                if not self.open:
                    raise Closed("the browser is gone")
                left = end - time.monotonic()
                if left <= 0:
                    raise Closed(f"the browser did not answer {method}")
                self._got.wait(left)
            answer = self._answers.pop(number)
        if "error" in answer:
            raise RuntimeError(str((answer["error"] or {}).get("message") or answer["error"]))
        return answer.get("result") or {}

    def close(self) -> None:
        self.open = False
        try:
            self.sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        try:
            self.sock.close()
        except OSError:
            pass


def connect(profile: Path, wait: float = 15.0, alive=lambda: True) -> Channel | None:
    """The browser's channel, once it has said where it is; None if it never does."""
    end = time.monotonic() + wait
    last = ""
    while time.monotonic() < end:
        found = read_port_file(profile)
        if found:
            try:
                return Channel(found[0], found[1])
            except (OSError, Closed) as err:
                last = str(err)
        if not alive():
            break
        time.sleep(0.15)
    if last:
        log.info("the browser's own channel could not be opened: %s", last)
    return None
