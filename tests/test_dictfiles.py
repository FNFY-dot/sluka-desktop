"""Your own dictionaries in other kinds of file, made into Yomitan dictionaries for Sluka (sluka_desktop/dictfiles.py):
each kind read as its makers write it, whatever it came in, as data only; and the calls the dashboard makes of it."""

from __future__ import annotations

import gzip
import io
import json
import struct
import tarfile
import time
import zipfile
from pathlib import Path

import pytest

from fakes import APP  # noqa: F401  (puts the app on the path)
from sluka_desktop import dictfiles, dictionaries
from sluka_desktop.host import Request


# ---------------------------------------------------------------- dictionaries of each kind, made here

def stardict(folder: Path, name="pets", same="h", wide=False, entries=None) -> list:
    """A StarDict dictionary's files: .ifo, .idx, .dict.dz (gzipped, as dictzip is) and .syn."""
    entries = entries or [("cat", "<b>cat</b><br>a small <i>furry</i> animal<script>alert(1)</script>"),
                          ("dog", "a <a href='https://example.org/dog'>dog</a>; <a href='javascript:x'>a bad link</a>")]
    dic, idx = b"", b""
    for word, text in entries:
        data = text.encode("utf-8") if same else b"t" + "ˈkæt".encode() + b"\0" + b"h" + text.encode() + b"\0"
        idx += word.encode() + b"\0" + struct.pack(">QI" if wide else ">II", len(dic), len(data))
        dic += data
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{name}.ifo").write_text("StarDict's dict ifo file\nversion=3.0.0\nbookname=Pets\nwordcount=2\n"
                                         + (f"sametypesequence={same}\n" if same else "")
                                         + ("idxoffsetbits=64\n" if wide else "") + "author=Someone\n", encoding="utf-8")
    (folder / f"{name}.idx").write_bytes(idx)
    with gzip.open(folder / f"{name}.dict.dz", "wb") as g:
        g.write(dic)
    (folder / f"{name}.syn").write_bytes(b"kitty\0" + struct.pack(">I", 0))
    return [folder / f"{name}{ext}" for ext in (".ifo", ".idx", ".dict.dz", ".syn")]


DSL = ('#NAME "Tiny Lingvo"\n#INDEX_LANGUAGE "English"\n#CONTENTS_LANGUAGE "Russian"\n\n'
       "colo(u)r\n\t[m1][p]n[/p] [trn]цв[']е[/']т[/trn][/m]\n\t[m2][ex]the ~ red[/ex] {{a note}}[/m]\n"
       "\t[m1][url]https://example.org/c[/url] [url]javascript:x[/url][/m]\n"
       "house\nhome\n\t[m1][trn]дом[/trn] [s]house.wav[/s][/m]\n")


def dsl(folder: Path, name="tiny.dsl") -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / name
    path.write_bytes(b"\xff\xfe" + DSL.encode("utf-16-le"))
    return path


JMDICT = ('<?xml version="1.0"?>\n<!DOCTYPE JMdict [\n<!ELEMENT JMdict (entry*)>\n<!ENTITY n "noun (common) (futsuumeishi)">\n]>\n'
          "<JMdict><entry><ent_seq>1</ent_seq><k_ele><keb>猫</keb></k_ele><r_ele><reb>ねこ</reb></r_ele>"
          "<sense><pos>&n;</pos><gloss>cat</gloss></sense><sense><pos>&n;</pos><gloss>shamisen</gloss></sense></entry></JMdict>")
CEDICT = "# CC-CEDICT\n中國 中国 [Zhong1 guo2] /China/Middle Kingdom/\n貓 猫 [mao1] /cat/\n"
CANTO = "# CC-Canto\n貓 猫 [mao1] {maau1} /cat/\n"
KAIKKI = json.dumps({"word": "gato", "lang": "Spanish", "lang_code": "es", "pos": "noun",
                     "senses": [{"glosses": ["cat"]}, {"glosses": ["jack"], "tags": ["mechanics"]}]}) + "\n"
FOLKETS = ('<?xml version="1.0" encoding="UTF-8"?><dictionary><word value="hus" class="nn"><translation value="house"/>'
           '<paradigm><inflection value="huset"/></paradigm></word></dictionary>')


