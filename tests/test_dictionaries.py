"""The Look up key's dictionaries offline (dictionaries.py): each one's own file read as its makers publish it, made
into Sluka's file, words looked up in it; installed from a download (here a stand-in for its site), with Wiktionary's
file found on its language's page; and the small windows asked for only for a site, or a page of the app's own."""

from __future__ import annotations

import gzip
import io
import json
import time
import zipfile

from fakes import APP  # noqa: F401  (puts the app on the path)
from sluka_desktop import dictionaries as D
from sluka_desktop.host import Request

JMDICT = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE JMdict [
<!ELEMENT JMdict (entry*)>
<!ENTITY n "noun (common) (futsuumeishi)">
<!ENTITY v1 "Ichidan verb">
<!ENTITY uk "word usually written using kana alone">
]>
<JMdict>
<entry><ent_seq>1</ent_seq><k_ele><keb>運命</keb></k_ele><r_ele><reb>うんめい</reb></r_ele>
<sense><pos>&n;</pos><gloss>fate</gloss><gloss>destiny</gloss></sense><sense><gloss>lot</gloss></sense></entry>
<entry><ent_seq>2</ent_seq><k_ele><keb>食べる</keb></k_ele><k_ele><keb>喰べる</keb></k_ele><r_ele><reb>たべる</reb></r_ele>
<sense><pos>&v1;</pos><misc>&uk;</misc><gloss>to eat</gloss></sense></entry>
<entry><ent_seq>3</ent_seq><r_ele><reb>ここ</reb></r_ele><sense><pos>&n;</pos><gloss>here</gloss></sense></entry>
</JMdict>
"""
CEDICT = """# CC-CEDICT
#! license=https://creativecommons.org/licenses/by-sa/4.0/
中國 中国 [Zhong1 guo2] /China/
命運 命运 [ming4 yun4] /fate/destiny/lot/
女 女 [nu:3] /female/woman/
"""
CANTO = "食飯 食饭 [shi2 fan4] {sik6 faan6} /to eat a meal/\n"
FOLKETS = """<?xml version="1.0" encoding="UTF-8"?>
<dictionary><word value="hund" class="nn" lang="sv"><translation value="dog"/><translation value="hound"/>
<paradigm><inflection value="hundar"/><inflection value="hunden"/></paradigm></word>
<word value="springa" class="vb" lang="sv"><translation value="run"/></word></dictionary>
"""
KAIKKI = "\n".join(json.dumps(x, ensure_ascii=False) for x in [
    {"word": "運命", "pos": "noun", "senses": [{"glosses": ["fate, destiny"], "tags": ["uncountable"]}], "sounds": [{"ipa": "[ɯ̟mme̞ː]"}]},
    {"word": "Pferd", "pos": "noun", "senses": [{"glosses": ["horse"]}]},
    {"word": "bad", "pos": "noun", "senses": []},
])


def test_pinyin_is_marked():
    assert D.pinyin_marks("Zhong1 guo2") == "Zhōng guó"
    assert D.pinyin_marks("nu:3 lu:4 xue2 liu2 ge5") == "nǚ lǜ xué liú ge"


def test_each_dictionary_is_read_as_its_makers_publish_it(tmp_path):
    files = {}
    files["jmdict"] = tmp_path / "JMdict_e.gz"
    files["jmdict"].write_bytes(gzip.compress(JMDICT.encode()))
    files["cedict"] = tmp_path / "cedict.txt.gz"
    files["cedict"].write_bytes(gzip.compress(CEDICT.encode()))
    files["cccanto"] = tmp_path / "cccanto.zip"
    with zipfile.ZipFile(files["cccanto"], "w") as z:
        z.writestr("cccanto-webdist.txt", "# CC-Canto\n" + CANTO)
    files["folkets"] = tmp_path / "folkets.xml"
    files["folkets"].write_text(FOLKETS, encoding="utf-8")
    files["kaikki"] = tmp_path / "kaikki.jsonl"
    files["kaikki"].write_text(KAIKKI, encoding="utf-8")
    made = {}
    for fmt, path in files.items():
        target = tmp_path / f"{fmt}.sqlite"
        made[fmt] = (D.build(D.READERS[fmt], path, target), target)
    n, db = made["jmdict"]
    assert n == 3
    fate = D.lookup(db, ["運命"])
    assert fate == [{"head": "運命", "also": [], "reading": "うんめい", "senses": [
        {"pos": "noun (common) (futsuumeishi)", "glosses": ["fate", "destiny"]},
        {"pos": "noun (common) (futsuumeishi)", "glosses": ["lot"]}]}]  # (a sense without its own: the one before's)
    eat = D.lookup(db, ["たべる"])[0]
    assert eat["head"] == "食べる" and eat["also"] == ["喰べる"] and eat["senses"][0]["notes"] == "word usually written using kana alone"
    assert D.lookup(db, ["ここ"])[0]["head"] == "ここ" and D.lookup(db, ["nothing"]) == []
    n, db = made["cedict"]
    assert n == 3 and D.lookup(db, ["命運"])[0] == {"head": "命运", "also": ["命運"], "reading": "mìng yùn",
                                                     "senses": [{"glosses": ["fate", "destiny", "lot"]}]}
    assert D.lookup(db, ["中国"])[0]["reading"] == "Zhōng guó"
    n, db = made["cccanto"]
    assert D.lookup(db, ["食饭"])[0]["reading"] == "sik6 faan6"
    n, db = made["folkets"]
    hund = D.lookup(db, ["hundar"])[0]
    assert hund["head"] == "hund" and hund["senses"][0] == {"pos": "noun", "glosses": ["dog", "hound"]}
    n, db = made["kaikki"]
    assert n == 2 and D.lookup(db, ["pferd"])[0]["senses"][0]["glosses"] == ["horse"]  # (any case)
    got = D.lookup(db, ["運命"])[0]
    assert got["reading"] == "[ɯ̟mme̞ː]" and got["senses"][0]["notes"] == "uncountable"


class Response(io.BytesIO):
    def __init__(self, data, headers=None):
        super().__init__(data)
        self.headers = headers or {"Content-Length": str(len(data))}

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


def test_installed_from_its_site_and_looked_up(tmp_path):
    asked = []
    page = '<html><a href="kaikki.org-dictionary-German.jsonl">JSONL data</a></html>'.encode()

    def fetch(url, method="GET"):
        asked.append((method, url))
        if url == "https://kaikki.org/dictionary/German/index.html":
            return Response(page)
        if url == "https://kaikki.org/dictionary/German/kaikki.org-dictionary-German.jsonl":
            return Response(KAIKKI.encode())
        if url == D.CATALOG["jmdict"]["url"]:
            return Response(gzip.compress(JMDICT.encode()))
        raise OSError(f"no {url}")

    dicts = D.Dictionaries(tmp_path / "dictionaries", fetch=fetch)
    assert dicts.installed() == [] and not dicts.state("jmdict", "ja")["installed"]
    assert dicts.size("wiktionary", "de", "German") == {"ok": True, "url": "https://kaikki.org/dictionary/German/kaikki.org-dictionary-German.jsonl", "size": len(KAIKKI.encode())}
    for dict_id, lang, name in (("wiktionary", "de", "German"), ("jmdict", "ja", "")):
        assert dicts.install(dict_id, lang, name) == {"ok": True, "started": True}
        for _ in range(100):
            if dicts.state(dict_id, lang).get("job", {}).get("state") in ("ready", "failed"):
                break
            time.sleep(0.05)
        state = dicts.state(dict_id, lang)
        assert state["installed"] and state["job"]["state"] == "ready", state
    assert dicts.installed() == ["jmdict-ja", "wiktionary-de"]
    assert dicts.state("jmdict", "ja")["entries"] == 3 and dicts.state("jmdict", "ja")["licence"] == "CC BY-SA 4.0"
    assert dicts.find("jmdict", "ja", ["運命"])["entries"][0]["senses"][0]["glosses"] == ["fate", "destiny"]
    assert not list((tmp_path / "dictionaries").glob("*.download"))  # (the download itself, gone)
    # One that cannot be had says why, and leaves nothing behind.
    assert dicts.install("cedict", "zh") == {"ok": True, "started": True}
    for _ in range(100):
        if dicts.state("cedict", "zh").get("job", {}).get("state") == "failed":
            break
        time.sleep(0.05)
    assert "no https://www.mdbg.net" in dicts.state("cedict", "zh")["job"]["error"]
    assert dicts.installed() == ["jmdict-ja", "wiktionary-de"]
    assert dicts.remove("jmdict", "ja") == {"ok": True} and dicts.installed() == ["wiktionary-de"]


def test_the_calls_take_only_what_there_is(tmp_path):
    class Shell:
        opened = []

        def open_dictionary(self, url, own):
            self.opened.append((url, own))

    class Host:
        shell = Shell()

    dicts = D.Dictionaries(tmp_path, host=Host(), fetch=lambda url, method="GET": Response(b""))
    out = []

    def call(name, args, method="POST", headers=None):
        dicts.api(name, Request(method=method, path="/", query={}, headers=headers or {"sec-fetch-site": "same-origin"},
                                body=json.dumps(args).encode()), out.append)
        r = out[-1]
        return r.status, (json.loads(r.body) if r.body else None)

    assert call("state", {"id": "jmdict", "lang": "ja"})[1]["name"] == "JMdict"
    assert call("state", {"id": "jmdict", "lang": "zh"})[0] == 400  # (not a dictionary of that language)
    assert call("state", {"id": "nosuch", "lang": "ja"})[0] == 400
    assert call("state", {"id": "wiktionary", "lang": "../x"})[0] == 400
    assert call("install", {"id": "wiktionary", "lang": "de", "name": "Ger<script>"})[0] == 400
    assert call("install", {"id": "wiktionary", "lang": "de"})[0] == 400  # (which language's file)
    assert call("state", {"id": "jmdict", "lang": "ja"}, headers={"sec-fetch-site": "cross-site"})[0] == 403
    assert call("open", {"url": "https://jisho.org/search/x"})[1] == {"ok": True}
    assert call("open", {"url": "/__sluka__/dict.html?d=jmdict&lang=ja&q=x", "offline": True})[1] == {"ok": True}
    assert call("open", {"url": "file:///C:/Windows/win.ini"})[1]["ok"] is False
    assert call("open", {"url": "javascript:alert(1)"})[1]["ok"] is False
    assert call("open", {"url": "https://evil.example/", "offline": True})[1]["ok"] is False
    assert Shell.opened == [("https://jisho.org/search/x", False), ("/__sluka__/dict.html?d=jmdict&lang=ja&q=x", True)]
    assert call("installed", {}, method="GET")[1] == {"ok": True, "installed": []}


class Net:
    """A host whose config.ini says how Sluka may reach the Internet."""

    def __init__(self, mode, socks="127.0.0.1:9050"):
        self.config = type("Config", (), {"network_mode": mode, "socks": socks})()


def test_offline_nothing_is_downloaded(tmp_path, monkeypatch):
    def no(*args, **kwargs):
        raise AssertionError("a connection was made while offline")

    monkeypatch.setattr(D.socket, "create_connection", no)
    monkeypatch.setattr(D.urllib.request.OpenerDirector, "open", no)
    d = D.Dictionaries(tmp_path / "dicts", host=Net("offline"))
    size = d.size("jmdict", "ja")
    assert size["ok"] is False and size["offline"] is True and "offline" in size["error"]
    assert d.install("jmdict", "ja")["started"] is True
    for _ in range(100):
        job = d.state("jmdict", "ja").get("job", {})
        if job.get("state") == "failed":
            break
        time.sleep(0.02)
    assert job["state"] == "failed" and "offline" in job["error"]
    assert d.installed() == []


def test_through_tor_the_proxy_resolves_the_name(tmp_path):
    """In tor mode a download goes through the SOCKS proxy, which is given the site's name (never resolved here)."""
    import socket
    import threading

    server = socket.socket()
    server.bind(("127.0.0.1", 0))
    server.listen(1)
    asked = {}

    def proxy():
        conn, _ = server.accept()
        with conn:
            assert conn.recv(3) == b"\x05\x01\x00"
            conn.sendall(b"\x05\x00")
            head = conn.recv(5)
            assert head[:4] == b"\x05\x01\x00\x03"
            name = conn.recv(head[4])
            port = int.from_bytes(conn.recv(2), "big")
            asked.update(name=name.decode(), port=port)
            conn.sendall(b"\x05\x00\x00\x01" + bytes(4) + bytes(2))
            request = b""
            while b"\r\n\r\n" not in request:
                request += conn.recv(4096)
            asked["request"] = request.decode("latin-1")
            body = b"<a href=\"kaikki.org-dictionary-Swedish.jsonl\">"
            conn.sendall(b"HTTP/1.1 200 OK\r\nContent-Length: %d\r\nConnection: close\r\n\r\n" % len(body) + body)

    thread = threading.Thread(target=proxy, daemon=True)
    thread.start()
    d = D.Dictionaries(tmp_path / "dicts", host=Net("tor", f"127.0.0.1:{server.getsockname()[1]}"))
    with d._urlopen("http://dictionary.example.invalid/Swedish/index.html") as res:
        assert b"Swedish.jsonl" in res.read()
    thread.join(5)
    server.close()
    assert asked["name"] == "dictionary.example.invalid" and asked["port"] == 80
    assert asked["request"].startswith("GET /Swedish/index.html HTTP/1.1") and "Sluka-Desktop" in asked["request"]
