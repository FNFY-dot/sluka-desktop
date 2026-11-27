# SPDX-License-Identifier: LicenseRef-Sluka
# Copyright (c) 2026 Sluka. Part of Sluka Desktop; see LICENSE.txt.
"""``sluka serve``: the app over HTTP on localhost, for development and tests.

Not how the app is meant to be used -- there is no window management, and a
browser gives the pages ``http:`` where Sluka looks for its own
``chrome-extension:`` scheme.  ``--as-extension`` rewrites those few checks as
the files are served, so the pages take the same paths they take in the app.
"""

from __future__ import annotations

import logging
import signal
import threading

from .config import Config
from .host import Host
from .httpd import Server

log = logging.getLogger("sluka.dev")

#: (file suffix, text as shipped, text served).  Each is a test of the page's
#: own address for Sluka's scheme, which a browser on localhost does not have.
EXTENSION_SCHEME_CHECKS = [
    ("", b"/-extension:$/.test(", b"/-extension:$|^https?:$/.test("),
    ("content/ui.js", b"location.protocol === 'chrome-extension:'", b"/^https?:$|^chrome-extension:$/.test(location.protocol)"),
]


def make_host(config: Config, as_extension: bool = False, with_mpv: bool = False, with_anki: bool = False) -> Host:
    host = Host(config)
    if as_extension:
        host.dev_rewrites = list(EXTENSION_SCHEME_CHECKS)
    if with_mpv and config.mpv_enabled:
        from .mpvbridge import MpvBridge
        host.mpv = MpvBridge(config)
        host.mpv.start()
    if with_anki and config.anki_enabled:
        from .ankibridge import AnkiBridge
        host.anki = AnkiBridge(config, host)
        host.anki.start()
    return host


def serve(config: Config, port: int = 0, as_extension: bool = False, with_mpv: bool = False, with_anki: bool = False) -> int:
    host = make_host(config, as_extension, with_mpv, with_anki)
    server = Server(host, port)
    print(f"{server.origin}/__sluka__/background.html   <- open this first, and keep it open", flush=True)
    print(f"{server.origin}/dashboard/dashboard.html", flush=True)
    stop = threading.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: stop.set())
    server.start()
    stop.wait()
    server.shutdown()
    host.close()
    return 0
