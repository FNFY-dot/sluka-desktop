# SPDX-License-Identifier: LicenseRef-Sluka
# Copyright (c) 2026 Sluka. Part of Sluka Desktop; see LICENSE.txt.
"""Microsoft Edge WebView2 -- the web view Windows itself has -- from Python, with ctypes alone.

WebView2 comes with Windows 11 (and with most Windows 10 by now) as the
"WebView2 Runtime", apart from the Edge browser: uninstalling Edge leaves it
in place.  It is the engine of Edge -- Chromium -- in a window of the
program's own, which is what Sluka's windows are here.

Programs normally reach it through a small DLL that comes with Microsoft's
SDK (WebView2Loader.dll).  This app ships no DLL of its own: it does what
that loader does for the usual case, which Microsoft documents --
``CreateWebViewEnvironmentWithOptionsInternal``, exported by
``EmbeddedBrowserWebView.dll`` in the runtime's own folder -- after finding
that folder where the runtime's installer records it.

Everything after that is COM: the places of the methods in each interface's
table (``*_`` constants below) are those of Microsoft's WebView2.h, which
never changes for an interface once released; every number was checked
against two independent translations of that header.  The interfaces used
are the first ones (SDK 1.0.622, 2020), and ICoreWebView2_4 for downloads,
which any runtime from 2021 on has.
"""

from __future__ import annotations

import ctypes
import logging
import ntpath
import os
import re
import sysconfig
from ctypes import c_uint32, POINTER, Structure, byref, c_double, c_int, c_int32, c_int64, c_void_p, c_wchar_p
from dataclasses import dataclass

from . import com
from .com import HRESULT, ComError, ComObject, Interface

log = logging.getLogger("sluka.webview2")

# ---------------------------------------------------------------- interface ids (WebView2.h)

IID_ICoreWebView2 = "{76eceacb-0462-4d94-ac83-423a6793775e}"
IID_ICoreWebView2_4 = "{20d02d59-6df2-42dc-bd06-f98a694b1302}"
IID_ICoreWebView2Controller = "{4d00c0d1-9434-4eb6-8078-8697a560334f}"
IID_ICoreWebView2Controller2 = "{c979903e-d4ca-4228-92eb-47ee3fa96eab}"
IID_ICoreWebView2Environment = "{b96d755e-0319-4e92-a296-23436f46a1fc}"
IID_ICoreWebView2Settings = "{e562e4f0-d7fa-43ac-8d71-c05150499f00}"
IID_ICoreWebView2EnvironmentOptions = "{2fde08a8-1e9a-4766-8c05-95a9ceb9d1c5}"

IID_EnvironmentCompletedHandler = "{4e8a3389-c9d8-4bd2-b6b5-124fee6cc14d}"
IID_ControllerCompletedHandler = "{6c4819f3-c9b7-4260-8127-c9f5bde7f68c}"
IID_AddScriptCompletedHandler = "{b99369f3-9b11-47b5-bc6f-8e7895fcea17}"
IID_ExecuteScriptCompletedHandler = "{49511172-cc67-4bca-9923-137112f4c4cc}"

IID_NavigationStartingEventHandler = "{9adbe429-f36d-432b-9ddc-f8881fbd76e3}"
IID_NavigationCompletedEventHandler = "{d33a35bf-1c49-4f98-93ab-006e0533fe1c}"
IID_PermissionRequestedEventHandler = "{15e1c6a3-c72a-4df3-91d7-d097fbec6bfd}"
IID_ProcessFailedEventHandler = "{79e0aea4-990b-42d9-aa1d-0fcc2e5bc7f1}"
IID_NewWindowRequestedEventHandler = "{d4c185fe-c81c-4989-97af-2d3fa7ab5651}"
IID_DocumentTitleChangedEventHandler = "{f5f2b923-953e-4042-9f95-f3a118e1afd4}"
IID_ContainsFullScreenElementChangedEventHandler = "{e45d98b1-afef-45be-8baf-6c7728867f73}"
IID_WindowCloseRequestedEventHandler = "{5c19e9e0-092f-486b-affa-ca8231913039}"
IID_DownloadStartingEventHandler = "{efedc989-c396-41ca-83f7-07f845a55724}"

# ---------------------------------------------------------------- places in the tables (0-2 are IUnknown's)

