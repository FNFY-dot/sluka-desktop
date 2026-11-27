# SPDX-License-Identifier: LicenseRef-Sluka
# Copyright (c) 2026 Sluka. Part of Sluka Desktop; see LICENSE.txt.
"""Which faces Sluka's font lists come to on this computer, and their measures: for the look in mpv on Windows.

On Linux the script in mpv asks fontconfig (``fc-list``, ``fc-match``) which
of the faces a page names are installed, which face holds a language's letters,
and where the files are, and reads each face's vertical measures from its file.
Windows has no fontconfig.  So there the app does all of it here and sends the
script the outcome (``look.faces``): the font files are read directly -- their
names, their measures, which letters they hold -- and a list of faces is
resolved the way a Chromium browser on Windows resolves it.

Nothing here is Windows' own interface except where the font folders are, so
the same code is tried on any folder of fonts.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import struct
import threading
import time
from pathlib import Path

log = logging.getLogger("sluka.fonts")

SUFFIXES = (".ttf", ".otf", ".ttc", ".otc")

#: What a browser's generic names stand for (as in mpv/sluka.lua): "ui" is the system's own face.
GENERIC = {
    "system-ui": "ui", "ui-sans-serif": "ui", "sans-serif": "sans-serif", "serif": "serif", "monospace": "monospace",
    "-apple-system": "", "blinkmacsystemfont": "", "ui-serif": "serif", "ui-monospace": "monospace",
}
#: The faces a Chromium browser on Windows takes the generic names for, first installed first.
WINDOWS_GENERIC = {
    "ui": ("Segoe UI", "Tahoma", "Arial"),
    "sans-serif": ("Arial", "Segoe UI", "Tahoma"),
    "serif": ("Times New Roman", "Georgia"),
    "monospace": ("Consolas", "Courier New"),
}
#: Where Windows goes for a language's letters when the face asked for has none, by kind of face.
WINDOWS_FALLBACK = {
    "ja": {"sans-serif": ("Yu Gothic UI", "Meiryo UI", "Yu Gothic", "Meiryo", "MS UI Gothic", "MS PGothic", "MS Gothic"),
           "serif": ("Yu Mincho", "BIZ UDPMincho", "MS PMincho", "MS Mincho")},
    "ko": {"sans-serif": ("Malgun Gothic", "Gulim", "Dotum"), "serif": ("Batang", "Malgun Gothic")},
    "zh-hk": {"sans-serif": ("Microsoft JhengHei UI", "Microsoft JhengHei", "PMingLiU", "MingLiU"), "serif": ("PMingLiU", "MingLiU", "Microsoft JhengHei")},
    "zh-tw": {"sans-serif": ("Microsoft JhengHei UI", "Microsoft JhengHei", "PMingLiU", "MingLiU"), "serif": ("PMingLiU", "MingLiU", "Microsoft JhengHei")},
    "zh-cn": {"sans-serif": ("Microsoft YaHei UI", "Microsoft YaHei", "SimSun"), "serif": ("SimSun", "NSimSun", "Microsoft YaHei")},
    "th": {"sans-serif": ("Leelawadee UI", "Tahoma"), "serif": ("Leelawadee UI", "Tahoma")},
    "ar": {"sans-serif": ("Segoe UI", "Tahoma", "Arial"), "serif": ("Times New Roman", "Segoe UI")},
    "ru": {"sans-serif": ("Segoe UI", "Arial"), "serif": ("Times New Roman",)},
    "uk": {"sans-serif": ("Segoe UI", "Arial"), "serif": ("Times New Roman",)},
    "el": {"sans-serif": ("Segoe UI", "Arial"), "serif": ("Times New Roman",)},
}
#: A few letters by which a face is known to hold a language's writing (the names fontconfig has for languages).
SAMPLES = {
    "ja": (0x3042, 0x30A2, 0x65E5, 0x8A9E), "ko": (0xD55C, 0xAE00), "zh-hk": (0x7684, 0x4E2D), "zh-tw": (0x7684, 0x4E2D),
    "zh-cn": (0x7684, 0x4E2D), "zh": (0x7684, 0x4E2D), "th": (0x0E01, 0x0E44), "ar": (0x0627, 0x0644),
    "ru": (0x042F, 0x0436), "uk": (0x0454, 0x0457), "el": (0x03B1, 0x03A9),
}


def _u16(data: bytes, at: int) -> int:
    return struct.unpack_from(">H", data, at)[0]


def _i16(data: bytes, at: int) -> int:
    return struct.unpack_from(">h", data, at)[0]


def _u32(data: bytes, at: int) -> int:
    return struct.unpack_from(">I", data, at)[0]


class Face:
    """One face in a font file: its names, weight, and where its tables are."""

    __slots__ = ("path", "index", "names", "english", "legacy", "weight", "italic", "tables", "wght", "outlines", "_measures", "_cmap")

    def __init__(self, path: str, index: int, tables: dict):
        self.path, self.index, self.tables = path, index, tables
        self.names: list[str] = []
        self.english = ""
        #: The face's older family name (name 1), which is the one Windows' older interface -- and so mpv's
        #: renderer -- knows it by: "Segoe UI Semibold" for the face a page knows as "Segoe UI" at 600.
        self.legacy = ""
        self.weight, self.italic = 400, False
        #: A variable font's weight axis: (lightest, the weight the file is drawn at by default, heaviest).
        self.wght: tuple[float, float, float] | None = None
        self.outlines = "glyf" if "glyf" in tables else "CFF2" if "CFF2" in tables else "CFF" if "CFF " in tables else ""
        self._measures = None
        self._cmap = None

    @property
    def variable(self) -> bool:
        return self.wght is not None

    # ---- measures, as mpv/sluka.lua reads them (read_metrics), with one difference said below

    def measures(self) -> dict | None:
        if self._measures is None:
            self._measures = self._read_measures() or False
        return self._measures or None

    def _table(self, handle, tag: str, most: int = 0) -> bytes:
        found = self.tables.get(tag)
        if not found:
            return b""
        handle.seek(found[0])
        return handle.read(min(found[1], most) if most else found[1])

    def _read_measures(self) -> dict | None:
        try:
            with open(self.path, "rb") as handle:
                head, hhea, os2 = self._table(handle, "head", 54), self._table(handle, "hhea", 36), self._table(handle, "OS/2", 96)
        except OSError:
            return None
        if len(head) < 20 or len(hhea) < 8:
            return None
        upm = _u16(head, 18)
        if upm < 16:
            return None
        ha, hd = _i16(hhea, 4) / upm, -_i16(hhea, 6) / upm
        wa, wd = ha, hd
        if len(os2) >= 78:
            win_a, win_d = _u16(os2, 74), _u16(os2, 76)
            typo_a, typo_d = _i16(os2, 68), -_i16(os2, 70)
            use_typo = bool(_u16(os2, 62) & 0x80)
            # The subtitle renderer goes by the Windows numbers where the face has them.
            if win_a + win_d:
                wa, wd = win_a / upm, win_d / upm
            # A page on Windows goes by them as well (a browser there asks DirectWrite, which gives these),
            # unless the face says its typographic ones are the ones to use.  On Linux a page goes by the
            # horizontal header instead, which is the one thing sluka.lua does differently for its own reading.
            if use_typo and typo_a + typo_d:
                ha, hd = typo_a / upm, typo_d / upm
            elif win_a + win_d:
                ha, hd = wa, wd
        if wa + wd <= 0.2 or ha + hd <= 0.2:
            return None
        return {"wa": round(wa, 5), "wd": round(wd, 5), "ha": round(ha, 5), "hd": round(hd, 5)}

    # ---- which letters it holds

    def has(self, codepoint: int) -> bool:
        if self._cmap is None:
            self._cmap = self._read_cmap()
        kind, data = self._cmap
        if kind == 12:
            groups = _u32(data, 12)
            low, high = 0, groups - 1
            while low <= high:
                mid = (low + high) // 2
                start, end = struct.unpack_from(">II", data, 16 + 12 * mid)
                if codepoint < start:
                    high = mid - 1
                elif codepoint > end:
                    low = mid + 1
                else:
                    return True
            return False
        if kind == 4 and codepoint <= 0xFFFF:
            count = _u16(data, 6) // 2
            ends, starts = 14, 16 + 2 * count
            deltas, ranges = starts + 2 * count, starts + 4 * count
            for i in range(count):
                end = _u16(data, ends + 2 * i)
                if codepoint > end:
                    continue
                start = _u16(data, starts + 2 * i)
                if codepoint < start or start == 0xFFFF:
                    return False
                offset = _u16(data, ranges + 2 * i)
                if not offset:
                    return (codepoint + _u16(data, deltas + 2 * i)) & 0xFFFF != 0
                at = ranges + 2 * i + offset + 2 * (codepoint - start)
                return at + 2 <= len(data) and _u16(data, at) != 0
        return False

    def _read_cmap(self) -> tuple[int, bytes]:
        try:
            with open(self.path, "rb") as handle:
                data = self._table(handle, "cmap")
        except OSError:
            return (0, b"")
        try:
            best = None
            for i in range(_u16(data, 2)):
                platform, encoding, offset = struct.unpack_from(">HHI", data, 4 + 8 * i)
                kind = _u16(data, offset)
                # Unicode's own tables: the full one (12) before the one for the first 65536 letters (4).
                if kind in (4, 12) and (platform == 0 or (platform == 3 and encoding in (1, 10))):
                    rank = (kind == 12, platform == 3)
                    if best is None or rank > best[0]:
                        best = (rank, kind, offset)
            if best is None:
                return (0, b"")
            _rank, kind, offset = best
            length = _u32(data, offset + 4) if kind == 12 else _u16(data, offset + 2)
            return (kind, data[offset:offset + length])
        except (struct.error, IndexError):
            return (0, b"")

    def holds(self, lang: str) -> bool:
        samples = SAMPLES.get(lang) or SAMPLES.get(lang.split("-")[0])
        if not samples:
            return True
        try:
            return all(self.has(c) for c in samples)
        except (struct.error, IndexError):
            return False


def _decode(platform: int, encoding: int, raw: bytes) -> str:
    try:
        if platform in (0, 3):
            return raw.decode("utf-16-be")
        if platform == 1 and encoding == 0:
            return raw.decode("mac_roman")
    except UnicodeDecodeError:
        pass
    return ""


def read_file(path: str) -> list[Face]:
    """The faces in one font file (several in a collection), with their names; [] if it is not a font this reads."""
    faces: list[Face] = []
    try:
        with open(path, "rb") as handle:
            start = handle.read(12)
            if len(start) < 12:
                return []
            offsets = [0]
            if start[:4] == b"ttcf":
                count = min(_u32(start, 8), 64)
                offsets = list(struct.unpack(f">{count}I", handle.read(4 * count)))
            for index, base in enumerate(offsets):
                handle.seek(base)
                header = handle.read(12)
                if len(header) < 12 or header[:4] not in (b"\x00\x01\x00\x00", b"OTTO", b"true", b"typ1"):
                    continue
                n = _u16(header, 4)
                if not 0 < n <= 512:
                    continue
                directory = handle.read(16 * n)
                tables = {}
                for i in range(n):
                    tag, _sum, offset, length = struct.unpack_from(">4sIII", directory, 16 * i)
                    tables[tag.decode("latin-1")] = (offset, length)
                face = Face(path, index, tables)
                names = face._table(handle, "name", 256 * 1024)
                if len(names) < 6:
                    continue
                count, strings = _u16(names, 2), _u16(names, 4)
                family, typographic = [], []
                for i in range(count):
                    at = 6 + 12 * i
                    if at + 12 > len(names):
                        break
                    platform, encoding, language, name_id, length, offset = struct.unpack_from(">6H", names, at)
                    if name_id not in (1, 16):
                        continue
                    text = _decode(platform, encoding, names[strings + offset:strings + offset + length]).strip("\0 ").strip()
                    if not text:
                        continue
                    english = (platform == 3 and language == 0x409) or (platform == 1 and language == 0) or platform == 0
                    (typographic if name_id == 16 else family).append((english, text))
                # The family a page names is the typographic one where a face has it ("Yu Gothic UI", of which
                # "Yu Gothic UI Semibold" is a member); the older name is known too.
                for group in (typographic, family):
                    for english, text in group:
                        if text not in face.names:
                            face.names.append(text)
                        if english and not face.english:
                            face.english = text
                if not face.names:
                    continue
                face.english = face.english or face.names[0]
                face.legacy = next((text for english, text in family if english), family[0][1] if family else face.english)
                os2 = face._table(handle, "OS/2", 64)
                if len(os2) >= 64:
                    face.weight = _u16(os2, 4) or 400
                    face.italic = bool(_u16(os2, 62) & 0x01)
                if "fvar" in tables:
                    face.wght = _weight_axis(face._table(handle, "fvar", 4096))
                faces.append(face)
    except (OSError, struct.error, IndexError, ValueError):
        return faces
    return faces


def _weight_axis(fvar: bytes) -> tuple[float, float, float] | None:
    """A variable font's weight axis, (lightest, default, heaviest); None where it has none."""
    try:
        offset, _res, count, size = struct.unpack_from(">HHHH", fvar, 4)
        for i in range(count):
            at = offset + i * size
            if fvar[at:at + 4] == b"wght":
                lo, default, hi = struct.unpack_from(">iii", fvar, at + 4)
                return lo / 65536.0, default / 65536.0, hi / 65536.0
    except struct.error:
        pass
    return None


