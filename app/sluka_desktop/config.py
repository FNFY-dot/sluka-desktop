# SPDX-License-Identifier: LicenseRef-Sluka
# Copyright (c) 2026 Sluka. Part of Sluka Desktop; see LICENSE.txt.
"""Where everything lives, and the few settings the app has.

Everything is kept under one folder (the one that holds the ``sluka`` launcher)
so that the whole app, with its data, survives on a Tails Persistent Storage:

    <root>/app/          this program
    <root>/extension/    the unpacked Sluka extension (yours; not shipped here)
    <root>/data/         word lists, dictionaries, books, logs  (created on first run)
    <root>/config.ini    optional settings (written with defaults on first run)
"""

from __future__ import annotations

import base64
import configparser
import hashlib
import json
import os
import re
import sys
from pathlib import Path

#: On Windows the app's windows are its own, with Windows' web view (WebView2) in them, and there is no Tails
#: to be careful for.
WINDOWS = os.name == "nt"
#: Where the app's pages are served on this computer on Windows.  The web view files what it keeps for the
#: app (books, dictionaries) under this address, so it has to be the same at every start.
DEFAULT_PORT = 47821


def local_dir() -> Path:
    """A folder of this user's for what need not last: where a player or Anki says it is there (Windows)."""
    base = os.environ.get("LOCALAPPDATA") or os.environ.get("TEMP") or str(Path.home())
    return Path(base) / "sluka-desktop"


def store_python() -> bool:
    """Whether this Python is a package from the Microsoft Store.

    Windows keeps what such a program newly writes under AppData in a folder of the program's own, where no
    other program sees it: Sluka's script would not reach mpv, nor its add-on Anki.  (Python from python.org,
    and the runtimes the newer "Python install manager" puts in, write where they are told.)
    """
    if not WINDOWS:
        return False
    import sys

    where = (sys.executable or "").lower() + "|" + (getattr(sys, "base_prefix", "") or "").lower()
    return "\\windowsapps\\" in where and "pythonsoftwarefoundation.python." in where


def kept_private(path) -> str:
    """Where Windows really put a file this program wrote, if that is a private copy and not ``path``; else ''."""
    if not WINDOWS:
        return ""
    try:
        real = os.path.realpath(str(path))
    except OSError:
        return ""
    low = real.lower()
    if os.path.normcase(real) != os.path.normcase(os.path.abspath(str(path))) and "\\packages\\" in low and "\\localcache\\" in low:
        return real
    return ""


PRIVATE_COPY = (
    "This Python is the one from the Microsoft Store, and Windows keeps what it writes under AppData\n"
    "in a folder of Python's own: {what} was written, but {who} will not see it.\n"
    "Install Python from https://www.python.org/downloads/windows/ (the Store's can stay), then run this again."
)


