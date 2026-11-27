# SPDX-License-Identifier: LicenseRef-Sluka
# Copyright (c) 2026 Sluka. Part of Sluka Desktop; see LICENSE.txt.
"""The clipboard, for the game text menu (Windows only): what is copied, and a game's lines put there.

Windows tells a window of the app each time the clipboard changes
(AddClipboardFormatListener); the text then on it is read, and passed on
unless it was the app that put it there, or it was copied in one of Sluka's
own windows.  Lines are put on the clipboard by the same window, marked so
that Windows' clipboard history (Win+V) does not keep each of them.

The window has a thread of its own that does nothing but answer it: a
program that holds the clipboard has to answer what Windows and other
programs ask it promptly, or they wait.
"""

from __future__ import annotations

import ctypes
import itertools
import logging
import queue
import sys
import threading
import time
from ctypes import wintypes

log = logging.getLogger("sluka.games")

WINDOWS = sys.platform == "win32"

CF_UNICODETEXT = 13
GMEM_MOVEABLE = 0x0002
WM_CLOSE = 0x0010
WM_DESTROY = 0x0002
WM_CLIPBOARDUPDATE = 0x031D
WM_APP_WRITE = 0x8000 + 0x51
HWND_MESSAGE = -3
ERROR_CLASS_ALREADY_EXISTS = 1410
#: The most of the clipboard's text that is read.
READ_MOST = 200_000
#: Each watch registers a window class of its own: a class keeps the window procedure it was registered with,
#: which must not outlive the watch that made it.
_classes = itertools.count(1)


class _Api:
    def __init__(self):
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        LRESULT = ctypes.c_ssize_t
        HWND, UINT, WPARAM, LPARAM, BOOL, HANDLE = (wintypes.HWND, wintypes.UINT, ctypes.c_size_t, ctypes.c_ssize_t,
                                                     wintypes.BOOL, wintypes.HANDLE)
        self.WNDPROC = ctypes.WINFUNCTYPE(LRESULT, HWND, UINT, WPARAM, LPARAM)

        class WNDCLASSW(ctypes.Structure):
            _fields_ = [
                ("style", UINT), ("lpfnWndProc", self.WNDPROC), ("cbClsExtra", ctypes.c_int), ("cbWndExtra", ctypes.c_int),
                ("hInstance", HANDLE), ("hIcon", HANDLE), ("hCursor", HANDLE), ("hbrBackground", HANDLE),
                ("lpszMenuName", wintypes.LPCWSTR), ("lpszClassName", wintypes.LPCWSTR),
            ]

        class MSG(ctypes.Structure):
            _fields_ = [("hwnd", HWND), ("message", UINT), ("wParam", WPARAM), ("lParam", LPARAM), ("time", wintypes.DWORD),
                        ("pt_x", ctypes.c_long), ("pt_y", ctypes.c_long)]

        self.WNDCLASSW, self.MSG = WNDCLASSW, MSG

        def fn(lib, name, restype, *argtypes):
            f = getattr(lib, name)
            f.restype, f.argtypes = restype, argtypes
            return f

        self.RegisterClassW = fn(user32, "RegisterClassW", wintypes.ATOM, ctypes.POINTER(WNDCLASSW))
        self.CreateWindowExW = fn(user32, "CreateWindowExW", HWND, wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD,
                                  ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, HWND, HANDLE, HANDLE, ctypes.c_void_p)
        self.DestroyWindow = fn(user32, "DestroyWindow", BOOL, HWND)
        self.DefWindowProcW = fn(user32, "DefWindowProcW", LRESULT, HWND, UINT, WPARAM, LPARAM)
        self.GetMessageW = fn(user32, "GetMessageW", BOOL, ctypes.POINTER(MSG), HWND, UINT, UINT)
        self.TranslateMessage = fn(user32, "TranslateMessage", BOOL, ctypes.POINTER(MSG))
        self.DispatchMessageW = fn(user32, "DispatchMessageW", LRESULT, ctypes.POINTER(MSG))
        self.PostMessageW = fn(user32, "PostMessageW", BOOL, HWND, UINT, WPARAM, LPARAM)
        self.PostQuitMessage = fn(user32, "PostQuitMessage", None, ctypes.c_int)
        self.AddClipboardFormatListener = fn(user32, "AddClipboardFormatListener", BOOL, HWND)
        self.RemoveClipboardFormatListener = fn(user32, "RemoveClipboardFormatListener", BOOL, HWND)
        self.OpenClipboard = fn(user32, "OpenClipboard", BOOL, HWND)
        self.CloseClipboard = fn(user32, "CloseClipboard", BOOL)
        self.EmptyClipboard = fn(user32, "EmptyClipboard", BOOL)
        self.GetClipboardData = fn(user32, "GetClipboardData", HANDLE, UINT)
        self.SetClipboardData = fn(user32, "SetClipboardData", HANDLE, UINT, HANDLE)
        self.GetClipboardOwner = fn(user32, "GetClipboardOwner", HWND)
        self.RegisterClipboardFormatW = fn(user32, "RegisterClipboardFormatW", UINT, wintypes.LPCWSTR)
        self.GetForegroundWindow = fn(user32, "GetForegroundWindow", HWND)
        self.GetWindowThreadProcessId = fn(user32, "GetWindowThreadProcessId", wintypes.DWORD, HWND, ctypes.POINTER(wintypes.DWORD))
        self.GlobalAlloc = fn(kernel32, "GlobalAlloc", HANDLE, UINT, ctypes.c_size_t)
        self.GlobalFree = fn(kernel32, "GlobalFree", HANDLE, HANDLE)
        self.GlobalLock = fn(kernel32, "GlobalLock", ctypes.c_void_p, HANDLE)
        self.GlobalUnlock = fn(kernel32, "GlobalUnlock", BOOL, HANDLE)
        self.GlobalSize = fn(kernel32, "GlobalSize", ctypes.c_size_t, HANDLE)
        self.GetModuleHandleW = fn(kernel32, "GetModuleHandleW", HANDLE, wintypes.LPCWSTR)


