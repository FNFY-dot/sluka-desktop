# SPDX-License-Identifier: GPL-3.0-only
# Copyright (c) 2026 Sluka.  Part of Sluka Desktop.
#
# This program is free software: you can redistribute it and/or modify it under the terms of the GNU General Public
# License as published by the Free Software Foundation, version 3 of the License.
#
# This program is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY; without even the implied
# warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License along with this program (LICENSES\GPL-3.0.txt, in
# Sluka Desktop's folder).  If not, see <https://www.gnu.org/licenses/>.
#
# It drives LunaTranslator's OCR and Windows helpers, CVUtils.dll and NativeUtils.dll (Copyright (C) 2026 HIllya51 and
# LunaTranslator's contributors, GNU GPL version 3: engine\LICENSES\LICENSE.LunaTranslator), declaring their functions
# as LunaTranslator's own Python declares them; hence version 3 of the licence, as LunaTranslator's.  It writes and
# reads Google Lens' messages as Chromium's lens_overlay protos define them (Copyright 2024 The Chromium Authors, under
# a BSD licence: engine\LICENSES\LICENSE.chromium.chromium).
"""Sluka's screen reader: the text in a box over a game's window, read off the screen (OCR), for a game whose text
no hook reads.

    python ocrd.py ENGINE_FOLDER [--log FILE] [--network MODE] [--socks HOST:PORT]

The app (ocrtext.py) starts this as a program apart from itself, as it starts hookd.py, and speaks with it in lines
of JSON (UTF-8).  It reads with one of three readers, ones LunaTranslator 12.1.3.12 has, driven as LunaTranslator
drives them:

  builtin   LunaTranslator's own OCR (CVUtils.dll), PaddleOCR's PP-OCRv5 model run by ONNX Runtime: offline, in
            the engine folder's ocr folder -- Japanese, Chinese and English
  windows   Windows' own OCR (Windows.Media.Ocr), through LunaTranslator's NativeUtils.dll: offline, once Windows
            has the language's OCR pack
  lens      Google Lens: online, each picture sent to Google (NativeUtils.dll writes the request, and reads the
            answer).  The app asks before it is used the first time.

(LunaTranslator has a fourth, the Snipping Tool's: the OCR inside Windows 11's Snipping Tool app, copied out of the
app's folder and run apart from it.  Sluka leaves it out: that OCR is a part of Microsoft's Snipping Tool, which
Microsoft has not licensed for other programs to copy out and run.)

  in   {"cmd": "engines", "lang": "ja"}                which readers can be used here, and why not
       {"cmd": "select", "delay": 0.4, "exclude": [pid]} a box dragged over the screen (LunaTranslator's own
                                                       window for it), and the window under it
       {"cmd": "cancel-select"}
       {"cmd": "watch", "hwnd": .., "pid": .., "box": [x, y, w, h], "client": [w, h], "engine": "auto" | "builtin" | ..,
        "mode": "auto" | "interval" | "trigger", "interval": 1.5, "lang": "ja", "direction": "auto" | "h" | "v",
        "furigana": true, "capture": "screen" | "window", "front": true, "allow": [pid]}
                                                       (hwnd 0: the box is where it is on the screen, in no window)
       {"cmd": "once"}                                 the box read now
       {"cmd": "stop"}
       {"cmd": "read", "rect": [x, y, w, h], "engine": .., "lang": .., "direction": .., "furigana": ..}
                                                       a place on the screen read once (sluka ocr-check)
       Sluka Vision (a game's whole window, read where its words are: VisionWatch):
       {"cmd": "vision-start", "engine": "lens" | .., "lang": .., "furigana": .., "capture": .., "auto": .., "allow":
        [pid], "hwnd": ..}                             (hwnd: a window chosen before)
       {"cmd": "vision-read", "front": true, "exclude": [pid]}   read now: the window in front, where it is not one of
                                                       these programs' (front), else the one chosen
       {"cmd": "vision-pick", "seconds": 10, "exclude": [pid]}  the next window put in front is the one
       {"cmd": "vision-cancel-pick"}  {"cmd": "vision-auto", "on": ..}  {"cmd": "vision-settings", ...}
       {"cmd": "vision-clear"}  (the words put away)  {"cmd": "vision-forget"}  (and the window)
       {"cmd": "vision-target", "hwnd": ..}  {"cmd": "vision-stop"}
       {"cmd": "vision-hold", "read": .., "lines": [i]}  the lines of that read that the word pointed at (or the one
                                                       whose panel is open) is on: what changes under them alone is not
                                                       read again by itself ("lines": [] for none)
       {"cmd": "vision-freeze", "on": .., "path": .., "ask": n}  the window's picture taken now and kept (written to
                                                       path, a BMP; n, the app's number for it, said back):
                                                       read where its words are not those shown, and looked at in place
                                                       of the window until "on": false (the game paused or not: the
                                                       app's)
       {"cmd": "quit"}
  out  {"ev": "ready", ...}   {"ev": "fatal", "text": ..}
       {"ev": "engines", "engines": {name: {"ok": .., "why": .., ...}}}
       {"ev": "selected", "rect": [x1, y1, x2, y2], "window": {"hwnd", "pid", "title", "class", "client": [x, y, w, h],
        "box": [x, y, w, h]}}  or  {"ev": "selected", "cancelled": true}
       {"ev": "watching", ...}  {"ev": "stopped", "why": ..}
       {"ev": "status", "state": .., "text": ..}       starting, loading, waiting, reading, hidden, behind, ...
       {"ev": "text", "text": .., "engine": .., "ms": .., "lines": .., "forced": ..}   ("" only for a read asked for)
       {"ev": "read", "engine": .., "text": .., "ms": .., "lines": .., "error": ..}
       {"ev": "capture", "how": "screen" | "window", "why": "frozen"}  (why: the game's own picture stays as it was)
       {"ev": "error", "text": ..}
       Sluka Vision's: {"ev": "vision-window", "window": {...} | null}  {"ev": "vision-picked", "window": .. | null}
       {"ev": "vision-layout", "id", "engine", "ms", "why", "area": [x, y, w, h], "size": [w, h], "lines": [{"i", "p",
        "v", "rtl", "text", "box": [cx, cy, w, h, angle], "words": [[start, end, from, to]]}]}   (the window's pixels)
       {"ev": "vision-area", "area": [x, y, w, h]}  {"ev": "vision-front", "on": .., "game": ..}  (game: the game's own
        window in front, not only one of Sluka's)  {"ev": "vision-capture", "how": "screen" | "window", "why"}  (how the
        window is read: Sluka's windows are to be left out of pictures of the screen while it is "screen")
        {"ev": "vision-stale", "lines": [i] | "all": true}  {"ev":
        "vision-back", "lines": [i]}  (what is under them is again as it was read)  {"ev": "vision-status", "state",
        "text"}  {"ev": "vision-error", "text"}
       {"ev": "vision-gone", "window"}  {"ev": "vision-stopped"}
       {"ev": "vision-frozen", "on": true, "path", "size": [w, h], "area": [x, y, w, h], "how"} | {"ev": "vision-frozen",
        "on": false} | {"ev": "vision-frozen", "on": false, "error": ..}  (no picture could be had); each with the
        "ask" of the vision-freeze it is about

This file stands alone (nothing of the app is imported), so that it runs as a plain script under the app's own
Python.  Coordinates are the screen's own pixels: this program says so to Windows as it starts (per-monitor DPI).
"""

from __future__ import annotations

import array
import collections
import ctypes
import http.client
import json
import math
import operator
import os
import queue
import random
import re
import socket
import ssl
import struct
import sys
import threading
import time
import traceback
import urllib.parse
import zlib
from ctypes import CFUNCTYPE, POINTER, Structure, c_bool, c_char, c_char_p, c_float, c_int, c_int32, c_size_t, c_uint64, c_void_p, c_wchar_p

PROTOCOL = 1
WINDOWS = sys.platform == "win32"
READERS = ("builtin", "windows", "lens")
MODES = ("auto", "interval", "trigger")
DIRECTIONS = {"h": 0, "v": 1, "auto": 2}  # CVUtils' Directional: horizontal, vertical, either
CAPTURES = ("screen", "window")
#: The readers "auto" tries, in turn (Google Lens never: it sends the pictures away).
AUTO_ORDER = ("builtin", "windows")
#: A pixel as one number of four bytes (Image.shrunk).
PIXEL = "I" if array.array("I").itemsize == 4 else "L"


def _c_text(data) -> str:
    """A message from a library's C++ (an exception's what(): the system's own code page there, as LunaTranslator reads
    it)."""
    return (data or b"").decode("mbcs" if WINDOWS else "utf-8", "replace")


def _add_dll_directory(folder: str) -> None:
    if WINDOWS:
        try:
            os.add_dll_directory(folder)
        except (AttributeError, OSError):
            pass


# ======================================================================================== pictures


class Image:
    """A picture: four bytes a pixel (blue, green, red, and a fourth not looked at), the top row first."""

    __slots__ = ("w", "h", "data")

    def __init__(self, w: int, h: int, data):
        self.w, self.h = int(w), int(h)
        self.data = bytes(data)
        if self.w < 0 or self.h < 0 or len(self.data) != self.w * self.h * 4:
            raise ValueError("a picture of the wrong size")

    def crop(self, x, y, w, h) -> "Image":
        x = max(0, min(self.w, int(x)))
        y = max(0, min(self.h, int(y)))
        w = max(0, min(self.w - x, int(w)))
        h = max(0, min(self.h - y, int(h)))
        stride = self.w * 4
        rows = [self.data[(y + r) * stride + x * 4:(y + r) * stride + (x + w) * 4] for r in range(h)]
        return Image(w, h, b"".join(rows))

    def bgr(self) -> bytes:
        out = bytearray(self.w * self.h * 3)
        out[0::3] = self.data[0::4]
        out[1::3] = self.data[1::4]
        out[2::3] = self.data[2::4]
        return bytes(out)

    def rgb(self) -> bytes:
        out = bytearray(self.w * self.h * 3)
        out[0::3] = self.data[2::4]
        out[1::3] = self.data[1::4]
        out[2::3] = self.data[0::4]
        return bytes(out)

    def rgba(self) -> bytes:
        out = bytearray(self.data)
        out[0::4] = self.data[2::4]
        out[2::4] = self.data[0::4]
        out[3::4] = b"\xff" * (self.w * self.h)
        return bytes(out)

    def scaled(self, factor: int) -> "Image":
        """Each pixel made factor x factor (for a reader that wants bigger letters)."""
        factor = int(factor)
        if factor <= 1:
            return self
        stride = self.w * 4
        rows = []
        for r in range(self.h):
            row = self.data[r * stride:(r + 1) * stride]
            wide = b"".join(row[i:i + 4] * factor for i in range(0, stride, 4))
            rows.extend([wide] * factor)
        return Image(self.w * factor, self.h * factor, b"".join(rows))

    def shrunk(self, w: int, h: int) -> "Image":
        """Made smaller, to w x h at most: each pixel the one of the picture nearest it (Sluka Vision's whole window, before
        it is sent to Google Lens)."""
        w, h = max(1, min(self.w, int(w))), max(1, min(self.h, int(h)))
        if (w, h) == (self.w, self.h):
            return self
        xs = [min(self.w - 1, int((i + 0.5) * self.w / w)) for i in range(w)]
        take = operator.itemgetter(*xs) if w > 1 else (lambda row: (row[xs[0]],))
        stride = self.w * 4
        rows = []
        for j in range(h):
            y = min(self.h - 1, int((j + 0.5) * self.h / h))
            pixels = array.array(PIXEL)
            pixels.frombytes(self.data[y * stride:(y + 1) * stride])
            rows.append(array.array(PIXEL, take(pixels)).tobytes())
        return Image(w, h, b"".join(rows))

    def padded(self, w: int, h: int) -> "Image":
        """At least w x h: the picture at the top left, the rest of the colour of its top-left corner."""
        if self.w >= w and self.h >= h:
            return self
        width, height = max(w, self.w), max(h, self.h)
        fill = self.data[:4] if self.data else b"\xff\xff\xff\xff"
        stride = self.w * 4
        rows = [self.data[r * stride:(r + 1) * stride] + fill * (width - self.w) for r in range(self.h)]
        rows.extend([fill * width] * (height - self.h))
        return Image(width, height, b"".join(rows))

    def blank(self) -> bool:
        """Black all over, or white: a picture of a window that gave nothing (as LunaTranslator tells one)."""
        if not self.data:
            return True
        step = max(1, (self.w * self.h) // 6000) * 4
        seen = set()
        for channel in (0, 1, 2):
            seen.update(self.data[channel::step])
            if len(seen) > 1:
                return False
        return seen <= {0} or seen <= {255}


def to_bmp(img: Image) -> bytes:
    """A 24-bit BMP, the bottom row first, as every program reads one."""
    row = img.w * 3
    pad = b"\0" * ((-row) % 4)
    bgr = img.bgr()
    pixels = b"".join(bgr[r * row:(r + 1) * row] + pad for r in range(img.h - 1, -1, -1))
    head = struct.pack("<2sIHHI", b"BM", 54 + len(pixels), 0, 0, 54)
    info = struct.pack("<IiiHHIIiiII", 40, img.w, img.h, 1, 24, 0, len(pixels), 2835, 2835, 0, 0)
    return head + info + pixels


def from_bmp(data: bytes) -> Image:
    """A 24-bit or 32-bit BMP (NativeUtils gives them, either way up) as a picture."""
    if len(data) < 54 or data[:2] != b"BM":
        raise ValueError("not a BMP")
    offset = struct.unpack_from("<I", data, 10)[0]
    w, h = struct.unpack_from("<ii", data, 18)
    bits = struct.unpack_from("<H", data, 28)[0]
    if bits not in (24, 32) or w <= 0 or h == 0:
        raise ValueError(f"a BMP of {bits} bits a pixel")
    top_down = h < 0
    h = abs(h)
    size = bits // 8
    row = ((w * bits + 31) // 32) * 4
    rows = []
    for r in range(h):
        src = data[offset + r * row:offset + r * row + w * size]
        if len(src) < w * size:
            raise ValueError("a BMP cut short")
        if size == 4:
            rows.append(src)
        else:
            px = bytearray(w * 4)
            px[0::4] = src[0::3]
            px[1::4] = src[1::3]
            px[2::4] = src[2::3]
            px[3::4] = b"\xff" * w
            rows.append(bytes(px))
    if not top_down:
        rows.reverse()
    return Image(w, h, b"".join(rows))


def _ask_number(value) -> int:
    """The number the app gave a picture it asked for (vision.py), said back with every word about it; 0 for none."""
    try:
        n = int(value)
    except (TypeError, ValueError):
        return 0
    return n if 0 < n < 2 ** 53 else 0


def _write_file(path: str, data: bytes) -> None:
    """``data`` written to ``path`` whole: to a file beside it first, then put in its place."""
    part = f"{path}.part"
    with open(part, "wb") as out:
        out.write(data)
    os.replace(part, path)


def to_png(img: Image) -> bytes:
    """A PNG (8-bit RGB), for Google Lens."""
    rgb = img.rgb()
    row = img.w * 3
    raw = b"".join(b"\0" + rgb[r * row:(r + 1) * row] for r in range(img.h))

    def chunk(kind: bytes, body: bytes) -> bytes:
        return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body) & 0xFFFFFFFF)

    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", img.w, img.h, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 6)) + chunk(b"IEND", b""))


def to_png_up(img: Image) -> bytes:
    """A PNG (8-bit RGB) whose rows are written as what each differs from the one above it (PNG's "Up" filter): for a
    picture of a game, a fifth smaller than to_png's -- Sluka Vision sends a whole window to Google Lens."""
    rgb = img.rgb()
    row = img.w * 3
    n = len(rgb)
    if not n:
        return to_png(img)
    above = bytes(row) + rgb[:-row]
    high = int.from_bytes(b"\x80" * n, "big")
    a, b = int.from_bytes(rgb, "big"), int.from_bytes(above, "big")
    # Every byte less the one over it, all at once: no byte borrows from the next (each one's top bit is set first,
    # and put right after).
    up = (((a | high) - (b & ~high)) ^ ((a ^ ~b) & high)).to_bytes(n, "big")
    raw = b"".join(b"\x02" + up[r * row:(r + 1) * row] for r in range(img.h))

    def chunk(kind: bytes, body: bytes) -> bytes:
        return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body) & 0xFFFFFFFF)

    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", img.w, img.h, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 6)) + chunk(b"IEND", b""))