def made(tmp_path: Path, files: list) -> tuple:
    work = tmp_path / "work"
    work.mkdir(exist_ok=True)
    moved = []
    for f in files:
        target = work / f.name
        target.write_bytes(f.read_bytes())
        moved.append(target)
    out = dictfiles.convert(moved, work, "sluka-test")
    with zipfile.ZipFile(out["path"]) as z:
        index = json.loads(z.read("index.json"))
        rows = [r for n in sorted(z.namelist()) if n.startswith("term_bank_") for r in json.loads(z.read(n))]
    return out, index, rows


def by_term(rows):
    return {r[0]: r for r in rows}


def sub(tmp_path: Path, name: str) -> Path:
    """A folder of its own, for another dictionary made in the same test."""
    folder = tmp_path / name
    folder.mkdir()
    return folder


# ---------------------------------------------------------------- each kind

def test_stardict_with_its_markup_as_yomitans_and_its_synonyms(tmp_path):
    out, index, rows = made(tmp_path, stardict(tmp_path / "in"))
    assert out["kind"] == "stardict" and out["entries"] == 3
    assert index["title"] == "Pets" and index["format"] == 3 and index["revision"] == "sluka-test" and index["author"] == "Someone"
    rows = by_term(rows)
    cat = rows["cat"][5][0]
    assert cat["type"] == "structured-content"
    assert cat["content"] == [{"tag": "span", "style": {"fontWeight": "bold"}, "content": "cat"}, {"tag": "br"}, "a small ",
                              {"tag": "span", "style": {"fontStyle": "italic"}, "content": "furry"}, " animal"]
    # A link only to the web; what is no link drawn is its text; nothing of a script.
    assert rows["dog"][5][0]["content"] == ["a ", {"tag": "a", "href": "https://example.org/dog", "content": "dog"}, "; a bad link"]
    assert "alert" not in json.dumps(rows)
    # A synonym: found, and taken to the word it is one of.
    assert rows["kitty"][5] == [["cat", ["synonym"]]]


def test_stardict_without_a_type_sequence_and_with_64_bit_offsets(tmp_path):
    out, _index, rows = made(tmp_path, stardict(tmp_path / "in", same="", wide=True))
    rows = by_term(rows)
    # Each part marked with its type: the phonetic one is the reading.
    assert rows["cat"][1] == "ˈkæt" and rows["cat"][5][0]["type"] == "structured-content"


def test_stardict_in_a_zip_or_a_tar(tmp_path):
    files = stardict(tmp_path / "in")
    with zipfile.ZipFile(tmp_path / "pets.zip", "w") as z:
        for f in files:
            z.write(f, "Pets dictionary/" + f.name)
        z.writestr("__MACOSX/._pets.ifo", b"junk")
    out, _index, rows = made(tmp_path, [tmp_path / "pets.zip"])
    assert out["kind"] == "stardict" and len(rows) == 3
    with tarfile.open(tmp_path / "pets.tar.bz2", "w:bz2") as t:
        for f in files:
            t.add(f, "pets/" + f.name)
    out, _index, rows = made(sub(tmp_path, "b"), [tmp_path / "pets.tar.bz2"])
    assert out["kind"] == "stardict" and len(rows) == 3


def test_a_lingvo_dsl_file(tmp_path):
    out, index, rows = made(tmp_path, [dsl(tmp_path / "in")])
    assert out["kind"] == "dsl" and index["title"] == "Tiny Lingvo"
    assert index["sourceLanguage"] == "en" and index["targetLanguage"] == "ru"
    rows = by_term(rows)
    # colo(u)r: found with its optional part and without it; house and home, one card's two headwords.
    assert set(rows) == {"colour", "color", "house", "home"}
    card = rows["colour"][5][0]["content"]
    assert card[0] == {"tag": "div", "content": [{"tag": "span", "style": {"fontStyle": "italic"}, "content": "n"}, " цве́т"]}
    # The second level indented; ~ the headword; a comment left out.
    assert card[1] == {"tag": "div", "style": {"marginLeft": "0.8em"}, "content": "the colour red"}
    assert card[2] == {"tag": "div", "content": [{"tag": "a", "href": "https://example.org/c", "content": "https://example.org/c"}, " javascript:x"]}
    # A sound file is not here.
    assert rows["house"][5][0]["content"] == {"tag": "div", "content": "дом"} or rows["house"][5][0]["content"] == [{"tag": "div", "content": "дом"}]
    assert rows["home"][5] == rows["house"][5]


