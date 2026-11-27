# SPDX-License-Identifier: LicenseRef-Sluka
# Copyright (c) 2026 Sluka. Part of Sluka Desktop; see LICENSE.txt.
"""A variable font at one weight, as a font of its own.

A variable font holds every weight of a face in one file: the outlines of one
weight, and how far each point moves for the others.  A browser draws it at
whatever weight a page asks for.  mpv's text renderer (libass, through
FreeType) loads such a file without saying where on its axes to draw, so it
gets the weight the file was made from -- for the Noto Sans JP and Noto Serif
JP that Windows 11 brings, the thinnest -- whatever weight the script asks for.

So the app makes, once, a plain font of the weight Sluka's pages use: each
glyph's points moved as the file says they move at that weight (the 'gvar'
table, with the points it leaves out worked out from their neighbours, as the
OpenType specification says), the widths moved with them ('HVAR', or the
glyphs' own phantom points), and everything that made the file variable left
out.  It is given a name of its own, so that it can sit beside the real one in
mpv's fonts folder without taking its place.

TrueType outlines only ('glyf'); a file with PostScript ones ('CFF2') is
refused (FontError), and the caller does without.  Nothing outside Python's
standard library is used.

What is not moved: the spacing between particular pairs of letters ('GPOS'
kerning) keeps the values of the weight the file was made from.  Japanese
and Chinese are set without such pairs, and in a Latin face the difference
between two weights' kerning is a fraction of a pixel at subtitle sizes.
"""

from __future__ import annotations

import struct
import time

#: Tables that only a variable font (or hinting, which is not varied here) needs.
DROPPED = {b"fvar", b"gvar", b"avar", b"HVAR", b"MVAR", b"VVAR", b"STAT", b"cvar", b"DSIG",
           b"fpgm", b"prep", b"cvt ", b"hdmx", b"LTSH", b"VDMX"}

# glyf flags
ON_CURVE, X_SHORT, Y_SHORT, REPEAT, X_SAME, Y_SAME, OVERLAP_SIMPLE = 0x01, 0x02, 0x04, 0x08, 0x10, 0x20, 0x40
# composite flags
ARG_WORDS, ARGS_XY, WE_HAVE_A_SCALE, MORE_COMPONENTS = 0x0001, 0x0002, 0x0008, 0x0020
XY_SCALE, TWO_BY_TWO, WE_HAVE_INSTRUCTIONS = 0x0040, 0x0080, 0x0100


class FontError(Exception):
    pass


# ------------------------------------------------------------------ reading

def tables_of(data: bytes, index: int = 0) -> dict[bytes, bytes]:
    """The tables of a font file (of face ``index`` in a collection)."""
    if len(data) < 12:
        raise FontError("not a font")
    base = 0
    if data[:4] == b"ttcf":
        count = struct.unpack(">I", data[8:12])[0]
        if index >= count:
            raise FontError(f"no face {index} in this collection")
        base = struct.unpack(">I", data[12 + 4 * index:16 + 4 * index])[0]
    version = data[base:base + 4]
    if version not in (b"\x00\x01\x00\x00", b"true", b"OTTO"):
        raise FontError("not a font")
    count = struct.unpack(">H", data[base + 4:base + 6])[0]
    out = {}
    for i in range(count):
        at = base + 12 + 16 * i
        tag = data[at:at + 4]
        offset, length = struct.unpack(">II", data[at + 8:at + 16])
        out[tag] = data[offset:offset + length]
    return out


def _f2(value: int) -> float:
    return value / 16384.0


def _fixed(value: int) -> float:
    return value / 65536.0


def axes_of(fvar: bytes) -> list[tuple[str, float, float, float]]:
    """``(tag, minimum, default, maximum)`` of each axis."""
    _major, _minor, offset, _res, count, size = struct.unpack(">HHHHHH", fvar[:12])
    axes = []
    for i in range(count):
        at = offset + i * size
        tag = fvar[at:at + 4].decode("latin-1")
        lo, default, hi = (_fixed(v) for v in struct.unpack(">iii", fvar[at + 4:at + 16]))
        axes.append((tag, lo, default, hi))
    return axes


def _avar_maps(avar: bytes | None, count: int) -> list[list[tuple[float, float]]]:
    if not avar:
        return [[] for _ in range(count)]
    axis_count = struct.unpack(">H", avar[6:8])[0]
    maps, at = [], 8
    for _ in range(axis_count):
        n = struct.unpack(">H", avar[at:at + 2])[0]
        at += 2
        pairs = []
        for _ in range(n):
            a, b = struct.unpack(">hh", avar[at:at + 4])
            pairs.append((_f2(a), _f2(b)))
            at += 4
        maps.append(pairs)
    while len(maps) < count:
        maps.append([])
    return maps


