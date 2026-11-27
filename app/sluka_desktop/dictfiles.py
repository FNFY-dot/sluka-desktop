# SPDX-License-Identifier: LicenseRef-Sluka
# Copyright (c) 2026 Sluka. Part of Sluka Desktop; see LICENSE.txt.
"""Dictionaries of your own in the kinds of file that Sluka's "Your own dictionaries" (Settings → Dictionary) does
not read itself, made on this computer into the kind it does -- a Yomitan dictionary (.zip) -- and handed to it as
if you had picked that (web/owndicts.js).  Sluka then reads it, asks what it asks, and keeps it as it keeps any
dictionary of yours.

    StarDict           the .ifo with its .idx and .dict (or .dict.dz), and the .syn if there is one
    ABBYY Lingvo DSL   .dsl or .dsl.dz
    JMdict             JMdict or JMdict_e, the XML or gzipped
    CC-CEDICT          cedict_ts.u8 and the like, plain or gzipped
    CC-Canto           cccanto-*.txt, or its zip
    Folkets lexikon    folkets_*.xml
    Wiktionary         kaikki.org's JSON lines (Wiktextract), plain or gzipped

Any of them may come in a zip, a tar (.tar, .tar.gz, .tgz, .tar.bz2, .tar.xz), or gzipped, bzip2- or xz-compressed.

The files are kept in a folder of their own under the app's data folder (dictionaries\\files\\) while they are read,
and read as data only: a name in an archive is not followed out of it, nothing in one is run, and a link in a
definition is kept only to the web.  The folder goes once Sluka has the dictionary, and whatever is left there goes
at the next start.
"""

from __future__ import annotations

import bz2
import gzip
import hashlib
import html.parser
import io
import json
import logging
import lzma
import os
import re
import secrets
import shutil
import struct
import tarfile
import threading
import time
import zipfile
from pathlib import Path

from . import dictionaries
from .host import Request, Response, error_response, json_response

log = logging.getLogger("sluka.dictfiles")

#: The most one file of a set may be, all of a set's files together, and all an archive may unpack to.
FILE_MOST = 4 * 1024 ** 3
SET_MOST = 6 * 1024 ** 3
#: The most files one set may have, and one archive may hold.
FILES_MOST = 24
MEMBERS_MOST = 400
#: Rows to a term bank, as Yomitan's own dictionaries have them.
BANK_ROWS = 10000
JOB = re.compile(r"[0-9a-f]{16}")
#: A set not taken is let go after this long.
LEFT_FOR = 6 * 3600

#: What each kind is called, for what the page says and the dictionary's description.
KINDS = {
    "stardict": "StarDict", "dsl": "ABBYY Lingvo (DSL)", "jmdict": "JMdict", "cedict": "CC-CEDICT", "cccanto": "CC-Canto",
    "folkets": "Folkets lexikon", "kaikki": "Wiktionary (kaikki.org)",
}
#: What a kind's makers ask to be credited with, where it is one of theirs.
CREDITS = {
    "jmdict": ("JMdict", "the Electronic Dictionary Research and Development Group (CC BY-SA 4.0)", "ja"),
    "cedict": ("CC-CEDICT", "MDBG and CC-CEDICT's contributors (CC BY-SA 4.0)", "zh"),
    "cccanto": ("CC-Canto", "Pleco Software (CC BY-SA 3.0)", "yue"),
    "folkets": ("Folkets lexikon", "Folkets lexikon, KTH Royal Institute of Technology (CC BY-SA 2.5)", "sv"),
    "kaikki": ("Wiktionary", "Wiktionary's contributors, extracted by kaikki.org (CC BY-SA 4.0 and GFDL)", ""),
}
#: A DSL file's #INDEX_LANGUAGE, as a language code, for the languages learners read most.
LANGUAGE_NAMES = {
    "english": "en", "russian": "ru", "german": "de", "french": "fr", "spanish": "es", "italian": "it", "portuguese": "pt",
    "japanese": "ja", "chinese": "zh", "korean": "ko", "polish": "pl", "ukrainian": "uk", "swedish": "sv", "dutch": "nl",
    "czech": "cs", "slovak": "sk", "turkish": "tr", "greek": "el", "finnish": "fi", "norwegian": "no", "danish": "da",
    "hungarian": "hu", "romanian": "ro", "bulgarian": "bg", "serbian": "sr", "croatian": "hr", "slovenian": "sl",
    "hebrew": "he", "arabic": "ar", "latin": "la", "estonian": "et", "latvian": "lv", "lithuanian": "lt", "belarusian": "be",
    "kazakh": "kk", "georgian": "ka", "armenian": "hy", "persian": "fa", "hindi": "hi", "vietnamese": "vi", "thai": "th",
    "indonesian": "id", "esperanto": "eo", "catalan": "ca", "icelandic": "is", "irish": "ga", "welsh": "cy",
}


class Unreadable(ValueError):
    """Not a kind of dictionary Sluka Desktop can make into one of Sluka's: said as a sentence for the page."""


# ---------------------------------------------------------------- unpacking, within bounds

def _safe_name(name: str) -> str:
    """A file's own name, to keep it under: the last part of whatever path it came with, in plain characters."""
    base = re.split(r"[\\/]", str(name or ""))[-1]
    base = re.sub(r"[^\w.\-()\[\] ]+", "_", base).strip(" .")
    return (base or "file")[:120]