def signature(img: Image, samples: int = 10000) -> bytes:
    """A small likeness of the picture: the blue, green and red of a pixel in every few, of a row in every few."""
    if not img.w or not img.h:
        return b""
    step = max(1, int(math.sqrt(img.w * img.h / samples)))
    stride = img.w * 4
    rows = []
    for y in range(0, img.h, step):
        row = img.data[y * stride:(y + 1) * stride]
        rows += [row[0::4 * step], row[1::4 * step], row[2::4 * step]]
    return b"".join(rows)


def difference(a: bytes, b: bytes, threshold: int = 40) -> float:
    """How much of two likenesses differs (0: nothing, 1: all of it)."""
    if not a or len(a) != len(b):
        return 1.0
    changed = sum(1 for x, y in zip(a, b) if x - y > threshold or y - x > threshold)
    return changed / len(a)


# ======================================================================================== what was read, as text

CJK_CHARS = "　-〿぀-ヿㇰ-ㇿ㐀-䶿一-鿿豈-﫿＀-￯"
CJK = re.compile(f"[{CJK_CHARS}]")
CJK_SPACE = re.compile(f"(?<=[{CJK_CHARS}])\\s+(?=[{CJK_CHARS}])")
KANA_ONLY = re.compile(r"^[぀-ゟ゠-ヿㇰ-ㇿｦ-ﾟ・ー]+$")


class Item:
    __slots__ = ("x1", "y1", "x2", "y2", "text")

    def __init__(self, x1, y1, x2, y2, text):
        self.x1, self.y1, self.x2, self.y2, self.text = x1, y1, x2, y2, text

    @property
    def w(self) -> float:
        return max(1.0, self.x2 - self.x1)

    @property
    def h(self) -> float:
        return max(1.0, self.y2 - self.y1)


def bounds(box) -> tuple:
    values = [float(v) for v in box]
    if len(values) >= 8:
        xs, ys = values[0:8:2], values[1:8:2]
        return min(xs), min(ys), max(xs), max(ys)
    x1, y1, x2, y2 = values[:4]
    return min(x1, x2), min(y1, y2), max(x1, x2), max(y1, y2)


def tidy(text) -> str:
    """One line of what a reader read: no breaks, no doubled spaces, and none between Japanese letters (Windows' OCR
    puts one between every word, Japanese ones too)."""
    text = str(text or "").replace("\r", " ").replace("\n", " ")
    text = re.sub(r"[ \t ]+", " ", text).strip()
    return CJK_SPACE.sub("", text)


def _median(values) -> float:
    s = sorted(values)
    if not s:
        return 0.0
    n = len(s)
    return s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2


def looks_vertical(items) -> bool:
    tall = sum(1 for i in items if i.h > 1.3 * i.w and len(i.text) > 1)
    wide = sum(1 for i in items if i.w > 1.3 * i.h and len(i.text) > 1)
    return tall > wide


def drop_furigana(items: list, vertical: bool) -> list:
    """The small kana over a word that tells how it is read (beside it, in vertical text): not part of the line."""
    if len(items) < 2:
        return items
    size = (lambda i: i.w) if vertical else (lambda i: i.h)
    main = [size(i) for i in items if not KANA_ONLY.match(i.text)] or [size(i) for i in items]
    usual = _median(main)

    def beside(small, big) -> bool:
        if vertical:  # to the right of its column
            overlap = min(small.y2, big.y2) - max(small.y1, big.y1)
            gap = small.x1 - big.x2
        else:  # above its line
            overlap = min(small.x2, big.x2) - max(small.x1, big.x1)
            gap = big.y1 - small.y2
        return overlap > 0 and -0.5 * usual <= gap <= 0.6 * usual

    kept = []
    for item in items:
        if KANA_ONLY.match(item.text) and size(item) < 0.7 * usual and any(
                other is not item and size(other) >= 0.85 * usual and beside(item, other) for other in items):
            continue
        kept.append(item)
    return kept


def lines_of(items: list, vertical: bool) -> list:
    """The pieces put in lines (columns, for vertical text): those whose middles fall inside each other's height,
    in reading order -- top to bottom; vertical columns right to left."""
    lo = (lambda i: i.x1) if vertical else (lambda i: i.y1)
    hi = (lambda i: i.x2) if vertical else (lambda i: i.y2)
    lines: list[list] = []
    for item in sorted(items, key=lambda i: (lo(i) + hi(i)) / 2):
        middle = (lo(item) + hi(item)) / 2
        for line in lines:
            low, high = min(lo(o) for o in line), max(hi(o) for o in line)
            if low <= middle <= high and lo(item) <= (low + high) / 2 <= hi(item):
                line.append(item)
                break
        else:
            lines.append([item])
    for line in lines:
        line.sort(key=(lambda i: i.y1) if vertical else (lambda i: i.x1))
    if vertical:
        lines.sort(key=lambda line: -sum(i.x1 + i.x2 for i in line) / len(line))
    else:
        lines.sort(key=lambda line: sum(i.y1 + i.y2 for i in line) / len(line))
    return lines


def joined(words) -> str:
    out = ""
    for word in words:
        if out and word and not (CJK.match(out[-1]) or CJK.match(word[0])):
            out += " "
        out += word
    return out


def arrange(results, direction: str = "auto", furigana: bool = True) -> tuple[str, int]:
    """What a reader found (a box and a text each) as the text of the box: its lines in reading order, a line each.
    The number of lines too."""
    items = []
    for box, text in results:
        text = tidy(text)
        if not text:
            continue
        try:
            x1, y1, x2, y2 = bounds(box)
        except (TypeError, ValueError):
            x1 = y1 = 0.0
            x2 = y2 = 1.0
        items.append(Item(x1, y1, x2, y2, text))
    if not items:
        return "", 0
    vertical = direction == "v" or (direction == "auto" and looks_vertical(items))
    if furigana:
        items = drop_furigana(items, vertical)
    lines = [joined(i.text for i in line) for line in lines_of(items, vertical)]
    return "\n".join(lines), len(lines)


def edit_distance(a: str, b: str) -> int:
    if a == b:
        return 0
    if len(a) < len(b):
        a, b = b, a
    previous = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        current = [i]
        for j, cb in enumerate(b, 1):
            current.append(min(previous[j] + 1, current[j - 1] + 1, previous[j - 1] + (ca != cb)))
        previous = current
    return previous[-1]


def same_text(a: str, b: str) -> bool:
    """The same line read twice (a reader may read a letter or two otherwise from one picture to the next)."""
    a, b = re.sub(r"\s+", "", a or ""), re.sub(r"\s+", "", b or "")
    if a == b:
        return True
    if not a or not b or max(len(a), len(b)) > 400:
        return False
    shortest = min(len(a), len(b))
    allowed = 2 if shortest >= 10 else 1 if shortest >= 4 else 0
    return abs(len(a) - len(b)) <= allowed and edit_distance(a, b) <= allowed


# ======================================================================================== Windows itself

if WINDOWS:
    from ctypes import wintypes

    class RECT(Structure):
        _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long), ("right", ctypes.c_long), ("bottom", ctypes.c_long)]

    class POINT(Structure):
        _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]

    class BITMAPINFOHEADER(Structure):
        _fields_ = [("biSize", wintypes.DWORD), ("biWidth", ctypes.c_long), ("biHeight", ctypes.c_long),
                    ("biPlanes", wintypes.WORD), ("biBitCount", wintypes.WORD), ("biCompression", wintypes.DWORD),
                    ("biSizeImage", wintypes.DWORD), ("biXPelsPerMeter", ctypes.c_long), ("biYPelsPerMeter", ctypes.c_long),
                    ("biClrUsed", wintypes.DWORD), ("biClrImportant", wintypes.DWORD)]

    class BITMAPINFO(Structure):
        _fields_ = [("bmiHeader", BITMAPINFOHEADER), ("bmiColors", wintypes.DWORD * 3)]


SRCCOPY = 0x00CC0020
PW_RENDERFULLCONTENT = 0x2
GWL_EXSTYLE = -20
WS_EX_TRANSPARENT = 0x20
WS_EX_TOOLWINDOW = 0x80
WS_EX_LAYERED = 0x80000
LWA_ALPHA = 0x2
DWMWA_CLOAKED = 14
#: The desktop's own windows (its picture and its icons): never a game's.
DESKTOP_CLASSES = ("Progman", "WorkerW")
#: ... and Windows' own over it, which may be in front for a moment as a game is gone back to -- the taskbar, the
#: hidden icons beside it, the task switcher: never the window Sluka Vision's key reads.
SHELL_CLASSES = DESKTOP_CLASSES + ("Shell_TrayWnd", "Shell_SecondaryTrayWnd", "NotifyIconOverflowWindow",
                                   "TopLevelWindowForOverflowXamlIsland", "MultitaskingViewFrame",
                                   "XamlExplorerHostIslandWindow", "ForegroundStaging")
WM_CLOSE = 0x0010
KEYS = {"click": 0x01, "enter": 0x0D, "space": 0x20, "ctrl": 0x11}


def dpi_aware() -> None:
    """Coordinates in the screen's own pixels, on every monitor (as the box dragged over the screen has them)."""
    if not WINDOWS:
        return
    user32 = ctypes.WinDLL("user32")
    try:
        user32.SetProcessDpiAwarenessContext.argtypes = (c_void_p,)
        user32.SetProcessDpiAwarenessContext.restype = wintypes.BOOL
        if user32.SetProcessDpiAwarenessContext(c_void_p(-4)):  # per monitor, v2
            return
    except AttributeError:
        pass
    try:
        if ctypes.WinDLL("shcore").SetProcessDpiAwareness(2) == 0:
            return
    except (OSError, AttributeError):
        pass
    try:
        user32.SetProcessDPIAware()
    except AttributeError:
        pass


def module_version(name: str) -> str:
    """The version of a library this program has loaded, as "14.38.33135.0" (Windows); '' where it cannot be told."""
    if not WINDOWS:
        return ""
    try:
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        version = ctypes.WinDLL("version")
        kernel32.GetModuleHandleW.restype = c_void_p
        kernel32.GetModuleHandleW.argtypes = (c_wchar_p,)
        kernel32.GetModuleFileNameW.restype = wintypes.DWORD
        kernel32.GetModuleFileNameW.argtypes = (c_void_p, c_wchar_p, wintypes.DWORD)
        version.GetFileVersionInfoSizeW.restype = wintypes.DWORD
        version.GetFileVersionInfoSizeW.argtypes = (c_wchar_p, c_void_p)
        version.GetFileVersionInfoW.restype = wintypes.BOOL
        version.GetFileVersionInfoW.argtypes = (c_wchar_p, wintypes.DWORD, wintypes.DWORD, c_void_p)
        version.VerQueryValueW.restype = wintypes.BOOL
        version.VerQueryValueW.argtypes = (c_void_p, c_wchar_p, POINTER(c_void_p), POINTER(wintypes.UINT))
        handle = kernel32.GetModuleHandleW(name)
        if not handle:
            return ""
        path = ctypes.create_unicode_buffer(32768)
        if not kernel32.GetModuleFileNameW(handle, path, 32768):
            return ""
        size = version.GetFileVersionInfoSizeW(path.value, None)
        if not size:
            return ""
        data = ctypes.create_string_buffer(size)
        if not version.GetFileVersionInfoW(path.value, 0, size, data):
            return ""
        info, length = c_void_p(), wintypes.UINT(0)
        if not version.VerQueryValueW(data, "\\", ctypes.byref(info), ctypes.byref(length)) or length.value < 16:
            return ""
        most, least = struct.unpack_from("<II", ctypes.string_at(info, 16), 8)  # VS_FIXEDFILEINFO's file version
        return f"{most >> 16}.{most & 0xFFFF}.{least >> 16}.{least & 0xFFFF}"
    except (OSError, AttributeError, ValueError):
        return ""


def runtime_too_old() -> str:
    """Why ONNX Runtime 1.21 and later cannot start in this program, as CVUtils.dll tells: Microsoft's C++ runtime
    loaded in it (msvcp140.dll, vcruntime140.dll) older than 14.40 -- Python's own vcruntime140.dll, mostly."""
    old = []
    for name in ("msvcp140.dll", "vcruntime140.dll"):
        found = module_version(name)
        try:
            if found and tuple(int(x) for x in found.split(".")[:2]) < (14, 40):
                old.append(f"{name} {found}")
        except ValueError:
            pass
    return ", ".join(old)


_winrt = threading.local()


def ro_initialize() -> None:
    """Windows' runtime, for the thread that calls it (Windows' OCR needs it)."""
    if not WINDOWS or getattr(_winrt, "done", False):
        return
    try:
        combase = ctypes.WinDLL("combase")
        combase.RoInitialize.argtypes = (c_int,)
        combase.RoInitialize.restype = ctypes.c_long
        combase.RoInitialize(1)  # multithreaded; one already there is as good
    except (OSError, AttributeError):
        pass
    _winrt.done = True


def share_apart(a: list, b: list) -> float:
    """How much two likenesses of one place (cells_of) differ: the share of their cells that changed."""
    if not a or len(a) != len(b):
        return 1.0
    return sum(1 for x, y in zip(a, b) if x != y and _differ(x, y, VisionWatch.MOVED) >= VisionWatch.MOVED_SAMPLES) / len(a)


def likeness(img: "Image") -> list:
    return cells_of(img, VisionWatch.CELL, VisionWatch.PER)[2]


WAY_SAID = {  # (what the log says, as a window's way of being taken changes)
    "print": "is taken as Windows itself draws it: the picture its device context gives is not what it shows",
    "dc": "is taken from its device context",
    "screen": "gives only a picture that no longer changes while the screen there does: the screen is read there",
}