DEFAULT_CONFIG = """\
# Sluka Desktop settings.  Lines starting with # are comments.
# Delete this file to get the defaults back.

[network]
# offline : Sluka cannot reach the Internet at all (dictionaries, books and
#           videos are local, so reading and watching work without it).
# tor     : online features (machine translation, cloud voices, downloading
#           extra dictionaries) go through the Tor SOCKS proxy below.
# direct  : no proxy.  For systems other than Tails.  Tails itself lets such a
#           connection reach only your local network, so there this mode
#           serves one thing: Sluka's sync over wifi with its phone app.
mode = offline
socks = 127.0.0.1:9050

[paths]
# Where files that Sluka "downloads" are written: backups, exported word
# lists, subtitle files.  Relative paths are relative to the app folder.
downloads = data/Downloads

[links]
# What to do with a link to a website: ask, open (in the system browser,
# which is Tor Browser on Tails) or ignore.
external = ask

[window]
width = 1280
height = 860
# Show WebKit's developer tools entry in the right-click menu.
devtools = no

[mpv]
# Talk to mpv / Celluloid when the Sluka mpv script is loaded there.
enabled = yes
# Put Sluka's script where mpv and Celluloid look for scripts, so that any video
# you open in them is seen by Sluka and gets its subtitles.  Done again at each
# start of the app, because Tails forgets the home folder at every restart.
# With "no", only a video started with  ./sluka mpv FILE  has them.
attach = yes
# Folder where the mpv script puts its socket.  Empty = $XDG_RUNTIME_DIR/sluka-mpv
socket_dir =
# Everything Sluka draws in mpv, larger or smaller: 1.3 is three tenths larger.
# Sluka's sizes are those of a web page; from a sofa they may be too small.
# (Kept here and not in mpv's own settings, which Tails forgets at a restart.
# Read when the app starts.)
scale = 1.0

[anki]
# Sluka in Anki's review screen, for an Anki that has this app's add-on (put
# there once with  ./sluka install-anki ).  Without the add-on nothing happens.
enabled = yes
# Where the add-on was put, one folder or several with ; between them.  Kept in
# step with the app at each start.  Written by  ./sluka install-anki .
addons =
# The add-on reaches Sluka's own files through a link to this app's folder.
# With "yes" they are copied into the add-on instead (about 200 MB), for an
# Anki that does not follow the link.  Written by  ./sluka install-anki --copy .
copy = no

[security]
# The extension's own Content-Security-Policy is applied to every page, which
# is what stops a script hidden inside an e-book from running.  Leave it on.
csp = on

[advanced]
# The kind of address Sluka's pages are given inside the app.  The default is
# the one they have in a browser.  Only if a web engine refuses it: any name
# ending in -extension works (sluka-extension), at the cost of the
# dictionaries being built again, since the engine files them by address.
scheme = chrome-extension
"""

