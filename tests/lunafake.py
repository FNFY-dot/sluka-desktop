"""The stand-ins for Sluka's engine, for the tests: a library of LunaHost64.dll's functions (fake_lunahost.c, built
with gcc), an injector (fake_inject.py), an engine folder of empty files, and the pretend game's script."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).parent
INJECTOR = [sys.executable, "-I", str(HERE / "fake_inject.py")]
APP = os.environ.get("SLUKA_APP", "/home/claude/work/sluka-desktop/app")
if APP not in sys.path:
    sys.path.insert(0, APP)

from sluka_desktop import texthook  # noqa: E402

ENGINE_FILES = list(texthook.ENGINE_FILES)


def build_library(out: Path) -> str:
    subprocess.run(["gcc", "-shared", "-fPIC", "-O1", "-Wall", "-o", str(out), str(HERE / "fake_lunahost.c"), "-lpthread"],
                   check=True)
    return str(out)


def make_engine(folder: Path) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    for name in ENGINE_FILES:
        (folder / name).write_bytes(b"")
    return folder


def engine_args(library: str) -> list[str]:
    return ["--library", library, "--injector", json.dumps(INJECTOR)]


def write_script(folder: Path, rows, pid=None) -> None:
    """What the pretend game's text threads say once it is connected (see fake_lunahost.c)."""
    lines = []
    for row in rows:
        if row[1] in ("crash", "engine", "leave"):
            lines.append("\t".join(str(x) for x in row))
            continue
        delay, addr, ctx, ctx2, name, code, text = row
        lines.append(f"{delay}\t{addr:X}\t{ctx:X}\t{ctx2:X}\t{name}\t{code}\t{text.replace(chr(10), chr(92) + 'n')}")
    (folder / (f"script-{pid}.txt" if pid else "script.txt")).write_text("\n".join(lines) + "\n", encoding="utf-8")