# ICoreWebView2Environment
ENV_CREATE_CONTROLLER = 3          # CreateCoreWebView2Controller(HWND, handler)
ENV_BROWSER_VERSION = 5            # get_BrowserVersionString(LPWSTR*)

# ICoreWebView2Controller
CTL_PUT_IS_VISIBLE = 4             # put_IsVisible(BOOL)
CTL_PUT_BOUNDS = 6                 # put_Bounds(RECT)
CTL_GET_ZOOM = 7                   # get_ZoomFactor(double*)
CTL_PUT_ZOOM = 8                   # put_ZoomFactor(double)
CTL_MOVE_FOCUS = 12                # MoveFocus(COREWEBVIEW2_MOVE_FOCUS_REASON)
CTL_NOTIFY_MOVED = 23              # NotifyParentWindowPositionChanged()
CTL_CLOSE = 24                     # Close()
CTL_GET_WEBVIEW = 25               # get_CoreWebView2(ICoreWebView2**)
# ICoreWebView2Controller2, whose two follow ICoreWebView2Controller's 0-25
CTL2_GET_BACKGROUND = 26           # get_DefaultBackgroundColor(COREWEBVIEW2_COLOR*)
CTL2_PUT_BACKGROUND = 27           # put_DefaultBackgroundColor(COREWEBVIEW2_COLOR)

# ICoreWebView2
WV_GET_SETTINGS = 3                # get_Settings(ICoreWebView2Settings**)
WV_GET_SOURCE = 4                  # get_Source(LPWSTR*)
WV_NAVIGATE = 5                    # Navigate(LPCWSTR)
WV_ADD_NAVIGATION_STARTING = 7
WV_ADD_NAVIGATION_COMPLETED = 15
WV_ADD_PERMISSION_REQUESTED = 23
WV_ADD_PROCESS_FAILED = 25
WV_ADD_SCRIPT_ON_DOCUMENT = 27     # AddScriptToExecuteOnDocumentCreated(LPCWSTR, handler)
WV_EXECUTE_SCRIPT = 29             # ExecuteScript(LPCWSTR, handler)
WV_RELOAD = 31                     # Reload()
WV_ADD_NEW_WINDOW_REQUESTED = 44
WV_ADD_TITLE_CHANGED = 46
WV_GET_TITLE = 48                  # get_DocumentTitle(LPWSTR*)
WV_OPEN_DEVTOOLS = 51              # OpenDevToolsWindow()
WV_ADD_FULLSCREEN_CHANGED = 52
WV_GET_FULLSCREEN = 54             # get_ContainsFullScreenElement(BOOL*)
WV_ADD_WINDOW_CLOSE_REQUESTED = 59
# ICoreWebView2_4 (after ICoreWebView2's 58, ICoreWebView2_2's 7 and ICoreWebView2_3's 5 methods)
WV4_ADD_DOWNLOAD_STARTING = 75

# ICoreWebView2Settings
SET_PUT_WEB_MESSAGE = 6            # put_IsWebMessageEnabled
SET_PUT_STATUS_BAR = 10            # put_IsStatusBarEnabled
SET_PUT_DEVTOOLS = 12              # put_AreDevToolsEnabled
SET_PUT_CONTEXT_MENUS = 14         # put_AreDefaultContextMenusEnabled
SET_PUT_HOST_OBJECTS = 16          # put_AreHostObjectsAllowed
SET_PUT_ZOOM_CONTROL = 18          # put_IsZoomControlEnabled

# event arguments
NAV_GET_URI = 3                    # ICoreWebView2NavigationStartingEventArgs::get_Uri
NAV_GET_USER_INITIATED = 4
NAV_PUT_CANCEL = 8
DONE_GET_IS_SUCCESS = 3            # ICoreWebView2NavigationCompletedEventArgs::get_IsSuccess
DONE_GET_ERROR = 4                 # get_WebErrorStatus
NEW_GET_URI = 3                    # ICoreWebView2NewWindowRequestedEventArgs::get_Uri
NEW_PUT_HANDLED = 6
NEW_GET_USER_INITIATED = 8
PERM_GET_URI = 3                   # ICoreWebView2PermissionRequestedEventArgs::get_Uri
PERM_GET_KIND = 4
PERM_PUT_STATE = 7
FAIL_GET_KIND = 3                  # ICoreWebView2ProcessFailedEventArgs::get_ProcessFailedKind
DL_GET_RESULT_PATH = 6             # ICoreWebView2DownloadStartingEventArgs::get_ResultFilePath
DL_PUT_RESULT_PATH = 7
DL_PUT_HANDLED = 9