@pytest.mark.parametrize("packed", [False, True])
def test_jmdict_plain_or_gzipped(tmp_path, packed):
    path = tmp_path / ("JMdict_e.gz" if packed else "JMdict_e")
    path.write_bytes(gzip.compress(JMDICT.encode()) if packed else JMDICT.encode())
    out, index, rows = made(tmp_path, [path])
    assert out["kind"] == "jmdict" and index["sourceLanguage"] == "ja" and "Electronic Dictionary" in index["attribution"]
    rows = by_term(rows)
    assert rows["猫"][1] == "ねこ" and rows["ねこ"][1] == ""
    # Its part of speech where it changes: said once.
    first, second = rows["猫"][5]
    assert first["content"][0] == {"tag": "span", "style": {"fontStyle": "italic"}, "content": "noun (common) (futsuumeishi)"}
    assert second == "shamisen"


def test_cedict_canto_kaikki_and_folkets(tmp_path):
    (tmp_path / "cedict_ts.u8").write_text("﻿" + CEDICT, encoding="utf-8")
    out, index, rows = made(tmp_path, [tmp_path / "cedict_ts.u8"])
    rows = by_term(rows)
    assert out["kind"] == "cedict" and index["sourceLanguage"] == "zh"
    assert rows["中國"][1] == "Zhōng guó" and rows["中国"][5] == ["China", "Middle Kingdom"]

    (tmp_path / "canto.txt.gz").write_bytes(gzip.compress(CANTO.encode()))
    out, index, rows = made(sub(tmp_path, "c"), [tmp_path / "canto.txt.gz"])
    assert out["kind"] == "cccanto" and by_term(rows)["貓"][1] == "maau1" and index["sourceLanguage"] == "yue"

    (tmp_path / "es.jsonl").write_text(KAIKKI, encoding="utf-8")
    out, index, rows = made(sub(tmp_path, "k"), [tmp_path / "es.jsonl"])
    gato = by_term(rows)["gato"][5]
    assert out["kind"] == "kaikki" and index["title"] == "Wiktionary: Spanish" and index["sourceLanguage"] == "es"
    assert gato[0]["content"][0]["content"] == "noun" and gato[1]["content"][0] == "jack "

    (tmp_path / "folkets_sv_en.xml").write_text(FOLKETS, encoding="utf-8")
    out, _index, rows = made(sub(tmp_path, "f"), [tmp_path / "folkets_sv_en.xml"])
    rows = by_term(rows)
    # An inflected form taken to its word, as a Yomitan dictionary has it.
    assert out["kind"] == "folkets" and rows["huset"][5] == [["hus", ["form"]]]


def test_the_apps_own_downloads_are_read_as_before(tmp_path):
    """The readers the offline dictionaries are installed with (dictionaries.py) take the makers' files as before."""
    (tmp_path / "c.gz").write_bytes(gzip.compress(CEDICT.encode()))
    assert [e["head"] for e, _w in dictionaries.read_cedict(tmp_path / "c.gz")] == ["中国", "猫"]
    (tmp_path / "j.gz").write_bytes(gzip.compress(JMDICT.encode()))
    assert [e["head"] for e, _w in dictionaries.read_jmdict(tmp_path / "j.gz")] == ["猫"]
    with zipfile.ZipFile(tmp_path / "canto.zip", "w") as z:
        z.writestr("cccanto-webdist.txt", CANTO)
    assert [e["reading"] for e, _w in dictionaries.read_cccanto(tmp_path / "canto.zip")] == ["maau1"]


# ---------------------------------------------------------------- what is not, and what may not be

def test_what_is_not_one_is_said_so(tmp_path):
    (tmp_path / "words.tsv").write_text("perro\tdog\n", encoding="utf-8")
    with pytest.raises(dictfiles.Unreadable, match="does not know this kind"):
        made(tmp_path, [tmp_path / "words.tsv"])
    files = stardict(tmp_path / "in")
    with pytest.raises(dictfiles.Unreadable, match="without its .ifo"):
        made(sub(tmp_path, "x"), [files[1]])


