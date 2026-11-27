"""winshell and webview2, tried against the stand-in engine and Windows of fakes.py."""

from __future__ import annotations

import json
import ntpath
import os
import shutil
import struct
import sys
import tempfile
import threading
import time
import urllib.request
import zlib
from pathlib import Path

import pytest

import fakes
from fakes import World

from sluka_desktop import com, winshell
from sluka_desktop import webview2 as wv2
from sluka_desktop.config import Config


def at(table, index):
    return table[index - 3][0]


def test_tables_are_as_long_as_the_header_says():
    assert len(fakes.ENVIRONMENT) == 5
    assert len(fakes.CONTROLLER) == 25
    assert len(fakes.WEBVIEW) == 58 + 7 + 5 + 4
    assert len(fakes.SETTINGS) == 18
    assert len(fakes.OPTIONS) == 8


def test_every_index_names_the_method_meant():
    E, C, W, S = fakes.ENVIRONMENT, fakes.CONTROLLER, fakes.WEBVIEW, fakes.SETTINGS
    assert at(E, wv2.ENV_CREATE_CONTROLLER) == "CreateCoreWebView2Controller"
    assert at(E, wv2.ENV_BROWSER_VERSION) == "get_BrowserVersionString"
    assert at(C, wv2.CTL_PUT_IS_VISIBLE) == "put_IsVisible"
    assert at(C, wv2.CTL_PUT_BOUNDS) == "put_Bounds"
    assert at(C, wv2.CTL_GET_ZOOM) == "get_ZoomFactor"
    assert at(C, wv2.CTL_PUT_ZOOM) == "put_ZoomFactor"
    assert at(C, wv2.CTL_MOVE_FOCUS) == "MoveFocus"
    assert at(C, wv2.CTL_NOTIFY_MOVED) == "NotifyParentWindowPositionChanged"
    assert at(C, wv2.CTL_CLOSE) == "Close"
    assert at(C, wv2.CTL_GET_WEBVIEW) == "get_CoreWebView2"
    assert at(C, wv2.CTL2_GET_BACKGROUND) == "get_DefaultBackgroundColor"
    assert at(C, wv2.CTL2_PUT_BACKGROUND) == "put_DefaultBackgroundColor"
    assert at(W, wv2.WV_GET_SETTINGS) == "get_Settings"
    assert at(W, wv2.WV_GET_SOURCE) == "get_Source"
    assert at(W, wv2.WV_NAVIGATE) == "Navigate"
    assert at(W, wv2.WV_ADD_NAVIGATION_STARTING) == "add_NavigationStarting"
    assert at(W, wv2.WV_ADD_NAVIGATION_COMPLETED) == "add_NavigationCompleted"
    assert at(W, wv2.WV_ADD_PERMISSION_REQUESTED) == "add_PermissionRequested"
    assert at(W, wv2.WV_ADD_PROCESS_FAILED) == "add_ProcessFailed"
    assert at(W, wv2.WV_ADD_SCRIPT_ON_DOCUMENT) == "AddScriptToExecuteOnDocumentCreated"
    assert at(W, wv2.WV_EXECUTE_SCRIPT) == "ExecuteScript"
    assert at(W, wv2.WV_RELOAD) == "Reload"
    assert at(W, wv2.WV_ADD_NEW_WINDOW_REQUESTED) == "add_NewWindowRequested"
    assert at(W, wv2.WV_ADD_TITLE_CHANGED) == "add_DocumentTitleChanged"
    assert at(W, wv2.WV_GET_TITLE) == "get_DocumentTitle"
    assert at(W, wv2.WV_OPEN_DEVTOOLS) == "OpenDevToolsWindow"
    assert at(W, wv2.WV_ADD_FULLSCREEN_CHANGED) == "add_ContainsFullScreenElementChanged"
    assert at(W, wv2.WV_GET_FULLSCREEN) == "get_ContainsFullScreenElement"
    assert at(W, wv2.WV_ADD_WINDOW_CLOSE_REQUESTED) == "add_WindowCloseRequested"
    assert at(W, wv2.WV4_ADD_DOWNLOAD_STARTING) == "add_DownloadStarting"
    for index, name in ((wv2.SET_PUT_WEB_MESSAGE, "put_IsWebMessageEnabled"), (wv2.SET_PUT_STATUS_BAR, "put_IsStatusBarEnabled"),
                        (wv2.SET_PUT_DEVTOOLS, "put_AreDevToolsEnabled"), (wv2.SET_PUT_CONTEXT_MENUS, "put_AreDefaultContextMenusEnabled"),
                        (wv2.SET_PUT_HOST_OBJECTS, "put_AreHostObjectsAllowed"), (wv2.SET_PUT_ZOOM_CONTROL, "put_IsZoomControlEnabled")):
        assert at(S, index) == name
    assert at(fakes.NAV_STARTING_ARGS, wv2.NAV_GET_URI) == "get_Uri"
    assert at(fakes.NAV_STARTING_ARGS, wv2.NAV_PUT_CANCEL) == "put_Cancel"
    assert at(fakes.NAV_COMPLETED_ARGS, wv2.DONE_GET_IS_SUCCESS) == "get_IsSuccess"
    assert at(fakes.NAV_COMPLETED_ARGS, wv2.DONE_GET_ERROR) == "get_WebErrorStatus"
    assert at(fakes.NEW_WINDOW_ARGS, wv2.NEW_GET_URI) == "get_Uri"
    assert at(fakes.NEW_WINDOW_ARGS, wv2.NEW_PUT_HANDLED) == "put_Handled"
    assert at(fakes.PERMISSION_ARGS, wv2.PERM_GET_KIND) == "get_PermissionKind"
    assert at(fakes.PERMISSION_ARGS, wv2.PERM_PUT_STATE) == "put_State"
    assert at(fakes.FAILED_ARGS, wv2.FAIL_GET_KIND) == "get_ProcessFailedKind"
    assert at(fakes.DOWNLOAD_ARGS, wv2.DL_GET_RESULT_PATH) == "get_ResultFilePath"
    assert at(fakes.DOWNLOAD_ARGS, wv2.DL_PUT_RESULT_PATH) == "put_ResultFilePath"
    assert at(fakes.DOWNLOAD_ARGS, wv2.DL_PUT_HANDLED) == "put_Handled"
    # The options object's own table is the header's.
    assert [name for name, _ in wv2.EnvironmentOptions.METHODS] == ["get_args", "put_args", "get_language", "put_language",
                                                                     "get_target", "put_target", "get_sso", "put_sso"]


