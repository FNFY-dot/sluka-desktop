# SPDX-License-Identifier: LicenseRef-Sluka
# Copyright (c) 2026 Sluka. Part of Sluka Desktop; see LICENSE.txt.
"""Sluka Desktop's setup: Sluka-Desktop-Setup-<version>.exe.

A Windows program of its own (Go, tools/installer), with its icon, its manifest (Windows' own look for its controls,
asInvoker: it installs for this user and asks for no administrator) and its version; then Sluka Desktop's files as a
zip after it, which it unpacks.  The same program, built for Linux, does the same work without its window, for the
tests (--headless).

    python build_installer.py OUT.exe [SOURCE_FOLDER] [--linux OUT_LINUX]
"""

import os
import re
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
GO_SRC = HERE / "installer"
GO = shutil.which("go") or "/usr/local/go/bin/go"
#: What a copy of the app has that is not the app's: never in the setup.
SKIP = {"data", "extension", "config.ini", ".setup-new", ".setup-old", "Sluka Desktop Setup.exe"}

MANIFEST = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<assembly xmlns="urn:schemas-microsoft-com:asm.v1" manifestVersion="1.0" xmlns:asmv3="urn:schemas-microsoft-com:asm.v3">
  <assemblyIdentity version="{v4}" processorArchitecture="amd64" name="Sluka.Desktop.Setup" type="win32"/>
  <description>Sluka Desktop Setup</description>
  <dependency>
    <dependentAssembly>
      <assemblyIdentity type="win32" name="Microsoft.Windows.Common-Controls" version="6.0.0.0"
                        processorArchitecture="*" publicKeyToken="6595b64144ccf1df" language="*"/>
    </dependentAssembly>
  </dependency>
  <trustInfo xmlns="urn:schemas-microsoft-com:asm.v3">
    <security>
      <requestedPrivileges>
        <requestedExecutionLevel level="asInvoker" uiAccess="false"/>
      </requestedPrivileges>
    </security>
  </trustInfo>
  <compatibility xmlns="urn:schemas-microsoft-com:compatibility.v1">
    <application>
      <supportedOS Id="{{8e0f7a12-bfb3-4fe8-b9a5-48fd50a15a9a}}"/>
      <supportedOS Id="{{1f676c76-80e1-4239-95bb-83d0f6d0da78}}"/>
      <supportedOS Id="{{4a2f28e3-53b9-4441-ba9c-d69d4a4a6e38}}"/>
      <supportedOS Id="{{35138b9a-5d96-4fbd-8e2d-a2440225f93a}}"/>
    </application>
  </compatibility>
  <asmv3:application>
    <asmv3:windowsSettings>
      <dpiAware xmlns="http://schemas.microsoft.com/SMI/2005/WindowsSettings">true</dpiAware>
    </asmv3:windowsSettings>
  </asmv3:application>
</assembly>
"""

RC = """1 ICON "setup.ico"
1 24 "manifest.xml"
1 VERSIONINFO
FILEVERSION {c4}
PRODUCTVERSION {c4}
FILEFLAGSMASK 0x3F
FILEFLAGS 0x0
FILEOS 0x40004
FILETYPE 0x1
FILESUBTYPE 0x0
BEGIN
  BLOCK "StringFileInfo"
  BEGIN
    BLOCK "040904B0"
    BEGIN
      VALUE "CompanyName", "Sluka Desktop"
      VALUE "LegalCopyright", "Copyright (c) 2026 Sluka. Licence: LICENSE.txt (sluka.app/terms)"
      VALUE "FileDescription", "Sluka Desktop Setup"
      VALUE "FileVersion", "{v}"
      VALUE "InternalName", "Sluka Desktop Setup"
      VALUE "OriginalFilename", "Sluka-Desktop-Setup-{v}.exe"
      VALUE "ProductName", "Sluka Desktop"
      VALUE "ProductVersion", "{v}"
    END
  END
  BLOCK "VarFileInfo"
  BEGIN
    VALUE "Translation", 0x409, 1200
  END
