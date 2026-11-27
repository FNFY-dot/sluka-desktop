"""Sluka Desktop's setup (tools/installer, Sluka-Desktop-Setup-<version>.exe): the Windows program itself -- its
icon, manifest and version, the app's files after it -- and its work, done by the same program built for Linux,
which works without its window (--headless), against the real app."""

from __future__ import annotations

import json
import os
import struct
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

APP = Path(os.environ.get("SLUKA_APP", "/home/claude/work/sluka-desktop/app"))
SOURCE = APP.parent
TOOLS = Path(os.environ.get("SLUKA_TOOLS", "/home/claude/tools"))
GO = os.environ.get("GO", "/usr/local/go/bin/go")
sys.path.insert(0, str(TOOLS))

import build_installer  # noqa: E402


def version() -> str:
    return build_installer.version_of(SOURCE)


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    """The setup, built from the app here (or the one named by SLUKA_INSTALLER), and its Linux twin."""
    folder = tmp_path_factory.mktemp("installer")
    exe = folder / f"Sluka-Desktop-Setup-{version()}.exe"
    linux = folder / "slukasetup"
    build_installer.build(exe, SOURCE, linux)
    if os.environ.get("SLUKA_INSTALLER"):
        exe = Path(os.environ["SLUKA_INSTALLER"])
    return exe, linux


# ------------------------------------------------------------------------------------------------ the program


class PE:
    """Just enough of a Windows program's headers: its sections and its resources."""

    def __init__(self, data: bytes):
        self.data = data
        assert data[:2] == b"MZ"
        pe = struct.unpack_from("<I", data, 0x3C)[0]
        assert data[pe:pe + 4] == b"PE\0\0"
        self.machine, nsections, _, _, _, opt_size, _ = struct.unpack_from("<HHIIIHH", data, pe + 4)
        opt = pe + 24
        self.magic = struct.unpack_from("<H", data, opt)[0]
        self.subsystem = struct.unpack_from("<H", data, opt + 68)[0]
        dirs = opt + (112 if self.magic == 0x20B else 96)
        self.res_rva, self.res_size = struct.unpack_from("<II", data, dirs + 8 * 2)
        self.cert_size = struct.unpack_from("<II", data, dirs + 8 * 4)[1]
        self.sections = []
        for i in range(nsections):
            at = opt + opt_size + 40 * i
            name = data[at:at + 8].rstrip(b"\0").decode()
            vsize, va, raw_size, raw_ptr = struct.unpack_from("<IIII", data, at + 8)
            self.sections.append((name, va, vsize, raw_ptr, raw_size))

    @property
    def end(self) -> int:
        return max(ptr + size for _n, _va, _vs, ptr, size in self.sections)

    def offset(self, rva: int) -> int:
        for _name, va, vsize, ptr, size in self.sections:
            if va <= rva < va + max(vsize, size):
                return ptr + rva - va
        raise ValueError(hex(rva))

    def resources(self) -> dict:
        """{type: {name: bytes}} (the first language of each)."""
        base = self.offset(self.res_rva)

        def entries(at):
            named, ids = struct.unpack_from("<HH", self.data, at + 12)
            for i in range(named + ids):
                name, target = struct.unpack_from("<II", self.data, at + 16 + 8 * i)
                yield name, target

        out = {}
        for rtype, t in entries(base):
            assert t & 0x80000000
            for rname, n in entries(base + (t & 0x7FFFFFFF)):
                lang = next(entries(base + (n & 0x7FFFFFFF)))[1] if n & 0x80000000 else n
                rva, size = struct.unpack_from("<II", self.data, base + lang)
                out.setdefault(rtype, {})[rname] = self.data[self.offset(rva):self.offset(rva) + size]
        return out


def test_the_program(built):
    exe, _linux = built
    data = exe.read_bytes()
    pe = PE(data)
    assert pe.machine == 0x8664 and pe.magic == 0x20B and pe.subsystem == 2  # 64-bit, a window (no console)
    res = pe.resources()
    assert {3, 14, 16, 24} <= set(res)  # icons, the icon's group, the version, the manifest
    group = res[14][1]
    count = struct.unpack_from("<HHH", group, 0)[2]
    sizes = sorted(group[6 + 14 * i] or 256 for i in range(count))
    assert sizes == [16, 20, 24, 32, 40, 48, 64, 128, 256]
    manifest = res[24][1].decode("utf-8")
    assert 'level="asInvoker"' in manifest  # (no administrator: it installs for you, where you may write)
    assert 'name="Microsoft.Windows.Common-Controls" version="6.0.0.0"' in manifest  # Windows' own look
    assert "<dpiAware" in manifest and "8e0f7a12-bfb3-4fe8-b9a5-48fd50a15a9a" in manifest  # sharp; Windows 10/11
    info = res[16][1].decode("utf-16-le", "replace")
    assert "Sluka Desktop Setup" in info and version() in info
    # The app's files follow the program: its last section ends where the zip begins.
    with zipfile.ZipFile(exe) as z:
        first = min(i.header_offset for i in z.infolist())
        names = sorted(i.filename for i in z.infolist())
        assert z.testzip() is None
    assert pe.end == first and pe.cert_size == 0
    mine = sorted("sluka-desktop/" + p.relative_to(SOURCE).as_posix() for p in SOURCE.rglob("*")
                  if p.is_file() and "__pycache__" not in p.parts and p.relative_to(SOURCE).parts[0] not in build_installer.SKIP)
    assert names == mine
    assert not any(n.endswith(("Sluka Setup.cmd", "sluka_setup.py")) for n in names)  # (0.10.0's console setup is gone)