DEFAULT_CONFIG_WINDOWS = """\
# Sluka Desktop settings.  Lines starting with # are comments.
# Delete this file to get the defaults back.

[app]
# Where Sluka's windows come from:
#   auto     : Windows' own web view (WebView2, which comes with Windows and
#              is kept up to date by it), else a browser's windows
#   webview2 : Windows' own web view: windows of the app's own, no browser
#   browser  : a browser's windows without address bar ([browser] below)
shell = auto
# The address the app's pages have on this computer: http://127.0.0.1:<port>.
# The web view keeps your books and dictionaries under that address, so a
# changed port hides them until it is changed back.
port = 47821
# An extension may read any website (Sluka does, for translation and
# dictionaries).  A page of a local program may not, so the app's web view is
# started with that rule off.  "on" keeps the rule; what Sluka then cannot
# fetch fails.  Links to websites open in your own browser either way.
web_security = off
# Sluka writes backups and exports through "downloads", into the folder in
# [paths].  With "yes" it may ask for folders with the engine's own pickers,
# as it does in Chrome.  (Not tried.)
pickers = no

[network]
# direct  : Sluka reaches the Internet as any program does: machine
#           translation, cloud voices, extra dictionaries, sync.
# offline : Sluka cannot reach the Internet at all (dictionaries, books and
#           videos are local, so reading and watching work without it).
# tor     : online features go through the SOCKS proxy below.
mode = direct
socks = 127.0.0.1:9050

[paths]
# Where files that Sluka "downloads" are written: backups, exported word
# lists, subtitle files.  Relative paths are relative to the app folder.
downloads = data/Downloads

[links]
# What to do with a link to a website: open (in your own browser), ask, or
# ignore.
external = open

[window]
width = 1280
height = 860
# The web view's developer tools: F12, and an entry in the window menu.
devtools = no

[webview2]
# The WebView2 Runtime to use: empty = the one Windows has.  Or the folder of
# a "fixed version" runtime (the folder that holds msedgewebview2.exe).
runtime =
# More command-line switches for the web view's engine, separated by spaces.
args =

[browser]
# Only for [app] shell = browser (or auto, on a Windows without its web view).
# The browser Sluka's windows are shown in, each as a window without address
# bar.  auto = Microsoft Edge, else Chrome, Brave, Vivaldi or Chromium.  Or the
# full path of the one to use, for example
#   path = C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe
# It runs with a profile of its own (data\\browser), apart from your browsing.
path = auto
# Sluka's background worker runs in a page that is in no window, which the
# browser is asked for over its debugging port (open to this computer only,
# for as long as the app runs).  With "no" the port is not opened, and the
# worker lives in whichever window is open: it then starts anew each time that
# window goes to another page.
hidden_worker = yes
# More command-line switches for the browser, separated by spaces.
args =

[mpv]
# Talk to mpv when the Sluka mpv script is loaded there.
enabled = yes
# Put Sluka's script where mpv looks for scripts (%APPDATA%\\mpv\\scripts, and
# mpv.net's folder if there is one), so that any video you open in mpv is seen
# by Sluka and gets its subtitles.  Done again at each start of the app.
attach = yes
# More "scripts" folders to put it in, with ; between them: for an mpv that
# keeps its settings beside itself (portable_config\\scripts).
# Written by  sluka install-mpv FOLDER .
scripts =
# mpv.exe, for  sluka mpv FILE .  Empty = looked for in the usual places.
player =
# Everything Sluka draws in mpv, larger or smaller: 1.3 is three tenths larger.
# Read when the app starts.
scale = 1.0

[anki]
# Sluka in Anki's review screen, for an Anki that has this app's add-on (put
# there once with  sluka install-anki ).  Without the add-on nothing happens.
enabled = yes
# Where the add-on was put, one folder or several with ; between them.  Kept in
# step with the app at each start.  Written by  sluka install-anki .
addons =
# The add-on reaches Sluka's own files through a link to this app's folder.
# With "yes" they are copied into the add-on instead (about 200 MB).
copy = no

[security]
# The extension's own Content-Security-Policy is applied to every page, which
# is what stops a script hidden inside an e-book from running.  Leave it on.
csp = on

[bar]
# The floating subtitles: Sluka's subtitle box in a window of its own that
# stays over every other, showing a line put into it by another program
# (the address http://127.0.0.1:<port>/__sluka__/api/bar/text, or
# sluka bar-text "...").  Its place, size and settings are kept in
# data\\bar.json; it is turned on and off with the button in the app's windows.
enabled = yes
# Where its button, and the game text menu's beside it, sit in the app's
# windows: bottom-left, bottom-right, top-left, top-right, or none.
button = bottom-left

[games]
# Text from games for the floating subtitles: the menu beside the subtitles
# button in the app's windows reads it out of a game with Sluka's own engine
# (LunaHook, from LunaTranslator 12.1.3.12, in the engine folder), or takes it
# from the clipboard or from another program (LunaTranslator, Textractor).
enabled = yes
# The engine's folder: empty = the engine folder that comes with the app.
# Another must hold the same files (LunaHost64.dll, LunaHook32.dll, ...).
engine =
"""

#: What 0.6.0 and 0.7.0 add to a config.ini of before.
BAR_BLOCK_WINDOWS = "\n" + """[bar]
# The floating subtitles: Sluka's subtitle box in a window of its own that
# stays over every other, showing a line put into it by another program
# (the address http://127.0.0.1:<port>/__sluka__/api/bar/text, or
# sluka bar-text "...").  Its place, size and settings are kept in
# data\\bar.json; it is turned on and off with the button in the app's windows.
enabled = yes
# Where its button, and the game text menu's beside it, sit in the app's
# windows: bottom-left, bottom-right, top-left, top-right, or none.
button = bottom-left

[games]
# Text from games for the floating subtitles: the menu beside the subtitles
# button in the app's windows reads it out of a game with Sluka's own engine
# (LunaHook, from LunaTranslator 12.1.3.12, in the engine folder), or takes it
# from the clipboard or from another program (LunaTranslator, Textractor).
enabled = yes
# The engine's folder: empty = the engine folder that comes with the app.
# Another must hold the same files (LunaHost64.dll, LunaHook32.dll, ...).
engine =
"""