def _free_name(folder: Path, name: str) -> Path:
    target = folder / name
    n = 2
    while target.exists():
        stem, dot, ext = name.partition(".")
        target = folder / f"{stem}-{n}{dot}{ext}"
        n += 1
    return target


class _Budget:
    """What may still be written in one set's folder."""

    def __init__(self, most: int | None = None):
        self.left = SET_MOST if most is None else most

    def take(self, n: int) -> None:
        self.left -= n
        if self.left < 0:
            raise Unreadable("This comes to more than Sluka Desktop reads at once (6 GB unpacked).")


def _copy(src, target: Path, budget: _Budget) -> Path:
    with open(target, "wb") as out:
        while True:
            piece = src.read(1024 * 1024)
            if not piece:
                break
            budget.take(len(piece))
            out.write(piece)
    return target


def _head(path: Path, n: int = 65536) -> bytes:
    try:
        with open(path, "rb") as f:
            return f.read(n)
    except OSError:
        return b""


COMPRESSED = (
    (b"\x1f\x8b", (".gz", ".dz", ".tgz"), gzip.open),
    (b"BZh", (".bz2", ".tbz", ".tbz2"), bz2.open),
    (b"\xfd7zXZ\x00", (".xz", ".txz"), lzma.open),
)


def _unpack_one(path: Path, folder: Path, budget: _Budget, depth: int) -> list:
    """The plain files in ``path``: itself, or what its archive or compression holds."""
    head = _head(path, 512)
    if depth < 3 and head.startswith(b"PK\x03\x04") and zipfile.is_zipfile(path):
        out = []
        with zipfile.ZipFile(path) as z:
            members = [i for i in z.infolist() if not i.is_dir()]
            if len(members) > MEMBERS_MOST:
                raise Unreadable("This zip holds too many files to be one dictionary.")
            for info in members:
                name = _safe_name(info.filename)
                if info.filename.startswith("__MACOSX/") or name.startswith("."):
                    continue
                with z.open(info) as src:
                    out += _unpack_one(_copy(src, _free_name(folder, name), budget), folder, budget, depth + 1)
        path.unlink()
        return out
    for magic, suffixes, opener in COMPRESSED:
        if depth < 3 and head.startswith(magic):
            low = path.name.lower()
            name = next((path.name[: -len(s)] for s in suffixes if low.endswith(s) and len(low) > len(s)), path.name + ".out")
            if low.endswith((".tgz", ".tbz", ".tbz2", ".txz")):
                name += ".tar"
            with opener(path, "rb") as src:
                try:
                    plain = _copy(src, _free_name(folder, _safe_name(name)), budget)
                except (OSError, EOFError, lzma.LZMAError) as err:
                    raise Unreadable(f"{path.name} could not be unpacked: {err}") from None
            path.unlink()
            return _unpack_one(plain, folder, budget, depth + 1)
    if depth < 3 and len(head) >= 262 and head[257:262] == b"ustar":
        out = []
        with tarfile.open(path, "r:") as tar:
            count = 0
            for member in tar:
                if not member.isreg():
                    continue
                count += 1
                if count > MEMBERS_MOST:
                    raise Unreadable("This archive holds too many files to be one dictionary.")
                name = _safe_name(member.name)
                if name.startswith("."):
                    continue
                src = tar.extractfile(member)
                if src is None:
                    continue
                with src:
                    out += _unpack_one(_copy(src, _free_name(folder, name), budget), folder, budget, depth + 1)
        path.unlink()
        return out
    return [path]


def unpack(files: list, folder: Path) -> list:
    """Every plain file of a set, its archives and compressed files opened, in ``folder``."""
    budget = _Budget()
    out = []
    for f in files:
        try:
            out += _unpack_one(f, folder, budget, 0)
        except (zipfile.BadZipFile, tarfile.TarError) as err:
            raise Unreadable(f"{f.name} could not be opened: {err}") from None
    return out


# ---------------------------------------------------------------- which kind it is

CEDICT_LINE = re.compile(r"^\S+ \S+ \[[^\]]*\](?: \{([^}]*)\})? /.*/\s*$")


def _text_of(head: bytes) -> str:
    """The start of a text file, in the encoding it says it is in (a byte order mark), else UTF-8, else UTF-16."""
    if head.startswith(b"\xff\xfe"):
        return head[2:].decode("utf-16-le", "replace")
    if head.startswith(b"\xfe\xff"):
        return head[2:].decode("utf-16-be", "replace")
    if head.startswith(b"\xef\xbb\xbf"):
        head = head[3:]
    if head[1:200:2].count(0) > 40:
        return head.decode("utf-16-le", "replace")
    return head.decode("utf-8", "replace")