def _round_f2(value: float) -> float:
    # As the coordinates are kept by the formats themselves: in 2.14.
    return int(value * 16384 + (0.5 if value >= 0 else -0.5)) / 16384.0


def normalized(axes, maps, location: dict[str, float]) -> list[float]:
    """The location on each axis between -1 and 1, the default at 0, and as 'avar' bends it."""
    out = []
    for (tag, lo, default, hi), pairs in zip(axes, maps):
        v = min(max(float(location.get(tag, default)), lo), hi)
        if v < default:
            n = (v - default) / (default - lo) if default != lo else 0.0
        elif v > default:
            n = (v - default) / (hi - default) if hi != default else 0.0
        else:
            n = 0.0
        if len(pairs) >= 2:
            for (a0, b0), (a1, b1) in zip(pairs, pairs[1:]):
                if a0 <= n <= a1:
                    n = b0 if a1 == a0 else b0 + (n - a0) * (b1 - b0) / (a1 - a0)
                    break
        out.append(_round_f2(n))
    return out


def _region_scalar(coords, region) -> float:
    """How much of a delta applies at ``coords``: ``region`` is a (start, peak, end) for each axis."""
    scalar = 1.0
    for v, (start, peak, end) in zip(coords, region):
        if peak == 0:
            continue
        if start > peak or peak > end or (start < 0 < end):
            continue
        if v < start or v > end:
            return 0.0
        if v == peak:
            continue
        if v < peak:
            scalar *= (v - start) / (peak - start)
        else:
            scalar *= (end - v) / (end - peak)
    return scalar


def _tuple_scalar(coords, peak, start=None, end=None) -> float:
    scalar = 1.0
    for i, p in enumerate(peak):
        if p == 0:
            continue
        v = coords[i]
        if v == p:
            continue
        if start is not None:
            s, e = start[i], end[i]
            if v < s or v > e:
                return 0.0
            if v < p:
                scalar *= (v - s) / (p - s) if p != s else 1.0
            else:
                scalar *= (e - v) / (e - p) if e != p else 1.0
        else:
            if v == 0 or v < min(0.0, p) or v > max(0.0, p):
                return 0.0
            scalar *= v / p
    return scalar


# ------------------------------------------------------------------ packed numbers (gvar)

def _points(data: bytes, at: int):
    """Packed point numbers: (list or None for all points, next offset)."""
    first = data[at]
    at += 1
    if first == 0:
        return None, at
    if first & 0x80:
        count = ((first & 0x7F) << 8) | data[at]
        at += 1
    else:
        count = first
    points, last = [], 0
    while len(points) < count:
        control = data[at]
        at += 1
        run = (control & 0x7F) + 1
        if control & 0x80:
            values = struct.unpack(f">{run}H", data[at:at + 2 * run])
            at += 2 * run
        else:
            values = data[at:at + run]
            at += run
        for v in values:
            last += v
            points.append(last)
    return points[:count], at


def _deltas(data: bytes, at: int, count: int):
    out = []
    while len(out) < count:
        control = data[at]
        at += 1
        run = (control & 0x3F) + 1
        if control & 0x80:
            out.extend([0] * run)
        elif control & 0x40:
            out.extend(struct.unpack(f">{run}h", data[at:at + 2 * run]))
            at += 2 * run
        else:
            out.extend(struct.unpack(f">{run}b", data[at:at + run]))
            at += run
    return out[:count], at


# ------------------------------------------------------------------ inferred deltas (IUP)

def _iup_segment(coords, c1, d1, c2, d2):
    """Deltas for the points of ``coords`` between two that have theirs, each axis apart."""
    out = []
    for j in (0, 1):
        x1, x2, a, b = c1[j], c2[j], d1[j], d2[j]
        column = []
        if x1 == x2:
            column = [a if a == b else 0.0] * len(coords)
        else:
            if x1 > x2:
                x1, x2, a, b = x2, x1, b, a
            scale = (b - a) / (x2 - x1)
            for point in coords:
                x = point[j]
                column.append(a if x <= x1 else b if x >= x2 else a + (x - x1) * scale)
        out.append(column)
    return list(zip(out[0], out[1]))


def _iup_contour(deltas, coords, touched):
    n = len(coords)
    if not n:
        return deltas
    have = [i for i in range(n) if touched[i]]
    if not have:
        return [(0.0, 0.0)] * n
    if len(have) == n:
        return deltas
    if len(have) == 1:
        return [deltas[have[0]]] * n
    out = list(deltas)
    for k, i in enumerate(have):
        j = have[(k + 1) % len(have)]
        if j == (i + 1) % n:
            continue
        between = list(range(i + 1, j)) if j > i else list(range(i + 1, n)) + list(range(0, j))
        if not between:
            continue
        filled = _iup_segment([coords[p] for p in between], coords[i], deltas[i], coords[j], deltas[j])
        for p, d in zip(between, filled):
            out[p] = d
    return out


