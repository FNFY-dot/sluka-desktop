# SPDX-License-Identifier: LicenseRef-Sluka
# Copyright (c) 2026 Sluka. Part of Sluka Desktop; see LICENSE.txt.
"""The dictionaries of the word panel's Look up key, on this computer: those whose makers publish them for anyone to
download and use (under Creative Commons Attribution-ShareAlike licences), installed on a click and read offline in
a small window of Sluka's own (web/dict.html), beside the menu's sites, which open online in another.

    Wiktionary       every language: Wiktionary's own entries, as kaikki.org extracts them (Wiktextract)
    JMdict           Japanese: Jisho's dictionary, the Electronic Dictionary Research and Development Group's
    CC-CEDICT        Chinese: MDBG's dictionary
    CC-Canto         Cantonese: Pleco Software's
    Folkets lexikon  Swedish: KTH's people's dictionary

Each is downloaded from its makers' own site, only when you install it, and kept in the app's data folder
(dictionaries\\), one SQLite file each, made from it: its entries, and the words each is found under.  Nothing else
of yours is sent, and a word looked up offline goes nowhere.  Each window of one says whose it is and under which
licence, as its licence asks.

What a site keeps to itself (Weblio, Naver, Larousse, Duden, ...) cannot be downloaded: those stay online.
"""

from __future__ import annotations

import functools
import gzip
import http.client
import io
import json
import logging
import os
import re
import socket
import sqlite3
import threading
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

from .host import Request, error_response, json_response

log = logging.getLogger("sluka.dictionaries")

#: The dictionaries there are, by the Look up menu's site they stand for (lib/dict-links.js).
CATALOG = {
    "wiktionary": {"name": "Wiktionary", "site": "wiktionary", "langs": "*", "format": "kaikki",
                   "page": "https://kaikki.org/dictionary/{name}/index.html",
                   "by": "Wiktionary's contributors; extracted by kaikki.org (Wiktextract)",
                   "licence": "CC BY-SA 4.0 and GFDL", "home": "https://kaikki.org/dictionary/"},
    "jmdict": {"name": "JMdict", "site": "jisho", "langs": ["ja"], "format": "jmdict",
               "url": "http://ftp.edrdg.org/pub/Nihongo/JMdict_e.gz",
               "by": "the Electronic Dictionary Research and Development Group",
               "licence": "CC BY-SA 4.0", "home": "https://www.edrdg.org/edrdg/licence.html"},
    "cedict": {"name": "CC-CEDICT", "site": "mdbg", "langs": ["zh"], "format": "cedict",
               "url": "https://www.mdbg.net/chinese/export/cedict/cedict_1_0_ts_utf-8_mdbg.txt.gz",
               "by": "MDBG and CC-CEDICT's contributors", "licence": "CC BY-SA 4.0",
               "home": "https://www.mdbg.net/chinese/dictionary?page=cc-cedict"},
    "cccanto": {"name": "CC-Canto", "site": "cccanto", "langs": ["yue"], "format": "cccanto",
                "url": "https://cantonese.org/cccanto-170202.zip",
                "by": "Pleco Software", "licence": "CC BY-SA 3.0", "home": "https://cantonese.org/"},
    "folkets": {"name": "Folkets lexikon", "site": "folkets", "langs": ["sv"], "format": "folkets",
                "url": "https://folkets-lexikon.csc.kth.se/folkets/folkets_sv_en_public.xml",
                "by": "Folkets lexikon (KTH Royal Institute of Technology)", "licence": "CC BY-SA 2.5",
                "home": "https://folkets-lexikon.csc.kth.se/folkets/"},
}
#: The Look up menu's sites that have an offline dictionary: site id -> dictionary id.
BY_SITE = {d["site"]: key for key, d in CATALOG.items()}
USER_AGENT = "Sluka-Desktop (dictionary download; +https://sluka.app)"
BODY_MOST = 16 * 1024
LOOKUP_MOST = 12
QUERY_MOST = 200
NAME = re.compile(r"[A-Za-z][A-Za-z \-'()À-ɏ]{1,60}")
LANG = re.compile(r"[a-z]{2,3}(?:-[A-Za-z]{2,4})?")


