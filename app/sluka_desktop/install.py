# SPDX-License-Identifier: LicenseRef-Sluka
# Copyright (c) 2026 Sluka. Part of Sluka Desktop; see LICENSE.txt.
"""``sluka install-extension``, ``sluka install-menu`` and ``sluka install-anki``.

The Sluka extension itself is not part of this app: you bring the zip from
sluka.app, and this unpacks it into the app folder.  A newer Sluka is put in
the same way, over the old one; your words and books are not in that folder.
"""

from __future__ import annotations

import json
import os
import shutil
import stat
import sys
import zipfile
from pathlib import Path

from .config import PRIVATE_COPY, WINDOWS, Config, ConfigError, kept_private

TAILS_DOTFILES = Path("/live/persistence/TailsData_unlocked/dotfiles")
#: How this app is called from a terminal, for what is said to the user.
SLUKA = ".\\sluka" if WINDOWS else "./sluka"


def _manifest_prefix(names: list[str]) -> str | None:
    """Where in the archive the extension is: '' or 'some-folder/'."""
    if "manifest.json" in names:
        return ""
    tops = sorted({n.split("/", 1)[0] for n in names if "/" in n})
    for top in tops:
        if f"{top}/manifest.json" in names:
            return f"{top}/"
    return None


def _unpack(archive: Path, target: Path) -> None:
    with zipfile.ZipFile(archive) as bundle:
        names = bundle.namelist()
        prefix = _manifest_prefix(names)
        if prefix is None:
            raise ConfigError("That zip does not hold a browser extension (no manifest.json in it).")
        root = os.path.realpath(target)
        done = 0
        for info in bundle.infolist():
            if not info.filename.startswith(prefix) or info.is_dir():
                continue
            rel = info.filename[len(prefix):]
            # Nothing may be written outside the folder, whatever the archive names it.
            if not rel or rel.startswith("/") or ".." in rel.replace("\\", "/").split("/"):
                raise ConfigError(f"The zip holds a path that is not allowed: {info.filename}")
            if stat.S_ISLNK(info.external_attr >> 16):
                raise ConfigError(f"The zip holds a link, which an extension has no use for: {info.filename}")
            dest = os.path.realpath(os.path.join(root, rel))
            if not dest.startswith(root + os.sep):
                raise ConfigError(f"The zip holds a path that is not allowed: {info.filename}")
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            with bundle.open(info) as src, open(dest, "wb") as out:
                shutil.copyfileobj(src, out, 1024 * 1024)
            done += 1
            if done % 200 == 0:
                print(f"  {done} files…", flush=True)
        print(f"  {done} files", flush=True)


def install_extension(config: Config, source: Path) -> int:
    source = source.expanduser()
    if not source.exists():
        print(f"sluka: {source} was not found.", file=sys.stderr)
        return 2
    target = config.ext_dir
    fresh = target.with_name(target.name + ".new")
    old = target.with_name(target.name + ".old")
    shutil.rmtree(fresh, ignore_errors=True)
    try:
        if source.is_dir():
            folder = source if (source / "manifest.json").is_file() else None
            if folder is None:
                inner = [p for p in source.iterdir() if (p / "manifest.json").is_file()]
                folder = inner[0] if inner else None
            if folder is None:
                raise ConfigError("That folder does not hold a browser extension (no manifest.json in it).")
            print(f"Copying {folder} …", flush=True)
            shutil.copytree(folder, fresh, symlinks=False)
        else:
            print(f"Unpacking {source.name} …", flush=True)
            fresh.mkdir(parents=True)
            _unpack(source, fresh)
        manifest = json.loads((fresh / "manifest.json").read_text(encoding="utf-8"))
        if manifest.get("manifest_version") != 3 or not manifest.get("background"):
            raise ConfigError("This does not look like the Sluka extension (Chrome edition, manifest version 3).")
        if manifest.get("browser_specific_settings", {}).get("gecko"):
            print("Note: this is the Firefox edition. It should work, but the Chrome edition is the one this app is tested with.")
    except (ConfigError, zipfile.BadZipFile, OSError, ValueError) as err:
        shutil.rmtree(fresh, ignore_errors=True)
        print(f"sluka: {err}", file=sys.stderr)
        return 1
    shutil.rmtree(old, ignore_errors=True)
    try:
        if target.exists():
            target.rename(old)
        fresh.rename(target)
    except OSError as err:
        # Windows will not move a folder a running program has files open in.
        print(f"sluka: the Sluka that is installed could not be replaced ({err}).\n"
              "Close Sluka Desktop (and Anki, if Sluka is in it), then run this again.", file=sys.stderr)
        if not target.exists() and old.exists():
            try:
                old.rename(target)
            except OSError:
                pass
        shutil.rmtree(fresh, ignore_errors=True)
        return 1
    shutil.rmtree(old, ignore_errors=True)
    print(f"Sluka {manifest.get('version', '?')} is in {target}")
    print(f"Start the app with:  {SLUKA}")
    return 0


