# SPDX-License-Identifier: LicenseRef-Sluka
# Copyright (c) 2026 Sluka. Part of Sluka Desktop; see LICENSE.txt.
"""Keys that work in every program: the game text menu's keys for the screen (ocrtext.py), pressed in the game.

Windows' own hotkeys (RegisterHotKey), as AutoHotkey's plain hotkeys are: they work whatever program is in front --
one run as administrator too, and a game in full screen that reads the keyboard itself -- and the program in front
does not get the key pressed.  They are held by a thread of their own, with a message queue of its own: a hotkey is
Windows' to the thread that asked for it.

A key is written as people write one: "Ctrl+Shift+R", "Alt+F2", "F8", "Ctrl+Num5".
"""

from __future__ import annotations

import logging
import queue
import sys
import threading

log = logging.getLogger("sluka.games")
WINDOWS = sys.platform == "win32"

MOD_ALT, MOD_CONTROL, MOD_SHIFT, MOD_WIN, MOD_NOREPEAT = 0x1, 0x2, 0x4, 0x8, 0x4000
#: The modifiers, as they are written: in this order.
MODIFIERS = (("Ctrl", MOD_CONTROL), ("Alt", MOD_ALT), ("Shift", MOD_SHIFT), ("Win", MOD_WIN))
ERROR_HOTKEY_ALREADY_REGISTERED = 1409


def _keys() -> dict[str, int]:
    keys = {chr(c): c for c in range(ord("A"), ord("Z") + 1)}
    keys.update({str(d): 0x30 + d for d in range(10)})
    keys.update({f"F{n}": 0x6F + n for n in range(1, 25)})
    keys.update({f"Num{d}": 0x60 + d for d in range(10)})
    keys.update({
        "Space": 0x20, "Enter": 0x0D, "Tab": 0x09, "Backspace": 0x08, "Esc": 0x1B,
        "Insert": 0x2D, "Delete": 0x2E, "Home": 0x24, "End": 0x23, "PageUp": 0x21, "PageDown": 0x22,
        "Left": 0x25, "Up": 0x26, "Right": 0x27, "Down": 0x28,
        "Pause": 0x13, "ScrollLock": 0x91, "PrintScreen": 0x2C,
        "Num*": 0x6A, "Num+": 0x6B, "Num-": 0x6D, "Num.": 0x6E, "Num/": 0x6F,
        # (named as they are on a US keyboard; elsewhere the same keys bear other marks)
        ";": 0xBA, "=": 0xBB, ",": 0xBC, "-": 0xBD, ".": 0xBE, "/": 0xBF, "`": 0xC0, "[": 0xDB, "\\": 0xDC, "]": 0xDD,
        "'": 0xDE, "<>": 0xE2,
    })
    return keys


#: Each key that can be part of one, as it is written, and Windows' number for it (its virtual-key code).
KEYS = _keys()
NAMES = {vk: name for name, vk in KEYS.items()}
#: Keys that may be one alone: they type nothing.  Any other needs Ctrl, Alt or Win with it.
ALONE = frozenset([f"F{n}" for n in range(1, 25)] + ["Pause", "ScrollLock", "PrintScreen", "Insert"])
#: What can be done with a key, and what the menu calls it.
ACTIONS = {"read": "Read the box now", "select": "Select the text box", "once": "Read a box once",
           "toggle": "Start or stop reading"}


class KeyError_(ValueError):
    """A key that cannot be one of these."""


def parse(spec: str, alone: bool = False) -> tuple[int, int]:
    """"Ctrl+Shift+R" as (Windows' modifiers, its virtual-key code); KeyError_ where it is none.  ``alone``: a key that
    types may be one by itself ("1", "K", "Esc") -- only Sluka's own, held for a moment (Sluka Vision's open panel),
    never one you choose."""
    text = str(spec or "").replace(" ", "")
    if not text:
        raise KeyError_("no key")
    # The key is the end ("Num+" and "-" are keys too), the modifiers before it.
    key = next((name for name in sorted(KEYS, key=len, reverse=True)
                if text.lower().endswith(name.lower()) and (len(text) == len(name) or text[-len(name) - 1] == "+")), None)
    if key is None:
        raise KeyError_(f"{text.rsplit('+', 1)[-1] or text} is not a key Sluka knows")
    mods = 0
    for part in [p for p in text[:-len(key)].split("+") if p]:
        found = next((value for name, value in MODIFIERS if name.lower() == part.lower()), None)
        if found is None:
            raise KeyError_(f"{part} is not Ctrl, Alt, Shift or Win")
        mods |= found
    if not alone:
        check(mods, KEYS[key])
    return mods, KEYS[key]


