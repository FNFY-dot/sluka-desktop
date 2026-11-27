"""The Windows shortcuts install-menu makes (the script given to PowerShell)."""

import subprocess
import sys
from pathlib import Path

import fakes  # noqa: F401

from sluka_desktop import install
from sluka_desktop.config import Config


def test_shortcut_script(tmp_path, monkeypatch):
    config = Config(root=tmp_path, data=tmp_path / "data")
    (tmp_path / "Sluka.cmd").write_text("@echo off\n")
    python = tmp_path / "Python314" / "python.exe"
    python.parent.mkdir()
    python.write_text("")
    (python.parent / "pythonw.exe").write_text("")
    monkeypatch.setattr(sys, "executable", str(python))
    monkeypatch.setattr("sluka_desktop.iconfile.ensure_icon", lambda config: tmp_path / "data" / "sluka.ico")
    seen = {}

    def run(command, **kw):
        seen["command"] = command
        return subprocess.CompletedProcess(command, 0, stdout="C:\\Users\\u\\Desktop\\Sluka.lnk\r\n", stderr="")

    monkeypatch.setattr(subprocess, "run", run)
    named = []
    monkeypatch.setattr(install, "set_shortcut_app_id", lambda path, app_id: named.append((path, app_id)) or True)
    assert install._install_menu_windows(config) == 0
    script = seen["command"][-1]
    print(script)
    assert f"$s.TargetPath = '{python.parent / 'pythonw.exe'}'" in script
    assert f"$s.Arguments = '-I \"{config.app_dir / 'run.py'}\"'" in script
    assert f"$s.IconLocation = '{tmp_path / 'data' / 'sluka.ico'},0'" in script
    assert "$s.WindowStyle = 1;" in script and script.rstrip().endswith("}")
    assert named == [("C:\\Users\\u\\Desktop\\Sluka.lnk", "SlukaDesktop.Sluka")]


def test_shortcut_places_asked_for(tmp_path, monkeypatch):
    """install-menu --no-desktop / --no-start-menu: shortcuts only where wanted, and the app's own one taken away from
    the other place."""
    from sluka_desktop import __main__ as main

    config_root = tmp_path / "Sluka Desktop"
    (config_root / "app").mkdir(parents=True)
    made, gone = [], []
    monkeypatch.setattr(main, "WINDOWS", True)
    monkeypatch.setattr(install, "WINDOWS", True)
    monkeypatch.setattr(install, "_install_menu_windows", lambda config, desktop=True, start_menu=True: made.append((desktop, start_menu)) or 0)
    monkeypatch.setattr(install, "remove_shortcuts", lambda config, desktop=True, start_menu=True: gone.append((desktop, start_menu)) or [])
    assert main._main(["--root", str(config_root), "install-menu", "--no-desktop"]) == 0
    assert main._main(["--root", str(config_root), "install-menu", "--no-start-menu"]) == 0
    assert main._main(["--root", str(config_root), "install-menu"]) == 0
    assert main._main(["--root", str(config_root), "install-menu", "--no-desktop", "--no-start-menu"]) == 0
    assert made == [(False, True), (True, False), (True, True), (False, False)]
    assert gone == [(True, False), (False, True), (True, True)]


def test_shortcut_script_for_one_place(tmp_path, monkeypatch):
    config = Config(root=tmp_path, data=tmp_path / "data")
    monkeypatch.setattr("sluka_desktop.iconfile.ensure_icon", lambda config: None)
    seen = []
    monkeypatch.setattr(subprocess, "run", lambda command, **kw: seen.append(command[-1]) or subprocess.CompletedProcess(command, 0, stdout="", stderr=""))
    install._install_menu_windows(config, desktop=False, start_menu=True)
    assert "GetFolderPath('Programs')" in seen[0] and "Desktop" not in seen[0].split("foreach")[1].split("{")[0]
    seen.clear()
    assert install._install_menu_windows(config, desktop=False, start_menu=False) == 0 and seen == []