def detect(files: list) -> tuple:
    """(kind, the file to read): the first of a set that is a dictionary Sluka Desktop knows."""
    files = sorted(files, key=lambda p: (-p.stat().st_size, p.name))
    ifos = sorted((f for f in files if f.name.lower().endswith(".ifo")), key=lambda p: p.name)
    if ifos:
        return "stardict", ifos[0]
    for f in files:
        text = _text_of(_head(f))
        start = text.lstrip()
        if re.match(r"#(NAME|INDEX_LANGUAGE|CONTENTS_LANGUAGE)\b", start):
            return "dsl", f
        if start.startswith("<"):
            if re.search(r"<!DOCTYPE\s+JMdict\b|<JMdict\b", text):
                return "jmdict", f
            if re.search(r"<dictionary\b", text) and re.search(r"<word\b", text):
                return "folkets", f
            continue
        lines = [ln for ln in text.splitlines()[:200] if ln.strip() and not ln.startswith("#")]
        if lines:
            m = CEDICT_LINE.match(lines[0])
            if m:
                return ("cccanto" if m.group(1) else "cedict"), f
            if lines[0].lstrip().startswith("{") and re.search(r'"word"\s*:', text) and re.search(r'"senses"\s*:', text):
                return "kaikki", f
    names = ", ".join(sorted(p.name for p in files)[:6])
    if any(p.name.lower().endswith((".idx", ".dict", ".syn")) for p in files):
        raise Unreadable("This is part of a StarDict dictionary, without its .ifo file: pick its .ifo, .idx and "
                         ".dict files together (or the archive they came in).")
    raise Unreadable(f"Sluka Desktop does not know this kind of dictionary ({names}). It reads StarDict, ABBYY Lingvo "
                     "(.dsl), JMdict, CC-CEDICT, CC-Canto, Folkets lexikon and kaikki.org's Wiktionary files; "
                     "Sluka itself reads Yomitan dictionaries and tables.")


# ---------------------------------------------------------------- markup as Yomitan's structured content

#: The tags that are blocks of their own, drawn as a div.
BLOCKS = {"p", "div", "blockquote", "section", "article", "header", "footer", "main", "aside", "dd", "dt", "dl",
          "center", "h1", "h2", "h3", "h4", "h5", "h6", "pre", "def", "address", "figure", "figcaption", "hr"}
#: The inline tags that mean a style.
STYLED = {
    "b": {"fontWeight": "bold"}, "strong": {"fontWeight": "bold"}, "k": {"fontWeight": "bold"},
    "i": {"fontStyle": "italic"}, "em": {"fontStyle": "italic"}, "cite": {"fontStyle": "italic"}, "var": {"fontStyle": "italic"},
    "dfn": {"fontStyle": "italic"}, "abr": {"fontStyle": "italic"}, "co": {"fontStyle": "italic"}, "gr": {"fontStyle": "italic"},
    "u": {"textDecorationLine": "underline"}, "ins": {"textDecorationLine": "underline"},
    "s": {"textDecorationLine": "line-through"}, "strike": {"textDecorationLine": "line-through"},
    "del": {"textDecorationLine": "line-through"},
    "sup": {"verticalAlign": "super", "fontSize": "0.8em"}, "sub": {"verticalAlign": "sub", "fontSize": "0.8em"},
    "small": {"fontSize": "0.85em"}, "big": {"fontSize": "1.15em"},
}
#: The tags Yomitan has, kept as they are.
KEPT = {"ul", "ol", "li", "table", "thead", "tbody", "tfoot", "tr", "td", "th", "ruby", "rt", "rp"}
#: What says nothing to read, left out with all that is in it.
DROPPED = {"script", "style", "head", "title", "audio", "video", "object", "embed", "iframe", "noscript", "template",
           "svg", "math", "button", "input", "select", "textarea", "form", "canvas", "map", "link", "meta"}
VOID = {"br", "img", "hr", "meta", "link", "input", "wbr", "area", "base", "col", "source", "track", "param"}
WEB = re.compile(r"^https?://[^\s\"'<>\\]+$", re.I)


def _tidy(node):
    """A tree made as small as it says the same in: one child for a list of one, no empty spans."""
    if isinstance(node, list):
        out = []
        for child in node:
            child = _tidy(child)
            if child in ("", None, []):
                continue
            if isinstance(child, str) and out and isinstance(out[-1], str):
                out[-1] += child
            elif isinstance(child, list):
                out.extend(child)
            else:
                out.append(child)
        return out[0] if len(out) == 1 and isinstance(out[0], str) else out
    if isinstance(node, dict):
        if node.get("tag") == "br":
            return node
        content = _tidy(node.get("content", []))
        if content in ("", None, []) and node.get("tag") not in ("td", "th", "li"):
            return None
        out = {k: v for k, v in node.items() if k != "content"}
        if content not in ("", None, []):
            out["content"] = content
        if out.get("tag") == "span" and len(out) == 2 and "content" in out:
            return out["content"]
        return out
    return node


def structured(content):
    """A definition: plain text as it is, anything with a shape as Yomitan's structured content."""
    content = _tidy(content)
    if content in ("", None, []):
        return None
    if isinstance(content, str):
        return content.strip() or None
    return {"type": "structured-content", "content": content}


def _lines(text: str) -> list:
    """Text whose lines are lines: each break a br."""
    out = []
    for i, line in enumerate(text.split("\n")):
        if i:
            out.append({"tag": "br"})
        if line:
            out.append(line)
    return out


