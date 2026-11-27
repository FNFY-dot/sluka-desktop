# SPDX-License-Identifier: LicenseRef-Sluka
# Copyright (c) 2026 Sluka. Part of Sluka Desktop; see LICENSE.txt.
"""The desktop windows: Sluka's pages in WebKitGTK views, with no browser.

Each window is one web view showing one of Sluka's own pages, served to it by
``host.Host`` through a custom URL scheme -- the same ``chrome-extension://``
address, with the same ID, that the pages have in a browser, so every check
Sluka makes of its own address comes out as it does there.  No socket is
opened: the web view asks this process directly.

One more web view, never shown, holds Sluka's background worker.

Works with GTK 4 + WebKitGTK 6.0 (Debian 13, Tails 7) and with GTK 3 +
WebKit2GTK 4.1 (Debian 12, Tails 6); which one is found at start.
"""

from __future__ import annotations

import glob
import importlib
import logging
import os
import queue
import secrets
import signal
import threading
import time
import urllib.parse
from pathlib import Path

from . import APP_NAME, LICENCE_NOTE, __version__
from .config import Config
from .host import Host, Request, Response, parse_query

log = logging.getLogger("sluka.shell")

APP_ID = "app.sluka.Desktop"

#: A request for a page the app is already showing is answered with that window
#: for this long after start: Sluka opens its dashboard itself on a first run.
REUSE_SECONDS = 20
#: Pages send their calls as request bodies, which a custom scheme has only had since this version.
MIN_ENGINE = (2, 40, 0)
#: How long a closed window's page is kept alive, out of sight: Sluka writes a
#: grade a moment after it is made, and writes what is owed when its page is hidden.
CLOSE_GRACE_MS = 1200
#: Largest slice of a file read into memory to answer a ranged request.
RANGE_IN_MEMORY = 64 * 1024 * 1024
#: Calls that wait on the disk.  A write to a USB stick can take long enough to
#: make every window stutter, so these are answered off the main loop.
DISK_CALLS = ("/__sluka__/api/storage", "/__sluka__/api/download")
#: The only calls that are about a window, and so are told which view asked.
WINDOW_CALLS = ("/__sluka__/api/shell", "/__sluka__/api/hello")
#: What an engine does to a page that is not on screen, which Sluka's background page never is.
HIDDEN_PAGE_FEATURES = ("HiddenPageDOMTimerThrottlingEnabled", "HiddenPageDOMTimerThrottlingAutoIncreases")

PAGES = {
    "": "dashboard/dashboard.html",
    "home": "dashboard/dashboard.html",
    "dashboard": "dashboard/dashboard.html",
    "books": "books/books.html",
    "videos": "videos/videos.html",
    "audio": "audio/audio.html",
}


class ShellUnavailable(Exception):
    pass


class Toolkit:
    """The GTK and WebKit generation in use, and the few places they differ."""

    def __init__(self):
        import gi

        try:
            repo = gi.Repository.get_default()
        except Exception:
            repo = None

        def versions(namespace: str) -> list:
            found = []
            try:
                found = list(repo.enumerate_versions(namespace))
            except Exception:
                pass
            # Asked of the files themselves where the bindings will not say.
            return found or _typelibs_on_disk(namespace)

        gtk, webkit, webkit2, soup = versions("Gtk"), versions("WebKit"), versions("WebKit2"), versions("Soup")
        if "4.0" in gtk and "6.0" in webkit and "3.0" in soup:
            choice = ("4.0", "WebKit", "6.0", "3.0")
        elif "3.0" in gtk and "4.1" in webkit2 and "3.0" in soup:
            choice = ("3.0", "WebKit2", "4.1", "3.0")
        elif "3.0" in gtk and "4.0" in webkit2 and "2.4" in soup:
            choice = ("3.0", "WebKit2", "4.0", "2.4")
        else:
            raise ShellUnavailable(
                "WebKitGTK's Python bindings were not found.\n"
                f"  found: Gtk {gtk or 'none'}, WebKit {webkit or 'none'}, WebKit2 {webkit2 or 'none'}, Soup {soup or 'none'}\n"
                "  On Tails 7 / Debian 13 install:  sudo apt install gir1.2-webkit-6.0\n"
                "  On Tails 6 / Debian 12 install:  sudo apt install gir1.2-webkit2-4.1\n"
                "  (on Tails, choose \"Install Every Time\" when asked, so it is there after a restart)"
            )
        self.gtk_version, namespace, self.webkit_version, soup_version = choice
        gi.require_version("Gtk", self.gtk_version)
        gi.require_version("Gdk", self.gtk_version)
        gi.require_version(namespace, self.webkit_version)
        gi.require_version("Soup", soup_version)
        from gi.repository import Gdk, Gio, GLib, Gtk, Soup

        self.Gtk, self.Gdk, self.Gio, self.GLib, self.Soup = Gtk, Gdk, Gio, GLib, Soup
        self.WebKit = importlib.import_module(f"gi.repository.{namespace}")
        self.gtk4 = self.gtk_version == "4.0"
        self.modern = self.webkit_version == "6.0"

    def ui_font(self) -> str:
        """The family of the desktop's own font ("Cantarell 11" is Cantarell), or "" where it cannot be asked."""
        try:
            name = self.Gtk.Settings.get_default().get_property("gtk-font-name") or ""
        except Exception:
            return ""
        try:
            gi = __import__("gi")
            gi.require_version("Pango", "1.0")
            from gi.repository import Pango

            family = Pango.FontDescription.from_string(name).get_family() or ""
        except Exception:
            # Without Pango to read it: the name is everything before the size at its end.
            family = name.rsplit(" ", 1)[0] if name[-1:].isdigit() and " " in name else name
        return family.split(",")[0].strip()

    def describe(self) -> str:
        wk = self.WebKit
        try:
            engine = f"{wk.get_major_version()}.{wk.get_minor_version()}.{wk.get_micro_version()}"
        except Exception:
            engine = "?"
        return f"GTK {self.gtk_version}, WebKitGTK {engine} (API {self.webkit_version})"

    def engine_version(self) -> tuple:
        wk = self.WebKit
        try:
            return (wk.get_major_version(), wk.get_minor_version(), wk.get_micro_version())
        except Exception:
            return (0, 0, 0)


