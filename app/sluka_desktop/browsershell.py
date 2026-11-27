# SPDX-License-Identifier: LicenseRef-Sluka
# Copyright (c) 2026 Sluka. Part of Sluka Desktop; see LICENSE.txt.
"""The desktop windows as a browser's own: where Windows' own web view is missing, or asked against.

On Windows the app's windows are normally its own (``winshell``).  This is the
other way, kept for a Windows without its web view and for testing: a
Chromium browser shows each of
Sluka's pages in a window without address bar ("app mode"), with a profile of
its own inside the app's data folder, apart from the user's browsing.  The
pages are served to it by ``host.Host`` over HTTP on the loopback address
(``httpd.Server``), which is what the app's tests have always driven.

Three things differ from the WebKitGTK shell, and the page script
(``web/shim.js``) knows them by ``shell: "browser"``:

*   A browser has no hidden window to give Sluka's background worker.  Asked
    over its own debugging protocol (``cdp``), a current one makes a page that
    is in no window, and the worker runs there.  Where that cannot be had, one
    of the open windows holds the worker in a frame nobody sees, and another
    takes it over when that window is closed.  Either way the app runs for as
    long as a window is open (minimised will do), and mpv and Anki are answered
    for exactly that long.

*   A browser gives the pages ``http:`` where Sluka looks for its own
    ``chrome-extension:`` address, and will not lend that address to anything
    but a real extension.  The two tests Sluka's files make of their own
    address are answered as they are served (``devserver.EXTENSION_SCHEME_CHECKS``);
    the files on disk are not touched, and nothing else in them is.

*   An extension may read any website, as Sluka does for translation and
    dictionaries; a page of a local program may not.  The app's own browser
    profile is therefore started with that rule off ([browser] web_security),
    and links to websites are handed to the user's own browser, so that this
    profile shows nothing but Sluka.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import signal
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from pathlib import Path

from . import APP_NAME, __version__, cdp
from .config import WINDOWS, Config
from .tell import problem, say
from .devserver import EXTENSION_SCHEME_CHECKS
from .host import Host
from .httpd import Server

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
#: How long the window that holds the background worker is kept waiting when it asks whether to go on.
ALIVE_HOLD = 20.0
#: No such question for this long, with the browser this app started gone: the windows are closed.
GONE_AFTER = 30.0
#: How long the first window may take to come up.
START_GRACE = 90.0
#: A browser that ended sooner than this handed the window to a copy of itself that was already running.
HANDED_OVER_WITHIN = 8.0
#: How long a first window is waited for when the browser ended at once and said it failed.
FAILED_GRACE = 15.0

#: The Chromium from which a browser can be asked for a page that is in no window (Target.createTarget, hidden).
HIDDEN_PAGES_SINCE = 136


def engine_major(user_agent: str, product: str = "") -> int:
    """The Chromium a browser is built on, as its first number; 0 if it does not say."""
    import re

    for text, pattern in ((user_agent, r"\bChrom(?:e|ium)/(\d+)"), (product, r"/(\d+)")):
        found = re.search(pattern, text or "")
        if found:
            return int(found.group(1))
    return 0


#: Chromium browsers, first choice first: (name, program on Windows, where under a "Program Files" folder).
WINDOWS_BROWSERS = (
    ("Microsoft Edge", "msedge.exe", r"Microsoft\Edge\Application"),
    ("Google Chrome", "chrome.exe", r"Google\Chrome\Application"),
    ("Brave", "brave.exe", r"BraveSoftware\Brave-Browser\Application"),
    ("Vivaldi", "vivaldi.exe", r"Vivaldi\Application"),
    ("Chromium", "chrome.exe", r"Chromium\Application"),
)
UNIX_BROWSERS = (
    ("Microsoft Edge", "microsoft-edge"), ("Microsoft Edge", "microsoft-edge-stable"),
    ("Google Chrome", "google-chrome"), ("Google Chrome", "google-chrome-stable"),
    ("Chromium", "chromium"), ("Chromium", "chromium-browser"),
    ("Brave", "brave-browser"), ("Vivaldi", "vivaldi"),
)
MAC_BROWSERS = (
    ("Microsoft Edge", "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge"),
    ("Google Chrome", "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"),
    ("Brave", "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser"),
    ("Chromium", "/Applications/Chromium.app/Contents/MacOS/Chromium"),
)


def _registered(program: str) -> str:
    """Where Windows itself says a program is (its "App Paths"), or ''."""
    try:
        import winreg
    except ImportError:
        return ""
    for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        try:
            with winreg.OpenKey(hive, r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths" + "\\" + program) as key:
                value, _kind = winreg.QueryValueEx(key, None)
        except OSError:
            continue
        value = str(value or "").strip().strip('"')
        if value and os.path.isfile(value):
            return value
    return ""


def find_browser(config: Config, env=None, windows: bool | None = None, exists=os.path.isfile, registered=_registered) -> tuple[str, str] | None:
    """The browser to show the windows in, as (name, program); None if there is none."""
    env = os.environ if env is None else env
    windows = WINDOWS if windows is None else windows
    asked = config.browser_path
    if asked and asked.lower() != "auto":
        asked = os.path.expandvars(os.path.expanduser(asked))
        if exists(asked):
            return (Path(asked).stem, asked)
        found = shutil.which(asked)
        if found:
            return (Path(found).stem, found)
        log.warning("[browser] path = %s is not a program on this computer; looking for another", asked)
    if windows:
        bases = [env.get(name) for name in ("ProgramFiles(x86)", "ProgramFiles", "ProgramW6432", "LOCALAPPDATA")]
        for name, program, where in WINDOWS_BROWSERS:
            for base in bases:
                if base:
                    candidate = os.path.join(base, where, program)
                    if exists(candidate):
                        return (name, candidate)
            if name != "Chromium":  # which shares its program's name with Chrome
                listed = registered(program)
                if listed:
                    return (name, listed)
        return None
    if sys.platform == "darwin":
        for name, program in MAC_BROWSERS:
            if exists(program):
                return (name, program)
    for name, program in UNIX_BROWSERS:
        found = shutil.which(program)
        if found:
            return (name, found)
    return None


def browser_switches(config: Config) -> list[str]:
    """The switches every start of the browser is given: its own profile, and what an app needs of it."""
    switches = [
        f"--user-data-dir={config.browser_dir}",
        "--no-first-run",
        "--no-default-browser-check",
        # The window that holds Sluka's worker must go on working while it is minimised or covered.
        "--disable-background-timer-throttling",
        "--disable-renderer-backgrounding",
        "--disable-backgrounding-occluded-windows",
        # When the last window is closed, the browser is to end, and the app with it.
        "--disable-background-mode",
        # Sluka opens its reader and its panels itself, and says words aloud without a click.
        "--disable-popup-blocking",
        "--autoplay-policy=no-user-gesture-required",
        # A page in the language being learned is not to be offered for translation by the browser.
        "--disable-features=Translate,TranslateUI,IntensiveWakeUpThrottling",
    ]
    if not config.browser_web_security:
        # What an extension's "<all_urls>" is to a browser: Sluka's pages may read other sites.
        # (--test-type only keeps the browser from showing a warning bar about the first switch.)
        switches += ["--disable-web-security", "--test-type"]
    mode = config.network_mode
    if mode in ("tor", "offline"):
        # offline: a proxy nothing listens on, so every site is refused at once, names unresolved.
        proxy = config.socks if mode == "tor" else "127.0.0.1:1"
        switches += [f"--proxy-server=socks5://{proxy}", "--host-resolver-rules=MAP * ~NOTFOUND , EXCLUDE 127.0.0.1"]
    return switches + list(config.browser_args)


def system_ui_font() -> str:
    """The family Windows sets its own messages in, which is what a page's system-ui means there."""
    if not WINDOWS:
        return ""
    try:
        import ctypes

        # NONCLIENTMETRICSW, as bytes: its last LOGFONTW is the message font, the face name 28 bytes into it.
        size = 504
        buffer = ctypes.create_string_buffer(size)
        ctypes.memmove(buffer, ctypes.byref(ctypes.c_uint32(size)), 4)
        if not ctypes.windll.user32.SystemParametersInfoW(0x0029, size, buffer, 0):
            return "Segoe UI"
        name = buffer.raw[436:500].decode("utf-16-le", "replace").split("\0", 1)[0].strip()
        return name or "Segoe UI"
    except Exception:
        return "Segoe UI"