#: The weights the script in mpv sets each of its faces in (mpv/sluka.lua: the line at 500; the card and
#: panel at 400, 500 and 600; the headword at 400).
USE_WEIGHTS = {"cc": (500,), "ui": (400, 500, 600), "word": (400,)}
#: How thick a stroke of a CJK face is at a weight, as a share of its size (Noto Sans CJK's, measured): for
#: thickening a variable face mpv can only draw at its default weight, where no plain copy of it is to be had.
STEMS = ((100, 0.0294), (300, 0.0498), (350, 0.070), (400, 0.078), (500, 0.100), (700, 0.126), (900, 0.154))
#: Bumped when what the app makes of a variable font changes, so that copies made before are made again.
INSTANCE_FORMAT = 1


def _stem(weight: float) -> float:
    if weight <= STEMS[0][0]:
        return STEMS[0][1]
    for (w0, s0), (w1, s1) in zip(STEMS, STEMS[1:]):
        if weight <= w1:
            return s0 + (weight - w0) * (s1 - s0) / (w1 - w0)
    return STEMS[-1][1]


def thickening(default: float, weight: float) -> float:
    """How much thicker (a share of the size) a face drawn at its ``default`` weight is to be made to look ``weight``.

    libass already thickens a face asked for 150 or more above its own weight, by a sixty-fourth of its size."""
    extra = _stem(weight) - _stem(default)
    if weight > default + 150:
        extra -= 1 / 64
    return round(max(0.0, extra), 4)