# ---------------------------------------------------------------- values

MOVE_FOCUS_PROGRAMMATIC = 0

PERMISSION_DEFAULT, PERMISSION_ALLOW, PERMISSION_DENY = 0, 1, 2
PERMISSION_NAMES = {
    0: "unknown", 1: "microphone", 2: "camera", 3: "geolocation", 4: "notifications", 5: "other sensors",
    6: "clipboard read", 7: "several downloads at once", 8: "file read/write", 9: "autoplay", 10: "local fonts",
    11: "MIDI system exclusive messages", 12: "window management", 13: "storage kept from being cleared (persistent storage)",
    14: "the local network", 15: "this computer's own address (loopback network)",
}

FAILED_BROWSER = 0
FAILED_RENDERER = 1
FAILED_UNRESPONSIVE = 2
FAILED_NAMES = {
    0: "the web view's engine (browser process) ended", 1: "the page's process ended", 2: "the page stopped answering",
    3: "a frame's process ended", 4: "a utility process ended", 5: "a sandbox helper ended", 6: "the GPU process ended",
    7: "a plugin process ended", 8: "a plugin broker ended", 9: "a process ended",
}

#: The SDK version the options say this app was written for.  A runtime at least this new is asked for;
#: Windows has kept its own up to date since 2021.
TARGET_VERSION = "120.0.2210.55"


class RECT(Structure):
    _fields_ = [("left", c_int32), ("top", c_int32), ("right", c_int32), ("bottom", c_int32)]


# ---------------------------------------------------------------- where the runtime is

#: The WebView2 Runtime's id with the installer (the stable channel).
RUNTIME_CLIENT = "{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}"


@dataclass
class Runtime:
    dll: str          # EmbeddedBrowserWebView.dll
    folder: str       # the version folder (msedgewebview2.exe in it)
    version: str
    fixed: bool       # a fixed-version runtime named in config.ini, rather than the installed one
    source: str       # how it was found, for the log and the doctor

    def describe(self) -> str:
        return f"WebView2 Runtime {self.version or '?'} ({self.folder})"


def process_arch() -> str:
    """The name of the runtime's folder for the kind of Windows program this Python is."""
    platform = sysconfig.get_platform().lower()
    if "arm64" in platform or "aarch64" in platform:
        return "arm64"
    if platform in ("win32", "win-x86") or ctypes.sizeof(c_void_p) == 4:
        return "x86"
    return "x64"


def client_dll(folder: str, arch: str | None = None) -> str:
    return ntpath.join(folder, "EBWebView", arch or process_arch(), "EmbeddedBrowserWebView.dll")


def _version_key(text: str) -> tuple:
    return tuple(int(part) for part in re.findall(r"\d+", text or "")[:4]) or (0,)


def _registry_values(hive_name: str, key: str, names: tuple) -> dict:
    try:
        import winreg
    except ImportError:
        return {}
    hive = getattr(winreg, hive_name)
    found = {}
    for view in (winreg.KEY_WOW64_32KEY, winreg.KEY_WOW64_64KEY):
        try:
            with winreg.OpenKey(hive, key, 0, winreg.KEY_READ | view) as handle:
                for name in names:
                    if name in found:
                        continue
                    try:
                        value, _kind = winreg.QueryValueEx(handle, name)
                    except OSError:
                        continue
                    if isinstance(value, str) and value.strip():
                        found[name] = value.strip().strip('"')
        except OSError:
            continue
    return found