class WindowWays:
    """How the game's own window is taken ("The game's own window" as what is read), for each window: from its device
    context ("dc", as LunaTranslator takes it first: quick), else as Windows itself draws it ("print", PrintWindow) --
    and the screen, where neither follows the game.

    A window's device context can keep a picture that no longer changes: a game that went on to draw with the graphics
    card past Windows keeps there what it showed before -- Ace Attorney, its title menu -- however often it is read.  So
    at once, and then now and then (CHECK), the device context's picture is put beside Windows' own drawing of the
    window: taken a moment apart, the two are one picture wherever both follow the game (ALIKE: no more apart than a
    moving game can be in that moment).  Where they are not, the one nearer what the screen shows is kept (the game in
    front), else Windows' own.  And where even that stays exactly as it was while the screen there has since changed
    much (FROZEN_MOVED), and shows something else than it over most of it (FROZEN_APART: more than Sluka's own words,
    cards and panels over the game can cover), at FROZEN_LOOKS looks running, the game in front all the while, the
    window is frozen: the screen is read instead, from then on (frozen(): the app says so), until forget() -- the way
    of reading chosen again.

    take(way, hwnd, rect) gives the box out of the window's picture taken that way (None: nothing, or all black);
    screen(rect) the screen's picture of it; in_front(hwnd) whether the game itself is in front."""

    CHECK = 2.0          # how often the way is looked at again (seconds)
    ALIKE = 0.02         # the device context's picture and Windows' own, apart in no more than this share: one picture
    FROZEN_MOVED = 0.3   # the screen changed in this share of its cells since the window's picture last changed, ...
    FROZEN_APART = 0.5   # ... and is apart from the window's picture in this share of them, ...
    FROZEN_LOOKS = 2     # ... at this many looks running: frozen

    def __init__(self, take, screen, in_front, clock=time.monotonic, check: float | None = None):
        self.take, self.screen, self.in_front, self.clock = take, screen, in_front, clock
        if check is not None:
            self.CHECK = check
        self._ways: dict = {}
        self._lock = threading.Lock()

    def way(self, hwnd) -> str:
        with self._lock:
            return (self._ways.get(hwnd) or {}).get("way", "dc")

    def frozen(self, hwnd) -> bool:
        return self.way(hwnd) == "screen"

    def forget(self) -> None:
        with self._lock:
            self._ways.clear()

    def grab(self, hwnd, rect):
        """The box out of the window's own picture, taken the way that follows the game: the picture, or None where
        the screen is to be read instead (frozen, or nothing from the window)."""
        now = self.clock()
        with self._lock:
            state = self._ways.setdefault(hwnd, {"way": "dc", "at": None, "looks": 0, "base": None})
            way = state["way"]
        if way == "screen":
            return None
        due = state["at"] is None or now - state["at"] >= self.CHECK
        img = None
        if way == "dc":
            img = self.take("dc", hwnd, rect)
            if img is None:
                img = self.take("print", hwnd, rect)  # (nothing from the device context, this time: as before)
            elif due:
                drawn = self.take("print", hwnd, rect)
                if drawn is not None and share_apart(likeness(img), likeness(drawn)) > self.ALIKE:
                    way = self._nearer(hwnd, rect, img, drawn)
                    if way == "print":
                        img = drawn  # (the device context keeps an old picture: Windows' own drawing, then)
        else:
            img = self.take("print", hwnd, rect)
        if img is not None and due:
            way = self._look(state, way, hwnd, rect, img)
        with self._lock:
            before, state["way"] = state["way"], way
            if due:
                state["at"] = now
        if way != before:
            name = f"{hwnd:#x}" if isinstance(hwnd, int) else str(hwnd)
            _say(f"window: {name} " + WAY_SAID.get(way, way))
        return None if way == "screen" else img

    def _nearer(self, hwnd, rect, dc, drawn) -> str:
        """Of the device context's picture and Windows' own drawing, which are not one: the one nearer what the screen
        shows, the game in front; else Windows' own."""
        if not self.in_front(hwnd):
            return "print"
        shown = self.screen(rect)
        if shown is None or (shown.w, shown.h) != (dc.w, dc.h):
            return "print"
        screen = likeness(shown)
        return "dc" if share_apart(likeness(dc), screen) < share_apart(likeness(drawn), screen) else "print"

    def _look(self, state: dict, way: str, hwnd, rect, img) -> str:
        """The window's picture, and the screen's, while the game itself is in front (else the screen there may show
        another window): frozen, once the window's picture has stayed exactly as it was while the screen has since
        changed much, at FROZEN_LOOKS looks running."""
        if not self.in_front(hwnd):
            state["looks"], state["base"] = 0, None
            return way
        shown = self.screen(rect)
        if shown is None or (shown.w, shown.h) != (img.w, img.h):
            return way
        window, screen = likeness(img), likeness(shown)
        base = state["base"]  # (the window's likeness, and the screen's, as they were when the window's last changed)
        if base is None or len(base[0]) != len(window) or len(base[1]) != len(screen) or share_apart(base[0], window) > 0:
            state["looks"], state["base"] = 0, (window, screen)
            return way
        moved = share_apart(base[1], screen) >= self.FROZEN_MOVED
        apart = share_apart(window, screen) >= self.FROZEN_APART
        state["looks"] = state["looks"] + 1 if moved and apart else 0
        return "screen" if state["looks"] >= self.FROZEN_LOOKS else way


class WindowsDesktop:
    """The screen, its windows, and the keys, through Windows' own functions."""

    def __init__(self):
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
        w = wintypes
        HWND, HDC, HANDLE = w.HWND, w.HDC, w.HANDLE
        self.WNDENUMPROC = ctypes.WINFUNCTYPE(w.BOOL, HWND, w.LPARAM)

        def fn(lib, name, restype, *argtypes):
            f = getattr(lib, name)
            f.restype = restype
            f.argtypes = argtypes
            return f

        self.GetDC = fn(user32, "GetDC", HDC, HWND)
        self.ReleaseDC = fn(user32, "ReleaseDC", c_int, HWND, HDC)
        self.GetForegroundWindow = fn(user32, "GetForegroundWindow", HWND)
        self.GetWindowThreadProcessId = fn(user32, "GetWindowThreadProcessId", w.DWORD, HWND, POINTER(w.DWORD))
        self.IsWindow = fn(user32, "IsWindow", w.BOOL, HWND)
        self.IsIconic = fn(user32, "IsIconic", w.BOOL, HWND)
        self.IsWindowVisible = fn(user32, "IsWindowVisible", w.BOOL, HWND)
        self.GetClientRect = fn(user32, "GetClientRect", w.BOOL, HWND, POINTER(RECT))
        self.ClientToScreen = fn(user32, "ClientToScreen", w.BOOL, HWND, POINTER(POINT))
        self.GetWindowRect = fn(user32, "GetWindowRect", w.BOOL, HWND, POINTER(RECT))
        self.EnumWindows = fn(user32, "EnumWindows", w.BOOL, self.WNDENUMPROC, w.LPARAM)
        self.GetWindowTextLengthW = fn(user32, "GetWindowTextLengthW", c_int, HWND)
        self.GetWindowTextW = fn(user32, "GetWindowTextW", c_int, HWND, w.LPWSTR, c_int)
        self.GetClassNameW = fn(user32, "GetClassNameW", c_int, HWND, w.LPWSTR, c_int)
        if ctypes.sizeof(c_void_p) == 8:
            self.GetWindowLong = fn(user32, "GetWindowLongPtrW", ctypes.c_ssize_t, HWND, c_int)
        else:
            self.GetWindowLong = fn(user32, "GetWindowLongW", ctypes.c_long, HWND, c_int)
        self.PrintWindow = fn(user32, "PrintWindow", w.BOOL, HWND, HDC, w.UINT)
        self.ScreenToClient = fn(user32, "ScreenToClient", w.BOOL, HWND, POINTER(POINT))
        self.GetLayeredWindowAttributes = fn(user32, "GetLayeredWindowAttributes", w.BOOL, HWND, POINTER(w.DWORD),
                                             POINTER(ctypes.c_ubyte), POINTER(w.DWORD))
        self.GetAsyncKeyState = fn(user32, "GetAsyncKeyState", ctypes.c_short, c_int)
        self.PostMessageW = fn(user32, "PostMessageW", w.BOOL, HWND, w.UINT, w.WPARAM, w.LPARAM)
        self.CreateCompatibleDC = fn(gdi32, "CreateCompatibleDC", HDC, HDC)
        self.CreateCompatibleBitmap = fn(gdi32, "CreateCompatibleBitmap", HANDLE, HDC, c_int, c_int)
        self.SelectObject = fn(gdi32, "SelectObject", HANDLE, HDC, HANDLE)
        self.BitBlt = fn(gdi32, "BitBlt", w.BOOL, HDC, c_int, c_int, c_int, c_int, HDC, c_int, c_int, w.DWORD)
        self.GetDIBits = fn(gdi32, "GetDIBits", c_int, HDC, HANDLE, w.UINT, w.UINT, c_void_p, POINTER(BITMAPINFO), w.UINT)
        self.DeleteObject = fn(gdi32, "DeleteObject", w.BOOL, HANDLE)
        self.DeleteDC = fn(gdi32, "DeleteDC", w.BOOL, HDC)
        try:
            dwmapi = ctypes.WinDLL("dwmapi")
            self.DwmGetWindowAttribute = fn(dwmapi, "DwmGetWindowAttribute", ctypes.c_long, HWND, w.DWORD, c_void_p, w.DWORD)
        except (OSError, AttributeError):
            self.DwmGetWindowAttribute = None
        # (the scale a window is made for, and its screen's: Windows 10 1607 and 8.1 on)
        try:
            self.GetDpiForWindow = fn(user32, "GetDpiForWindow", w.UINT, HWND)
            self.MonitorFromWindow = fn(user32, "MonitorFromWindow", HANDLE, HWND, w.DWORD)
            self.GetDpiForMonitor = fn(ctypes.WinDLL("shcore"), "GetDpiForMonitor", ctypes.c_long, HANDLE, c_int,
                                       POINTER(w.UINT), POINTER(w.UINT))
        except (OSError, AttributeError):
            self.GetDpiForWindow = self.MonitorFromWindow = self.GetDpiForMonitor = None
        self.ways = WindowWays(self._take, self._screen, self._in_front)

    # ---------------------------------------------------------------- windows

    def _pid(self, hwnd) -> int:
        pid = wintypes.DWORD(0)
        self.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        return int(pid.value)

    def foreground_pid(self) -> int:
        hwnd = self.GetForegroundWindow()
        return self._pid(hwnd) if hwnd else 0

    def foreground_ghost(self) -> bool:
        """Whether the window in front is the stand-in Windows puts in place of a program's that does not answer (a
        game paused by Sluka Vision): Windows' own "Ghost", with the game's picture and place."""
        hwnd = self.GetForegroundWindow()
        if not hwnd:
            return False
        klass = ctypes.create_unicode_buffer(64)
        self.GetClassNameW(hwnd, klass, 64)
        return klass.value == "Ghost"

    def foreground_window(self, exclude) -> dict | None:
        """The window in front (Sluka Vision reads it when its key is pressed): None where it is one of the given
        programs', or the desktop."""
        hwnd = self.GetForegroundWindow()
        if not hwnd or self.IsIconic(hwnd) or self._pid(hwnd) in {int(p) for p in exclude}:
            return None
        window = self.info(hwnd)
        return None if window["class"] in SHELL_CLASSES or window["client"][2] <= 0 or window["client"][3] <= 0 else window

    def exists(self, hwnd) -> bool:
        return bool(hwnd) and bool(self.IsWindow(hwnd))

    def minimized(self, hwnd) -> bool:
        return bool(self.IsIconic(hwnd))

    def client_area(self, hwnd):
        """The window's inside, on the screen: (x, y, w, h); None for a window that is gone."""
        if not self.exists(hwnd):
            return None
        rect = RECT()
        point = POINT(0, 0)
        if not self.GetClientRect(hwnd, ctypes.byref(rect)) or not self.ClientToScreen(hwnd, ctypes.byref(point)):
            return None
        return (int(point.x), int(point.y), int(rect.right - rect.left), int(rect.bottom - rect.top))

    def info(self, hwnd) -> dict:
        length = max(0, self.GetWindowTextLengthW(hwnd))
        title = ctypes.create_unicode_buffer(length + 1)
        self.GetWindowTextW(hwnd, title, length + 1)
        klass = ctypes.create_unicode_buffer(256)
        self.GetClassNameW(hwnd, klass, 256)
        return {"hwnd": int(hwnd or 0), "pid": self._pid(hwnd), "title": title.value, "class": klass.value,
                "client": list(self.client_area(hwnd) or (0, 0, 0, 0))}

    def _cloaked(self, hwnd) -> bool:
        if self.DwmGetWindowAttribute is None:
            return False
        value = wintypes.DWORD(0)
        return self.DwmGetWindowAttribute(hwnd, DWMWA_CLOAKED, ctypes.byref(value), ctypes.sizeof(value)) == 0 and bool(value.value)

    def window_at(self, x: int, y: int, exclude) -> dict | None:
        """The window a person sees at (x, y): the topmost one there that shows, past the given programs' and past
        see-through ones (the overlays of other programs), as LunaTranslator finds it; None over the desktop."""
        found = []
        exclude = {int(p) for p in exclude}

        def each(hwnd, _lparam):
            try:
                if not self.IsWindowVisible(hwnd) or self.IsIconic(hwnd) or self._cloaked(hwnd):
                    return True
                style = self.GetWindowLong(hwnd, GWL_EXSTYLE) or 0
                if style & (WS_EX_TRANSPARENT | WS_EX_TOOLWINDOW):
                    return True
                if style & WS_EX_LAYERED:
                    alpha, flags = ctypes.c_ubyte(255), wintypes.DWORD(0)
                    if (self.GetLayeredWindowAttributes(hwnd, None, ctypes.byref(alpha), ctypes.byref(flags))
                            and flags.value & LWA_ALPHA and alpha.value < 255):
                        return True  # (half see-through)
                rect = RECT()
                if not self.GetWindowRect(hwnd, ctypes.byref(rect)):
                    return True
                if not (rect.left <= x < rect.right and rect.top <= y < rect.bottom):
                    return True
                if self._pid(hwnd) in exclude:
                    return True
                found.append(hwnd)
                return False
            except Exception:
                return True

        self.EnumWindows(self.WNDENUMPROC(each), 0)
        if not found:
            return None
        window = self.info(found[0])
        return None if window["class"] in DESKTOP_CLASSES else window

    # ---------------------------------------------------------------- pictures

    def _bits(self, dc, bitmap, w: int, h: int):
        info = BITMAPINFO()
        info.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
        info.bmiHeader.biWidth = w
        info.bmiHeader.biHeight = -h  # the top row first
        info.bmiHeader.biPlanes = 1
        info.bmiHeader.biBitCount = 32
        info.bmiHeader.biCompression = 0  # BI_RGB
        buffer = ctypes.create_string_buffer(w * h * 4)
        lines = self.GetDIBits(dc, bitmap, 0, h, buffer, ctypes.byref(info), 0)
        return buffer.raw if lines == h else None

    def _screen(self, rect):
        x, y, w, h = rect
        screen = self.GetDC(None)
        if not screen:
            return None
        memory = self.CreateCompatibleDC(screen)
        bitmap = self.CreateCompatibleBitmap(screen, w, h)
        data = None
        try:
            old = self.SelectObject(memory, bitmap)
            # (no CAPTUREBLT, as LunaTranslator takes it: with it the mouse pointer flickers at every picture)
            ok = self.BitBlt(memory, 0, 0, w, h, screen, x, y, SRCCOPY)
            self.SelectObject(memory, old)
            if ok:
                data = self._bits(screen, bitmap, w, h)
        finally:
            self.DeleteObject(bitmap)
            self.DeleteDC(memory)
            self.ReleaseDC(None, screen)
        return Image(w, h, data) if data else None

    def _window_dc(self, hwnd, rect):
        """The box out of the window's own picture (its device context), as LunaTranslator takes it first: what the
        window drew, whatever is over it -- black, for a game that draws with the graphics card past Windows."""
        x, y, w, h = rect
        corner = POINT(x, y)
        if not self.ScreenToClient(hwnd, ctypes.byref(corner)):
            return None
        source = self.GetDC(hwnd)
        if not source:
            return None
        memory = self.CreateCompatibleDC(source)
        bitmap = self.CreateCompatibleBitmap(source, w, h)
        data = None
        try:
            old = self.SelectObject(memory, bitmap)
            ok = self.BitBlt(memory, 0, 0, w, h, source, corner.x, corner.y, SRCCOPY)
            self.SelectObject(memory, old)
            if ok:
                data = self._bits(source, bitmap, w, h)
        finally:
            self.DeleteObject(bitmap)
            self.DeleteDC(memory)
            self.ReleaseDC(hwnd, source)
        if not data:
            return None
        img = Image(w, h, data)
        return None if img.blank() else img

    def _window(self, hwnd, rect):
        """The window drawn by itself (PrintWindow), as if nothing were over it; the box cut out of it."""
        frame = RECT()
        if not self.GetWindowRect(hwnd, ctypes.byref(frame)):
            return None
        ww, wh = frame.right - frame.left, frame.bottom - frame.top
        if ww <= 0 or wh <= 0:
            return None
        screen = self.GetDC(None)
        memory = self.CreateCompatibleDC(screen)
        bitmap = self.CreateCompatibleBitmap(screen, ww, wh)
        data = None
        try:
            old = self.SelectObject(memory, bitmap)
            ok = self.PrintWindow(hwnd, memory, PW_RENDERFULLCONTENT)
            self.SelectObject(memory, old)
            if ok:
                data = self._bits(screen, bitmap, ww, wh)
        finally:
            self.DeleteObject(bitmap)
            self.DeleteDC(memory)
            self.ReleaseDC(None, screen)
        if not data:
            return None
        x, y, w, h = rect
        img = Image(ww, wh, data).crop(x - frame.left, y - frame.top, w, h)
        return None if img.blank() else img

    def _stretched(self, hwnd) -> bool:
        """A window Windows enlarges (or shrinks) for its screen -- one made for another scale than the screen's 125 %
        or 150 %: its own picture is not as large as it shows, and would be read out of place."""
        if self.GetDpiForWindow is None:
            return False
        try:
            made = int(self.GetDpiForWindow(hwnd) or 0)
            monitor = self.MonitorFromWindow(hwnd, 2)  # (MONITOR_DEFAULTTONEAREST)
            x, y = wintypes.UINT(0), wintypes.UINT(0)
            if not made or not monitor or self.GetDpiForMonitor(monitor, 0, ctypes.byref(x), ctypes.byref(y)) != 0:
                return False
        except OSError:
            return False
        return bool(x.value) and made != x.value

    def _take(self, way: str, hwnd, rect):
        return self._window_dc(hwnd, rect) if way == "dc" else self._window(hwnd, rect)

    def _in_front(self, hwnd) -> bool:
        front = self.GetForegroundWindow()
        return bool(front) and (front == hwnd or self._pid(front) == self._pid(hwnd))

    def frozen(self, hwnd) -> bool:
        """Whether the window's own picture stays as it was while the game goes on (WindowWays): the screen is read."""
        return self.ways.frozen(hwnd)

    def grab(self, how: str, hwnd, rect):
        """The box's picture, and how it was taken: what the screen shows there; or ("window") the window's own
        picture -- from its device context, else drawn by itself, whichever follows the game (WindowWays) -- and the
        screen's where neither gives anything or follows the game (or where Windows enlarges the window for its
        screen: its own picture is not as it shows)."""
        if rect[2] <= 0 or rect[3] <= 0:
            return None, how
        if how == "window" and hwnd and not self._stretched(hwnd):
            img = self.ways.grab(hwnd, rect)
            if img is not None:
                return img, "window"
        return self._screen(rect), "screen"

    # ---------------------------------------------------------------- the person

    def keys(self) -> set:
        return {name for name, vk in KEYS.items() if self.GetAsyncKeyState(vk) & 0x8000}

    def select(self, native, delay: float):
        time.sleep(max(0.0, delay))
        return native.select()

    def cancel_select(self) -> None:
        """The box-dragging window closed (it is this program's only window)."""
        mine = os.getpid()
        windows = []

        def each(hwnd, _lparam):
            if self._pid(hwnd) == mine and self.IsWindowVisible(hwnd):
                windows.append(hwnd)
            return True

        self.EnumWindows(self.WNDENUMPROC(each), 0)
        for hwnd in windows:
            self.PostMessageW(hwnd, WM_CLOSE, 0, 0)