def test_guid_text_round_trip():
    text = "{4e8a3389-c9d8-4bd2-b6b5-124fee6cc14d}"
    guid = com.GUID.parse(text)
    assert guid.Data1 == 0x4E8A3389 and guid.Data2 == 0xC9D8 and guid.Data3 == 0x4BD2
    assert bytes(guid.Data4) == bytes.fromhex("b6b5124fee6cc14d")
    assert guid.text() == text
    assert com.norm_iid(text.upper()) == text


def test_python_objects_answer_as_com_objects_do():
    seen = []
    handler = wv2.EventHandler(wv2.IID_NavigationStartingEventHandler, lambda args: seen.append(args))
    assert com.query(handler.ptr, wv2.IID_NavigationStartingEventHandler) == handler.ptr
    assert handler.refs == 2
    com.release(handler.ptr)
    assert com.query(handler.ptr, com.IID_IUnknown) == handler.ptr
    com.release(handler.ptr)
    assert com.query(handler.ptr, wv2.IID_NewWindowRequestedEventHandler) == 0  # not what it is
    assert fakes.invoke(handler.ptr, (fakes.PTR, fakes.PTR), 0x10, 0x20) == 0
    assert seen == [0x20]
    before = com.live_objects()
    handler.drop()
    assert com.live_objects() == before - 1
    com.collect()


def test_an_error_in_a_handler_stays_on_this_side(caplog):
    def broken(_args):
        raise RuntimeError("boom")

    handler = wv2.EventHandler(wv2.IID_ProcessFailedEventHandler, broken)
    assert fakes.invoke(handler.ptr, (fakes.PTR, fakes.PTR), 0, 0) == 0
    assert "boom" in caplog.text
    handler.drop()


def test_options_give_strings_the_engine_frees():
    options = wv2.EnvironmentOptions(arguments="--a --b", language="")
    out = fakes.c_void_p()
    found = com.query(options.ptr, fakes.IID_OPTIONS)
    assert found == options.ptr
    assert com.method(found, 3, (fakes.OUT,))(found, fakes.byref(out)) == 0
    assert com.take_string(out.value) == "--a --b"
    assert com.method(found, 7, (fakes.OUT,))(found, fakes.byref(out)) == 0
    assert com.take_string(out.value) == wv2.TARGET_VERSION
    com.release(found)