def find_runtime(override: str = "", env=None, exists=os.path.isfile, registry=_registry_values, listdir=os.listdir) -> Runtime | None:
    """The WebView2 Runtime to use: the one named in config.ini, else the one Windows has; None if none is found."""
    env = os.environ if env is None else env
    arch = process_arch()
    if override:
        folder = os.path.expandvars(os.path.expanduser(override.strip().strip('"'))).rstrip("\\/")
        if ntpath.basename(folder).lower() == "msedgewebview2.exe":
            folder = ntpath.dirname(folder)
        dll = client_dll(folder, arch)
        if exists(dll):
            return Runtime(dll, folder, ntpath.basename(folder), True, "config.ini [webview2] runtime")
        log.warning("[webview2] runtime = %s holds no %s; looking for the installed one", override, dll)

    candidates: list[tuple[str, str, str]] = []  # (folder, version, how)
    for hive in ("HKEY_LOCAL_MACHINE", "HKEY_CURRENT_USER"):
        state = registry(hive, r"SOFTWARE\Microsoft\EdgeUpdate\ClientState" + "\\" + RUNTIME_CLIENT, ("EBWebView",))
        if state.get("EBWebView"):
            folder = state["EBWebView"].rstrip("\\/")
            candidates.append((folder, ntpath.basename(folder), f"the installer's record ({hive})"))
        client = registry(hive, r"SOFTWARE\Microsoft\EdgeUpdate\Clients" + "\\" + RUNTIME_CLIENT, ("pv", "location"))
        if client.get("pv"):
            for base in [client.get("location", "")] + [env.get(name, "") for name in ("ProgramFiles(x86)", "ProgramFiles", "LOCALAPPDATA")]:
                if not base:
                    continue
                root = base if base.lower().rstrip("\\/").endswith("application") else ntpath.join(base, "Microsoft", "EdgeWebView", "Application")
                candidates.append((ntpath.join(root, client["pv"]), client["pv"], f"version {client['pv']} ({hive})"))

    # Failing a record: whatever version folders there are where the runtime is put.
    for base in (env.get("ProgramFiles(x86)"), env.get("ProgramFiles"), env.get("LOCALAPPDATA")):
        if not base:
            continue
        root = ntpath.join(base, "Microsoft", "EdgeWebView", "Application")
        try:
            names = listdir(root)
        except OSError:
            continue
        for name in sorted((n for n in names if re.fullmatch(r"\d+(\.\d+){1,3}", n)), key=_version_key, reverse=True):
            candidates.append((ntpath.join(root, name), name, "its folder"))

    for folder, version, how in candidates:
        dll = client_dll(folder, arch)
        if exists(dll):
            return Runtime(dll, folder, version, False, how)
    return None


# ---------------------------------------------------------------- handlers: what the engine calls back


class EnvironmentCompleted(ComObject):
    IIDS = (IID_EnvironmentCompletedHandler,)
    METHODS = (("invoke", (HRESULT, c_void_p)),)

    def __init__(self, done):
        self._done = done
        super().__init__()

    def invoke(self, hr, environment):
        self._done(int(hr), int(environment or 0))


class ControllerCompleted(ComObject):
    IIDS = (IID_ControllerCompletedHandler,)
    METHODS = (("invoke", (HRESULT, c_void_p)),)

    def __init__(self, done):
        self._done = done
        super().__init__()

    def invoke(self, hr, controller):
        self._done(int(hr), int(controller or 0))


class TextCompleted(ComObject):
    """For AddScriptToExecuteOnDocumentCreated and ExecuteScript: a result and a text."""

    METHODS = (("invoke", (HRESULT, c_wchar_p)),)

    def __init__(self, iid: str, done):
        self.IIDS = (iid,)
        self._done = done
        super().__init__()

    def invoke(self, hr, text):
        self._done(int(hr), text or "")


class EventHandler(ComObject):
    """For every event: ``Invoke(sender, args)``; the callback gets the args' address (valid during the call)."""

    METHODS = (("invoke", (c_void_p, c_void_p)),)

    def __init__(self, iid: str, on_event):
        self.IIDS = (iid,)
        self._on_event = on_event
        super().__init__()

    def invoke(self, _sender, args):
        self._on_event(int(args or 0))


