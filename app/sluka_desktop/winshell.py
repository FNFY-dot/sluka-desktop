# SPDX-License-Identifier: LicenseRef-Sluka
# Copyright (c) 2026 Sluka. Part of Sluka Desktop; see LICENSE.txt.
"""The desktop windows on Windows: Sluka's pages in Windows' own web view, with no browser.

What ``gtkshell`` is on Tails, this is on Windows.  Each of the app's windows
is a window of this program's own -- its title, its icon, its place in the
taskbar -- with a WebView2 view filling it: the engine of Edge, which comes
with Windows itself (``webview2``).  One more view, in a window that is never
shown, holds Sluka's background worker, as the never-shown view on Tails does.

The pages are served by ``host.Host`` over HTTP on the loopback address
(``httpd.Server``), as for the browser shell: a WebView2 view is a Chromium
page, the same as a browser's, so the page script (``web/shim.js``) and the
answers to the two tests Sluka's files make of their own address are the
same.  What the shell adds is what a browser would not do:

*   it knows each of its views, and tells each page which one it is (a name
    the page sends along with its calls to the host), so "close this tab",
    "bring that window forward" and "this film will not play" reach the
    right window;
*   links to websites are handed to the user's own browser, and nothing but
    Sluka's own pages is shown in the app's windows;
*   the web view goes full screen with a video, downloads land in the app's
    downloads folder, and the window menu (Alt+Space, or a right click on the
    title bar) has what the menu of the Tails windows has;
*   the floating subtitles (``bar``) are a window of their own: as large as
    the screen, see-through, over every other, and shaped to what their page
    draws, so that the pointer goes through everywhere else.

Every call into WebView2 is made on the one thread that runs the window
messages: the calls the host gets from the HTTP threads are handed to it.
"""

from __future__ import annotations

import ctypes
import json
import logging
import math
import ntpath
import os
import queue
import signal
import sys
import threading
import time
import urllib.parse
import webbrowser
from concurrent.futures import Future, TimeoutError as FutureTimeout
from ctypes import (POINTER, Structure, byref, c_int, c_int32, c_short, c_size_t, c_ssize_t, c_ubyte, c_uint, c_uint32, c_ushort, c_void_p,
                    c_wchar_p)
from pathlib import Path

from . import APP_NAME, LICENCE_NOTE, __version__, com
from . import webview2 as wv2
from .com import ComError
from .config import Config
from .tell import problem, say

log = logging.getLogger("sluka.shell")

PAGES = {
    "": "dashboard/dashboard.html",
    "home": "dashboard/dashboard.html",
    "dashboard": "dashboard/dashboard.html",
    "books": "books/books.html",
    "videos": "videos/videos.html",
    "audio": "audio/audio.html",
}

#: A request for a page the app is already showing is answered with that window
#: for this long after start: Sluka opens its dashboard itself on a first run.
REUSE_SECONDS = 20
#: How long a closed window's page is kept alive, out of sight: Sluka writes a
#: grade a moment after it is made, and writes what is owed when its page is hidden.
CLOSE_GRACE_MS = 1200
#: After the last window, for the calls its page made as it went to finish.
QUIT_GRACE_MS = 700
#: How often the message loop wakes by itself (for Ctrl+C, and to free what the engine let go of).
TICK_MS = 250
#: How long the engine may take to start; the first start on a slow disk takes a while.
START_SECONDS = 90.0
#: How long the host's threads wait for the window thread to do what they asked.
CALL_SECONDS = 20.0

CLASS_NAME = "SlukaDesktopWindow"
#: The floating subtitles' window, which is of another kind: no frame, no taskbar button, a black (see-through) ground.
BAR_CLASS_NAME = "SlukaDesktopBar"
#: How often the floating subtitles' window looks where the pointer is, while clicks go through it.
BAR_WATCH_MS = 50
#: And how often it otherwise wakes, to stay over every other window (a game as large as the screen is one too).
BAR_TICK_MS = 1000
BAR_TOPMOST_SECONDS = 2.0
#: Sluka Vision's window, laid over a game's: of the floating subtitles' kind, kept out of pictures of the screen while
#: the screen is what it reads.
VISION_CLASS_NAME = "SlukaDesktopVision"
VISION_TICK_MS = 1000
#: SetWindowDisplayAffinity: seen on the screen, never in a picture of it (Windows 10 2004 and later).
WDA_NONE, WDA_EXCLUDEFROMCAPTURE = 0x0, 0x11
#: Who the windows are to the taskbar: Sluka's own, with its icon, not Python's.
APP_USER_MODEL_ID = "SlukaDesktop.Sluka"

#: Set before any page script runs, in every page of a view: which view the page is in (see shim.js, api()).
VIEW_SCRIPT = ("try { Object.defineProperty(globalThis, '__SLUKA_VIEW__', "
               "{ value: %s, configurable: false, enumerable: false, writable: false }); } catch (e) {}")

# ---------------------------------------------------------------- Windows' numbers

WM_DESTROY = 0x0002
WM_MOVE = 0x0003
WM_SIZE = 0x0005
WM_SETFOCUS = 0x0007
WM_CLOSE = 0x0010
WM_MOUSEACTIVATE = 0x0021
WM_GETMINMAXINFO = 0x0024
WM_WINDOWPOSCHANGING = 0x0046
WM_STYLECHANGING = 0x007C
WM_DISPLAYCHANGE = 0x007E
WM_SYSCOMMAND = 0x0112
WM_TIMER = 0x0113
WM_INITMENU = 0x0116
WM_MOVING = 0x0216
WM_DPICHANGED = 0x02E0
WM_APP = 0x8000
WM_APP_CALL = WM_APP + 1

WS_OVERLAPPEDWINDOW = 0x00CF0000
WS_POPUP = 0x80000000
WS_VISIBLE = 0x10000000
WS_CLIPCHILDREN = 0x02000000
WS_EX_TOPMOST, WS_EX_TRANSPARENT, WS_EX_TOOLWINDOW = 0x00000008, 0x00000020, 0x00000080
WS_EX_LAYERED, WS_EX_NOACTIVATE = 0x00080000, 0x08000000
CW_USEDEFAULT = -0x80000000
GWL_STYLE, GWL_EXSTYLE = -16, -20
HWND_MESSAGE = -3
HWND_TOPMOST = -1
MA_NOACTIVATE = 3
VK_CONTROL = 0x11
RGN_OR = 2
BLACK_BRUSH = 4
DWM_BB_ENABLE, DWM_BB_BLURREGION = 0x1, 0x2
RDW_INVALIDATE, RDW_ERASE, RDW_FRAME, RDW_ALLCHILDREN = 0x1, 0x4, 0x400, 0x80

SW_HIDE, SW_SHOWNORMAL, SW_MAXIMIZE, SW_SHOWNOACTIVATE, SW_SHOW, SW_MINIMIZE, SW_RESTORE = 0, 1, 3, 4, 5, 6, 9
SWP_NOSIZE, SWP_NOMOVE, SWP_NOZORDER, SWP_NOACTIVATE, SWP_FRAMECHANGED, SWP_NOOWNERZORDER = 0x1, 0x2, 0x4, 0x10, 0x20, 0x200
SWP_SHOWWINDOW = 0x40
MONITOR_DEFAULTTONULL, MONITOR_DEFAULTTOPRIMARY, MONITOR_DEFAULTTONEAREST = 0, 1, 2

MB_OK, MB_YESNO = 0x0, 0x4
MB_ICONWARNING, MB_ICONQUESTION, MB_ICONINFORMATION = 0x30, 0x20, 0x40
MB_SETFOREGROUND = 0x10000
IDYES = 6

MF_STRING, MF_SEPARATOR, MF_CHECKED = 0x0, 0x800, 0x8
IMAGE_ICON, LR_LOADFROMFILE = 1, 0x10
SM_CXICON, SM_CYICON, SM_CXSMICON, SM_CYSMICON = 11, 12, 49, 50
IDC_ARROW = 32512
COLOR_WINDOW = 5
COINIT_APARTMENTTHREADED, COINIT_DISABLE_OLE1DDE = 0x2, 0x4
RPC_E_CHANGED_MODE = com._signed(0x80010106)

OFN_HIDEREADONLY, OFN_NOCHANGEDIR, OFN_ALLOWMULTISELECT = 0x4, 0x8, 0x200
OFN_PATHMUSTEXIST, OFN_FILEMUSTEXIST, OFN_EXPLORER = 0x800, 0x1000, 0x80000

TIMER_TICK, TIMER_CLOSE, TIMER_RELOAD, TIMER_QUIT, TIMER_BAR, TIMER_VISION = 1, 2, 3, 4, 5, 6

#: The window menu's own entries (the low four bits of a WM_SYSCOMMAND are Windows').
MENU_RELOAD, MENU_ZOOM_IN, MENU_ZOOM_OUT, MENU_ZOOM_RESET = 0x0010, 0x0020, 0x0030, 0x0040
MENU_MPV, MENU_DATA, MENU_DEVTOOLS, MENU_ABOUT, MENU_BAR, MENU_BAR_THROUGH = 0x0050, 0x0060, 0x0070, 0x0080, 0x0090, 0x00A0
MENU_LICENSES = 0x00B0

#: What a page may have without asking: the clipboard (Sluka copies words and sentences), several
#: downloads at once (exports), sound without a click (reading aloud), the fonts of this computer, and
#: storage that is not cleared to make room (Sluka's word lists are kept in the page's storage too).
ALLOWED_PERMISSIONS = {6, 7, 9, 10, 13}
#: What only the app's own pages may have without asking: the network of this computer and its own
#: address, which is where the app's host is (newer engines ask for these).
OWN_PAGE_PERMISSIONS = {14, 15}
#: What Sluka has no use for.  Everything else is the web view's own to ask the user about.
DENIED_PERMISSIONS = {3, 4, 5, 12}

# ---------------------------------------------------------------- Windows' types

HWND = c_void_p
WPARAM = c_size_t
LPARAM = c_ssize_t
LRESULT = c_ssize_t
WNDPROC = com.FUNCTYPE(LRESULT, HWND, c_uint, WPARAM, LPARAM)
RECT = wv2.RECT


class POINT(Structure):
    _fields_ = [("x", c_int32), ("y", c_int32)]


class MSG(Structure):
    _fields_ = [("hwnd", HWND), ("message", c_uint), ("wParam", WPARAM), ("lParam", LPARAM),
                ("time", c_uint32), ("pt", POINT), ("lPrivate", c_uint32)]


class WNDCLASSEXW(Structure):
    _fields_ = [("cbSize", c_uint), ("style", c_uint), ("lpfnWndProc", WNDPROC), ("cbClsExtra", c_int),
                ("cbWndExtra", c_int), ("hInstance", c_void_p), ("hIcon", c_void_p), ("hCursor", c_void_p),
                ("hbrBackground", c_void_p), ("lpszMenuName", c_wchar_p), ("lpszClassName", c_wchar_p),
                ("hIconSm", c_void_p)]


class WINDOWPOS(Structure):
    _fields_ = [("hwnd", HWND), ("hwndInsertAfter", HWND), ("x", c_int), ("y", c_int), ("cx", c_int), ("cy", c_int),
                ("flags", c_uint)]


class STYLESTRUCT(Structure):
    _fields_ = [("styleOld", c_uint32), ("styleNew", c_uint32)]


class MINMAXINFO(Structure):
    _fields_ = [("ptReserved", POINT), ("ptMaxSize", POINT), ("ptMaxPosition", POINT),
                ("ptMinTrackSize", POINT), ("ptMaxTrackSize", POINT)]


class MONITORINFO(Structure):
    _fields_ = [("cbSize", c_uint32), ("rcMonitor", RECT), ("rcWork", RECT), ("dwFlags", c_uint32)]


class WINDOWPLACEMENT(Structure):
    _fields_ = [("length", c_uint), ("flags", c_uint), ("showCmd", c_uint), ("ptMinPosition", POINT),
                ("ptMaxPosition", POINT), ("rcNormalPosition", RECT)]


class DWM_BLURBEHIND(Structure):
    _fields_ = [("dwFlags", c_uint32), ("fEnable", c_int), ("hRgnBlur", c_void_p), ("fTransitionOnMaximized", c_int)]


class OPENFILENAMEW(Structure):
    _fields_ = [("lStructSize", c_uint32), ("hwndOwner", HWND), ("hInstance", c_void_p), ("lpstrFilter", c_void_p),
                ("lpstrCustomFilter", c_wchar_p), ("nMaxCustFilter", c_uint32), ("nFilterIndex", c_uint32),
                ("lpstrFile", c_void_p), ("nMaxFile", c_uint32), ("lpstrFileTitle", c_wchar_p), ("nMaxFileTitle", c_uint32),
                ("lpstrInitialDir", c_wchar_p), ("lpstrTitle", c_wchar_p), ("Flags", c_uint32), ("nFileOffset", c_ushort),
                ("nFileExtension", c_ushort), ("lpstrDefExt", c_wchar_p), ("lCustData", LPARAM), ("lpfnHook", c_void_p),
                ("lpTemplateName", c_wchar_p), ("pvReserved", c_void_p), ("dwReserved", c_uint32), ("FlagsEx", c_uint32)]


