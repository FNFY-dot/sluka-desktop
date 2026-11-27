"""A stand-in WebView2 runtime and a stand-in Win32 for trying winshell on Linux.

The stand-in engine's objects are real COM objects (com.ComObject): the app's
code reaches them through their tables with ctypes, exactly as it reaches the
real engine's.  Their tables are written out here, method by method, in the
order of Microsoft's WebView2.h as two translations of it give it
(webview2-com-sys's *_Vtbl structs and webview2-sys's interfaces) -- not
from the app's index constants -- so an index of the app's that is off calls
the wrong method here and the tests fail.
"""

from __future__ import annotations

import ctypes
import itertools
import sys
import threading
import time
from collections import deque
from ctypes import POINTER, byref, c_double, c_int, c_int64, c_uint32, c_uint64, c_void_p, c_wchar_p

import os
APP = os.environ.get("SLUKA_APP", "/home/claude/work/sluka-desktop/app")
if APP not in sys.path:
    sys.path.insert(0, APP)

from sluka_desktop import com, winshell  # noqa: E402
from sluka_desktop import webview2 as wv2  # noqa: E402

HR = com.HRESULT
PTR = c_void_p
OUT = POINTER(c_void_p)
TOK = POINTER(c_int64)
BOOLP = POINTER(c_int)
INTP = POINTER(c_int)


def EV(name):
    """An add_/remove_ pair for an event."""
    return [(f"add_{name}", (PTR, TOK)), (f"remove_{name}", (c_int64,))]


# ---------------------------------------------------------------- the tables, in WebView2.h's order

ENVIRONMENT = [
    ("CreateCoreWebView2Controller", (PTR, PTR)),
    ("CreateWebResourceResponse", (PTR, c_int, c_wchar_p, c_wchar_p, OUT)),
    ("get_BrowserVersionString", (OUT,)),
    *EV("NewBrowserVersionAvailable"),
]

CONTROLLER = [
    ("get_IsVisible", (BOOLP,)), ("put_IsVisible", (c_int,)),
    ("get_Bounds", (POINTER(wv2.RECT),)), ("put_Bounds", (wv2.RECT,)),
    ("get_ZoomFactor", (POINTER(c_double),)), ("put_ZoomFactor", (c_double,)),
    *EV("ZoomFactorChanged"),
    ("SetBoundsAndZoomFactor", (wv2.RECT, c_double)),
    ("MoveFocus", (c_int,)),
    *EV("MoveFocusRequested"), *EV("GotFocus"), *EV("LostFocus"), *EV("AcceleratorKeyPressed"),
    ("get_ParentWindow", (OUT,)), ("put_ParentWindow", (PTR,)),
    ("NotifyParentWindowPositionChanged", ()),
    ("Close", ()),
    ("get_CoreWebView2", (OUT,)),
    # ICoreWebView2Controller2
    ("get_DefaultBackgroundColor", (POINTER(c_uint32),)), ("put_DefaultBackgroundColor", (c_uint32,)),
]

