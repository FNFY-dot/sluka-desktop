# SPDX-License-Identifier: LicenseRef-Sluka
# Copyright (c) 2026 Sluka. Part of Sluka Desktop; see LICENSE.txt.
"""A message of the app's own that is not to wait for the menu to be opened: Windows' own message box, above every
window, in a thread of its own (nothing waits for it to be closed).  Elsewhere, the log has it."""

from __future__ import annotations

import logging
import sys
import threading

log = logging.getLogger("sluka.popups")

MB_OK, MB_ICONINFORMATION, MB_SETFOREGROUND, MB_TOPMOST = 0x0, 0x40, 0x10000, 0x40000


def _box(title: str, text: str) -> None:
    import ctypes

    try:
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        user32.MessageBoxW.argtypes = (ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_uint)
        user32.MessageBoxW.restype = ctypes.c_int
        user32.MessageBoxW(None, text, title, MB_OK | MB_ICONINFORMATION | MB_SETFOREGROUND | MB_TOPMOST)
    except Exception:
        log.exception("a message could not be shown: %s", title)


def show(title: str, text: str) -> None:
    log.info("%s: %s", title, text.replace("\n", " "))
    if sys.platform != "win32":
        return
    threading.Thread(target=_box, args=(title, text), name="sluka-popup", daemon=True).start()
