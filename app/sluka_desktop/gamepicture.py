# SPDX-License-Identifier: LicenseRef-Sluka
# Copyright (c) 2026 Sluka. Part of Sluka Desktop; see LICENSE.txt.
"""A picture of a game's window as it is now, for the line's Anki card (ankicards.py): its inside only, as Windows
itself draws it (PrintWindow, which follows games drawn with the graphics card), else from its device context, else
off the screen where it is -- where Sluka keeps its own windows out of pictures meanwhile, or Sluka's words are in it.

Made smaller with Windows' own filter (HALFTONE) to at most MAX_WIDTH across, and handed over as a BMP file, which
the engine's page makes the card's JPEG of (as the extension makes a video's picture: content/cc-clip.js).
"""

from __future__ import annotations

import ctypes
import logging
import struct
import sys

log = logging.getLogger("sluka.picture")

#: The widest picture handed over (the card's is made at most 640 across from it).
MAX_WIDTH = 1280

IS_WINDOWS = sys.platform == "win32"


def bmp(width: int, height: int, rows: bytes) -> bytes:
    """A 24-bit BMP file of ``rows``: bottom row first, each of blue, green, red, padded to four bytes."""
    stride = (width * 3 + 3) & ~3
    data = bytes(rows[: stride * height])
    header = struct.pack("<IiiHHIIiiII", 40, width, height, 1, 24, 0, len(data), 2835, 2835, 0, 0)
    return b"BM" + struct.pack("<IHHI", 14 + len(header) + len(data), 0, 0, 14 + len(header)) + header + data


def smaller(data: bytes, most: int = MAX_WIDTH) -> bytes:
    """A 24-bit BMP (Sluka Vision's picture kept) at most ``most`` across: each pixel the one nearest it.  Given back as
    it is where it is that small already, or is not such a BMP."""
    try:
        if data[:2] != b"BM" or struct.unpack_from("<H", data, 28)[0] != 24 or struct.unpack_from("<I", data, 30)[0] != 0:
            return data
        offset = struct.unpack_from("<I", data, 10)[0]
        width, height = struct.unpack_from("<ii", data, 18)
    except struct.error:
        return data
    if width <= most or height == 0:
        return data
    rows_up = height > 0
    height = abs(height)
    stride = (width * 3 + 3) & ~3
    if len(data) < offset + stride * height:
        return data
    out_w = most
    out_h = max(1, round(height * out_w / width))
    out_stride = (out_w * 3 + 3) & ~3
    pad = b"\0" * (out_stride - out_w * 3)
    picks = [min(width - 1, int((i + 0.5) * width / out_w)) * 3 for i in range(out_w)]
    rows = []
    for j in range(out_h):
        y = min(height - 1, int((j + 0.5) * height / out_h))
        row = data[offset + y * stride:offset + y * stride + width * 3]
        line = bytearray(out_w * 3)
        line[0::3] = bytes(row[k] for k in picks)
        line[1::3] = bytes(row[k + 1] for k in picks)
        line[2::3] = bytes(row[k + 2] for k in picks)
        rows.append(bytes(line) + pad)
    # (rows kept in the order they came: a picture written bottom row first stays so; one written top first is turned)
    return bmp(out_w, out_h, b"".join(rows)) if rows_up else _top_down(out_w, out_h, b"".join(rows))


def _top_down(width: int, height: int, rows: bytes) -> bytes:
    stride = (width * 3 + 3) & ~3
    flipped = b"".join(rows[(height - 1 - r) * stride:(height - r) * stride] for r in range(height))
    return bmp(width, height, flipped)


def blank(rows: bytes, step: int = 997) -> bool:
    """Whether a picture is all one colour (black, as a window that cannot be drawn so comes out): looked at in many
    places across it."""
    if len(rows) < 6:
        return True
    first = rows[:3]
    return all(rows[i:i + 3] == first for i in range(0, len(rows) - 3, step))