class FileDesktop:
    """A pretend screen, for the tests: what desktop.json in a folder says, read again each time --

        {"windows": [{"hwnd", "pid", "title", "class", "client": [x, y, w, h], "minimized", "gone"}],  front first
         "foreground": pid, "screen": "screen.bmp", "select": [x1, y1, x2, y2] | null, "keys": ["enter"],
         "blank": ["window"],  (ways of taking a picture that give nothing: the screen's is taken)
         "frozen": {"dc": "old.bmp", "print": "old.bmp"},  (ways of taking the window's picture that keep an old one)
         "ghost": true}  (the window in front is Windows' stand-in for one that does not answer)

    The game's own window is taken as WindowsDesktop takes it (WindowWays), its pictures the screen's but where frozen.
    """

    def __init__(self, folder: str):
        self.folder = folder
        self.ways = WindowWays(self._take, self._live, self._in_front, check=0.2)

    def _picture(self, name: str):
        try:
            with open(os.path.join(self.folder, name), "rb") as f:
                return from_bmp(f.read())
        except (OSError, ValueError):
            return None

    def _live(self, rect):
        screen = self._picture(self._state().get("screen", "screen.bmp"))
        return screen.crop(*rect) if screen is not None else None

    def _take(self, way: str, hwnd, rect):
        state = self._state()
        if "window" in state.get("blank", []):
            return None
        old = (state.get("frozen") or {}).get(way)
        picture = self._picture(old) if old else self._picture(state.get("screen", "screen.bmp"))
        return picture.crop(*rect) if picture is not None else None

    def _in_front(self, hwnd) -> bool:
        window = self._window(hwnd)
        return window is not None and window.get("pid") == self.foreground_pid()

    def frozen(self, hwnd) -> bool:
        return self.ways.frozen(hwnd)

    def _state(self) -> dict:
        try:
            with open(os.path.join(self.folder, "desktop.json"), encoding="utf-8") as f:
                return json.load(f)
        except (OSError, ValueError):
            return {}

    def _window(self, hwnd):
        for window in self._state().get("windows", []):
            if window.get("hwnd") == hwnd:
                return window
        return None

    def foreground_pid(self) -> int:
        return int(self._state().get("foreground") or 0)

    def foreground_ghost(self) -> bool:
        return bool(self._state().get("ghost"))

    def foreground_window(self, exclude) -> dict | None:
        pid = self.foreground_pid()
        if not pid or pid in {int(p) for p in exclude}:
            return None
        for window in self._state().get("windows", []):
            if window.get("pid") == pid and not window.get("gone") and not window.get("minimized"):
                found = self.info(window["hwnd"])
                return None if found.get("class") in SHELL_CLASSES else found
        return None

    def exists(self, hwnd) -> bool:
        window = self._window(hwnd)
        return window is not None and not window.get("gone")

    def minimized(self, hwnd) -> bool:
        return bool((self._window(hwnd) or {}).get("minimized"))

    def client_area(self, hwnd):
        window = self._window(hwnd)
        if window is None or window.get("gone"):
            return None
        return tuple(int(v) for v in window["client"])

    def info(self, hwnd) -> dict:
        window = self._window(hwnd) or {}
        return {"hwnd": hwnd, "pid": window.get("pid", 0), "title": window.get("title", ""), "class": window.get("class", ""),
                "client": list(window.get("client", (0, 0, 0, 0)))}

    def window_at(self, x, y, exclude):
        exclude = {int(p) for p in exclude}
        for window in self._state().get("windows", []):
            cx, cy, cw, ch = window["client"]
            if window.get("gone") or window.get("minimized") or window.get("pid") in exclude:
                continue
            if cx <= x < cx + cw and cy <= y < cy + ch:
                return self.info(window["hwnd"])
        return None

    def grab(self, how, hwnd, rect):
        if how == "window" and hwnd:
            img = self.ways.grab(hwnd, rect)
            if img is not None:
                return img, "window"
        return self._live(rect), "screen"

    def keys(self) -> set:
        return set(self._state().get("keys", []))

    def select(self, native, delay):
        time.sleep(min(0.05, max(0.0, delay)))
        chosen = self._state().get("select")
        return tuple(chosen) if chosen else None

    def cancel_select(self) -> None:
        pass


# ======================================================================================== NativeUtils.dll


class Native:
    """LunaTranslator's NativeUtils.dll, loaded when first wanted: Windows' OCR, the box dragged over the screen, and
    Google Lens' requests -- each declared as LunaTranslator's NativeUtils.py declares it."""

    OCR_CB = CFUNCTYPE(None, c_float, c_float, c_float, c_float, c_wchar_p)
    LANGUAGE_CB = CFUNCTYPE(None, c_wchar_p, c_wchar_p)
    BYTES_CB = CFUNCTYPE(None, POINTER(c_char), c_size_t)
    LENS_CB = CFUNCTYPE(None, c_char_p, c_float, c_float, c_float, c_float)
    SELECT_CB = CFUNCTYPE(None, c_int, c_int, c_int, c_int, c_int, c_int, POINTER(c_char), c_size_t)

    def __init__(self, path: str):
        self.path = path
        self.dll = None
        self._lock = threading.Lock()

    def load(self):
        with self._lock:
            if self.dll is None:
                if WINDOWS and struct.calcsize("P") != 8:
                    raise OSError("NativeUtils.dll is 64-bit, and this Python is 32-bit")
                _add_dll_directory(os.path.dirname(os.path.abspath(self.path)))
                dll = ctypes.CDLL(self.path)

                def fn(name, argtypes, restype=None):
                    f = getattr(dll, name)
                    f.argtypes = argtypes
                    f.restype = restype

                fn("winrt_OCR", (c_void_p, c_size_t, c_wchar_p, c_void_p))
                fn("winrt_OCR_check_language_valid", (c_wchar_p,), c_bool)
                fn("winrt_OCR_get_AvailableRecognizerLanguages", (c_void_p,))
                fn("glens_create_request", (c_uint64, c_char_p, c_size_t, c_char_p, c_size_t, c_int32, c_int32, self.BYTES_CB))
                fn("glens_parse_response", (c_char_p, c_size_t, self.LENS_CB))
                fn("CreateSelectRangeWindow", (c_void_p, c_float, c_int, c_int, c_int, c_float, self.SELECT_CB))
                self.dll = dll
        return self.dll

    def ocr_languages(self) -> list:
        found = []
        cb = self.LANGUAGE_CB(lambda tag, name: found.append((tag or "", name or "")))
        self.load().winrt_OCR_get_AvailableRecognizerLanguages(cb)
        return found

    def ocr_supported(self, tag: str) -> bool:
        return bool(self.load().winrt_OCR_check_language_valid(tag))

    def ocr(self, picture: bytes, tag: str) -> list:
        lines = []
        cb = self.OCR_CB(lambda x1, y1, x2, y2, text: lines.append((x1, y1, x2, y2, text or "")))
        buffer = ctypes.create_string_buffer(picture, len(picture))
        self.load().winrt_OCR(buffer, len(picture), tag, cb)
        return lines


    def lens_request(self, number: int, nonce: bytes, png: bytes, w: int, h: int) -> bytes:
        got = []
        cb = self.BYTES_CB(lambda ptr, size: got.append(ctypes.string_at(ptr, size)))
        self.load().glens_create_request(number, nonce, len(nonce), png, len(png), w, h, cb)
        if not got:
            raise RuntimeError("the request to Google Lens could not be written")
        return got[0]

    def lens_parse(self, data: bytes) -> list:
        found = []
        cb = self.LENS_CB(lambda text, x, y, w, h: found.append(((text or b"").decode("utf-8", "replace"), x, y, w, h)))
        self.load().glens_parse_response(data, len(data), cb)
        return found

    def select(self, color=(64, 156, 255), dim: float = 0.35, width: float = 2.0):
        """LunaTranslator's own box-dragging window, over the whole screen (it waits, in a loop of its own, until the
        box is dragged, or right-click or Escape): the box on the screen, or None."""
        got = []

        def done(x1, y1, x2, y2, xoff, yoff, _picture, _size):
            got.append((min(x1, x2) + xoff, min(y1, y2) + yoff, max(x1, x2) + xoff, max(y1, y2) + yoff))

        cb = self.SELECT_CB(done)
        self.load().CreateSelectRangeWindow(None, dim, color[0], color[1], color[2], width, cb)
        return got[0] if got else None


# ======================================================================================== the readers


class Unavailable(Exception):
    """A reader that cannot be used here (and why)."""


class _OrtApiBase(Structure):
    """ONNX Runtime's OrtApiBase (onnxruntime_c_api.h): the way to its C API, whatever its version."""
    _fields_ = [("GetApi", CFUNCTYPE(c_void_p, ctypes.c_uint32)), ("GetVersionString", CFUNCTYPE(c_char_p))]


_ORT_QUIET = False


def _say(text: str) -> None:
    """A note for the log, from code outside the program's main loop (main() points this at the log)."""


def trace_events_off(ort) -> str:
    """ONNX Runtime's trace events turned off, through the C API of ort (the library, loaded): what came of it.

    The call is DisableTelemetryEvents: the seventh function of the C API's table (OrtApi in onnxruntime_c_api.h:
    CreateStatus, GetErrorCode, GetErrorMessage, CreateEnv, CreateEnvWithCustomLogger, EnableTelemetryEvents,
    DisableTelemetryEvents, ...), which ONNX Runtime never reorders, and which works on the whole program -- the
    environment it is given is not used, so none is made for it."""
    ort.OrtGetApiBase.argtypes = ()
    ort.OrtGetApiBase.restype = POINTER(_OrtApiBase)
    base = ort.OrtGetApiBase().contents
    version = (base.GetVersionString() or b"").decode("ascii", "replace")
    api = base.GetApi(1)
    if not api:
        return f"ONNX Runtime {version} gave no C API: its trace events are left as they are"
    table = ctypes.cast(api, POINTER(c_void_p))
    failed = CFUNCTYPE(c_void_p, c_void_p)(table[6])(None)
    return f"ONNX Runtime {version}: its trace events {'could not be turned off' if failed else 'are off'}"


def quiet_onnxruntime() -> None:
    """ONNX Runtime's own trace events turned off, for this program.

    Microsoft's builds of ONNX Runtime (onnxruntime.dll here is one) note how they are used as trace events of
    Windows' own (ETW), which Windows may send to Microsoft as part of its diagnostic data, as its privacy settings
    allow; Microsoft says so in ONNX Runtime's Privacy.md, and lets programs turn them off.  Sluka sends nothing of the
    kind, so neither does the OCR it runs.  Done once ONNX Runtime is loaded (by CVUtils.dll), before the OCR starts,
    on the very library loaded (trace_events_off); where anything of it fails, the OCR goes on as before."""
    global _ORT_QUIET
    if _ORT_QUIET or not WINDOWS:
        return
    _ORT_QUIET = True
    try:
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.GetModuleHandleW.argtypes = (c_wchar_p,)
        kernel32.GetModuleHandleW.restype = c_void_p
        module = kernel32.GetModuleHandleW("onnxruntime.dll")
        if not module:
            _say("ONNX Runtime is not loaded: its trace events are left as they are")
            return
        _say(trace_events_off(ctypes.CDLL("onnxruntime.dll", handle=module)))  # (the one loaded, not loaded again)
    except Exception as err:  # (never in the way of the OCR itself)
        _say(f"ONNX Runtime's trace events could not be turned off: {err!r}")


class BuiltinReader:
    """LunaTranslator's own OCR: CVUtils.dll, with PaddleOCR's PP-OCRv5 model run by ONNX Runtime (LunaTranslator's
    CVUtils.py and ocrengines/local.py, its default reader)."""

    name = "builtin"
    DETECT_CB = CFUNCTYPE(None, c_float, c_float, c_float, c_float, c_float, c_float, c_float, c_float, c_char_p)
    ERROR_CB = CFUNCTYPE(None, c_char_p)
    FILES = ("CVUtils.dll", "NativeUtils.dll", "onnxruntime.dll", "model/det.onnx", "model/rec.onnx", "model/dict.txt")
    THREADS = 4  # (LunaTranslator's own setting)

    def __init__(self, folder: str, library: str = ""):
        self.folder = os.path.join(folder, "ocr")
        self.library = library or os.path.join(self.folder, "CVUtils.dll")
        self.dll = None
        self.handle = None
        self._keep = []
        self._lock = threading.Lock()

    def _load(self):
        if self.dll is None:
            if WINDOWS and struct.calcsize("P") != 8:
                raise Unavailable("the built-in OCR is 64-bit, and this Python is 32-bit")
            _add_dll_directory(os.path.dirname(os.path.abspath(self.library)))
            dll = ctypes.CDLL(self.library)

            def fn(name, argtypes, restype=None):
                f = getattr(dll, name)
                f.argtypes = argtypes
                f.restype = restype

            fn("OcrLoadRuntime", (), c_bool)
            fn("OcrInit", (c_wchar_p, c_wchar_p, c_wchar_p, c_int32, c_bool, c_uint64, c_char_p, self.ERROR_CB), c_void_p)
            fn("OcrDetect", (c_void_p, c_void_p, c_int32, self.DETECT_CB, self.ERROR_CB))
            fn("OcrDestroy", (c_void_p,))
            fn("cvMatFromBGR888", (c_void_p, c_int, c_int, c_int), c_void_p)
            fn("cvMatDestroy", (c_void_p,))
            self.dll = dll
        return self.dll

    def check(self, lang: str = "") -> dict:
        names = self.FILES if self.library == os.path.join(self.folder, "CVUtils.dll") else self.FILES[3:]
        missing = [n for n in names if not os.path.isfile(os.path.join(self.folder, n))]
        if missing:
            return {"ok": False, "why": f"files missing from {self.folder}: {', '.join(missing)} (unpack Sluka Desktop's zip "
                                        "again; an antivirus may have taken them)"}
        try:
            with self._lock:
                if not self._load().OcrLoadRuntime():
                    return {"ok": False, "why": self._no_runtime()}
                quiet_onnxruntime()
        except Unavailable as err:
            return {"ok": False, "why": str(err)}
        except OSError as err:
            return {"ok": False, "why": f"CVUtils.dll could not be loaded ({err})"}
        return {"ok": True, "why": "offline, in the engine folder: Japanese, Chinese and English (PP-OCRv5)"}

    @staticmethod
    def _no_runtime() -> str:
        old = runtime_too_old()
        if old:
            return (f"its ONNX Runtime needs Microsoft's C++ runtime 14.40 or later, and this Python came with an older one "
                    f"({old}): the newest Python from python.org has a newer one. Meanwhile Windows' own "
                    "OCR reads the screen")
        return "its ONNX Runtime (onnxruntime.dll, in the engine folder's ocr folder) could not be started"

    def prepare(self) -> None:
        with self._lock:
            dll = self._load()
            if self.handle:
                return
            if not dll.OcrLoadRuntime():
                raise Unavailable("The built-in OCR cannot start here: " + self._no_runtime() + ".")
            quiet_onnxruntime()
            errors = []
            cb = self.ERROR_CB(errors.append)
            model = os.path.join(self.folder, "model")
            handle = dll.OcrInit(os.path.join(model, "det.onnx"), os.path.join(model, "rec.onnx"), os.path.join(model, "dict.txt"),
                                 self.THREADS, False, 0, b"CPU", cb)
            if errors:
                raise Unavailable("The built-in OCR's model could not be loaded: " + _c_text(errors[0]))
            if not handle:
                raise Unavailable("The built-in OCR's model could not be loaded.")
            self.handle = handle
            self._keep.append(cb)

    def recognize(self, img: Image, settings: dict) -> list:
        self.prepare()
        with self._lock:
            bgr = img.bgr()
            buffer = ctypes.create_string_buffer(bgr, len(bgr))
            mat = self.dll.cvMatFromBGR888(buffer, img.w, img.h, img.w * 3)
            if not mat:
                raise RuntimeError("the picture could not be handed to the OCR")
            found, errors = [], []

            def each(x1, y1, x2, y2, x3, y3, x4, y4, text):
                found.append(((x1, y1, x2, y2, x3, y3, x4, y4), (text or b"").decode("utf-8", "replace")))

            cb, err = self.DETECT_CB(each), self.ERROR_CB(errors.append)
            try:
                self.dll.OcrDetect(self.handle, mat, DIRECTIONS.get(settings.get("direction"), 2), cb, err)
            finally:
                self.dll.cvMatDestroy(mat)
            if errors:
                raise RuntimeError("the OCR failed: " + _c_text(errors[0]))
            return found

    def close(self) -> None:
        with self._lock:
            if self.dll is not None and self.handle:
                self.dll.OcrDestroy(self.handle)
            self.handle = None