def check(mods: int, vk: int) -> None:
    """KeyError_ for a key that would be taken from typing (a letter alone), or that Windows keeps (Win+L)."""
    name = NAMES.get(vk)
    if name is None:
        raise KeyError_("that key cannot be one (Sluka knows letters, digits, F1 to F24, the arrows and the like)")
    if name not in ALONE and not mods & (MOD_CONTROL | MOD_ALT | MOD_WIN):
        raise KeyError_(f"{name} alone{' with Shift' if mods & MOD_SHIFT else ''} types: take it with Ctrl or Alt")
    if name == "F12" and not mods:
        raise KeyError_("F12 alone is Windows' own, for debuggers: take it with Ctrl or Alt")
    if mods & MOD_WIN and name in ("L", "D", "Tab"):
        raise KeyError_(f"Win+{name} is Windows' own")


def spec(mods: int, vk: int) -> str:
    """Windows' modifiers and key as they are written: "Ctrl+Shift+R"."""
    name = NAMES.get(vk)
    if name is None:
        raise KeyError_("that key cannot be one")
    return "+".join([label for label, value in MODIFIERS if mods & value] + [name])


def normal(text: str) -> str:
    """A key as it is written, written the one way ("ctrl + shift + r" is "Ctrl+Shift+R"); '' for none."""
    if not str(text or "").strip():
        return ""
    return spec(*parse(text))


def altgr_note(text: str) -> str:
    """Ctrl+Alt with a key that types is AltGr with it on many keyboards (AltGr+S is "ș" on a Romanian one): while
    Sluka has the key, it types nothing."""
    try:
        mods, vk = parse(text)
    except KeyError_:
        return ""
    if mods & MOD_CONTROL and mods & MOD_ALT and NAMES[vk] not in ALONE and not NAMES[vk].startswith("Num"):
        return (f"{text}: Ctrl+Alt is AltGr on many keyboards, so AltGr+{NAMES[vk]} types nothing while Sluka has it "
                "(Ctrl+Shift or Alt+Shift keep AltGr free)")
    return ""


# ------------------------------------------------------------------------------------------ the keys, held


class NullBackend:
    """Where there are no such keys (not Windows): none is held, and saying so."""

    def start(self, on_press) -> None:
        pass

    def apply(self, wanted: dict[int, tuple[int, int]]) -> dict[int, str]:
        return {number: "keys that work in every program are Windows'" for number in wanted}

    def close(self) -> None:
        pass