# ------------------------------------------------------------------ glyphs

class Glyph:
    __slots__ = ("kind", "points", "flags", "ends", "components", "data", "overlap")

    def __init__(self):
        self.kind = "empty"
        self.points = []        # simple: (x, y)
        self.flags = []
        self.ends = []
        self.components = []    # composite: dicts
        self.data = b""
        self.overlap = False


def parse_glyph(data: bytes) -> Glyph:
    glyph = Glyph()
    if len(data) < 10:
        return glyph
    contours = struct.unpack(">h", data[:2])[0]
    if contours >= 0:
        glyph.kind = "simple"
        at = 10
        glyph.ends = list(struct.unpack(f">{contours}H", data[at:at + 2 * contours]))
        at += 2 * contours
        count = glyph.ends[-1] + 1 if contours else 0
        ilen = struct.unpack(">H", data[at:at + 2])[0]
        at += 2 + ilen
        flags = []
        while len(flags) < count:
            f = data[at]
            at += 1
            flags.append(f)
            if f & REPEAT:
                flags.extend([f] * data[at])
                at += 1
        flags = flags[:count]
        xs, x = [], 0
        for f in flags:
            if f & X_SHORT:
                d = data[at]
                at += 1
                x += d if f & X_SAME else -d
            elif not f & X_SAME:
                x += struct.unpack(">h", data[at:at + 2])[0]
                at += 2
            xs.append(x)
        ys, y = [], 0
        for f in flags:
            if f & Y_SHORT:
                d = data[at]
                at += 1
                y += d if f & Y_SAME else -d
            elif not f & Y_SAME:
                y += struct.unpack(">h", data[at:at + 2])[0]
                at += 2
            ys.append(y)
        glyph.points = list(zip(xs, ys))
        glyph.flags = [f & ON_CURVE for f in flags]
        glyph.overlap = bool(flags and flags[0] & OVERLAP_SIMPLE)
        return glyph
    glyph.kind = "composite"
    at = 10
    while True:
        flags, gid = struct.unpack(">HH", data[at:at + 4])
        at += 4
        if flags & ARG_WORDS:
            if flags & ARGS_XY:
                a, b = struct.unpack(">hh", data[at:at + 4])
            else:
                a, b = struct.unpack(">HH", data[at:at + 4])
            at += 4
        else:
            if flags & ARGS_XY:
                a, b = struct.unpack(">bb", data[at:at + 2])
            else:
                a, b = data[at], data[at + 1]
            at += 2
        transform = b""
        if flags & WE_HAVE_A_SCALE:
            transform = data[at:at + 2]
        elif flags & XY_SCALE:
            transform = data[at:at + 4]
        elif flags & TWO_BY_TWO:
            transform = data[at:at + 8]
        at += len(transform)
        glyph.components.append({"flags": flags, "gid": gid, "a": a, "b": b, "transform": transform})
        if not flags & MORE_COMPONENTS:
            break
    return glyph


def _matrix(component) -> tuple[float, float, float, float]:
    t, flags = component["transform"], component["flags"]
    if flags & WE_HAVE_A_SCALE:
        s = _f2(struct.unpack(">h", t)[0])
        return s, 0.0, 0.0, s
    if flags & XY_SCALE:
        sx, sy = (_f2(v) for v in struct.unpack(">hh", t))
        return sx, 0.0, 0.0, sy
    if flags & TWO_BY_TWO:
        a, b, c, d = (_f2(v) for v in struct.unpack(">hhhh", t))
        return a, b, c, d
    return 1.0, 0.0, 0.0, 1.0