WEBVIEW = [
    ("get_Settings", (OUT,)), ("get_Source", (OUT,)), ("Navigate", (c_wchar_p,)), ("NavigateToString", (c_wchar_p,)),
    *EV("NavigationStarting"), *EV("ContentLoading"), *EV("SourceChanged"), *EV("HistoryChanged"),
    *EV("NavigationCompleted"), *EV("FrameNavigationStarting"), *EV("FrameNavigationCompleted"),
    *EV("ScriptDialogOpening"), *EV("PermissionRequested"), *EV("ProcessFailed"),
    ("AddScriptToExecuteOnDocumentCreated", (c_wchar_p, PTR)), ("RemoveScriptToExecuteOnDocumentCreated", (c_wchar_p,)),
    ("ExecuteScript", (c_wchar_p, PTR)), ("CapturePreview", (c_int, PTR, PTR)), ("Reload", ()),
    ("PostWebMessageAsJson", (c_wchar_p,)), ("PostWebMessageAsString", (c_wchar_p,)), *EV("WebMessageReceived"),
    ("CallDevToolsProtocolMethod", (c_wchar_p, c_wchar_p, PTR)), ("get_BrowserProcessId", (POINTER(c_uint32),)),
    ("get_CanGoBack", (BOOLP,)), ("get_CanGoForward", (BOOLP,)), ("GoBack", ()), ("GoForward", ()),
    ("GetDevToolsProtocolEventReceiver", (c_wchar_p, OUT)), ("Stop", ()),
    *EV("NewWindowRequested"), *EV("DocumentTitleChanged"), ("get_DocumentTitle", (OUT,)),
    ("AddHostObjectToScript", (c_wchar_p, PTR)), ("RemoveHostObjectFromScript", (c_wchar_p,)), ("OpenDevToolsWindow", ()),
    *EV("ContainsFullScreenElementChanged"), ("get_ContainsFullScreenElement", (BOOLP,)),
    *EV("WebResourceRequested"), ("AddWebResourceRequestedFilter", (c_wchar_p, c_int)), ("RemoveWebResourceRequestedFilter", (c_wchar_p, c_int)),
    *EV("WindowCloseRequested"),
    # ICoreWebView2_2
    *EV("WebResourceResponseReceived"), ("NavigateWithWebResourceRequest", (PTR,)), *EV("DOMContentLoaded"),
    ("get_CookieManager", (OUT,)), ("get_Environment", (OUT,)),
    # ICoreWebView2_3
    ("TrySuspend", (PTR,)), ("Resume", ()), ("get_IsSuspended", (BOOLP,)),
    ("SetVirtualHostNameToFolderMapping", (c_wchar_p, c_wchar_p, c_int)), ("ClearVirtualHostNameToFolderMapping", (c_wchar_p,)),
    # ICoreWebView2_4
    *EV("FrameCreated"), *EV("DownloadStarting"),
]

SETTINGS = []
for _name in ("IsScriptEnabled", "IsWebMessageEnabled", "AreDefaultScriptDialogsEnabled", "IsStatusBarEnabled",
              "AreDevToolsEnabled", "AreDefaultContextMenusEnabled", "AreHostObjectsAllowed", "IsZoomControlEnabled",
              "IsBuiltInErrorPageEnabled"):
    SETTINGS += [(f"get_{_name}", (BOOLP,)), (f"put_{_name}", (c_int,))]

NAV_STARTING_ARGS = [("get_Uri", (OUT,)), ("get_IsUserInitiated", (BOOLP,)), ("get_IsRedirected", (BOOLP,)),
                     ("get_RequestHeaders", (OUT,)), ("get_Cancel", (BOOLP,)), ("put_Cancel", (c_int,)),
                     ("get_NavigationId", (POINTER(c_uint64),))]
NAV_COMPLETED_ARGS = [("get_IsSuccess", (BOOLP,)), ("get_WebErrorStatus", (INTP,)), ("get_NavigationId", (POINTER(c_uint64),))]
NEW_WINDOW_ARGS = [("get_Uri", (OUT,)), ("put_NewWindow", (PTR,)), ("get_NewWindow", (OUT,)), ("put_Handled", (c_int,)),
                   ("get_Handled", (BOOLP,)), ("get_IsUserInitiated", (BOOLP,)), ("GetDeferral", (OUT,)), ("get_WindowFeatures", (OUT,))]
PERMISSION_ARGS = [("get_Uri", (OUT,)), ("get_PermissionKind", (INTP,)), ("get_IsUserInitiated", (BOOLP,)),
                   ("get_State", (INTP,)), ("put_State", (c_int,)), ("GetDeferral", (OUT,))]
FAILED_ARGS = [("get_ProcessFailedKind", (INTP,))]
DOWNLOAD_ARGS = [("get_DownloadOperation", (OUT,)), ("get_Cancel", (BOOLP,)), ("put_Cancel", (c_int,)),
                 ("get_ResultFilePath", (OUT,)), ("put_ResultFilePath", (c_wchar_p,)), ("get_Handled", (BOOLP,)),
                 ("put_Handled", (c_int,)), ("GetDeferral", (OUT,))]
OPTIONS = [("get_AdditionalBrowserArguments", (OUT,)), ("put_AdditionalBrowserArguments", (c_wchar_p,)),
           ("get_Language", (OUT,)), ("put_Language", (c_wchar_p,)),
           ("get_TargetCompatibleBrowserVersion", (OUT,)), ("put_TargetCompatibleBrowserVersion", (c_wchar_p,)),
           ("get_AllowSingleSignOnUsingOSPrimaryAccount", (BOOLP,)), ("put_AllowSingleSignOnUsingOSPrimaryAccount", (c_int,))]

