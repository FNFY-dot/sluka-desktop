# SPDX-License-Identifier: LicenseRef-Sluka
# Copyright (c) 2026 Sluka. Part of Sluka Desktop; see LICENSE.txt.
"""``sluka doctor``: what this computer has and lacks for the app, with the fix beside each lack."""

from __future__ import annotations

import os
import shutil
import socket
import subprocess
import sys
from pathlib import Path

from . import APP_NAME, __version__
from .config import WINDOWS, Config, ConfigError, kept_private, store_python
from .storage import free_bytes

#: How this app is called from a terminal, for what is said to the user.
SLUKA = ".\\sluka" if WINDOWS else "./sluka"

OK, WARN, BAD = "ok  ", "note", "MISSING"


def _tails() -> str:
    for path in ("/etc/amnesia/version", "/etc/os-release"):
        try:
            text = Path(path).read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if path.endswith("version"):
            return text.split("\n", 1)[0].strip() or "Tails"
        if "TAILS" in text or "Tails" in text:
            for line in text.splitlines():
                if line.startswith("PRETTY_NAME="):
                    return line.split("=", 1)[1].strip('"')
            return "Tails"
    return ""


def _persistent(path: Path) -> bool:
    real = os.path.realpath(str(path))
    return real.startswith("/home/amnesia/Persistent") or real.startswith("/live/persistence/TailsData_unlocked")


#: What the web engine's player (GStreamer) needs for a kind of file: any one of the parts named.
PLAYER_NEEDS = {
    "mkv files": ("matroskademux",),
    "mp4 files": ("qtdemux",),
    "H.264": ("avdec_h264", "openh264dec", "vah264dec", "vaapih264dec"),
    "AV1": ("dav1ddec", "av1dec", "avdec_av1", "vaav1dec"),
    "VP9": ("vp9dec", "avdec_vp9", "vavp9dec"),
    "AAC sound": ("avdec_aac", "fdkaacdec", "faad"),
    "Opus sound": ("opusdec", "avdec_opus"),
}


def _gstreamer():
    """A test for "is this part of GStreamer installed", or None where that cannot be asked."""
    try:
        import gi

        gi.require_version("Gst", "1.0")
        from gi.repository import Gst

        Gst.init(None)
        return lambda name: Gst.ElementFactory.find(name) is not None
    except Exception:
        pass
    inspect = shutil.which("gst-inspect-1.0")
    if inspect:
        return lambda name: subprocess.run([inspect, "--exists", name], capture_output=True).returncode == 0
    return None