def _encode_simple(glyph: Glyph) -> bytes:
    if not glyph.points:
        return b""
    xs = [p[0] for p in glyph.points]
    ys = [p[1] for p in glyph.points]
    head = struct.pack(">hhhhh", len(glyph.ends), min(xs), min(ys), max(xs), max(ys))
    head += struct.pack(f">{len(glyph.ends)}H", *glyph.ends) + b"\x00\x00"  # no instructions
    flags, xdata, ydata = [], bytearray(), bytearray()
    px = py = 0
    for i, ((x, y), on) in enumerate(zip(glyph.points, glyph.flags)):
        f = ON_CURVE if on else 0
        if i == 0 and glyph.overlap:
            f |= OVERLAP_SIMPLE
        dx, dy = x - px, y - py
        px, py = x, y
        if dx == 0:
            f |= X_SAME
        elif -255 <= dx <= 255:
            f |= X_SHORT | (X_SAME if dx > 0 else 0)
            xdata.append(abs(dx))
        else:
            xdata += struct.pack(">h", dx)
        if dy == 0:
            f |= Y_SAME
        elif -255 <= dy <= 255:
            f |= Y_SHORT | (Y_SAME if dy > 0 else 0)
            ydata.append(abs(dy))
        else:
            ydata += struct.pack(">h", dy)
        flags.append(f)
    packed = bytearray()
    i = 0
    while i < len(flags):
        f = flags[i]
        run = 1
        while i + run < len(flags) and flags[i + run] == f and run < 256:
            run += 1
        if run > 1:
            packed += bytes((f | REPEAT, run - 1))
        else:
            packed.append(f)
        i += run
    return head + bytes(packed) + bytes(xdata) + bytes(ydata)


def _encode_composite(glyph: Glyph, bbox) -> bytes:
    out = bytearray(struct.pack(">hhhhh", -1, *bbox))
    for i, c in enumerate(glyph.components):
        flags = c["flags"] & ~(ARG_WORDS | WE_HAVE_INSTRUCTIONS | MORE_COMPONENTS)
        if i < len(glyph.components) - 1:
            flags |= MORE_COMPONENTS
        a, b = c["a"], c["b"]
        if flags & ARGS_XY:
            words = not (-128 <= a <= 127 and -128 <= b <= 127)
        else:
            words = not (0 <= a <= 255 and 0 <= b <= 255)
        if words:
            flags |= ARG_WORDS
        out += struct.pack(">HH", flags, c["gid"])
        if words:
            out += struct.pack(">hh" if flags & ARGS_XY else ">HH", a, b)
        else:
            out += struct.pack(">bb" if flags & ARGS_XY else ">BB", a, b)
        out += c["transform"]
    return bytes(out)


# ------------------------------------------------------------------ item variation store (HVAR)

class ItemStore:
    def __init__(self, data: bytes, coords):
        fmt, regions_at, count = struct.unpack(">HIH", data[:8])
        offsets = struct.unpack(f">{count}I", data[8:8 + 4 * count])
        axis_count, region_count = struct.unpack(">HH", data[regions_at:regions_at + 4])
        scalars = []
        at = regions_at + 4
        for _ in range(region_count):
            region = []
            for _ in range(axis_count):
                region.append(tuple(_f2(v) for v in struct.unpack(">hhh", data[at:at + 6])))
                at += 6
            scalars.append(_region_scalar(coords, region))
        self.data, self.offsets, self.scalars = data, offsets, scalars
        self._rows: dict[int, list[float]] = {}

    def delta(self, outer: int, inner: int) -> float:
        if outer >= len(self.offsets):
            return 0.0
        rows = self._rows.get(outer)
        if rows is None:
            rows = self._rows[outer] = self._read(outer)
        return rows[inner] if inner < len(rows) else 0.0

    def _read(self, outer: int) -> list[float]:
        data, at = self.data, self.offsets[outer]
        items, word_count, region_n = struct.unpack(">HHH", data[at:at + 6])
        longs = bool(word_count & 0x8000)
        word_count &= 0x7FFF
        regions = struct.unpack(f">{region_n}H", data[at + 6:at + 6 + 2 * region_n])
        at += 6 + 2 * region_n
        big, small = (">i", 4) if longs else (">h", 2)
        little, tiny = (">h", 2) if longs else (">b", 1)
        weights = [self.scalars[r] if r < len(self.scalars) else 0.0 for r in regions]
        rows = []
        for _ in range(items):
            total = 0.0
            for k in range(region_n):
                if k < word_count:
                    v = struct.unpack(big, data[at:at + small])[0]
                    at += small
                else:
                    v = struct.unpack(little, data[at:at + tiny])[0]
                    at += tiny
                if weights[k]:
                    total += v * weights[k]
            rows.append(total)
        return rows


def _index_map(data: bytes, at: int):
    fmt, entry = data[at], data[at + 1]
    if fmt == 0:
        count = struct.unpack(">H", data[at + 2:at + 4])[0]
        at += 4
    else:
        count = struct.unpack(">I", data[at + 2:at + 6])[0]
        at += 6
    size = ((entry & 0x30) >> 4) + 1
    inner_bits = (entry & 0x0F) + 1
    out = []
    for i in range(count):
        v = int.from_bytes(data[at + i * size:at + (i + 1) * size], "big")
        out.append((v >> inner_bits, v & ((1 << inner_bits) - 1)))
    return out