class _Markup(html.parser.HTMLParser):
    """HTML, Pango's or XDXF's markup, as structured content: what Yomitan draws kept, the rest as its text."""

    def __init__(self, mode: str = "h"):
        super().__init__(convert_charrefs=True)
        self.mode = mode
        self.root: list = []
        self.stack: list = [("", self.root)]
        self.dropping = 0
        self.pre = 0

    def _open(self, tag: str, node) -> None:
        if node is None:
            self.stack.append((tag, self.stack[-1][1]))
            return
        self.stack[-1][1].append(node)
        node.setdefault("content", [])
        self.stack.append((tag, node["content"]))

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        if self.dropping or tag in DROPPED:
            if tag not in VOID:
                self.dropping += 1
            return
        a = {k.lower(): (v or "") for k, v in attrs}
        here = self.stack[-1][1]
        if tag == "br":
            here.append({"tag": "br"})
            return
        if tag == "img":
            said = (a.get("alt") or a.get("title") or "").strip()
            if said:
                here.append(f"[{said}]")
            return
        if tag == "hr" or tag in VOID:
            return
        if self.mode == "x" and tag == "tr":  # XDXF: a transcription
            node = {"tag": "span"}
            self._open(tag, node)
            node["content"].append("[")
            return
        if self.mode == "x" and tag == "blockquote":
            self._open(tag, {"tag": "div", "style": {"marginLeft": "1em"}})
            return
        if tag == "a":
            href = a.get("href", "").strip()
            self._open(tag, {"tag": "a", "href": href} if WEB.match(href) else {"tag": "span"})
            return
        if tag in BLOCKS:
            node = {"tag": "div"}
            if tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
                node["style"] = {"fontWeight": "bold"}
            if tag == "pre":
                self.pre += 1
            self._open(tag, node)
            return
        if tag in STYLED:
            self._open(tag, {"tag": "span", "style": dict(STYLED[tag])})
            return
        if tag == "span" and self.mode == "g":
            style = {}
            if a.get("weight", "").lower() in ("bold", "heavy", "ultrabold"):
                style["fontWeight"] = "bold"
            if a.get("style", "").lower() == "italic":
                style["fontStyle"] = "italic"
            if a.get("underline", "none").lower() != "none":
                style["textDecorationLine"] = "underline"
            self._open(tag, {"tag": "span", "style": style} if style else {"tag": "span"})
            return
        if tag in KEPT:
            node = {"tag": tag}
            if tag in ("td", "th"):
                for name, key in (("colspan", "colSpan"), ("rowspan", "rowSpan")):
                    if a.get(name, "").isdigit() and 1 < int(a[name]) <= 50:
                        node[key] = int(a[name])
            self._open(tag, node)
            return
        # Any other tag (span, font, XDXF's own): only its text.
        self._open(tag, None)

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag.lower() not in VOID:
            self.handle_endtag(tag)

    def handle_endtag(self, tag):
        tag = tag.lower()
        if self.dropping:
            if tag not in VOID:
                self.dropping -= 1
            return
        if tag in VOID:
            return
        for i in range(len(self.stack) - 1, 0, -1):
            if self.stack[i][0] == tag:
                if self.mode == "x" and tag == "tr":
                    self.stack[i][1].append("]")
                if tag == "pre":
                    self.pre = max(0, self.pre - 1)
                del self.stack[i:]
                return

    def handle_data(self, data):
        if self.dropping or not data:
            return
        here = self.stack[-1][1]
        if self.pre or self.mode in ("g", "x"):
            here.extend(_lines(data))
        else:
            here.append(re.sub(r"\s+", " ", data))


def markup(text: str, mode: str = "h"):
    """HTML (StarDict's h), Pango markup (g) or XDXF (x), as one definition."""
    parser = _Markup(mode)
    try:
        parser.feed(text)
        parser.close()
    except Exception:  # a definition too broken to read is its text
        return structured(re.sub(r"<[^>]*>", "", text))
    return structured(parser.root)


# ---------------------------------------------------------------- StarDict

def _companion(ifo: Path, ext: str):
    stem = ifo.name[:-4].lower()
    for f in ifo.parent.iterdir():
        if f.name.lower() == stem + ext:
            return f
    return None


def _fields(data: bytes, same: str) -> list:
    """An entry's parts, (type, bytes): as its .ifo's sametypesequence says, or each marked with its type."""
    out = []
    pos = 0
    types = iter(same) if same else None
    while pos < len(data):
        if types is not None:
            t = next(types, None)
            if t is None:
                break
            last = len(out) == len(same) - 1
        else:
            t = chr(data[pos])
            pos += 1
            last = False
        if t.isupper():
            if last:
                out.append((t, data[pos:]))
                break
            if pos + 4 > len(data):
                break
            n = struct.unpack_from(">I", data, pos)[0]
            out.append((t, data[pos + 4: pos + 4 + n]))
            pos += 4 + n
        else:
            end = len(data) if last else data.find(b"\0", pos)
            end = len(data) if end < 0 else end
            out.append((t, data[pos:end]))
            pos = end + 1
    return out


def _stardict_info(ifo: Path) -> dict:
    info = {}
    with open(ifo, "r", encoding="utf-8-sig", errors="replace") as f:
        first = f.readline().strip()
        if "StarDict" not in first:
            raise Unreadable(f"{ifo.name} is not a StarDict .ifo file.")
        for line in f:
            key, eq, value = line.partition("=")
            if eq:
                info[key.strip()] = value.strip()
    return info