def _run(cmd: list[str]) -> str:
    try:
        done = subprocess.run(cmd, capture_output=True, text=True, timeout=8)
        return (done.stdout or done.stderr or "").strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def run_doctor(config: Config) -> int:
    rows: list[tuple[str, str, str]] = []
    fatal = False

    def say(state: str, what: str, how: str = "") -> None:
        nonlocal fatal
        rows.append((state, what, how))
        if state == BAD:
            fatal = True

    print(f"{APP_NAME} {__version__}")
    tails = _tails()
    system = tails
    if WINDOWS:
        import platform

        system = f"Windows {platform.release()} ({platform.version()})"
    say(OK, f"Python {sys.version.split()[0]}" + (f" on {system}" if system else ""))
    if sys.version_info < (3, 9):
        say(BAD, "this Python is too old for the app", "Python 3.9 or newer is needed")
    if store_python():
        say(WARN, "this Python is the one from the Microsoft Store",
            "Windows keeps what it writes under AppData to itself, so mpv would not see Sluka's script, nor Anki\n"
            "the add-on. The app's own windows work. For mpv and Anki: Python from https://www.python.org/downloads/windows/")

    # --- the extension
    try:
        config.load_manifest()
        say(OK, f"Sluka {config.extension_version} in {config.ext_dir}")
    except ConfigError:
        say(BAD, f"no Sluka extension in {config.ext_dir}", f"{SLUKA} install-extension " + ("C:\\path\\to\\sluka-extension-x_y_z.zip" if WINDOWS else "/path/to/sluka-extension-x_y_z.zip"))

    # --- where the data goes
    try:
        config.data_dir.mkdir(parents=True, exist_ok=True)
        probe = config.data_dir / ".write-test"
        probe.write_text("ok")
        probe.unlink()
        free = free_bytes(config.data_dir)
        say(OK if free > 500 * 1024 * 1024 else WARN, f"data folder {config.data_dir} ({free // (1024 * 1024)} MB free)",
            "" if free > 500 * 1024 * 1024 else "less than 500 MB free: dictionaries and books need room")
    except OSError as err:
        say(BAD, f"the data folder {config.data_dir} cannot be written ({err})", "move the app folder somewhere you can write")
    if tails and not _persistent(config.root):
        say(WARN, "the app folder is not in the Persistent Storage",
            "everything, your words included, is gone at the next restart: move the folder to ~/Persistent")

    if config.shell in ("browser", "webview2"):
        if config.shell == "webview2":
            _webview_rows(config, say)
        else:
            _browser_rows(config, say)
        _address_rows(config, say)
        _engine_rows(config, say)
        _network_rows(config, say)
        if WINDOWS:
            _windows_mpv_rows(config, say)
        else:
            say(OK, "mpv: looked at as on any Linux when the app's own windows are used (shell = gtk)")
        _anki_rows(config, say)
        if WINDOWS:
            _games_rows(config, say)
        _live_rows(config, say)
        return _verdict(rows, fatal_of=lambda: fatal)

    # --- the window toolkit
    try:
        import gi  # noqa: F401

        from .gtkshell import MIN_ENGINE, ShellUnavailable, Toolkit

        try:
            tk = Toolkit()
            engine = tk.engine_version()
            if engine < MIN_ENGINE:
                say(BAD, f"{tk.describe()} is too old", "WebKitGTK 2.40 or newer is needed: update the system")
            else:
                say(OK, tk.describe())
        except ShellUnavailable as err:
            lines = str(err).splitlines()
            say(BAD, lines[0], "\n".join(line.strip() for line in lines[2:]) or "install WebKitGTK's Python bindings")
        except Exception as err:  # a display that is not there, a broken install
            say(WARN, f"the window toolkit could not be tried here ({type(err).__name__}: {err})")
    except ImportError:
        say(BAD, "Python's GTK bindings (python3-gi)", "sudo apt install python3-gi gir1.2-webkit-6.0")

    if not os.environ.get("WAYLAND_DISPLAY") and not os.environ.get("DISPLAY"):
        say(WARN, "no display in this terminal", "start the app from a terminal inside the desktop")

    _network_rows(config, say)

    # --- video inside the app
    has = _gstreamer()
    if has is None:
        say(WARN, "what the app's own player can play could not be looked up here", f"{SLUKA} selftest  lists it; mpv plays everything")
    else:
        kinds = {name: any(has(element) for element in elements) for name, elements in PLAYER_NEEDS.items()}
        yes = [name for name, there in kinds.items() if there]
        no = [name for name, there in kinds.items() if not there]
        say(OK if not no else WARN,
            "the app's own player has what it takes for: " + (", ".join(yes) or "nothing") + (f"; not for: {', '.join(no)}" if no else ""),
            "" if not no else "mpv plays everything. For the app's own player:  sudo apt install gstreamer1.0-libav gstreamer1.0-plugins-good gstreamer1.0-plugins-bad")

    # --- mpv
    from .mpvbridge import FLATPAK_PLAYERS, _player_processes, flatpak_players, runtime_dir

    script = config.mpv_dir / "sluka.lua"
    mpv, celluloid, sandboxed = shutil.which("mpv"), shutil.which("celluloid"), flatpak_players()
    home = Path.home()
    if not script.is_file():
        say(WARN, f"the mpv script is missing ({script})")
    else:
        if mpv:
            version = _run([mpv, "--version"]).splitlines()[:1]
            say(OK, f"{version[0] if version else 'mpv'}")
        if sandboxed:
            # Celluloid in Tails 7.10 and later.
            say(OK, f"{', '.join(sandboxed)} (a Flatpak: it reads no folder but its own)")
        elif celluloid:
            say(OK, "Celluloid (plays with mpv inside it)")
        if not (mpv or celluloid or sandboxed):
            say(WARN, "no mpv and no Celluloid", "for Sluka's subtitles in mpv:  sudo apt install mpv")
        elif not mpv:
            say(WARN, "the plain mpv player is not installed",
                "the simplest case for Sluka's script; if Celluloid gives trouble:  sudo apt install mpv")

        # Where the script has to be for a video opened from the desktop to be seen.
        places = [("mpv", home / ".config/mpv/scripts/sluka.lua"), ("Celluloid", home / ".config/celluloid/scripts/sluka.lua")]
        places += [(app, home / ".var/app" / app / FLATPAK_PLAYERS[app] / "sluka.lua") for app in sandboxed]
        there = [name for name, path in places if path.is_file() or path.is_symlink()]
        if not config.mpv_enabled:
            say(WARN, "the bridge to mpv is off ([mpv] enabled = no)")
        elif not config.mpv_attach:
            say(WARN, "[mpv] attach is off", f"only a video started with  {SLUKA} mpv FILE  gets Sluka's subtitles")
        elif there:
            say(OK, f"Sluka's script is in place for: {', '.join(there)}", "any video opened in them is seen while the app is running")
        else:
            say(WARN, "Sluka's script is not in the players yet", f"it is put there when the app starts:  {SLUKA}")
        running = _player_processes()
        if running:
            sockets = []
            for folder in [Path(config.mpv_socket_dir)] + [runtime_dir() / "app" / app / "sluka-mpv" for app in FLATPAK_PLAYERS]:
                try:
                    sockets += [name for name in os.listdir(folder) if name.endswith(".sock")]
                except OSError:
                    pass
            say(OK if sockets else WARN, f"playing now: {', '.join(f'{name} ({pid})' for pid, name in sorted(running.items()))}",
                f"with Sluka's script: {len(sockets)}" + ("" if sockets else "; a video opened before the script was in place has to be opened again"))

    _anki_rows(config, say)
    return _verdict(rows, fatal_of=lambda: fatal)