class EnvironmentOptions(ComObject):
    """ICoreWebView2EnvironmentOptions: the engine's command line, chiefly.  What the SDK's loader would make."""

    IIDS = (IID_ICoreWebView2EnvironmentOptions,)
    METHODS = (
        ("get_args", (POINTER(c_void_p),)),
        ("put_args", (c_wchar_p,)),
        ("get_language", (POINTER(c_void_p),)),
        ("put_language", (c_wchar_p,)),
        ("get_target", (POINTER(c_void_p),)),
        ("put_target", (c_wchar_p,)),
        ("get_sso", (POINTER(c_int),)),
        ("put_sso", (c_int,)),
    )
    ON_ERROR = com.E_FAIL

    def __init__(self, arguments: str = "", language: str = "", target: str = TARGET_VERSION):
        self.arguments, self.language, self.target, self.sso = arguments, language, target, False
        self.asked: list[str] = []
        super().__init__()

    def _give(self, out, text: str, name: str):
        self.asked.append(name)
        if not out:
            return com.E_POINTER
        out[0] = com.task_string(text)
        return com.S_OK

    def get_args(self, out):
        return self._give(out, self.arguments, "AdditionalBrowserArguments")

    def put_args(self, value):
        self.arguments = value or ""

    def get_language(self, out):
        return self._give(out, self.language, "Language")

    def put_language(self, value):
        self.language = value or ""

    def get_target(self, out):
        return self._give(out, self.target, "TargetCompatibleBrowserVersion")

    def put_target(self, value):
        self.target = value or ""

    def get_sso(self, out):
        self.asked.append("AllowSingleSignOnUsingOSPrimaryAccount")
        if not out:
            return com.E_POINTER
        out[0] = 1 if self.sso else 0
        return com.S_OK

    def put_sso(self, value):
        self.sso = bool(value)


# ---------------------------------------------------------------- the engine's objects


class Settings(Interface):
    def configure(self, devtools: bool, zoom: bool = True) -> None:
        for index, value, what in (
            (SET_PUT_STATUS_BAR, False, "status bar"),      # no address shown at the bottom when pointing at a link
            (SET_PUT_DEVTOOLS, devtools, "developer tools"),
            (SET_PUT_HOST_OBJECTS, False, "host objects"),
            (SET_PUT_CONTEXT_MENUS, True, "context menus"),
            (SET_PUT_ZOOM_CONTROL, zoom, "zoom"),            # Ctrl and the wheel (the floating subtitles have their own sizes)
        ):
            try:
                self.set_bool(index, value, what=f"settings: {what}")
            except ComError as err:
                log.warning("%s", err)


class WebView(Interface):
    """ICoreWebView2: the page."""

    def settings(self) -> Settings:
        return self.get_object(WV_GET_SETTINGS, Settings, what="get_Settings")

    def navigate(self, url: str) -> None:
        self.set_string(WV_NAVIGATE, url, what="Navigate")

    def source(self) -> str:
        return self.get_string(WV_GET_SOURCE, what="get_Source")

    def reload(self) -> None:
        self.call(WV_RELOAD, what="Reload")

    def title(self) -> str:
        return self.get_string(WV_GET_TITLE, what="get_DocumentTitle")

    def contains_fullscreen(self) -> bool:
        return self.get_bool(WV_GET_FULLSCREEN, what="get_ContainsFullScreenElement")

    def open_devtools(self) -> None:
        self.call(WV_OPEN_DEVTOOLS, what="OpenDevToolsWindow")

    def _add(self, index: int, handler: ComObject, what: str) -> int:
        token = c_int64()
        try:
            self.call(index, (c_void_p, POINTER(c_int64)), handler.ptr, byref(token), what=what)
        finally:
            handler.drop()  # the engine holds it now, for as long as the page lives
        return token.value

    def on(self, index: int, iid: str, callback, what: str) -> int:
        return self._add(index, EventHandler(iid, callback), what)

    def add_script(self, script: str, done) -> None:
        handler = TextCompleted(IID_AddScriptCompletedHandler, done)
        try:
            self.call(WV_ADD_SCRIPT_ON_DOCUMENT, (c_wchar_p, c_void_p), script, handler.ptr, what="AddScriptToExecuteOnDocumentCreated")
        finally:
            handler.drop()

    def execute_script(self, script: str, done) -> None:
        handler = TextCompleted(IID_ExecuteScriptCompletedHandler, done)
        try:
            self.call(WV_EXECUTE_SCRIPT, (c_wchar_p, c_void_p), script, handler.ptr, what="ExecuteScript")
        finally:
            handler.drop()

    def on_download(self, callback) -> bool:
        """Downloads, where the runtime has ICoreWebView2_4 (2021 on); False where it has not."""
        four = self.query(IID_ICoreWebView2_4)
        if four is None:
            return False
        try:
            token = c_int64()
            handler = EventHandler(IID_DownloadStartingEventHandler, callback)
            try:
                four.call(WV4_ADD_DOWNLOAD_STARTING, (c_void_p, POINTER(c_int64)), handler.ptr, byref(token), what="add_DownloadStarting")
            finally:
                handler.drop()
        finally:
            four.release()
        return True