#: The lines 0.6.0 wrote for its button, at the top right (where it sat on Sluka's own buttons).
BUTTON_LINES_060 = """# Where that button sits in the app's windows: top-right, top-left,
# bottom-right, bottom-left, or none.
button = top-right
"""
BUTTON_LINES_070 = """# Where its button, and the game text menu's beside it, sit in the app's
# windows: bottom-left, bottom-right, top-left, top-right, or none.
button = bottom-left
"""

#: What 0.7.0 wrote about its text hooker, which it fetched; 0.8.0 has an engine of its own, that comes with it.
GAMES_LINES_070 = """# Text from games for the floating subtitles: the menu beside the subtitles
# button in the app's windows takes it from a game (Sluka's text hooker), from
# the clipboard, or from another program (LunaTranslator, Textractor).
"""
GAMES_LINES_080 = """# Text from games for the floating subtitles: the menu beside the subtitles
# button in the app's windows reads it out of a game with Sluka's own engine
# (LunaHook, from LunaTranslator 12.1.3.12, in the engine folder), or takes it
# from the clipboard or from another program (LunaTranslator, Textractor).
"""
HOOKER_LINES_070 = """# A folder that holds the text hooker to use: LunaHook (LunaHostCLI32.exe and
# LunaHostCLI64.exe) or Textractor (TextractorCLI.exe).  Empty = the LunaHook
# the menu fetches into data\\tools\\LunaHook, else a Textractor in its usual place.
hooker =
"""
ENGINE_LINES_080 = """# The engine's folder: empty = the engine folder that comes with the app.
# Another must hold the same files (LunaHost64.dll, LunaHook32.dll, ...).
engine =
"""

#: What 0.7.0 adds to a config.ini that 0.6.0 wrote.
GAMES_BLOCK_WINDOWS = "\n" + """[games]
# Text from games for the floating subtitles: the menu beside the subtitles
# button in the app's windows reads it out of a game with Sluka's own engine
# (LunaHook, from LunaTranslator 12.1.3.12, in the engine folder), or takes it
# from the clipboard or from another program (LunaTranslator, Textractor).
enabled = yes
# The engine's folder: empty = the engine folder that comes with the app.
# Another must hold the same files (LunaHost64.dll, LunaHook32.dll, ...).
engine =
"""

#: What 0.5.0 adds to a config.ini that 0.4.0 wrote (its [browser] port and web_security go on being read).
APP_BLOCK_WINDOWS = """
[app]
# Where Sluka's windows come from (since Sluka Desktop 0.5.0):
#   auto     : Windows' own web view (WebView2, which comes with Windows and
#              is kept up to date by it), else a browser's windows
#   webview2 : Windows' own web view: windows of the app's own, no browser
#   browser  : a browser's windows without address bar ([browser] below)
shell = auto

[webview2]
# The WebView2 Runtime to use: empty = the one Windows has.  Or the folder of
# a "fixed version" runtime (the folder that holds msedgewebview2.exe).
runtime =
# More command-line switches for the web view's engine, separated by spaces.
args =
"""


def default_config_text() -> str:
    return DEFAULT_CONFIG_WINDOWS if WINDOWS else DEFAULT_CONFIG


def _as_bool(text: str, default: bool) -> bool:
    value = str(text or "").strip().lower()
    if value in ("1", "yes", "true", "on"):
        return True
    if value in ("0", "no", "false", "off"):
        return False
    return default