def read_stardict(ifo: Path):
    """(word, reading, definitions, synonyms) for each entry."""
    info = _stardict_info(ifo)
    idx, dic = _companion(ifo, ".idx"), _companion(ifo, ".dict")
    if not idx or not dic:
        raise Unreadable(f"{ifo.name} came without its .idx and .dict files: pick all of the dictionary's files "
                         "together (or the archive they came in).")
    syn = _companion(ifo, ".syn")
    wide = info.get("idxoffsetbits") == "64"
    step, fmt = (12, ">QI") if wide else (8, ">II")
    same = info.get("sametypesequence", "")
    data = idx.read_bytes()
    entries = []
    pos = 0
    while pos < len(data):
        end = data.find(b"\0", pos)
        if end < 0 or end + 1 + step > len(data):
            break
        off, size = struct.unpack_from(fmt, data, end + 1)
        entries.append((data[pos:end].decode("utf-8", "replace"), off, size))
        pos = end + 1 + step
    del data
    synonyms: dict = {}
    if syn:
        data = syn.read_bytes()
        pos = 0
        while pos < len(data):
            end = data.find(b"\0", pos)
            if end < 0 or end + 5 > len(data):
                break
            (at,) = struct.unpack_from(">I", data, end + 1)
            synonyms.setdefault(at, []).append(data[pos:end].decode("utf-8", "replace"))
            pos = end + 5
        del data
    with open(dic, "rb") as f:
        for n, (word, off, size) in enumerate(entries):
            if size <= 0 or size > 16 * 1024 * 1024:
                continue
            f.seek(off)
            reading, defs = "", []
            for t, raw in _fields(f.read(size), same):
                text = raw.decode("utf-8", "replace").strip("\0")
                if t in "ty":
                    reading = reading or text.strip()
                elif t in "mlnw":
                    d = structured(_lines(text.strip()))
                    if d:
                        defs.append(d)
                elif t in "hgx":
                    d = markup(text, t)
                    if d:
                        defs.append(d)
                elif t == "k":  # KingSoft PowerWord's XML: its text
                    d = markup(text, "x")
                    if d:
                        defs.append(d)
            if word.strip() and defs:
                yield word.strip(), reading, defs, synonyms.get(n, [])


# ---------------------------------------------------------------- ABBYY Lingvo DSL

DSL_STRESS = "\u0301"  # (a combining acute: the stress mark over the letter before it)


def _dsl_encoding(path: Path) -> str:
    head = _head(path, 4096)
    if head.startswith(b"\xff\xfe"):
        return "utf-16"
    if head.startswith(b"\xfe\xff"):
        return "utf-16"
    if head.startswith(b"\xef\xbb\xbf"):
        return "utf-8-sig"
    if head[1:200:2].count(0) > 40:
        return "utf-16-le"
    try:
        head.decode("utf-8")
        return "utf-8"
    except UnicodeDecodeError as err:
        # (a character cut at the end of the sample is still UTF-8)
        return "utf-8" if err.start > len(head) - 4 else "cp1251"


def _dsl_unescape(text: str) -> str:
    return re.sub(r"\\(.)", r"\1", text)


def _dsl_heads(line: str) -> tuple:
    """A headword line: (as shown, the keys it is found under)."""
    line = re.sub(r"\{\{.*?\}\}", "", line)  # a comment
    shown = re.sub(r"(?<!\\)[{}]", "", line)
    key = re.sub(r"(?<!\\)\{.*?(?<!\\)\}", "", line)
    keys = [key]
    # An optional part, (u) in colo(u)r: the word with it, then without it.
    if re.search(r"(?<!\\)\(", key):
        keys = [re.sub(r"(?<!\\)\((.*?)(?<!\\)\)", r"\1", key), re.sub(r"(?<!\\)\(.*?(?<!\\)\)", "", key)]
    clean = [re.sub(r"\s+", " ", _dsl_unescape(k)).strip() for k in keys]
    return re.sub(r"\s+", " ", _dsl_unescape(shown)).strip(), [k for k in dict.fromkeys(clean) if k]


DSL_TAG = re.compile(r"\[(/?)([a-z!*']+\d?)((?:\s[^\]]*)?)\]", re.I)


def _dsl_line(text: str, head: str) -> list:
    """One line of a card as structured content: its tags, what Yomitan draws of them, the rest as text."""
    text = re.sub(r"\{\{.*?\}\}", "", text)
    text = re.sub(r"(?<!\\)~", lambda _m: head, text)
    root: list = []
    stack = [("", root, None)]
    pos = 0
    skip = 0

    def add(s: str) -> None:
        if s and not skip:
            stack[-1][1].append(_dsl_unescape(s))

    for m in DSL_TAG.finditer(text):
        if m.start() and text[m.start() - 1] == "\\":
            continue
        add(text[pos:m.start()])
        pos = m.end()
        closing, name, _rest = m.group(1) == "/", m.group(2).lower(), m.group(3)
        if re.fullmatch(r"m\d?", name):
            continue  # a line's indent: the line is a block of its own already
        if name == "s":  # a sound or picture file: not here
            skip = skip - 1 if closing and skip else skip + (0 if closing else 1)
            continue
        if closing:
            for i in range(len(stack) - 1, 0, -1):
                if stack[i][0] == name:
                    if name == "'":
                        stack[i][1].append(DSL_STRESS)
                    node = stack[i][2]
                    said = "".join(c for c in node["content"] if isinstance(c, str)).strip() if node else ""
                    # A link's text is its address: kept as a link where it is one to the web.
                    if name == "url" and WEB.match(said):
                        node.update(tag="a", href=said)
                    del stack[i:]
                    break
            continue
        if name == "br":
            stack[-1][1].append({"tag": "br"})
            continue
        style = {"b": {"fontWeight": "bold"}, "i": {"fontStyle": "italic"}, "u": {"textDecorationLine": "underline"},
                 "sup": {"verticalAlign": "super", "fontSize": "0.8em"}, "sub": {"verticalAlign": "sub", "fontSize": "0.8em"},
                 "p": {"fontStyle": "italic"}, "com": {"fontStyle": "italic"}}.get(name)
        node = {"tag": "span", "content": []}
        if style:
            node["style"] = dict(style)
        stack[-1][1].append(node)
        stack.append((name, node["content"], node))
    add(text[pos:])
    # (the line's own ends: no space left where a sound file was)
    if root and isinstance(root[0], str):
        root[0] = root[0].lstrip()
    if root and isinstance(root[-1], str):
        root[-1] = root[-1].rstrip()
    return root