def test_find_runtime_from_the_installers_record_and_from_folders():
    base = r"C:\Program Files (x86)\Microsoft\EdgeWebView\Application"
    dll = lambda version: ntpath.join(base, version, "EBWebView", "x64", "EmbeddedBrowserWebView.dll")  # noqa: E731

    def registry(hive, key, names):
        if hive == "HKEY_LOCAL_MACHINE" and key.endswith(r"ClientState" + "\\" + wv2.RUNTIME_CLIENT):
            return {"EBWebView": base + "\\142.0.3595.80"}
        return {}

    found = wv2.find_runtime(env={}, exists=lambda p: p == dll("142.0.3595.80"), registry=registry, listdir=lambda p: [])
    assert found and found.version == "142.0.3595.80" and not found.fixed

    # No record: the newest version folder there is.
    env = {"ProgramFiles(x86)": r"C:\Program Files (x86)"}
    found = wv2.find_runtime(env=env, exists=lambda p: p in (dll("131.0.2903.70"), dll("140.0.3485.14")),
                             registry=lambda *a: {}, listdir=lambda p: ["131.0.2903.70", "SetupMetrics", "140.0.3485.14"])
    assert found and found.version == "140.0.3485.14"
    assert wv2.find_runtime(env=env, exists=lambda p: False, registry=lambda *a: {}, listdir=lambda p: []) is None

    # A fixed version named in config.ini.
    fixed = r"D:\wv2\Microsoft.WebView2.FixedVersionRuntime.142.0.3595.80.x64"
    found = wv2.find_runtime(fixed, env=env, exists=lambda p: p == ntpath.join(fixed, "EBWebView", "x64", "EmbeddedBrowserWebView.dll"),
                             registry=lambda *a: {}, listdir=lambda p: [])
    assert found and found.fixed


def test_engine_arguments_follow_the_settings():
    class C:
        web_security = False
        network_mode = "direct"
        socks = "127.0.0.1:9050"
        webview_args = ["--lang=ro"]

    switches = wv2.engine_arguments(C())
    assert "--disable-web-security" in switches and switches[-1] == "--lang=ro"
    C.network_mode, C.web_security = "offline", True
    line = wv2.quote_arguments(wv2.engine_arguments(C()))
    assert "--disable-web-security" not in line
    assert '--host-resolver-rules="MAP * ~NOTFOUND , EXCLUDE 127.0.0.1"' in line
    assert "--proxy-server=socks5://127.0.0.1:1" in line


def test_dictionary_sites_get_a_browsers_web_security():
    """The Look up key's sites run in a web view of their own: none of the app's pages' freedoms, its network mode."""
    class C:
        web_security = False
        network_mode = "direct"
        socks = "127.0.0.1:9050"
        webview_args = ["--lang=ro", "--disable-web-security"]

    assert wv2.site_arguments(C()) == ["--lang=ro"]
    C.network_mode = "tor"
    line = wv2.quote_arguments(wv2.site_arguments(C()))
    assert "--proxy-server=socks5://127.0.0.1:9050" in line and "--disable-web-security" not in line
    assert "--disable-popup-blocking" not in line and "autoplay" not in line
    C.network_mode = "offline"
    assert "--proxy-server=socks5://127.0.0.1:1" in wv2.site_arguments(C())


# ---------------------------------------------------------------- the shell, with the stand-in engine


class FakeConfig:
    def __init__(self, folder: Path):
        self.webview_dir = folder / "webview2"
        self.data_dir = folder
        self.log_dir = folder / "logs"
        self.downloads_dir = folder / "Downloads"
        self.ext_dir = folder / "ext"
        self.manifest = {}
        self.window_width, self.window_height = 1000, 700
        self.devtools = True
        self.web_security = False
        self.network_mode = "direct"
        self.socks = "127.0.0.1:9050"
        self.webview_args = []
        self.external_links = "open"
        self.extension_version = "0.7.4"
        self.webview_runtime = ""
        self.mpv_enabled = True
        self.bar_enabled = True
        self.bar_button = "top-right"


class FakeHost:
    def __init__(self):
        self.played = []

        class Mpv:
            def __init__(inner):
                inner.files = []

            def play(inner, files):
                self.played.append(files)
                return None

            def status(inner):
                return {"players": 0}

        self.mpv = Mpv()