IID_OPTIONS = "{2fde08a8-1e9a-4766-8c05-95a9ceb9d1c5}"
IID_WEBVIEW = "{76eceacb-0462-4d94-ac83-423a6793775e}"
IID_WEBVIEW_4 = "{20d02d59-6df2-42dc-bd06-f98a694b1302}"


class Fake(com.ComObject):
    """An engine object: its table is TABLE; what it does not implement is a call nobody should make."""

    TABLE: list = []

    def __init__(self, world, **kw):
        self.world = world
        self.__dict__.update(kw)
        self._prepare()
        methods = []
        for name, argtypes in self.TABLE:
            if not hasattr(self, name):
                setattr(self, name, self._unexpected(name))
            methods.append((name, argtypes))
        self.METHODS = tuple(methods)
        super().__init__()

    def _prepare(self):
        pass

    def _unexpected(self, name):
        def stub(*_args):
            self.world.unexpected.append(f"{type(self).__name__}.{name}")
            return com.E_NOTIMPL
        return stub


def invoke(handler: int, argtypes, *args):
    return com.method(handler, 3, argtypes)(handler, *args)


class FakeEnvironment(Fake):
    IIDS = ("{b96d755e-0319-4e92-a296-23436f46a1fc}",)
    TABLE = ENVIRONMENT

    def CreateCoreWebView2Controller(self, hwnd, handler):
        com.add_ref(handler)
        self.world.calls.append(("CreateCoreWebView2Controller", hwnd))

        def later():
            if self.world.fail_controllers:
                invoke(handler, (HR, PTR), com.E_FAIL, None)
            else:
                controller = FakeController(self.world, hwnd=hwnd)
                self.world.controllers.append(controller)
                invoke(handler, (HR, PTR), 0, controller.ptr)
            com.release(handler)
        self.world.later(later)

    def get_BrowserVersionString(self, out):
        out[0] = com.task_string("142.0.3595.80")


class FakeController(Fake):
    IIDS = ("{4d00c0d1-9434-4eb6-8078-8697a560334f}", "{c979903e-d4ca-4228-92eb-47ee3fa96eab}")
    TABLE = CONTROLLER

    def __init__(self, world, hwnd):
        super().__init__(world, hwnd=hwnd, visible=True, bounds=None, zoom=1.0, closed=False, focus=0, moved=0, background=0xFFFFFFFF)
        self.webview = FakeWebView(world, controller=self)

    def get_DefaultBackgroundColor(self, out):
        out[0] = self.background

    def put_DefaultBackgroundColor(self, value):
        # COREWEBVIEW2_COLOR {A, R, G, B} by value: four bytes, A the first.
        self.background = value & 0xFFFFFFFF

    def put_IsVisible(self, value):
        self.visible = bool(value)

    def get_IsVisible(self, out):
        out[0] = 1 if self.visible else 0

    def put_Bounds(self, rect):
        self.bounds = (rect.left, rect.top, rect.right, rect.bottom)

    def get_ZoomFactor(self, out):
        out[0] = self.zoom

    def put_ZoomFactor(self, value):
        self.zoom = float(value)

    def MoveFocus(self, reason):
        self.focus += 1
        assert reason == 0

    def NotifyParentWindowPositionChanged(self):
        self.moved += 1

    def Close(self):
        self.closed = True

    def get_CoreWebView2(self, out):
        com.add_ref(self.webview.ptr)  # an out-parameter: a reference for the caller
        out[0] = self.webview.ptr


class FakeSettings(Fake):
    IIDS = ("{e562e4f0-d7fa-43ac-8d71-c05150499f00}",)
    TABLE = SETTINGS

    def __init__(self, world):
        super().__init__(world, values={})

    def _prepare(self):
        for name, _types in SETTINGS:
            if name.startswith("put_"):
                setattr(self, name, self._putter(name[4:]))

    def _putter(self, name):
        def put(value):
            self.values[name] = bool(value)
        return put