# ------------------------------------------------------------------ the instance

def _name_table(old: bytes | None, family: str, style: str, postscript: str) -> bytes:
    """A 'name' table with the new names, keeping the font's copyright and licence lines."""
    keep = []
    if old and len(old) >= 6:
        _fmt, count, strings = struct.unpack(">HHH", old[:6])
        for i in range(count):
            platform, encoding, language, name_id, length, offset = struct.unpack(">HHHHHH", old[6 + 12 * i:18 + 12 * i])
            if name_id in (0, 7, 8, 9, 11, 12, 13, 14) and platform == 3:
                keep.append((platform, encoding, language, name_id, old[strings + offset:strings + offset + length]))
    full = f"{family} {style}" if style != "Regular" else family
    for name_id, text in ((1, family), (2, style), (3, f"{postscript};sluka-desktop"), (4, full), (6, postscript), (16, family), (17, style)):
        keep.append((3, 1, 0x409, name_id, text.encode("utf-16-be")))
    keep.sort(key=lambda r: (r[0], r[1], r[2], r[3]))
    records, pool = bytearray(), bytearray()
    for platform, encoding, language, name_id, raw in keep:
        records += struct.pack(">HHHHHH", platform, encoding, language, name_id, len(raw), len(pool))
        pool += raw
    return struct.pack(">HHH", 0, len(keep), 6 + len(records)) + bytes(records) + bytes(pool)


def _checksum(data: bytes) -> int:
    padded = data + b"\x00" * (-len(data) % 4)
    return sum(struct.unpack(f">{len(padded) // 4}I", padded)) & 0xFFFFFFFF


def _sfnt(tables: dict[bytes, bytes]) -> bytes:
    tags = sorted(tables)
    count = len(tags)
    power = 1
    while power * 2 <= count:
        power *= 2
    search = power * 16
    header = struct.pack(">IHHHH", 0x00010000, count, search, power.bit_length() - 1, count * 16 - search)
    offset = 12 + 16 * count
    directory, body = bytearray(), bytearray()
    for tag in tags:
        data = tables[tag]
        directory += tag + struct.pack(">III", _checksum(data), offset + len(body), len(data))
        body += data + b"\x00" * (-len(data) % 4)
    font = bytearray(header + bytes(directory) + bytes(body))
    # head.checkSumAdjustment, now that everything else is in place.
    at = offset + 0
    for tag in tags:
        if tag == b"head":
            break
        at += len(tables[tag]) + (-len(tables[tag]) % 4)
    adjust = (0xB1B0AFBA - _checksum(bytes(font))) & 0xFFFFFFFF
    font[at + 8:at + 12] = struct.pack(">I", adjust)
    return bytes(font)


def variable_info(data: bytes, index: int = 0) -> dict | None:
    """What a font file says of its axes: ``{"axes": [...], "outlines": "glyf"|"CFF2"|...}``; None for a plain font."""
    tables = tables_of(data, index)
    if b"fvar" not in tables:
        return None
    outlines = "glyf" if b"glyf" in tables else "CFF2" if b"CFF2" in tables else "?"
    return {"axes": axes_of(tables[b"fvar"]), "outlines": outlines}


#: Words in a font's own licence lines that say no changed copy of it is to be made: the fonts Microsoft supplies with
#: Windows say "Microsoft supplied font ... Any other use is prohibited".
NO_CHANGES = ("any other use is prohibited", "microsoft supplied font", "you may only (i) embed this font")


def licence_lines(tables: dict[bytes, bytes]) -> list[str]:
    """What the font says of its copyright and its licence: its 'name' table's lines 0, 13 and 14."""
    name = tables.get(b"name") or b""
    found = []
    if len(name) < 6:
        return found
    _fmt, count, strings = struct.unpack(">HHH", name[:6])
    for i in range(count):
        at = 6 + 12 * i
        if at + 12 > len(name):
            break
        platform, encoding, _language, name_id, length, offset = struct.unpack(">HHHHHH", name[at:at + 12])
        if name_id not in (0, 13, 14):
            continue
        raw = name[strings + offset:strings + offset + length]
        text = raw.decode("utf-16-be", "replace") if platform in (0, 3) else raw.decode("latin-1")
        if text and text not in found:
            found.append(text)
    return found