class WindowsReader:
    """Windows' own OCR (Windows.Media.Ocr), through NativeUtils.dll (LunaTranslator's ocrengines/windowsocr.py)."""

    name = "windows"
    MIN_HEIGHT = 40  # (smaller letters it does not read: LunaTranslator makes the picture this high at least)

    def __init__(self, native: Native, fake: bool = False):
        self.native = native
        self.fake = fake
        self._valid: dict[str, bool] = {}

    def check(self, lang: str = "ja") -> dict:
        if not WINDOWS and not self.fake:
            return {"ok": False, "why": "Windows' own OCR is Windows'"}
        try:
            ro_initialize()
            languages = self.native.ocr_languages()
            ok = self.native.ocr_supported(lang or "ja")
        except (OSError, AttributeError) as err:
            return {"ok": False, "why": f"NativeUtils.dll could not be loaded ({err})"}
        names = ", ".join(name for _tag, name in languages) or "none"
        if ok:
            return {"ok": True, "why": f"offline, Windows' own; its languages here: {names}", "languages": [list(x) for x in languages]}
        return {"ok": False, "languages": [list(x) for x in languages],
                "why": f"Windows has no OCR for {lang or 'ja'} here (its OCR languages: {names}). A language is added, with its "
                       "OCR, in Settings > Time & language > Language & region; Japanese's alone, in PowerShell as "
                       "administrator: Add-WindowsCapability -Online -Name \"Language.OCR~~~ja-JP~0.0.1.0\""}

    def prepare(self) -> None:
        ro_initialize()
        self.native.load()

    def recognize(self, img: Image, settings: dict) -> list:
        ro_initialize()
        lang = settings.get("lang") or "ja"
        if lang not in self._valid:
            # (asked once a language, as LunaTranslator asks before each read: Windows' OCR is not to be given another)
            self._valid[lang] = bool(self.native.ocr_supported(lang))
        if not self._valid[lang]:
            raise Unavailable(self.check(lang)["why"] + ".")
        factor = min(8, math.ceil(self.MIN_HEIGHT / img.h)) if 0 < img.h < self.MIN_HEIGHT else 1
        picture = img.scaled(factor)
        lines = self.native.ocr(to_bmp(picture), lang)
        return [((x1 / factor, y1 / factor, x2 / factor, y2 / factor), text) for x1, y1, x2, y2, text in lines]

    def close(self) -> None:
        pass


def socks_connect(proxy: str, host: str, port: int, timeout: float) -> socket.socket:
    """A connection to host:port through a SOCKS5 proxy (Tor's), the name looked up by the proxy."""
    at, _, number = proxy.rpartition(":")
    sock = socket.create_connection((at or "127.0.0.1", int(number or 9050)), timeout=timeout)

    def take(n: int) -> bytes:
        data = b""
        while len(data) < n:
            more = sock.recv(n - len(data))
            if not more:
                raise OSError("the SOCKS proxy closed the connection")
            data += more
        return data

    try:
        sock.sendall(b"\x05\x01\x00")
        if take(2) != b"\x05\x00":
            raise OSError("the SOCKS proxy wants a sign-in Sluka does not give")
        name = host.encode("idna")
        sock.sendall(b"\x05\x01\x00\x03" + bytes([len(name)]) + name + struct.pack(">H", port))
        head = take(4)
        if head[1] != 0:
            raise OSError(f"the SOCKS proxy could not connect to {host} (its answer: {head[1]})")
        take({1: 4, 4: 16}.get(head[3]) or take(1)[0])
        take(2)
    except Exception:
        sock.close()
        raise
    return sock


class SocksHTTPConnection(http.client.HTTPConnection):
    """HTTP through a SOCKS5 proxy (Tor), for Sluka set to go online through it."""

    def __init__(self, host: str, port: int, socks_at: str, timeout: float = 40):
        super().__init__(host, port, timeout=timeout)
        self._socks = socks_at

    def connect(self):
        self.sock = socks_connect(self._socks, self.host, self.port, self.timeout)


class SocksHTTPSConnection(http.client.HTTPSConnection):
    """HTTPS through a SOCKS5 proxy (Tor)."""

    def __init__(self, host: str, port: int, socks_at: str, timeout: float = 40):
        super().__init__(host, port, timeout=timeout, context=ssl.create_default_context())
        self._socks = socks_at

    def connect(self):
        sock = socks_connect(self._socks, self.host, self.port, self.timeout)
        self.sock = self._context.wrap_socket(sock, server_hostname=self.host)


class LensReader:
    """Google Lens: the picture sent to Google, as LunaTranslator's ocrengines/googlelens.py sends it (NativeUtils.dll
    writes the request and reads the answer)."""

    name = "lens"
    ENDPOINT = "https://lensfrontend-pa.googleapis.com/v1/crupload"
    #: (Google's own key for its Lens web page, as LunaTranslator and owocr send it)
    KEY = "AIzaSyDr2UxVnv_U85AbhhY8XSHSIavUW0DC-sY"

    def __init__(self, native: Native, network: dict, endpoint: str = ""):
        self.native = native
        self.network = network
        self.endpoint = endpoint or self.ENDPOINT

    def check(self, lang: str = "") -> dict:
        if self.network.get("mode") == "offline":
            return {"ok": False, "why": "Sluka is set to stay offline ([network] mode in config.ini)"}
        try:
            self.native.load()
        except (OSError, AttributeError) as err:
            return {"ok": False, "why": f"NativeUtils.dll could not be loaded ({err})"}
        through = " through Tor" if self.network.get("mode") == "tor" else ""
        return {"ok": True, "why": f"online{through}: each picture of the box is sent to Google"}

    def prepare(self) -> None:
        self.native.load()

    def _post(self, body: bytes) -> bytes:
        url = urllib.parse.urlsplit(self.endpoint)
        headers = {"Content-Type": "application/x-protobuf", "X-Goog-Api-Key": self.KEY, "Sec-Fetch-Site": "none",
                   "Sec-Fetch-Mode": "no-cors", "Sec-Fetch-Dest": "empty"}
        tor = self.network.get("mode") == "tor"
        proxy = self.network.get("socks") or "127.0.0.1:9050"
        if url.scheme == "http":  # (the tests' stand-in for Google)
            conn = (SocksHTTPConnection(url.hostname, url.port or 80, proxy) if tor
                    else http.client.HTTPConnection(url.hostname, url.port or 80, timeout=30))
        elif tor:
            conn = SocksHTTPSConnection(url.hostname, url.port or 443, proxy)
        else:
            conn = http.client.HTTPSConnection(url.hostname, url.port or 443, timeout=30, context=ssl.create_default_context())
        try:
            conn.request("POST", (url.path or "/") + (f"?{url.query}" if url.query else ""), body=body, headers=headers)
            response = conn.getresponse()
            data = response.read()
        finally:
            conn.close()
        if response.status != 200:
            raise RuntimeError(f"Google Lens answered {response.status}")
        return data

    def recognize(self, img: Image, settings: dict) -> list:
        if self.network.get("mode") == "offline":
            raise Unavailable("Sluka is set to stay offline")
        request = self.native.lens_request(random.getrandbits(64), os.urandom(16), to_png(img), img.w, img.h)
        found = []
        for text, cx, cy, bw, bh in self.native.lens_parse(self._post(request)):
            x, y, half_w, half_h = cx * img.w, cy * img.h, bw * img.w / 2, bh * img.h / 2
            found.append(((x - half_w, y - half_h, x + half_w, y + half_h), text))
        return found

    def layout(self, img: Image) -> list:
        """A whole window read for Sluka Vision: every paragraph, line and word Google Lens found, where each is and
        how it is tilted (lens_layout) -- the request written and the answer read here, as NativeUtils keeps only the
        paragraphs.  A window larger than full HD is sent smaller."""
        if self.network.get("mode") == "offline":
            raise Unavailable("Sluka is set to stay offline ([network] mode in config.ini): Google Lens is not asked")
        scale = min(1.0, LENS_SIDE / max(1, img.w, img.h), math.sqrt(LENS_AREA / max(1, img.w * img.h)))
        sent = img.shrunk(round(img.w * scale), round(img.h * scale)) if scale < 1.0 else img
        body = lens_request(to_png_up(sent), sent.w, sent.h, random.getrandbits(64), os.urandom(16))
        return lens_layout(self._post(body), (sent.w, sent.h), (img.w, img.h))

    def close(self) -> None:
        pass


# ======================================================================================== reading the box


def place(area, box, client) -> tuple:
    """The box on the screen, now: kept where it was in the window's inside, and grown with it."""
    ax, ay, aw, ah = area
    bx, by, bw, bh = box
    cw, ch = client if client and client[0] > 0 and client[1] > 0 else (aw, ah)
    sx, sy = aw / cw, ah / ch
    x, y = ax + round(bx * sx), ay + round(by * sy)
    w, h = round(bw * sx), round(bh * sy)
    x = max(ax, min(x, ax + aw - 1))
    y = max(ay, min(y, ay + ah - 1))
    return (x, y, max(1, min(w, ax + aw - x)), max(1, min(h, ay + ah - y)))


class Watch:
    """The box of a window watched, and read when it shows new text: when the text changes and has settled
    ("auto"), every few seconds where it changed ("interval"), or after a click, Enter or Space in the game
    ("trigger"), as LunaTranslator's three ways."""

    TICK = 0.2
    TICK_WINDOW = 0.5
    STILL = 0.0015  # less of the box than this changed since it last moved: it is still (a "。" is more)
    SAME = 0.0015   # ... since a picture read before: nothing new to read
    SETTLE = 0.35   # still this long, the text has come (letters that come one by one)
    GAP = 0.3       # the least time between two reads
    STALE = 2.5     # a box that never stops changing (pictures moving behind it) is read this often
    PRESS = frozenset({"click", "enter", "space"})
    RELEASE = frozenset({"ctrl"})

    def __init__(self, daemon: "Ocrd", params: dict):
        self.d = daemon
        self.p = params
        self.stop_event = threading.Event()
        self.once_event = threading.Event()
        self.thread = threading.Thread(target=self._run, name="ocr-watch", daemon=True)
        self._state = None
        self._errors: dict[str, float] = {}

    def start(self) -> None:
        self.thread.start()

    def stop(self) -> None:
        self.stop_event.set()
        self.once_event.set()

    def status(self, state: str, text: str = "") -> None:
        if (state, text) != self._state:
            self._state = (state, text)
            self.d.emit({"ev": "status", "state": state, "text": text})

    def error(self, text: str) -> None:
        now = time.monotonic()
        if now - self._errors.get(text, -1e9) > 15:
            self._errors[text] = now
            self.d.log(f"error: {text}")
            self.d.emit({"ev": "error", "text": text})

    def _run(self) -> None:
        try:
            self._watch()
        except Exception as err:
            self.d.log("the watch failed:\n" + traceback.format_exc())
            self.d.emit({"ev": "error", "text": f"Reading stopped: {err}"})
            self.d.emit({"ev": "stopped", "why": "error"})

    def _watch(self) -> None:
        p = self.p
        self.status("loading", "")
        reader, why = self.d.pick(p["engine"], p.get("lang") or "ja")
        if reader is None:
            self.d.emit({"ev": "error", "text": why})
            self.d.emit({"ev": "stopped", "why": "unavailable"})
            return
        try:
            reader.prepare()
        except Unavailable as err:
            self.d.emit({"ev": "error", "text": str(err)})
            self.d.emit({"ev": "stopped", "why": "unavailable"})
            return
        except OSError as err:
            self.d.emit({"ev": "error", "text": f"The reader could not be started: {err}"})
            self.d.emit({"ev": "stopped", "why": "unavailable"})
            return
        desktop = self.d.desktop
        hwnd = p["hwnd"]
        allowed = {int(x) for x in p.get("allow", [])} | {int(p.get("pid") or 0), os.getpid()}
        mode = p["mode"]
        interval = max(0.3, float(p.get("interval") or 1.5))
        # (a window drawn by itself costs more than a piece of the screen: looked at less often)
        tick = self.TICK if p.get("capture") != "window" or not hwnd else self.TICK_WINDOW
        told_how = ""
        anchor = None  # the picture as it was when it last moved
        new = True
        still_since = time.monotonic()
        read_sigs: collections.deque = collections.deque(maxlen=3)
        last_read = time.monotonic() - self.STALE + 1.0  # (the first read too waits for the box to settle, a second at most)
        last_text = ""
        armed = 0.0
        keys_before: set = set()
        self.d.emit({"ev": "watching", "hwnd": hwnd, "engine": reader.name, "mode": mode})
        while not self.stop_event.is_set():
            once = self.once_event.is_set()
            if not once:
                self.once_event.wait(tick)
                once = self.once_event.is_set()
            self.once_event.clear()
            if self.stop_event.is_set():
                break
            if hwnd:
                area = desktop.client_area(hwnd)
                if area is None:
                    self.status("gone", "The window has closed.")
                    self.d.emit({"ev": "stopped", "why": "gone"})
                    return
                if desktop.minimized(hwnd):
                    self.status("hidden", "The game's window is minimized.")
                    continue
                if p.get("front", True) and not once and desktop.foreground_pid() not in allowed:
                    self.status("behind", "Another program's window is in front: reading waits for the game.")
                    continue
                rect = place(area, p["box"], p.get("client"))
            else:
                rect = tuple(p["box"])  # (a box on the screen, in no window)
            try:
                img, how = desktop.grab(p.get("capture", "screen"), hwnd, rect)
            except (OSError, ValueError) as err:
                self.error(f"No picture of the box could be taken: {err}")
                img, how = None, ""
            if img is None or not img.w or not img.h:
                self.status("nopicture", "No picture of the box could be taken.")
                continue
            if how != told_how:
                told_how = how
                event = {"ev": "capture", "how": how}
                if how == "screen" and hwnd and getattr(desktop, "frozen", lambda _h: False)(hwnd):
                    event["why"] = "frozen"  # (the game's own picture stays as it was: the screen has to be read)
                self.d.emit(event)
            now = time.monotonic()
            sig = signature(img)
            # Measured against the picture as it last moved (a slow fade adds up), and only where it moved: whether
            # it is one read before (the arrow that blinks at the end of a line, there and gone again) is known.
            if anchor is None or (sig != anchor and difference(sig, anchor) > self.STILL):
                anchor = sig
                still_since = now
                new = not any(sig == seen or difference(sig, seen) <= self.SAME for seen in read_sigs)
            if mode == "trigger":
                keys = desktop.keys()
                pressed = ((keys - keys_before) & self.PRESS) or ((keys_before - keys) & self.RELEASE)
                keys_before = keys
                if pressed and (not hwnd or desktop.foreground_pid() == p.get("pid")):
                    armed = now  # (a click in the game itself: not one in Sluka's window)
            read = once
            if not read:
                if mode == "auto":
                    read = new and now - last_read >= self.GAP and (
                        now - still_since >= self.SETTLE or now - last_read >= self.STALE)
                elif mode == "interval":
                    read = new and now - last_read >= interval
                elif mode == "trigger" and armed and now - armed >= 0.15:
                    if now - still_since >= 0.3 or now - armed >= 3.0:
                        read = True
                        armed = 0.0
            if not read:
                self.status("waiting", "")
                continue
            self.status("reading", "")
            started = time.monotonic()
            try:
                found = reader.recognize(img, p)
            except Unavailable as err:
                self.d.emit({"ev": "error", "text": str(err)})
                self.d.emit({"ev": "stopped", "why": "unavailable"})
                return
            except Exception as err:
                self.d.log("a read failed:\n" + traceback.format_exc())
                self.error(f"The box could not be read: {err}")
                last_read = now
                time.sleep(1.0)
                continue
            ms = int((time.monotonic() - started) * 1000)
            last_read = now
            read_sigs.append(sig)
            new = False
            text, lines = arrange(found, p.get("direction", "auto"), bool(p.get("furigana", True)))
            if not text:
                if once:  # (asked for: said, though nothing was read)
                    self.d.emit({"ev": "text", "text": "", "engine": reader.name, "ms": ms, "lines": 0, "forced": True,
                                 "box": list(rect)})
                self.status("waiting", "")
                continue
            if not once and same_text(text, last_text):
                continue
            last_text = text
            self.d.log(f"read ({reader.name}, {ms} ms): {text[:200]!r}")
            self.d.emit({"ev": "text", "text": text, "engine": reader.name, "ms": ms, "lines": lines, "forced": bool(once),
                         "box": list(rect)})
        self.d.emit({"ev": "stopped", "why": "asked"})