class Args(Fake):
    def __init__(self, world, **kw):
        super().__init__(world, **kw)

    def get_Uri(self, out):
        out[0] = com.task_string(self.uri)


class NavStartingArgs(Args):
    TABLE = NAV_STARTING_ARGS
    cancel = False

    def put_Cancel(self, value):
        self.cancel = bool(value)

    def get_IsUserInitiated(self, out):
        out[0] = 1


class NavCompletedArgs(Args):
    TABLE = NAV_COMPLETED_ARGS

    def get_IsSuccess(self, out):
        out[0] = 1 if self.ok else 0

    def get_WebErrorStatus(self, out):
        out[0] = 0 if self.ok else 7


class NewWindowArgs(Args):
    TABLE = NEW_WINDOW_ARGS
    handled = False

    def put_Handled(self, value):
        self.handled = bool(value)

    def get_IsUserInitiated(self, out):
        out[0] = 1


class PermissionArgs(Args):
    TABLE = PERMISSION_ARGS
    state = 0

    def get_PermissionKind(self, out):
        out[0] = self.kind

    def put_State(self, value):
        self.state = int(value)


class FailedArgs(Args):
    TABLE = FAILED_ARGS

    def get_ProcessFailedKind(self, out):
        out[0] = self.kind


class DownloadArgs(Args):
    TABLE = DOWNLOAD_ARGS
    result = None
    handled = False

    def get_ResultFilePath(self, out):
        out[0] = com.task_string(self.suggested)

    def put_ResultFilePath(self, value):
        self.result = value

    def put_Handled(self, value):
        self.handled = bool(value)


class FakeWebView(Fake):
    IIDS = (IID_WEBVIEW, IID_WEBVIEW_4, "{9e8f0cf8-e670-4b5e-b2bc-73e061e3184c}", "{a0d6df20-3b92-416d-aa0c-437a9c727857}")
    TABLE = WEBVIEW

    def __init__(self, world, controller):
        super().__init__(world, controller=controller, handlers={}, source="", title="", scripts=[], navigated=[],
                         reloads=0, devtools=0, fullscreen=False, executed=[])

    def _prepare(self):
        for name, _types in WEBVIEW:
            if name.startswith("add_"):
                setattr(self, name, self._adder(name[4:]))
            elif name.startswith("remove_"):
                setattr(self, name, lambda token: 0)

    def _adder(self, event):
        def add(handler, token):
            com.add_ref(handler)
            self.handlers.setdefault(event, []).append(handler)
            token[0] = len(self.handlers[event])
        return add

    def fire(self, event, args=None):
        for handler in list(self.handlers.get(event, [])):
            invoke(handler, (PTR, PTR), self.ptr, args.ptr if args is not None else None)
        return args

    def get_Settings(self, out):
        settings = FakeSettings(self.world)
        self.world.settings.append(settings)
        out[0] = settings.ptr  # its first reference is the caller's

    def get_Source(self, out):
        out[0] = com.task_string(self.source)

    def Navigate(self, url):
        self.navigated.append(url)

        def later():
            args = self.fire("NavigationStarting", NavStartingArgs(self.world, uri=url))
            if args.cancel:
                return
            self.source = url
            self.fire("NavigationCompleted", NavCompletedArgs(self.world, ok=True))
            self.title = "Title of " + url.rsplit("/", 1)[-1]
            self.fire("DocumentTitleChanged")
            self.world.on_navigated(self, url)
        self.world.later(later)

    def AddScriptToExecuteOnDocumentCreated(self, script, handler):
        self.scripts.append(script)
        com.add_ref(handler)

        def later():
            invoke(handler, (HR, c_wchar_p), 0, "script-1")
            com.release(handler)
        self.world.later(later)

    def ExecuteScript(self, script, handler):
        self.executed.append(script)
        com.add_ref(handler)

        def later():
            invoke(handler, (HR, c_wchar_p), 0, '"FakeEngine/142"')
            com.release(handler)
        self.world.later(later)

    def Reload(self):
        self.reloads += 1

    def get_DocumentTitle(self, out):
        out[0] = com.task_string(self.title)

    def OpenDevToolsWindow(self):
        self.devtools += 1

    def get_ContainsFullScreenElement(self, out):
        out[0] = 1 if self.fullscreen else 0

    # what a page does, for the tests
    def token(self) -> str:
        import json
        import re

        for script in self.scripts:
            found = re.search(r"value: (\"[^\"]*\")", script)
            if found:
                return json.loads(found.group(1))
        return ""


