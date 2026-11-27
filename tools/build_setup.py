"""Sluka Desktop's setup as one file: Sluka-Setup-<version>.cmd.

A batch file for its first lines -- it finds Python, as Sluka.cmd does, and has it run this very file -- then a zip,
which Python runs as an app (a zip may have anything before it): its __main__.py, which starts app\\sluka_setup.py
from inside the zip, and the app itself under payload/sluka-desktop/.  cmd.exe never reads past the line that starts
Python: that line ends in "exit /b".

    python build_setup.py OUT.cmd [SOURCE_FOLDER]
"""

import sys
import zipfile
from pathlib import Path

HEADER = r'''@echo off
rem Sluka Desktop's setup.  Double-click it: it installs Sluka Desktop where you choose, or
rem updates it, from a menu in this window.  A zip dragged onto it is taken at once.
rem
rem (This file is a batch file for these lines, and a zip after them -- the setup and the app
rem -- that Python runs.  Nothing is read past the line that starts Python.)
setlocal
title Sluka Desktop setup
color 0F
set "SLUKA_TEST=import sys; sys.exit(sys.hexversion // 0x3090000 == 0)"
set "SLUKA_PY="
py -3 -c "%SLUKA_TEST%" >nul 2>nul && set "SLUKA_PY=py -3"
if not defined SLUKA_PY python -c "%SLUKA_TEST%" >nul 2>nul && set "SLUKA_PY=python"
if not defined SLUKA_PY python3 -c "%SLUKA_TEST%" >nul 2>nul && set "SLUKA_PY=python3"
if defined SLUKA_PY %SLUKA_PY% -I "%~f0" %* & exit /b
echo.
echo   Sluka Desktop needs Python 3.9 or newer, and found none on this computer.
echo.
echo   Get it one of these ways, then double-click this file again:
echo     - from https://www.python.org/downloads/windows/
echo     - or in a terminal:   winget install -e --id Python.Python.3.13
echo   (Not the "Python 3.x" apps of the Microsoft Store: what those write for
echo   mpv and Anki, Windows keeps where mpv and Anki do not look.)
echo.
pause
exit /b 9009
'''

MAIN = '''"""Sluka Desktop's setup, run from its own file (Sluka-Setup-<version>.cmd): app\\\\sluka_setup.py, from inside it."""
import os
import sys

archive = os.path.abspath(sys.argv[0])
sys.path.insert(0, os.path.join(archive, "payload", "sluka-desktop", "app"))
import sluka_setup  # noqa: E402

sys.exit(sluka_setup.main(sys.argv[1:], archive=archive))
'''

#: What a copy of the app has that is not the app's: never in the setup.
SKIP = {"data", "extension", "config.ini", ".setup-new", ".setup-old"}


def build(out: Path, src: Path) -> int:
    entries = []
    for path in sorted(src.rglob("*")):
        rel = path.relative_to(src)
        if "__pycache__" in rel.parts or path.suffix == ".pyc" or path.is_dir() or rel.parts[0] in SKIP:
            continue
        entries.append((path, "payload/sluka-desktop/" + rel.as_posix()))
    header = HEADER.replace("\r\n", "\n").replace("\n", "\r\n").encode("ascii")
    with open(out, "wb") as f:
        f.write(header)
        with zipfile.ZipFile(f, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
            def add(name, data):
                info = zipfile.ZipInfo(name, date_time=(2026, 11, 24, 12, 0, 0))
                info.external_attr = (0o100644 << 16)
                info.compress_type = zipfile.ZIP_DEFLATED
                z.writestr(info, data)

            add("__main__.py", MAIN.encode("utf-8"))
            for path, name in entries:
                add(name, path.read_bytes())
    return len(entries)


if __name__ == "__main__":
    target = Path(sys.argv[1])
    count = build(target, Path(sys.argv[2] if len(sys.argv) > 2 else "/home/claude/work/sluka-desktop"))
    print(target, count, "files", target.stat().st_size, "bytes")