class Controller(Interface):
    """ICoreWebView2Controller: the web view's place in its window."""

    def webview(self) -> WebView:
        return self.get_object(CTL_GET_WEBVIEW, WebView, what="get_CoreWebView2")

    def set_visible(self, visible: bool) -> None:
        self.set_bool(CTL_PUT_IS_VISIBLE, visible, what="put_IsVisible")

    def set_bounds(self, left: int, top: int, right: int, bottom: int) -> None:
        self.call(CTL_PUT_BOUNDS, (RECT,), RECT(left, top, right, bottom), what="put_Bounds")

    def zoom(self) -> float:
        value = c_double()
        self.call(CTL_GET_ZOOM, (POINTER(c_double),), byref(value), what="get_ZoomFactor")
        return float(value.value)

    def set_zoom(self, factor: float) -> None:
        self.call(CTL_PUT_ZOOM, (c_double,), float(factor), what="put_ZoomFactor")

    def move_focus(self) -> None:
        self.set_int(CTL_MOVE_FOCUS, MOVE_FOCUS_PROGRAMMATIC, what="MoveFocus")

    def notify_moved(self) -> None:
        self.call(CTL_NOTIFY_MOVED, what="NotifyParentWindowPositionChanged")

    def close(self) -> None:
        self.call(CTL_CLOSE, what="Close")

    def set_transparent(self) -> bool:
        """Nothing drawn under the page: where it draws nothing, what is behind the window shows (False: not to be had)."""
        two = self.query(IID_ICoreWebView2Controller2)
        if two is None:
            return False
        try:
            # COREWEBVIEW2_COLOR, four bytes A R G B, passed as they are: all four nought is see-through.
            two.call(CTL2_PUT_BACKGROUND, (c_uint32,), 0, what="put_DefaultBackgroundColor")
        finally:
            two.release()
        return True


class Environment(Interface):
    """ICoreWebView2Environment: the engine, shared by every view of the app."""

    def version(self) -> str:
        return self.get_string(ENV_BROWSER_VERSION, what="get_BrowserVersionString")

    def create_controller(self, hwnd: int, done) -> None:
        """A web view in the window ``hwnd``; ``done(hr, controller address)`` is called later, on this thread."""
        handler = ControllerCompleted(done)
        try:
            self.call(ENV_CREATE_CONTROLLER, (c_void_p, c_void_p), hwnd, handler.ptr, what="CreateCoreWebView2Controller")
        finally:
            handler.drop()


# ---------------------------------------------------------------- event arguments (borrowed for the length of a call)


def navigation_uri(args: int) -> str:
    return Interface(args).get_string(NAV_GET_URI, what="NavigationStarting.get_Uri")


def cancel_navigation(args: int) -> None:
    Interface(args).set_bool(NAV_PUT_CANCEL, True, what="NavigationStarting.put_Cancel")


def navigation_succeeded(args: int) -> tuple[bool, int]:
    item = Interface(args)
    ok = item.get_bool(DONE_GET_IS_SUCCESS, what="NavigationCompleted.get_IsSuccess")
    status = 0 if ok else item.get_int(DONE_GET_ERROR, what="NavigationCompleted.get_WebErrorStatus")
    return ok, status


def new_window_uri(args: int) -> str:
    return Interface(args).get_string(NEW_GET_URI, what="NewWindowRequested.get_Uri")


def handle_new_window(args: int) -> None:
    Interface(args).set_bool(NEW_PUT_HANDLED, True, what="NewWindowRequested.put_Handled")


def permission_kind(args: int) -> int:
    return Interface(args).get_int(PERM_GET_KIND, what="PermissionRequested.get_PermissionKind")


def permission_uri(args: int) -> str:
    return Interface(args).get_string(PERM_GET_URI, what="PermissionRequested.get_Uri")


def set_permission(args: int, state: int) -> None:
    Interface(args).set_int(PERM_PUT_STATE, state, what="PermissionRequested.put_State")


def failure_kind(args: int) -> int:
    return Interface(args).get_int(FAIL_GET_KIND, what="ProcessFailed.get_ProcessFailedKind")


