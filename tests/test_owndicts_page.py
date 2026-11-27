"""Settings → Dictionary → Your own dictionaries, in the app (web/owndicts.js): a dictionary in a kind of file Sluka
does not read itself, picked with Sluka's own "Add a dictionary…", made into a Yomitan dictionary by the app
(dictfiles.py, the real one, behind a real Dictionaries) and handed to Sluka's own file box as if that had been
picked -- where Sluka's own Yomitan reader (lib/own-dicts/yomitan.js) reads it; a Yomitan dictionary or a table goes
to Sluka just as it is.

Skipped where there is no Chrome and Playwright, or no Sluka extension whole (SLUKA_EXTENSION_FULL).
"""

from __future__ import annotations

import functools
import gzip
import http.server
import json
import os
import shutil
import threading
import urllib.parse
from pathlib import Path

import pytest

from fakes import APP as _APP  # noqa: F401  (puts the app on the path)
from sluka_desktop import dictionaries
from sluka_desktop.host import Request
from test_dictfiles import CEDICT, dsl, stardict

APP = Path(os.environ.get("SLUKA_APP", "/home/claude/work/sluka-desktop/app"))
EXTENSION = Path(os.environ.get("SLUKA_EXTENSION_FULL", "/home/claude/untrusted/sluka-ext-0.7.4-full/sluka-extension"))
CHROME = shutil.which("google-chrome") or shutil.which("chromium")

playwright = pytest.importorskip("playwright.sync_api")
if not CHROME:
    pytest.skip("no Chrome here", allow_module_level=True)
if not (EXTENSION / "lib" / "own-dicts" / "yomitan.js").is_file():
    pytest.skip("no Sluka extension with its own dictionaries to try it with", allow_module_level=True)

# The card as the dashboard has it (dashboard/dashboard.html #ownDictCard), and in place of Sluka's own reading of
# what is picked (dashboard/own-dicts.js), one that reads a Yomitan dictionary with Sluka's own reader -- its button
# off while it reads, as Sluka's is.
PAGE = """<!doctype html><meta charset="utf-8"><title>dashboard</title><body>
<div class="card" id="ownDictCard">
  <h2>Your own dictionaries</h2>
  <p class="muted">Sluka reads Yomitan dictionaries (.zip) and tables (.csv, .tsv or .txt).</p>
  <div class="row"><button type="button" id="ownDictAdd">Add a dictionary…</button><input type="file" id="ownDictFile" hidden /></div>
  <p class="note" id="ownDictNote"></p>
</div>
<script type="module">
const taken = (globalThis.__taken = []);
const add = document.getElementById('ownDictAdd');
const box = document.getElementById('ownDictFile');
add.addEventListener('click', () => box.click());
box.addEventListener('change', async (e) => {
  const picked = e.target.files?.[0];
  e.target.value = '';
  if (!picked) return;
  add.disabled = true;
  try {
    const head = new Uint8Array(await picked.slice(0, 2).arrayBuffer());
    if (head[0] === 0x50 && head[1] === 0x4b) {
      const { openYomitan, yomitanRows } = await import('/ext/lib/own-dicts/yomitan.js');
      const dict = await openYomitan(picked);
      let rows = 0;
      for await (const batch of yomitanRows(dict, 'en')) rows += batch.rows.length;
      taken.push({ name: picked.name, kind: 'yomitan', title: dict.title, rows, revision: dict.about.revision });
    } else {
      taken.push({ name: picked.name, kind: 'table', text: await picked.text() });
    }
  } catch (err) {
    taken.push({ name: picked.name, error: String(err?.message || err) });
  } finally {
    add.disabled = false;
  }
});
globalThis.__slukaShim = {
  async api(name, body) {
    const res = await fetch('/__sluka__/api/' + name, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body ?? {}) });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || name);
    return data;
  },
};
const own = document.createElement('script');
own.src = '/__sluka__/owndicts.js';
document.head.append(own);
globalThis.__ready = true;
</script>
"""


class Site(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    dicts: dictionaries.Dictionaries = None
    asked: list = []

    def log_message(self, *args):
        pass

    def _send(self, status: int, kind: str, body: bytes):
        self.send_response(status)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _api(self):
        url = urllib.parse.urlsplit(self.path)
        name = url.path[len("/__sluka__/api/dict/"):]
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length) if length else b""
        req = Request(method=self.command, path=url.path, query={k: v[-1] for k, v in urllib.parse.parse_qs(url.query).items()},
                      headers={k.lower(): v for k, v in self.headers.items()}, body=body)
        Site.asked.append(name)
        got = []
        self.dicts.api(name, req, got.append)
        resp = got[0]
        data = resp.body
        if resp.file:
            with open(resp.file[0], "rb") as f:
                data = f.read()
        self._send(resp.status, resp.content_type, data)

    def do_POST(self):  # noqa: N802
        if self.path.startswith("/__sluka__/api/dict/"):
            return self._api()
        self._send(404, "text/plain", b"")

    def do_GET(self):  # noqa: N802
        path = self.path.split("?", 1)[0]
        if path.startswith("/__sluka__/api/dict/"):
            return self._api()
        if path == "/dashboard/test.html":
            return self._send(200, "text/html; charset=utf-8", PAGE.encode("utf-8"))
        if path == "/__sluka__/owndicts.js":
            return self._send(200, "text/javascript", (APP / "web" / "owndicts.js").read_bytes())
        if path.startswith("/ext/"):
            file = EXTENSION / path[len("/ext/"):]
            if file.is_file():
                return self._send(200, "text/javascript" if file.suffix == ".js" else "application/json", file.read_bytes())
        self._send(404, "text/plain", b"")


