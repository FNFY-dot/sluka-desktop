# SPDX-License-Identifier: LicenseRef-Sluka
# Copyright (c) 2026 Sluka. Part of Sluka Desktop; see LICENSE.txt.
"""Command line of Sluka Desktop.

    sluka                     open the app
    sluka doctor              check that this computer has what the app needs
    sluka install-extension Z unpack a Sluka extension zip into the app folder
    sluka install-menu        add Sluka to the desktop's application menu (Windows: shortcuts)
    sluka remove-from-pc      (Windows) take away what the app put outside its folder (the setup's Uninstall)
    sluka install-anki [DIR]  put Sluka into Anki's review screen
    sluka install-mpv DIR     (Windows) an mpv that keeps its settings beside itself: where it is
    sluka mpv FILE            play a video in mpv with Sluka's subtitles
    sluka selftest            open a window that checks what the web engine here can do
    sluka webview-check       (Windows) try Windows' own web view, step by step
    sluka serve               (development) serve the app to a browser on localhost
"""

from __future__ import annotations

import argparse
import logging
import logging.handlers
import os
import sys
from pathlib import Path

from . import APP_NAME, __version__
from .config import WINDOWS, Config, ConfigError
from .tell import has_terminal, problem


def setup_logging(config: Config | None, verbose: bool) -> None:
    root = logging.getLogger()
    root.setLevel(logging.DEBUG if verbose else logging.INFO)
    fmt = logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s", "%Y-%m-%d %H:%M:%S")
    if WINDOWS:
        # Two of the app's processes may hold the log at once there (a second start, the doctor), and Windows
        # then refuses to move the full file aside: that is no reason to print a traceback.
        logging.raiseExceptions = False
    if has_terminal():  # not when started without a console window (Windows, pythonw)
        stream = logging.StreamHandler(sys.stderr)
        stream.setFormatter(fmt)
        stream.setLevel(logging.DEBUG if verbose else logging.WARNING)
        root.addHandler(stream)
    if config:
        try:
            config.log_dir.mkdir(parents=True, exist_ok=True)
            handler = logging.handlers.RotatingFileHandler(
                config.log_dir / "sluka-desktop.log", maxBytes=1_000_000, backupCount=3, encoding="utf-8"
            )
            handler.setFormatter(fmt)
            root.addHandler(handler)
        except OSError as err:
            if has_terminal():
                print(f"warning: no log file ({err})", file=sys.stderr)


def detach(config: Config, argv: list[str], page: str) -> int | None:
    """Windows: carry on without a console window.  The exit code if that was done, None to carry on here.

    Started from Sluka.cmd or a shortcut, the app would otherwise keep a black window open for as long
    as it runs, and end when that window is closed.  What can go wrong at the start is looked at first,
    while there still is a window to say it in.
    """
    import os
    import subprocess
    import time

    from . import browsershell

    here = Path(sys.executable)
    windowless = here.with_name("pythonw.exe")
    if here.name.lower().startswith("pythonw") or not windowless.is_file():
        return None
    port = config.browser_port
    if browsershell.running_copy(port):
        return None  # the running app is asked for a window, which takes no time
    if not can_show_windows(config):
        return None  # said where it can be read
    entry = Path(__file__).resolve().parent.parent / "run.py"
    if not entry.is_file():
        return None
    command = [str(windowless), "-I", str(entry)]
    command += [a for a in argv if a != "--foreground"] + ["--foreground"]
    flags = getattr(subprocess, "DETACHED_PROCESS", 0x8) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x200)
    try:
        child = subprocess.Popen(command, cwd=str(entry.parent), close_fds=True, creationflags=flags,
                                 stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                 env={**os.environ, "SLUKA_DETACHED": "1"})
    except OSError:
        return None
    until = time.monotonic() + 20
    while time.monotonic() < until:
        if browsershell.running_copy(port):
            print(f"{APP_NAME} is running. This window can be closed.")
            return 0
        code = child.poll()
        if code is not None:
            if code:
                print(f"sluka: the app ended at once (code {code}). The log says why: {config.log_dir / 'sluka-desktop.log'}", file=sys.stderr)
            return code
        time.sleep(0.25)
    print(f"{APP_NAME} is starting. This window can be closed.")
    return 0