def _typelibs_on_disk(namespace: str) -> list:
    """The versions of a binding installed, read from the names of its files."""
    folders = [d for d in os.environ.get("GI_TYPELIB_PATH", "").split(os.pathsep) if d]
    folders += glob.glob("/usr/lib/*/girepository-1.0") + ["/usr/lib/girepository-1.0", "/usr/lib64/girepository-1.0", "/usr/local/lib/girepository-1.0"]
    found = []
    for folder in folders:
        for path in glob.glob(os.path.join(glob.escape(folder), f"{namespace}-*.typelib")):
            version = os.path.basename(path)[len(namespace) + 1:-len(".typelib")]
            if version and version not in found:
                found.append(version)
    return found


class DiskQueue:
    """One thread for the calls that wait on the disk: one at a time, in the order they were made."""

    def __init__(self):
        self._jobs: queue.SimpleQueue = queue.SimpleQueue()
        self._thread = threading.Thread(target=self._run, name="sluka-disk", daemon=True)
        self._thread.start()

    def put(self, job) -> None:
        self._jobs.put(job)

    def _run(self) -> None:
        while True:
            job = self._jobs.get()
            if job is None:
                return
            try:
                job()
            except Exception:
                log.exception("a call that waits on the disk failed")

    def stop(self, timeout: float = 15.0) -> None:
        """Everything already asked for is done first."""
        self._jobs.put(None)
        self._thread.join(timeout)