def _dsl_card(heads: list, body: list):
    # The word a card's ~ stands for: its first headword as it is found.
    shown = heads[0][1][0] if heads[0][1] else heads[0][0]
    blocks = []
    for raw in body:
        indent = 0
        m = re.match(r"\s*\[m(\d)\]", raw)
        if m:
            indent = int(m.group(1))
        line = raw.strip()
        if line.startswith("@"):
            line = line[1:].strip()
            if not line:
                continue
            blocks.append({"tag": "div", "style": {"fontWeight": "bold", "marginTop": "0.3em"}, "content": _dsl_line(line, shown)})
            continue
        content = _dsl_line(line, shown)
        node = {"tag": "div", "content": content}
        if indent > 1:
            node["style"] = {"marginLeft": f"{min(indent - 1, 6) * 0.8:g}em"}
        blocks.append(node)
    return structured(blocks)


def read_dsl(path: Path):
    """(meta, entries): the file's #NAME and #INDEX_LANGUAGE, and (shown, keys, definition) for each card."""
    meta = {}
    enc = _dsl_encoding(path)

    def cards():
        heads, body = [], []
        started = False
        with open(path, "r", encoding=enc, errors="replace", newline=None) as f:
            for raw in f:
                raw = raw.rstrip("\r\n").lstrip("\ufeff")
                if not raw.strip():
                    if body and heads:
                        yield heads, body
                        heads, body = [], []
                    continue
                if raw.startswith("#") and not started:
                    m = re.match(r'#(\w+)\s+"?(.*?)"?\s*$', raw)
                    if m:
                        meta[m.group(1).upper()] = m.group(2)
                    continue
                if raw[0] in " \t":
                    if heads:
                        body.append(raw)
                    continue
                if body:
                    yield heads, body
                    heads, body = [], []
                started = True
                heads.append(_dsl_heads(raw))
        if heads and body:
            yield heads, body

    def entries():
        for heads, body in cards():
            heads = [h for h in heads if h[1]]
            if not heads:
                continue
            d = _dsl_card(heads, body)
            if d:
                yield heads, d

    return meta, entries()


# ---------------------------------------------------------------- the dictionaries the app also downloads

def _sense(sense: dict, split: bool, said_pos: str = "") -> list:
    """A sense's definitions: its glosses, and its part of speech where the sense before had another."""
    glosses = [g for g in sense.get("glosses") or () if isinstance(g, str) and g.strip()]
    if not glosses:
        return []
    pos, notes = str(sense.get("pos") or "").strip(), str(sense.get("notes") or "").strip()
    if pos == said_pos:
        pos = ""
    if split and not pos and not notes:
        return glosses
    content = []
    if pos:
        content += [{"tag": "span", "style": {"fontStyle": "italic"}, "content": pos}, " "]
    content.append("; ".join(glosses))
    if notes:
        content += [" ", {"tag": "span", "style": {"fontSize": "0.85em"}, "content": f"({notes})"}]
    return [structured(content)]


def entry_rows(kind: str, path: Path):
    """The Yomitan rows of a dictionary the app also downloads (dictionaries.py READERS), one or more an entry."""
    reader = dictionaries.READERS[kind]
    split = kind in ("cedict", "cccanto")
    for seq, (entry, words) in enumerate(reader(path), 1):
        glossary, said = [], ""
        for s in entry.get("senses") or ():
            glossary += [d for d in _sense(s, split, said) if d]
            said = str(s.get("pos") or "").strip() or said
        if not glossary:
            continue
        head = entry["head"]
        readings = [r for r in str(entry.get("reading") or "").split("、") if r]
        forms = set(entry.get("forms") or ())
        for word in dict.fromkeys(words):
            if word in forms and word != head:
                yield [word, "", "", "", 0, [[head, ["form"]]], seq, ""]
            else:
                reading = "" if word in readings else (readings[0] if readings else "")
                yield [word, reading, "", "", 0, glossary, seq, ""]


# ---------------------------------------------------------------- the Yomitan dictionary made

