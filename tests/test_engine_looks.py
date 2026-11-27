"""The 👀 count in the engine that answers mpv, the floating subtitles and Sluka Vision (web/mpv-engine.js): a click on
a word is a lookup, counted by Sluka's own counter (lib/lookups.js) into the counts its pages keep -- run here in a real
Chromium against the Sluka extension's own module, with a stand-in for the browser's storage.

The engine's part that counts is taken from mpv-engine.js as it is, between its markers.  Skipped where there is no
Chrome and Playwright, or no Sluka extension to try it with (SLUKA_EXTENSION: its unpacked folder).
"""

from __future__ import annotations

import functools
import http.server
import os
import shutil
import threading
from pathlib import Path

import pytest

APP = Path(os.environ.get("SLUKA_APP", "/home/claude/work/sluka-desktop/app"))
ENGINE = APP / "web" / "mpv-engine.js"
EXTENSION = Path(os.environ.get("SLUKA_EXTENSION", "/home/claude/untrusted/sluka-ext-0.7.4/sluka-extension"))
CHROME = shutil.which("google-chrome") or shutil.which("chromium")

playwright = pytest.importorskip("playwright.sync_api")
if not CHROME:
    pytest.skip("no Chrome here", allow_module_level=True)
if not (EXTENSION / "lib" / "lookups.js").is_file():
    pytest.skip("no Sluka extension to try the count with", allow_module_level=True)

START = "/*\n * How many times each word was looked up (lib/lookups.js)"
END = "// ------------------------------------------------------------ players"


def engine_part() -> str:
    text = ENGINE.read_text(encoding="utf-8")
    start, end = text.index(START), text.index(END)
    assert start < end
    return text[start:end]


PAGE = """<!doctype html><meta charset="utf-8"><title>looks</title>
<script type="module">
const store = {};
const heard = [];
const pick = (keys) => {
  if (keys == null) return { ...store };
  const out = {};
  for (const k of [].concat(keys)) if (Object.hasOwn(store, k)) out[k] = structuredClone(store[k]);
  return out;
};
globalThis.chrome = {
  storage: {
    local: {
      get: async (keys) => pick(keys),
      set: async (items) => {
        const changes = {};
        for (const [k, v] of Object.entries(items)) {
          changes[k] = { oldValue: store[k], newValue: structuredClone(v) };
          store[k] = structuredClone(v);
        }
        for (const f of heard) f(changes, 'local');
      },
    },
    onChanged: { addListener: (f) => heard.push(f), removeListener: (f) => heard.splice(heard.indexOf(f), 1) },
  },
  runtime: { sendMessage: async () => undefined, getURL: (p) => `/ext/${p}` },
};
globalThis.__store = store;
const { LookupCounter } = await import('/ext/lib/lookups.js');
const { Tn } = await import('/ext/lib/i18n.js');
const O = globalThis.__noCounter ? {} : { LookupCounter, Tn };
const errors = (globalThis.__errors = []);
function report(err) { errors.push(String(err)); }
/*ENGINE*/
globalThis.__looks = { looksOf, looksNote };
globalThis.__ready = true;
</script>
"""


class Site(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):  # noqa: N802
        path = self.path.split("?", 1)[0]
        if path == "/test.html":
            return self._send(PAGE.replace("/*ENGINE*/", engine_part()).encode("utf-8"), "text/html; charset=utf-8")
        if path.startswith("/ext/"):
            parts = [p for p in path[len("/ext/"):].split("/") if p not in ("", ".", "..")]
            file = EXTENSION.joinpath(*parts)
            if file.is_file() and EXTENSION in file.resolve().parents:
                kind = {".js": "text/javascript", ".json": "application/json"}.get(file.suffix, "application/octet-stream")
                return self._send(file.read_bytes(), kind)
        self.send_error(404)

    def _send(self, body: bytes, kind: str):
        self.send_response(200)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


@pytest.fixture(scope="module")
def site():
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(Site))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_port}"
    server.shutdown()


@pytest.fixture(scope="module")
def browser():
    with playwright.sync_playwright() as p:
        chrome = p.chromium.launch(executable_path=CHROME, args=["--no-sandbox"])
        yield chrome
        chrome.close()


def open_page(browser, site, seed=None, no_counter=False):
    page = browser.new_page()
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    script = ""
    if no_counter:
        script += "globalThis.__noCounter = true;"
    page.add_init_script(script or "void 0")
    page.goto(f"{site}/test.html")
    page.wait_for_function("() => globalThis.__ready === true")
    if seed:
        page.evaluate("(seed) => Object.assign(globalThis.__store, seed)", seed)
    return page, errors


def test_a_click_is_counted_as_sluka_counts_one(browser, site):
    # Looked up twice already, on another device (or in a book of the app's): the third is this click.
    page, errors = open_page(browser, site, seed={"lookups:ja": {"lphone1": {"面倒": 2, "公衆電話": 7}}})
    got = page.evaluate("""async () => {
      const L = { id: 'ja' };
      const out = {};
      out.hover = await __looks.looksOf(L, '面倒', false);
      out.click = await __looks.looksOf(L, '面倒', true);
      out.again = await __looks.looksOf(L, '面倒', true);
      out.other = await __looks.looksOf(L, '公衆電話', false);
      out.first = await __looks.looksOf(L, 'わかった', true);
      out.none = await __looks.looksOf(L, '', true);
      await new Promise((r) => setTimeout(r, 300));
      out.store = structuredClone(globalThis.__store);
      out.notes = [__looks.looksNote(out.click), __looks.looksNote(out.first), __looks.looksNote(0), __looks.looksNote(1234)];
      out.errors = globalThis.__errors;
      return out;
    }""")
    # A word only pointed at is not a lookup; a click is, once a minute at most (lib/lookups.js LOOKUP_AGAIN_MS).
    assert (got["hover"], got["click"], got["again"], got["other"], got["first"], got["none"]) == (2, 3, 3, 7, 1, 0)
    # Written at once, under this device's own name, beside the other's.
    device = got["store"]["lookupsDevice"]
    assert device.startswith("l") and got["store"]["lookups:ja"][device] == {"面倒": 1, "わかった": 1}
    assert got["store"]["lookups:ja"]["lphone1"] == {"面倒": 2, "公衆電話": 7}
    # The panel's note: from the third lookup, as Sluka's says it.
    assert got["notes"][0] == {"looks": 3, "looks_title": "Looked up 3 times"}
    assert got["notes"][1] == {} and got["notes"][2] == {}
    assert got["notes"][3] == {"looks": 1234, "looks_title": "Looked up 1,234 times"}
    assert not got["errors"] and not errors, (got["errors"], errors)


def test_a_sluka_without_the_counter_counts_nothing(browser, site):
    page, errors = open_page(browser, site, no_counter=True)
    got = page.evaluate("async () => [await __looks.looksOf({ id: 'ja' }, '面倒', true), __looks.looksNote(0), structuredClone(globalThis.__store)]")
    assert got == [0, {}, {}]
    assert not errors, errors


def test_the_entry_carries_it():
    # The entry sent for a lookup carries the note; mpv's script reads what it knows of an entry and no more.
    text = ENGINE.read_text(encoding="utf-8")
    assert "const looks = looksNote(await looksOf(L, key, !!m.pin && mine));" in text
    # (and, on a pinned panel, its head's keys: ...anki, ...tools)
    assert "await send(player, { t: 'entry', id: m.id, tok: m.tok, ...entry, ...looks, ...(anki ? { anki } : {}), ...(tools ? { tools } : {}) });" in text
    assert "'/lib/lookups.js': ['LookupCounter']" in text