class World:
    """The stand-in engine and Windows together."""

    def __init__(self):
        self.unexpected: list[str] = []
        self.controllers: list[FakeController] = []
        self.settings: list[FakeSettings] = []
        self.calls: list = []
        self.options_read: dict = {}
        self.fail_controllers = False
        self.environment = None
        self.win = FakeWin32(self)
        self.navigation_hooks = []

    def later(self, job):
        self.win.post_job(job)

    def on_navigated(self, webview, url):
        for hook in list(self.navigation_hooks):
            hook(webview, url)

    def entry(self, runtime):
        """What CreateWebViewEnvironmentWithOptionsInternal is in the stand-in runtime: a C function."""
        world = self

        def create(check_running, runtime_type, user_data, options, handler):
            world.calls.append(("create", check_running, runtime_type, user_data))
            # The engine reads the options as the real one does: through ICoreWebView2EnvironmentOptions.
            found = com.query(options, IID_OPTIONS)
            assert found, "the options are not ICoreWebView2EnvironmentOptions"
            assert not com.query(options, "{ff85c98a-1ba7-4a6b-90c8-2b752c89e9e2}"), "the options claim a newer interface"
            for index, name in ((3, "args"), (5, "language"), (7, "target")):
                out = c_void_p()
                assert com.method(found, index, (OUT,))(found, byref(out)) == 0
                world.options_read[name] = com.take_string(out.value)
            sso = c_int(5)
            com.method(found, 9, (BOOLP,))(found, byref(sso))
            world.options_read["sso"] = sso.value
            com.release(found)
            com.add_ref(handler)

            def later():
                world.environment = FakeEnvironment(world)
                invoke(handler, (HR, PTR), 0, world.environment.ptr)
                com.release(handler)
            world.later(later)
            return 0

        self._create = com.FUNCTYPE(HR, c_int, c_int, c_wchar_p, c_void_p, c_void_p)(create)
        return self._create

    def webviews(self):
        return [c.webview for c in self.controllers]


# ---------------------------------------------------------------- Windows


FAKE_JOB = 0xC123