#: What to do when Windows' own web view is missing.
WEBVIEW_HELP = (
    "Windows' web view (the Microsoft Edge WebView2 Runtime) comes with Windows 11 and is kept up to date by\n"
    "Windows Update; uninstalling Edge leaves it in place. Should it be missing, its installer (the\n"
    "\"Evergreen Bootstrapper\") is at https://developer.microsoft.com/microsoft-edge/webview2/\n"
    "Or have a browser show the windows: in config.ini,  [app]  shell = browser"
)


def can_show_windows(config: Config) -> bool:
    """Whether there is something here to show the app's windows in (Windows' web view, or a browser)."""
    from .browsershell import find_browser

    if config.shell == "webview2":
        from .webview2 import find_runtime

        if find_runtime(config.webview_runtime):
            return True
        return bool(config.shell_auto and find_browser(config))
    return bool(find_browser(config))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="sluka", description=f"{APP_NAME} {__version__}")
    parser.add_argument("--root", help="the app folder (default: where this program is)")
    parser.add_argument("--extension", help="folder holding the unpacked Sluka extension")
    parser.add_argument("--data", help="folder for Sluka's data")
    parser.add_argument("-v", "--verbose", action="store_true", help="say more, on the terminal too")
    # Also taken without a command, as in "sluka --safe-graphics".
    parser.add_argument("--safe-graphics", dest="top_safe_graphics", action="store_true",
                        help="turn off accelerated drawing in the web view")
    parser.add_argument("--no-webkit-sandbox", dest="top_no_webkit_sandbox", action="store_true",
                        help="run the web view without its sandbox")
    parser.add_argument("--foreground", dest="top_foreground", action="store_true",
                        help="(Windows) stay in this terminal instead of carrying on without a window")
    sub = parser.add_subparsers(dest="command")

    run = sub.add_parser("run", help="open the app (the default)")
    run.add_argument("page", nargs="?", default="", help="page to open: dashboard, books, videos, audio")
    run.add_argument("--safe-graphics", action="store_true", help="turn off accelerated drawing in the web view")
    run.add_argument("--no-webkit-sandbox", action="store_true", help="run the web view without its sandbox")
    run.add_argument("--foreground", action="store_true", help="(Windows) stay in this terminal")

    sub.add_parser("doctor", help="check this computer")
    test = sub.add_parser("selftest", help="open a window that checks what the web engine here can do")
    test.add_argument("--safe-graphics", action="store_true", help="turn off accelerated drawing in the web view")
    test.add_argument("--no-webkit-sandbox", action="store_true", help="run the web view without its sandbox")
    test.add_argument("--foreground", action="store_true", help="(Windows) stay in this terminal")

    install = sub.add_parser("install-extension", help="unpack a Sluka extension zip into the app folder")
    install.add_argument("zip", help="the sluka-extension zip (or an unpacked folder)")

    menu = sub.add_parser("install-menu", help="add Sluka to the desktop's application menu")
    menu.add_argument("--mpv", action="store_true", help="also have mpv and Celluloid load Sluka's script by themselves")
    menu.add_argument("--no-desktop", action="store_true", help="(Windows) no shortcut on the desktop (and the one there taken away)")
    menu.add_argument("--no-start-menu", action="store_true", help="(Windows) none in the Start menu (and the one there taken away)")
    sub.add_parser("remove-from-pc", help="(Windows) take away what the app put outside its folder: shortcuts, Anki's add-on, mpv's script")

    anki = sub.add_parser("install-anki", help="put Sluka into Anki's review screen (an add-on of this app's)")
    anki.add_argument("folder", nargs="?", default="", help="Anki's own folder, the one that holds addons21 (default: the usual places)")
    anki.add_argument("--copy", action="store_true", help="copy Sluka's files into the add-on instead of linking to them (about 200 MB)")

    place = sub.add_parser("install-mpv", help="put Sluka's script where an mpv reads its scripts (Windows: an mpv with its own folder)")
    place.add_argument("folder", nargs="?", default="", help="the folder mpv.exe is in, or the folder of its settings")

    mpv = sub.add_parser("mpv", help="play a video in mpv with Sluka's subtitles")
    mpv.add_argument("files", nargs="*", help="video (and subtitle) files")

    bar = sub.add_parser("bar", help="(Windows) turn the floating subtitles of the running app on or off")
    bar.add_argument("what", nargs="?", default="toggle", choices=("on", "off", "toggle"), help="on, off, or the other of the two (default)")
    text = sub.add_parser("bar-text", help="(Windows) show a line in the floating subtitles of the running app")
    text.add_argument("text", help='the line ("-": read it from what is piped in)')
    text.add_argument("--lang", default="", help="its language, where it is another of yours than the one Sluka is set to (ja, zh, ko, ...)")

    sub.add_parser("webview-check", help="(Windows) try Windows' own web view, step by step (the doctor does this)")
    hook = sub.add_parser("hook-check", help="(Windows) try Sluka's engine for game text, and read a game's text threads for a while")
    hook.add_argument("pid", nargs="?", type=int, default=0, help="the game's program number (the PID in Task Manager, or from --list)")
    hook.add_argument("--list", action="store_true", help="list the programs with a window, as the game text menu does")
    hook.add_argument("--admin", action="store_true", help="put the hook in as administrator (for a game run as administrator; Windows asks first)")
    hook.add_argument("--seconds", type=int, default=40, help="how long to read the game's text (default 40)")
    ocr = sub.add_parser("ocr-check", help="(Windows) try the screen's readers (OCR): which can be used here, and what each reads in a box")
    ocr.add_argument("--read", action="store_true", help="drag a box over the screen, and have each reader that can be used here read it")
    ocr.add_argument("--reader", choices=("builtin", "windows", "lens"), default="",
                     help="only this reader (lens: Google Lens, which sends the picture to Google)")
    ocr.add_argument("--lang", default="ja", help="the language Windows' OCR is to read (default ja)")

    serve = sub.add_parser("serve", help="(development) serve the app over HTTP on localhost")
    serve.add_argument("--port", type=int, default=0)
    serve.add_argument("--as-extension", action="store_true",
                       help="make pages behave as on the chrome-extension: scheme (tests)")
    serve.add_argument("--mpv", action="store_true", help="start the mpv bridge too")
    serve.add_argument("--anki", action="store_true", help="start the bridge to Anki too")
    return parser


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if os.environ.get("SLUKA_OUTPUT", "").lower() == "utf-8":
        # Run by Sluka Desktop's setup, which reads what is said here through a pipe: in UTF-8, whatever the
        # Windows' code page (a user name with letters outside it is said all the same).
        for stream in (sys.stdout, sys.stderr):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except (AttributeError, ValueError, OSError):
                pass
    # A zip dragged onto Sluka.cmd arrives as the one argument: the extension, to be put in.
    dropped = len(argv) == 1 and argv[0].lower().endswith(".zip") and Path(argv[0]).is_file()
    if not dropped:
        return _main(argv)
    code = _main(["install-extension", argv[0]])
    try:
        if sys.stdin is not None and sys.stdin.isatty():
            input("\nPress Enter to close this window. ")
    except (EOFError, OSError, ValueError):
        pass
    return code