def download_path(args: int) -> str:
    return Interface(args).get_string(DL_GET_RESULT_PATH, what="DownloadStarting.get_ResultFilePath")


def set_download_path(args: int, path: str) -> None:
    Interface(args).set_string(DL_PUT_RESULT_PATH, path, what="DownloadStarting.put_ResultFilePath")


# ---------------------------------------------------------------- starting the engine


#: The loaded runtime DLLs, kept for as long as the process runs: the engine's objects live in them.
_loaded: list = []


def entry_point(runtime: Runtime):
    """``CreateWebViewEnvironmentWithOptionsInternal`` of the runtime's DLL (documented by Microsoft as the
    export the SDK's loader calls)."""
    loader = getattr(ctypes, "WinDLL", ctypes.CDLL)
    library = loader(runtime.dll)
    _loaded.append(library)
    function = library.CreateWebViewEnvironmentWithOptionsInternal
    function.restype = HRESULT
    # (bool checkRunningInstance, int runtimeType, PCWSTR userDataFolder, IUnknown* options, handler*)
    function.argtypes = [c_int, c_int, c_wchar_p, c_void_p, c_void_p]
    return function


def create_environment(runtime: Runtime, user_data: str, options: EnvironmentOptions, done, entry=None) -> None:
    """Start the engine with ``options`` and its data in ``user_data``; ``done(hr, environment address)`` later.

    The completion arrives through the window messages of this thread, which has to be a COM single-threaded
    apartment with a message loop.
    """
    function = (entry or entry_point)(runtime)
    handler = EnvironmentCompleted(done)
    try:
        hr = function(1, 1 if runtime.fixed else 0, user_data, options.ptr, handler.ptr)
    finally:
        handler.drop()
    if hr < 0:
        raise ComError(hr, "starting the web view (CreateWebViewEnvironmentWithOptionsInternal)")


def engine_arguments(config, background: bool = True) -> list[str]:
    """The engine's command line: what an extension's pages may do that a page's may not, and the network mode."""
    switches = [
        # Sluka's worker runs in a page nobody sees, and has to go on working at full speed there.
        "--disable-background-timer-throttling",
        "--disable-renderer-backgrounding",
        "--disable-backgrounding-occluded-windows",
        # Sluka opens its reader and its panels itself, and says words aloud without a click.
        "--disable-popup-blocking",
        "--autoplay-policy=no-user-gesture-required",
        # A page in the language being learned is not to be offered for translation, nor its address checked online.
        "--disable-features=Translate,TranslateUI,IntensiveWakeUpThrottling,msSmartScreenProtection",
    ]
    if not config.web_security:
        # What an extension's "<all_urls>" is to a browser: Sluka's pages may read other sites.
        switches.append("--disable-web-security")
    mode = config.network_mode
    if mode in ("tor", "offline"):
        # offline: a proxy nothing listens on, so every site is refused at once, names unresolved.
        proxy = config.socks if mode == "tor" else "127.0.0.1:1"
        switches += [f"--proxy-server=socks5://{proxy}", "--host-resolver-rules=MAP * ~NOTFOUND , EXCLUDE 127.0.0.1"]
    return switches + list(getattr(config, "webview_args", []) or [])


def site_arguments(config) -> list[str]:
    """The command line of the web view for sites themselves (the Look up key's dictionary sites): a browser's, its web
    security whole -- none of what the app's own pages may do -- and only the app's network mode."""
    switches = []
    mode = config.network_mode
    if mode in ("tor", "offline"):
        proxy = config.socks if mode == "tor" else "127.0.0.1:1"
        switches += [f"--proxy-server=socks5://{proxy}", "--host-resolver-rules=MAP * ~NOTFOUND , EXCLUDE 127.0.0.1"]
    return switches + [a for a in (getattr(config, "webview_args", []) or []) if a != "--disable-web-security"]


def quote_arguments(switches: list[str]) -> str:
    """One command line out of switches (a switch with a space in it is quoted as Windows reads quotes)."""
    out = []
    for switch in switches:
        if " " in switch and not switch.startswith('"'):
            name, eq, value = switch.partition("=")
            switch = f'{name}="{value}"' if eq else f'"{switch}"'
        out.append(switch)
    return " ".join(out)