DESKTOP_ENTRY = """[Desktop Entry]
Type=Application
Name=Sluka
GenericName=Language learning
Comment=Read and watch with new words lit up
Exec=sh {launcher}
Icon={icon}
Terminal=false
Categories=Education;Languages;
StartupWMClass=sluka-desktop
"""

MPV_STUB = """-- Loads Sluka's mpv script from the app folder, so that it is always the app's own version.
dofile([==[{path}]==])
"""

WINDOWS_NOTE = """-- Sluka's mpv script, copied here by Sluka Desktop ({root}).
-- The app writes it again at every start, so that it is always the app's own
-- version.  Changes made here are lost.

"""

FLATPAK_NOTE = """-- Sluka's mpv script, copied here by Sluka Desktop ({root}).
-- This player is a Flatpak and cannot read the app folder, so it has a copy of
-- its own; the app writes it again at every start.  Changes made here are lost.

"""


def _write(path: Path, text: str, quiet: bool = False) -> bool:
    """``text`` in ``path``; true when the file now holds it."""
    try:
        if path.is_file() and not path.is_symlink() and path.read_text(encoding="utf-8") == text:
            return True
    except (OSError, UnicodeDecodeError):
        pass
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return True
    except OSError as err:
        if not quiet:
            print(f"  could not write {path}: {err}")
        return False


def hook_players(config: Config, quiet: bool = False) -> list[Path]:
    """Put Sluka's script where mpv and Celluloid look for scripts; the files that hold it now.

    Run at every start of the app unless ``[mpv] attach`` is off: on Tails the
    home folder is new at every restart.
    """
    from .mpvbridge import FLATPAK_PLAYERS, flatpak_installed

    script = config.mpv_dir / "sluka.lua"
    if not script.is_file():
        if not quiet:
            print(f"  the mpv script is missing: {script}")
        return []
    home = Path.home()
    if WINDOWS:
        return _hook_windows_players(config, script, quiet)
    stub = MPV_STUB.format(path=str(script))
    jobs = [(home / ".config/mpv/scripts/sluka.lua", stub), (home / ".config/celluloid/scripts/sluka.lua", stub)]
    try:
        whole = FLATPAK_NOTE.format(root=config.root) + script.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        whole = ""
    for app, where in FLATPAK_PLAYERS.items():
        # A sandboxed player reads no folder but its own, so it is given the script itself.
        if whole and flatpak_installed(app):
            jobs.append((home / ".var/app" / app / where / "sluka.lua", whole))
    done = []
    for path, text in jobs:
        if path.is_symlink():
            done.append(path)  # linked from Tails' Dotfiles folder: already the stub
            continue
        if _write(path, text, quiet):
            done.append(path)
    return done


def windows_script_folders(config: Config, env=None, isdir=os.path.isdir) -> list[Path]:
    """Every "scripts" folder an mpv on this Windows may read: its own place, mpv.net's, and those named in config.ini."""
    env = os.environ if env is None else env
    found: list[Path] = []
    if env.get("MPV_HOME"):
        found.append(Path(env["MPV_HOME"]) / "scripts")
    appdata = env.get("APPDATA")
    if appdata:
        # mpv's own place.  It is made if it is not there: an mpv that has never been given settings has none yet.
        found.append(Path(appdata) / "mpv" / "scripts")
        if isdir(os.path.join(appdata, "mpv.net")):
            found.append(Path(appdata) / "mpv.net" / "scripts")
    # An mpv that keeps its settings beside itself (a folder "portable_config": Scoop's does) reads those and no others.
    from .mpvbridge import windows_players

    for player in windows_players(config, env=env):
        if isdir(os.path.join(os.path.dirname(player), "portable_config")):
            found.append(Path(os.path.dirname(player)) / "portable_config" / "scripts")
    found += list(config.mpv_scripts)
    unique: list[Path] = []
    for folder in found:
        if os.path.normcase(str(folder)) not in [os.path.normcase(str(u)) for u in unique]:
            unique.append(folder)
    return unique