class AppWindow:
    """One top-level window holding one of Sluka's pages."""

    def __init__(self, shell: "Shell", url: str, kind: str = "tab", width: int = 0, height: int = 0):
        tk = shell.tk
        Gtk = tk.Gtk
        self.shell = shell
        self.tab_id = None
        self.closing = False
        #: The page's last request for a file, kept after the engine's own dialog answered it.
        self.chooser_request = None
        #: When this window last offered mpv for a file its page could not play.
        self.offered_mpv = 0.0
        self.created = time.monotonic()
        self.kind = kind
        self.view = shell.new_view()
        self.window = Gtk.ApplicationWindow(application=shell.app)
        self.window.set_title(APP_NAME)
        popup = kind == "popup"
        self.window.set_default_size(
            int(width) or (520 if popup else shell.config.window_width),
            int(height) or (680 if popup else shell.config.window_height),
        )
        try:
            self.window.set_icon_name("sluka-desktop")
        except Exception:
            pass
        self._build_header()
        if tk.gtk4:
            self.window.set_child(self.view)
            self.window.connect("close-request", self._on_close_request)
        else:
            self.window.add(self.view)
            self.window.connect("delete-event", self._on_close_request)

        self.view.connect("notify::title", self._on_title)
        self.view.connect("close", lambda *_: self.close())
        self.view.connect("create", self._on_create)
        self.view.connect("decide-policy", self._on_decide_policy)
        self.view.connect("permission-request", shell.on_permission_request)
        self.view.connect("web-process-terminated", self._on_crash)
        self.view.connect("load-failed", self._on_load_failed)
        try:
            self.view.connect("run-file-chooser", self._on_file_chooser)
        except Exception as err:  # the app works without it
            log.info("file choices cannot be watched (%s)", err)

        if tk.gtk4:
            self.window.present()
        else:
            self.window.show_all()
            self.window.present()
        self.view.load_uri(url)

    # -- chrome around the page ---------------------------------------------

    def _build_header(self) -> None:
        tk = self.shell.tk
        Gtk, Gio = tk.Gtk, tk.Gio
        menu = Gio.Menu()
        if self.shell.host is not None and self.shell.host.mpv:
            section = Gio.Menu()
            section.append("Play a video in mpv with Sluka…", "app.mpv-open")
            menu.append_section(None, section)
        section = Gio.Menu()
        section.append("Reload this page", "win.reload")
        section.append("Larger", "win.zoom-in")
        section.append("Smaller", "win.zoom-out")
        section.append("Normal size", "win.zoom-reset")
        menu.append_section(None, section)
        section = Gio.Menu()
        section.append("Open Sluka's data folder", "app.data-folder")
        section.append(f"About {APP_NAME}", "app.about")
        menu.append_section(None, section)

        for name, handler in (
            ("reload", lambda *_: self.view.reload()),
            ("zoom-in", lambda *_: self._zoom(1.1)),
            ("zoom-out", lambda *_: self._zoom(1 / 1.1)),
            ("zoom-reset", lambda *_: self.view.set_zoom_level(1.0)),
        ):
            action = Gio.SimpleAction.new(name, None)
            action.connect("activate", handler)
            self.window.add_action(action)

        self.header = Gtk.HeaderBar()
        button = Gtk.MenuButton()
        button.set_menu_model(menu)
        if tk.gtk4:
            button.set_icon_name("open-menu-symbolic")
        else:
            button.set_image(Gtk.Image.new_from_icon_name("open-menu-symbolic", Gtk.IconSize.BUTTON))
            self.header.set_show_close_button(True)
            self.header.set_title(APP_NAME)
        self.header.pack_end(button)
        self.window.set_titlebar(self.header)

    def _zoom(self, factor: float) -> None:
        level = max(0.5, min(3.0, self.view.get_zoom_level() * factor))
        self.view.set_zoom_level(level)

    def _on_title(self, *_args) -> None:
        title = self.view.get_title() or APP_NAME
        self.window.set_title(title)
        if not self.shell.tk.gtk4:
            self.header.set_title(title)

    # -- where the page may go ----------------------------------------------

    def _on_decide_policy(self, _view, decision, kind) -> bool:
        wk = self.shell.tk.WebKit
        if kind == wk.PolicyDecisionType.RESPONSE:
            # What the view cannot show is saved instead (a word list exported as a file).
            try:
                if not decision.is_mime_type_supported():
                    decision.download()
                    return True
            except Exception:
                pass
            return False
        try:
            uri = decision.get_navigation_action().get_request().get_uri() or ""
        except Exception:
            return False
        if kind == wk.PolicyDecisionType.NEW_WINDOW_ACTION:
            decision.ignore()
            self.shell.open_from_page(uri)
            return True
        if self.shell.is_own(uri) or uri.startswith(("about:", "data:")):
            return False
        # Anywhere else is not this app's to show: a web view of Sluka's pages is not a browser.
        decision.ignore()
        self.shell.open_external(uri, self)
        return True

    def _on_create(self, _view, action):
        try:
            uri = action.get_request().get_uri() or ""
        except Exception:
            uri = ""
        # Opened by this app as a window of its own rather than handed back to the
        # engine: the new page then starts clean, with a tab number of its own.
        if uri:
            self.shell.tk.GLib.idle_add(lambda: self.shell.open_from_page(uri) and False)
        return None

    def _on_crash(self, _view, reason) -> None:
        log.error("the page in a window stopped (%s); loading it again", reason)
        self.shell.tk.GLib.timeout_add(500, lambda: self.view.reload() and False)

    def _on_load_failed(self, _view, _event, uri, error) -> bool:
        log.warning("could not load %s: %s", uri, getattr(error, "message", error))
        return False

    # -- the window itself --------------------------------------------------

    def _on_file_chooser(self, _view, request) -> bool:
        """Looked at, not answered: the engine's own dialog does the choosing.

        The request is kept, because once that dialog has been answered it knows
        which files the page was given -- which the page itself is never told.
        """
        self.chooser_request = request
        return False

    def chosen_files(self) -> list:
        """The files last picked for this window's page, as paths; empty when that is not known."""
        try:
            return [str(path) for path in (self.chooser_request.get_selected_files() or []) if path]
        except Exception:
            return []

    def _on_close_request(self, *_args) -> bool:
        self.close()
        return True  # closed by close(), a moment from now

    def close(self) -> None:
        """Out of sight at once; gone once the page has had the time to write what it owes."""
        if self.closing:
            return
        self.closing = True
        self.window.set_visible(False)
        self.shell.tk.GLib.timeout_add(CLOSE_GRACE_MS, self._destroy)

    def _destroy(self) -> bool:
        self.shell.window_closed(self)
        self.window.destroy()
        return False

    def present(self) -> None:
        self.window.present()

    def path(self) -> str:
        try:
            return urllib.parse.urlsplit(self.view.get_uri() or "").path
        except Exception:
            return ""