def extension_id_from_key(key_b64: str) -> str:
    """Chrome's ID for an extension, from the public key in its manifest.

    The first 16 bytes of the key's SHA-256, each hex digit written a-p.  Using
    the same ID as the browser keeps every address identical to the real thing.
    """
    der = base64.b64decode(key_b64)
    digest = hashlib.sha256(der).hexdigest()[:32]
    return "".join(chr(ord("a") + int(c, 16)) for c in digest)


def extension_id_from_path(path: Path) -> str:
    digest = hashlib.sha256(str(path).encode("utf-8")).hexdigest()[:32]
    return "".join(chr(ord("a") + int(c, 16)) for c in digest)


#: What 0.1.0 wrote into every config.ini about the mpv script, and what stands there now.
OLD_MPV_BLOCK = """# Put Sluka's script into mpv and Celluloid each time the app starts, so that
# any video you open in them has Sluka's subtitles.  (Tails forgets the home
# folder at every restart, so once is not enough there.)
# Turned on by:  ./sluka install-menu --mpv
hook = no
"""
NEW_MPV_BLOCK = """# Put Sluka's script where mpv and Celluloid look for scripts, so that any video
# you open in them is seen by Sluka and gets its subtitles.  Done again at each
# start of the app, because Tails forgets the home folder at every restart.
# With "no", only a video started with  ./sluka mpv FILE  has them.
attach = yes
"""


class ConfigError(Exception):
    pass