def test_go_tests():
    """The setup's own tests (tools/installer/setup_test.go), here with the rest."""
    done = subprocess.run([GO, "test", "-count=1", "./..."], cwd=TOOLS / "installer", capture_output=True, text=True,
                          env={**os.environ, "GOFLAGS": "-mod=mod", "GOPROXY": "off"}, timeout=600)
    assert done.returncode == 0, done.stdout + done.stderr
    vet = subprocess.run([GO, "vet", "./..."], cwd=TOOLS / "installer", capture_output=True, text=True,
                         env={**os.environ, "GOOS": "windows", "GOFLAGS": "-mod=mod", "GOPROXY": "off"}, timeout=600)
    assert vet.returncode == 0, vet.stdout + vet.stderr


# ------------------------------------------------------------------------------------------------ its work


def make_extension(path: Path, version: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("sluka-extension/manifest.json", json.dumps({"manifest_version": 3, "name": "Sluka", "version": version,
                                                                "background": {"service_worker": "background.js"}}))
        z.writestr("sluka-extension/background.js", "// the worker\n")
    return path


class World:
    """A pretend Windows' places, for the Linux twin."""

    def __init__(self, base: Path, linux: Path, exe: Path):
        self.base, self.linux, self.exe = base, linux, exe
        self.home = base / "home"
        for folder in ("home/Downloads", "Desktop", "Start Menu"):
            (base / folder).mkdir(parents=True, exist_ok=True)
        self.default = base / "Programs" / "Sluka Desktop"
        self.state = base / "state.json"
        self.env = {k: v for k, v in os.environ.items() if not k.startswith(("SLUKA", "PYTHON"))}
        self.env.update(HOME=str(self.home), SLUKA_SETUP_DEFAULT=str(self.default), SLUKA_SETUP_DESKTOP=str(base / "Desktop"),
                        SLUKA_SETUP_PROGRAMS=str(base / "Start Menu"), SLUKA_SETUP_DOWNLOADS=str(self.home / "Downloads"),
                        SLUKA_SETUP_STATE=str(self.state), SLUKA_SETUP_LOCAL=str(base / "Local" / "sluka-desktop"),
                        SLUKA_SETUP_PROGRAM_FILES=str(base / "Program Files"), SLUKA_SETUP_PYTHON=sys.executable,
                        SLUKA_SETUP_ANKI="0", SLUKA_SETUP_LATER=str(base / "later.txt"))

    def run(self, *args, code=0):
        done = subprocess.run([str(self.linux), "--headless", *args], capture_output=True, text=True, env=self.env,
                              cwd=self.base, timeout=600)
        print(done.stdout, done.stderr)
        assert done.returncode == code, done.stdout + done.stderr
        return done.stdout

    def registered(self) -> dict:
        return json.loads(self.state.read_text()) if self.state.exists() else {}


def files(root: Path) -> dict:
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()}