def offers(dict_id: str, lang: str) -> bool:
    entry = CATALOG.get(dict_id)
    return bool(entry) and (entry["langs"] == "*" or lang in entry["langs"])


# ---------------------------------------------------------------- reading each one's file

TONES = {"a": "āáǎà", "e": "ēéěè", "i": "īíǐì", "o": "ōóǒò", "u": "ūúǔù", "ü": "ǖǘǚǜ"}


def pinyin_marks(text: str) -> str:
    """``zhong1 guo2`` as ``zhōng guó`` (CC-CEDICT's readings, numbered)."""
    def one(syl: str) -> str:
        m = re.fullmatch(r"([A-Za-züÜv:]+)([1-5])", syl)
        if not m:
            return syl
        body, tone = m.group(1).replace("u:", "ü").replace("v", "ü").replace("U:", "Ü"), int(m.group(2))
        if tone == 5:
            return body
        low = body.lower()
        at = low.find("a") if "a" in low else low.find("e") if "e" in low else low.find("ou") if "ou" in low else -1
        if at < 0:
            vowels = [i for i, c in enumerate(low) if c in TONES]
            at = vowels[-1] if vowels else -1
        if at < 0:
            return body
        mark = TONES[low[at]][tone - 1]
        mark = mark.upper() if body[at].isupper() else mark
        return body[:at] + mark + body[at + 1:]

    return " ".join(one(s) for s in text.split())


def _cedict_lines(lines, canto: bool = False):
    pattern = re.compile(r"^(\S+) (\S+) \[([^\]]*)\](?: \{([^}]*)\})? /(.*)/\s*$")
    for line in lines:
        if not line or line.startswith("#"):
            continue
        m = pattern.match(line.rstrip("\r\n"))
        if not m:
            continue
        trad, simp, pinyin, jyut, glosses = m.groups()
        reading = jyut if canto and jyut else pinyin_marks(pinyin)
        entry = {"head": simp if not canto else trad, "also": [w for w in dict.fromkeys((trad, simp)) if w != (trad if canto else simp)],
                 "reading": reading, "senses": [{"glosses": [g for g in glosses.split("/") if g]}]}
        yield entry, list(dict.fromkeys((trad, simp)))


def _open_bin(path: Path):
    """A file's bytes, gunzipped where it is gzipped: the makers' downloads are, a copy of your own may not be
    (dictfiles.py)."""
    with open(path, "rb") as f:
        gzipped = f.read(2) == b"\x1f\x8b"
    return gzip.open(path, "rb") if gzipped else open(path, "rb")


def _open_text(path: Path):
    return io.TextIOWrapper(_open_bin(path), encoding="utf-8-sig", errors="replace")


def read_cedict(path: Path):
    with _open_text(path) as f:
        yield from _cedict_lines(f)


def read_cccanto(path: Path):
    if not zipfile.is_zipfile(path):  # (its text file, out of the zip it comes in)
        with _open_text(path) as f:
            yield from _cedict_lines(f, canto=True)
        return
    with zipfile.ZipFile(path) as z:
        names = [n for n in z.namelist() if n.endswith(".txt") and "readings" not in n] or z.namelist()
        with z.open(names[0]) as raw:
            yield from _cedict_lines(io.TextIOWrapper(raw, encoding="utf-8", errors="replace"), canto=True)


def read_jmdict(path: Path):
    """JMdict's XML (JMdict_e): its entities -- the parts of speech -- as their names say them."""
    with _open_bin(path) as f:
        pos: list = []
        for _event, el in ET.iterparse(f, events=("end",)):
            if el.tag != "entry":
                continue
            kebs = [k.text for k in el.iterfind("k_ele/keb") if k.text]
            rebs = [r.text for r in el.iterfind("r_ele/reb") if r.text]
            senses = []
            pos = []
            for sense in el.iterfind("sense"):
                said = [p.text for p in sense.iterfind("pos") if p.text]
                pos = said or pos  # (a sense says its part of speech only where it changes)
                glosses = [g.text for g in sense.iterfind("gloss") if g.text]
                notes = [n.text for n in sense.iterfind("misc") if n.text] + [n.text for n in sense.iterfind("s_inf") if n.text]
                if glosses:
                    senses.append({"pos": "; ".join(pos), "glosses": glosses, **({"notes": "; ".join(notes)} if notes else {})})
            el.clear()
            if not senses or not (kebs or rebs):
                continue
            head = kebs[0] if kebs else rebs[0]
            yield ({"head": head, "also": [w for w in kebs[1:]], "reading": "、".join(rebs) if kebs else "", "senses": senses},
                   list(dict.fromkeys(kebs + rebs)))