def _hook_windows_players(config: Config, script: Path, quiet: bool) -> list[Path]:
    """Windows: the script itself, written into every place found, so that no player has to read the app's folder."""
    try:
        whole = WINDOWS_NOTE.format(root=config.root) + script.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return []
    placed = [folder / "sluka.lua" for folder in windows_script_folders(config) if _write(folder / "sluka.lua", whole, quiet)]
    seen = [path for path in placed if not kept_private(path)]
    if len(seen) < len(placed):
        text = PRIVATE_COPY.format(what="Sluka's script for mpv", who="mpv")
        import logging

        logging.getLogger("sluka").warning("%s", text.replace("\n", " "))
        if not quiet:
            print(text)
    return seen


def mpv_scripts_folder(given: Path) -> tuple[Path | None, str]:
    """From a folder the user named, the "scripts" folder to use and the mpv.exe beside it, if there is one."""
    given = given.expanduser()
    if given.is_file():
        given = given.parent
    player = next((str(given / name) for name in ("mpv.exe", "mpvnet.exe") if (given / name).is_file()), "")
    if given.name.lower() == "scripts":
        return given, ""
    if (given / "portable_config").is_dir():
        return given / "portable_config" / "scripts", player
    if given.name.lower() == "portable_config" or (given / "mpv.conf").is_file() or (given / "scripts").is_dir() or (given / "input.conf").is_file():
        return given / "scripts", player
    return None, player


def install_mpv(config: Config, where: str) -> int:
    """``sluka install-mpv FOLDER``: one more place the mpv script is put, and remembered."""
    folder, player = mpv_scripts_folder(Path(where)) if where else (None, "")
    if where and folder is None and not player:
        print(f"sluka: {where} does not look like mpv's folder.\n"
              "Name the folder mpv.exe is in, or the folder of its settings (the one that holds mpv.conf or \"scripts\").", file=sys.stderr)
        return 2
    if player:
        config.set_option("mpv", "player", player)
        config.mpv_player = player
        print(f"  config.ini: [mpv] player = {player}")
    if folder is not None:
        known = [str(f) for f in config.mpv_scripts]
        if os.path.normcase(str(folder)) not in [os.path.normcase(k) for k in known]:
            known.append(str(folder))
            config.set_option("mpv", "scripts", ";".join(known))
            config.mpv_scripts = [Path(k) for k in known]
            print(f"  config.ini: [mpv] scripts = {';'.join(known)}")
    elif where:
        print("  This mpv keeps no settings beside itself (no portable_config folder), so it reads the usual place,\n"
              "  where the script already goes.")
    placed = hook_players(config)
    for path in placed:
        print(f"  Sluka's script is in {path}")
    if not placed:
        print("sluka: the script could not be put anywhere.", file=sys.stderr)
        return 1
    print("With Sluka Desktop running, any video opened in mpv from now on has Sluka in it.")
    return 0


def shell_folder(which: str) -> Path | None:
    """Windows' own folder for the desktop ("desktop") or the Start menu's programs ("programs"), wherever it was moved
    (OneDrive keeps the desktop elsewhere, say)."""
    if not WINDOWS:
        return None
    import ctypes

    buffer = ctypes.create_unicode_buffer(32768)
    code = {"desktop": 0x0010, "programs": 0x0002}[which]  # CSIDL_DESKTOPDIRECTORY, CSIDL_PROGRAMS
    try:
        if ctypes.windll.shell32.SHGetFolderPathW(None, code, None, 0, buffer) != 0:
            return None
    except (OSError, AttributeError):
        return None
    return Path(buffer.value) if buffer.value else None


def shortcut_leads_to(path: Path, root: Path) -> bool:
    """Whether a shortcut (.lnk) starts the app in this folder: the folder is in it (Windows writes a shortcut's paths
    and arguments in UTF-16; an old one, in the system's code page)."""
    try:
        data = path.read_bytes()
    except OSError:
        return False
    sep = "\\" if WINDOWS else "/"
    want = str(root).rstrip("\\/") + sep  # (with the separator: "Sluka Desktop 2" is another folder)
    folded = data.lower()  # (the ASCII letters of UTF-16 made lower case: enough for the case Windows ignores)
    for text in (want, want.lower()):
        wide = text.encode("utf-16-le")
        if wide in data or wide in folded:
            return True
        try:
            narrow = text.encode("mbcs" if WINDOWS else "utf-8")
        except (LookupError, UnicodeEncodeError):
            continue
        if narrow in data or narrow in folded:
            return True
    return False