def _network_rows(config: Config, say) -> None:
    say(OK, f"network mode: {config.network_mode}" + {
        "offline": " (nothing leaves this computer)",
        "tor": f" (through Tor at {config.socks})",
        "direct": " (no proxy)",
    }[config.network_mode])
    if config.network_mode == "tor":
        host, _, port = config.socks.partition(":")
        try:
            with socket.create_connection((host or "127.0.0.1", int(port or 9050)), timeout=2):
                say(OK, "Tor's SOCKS port answers")
        except (OSError, ValueError):
            say(WARN, f"nothing answers at {config.socks}", "connect to Tor first, or set [network] socks in config.ini")


def _browser_rows(config: Config, say, needed: bool = True) -> None:
    """The browser the windows are shown in ([app] shell = browser, or where Windows has no web view)."""
    from .browsershell import find_browser

    browser = find_browser(config)
    if browser:
        say(OK, f"the windows are shown by {browser}", f"with a profile of its own: {config.browser_dir}")
    elif needed:
        say(BAD, "no browser to show the windows in (Microsoft Edge, Chrome, Brave, Vivaldi or Chromium)",
            "install one, or name it in config.ini:  [browser]  path = ...")


def _webview_rows(config: Config, say) -> None:
    """Windows' own web view: there, and tried with a page of its own."""
    from .browsershell import find_browser
    from .webview2 import find_runtime

    runtime = find_runtime(config.webview_runtime)
    if runtime is None:
        browser = find_browser(config) if config.shell_auto else None
        if browser:
            say(WARN, "Windows' own web view (the WebView2 Runtime) was not found",
                f"the windows are {browser[0]}'s instead ({browser[1]})\n"
                "Windows' web view is put in by Windows Update; or: https://developer.microsoft.com/microsoft-edge/webview2/")
        else:
            say(BAD, "Windows' own web view (the WebView2 Runtime) was not found",
                "it comes with Windows 11 and Windows Update keeps it; should it be missing, its installer\n"
                "(\"Evergreen Bootstrapper\") is at https://developer.microsoft.com/microsoft-edge/webview2/\n"
                "or have a browser show the windows:  [app]  shell = browser  in config.ini")
        return
    say(OK, f"Windows' own web view: {runtime.describe()}", "the app's windows are its own: no browser is needed")
    code, lines, errors = _try_webview()
    said = [line.split(":", 1) for line in lines if ":" in line]
    oks = [text.strip() for state, text in said if state.strip() == "ok"]
    failed = [text.strip() for state, text in said if state.strip() == "failed"]
    if code == 0:
        answer = next((t for t in oks if t.startswith("a script in the page answered")), "")
        engine = answer.split(":", 1)[1].strip() if ":" in answer else ""
        say(OK, "a page was opened in it, and a script in the page answered", engine)
        return
    how = f"each step:  {SLUKA} webview-check"
    if code is None:
        say(BAD, "Windows' web view did not answer within two minutes" + (f" (last: {oks[-1]})" if oks else ""), how)
    elif failed:
        say(BAD, f"Windows' web view did not work for the app: {failed[-1]}", how)
    else:
        crash = next((line.strip() for line in errors if "exception" in line.lower() or "fatal" in line.lower()), "")
        say(BAD, f"the try of Windows' web view ended on a crash (code {code & 0xFFFFFFFF:#x})"
            + (f" after: {oks[-1]}" if oks else ""), "\n".join(filter(None, [crash, how])))