FOLKETS_CLASS = {"nn": "noun", "vb": "verb", "jj": "adjective", "ab": "adverb", "pp": "preposition", "pn": "pronoun",
                 "kn": "conjunction", "in": "interjection", "rg": "numeral", "pm": "proper noun", "abbrev": "abbreviation"}


def read_folkets(path: Path):
    with _open_bin(path) as f:
        for _event, el in ET.iterparse(f, events=("end",)):
            if el.tag != "word":
                continue
            word = el.get("value") or ""
            kind = el.get("class") or ""
            glosses = [t.get("value") for t in el.iterfind("translation") if t.get("value")]
            forms = [i.get("value") for i in el.iterfind("paradigm/inflection") if i.get("value")]
            forms += [i.get("value") for i in el.iterfind("inflection") if i.get("value")]
            el.clear()
            if word and glosses:
                yield ({"head": word, "reading": "", "senses": [{"pos": FOLKETS_CLASS.get(kind, kind),
                                                               "glosses": glosses}], **({"forms": forms[:12]} if forms else {})},
                       list(dict.fromkeys([word] + forms)))


def read_kaikki(path: Path):
    with _open_text(path) as f:
        for line in f:
            try:
                item = json.loads(line)
            except ValueError:
                continue
            word = item.get("word") or ""
            senses = []
            for sense in item.get("senses") or ():
                glosses = [g for g in sense.get("glosses") or () if isinstance(g, str)]
                if glosses:
                    tags = [t for t in sense.get("tags") or () if isinstance(t, str)]
                    senses.append({"glosses": glosses[-1:] if len(glosses) > 1 else glosses, **({"notes": ", ".join(tags[:6])} if tags else {})})
            if not word or not senses:
                continue
            ipa = next((s.get("ipa") for s in item.get("sounds") or () if isinstance(s, dict) and s.get("ipa")), "")
            yield {"head": word, "reading": ipa, "senses": [{**s, "pos": item.get("pos") or ""} for s in senses[:12]]}, [word]


READERS = {"cedict": read_cedict, "cccanto": read_cccanto, "jmdict": read_jmdict, "folkets": read_folkets, "kaikki": read_kaikki}


def build(reader, source: Path, target: Path, progress=None) -> int:
    """The SQLite file of a dictionary from its own file: its entries, and the words each is found under."""
    temp = target.with_suffix(".building")
    if temp.exists():
        temp.unlink()
    db = sqlite3.connect(str(temp))
    try:
        db.executescript("PRAGMA journal_mode=OFF; PRAGMA synchronous=OFF;"
                         "CREATE TABLE entries (id INTEGER PRIMARY KEY, data TEXT NOT NULL);"
                         "CREATE TABLE keys (key TEXT NOT NULL, id INTEGER NOT NULL);")
        n = 0
        entries, keys = [], []
        for entry, words in reader(source):
            n += 1
            entries.append((n, json.dumps(entry, ensure_ascii=False, separators=(",", ":"))))
            for w in words:
                keys.append((w, n))
                low = w.lower()
                if low != w:
                    keys.append((low, n))
            if len(entries) >= 5000:
                db.executemany("INSERT INTO entries VALUES (?, ?)", entries)
                db.executemany("INSERT INTO keys VALUES (?, ?)", keys)
                entries, keys = [], []
                if progress:
                    progress(n)
        db.executemany("INSERT INTO entries VALUES (?, ?)", entries)
        db.executemany("INSERT INTO keys VALUES (?, ?)", keys)
        db.execute("CREATE INDEX keys_key ON keys (key)")
        db.commit()
    finally:
        db.close()
    os.replace(temp, target)
    return n