def _install_menu_windows(config: Config, desktop: bool = True, start_menu: bool = True) -> int:
    """Shortcuts on the desktop and in the Start menu, made by Windows' own script host.

    They start the app with Python's windowless program, so no console window shows, with Sluka's icon,
    and they carry the name the app's windows go by in the taskbar: pinned, the shortcut and the running
    app are one button.
    """
    import subprocess

    from .iconfile import ensure_icon
    from .winshell import APP_USER_MODEL_ID

    try:
        icon = ensure_icon(config)
    except Exception:
        icon = None
    windowless = Path(sys.executable).with_name("pythonw.exe")
    entry = config.app_dir / "run.py"
    if windowless.is_file() and entry.is_file():
        target, arguments, style = windowless, f'-I "{entry}"', 1
    else:  # a Python without its windowless program: through the launcher, its console minimised
        target, arguments, style = config.root / "Sluka.cmd", "", 7
    quote = lambda text: "'" + str(text).replace("'", "''") + "'"  # noqa: E731
    places = ", ".join(f"[Environment]::GetFolderPath('{name}')" for name, wanted in (("Desktop", desktop), ("Programs", start_menu))
                       if wanted)
    if not places:
        return 0
    script = (
        "$w = New-Object -ComObject WScript.Shell; "
        f"foreach ($d in @({places})) {{ "
        "$p = Join-Path $d 'Sluka.lnk'; $s = $w.CreateShortcut($p); "
        f"$s.TargetPath = {quote(target)}; $s.Arguments = {quote(arguments)}; $s.WorkingDirectory = {quote(config.root)}; "
        + (f"$s.IconLocation = {quote(str(icon) + ',0')}; " if icon else "")
        + f"$s.WindowStyle = {style}; $s.Description = 'Sluka Desktop'; $s.Save(); Write-Output $p }}"
    )
    try:
        done = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script],
                              capture_output=True, text=True, timeout=60)
        made = [line.strip() for line in (done.stdout or "").splitlines() if line.strip().lower().endswith(".lnk")]
    except (OSError, subprocess.SubprocessError):
        made = []
    for path in made:
        print(f"  made {path}")
        try:
            if not set_shortcut_app_id(path, APP_USER_MODEL_ID):
                print("    (without the taskbar's name for the app: pinned, it and the open app are two buttons)")
        except Exception as err:  # the shortcut works without it
            print(f"    (the taskbar's name for the app could not be added: {err})")
    if not made:
        print("No shortcut could be made by itself. By hand: right-click Sluka.cmd in the app folder,\n"
              "\"Show more options\", \"Send to\", \"Desktop (create shortcut)\".")
        return 1
    return 0


def set_shortcut_app_id(path: str, app_id: str) -> bool:
    """Give a shortcut the AppUserModelID the app's windows have (System.AppUserModel.ID), with the shell's
    own objects: IShellLinkW, IPersistFile and IPropertyStore."""
    import ctypes
    from ctypes import POINTER, Structure, byref, c_uint32, c_ushort, c_void_p, c_wchar_p

    from . import com

    class PROPERTYKEY(Structure):
        _fields_ = [("fmtid", com.GUID), ("pid", c_uint32)]

    class PROPVARIANT(Structure):
        _fields_ = [("vt", c_ushort), ("r1", c_ushort), ("r2", c_ushort), ("r3", c_ushort),
                    ("pointer", c_void_p), ("rest", c_void_p)]

    ole32 = ctypes.WinDLL("ole32")
    ole32.CoInitializeEx.restype, ole32.CoInitializeEx.argtypes = com.HRESULT, [c_void_p, c_uint32]
    ole32.CoInitializeEx(None, 0x2)
    create = ole32.CoCreateInstance
    create.restype = com.HRESULT
    create.argtypes = [POINTER(com.GUID), c_void_p, c_uint32, POINTER(com.GUID), POINTER(c_void_p)]
    out = c_void_p()
    hr = create(byref(com.GUID.parse("{00021401-0000-0000-c000-000000000046}")), None, 1,  # CLSID_ShellLink, in-process
                byref(com.GUID.parse("{000214f9-0000-0000-c000-000000000046}")), byref(out))  # IShellLinkW
    if hr < 0 or not out.value:
        return False
    link = com.Interface(out.value)
    persist = store = None
    try:
        persist = link.query("{0000010b-0000-0000-c000-000000000046}")  # IPersistFile
        store = link.query("{886d8eeb-8cf2-4446-8d02-cdba1dbdcf99}")  # IPropertyStore
        if persist is None or store is None:
            return False
        persist.call(5, (c_wchar_p, c_uint32), path, 0x2, what="IPersistFile.Load")  # STGM_READWRITE
        key = PROPERTYKEY(com.GUID.parse("{9f4c2855-9f79-4b39-a8d0-e1d42de1d5f3}"), 5)  # PKEY_AppUserModel_ID
        text = ctypes.create_unicode_buffer(app_id)
        value = PROPVARIANT(31, 0, 0, 0, ctypes.addressof(text), None)  # VT_LPWSTR
        store.call(6, (POINTER(PROPERTYKEY), POINTER(PROPVARIANT)), byref(key), byref(value), what="IPropertyStore.SetValue")
        store.call(7, (), what="IPropertyStore.Commit")
        persist.call(6, (c_wchar_p, ctypes.c_int), path, 1, what="IPersistFile.Save")
        return True
    finally:
        for item in (store, persist, link):
            if item is not None:
                item.release()