def _try_webview() -> tuple:
    """``sluka webview-check`` as a program of its own: (its exit code or None, its lines, its error lines)."""
    entry = Path(__file__).resolve().parent.parent / "run.py"
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        done = subprocess.run([sys.executable, "-I", str(entry), "webview-check"], capture_output=True, text=True,
                              errors="replace", timeout=120, creationflags=flags)
    except subprocess.TimeoutExpired as err:
        out = err.stdout.decode("utf-8", "replace") if isinstance(err.stdout, bytes) else (err.stdout or "")
        return None, out.splitlines(), []
    except OSError as err:
        return 1, [f"failed: it could not be started ({err})"], []
    return done.returncode, (done.stdout or "").splitlines(), (done.stderr or "").splitlines()


def _address_rows(config: Config, say) -> None:
    """The address the app's pages have on this computer."""
    from .browsershell import running_copy

    port = config.browser_port
    if running_copy(port):
        say(OK, f"the app is running now (http://127.0.0.1:{port})")
        return
    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            probe.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        probe.bind(("127.0.0.1", port))
        say(OK, f"the app's address is free (http://127.0.0.1:{port})")
    except OSError as err:
        say(BAD, f"another program has the port the app needs ({port}: {err})",
            "choose another in config.ini:  [app]  port = 47822")
    finally:
        probe.close()


def _engine_rows(config: Config, say) -> None:
    """What the app's pages may do, and the fonts for mpv."""
    if not config.web_security:
        say(OK, "the app's pages may fetch from any website, as the extension may ([app] web_security = off)")
    else:
        say(WARN, "[app] web_security = on", "what Sluka fetches from websites (translation, online dictionaries) will fail")
    if WINDOWS:
        try:
            from .winfonts import Finder

            finder = Finder()
            finder._load()
            count = len(finder.families)
            say(OK if count else WARN, f"the fonts of this computer are read for mpv ({count} families)",
                "" if count else "Sluka's text in mpv may be set in another font than in the app")
        except Exception as err:
            say(WARN, f"the fonts could not be read ({type(err).__name__}: {err})", "Sluka's text in mpv may be set in another font than in the app")


def _windows_mpv_rows(config: Config, say) -> None:
    from .install import windows_script_folders
    from .mpvbridge import PIPE_NAME, find_windows_player, pipe_names

    script = config.mpv_dir / "sluka.lua"
    if not script.is_file():
        say(WARN, f"the mpv script is missing ({script})")
        return
    player = find_windows_player(config)
    if player:
        version = _run([player, "--version"]).splitlines()[:1] if player.lower().endswith("mpv.exe") else []
        say(OK, (version[0] if version else "mpv") + f" ({player})")
    else:
        say(WARN, "no mpv was found (on the PATH, or in the usual folders)",
            "get it from https://mpv.io/installation/ ; if it is in a folder of its own, say where:\n"
            f"{SLUKA} install-mpv C:\\path\\to\\mpv")
    places = windows_script_folders(config)
    there = [str(folder) for folder in places if (folder / "sluka.lua").is_file() and not kept_private(folder / "sluka.lua")]
    if not config.mpv_enabled:
        say(WARN, "the bridge to mpv is off ([mpv] enabled = no)")
    elif not config.mpv_attach:
        say(WARN, "[mpv] attach is off", f"only a video started with  {SLUKA} mpv FILE  gets Sluka's subtitles")
    elif there:
        say(OK, "Sluka's script is in place: " + ", ".join(there), "any video opened in mpv is seen while the app is running")
    else:
        say(WARN, "Sluka's script is not in mpv's folder yet (" + ", ".join(str(f) for f in places) + ")",
            f"it is put there when the app starts:  {SLUKA}")
    playing = [name for name in pipe_names() if name.startswith(PIPE_NAME)]
    if playing:
        say(OK, f"mpv is playing with Sluka's script now ({len(playing)})")