def rows_of(kind: str, path: Path, meta: dict):
    """The rows of ``path``, and what is said of it in ``meta`` (title, sourceLanguage, attribution, ...)."""
    if kind == "stardict":
        info = _stardict_info(path)
        meta["title"] = info.get("bookname") or path.stem
        if info.get("author"):
            meta["author"] = info["author"][:300]
        if info.get("description"):
            meta["description"] = re.sub(r"<[^>]*>", " ", info["description"])[:1000]
        if info.get("website") and WEB.match(info["website"]):
            meta["url"] = info["website"]
        return _stardict_rows(path)
    if kind == "dsl":
        about, entries = read_dsl(path)

        def rows():
            for seq, (heads, d) in enumerate(entries, 1):
                for shown, keys in heads:
                    for key in keys:
                        yield [key, "", "", "", 0, [d], seq, ""]
            meta["title"] = about.get("NAME") or meta.get("title") or path.stem
            lang = LANGUAGE_NAMES.get(str(about.get("INDEX_LANGUAGE") or "").strip().lower())
            if lang:
                meta["sourceLanguage"] = lang
            target = LANGUAGE_NAMES.get(str(about.get("CONTENTS_LANGUAGE") or "").strip().lower())
            if target:
                meta["targetLanguage"] = target

        return rows()
    title, credit, lang = CREDITS[kind]
    meta["title"] = title
    meta["attribution"] = credit
    if lang:
        meta["sourceLanguage"] = lang
    elif kind == "kaikki":
        first = _first_json(path)
        if first.get("lang"):
            meta["title"] = f"Wiktionary: {str(first['lang'])[:60]}"
        if re.fullmatch(r"[a-z]{2,3}", str(first.get("lang_code") or "")):
            meta["sourceLanguage"] = first["lang_code"]
    return entry_rows(kind, path)


def _first_json(path: Path) -> dict:
    try:
        with dictionaries._open_text(path) as f:
            for line in f:
                if line.strip():
                    item = json.loads(line)
                    return item if isinstance(item, dict) else {}
    except (OSError, ValueError):
        pass
    return {}


def _stardict_rows(ifo: Path):
    for seq, (word, reading, defs, synonyms) in enumerate(read_stardict(ifo), 1):
        yield [word, reading if reading != word else "", "", "", 0, defs, seq, ""]
        for other in dict.fromkeys(synonyms):
            if other and other != word:
                yield [other, "", "", "", 0, [[word, ["synonym"]]], seq, ""]