def remove_shortcuts(config: Config, desktop: bool = True, start_menu: bool = True) -> list[Path]:
    """The shortcuts install-menu made for this app (Sluka.lnk on the desktop, in the Start menu), taken away; those of
    another copy of the app are left."""
    gone = []
    for which, wanted in (("desktop", desktop), ("programs", start_menu)):
        folder = shell_folder(which) if wanted else None
        path = folder / "Sluka.lnk" if folder else None
        if path is not None and path.is_file() and shortcut_leads_to(path, config.root):
            try:
                path.unlink()
                gone.append(path)
            except OSError as err:
                print(f"  could not take away {path}: {err}")
    return gone


def remove_from_pc(config: Config) -> int:
    """``sluka remove-from-pc``: what the app put outside its own folder, taken away -- before the folder itself goes
    (the setup's Uninstall does this).  Its shortcuts, its add-on in Anki, its script for mpv and the font copies
    beside it.  What another copy of the app put there (its shortcuts, an add-on leading to its extension, its
    script) is left to that copy."""
    for path in remove_shortcuts(config):
        print(f"  took away {path}")
    listed = {os.path.normcase(str(anki_addon_folder(f) or f)) for f in config.anki_addons}
    seen = set()
    for folder in list(config.anki_addons) + [base / "addons21" / ANKI_ADDON for base in anki_bases()]:
        target = anki_addon_folder(folder) or folder
        key = os.path.normcase(str(target))
        if key in seen or target.name != ANKI_ADDON or not (target / "__init__.py").is_file():
            continue
        seen.add(key)
        try:
            if "Sluka Desktop" not in (target / "__init__.py").read_text(encoding="utf-8", errors="replace"):
                continue  # (another add-on of that name)
            ext = target / "ext"
            linked = _is_link(ext)
            # Whose it is: where its link to Sluka's files leads; a copy of them (or a link to nowhere), the copy of
            # the app whose config.ini names it.
            ours = _leads_to(ext, config.ext_dir) if linked and ext.exists() else key in listed
            if not ours:
                continue
            if linked:
                _remove_link(ext)  # (first: what it leads to stays as it is)
            shutil.rmtree(target)
            print(f"  took Sluka's add-on out of Anki: {target}")
        except OSError as err:
            print(f"  could not take Sluka's add-on out of {target} (close Anki first): {err}")
    if WINDOWS:
        note = WINDOWS_NOTE.format(root=config.root).splitlines()[0]
        for folder in windows_script_folders(config):
            script = folder / "sluka.lua"
            try:
                if script.is_file() and script.read_text(encoding="utf-8", errors="replace").splitlines()[:1] == [note]:
                    script.unlink()
                    print(f"  took Sluka's script away from mpv: {script}")
            except (OSError, IndexError):
                pass
            if script.exists():
                continue  # (another copy's: the fonts beside it are its too)
            fonts = folder.parent / "fonts"
            gone = 0
            for font in sorted(fonts.glob("Sluka-*.ttf")) if fonts.is_dir() else []:
                try:
                    font.unlink()
                    gone += 1
                except OSError:
                    pass
            if gone:
                print(f"  took Sluka's {gone} font copies away from {fonts}")
    return 0