@pytest.fixture
def setup(tmp_path, monkeypatch):
    monkeypatch.setattr(winshell, "CLOSE_GRACE_MS", 60)
    monkeypatch.setattr(winshell, "QUIT_GRACE_MS", 60)
    world = World()
    config = FakeConfig(tmp_path)
    shell = winshell.Shell(config, fakes.runtime(), "http://127.0.0.1:47999", "http://127.0.0.1:47999/dashboard/dashboard.html",
                           api=world.win, entry=world.entry)
    opened = []
    monkeypatch.setattr(winshell.webbrowser, "open", lambda url: opened.append(url))
    return world, shell, config, opened


def run_with(shell, host, driver, limit=20.0):
    """The shell's loop on this thread, the driver on another, as the HTTP threads and the user are."""
    failure = []

    def drive():
        try:
            driver()
        except BaseException as err:  # reported on the test's thread
            failure.append(err)
            shell.stop()

    thread = threading.Thread(target=drive, daemon=True)
    timer = threading.Timer(limit, shell.stop)
    timer.start()
    thread.start()
    try:
        code = shell.run(host)
    finally:
        timer.cancel()
    thread.join(5)
    if failure:
        raise failure[0]
    return code


def wait_for(test, limit=5.0):
    until = time.monotonic() + limit
    while time.monotonic() < until:
        if test():
            return True
        time.sleep(0.01)
    raise AssertionError("waited in vain")


def test_the_engine_starts_with_the_apps_options(setup):
    world, shell, config, _ = setup
    shell.start_engine()
    assert world.calls[0][:3] == ("create", 1, 0)
    assert world.calls[0][3] == str(config.webview_dir)
    assert "--disable-web-security" in world.options_read["args"]
    assert world.options_read["target"] == wv2.TARGET_VERSION
    assert world.options_read["sso"] == 0
    assert shell.engine_version == "142.0.3595.80"
    assert world.win.klass is not None
    shell.shutdown_engine()
    assert not world.unexpected


