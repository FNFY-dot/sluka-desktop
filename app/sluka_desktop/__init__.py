# SPDX-License-Identifier: LicenseRef-Sluka
# Copyright (c) 2026 Sluka. Part of Sluka Desktop; see LICENSE.txt.
"""Sluka Desktop: runs the Sluka browser extension as a standalone desktop app.

The extension's own files are served unmodified.  A small JavaScript shim
stands in for the browser's ``chrome.*`` extension API, and this package is the
native side of that shim: files, storage, downloads, windows and the mpv bridge.

Only the Python standard library is used here.  On Tails the window shell
additionally needs PyGObject with WebKitGTK, which is imported only by
``gtkshell``; on Windows the windows are the app's own, with Windows' web view
(WebView2) in them, reached with ctypes alone (``winshell``).
"""

__version__ = "0.16.2"
APP_NAME = "Sluka Desktop"
#: What Sluka Desktop is used under, as its About says.
LICENCE_NOTE = ("Sluka Desktop is used under Sluka's terms (sluka.app/terms). Parts of it are free software, under the "
                "GNU General Public License, and it comes with others' software, each under its own licence: "
                "LICENSE.txt and NOTICES.txt, in its folder, say which.")