def _main(argv: list[str]) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    command = args.command or "run"
    try:
        config = Config(
            root=Path(args.root) if args.root else None,
            extension=Path(args.extension) if args.extension else None,
            data=Path(args.data) if args.data else None,
        )
    except ConfigError as err:
        print(f"sluka: {err}", file=sys.stderr)
        return 2

    if command == "doctor":
        from .doctor import run_doctor
        return run_doctor(config)

    if command == "webview-check":
        if not WINDOWS:
            print("sluka: Windows' web view is only on Windows.", file=sys.stderr)
            return 2
        setup_logging(None, args.verbose)
        try:
            config.load_manifest()
        except ConfigError:
            pass
        from .winshell import check
        return check(config)

    if command == "install-extension":
        from .install import install_extension
        return install_extension(config, Path(args.zip).expanduser())

    if command == "install-menu":
        from .install import install_menu
        try:
            config.load_manifest()
        except ConfigError:
            pass
        if WINDOWS and (args.no_desktop or args.no_start_menu):
            from .install import remove_shortcuts

            for path in remove_shortcuts(config, desktop=args.no_desktop, start_menu=args.no_start_menu):
                print(f"  took away {path}")
        return install_menu(config, with_mpv=args.mpv, desktop=not args.no_desktop, start_menu=not args.no_start_menu)

    if command == "remove-from-pc":
        from .install import remove_from_pc

        return remove_from_pc(config)

    if command == "install-anki":
        from .install import install_anki
        try:
            config.load_manifest()
        except ConfigError:
            pass
        config.write_default_config()
        return install_anki(config, args.folder, copy=args.copy)

    if command == "hook-check":
        setup_logging(None, args.verbose)
        from .texthook import command_check

        return command_check(config, args.pid, seconds=args.seconds, show_list=args.list, elevate=args.admin)

    if command == "ocr-check":
        setup_logging(None, args.verbose)
        from .ocrtext import command_check as ocr_check

        return ocr_check(config, read=args.read or bool(args.reader), reader=args.reader, lang=args.lang)

    if command in ("bar", "bar-text"):
        # Said to the app that is running, the way any other program can say it (bar.py).
        from .bar import command_bar, command_text

        if command == "bar":
            return command_bar(config, args.what)
        return command_text(config, args.text, args.lang)

    if command == "install-mpv":
        from .install import hook_players, install_mpv
        config.write_default_config()
        if WINDOWS:
            return install_mpv(config, args.folder)
        placed = hook_players(config)
        return 0 if placed else 1

    setup_logging(config, args.verbose)
    log = logging.getLogger("sluka")
    try:
        config.load_manifest()
    except ConfigError as err:
        problem(str(err))
        return 2
    config.ensure_dirs()
    config.write_default_config()
    config.bring_up_to_date()
    log.info("%s %s, Sluka %s, data in %s", APP_NAME, __version__, config.extension_version, config.data_dir)

    if command == "serve":
        from .devserver import serve
        return serve(config, port=args.port, as_extension=args.as_extension, with_mpv=args.mpv, with_anki=args.anki)

    if command == "mpv":
        from .mpvbridge import launch_player
        return launch_player(config, args.files)

    if config.mpv_enabled and config.mpv_attach:
        # So that a video opened in mpv or Celluloid is seen.  At every start, because Tails forgets.
        try:
            from .install import hook_players

            placed = hook_players(config, quiet=True)
            for path in placed:
                log.info("mpv script in %s", path)
            if not placed:
                log.warning("Sluka's script could not be put where mpv looks for scripts")
        except Exception:
            log.exception("could not put the mpv script in place")
    elif config.mpv_enabled:
        log.info("[mpv] attach is off: only a video started with 'sluka mpv FILE' gets Sluka's subtitles")

    if config.anki_enabled and config.anki_addons:
        # The add-on in Anki is this app's, and is kept the same version as it.
        try:
            from .install import refresh_anki

            for line in refresh_anki(config):
                log.info("%s", line)
        except Exception:
            log.exception("could not bring the Anki add-on up to date")

    page = "__sluka__/selftest.html" if command == "selftest" else getattr(args, "page", "")
    if config.shell in ("webview2", "browser"):
        # Windows: the app's own windows with Windows' web view in them, or (where it has none) a browser's.
        foreground = args.top_foreground or getattr(args, "foreground", False)
        if WINDOWS and not foreground and has_terminal():
            done = detach(config, argv, page)
            if done is not None:
                return done
            print(f"{APP_NAME} runs from this window: closing it ends the app.", flush=True)
        use_browser = config.shell == "browser"
        if not use_browser:
            from . import winshell

            try:
                return winshell.run_app(config, page=page)
            except winshell.Unavailable as err:
                from .browsershell import find_browser

                if config.shell_auto and find_browser(config):
                    log.warning("%s The windows are a browser's instead.", err)
                    use_browser = True
                else:
                    problem(f"{err}\n\n{WEBVIEW_HELP}")
                    return 3
            except Exception as err:
                log.exception("the app stopped on an error")
                problem(f"{APP_NAME} stopped on an error ({type(err).__name__}: {err}).\n"
                        f"The log says more: {config.log_dir / 'sluka-desktop.log'}")
                return 1
        from .browsershell import run_app as run_in_browser

        try:
            return run_in_browser(config, page=page)
        except Exception as err:
            log.exception("the app stopped on an error")
            problem(f"{APP_NAME} stopped on an error ({type(err).__name__}: {err}).\n"
                    f"The log says more: {config.log_dir / 'sluka-desktop.log'}")
            return 1

    from .gtkshell import run_app
    return run_app(
        config,
        page=page,
        safe_graphics=args.top_safe_graphics or getattr(args, "safe_graphics", False),
        no_sandbox=args.top_no_webkit_sandbox or getattr(args, "no_webkit_sandbox", False),
    )


if __name__ == "__main__":
    sys.exit(main())