def _ask_running(port: int, name: str, timeout: float = 2.0):
    """One of the running app's own answers about itself (``/__sluka__/api/<name>``); None where there is none."""
    import json
    import urllib.error

    from .browsershell import _straight

    try:
        with _straight.open(f"http://127.0.0.1:{port}/__sluka__/api/{name}", timeout=timeout) as answer:
            found = json.loads(answer.read(1_000_000).decode("utf-8", "replace"))
    except (OSError, ValueError, urllib.error.URLError):
        return None
    return found if isinstance(found, dict) else None


def _live_rows(config: Config, say) -> None:
    """Whom the running app is talking to now: the players and the Ankis that answered it, not only the files in place."""
    port = config.browser_port
    info = _ask_running(port, "info")
    if not info or (info.get("app") or {}).get("name") != APP_NAME:
        say(OK, "the app is not running now",
            "with it running, the doctor also says whether mpv and Anki answer it: start the app, open them, ask again")
        return
    running = str((info.get("app") or {}).get("version") or "")
    if running and running != __version__:
        say(WARN, f"the app running now is version {running}, and this copy {__version__}", "close it, and start this one")
    if config.mpv_enabled:
        mpv = _ask_running(port, "mpv/status")
        if mpv is not None:
            players, answered = list(mpv.get("names") or []), set(mpv.get("answered") or [])
            silent = [name for name in players if name not in answered]
            if not players:
                say(OK, "no mpv player is talking to the app now", "open a video in mpv: the app finds it within a second or two")
            elif silent:
                say(WARN, f"mpv players connected to the app: {len(players)}; answering: {len(players) - len(silent)}",
                    "a player that does not answer has the script of before in it: close it and open the video again")
            else:
                say(OK, f"mpv players talking to the app: {len(players)}")
            if players and "engine" in mpv and not mpv.get("engine"):
                say(WARN, "Sluka's own code in the app's hidden page is not asking for mpv's lines",
                    "close the app and start it again; its log (sluka-desktop.log) says why")
    if config.anki_enabled:
        anki = _ask_running(port, "anki/status")
        if anki is not None:
            older = list(anki.get("older") or [])
            count = int(anki.get("ankis") or 0)
            heard = [about for about in anki.get("about") or [] if isinstance(about, dict) and about.get("addon")]
            if older:
                say(WARN, "an Anki is running the add-on of an older Sluka Desktop, which falls over when the app connects: "
                          "the app leaves it alone", "close Anki and start it again: it then loads the add-on this app put in place")
            if count:
                described = "; ".join(f"Anki {a.get('anki') or '?'}, add-on {a.get('addon')}" for a in heard)
                say(OK if len(heard) == count else WARN, f"Anki talking to the app: {count}" + (f" ({described})" if described else ""),
                    "" if len(heard) == count else "an Anki connected and has not answered: its add-on's notes are in user_files/log.txt in the add-on's folder")
                for about in heard:
                    if about.get("addon") != __version__:
                        say(WARN, f"the add-on running in Anki is version {about.get('addon')}, the app {__version__}",
                            "close Anki and start it again")
            elif not older:
                say(OK, "no Anki is talking to the app now", "start Anki: the app finds it as it opens")
    corner = {"top-right": "top right", "top-left": "top left", "bottom-right": "bottom right"}.get(getattr(config, "bar_button", ""), "bottom left")
    bar = info.get("bar")
    if isinstance(bar, dict):
        if not bar.get("on"):
            say(OK, "the floating subtitles are off", f"the subtitles button at the {corner} of Sluka's window turns them on")
        elif not bar.get("engine"):
            say(WARN, "the floating subtitles are on, without Sluka's engine: lines are shown as they come, not read",
                "the app's log (sluka-desktop.log) says why the engine is not there")
        else:
            say(OK, "the floating subtitles are on" + ("" if bar.get("page") else ", their window still starting"),
                "a line goes into them by  sluka bar-text \"...\"  or the address http://127.0.0.1:%d/__sluka__/api/bar/text" % port)
    games = info.get("games")
    if isinstance(games, dict):
        mode = games.get("mode")
        game = games.get("game") if isinstance(games.get("game"), dict) else None
        if mode == "game" and game:
            state = game.get("state")
            say(OK if state in ("attaching", "attached") else WARN,
                f"game text: {game.get('exe') or 'a game'} ({game.get('bits')}-bit) is {state}; text threads: {games.get('threads', 0)}, "
                f"picked: {games.get('selected', 0)}",
                "" if games.get("selected") or state != "attached" else "pick the thread with the game's lines in the game text menu")
        elif mode == "clipboard":
            say(OK, "game text comes from the clipboard")
        elif mode == "vision":
            vision = games.get("vision") if isinstance(games.get("vision"), dict) else {}
            target = vision.get("target") if isinstance(vision.get("target"), dict) else None
            if vision.get("error"):
                say(WARN, f"Sluka Vision: {vision['error']}", "its reader's notes are in data\\logs\\ocrd-vision.log")
            elif target:
                last = vision.get("last") if isinstance(vision.get("last"), dict) else {}
                say(OK, f"Sluka Vision reads {target.get('title') or target.get('exe') or 'a window'}"
                    + (f": {last.get('lines')} lines last time, in {last.get('ms')} ms, by {last.get('engine')}" if last.get("engine") else ""))
            else:
                say(OK, "Sluka Vision: no window is read yet", "press its key in the game (Alt+S as it comes)")
        elif mode == "screen":
            screen = games.get("screen") if isinstance(games.get("screen"), dict) else {}
            target = screen.get("target") if isinstance(screen.get("target"), dict) else None
            if screen.get("error"):
                say(WARN, f"game text is read off the screen, and the screen reader cannot start: {screen['error']}",
                    "its notes are in data\\logs\\ocrd.log")
            elif target:
                state = target.get("state")
                say(OK if state in ("starting", "watching") else WARN,
                    f"game text is read off the screen: a box of {target.get('title') or target.get('exe') or 'the screen'} is "
                    f"{'read' if state == 'watching' else state}" + (f", by {target.get('engine')}" if target.get("engine") else ""))
            else:
                say(OK, "game text is read off the screen: no box is chosen now",
                    f"the game text button beside the subtitles button, at the {corner}: Screen, Select the text box")
        elif mode == "game":
            say(OK, "game text: no game is hooked now", f"the game text button beside the subtitles button, at the {corner}")