class FakeWin32:
    """What winshell asks of Windows, with windows that are records and a message queue of Python's own."""

    def __init__(self, world):
        self.world = world
        self.cv = threading.Condition()
        self.queue = deque()
        self.timers: dict = {}
        self.windows: dict = {}
        self.hwnds = itertools.count(0x1000, 0x10)
        self.klass = None
        self.quit = None
        self.boxes: list = []
        self.box_answer = 7  # IDNO
        self.menus: dict = {}
        self.jobs: dict = {}
        self.job_ids = itertools.count(1)
        self.chosen = ["C:\\films", "film.mkv", "film.srt"]
        self.foreground = []
        self.allowed_foreground = []
        self.GetOpenFileNameW = self._open_file
        self.dwm = []  # (hwnd, attribute, value) as each window's title bar is set
        self.DwmSetWindowAttribute = lambda hwnd, attribute, value, size: self.dwm.append((hwnd, attribute, value._obj.value)) or 0
        self.GetDpiForWindow = lambda hwnd: 144
        self.GetDpiForSystem = lambda: 144
        self.SetProcessDpiAwarenessContext = lambda context: 1
        self.SetProcessDPIAware = lambda: 1
        self.SetCurrentProcessExplicitAppUserModelID = lambda name: 0
        self.classes: dict = {}
        self.regions: dict = {}
        self.region_ids = itertools.count(0x9000)
        self.cursor = (0, 0)
        self.ctrl_down = False
        self.blur = []
        self.layered = []
        self.checks = []
        self.redrawn = []
        # Two screens side by side: the main one, and one to its right at 100 %.
        self.screens = [((0, 0, 2880, 1620), (0, 0, 2880, 1572)), ((2880, 0, 4800, 1080), (2880, 0, 4800, 1040))]

    @staticmethod
    def last_error():
        return 0

    # the process
    def CoInitializeEx(self, reserved, flags):
        assert flags & 0x2, "COM is to be an STA"
        return 0

    def GetModuleHandleW(self, name):
        return 0x400000

    def LoadImageW(self, *args):
        return 0x77

    def GetSystemMetrics(self, index):
        return 32

    def CreateSolidBrush(self, colour):
        return 0x55

    def LoadCursorW(self, instance, name):
        return 0x66

    def RegisterClassExW(self, klass_ref):
        klass = klass_ref._obj
        assert klass.cbSize == ctypes.sizeof(winshell.WNDCLASSEXW)
        if self.klass is None:
            self.klass = klass
        self.classes[klass.lpszClassName] = klass
        return 1

    def GetStockObject(self, index):
        return 0x4400 + index

    # windows
    def CreateWindowExW(self, ex, klass, title, style, x, y, w, h, parent, menu, instance, param):
        hwnd = next(self.hwnds)
        message_only = parent is not None and getattr(parent, "value", parent) in (-3, 2**64 - 3, 2**32 - 3)
        self.windows[hwnd] = {"title": title, "style": style, "w": 1280 if w == winshell.CW_USEDEFAULT else w,
                              "h": 860 if h == winshell.CW_USEDEFAULT else h, "visible": False, "destroyed": False,
                              "message_only": message_only, "shows": [], "ex": ex, "class": klass, "region": "none",
                              "topmost": 0}
        if x != winshell.CW_USEDEFAULT:
            self.windows[hwnd]["x"], self.windows[hwnd]["y"] = x, y
        return hwnd

    def _send(self, hwnd, message, wparam=0, lparam=0):
        return self.klass.lpfnWndProc(hwnd, message, wparam, lparam)

    def DestroyWindow(self, hwnd):
        window = self.windows.get(hwnd)
        if window is None or window["destroyed"]:
            return 0
        window["destroyed"] = True
        window["visible"] = False
        self._send(hwnd, winshell.WM_DESTROY)
        return 1

    def ShowWindow(self, hwnd, command):
        window = self.windows[hwnd]
        window["shows"].append(command)
        was = window["visible"]
        show = command not in (winshell.SW_HIDE,)
        if show and not was:
            # As Windows does: the window is asked first (WM_WINDOWPOSCHANGING), and may keep itself hidden.
            pos = winshell.WINDOWPOS(hwnd=hwnd, flags=winshell.SWP_SHOWWINDOW | winshell.SWP_NOSIZE | winshell.SWP_NOMOVE)
            self._send(hwnd, winshell.WM_WINDOWPOSCHANGING, 0, ctypes.addressof(pos))
            show = bool(pos.flags & winshell.SWP_SHOWWINDOW)
            if not show:
                window["refused"] = window.get("refused", 0) + 1
                return 0
        window["visible"] = show
        if window["visible"] and command != winshell.SW_MINIMIZE:
            self._send(hwnd, winshell.WM_SIZE)
        return 1 if was else 0

    def UpdateWindow(self, hwnd):
        return 1

    def IsWindowVisible(self, hwnd):
        window = self.windows.get(hwnd)
        return 1 if window and window["visible"] and not window["destroyed"] else 0

    def shown_unasked(self, hwnd):
        """Something makes the window show without asking it first (no WM_WINDOWPOSCHANGING), as the frozen white
        window came up on a person's computer."""
        self.windows[hwnd]["visible"] = True

    def give_style(self, hwnd, style):
        """SetWindowLong(GWL_STYLE) as Windows does it: the window is asked first (WM_STYLECHANGING), and WS_VISIBLE
        in it shows the window."""
        window = self.windows[hwnd]
        change = winshell.STYLESTRUCT(styleOld=window["style"] & 0xFFFFFFFF, styleNew=style & 0xFFFFFFFF)
        self._send(hwnd, winshell.WM_STYLECHANGING, winshell.GWL_STYLE & (2 ** 64 - 1), ctypes.addressof(change))
        window["style"] = change.styleNew
        if change.styleNew & winshell.WS_VISIBLE:
            window["visible"] = True

    def SetForegroundWindow(self, hwnd):
        self.foreground.append(hwnd)
        return 1

    def IsIconic(self, hwnd):
        return 0

    def SetWindowTextW(self, hwnd, text):
        self.windows[hwnd]["title"] = text
        return 1

    def GetClientRect(self, hwnd, rect_ref):
        window = self.windows[hwnd]
        rect = rect_ref._obj
        rect.left, rect.top, rect.right, rect.bottom = 0, 0, window["w"] - 16, window["h"] - 39
        return 1

    def GetWindowRect(self, hwnd, rect_ref):
        window = self.windows[hwnd]
        rect = rect_ref._obj
        x, y = window.get("x", 100), window.get("y", 100)
        rect.left, rect.top, rect.right, rect.bottom = x, y, x + window["w"], y + window["h"]
        return 1

    def SetWindowPos(self, hwnd, after, x, y, w, h, flags):
        window = self.windows[hwnd]
        if getattr(after, "value", after) in (-1, 2**64 - 1, 2**32 - 1):
            window["topmost"] += 1
        if not flags & winshell.SWP_NOSIZE:
            window["w"], window["h"] = w, h
            self._send(hwnd, winshell.WM_SIZE)
        if not flags & winshell.SWP_NOMOVE:
            window["x"], window["y"] = x, y
        return 1

    def GetWindowLongPtrW(self, hwnd, index):
        if index == winshell.GWL_EXSTYLE:
            return winshell._as_long(self.windows[hwnd]["ex"])
        assert index == winshell.GWL_STYLE
        return winshell._as_long(self.windows[hwnd]["style"] | 0x10000000)

    def SetWindowLongPtrW(self, hwnd, index, value):
        key = "ex" if index == winshell.GWL_EXSTYLE else "style"
        old = self.windows[hwnd][key]
        self.windows[hwnd][key] = value & 0xFFFFFFFF
        return old

    # shapes
    def CreateRectRgn(self, left, top, right, bottom):
        handle = next(self.region_ids)
        self.regions[handle] = [] if right <= left or bottom <= top else [(left, top, right, bottom)]
        return handle

    def CombineRgn(self, dest, one, other, mode):
        assert mode == winshell.RGN_OR
        self.regions[dest] = list(self.regions[one]) + list(self.regions[other])
        return 2

    def DeleteObject(self, handle):
        return 1 if self.regions.pop(handle, None) is not None or handle else 0

    def SetWindowRgn(self, hwnd, region, redraw):
        region = getattr(region, "value", region)
        self.windows[hwnd]["region"] = None if not region else self.regions.pop(region)
        return 1

    def DwmEnableBlurBehindWindow(self, hwnd, ref):
        blur = ref._obj
        self.blur.append((hwnd, blur.dwFlags, blur.fEnable, self.regions.get(blur.hRgnBlur)))
        return 0

    def SetLayeredWindowAttributes(self, hwnd, key, alpha, flags):
        self.layered.append((hwnd, key, alpha, flags))
        return 1

    def SetWindowDisplayAffinity(self, hwnd, affinity):
        window = self.windows[hwnd]
        window["affinity"] = affinity
        # (and whether the window showed then: a window never shown is never to be told -- the frozen white window)
        window.setdefault("affinities", []).append((affinity, window["visible"]))
        return 1

    def RedrawWindow(self, hwnd, rect, region, flags):
        self.redrawn.append(hwnd)
        return 1

    # the pointer and the keys
    def GetCursorPos(self, ref):
        ref._obj.x, ref._obj.y = self.cursor
        return 1

    def GetAsyncKeyState(self, key):
        return -32768 if key == winshell.VK_CONTROL and self.ctrl_down else 0

    def MonitorFromPoint(self, point, flags):
        for i, ((left, top, right, bottom), _work) in enumerate(self.screens):
            if left <= point.x < right and top <= point.y < bottom:
                return 1 + i
        return 1 if flags else 0

    def CheckMenuItem(self, menu, ident, flags):
        self.checks.append((getattr(menu, "value", menu), ident, flags))
        return 0

    def GetWindowPlacement(self, hwnd, ref):
        ref._obj.showCmd = 1
        return 1

    def SetWindowPlacement(self, hwnd, ref):
        self.windows[hwnd]["placed"] = ref._obj.showCmd
        return 1

    def MonitorFromWindow(self, hwnd, flags):
        window = self.windows.get(hwnd) or {}
        x = window.get("x", 100)
        for i, ((left, _top, right, _bottom), _work) in enumerate(self.screens):
            if left <= x < right:
                return 1 + i
        return 1

    def GetMonitorInfoW(self, monitor, ref):
        info = ref._obj
        assert info.cbSize == ctypes.sizeof(winshell.MONITORINFO)
        screen, work = self.screens[(getattr(monitor, "value", monitor) or 1) - 1]
        info.rcMonitor.left, info.rcMonitor.top, info.rcMonitor.right, info.rcMonitor.bottom = screen
        info.rcWork.left, info.rcWork.top, info.rcWork.right, info.rcWork.bottom = work
        return 1

    def GetSystemMenu(self, hwnd, revert):
        self.menus.setdefault(hwnd, [])
        return hwnd + 0x1_000_000

    def AppendMenuW(self, menu, flags, ident, text):
        self.menus[menu - 0x1_000_000].append((flags, ident, text))
        return 1

    def MessageBoxW(self, owner, text, title, flags):
        self.boxes.append((owner, text, flags))
        return self.box_answer if flags & 0x4 else 1

    def AllowSetForegroundWindow(self, pid):
        self.allowed_foreground.append(pid)
        return 1

    def _open_file(self, ref):
        dialog = ref._obj
        payload = "\0".join(self.chosen) + "\0\0"
        buffer = ctypes.create_unicode_buffer(payload, len(payload) + 1)
        ctypes.memmove(dialog.lpstrFile, buffer, ctypes.sizeof(buffer))
        return 1

    # messages
    def DefWindowProcW(self, hwnd, message, wparam, lparam):
        return 0

    def post_job(self, job):
        ident = next(self.job_ids)
        self.jobs[ident] = job
        self.PostMessageW(None, FAKE_JOB, ident, 0)

    def PostMessageW(self, hwnd, message, wparam, lparam):
        with self.cv:
            self.queue.append((hwnd, message, wparam, lparam))
            self.cv.notify_all()
        return 1

    def PostQuitMessage(self, code):
        with self.cv:
            self.quit = code
            self.cv.notify_all()

    def SetTimer(self, hwnd, ident, ms, proc):
        with self.cv:
            self.timers[(hwnd, ident)] = (ms / 1000.0, time.monotonic() + ms / 1000.0)
            self.cv.notify_all()
        return ident

    def KillTimer(self, hwnd, ident):
        with self.cv:
            return 1 if self.timers.pop((hwnd, ident), None) else 0

    def GetMessageW(self, msg_ref, hwnd, low, high):
        msg = msg_ref._obj
        with self.cv:
            while True:
                if self.queue:
                    target, message, wparam, lparam = self.queue.popleft()
                    break
                now = time.monotonic()
                due = sorted((when, key) for key, (_every, when) in self.timers.items())
                if due and due[0][0] <= now:
                    (target, ident) = due[0][1]
                    every, _when = self.timers[due[0][1]]
                    self.timers[due[0][1]] = (every, now + every)
                    message, wparam, lparam = winshell.WM_TIMER, ident, 0
                    break
                if self.quit is not None:
                    return 0
                self.cv.wait(min(0.05, max(0.0, due[0][0] - now)) if due else 0.05)
        msg.hwnd, msg.message, msg.wParam, msg.lParam = target, message, wparam, lparam
        return 1

    def TranslateMessage(self, msg_ref):
        return 0

    def DispatchMessageW(self, msg_ref):
        msg = msg_ref._obj
        if msg.message == FAKE_JOB:
            job = self.jobs.pop(msg.wParam)
            job()
            return 0
        return self._send(msg.hwnd, msg.message, msg.wParam, msg.lParam)

    # for the tests
    def app_windows(self):
        return {h: w for h, w in self.windows.items() if not w["message_only"]}

    def close(self, hwnd):
        """The user clicks the window's X."""
        self.PostMessageW(hwnd, winshell.WM_CLOSE, 0, 0)

    def system_command(self, hwnd, command):
        self.PostMessageW(hwnd, winshell.WM_SYSCOMMAND, command, 0)


def runtime():
    return wv2.Runtime(dll="C:\\fake\\EBWebView\\x64\\EmbeddedBrowserWebView.dll", folder="C:\\fake", version="142.0.3595.80",
                       fixed=False, source="the test")