#: For the app's own questions to itself.  Never through a proxy: Windows' own setting for one would send a
#: request for this computer's address to another computer.
_straight = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def running_copy(port: int, timeout: float = 1.5) -> bool:
    """Whether this app is already serving on the port."""
    try:
        with _straight.open(f"http://127.0.0.1:{port}/__sluka__/api/info", timeout=timeout) as answer:
            info = json.loads(answer.read(200000).decode("utf-8", "replace"))
    except (OSError, ValueError, urllib.error.URLError):
        return False
    return isinstance(info, dict) and isinstance(info.get("app"), dict) and info["app"].get("name") == APP_NAME


def allow_foreground(port: int) -> None:
    """Let the running copy bring its new window to the front.

    Windows lets only the program the user is working with put a window in front of the others; this one,
    just started, is that program, and passes the right on.
    """
    if not WINDOWS:
        return
    pid = 0
    try:
        with _straight.open(f"http://127.0.0.1:{port}/__sluka__/api/info", timeout=1.5) as answer:
            pid = int(json.loads(answer.read(200000).decode("utf-8", "replace")).get("pid") or 0)
    except (OSError, ValueError, TypeError, AttributeError, urllib.error.URLError):
        pid = 0
    try:
        import ctypes

        allow = ctypes.windll.user32.AllowSetForegroundWindow
        allow.argtypes = [ctypes.c_uint32]
        allow(pid if pid > 0 else 0xFFFFFFFF)  # ASFW_ANY where the running copy did not say who it is
    except Exception:
        pass