def test_a_whole_session(setup):
    world, shell, config, opened = setup
    shell.start_engine()
    host = FakeHost()
    state = {}

    def driver():
        wait_for(lambda: len(world.webviews()) == 2 and all(w.navigated for w in world.webviews()))
        background, first = world.webviews()
        assert background.navigated == ["http://127.0.0.1:47999/__sluka__/background.html"]
        assert background.controller.visible is False
        assert first.navigated == ["http://127.0.0.1:47999/dashboard/dashboard.html"]
        assert first.controller.visible is True and first.controller.bounds is not None
        token = first.token()
        assert token.startswith("w") and background.token().startswith("bg")
        # 1000 x 700 at 150 % fits the screen as it is; a taller window would have been made to fit.
        window = world.win.windows[first.controller.hwnd]
        assert (window["w"], window["h"]) == (1500, 1050) and "x" not in window
        # Settings as the app wants them.
        values = world.settings[-1].values
        assert values["IsStatusBarEnabled"] is False and values["AreDevToolsEnabled"] is True and values["AreHostObjectsAllowed"] is False

        # The title follows the page's.
        wait_for(lambda: any(w["title"] == "Title of dashboard.html" for w in world.win.app_windows().values()))

        # The page says hello and gets its tab number; later calls name the window.
        shell.register({"tabId": 77, "url": first.navigated[0]}, token)
        wait_for(lambda: shell.call(lambda: shell.find(tab_id=77)) is not None)

        # Opening the page that is already shown (within the first seconds) brings that window forward.
        answer = shell.request("open", {"url": "http://127.0.0.1:47999/dashboard/dashboard.html", "kind": "tab"})
        assert answer == {"ok": True, "handled": True, "reusedTabId": 77}

        # A new page gets a window of its own.
        answer = shell.request("open", {"url": "http://127.0.0.1:47999/books/books.html", "kind": "tab"})
        assert answer == {"ok": True, "handled": True}
        wait_for(lambda: len(world.webviews()) == 3 and world.webviews()[2].navigated)
        books = world.webviews()[2]

        # A link to a website is the user's browser's; the window stays on Sluka's page.
        books.fire("NavigationStarting", args := fakes.NavStartingArgs(world, uri="https://example.org/word"))
        assert args.cancel
        wait_for(lambda: opened == ["https://example.org/word"])

        # window.open of one of the app's pages: a window of the app's; of a website: the browser.
        world.later(lambda: state.setdefault("nw", books.fire("NewWindowRequested", fakes.NewWindowArgs(world, uri="http://127.0.0.1:47999/audio/audio.html"))))
        wait_for(lambda: len(world.webviews()) == 4)
        assert state["nw"].handled
        world.later(lambda: state.setdefault("nw2", books.fire("NewWindowRequested", fakes.NewWindowArgs(world, uri="https://example.org/x"))))
        wait_for(lambda: opened[-1] == "https://example.org/x")

        # Permissions.
        own = "http://127.0.0.1:47999/books/library.html"
        for kind, uri, expected in ((6, "", 1), (4, "", 2), (1, "", 0), (13, own, 1), (13, "https://example.org/", 1),
                                    (15, own, 1), (14, own, 1), (15, "https://example.org/", 0), (14, "", 0)):
            box = {}
            world.later(lambda kind=kind, uri=uri, box=box: box.setdefault("a", books.fire("PermissionRequested", fakes.PermissionArgs(world, uri=uri, kind=kind))))
            wait_for(lambda box=box: "a" in box)
            assert box["a"].state == expected, (kind, uri)

        # A download goes to the app's folder, under a name not taken yet.
        config.downloads_dir.mkdir(parents=True, exist_ok=True)
        (config.downloads_dir / "words.csv").write_text("x")
        box = {}
        world.later(lambda: box.setdefault("d", books.fire("DownloadStarting", fakes.DownloadArgs(world, uri="", suggested="C:\\Users\\u\\Downloads\\words.csv"))))
        wait_for(lambda: "d" in box)
        assert box["d"].result == str(config.downloads_dir / "words (1).csv")

        # Full screen for a video, and back.
        books.fullscreen = True
        world.later(lambda: books.fire("ContainsFullScreenElementChanged"))
        hwnd = books.controller.hwnd
        wait_for(lambda: world.win.windows[hwnd]["w"] == 2880)
        assert world.win.windows[hwnd]["style"] & 0x80000000  # WS_POPUP
        assert books.controller.bounds == (0, 0, 2880 - 16, 1620 - 39)
        books.fullscreen = False
        world.later(lambda: books.fire("ContainsFullScreenElementChanged"))
        wait_for(lambda: world.win.windows[hwnd].get("placed") == 1)
        assert world.win.windows[hwnd]["style"] & winshell.WS_OVERLAPPEDWINDOW == winshell.WS_OVERLAPPEDWINDOW

        # The window menu.
        items = [text for _f, _i, text in world.win.menus[hwnd] if text]
        assert any("mpv" in t for t in items) and any("About" in t for t in items) and any("Developer" in t for t in items)
        world.win.system_command(hwnd, winshell.MENU_ZOOM_IN)
        wait_for(lambda: abs(books.controller.zoom - 1.1) < 1e-9)
        world.win.system_command(hwnd, winshell.MENU_RELOAD)
        wait_for(lambda: books.reloads == 1)
        world.win.system_command(hwnd, winshell.MENU_DEVTOOLS)
        wait_for(lambda: books.devtools == 1)
        world.win.system_command(hwnd, winshell.MENU_MPV)
        wait_for(lambda: host.played == [["C:\\films\\film.mkv", "C:\\films\\film.srt"]])

        # A film the page cannot play: mpv is offered (and declined here).
        shell.request("media-failed", {"code": 4}, token)
        wait_for(lambda: any("cannot play" in text for _o, text, _f in world.win.boxes))

        # A renderer that crashed is loaded again.
        world.later(lambda: books.fire("ProcessFailed", fakes.FailedArgs(world, uri="", kind=1)))
        wait_for(lambda: books.reloads == 2)

        # Closing by the page (tabs.remove), by window.close(), and by the user.
        assert shell.request("close", {"tabId": 77}) == {"ok": True, "handled": True}
        wait_for(lambda: first.controller.closed)
        audio = world.webviews()[3]
        world.later(lambda: audio.fire("WindowCloseRequested"))
        wait_for(lambda: audio.controller.closed)
        world.win.close(hwnd)
        wait_for(lambda: books.controller.closed)

    code = run_with(shell, host, driver)
    assert code == 0
    background = world.webviews()[0]
    assert background.controller.closed
    assert not world.unexpected, world.unexpected
    shell.shutdown_engine()
    # Everything the app held of the engine's was let go: only the engine's own references are left.
    for controller in world.controllers:
        assert controller.refs == 1, controller
        assert controller.webview.refs == 1
    for settings in world.settings:
        assert settings.refs == 0