END
"""


def version_of(src: Path) -> str:
    text = (src / "app" / "sluka_desktop" / "__init__.py").read_text(encoding="utf-8")
    return re.search(r'__version__\s*=\s*"([^"]+)"', text).group(1)


def run(command, **kw):
    done = subprocess.run(command, capture_output=True, text=True, **kw)
    if done.returncode:
        raise SystemExit(f"{command[0]} failed:\n{done.stdout}\n{done.stderr}")
    return done


def resources(build: Path, version: str) -> Path:
    """The icon, the manifest and the version, as an object Go puts into the program (a .syso)."""
    sys.path.insert(0, str(HERE))
    import make_setup_icon

    make_setup_icon.main(str(build / "setup.ico"))
    nums = [int(n) for n in re.findall(r"\d+", version)][:4]
    nums += [0] * (4 - len(nums))
    (build / "manifest.xml").write_text(MANIFEST.format(v4=".".join(map(str, nums))), encoding="utf-8")
    (build / "setup.rc").write_text(RC.format(c4=",".join(map(str, nums)), v=version), encoding="utf-8")
    run(["llvm-rc", "-no-preprocess", "-fo", str(build / "setup.res"), str(build / "setup.rc")], cwd=build)
    syso = GO_SRC / "rsrc_windows_amd64.syso"
    run(["llvm-cvtres", "/machine:x64", f"/out:{syso}", str(build / "setup.res")])
    return syso


def terms(src: Path) -> str:
    """The licence agreement Setup shows first (and prints for --headless license): Sluka Desktop's LICENSE.txt; then
    NOTICES.txt, which the agreement points to (Microsoft's terms for its runtime files, part of the agreement, among
    them), to be read before the agreement is accepted; then the licence of Go, whose standard library is in Setup
    itself (Go's own LICENSE file)."""
    parts = []
    for name in ("LICENSE.txt", "NOTICES.txt"):
        path = src / name
        if not path.is_file():
            raise SystemExit(f"{path} is missing: Setup is never built without its licence agreement and its notices")
        parts.append(path.read_text(encoding="utf-8").replace("\r\n", "\n").rstrip())
    goroot = Path(run([GO, "env", "GOROOT"]).stdout.strip())
    go = (goroot / "LICENSE").read_text(encoding="utf-8").replace("\r\n", "\n").strip()
    if "The Go Authors" not in go:
        raise SystemExit(f"{goroot / 'LICENSE'} is not Go's licence")
    title = "GO, WHICH SETUP IS BUILT WITH"
    return ("\n\n\n".join(parts) + "\n\n\n" + title + "\n"
            + "=" * len(title) + "\n\nSetup (Sluka Desktop Setup.exe) is built with Go, whose standard\nlibrary is in it, "
            "under this licence (LICENSES\\Go.txt has it too, with\nGoogle's patent grant for Go):\n\n" + go + "\n")


def go_build(out: Path, goos: str) -> None:
    env = {**os.environ, "GOOS": goos, "GOARCH": "amd64", "CGO_ENABLED": "0", "GOFLAGS": "-mod=mod", "GOPROXY": "off"}
    flags = "-s -w" + (" -H windowsgui" if goos == "windows" else "")
    run([GO, "build", "-trimpath", "-ldflags", flags, "-o", str(out), "."], cwd=GO_SRC, env=env)


def payload(src: Path) -> bytes:
    """Sluka Desktop's files as a zip, under sluka-desktop/ (as in sluka-desktop-<version>-windows.zip)."""
    import io

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for path in sorted(src.rglob("*")):
            rel = path.relative_to(src)
            if "__pycache__" in rel.parts or path.suffix == ".pyc" or path.is_dir() or rel.parts[0] in SKIP:
                continue
            info = zipfile.ZipInfo("sluka-desktop/" + rel.as_posix(), date_time=(2026, 11, 26, 12, 0, 0))
            info.external_attr = 0o100644 << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            z.writestr(info, path.read_bytes())
    return buf.getvalue()


def build(out: Path, src: Path, linux: Path | None = None) -> dict:
    out, src = Path(out).resolve(), Path(src).resolve()
    linux = Path(linux).resolve() if linux is not None else None
    version = version_of(src)
    work = out.parent / (out.name + ".build")
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True)
    syso = GO_SRC / "rsrc_windows_amd64.syso"
    try:
        (GO_SRC / "terms.txt").write_text(terms(src), encoding="utf-8", newline="\n")
        resources(work, version)
        stub = work / "stub.exe"
        go_build(stub, "windows")
        if linux is not None:
            go_build(linux, "linux")  # (the .syso, named for Windows, is no Linux program's)
        data = payload(src)
        program = stub.read_bytes()
        out.write_bytes(program + data)
        return {"version": version, "stub": len(program), "payload": len(data), "size": out.stat().st_size}
    finally:
        if syso.exists():
            syso.unlink()
        shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    args = sys.argv[1:]
    linux_out = None
    if "--linux" in args:
        i = args.index("--linux")
        linux_out = Path(args[i + 1])
        del args[i:i + 2]
    target = Path(args[0])
    source = Path(args[1] if len(args) > 1 else "/home/claude/work/sluka-desktop")
    print(target, build(target, source, linux_out))