class Win32:
    """The functions of Windows the shell calls, each with its types: every handle is as wide as a pointer."""

    def __init__(self):
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        ole32 = ctypes.WinDLL("ole32")
        shell32 = ctypes.WinDLL("shell32")
        gdi32 = ctypes.WinDLL("gdi32")
        BOOL, UINT, DWORD, INT = c_int, c_uint, c_uint32, c_int

        def bind(library, name, restype, *argtypes, optional=False):
            try:
                function = getattr(library, name)
            except AttributeError:
                if optional:
                    return None
                raise
            function.restype, function.argtypes = restype, list(argtypes)
            return function

        self.RegisterClassExW = bind(user32, "RegisterClassExW", c_ushort, POINTER(WNDCLASSEXW))
        self.CreateWindowExW = bind(user32, "CreateWindowExW", HWND, DWORD, c_wchar_p, c_wchar_p, DWORD, INT, INT, INT, INT,
                                    HWND, c_void_p, c_void_p, c_void_p)
        self.DefWindowProcW = bind(user32, "DefWindowProcW", LRESULT, HWND, UINT, WPARAM, LPARAM)
        self.DestroyWindow = bind(user32, "DestroyWindow", BOOL, HWND)
        self.ShowWindow = bind(user32, "ShowWindow", BOOL, HWND, INT)
        self.UpdateWindow = bind(user32, "UpdateWindow", BOOL, HWND)
        self.SetForegroundWindow = bind(user32, "SetForegroundWindow", BOOL, HWND)
        self.GetForegroundWindow = bind(user32, "GetForegroundWindow", HWND)
        self.IsIconic = bind(user32, "IsIconic", BOOL, HWND)
        self.SetWindowTextW = bind(user32, "SetWindowTextW", BOOL, HWND, c_wchar_p)
        self.GetClientRect = bind(user32, "GetClientRect", BOOL, HWND, POINTER(RECT))
        self.GetWindowRect = bind(user32, "GetWindowRect", BOOL, HWND, POINTER(RECT))
        self.SetWindowPos = bind(user32, "SetWindowPos", BOOL, HWND, HWND, INT, INT, INT, INT, UINT)
        if ctypes.sizeof(c_void_p) == 8:
            self.GetWindowLongPtrW = bind(user32, "GetWindowLongPtrW", c_ssize_t, HWND, INT)
            self.SetWindowLongPtrW = bind(user32, "SetWindowLongPtrW", c_ssize_t, HWND, INT, c_ssize_t)
        else:  # 32-bit Windows has them only as the older names
            self.GetWindowLongPtrW = bind(user32, "GetWindowLongW", c_ssize_t, HWND, INT)
            self.SetWindowLongPtrW = bind(user32, "SetWindowLongW", c_ssize_t, HWND, INT, c_ssize_t)
        self.GetWindowPlacement = bind(user32, "GetWindowPlacement", BOOL, HWND, POINTER(WINDOWPLACEMENT))
        self.SetWindowPlacement = bind(user32, "SetWindowPlacement", BOOL, HWND, POINTER(WINDOWPLACEMENT))
        self.MonitorFromWindow = bind(user32, "MonitorFromWindow", c_void_p, HWND, DWORD)
        self.GetMonitorInfoW = bind(user32, "GetMonitorInfoW", BOOL, c_void_p, POINTER(MONITORINFO))
        self.GetMessageW = bind(user32, "GetMessageW", BOOL, POINTER(MSG), HWND, UINT, UINT)
        self.TranslateMessage = bind(user32, "TranslateMessage", BOOL, POINTER(MSG))
        self.DispatchMessageW = bind(user32, "DispatchMessageW", LRESULT, POINTER(MSG))
        self.PostMessageW = bind(user32, "PostMessageW", BOOL, HWND, UINT, WPARAM, LPARAM)
        self.PostQuitMessage = bind(user32, "PostQuitMessage", None, INT)
        self.SetTimer = bind(user32, "SetTimer", c_size_t, HWND, c_size_t, UINT, c_void_p)
        self.KillTimer = bind(user32, "KillTimer", BOOL, HWND, c_size_t)
        self.LoadCursorW = bind(user32, "LoadCursorW", c_void_p, c_void_p, c_void_p)
        self.LoadImageW = bind(user32, "LoadImageW", c_void_p, c_void_p, c_wchar_p, UINT, INT, INT, UINT)
        self.GetSystemMetrics = bind(user32, "GetSystemMetrics", INT, INT)
        self.GetSystemMenu = bind(user32, "GetSystemMenu", c_void_p, HWND, BOOL)
        self.AppendMenuW = bind(user32, "AppendMenuW", BOOL, c_void_p, UINT, c_size_t, c_wchar_p)
        self.MessageBoxW = bind(user32, "MessageBoxW", INT, HWND, c_wchar_p, c_wchar_p, UINT)
        self.AllowSetForegroundWindow = bind(user32, "AllowSetForegroundWindow", BOOL, DWORD)
        self.GetDpiForWindow = bind(user32, "GetDpiForWindow", UINT, HWND, optional=True)
        self.GetDpiForSystem = bind(user32, "GetDpiForSystem", UINT, optional=True)
        self.SetProcessDpiAwarenessContext = bind(user32, "SetProcessDpiAwarenessContext", BOOL, c_void_p, optional=True)
        self.SetProcessDPIAware = bind(user32, "SetProcessDPIAware", BOOL, optional=True)
        self.GetModuleHandleW = bind(kernel32, "GetModuleHandleW", c_void_p, c_wchar_p)
        self.CoInitializeEx = bind(ole32, "CoInitializeEx", com.HRESULT, c_void_p, DWORD)
        self.SetCurrentProcessExplicitAppUserModelID = bind(shell32, "SetCurrentProcessExplicitAppUserModelID", com.HRESULT,
                                                            c_wchar_p, optional=True)
        self.CreateSolidBrush = bind(gdi32, "CreateSolidBrush", c_void_p, DWORD)
        # For the floating subtitles' window: its shape, its see-through ground, and clicks that go through it.
        self.GetStockObject = bind(gdi32, "GetStockObject", c_void_p, INT, optional=True)
        self.CreateRectRgn = bind(gdi32, "CreateRectRgn", c_void_p, INT, INT, INT, INT, optional=True)
        self.CombineRgn = bind(gdi32, "CombineRgn", INT, c_void_p, c_void_p, c_void_p, INT, optional=True)
        self.DeleteObject = bind(gdi32, "DeleteObject", BOOL, c_void_p, optional=True)
        self.SetWindowRgn = bind(user32, "SetWindowRgn", INT, HWND, c_void_p, BOOL, optional=True)
        self.SetLayeredWindowAttributes = bind(user32, "SetLayeredWindowAttributes", BOOL, HWND, DWORD, c_ubyte, DWORD, optional=True)
        self.GetCursorPos = bind(user32, "GetCursorPos", BOOL, POINTER(POINT), optional=True)
        self.GetAsyncKeyState = bind(user32, "GetAsyncKeyState", c_short, INT, optional=True)
        self.MonitorFromPoint = bind(user32, "MonitorFromPoint", c_void_p, POINT, DWORD, optional=True)
        self.CheckMenuItem = bind(user32, "CheckMenuItem", DWORD, c_void_p, UINT, UINT, optional=True)
        self.RedrawWindow = bind(user32, "RedrawWindow", BOOL, HWND, c_void_p, c_void_p, UINT, optional=True)
        self.SetWindowDisplayAffinity = bind(user32, "SetWindowDisplayAffinity", BOOL, HWND, DWORD, optional=True)
        self.GetWindowDisplayAffinity = bind(user32, "GetWindowDisplayAffinity", BOOL, HWND, POINTER(DWORD), optional=True)
        self.IsWindowVisible = bind(user32, "IsWindowVisible", BOOL, HWND, optional=True)
        try:
            comdlg32 = ctypes.WinDLL("comdlg32")
            self.GetOpenFileNameW = bind(comdlg32, "GetOpenFileNameW", BOOL, POINTER(OPENFILENAMEW))
        except OSError:
            self.GetOpenFileNameW = None
        try:
            dwmapi = ctypes.WinDLL("dwmapi")
            self.DwmSetWindowAttribute = bind(dwmapi, "DwmSetWindowAttribute", com.HRESULT, HWND, DWORD, c_void_p, DWORD)
            self.DwmEnableBlurBehindWindow = bind(dwmapi, "DwmEnableBlurBehindWindow", com.HRESULT, HWND, POINTER(DWM_BLURBEHIND),
                                                  optional=True)
        except OSError:
            self.DwmSetWindowAttribute = None
            self.DwmEnableBlurBehindWindow = None

    @staticmethod
    def last_error() -> int:
        return ctypes.get_last_error() if hasattr(ctypes, "get_last_error") else 0


def _as_long(value: int) -> int:
    """A window style as Windows' 32-bit LONG (WS_POPUP is its sign bit)."""
    value &= 0xFFFFFFFF
    return value - (1 << 32) if value & 0x80000000 else value


class Unavailable(Exception):
    """Windows' web view cannot be used here; the reason is said in words for the user."""


def system_dark() -> bool:
    """Whether Windows is set to dark for apps."""
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize") as key:
            value, _kind = winreg.QueryValueEx(key, "AppsUseLightTheme")
        return int(value) == 0
    except (ImportError, OSError, ValueError):
        return False


class View:
    """One web view and the window it is in: one of the app's windows, or the never-shown one of the worker."""

    def __init__(self, shell: "Shell", url: str, hidden: bool = False, kind: str = "tab"):
        self.shell = shell
        self.url = url
        self.hidden = hidden
        self.kind = kind
        self.token = shell.new_token("bg" if hidden else "w")
        self.hwnd = 0
        self.controller: wv2.Controller | None = None
        self.webview: wv2.WebView | None = None
        self.tab_id = None
        self.closing = False
        self.gone = False
        self.fullscreen = False
        self._restore = None
        self.offered_mpv = 0.0
        self.created = time.monotonic()
        self.kept_hidden = 0  # (times something asked this never-shown window to show itself, or showed it)
        self.asked_shown = False  # (... said in the log once each way)
        self.found_shown = False

    def path(self) -> str:
        return urllib.parse.urlsplit(self.url or "").path

    def __repr__(self) -> str:
        return f"<View {self.token} {self.path()}>"