def changes_forbidden(tables: dict[bytes, bytes]) -> str:
    """Why the font's own words let no changed copy of it be made ('' where they do not say so): its embedding
    licence ('OS/2' fsType) "restricted" -- which the OpenType specification says means it must not be modified -- or
    its licence lines saying so (NO_CHANGES)."""
    os2 = tables.get(b"OS/2") or b""
    if len(os2) >= 10:
        fs_type = struct.unpack(">H", os2[8:10])[0]
        if fs_type & 0x000E == 0x0002:
            return "its licence lets no changed copy of it be made (its embedding licence is \"restricted\")"
    for line in licence_lines(tables):
        low = " ".join(line.lower().split())
        if any(words in low for words in NO_CHANGES):
            return "its licence lets no changed copy of it be made (it says: " + " ".join(line.split())[:160] + ")"
    return ""


def instance(data: bytes, location: dict[str, float], family: str, style: str = "Regular",
             weight_class: int | None = None, index: int = 0, deadline: float | None = None) -> bytes:
    """The font of ``data`` at ``location`` (e.g. ``{"wght": 500}``), as a plain TrueType font named ``family``.

    Only where the font's own licence lets a changed copy of it be made (changes_forbidden): the fonts of the Open
    Font License (Noto's, among them those that Windows 11 brings) do; the fonts Microsoft supplies with Windows say
    that any use but showing and printing with them is prohibited, and are refused, as a PostScript one is."""
    tables = tables_of(data, index)
    forbidden = changes_forbidden(tables)
    if forbidden:
        raise FontError(forbidden)
    if b"fvar" not in tables:
        raise FontError("not a variable font")
    if b"glyf" not in tables or b"gvar" not in tables:
        raise FontError("its outlines are not TrueType ones" if b"CFF2" in tables else "it has no glyph variations")
    axes = axes_of(tables[b"fvar"])
    coords = normalized(axes, _avar_maps(tables.get(b"avar"), len(axes)), location)

    head = bytearray(tables[b"head"])
    long_loca = struct.unpack(">h", head[50:52])[0] == 1
    count = struct.unpack(">H", tables[b"maxp"][4:6])[0]
    loca_raw = tables[b"loca"]
    if long_loca:
        loca = struct.unpack(f">{count + 1}I", loca_raw[:4 * (count + 1)])
    else:
        loca = [v * 2 for v in struct.unpack(f">{count + 1}H", loca_raw[:2 * (count + 1)])]
    glyf = tables[b"glyf"]
    hhea = bytearray(tables[b"hhea"])
    metrics_n = struct.unpack(">H", hhea[34:36])[0]
    hmtx = tables[b"hmtx"]
    widths, lsbs = [], []
    for gid in range(count):
        if gid < metrics_n:
            w, l = struct.unpack(">Hh", hmtx[4 * gid:4 * gid + 4])
        else:
            w = widths[-1]
            l = struct.unpack(">h", hmtx[4 * metrics_n + 2 * (gid - metrics_n):4 * metrics_n + 2 * (gid - metrics_n) + 2])[0]
        widths.append(w)
        lsbs.append(l)

    hvar_store = hvar_map = None
    if b"HVAR" in tables:
        hvar = tables[b"HVAR"]
        store_at, map_at = struct.unpack(">II", hvar[4:12])
        if store_at:
            hvar_store = ItemStore(hvar[store_at:], coords)
            hvar_map = _index_map(hvar, map_at) if map_at else None

    gvar = tables[b"gvar"]
    axis_count, shared_n = struct.unpack(">HH", gvar[4:8])
    shared_at = struct.unpack(">I", gvar[8:12])[0]
    gvar_count, gvar_flags = struct.unpack(">HH", gvar[12:16])
    data_at = struct.unpack(">I", gvar[16:20])[0]
    if gvar_flags & 1:
        voffsets = struct.unpack(f">{gvar_count + 1}I", gvar[20:20 + 4 * (gvar_count + 1)])
    else:
        voffsets = [v * 2 for v in struct.unpack(f">{gvar_count + 1}H", gvar[20:20 + 2 * (gvar_count + 1)])]
    shared = []
    for i in range(shared_n):
        at = shared_at + 2 * axis_count * i
        shared.append([_f2(v) for v in struct.unpack(f">{axis_count}h", gvar[at:at + 2 * axis_count])])

    def deltas_for(gid: int, coords_of, ends) -> list[tuple[float, float]] | None:
        """Summed deltas for the glyph's points (phantom points last); None where it has none."""
        if gid >= gvar_count:
            return None
        start, end = data_at + voffsets[gid], data_at + voffsets[gid + 1]
        if end <= start:
            return None
        g = gvar[start:end]
        tuple_count, offset = struct.unpack(">HH", g[:4])
        shared_points = bool(tuple_count & 0x8000)
        tuple_count &= 0x0FFF
        n = len(coords_of)
        total = [[0.0, 0.0] for _ in range(n)]
        headers, at = [], 4
        for _ in range(tuple_count):
            size, index_flags = struct.unpack(">HH", g[at:at + 4])
            at += 4
            if index_flags & 0x8000:
                peak = [_f2(v) for v in struct.unpack(f">{axis_count}h", g[at:at + 2 * axis_count])]
                at += 2 * axis_count
            else:
                peak = shared[index_flags & 0x0FFF]
            s = e = None
            if index_flags & 0x4000:
                s = [_f2(v) for v in struct.unpack(f">{axis_count}h", g[at:at + 2 * axis_count])]
                e = [_f2(v) for v in struct.unpack(f">{axis_count}h", g[at + 2 * axis_count:at + 4 * axis_count])]
                at += 4 * axis_count
            headers.append((size, index_flags, peak, s, e))
        data_pos = offset
        common = None
        if shared_points:
            common, data_pos = _points(g, data_pos)
        any_delta = False
        for size, index_flags, peak, s, e in headers:
            here = data_pos
            data_pos += size
            scalar = _tuple_scalar(coords, peak, s, e)
            if scalar == 0.0:
                continue
            points = common
            if index_flags & 0x2000:
                points, here = _points(g, here)
            m = n if points is None else len(points)
            xs, here = _deltas(g, here, m)
            ys, here = _deltas(g, here, m)
            if points is None:
                for i in range(n):
                    total[i][0] += xs[i] * scalar
                    total[i][1] += ys[i] * scalar
                any_delta = True
                continue
            raw = [(0.0, 0.0)] * n
            touched = [False] * n
            for p, dx, dy in zip(points, xs, ys):
                if p < n:
                    raw[p] = (dx, dy)
                    touched[p] = True
            if ends is not None:
                # Points of a contour the tuple leaves out move with their neighbours (IUP).
                first = 0
                for last in ends:
                    seg = slice(first, last + 1)
                    filled = _iup_contour(raw[seg], coords_of[seg], touched[seg])
                    raw[seg] = filled
                    first = last + 1
            for i in range(n):
                dx, dy = raw[i]
                if dx or dy:
                    total[i][0] += dx * scalar
                    total[i][1] += dy * scalar
            any_delta = True
        return [(dx, dy) for dx, dy in total] if any_delta else None

    glyphs: list[Glyph] = []
    bounds: list = [None] * count
    for gid in range(count):
        if deadline is not None and gid % 512 == 0 and time.monotonic() > deadline:
            raise FontError("it took too long")
        raw = glyf[loca[gid]:loca[gid + 1]]
        glyph = parse_glyph(raw)
        if glyph.kind == "simple":
            pts = glyph.points
            xmin = min(p[0] for p in pts) if pts else 0
            ymax = max(p[1] for p in pts) if pts else 0
            pp1x = xmin - lsbs[gid]
            phantom = [(pp1x, 0), (pp1x + widths[gid], 0), (0, ymax), (0, 0)]
            deltas = deltas_for(gid, pts + phantom, glyph.ends)
            if deltas:
                moved = [(x + dx, y + dy) for (x, y), (dx, dy) in zip(pts + phantom, deltas)]
                new_pp1 = moved[len(pts)][0]
                new_pp2 = moved[len(pts) + 1][0]
                shift = round(new_pp1)
                glyph.points = [(round(x) - shift, round(y)) for x, y in moved[:len(pts)]]
                widths[gid] = max(0, round(new_pp2 - new_pp1))
        elif glyph.kind == "composite":
            offsets = [(c["a"], c["b"]) if c["flags"] & ARGS_XY else (0, 0) for c in glyph.components]
            # The width a composite has is its own (phantom points), however its parts are placed.
            phantom = [(0 - lsbs[gid], 0), (0 - lsbs[gid] + widths[gid], 0), (0, 0), (0, 0)]
            deltas = deltas_for(gid, offsets + phantom, None)
            if deltas:
                for c, (dx, dy) in zip(glyph.components, deltas):
                    if c["flags"] & ARGS_XY:
                        c["a"], c["b"] = round(c["a"] + dx), round(c["b"] + dy)
                pp1 = phantom[0][0] + deltas[len(offsets)][0]
                pp2 = phantom[1][0] + deltas[len(offsets) + 1][0]
                widths[gid] = max(0, round(pp2 - pp1))
                # Where the left side bearing point moved, the glyph moves with it, as a renderer moves it.
                shift = round(deltas[len(offsets)][0])
                if shift:
                    for c in glyph.components:
                        if c["flags"] & ARGS_XY:
                            c["a"] -= shift
        glyphs.append(glyph)

    if hvar_store is not None:
        # Where the font says how its widths move, that is what they do.
        default_widths = []
        for gid in range(count):
            w = struct.unpack(">H", hmtx[4 * min(gid, metrics_n - 1):4 * min(gid, metrics_n - 1) + 2])[0]
            default_widths.append(w)
        for gid in range(count):
            if hvar_map is not None:
                outer, inner = hvar_map[min(gid, len(hvar_map) - 1)] if hvar_map else (0, gid)
            else:
                outer, inner = 0, gid
            widths[gid] = max(0, round(default_widths[gid] + hvar_store.delta(outer, inner)))

    def bbox(gid: int, depth: int = 0):
        if bounds[gid] is not None:
            return bounds[gid]
        glyph = glyphs[gid]
        if glyph.kind == "simple" and glyph.points:
            xs = [p[0] for p in glyph.points]
            ys = [p[1] for p in glyph.points]
            box = (min(xs), min(ys), max(xs), max(ys))
        elif glyph.kind == "composite" and depth < 8:
            corners = []
            for c in glyph.components:
                if c["gid"] >= count:
                    continue
                inner = bbox(c["gid"], depth + 1)
                if inner is None:
                    continue
                a, b, cc, d = _matrix(c)
                dx, dy = (c["a"], c["b"]) if c["flags"] & ARGS_XY else (0, 0)
                for x, y in ((inner[0], inner[1]), (inner[0], inner[3]), (inner[2], inner[1]), (inner[2], inner[3])):
                    corners.append((a * x + cc * y + dx, b * x + d * y + dy))
            if not corners:
                return None
            box = (int(min(c[0] for c in corners) // 1), int(min(c[1] for c in corners) // 1),
                   int(-(-max(c[0] for c in corners) // 1)), int(-(-max(c[1] for c in corners) // 1)))
        else:
            return None
        bounds[gid] = box
        return box

    out_glyf, offsets, lsb_out = bytearray(), [], []
    for gid, glyph in enumerate(glyphs):
        offsets.append(len(out_glyf))
        box = bbox(gid)
        if glyph.kind == "simple":
            encoded = _encode_simple(glyph)
        elif glyph.kind == "composite":
            encoded = _encode_composite(glyph, box or (0, 0, 0, 0))
        else:
            encoded = b""
        out_glyf += encoded + b"\x00" * (-len(encoded) % 4)
        lsb_out.append(box[0] if box else 0)
    offsets.append(len(out_glyf))

    hmtx_out = bytearray()
    for w, l in zip(widths, lsb_out):
        hmtx_out += struct.pack(">Hh", w, max(-32768, min(32767, l)))
    boxes = [b for b in (bbox(g) for g in range(count)) if b]
    if boxes:
        struct.pack_into(">hhhh", head, 36, min(b[0] for b in boxes), min(b[1] for b in boxes), max(b[2] for b in boxes), max(b[3] for b in boxes))
    struct.pack_into(">h", head, 50, 1)                      # long offsets in 'loca'
    struct.pack_into(">I", head, 8, 0)                       # checkSumAdjustment, set at the end
    struct.pack_into(">H", head, 44, 0)                      # macStyle: neither bold nor italic, the name says the weight
    struct.pack_into(">H", hhea, 10, max(widths) if widths else 0)
    struct.pack_into(">H", hhea, 34, count)
    out = {tag: data for tag, data in tables.items() if tag not in DROPPED}
    out[b"glyf"] = bytes(out_glyf)
    out[b"loca"] = struct.pack(f">{count + 1}I", *offsets)
    out[b"hmtx"] = bytes(hmtx_out)
    out[b"head"] = bytes(head)
    out[b"hhea"] = bytes(hhea)
    if b"OS/2" in out and len(out[b"OS/2"]) >= 64:
        os2 = bytearray(out[b"OS/2"])
        weight = int(weight_class if weight_class is not None else location.get("wght", struct.unpack(">H", os2[4:6])[0]))
        struct.pack_into(">H", os2, 4, max(1, min(1000, weight)))
        selection = struct.unpack(">H", os2[62:64])[0]
        selection = (selection & ~0x0061) | 0x0040          # REGULAR; neither ITALIC nor BOLD
        struct.pack_into(">H", os2, 62, selection)
        out[b"OS/2"] = bytes(os2)
    if b"post" in out and len(out[b"post"]) >= 32:
        # Glyph names are of no use to a renderer, and version 2's would have to be kept in step: version 3.
        post = bytearray(out[b"post"][:32])
        struct.pack_into(">I", post, 0, 0x00030000)
        out[b"post"] = bytes(post)
    postscript = "".join(ch for ch in family if ch.isalnum()) + "-" + "".join(ch for ch in style if ch.isalnum())
    out[b"name"] = _name_table(tables.get(b"name"), family, style, postscript[:63])
    return _sfnt(out)