def lookup(path: Path, words, most: int = LOOKUP_MOST) -> list:
    """The entries found under any of ``words``, the first word's first."""
    out, seen = [], set()
    db = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        for word in words:
            for key in dict.fromkeys((word, word.lower())):
                for (ident, data) in db.execute(
                        "SELECT entries.id, entries.data FROM keys JOIN entries ON entries.id = keys.id WHERE keys.key = ? "
                        "ORDER BY entries.id LIMIT ?", (key, most)):
                    if ident not in seen:
                        seen.add(ident)
                        out.append(json.loads(data))
                if len(out) >= most:
                    return out[:most]
    finally:
        db.close()
    return out


# ---------------------------------------------------------------- downloads, as the app's network mode has them

class Offline(OSError):
    """Sluka is set to work offline (config.ini [network] mode): nothing is downloaded."""


def _take(sock: socket.socket, n: int) -> bytes:
    got = b""
    while len(got) < n:
        piece = sock.recv(n - len(got))
        if not piece:
            raise OSError("the SOCKS proxy hung up")
        got += piece
    return got


def socks_connect(proxy: str, host: str, port: int, timeout: float | None = 60) -> socket.socket:
    """A connection to ``host:port`` through a SOCKS5 proxy (Tor's), which resolves the name itself: nothing about
    the site leaves this computer but through the proxy."""
    where, _, number = proxy.strip().rpartition(":")
    sock = socket.create_connection((where.strip("[]") or "127.0.0.1", int(number or 9050)), timeout=timeout)
    try:
        sock.sendall(b"\x05\x01\x00")  # (version 5; one method: none)
        if _take(sock, 2) != b"\x05\x00":
            raise OSError("the SOCKS proxy refused Sluka")
        name = host.encode("idna")
        sock.sendall(b"\x05\x01\x00\x03" + bytes([len(name)]) + name + int(port).to_bytes(2, "big"))
        head = _take(sock, 4)
        if head[1] != 0:
            raise OSError(f"Tor could not reach {host} (SOCKS error {head[1]})")
        _take(sock, {1: 4, 4: 16}.get(head[3]) or _take(sock, 1)[0])  # (the address it bound, unused)
        _take(sock, 2)
        return sock
    except BaseException:
        sock.close()
        raise


class _SocksHTTP(http.client.HTTPConnection):
    def __init__(self, *args, proxy: str, **kwargs):
        super().__init__(*args, **kwargs)
        self._proxy = proxy

    def connect(self):
        self.sock = socks_connect(self._proxy, self.host, self.port, self.timeout)


class _SocksHTTPS(http.client.HTTPSConnection):
    def __init__(self, *args, proxy: str, **kwargs):
        super().__init__(*args, **kwargs)
        self._proxy = proxy

    def connect(self):
        sock = socks_connect(self._proxy, self.host, self.port, self.timeout)
        self.sock = self._context.wrap_socket(sock, server_hostname=self.host)


class _SocksHTTPHandler(urllib.request.HTTPHandler):
    def __init__(self, proxy: str):
        super().__init__()
        self._proxy = proxy

    def http_open(self, req):
        return self.do_open(functools.partial(_SocksHTTP, proxy=self._proxy), req)


class _SocksHTTPSHandler(urllib.request.HTTPSHandler):
    def __init__(self, proxy: str):
        super().__init__()
        self._proxy = proxy

    def https_open(self, req):
        return self.do_open(functools.partial(_SocksHTTPS, proxy=self._proxy), req, context=self._context)


def opener_for(config) -> urllib.request.OpenerDirector:
    """How a dictionary is downloaded: not at all offline, through Tor's SOCKS proxy in tor mode (names resolved
    there), as any program's download otherwise."""
    mode = getattr(config, "network_mode", "direct")
    if mode == "offline":
        raise Offline("Sluka is set to work offline (config.ini, [network] mode = offline), so nothing is "
                      "downloaded. Set mode = tor there (or direct, away from Tails), start Sluka again, and "
                      "try again.")
    if mode == "tor":
        proxy = getattr(config, "socks", "") or "127.0.0.1:9050"
        return urllib.request.build_opener(urllib.request.ProxyHandler({}), _SocksHTTPHandler(proxy), _SocksHTTPSHandler(proxy))
    return urllib.request.build_opener()


# ---------------------------------------------------------------- the app's side