def css_weight(available: list[int], wanted: int) -> int:
    """The weight a browser takes from a family's ``available`` ones for ``wanted`` (CSS Fonts, font matching)."""
    have = sorted(set(available))
    if wanted in have:
        return wanted
    below = [w for w in have if w < wanted]
    above = [w for w in have if w > wanted]
    if 400 <= wanted <= 500:
        up_to_500 = [w for w in above if w <= 500]
        if up_to_500:
            return up_to_500[0]
        if below:
            return below[-1]
        return above[0]
    if wanted < 400:
        return below[-1] if below else above[0]
    return above[0] if above else below[-1]


def windows_font_files(env=None) -> list[str]:
    """Every font file Windows has installed: its own folder, the user's, and what the registry lists elsewhere."""
    env = os.environ if env is None else env
    folders = [os.path.join(env.get("WINDIR") or env.get("SystemRoot") or r"C:\Windows", "Fonts")]
    if env.get("LOCALAPPDATA"):
        folders.append(os.path.join(env["LOCALAPPDATA"], "Microsoft", "Windows", "Fonts"))
    found: dict[str, str] = {}
    for folder in folders:
        try:
            for name in os.listdir(folder):
                if name.lower().endswith(SUFFIXES):
                    found.setdefault(os.path.join(folder, name).lower(), os.path.join(folder, name))
        except OSError:
            pass
    try:
        import winreg

        for hive in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
            try:
                with winreg.OpenKey(hive, r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\Fonts") as key:
                    for i in range(winreg.QueryInfoKey(key)[1]):
                        value = str(winreg.EnumValue(key, i)[1] or "")
                        # A bare file name is in the fonts folder, and was found there; a whole path is somewhere else.
                        if os.path.isabs(value) and value.lower().endswith(SUFFIXES) and os.path.isfile(value):
                            found.setdefault(value.lower(), value)
            except OSError:
                pass
    except ImportError:
        pass
    return sorted(found.values())


def folder_font_files(folders: list[str]) -> list[str]:
    found = []
    for folder in folders:
        for top, _dirs, names in os.walk(folder):
            found += [os.path.join(top, name) for name in names if name.lower().endswith(SUFFIXES)]
    return sorted(found)


class Finder:
    """The faces of this computer, read once, and what a page's list of faces comes to among them."""

    def __init__(self, files=None, generic=None, fallback=None, mpv_font_dirs=None, state_file=None):
        self._files = files
        self.generic = WINDOWS_GENERIC if generic is None else generic
        self.fallback = WINDOWS_FALLBACK if fallback is None else fallback
        self.families: dict[str, list[Face]] = {}
        self._lock = threading.Lock()
        self._read = False
        self._answers: dict[str, dict | None] = {}
        self._chosen: dict[str, tuple[Face, Face] | None] = {}
        #: mpv's fonts folders (beside each scripts folder the app writes into), where the plain copies of
        #: variable faces go; and the file that remembers which copies were asked for.
        self.mpv_font_dirs: list[Path] = [Path(d) for d in (mpv_font_dirs or [])]
        self.state_file = Path(state_file) if state_file else None
        self._wanted: dict[str, dict] = {}
        self._queue: list[tuple] = []
        self._building = False
        self._made: set[str] = set()
        self._work_lock = threading.Lock()

    def warm(self) -> None:
        """Read the fonts now, apart, so that the first video does not wait for it; and make the copies asked for before."""
        def read_and_make() -> None:
            self._load()
            self._make_remembered()

        threading.Thread(target=read_and_make, name="sluka-fonts", daemon=True).start()

    def _load(self) -> None:
        with self._lock:
            if self._read:
                return
            files = self._files() if callable(self._files) else (self._files if self._files is not None else windows_font_files())
            families: dict[str, list[Face]] = {}
            count = 0
            for path in files:
                for face in read_file(path):
                    count += 1
                    for name in face.names:
                        families.setdefault(name.lower(), []).append(face)
            self.families = families
            self._read = True
            log.info("%d faces in %d font files, under %d names", count, len(files), len(families))

    def face(self, name: str) -> Face | None:
        """The upright, regular face of a family, or the nearest to it there is."""
        self._load()
        found = self.families.get(name.strip().lower())
        if not found:
            return None
        return min(found, key=lambda f: (f.italic, abs(f.weight - 400), f.english.lower() != name.strip().lower(), f.index))

    def _described(self, face: Face) -> dict:
        out = {"name": face.english}
        out.update(face.measures() or {})
        return out

    def _generic(self, kind: str, ui_font: str) -> Face | None:
        names = self.generic.get(kind, ())
        if kind == "ui" and ui_font:
            names = (ui_font,) + tuple(names)
        for name in names:
            face = self.face(name)
            if face:
                return face
        return None

    def resolve(self, stack: list[str], lang: str = "", ui_font: str = "") -> dict | None:
        """``{"P": face, "G": face}`` for a list of faces: the first there is, and the one that holds the language's letters."""
        key = "\1".join(stack) + "\2" + lang + "\2" + ui_font
        if key in self._answers:
            return self._answers[key]
        self._load()
        answer = self._resolve(stack, lang, ui_font) if self.families else None
        self._answers[key] = answer
        return answer

    def chosen(self, stack: list[str], lang: str = "", ui_font: str = "") -> tuple[Face, Face] | None:
        """The two faces resolve() described."""
        key = "\1".join(stack) + "\2" + lang + "\2" + ui_font
        if key not in self._answers:
            self.resolve(stack, lang, ui_font)
        return self._chosen.get(key)

    def _resolve(self, stack: list[str], lang: str, ui_font: str) -> dict | None:
        kind = "sans-serif"
        for name in stack:
            generic = GENERIC.get(str(name).lower())
            if generic:
                kind = "sans-serif" if generic == "ui" else generic
                break
        first = None
        for name in stack:
            generic = GENERIC.get(str(name).lower())
            if generic is None:
                first = self.face(str(name))
            elif generic:
                first = self._generic(generic, ui_font)
            if first:
                break
        first = first or self._generic(kind, ui_font) or self._generic("sans-serif", ui_font)
        if not first:
            return None
        letters = first
        if lang and not first.holds(lang):
            letters = None
            wanted = self.fallback.get(lang) or self.fallback.get(lang.split("-")[0]) or {}
            for name in tuple(wanted.get(kind, ())) + tuple(wanted.get("sans-serif", ())):
                face = self.face(name)
                if face and face.holds(lang):
                    letters = face
                    break
            if letters is None:
                # None of the usual ones: any face that holds the letters, the plainest name first.
                for name in sorted(self.families, key=len):
                    face = self.face(name)
                    if face and not face.italic and face.holds(lang):
                        letters = face
                        break
            letters = letters or first
        self._chosen["\1".join(stack) + "\2" + lang + "\2" + ui_font] = (first, letters)
        return {"P": self._described(first), "G": self._described(letters)}

    def faces(self, stacks: dict, lang: str = "", ui_font: str = "", weights: dict | None = None) -> dict | None:
        """The three uses the script in mpv has (``cc``, ``ui``, ``word``), each resolved; None if no font could be read.

        Each face says, for each weight the script sets it in, which face of
        its family a browser draws there and how mpv's renderer is to ask for
        that one (``w``): see plan()."""
        out = {}
        for use, stack in stacks.items():
            if isinstance(stack, list) and stack:
                names = [str(s) for s in stack][:24]
                found = self.resolve(names, lang, ui_font)
                if not found:
                    continue
                entry = {role: dict(found[role]) for role in ("P", "G")}
                pair = self.chosen(names, lang, ui_font)
                wanted = (weights or {}).get(str(use)) or USE_WEIGHTS.get(str(use), (400,))
                if pair:
                    for role, face in zip(("P", "G"), pair):
                        plans = {}
                        for weight in wanted:
                            try:
                                plans[str(int(weight))] = self.plan(face, int(weight))
                            except (OSError, ValueError):
                                log.exception("how mpv is to draw %s at %s could not be worked out", face.english, weight)
                        entry[role]["w"] = plans
                out[str(use)] = entry
        return out or None

    # ------------------------------------------------------------ the face of a weight, for mpv's renderer

    def members(self, face: Face) -> list[Face]:
        """The upright faces of a face's family (as a page names it)."""
        found = [f for f in self.families.get(face.english.lower(), []) if not f.italic]
        return found or [face]

    def plan(self, face: Face, weight: int) -> dict:
        """How mpv's renderer is to ask for the face a browser draws ``face``'s family in at ``weight``.

        ``{"n": name, "b": weight}``: a plain face, asked for by the older
        family name Windows' older interface knows it by ("Segoe UI Semibold"),
        which is how libass finds faces there.  A variable face at another
        weight than its default is drawn by libass at the default whatever it
        is asked for, so a plain copy of it at ``weight`` is made into mpv's
        fonts folder under a name of its own (``"file"``); ``"via"`` says what
        to do in a player that started before the copy was there (the
        variable face, made to look thicker by ``x``, a share of its size)."""
        family = self.members(face)
        variable = next((f for f in family if f.variable), None)
        if variable is not None and variable.wght[0] - 1 <= weight <= variable.wght[2] + 1:
            low, default, high = variable.wght
            name = variable.legacy or variable.english
            if abs(weight - default) <= 1:
                return {"n": name, "b": weight}
            fallback = {"n": name, "b": weight, "x": thickening(default, weight)}
            if variable.outlines != "glyf" or not self.mpv_font_dirs:
                return fallback
            copy_family, filename = self._copy_names(variable, weight)
            self._want(variable, weight, copy_family, filename)
            return {"n": copy_family, "b": weight, "file": filename, "via": fallback}
        picked = css_weight([f.weight for f in family], weight)
        best = min((f for f in family if f.weight == picked),
                   key=lambda f: (f.legacy.lower() != face.english.lower(), f.index))
        return {"n": best.legacy or best.english, "b": best.weight}

    def _copy_names(self, face: Face, weight: int) -> tuple[str, str]:
        try:
            st = os.stat(face.path)
            stamp = f"{st.st_size}|{st.st_mtime_ns}"
        except OSError:
            stamp = "?"
        key = f"{os.path.normcase(face.path)}|{face.index}|{stamp}|{weight}|{INSTANCE_FORMAT}"
        digest = hashlib.sha1(key.encode("utf-8")).hexdigest()[:8]
        stem = "".join(ch for ch in face.english if ch.isalnum()) or "Face"
        return f"Sluka {face.english} {weight}", f"Sluka-{stem}-{weight}-{digest}.ttf"

    def _want(self, face: Face, weight: int, family: str, filename: str) -> None:
        with self._work_lock:
            if filename in self._made or any(job[3] == filename for job in self._queue):
                return
            if all((folder / filename).is_file() for folder in self.mpv_font_dirs):
                self._made.add(filename)
                self._remember(face, weight, family, filename)
                return
            self._queue.append((face, weight, family, filename))
            self._remember(face, weight, family, filename)
            if self._building:
                return
            self._building = True
        threading.Thread(target=self._work, name="sluka-font-copies", daemon=True).start()

    def _work(self) -> None:
        while True:
            with self._work_lock:
                if not self._queue:
                    self._building = False
                    return
                face, weight, family, filename = self._queue.pop(0)
            began = time.monotonic()
            try:
                from . import varfont

                with open(face.path, "rb") as handle:
                    data = handle.read()
                made = varfont.instance(data, {"wght": weight}, family=family, weight_class=weight, index=face.index,
                                        deadline=time.monotonic() + 600)
            except Exception as err:
                log.warning("a plain copy of %s at %d for mpv could not be made: %s", face.english, weight, err)
                with self._work_lock:
                    self._made.add(filename)  # not tried again until the next start
                continue
            stem = filename.rsplit("-", 1)[0]
            for folder in self.mpv_font_dirs:
                try:
                    folder.mkdir(parents=True, exist_ok=True)
                    part = folder / (filename + ".part")
                    part.write_bytes(made)
                    os.replace(part, folder / filename)
                    # A copy of before (another version of the face, or of this app) goes.
                    for old in folder.glob(stem + "-*.ttf"):
                        if old.name != filename:
                            try:
                                old.unlink()
                            except OSError:
                                pass
                except OSError as err:
                    log.warning("the copy of %s at %d could not be put into %s: %s", face.english, weight, folder, err)
            with self._work_lock:
                self._made.add(filename)
            log.info("made a plain copy of %s at weight %d for mpv (%d KB, %.1f s), which mpv uses from the next video it opens",
                     face.english, weight, len(made) // 1024, time.monotonic() - began)

    def _read_wanted(self) -> dict:
        try:
            found = json.loads(self.state_file.read_text(encoding="utf-8")) if self.state_file else {}
        except (OSError, ValueError):
            found = {}
        return found if isinstance(found, dict) else {}

    def _remember(self, face: Face, weight: int, family: str, filename: str) -> None:
        if self.state_file is None:
            return
        if not self._wanted:
            self._wanted = self._read_wanted()
        # One copy of a face at a weight: the one for the face's file as it is now.
        stem = filename.rsplit("-", 1)[0]
        for old in [name for name in self._wanted if name.rsplit("-", 1)[0] == stem and name != filename]:
            del self._wanted[old]
        self._wanted[filename] = {"path": face.path, "index": face.index, "weight": weight}
        try:
            self.state_file.parent.mkdir(parents=True, exist_ok=True)
            self.state_file.write_text(json.dumps(self._wanted, indent=1), encoding="utf-8")
        except OSError:
            pass

    def _make_remembered(self) -> None:
        """The copies asked for at an earlier start, made again where they are missing (or their face changed)."""
        if self.state_file is None or not self.mpv_font_dirs:
            return
        wanted = self._read_wanted()
        with self._work_lock:
            self._wanted = dict(wanted, **self._wanted)
        for entry in list(wanted.values()):
            try:
                path, index, weight = str(entry["path"]), int(entry["index"]), int(entry["weight"])
            except (KeyError, TypeError, ValueError):
                continue
            face = next((f for faces in self.families.values() for f in faces if f.path == path and f.index == index and f.variable), None)
            if face is not None:
                family, filename = self._copy_names(face, weight)
                self._want(face, weight, family, filename)


def finder_for(config) -> Finder:
    """The finder the app uses on Windows: with mpv's fonts folders (beside each scripts folder the script goes
    into), where plain copies of variable faces are put, and a file in the data folder remembering which."""
    dirs: list[Path] = []
    if getattr(config, "mpv_enabled", False):
        try:
            from .install import windows_script_folders

            dirs = [folder.parent / "fonts" for folder in windows_script_folders(config)]
        except Exception:
            log.exception("mpv's fonts folders could not be worked out")
    return Finder(mpv_font_dirs=dirs, state_file=Path(config.data_dir) / "mpv-fonts.json")