def _games_rows(config: Config, say) -> None:
    """Sluka's engine for game text: whether all of it is here, and whether it starts."""
    if not getattr(config, "games_enabled", False):
        return
    from .texthook import ENGINE_VERSION, find_engine, try_engine

    engine = find_engine(config)
    if not engine.ok:
        say(WARN, "game text: Sluka's engine cannot be used", engine.error)
        return
    ok, said = try_engine(engine, log_path=config.log_dir / "hookd-doctor.log")
    if ok:
        say(OK, f"game text: Sluka's engine (LunaHook from {ENGINE_VERSION}) starts ({said}), for 32-bit and 64-bit games",
            f"try it on a running game with  {SLUKA} hook-check --list  and  {SLUKA} hook-check PID")
    else:
        say(WARN, f"game text: Sluka's engine (in {engine.folder}) does not start: {said}",
            "its own notes are in data\\logs\\hookd-doctor.log; the Clipboard tab of the game text menu "
            "still takes what LunaTranslator or Textractor read")
    _screen_rows(config, say)


#: Sluka's own OCR, in the engine folder's ocr folder (LunaTranslator's).
OCR_FILES = ("CVUtils.dll", "NativeUtils.dll", "onnxruntime.dll", "model/det.onnx", "model/rec.onnx", "model/dict.txt")