class Shell:
    """The application: its web views, its windows, and the host behind them."""

    def __init__(self, config: Config, page: str = ""):
        self.config = config
        self.tk = Toolkit()
        #: The address Sluka's pages have in a browser, unless config.ini says otherwise.
        self.scheme = config.scheme
        self.origin = f"{self.scheme}://{config.extension_id}"
        self.first_page = PAGES.get(page.strip().lower(), page or PAGES[""])
        self.windows: list[AppWindow] = []
        self.background = None
        self.background_window = None
        self.started = 0.0
        self._main_thread = threading.current_thread()
        #: Made when the app turns out to be the one running copy (_on_activate):
        #: a second start only wakes the first, and must not open the data.
        self.host = None
        self.disk = None
        #: Requests not answered yet, by number.  Only the number ever leaves the
        #: main thread: the engine's own objects are let go of where they were made.
        self._pending: dict[int, object] = {}
        self._serial = 0
        self._chooser = None
        Gio = self.tk.Gio
        self.app = self.tk.Gtk.Application(application_id=APP_ID, flags=Gio.ApplicationFlags.FLAGS_NONE)
        self.app.connect("activate", self._on_activate)
        self.app.connect("shutdown", self._on_shutdown)

    # ------------------------------------------------------------ start

    def run(self) -> int:
        GLib = self.tk.GLib
        try:
            GLib.set_prgname("sluka-desktop")
            GLib.set_application_name(APP_NAME)
        except Exception:
            pass
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, sig, self._quit_from_signal)
            except Exception:
                pass
        return int(self.app.run(None) or 0)

    def _quit_from_signal(self) -> bool:
        self.app.quit()
        return False

    def _on_activate(self, _app) -> None:
        if self.background is not None:
            # Started a second time: the app is running, so show it.
            if self.open_windows():
                self.open_windows()[-1].present()
            else:
                self.open_window(f"{self.origin}/{self.first_page}")
            return
        log.info("%s", self.tk.describe())
        if self.tk.engine_version() < MIN_ENGINE:
            self._message(
                f"This WebKitGTK is too old for {APP_NAME} "
                f"({'.'.join(map(str, self.tk.engine_version()))}; {'.'.join(map(str, MIN_ENGINE))} or newer is needed)."
            )
            return
        self.started = time.monotonic()
        self.host = Host(self.config, shell=self)
        # Sluka's backup folder, chosen in the system's own folder window (folders.py).
        self.host.boot_extra["folders"] = True
        self.host.folders.picker = self.pick_folder
        self.host.engine = self.tk.describe()
        self.host.ui_font = self.tk.ui_font()
        self.disk = DiskQueue()
        if self.config.mpv_enabled:
            try:
                from .mpvbridge import MpvBridge

                self.host.mpv = MpvBridge(self.config)
            except Exception:
                log.exception("the mpv bridge could not be set up")
        if self.config.anki_enabled:
            try:
                from .ankibridge import AnkiBridge

                self.host.anki = AnkiBridge(self.config, self.host)
            except Exception:
                log.exception("the bridge to Anki could not be set up")
        self._setup_engine()
        self._setup_actions()
        self._start_background()
        if self.host.mpv:
            self.host.mpv.start()
        if self.host.anki:
            self.host.anki.start()
        self.open_window(f"{self.origin}/{self.first_page}")

    def _setup_engine(self) -> None:
        tk, cfg = self.tk, self.config
        wk = tk.WebKit
        data, cache = str(cfg.webkit_data_dir), str(cfg.webkit_cache_dir)
        if tk.modern:
            self.session = wk.NetworkSession.new(data, cache)
            self.context = wk.WebContext.new()
            network = self.session
            downloads = self.session
        else:
            try:
                # Up to four fifths of the disk for one origin: the default is 1 GiB, and films kept in Sluka pass it.
                manager = wk.WebsiteDataManager(base_data_directory=data, base_cache_directory=cache, origin_storage_ratio=0.8)
            except TypeError:
                manager = wk.WebsiteDataManager(base_data_directory=data, base_cache_directory=cache)
            self.session = None
            self.context = wk.WebContext.new_with_website_data_manager(manager)
            network = manager
            downloads = self.context
        self.network = network

        # Nothing here is a website to be tracked across, and its storage must never be aged out.
        for target, name, args in (
            (network, "set_itp_enabled", (False,)),
            (network, "set_persistent_credential_storage_enabled", (False,)),
        ):
            try:
                getattr(target, name)(*args)
            except Exception:
                pass

        self._apply_network_mode()

        self.context.register_uri_scheme(self.scheme, self._on_uri_request)
        security = self.context.get_security_manager()
        # A secure context, as an extension's pages are: Sluka checks licences with WebCrypto.
        security.register_uri_scheme_as_secure(self.scheme)
        security.register_uri_scheme_as_cors_enabled(self.scheme)
        downloads.connect("download-started", self._on_download_started)

        self.settings = self._make_settings()

    def _make_settings(self):
        wk, cfg = self.tk.WebKit, self.config
        settings = wk.Settings()
        wanted = {
            "enable-developer-extras": cfg.devtools,
            "enable-write-console-messages-to-stdout": False,
            "javascript-can-access-clipboard": True,
            "media-playback-requires-user-gesture": False,
            "enable-webrtc": False,
            "enable-media-stream": False,
            "enable-dns-prefetching": False,
            "enable-page-cache": False,
            "enable-html5-database": True,
            "enable-html5-local-storage": True,
            "default-charset": "utf-8",
        }
        for name, value in wanted.items():
            try:
                settings.set_property(name, value)
            except Exception:  # not every engine version has every setting
                pass
        return settings

    def _background_settings(self):
        """Settings for the page that is never shown.

        An engine slows the timers of a page that is not on screen, to once a
        second and then less often still.  Sluka's background code is written
        for a browser that stops it altogether between events, so it does not
        lean on timers; where the engine lets the slowing be switched off
        (WebKitGTK 2.42 and later name their features), it is switched off anyway.
        """
        settings = self._make_settings()
        off = []
        try:
            features = self.tk.WebKit.Settings.get_all_features()
            for index in range(features.get_length()):
                feature = features.get(index)
                if feature.get_identifier() in HIDDEN_PAGE_FEATURES:
                    settings.set_feature_enabled(feature, False)
                    off.append(feature.get_identifier())
        except Exception as err:
            log.info("the engine's features could not be listed (%s)", err)
        log.info("background page: timer slowing %s", "switched off" if off else "left as the engine has it")
        return settings

    def _apply_network_mode(self) -> None:
        """Offline: every connection out fails.  Tor: every one goes through Tor's SOCKS port."""
        wk, cfg = self.tk.WebKit, self.config
        try:
            if cfg.network_mode == "tor":
                # Its own credentials, so Tor gives this app circuits of its own.
                token = secrets.token_hex(8)
                proxy = wk.NetworkProxySettings.new(f"socks5://sluka:{token}@{cfg.socks}", ["127.0.0.1", "localhost"])
                mode = wk.NetworkProxyMode.CUSTOM
            elif cfg.network_mode == "direct":
                proxy, mode = None, wk.NetworkProxyMode.NO_PROXY
            else:
                # A proxy nothing listens on: refused at once, for every host, names unresolved.
                proxy = wk.NetworkProxySettings.new("socks5://127.0.0.1:1", None)
                mode = wk.NetworkProxyMode.CUSTOM
            if self.tk.modern:
                self.network.set_proxy_settings(mode, proxy)
            else:
                self.network.set_network_proxy_settings(mode, proxy)
            log.info("network: %s", cfg.network_mode)
        except Exception:
            log.exception("could not set the network mode; the app will not start with the network open")
            raise

    def _setup_actions(self) -> None:
        Gio = self.tk.Gio
        for name, handler in (
            ("mpv-open", self._action_mpv_open),
            ("data-folder", lambda *_: self._open_folder(self.config.data_dir)),
            ("about", self._action_about),
        ):
            action = Gio.SimpleAction.new(name, None)
            action.connect("activate", handler)
            self.app.add_action(action)
        self.app.set_accels_for_action("win.zoom-in", ["<Control>plus", "<Control>equal", "<Control>KP_Add"])
        self.app.set_accels_for_action("win.zoom-out", ["<Control>minus", "<Control>KP_Subtract"])
        self.app.set_accels_for_action("win.zoom-reset", ["<Control>0"])
        self.app.set_accels_for_action("win.reload", ["F5"])

    def new_view(self, settings=None):
        wk, cfg = self.tk.WebKit, self.config
        props = {"web_context": self.context, "settings": settings or self.settings}
        if self.tk.modern:
            props["network_session"] = self.session
        policy = self.page_policy()
        if policy:
            # The engine's own enforcement of the policy, whatever becomes of the header.
            props["default_content_security_policy"] = policy
        try:
            view = wk.WebView(**props)
        except TypeError:
            props.pop("default_content_security_policy", None)
            view = wk.WebView(**props)
        if cfg.network_mode != "offline":
            # An extension's pages may fetch from any site; so may these, when online.
            try:
                view.set_cors_allowlist(["*://*/*"])
            except Exception:
                pass
        return view

    def page_policy(self) -> str:
        if not self.config.csp:
            return ""
        policy = self.config.csp_policy.rstrip("; ")
        if self.config.network_mode == "offline":
            policy += "; connect-src 'self' blob: data:"
        return policy

    def _start_background(self) -> None:
        Gtk = self.tk.Gtk
        self.background = self.new_view(self._background_settings())
        # A window that is never shown gives the view a place in the widget tree.
        self.background_window = Gtk.Window()
        if self.tk.gtk4:
            self.background_window.set_child(self.background)
        else:
            self.background_window.add(self.background)
        self.background.connect("web-process-terminated", self._on_background_crash)
        self.background.connect("decide-policy", self._background_policy)
        self.background.connect("permission-request", self.on_permission_request)
        self.background.load_uri(f"{self.origin}/__sluka__/background.html")

    def _on_background_crash(self, _view, reason) -> None:
        log.error("Sluka's background page stopped (%s); starting it again", reason)
        self.tk.GLib.timeout_add(800, lambda: self.background.load_uri(f"{self.origin}/__sluka__/background.html") and False)

    def _background_policy(self, _view, decision, kind) -> bool:
        wk = self.tk.WebKit
        if kind == wk.PolicyDecisionType.RESPONSE:
            return False
        try:
            uri = decision.get_navigation_action().get_request().get_uri() or ""
        except Exception:
            return False
        if self.is_own(uri) or uri.startswith(("about:", "data:")):
            return False
        decision.ignore()
        return True

    # ------------------------------------------------------------ requests from pages

    def _on_uri_request(self, request) -> None:
        try:
            parts = urllib.parse.urlsplit(request.get_uri())
            method = "GET"
            try:
                method = request.get_http_method() or "GET"
            except Exception:
                pass
            headers = {}
            try:
                sent = request.get_http_headers()
                if sent is not None:
                    for name in ("Range", "Origin", "Content-Type"):
                        value = sent.get_one(name)
                        if value:
                            headers[name.lower()] = value
            except Exception:
                pass
            body = b""
            if method not in ("GET", "HEAD"):
                body = self._read_body(request)
            path = urllib.parse.unquote(parts.path) or "/"
            req = Request(
                method=method,
                path=path,
                query=parse_query(parts.query),
                headers=headers,
                body=body,
                origin=self.origin,
                view=request.get_web_view() if path in WINDOW_CALLS else None,
            )
        except Exception as err:
            log.exception("a request could not be read")
            self._finish(request, Response(status=500, content_type="text/plain; charset=utf-8", body=str(err).encode()))
            return
        self._serial += 1
        number = self._serial
        self._pending[number] = request

        def respond(resp: Response) -> None:
            self._respond(number, resp)

        if self.disk is not None and path.startswith(DISK_CALLS):
            self.disk.put(lambda: self.host.handle(req, respond))
        else:
            self.host.handle(req, respond)

    def _read_body(self, request) -> bytes:
        try:
            stream = request.get_http_body()
        except Exception:
            return b""
        if stream is None:
            return b""
        chunks = []
        while True:
            piece = stream.read_bytes(1024 * 1024, None)
            data = piece.get_data() if piece is not None else None
            if not data:
                break
            chunks.append(bytes(data))
        try:
            stream.close(None)
        except Exception:
            pass
        return b"".join(chunks)

    def _respond(self, number: int, resp: Response) -> None:
        """Answer a request; from another thread (the disk's, the mpv bridge's) this is handed to the main loop."""
        if threading.current_thread() is self._main_thread:
            self._answer(number, resp)
        else:
            self.tk.GLib.idle_add(self._answer, number, resp)

    def _answer(self, number: int, resp: Response) -> bool:
        request = self._pending.pop(number, None)
        if request is not None:  # answered once, whatever asks twice
            self._finish(request, resp)
        return False

    def _finish(self, request, resp: Response) -> None:
        tk = self.tk
        Gio, GLib, Soup, wk = tk.Gio, tk.GLib, tk.Soup, tk.WebKit
        try:
            if resp.file:
                path, offset, length = resp.file
                whole = offset == 0 and length == os.path.getsize(path)
                if whole:
                    stream = Gio.File.new_for_path(path).read(None)
                elif length <= RANGE_IN_MEMORY:
                    with open(path, "rb") as handle:
                        handle.seek(offset)
                        stream = Gio.MemoryInputStream.new_from_bytes(GLib.Bytes.new(handle.read(length)))
                else:
                    # Too large a slice to hold: the whole file instead, said as such.
                    stream = Gio.File.new_for_path(path).read(None)
                    length = os.path.getsize(path)
                    resp.status = 200
                    resp.headers.pop("Content-Range", None)
            else:
                length = len(resp.body)
                stream = Gio.MemoryInputStream.new_from_bytes(GLib.Bytes.new(resp.body))

            if not hasattr(wk, "URISchemeResponse"):
                # An engine from before 2.36: no status and no headers to give.
                request.finish(stream, length, resp.content_type)
                return
            response = wk.URISchemeResponse.new(stream, length)
            response.set_content_type(resp.content_type)
            response.set_status(int(resp.status), None)
            headers = Soup.MessageHeaders.new(Soup.MessageHeadersType.RESPONSE)
            for name, value in resp.headers.items():
                headers.append(name, str(value))
            headers.append("Content-Type", resp.content_type)
            response.set_http_headers(headers)
            request.finish_with_response(response)
        except Exception as err:
            log.exception("a request could not be answered")
            try:
                request.finish_error(GLib.Error(str(err)))
            except Exception:
                pass

    # ------------------------------------------------------------ what the host asks of the windows

    def is_own(self, uri: str) -> bool:
        return uri.startswith(self.origin + "/") or uri == self.origin or uri.startswith("blob:" + self.origin)

    def find(self, tab_id=None, view=None):
        for win in self.windows:
            if (tab_id is not None and win.tab_id == tab_id) or (view is not None and win.view is view):
                return win
        return None

    def open_windows(self) -> list:
        """The windows still on screen."""
        return [win for win in self.windows if not win.closing]

    def register(self, info: dict, view=None) -> None:
        win = self.find(view=view)
        if win is not None and isinstance(info.get("tabId"), int):
            win.tab_id = info["tabId"]

    def request(self, op: str, args: dict, view=None) -> dict:
        if op == "open":
            return self._op_open(args)
        if op == "external":
            self.open_external(str(args.get("url") or ""), self.find(view=view))
            return {"ok": True, "handled": True}
        if op == "media-failed":
            self.offer_mpv(self.find(view=view))
            return {"ok": True, "handled": True}
        win = self.find(tab_id=args.get("tabId")) if args.get("tabId") is not None else self.find(view=view)
        if win is None or win.closing:
            return {"ok": False, "handled": True}
        if op == "focus":
            win.present()
        elif op == "close":
            win.close()
        elif op == "state":
            self._op_state(win, args)
        return {"ok": True, "handled": True}

    def _op_open(self, args: dict) -> dict:
        url = str(args.get("url") or "")
        if not self.is_own(url):
            self.open_external(url, None)
            return {"ok": True, "handled": True}
        path = urllib.parse.urlsplit(url).path
        kind = str(args.get("kind") or "tab")
        if kind == "tab" and time.monotonic() - self.started < REUSE_SECONDS:
            for win in self.open_windows():
                if win.path() == path:
                    if (win.view.get_uri() or "") != url:
                        win.view.load_uri(url)
                    win.present()
                    return {"ok": True, "handled": True, "reusedTabId": win.tab_id}
        self.open_window(url, kind=kind, width=args.get("width") or 0, height=args.get("height") or 0, state=args.get("state"))
        return {"ok": True, "handled": True}

    def _op_state(self, win: AppWindow, args: dict) -> None:
        state = args.get("state")
        window = win.window
        try:
            if state == "minimized":
                window.minimize() if self.tk.gtk4 else window.iconify()
            elif state == "maximized":
                window.maximize()
            elif state == "fullscreen":
                window.fullscreen()
            elif state == "normal":
                window.unmaximize()
                window.unfullscreen()
                window.present()
            width, height = args.get("width"), args.get("height")
            if isinstance(width, int) and isinstance(height, int) and width > 100 and height > 100:
                window.set_default_size(width, height)
        except Exception:
            log.exception("could not change a window's state")

    def open_dictionary(self, url: str, own: bool) -> None:
        """The Look up key's window: an offline dictionary's page in a small window of the app's; a site online as
        any link to the outside is opened (config.ini [links]: on Tails, in Tor Browser, asked first by default)."""
        def show():
            if own:
                self.open_window(f"{self.origin}{url}", kind="popup", width=520, height=680)
            else:
                self.open_external(url, self.windows[-1] if self.windows else None)
            return False

        self.tk.GLib.idle_add(show)

    def open_window(self, url: str, kind: str = "tab", width=0, height=0, state=None) -> AppWindow:
        win = AppWindow(self, url, kind=kind, width=width or 0, height=height or 0)
        self.windows.append(win)
        if state in ("maximized", "fullscreen", "minimized"):
            self._op_state(win, {"state": state})
        return win

    def open_from_page(self, uri: str) -> None:
        """A link or script on a page asked for a new window."""
        if self.is_own(uri):
            self.open_window(uri)
        elif uri and not uri.startswith(("about:", "javascript:")):
            self.open_external(uri, self.windows[-1] if self.windows else None)

    def window_closed(self, win: AppWindow) -> None:
        if win in self.windows:
            self.windows.remove(win)
        # With its last window the app is done; the background page goes with it.

    # ------------------------------------------------------------ links to the outside

    def open_external(self, uri: str, parent: AppWindow | None) -> None:
        if not uri or urllib.parse.urlsplit(uri).scheme not in ("http", "https", "mailto"):
            return
        policy = self.config.external_links
        if policy == "ignore":
            return
        if policy == "open":
            self._launch(uri)
            return
        Gtk = self.tk.Gtk
        shown = uri if len(uri) <= 300 else uri[:300] + "…"
        dialog = Gtk.MessageDialog(
            transient_for=parent.window if parent else None,
            modal=True,
            message_type=Gtk.MessageType.QUESTION,
            buttons=Gtk.ButtonsType.NONE,
            text="Open this link in your web browser?",
        )
        try:
            dialog.set_property("secondary-text", shown)
        except Exception:
            pass
        dialog.add_button("Cancel", Gtk.ResponseType.CANCEL)
        dialog.add_button("Copy link", Gtk.ResponseType.APPLY)
        dialog.add_button("Open", Gtk.ResponseType.OK)

        def answered(dlg, response):
            if response == Gtk.ResponseType.OK:
                self._launch(uri)
            elif response == Gtk.ResponseType.APPLY:
                self._copy(uri)
            dlg.destroy()

        dialog.connect("response", answered)
        dialog.present() if self.tk.gtk4 else dialog.show()

    def offer_mpv(self, win: AppWindow | None) -> None:
        """A page could not play the film it was given: mpv can, and Sluka is in mpv too."""
        if win is None or win.closing or self.host is None or not self.host.mpv:
            return
        now = time.monotonic()
        if now - win.offered_mpv < 20:
            return  # one film sets off several tries on a page
        win.offered_mpv = now
        from .mpvbridge import SUBTITLE_SUFFIXES, VIDEO_SUFFIXES

        files = [f for f in win.chosen_files() if os.path.splitext(f)[1].lower() in VIDEO_SUFFIXES | SUBTITLE_SUFFIXES and os.path.isfile(f)]
        if not any(os.path.splitext(f)[1].lower() in VIDEO_SUFFIXES for f in files):
            # Dropped onto the page, or picked some other way: which file it was is not known here.
            self._message("The app's own player cannot play this video's format.\n\n"
                          "mpv can: open the video in mpv while Sluka is running, or choose "
                          "\"Play a video in mpv with Sluka…\" in the menu of this window.")
            return
        Gtk = self.tk.Gtk
        dialog = Gtk.MessageDialog(
            transient_for=win.window,
            modal=True,
            message_type=Gtk.MessageType.QUESTION,
            buttons=Gtk.ButtonsType.NONE,
            text="The app's own player cannot play this video's format. Play it in mpv?",
        )
        # Named, so that it can be seen which file is meant: it is the last one picked in this window.
        named = ", ".join(os.path.basename(f) for f in files if os.path.splitext(f)[1].lower() in VIDEO_SUFFIXES)
        try:
            dialog.set_property("secondary-text", f"{named}\n\nmpv plays it, and Sluka's subtitles are drawn inside mpv.")
        except Exception:
            pass
        dialog.add_button("Not now", Gtk.ResponseType.CANCEL)
        dialog.add_button("Play in mpv", Gtk.ResponseType.OK)

        def answered(dlg, response):
            dlg.destroy()
            if response == Gtk.ResponseType.OK:
                problem = self.host.mpv.play(files)
                if problem:
                    self._message(problem)

        dialog.connect("response", answered)
        dialog.present() if self.tk.gtk4 else dialog.show()

    def _launch(self, uri: str) -> None:
        try:
            self.tk.Gio.AppInfo.launch_default_for_uri(uri, None)
        except Exception as err:
            log.warning("could not open %s: %s", uri, err)

    def _copy(self, text: str) -> None:
        try:
            if self.tk.gtk4:
                self.tk.Gdk.Display.get_default().get_clipboard().set(text)
            else:
                self.tk.Gtk.Clipboard.get(self.tk.Gdk.SELECTION_CLIPBOARD).set_text(text, -1)
        except Exception:
            log.exception("could not copy to the clipboard")

    def _open_folder(self, folder: Path) -> None:
        self._launch(Path(folder).as_uri())

    # ------------------------------------------------------------ downloads started by a page

    def _on_download_started(self, _source, download) -> None:
        download.connect("decide-destination", self._on_decide_destination)
        download.connect("failed", lambda _d, err: log.warning("a download failed: %s", getattr(err, "message", err)))
        download.connect("finished", lambda d: log.info("downloaded %s", d.get_destination()))

    def _on_decide_destination(self, download, suggested: str) -> bool:
        name = os.path.basename(suggested or "") or "download"
        folder = self.config.downloads_dir
        folder.mkdir(parents=True, exist_ok=True)
        target = folder / name
        stem, suffix = target.stem, target.suffix
        n = 1
        while target.exists():
            target = folder / f"{stem} ({n}){suffix}"
            n += 1
        # A path in the new API, a file:// address in the old one.
        download.set_destination(str(target) if self.tk.modern else target.as_uri())
        return True

    # ------------------------------------------------------------ permissions

    def on_permission_request(self, _view, request) -> bool:
        kind = type(request).__name__
        # Copying a word or a sentence is Sluka's everyday; nothing else is asked for by its pages.
        if "Clipboard" in kind:
            request.allow()
        else:
            log.info("refused a page's request: %s", kind)
            request.deny()
        return True

    # ------------------------------------------------------------ menu

    def _action_mpv_open(self, *_args) -> None:
        Gtk = self.tk.Gtk
        parent = self.windows[-1].window if self.windows else None
        chooser = Gtk.FileChooserNative.new("Play in mpv with Sluka", parent, Gtk.FileChooserAction.OPEN, "_Play", "_Cancel")
        chooser.set_select_multiple(True)

        def chosen(dlg, response):
            files = []
            if response == Gtk.ResponseType.ACCEPT:
                if self.tk.gtk4:
                    model = dlg.get_files()
                    files = [model.get_item(i).get_path() for i in range(model.get_n_items())]
                else:
                    files = list(dlg.get_filenames())
            dlg.destroy()
            self._chooser = None
            files = [f for f in files if f]
            if files and self.host.mpv:
                problem = self.host.mpv.play(files)
                if problem:
                    self._message(problem)

        chooser.connect("response", chosen)
        self._chooser = chooser  # kept alive until it answers
        chooser.show()

    def pick_folder(self, title: str, remember: str = "") -> str:
        """A folder chosen in the system's folder window, from any thread; "" for none."""
        done = threading.Event()
        got = {"path": ""}

        def show():
            Gtk = self.tk.Gtk
            parent = self.windows[-1].window if self.windows else None
            chooser = Gtk.FileChooserNative.new(title, parent, Gtk.FileChooserAction.SELECT_FOLDER, "_Choose", "_Cancel")

            def chosen(dlg, response):
                try:
                    if response == Gtk.ResponseType.ACCEPT:
                        picked = dlg.get_file()
                        got["path"] = (picked.get_path() if picked else "") or ""
                finally:
                    dlg.destroy()
                    self._folder_chooser = None
                    done.set()

            chooser.connect("response", chosen)
            self._folder_chooser = chooser  # kept alive until it answers
            chooser.show()
            return False

        self.tk.GLib.idle_add(show)
        done.wait()
        return got["path"]

    def _action_about(self, *_args) -> None:
        cfg = self.config
        mpv = self.host.mpv.status() if self.host.mpv else None
        lines = [
            f"{APP_NAME} {__version__}",
            f"Sluka {cfg.extension_version}",
            self.tk.describe(),
            f"Network: {cfg.network_mode}",
            f"Data: {cfg.data_dir}",
            f"Saved files: {cfg.downloads_dir}",
        ]
        if mpv is not None:
            lines.append(f"mpv: {mpv.get('players', 0)} player(s) connected")
        lines += ["", LICENCE_NOTE]
        self._message("\n".join(lines))

    def _message(self, text: str) -> None:
        Gtk = self.tk.Gtk
        parent = self.windows[-1].window if self.windows else None
        dialog = Gtk.MessageDialog(
            transient_for=parent, modal=True, message_type=Gtk.MessageType.INFO, buttons=Gtk.ButtonsType.CLOSE, text=text
        )
        dialog.connect("response", lambda dlg, _r: dlg.destroy())
        dialog.present() if self.tk.gtk4 else dialog.show()

    # ------------------------------------------------------------ end

    def _on_shutdown(self, _app) -> None:
        log.info("closing")
        try:
            if self.background_window is not None:
                self.background_window.destroy()
        except Exception:
            pass
        if self.disk is not None:
            self.disk.stop()  # what was asked to be written is written
        self._pending.clear()
        if self.host is not None:
            self.host.close()


def run_app(config: Config, page: str = "", safe_graphics: bool = False, no_sandbox: bool = False) -> int:
    # Read by WebKit as it loads, so set before it is imported.
    if safe_graphics:
        os.environ["WEBKIT_DISABLE_DMABUF_RENDERER"] = "1"
        os.environ["WEBKIT_DISABLE_COMPOSITING_MODE"] = "1"
    if no_sandbox:
        os.environ["WEBKIT_DISABLE_SANDBOX_THIS_IS_DANGEROUS"] = "1"
    try:
        shell = Shell(config, page)
    except ShellUnavailable as err:
        print(f"sluka: {err}", flush=True)
        print("Run  ./sluka doctor  for a full check.", flush=True)
        return 3
    except ImportError as err:
        print(f"sluka: Python's GTK bindings are missing ({err}).\nInstall them with:  sudo apt install python3-gi", flush=True)
        return 3
    return shell.run()