def install_menu(config: Config, with_mpv: bool = False, desktop: bool = True, start_menu: bool = True) -> int:
    if WINDOWS:
        code = _install_menu_windows(config, desktop=desktop, start_menu=start_menu)
        if with_mpv:
            for path in hook_players(config):
                print(f"  Sluka's script is in {path}")
        return code
    launcher = config.root / "sluka"
    icon = config.ext_dir / "icons" / "icon-128.png"
    entry = DESKTOP_ENTRY.format(launcher=_quote(str(launcher)), icon=str(icon) if icon.is_file() else "applications-education")
    home = Path.home()
    wrote = []
    targets = [home / ".local/share/applications/sluka-desktop.desktop"]
    on_tails = TAILS_DOTFILES.is_dir()
    if on_tails:
        # Tails links every file of the Dotfiles folder into the home folder at each start.
        targets.append(TAILS_DOTFILES / ".local/share/applications/sluka-desktop.desktop")
    for path in targets:
        if _write(path, entry):
            wrote.append(path)
    if with_mpv:
        wrote += hook_players(config)
        config.bring_up_to_date()
        if config.set_option("mpv", "attach", "yes"):
            print("  config.ini: [mpv] attach = yes  (the script is put back at every start of the app)")
        if on_tails:
            # With these, a video opened before the app is started is seen as well, once the app is up.
            script = config.mpv_dir / "sluka.lua"
            for where in (".config/mpv/scripts/sluka.lua", ".config/celluloid/scripts/sluka.lua"):
                if _write(TAILS_DOTFILES / where, MPV_STUB.format(path=str(script))):
                    wrote.append(TAILS_DOTFILES / where)
    for path in wrote:
        print(f"  wrote {path}")
    if on_tails:
        print("The Dotfiles folder was found, so the menu entry will be there after a restart too.")
    elif Path("/etc/amnesia").exists():
        print("On Tails the menu entry is gone after a restart unless the Dotfiles feature of the")
        print("Persistent Storage is on. Turn it on, then run this command once more.")
    if with_mpv:
        print("Any video opened in mpv or Celluloid gets Sluka's subtitles while the app is running.")
    return 0 if wrote else 1


def _quote(path: str) -> str:
    """A path as one argument of a desktop entry's Exec line."""
    for char in ("\\", '"', "`", "$"):
        path = path.replace(char, "\\" + char)
    return '"' + path.replace("%", "%%") + '"'


# ---------------------------------------------------------------------- Anki

#: Where Anki keeps its things, as it comes from its own site and as a Flatpak.
ANKI_BASES = ("~/.local/share/Anki2", "~/.var/app/net.ankiweb.Anki/data/Anki2")


def anki_bases() -> list[Path]:
    """The usual places of Anki's own folder on this system."""
    if WINDOWS:
        roaming = os.environ.get("APPDATA")
        return [Path(roaming) / "Anki2"] if roaming else []
    return [Path(base).expanduser() for base in ANKI_BASES]
ANKI_ADDON = "sluka_desktop"
#: What of Sluka's own files its page script may fetch (the extension's web_accessible_resources).
ANKI_SHARES = ("manifest.json", "lib", "content", "data", "vendor/readability", "vendor/opencc",
               "books/pager.js", "books/page-layout.js", "books/chrome-vars.js")


def _same(a: Path, b: Path) -> bool:
    try:
        return a.read_bytes() == b.read_bytes()
    except OSError:
        return False


def _copy_if_other(src: Path, dest: Path) -> bool:
    if dest.is_file() and _same(src, dest):
        return False
    dest.parent.mkdir(parents=True, exist_ok=True)
    partial = dest.with_name(dest.name + ".new")
    shutil.copyfile(src, partial)
    os.replace(partial, dest)
    return True


def _mirror(src: Path, dest: Path) -> int:
    """``src`` (a file or a folder) copied to ``dest``, leaving alone what is already there with the same size and time."""
    copied = 0
    if src.is_file():
        pairs = [(src, dest)]
    else:
        pairs = [(Path(root) / name, dest / os.path.relpath(os.path.join(root, name), src))
                 for root, _dirs, names in os.walk(src) for name in names]
    for a, b in pairs:
        try:
            sa = a.stat()
            sb = b.stat() if b.exists() else None
            if sb and sb.st_size == sa.st_size and int(sb.st_mtime) == int(sa.st_mtime):
                continue
            b.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(a, b)
            copied += 1
        except OSError:
            continue
    return copied