class Dictionaries:
    """The offline dictionaries: which there are for a language, installing one (downloaded, then read into its own
    file), looking words up in one, and the small windows the Look up key opens."""

    def __init__(self, folder, host=None, fetch=None):
        self.folder = Path(folder)
        self.host = host
        self._fetch = fetch or self._urlopen
        self._lock = threading.Lock()
        self._jobs: dict[str, dict] = {}
        # Your own dictionaries in other kinds of file, made into Yomitan dictionaries for Sluka (dictfiles.py).
        from .dictfiles import Files
        self.files = Files(self.folder / "files")

    def _urlopen(self, url: str, method: str = "GET"):
        opener = opener_for(getattr(self.host, "config", None))
        request = urllib.request.Request(url, method=method, headers={"User-Agent": USER_AGENT})
        return opener.open(request, timeout=60)

    def _file(self, dict_id: str, lang: str) -> Path:
        return self.folder / f"{dict_id}-{lang}.sqlite"

    def _about(self, dict_id: str, lang: str) -> dict:
        try:
            return json.loads((self.folder / f"{dict_id}-{lang}.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def installed(self) -> list:
        """Every dictionary installed, as ``"<id>-<lang>"``."""
        try:
            return sorted(p.stem for p in self.folder.glob("*.sqlite"))
        except OSError:
            return []

    def state(self, dict_id: str, lang: str) -> dict:
        about = CATALOG[dict_id]
        key = f"{dict_id}-{lang}"
        with self._lock:
            job = dict(self._jobs.get(key) or {})
        out = {"ok": True, "id": dict_id, "lang": lang, "name": about["name"], "by": about["by"], "licence": about["licence"],
               "home": about["home"], "installed": self._file(dict_id, lang).is_file()}
        if out["installed"]:
            out.update({k: v for k, v in self._about(dict_id, lang).items() if k in ("entries", "source", "date", "size")})
        if job:
            out["job"] = job
        return out

    def _source(self, dict_id: str, lang: str, name: str) -> str:
        about = CATALOG[dict_id]
        if about.get("url"):
            return about["url"]
        # Wiktionary: the language's own file, as its page at kaikki.org links it.
        page = about["page"].format(name=urllib.parse.quote(name))
        with self._fetch(page) as res:
            html = res.read(4 * 1024 * 1024).decode("utf-8", "replace")
        links = re.findall(r'href="([^"]+\.jsonl)"', html)
        if not links:
            raise OSError(f"kaikki.org has no file for {name}")
        return urllib.parse.urljoin(page, links[0])

    def size(self, dict_id: str, lang: str, name: str = "") -> dict:
        """How large the download is, before it is asked for."""
        try:
            url = self._source(dict_id, lang, name)
            with self._fetch(url, method="HEAD") as res:
                length = int(res.headers.get("Content-Length") or 0)
            return {"ok": True, "url": url, "size": length}
        except Offline as err:
            return {"ok": False, "offline": True, "error": str(err)}
        except Exception as err:
            return {"ok": False, "error": str(err)}

    def install(self, dict_id: str, lang: str, name: str = "") -> dict:
        key = f"{dict_id}-{lang}"
        with self._lock:
            if self._jobs.get(key, {}).get("state") in ("downloading", "reading"):
                return {"ok": True, "started": False}
            self._jobs[key] = {"state": "downloading", "got": 0, "size": 0}
        threading.Thread(target=self._install, args=(dict_id, lang, name), name=f"sluka-dict-{key}", daemon=True).start()
        return {"ok": True, "started": True}

    def _job(self, key: str, **changes) -> None:
        with self._lock:
            self._jobs.setdefault(key, {}).update(changes)

    def _install(self, dict_id: str, lang: str, name: str) -> None:
        key = f"{dict_id}-{lang}"
        about = CATALOG[dict_id]
        download = self.folder / f"{key}.download"
        try:
            self.folder.mkdir(parents=True, exist_ok=True)
            url = self._source(dict_id, lang, name)
            got = 0
            with self._fetch(url) as res, open(download, "wb") as out:
                size = int(res.headers.get("Content-Length") or 0)
                self._job(key, size=size)
                while True:
                    piece = res.read(256 * 1024)
                    if not piece:
                        break
                    out.write(piece)
                    got += len(piece)
                    self._job(key, got=got)
            self._job(key, state="reading", entries=0)
            n = build(READERS[about["format"]], download, self._file(dict_id, lang),
                      progress=lambda count: self._job(key, entries=count))
            if not n:
                raise OSError("the file held no entries")
            (self.folder / f"{key}.json").write_text(json.dumps(
                {"entries": n, "source": url, "date": time.strftime("%Y-%m-%d"), "size": got}), encoding="utf-8")
            self._job(key, state="ready", entries=n)
            log.info("the offline dictionary %s (%s) is installed: %d entries, from %s", about["name"], lang, n, url)
        except Exception as err:
            log.warning("the offline dictionary %s (%s) could not be installed: %s", about["name"], lang, err)
            self._job(key, state="failed", error=str(err))
            try:
                self._file(dict_id, lang).with_suffix(".building").unlink()
            except OSError:
                pass
        finally:
            try:
                download.unlink()
            except OSError:
                pass

    def remove(self, dict_id: str, lang: str) -> dict:
        for path in (self._file(dict_id, lang), self.folder / f"{dict_id}-{lang}.json"):
            try:
                path.unlink()
            except FileNotFoundError:
                pass
        with self._lock:
            self._jobs.pop(f"{dict_id}-{lang}", None)
        return {"ok": True}

    def find(self, dict_id: str, lang: str, words) -> dict:
        path = self._file(dict_id, lang)
        if not path.is_file():
            return {"ok": False, "error": "not installed"}
        words = [str(w)[:QUERY_MOST] for w in words if isinstance(w, str) and w.strip()][:4]
        return {"ok": True, "entries": lookup(path, [w.strip() for w in words])}

    def open(self, args: dict) -> dict:
        """A small window of Sluka's own: a site online (``url``), or an offline dictionary's page of the app's."""
        shell = getattr(self.host, "shell", None)
        url = str(args.get("url") or "")
        own = bool(args.get("offline"))
        scheme = urllib.parse.urlsplit(url).scheme.lower()
        if own:
            if not url.startswith("/__sluka__/dict.html?"):
                return {"ok": False, "error": "not a page of the app's"}
        elif scheme != "https" and scheme != "http":
            return {"ok": False, "error": "not a site"}
        opener = getattr(shell, "open_dictionary", None)
        if not callable(opener):
            return {"ok": False, "error": "no window here"}
        opener(url, own)
        return {"ok": True}

    def api(self, name: str, req: Request, respond) -> None:
        site = str(req.headers.get("sec-fetch-site", "") or "").lower()
        if site and site not in ("same-origin", "none"):
            respond(error_response(403, "forbidden"))
            return
        if name == "installed":
            respond(json_response({"ok": True, "installed": self.installed()}))
            return
        if self.files.api(name, req, respond):
            return
        if req.method != "POST":
            respond(error_response(405, "POST"))
            return
        body = req.body or b""
        if len(body) > BODY_MOST:
            respond(error_response(413, "too large"))
            return
        try:
            args = json.loads(body.decode("utf-8")) if body else {}
        except (ValueError, UnicodeDecodeError):
            respond(error_response(400, "not JSON"))
            return
        if not isinstance(args, dict):
            respond(error_response(400, "not an object"))
            return
        if name == "open":
            respond(json_response(self.open(args)))
            return
        dict_id, lang = str(args.get("id") or ""), str(args.get("lang") or "")
        wiki = str(args.get("name") or "")
        if not LANG.fullmatch(lang) or not offers(dict_id, lang) or (wiki and not NAME.fullmatch(wiki)):
            respond(error_response(400, "no such dictionary"))
            return
        if name == "state":
            respond(json_response(self.state(dict_id, lang)))
        elif name == "size":
            threading.Thread(target=lambda: respond(json_response(self.size(dict_id, lang, wiki))), daemon=True).start()
        elif name == "install":
            if dict_id == "wiktionary" and not wiki:
                respond(error_response(400, "which language"))
                return
            respond(json_response(self.install(dict_id, lang, wiki)))
        elif name == "remove":
            respond(json_response(self.remove(dict_id, lang)))
        elif name == "lookup":
            words = args.get("words") if isinstance(args.get("words"), list) else []
            respond(json_response(self.find(dict_id, lang, words)))
        else:
            respond(error_response(404, "no such call"))