def write_yomitan(rows, target: Path, meta: dict, progress=None) -> int:
    """A Yomitan dictionary (format 3) of ``rows``, at ``target``: its rows a bank at a time."""
    temp = target.with_name(target.name + ".part")
    n = banks = 0
    with zipfile.ZipFile(temp, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        bank = []
        for row in rows:
            if not isinstance(row[0], str) or not row[0].strip() or len(row[0]) > 200:
                continue
            bank.append(row)
            n += 1
            if len(bank) >= BANK_ROWS:
                banks += 1
                z.writestr(f"term_bank_{banks}.json", json.dumps(bank, ensure_ascii=False, separators=(",", ":")))
                bank = []
                if progress:
                    progress(n)
        if bank:
            banks += 1
            z.writestr(f"term_bank_{banks}.json", json.dumps(bank, ensure_ascii=False, separators=(",", ":")))
        index = {"title": str(meta.get("title") or target.stem)[:200], "revision": meta.get("revision") or "1", "format": 3,
                 "sequenced": False}
        for key in ("author", "attribution", "description", "url", "sourceLanguage", "targetLanguage"):
            if meta.get(key):
                index[key] = meta[key]
        z.writestr("index.json", json.dumps(index, ensure_ascii=False, indent=1))
    if not n:
        temp.unlink()
        raise Unreadable("No entries could be read from this dictionary.")
    os.replace(temp, target)
    return n


def convert(files: list, folder: Path, revision: str, progress=None) -> dict:
    """A set of files made into a Yomitan dictionary in ``folder``: what it is, and where."""
    plain = unpack(files, folder)
    kind, path = detect(plain)
    meta = {"revision": revision, "title": path.stem, "description": f"Made by Sluka Desktop from {path.name} ({KINDS[kind]})."}
    rows = rows_of(kind, path, meta)
    target = folder / "made.zip"
    if progress:
        progress(0, kind)
    n = write_yomitan(rows, target, meta, (lambda count: progress(count, kind)) if progress else None)
    return {"kind": kind, "name": KINDS[kind], "title": meta.get("title") or path.stem, "entries": n, "path": target,
            "from": path.name}


# ---------------------------------------------------------------- the app's side

class Files:
    """Your files on their way to being dictionaries of Sluka's: each set in a folder of its own, until it is taken."""

    def __init__(self, folder):
        self.folder = Path(folder)
        self._lock = threading.Lock()
        self._jobs: dict = {}
        # Whatever a last run left, gone.
        shutil.rmtree(self.folder, ignore_errors=True)

    def _sweep(self) -> None:
        now = time.time()
        with self._lock:
            old = [j for j, job in self._jobs.items() if now - job["at"] > LEFT_FOR and job.get("state") != "reading"]
            for j in old:
                self._jobs.pop(j, None)
        for j in old:
            shutil.rmtree(self.folder / j, ignore_errors=True)

    def take(self, job: str, name: str, req: Request) -> dict:
        """One file of a set, its bytes the request's own."""
        self._sweep()
        with self._lock:
            if job:
                record = self._jobs.get(job)
                if not record or record.get("state") != "taking":
                    return {"ok": False, "error": "no such set of files"}
            else:
                job = secrets.token_hex(8)
                record = self._jobs[job] = {"state": "taking", "files": [], "size": 0, "at": time.time(), "hashes": []}
            if len(record["files"]) >= FILES_MOST:
                return {"ok": False, "error": "too many files for one dictionary"}
        folder = self.folder / job / "in"
        folder.mkdir(parents=True, exist_ok=True)
        target = _free_name(folder, _safe_name(name))
        digest = hashlib.sha256()
        size = 0
        try:
            with open(target, "wb") as out:
                pieces = iter(lambda: req.body_reader(1024 * 1024), b"") if req.body_reader else iter((req.body or b"",))
                for piece in pieces:
                    size += len(piece)
                    if size > FILE_MOST or record["size"] + size > SET_MOST:
                        raise Unreadable("This file is larger than Sluka Desktop reads (4 GB a file, 6 GB in all).")
                    digest.update(piece)
                    out.write(piece)
        except (OSError, Unreadable) as err:
            try:
                target.unlink()
            except OSError:
                pass
            return {"ok": False, "job": job, "error": str(err)}
        with self._lock:
            record["files"].append(target)
            record["size"] += size
            record["hashes"].append(digest.hexdigest())
            record["at"] = time.time()
        return {"ok": True, "job": job, "size": size}

    def start(self, job: str) -> dict:
        with self._lock:
            record = self._jobs.get(job)
            if not record or not record["files"]:
                return {"ok": False, "error": "no such set of files"}
            if record["state"] != "taking":
                return {"ok": True, "started": False}
            record.update(state="reading", entries=0, at=time.time())
        threading.Thread(target=self._convert, args=(job,), name=f"sluka-dictfile-{job}", daemon=True).start()
        return {"ok": True, "started": True}

    def _convert(self, job: str) -> None:
        with self._lock:
            record = self._jobs[job]
            files = list(record["files"])
            revision = "sluka-" + hashlib.sha256("".join(sorted(record["hashes"])).encode()).hexdigest()[:16]

        def progress(n, kind):
            with self._lock:
                record.update(entries=n, kind=kind, name=KINDS.get(kind, kind), at=time.time())

        work = self.folder / job / "work"
        try:
            work.mkdir(parents=True, exist_ok=True)
            moved = []
            for f in files:
                moved.append(f.rename(_free_name(work, f.name)))
            made = convert(moved, work, revision, progress)
            with self._lock:
                record.update(state="ready", entries=made["entries"], kind=made["kind"], name=made["name"],
                              title=made["title"], made=made["path"], source=made["from"], at=time.time())
            log.info("a dictionary of yours (%s) was made from %s: %d entries", made["name"], made["from"], made["entries"])
        except Unreadable as err:
            with self._lock:
                record.update(state="failed", error=str(err), at=time.time())
        except Exception as err:  # a file this broken is said to be so, not the app's to fall over
            log.warning("a dictionary of yours could not be read: %s", err, exc_info=True)
            with self._lock:
                record.update(state="failed", error=f"It could not be read: {err}", at=time.time())
        finally:
            for f in work.glob("*"):
                if f.name != "made.zip":
                    try:
                        f.unlink()
                    except OSError:
                        pass

    def state(self, job: str) -> dict:
        with self._lock:
            record = self._jobs.get(job)
            if not record:
                return {"ok": False, "error": "no such set of files"}
            out = {k: record[k] for k in ("state", "entries", "kind", "name", "title", "error", "source") if k in record}
        return {"ok": True, **out}

    def made(self, job: str):
        with self._lock:
            record = self._jobs.get(job)
            path = record.get("made") if record and record.get("state") == "ready" else None
        if not path or not Path(path).is_file():
            return None
        return Path(path)

    def forget(self, job: str) -> dict:
        with self._lock:
            record = self._jobs.pop(job, None)
        if record and record.get("state") == "reading":
            with self._lock:  # (still being read: let go once it is done)
                self._jobs[job] = record
                record["at"] = 0
            return {"ok": True}
        shutil.rmtree(self.folder / job, ignore_errors=True)
        return {"ok": True}

    def api(self, name: str, req: Request, respond) -> bool:
        """The calls of web/owndicts.js; False for a name that is none of them."""
        if name == "file":
            if req.method != "POST":
                respond(error_response(405, "POST"))
                return True
            job = str(req.query.get("job") or "")
            if job and not JOB.fullmatch(job):
                respond(error_response(400, "no such set of files"))
                return True
            got = self.take(job, str(req.query.get("name") or "file"), req)
            respond(json_response(got, 200 if got.get("ok") else 400))
            return True
        if name == "made":
            job = str(req.query.get("job") or "")
            path = self.made(job) if JOB.fullmatch(job) else None
            if not path:
                respond(error_response(404, "not made"))
                return True
            respond(Response(content_type="application/zip", file=(str(path), 0, path.stat().st_size),
                             headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"}))
            return True
        if name not in ("convert", "converting", "forget"):
            return False
        if req.method != "POST":
            respond(error_response(405, "POST"))
            return True
        try:
            args = json.loads((req.body or b"{}").decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            args = None
        job = str(args.get("job") or "") if isinstance(args, dict) else ""
        if not JOB.fullmatch(job):
            respond(error_response(400, "no such set of files"))
            return True
        respond(json_response({"convert": self.start, "converting": self.state, "forget": self.forget}[name](job)))
        return True