def _is_link(path: Path) -> bool:
    """A symbolic link -- or, on Windows, a junction: a folder that is another folder."""
    if path.is_symlink():
        return True
    junction = getattr(os.path, "isjunction", None)
    try:
        if junction is not None and junction(path):
            return True
        # Python before 3.12 does not know a junction when it sees one.  Windows marks it, as it marks every
        # folder that stands for something else (FILE_ATTRIBUTE_REPARSE_POINT), whether or not what it leads
        # to is still there.
        return bool(getattr(os.lstat(path), "st_file_attributes", 0) & 0x400)
    except OSError:
        pass
    return False


def _leads_to(link: Path, want: Path) -> bool:
    try:
        return os.path.normcase(os.path.realpath(link)) == os.path.normcase(os.path.realpath(want))
    except OSError:
        return False


def _remove_link(link: Path) -> None:
    try:
        os.unlink(link)
    except OSError:
        os.rmdir(link)  # a junction is taken away as a folder is; what it leads to stays


def _make_link(want: Path, link: Path) -> str:
    """A way from ``link`` to the folder ``want``; how it was made.  Raises OSError if this system makes none."""
    if not WINDOWS:
        os.symlink(str(want), link)
        return "link"
    try:
        os.symlink(str(want), link, target_is_directory=True)
        return "link"
    except (OSError, NotImplementedError):
        pass  # Windows keeps symbolic links for administrators; a junction needs no such leave
    try:
        import _winapi

        _winapi.CreateJunction(str(want), str(link))
    except (ImportError, AttributeError) as err:
        raise OSError(f"this Python makes no junctions ({err})") from err
    return "junction"


def _real(folder: Path) -> Path:
    """
    Where a folder really is.  On Tails, Anki's usual folder is often a link into the Persistent
    Storage that somebody puts back after each restart: the place it points to is the one that lasts,
    and the one to remember.
    """
    try:
        return folder.resolve()
    except (OSError, RuntimeError):
        return folder


def anki_addon_folder(given: Path) -> Path | None:
    """The folder this app's add-on goes into, from what was named: Anki's own folder, its addons21, or the add-on's."""
    given = given.expanduser()
    if given.name == ANKI_ADDON and given.parent.name == "addons21":
        return _real(given.parent) / ANKI_ADDON
    if given.name == "addons21":
        return _real(given) / ANKI_ADDON
    if (given / "addons21").is_dir() or (given / "prefs21.db").exists():
        return _real(given / "addons21") / ANKI_ADDON
    return None


def put_anki_addon(config: Config, target: Path) -> tuple[list[str], str]:
    """The add-on, the app's two scripts and the way to Sluka's files, put into ``target``: ``(what changed, problem)``."""
    changed: list[str] = []
    source = config.anki_dir / ANKI_ADDON
    if not (source / "__init__.py").is_file():
        return changed, f"this copy of the app has no add-on in it ({source})"
    try:
        target.mkdir(parents=True, exist_ok=True)
        for name in ("__init__.py", "manifest.json", "config.json", "config.md", "LICENSE.txt"):
            if (source / name).is_file() and _copy_if_other(source / name, target / name):
                changed.append(name)
        for name in ("shim.js", "anki-page.js"):
            if _copy_if_other(config.web_dir / name, target / "web" / name):
                changed.append(f"web/{name}")
    except OSError as err:
        return changed, f"could not write to {target}: {err}"

    # Sluka's own files: a link to where the app keeps them.  An Anki in a sandbox cannot follow a link
    # out of it, so there they are copied, which takes the room of the extension once more; so they are
    # where that was asked for ([anki] copy), and where a copy already is.
    ext = target / "ext"
    sandboxed = ".var/app/" in str(target).replace("\\", "/")
    linked = _is_link(ext)
    copying = sandboxed or config.anki_copy or (ext.is_dir() and not linked)
    why = ": this Anki is a Flatpak and cannot follow a link out of its sandbox" if sandboxed else ""
    if not config.extension_present():
        return changed, f"no Sluka extension is installed yet ({SLUKA} install-extension ZIP), so there is nothing for Anki to show"
    try:
        if not copying and not (linked and _leads_to(ext, config.ext_dir)):
            if linked:
                _remove_link(ext)
            if not ext.exists():
                try:
                    _make_link(config.ext_dir, ext)
                    changed.append(f"ext -> {config.ext_dir}")
                except OSError as err:
                    if not WINDOWS:
                        raise
                    # No link and no junction to be had (another disk, a network folder): the files themselves, then.
                    copying, why = True, f": Windows would make no link from there ({err})"
        if copying:
            if _is_link(ext):
                _remove_link(ext)
            copied = sum(_mirror(config.ext_dir / share, ext / share) for share in ANKI_SHARES if (config.ext_dir / share).exists())
            if copied:
                changed.append(f"ext/ ({copied} files copied{why})")
    except OSError as err:
        return changed, f"could not link Sluka's files into {target}: {err}"
    return changed, ""


