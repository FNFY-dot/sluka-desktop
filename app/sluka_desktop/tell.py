# SPDX-License-Identifier: LicenseRef-Sluka
# Copyright (c) 2026 Sluka. Part of Sluka Desktop; see LICENSE.txt.
"""Telling the user something, whether or not there is a terminal to tell it in.

On Windows the app is started without a console window (pythonw), and then has neither a place to print to
nor anybody reading one: what has to be said is said in a message box, and written to the log.
"""

from __future__ import annotations

import logging
import os
import sys

from . import APP_NAME

log = logging.getLogger("sluka")


def has_terminal() -> bool:
    # SLUKA_DETACHED: set by the app for the copy of itself it starts without a console window, whose
    # output goes nowhere.
    return sys.stderr is not None and os.environ.get("SLUKA_DETACHED") != "1"


def message_box(text: str) -> bool:
    if os.name != "nt":
        return False
    try:
        import ctypes

        # MB_OK | MB_ICONWARNING | MB_SETFOREGROUND
        ctypes.windll.user32.MessageBoxW(None, text, APP_NAME, 0x00000030 | 0x00010000)
        return True
    except Exception:
        return False


def say(text: str) -> None:
    """Something good to know; lost where there is no terminal."""
    if sys.stdout is not None:
        try:
            print(text, flush=True)
        except (OSError, ValueError):
            pass


def problem(text: str) -> None:
    """Something that stops the app, or the user's wish: always said, one way or the other."""
    # For the log file; the terminal, which shows warnings and worse, gets it once, below.
    log.info("said to the user: %s", text.replace("\n", " | "))
    if has_terminal():
        try:
            print(f"sluka: {text}", file=sys.stderr, flush=True)
            if os.environ.get("SLUKA_CLICKED") == "1":
                # Started by a double-click (Sluka.cmd): the console may be minimised, or gone in a moment.
                message_box(text)
            return
        except (OSError, ValueError):
            pass
    message_box(text)