@pytest.fixture(scope="module")
def site(tmp_path_factory):
    Site.dicts = dictionaries.Dictionaries(tmp_path_factory.mktemp("data") / "dictionaries")
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(Site))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    with playwright.sync_playwright() as p:
        chrome = p.chromium.launch(executable_path=CHROME, args=["--no-sandbox"])
        yield chrome, f"http://127.0.0.1:{server.server_port}"
        chrome.close()
    server.shutdown()


def open_card(site):
    chrome, base = site
    page = chrome.new_page()
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto(f"{base}/dashboard/test.html")
    page.wait_for_function("() => globalThis.__ready && document.querySelector('.sluka-desktop-kinds')")
    Site.asked.clear()
    return page, errors


def taken(page, n=1):
    page.wait_for_function(f"() => globalThis.__taken.length >= {n}", timeout=20000)
    return page.evaluate("() => globalThis.__taken")


def test_a_stardict_dictionary_made_into_one_sluka_reads(site, tmp_path):
    page, errors = open_card(site)
    assert page.evaluate("() => document.getElementById('ownDictFile').multiple") is True
    assert "StarDict, ABBYY Lingvo (.dsl), JMdict" in page.locator(".sluka-desktop-kinds").inner_text()
    files = stardict(tmp_path / "pets")
    page.set_input_files("#ownDictFile", [str(f) for f in files])
    got = taken(page)
    # Sluka's own reader took it: its title, all its entries, the revision that tells the same file added again.
    assert got == [{"name": "pets.zip", "kind": "yomitan", "title": "Pets", "rows": 3, "revision": got[0]["revision"]}]
    assert got[0]["revision"].startswith("sluka-")
    assert Site.asked.count("file") == 4 and "convert" in Site.asked and "made" in Site.asked
    # And the app let its copies go.
    page.wait_for_function("() => !document.getElementById('ownDictAdd').disabled")
    page.wait_for_timeout(200)
    assert "forget" in Site.asked
    assert page.locator(".sluka-desktop-making").is_hidden()
    assert not errors, errors


def test_a_lingvo_file_and_a_gzipped_cedict(site, tmp_path):
    page, errors = open_card(site)
    (tmp_path / "cedict_1_0_ts_utf-8_mdbg.txt.gz").write_bytes(gzip.compress(CEDICT.encode()))
    page.set_input_files("#ownDictFile", [str(dsl(tmp_path)), str(tmp_path / "cedict_1_0_ts_utf-8_mdbg.txt.gz")])
    got = taken(page, 2)
    assert [(g["name"], g["title"], g["rows"]) for g in got] == [("tiny.zip", "Tiny Lingvo", 4), ("cedict_1_0_ts_utf-8_mdbg.zip", "CC-CEDICT", 4)]
    assert not errors, errors


def test_what_sluka_reads_itself_goes_to_it_as_it_is(site, tmp_path):
    page, errors = open_card(site)
    (tmp_path / "words.tsv").write_text("perro\tdog\n", encoding="utf-8")
    page.set_input_files("#ownDictFile", [str(tmp_path / "words.tsv")])
    got = taken(page)
    assert got == [{"name": "words.tsv", "kind": "table", "text": "perro\tdog\n"}]
    # A Yomitan dictionary of its own, too.
    zipped = tmp_path / "mine.zip"
    import zipfile
    with zipfile.ZipFile(zipped, "w") as z:
        z.writestr("index.json", json.dumps({"title": "Mine", "revision": "1", "format": 3}))
        z.writestr("term_bank_1.json", json.dumps([["perro", "", "", "", 0, ["dog"], 1, ""]]))
    page.set_input_files("#ownDictFile", [str(zipped)])
    got = taken(page, 2)
    assert got[1] == {"name": "mine.zip", "kind": "yomitan", "title": "Mine", "rows": 1, "revision": "1"}
    assert "file" not in Site.asked
    assert not errors, errors


def test_a_file_no_one_reads_is_said_to_be_so(site, tmp_path):
    page, errors = open_card(site)
    (tmp_path / "pets.idx").write_bytes(b"cat\0\0\0\0\0\0\0\0\x05")
    page.set_input_files("#ownDictFile", [str(tmp_path / "pets.idx")])
    page.wait_for_function("() => /without its .ifo/.test(document.querySelector('.sluka-desktop-making').textContent)")
    assert page.evaluate("() => globalThis.__taken") == []
    assert page.evaluate("() => document.getElementById('ownDictAdd').disabled") is False
    assert not errors, errors