def ask_running_copy(port: int, url: str) -> bool:
    """Have the copy that is already running open a window."""
    allow_foreground(port)
    body = json.dumps({"op": "open", "url": url, "kind": "tab", "again": True}).encode("utf-8")
    request = urllib.request.Request(f"http://127.0.0.1:{port}/__sluka__/api/shell", data=body,
                                     headers={"Content-Type": "application/json"}, method="POST")
    try:
        with _straight.open(request, timeout=5) as answer:
            return answer.status == 200
    except (OSError, urllib.error.URLError):
        return False


class BrowserShell:
    """The window manager the host talks to: here, a browser started with the right switches."""

    def __init__(self, config: Config, browser: tuple[str, str], origin: str):
        self.config = config
        self.name, self.program = browser
        self.origin = origin
        self.proc: subprocess.Popen | None = None
        self.launched = 0.0
        self.started = time.monotonic()
        #: When the window that holds the worker last asked whether to go on.
        self.last_alive = 0.0
        self.ever_alive = False
        #: The pages that said hello, by their tab number.
        self.tabs: dict[int, str] = {}
        self.calls: list[dict] = []
        self._lock = threading.Lock()
        self._stop = threading.Event()
        #: The browser's own channel, and the page it made for the worker, if it could be asked for one.
        self.channel: cdp.Channel | None = None
        self.worker_page = ""
        self._seen_windows = False
        self._none_since = 0.0

    # ------------------------------------------------------------ the browser

    def command(self, url: str, width: int = 0, height: int = 0, first: bool = False) -> list[str]:
        args = [self.program] + browser_switches(self.config)
        if first and self.config.browser_hidden_worker:
            # The browser picks a port on this computer and says which in its profile folder (cdp.connect).
            args.append("--remote-debugging-port=0")
        if width and height:
            args.append(f"--window-size={int(width)},{int(height)}")
        return args + [f"--app={url}"]

    def launch(self, url: str, width: int = 0, height: int = 0) -> bool:
        """A window on ``url``.  The first call starts the browser; later ones are passed on to it by the browser itself."""
        first = self.proc is None
        if first:
            cdp.forget_port_file(self.config.browser_dir)
        args = self.command(url, width, height, first)
        options: dict = {"stdin": subprocess.DEVNULL, "stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL, "close_fds": True}
        if not WINDOWS:
            options["start_new_session"] = True
        try:
            proc = subprocess.Popen(args, **options)
        except OSError as err:
            log.error("%s could not be started (%s): %s", self.name, self.program, err)
            return False
        with self._lock:
            if self.proc is None or self.proc.poll() is not None:
                self.proc = proc
                self.launched = time.monotonic()
        return True

    def attach(self) -> None:
        """Ask the browser for the page that is in no window, for Sluka's worker; without it a window holds the worker."""
        if not self.config.browser_hidden_worker:
            return
        proc = self.proc
        channel = cdp.connect(self.config.browser_dir, wait=20.0,
                              alive=lambda: not self._stop.is_set() and proc is not None and proc.poll() is None)
        if channel is None:
            log.info("%s could not be spoken to directly: Sluka's worker lives in whichever window is open", self.name)
            return
        self.channel = channel
        try:
            version = channel.call("Browser.getVersion")
            product = str(version.get("product") or "")
            major = engine_major(str(version.get("userAgent") or ""), product)
            if major < HIDDEN_PAGES_SINCE:
                # An older browser would not know the word "hidden", and put the page in a window.
                log.info("%s is too old to make a page out of sight: Sluka's worker lives in whichever window is open", product or self.name)
                return
            made = channel.call("Target.createTarget", {"url": f"{self.origin}/__sluka__/background.html", "hidden": True})
            self.worker_page = str(made.get("targetId") or "")
            log.info("%s: a page out of sight was made for Sluka's worker", product or self.name)
        except (RuntimeError, cdp.Closed) as err:
            log.info("%s makes no page out of sight (%s): Sluka's worker lives in whichever window is open", self.name, err)

    def _windows(self) -> int | None:
        """How many of the app's windows the browser has; None if it cannot be asked."""
        channel = self.channel
        if channel is None or not channel.open:
            return None
        try:
            found = channel.call("Target.getTargets", timeout=4.0).get("targetInfos") or []
        except (RuntimeError, cdp.Closed):
            return None
        # The app's own pages only: a browser may keep pages of its own that are in no window (Edge has some).
        return sum(1 for t in found if t.get("type") == "page" and t.get("targetId") != self.worker_page
                   and (self.is_own(str(t.get("url") or "")) or str(t.get("url") or "") in ("", "about:blank")))

    def is_own(self, url: str) -> bool:
        return url.startswith(self.origin + "/") or url == self.origin or url.startswith("blob:" + self.origin)

    def open_external(self, url: str) -> None:
        if not url or urllib.parse.urlsplit(url).scheme not in ("http", "https", "mailto"):
            return
        if self.config.external_links == "ignore":
            return
        try:
            # The user's own browser, with their own profile: not the one this app runs.
            webbrowser.open(url)
        except Exception:
            log.exception("could not hand a link to the system's browser")

    # ------------------------------------------------------------ what pages ask for

    def register(self, info: dict, view=None) -> None:
        if isinstance(info.get("tabId"), int):
            with self._lock:
                self.tabs[info["tabId"]] = str(info.get("url") or "")
                for old in list(self.tabs)[:-60]:
                    del self.tabs[old]

    def request(self, op: str, args: dict, view=None) -> dict:
        if op == "alive":
            # Asked by the window that holds Sluka's worker, again as soon as it is answered: while the
            # question keeps coming there is a window, whatever became of the process this app started.
            self.last_alive = time.monotonic()
            self.ever_alive = True
            self._stop.wait(ALIVE_HOLD)
            self.last_alive = time.monotonic()
            return {"ok": True, "handled": True, "stop": self._stop.is_set()}
        with self._lock:
            self.calls.append({"op": op, **{k: v for k, v in args.items() if k in ("url", "kind", "tabId")}})
            del self.calls[:-200]
        if op == "open":
            return self._op_open(args)
        if op == "external":
            self.open_external(str(args.get("url") or ""))
            return {"ok": True, "handled": True}
        # Moving, closing and sizing a window are the browser's and the page's own business here.
        return {"ok": True, "handled": False}

    def _op_open(self, args: dict) -> dict:
        url = str(args.get("url") or "")
        if not self.is_own(url):
            self.open_external(url)
            return {"ok": True, "handled": True}
        path = urllib.parse.urlsplit(url).path
        kind = str(args.get("kind") or "tab")
        if kind == "tab" and not args.get("again") and time.monotonic() - self.started < REUSE_SECONDS:
            with self._lock:
                showing = [(tab, at) for tab, at in self.tabs.items() if urllib.parse.urlsplit(at).path == path]
            if showing:
                return {"ok": True, "handled": True, "reusedTabId": showing[-1][0]}
            if path == urllib.parse.urlsplit(self.first_url).path and not self.tabs:
                # The window this app opened at its start is on that page, and has not said hello yet.
                return {"ok": True, "handled": True}
        popup = kind == "popup"
        ok = self.launch(url, int(args.get("width") or 0) if popup else 0, int(args.get("height") or 0) if popup else 0)
        return {"ok": ok, "handled": True}

    first_url = ""

    # ------------------------------------------------------------ how long to go on

    def wait(self) -> None:
        """Until the windows are closed (or the app is told to stop)."""
        while not self._stop.wait(1.0):
            now = time.monotonic()
            proc = self.proc
            windows = self._windows()
            if windows is not None:
                # The browser itself says how many windows there are.
                if windows > 0:
                    self._seen_windows, self._none_since = True, 0.0
                    continue
                if self._seen_windows or now - self.started > START_GRACE:
                    self._none_since = self._none_since or now
                    if now - self._none_since >= 2.0:
                        if self._seen_windows:
                            log.info("the last window was closed")
                        else:
                            self.never_shown = True
                        return
                continue
            if proc is not None and proc.poll() is None:
                continue
            if proc is not None and self.launched and now - self.launched > HANDED_OVER_WITHIN and not self._handed_over:
                # The browser this app started has ended, and it was the browser itself: every window is closed.
                log.info("%s was closed", self.name)
                return
            # It ended at once: a copy of it was already running with this profile and took the window.
            # Then only the pages can say whether they are still there.
            self._handed_over = True
            if not self.ever_alive:
                # A browser that ended with an error handed nothing over: it is not waited for as long.
                grace = START_GRACE if not (proc is not None and proc.returncode) else FAILED_GRACE
                if now - self.started > grace:
                    log.warning("no window of %s ever asked for the app: giving up", self.name)
                    self.never_shown = True
                    return
                continue
            if now - self.last_alive > GONE_AFTER:
                log.info("the windows are closed")
                return

    _handed_over = False
    #: The app gave up waiting for a first window.
    never_shown = False

    def stop(self) -> None:
        self._stop.set()

    def close(self) -> None:
        self._stop.set()
        proc = self.proc
        channel, self.channel = self.channel, None
        if channel is not None:
            # The page for the worker is in no window, so the browser may not end by itself: it is told to.
            try:
                if channel.open:
                    channel.call("Browser.close", timeout=3.0)
            except (RuntimeError, cdp.Closed):
                pass
            if proc is not None:
                try:
                    proc.wait(timeout=5)
                except (subprocess.TimeoutExpired, OSError):
                    pass
            channel.close()
        if proc is not None and proc.poll() is None:
            # The app is ending with its windows still open (it was told to): they cannot go on without it.
            try:
                proc.terminate()
            except OSError:
                pass


def run_app(config: Config, page: str = "") -> int:
    browser = find_browser(config)
    if not browser:
        problem("No browser to show the windows in was found (Microsoft Edge, Chrome, Brave, Vivaldi or Chromium).\n"
                "Name one in config.ini:  [browser]  path = C:\\...\\msedge.exe")
        return 3
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

    shell = BrowserShell(config, browser, origin)
    shell.first_url = first
    host = Host(config, shell=shell)
    host.dev_rewrites = list(EXTENSION_SCHEME_CHECKS)
    host.boot_extra = {"shell": "browser", "pickers": bool(config.browser_pickers)}
    host.engine = f"{shell.name} ({shell.program}), its windows as the app's; pages at {origin}"
    host.ui_font = system_ui_font()
    if WINDOWS:
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
        problem(f"The address {origin} could not be taken ({err}).\n"
                "Another program uses that port. Choose another in config.ini:  [browser]  port = 47822\n"
                "(Books and dictionaries are kept by the browser under the address, so choose once.)")
        return 3

    if config.mpv_enabled:
        try:
            from .mpvbridge import MpvBridge

            host.mpv = MpvBridge(config)
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

    for name in ("SIGINT", "SIGTERM", "SIGBREAK"):
        sig = getattr(signal, name, None)
        if sig is not None:
            try:
                signal.signal(sig, lambda *_: shell.stop())
            except (ValueError, OSError):
                pass  # not the main thread, or not a signal this system has

    code = 0
    try:
        if shell.launch(first, config.window_width, config.window_height):
            threading.Thread(target=shell.attach, name="sluka-browser", daemon=True).start()
            shell.wait()
            if shell.never_shown:
                problem(f"{shell.name} was started, but no window of {APP_NAME} came up ({shell.program}).\n"
                        f"The log may say why: {config.log_dir / 'sluka-desktop.log'}\n"
                        "Another browser can be named in config.ini:  [browser]  path = ...")
                code = 3
        else:
            problem(f"{shell.name} could not be started ({shell.program}).")
            code = 3
    finally:
        shell.close()
        server.shutdown()
        server.drain(5.0)
        host.close()
        log.info("%s %s has ended", APP_NAME, __version__)
    return code