def test_names_in_an_archive_stay_inside_it(tmp_path):
    files = stardict(tmp_path / "in")
    with zipfile.ZipFile(tmp_path / "evil.zip", "w") as z:
        for f in files:
            z.write(f, "../../" + f.name)
        z.writestr("/etc/passwd-not", b"x")
    with tarfile.open(tmp_path / "evil.tar", "w") as t:
        link = tarfile.TarInfo("../outside")
        link.type = tarfile.SYMTYPE
        link.linkname = "/etc/passwd"
        t.addfile(link)
        t.add(tmp_path / "evil.zip", "../evil.zip")
    out, _index, rows = made(tmp_path, [tmp_path / "evil.tar"])
    assert out["kind"] == "stardict" and len(rows) == 3
    work = tmp_path / "work"
    assert not (tmp_path / "outside").exists() and not (tmp_path.parent / "pets.ifo").exists()
    assert all(p.parent == work for p in work.iterdir())


def test_an_archive_that_would_fill_the_disk_is_stopped(tmp_path, monkeypatch):
    monkeypatch.setattr(dictfiles, "SET_MOST", 2 * 1024 * 1024)
    (tmp_path / "big.gz").write_bytes(gzip.compress(b"\0" * (5 * 1024 * 1024)))
    with pytest.raises(dictfiles.Unreadable, match="more than Sluka Desktop reads"):
        made(tmp_path, [tmp_path / "big.gz"])


# ---------------------------------------------------------------- the calls

def call(d, name, body=None, method="POST", query=None, headers=None, raw=None, stream=False):
    got = []
    data = raw if raw is not None else (json.dumps(body).encode() if body is not None else b"")
    reader = None
    if stream:
        src = io.BytesIO(data)
        reader = src.read
        data = b""
    req = Request(method=method, path=f"/__sluka__/api/dict/{name}", query=query or {},
                  headers={"sec-fetch-site": "same-origin", **(headers or {})}, body=data, body_reader=reader)
    d.api(name, req, got.append)
    return got[0]


def answer(resp):
    return json.loads(resp.body.decode())


def test_the_dashboards_calls(tmp_path):
    d = dictionaries.Dictionaries(tmp_path / "dictionaries")
    files = stardict(tmp_path / "in")
    job = ""
    for i, f in enumerate(files):
        got = answer(call(d, "file", raw=f.read_bytes(), query={"name": f.name, **({"job": job} if job else {})}, stream=i == 2))
        assert got["ok"] and got["size"] == f.stat().st_size
        job = got["job"]
    # (a name of the job's own making only)
    assert call(d, "file", raw=b"x", query={"job": "../../x", "name": "a"}).status == 400
    assert answer(call(d, "convert", {"job": job}))["started"] is True
    for _ in range(100):
        state = answer(call(d, "converting", {"job": job}))
        if state["state"] != "reading":
            break
        time.sleep(0.05)
    assert state["state"] == "ready" and state["entries"] == 3 and state["name"] == "StarDict" and state["title"] == "Pets"
    resp = call(d, "made", method="GET", query={"job": job})
    assert resp.content_type == "application/zip" and resp.file
    with zipfile.ZipFile(resp.file[0]) as z:
        assert json.loads(z.read("index.json"))["title"] == "Pets"
    # The same files again are the same dictionary: Sluka says it is added already.
    assert json.loads(zipfile.ZipFile(resp.file[0]).read("index.json"))["revision"].startswith("sluka-")
    assert answer(call(d, "forget", {"job": job}))["ok"]
    assert not (tmp_path / "dictionaries" / "files" / job).exists()
    assert call(d, "made", method="GET", query={"job": job}).status == 404
    # Another site's page is no one to answer.
    assert call(d, "file", raw=b"x", query={"name": "a"}, headers={"sec-fetch-site": "cross-site"}).status == 403


def test_a_file_that_is_none_says_so_and_what_was_left_goes(tmp_path):
    d = dictionaries.Dictionaries(tmp_path / "dictionaries")
    job = answer(call(d, "file", raw=b"perro\tdog\n", query={"name": "words.tsv"}))["job"]
    call(d, "convert", {"job": job})
    for _ in range(100):
        state = answer(call(d, "converting", {"job": job}))
        if state["state"] != "reading":
            break
        time.sleep(0.05)
    assert state["state"] == "failed" and "does not know this kind" in state["error"]
    # A new start: whatever the last one left is gone.
    (tmp_path / "dictionaries" / "files" / "0123456789abcdef").mkdir(parents=True)
    dictionaries.Dictionaries(tmp_path / "dictionaries")
    assert not (tmp_path / "dictionaries" / "files").exists()