def test_the_hidden_windows_stay_hidden(setup, caplog):
    """The worker page's window is never seen: asked to show itself, by whatever, it stays hidden (seen, it would be
    an empty white window that does nothing)."""
    world, shell, config, _ = setup
    shell.start_engine()
    state = {}

    def driver():
        wait_for(lambda: len(world.webviews()) == 2 and all(w.navigated for w in world.webviews()))
        background, first = world.webviews()
        hidden, shown = background.controller.hwnd, first.controller.hwnd
        assert world.win.windows[hidden]["visible"] is False and world.win.windows[shown]["visible"] is True
        world.later(lambda: state.setdefault("asked", world.win.ShowWindow(hidden, winshell.SW_SHOW)))
        world.later(lambda: world.win.ShowWindow(hidden, winshell.SW_SHOWNORMAL))
        wait_for(lambda: world.win.windows[hidden].get("refused") == 2)
        assert world.win.windows[hidden]["visible"] is False
        # The app's own windows show as before.
        world.later(lambda: world.win.ShowWindow(shown, winshell.SW_HIDE))
        world.later(lambda: world.win.ShowWindow(shown, winshell.SW_SHOW))
        wait_for(lambda: world.win.windows[shown]["shows"][-1] == winshell.SW_SHOW)
        assert world.win.windows[shown]["visible"] is True
        state["kept"] = shell.call(lambda: shell.views[0].kept_hidden)
        # Made to show without being asked (as the frozen white window was): out of sight again at once.
        world.later(lambda: world.win.shown_unasked(hidden))
        wait_for(lambda: world.win.windows[hidden]["visible"] is True or world.win.windows[hidden]["shows"][-1:] == [winshell.SW_HIDE])
        wait_for(lambda: world.win.windows[hidden]["visible"] is False)
        assert world.win.windows[hidden]["shows"][-1] == winshell.SW_HIDE
        # Nor by a style that shows it.
        world.later(lambda: world.win.give_style(hidden, world.win.windows[hidden]["style"] | winshell.WS_VISIBLE))
        time.sleep(0.3)
        assert world.win.windows[hidden]["visible"] is False and not world.win.windows[hidden]["style"] & winshell.WS_VISIBLE
        # Its X (were it ever seen): out of sight, and the background worker still there.
        world.win.close(hidden)
        time.sleep(0.5)
        assert not world.win.windows[hidden]["destroyed"] and background.controller is not None
        state["views"] = shell.call(lambda: [v.hidden for v in shell.views])
        world.win.close(shown)

    assert run_with(shell, FakeHost(), driver) == 0
    shell.shutdown_engine()
    assert state["kept"] == 2 and state["views"][0] is True
    assert sum("was asked to show itself" in r.getMessage() for r in caplog.records) == 1
    found = [r.getMessage() for r in caplog.records if "was found on the screen" in r.getMessage()]
    assert len(found) == 1 and "style 0x" in found[0]


def test_a_window_taller_than_the_screen_is_made_to_fit(setup):
    world, shell, config, _ = setup
    shell.start_engine()
    config.window_height = 1400  # 2100 at 150 %, on a screen 1572 high
    host = FakeHost()

    def driver():
        wait_for(lambda: len(world.webviews()) == 2)
        window = world.win.windows[world.webviews()[1].controller.hwnd]
        assert window["h"] == int(1572 * 0.95) and window["y"] >= 0 and window["y"] + window["h"] <= 1572
        world.win.close(world.webviews()[1].controller.hwnd)

    assert run_with(shell, host, driver) == 0
    shell.shutdown_engine()


def test_a_view_that_cannot_be_made_is_said(setup):
    world, shell, config, _ = setup
    shell.start_engine()
    world.fail_controllers = True

    def driver():
        wait_for(lambda: any("background page could not be started" in text for _o, text, _f in world.win.boxes))

    code = run_with(shell, FakeHost(), driver)
    assert code == 0
    shell.shutdown_engine()