class Shell:
    """The application: its windows and their web views, one engine behind them, and the message loop."""

    def __init__(self, config: Config, runtime: wv2.Runtime, origin: str, first_url: str, api=None, entry=None):
        self.config = config
        self.runtime = runtime
        self.origin = origin
        self.first_url = first_url
        self.api = api
        self.entry = entry
        self.host = None
        self.environment: wv2.Environment | None = None
        self.engine_version = ""
        self.options = None
        self.views: list[View] = []
        self.by_hwnd: dict[int, View] = {}
        self.msg_hwnd = 0
        self.hinstance = None
        self.started = time.monotonic()
        self.quitting = False
        self.ended = False
        self.dark = False
        self.icon_big = self.icon_small = None
        self._tokens = 0
        self._calls: queue.SimpleQueue = queue.SimpleQueue()
        self._ui_thread = threading.current_thread()
        self._proc = None
        self._stop_asked = False
        self._engine_gone = False
        self.calls: list[dict] = []  # what pages asked of the windows (the host's shell-log)
        # The floating subtitles: their view, the screen their window covers, and the parts of it drawn on.
        self.bar_view: View | None = None
        self.bar_screen = (0, 0, 0, 0)
        self.bar_rects: list[tuple[int, int, int, int]] = []
        self.bar_live: list[tuple[int, int, int, int]] = []
        self.bar_whole = False
        self.bar_lets_through = False
        self.bar_takes_pointer = True
        self._bar_class = None
        self._bar_topmost_at = 0.0
        # Sluka Vision's window: its view, the game's inside it covers, and the parts of it drawn on.
        self.vision_view: View | None = None
        self.vision_area = (0, 0, 0, 0)
        self.vision_frame = (0, 0, 0, 0)
        self.vision_rects: list[tuple[int, int, int, int]] = []
        self.vision_shows = True
        self._vision_class = None
        #: Its window left out of pictures of the screen (while the screen is what Sluka Vision reads: vision.py), or in
        #: them -- screenshots, recordings -- while the game's own window is.  Out, until told.
        self.vision_kept_out = True
        self._vision_said_out = False

    # ------------------------------------------------------------ start

    def new_token(self, prefix: str) -> str:
        self._tokens += 1
        return f"{prefix}{self._tokens}"

    def _setup_process(self) -> None:
        api = self.api
        hr = api.CoInitializeEx(None, COINIT_APARTMENTTHREADED | COINIT_DISABLE_OLE1DDE)
        if hr == RPC_E_CHANGED_MODE:
            raise Unavailable("This program's main thread was set up for COM in a way Windows' web view cannot use.")
        # Sharp text on every screen: the engine scales itself, so the windows say they can.
        done = False
        if api.SetProcessDpiAwarenessContext is not None:
            done = bool(api.SetProcessDpiAwarenessContext(c_void_p(-4)))  # per monitor, v2
        if not done and api.SetProcessDPIAware is not None:
            api.SetProcessDPIAware()
        if api.SetCurrentProcessExplicitAppUserModelID is not None:
            api.SetCurrentProcessExplicitAppUserModelID(APP_USER_MODEL_ID)
        self.hinstance = api.GetModuleHandleW(None)
        self.dark = system_dark()

    def _register_class(self) -> None:
        api = self.api
        self._wndproc_thunk = WNDPROC(self._wndproc)
        icon = None
        try:
            from .iconfile import ensure_icon

            icon = ensure_icon(self.config)
        except Exception:
            log.exception("Sluka's icon could not be made")
        if icon is not None:
            self.icon_big = api.LoadImageW(None, str(icon), IMAGE_ICON, api.GetSystemMetrics(SM_CXICON),
                                           api.GetSystemMetrics(SM_CYICON), LR_LOADFROMFILE)
            self.icon_small = api.LoadImageW(None, str(icon), IMAGE_ICON, api.GetSystemMetrics(SM_CXSMICON),
                                             api.GetSystemMetrics(SM_CYSMICON), LR_LOADFROMFILE)
        background = api.CreateSolidBrush(0x00202020) if self.dark else c_void_p(COLOR_WINDOW + 1)
        klass = WNDCLASSEXW()
        klass.cbSize = ctypes.sizeof(WNDCLASSEXW)
        klass.style = 0x0003  # CS_HREDRAW | CS_VREDRAW
        klass.lpfnWndProc = self._wndproc_thunk
        klass.hInstance = self.hinstance
        klass.hIcon = self.icon_big
        klass.hIconSm = self.icon_small
        klass.hCursor = api.LoadCursorW(None, c_void_p(IDC_ARROW))
        klass.hbrBackground = background
        klass.lpszClassName = CLASS_NAME
        self._class = klass
        if not api.RegisterClassExW(byref(klass)):
            raise Unavailable(f"Windows refused the app's kind of window (error {api.last_error()}).")

    def _make_message_window(self) -> int:
        hwnd = self.api.CreateWindowExW(0, CLASS_NAME, f"{APP_NAME} messages", 0, 0, 0, 0, 0,
                                        c_void_p(HWND_MESSAGE), None, self.hinstance, None)
        if not hwnd:
            raise Unavailable(f"Windows refused the app a window for its messages (error {self.api.last_error()}).")
        return int(hwnd)

    def start_engine(self) -> None:
        """Windows' web view, started for the app (or Unavailable, saying why)."""
        if self.api is None:
            self.api = Win32()
        self._setup_process()
        self._register_class()
        self.msg_hwnd = self._make_message_window()
        self.api.SetTimer(self.msg_hwnd, TIMER_TICK, TICK_MS, None)

        arguments = wv2.quote_arguments(wv2.engine_arguments(self.config))
        self.options = wv2.EnvironmentOptions(arguments=arguments)
        result: dict = {}

        def done(hr: int, ptr: int) -> None:
            result["hr"] = hr
            if hr >= 0 and ptr:
                result["environment"] = wv2.Environment.borrowed(ptr)

        folder = Path(self.config.webview_dir)
        try:
            folder.mkdir(parents=True, exist_ok=True)
        except OSError as err:
            raise Unavailable(f"The web view's data folder could not be made ({folder}: {err}).") from err
        log.info("starting %s, engine switches: %s", self.runtime.describe(), arguments)
        try:
            wv2.create_environment(self.runtime, str(folder), self.options, done, entry=self.entry)
        except ComError as err:
            raise Unavailable(f"Windows' web view could not be started: {err}.") from err
        except (OSError, AttributeError) as err:
            raise Unavailable(f"Windows' web view could not be loaded from {self.runtime.dll} ({err}).") from err
        self._loop(until=lambda: "hr" in result, timeout=START_SECONDS)
        if "hr" not in result:
            raise Unavailable("Windows' web view did not start within a minute and a half.")
        if result["hr"] < 0 or "environment" not in result:
            raise Unavailable(f"Windows' web view could not be started ({com.describe(result['hr'])}).")
        self.environment = result["environment"]
        try:
            self.engine_version = self.environment.version()
        except ComError:
            self.engine_version = self.runtime.version
        log.info("Windows' web view is up: WebView2 %s; it asked for %s", self.engine_version, ", ".join(self.options.asked) or "no options")

    def describe(self) -> str:
        return f"WebView2 {self.engine_version or self.runtime.version} ({self.runtime.folder}), the app's own windows; pages at {self.origin}"

    def run(self, host) -> int:
        """Show the app, and go on until its last window is closed."""
        self.host = host
        self.started = time.monotonic()
        try:
            background = View(self, f"{self.origin}/__sluka__/background.html", hidden=True)
            self.make_window(background, 640, 480, visible=False)
            self.views.append(background)
            self.start_view(background)
            self.open_window(self.first_url)
            bar = self._bar()
            if bar is not None and bar.on:
                # Left on when the app last ended: there again.
                self._open_bar()
            self._loop()
        finally:
            self._teardown()
        if self._engine_gone:
            return 4
        return 0

    # ------------------------------------------------------------ the message loop

    def _loop(self, until=None, timeout: float | None = None) -> bool:
        """Window messages, until ``until()`` says so (True), the time is up or the app ends (False)."""
        api = self.api
        msg = MSG()
        deadline = time.monotonic() + timeout if timeout else None
        while True:
            if until is not None and until():
                return True
            if deadline is not None and time.monotonic() > deadline:
                return False
            got = api.GetMessageW(byref(msg), None, 0, 0)
            if got == 0:  # WM_QUIT
                self.quitting = True
                return False
            if got == -1:
                log.error("the window messages could not be read (error %s)", api.last_error())
                return False
            api.TranslateMessage(byref(msg))
            api.DispatchMessageW(byref(msg))

    def _wndproc(self, hwnd, message, wparam, lparam):
        try:
            hwnd = int(hwnd or 0)
            if hwnd and hwnd == self.msg_hwnd:
                if message == WM_APP_CALL:
                    self._run_calls()
                    return 0
                if message == WM_TIMER:
                    if wparam == TIMER_TICK:
                        self._tick()
                    elif wparam == TIMER_QUIT:
                        self.api.KillTimer(hwnd, TIMER_QUIT)
                        self.api.PostQuitMessage(0)
                    return 0
            else:
                view = self.by_hwnd.get(hwnd)
                if view is not None:
                    answer = self._view_message(view, message, wparam, lparam)
                    if answer is not None:
                        return answer
        except Exception:
            log.exception("a window message (%#x) could not be handled", message)
        return self.api.DefWindowProcW(hwnd, message, wparam, lparam)

    def _tick(self) -> None:
        com.collect()
        self._keep_hidden()
        if self._stop_asked:
            self._stop_asked = False
            self._close_everything()

    def _keep_hidden(self) -> None:
        """The never-shown windows (the worker's page, the web view check's) put out of sight again, whatever showed
        them and however: seen, one is an empty white window that does nothing and cannot be closed, there until the
        app ends.  (What showed it is said once in the log, as far as the window tells.)"""
        api = self.api
        visible = getattr(api, "IsWindowVisible", None)
        if visible is None:
            return
        for view in list(self.views):
            if not view.hidden or not view.hwnd or view.gone or not visible(view.hwnd):
                continue
            view.kept_hidden += 1
            if not view.found_shown:
                view.found_shown = True
                log.warning("the never-shown window of %s was found on the screen: it is hidden again (%s)", view.path(),
                            self._window_note(view.hwnd))
            api.ShowWindow(view.hwnd, SW_HIDE)

    def _window_note(self, hwnd: int) -> str:
        """What the log says of a window: its styles and whether it is kept out of pictures of the screen."""
        api = self.api
        parts = []
        try:
            parts.append(f"style {api.GetWindowLongPtrW(hwnd, GWL_STYLE) & 0xFFFFFFFF:#010x}")
            parts.append(f"extended {api.GetWindowLongPtrW(hwnd, GWL_EXSTYLE) & 0xFFFFFFFF:#010x}")
        except Exception:
            pass
        affinity = getattr(api, "GetWindowDisplayAffinity", None)
        if affinity is not None:
            value = c_uint32(0)
            try:
                if affinity(hwnd, byref(value)):
                    parts.append(f"display affinity {value.value:#x}")
            except Exception:
                pass
        return ", ".join(parts) or "nothing more is known"

    def _view_message(self, view: View, message: int, wparam: int, lparam: int):
        api = self.api
        if message == WM_WINDOWPOSCHANGING and view.hidden and lparam:
            # The never-shown windows (the worker's page, the web view check's) stay out of sight, whatever asks
            # for them to be shown: seen, one is an empty white window that does nothing.
            pos = WINDOWPOS.from_address(lparam)
            if pos.flags & SWP_SHOWWINDOW:
                pos.flags &= ~SWP_SHOWWINDOW
                view.kept_hidden += 1
                if not view.asked_shown:
                    view.asked_shown = True
                    log.warning("the never-shown window of %s was asked to show itself: it stays hidden", view.path())
            return None
        if view.hidden:
            if message == WM_STYLECHANGING and lparam and (wparam & 0xFFFFFFFF) == (GWL_STYLE & 0xFFFFFFFF):
                # ... nor made to show by its style.
                change = STYLESTRUCT.from_address(lparam)
                if change.styleNew & WS_VISIBLE and not change.styleOld & WS_VISIBLE:
                    change.styleNew &= ~WS_VISIBLE
                    view.kept_hidden += 1
                    if not view.asked_shown:
                        view.asked_shown = True
                        log.warning("the never-shown window of %s was given a style that shows it: it stays hidden", view.path())
                return 0
            if message == WM_CLOSE:
                # Closed, it would take the app's background worker with it: put out of sight, and nothing more.
                api.ShowWindow(view.hwnd, SW_HIDE)
                return 0
        if view.kind == "bar":
            answer = self._bar_message(view, message, wparam, lparam)
            if answer is not None:
                return answer
        if view.kind == "vision":
            answer = self._vision_message(view, message, wparam, lparam)
            if answer is not None:
                return answer
        if message == WM_SIZE:
            self._fit(view)
            return 0
        if message in (WM_MOVE, WM_MOVING):
            if view.controller:
                try:
                    view.controller.notify_moved()
                except ComError:
                    pass
            return None
        if message == WM_SETFOCUS:
            if view.controller and not view.hidden:
                try:
                    view.controller.move_focus()
                except ComError:
                    pass
            return 0
        if message == WM_GETMINMAXINFO and lparam:
            info = MINMAXINFO.from_address(lparam)
            scale = self.scale(view.hwnd)
            info.ptMinTrackSize.x, info.ptMinTrackSize.y = int(420 * scale), int(320 * scale)
            return 0
        if message == WM_DPICHANGED and lparam and not view.fullscreen:
            wanted = RECT.from_address(lparam)
            api.SetWindowPos(view.hwnd, None, wanted.left, wanted.top, wanted.right - wanted.left, wanted.bottom - wanted.top,
                             SWP_NOZORDER | SWP_NOACTIVATE)
            return 0
        if message == WM_CLOSE:
            self.close_view(view)
            return 0
        if message == WM_TIMER:
            if wparam == TIMER_CLOSE:
                api.KillTimer(view.hwnd, TIMER_CLOSE)
                self._destroy(view)
            elif wparam == TIMER_RELOAD:
                api.KillTimer(view.hwnd, TIMER_RELOAD)
                if view.webview and not view.gone:
                    try:
                        view.webview.reload()
                    except ComError as err:
                        log.warning("the page could not be loaded again: %s", err)
            return 0
        if message == WM_SYSCOMMAND:
            command = wparam & 0xFFF0
            if command in (MENU_RELOAD, MENU_ZOOM_IN, MENU_ZOOM_OUT, MENU_ZOOM_RESET, MENU_MPV, MENU_DATA, MENU_DEVTOOLS, MENU_ABOUT,
                           MENU_BAR, MENU_BAR_THROUGH, MENU_LICENSES):
                self._menu(view, command)
                return 0
            return None
        if message == WM_INITMENU:
            bar = self._bar()
            check = getattr(api, "CheckMenuItem", None)
            if bar is not None and check is not None and wparam:
                check(c_void_p(wparam), MENU_BAR, MF_CHECKED if bar.on else 0)
                check(c_void_p(wparam), MENU_BAR_THROUGH, MF_CHECKED if bar.state.get("through") else 0)
            return None
        if message == WM_DESTROY:
            self.by_hwnd.pop(view.hwnd, None)
            return 0
        return None

    # ------------------------------------------------------------ work handed over from other threads

    def pick_folder(self, title: str, remember: str = "") -> str:
        """A folder chosen in Windows' own folder window, over the window of Sluka's in front; "" for none."""
        from .folderdialog import pick_folder

        owner = 0
        try:
            front = int(self.api.GetForegroundWindow() or 0)
            owner = front if front in self.by_hwnd and not self.by_hwnd[front].hidden else 0
        except Exception:
            owner = 0
        return pick_folder(title, owner, remember)

    def post(self, job) -> None:
        """Have ``job()`` done on the window thread, soon; from any thread."""
        if self.ended or not self.msg_hwnd:
            return
        self._calls.put(job)
        self.api.PostMessageW(self.msg_hwnd, WM_APP_CALL, 0, 0)

    def call(self, job, timeout: float = CALL_SECONDS):
        """``job()`` done on the window thread, and its answer; None if the app is ending or it took too long."""
        if threading.current_thread() is self._ui_thread:
            return job()
        if self.ended:
            return None
        future: Future = Future()

        def run() -> None:
            if not future.set_running_or_notify_cancel():
                return
            try:
                future.set_result(job())
            except BaseException as err:  # handed back to the thread that asked
                future.set_exception(err)

        self.post(run)
        try:
            return future.result(timeout)
        except FutureTimeout:
            future.cancel()
            log.warning("the window thread did not get to a call in %d s", timeout)
            return None

    def _run_calls(self) -> None:
        while True:
            try:
                job = self._calls.get_nowait()
            except queue.Empty:
                return
            try:
                job()
            except Exception:
                log.exception("a call on the window thread failed")

    # ------------------------------------------------------------ windows

    def scale(self, hwnd=None) -> float:
        api = self.api
        dpi = 0
        if hwnd and api.GetDpiForWindow is not None:
            dpi = api.GetDpiForWindow(hwnd)
        if not dpi and api.GetDpiForSystem is not None:
            dpi = api.GetDpiForSystem()
        return (dpi or 96) / 96.0

    def make_window(self, view: View, width: int, height: int, visible: bool = True) -> int:
        api = self.api
        scale = self.scale()
        style = WS_OVERLAPPEDWINDOW | WS_CLIPCHILDREN
        hwnd = api.CreateWindowExW(0, CLASS_NAME, APP_NAME, style, CW_USEDEFAULT, CW_USEDEFAULT,
                                   int(width * scale) if width else CW_USEDEFAULT,
                                   int(height * scale) if height else CW_USEDEFAULT,
                                   None, None, self.hinstance, None)
        if not hwnd:
            raise OSError(f"Windows refused a window (error {api.last_error()})")
        view.hwnd = int(hwnd)
        self.by_hwnd[view.hwnd] = view
        if not visible:
            return view.hwnd
        self._keep_on_screen(view.hwnd)
        self._dark_title_bar(view.hwnd)
        self._add_menu(view)
        api.ShowWindow(view.hwnd, SW_SHOWNORMAL)
        api.UpdateWindow(view.hwnd)
        api.SetForegroundWindow(view.hwnd)
        return view.hwnd

    def _dark_title_bar(self, hwnd: int) -> None:
        """The window's title bar black, as Setup's is (tools/installer/theme_windows.go darkTitleBar), whatever
        Windows' settings give title bars: dark mode, then (Windows 11) its colour, its text's and its edge's.
        Where Windows cannot, nothing happens."""
        api = self.api
        if api.DwmSetWindowAttribute is None:
            return
        on = c_int(1)
        for attribute in (20, 19):  # DWMWA_USE_IMMERSIVE_DARK_MODE, and its number before Windows 10 20H1
            if api.DwmSetWindowAttribute(hwnd, attribute, byref(on), ctypes.sizeof(on)) == 0:
                break
        # DWMWA_CAPTION_COLOR #111110, DWMWA_TEXT_COLOR #F2F0EB, DWMWA_BORDER_COLOR #2E2E2B (COLORREF: 0x00BBGGRR)
        for attribute, color in ((35, 0x00101111), (36, 0x00EBF0F2), (34, 0x002B2E2E)):
            value = c_uint32(color)
            api.DwmSetWindowAttribute(hwnd, attribute, byref(value), ctypes.sizeof(value))

    def _keep_on_screen(self, hwnd: int) -> None:
        """A window larger than the screen it opens on (1280 x 860 at 150 % is 1920 x 1290) is made to fit it."""
        api = self.api
        info = MONITORINFO()
        info.cbSize = ctypes.sizeof(MONITORINFO)
        rect = RECT()
        if not api.GetMonitorInfoW(api.MonitorFromWindow(hwnd, MONITOR_DEFAULTTONEAREST), byref(info)) or not api.GetWindowRect(hwnd, byref(rect)):
            return
        work = info.rcWork
        room_w, room_h = work.right - work.left, work.bottom - work.top
        width, height = rect.right - rect.left, rect.bottom - rect.top
        if room_w <= 0 or room_h <= 0:
            return
        inside = rect.left >= work.left and rect.top >= work.top and rect.right <= work.right and rect.bottom <= work.bottom
        if inside:
            return
        width, height = min(width, int(room_w * 0.95)), min(height, int(room_h * 0.95))
        left = min(max(rect.left, work.left), work.right - width)
        top = min(max(rect.top, work.top), work.bottom - height)
        api.SetWindowPos(hwnd, None, left, top, width, height, SWP_NOZORDER | SWP_NOACTIVATE)

    def _add_menu(self, view: View) -> None:
        api = self.api
        menu = api.GetSystemMenu(view.hwnd, 0)
        if not menu:
            return
        groups = [[(MENU_RELOAD, "Reload this page\tF5")],
                  [(MENU_ZOOM_IN, "Larger\tCtrl +"), (MENU_ZOOM_OUT, "Smaller\tCtrl -"), (MENU_ZOOM_RESET, "Normal size\tCtrl 0")]]
        last = []
        if self._bar() is not None:
            last.append((MENU_BAR, "Floating subtitles"))
            last.append((MENU_BAR_THROUGH, "Clicks go through the floating subtitles"))
        if self.host is not None and getattr(self.host, "mpv", None) and self.config.mpv_enabled:
            last.append((MENU_MPV, "Play a video in mpv with Sluka…"))
        last.append((MENU_DATA, "Open Sluka's data folder"))
        if self.config.devtools:
            last.append((MENU_DEVTOOLS, "Developer tools\tF12"))
        last.append((MENU_LICENSES, "Licences and notices"))
        last.append((MENU_ABOUT, f"About {APP_NAME}"))
        for group in groups + [last]:
            api.AppendMenuW(menu, MF_SEPARATOR, 0, None)
            for command, text in group:
                api.AppendMenuW(menu, MF_STRING, command, text)

    def _fit(self, view: View) -> None:
        if not view.controller or view.hidden:
            return
        rect = RECT()
        self.api.GetClientRect(view.hwnd, byref(rect))
        try:
            view.controller.set_bounds(rect.left, rect.top, rect.right, rect.bottom)
        except ComError as err:
            log.debug("%s", err)

    def open_windows(self) -> list[View]:
        return [v for v in self.views if not v.hidden and not v.closing]

    def open_window(self, url: str, kind: str = "tab", width=0, height=0, state=None) -> View:
        view = View(self, url, hidden=False, kind=kind)
        popup = kind == "popup"
        self.make_window(view, int(width or 0) or (520 if popup else self.config.window_width),
                         int(height or 0) or (680 if popup else self.config.window_height), visible=True)
        self.views.append(view)
        self.start_view(view)
        if state in ("maximized", "fullscreen", "minimized"):
            self.set_state(view, {"state": state})
        return view

    #: The Look up key's small windows (dictionaries.py open): an offline dictionary's page of the app's ("dict"), and a
    #: site online ("dictweb") -- in a web view of its own, its own data folder (webview2-dictionaries), with nothing of
    #: the app's: no token, none of its pages, none of its storage, so the sites and the app never meet.  Each is kept,
    #: and a later look up goes into it; over the game, as the panel it came from was.
    DICT_SIZE = (520, 680)

    def open_dictionary(self, url: str, own: bool) -> None:
        self.post(lambda: self._open_dictionary(url, own))

    def _open_dictionary(self, url: str, own: bool) -> None:
        kind = "dict" if own else "dictweb"
        full = f"{self.origin}{url}" if own else url
        view = next((v for v in self.views if v.kind == kind and not v.closing and not v.gone and v.hwnd), None)
        if view is None:
            view = View(self, full, hidden=False, kind=kind)
            self.make_window(view, *self.DICT_SIZE, visible=True)
            self.views.append(view)
            if own:
                self.start_view(view)
            else:
                self._start_web_view(view)
        else:
            view.url = full
            if view.webview is not None:
                self._navigate(view)
        self.present(view)
        self.api.SetWindowPos(view.hwnd, HWND_TOPMOST, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE)

    def _start_web_view(self, view: View) -> None:
        """A site's web view, from the sites' own engine: started the first time one is asked for."""
        environment = getattr(self, "web_environment", None)
        if environment is not None:
            try:
                environment.create_controller(view.hwnd, lambda hr, ptr: self._view_ready(view, hr, ptr))
            except ComError as err:
                self._view_failed(view, err.hresult)
            return
        waiting = getattr(self, "_web_waiting", None)
        if waiting is not None:
            waiting.append(view)
            return
        self._web_waiting = [view]
        folder = Path(self.config.data_dir) / "webview2-dictionaries"

        def done(hr: int, ptr: int) -> None:
            views, self._web_waiting = self._web_waiting or [], None
            if hr < 0 or not ptr:
                log.error("the web view for dictionary sites could not be started (%s)", com.describe(hr))
                for v in views:
                    self._view_failed(v, hr)
                return
            self.web_environment = wv2.Environment.borrowed(ptr)
            for v in views:
                if not v.gone and not v.closing:
                    self._start_web_view(v)

        try:
            folder.mkdir(parents=True, exist_ok=True)
            # (its own command line: the sites get none of the app's pages' freedoms, only its network mode)
            self.web_options = wv2.EnvironmentOptions(arguments=wv2.quote_arguments(wv2.site_arguments(self.config)))
            wv2.create_environment(self.runtime, str(folder), self.web_options, done, entry=self.entry)
        except (ComError, OSError) as err:
            self._web_waiting = None
            log.error("the web view for dictionary sites could not be started: %s", err)
            self._view_failed(view, getattr(err, "hresult", -1))

    def present(self, view: View) -> None:
        api = self.api
        if api.IsIconic(view.hwnd):
            api.ShowWindow(view.hwnd, SW_RESTORE)
        api.ShowWindow(view.hwnd, SW_SHOW)
        api.SetForegroundWindow(view.hwnd)

    def set_state(self, view: View, args: dict) -> None:
        api = self.api
        state = args.get("state")
        if state == "minimized":
            api.ShowWindow(view.hwnd, SW_MINIMIZE)
        elif state == "maximized":
            self.set_fullscreen(view, False)
            api.ShowWindow(view.hwnd, SW_MAXIMIZE)
        elif state == "fullscreen":
            self.set_fullscreen(view, True)
        elif state == "normal":
            self.set_fullscreen(view, False)
            api.ShowWindow(view.hwnd, SW_RESTORE)
        width, height = args.get("width"), args.get("height")
        if isinstance(width, int) and isinstance(height, int) and width > 100 and height > 100 and not view.fullscreen:
            scale = self.scale(view.hwnd)
            api.SetWindowPos(view.hwnd, None, 0, 0, int(width * scale), int(height * scale), SWP_NOMOVE | SWP_NOZORDER | SWP_NOACTIVATE)

    def set_fullscreen(self, view: View, on: bool) -> None:
        """The whole screen for the window (a video asked for it), or its place back."""
        api = self.api
        if on == view.fullscreen:
            return
        if on:
            placement = WINDOWPLACEMENT()
            placement.length = ctypes.sizeof(WINDOWPLACEMENT)
            api.GetWindowPlacement(view.hwnd, byref(placement))
            style = api.GetWindowLongPtrW(view.hwnd, GWL_STYLE)
            view._restore = (style, placement)
            info = MONITORINFO()
            info.cbSize = ctypes.sizeof(MONITORINFO)
            if not api.GetMonitorInfoW(api.MonitorFromWindow(view.hwnd, MONITOR_DEFAULTTONEAREST), byref(info)):
                return
            api.SetWindowLongPtrW(view.hwnd, GWL_STYLE, _as_long(((style & 0xFFFFFFFF) & ~WS_OVERLAPPEDWINDOW) | WS_POPUP))
            screen = info.rcMonitor
            api.SetWindowPos(view.hwnd, None, screen.left, screen.top, screen.right - screen.left, screen.bottom - screen.top,
                             SWP_NOOWNERZORDER | SWP_FRAMECHANGED)
            view.fullscreen = True
        else:
            view.fullscreen = False
            if view._restore is not None:
                style, placement = view._restore
                view._restore = None
                api.SetWindowLongPtrW(view.hwnd, GWL_STYLE, style)
                api.SetWindowPlacement(view.hwnd, byref(placement))
                api.SetWindowPos(view.hwnd, None, 0, 0, 0, 0,
                                 SWP_NOMOVE | SWP_NOSIZE | SWP_NOZORDER | SWP_NOOWNERZORDER | SWP_FRAMECHANGED)
        self._fit(view)

    def close_view(self, view: View) -> None:
        """Out of sight at once; gone once the page has had the time to write what it owes."""
        if view.closing:
            return
        view.closing = True
        if view.controller:
            try:
                view.controller.set_visible(False)  # the page is told it is hidden, and writes what it owes
            except ComError:
                pass
        self.api.ShowWindow(view.hwnd, SW_HIDE)
        self.api.SetTimer(view.hwnd, TIMER_CLOSE, CLOSE_GRACE_MS, None)

    def _drop_view(self, view: View) -> None:
        view.gone = True
        controller, webview = view.controller, view.webview
        view.controller = view.webview = None
        if controller is not None:
            try:
                controller.close()
            except ComError:
                pass
        for item in (webview, controller):
            if item is not None:
                item.release()

    def _destroy(self, view: View) -> None:
        self._drop_view(view)
        if view.hwnd:
            self.api.DestroyWindow(view.hwnd)
            self.by_hwnd.pop(view.hwnd, None)
        if view in self.views:
            self.views.remove(view)
        if view is self.bar_view:
            self.bar_view = None
            bar = self._bar()
            if bar is not None:
                bar.page_gone()
        if view is self.vision_view:
            self.vision_view = None
            vision = self._vision()
            if vision is not None:
                vision.overlay_closed()
        # The app is its windows: the floating subtitles and Sluka Vision's go with the last of them (and the
        # subtitles come back with the app).
        if not any(not v.hidden and v.kind not in ("bar", "vision") for v in self.views):
            self.quit()

    def quit(self) -> None:
        """The last window went: the app ends a moment later (the background page with it)."""
        if self.quitting:
            return
        self.quitting = True
        log.info("the last window was closed")
        self.api.SetTimer(self.msg_hwnd, TIMER_QUIT, QUIT_GRACE_MS, None)

    def stop(self) -> None:
        """End the app (Ctrl+C, or the engine gone); from any thread or a signal handler."""
        self._stop_asked = True
        try:
            if self.msg_hwnd and not self.ended:
                self.api.PostMessageW(self.msg_hwnd, WM_APP_CALL, 0, 0)
        except Exception:
            pass

    def _close_everything(self) -> None:
        windows = self.open_windows()
        for view in windows:
            self.close_view(view)
        if not windows:
            self.quit()

    def _teardown(self) -> None:
        self.ended = True
        for view in list(self.views):
            self._drop_view(view)
            if view.hwnd:
                try:
                    self.api.DestroyWindow(view.hwnd)
                except Exception:
                    pass
        self.views.clear()
        self.by_hwnd.clear()

    def shutdown_engine(self) -> None:
        """Let go of the engine (after run, or when the app does not get as far)."""
        self.ended = True
        environment, self.environment = self.environment, None
        if environment is not None:
            environment.release()
        if self.msg_hwnd:
            try:
                self.api.KillTimer(self.msg_hwnd, TIMER_TICK)
                self.api.DestroyWindow(self.msg_hwnd)
            except Exception:
                pass
            self.msg_hwnd = 0

    # ------------------------------------------------------------ the web views

    def start_view(self, view: View) -> None:
        try:
            self.environment.create_controller(view.hwnd, lambda hr, ptr: self._view_ready(view, hr, ptr))
        except ComError as err:
            self._view_failed(view, err.hresult)

    def _view_failed(self, view: View, hr: int) -> None:
        log.error("a web view could not be made for %s (%s)", view.path(), com.describe(hr))
        if view.hidden:
            def tell_and_stop() -> None:
                self.message("Sluka's background page could not be started in Windows' web view "
                             f"({com.describe(hr)}).\nThe app cannot work without it, and ends.", None, MB_ICONWARNING)
                self.stop()

            self.post(tell_and_stop)
            return

        def tell_and_close() -> None:
            # Said first: with the last window gone the app ends, and a message still up would go with it.
            self.message(f"A window of {APP_NAME} could not be shown ({com.describe(hr)}).\n"
                         f"The log may say more: {self.config.log_dir / 'sluka-desktop.log'}", None, MB_ICONWARNING)
            if view.kind == "bar" and self._bar() is not None:
                self._bar().set_on(False)
            self.close_view(view)

        if view.kind == "vision":
            # (said in the game text menu's log, not in a box over the game)
            log.error("Sluka Vision's window could not be shown (%s)", com.describe(hr))
            self.post(lambda: self.close_view(view))
            return

        self.post(tell_and_close)

    def _view_ready(self, view: View, hr: int, ptr: int) -> None:
        if hr < 0 or not ptr:
            self._view_failed(view, hr)
            return
        controller = wv2.Controller.borrowed(ptr)
        if view.gone or view.closing:
            # Closed before its page came.
            try:
                controller.close()
            except ComError:
                pass
            controller.release()
            return
        webview = controller.webview()
        view.controller, view.webview = controller, webview
        settings = webview.settings()
        try:
            settings.configure(devtools=self.config.devtools, zoom=view.kind not in ("bar", "vision"))
        finally:
            settings.release()
        if view.kind in ("bar", "vision"):
            # Nothing under the page: where it draws nothing, what is behind the window shows.
            try:
                if not controller.set_transparent():
                    log.warning("this WebView2 cannot show a see-through page: %s stand on a ground of their own",
                                "the floating subtitles" if view.kind == "bar" else "Sluka Vision's words")
            except ComError as err:
                log.warning("the page of %s could not be made see-through: %s", view.kind, err)
            self._fit(view)
        elif view.hidden:
            # Out of sight, with a page of an ordinary size all the same, for whatever measures itself there.
            controller.set_visible(False)
            controller.set_bounds(0, 0, 1024, 768)
        else:
            self._fit(view)
            try:
                controller.move_focus()  # the keyboard to the page: the window was in front before its view came
            except ComError:
                pass
        self._watch(view)
        if view.kind == "dictweb":
            self._navigate(view)  # (a site: nothing of the app's added to its pages)
            return

        def added(result: int, _ident: str) -> None:
            if result < 0:
                log.warning("the page of %s will not know its window (%s)", view.token, com.describe(result))
            self._navigate(view)

        try:
            webview.add_script(VIEW_SCRIPT % json.dumps(view.token), added)
        except ComError as err:
            log.warning("%s", err)
            self._navigate(view)

    def _navigate(self, view: View) -> None:
        if view.gone or not view.webview:
            return
        try:
            view.webview.navigate(view.url)
        except ComError as err:
            log.error("%s could not be opened: %s", view.path(), err)

    def _watch(self, view: View) -> None:
        webview = view.webview
        events = [
            (wv2.WV_ADD_NAVIGATION_STARTING, wv2.IID_NavigationStartingEventHandler, lambda a: self._navigation_starting(view, a), "add_NavigationStarting"),
            (wv2.WV_ADD_NEW_WINDOW_REQUESTED, wv2.IID_NewWindowRequestedEventHandler, lambda a: self._new_window(view, a), "add_NewWindowRequested"),
            (wv2.WV_ADD_PERMISSION_REQUESTED, wv2.IID_PermissionRequestedEventHandler, lambda a: self._permission(view, a), "add_PermissionRequested"),
            (wv2.WV_ADD_PROCESS_FAILED, wv2.IID_ProcessFailedEventHandler, lambda a: self._process_failed(view, a), "add_ProcessFailed"),
        ]
        if view.kind == "bar":
            events.append((wv2.WV_ADD_WINDOW_CLOSE_REQUESTED, wv2.IID_WindowCloseRequestedEventHandler,
                           lambda a: self._bar_off(), "add_WindowCloseRequested"))
        elif view.kind == "vision":
            events.append((wv2.WV_ADD_WINDOW_CLOSE_REQUESTED, wv2.IID_WindowCloseRequestedEventHandler,
                           lambda a: self._close_vision(), "add_WindowCloseRequested"))
        elif not view.hidden:
            events += [
                (wv2.WV_ADD_TITLE_CHANGED, wv2.IID_DocumentTitleChangedEventHandler, lambda a: self._title_changed(view), "add_DocumentTitleChanged"),
                (wv2.WV_ADD_FULLSCREEN_CHANGED, wv2.IID_ContainsFullScreenElementChangedEventHandler, lambda a: self._fullscreen_changed(view), "add_ContainsFullScreenElementChanged"),
                (wv2.WV_ADD_WINDOW_CLOSE_REQUESTED, wv2.IID_WindowCloseRequestedEventHandler, lambda a: self.close_view(view), "add_WindowCloseRequested"),
            ]
        for index, iid, callback, what in events:
            try:
                webview.on(index, iid, callback, what)
            except ComError as err:
                log.warning("%s", err)
        try:
            if not webview.on_download(lambda a: self._download(view, a)):
                log.info("this web view runtime has no download event: downloads go where it puts them")
        except ComError as err:
            log.warning("%s", err)

    def _asked_by_own_page(self, args: int) -> bool:
        try:
            return self.is_own(wv2.permission_uri(args))
        except ComError:
            return False

    def is_own(self, url: str) -> bool:
        return url == self.origin or url.startswith(self.origin + "/") or url.startswith("blob:" + self.origin)

    def _navigation_starting(self, view: View, args: int) -> None:
        uri = wv2.navigation_uri(args)
        scheme = urllib.parse.urlsplit(uri).scheme.lower()
        if view.kind == "dictweb":
            # A dictionary site's window: the web, and only the web, in it; never a page of the app's.
            if scheme in ("http", "https") and not self.is_own(uri):
                view.url = uri
            elif scheme not in ("about", "data"):
                wv2.cancel_navigation(args)
            return
        if self.is_own(uri):
            view.url = uri
            return
        if scheme not in ("http", "https", "mailto", "file", "ftp", "ws", "wss"):
            return  # about:, data:, the engine's own error pages
        # Anywhere else is not this app's to show: a web view of Sluka's pages is not a browser.
        wv2.cancel_navigation(args)
        if scheme in ("http", "https", "mailto") and not view.hidden:
            self.post(lambda: self.open_external(uri, view))
        else:
            log.info("a page of the app was kept from going to a %s: address", scheme)

    def _new_window(self, view: View, args: int) -> None:
        uri = wv2.new_window_uri(args)
        wv2.handle_new_window(args)  # never the engine's own window: one of the app's, or the user's browser
        if view.kind == "dictweb":
            # A site's link that would open a window of its own: in the same one.
            if urllib.parse.urlsplit(uri).scheme.lower() in ("http", "https") and not self.is_own(uri):
                view.url = uri
                self.post(lambda: self._navigate(view))
            return
        if self.is_own(uri):
            # A window of its own, so the new page starts clean, with a tab number of its own.
            self.post(lambda: self.open_window(uri))
        elif urllib.parse.urlsplit(uri).scheme.lower() in ("http", "https", "mailto"):
            self.post(lambda: self.open_external(uri, view))

    def _permission(self, view: View, args: int) -> None:
        if view.kind == "dictweb":
            wv2.set_permission(args, wv2.PERMISSION_DENY)  # (a dictionary site: no camera, microphone, place, ...)
            return
        kind = wv2.permission_kind(args)
        name = wv2.PERMISSION_NAMES.get(kind, str(kind))
        if kind in ALLOWED_PERMISSIONS:
            wv2.set_permission(args, wv2.PERMISSION_ALLOW)
        elif kind in OWN_PAGE_PERMISSIONS and self._asked_by_own_page(args):
            wv2.set_permission(args, wv2.PERMISSION_ALLOW)
        elif kind in DENIED_PERMISSIONS:
            wv2.set_permission(args, wv2.PERMISSION_DENY)
            log.info("refused a page's request: %s", name)
        else:
            log.info("a page asks for %s: the web view asks you", name)

    def _process_failed(self, view: View, args: int) -> None:
        kind = wv2.failure_kind(args)
        said = wv2.FAILED_NAMES.get(kind, f"process failure {kind}")
        if kind == wv2.FAILED_BROWSER:
            log.error("%s", said)
            self.post(self._lost_engine)
        elif kind == wv2.FAILED_RENDERER:
            log.error("%s (%s); loading it again", said, "background page" if view.hidden else view.path())
            self.api.SetTimer(view.hwnd, TIMER_RELOAD, 800 if view.hidden else 500, None)
        elif kind == wv2.FAILED_UNRESPONSIVE:
            log.warning("%s (%s)", said, "background page" if view.hidden else view.path())
        else:
            log.info("%s", said)

    def _lost_engine(self) -> None:
        if self._engine_gone:
            return
        self._engine_gone = True
        self.message("Windows' web view stopped working, and the app with it.\nStart Sluka again.", None, MB_ICONWARNING)
        self.stop()

    def _title_changed(self, view: View) -> None:
        if view.webview and not view.gone:
            self.api.SetWindowTextW(view.hwnd, view.webview.title() or APP_NAME)

    def _fullscreen_changed(self, view: View) -> None:
        if view.webview and not view.gone:
            self.set_fullscreen(view, view.webview.contains_fullscreen())

    def _download(self, view: View, args: int) -> None:
        """A file a page downloads itself goes to the app's downloads folder, as Sluka's own saves do."""
        suggested = wv2.download_path(args)
        name = ntpath.basename(suggested.rstrip("\\/")) or "download"
        folder = Path(self.config.downloads_dir)
        folder.mkdir(parents=True, exist_ok=True)
        target = folder / name
        stem, suffix = target.stem, target.suffix
        n = 1
        while target.exists():
            target = folder / f"{stem} ({n}){suffix}"
            n += 1
        wv2.set_download_path(args, str(target))
        log.info("a download goes to %s", target)

    # ------------------------------------------------------------ what the host asks of the windows (HTTP threads)

    def find(self, tab_id=None, token=None) -> View | None:
        for view in self.views:
            if view.hidden:
                continue
            if (tab_id is not None and view.tab_id == tab_id) or (token is not None and view.token == token):
                return view
        return None

    def register(self, info: dict, view=None) -> None:
        token = str(view or "")
        if not token or not isinstance(info.get("tabId"), int):
            return

        def note() -> None:
            found = self.find(token=token)
            if found is not None:
                found.tab_id = info["tabId"]
                if isinstance(info.get("url"), str) and self.is_own(info["url"]):
                    found.url = info["url"]

        self.post(note)

    def request(self, op: str, args: dict, view=None) -> dict:
        token = str(view or "") or None
        self.calls.append({"op": op, **{k: v for k, v in args.items() if k in ("url", "kind", "tabId")}})
        del self.calls[:-200]
        if op == "alive":  # the browser shell's question; nothing to hold here
            return {"ok": True, "handled": False}
        if op == "external":
            url = str(args.get("url") or "")
            self.post(lambda: self.open_external(url, self.find(token=token)))
            return {"ok": True, "handled": True}
        if op == "media-failed":
            self.post(lambda: self.offer_mpv(self.find(token=token)))
            return {"ok": True, "handled": True}
        if op == "open":
            answer = self.call(lambda: self._op_open(args))
            return answer if isinstance(answer, dict) else {"ok": False, "handled": True}
        answer = self.call(lambda: self._op_window(op, args, token))
        return answer if isinstance(answer, dict) else {"ok": False, "handled": True}

    def _op_open(self, args: dict) -> dict:
        url = str(args.get("url") or "")
        if not self.is_own(url):
            self.post(lambda: self.open_external(url, None))
            return {"ok": True, "handled": True}
        if self.quitting or self.ended:
            return {"ok": False, "handled": True}
        path = urllib.parse.urlsplit(url).path
        kind = str(args.get("kind") or "tab")
        if kind == "tab" and not args.get("again") and time.monotonic() - self.started < REUSE_SECONDS:
            for view in self.open_windows():
                if view.path() == path:
                    if view.url != url and view.webview:
                        view.url = url
                        self._navigate(view)
                    self.present(view)
                    return {"ok": True, "handled": True, "reusedTabId": view.tab_id}
        view = self.open_window(url, kind=kind, width=args.get("width") or 0, height=args.get("height") or 0, state=args.get("state"))
        if args.get("again"):
            self.present(view)
        return {"ok": True, "handled": True}

    def _op_window(self, op: str, args: dict, token) -> dict:
        view = self.find(tab_id=args.get("tabId")) if args.get("tabId") is not None else self.find(token=token)
        if view is None or view.closing:
            return {"ok": False, "handled": True}
        if op == "focus":
            self.present(view)
        elif op == "close":
            self.close_view(view)
        elif op == "state":
            self.set_state(view, args)
        return {"ok": True, "handled": True}

    # ------------------------------------------------------------ the floating subtitles

    def _bar(self):
        return getattr(self.host, "bar", None) if self.host is not None else None

    def _bar_off(self) -> None:
        bar = self._bar()
        if bar is not None:
            bar.set_on(False)
        elif self.bar_view is not None:
            self.close_view(self.bar_view)

    def open_bar(self) -> None:
        """The floating subtitles' window, from any thread."""
        self.post(self._open_bar)

    def close_bar(self) -> None:
        self.post(self._close_bar)

    def bar_shape(self, rects: list, live: list, whole: bool, dpr: float) -> None:
        """The parts of the window its page draws on, in the page's pixels (``dpr`` of the screen's each); from any thread."""
        self.post(lambda: self._bar_shape(list(rects), list(live), bool(whole), float(dpr or 1.0)))

    def bar_through(self, on: bool) -> None:
        """Clicks through the floating subtitles, or not; from any thread."""
        self.post(lambda: self._bar_set_through(bool(on)))

    def bar_to_monitor(self, x: float, y: float, dpr: float):
        """The window moved to the screen the point (the page's pixels) is on: where the point is there, or None."""
        return self.call(lambda: self._bar_to_monitor(float(x), float(y), float(dpr or 1.0)))

    def _open_bar(self) -> None:
        if self.quitting or self.ended or self.environment is None:
            return
        view = self.bar_view
        if view is not None and not view.closing and not view.gone:
            return
        bar = self._bar()
        view = View(self, f"{self.origin}/__sluka__/bar.html", hidden=False, kind="bar")
        try:
            self._make_bar_window(view, bar.state.get("monitor") if bar is not None else None)
        except OSError as err:
            log.error("the floating subtitles could not be shown: %s", err)
            if bar is not None:
                bar.set_on(False)
            return
        self.bar_view = view
        self.views.append(view)
        if bar is not None and bar.state.get("through"):
            # Clicks went through it when it was put away: they do again.
            self._bar_set_through(True)
        self.start_view(view)
        log.info("the floating subtitles are shown on the screen at %s", self.bar_screen)

    def _close_bar(self) -> None:
        view = self.bar_view
        if view is not None and not view.closing:
            self.close_view(view)

    def _register_bar_class(self) -> bool:
        if self._bar_class is not None:
            return True
        api = self.api
        klass = WNDCLASSEXW()
        klass.cbSize = ctypes.sizeof(WNDCLASSEXW)
        klass.lpfnWndProc = self._wndproc_thunk
        klass.hInstance = self.hinstance
        klass.hIcon = self.icon_big
        klass.hIconSm = self.icon_small
        klass.hCursor = api.LoadCursorW(None, c_void_p(IDC_ARROW))
        # Black: on a window whose alpha Windows goes by (_see_through), no colour at all.
        stock = getattr(api, "GetStockObject", None)
        klass.hbrBackground = stock(BLACK_BRUSH) if stock is not None else None
        klass.lpszClassName = BAR_CLASS_NAME
        if not api.RegisterClassExW(byref(klass)):
            return False
        self._bar_class = klass
        return True

    def _screen_of(self, saved=None) -> tuple[int, int, int, int]:
        """The screen for the floating subtitles: the one they were on, else the one of the app's window, else the main one."""
        api = self.api
        from_point = getattr(api, "MonitorFromPoint", None)
        monitor = None
        if from_point is not None and isinstance(saved, (list, tuple)) and len(saved) == 4:
            try:
                monitor = from_point(POINT((int(saved[0]) + int(saved[2])) // 2, (int(saved[1]) + int(saved[3])) // 2), MONITOR_DEFAULTTONULL)
            except (TypeError, ValueError):
                monitor = None
        if not monitor:
            windows = [v for v in self.open_windows() if v.kind not in ("bar", "vision")]
            if windows:
                monitor = api.MonitorFromWindow(windows[-1].hwnd, MONITOR_DEFAULTTONEAREST)
        if not monitor and from_point is not None:
            monitor = from_point(POINT(0, 0), MONITOR_DEFAULTTOPRIMARY)
        info = MONITORINFO()
        info.cbSize = ctypes.sizeof(MONITORINFO)
        if monitor and api.GetMonitorInfoW(monitor, byref(info)):
            screen = info.rcMonitor
            return (screen.left, screen.top, screen.right, screen.bottom)
        return (0, 0, 1920, 1080)

    def _make_bar_window(self, view: View, saved) -> None:
        api = self.api
        if getattr(api, "SetWindowRgn", None) is None or getattr(api, "CreateRectRgn", None) is None:
            raise OSError("this Windows lacks what shapes a window")
        if not self._register_bar_class():
            raise OSError(f"Windows refused the floating subtitles' kind of window (error {api.last_error()})")
        screen = self._screen_of(saved)
        hwnd = api.CreateWindowExW(WS_EX_TOPMOST | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE, BAR_CLASS_NAME, f"{APP_NAME} subtitles",
                                   WS_POPUP | WS_CLIPCHILDREN, *self._bar_frame(screen), None, None, self.hinstance, None)
        if not hwnd:
            raise OSError(f"Windows refused a window (error {api.last_error()})")
        view.hwnd = int(hwnd)
        self.by_hwnd[view.hwnd] = view
        self.bar_screen = screen
        self.bar_lets_through = False
        self.bar_takes_pointer = True
        # Nothing of it is seen, nor takes the pointer, until its page says what it draws.
        self._bar_region(view, [], [], False)
        self._see_through(view.hwnd)
        api.ShowWindow(view.hwnd, SW_SHOWNOACTIVATE)
        api.SetTimer(view.hwnd, TIMER_BAR, BAR_TICK_MS, None)
        bar = self._bar()
        if bar is not None:
            bar.remember_screen(list(screen))

    @staticmethod
    def _bar_frame(screen) -> tuple[int, int, int, int]:
        """Where the window goes on ``screen``: all of it but its last row of pixels, so that Windows never takes
        it for a program gone full screen (and hides the taskbar for it, or holds back notifications)."""
        left, top, right, bottom = screen
        return left, top, max(1, right - left), max(1, bottom - top - 1)

    def _see_through(self, hwnd: int) -> None:
        """A window whose pixels' alpha Windows goes by, so that where nothing is drawn the screen shows through.

        Done as Tauri and GLFW do it: blur behind the window, for a region of no pixels at all.
        """
        api = self.api
        blur, make = getattr(api, "DwmEnableBlurBehindWindow", None), getattr(api, "CreateRectRgn", None)
        if blur is None or make is None:
            log.warning("Windows has no see-through windows here: the floating subtitles may show a black ground")
            return
        region = make(0, 0, -1, -1)
        try:
            hr = blur(hwnd, byref(DWM_BLURBEHIND(DWM_BB_ENABLE | DWM_BB_BLURREGION, 1, region, 0)))
        finally:
            if region and getattr(api, "DeleteObject", None) is not None:
                api.DeleteObject(region)
        if hr is not None and int(hr) < 0:
            log.warning("the floating subtitles' window could not be made see-through (%s)", com.describe(int(hr)))

    def _bar_shape(self, rects: list, live: list, whole: bool, dpr: float) -> None:
        view = self.bar_view
        if view is None or view.closing or view.gone or not view.hwnd:
            return
        self._bar_region(view, rects, live, whole, dpr)

    @staticmethod
    def _pixels(items: list, dpr: float, most: int = 24) -> list[tuple[int, int, int, int]]:
        out = []
        for item in items:
            try:
                x, y, w, h = (float(v) for v in list(item)[:4])
            except (TypeError, ValueError):
                continue
            if not all(math.isfinite(v) for v in (x, y, w, h)) or w <= 0 or h <= 0:
                continue
            out.append((math.floor(x * dpr), math.floor(y * dpr), math.ceil((x + w) * dpr), math.ceil((y + h) * dpr)))
        return out[:most]

    def _bar_region(self, view: View, rects: list, live: list, whole: bool, dpr: float = 1.0) -> None:
        """The window shaped to what its page draws: only there is it seen, and only there does it take the pointer."""
        api = self.api
        self.bar_rects = self._pixels(rects, dpr)
        self.bar_live = self._pixels(live, dpr)
        self.bar_whole = whole
        if whole:
            # Being moved: all of it, so that what is moved is never cut off on its way.
            api.SetWindowRgn(view.hwnd, None, 1)
            return
        region = api.CreateRectRgn(0, 0, 0, 0)
        for left, top, right, bottom in self.bar_rects:
            part = api.CreateRectRgn(left, top, right, bottom)
            api.CombineRgn(region, region, part, RGN_OR)
            api.DeleteObject(part)
        if not api.SetWindowRgn(view.hwnd, region, 1):
            api.DeleteObject(region)  # still this program's when Windows did not take it

    def _ex_style(self, hwnd: int, add: int = 0, remove: int = 0) -> None:
        api = self.api
        style = api.GetWindowLongPtrW(hwnd, GWL_EXSTYLE) & 0xFFFFFFFF
        changed = (style | add) & ~remove
        if changed != style:
            api.SetWindowLongPtrW(hwnd, GWL_EXSTYLE, _as_long(changed))

    def _bar_set_through(self, on: bool) -> None:
        """Clicks through the whole window (as a window with no shape would let them), but where the page says otherwise.

        A layered window marked transparent is passed over by the pointer.  How it is drawn is left as it was --
        no colour taken out, no alpha laid over it -- as GLFW does for the same; while the pointer is on a part
        that takes it anyway, or Ctrl is held on the bar, the mark comes off (_bar_watch).
        """
        view = self.bar_view
        api = self.api
        if view is None or view.closing or not view.hwnd:
            return
        self.bar_lets_through = on
        layered = getattr(api, "SetLayeredWindowAttributes", None)
        if on and layered is not None:
            self._ex_style(view.hwnd, add=WS_EX_LAYERED | WS_EX_TRANSPARENT)
            layered(view.hwnd, 0, 0, 0)
            self.bar_takes_pointer = False
        else:
            self._ex_style(view.hwnd, remove=WS_EX_LAYERED | WS_EX_TRANSPARENT)
            self.bar_takes_pointer = True
            redraw = getattr(api, "RedrawWindow", None)
            if redraw is not None:
                redraw(view.hwnd, None, None, RDW_INVALIDATE | RDW_ERASE | RDW_FRAME | RDW_ALLCHILDREN)
        api.SetTimer(view.hwnd, TIMER_BAR, BAR_WATCH_MS if self.bar_lets_through else BAR_TICK_MS, None)
        log.info("clicks %s the floating subtitles", "go through" if self.bar_lets_through else "are taken by")

    def _bar_watch(self, view: View) -> None:
        api = self.api
        now = time.monotonic()
        if now - self._bar_topmost_at >= BAR_TOPMOST_SECONDS:
            # Over every other window, a game as large as the screen included, even one that came over it later.
            self._bar_topmost_at = now
            api.SetWindowPos(view.hwnd, c_void_p(HWND_TOPMOST), 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE | SWP_NOOWNERZORDER)
        if not self.bar_lets_through:
            return
        where, keys = getattr(api, "GetCursorPos", None), getattr(api, "GetAsyncKeyState", None)
        if where is None:
            return
        point = POINT()
        if not where(byref(point)):
            return
        x, y = point.x - self.bar_screen[0], point.y - self.bar_screen[1]

        def on(rects) -> bool:
            return any(left <= x < right and top <= y < bottom for left, top, right, bottom in rects)

        ctrl = keys is not None and bool(keys(VK_CONTROL) & 0x8000)
        wanted = self.bar_whole or on(self.bar_live) or (ctrl and on(self.bar_rects))
        if wanted != self.bar_takes_pointer:
            self.bar_takes_pointer = wanted
            if wanted:
                self._ex_style(view.hwnd, remove=WS_EX_TRANSPARENT)
            else:
                self._ex_style(view.hwnd, add=WS_EX_TRANSPARENT)

    def _bar_place(self, view: View, screen) -> None:
        self.bar_screen = tuple(int(v) for v in screen)
        left, top, width, height = self._bar_frame(self.bar_screen)
        self.api.SetWindowPos(view.hwnd, c_void_p(HWND_TOPMOST), left, top, width, height, SWP_NOACTIVATE | SWP_NOOWNERZORDER)
        self._fit(view)
        bar = self._bar()
        if bar is not None:
            bar.remember_screen(list(self.bar_screen))

    def _bar_cover_again(self, view: View) -> None:
        """Its screen changed size, or the window was told another DPI: it covers its screen again, as it is now."""
        api = self.api
        info = MONITORINFO()
        info.cbSize = ctypes.sizeof(MONITORINFO)
        if api.GetMonitorInfoW(api.MonitorFromWindow(view.hwnd, MONITOR_DEFAULTTONEAREST), byref(info)):
            screen = info.rcMonitor
            self._bar_place(view, (screen.left, screen.top, screen.right, screen.bottom))

    def _bar_to_monitor(self, x: float, y: float, dpr: float):
        view = self.bar_view
        api = self.api
        from_point = getattr(api, "MonitorFromPoint", None)
        if view is None or view.closing or from_point is None or not all(math.isfinite(v) for v in (x, y, dpr)):
            return None
        sx, sy = self.bar_screen[0] + int(round(x * dpr)), self.bar_screen[1] + int(round(y * dpr))
        monitor = from_point(POINT(sx, sy), MONITOR_DEFAULTTONULL)
        info = MONITORINFO()
        info.cbSize = ctypes.sizeof(MONITORINFO)
        if not monitor or not api.GetMonitorInfoW(monitor, byref(info)):
            return None
        screen = (info.rcMonitor.left, info.rcMonitor.top, info.rcMonitor.right, info.rcMonitor.bottom)
        if screen == tuple(self.bar_screen):
            return None
        self._bar_place(view, screen)
        width, height = max(1, screen[2] - screen[0]), max(1, screen[3] - screen[1])
        log.info("the floating subtitles were taken to the screen at %s", screen)
        return {"fx": (sx - screen[0]) / width, "fy": (sy - screen[1]) / height, "screen": list(screen)}

    def _bar_message(self, view: View, message: int, wparam: int, lparam: int):
        """What the floating subtitles' window does otherwise than the app's own windows."""
        if message == WM_MOUSEACTIVATE:
            return MA_NOACTIVATE  # a click on it leaves the keyboard where it was: with the game, the reader, the player
        if message == WM_TIMER and wparam == TIMER_BAR:
            self._bar_watch(view)
            return 0
        if message in (WM_DPICHANGED, WM_DISPLAYCHANGE):
            self._bar_cover_again(view)
            return 0
        if message == WM_CLOSE:
            self._bar_off()
            return 0
        return None

    # ------------------------------------------------------------ Sluka Vision's window

    def _vision(self):
        games = getattr(self.host, "games", None) if self.host is not None else None
        return getattr(games, "vision", None) if games is not None else None

    def open_vision(self, area) -> None:
        """Sluka Vision's window, laid over the game's inside (x, y, w, h on the screen); from any thread."""
        self.post(lambda: self._open_vision(tuple(int(v) for v in list(area)[:4])))

    def close_vision(self) -> None:
        self.post(self._close_vision)

    def vision_place(self, area) -> None:
        """Over the game's inside where it is now (it was moved or made larger); from any thread."""
        self.post(lambda: self._vision_place(tuple(int(v) for v in list(area)[:4])))

    def vision_visible(self, on: bool) -> None:
        """Shown (the game, or Sluka, in front) or not; from any thread."""
        self.post(lambda: self._vision_visible(bool(on)))

    def vision_shape(self, rects: list, dpr: float) -> None:
        """The parts of the window its page draws on, in the page's pixels (``dpr`` of the screen's each); from any thread."""
        self.post(lambda: self._vision_shape(list(rects), float(dpr or 1.0)))

    def vision_keep_out(self, on: bool) -> None:
        """Its window left out of pictures of the screen, or in them (screenshots, recordings); from any thread."""
        self.post(lambda: self._vision_keep_out(bool(on)))

    def _open_vision(self, area) -> None:
        if self.quitting or self.ended or self.environment is None or len(area) != 4:
            return
        view = self.vision_view
        if view is not None and not view.closing and not view.gone:
            self._vision_place(area)
            return
        view = View(self, f"{self.origin}/__sluka__/vision.html", hidden=False, kind="vision")
        try:
            self._make_vision_window(view, area)
        except OSError as err:
            log.error("Sluka Vision's window could not be made: %s", err)
            return
        self.vision_view = view
        self.views.append(view)
        self.start_view(view)
        log.info("Sluka Vision's window is laid over the game at %s", self.vision_area)

    def _close_vision(self) -> None:
        view = self.vision_view
        if view is not None and not view.closing:
            self.close_view(view)

    def _register_vision_class(self) -> bool:
        if self._vision_class is not None:
            return True
        api = self.api
        klass = WNDCLASSEXW()
        klass.cbSize = ctypes.sizeof(WNDCLASSEXW)
        klass.lpfnWndProc = self._wndproc_thunk
        klass.hInstance = self.hinstance
        klass.hIcon = self.icon_big
        klass.hIconSm = self.icon_small
        klass.hCursor = api.LoadCursorW(None, c_void_p(IDC_ARROW))
        stock = getattr(api, "GetStockObject", None)
        klass.hbrBackground = stock(BLACK_BRUSH) if stock is not None else None
        klass.lpszClassName = VISION_CLASS_NAME
        if not api.RegisterClassExW(byref(klass)):
            return False
        self._vision_class = klass
        return True

    def _vision_frame_of(self, area) -> tuple[int, int, int, int]:
        """Where the window goes: over the game's inside -- all but its last row of pixels where that is a whole
        screen, so that Windows never takes it for a program gone full screen (as the floating subtitles' window)."""
        x, y, w, h = (int(v) for v in area)
        api = self.api
        from_point = getattr(api, "MonitorFromPoint", None)
        if from_point is not None:
            monitor = from_point(POINT(x + w // 2, y + h // 2), MONITOR_DEFAULTTONEAREST)
            info = MONITORINFO()
            info.cbSize = ctypes.sizeof(MONITORINFO)
            if monitor and api.GetMonitorInfoW(monitor, byref(info)):
                screen = info.rcMonitor
                if x <= screen.left and y <= screen.top and x + w >= screen.right and y + h >= screen.bottom:
                    h -= 1
        return x, y, max(1, w), max(1, h)

    def _make_vision_window(self, view: View, area) -> None:
        api = self.api
        if getattr(api, "SetWindowRgn", None) is None or getattr(api, "CreateRectRgn", None) is None:
            raise OSError("this Windows lacks what shapes a window")
        if not self._register_vision_class():
            raise OSError(f"Windows refused Sluka Vision's kind of window (error {api.last_error()})")
        frame = self._vision_frame_of(area)
        hwnd = api.CreateWindowExW(WS_EX_TOPMOST | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE, VISION_CLASS_NAME, f"{APP_NAME} Vision",
                                   WS_POPUP | WS_CLIPCHILDREN, *frame, None, None, self.hinstance, None)
        if not hwnd:
            raise OSError(f"Windows refused a window (error {api.last_error()})")
        view.hwnd = int(hwnd)
        self.by_hwnd[view.hwnd] = view
        self.vision_area = tuple(int(v) for v in area)
        self.vision_frame = frame
        self.vision_shows = True
        # Nothing of it is seen, nor takes the pointer, until its page says where its words are.
        self._vision_region(view, [], 1.0)
        self._see_through(view.hwnd)
        api.ShowWindow(view.hwnd, SW_SHOWNOACTIVATE)
        # Out of pictures of the screen while the screen is what is read, so that its own marks are never read back;
        # in them while the game's own window is.  (Told once it shows, as every window of the app's is.)
        self._vision_affinity(view)
        api.SetTimer(view.hwnd, TIMER_VISION, VISION_TICK_MS, None)

    def _vision_place(self, area) -> None:
        view = self.vision_view
        if view is None or view.closing or view.gone or not view.hwnd or len(area) != 4:
            return
        self.vision_area = tuple(int(v) for v in area)
        frame = self._vision_frame_of(area)
        if frame != self.vision_frame:
            self.vision_frame = frame
            self.api.SetWindowPos(view.hwnd, c_void_p(HWND_TOPMOST), *frame, SWP_NOACTIVATE | SWP_NOOWNERZORDER)
            self._fit(view)

    def _vision_keep_out(self, on: bool) -> None:
        changed = on != self.vision_kept_out
        self.vision_kept_out = on
        view = self.vision_view
        if not changed or view is None or view.closing or view.gone or not view.hwnd or not self.vision_shows:
            return  # (told as it shows)
        self._vision_affinity(view)

    def _vision_affinity(self, view: View) -> None:
        affinity = getattr(self.api, "SetWindowDisplayAffinity", None)
        done = affinity is not None and affinity(view.hwnd, WDA_EXCLUDEFROMCAPTURE if self.vision_kept_out else WDA_NONE)
        if self.vision_kept_out and not done and not self._vision_said_out:
            self._vision_said_out = True
            log.warning("Sluka Vision's window cannot be kept out of pictures of the screen here (Windows 10 2004 and "
                        "later can): read the game's own window instead (What is read, in the Sluka Vision tab)")

    def _vision_visible(self, on: bool) -> None:
        view = self.vision_view
        if view is None or view.closing or view.gone or not view.hwnd or on == self.vision_shows:
            return
        self.vision_shows = on
        self.api.ShowWindow(view.hwnd, SW_SHOWNOACTIVATE if on else SW_HIDE)
        if on:
            self._vision_affinity(view)
            self.api.SetWindowPos(view.hwnd, c_void_p(HWND_TOPMOST), 0, 0, 0, 0,
                                  SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE | SWP_NOOWNERZORDER)

    def _vision_shape(self, rects: list, dpr: float) -> None:
        view = self.vision_view
        if view is None or view.closing or view.gone or not view.hwnd:
            return
        self._vision_region(view, rects, dpr)

    def _vision_region(self, view: View, rects: list, dpr: float) -> None:
        """The window shaped to its words, card and panel: only there is it seen, and only there does it take the pointer."""
        api = self.api
        self.vision_rects = self._pixels(rects, dpr, 600)
        region = api.CreateRectRgn(0, 0, 0, 0)
        for left, top, right, bottom in self.vision_rects:
            part = api.CreateRectRgn(left, top, right, bottom)
            api.CombineRgn(region, region, part, RGN_OR)
            api.DeleteObject(part)
        if not api.SetWindowRgn(view.hwnd, region, 1):
            api.DeleteObject(region)

    def _vision_message(self, view: View, message: int, wparam: int, lparam: int):
        """What Sluka Vision's window does otherwise than the app's own windows."""
        if message == WM_MOUSEACTIVATE:
            return MA_NOACTIVATE  # a click on a word leaves the keyboard with the game
        if message == WM_TIMER and wparam == TIMER_VISION:
            if self.vision_shows:
                # Over every other window, the game as large as the screen included.
                self.api.SetWindowPos(view.hwnd, c_void_p(HWND_TOPMOST), 0, 0, 0, 0,
                                      SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE | SWP_NOOWNERZORDER)
            return 0
        if message in (WM_DPICHANGED, WM_DISPLAYCHANGE):
            # The game's inside covered again as it is (not Windows' own idea of the window's new size).
            self.api.SetWindowPos(view.hwnd, c_void_p(HWND_TOPMOST), *self.vision_frame, SWP_NOACTIVATE | SWP_NOOWNERZORDER)
            self._fit(view)
            return 0
        if message == WM_CLOSE:
            vision = self._vision()
            if vision is not None:
                vision.clear()
            else:
                self.close_view(view)
            return 0
        return None

    # ------------------------------------------------------------ the user's side of things

    def message(self, text: str, view: View | None = None, flags: int = MB_ICONINFORMATION) -> int:
        owner = view.hwnd if view is not None and not view.closing else None
        return self.api.MessageBoxW(owner, text, APP_NAME, flags | MB_SETFOREGROUND)

    def open_external(self, url: str, view: View | None) -> None:
        if not url or urllib.parse.urlsplit(url).scheme.lower() not in ("http", "https", "mailto"):
            return
        policy = self.config.external_links
        if policy == "ignore":
            return
        if policy == "ask":
            shown = url if len(url) <= 300 else url[:300] + "…"
            if self.message(f"Open this link in your web browser?\n\n{shown}", view, MB_YESNO | MB_ICONQUESTION) != IDYES:
                return
        try:
            # The user's own browser, with their own profile.
            webbrowser.open(url)
        except Exception:
            log.exception("could not hand a link to the system's browser")

    def offer_mpv(self, view: View | None) -> None:
        """A page could not play the film it was given: mpv can, and Sluka is in mpv too."""
        if view is None or view.closing or self.host is None or not getattr(self.host, "mpv", None) or not self.config.mpv_enabled:
            return
        now = time.monotonic()
        if now - view.offered_mpv < 20:
            return  # one film sets off several tries on a page
        view.offered_mpv = now
        if self.message("The app's own player cannot play this video's format.\n\n"
                        "mpv can, and Sluka's subtitles are drawn inside it. Choose the video (and its subtitles) to play in mpv?",
                        view, MB_YESNO | MB_ICONQUESTION) == IDYES:
            self.play_in_mpv(view)

    def play_in_mpv(self, view: View | None) -> None:
        files = self.choose_files(view, "Play in mpv with Sluka")
        if files and self.host is not None and self.host.mpv:
            trouble = self.host.mpv.play(files)
            if trouble:
                self.message(trouble, view, MB_ICONWARNING)

    def choose_files(self, view: View | None, title: str) -> list[str]:
        api = self.api
        if api.GetOpenFileNameW is None:
            return []
        from .mpvbridge import SUBTITLE_SUFFIXES, VIDEO_SUFFIXES

        patterns = ";".join(f"*{s}" for s in sorted(VIDEO_SUFFIXES | SUBTITLE_SUFFIXES))
        filters = ctypes.create_unicode_buffer(f"Videos and subtitles\0{patterns}\0All files\0*.*\0\0")
        size = 32768
        buffer = ctypes.create_unicode_buffer(size)
        dialog = OPENFILENAMEW()
        dialog.lStructSize = ctypes.sizeof(OPENFILENAMEW)
        dialog.hwndOwner = view.hwnd if view is not None else None
        dialog.lpstrFilter = ctypes.addressof(filters)
        dialog.lpstrFile = ctypes.addressof(buffer)
        dialog.nMaxFile = size
        dialog.lpstrTitle = title
        dialog.Flags = OFN_EXPLORER | OFN_ALLOWMULTISELECT | OFN_FILEMUSTEXIST | OFN_PATHMUSTEXIST | OFN_HIDEREADONLY | OFN_NOCHANGEDIR
        if not api.GetOpenFileNameW(byref(dialog)):
            return []
        parts = buffer[:].split("\0")
        names = []
        for part in parts:
            if not part:
                break
            names.append(part)
        if len(names) == 1:
            return names
        folder = names[0]
        return [ntpath.join(folder, name) for name in names[1:]]

    def _menu(self, view: View, command: int) -> None:
        controller, webview = view.controller, view.webview
        try:
            if command == MENU_RELOAD and webview:
                webview.reload()
            elif command in (MENU_ZOOM_IN, MENU_ZOOM_OUT, MENU_ZOOM_RESET) and controller:
                level = 1.0 if command == MENU_ZOOM_RESET else controller.zoom() * (1.1 if command == MENU_ZOOM_IN else 1 / 1.1)
                controller.set_zoom(max(0.25, min(5.0, level)))
            elif command == MENU_MPV:
                self.play_in_mpv(view)
            elif command == MENU_DATA:
                os.startfile(str(self.config.data_dir))  # type: ignore[attr-defined]  (Windows)
            elif command == MENU_DEVTOOLS and webview:
                webview.open_devtools()
            elif command == MENU_ABOUT:
                self._about(view)
            elif command == MENU_LICENSES:
                self._licences(view)
            elif command == MENU_BAR and self._bar() is not None:
                self._bar().set_on(not self._bar().on)
            elif command == MENU_BAR_THROUGH and self._bar() is not None:
                self._bar().set_through(not self._bar().state.get("through"))
        except (ComError, OSError, AttributeError) as err:
            log.warning("the window menu: %s", err)

    def _about(self, view: View) -> None:
        cfg = self.config
        lines = [
            f"{APP_NAME} {__version__}",
            f"Sluka {cfg.extension_version}",
            f"Windows' own web view: WebView2 {self.engine_version or self.runtime.version}",
            f"Network: {cfg.network_mode}",
            f"Data: {cfg.data_dir}",
            f"Saved files: {cfg.downloads_dir}",
        ]
        mpv = self.host.mpv.status() if self.host is not None and self.host.mpv else None
        if mpv is not None:
            lines.append(f"mpv: {mpv.get('players', 0)} player(s) connected")
        bar = self._bar()
        if bar is not None:
            lines.append(f"Floating subtitles: {'on' if bar.on else 'off'}")
        lines += ["", LICENCE_NOTE]
        games = getattr(self.host, "games", None) if self.host is not None else None
        lens = getattr(games, "lens", None)
        if lens is not None and lens.allowed():
            lines += ["", "Google Lens: allowed. Each picture it reads is sent to Google.",
                      "Have Sluka ask again before Google Lens next reads?"]
            if self.message("\n".join(lines), view, MB_YESNO | MB_ICONINFORMATION) == IDYES:
                lens.forget()
            return
        self.message("\n".join(lines), view)

    def _licences(self, view: View) -> None:
        """Sluka Desktop's licence agreement (LICENSE.txt), which says where the rest is: NOTICES.txt and
        the LICENSES folder, beside it."""
        agreement = Path(self.config.root) / "LICENSE.txt"
        if agreement.is_file():
            try:
                os.startfile(str(agreement))  # type: ignore[attr-defined]  (Windows)
                return
            except OSError as err:
                log.warning("the licence agreement could not be opened: %s", err)
        self.message(f"{LICENCE_NOTE}\n\nThey are in {self.config.root}.", view)


# ---------------------------------------------------------------- the app


def run_app(config: Config, page: str = "", api=None, entry=None, runtime=None) -> int:
    """The app with Windows' own web view.  Raises Unavailable when that cannot be had, before anything is shown."""
    from .browsershell import ask_running_copy, running_copy, system_ui_font
    from .devserver import EXTENSION_SCHEME_CHECKS
    from .host import Host
    from .httpd import Server

    runtime = runtime or wv2.find_runtime(config.webview_runtime)
    if runtime is None:
        raise Unavailable("Windows' own web view (the Microsoft Edge WebView2 Runtime) was not found on this computer.")
    port = config.browser_port
    origin = f"http://127.0.0.1:{port}"
    first = f"{origin}/{PAGES.get(page.strip().lower(), page or PAGES[''])}"

    if running_copy(port):
        # Started a second time: the app is running, so show it.
        if ask_running_copy(port, first):
            say(f"{APP_NAME} is already running: a window was opened.")
            return 0
        problem(f"{APP_NAME} is already running, and did not open a window when asked.")
        return 1

    crash_log = _crash_log(config)
    shell = Shell(config, runtime, origin, first, api=api, entry=entry)
    try:
        shell.start_engine()
    except Unavailable:
        shell.shutdown_engine()
        raise
    host = Host(config, shell=shell)
    host.dev_rewrites = list(EXTENSION_SCHEME_CHECKS)
    host.boot_extra = {"shell": "webview2", "pickers": bool(config.pickers), "barButton": config.bar_button, "folders": True}
    # Sluka's backup folder, chosen in Windows' own folder window (folders.py, folderdialog.py).
    host.folders.picker = lambda title, remember="": shell.pick_folder(title, remember)
    host.engine = shell.describe()
    host.ui_font = system_ui_font()
    if sys.platform == "win32":
        # The script in mpv has no fontconfig to ask there: the app reads the fonts for it.
        try:
            from .winfonts import finder_for

            host.fonts = finder_for(config)
            host.fonts.warm()
        except Exception:
            log.exception("the fonts could not be looked into")
    log.info("%s", host.engine)
    try:
        server = Server(host, port)
    except OSError as err:
        host.close()
        shell.shutdown_engine()
        # Two starts at once: the other one got there first.
        for _ in range(12):
            if running_copy(port):
                return 0 if ask_running_copy(port, first) else 1
            time.sleep(0.25)
        problem(f"The address {origin} could not be taken ({err}).\n"
                "Another program uses that port. Choose another in config.ini:  [app]  port = 47822\n"
                "(Books and dictionaries are kept by the web view under the address, so choose once.)")
        return 3

    if config.bar_enabled:
        try:
            from .bar import Bar

            host.bar = Bar(config, host)
            host.bar.shell = shell
        except Exception:
            log.exception("the floating subtitles could not be set up")
    if host.bar and getattr(config, "games_enabled", True):
        try:
            from .gametext import GameText

            host.games = GameText(config, host)
            host.games.vision.shell = shell
        except Exception:
            log.exception("the game text could not be set up")
    if config.mpv_enabled or host.bar:
        # Sluka's engine for mpv reads the floating subtitles' words too: it runs for them where mpv is off.
        try:
            from .mpvbridge import MpvBridge

            host.mpv = MpvBridge(config, players=config.mpv_enabled)
        except Exception:
            log.exception("the mpv bridge could not be set up")
    if config.anki_enabled:
        try:
            from .ankibridge import AnkiBridge

            host.anki = AnkiBridge(config, host)
        except Exception:
            log.exception("the bridge to Anki could not be set up")

    server.start()
    if host.mpv:
        host.mpv.start()
    if host.anki:
        host.anki.start()
    if host.bar:
        host.bar.start()
    if host.games:
        try:
            host.games.start()
        except Exception:
            log.exception("the game text could not be started")

    for name in ("SIGINT", "SIGTERM", "SIGBREAK"):
        sig = getattr(signal, name, None)
        if sig is not None:
            try:
                signal.signal(sig, lambda *_: shell.stop())
            except (ValueError, OSError):
                pass

    code = 0
    try:
        code = shell.run(host)
    finally:
        shell.shutdown_engine()
        server.shutdown()
        server.drain(5.0)
        host.close()
        log.info("%s %s has ended", APP_NAME, __version__)
        if crash_log is not None:
            _close_crash_log(crash_log)
    return code


def _crash_log(config: Config):
    """Where a crash inside the engine's code is written down, with the Python lines that led to it."""
    try:
        import faulthandler

        config.log_dir.mkdir(parents=True, exist_ok=True)
        handle = open(config.log_dir / "crash.log", "w", encoding="utf-8")
        handle.write(f"{APP_NAME} {__version__}: anything below is a crash, and the lines of the app that led to it.\n")
        handle.flush()
        faulthandler.enable(file=handle, all_threads=True)
        return handle
    except Exception:
        return None


def _close_crash_log(handle) -> None:
    try:
        import faulthandler

        faulthandler.disable()
        handle.close()
    except Exception:
        pass


# ---------------------------------------------------------------- sluka webview-check


def check(config: Config, api=None, entry=None, out=None, runtime=None) -> int:
    """Try Windows' web view step by step, saying each step as it is reached (``sluka webview-check``).

    The doctor runs this as a program of its own, so that a crash inside the engine's code -- which would
    take the program down with it -- still leaves the steps that came before it on the screen.
    """
    from .config import local_dir

    out = out or sys.stdout
    try:
        import faulthandler

        if sys.stderr is not None:
            faulthandler.enable()  # a crash in the engine's code still says where it happened
    except Exception:
        pass

    def step(state: str, text: str) -> None:
        try:
            print(f"{state}: {text}", file=out, flush=True)
        except (OSError, ValueError):
            pass

    runtime = runtime or wv2.find_runtime(config.webview_runtime)
    if runtime is None:
        step("failed", "no WebView2 Runtime was found")
        return 2
    step("ok", f"{runtime.describe()}, found by {runtime.source}")
    step("ok", f"its part for this Python: {runtime.dll}")
    probe_config = _ProbeConfig(config, local_dir() / "webview-check")
    shell = Shell(probe_config, runtime, "about:", "about:blank", api=api, entry=entry)
    try:
        shell.start_engine()
    except Unavailable as err:
        step("failed", str(err))
        shell.shutdown_engine()
        return 3
    step("ok", f"the engine started: WebView2 {shell.engine_version}")
    result: dict = {}
    view = View(shell, "about:blank", hidden=True)
    try:
        shell.make_window(view, 640, 480, visible=False)
        shell.views.append(view)

        def answered(hr: int, text: str) -> None:
            result["script"] = (hr, text)

        def loaded(args: int) -> None:
            result["loaded"] = wv2.navigation_succeeded(args)

        def added(hr: int, _ident: str) -> None:
            result["added"] = hr
            view.webview.navigate("about:blank")

        def ready(hr: int, ptr: int) -> None:
            result["view"] = hr
            if hr < 0 or not ptr:
                return
            controller = wv2.Controller.borrowed(ptr)
            view.controller, view.webview = controller, controller.webview()
            controller.set_visible(False)
            settings = view.webview.settings()
            try:
                settings.configure(devtools=False)
            finally:
                settings.release()
            view.webview.on(wv2.WV_ADD_NAVIGATION_COMPLETED, wv2.IID_NavigationCompletedEventHandler, loaded, "add_NavigationCompleted")
            view.webview.add_script(VIEW_SCRIPT % json.dumps("check"), added)

        shell.environment.create_controller(view.hwnd, ready)
        shell._loop(until=lambda: "loaded" in result or result.get("view", 0) < 0, timeout=45.0)
        if "view" in result and result["view"] >= 0 and view.webview:
            # Asked whether the page loaded or not: a script answers either way.
            view.webview.execute_script("navigator.userAgent", answered)
            shell._loop(until=lambda: "script" in result, timeout=20.0)
        if "view" not in result:
            step("failed", "no web view came within 45 s")
            return 4
        if result["view"] < 0:
            step("failed", f"a web view could not be made ({com.describe(result['view'])})")
            return 4
        step("ok", "a web view was made in a window of the app's own")
        if result.get("added", 0) < 0:
            step("note", f"a script could not be set for every page ({com.describe(result['added'])})")
        if "loaded" not in result:
            step("note", "the engine did not say that its page loaded")
        else:
            ok, status = result["loaded"]
            step("ok" if ok else "note", "a page loaded in it" if ok else f"its page did not load (status {status})")
        if "script" not in result:
            step("failed", "a script in the page did not answer")
            return 6
        hr, text = result["script"]
        if hr < 0:
            step("failed", f"a script in the page failed ({com.describe(hr)})")
            return 6
        step("ok", f"a script in the page answered: {text.strip(chr(34))}")
        step("ok", "Windows' web view works for the app")
        return 0
    finally:
        shell._teardown()
        shell.shutdown_engine()


class _ProbeConfig:
    """The app's settings, with a data folder of its own for the check (the app may be running meanwhile)."""

    def __init__(self, config: Config, folder: Path):
        self._config = config
        self.webview_dir = folder

    def __getattr__(self, name):
        return getattr(self._config, name)