# ======================================================================================== Sluka Vision: a whole window

#: A window wider or taller than this, or of more pixels than this, is made smaller before it is sent to Google Lens
#: (a full HD window goes as it is).
LENS_SIDE = 1920
LENS_AREA = 2_100_000
#: Google Lens' ways of writing a paragraph (lens_overlay_text.proto's WritingDirection).
LEFT_TO_RIGHT, RIGHT_TO_LEFT, TOP_TO_BOTTOM = 0, 1, 2
KANJI = re.compile("[㐀-䶿一-鿿豈-﫿々〆〇ヵヶ]")
KANA_LINE = re.compile(r"^[぀-ゟ゠-ヿㇰ-ㇿｦ-ﾟ・ー\s]+$")

# Google Lens' request and answer are protocol buffers, as Chromium's lens_overlay protos define them
# (third_party/lens_server_proto, under Chromium's BSD licence, which LunaTranslator's source has): the few fields
# used here are written and read by hand, by their numbers.


def _pb_varint(value: int) -> bytes:
    value &= (1 << 64) - 1
    out = bytearray()
    while value > 0x7F:
        out.append(value & 0x7F | 0x80)
        value >>= 7
    out.append(value)
    return bytes(out)


def _pb(field: int, value) -> bytes:
    """One field: a whole number, or bytes (a string, or a message written already)."""
    if isinstance(value, int):
        return _pb_varint(field << 3) + _pb_varint(value)
    return _pb_varint(field << 3 | 2) + _pb_varint(len(value)) + bytes(value)


def _pb_read(data: bytes, at: int) -> tuple[int, int]:
    value = shift = 0
    while True:
        if at >= len(data):
            raise ValueError("an answer cut short")
        byte = data[at]
        at += 1
        value |= (byte & 0x7F) << shift
        if byte < 0x80:
            return value, at
        shift += 7
        if shift > 70:
            raise ValueError("a number too long")


def _pb_fields(data: bytes):
    """The fields of a message, in order: (number, wire type, value)."""
    at, end = 0, len(data)
    while at < end:
        key, at = _pb_read(data, at)
        field, wire = key >> 3, key & 7
        if wire == 0:
            value, at = _pb_read(data, at)
        elif wire == 1:
            value, at = data[at:at + 8], at + 8
        elif wire == 2:
            size, at = _pb_read(data, at)
            value, at = data[at:at + size], at + size
        elif wire == 5:
            value, at = data[at:at + 4], at + 4
        else:
            raise ValueError(f"a field of wire type {wire}")
        if at > end:
            raise ValueError("an answer cut short")
        yield field, wire, value


def _pb_all(data: bytes, field: int) -> list:
    """Each value of a field that is a string, bytes or a message."""
    return [value for number, wire, value in _pb_fields(data) if number == field and wire == 2]


def _pb_number(data: bytes, field: int, default: int = 0) -> int:
    for number, wire, value in _pb_fields(data):
        if number == field and wire == 0:
            default = value
    return default


def lens_request(png: bytes, w: int, h: int, number: int, nonce: bytes) -> bytes:
    """Google Lens' request for a picture (a LensOverlayServerRequest), as LunaTranslator's NativeUtils writes one:
    a request id, the web as the platform and Chromium as the surface, Lens' own filter, and the picture."""
    request_id = _pb(1, number) + _pb(4, nonce)
    client = _pb(1, 3) + _pb(2, 4) + _pb(4, b"") + _pb(17, _pb(1, _pb(1, 7)))
    context = _pb(3, request_id) + _pb(4, client)
    image = _pb(1, _pb(1, png)) + _pb(3, _pb(1, w) + _pb(2, h))
    return _pb(1, _pb(1, context) + _pb(3, image))


def js_len(text: str) -> int:
    """A text's length as JavaScript counts it (UTF-16 units): where a word is in its line, to the overlay's page."""
    return len(text.encode("utf-16-le")) // 2


def _lens_box(geometry: bytes, sent, size):
    """A Geometry's CenterRotatedBox as [cx, cy, w, h, angle] in the window's pixels (the angle in radians,
    clockwise); None where it has none."""
    found = _pb_all(geometry, 1)
    if not found:
        return None
    floats, kind = {}, 1
    for number, wire, value in _pb_fields(found[0]):
        if wire == 5 and 1 <= number <= 5:
            floats[number] = struct.unpack("<f", value)[0]
        elif number == 6 and wire == 0:
            kind = value
    cx, cy, bw, bh, angle = (floats.get(i, 0.0) for i in range(1, 6))
    if kind == 2:  # in the pixels of the picture sent, not as shares of it
        sw, sh = max(1, sent[0]), max(1, sent[1])
        cx, cy, bw, bh = cx / sw, cy / sh, bw / sw, bh / sh
    w, h = size
    values = (cx * w, cy * h, abs(bw) * w, abs(bh) * h, angle)
    if not all(math.isfinite(v) for v in values):
        return None
    return [round(values[0], 1), round(values[1], 1), round(values[2], 1), round(values[3], 1), round(values[4], 4)]


def lens_layout(data: bytes, sent, size) -> list[dict]:
    """Google Lens' answer (a LensOverlayServerResponse) as what it found, paragraph by paragraph --
    [{"dir": LEFT_TO_RIGHT | RIGHT_TO_LEFT | TOP_TO_BOTTOM, "box", "lines": [{"text", "box", "words": [[start, end,
    box]]}]}] -- each box in the window's pixels (``size``; ``sent``: the size of the picture sent), each word by where
    it is in its line's text, as JavaScript counts."""
    out = []
    for objects in _pb_all(data, 2):
        for text in _pb_all(objects, 3):
            for layout in _pb_all(text, 1):
                for paragraph in _pb_all(layout, 1):
                    lines = []
                    for line in _pb_all(paragraph, 2):
                        said, words = "", []
                        for word in _pb_all(line, 1):
                            plain = b"".join(_pb_all(word, 2)).decode("utf-8", "replace")
                            gap = b"".join(_pb_all(word, 3)).decode("utf-8", "replace")
                            shape = _pb_all(word, 4)
                            start = js_len(said)
                            said += plain
                            box = _lens_box(shape[0], sent, size) if shape else None
                            if plain.strip() and box:
                                words.append([start, js_len(said), box])
                            said += gap
                        shape = _pb_all(line, 2)
                        box = _lens_box(shape[0], sent, size) if shape else None
                        said = said.rstrip()
                        if said.strip() and box and box[2] > 0 and box[3] > 0:
                            lines.append({"text": said, "box": box, "words": words})
                    if lines:
                        shape = _pb_all(paragraph, 3)
                        out.append({"dir": _pb_number(paragraph, 4), "box": _lens_box(shape[0], sent, size) if shape else None,
                                    "lines": lines})
    errors = _pb_all(data, 1)
    if errors and not out:
        raise RuntimeError(f"Google Lens answered with an error (of type {_pb_number(errors[0], 1)})")
    return out


def _quad_box(box) -> list | None:
    """A reader's box -- four corners, or two -- as [cx, cy, w, h, angle], tilted as its first side is (less than
    45 degrees either way: a side nearer upright is taken for the box's height)."""
    try:
        values = [float(v) for v in box]
    except (TypeError, ValueError):
        return None
    if len(values) >= 8:
        points = list(zip(values[0:8:2], values[1:8:2]))
        cx, cy = sum(p[0] for p in points) / 4, sum(p[1] for p in points) / 4
        (x1, y1), (x2, y2), (x3, y3) = points[0], points[1], points[2]
        w, h = math.hypot(x2 - x1, y2 - y1), math.hypot(x3 - x2, y3 - y2)
        angle = math.atan2(y2 - y1, x2 - x1)
        while angle > math.pi / 4:
            angle -= math.pi / 2
            w, h = h, w
        while angle <= -math.pi / 4:
            angle += math.pi / 2
            w, h = h, w
    elif len(values) >= 4:
        x1, y1, x2, y2 = bounds(values)
        cx, cy, w, h, angle = (x1 + x2) / 2, (y1 + y2) / 2, x2 - x1, y2 - y1, 0.0
    else:
        return None
    if not all(math.isfinite(v) for v in (cx, cy, w, h, angle)) or w <= 0 or h <= 0:
        return None
    return [round(cx, 1), round(cy, 1), round(w, 1), round(h, 1), round(angle, 4)]


def paragraphs_of(found) -> list[dict]:
    """What an offline reader found (a box and a text each) as Lens' paragraphs: each a line of its own, with no
    words (the overlay's page spreads its letters over it)."""
    out = []
    for box, text in found:
        text = tidy(text)
        shape = _quad_box(box)
        if not text or shape is None:
            continue
        vertical = shape[3] > 1.3 * shape[2] and len(text) > 1
        out.append({"dir": TOP_TO_BOTTOM if vertical else LEFT_TO_RIGHT, "box": shape,
                    "lines": [{"text": text, "box": shape, "words": []}]})
    return out


def _extent(box) -> tuple:
    """The upright rectangle a box covers, tilted as it may be: (x1, y1, x2, y2)."""
    cx, cy, w, h, angle = box
    c, s = abs(math.cos(angle)), abs(math.sin(angle))
    half_w, half_h = (w * c + h * s) / 2, (w * s + h * c) / 2
    return cx - half_w, cy - half_h, cx + half_w, cy + half_h


def _along(line_box, word_box, vertical: bool) -> tuple:
    """Where a word is along its line, from the line's start (its left end; its top, in a column): (from, to)."""
    cx, cy, w, h, angle = line_box
    ux, uy = (-math.sin(angle), math.cos(angle)) if vertical else (math.cos(angle), math.sin(angle))
    length = h if vertical else w
    sx, sy = cx - ux * length / 2, cy - uy * length / 2
    wx, wy, ww, wh, _ = word_box
    middle = (wx - sx) * ux + (wy - sy) * uy
    half = (wh if vertical else ww) / 2
    return round(max(0.0, middle - half), 1), round(min(length, middle + half), 1)


def _ruby_of(small: dict, big: dict) -> bool:
    """Whether a line is furigana of another: at most two thirds as thick, just over it (just right of it, in a
    column), and along the part of it under it -- measured as the other line is tilted."""
    scx, scy, sw, sh, _ = small["box"]
    bcx, bcy, bw, bh, angle = big["box"]
    dx, dy = scx - bcx, scy - bcy
    x = dx * math.cos(angle) + dy * math.sin(angle)   # (the small line's middle, as the big one is tilted)
    y = -dx * math.sin(angle) + dy * math.cos(angle)
    if small["v"]:
        thin, thick, length = sw, bw, sh
        overlap = min(y + sh / 2, bh / 2) - max(y - sh / 2, -bh / 2)
        gap = (x - sw / 2) - bw / 2
    else:
        thin, thick, length = sh, bh, sw
        overlap = min(x + sw / 2, bw / 2) - max(x - sw / 2, -bw / 2)
        gap = -bh / 2 - (y + sh / 2)
    return thin <= 0.66 * thick and overlap >= 0.6 * length and -0.35 * thick <= gap <= 0.6 * thick


def drop_ruby(lines: list) -> list:
    """The furigana left out: a line of kana alone that is the reading of a line with kanji beside it."""
    return [small for small in lines if not (KANA_LINE.match(small["text"]) and any(
        _ruby_of(small, big) for big in lines if big is not small and big["v"] == small["v"] and KANJI.search(big["text"])))]


def vision_lines(paragraphs: list, furigana: bool = True) -> list[dict]:
    """What a read found as the overlay's lines, in reading order: [{"i", "p", "v", "rtl", "text", "box", "words":
    [[start, end, from, to]]}] -- each word by where it is in its line's text, and where along the line (from the
    line's start, in the window's pixels)."""
    lines = []
    for p, paragraph in enumerate(paragraphs):
        vertical = paragraph.get("dir") == TOP_TO_BOTTOM
        rows = paragraph.get("lines") or []
        if vertical:  # columns, right to left
            rows = sorted(rows, key=lambda line: -line["box"][0])
        for line in rows:
            words = []
            for start, end, box in line.get("words") or []:
                a, b = _along(line["box"], box, vertical)
                if b > a:
                    words.append([start, end, a, b])
            lines.append({"p": p, "v": vertical, "rtl": paragraph.get("dir") == RIGHT_TO_LEFT, "text": line["text"],
                          "box": list(line["box"]), "words": words})
    if furigana:
        lines = drop_ruby(lines)
    for i, line in enumerate(lines):
        line["i"] = i
    return lines