def test_every_window_has_setups_black_title_bar(setup):
    """Black title bars, as Setup's, whatever Windows' own theme (here: light)."""
    world, shell, config, opened = setup
    shell.dark = False
    shell.start_engine()
    host = FakeHost()

    def driver():
        wait_for(lambda: len(world.webviews()) == 2 and all(w.navigated for w in world.webviews()))
        hwnd = world.webviews()[1].controller.hwnd
        got = {a: v for h, a, v in world.win.dwm if h == hwnd}
        assert got[20] == 1 and got[35] == 0x101111 and got[36] == 0xEBF0F2 and got[34] == 0x2B2E2E
        shell.stop()

    run_with(shell, host, driver)
    assert not world.unexpected, world.unexpected


def test_the_look_up_keys_windows(setup):
    """A dictionary site in a small window from its own engine (its own data folder and command line, no app token, kept
    to sites); an offline dictionary's page in one of the app's; each kind reused for the next word."""
    world, shell, config, opened = setup
    shell.start_engine()
    host = FakeHost()

    def driver():
        wait_for(lambda: len(world.webviews()) == 2 and all(w.navigated for w in world.webviews()))
        app_options = dict(world.options_read)
        shell.open_dictionary("https://jisho.org/search/%E9%9D%A2%E5%80%92", False)
        wait_for(lambda: len(world.webviews()) == 3 and world.webviews()[2].navigated)
        site = world.webviews()[2]
        created = [c for c in world.calls if c[0] == "create"]
        assert len(created) == 2 and created[1][3] == str(config.data_dir / "webview2-dictionaries")
        assert "--disable-web-security" not in world.options_read["args"] and "--disable-web-security" in app_options["args"]
        assert site.navigated == ["https://jisho.org/search/%E9%9D%A2%E5%80%92"]
        assert site.token() == ""  # (no way into the app's API)
        window = world.win.windows[site.controller.hwnd]
        assert (window["w"], window["h"]) == (780, 1020)  # (520 x 680 at 150 %)
        # The site may go elsewhere on the web, never to the app's own pages.
        wait_for(lambda: site.source == "https://jisho.org/search/%E9%9D%A2%E5%80%92")
        args = site.fire("NavigationStarting", fakes.NavStartingArgs(world, uri="http://127.0.0.1:47999/dashboard/dashboard.html"))
        assert args.cancel
        args = site.fire("NavigationStarting", fakes.NavStartingArgs(world, uri="https://www.weblio.jp/content/x"))
        assert not args.cancel
        # The next word: the same window.
        shell.open_dictionary("https://jisho.org/search/%E6%98%A5", False)
        wait_for(lambda: len(site.navigated) == 2)
        assert len(world.webviews()) == 3
        # An offline dictionary: the app's page, in a window of the app's engine.
        shell.open_dictionary("/__sluka__/dict.html?d=jmdict&lang=ja&q=%E6%98%A5", True)
        wait_for(lambda: len(world.webviews()) == 4 and world.webviews()[3].navigated)
        own = world.webviews()[3]
        assert own.navigated == ["http://127.0.0.1:47999/__sluka__/dict.html?d=jmdict&lang=ja&q=%E6%98%A5"]
        assert own.token() != ""
        assert len([c for c in world.calls if c[0] == "create"]) == 2
        assert opened == []  # (nothing went to the system's browser)
        shell.stop()

    run_with(shell, host, driver)
    assert not world.unexpected, world.unexpected


def test_the_check_goes_step_by_step(tmp_path, monkeypatch):
    world = World()
    lines = []

    class Out:
        def write(self, text):
            lines.append(text)

        def flush(self):
            pass

    config = FakeConfig(tmp_path)
    monkeypatch.setattr("sluka_desktop.config.local_dir", lambda: tmp_path / "local")
    code = winshell.check(config, api=world.win, entry=world.entry, out=Out(), runtime=fakes.runtime())
    said = "".join(lines)
    assert code == 0, said
    assert "a script in the page answered: FakeEngine/142" in said
    assert world.calls[0][3] == str(tmp_path / "local" / "webview-check")
    assert not world.unexpected


# ---------------------------------------------------------------- the whole app: host, HTTP server, shell


def tiny_png(size: int) -> bytes:
    raw = b"".join(b"\x00" + b"\xff\x00\x00\xff" * size for _ in range(size))

    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)

    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


