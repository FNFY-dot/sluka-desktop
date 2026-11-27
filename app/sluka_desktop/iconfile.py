# SPDX-License-Identifier: LicenseRef-Sluka
# Copyright (c) 2026 Sluka. Part of Sluka Desktop; see LICENSE.txt.
"""Sluka's own icon as a Windows .ico file, made from the extension's PNG icons.

Windows wants an .ico for a window, the taskbar and a shortcut.  Since Windows
Vista an .ico may hold PNG images as they are, so the extension's icons are
put in one unchanged: no image library is needed.
"""

from __future__ import annotations

import logging
import struct
from pathlib import Path

log = logging.getLogger("sluka")

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def png_size(data: bytes) -> tuple[int, int] | None:
    """Width and height of a PNG, from its header; None if it is no PNG."""
    if len(data) < 24 or not data.startswith(PNG_SIGNATURE) or data[12:16] != b"IHDR":
        return None
    width, height = struct.unpack(">II", data[16:24])
    return (width, height) if width and height else None


def make_ico(pngs: list[bytes]) -> bytes:
    """An .ico holding each PNG (largest last, as Windows' own tools write them); empty if none is usable."""
    images = []
    for data in pngs:
        size = png_size(data)
        if size and size[0] <= 256 and size[1] <= 256:
            images.append((size, data))
    images.sort(key=lambda item: item[0][0])
    if not images:
        return b""
    head = struct.pack("<HHH", 0, 1, len(images))
    offset = 6 + 16 * len(images)
    entries, blobs = b"", b""
    for (width, height), data in images:
        entries += struct.pack("<BBBBHHII", width % 256, height % 256, 0, 0, 1, 32, len(data), offset + len(blobs))
        blobs += data
    return head + entries + blobs


def extension_pngs(config) -> list[bytes]:
    """The extension's icons, as its manifest names them."""
    manifest = config.manifest or {}
    named = manifest.get("icons") if isinstance(manifest.get("icons"), dict) else {}
    action = manifest.get("action") or manifest.get("browser_action") or {}
    if isinstance(action, dict) and isinstance(action.get("default_icon"), dict):
        named = {**action["default_icon"], **named}
    found, seen = [], set()
    root = Path(config.ext_dir).resolve()
    for _size, rel in sorted(named.items(), key=lambda item: int(item[0]) if str(item[0]).isdigit() else 0):
        if not isinstance(rel, str) or not rel.lower().endswith(".png"):
            continue
        path = (root / rel.lstrip("/")).resolve()
        if root not in path.parents or path in seen or not path.is_file():
            continue
        seen.add(path)
        try:
            found.append(path.read_bytes())
        except OSError:
            continue
    return found


def ensure_icon(config) -> Path | None:
    """data/sluka.ico, written (again) from the extension's icons; None if there are none."""
    target = Path(config.data_dir) / "sluka.ico"
    try:
        data = make_ico(extension_pngs(config))
    except Exception:
        log.exception("Sluka's icon could not be made")
        return target if target.is_file() else None
    if not data:
        return target if target.is_file() else None
    try:
        if not target.is_file() or target.read_bytes() != data:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
    except OSError as err:
        log.warning("Sluka's icon could not be written (%s)", err)
        return target if target.is_file() else None
    return target