def cells_of(img: Image, cell: int, per: int) -> tuple[int, int, list]:
    """A likeness of a picture, to tell where it changes: for each square of cell x cell pixels (those cut short at
    its right and bottom edges left out), the green of per x per of its pixels, evenly spread."""
    cols, rows = img.w // cell, img.h // cell
    if cols <= 0 or rows <= 0:
        return 0, 0, []
    step = max(1, cell // per)
    first = step // 2
    stride = img.w * 4
    out = []
    for r in range(rows):
        lines = []
        for k in range(per):
            y = min(img.h - 1, r * cell + first + k * step)
            at = y * stride + 1  # (the green of each pixel)
            lines.append(img.data[at + first * 4:at + cols * cell * 4:step * 4])
        for c in range(cols):
            s = c * per
            out.append(b"".join(line[s:s + per] for line in lines))
    return cols, rows, out


def _differ(a: bytes, b: bytes, threshold: int) -> int:
    """How many of two cells' samples differ by more than the threshold."""
    if a == b:
        return 0
    return sum(1 for x, y in zip(a, b) if x - y > threshold or y - x > threshold)


#: How many of the bits of each number below 4096 are set (VisionWatch's record of the looks a cell changed at).
_SET_BITS = bytes(bin(n).count("1") for n in range(4096))


class VisionWatch:
    """Sluka Vision's side here: the window of a game, watched while its tab is chosen -- read whole when asked (its
    key, the menu's button) and, where reading by itself is on, as soon as what it shows has changed and settled, as
    YomiNinja's automatic reading does; and the words read before said to be gone the moment what is under them
    changes, so that none is left where its text is no more.

    What it shows is watched as a likeness (cells_of): a cell that has changed of late again and again is taken to
    move by itself (a picture, not text) and is not waited for.

    A line read is said to be gone once what is under it has changed and is still again (or has been for a moment):
    not while it moves, nor where it keeps moving -- a game's button, its letters bobbing or glowing in place, keeps
    its words -- and said to be back where what is under it is again as it was read (the button the pointer lit, dark
    again).  Changed and still, dialogue put in its place goes within half a second.
    """

    TICK = 0.25          # how often the window is looked at; more seldom where a picture of it takes long
    CELL = 24            # the likeness' squares, in the window's pixels ...
    PER = 4              # ... and the samples across each (sixteen in all)
    MOVED = 36           # a sample that changed by more than this ...
    MOVED_SAMPLES = 2    # ... in this many of a cell's: the cell changed
    BUSY = 0.45          # a cell that changed this often of late moves by itself
    CALM_MOVED = 2       # this many of the other cells changed: what the window shows has changed ...
    SETTLE = 0.45        # ... and it has settled once none has for this long
    GAP = 0.6            # the least time between two reads by itself (an offline reader) ...
    GAP_LENS = 1.2       # ... and with Google Lens
    STALE_SHARE = 0.3    # this much of a line's quiet cells changed since it was read: its text is gone ...
    BACK_SHARE = 0.1     # ... and no more than this of them, all still: it is back as it was read
    LOOKS = 12           # what each cell did is kept for this many looks (three seconds) ...
    LIVELY = 5           # ... and one that changed at this many of them keeps moving: no word is put away for it
    STILL = 2            # a cell that has not changed for this many looks is still
    BACKOFF_MOST = 30.0  # a reader that keeps failing is asked again this seldom at most
    WINDOW_HOLD = 2.0    # the game's own window read again for this long after the screen had to be: so said

    def __init__(self, daemon: "Ocrd", params: dict):
        self.d = daemon
        self.p = dict(params)
        self.inbox: queue.Queue = queue.Queue()
        self.stop_event = threading.Event()
        self.thread = threading.Thread(target=self._run, name="ocr-vision", daemon=True)
        self.target: dict | None = None
        self.reader = None
        self.reader_name = ""
        self.read_id = 0
        self.new_target = False  # (a window to read set since: how it is read is said again)
        self._state = None
        self._errors: dict[str, float] = {}

    def start(self) -> None:
        self.thread.start()

    def stop(self) -> None:
        self.stop_event.set()
        self.inbox.put(("stop", {}))

    def ask(self, what: str, **args) -> None:
        self.inbox.put((what, args))

    def status(self, state: str, text: str = "") -> None:
        if (state, text) != self._state:
            self._state = (state, text)
            self.d.emit({"ev": "vision-status", "state": state, "text": text})

    def error(self, text: str, again_after: float = 0.0) -> None:
        now = time.monotonic()
        if now - self._errors.get(text, -1e9) > max(5.0, again_after):
            self._errors[text] = now
            self.d.log(f"vision error: {text}")
            self.d.emit({"ev": "vision-error", "text": text})

    def _run(self) -> None:
        try:
            self._loop()
        except Exception as err:
            self.d.log("Sluka Vision failed:\n" + traceback.format_exc())
            self.d.emit({"ev": "vision-error", "text": f"Sluka Vision stopped: {err}"})
        self.d.emit({"ev": "vision-stopped"})

    # ---------------------------------------------------------------- reading

    def _read(self, img: Image) -> tuple[list, str]:
        name = self.p.get("engine") or "lens"
        if name == "lens":
            return self.d.readers["lens"].layout(img), "lens"
        if self.reader is None or self.reader_name != name:
            reader, why = self.d.pick(name, self.p.get("lang") or "ja")
            if reader is None:
                raise Unavailable(why)
            reader.prepare()
            self.reader, self.reader_name = reader, name
        found = self.reader.recognize(img, {"lang": self.p.get("lang") or "ja", "direction": "auto"})
        return paragraphs_of(found), self.reader.name

    def _window(self, window: dict) -> None:
        self.target = dict(window)
        self.new_target = True
        self.d.emit({"ev": "vision-window", "window": self.target})

    # ---------------------------------------------------------------- the watching

    def _loop(self) -> None:
        desktop = self.d.desktop
        tick = self.TICK
        own = os.getpid()
        pick_until, pick_exclude = 0.0, set()
        want = ""           # a read asked for: "key" (the window in front), "menu", "auto"
        auto = bool(self.p.get("auto"))
        held = (0, frozenset())  # the lines (of the read numbered so) a word pointed at or its open panel is on
        layout = None       # the lines read last, with the cells each covers
        read_cells = None   # the likeness of the window as it was read
        prev = None         # ... as it was a moment ago
        busy: list = []
        moves: list = []    # each cell's last LOOKS looks, a bit each (the lowest the last): set where it changed
        stale: set = set()
        pending = False
        last_motion = 0.0
        last_read = -1e9
        backoff = 0.0
        area = None
        shown = None        # the game, or one of Sluka's windows, in front ...
        game_shown = None   # ... the game itself
        told_capture = None  # how the window is read, as the app was last told ("screen": Sluka's windows are then to
        last_screen = -1e9   # be left out of pictures of the screen; "window": the game's own picture) ... and when
        grid = (0, 0)
        frozen = None       # the picture kept (vision-freeze), looked at in place of the window meanwhile ...
        frozen_how = ""     # ... as it was taken
        freeze_to = ""      # a picture to keep, asked for (written to this path)
        freeze_ask = 0      # the number the app gave that request, said back with every word about it ...
        frozen_ask = 0      # ... and about the picture kept for it
        lively_bits = (1 << self.LOOKS) - 1
        still_bits = (1 << self.STILL) - 1

        def lively(k: int) -> bool:
            return _SET_BITS[moves[k] & lively_bits] >= self.LIVELY

        def forget_words() -> None:
            nonlocal layout, read_cells, prev, busy, moves, stale, pending
            layout, read_cells, prev, busy, moves, stale, pending = None, None, None, [], [], set(), False

        while not self.stop_event.is_set():
            batch = []
            try:
                batch.append(self.inbox.get(timeout=tick))
                while True:
                    batch.append(self.inbox.get_nowait())
            except queue.Empty:
                pass
            now = time.monotonic()
            for what, args in batch:
                if what == "stop":
                    return
                if what == "read":
                    if args.get("front") and frozen is None:
                        window = desktop.foreground_window(set(args.get("exclude") or []) | {own})
                        if window is not None and (self.target is None or window["hwnd"] != self.target["hwnd"]):
                            self._window(window)
                            forget_words()
                            area, shown = None, None
                    if self.target is None:
                        self.error("There is no window to read yet: press Sluka Vision's key in the game, or choose "
                                   "its window in the Sluka Vision tab.")
                    else:
                        want = "key" if args.get("front") else "menu"
                elif what == "target":
                    hwnd = int(args.get("hwnd") or 0)
                    if hwnd and desktop.exists(hwnd):
                        self._window(desktop.info(hwnd))
                        forget_words()
                        area, shown = None, None
                elif what == "pick":
                    pick_until = now + max(1.0, float(args.get("seconds") or 10))
                    pick_exclude = set(int(p) for p in args.get("exclude") or []) | {own}
                    self.status("picking", "")
                elif what == "cancel-pick":
                    pick_until = 0.0
                elif what == "auto":
                    auto = bool(args.get("on"))
                    pending = False
                    if auto and self.target is not None and layout is None:
                        want = want or "auto"
                elif what == "hold":
                    try:
                        held = (int(args.get("read") or 0), frozenset(int(i) for i in args.get("lines") or []))
                    except (TypeError, ValueError):
                        held = (0, frozenset())
                    # (what changed under the lines let go of meanwhile is read now, if anything did)
                    pending = pending or auto
                elif what == "settings":
                    if "capture" in args and args["capture"] != self.p.get("capture"):
                        told_capture, last_screen = None, -1e9
                        forget = getattr(getattr(desktop, "ways", None), "forget", None)
                        if forget is not None:
                            forget()  # (the game's own window chosen again: each way of taking it tried afresh)
                    for key in ("engine", "lang", "furigana", "capture", "allow"):
                        if key in args:
                            self.p[key] = args[key]
                    if self.reader_name and self.reader_name != self.p.get("engine"):
                        self.reader, self.reader_name = None, ""
                elif what == "freeze":
                    if args.get("on"):
                        # (asked for anew: a picture still kept is the app's no longer, and a new one is taken)
                        frozen, frozen_how = None, ""
                        freeze_to = str(args.get("path") or "")
                        freeze_ask = _ask_number(args.get("ask"))
                    else:
                        freeze_to = ""
                        if frozen is not None:
                            frozen, frozen_how = None, ""
                            # (what the window shows now is compared with what was read off the picture: the words of
                            # what has gone go, and what took its place is read, as ever)
                            self.d.emit({"ev": "vision-frozen", "on": False, "ask": frozen_ask})
                elif what == "clear":
                    forget_words()
                elif what == "forget":
                    forget_words()
                    self.target, area, shown = None, None, None
                    self.d.emit({"ev": "vision-window", "window": None})

            if pick_until:
                if now > pick_until:
                    pick_until = 0.0
                    self.d.emit({"ev": "vision-picked", "window": None})
                else:
                    window = desktop.foreground_window(pick_exclude)
                    if window is not None:
                        pick_until = 0.0
                        self._window(window)
                        self.d.emit({"ev": "vision-picked", "window": self.target})
                        forget_words()
                        area, shown = None, None
                        want = "menu"
                    else:
                        continue
            if self.target is None:
                if freeze_to:
                    freeze_to = ""
                    self.d.emit({"ev": "vision-frozen", "on": False, "ask": freeze_ask, "error": "There is no window to keep a picture of."})
                self.status("idle", "")
                continue
            if self.new_target:
                self.new_target = False
                told_capture, last_screen = None, -1e9
                if frozen is not None:
                    # (another window: the picture of the one before is let go of)
                    frozen, frozen_how = None, ""
                    self.d.emit({"ev": "vision-frozen", "on": False, "ask": frozen_ask})
            hwnd = self.target["hwnd"]
            here = desktop.client_area(hwnd)
            if here is None:
                self.d.emit({"ev": "vision-gone", "window": self.target})
                self.target, area, shown = None, None, None
                forget_words()
                want = ""
                if frozen is not None or freeze_to:
                    gone = frozen_ask if frozen is not None else freeze_ask
                    frozen, frozen_how, freeze_to = None, "", ""
                    self.d.emit({"ev": "vision-frozen", "on": False, "ask": gone})
                continue
            if desktop.minimized(hwnd):
                if freeze_to:
                    freeze_to = ""
                    self.d.emit({"ev": "vision-frozen", "on": False, "ask": freeze_ask, "error": "The game's window is minimized."})
                if shown is not False:
                    shown, game_shown = False, False
                    self.d.emit({"ev": "vision-front", "on": False, "game": False, "why": "minimized"})
                self.status("hidden", "The game's window is minimized.")
                continue
            allowed = {int(x) for x in self.p.get("allow") or []} | {int(self.target.get("pid") or 0), own}
            in_front = desktop.foreground_pid()
            if frozen is not None and in_front not in allowed and getattr(desktop, "foreground_ghost", lambda: False)():
                # (the game paused: Windows' stand-in for its window, which does not answer, is the game in front)
                in_front = int(self.target.get("pid") or 0)
            front = in_front in allowed
            # (the game itself, and not only one of Sluka's windows: while a panel is open, its keys are then Sluka's)
            game = bool(in_front) and in_front == int(self.target.get("pid") or 0)
            if front != shown or game != game_shown:
                shown, game_shown = front, game
                self.d.emit({"ev": "vision-front", "on": front, "game": game, "why": "" if front else "behind"})
            if here != area:
                resized = area is not None and tuple(here[2:4]) != tuple(area[2:4])
                area = here
                self.d.emit({"ev": "vision-area", "area": list(here)})
                if resized and layout is not None:
                    self.d.emit({"ev": "vision-stale", "all": True})
                    forget_words()
                    if auto:
                        pending, last_motion = True, now
            if not want and not front and not freeze_to:
                self.status("behind", "Another program's window is in front of the game.")
                continue
            if not want and not auto and layout is None and not freeze_to and frozen is None:
                self.status("waiting", "")
                continue

            if frozen is not None:
                # Kept: the picture looked at in place of the window, which is not taken meanwhile (it may be a game
                # paused, whose window Windows would soon fade, or one that goes on behind the picture).
                img, how = frozen, frozen_how
            else:
                started = time.monotonic()
                try:
                    img, how = desktop.grab(self.p.get("capture") or "screen", hwnd, here)
                except (OSError, ValueError) as err:
                    self.error(f"No picture of the window could be taken: {err}")
                    img, how = None, ""
                took = time.monotonic() - started
                # (a large window taken often costs: looked at no more than a quarter of the time)
                tick = max(self.TICK, min(1.0, took * 4))
            if img is None or not img.w or not img.h:
                if freeze_to:
                    freeze_to = ""
                    self.d.emit({"ev": "vision-frozen", "on": False, "ask": freeze_ask,
                                 "error": "No picture of the game's window could be taken."})
                self.status("nopicture", "No picture of the game's window could be taken.")
                continue
            if freeze_to:
                path, freeze_to = freeze_to, ""
                try:
                    _write_file(path, to_bmp(img))
                except OSError as err:
                    self.d.emit({"ev": "vision-frozen", "on": False, "ask": freeze_ask, "error": f"The picture could not be kept: {err}"})
                else:
                    frozen, frozen_how, frozen_ask = img, how, freeze_ask
                    self.d.emit({"ev": "vision-frozen", "on": True, "path": path, "size": [img.w, img.h], "area": list(here),
                                 "how": how, "ask": freeze_ask})
                    # Read where its words are not those shown (nothing read yet, or what was read has changed since).
                    if layout is None or read_cells is None:
                        want = want or "freeze"
                    else:
                        _c, _r, now_cells = cells_of(img, self.CELL, self.PER)
                        if len(now_cells) != len(read_cells) or sum(
                                1 for before, after in zip(read_cells, now_cells)
                                if _differ(before, after, self.MOVED) >= self.MOVED_SAMPLES) >= self.CALM_MOVED:
                            want = want or "freeze"
            # How it was read, said to the app: Sluka's windows are left out of pictures of the screen while the screen
            # is read (at once), and are in them again once the game's own window has been read for a moment (a black
            # screen in the game, which gives no picture of the window, does not make them blink).
            if frozen is not None and frozen_how == how and told_capture is not None:
                capture = told_capture
            elif how != "window":
                last_screen = now
                capture = "screen"
            elif told_capture == "screen" and now - last_screen < self.WINDOW_HOLD:
                capture = "screen"
            else:
                capture = "window"
            if capture != told_capture:
                was, told_capture = told_capture, capture
                event = {"ev": "vision-capture", "how": capture}
                if capture == "screen" and hwnd and getattr(desktop, "frozen", lambda _h: False)(hwnd):
                    event["why"] = "frozen"  # (the game's own picture stays as it was: the screen has to be read)
                self.d.emit(event)
                if capture == "screen" and was == "window":
                    # (this picture may still have Sluka's own words in it: they are left out of the next)
                    continue
            cols, rows, cells = cells_of(img, self.CELL, self.PER)
            if (cols, rows) != grid or prev is None or len(prev) != len(cells):
                grid = (cols, rows)
                busy = [0.0] * len(cells)
                moves = [0] * len(cells)
                if read_cells is not None and len(read_cells) != len(cells):
                    read_cells = None
            else:
                calm = 0
                for k, (before, after) in enumerate(zip(prev, cells)):
                    moved = before != after and _differ(before, after, self.MOVED) >= self.MOVED_SAMPLES
                    if moved and busy[k] < self.BUSY:
                        calm += 1
                    busy[k] = busy[k] * 0.85 + (0.15 if moved else 0.0)
                    moves[k] = ((moves[k] << 1) | moved) & lively_bits
                if calm >= self.CALM_MOVED:
                    last_motion = now
                    if auto:
                        pending = True
            prev = cells

            # The words whose text has gone: said as soon as what took its place is still (and back, where it is so).
            if layout is not None and read_cells is not None and len(read_cells) == len(cells):
                gone, back = [], []
                for line in layout:
                    quiet = [k for k in line["cells"] if k < len(moves) and not lively(k)]
                    if not quiet:
                        continue
                    changed = [k for k in quiet if _differ(read_cells[k], cells[k], self.MOVED) >= self.MOVED_SAMPLES]
                    if line["i"] not in stale:
                        settled = sum(1 for k in changed if not moves[k] & still_bits)
                        if settled >= max(1.0, self.STALE_SHARE * len(quiet)):
                            gone.append(line["i"])
                    elif len(changed) <= self.BACK_SHARE * len(quiet) and not any(moves[k] & still_bits for k in quiet):
                        back.append(line["i"])
                if gone:
                    stale.update(gone)
                    self.d.emit({"ev": "vision-stale", "lines": gone})
                    if auto:
                        # (what took their place is to be read: that it changed is known for certain by now)
                        pending = True
                if back:
                    stale.difference_update(back)
                    self.d.emit({"ev": "vision-back", "lines": back})

            gap = (self.GAP_LENS if (self.p.get("engine") or "lens") == "lens" else self.GAP) + backoff
            if auto and pending and not want and now - last_motion >= self.SETTLE and now - last_read >= gap:
                pending = False
                # (what changes under the word pointed at alone is the pointer's doing -- a button lit by it --, and is
                # not read: the card would go from under the pointer)
                looked_at = set()
                if layout is not None and held[1] and held[0] == self.read_id:
                    for line in layout:
                        if line["i"] in held[1]:
                            looked_at.update(line["cells"])
                if layout is None or read_cells is None or sum(
                        1 for k, (before, after) in enumerate(zip(read_cells, cells))
                        if not lively(k) and k not in looked_at
                        and _differ(before, after, self.MOVED) >= self.MOVED_SAMPLES) >= self.CALM_MOVED:
                    want = "auto"
            if not want:
                self.status("waiting", "")
                continue

            why, want = want, ""
            self.status("reading", "")
            begun = time.monotonic()
            try:
                paragraphs, engine = self._read(img)
            except Unavailable as err:
                # (said again at each press of the key; by itself, once a minute at most)
                self.error(str(err), 60 if why == "auto" else 0)
                self.status("failed", str(err))
                last_read, backoff = now, self.BACKOFF_MOST
                continue
            except Exception as err:
                self.d.log("a read of the window failed:\n" + traceback.format_exc())
                self.error(f"The window could not be read: {err}")
                last_read = now
                backoff = min(self.BACKOFF_MOST, max(2.0, backoff * 2))
                self.status("failed", str(err))
                continue
            backoff = 0.0
            ms = int((time.monotonic() - begun) * 1000)
            lines = vision_lines(paragraphs, bool(self.p.get("furigana", True)))
            for line in lines:
                x1, y1, x2, y2 = _extent(line["box"])
                c1, c2 = max(0, int(x1 // self.CELL)), min(cols - 1, int(x2 // self.CELL))
                r1, r2 = max(0, int(y1 // self.CELL)), min(rows - 1, int(y2 // self.CELL))
                line["cells"] = [r * cols + c for r in range(r1, r2 + 1) for c in range(c1, c2 + 1)]
            self.read_id += 1
            layout, read_cells, stale, last_read, pending = lines, cells, set(), now, False
            told = [{k: v for k, v in line.items() if k != "cells"} for line in lines]
            self.d.log(f"vision read ({engine}, {ms} ms, {len(told)} lines): "
                       f"{' / '.join(line['text'] for line in told)[:200]!r}")
            self.d.emit({"ev": "vision-layout", "id": self.read_id, "engine": engine, "ms": ms, "why": why,
                         "area": list(here), "size": [img.w, img.h], "lines": told})
            self.status("waiting", "")


# ======================================================================================== the program


class Ocrd:
    def __init__(self, folder: str, write, log=None, options: dict | None = None):
        options = options or {}
        self.folder = os.path.abspath(folder)
        self.write = write
        self.log = log or (lambda text: None)
        self._out = threading.Lock()
        if options.get("desktop"):
            self.desktop = FileDesktop(options["desktop"])
        elif WINDOWS:
            self.desktop = WindowsDesktop()
        else:
            self.desktop = None
        self.native = Native(options.get("nativeutils") or os.path.join(self.folder, "ocr", "NativeUtils.dll"))
        network = {"mode": options.get("network") or "direct", "socks": options.get("socks") or "127.0.0.1:9050"}
        self.readers = {
            "builtin": BuiltinReader(self.folder, options.get("cvutils") or ""),
            "windows": WindowsReader(self.native, fake=bool(options.get("nativeutils"))),
            "lens": LensReader(self.native, network, options.get("lens_url") or ""),
        }
        self.watch: Watch | None = None
        self.vision: VisionWatch | None = None
        self._selecting = False

    def emit(self, event: dict) -> None:
        line = json.dumps(event, ensure_ascii=False, separators=(",", ":")) + "\n"
        with self._out:
            try:
                self.write(line.encode("utf-8", "replace"))
            except (OSError, ValueError):
                pass

    # ---------------------------------------------------------------- the commands

    def _check(self, name: str, lang: str) -> dict:
        try:
            return self.readers[name].check(lang)
        except Exception as err:
            self.log(f"{name} could not be looked at:\n" + traceback.format_exc())
            return {"ok": False, "why": str(err)}

    def engines(self, lang: str) -> None:
        """Which readers can be used here (in a thread of its own: loading one takes a moment)."""

        def run():
            found = {name: self._check(name, lang) for name in self.readers}
            self.emit({"ev": "engines", "engines": found})

        threading.Thread(target=run, name="ocr-engines", daemon=True).start()

    def pick(self, name: str, lang: str):
        """The reader asked for, or for "auto" the first that can be used here: (reader, '') or (None, why not)."""
        if name in self.readers:
            return self.readers[name], ""
        whys = []
        for candidate in AUTO_ORDER:
            found = self._check(candidate, lang)
            if found.get("ok"):
                return self.readers[candidate], ""
            whys.append(f"{candidate}: {found.get('why')}")
        return None, "No reader can be used here (" + "; ".join(whys) + ")."

    def select(self, delay: float, exclude) -> None:
        if self.desktop is None:
            self.emit({"ev": "selected", "cancelled": True, "error": "There is no screen here."})
            return
        if self._selecting:
            return
        self._selecting = True

        def run():
            try:
                rect = self.desktop.select(self.native, delay)
                if not rect or rect[2] - rect[0] < 4 or rect[3] - rect[1] < 4:
                    self.emit({"ev": "selected", "cancelled": True})
                    return
                x1, y1, x2, y2 = (int(v) for v in rect)
                window = self.desktop.window_at((x1 + x2) // 2, (y1 + y2) // 2, list(exclude) + [os.getpid()])
                if window:
                    cx, cy, cw, ch = window["client"]
                    bx, by = max(0, x1 - cx), max(0, y1 - cy)
                    window["box"] = [bx, by, max(1, min(x2, cx + cw) - cx - bx), max(1, min(y2, cy + ch) - cy - by)]
                self.emit({"ev": "selected", "rect": [x1, y1, x2, y2], "window": window})
            except Exception as err:
                self.log("the selection failed:\n" + traceback.format_exc())
                self.emit({"ev": "selected", "cancelled": True, "error": str(err)})
            finally:
                self._selecting = False

        threading.Thread(target=run, name="ocr-select", daemon=True).start()

    def start_watch(self, command: dict) -> None:
        before = self.watch.p.get("capture") if self.watch is not None else None
        self.stop_watch()
        if before is not None and before != command.get("capture"):
            forget = getattr(getattr(self.desktop, "ways", None), "forget", None)
            if forget is not None:
                forget()  # (what is read chosen again: each way of taking the game's own window tried afresh)
        if self.desktop is None:
            self.emit({"ev": "error", "text": "There is no screen to read here."})
            return
        try:
            box = [int(v) for v in command["box"]][:4]
            if len(box) != 4 or box[2] <= 0 or box[3] <= 0:
                raise ValueError("the box")
            params = {
                "hwnd": int(command.get("hwnd") or 0),
                "pid": int(command.get("pid") or 0),
                "box": box,
                "client": [int(v) for v in command.get("client") or []][:2] or None,
                "engine": command.get("engine") if command.get("engine") in READERS else "auto",
                "mode": command.get("mode") if command.get("mode") in MODES else "auto",
                "interval": float(command.get("interval") or 1.5),
                "lang": str(command.get("lang") or "ja")[:20],
                "direction": command.get("direction") if command.get("direction") in DIRECTIONS else "auto",
                "furigana": bool(command.get("furigana", True)),
                "capture": command.get("capture") if command.get("capture") in CAPTURES else "screen",
                "front": bool(command.get("front", True)),
                "allow": [int(x) for x in command.get("allow") or []],
            }
        except (KeyError, TypeError, ValueError) as err:
            self.emit({"ev": "error", "text": f"Nothing to watch ({err})."})
            return
        self.watch = Watch(self, params)
        self.watch.start()

    def read_once(self, command: dict) -> None:
        """A place on the screen read once by one reader (or "auto"'s), in a thread of its own: "read"."""

        def run():
            name = str(command.get("engine") or "auto")
            lang = str(command.get("lang") or "ja")[:20]
            direction = command.get("direction") if command.get("direction") in DIRECTIONS else "auto"
            out = {"ev": "read", "engine": name, "text": "", "ms": 0, "lines": 0, "error": ""}
            try:
                reader, why = self.pick(name, lang)
                if reader is None:
                    raise Unavailable(why)
                out["engine"] = reader.name
                if self.desktop is None:
                    raise Unavailable("There is no screen to read here.")
                rect = [int(v) for v in command["rect"]][:4]
                if len(rect) != 4 or rect[2] <= 0 or rect[3] <= 0:
                    raise ValueError("no place to read")
                reader.prepare()
                img, _how = self.desktop.grab("screen", 0, rect)
                if img is None or not img.w or not img.h:
                    raise RuntimeError("no picture of the place could be taken")
                started = time.monotonic()
                found = reader.recognize(img, {"lang": lang, "direction": direction})
                out["ms"] = int((time.monotonic() - started) * 1000)
                out["text"], out["lines"] = arrange(found, direction, bool(command.get("furigana", True)))
            except Exception as err:
                if not isinstance(err, (Unavailable, ValueError)):
                    self.log("a read failed:\n" + traceback.format_exc())
                out["error"] = str(err) or type(err).__name__
            self.emit(out)

        threading.Thread(target=run, name="ocr-read", daemon=True).start()

    def stop_watch(self) -> None:
        watch, self.watch = self.watch, None
        if watch is not None:
            watch.stop()
            watch.thread.join(timeout=5)

    def start_vision(self, command: dict) -> None:
        """Sluka Vision: a whole window watched and read ("vision-start"; then "vision-read", "-pick", ...)."""
        self.stop_vision()
        if self.desktop is None:
            self.emit({"ev": "vision-error", "text": "There is no screen to read here."})
            return
        params = {
            "engine": command.get("engine") if command.get("engine") in READERS else "lens",
            "lang": str(command.get("lang") or "ja")[:20],
            "furigana": bool(command.get("furigana", True)),
            "capture": command.get("capture") if command.get("capture") in CAPTURES else "screen",
            "auto": bool(command.get("auto")),
            "allow": [int(x) for x in command.get("allow") or []],
        }
        self.vision = VisionWatch(self, params)
        self.vision.start()
        if command.get("hwnd"):
            self.vision.ask("target", hwnd=int(command["hwnd"]))

    def stop_vision(self) -> None:
        vision, self.vision = self.vision, None
        if vision is not None:
            vision.stop()
            vision.thread.join(timeout=5)

    def run(self, lines) -> None:
        for raw in lines:
            try:
                command = json.loads(raw.decode("utf-8") if isinstance(raw, bytes) else raw)
            except ValueError:
                continue
            if not isinstance(command, dict):
                continue
            what = command.get("cmd")
            self.log(f"command: {json.dumps(command, ensure_ascii=False)[:300]}")
            try:
                if what == "engines":
                    self.engines(str(command.get("lang") or "ja"))
                elif what == "select":
                    self.select(float(command.get("delay") or 0), command.get("exclude") or [])
                elif what == "cancel-select":
                    if self.desktop is not None:
                        self.desktop.cancel_select()
                elif what == "watch":
                    self.start_watch(command)
                elif what == "once":
                    if self.watch is not None:
                        self.watch.once_event.set()
                elif what == "stop":
                    self.stop_watch()
                elif what == "read":
                    self.read_once(command)
                elif what == "vision-start":
                    self.start_vision(command)
                elif what == "vision-stop":
                    self.stop_vision()
                elif isinstance(what, str) and what.startswith("vision-"):
                    if self.vision is not None:
                        args = {k: v for k, v in command.items() if k != "cmd"}
                        self.vision.ask(what[len("vision-"):], **args)
                elif what == "quit":
                    break
            except Exception as err:
                self.log("a command failed:\n" + traceback.format_exc())
                self.emit({"ev": "error", "text": f"Sluka's screen reader could not do {what!r}: {err}"})
        self.stop_watch()
        self.stop_vision()
        for reader in self.readers.values():
            try:
                reader.close()
            except Exception:
                pass


def _option(argv: list, name: str) -> str:
    if name in argv[1:]:
        at = argv.index(name, 1)
        if at + 1 < len(argv):
            return argv[at + 1]
    return ""


def main(argv: list | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0].startswith("--"):
        print("usage: ocrd.py ENGINE_FOLDER [--log FILE]", file=sys.stderr)
        return 2
    folder = argv[0]
    log_file = None
    if _option(argv, "--log"):
        try:
            os.makedirs(os.path.dirname(os.path.abspath(_option(argv, "--log"))), exist_ok=True)
            log_file = open(_option(argv, "--log"), "a", encoding="utf-8")
        except OSError:
            log_file = None
    lock = threading.Lock()

    def log(text: str) -> None:
        if log_file is None:
            return
        with lock:
            try:
                log_file.write(time.strftime("%Y-%m-%d %H:%M:%S ") + text + "\n")
                log_file.flush()
            except (OSError, ValueError):
                pass

    global _say
    _say = log

    # The pipe to the app is for the events alone: what the libraries' own C code may print goes nowhere.
    try:
        events = os.dup(1)
        nowhere = os.open(os.devnull, os.O_WRONLY)
        os.dup2(nowhere, 1)
        os.close(nowhere)
        out = os.fdopen(events, "wb", buffering=0)
    except (OSError, ValueError):
        out = sys.stdout.buffer
    stdin = sys.stdin.buffer if sys.stdin is not None else os.fdopen(0, "rb")

    def write(data: bytes) -> None:
        view = memoryview(data)
        while view:
            done = out.write(view)
            view = view[done or 0:]
        out.flush()

    dpi_aware()
    options = {
        "network": _option(argv, "--network"),
        "socks": _option(argv, "--socks"),
        # (the tests' stand-ins: a screen, the libraries, Google Lens)
        "desktop": _option(argv, "--desktop"),
        "cvutils": _option(argv, "--cvutils"),
        "nativeutils": _option(argv, "--nativeutils"),
        "lens_url": _option(argv, "--lens-url"),
    }
    log(f"Sluka's screen reader starting: Python {sys.version.split()[0]} ({struct.calcsize('P') * 8}-bit), folder {folder}")
    try:
        daemon = Ocrd(folder, write, log, options)
    except Exception as err:
        log("it could not be started:\n" + traceback.format_exc())
        try:
            write((json.dumps({"ev": "fatal", "text": str(err)}, ensure_ascii=False) + "\n").encode("utf-8"))
        except OSError:
            pass
        return 3
    daemon.emit({"ev": "ready", "protocol": PROTOCOL, "python": sys.version.split()[0], "bits": struct.calcsize("P") * 8,
                 "pid": os.getpid()})
    log("ready")
    try:
        daemon.run(iter(stdin.readline, b""))
    finally:
        log("ended")
        if log_file is not None:
            log_file.close()
    return 0


if __name__ == "__main__":
    code = main()
    # Out at once: the libraries' own threads may still be running, and a Python closing down is not to be called.
    os._exit(code)