def make_app(root: Path, port: int) -> Config:
    ext = root / "extension"
    for page in ("dashboard/dashboard.html", "books/books.html"):
        (ext / page).parent.mkdir(parents=True, exist_ok=True)
        (ext / page).write_text("<!doctype html><html><head><title>t</title></head><body>page</body></html>")
    (ext / "icons").mkdir()
    for size in (16, 32, 128):
        (ext / "icons" / f"icon-{size}.png").write_bytes(tiny_png(size))
    (ext / "background").mkdir()
    (ext / "background" / "service-worker.js").write_text("// worker\n")
    (ext / "manifest.json").write_text(json.dumps({
        "manifest_version": 3, "name": "Sluka", "version": "0.7.4",
        "icons": {"16": "icons/icon-16.png", "32": "icons/icon-32.png", "128": "icons/icon-128.png"},
        "background": {"service_worker": "background/service-worker.js"},
    }))
    (root / "config.ini").write_text(f"[app]\nport = {port}\n[mpv]\nenabled = no\n[anki]\nenabled = no\n")
    config = Config(root=root, extension=ext, data=root / "data")
    config.load_manifest()
    config.ensure_dirs()
    return config


def free_port() -> int:
    import socket

    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def post(port, name, body, view=None):
    request = urllib.request.Request(f"http://127.0.0.1:{port}/__sluka__/api/{name}", data=json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json", **({"X-Sluka-View": view} if view else {})})
    with urllib.request.urlopen(request, timeout=10) as answer:
        return json.loads(answer.read())


def test_the_app_end_to_end(tmp_path, monkeypatch):
    monkeypatch.setattr(winshell, "CLOSE_GRACE_MS", 60)
    monkeypatch.setattr(winshell, "QUIT_GRACE_MS", 60)
    port = free_port()
    config = make_app(tmp_path, port)
    assert config.shell == "gtk" and config.port == port  # (this is Linux; the shell is asked for by hand below)
    world = World()
    failure = []

    def driver():
        try:
            wait_for(lambda: len(world.webviews()) == 2 and world.webviews()[1].navigated, 10)
            first = world.webviews()[1]
            token = first.token()
            # The page itself, as the web view gets it: Sluka's file with the shim put in.
            with urllib.request.urlopen(first.navigated[0], timeout=10) as answer:
                page = answer.read().decode()
            assert "/__sluka__/shim.js" in page
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/__sluka__/boot.js", timeout=10) as answer:
                boot = answer.read().decode()
            assert '"shell": "webview2"' in boot
            info = post(port, "info", {})
            assert info["pid"] == os.getpid() and info["engine"].startswith("WebView2 142.0.3595.80")
            assert post(port, "hello", {"tabId": 5, "role": "tab", "url": first.navigated[0]}, view=token) == {"ok": True}
            answer = post(port, "shell", {"op": "open", "url": f"http://127.0.0.1:{port}/books/books.html", "kind": "tab"}, view=token)
            assert answer["ok"] and answer["handled"]
            wait_for(lambda: len(world.webviews()) == 3, 10)
            # The page closes its own window by name, without a tab number.
            assert post(port, "shell", {"op": "close"}, view=token) == {"ok": True, "handled": True}
            wait_for(lambda: first.controller.closed, 10)
            # A second start of the app is answered by this one.
            from sluka_desktop.browsershell import ask_running_copy, running_copy

            assert running_copy(port)
            assert ask_running_copy(port, f"http://127.0.0.1:{port}/dashboard/dashboard.html")
            wait_for(lambda: len(world.webviews()) == 4, 10)
            for view in world.webviews()[2:]:
                world.win.close(view.controller.hwnd)
        except BaseException as err:
            failure.append(err)
            for hwnd in list(world.win.app_windows()):
                world.win.close(hwnd)

    thread = threading.Thread(target=driver, daemon=True)
    thread.start()
    code = winshell.run_app(config, api=world.win, entry=world.entry, runtime=fakes.runtime())
    thread.join(10)
    if failure:
        raise failure[0]
    assert code == 0
    assert not world.unexpected, world.unexpected
    assert (config.data_dir / "sluka.ico").is_file()
    from sluka_desktop.iconfile import png_size

    ico = (config.data_dir / "sluka.ico").read_bytes()
    assert struct.unpack("<HHH", ico[:6]) == (0, 1, 3)
    log = (config.log_dir / "sluka-desktop.log")
    crash = (config.log_dir / "crash.log").read_text()
    assert "anything below is a crash" in crash and "Fatal" not in crash