def _screen_rows(config: Config, say) -> None:
    """The screen's readers (OCR): which of them can be used here, and why not the others."""
    from .ocrtext import AUTO_ORDER, READER_NAMES, try_readers
    from .texthook import engine_dir

    folder = engine_dir(config) / "ocr"
    missing = [name for name in OCR_FILES if not (folder / name).is_file()]
    if missing:
        say(WARN, f"screen text: files of Sluka's own OCR are missing from {folder}: {', '.join(missing)}",
            "unpack Sluka Desktop's zip again (an antivirus may have taken them away)")
    ok, found = try_readers(config)
    if not ok:
        say(WARN, f"screen text: Sluka's screen reader does not start: {found}", "its notes are in data\\logs\\ocrd-doctor.log")
        return
    usable = [name for name in AUTO_ORDER if (found.get(name) or {}).get("ok")]
    online = (found.get("lens") or {}).get("ok")
    others = [f"{READER_NAMES[name]} OCR: {(found.get(name) or {}).get('why') or 'not here'}" for name in AUTO_ORDER if name not in usable]
    if usable:
        say(OK, "screen text: the screen can be read here by " + ", ".join(f"{READER_NAMES[name]} OCR" for name in usable)
            + (", and Google Lens (online)" if online else ""),
            "\n".join(others + [f"try one on a box of the screen with  {SLUKA} ocr-check --read"]))
    else:
        say(WARN, "screen text: none of the offline readers can be used here" + (" (Google Lens, online, can)" if online else ""),
            "\n".join(others))


def _verdict(rows, fatal_of) -> int:
    for state, what, how in rows:
        print(f"  [{state}] {what}")
        for line in how.splitlines():
            print(f"           -> {line}")
    print()
    if fatal_of():
        print("Not ready yet: see MISSING above.")
        return 1
    print(f"Ready. Start the app with:  {SLUKA}")
    return 0


def _anki_rows(config: Config, say) -> None:
    from .ankibridge import AnkiBridge
    from .install import ANKI_ADDON, anki_bases

    addon_source = config.anki_dir / ANKI_ADDON / "__init__.py"
    known = [folder for folder in config.anki_addons if (folder / "__init__.py").is_file()]
    found = [folder for folder in anki_bases() if folder.is_dir()]
    if not addon_source.is_file():
        say(WARN, f"the add-on for Anki is missing from this copy of the app ({addon_source.parent})")
    elif not config.anki_enabled:
        say(WARN, "the bridge to Anki is off ([anki] enabled = no)")
    elif known:
        for folder in known:
            if kept_private(folder / "__init__.py"):
                say(WARN, f"Sluka's add-on is not where Anki sees it ({folder})",
                    "it was written by the Microsoft Store's Python, into a folder of its own: see above")
                continue
            linked = (folder / "ext" / "manifest.json").is_file()
            say(OK if linked else WARN, f"Sluka's add-on is in Anki ({folder})",
                "with the app running, Sluka reads the cards you review" if linked
                else f"but Sluka's own files are not reachable from there:  {SLUKA} install-anki  puts that right")
        waiting = []
        for _who, folder in AnkiBridge(config, None).places():
            try:
                waiting += [name for name in os.listdir(folder) if name.endswith((".sock", ".port"))]
            except OSError:
                pass
        if waiting:
            say(OK, f"Anki is running with the add-on ({len(waiting)})")
    elif config.anki_addons:
        say(WARN, "Sluka's add-on is not where it was put (" + ", ".join(str(f) for f in config.anki_addons) + ")",
            f"Anki's folder is not there now, or the add-on was removed:  {SLUKA} install-anki [Anki's folder]")
    elif found:
        say(OK, f"Anki is here ({', '.join(str(f) for f in found)}); Sluka is not in it",
            f"to have Sluka read the cards you review:  {SLUKA} install-anki")
    else:
        say(OK, "Sluka is not in Anki",
            f"to have Sluka read the cards you review:  {SLUKA} install-anki FOLDER\n"
            "(FOLDER: the one that holds Anki's addons21; in Anki, Tools > Add-ons > View Files opens addons21)")