def lnk(root, sep="\\"):
    """A stand-in for a shortcut: its paths in UTF-16, as Windows writes them."""
    return b"L\x00\x00\x00" + f'pythonw.exe\x00-I "{root}{sep}app{sep}run.py"\x00{root}'.encode("utf-16-le")


def test_remove_from_pc(tmp_path, monkeypatch):
    """What the app put outside its folder taken away, and what another copy of the app put there left alone."""
    import json
    import os

    root = tmp_path / "Sluka Desktop"
    other = tmp_path / "Sluka Desktop 2"
    for folder in (root, other):
        (folder / "extension").mkdir(parents=True)
        (folder / "extension" / "manifest.json").write_text(json.dumps({"manifest_version": 3, "version": "0.7.4"}))
    # Anki: the add-on linked to this copy's extension; one linked to the other copy's; a copied one this copy's
    # config.ini names; another add-on of the same name.
    def addon(base, ext=None, text="Sluka Desktop's add-on"):
        folder = tmp_path / base / "addons21" / "sluka_desktop"
        folder.mkdir(parents=True)
        (folder / "__init__.py").write_text(f'"""{text}"""\n')
        if ext is None:
            (folder / "ext").mkdir()
            (folder / "ext" / "manifest.json").write_text("{}")
        else:
            os.symlink(ext, folder / "ext")
        return folder

    mine = addon("Anki2", root / "extension")
    theirs = addon("Anki2-b", other / "extension")
    copied = addon("Anki2-c")
    stranger = addon("Anki2-d", text="Someone else's add-on")
    (root / "config.ini").write_text(f"[anki]\naddons = {mine} ; {copied} ; {stranger}\n")
    config = Config(root=root, data=root / "data")
    monkeypatch.setattr(install, "anki_bases", lambda: [tmp_path / "Anki2", tmp_path / "Anki2-b"])
    # Windows' places: the shortcuts, mpv's scripts folders and the font copies beside them.
    monkeypatch.setattr(install, "WINDOWS", True)
    places = {"desktop": tmp_path / "Desktop", "programs": tmp_path / "Programs"}
    for folder in places.values():
        folder.mkdir()
    (places["desktop"] / "Sluka.lnk").write_bytes(lnk(root))
    (places["programs"] / "Sluka.lnk").write_bytes(lnk(other))
    monkeypatch.setattr(install, "shell_folder", lambda which: places[which])
    scripts = [tmp_path / "mpv" / "scripts", tmp_path / "mpv.net" / "scripts", tmp_path / "portable" / "scripts"]
    monkeypatch.setattr(install, "windows_script_folders", lambda config: scripts)
    notes = [install.WINDOWS_NOTE.format(root=root), install.WINDOWS_NOTE.format(root=other), None]
    for folder, note in zip(scripts, notes):
        (folder.parent / "fonts").mkdir(parents=True)
        (folder.parent / "fonts" / "Sluka-NotoSansJP-700-1a2b.ttf").write_bytes(b"font")
        (folder.parent / "fonts" / "MyFont.ttf").write_bytes(b"mine")
        if note is not None:
            folder.mkdir()
            (folder / "sluka.lua").write_text(note + "-- the script\n")

    assert install.remove_from_pc(config) == 0
    assert not (places["desktop"] / "Sluka.lnk").exists() and (places["programs"] / "Sluka.lnk").is_file()
    assert not mine.exists() and not copied.exists()
    assert theirs.is_dir() and stranger.is_dir()
    assert (root / "extension" / "manifest.json").is_file() and (other / "extension" / "manifest.json").is_file()
    assert not (scripts[0] / "sluka.lua").exists() and (scripts[1] / "sluka.lua").is_file()
    assert [sorted(p.name for p in (f.parent / "fonts").iterdir()) for f in scripts] == [
        ["MyFont.ttf"], ["MyFont.ttf", "Sluka-NotoSansJP-700-1a2b.ttf"], ["MyFont.ttf"]]