class Config:
    def __init__(self, root: Path | None = None, extension: Path | None = None, data: Path | None = None):
        here = Path(__file__).resolve()
        # <root>/app/sluka_desktop/config.py
        self.root = Path(root).resolve() if root else here.parents[2]
        self.app_dir = here.parents[1]
        self.web_dir = self.app_dir / "web"
        self.mpv_dir = self.root / "mpv"
        self.anki_dir = self.root / "anki"
        self.ext_dir = Path(
            extension or os.environ.get("SLUKA_EXTENSION_DIR") or (self.root / "extension")
        ).expanduser().resolve()
        self.data_dir = Path(data or os.environ.get("SLUKA_DATA_DIR") or (self.root / "data")).expanduser().resolve()
        self.config_file = self.root / "config.ini"

        # No %(name)s substitution: a Windows path may well hold a % of its own.
        parser = configparser.ConfigParser(interpolation=None)
        parser.read_string(default_config_text())
        #: What config.ini itself says, apart from the defaults: a setting that moved to another section is
        #: still read where an earlier version wrote it.
        user = configparser.ConfigParser(interpolation=None)
        if self.config_file.is_file():
            try:
                parser.read(self.config_file, encoding="utf-8")
                user.read(self.config_file, encoding="utf-8")
            except configparser.Error as err:
                raise ConfigError(f"config.ini could not be read: {err}") from err
        self._parser = parser
        self._user = user

        usual = "direct" if WINDOWS else "offline"
        mode = parser.get("network", "mode", fallback=usual).strip().lower()
        if os.environ.get("SLUKA_NETWORK"):
            mode = os.environ["SLUKA_NETWORK"].strip().lower()
        self.network_mode = mode if mode in ("offline", "tor", "direct") else usual
        self.socks = parser.get("network", "socks", fallback="127.0.0.1:9050").strip() or "127.0.0.1:9050"

        downloads = parser.get("paths", "downloads", fallback="data/Downloads").strip() or "data/Downloads"
        downloads_path = Path(downloads).expanduser()
        self.downloads_dir = (downloads_path if downloads_path.is_absolute() else self.root / downloads_path).resolve()

        external = parser.get("links", "external", fallback="ask").strip().lower()
        self.external_links = external if external in ("ask", "open", "ignore") else "ask"

        self.window_width = max(480, parser.getint("window", "width", fallback=1280))
        self.window_height = max(360, parser.getint("window", "height", fallback=860))
        self.devtools = _as_bool(parser.get("window", "devtools", fallback="no"), False)

        self.bar_enabled = _as_bool(parser.get("bar", "enabled", fallback="yes"), True)
        button = parser.get("bar", "button", fallback="bottom-left").strip().lower()
        self.bar_button = button if button in ("top-right", "top-left", "bottom-right", "bottom-left", "none") else "bottom-left"
        self.games_enabled = self.bar_enabled and _as_bool(parser.get("games", "enabled", fallback="yes"), True)
        #: Sluka's engine for game text (LunaHook, as LunaTranslator has it): the engine folder that comes with the app.
        engine = parser.get("games", "engine", fallback="").strip().strip('"')
        engine_path = Path(engine).expanduser() if engine else Path("engine")
        self.engine_dir = (engine_path if engine_path.is_absolute() else self.root / engine_path).resolve()

        self.mpv_enabled = _as_bool(parser.get("mpv", "enabled", fallback="yes"), True)
        # 0.1.0 called this "hook" and wrote "hook = no" into every config.ini as
        # its default, so that line says nothing about what its owner wants.
        self.mpv_attach = _as_bool(parser.get("mpv", "attach", fallback="yes"), True)
        try:
            scale = float(parser.get("mpv", "scale", fallback="1").strip().replace(",", ".") or 1)
        except ValueError:
            scale = 1.0
        self.mpv_scale = scale if 0.5 <= scale <= 4 else 1.0
        socket_dir = parser.get("mpv", "socket_dir", fallback="").strip()
        self.mpv_socket_dir = Path(socket_dir).expanduser() if socket_dir else default_mpv_socket_dir()

        # More folders the mpv script is put in, and the player to start (both for Windows, where mpv has no one place).
        self.mpv_scripts = [Path(p.strip()).expanduser() for p in parser.get("mpv", "scripts", fallback="").split(";") if p.strip()]
        self.mpv_player = parser.get("mpv", "player", fallback="").strip().strip('"')

        # The windows: the desktop's own toolkit with WebKit in it (Tails), Windows' own web view, or a browser's.
        shell = (os.environ.get("SLUKA_SHELL") or parser.get("app", "shell", fallback="auto")).strip().lower()
        if shell == "webview":
            shell = "webview2"
        #: Chosen by the app, not by config.ini: on Windows a browser stands in where Windows has no web view.
        self.shell_auto = shell not in ("gtk", "browser", "webview2")
        if self.shell_auto:
            shell = "webview2" if WINDOWS else "browser" if sys.platform == "darwin" else "gtk"
        self.shell = shell
        self.browser_path = (os.environ.get("SLUKA_BROWSER") or parser.get("browser", "path", fallback="auto")).strip().strip('"') or "auto"
        try:
            port = int(self._first(("app", "port"), ("browser", "port"), fallback=str(DEFAULT_PORT)).strip() or DEFAULT_PORT)
        except ValueError:
            port = DEFAULT_PORT
        self.port = port if 1024 <= port <= 65535 else DEFAULT_PORT
        self.web_security = _as_bool(self._first(("app", "web_security"), ("browser", "web_security"), fallback="off"), False)
        self.pickers = _as_bool(self._first(("app", "pickers"), ("browser", "pickers"), fallback="no"), False)
        # (The names the browser shell has always used.)
        self.browser_port = self.port
        self.browser_web_security = self.web_security
        self.browser_pickers = self.pickers
        self.browser_args = parser.get("browser", "args", fallback="").split()
        self.browser_hidden_worker = _as_bool(parser.get("browser", "hidden_worker", fallback="yes"), True)
        self.webview_runtime = (os.environ.get("SLUKA_WEBVIEW2_RUNTIME") or parser.get("webview2", "runtime", fallback="")).strip().strip('"')
        self.webview_args = parser.get("webview2", "args", fallback="").split()

        self.anki_enabled = _as_bool(parser.get("anki", "enabled", fallback="yes"), True)
        self.anki_addons = [Path(p.strip()).expanduser() for p in parser.get("anki", "addons", fallback="").split(";") if p.strip()]
        self.anki_copy = _as_bool(parser.get("anki", "copy", fallback="no"), False)

        self.csp = _as_bool(parser.get("security", "csp", fallback="on"), True)

        scheme = parser.get("advanced", "scheme", fallback="chrome-extension").strip().lower()
        # Sluka knows its own pages by an address ending in "-extension:".
        self.scheme = scheme if re.fullmatch(r"[a-z][a-z0-9.+-]*-extension", scheme) else "chrome-extension"

        self.log_dir = self.data_dir / "logs"
        self.webkit_data_dir = self.data_dir / "webkit"
        self.webkit_cache_dir = self.data_dir / "webkit-cache"
        #: The profile of the browser that shows the app's windows, where a browser does.
        self.browser_dir = self.data_dir / "browser"
        #: What Windows' web view keeps for the app: books, dictionaries, films (its "user data folder").
        self.webview_dir = self.data_dir / "webview2"
        self.db_path = self.data_dir / "storage.sqlite"

        self.manifest: dict = {}
        self.extension_id = ""

    def _first(self, *places, fallback: str = "") -> str:
        """The first of the (section, option) places that config.ini itself sets, else the first the defaults set."""
        for section, option in places:
            if self._user.has_option(section, option):
                return self._user.get(section, option)
        for section, option in places:
            if self._parser.has_option(section, option):
                return self._parser.get(section, option)
        return fallback

    # -- the extension ----------------------------------------------------

    def extension_present(self) -> bool:
        return (self.ext_dir / "manifest.json").is_file()

    def load_manifest(self) -> dict:
        path = self.ext_dir / "manifest.json"
        if not path.is_file():
            if WINDOWS:
                raise ConfigError(
                    f"No Sluka extension found in {self.ext_dir}.\n"
                    "Put yours there: drag the sluka-extension zip onto Sluka.cmd, or in a terminal:\n"
                    "    .\\sluka install-extension C:\\path\\to\\sluka-extension-x_y_z.zip"
                )
            raise ConfigError(
                f"No Sluka extension found in {self.ext_dir}.\n"
                "Unpack it there with:  ./sluka install-extension /path/to/sluka-extension-x_y_z.zip"
            )
        try:
            self.manifest = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as err:
            raise ConfigError(f"{path} could not be read: {err}") from err
        key = self.manifest.get("key")
        try:
            self.extension_id = extension_id_from_key(key) if key else extension_id_from_path(self.ext_dir)
        except Exception:  # a malformed key must not stop the app
            self.extension_id = extension_id_from_path(self.ext_dir)
        return self.manifest

    @property
    def extension_version(self) -> str:
        return str(self.manifest.get("version", ""))

    @property
    def csp_policy(self) -> str:
        """The policy the browser would apply to the extension's pages."""
        declared = self.manifest.get("content_security_policy")
        if isinstance(declared, dict) and declared.get("extension_pages"):
            return str(declared["extension_pages"])
        if isinstance(declared, str) and declared:
            return declared
        return "script-src 'self' 'wasm-unsafe-eval'; object-src 'self'"

    # -- folders ----------------------------------------------------------

    def ensure_dirs(self) -> None:
        engine = {"browser": (self.browser_dir,), "webview2": (self.webview_dir,)}.get(self.shell, (self.webkit_data_dir, self.webkit_cache_dir))
        for folder in (self.data_dir, self.log_dir, self.downloads_dir) + engine:
            folder.mkdir(parents=True, exist_ok=True)
        # Private to the user: the word list and API keys live in here.
        try:
            os.chmod(self.data_dir, 0o700)
        except OSError:
            pass

    def write_default_config(self) -> bool:
        if self.config_file.exists():
            return False
        try:
            self.config_file.write_text(default_config_text(), encoding="utf-8")
            return True
        except OSError:
            return False

    def bring_up_to_date(self) -> bool:
        """Rewrite what an earlier version of the app put in config.ini as its own default; true if it did."""
        try:
            text = self.config_file.read_text(encoding="utf-8")
        except OSError:
            return False
        new = text
        if not re.search(r"(?mi)^\s*attach\s*=", text):
            for said in ("no", "yes"):
                new = new.replace(OLD_MPV_BLOCK.replace("hook = no", f"hook = {said}"), NEW_MPV_BLOCK)
            if new == text:
                # The lines around it were changed by hand: only the setting itself is renamed.
                new = re.sub(r"(?mi)^[ \t]*hook[ \t]*=.*$", "attach = yes", text, count=1)
        if WINDOWS and not re.search(r"(?mi)^\s*\[app\]\s*$", new):
            # Written by 0.4.0, which had only a browser's windows: the choice of windows is said where it can be seen.
            new = new.rstrip("\n") + "\n" + APP_BLOCK_WINDOWS
        if WINDOWS and not re.search(r"(?mi)^\s*\[bar\]\s*$", new):
            # Written before 0.6.0: the floating subtitles' settings, where they can be seen.
            new = new.rstrip("\n") + "\n" + BAR_BLOCK_WINDOWS
        if WINDOWS and BUTTON_LINES_060 in new:
            # 0.6.0's own default put the button over Sluka's buttons at the top: it goes to the bottom, as 0.7.0 has
            # it.  A place chosen by hand (other lines than 0.6.0 wrote) stays.
            new = new.replace(BUTTON_LINES_060, BUTTON_LINES_070, 1)
        if WINDOWS and not re.search(r"(?mi)^\s*\[games\]\s*$", new):
            # Written before 0.7.0: the game text's settings, where they can be seen.
            new = new.rstrip("\n") + "\n" + GAMES_BLOCK_WINDOWS
        if WINDOWS and (GAMES_LINES_070 in new or HOOKER_LINES_070 in new):
            # 0.7.0 fetched its text hooker, and said so: 0.8.0's engine comes with it.  A folder written there by hand
            # (other lines than 0.7.0 wrote) stays, read no more.
            new = new.replace(GAMES_LINES_070, GAMES_LINES_080, 1).replace(HOOKER_LINES_070, ENGINE_LINES_080, 1)
        if new == text:
            return False
        try:
            self.config_file.write_text(new, encoding="utf-8")
        except OSError:
            return False
        return True

    def set_option(self, section: str, key: str, value: str) -> bool:
        """Change one line of config.ini, leaving every other line and comment as it is."""
        self.write_default_config()
        try:
            lines = self.config_file.read_text(encoding="utf-8").splitlines()
        except OSError:
            return False
        header = f"[{section}]"
        start = next((i for i, line in enumerate(lines) if line.strip().lower() == header), None)
        if start is None:
            lines += ["", header, f"{key} = {value}"]
        else:
            end = next((i for i in range(start + 1, len(lines)) if lines[i].strip().startswith("[")), len(lines))
            at = next((i for i in range(start + 1, end)
                       if lines[i].split("=", 1)[0].strip().lower() == key and "=" in lines[i] and not lines[i].lstrip().startswith(("#", ";"))), None)
            if at is None:
                lines.insert(start + 1, f"{key} = {value}")
            else:
                lines[at] = f"{key} = {value}"
        try:
            self.config_file.write_text("\n".join(lines) + "\n", encoding="utf-8")
        except OSError:
            return False
        return True


def default_mpv_socket_dir() -> Path:
    if WINDOWS:
        # Where the script in mpv says which pipe its player listens on (mpv/sluka.lua has the same words).
        return local_dir() / "mpv"
    runtime = os.environ.get("XDG_RUNTIME_DIR")
    if runtime and os.path.isdir(runtime):
        return Path(runtime) / "sluka-mpv"
    return Path("/tmp") / f"sluka-mpv-{os.getuid()}"