class Clipboard:
    """The clipboard's text as it changes (``on_text(text, mine)``; ``mine``: copied in one of the app's own
    windows), and lines put on it (``put``)."""

    def __init__(self, on_text, own_pid: int):
        self.on_text = on_text
        self.own_pid = own_pid
        self.hwnd = None
        self.watching = False
        self.error = ""
        self._writes: queue.SimpleQueue = queue.SimpleQueue()
        self._thread: threading.Thread | None = None
        self._started = threading.Event()
        self._api = None
        self._proc = None
        self._formats: list[int] = []
        self._last_read = ("", 0.0)

    def start(self) -> bool:
        if not WINDOWS:
            self.error = "not Windows"
            return False
        if self._thread is not None and self._thread.is_alive():
            return True
        self._started.clear()
        self._thread = threading.Thread(target=self._run, name="sluka-clipboard", daemon=True)
        self._thread.start()
        self._started.wait(5.0)
        return bool(self.hwnd)

    def stop(self) -> None:
        if self.hwnd and self._api is not None:
            self._api.PostMessageW(self.hwnd, WM_CLOSE, 0, 0)
        thread = self._thread
        if thread is not None:
            thread.join(3.0)
        self._thread = None

    def put(self, text: str) -> None:
        """A line on the clipboard (from any thread; done on the clipboard's own)."""
        if not self.hwnd or self._api is None:
            return
        self._writes.put(str(text))
        self._api.PostMessageW(self.hwnd, WM_APP_WRITE, 0, 0)

    # ---------------------------------------------------------------- the window's thread

    def _run(self) -> None:
        try:
            api = self._api = _Api()
        except Exception as err:
            self.error = f"the clipboard functions could not be had ({err})"
            self._started.set()
            return
        self._proc = api.WNDPROC(self._wndproc)
        instance = api.GetModuleHandleW(None)
        name = f"SlukaDesktopClipboard{next(_classes)}"
        self._class = klass = api.WNDCLASSW()
        klass.lpfnWndProc = self._proc
        klass.hInstance = instance
        klass.lpszClassName = name
        if not api.RegisterClassW(ctypes.byref(klass)) and ctypes.get_last_error() != ERROR_CLASS_ALREADY_EXISTS:
            self.error = f"Windows refused the clipboard's window (error {ctypes.get_last_error()})"
            self._started.set()
            return
        hwnd = api.CreateWindowExW(0, name, "Sluka clipboard", 0, 0, 0, 0, 0,
                                   wintypes.HWND(HWND_MESSAGE), None, instance, None)
        if not hwnd:
            self.error = f"Windows refused the clipboard's window (error {ctypes.get_last_error()})"
            self._started.set()
            return
        self.hwnd = hwnd
        self._formats = [api.RegisterClipboardFormatW(name) for name in ("CanIncludeInClipboardHistory", "CanUploadToCloudClipboard")]
        self.watching = bool(api.AddClipboardFormatListener(hwnd))
        if not self.watching:
            self.error = f"Windows does not tell this app of the clipboard's changes (error {ctypes.get_last_error()})"
        self._started.set()
        msg = api.MSG()
        while api.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            api.TranslateMessage(ctypes.byref(msg))
            api.DispatchMessageW(ctypes.byref(msg))
        self.hwnd = None
        self.watching = False

    def _wndproc(self, hwnd, message, wparam, lparam):
        api = self._api
        try:
            if message == WM_CLIPBOARDUPDATE:
                self._changed(hwnd)
                return 0
            if message == WM_APP_WRITE:
                while True:
                    try:
                        text = self._writes.get_nowait()
                    except queue.Empty:
                        break
                    self._write(hwnd, text)
                return 0
            if message == WM_CLOSE:
                api.RemoveClipboardFormatListener(hwnd)
                api.DestroyWindow(hwnd)
                return 0
            if message == WM_DESTROY:
                api.PostQuitMessage(0)
                return 0
        except Exception:
            log.exception("a clipboard message (%#x) could not be handled", message)
        return api.DefWindowProcW(hwnd, message, wparam, lparam)

    def _open(self, hwnd) -> bool:
        # Another program may hold it for a moment.
        for _ in range(12):
            if self._api.OpenClipboard(hwnd):
                return True
            time.sleep(0.015)
        return False

    def _changed(self, hwnd) -> None:
        api = self._api
        owner = api.GetClipboardOwner()
        if owner and int(owner) == int(hwnd or 0):
            return  # what the app itself put there
        mine = self._in_front_is_ours()
        if not self._open(hwnd):
            return
        text = None
        try:
            handle = api.GetClipboardData(CF_UNICODETEXT)
            size = api.GlobalSize(handle) if handle else 0
            if size:
                pointer = api.GlobalLock(handle)
                if pointer:
                    try:
                        # UTF-16, ending at its first nought (or where the memory ends).
                        raw = ctypes.string_at(pointer, min(size, READ_MOST * 2) & ~1)
                        text = raw.decode("utf-16-le", "replace").split("\x00", 1)[0]
                    finally:
                        api.GlobalUnlock(handle)
        finally:
            api.CloseClipboard()
        if text is None:
            return
        # Some programs set the clipboard twice for one copy.
        now = time.monotonic()
        if text == self._last_read[0] and now - self._last_read[1] < 0.5:
            return
        self._last_read = (text, now)
        try:
            self.on_text(text, mine)
        except Exception:
            log.exception("copied text could not be passed on")

    def _in_front_is_ours(self) -> bool:
        api = self._api
        hwnd = api.GetForegroundWindow()
        if not hwnd:
            return False
        pid = wintypes.DWORD(0)
        api.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        return int(pid.value) == self.own_pid

    def _write(self, hwnd, text: str) -> bool:
        api = self._api
        data = (text + "\x00").encode("utf-16-le")
        handle = api.GlobalAlloc(GMEM_MOVEABLE, len(data))
        if not handle:
            return False
        pointer = api.GlobalLock(handle)
        if not pointer:
            api.GlobalFree(handle)
            return False
        ctypes.memmove(pointer, data, len(data))
        api.GlobalUnlock(handle)
        if not self._open(hwnd):
            api.GlobalFree(handle)
            return False
        try:
            api.EmptyClipboard()
            if not api.SetClipboardData(CF_UNICODETEXT, handle):
                api.GlobalFree(handle)
                return False
            # Not kept in Windows' clipboard history, nor sent to the cloud: a game says a great many lines.
            for fmt in self._formats:
                if not fmt:
                    continue
                flag = api.GlobalAlloc(GMEM_MOVEABLE, 4)
                if not flag:
                    continue
                p = api.GlobalLock(flag)
                if p:
                    ctypes.memmove(p, b"\x00\x00\x00\x00", 4)
                    api.GlobalUnlock(flag)
                if not api.SetClipboardData(fmt, flag):
                    api.GlobalFree(flag)
            return True
        finally:
            api.CloseClipboard()