def refresh_anki(config: Config) -> list[str]:
    """At each start of the app: the add-on kept in step with it, wherever it was put.  What was done, for the log."""
    said = []
    for folder in config.anki_addons:
        if not folder.parent.parent.is_dir():
            # Anki's folder is not there now (another disk, a Tails without its Persistent): nothing to keep up,
            # and nothing to make -- a folder made here would be in the way of the real one.
            continue
        changed, problem = put_anki_addon(config, folder)
        if problem:
            said.append(f"Anki add-on in {folder}: {problem}")
        elif changed:
            said.append(f"Anki add-on in {folder} brought up to date ({', '.join(changed)}): restart Anki to use it")
    return said


def install_anki(config: Config, where: str = "", copy: bool = False) -> int:
    """Put this app's add-on into Anki, and remember where."""
    if copy and not config.anki_copy:
        config.set_option("anki", "copy", "yes")
        config.anki_copy = True
    candidates: list[Path] = []
    if where:
        folder = anki_addon_folder(Path(where))
        if folder is None:
            print(f"sluka: {where} is not Anki's folder.\n"
                  "Name the folder that holds Anki's \"addons21\" folder, or addons21 itself (in Anki, Tools >\n"
                  "Add-ons > View Files opens addons21), for example:\n"
                  f"    {SLUKA} install-anki " + ("%APPDATA%\\Anki2" if WINDOWS else "~/.local/share/Anki2"), file=sys.stderr)
            return 2
        candidates = [folder]
    else:
        for folder in anki_bases():
            if folder.is_dir():
                candidates.append(_real(folder / "addons21") / ANKI_ADDON)
        if not candidates:
            print("sluka: Anki's folder was not found in the usual places (" + ", ".join(str(b) for b in anki_bases()) + ").\n"
                  "Name it: the folder that holds \"addons21\", or addons21 itself (in Anki, Tools > Add-ons >\n"
                  "View Files opens addons21):\n"
                  f"    {SLUKA} install-anki " + ("C:\\path\\to\\Anki2" if WINDOWS else "/path/to/Anki2"), file=sys.stderr)
            return 2

    worst = 0
    known = [str(p) for p in config.anki_addons]
    for folder in candidates:
        changed, problem = put_anki_addon(config, folder)
        if problem:
            print(f"sluka: {problem}", file=sys.stderr)
            worst = 1
            if not (folder / "__init__.py").is_file():
                continue
        if kept_private(folder / "__init__.py"):
            print("sluka: " + PRIVATE_COPY.format(what="the add-on", who="Anki"), file=sys.stderr)
            worst = 1
            continue
        print(f"Sluka's add-on is in {folder}")
        for item in changed:
            print(f"  {item}")
        if str(folder) not in known:
            known.append(str(folder))
    if known != [str(p) for p in config.anki_addons]:
        config.set_option("anki", "addons", " ; ".join(known))
    if worst == 0 or known:
        print("\nNow restart Anki.  With Sluka Desktop running, the words of your cards are Sluka's while you review:\n"
              "point at one for its card, click it for its panel.  Without the app, Anki is as it always is.")
        if Path("/etc/amnesia").exists() and any(not k.startswith(str(Path.home() / "Persistent")) and not Path(k).resolve().as_posix().startswith("/live/persistence") for k in known):
            print("\nOn Tails: this only lasts if Anki's own folder does.  If your Anki keeps its things in the\n"
                  "Persistent folder (anki -b ~/Persistent/Anki2), name that folder:  ./sluka install-anki ~/Persistent/Anki2")
    return worst