if IS_WINDOWS:  # pragma: no cover - Windows' own, tried on Windows
    from ctypes import POINTER, Structure, byref, c_int, c_uint32, c_void_p
    from ctypes import wintypes

    _user32 = ctypes.WinDLL("user32", use_last_error=True)
    _gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)

    def _fn(lib, name, restype, *argtypes):
        f = getattr(lib, name)
        f.restype = restype
        f.argtypes = argtypes
        return f

    HWND, HDC, HGDI = wintypes.HWND, c_void_p, c_void_p
    GetClientRect = _fn(_user32, "GetClientRect", wintypes.BOOL, HWND, POINTER(wintypes.RECT))
    ClientToScreen = _fn(_user32, "ClientToScreen", wintypes.BOOL, HWND, POINTER(wintypes.POINT))
    GetDC = _fn(_user32, "GetDC", HDC, HWND)
    ReleaseDC = _fn(_user32, "ReleaseDC", c_int, HWND, HDC)
    PrintWindow = _fn(_user32, "PrintWindow", wintypes.BOOL, HWND, HDC, wintypes.UINT)
    IsWindow = _fn(_user32, "IsWindow", wintypes.BOOL, HWND)
    try:  # Windows 10 version 1607 and later
        GetDpiForWindow = _fn(_user32, "GetDpiForWindow", wintypes.UINT, HWND)
        GetWindowDpiAwarenessContext = _fn(_user32, "GetWindowDpiAwarenessContext", c_void_p, HWND)
        GetAwarenessFromDpiAwarenessContext = _fn(_user32, "GetAwarenessFromDpiAwarenessContext", c_int, c_void_p)
    except AttributeError:
        GetDpiForWindow = None
    CreateCompatibleDC = _fn(_gdi32, "CreateCompatibleDC", HDC, HDC)
    CreateCompatibleBitmap = _fn(_gdi32, "CreateCompatibleBitmap", HGDI, HDC, c_int, c_int)
    SelectObject = _fn(_gdi32, "SelectObject", HGDI, HDC, HGDI)
    DeleteObject = _fn(_gdi32, "DeleteObject", wintypes.BOOL, HGDI)
    DeleteDC = _fn(_gdi32, "DeleteDC", wintypes.BOOL, HDC)
    BitBlt = _fn(_gdi32, "BitBlt", wintypes.BOOL, HDC, c_int, c_int, c_int, c_int, HDC, c_int, c_int, wintypes.DWORD)
    StretchBlt = _fn(_gdi32, "StretchBlt", wintypes.BOOL, HDC, c_int, c_int, c_int, c_int, HDC, c_int, c_int, c_int, c_int,
                     wintypes.DWORD)
    SetStretchBltMode = _fn(_gdi32, "SetStretchBltMode", c_int, HDC, c_int)
    SetBrushOrgEx = _fn(_gdi32, "SetBrushOrgEx", wintypes.BOOL, HDC, c_int, c_int, c_void_p)

    class _BitmapInfoHeader(Structure):
        _fields_ = [("biSize", c_uint32), ("biWidth", c_int), ("biHeight", c_int), ("biPlanes", wintypes.WORD),
                    ("biBitCount", wintypes.WORD), ("biCompression", c_uint32), ("biSizeImage", c_uint32),
                    ("biXPelsPerMeter", c_int), ("biYPelsPerMeter", c_int), ("biClrUsed", c_uint32),
                    ("biClrImportant", c_uint32)]

    GetDIBits = _fn(_gdi32, "GetDIBits", c_int, HDC, HGDI, wintypes.UINT, wintypes.UINT, c_void_p,
                    POINTER(_BitmapInfoHeader), wintypes.UINT)

    SRCCOPY = 0x00CC0020
    CAPTUREBLT = 0x40000000
    HALFTONE = 4
    PW_CLIENTONLY = 0x1
    PW_RENDERFULLCONTENT = 0x2
    DIB_RGB_COLORS = 0

    def _rows(dc, bitmap, width: int, height: int) -> bytes:
        info = _BitmapInfoHeader(ctypes.sizeof(_BitmapInfoHeader), width, height, 1, 24, 0, 0, 0, 0, 0, 0)
        stride = (width * 3 + 3) & ~3
        buf = ctypes.create_string_buffer(stride * height)
        got = GetDIBits(dc, bitmap, 0, height, buf, byref(info), DIB_RGB_COLORS)
        return buf.raw if got == height else b""

    def _shrunk(screen_dc, source_dc, width: int, height: int) -> bytes | None:
        """The picture in ``source_dc`` (``width`` by ``height``) as a BMP, at most MAX_WIDTH across."""
        out_w = min(width, MAX_WIDTH)
        out_h = max(1, round(height * out_w / width))
        dc = CreateCompatibleDC(screen_dc)
        bitmap = CreateCompatibleBitmap(screen_dc, out_w, out_h)
        old = SelectObject(dc, bitmap)
        try:
            SetStretchBltMode(dc, HALFTONE)
            SetBrushOrgEx(dc, 0, 0, None)
            if not StretchBlt(dc, 0, 0, out_w, out_h, source_dc, 0, 0, width, height, SRCCOPY):
                return None
            SelectObject(dc, old)
            old = None
            rows = _rows(dc, bitmap, out_w, out_h)
            if not rows or blank(rows):
                return None
            return bmp(out_w, out_h, rows)
        finally:
            if old is not None:
                SelectObject(dc, old)
            DeleteObject(bitmap)
            DeleteDC(dc)

    def _stretched(hwnd) -> bool:
        """Whether Windows enlarges the window for the screen's scale (a program that knows no scale, on a 125 % or
        150 % screen): its own picture is then smaller than it shows, and the screen is read there instead."""
        if GetDpiForWindow is None:
            return False
        try:
            unaware = GetAwarenessFromDpiAwarenessContext(GetWindowDpiAwarenessContext(hwnd)) == 0
            return unaware and GetDpiForWindow(hwnd) not in (0, 96)
        except OSError:
            return False

    def _client(hwnd) -> tuple[int, int, int, int] | None:
        rect = wintypes.RECT()
        if not IsWindow(hwnd) or not GetClientRect(hwnd, byref(rect)):
            return None
        origin = wintypes.POINT(0, 0)
        ClientToScreen(hwnd, byref(origin))
        width, height = rect.right - rect.left, rect.bottom - rect.top
        return (origin.x, origin.y, width, height) if width > 0 and height > 0 else None

    def _from_window(hwnd, width: int, height: int, printed: bool) -> bytes | None:
        screen = GetDC(None)
        dc = CreateCompatibleDC(screen)
        bitmap = CreateCompatibleBitmap(screen, width, height)
        old = SelectObject(dc, bitmap)
        try:
            if printed:
                ok = PrintWindow(hwnd, dc, PW_CLIENTONLY | PW_RENDERFULLCONTENT)
            else:
                own = GetDC(hwnd)
                try:
                    ok = BitBlt(dc, 0, 0, width, height, own, 0, 0, SRCCOPY)
                finally:
                    ReleaseDC(hwnd, own)
            return _shrunk(screen, dc, width, height) if ok else None
        finally:
            SelectObject(dc, old)
            DeleteObject(bitmap)
            DeleteDC(dc)
            ReleaseDC(None, screen)

    def _from_screen(x: int, y: int, width: int, height: int) -> bytes | None:
        screen = GetDC(None)
        dc = CreateCompatibleDC(screen)
        bitmap = CreateCompatibleBitmap(screen, width, height)
        old = SelectObject(dc, bitmap)
        try:
            if not BitBlt(dc, 0, 0, width, height, screen, x, y, SRCCOPY | CAPTUREBLT):
                return None
            return _shrunk(screen, dc, width, height)
        finally:
            SelectObject(dc, old)
            DeleteObject(bitmap)
            DeleteDC(dc)
            ReleaseDC(None, screen)


def take(hwnd: int, how: str = "window", area: list | None = None) -> bytes | None:
    """The inside of window ``hwnd`` as a BMP file: ``how`` "window", as Windows draws it (else its device context,
    else the screen there); "screen", off the screen -- in ``area`` ([x, y, w, h] on the screen) where that is known.
    None where nothing could be had."""
    if not IS_WINDOWS:
        return None
    try:  # pragma: no cover - Windows' own
        client = _client(hwnd) if hwnd else None
        if how == "window" and client is not None and not _stretched(hwnd):
            _x, _y, width, height = client
            for printed in (True, False):
                got = _from_window(hwnd, width, height, printed)
                if got:
                    return got
        box = [int(v) for v in area][:4] if area and len(area) >= 4 else (list(client) if client else None)
        if box and box[2] > 0 and box[3] > 0:
            return _from_screen(*box)
    except Exception:
        log.exception("a picture of the game could not be taken")
    return None