class WindowsBackend:
    """RegisterHotKey, in a thread of its own: Windows posts WM_HOTKEY to the thread that asked for the key."""

    WM_HOTKEY = 0x0312
    WM_QUIT = 0x0012
    WM_APPLY = 0x8000 + 1  # (WM_APP + 1)

    def __init__(self):
        import ctypes
        from ctypes import wintypes

        self.ctypes = ctypes
        self.wintypes = wintypes
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

        def fn(lib, name, restype, *argtypes):
            f = getattr(lib, name)
            f.restype = restype
            f.argtypes = argtypes
            return f

        w = wintypes
        self.RegisterHotKey = fn(user32, "RegisterHotKey", w.BOOL, w.HWND, ctypes.c_int, w.UINT, w.UINT)
        self.UnregisterHotKey = fn(user32, "UnregisterHotKey", w.BOOL, w.HWND, ctypes.c_int)
        self.GetMessageW = fn(user32, "GetMessageW", w.BOOL, ctypes.POINTER(w.MSG), w.HWND, w.UINT, w.UINT)
        self.PeekMessageW = fn(user32, "PeekMessageW", w.BOOL, ctypes.POINTER(w.MSG), w.HWND, w.UINT, w.UINT, w.UINT)
        self.PostThreadMessageW = fn(user32, "PostThreadMessageW", w.BOOL, w.DWORD, w.UINT, w.WPARAM, w.LPARAM)
        self.GetCurrentThreadId = fn(kernel32, "GetCurrentThreadId", w.DWORD)
        self._thread: threading.Thread | None = None
        self._tid = 0
        self._ready = threading.Event()
        self._jobs: queue.Queue = queue.Queue()
        self._held: set[int] = set()
        self._on_press = None

    def start(self, on_press) -> None:
        if self._thread is not None:
            return
        self._on_press = on_press
        self._thread = threading.Thread(target=self._run, name="hotkeys", daemon=True)
        self._thread.start()
        self._ready.wait(5)

    def _run(self) -> None:
        msg = self.wintypes.MSG()
        # The thread's message queue, made before anything is posted to it.
        self.PeekMessageW(self.ctypes.byref(msg), None, 0, 0, 0)
        self._tid = int(self.GetCurrentThreadId())
        self._ready.set()
        try:
            while True:
                got = self.GetMessageW(self.ctypes.byref(msg), None, 0, 0)
                if got == 0 or got == -1:
                    break
                if msg.message == self.WM_HOTKEY:
                    number = int(msg.wParam)
                    if self._on_press is not None:
                        # (not in this thread: it is to be back at its messages at once)
                        threading.Thread(target=self._on_press, args=(number,), name="hotkey", daemon=True).start()
                elif msg.message == self.WM_APPLY:
                    self._apply_waiting()
        except Exception:
            log.exception("the keys' thread stopped")
        finally:
            for number in list(self._held):
                self.UnregisterHotKey(None, number)
            self._held.clear()

    def _apply_waiting(self) -> None:
        while True:
            try:
                job = self._jobs.get_nowait()
            except queue.Empty:
                return
            for number in list(self._held):
                self.UnregisterHotKey(None, number)
                self._held.discard(number)
            errors = {}
            for number, (mods, vk) in job["wanted"].items():
                if self.RegisterHotKey(None, number, mods | MOD_NOREPEAT, vk):
                    self._held.add(number)
                else:
                    code = self.ctypes.get_last_error()
                    errors[number] = ("it is taken by another program, or by Windows" if code == ERROR_HOTKEY_ALREADY_REGISTERED
                                      else f"Windows would not give it (error {code})")
            job["errors"] = errors
            job["done"].set()

    def apply(self, wanted: dict[int, tuple[int, int]]) -> dict[int, str]:
        if self._thread is None or not self._tid:
            return {number: "the keys' thread is not running" for number in wanted}
        job = {"wanted": dict(wanted), "errors": {}, "done": threading.Event()}
        self._jobs.put(job)
        if not self.PostThreadMessageW(self._tid, self.WM_APPLY, 0, 0):
            return {number: "the keys' thread could not be reached" for number in wanted}
        if not job["done"].wait(5):
            return {number: "the keys' thread did not answer" for number in wanted}
        return job["errors"]

    def close(self) -> None:
        if self._thread is not None and self._tid:
            self.PostThreadMessageW(self._tid, self.WM_QUIT, 0, 0)
            self._thread.join(timeout=3)
        self._thread = None
        self._tid = 0


def make_backend():
    """The keys of this computer (the tests put their own here)."""
    return WindowsBackend() if WINDOWS else NullBackend()


class Hotkeys:
    """The keys of the screen reader's actions, held while they are wanted: ``set({action: "Ctrl+Shift+R"})``,
    ``clear()``; a key pressed calls ``on_press(action)``."""

    def __init__(self, on_press, backend=None):
        self.on_press = on_press
        self.backend = backend
        self._lock = threading.Lock()
        self._numbers: dict[int, str] = {}
        self.held: dict[str, str] = {}
        self.errors: dict[str, str] = {}

    def _press(self, number: int) -> None:
        action = self._numbers.get(number)
        if action:
            try:
                self.on_press(action)
            except Exception:
                log.exception("a key's action failed")

    def set(self, bindings: dict[str, str], alone: bool = False) -> dict[str, str]:
        """Hold these keys (and no others): what could not be held, and why.  (``alone``: as parse.)"""
        with self._lock:
            wanted: dict[int, tuple[int, int]] = {}
            numbers: dict[int, str] = {}
            errors: dict[str, str] = {}
            for index, (action, text) in enumerate(sorted(bindings.items()), start=1):
                if not text:
                    continue
                try:
                    wanted[index] = parse(text, alone=alone)
                    numbers[index] = action
                except KeyError_ as err:
                    errors[action] = str(err)
            if self.backend is None:
                if not wanted and not self._numbers:
                    self.held, self.errors = {}, errors
                    return errors
                self.backend = make_backend()
                self.backend.start(self._press)
            failed = self.backend.apply(wanted)
            self._numbers = {n: a for n, a in numbers.items() if n not in failed}
            for number, why in failed.items():
                errors[numbers[number]] = why
            self.held = {action: bindings[action] for action in self._numbers.values()}
            self.errors = errors
            return errors

    def clear(self) -> None:
        self.set({})

    def close(self) -> None:
        with self._lock:
            backend, self.backend = self.backend, None
            self._numbers = {}
            self.held = {}
        if backend is not None:
            try:
                backend.apply({})
            finally:
                backend.close()