def test_its_work_from_end_to_end(built, tmp_path):
    exe, linux = built
    w = World(tmp_path, linux, exe)
    said = w.run("find", "--payload", str(exe))
    assert f"payload: Sluka Desktop {version()}" in said and "python: " + sys.executable in said and "install:" not in said

    # The licence agreement, which installing and updating need accepted (as the window asks first).
    terms = w.run("license")
    assert "SLUKA DESKTOP" in terms and "https://sluka.app/terms" in terms and "GNU General Public License" in terms
    assert "Copyright 2009 The Go Authors." in terms  # (Setup is built with Go, whose licence goes with it)
    # The notices the agreement points to (Microsoft's terms for its runtime files, part of it, among them), after it.
    assert terms.index("SLUKA DESKTOP: LICENCE AGREEMENT") < terms.index("SLUKA DESKTOP: NOTICES") < terms.index("Go Authors")
    assert "As part of Sluka Desktop's licence agreement" in " ".join(terms.split())
    said = w.run("install", "--payload", str(exe), code=2)
    assert "--accept-license" in said and not w.default.exists()

    # Not under Program Files.
    said = w.run("install", "--payload", str(exe), "--folder", str(tmp_path / "Program Files" / "Sluka"), "--accept-license",
                 code=1)
    assert "Not under" in said and not (tmp_path / "Program Files").exists()

    # Installed where it goes by itself, with the extension found in Downloads (as the window offers it).
    ext = make_extension(w.home / "Downloads" / "sluka-extension-0_7_4.zip", "0.7.4")
    said = w.run("install", "--payload", str(exe), "--extension", str(ext), "--no-desktop", "--accept-license")
    root = w.default
    assert f"done: Sluka Desktop {version()} is in {root}." in said
    assert "log: Sluka 0.7.4 is in" in said  # (the app's own install-extension said it)
    assert "done: The Sluka extension 0.7.4 is in it." in said
    assert (root / "extension" / "background.js").is_file() and (root / "app" / "run.py").is_file()
    # The licence agreement and the notices, with the app (and taken away with it: below).
    assert (root / "LICENSE.txt").is_file() and (root / "NOTICES.txt").is_file()
    assert not (root / "THIRD-PARTY-NOTICES.txt").exists()
    assert (root / "LICENSES" / "GPL-3.0.txt").is_file() and (root / "anki" / "sluka_desktop" / "LICENSE.txt").is_file()
    assert not (root / "Sluka Setup.cmd").exists()
    assert (w.home / ".local" / "share" / "applications" / "sluka-desktop.desktop").is_file()  # (the app's install-menu)
    assert "log: > install-menu --no-desktop" in said
    assert (tmp_path / "Start Menu" / "Sluka Desktop Setup.lnk").is_file()
    reg = w.registered()
    assert reg["InstallLocation"] == str(root) and reg["DisplayVersion"] == version() and reg["DisplayName"] == "Sluka Desktop"
    assert reg["UninstallString"] == f'"{root / "Sluka Desktop Setup.exe"}" /uninstall'
    assert reg["EstimatedSize"] > 30000  # KB: the program and the extension, not your data
    assert "warning:" not in said and "error:" not in said

    # Found again, by Windows' list of apps.
    assert f"install: Sluka Desktop {version()}, in {root}, with the Sluka extension 0.7.4" in w.run("find")

    # A newer extension, from a zip.
    newer = make_extension(w.home / "Downloads" / "sluka-extension-0_7_6.zip", "0.7.6")
    said = w.run("zip", "--accept-license", str(newer))
    assert "done: The Sluka extension is updated from 0.7.4 to 0.7.6." in said
    assert json.loads((root / "extension" / "manifest.json").read_text())["version"] == "0.7.6"

    # Your data, and an update from a setup: what is yours stays; the setup's own program goes beside the app.
    (root / "data").mkdir(exist_ok=True)
    (root / "data" / "storage.sqlite").write_bytes(b"your words")
    (root / "config.ini").write_text("[app]\nport = 47999\n")
    (root / "Sluka Setup.cmd").write_text("0.10.0's setup")  # (left by 0.10.0: goes)
    yours = {k: v for k, v in files(root).items() if k.startswith(("data/", "extension/")) or k == "config.ini"}
    said = w.run("zip", "--accept-license", str(exe))
    assert f"done: Sluka Desktop {version()} is installed again, in {root}." in said
    assert {k: v for k, v in files(root).items() if k.startswith(("data/", "extension/")) or k == "config.ini"} == yours
    assert not (root / "Sluka Setup.cmd").exists()
    setup = (root / "Sluka Desktop Setup.exe").read_bytes()
    pe = PE(exe.read_bytes())
    assert setup == exe.read_bytes()[:pe.end]  # the program, without the app's files
    with pytest.raises(zipfile.BadZipFile):
        zipfile.ZipFile(root / "Sluka Desktop Setup.exe")

    # Uninstalled, your data kept; then installed again there, and uninstalled for good.
    said = w.run("uninstall", "--keep-data")
    assert "Your words, books and settings stay in" in said
    assert sorted(files(root)) == ["config.ini", "data/storage.sqlite"]
    assert not w.state.exists() and not (tmp_path / "Start Menu" / "Sluka Desktop Setup.lnk").exists()
    said = w.run("install", "--payload", str(exe), "--folder", str(root), "--no-desktop", "--no-start-menu", "--accept-license")
    assert (root / "data" / "storage.sqlite").read_bytes() == b"your words" and (root / "app" / "run.py").is_file()
    assert "Sluka Desktop has no Sluka extension yet" in said  # (the uninstall took it away)
    w.run("uninstall", "--folder", str(root))
    assert not root.exists() and not w.state.exists()
