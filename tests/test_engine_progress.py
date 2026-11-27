"""The engine that answers mpv, the floating subtitles and Sluka Vision (web/mpv-engine.js), whole, with what it counts
on Sluka's Home page wired in (web/progress.js): run in a real Chromium against the whole Sluka extension -- its
modules and its data -- with the app's host stood in for (the questions it passes on, the answers it carries back)
and Sluka's worker stood in for by one that writes as it writes.

What is checked is the wiring: a line answered first and counted after, an mpv player's looks banked as a film's
minutes, a game's time halved, Sluka Vision's words shown and put away -- and the subtitles answered exactly as before.

Skipped where there is no Chrome and Playwright, or no whole Sluka extension (SLUKA_EXTENSION_FULL: its unpacked
folder, data and all).
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
WEB = APP / "web"
EXTENSION = Path(os.environ.get("SLUKA_EXTENSION_FULL", "/home/claude/untrusted/sluka-ext-0.7.4-full/sluka-extension"))
CHROME = shutil.which("google-chrome") or shutil.which("chromium")

playwright = pytest.importorskip("playwright.sync_api")
if not CHROME:
    pytest.skip("no Chrome here", allow_module_level=True)
if not (EXTENSION / "data" / "es").is_dir():
    pytest.skip("no whole Sluka extension to run the engine with", allow_module_level=True)

PAGE = """<!doctype html><meta charset="utf-8"><title>engine</title>
<script>
// Sluka's settings: learning Spanish.
const store = { settings: { activeLang: 'es', activeLanguages: ['es'] } };
const heard = [];
const pick = (keys) => {
  if (keys == null) return structuredClone(store);
  if (typeof keys === 'object' && !Array.isArray(keys)) {
    const out = {};
    for (const [k, v] of Object.entries(keys)) out[k] = Object.hasOwn(store, k) ? structuredClone(store[k]) : v;
    return out;
  }
  const out = {};
  for (const k of [].concat(keys)) if (Object.hasOwn(store, k)) out[k] = structuredClone(store[k]);
  return out;
};
const sent = [];
let stats = null;
let listening = null;
let constants = null;
async function worker(msg) {
  sent.push(structuredClone(msg));
  if (!constants) return undefined;
  // A worker slow to write (busy, or a phone's store): never a reason for a line to wait.
  if (E.slow && Object.values(constants.MSG).includes(msg.type) && /^(readWords|listen)/.test(msg.type)) {
    await new Promise((r) => setTimeout(r, E.slow));
  }
  const { MSG, KEY } = constants;
  if (msg.type === MSG.READ_WORDS) {
    await stats.recordReading(msg.lang, { words: msg.words, cc: Number(msg.cc) > 0 ? Number(msg.cc) : 0, docs: msg.docs || null, unit: msg.unit });
    return { ok: true, words: msg.words };
  }
  if (msg.type === MSG.LISTEN_LOCAL_VIDEO) {
    const now = Date.now();
    const got = await chrome.storage.local.get([KEY.listenRecent]);
    const today = listening.creditLocalVideo(got[KEY.listenRecent] || [], { title: msg.title, lang: msg.lang, ms: msg.ms, now, platform: 'pc' });
    await chrome.storage.local.set({ [KEY.listenRecent]: listening.retire(today, listening.startOfDay(now)).recent });
    await stats.recordDayDeltas(msg.lang, { listenedMs: msg.ms });
    return { ok: true };
  }
  if (msg.type === MSG.LISTEN_NARRATED) {
    await stats.recordDayDeltas(msg.lang, { listenedMs: msg.ms });
    return { ok: true };
  }
  return undefined;
}
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
      remove: async (keys) => { for (const k of [].concat(keys)) delete store[k]; },
    },
    onChanged: { addListener: (f) => heard.push(f), removeListener: () => {} },
  },
  runtime: {
    id: 'sluka',
    getURL: (p = '') => location.origin + '/' + String(p).replace(/^\\/+/, ''),
    getManifest: () => ({ version: '0.7.4' }),
    sendMessage: (msg) => worker(msg),
    onMessage: { addListener: () => {}, removeListener: () => {} },
  },
};

// The app's host: the questions the players ask, passed on as mpvbridge.py passes them, and the answers kept.
const waiting = [];
const queue = [];
const replies = [];
const logs = [];
function give() {
  while (waiting.length && queue.length) waiting.shift()({ msgs: queue.splice(0) });
}
async function api(name, body) {
  if (name === 'mpv/poll') {
    return new Promise((resolve) => {
      waiting.push(resolve);
      give();
      setTimeout(() => {
        const i = waiting.indexOf(resolve);
        if (i >= 0) { waiting.splice(i, 1); resolve({ msgs: [] }); }
      }, 20000);
    });
  }
  if (name === 'mpv/reply') { replies.push(structuredClone(body)); return { ok: true }; }
  if (name === 'log') { logs.push(structuredClone(body)); return { ok: true }; }
  if (name === 'info') return {};
  return {};
}
globalThis.__slukaShim = { api };
globalThis.E = {
  store, sent, replies, logs, slow: 0,
  say(player, msg) { queue.push({ player, msg }); give(); },
  async modules() {
    constants = await import('/lib/constants.js');
    stats = await import('/lib/stats.js');
    listening = await import('/lib/listening.js');
  },
  today(lang) {
    const days = store[constants.KEY.stats(lang)] || {};
    const keys = Object.keys(days);
    return keys.length ? days[keys[0]] : {};
  },
};
</script>
<script type="module">
await E.modules();
await import('/__sluka__/mpv-engine.js');
</script>
"""


class Site(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):  # noqa: N802
        path = self.path.split("?", 1)[0]
        if path == "/test.html":
            return self._send(PAGE.encode("utf-8"), "text/html; charset=utf-8")
        if path.startswith("/__sluka__/"):
            root, rel = WEB, path[len("/__sluka__/"):]
        else:
            root, rel = EXTENSION, path[1:]
        parts = [p for p in rel.split("/") if p not in ("", ".", "..")]
        file = root.joinpath(*parts)
        if file.is_file() and root.resolve() in file.resolve().parents:
            kind = {".js": "text/javascript", ".json": "application/json", ".wasm": "application/wasm"}.get(
                file.suffix, "application/octet-stream")
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


def wait_for(page, js: str, timeout: float = 20000):
    page.wait_for_function(js, timeout=timeout)


def test_the_engine_answers_as_before_and_counts_what_is_read_and_heard(browser, site):
    page = browser.new_page()
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.on("console", lambda m: errors.append(m.text) if m.type == "error" and "Failed to load resource" not in m.text else None)
    missing = []
    page.on("response", lambda r: missing.append(r.url) if r.status == 404 else None)
    page.goto(f"{site}/test.html")
    wait_for(page, "() => globalThis.E && E.replies !== undefined")

    # The floating subtitles say hello, and are answered as ever: ready, then the words of their line.
    page.evaluate("() => E.say('bar', { t: 'hello', v: 2, sub_lang: '' })")
    wait_for(page, "() => E.replies.some((r) => r.player === 'bar' && r.msg.t === 'ready')", 60000)
    text = "Hola amigo, ¿cómo estás hoy?"
    page.evaluate("(text) => E.say('bar', { t: 'line', id: 1, text })", text)
    wait_for(page, "() => E.replies.some((r) => r.player === 'bar' && r.msg.t === 'tokens')", 60000)
    tokens = page.evaluate("() => E.replies.find((r) => r.player === 'bar' && r.msg.t === 'tokens').msg")
    assert tokens["id"] == 1 and len(tokens["toks"]) >= 4, tokens

    # A game played with them (the app's play clock), and the bar's page going: half of it heard, and what was read.
    page.wait_for_timeout(1500)
    page.evaluate("() => E.say('bar', { t: 'played', ms: 60000 })")
    page.evaluate("() => E.say('bar', { t: 'bye' })")
    wait_for(page, "() => E.sent.some((m) => m.type === 'listenNarrated') && E.sent.some((m) => m.type === 'readWords')")
    narrated = page.evaluate("() => E.sent.find((m) => m.type === 'listenNarrated')")
    assert narrated["lang"] == "es" and narrated["ms"] == 30000
    read = page.evaluate("() => E.sent.find((m) => m.type === 'readWords')")
    assert read["lang"] == "es" and read["unit"] == "words" and "sluka-desktop:bar" in read["docs"]

    # An mpv player: hello, a line with its times, its looks for half a minute, and it closes.
    page.evaluate("() => E.say('7001', { t: 'hello', v: 2, pid: 7001, sub_lang: 'spa' })")
    wait_for(page, "() => E.replies.some((r) => r.player === '7001' && r.msg.t === 'ready')", 60000)
    page.evaluate("""() => {
        E.say('7001', { t: 'clock', at: 100, pos: 9, play: true, sound: true, title: 'La película.mkv', alang: '' });
        E.say('7001', { t: 'line', id: 1, text: 'Hola amigo, ¿cómo estás hoy?', start: 10, end: 12 });
        for (let i = 1; i <= 30; i++) E.say('7001', { t: 'clock', at: 100 + i, pos: 9 + i, play: true, sound: true, title: 'La película.mkv', alang: '' });
        E.say('7001', { t: 'bye' });
    }""")
    wait_for(page, "() => E.sent.some((m) => m.type === 'listenLocalVideo')")
    film = page.evaluate("() => E.sent.find((m) => m.type === 'listenLocalVideo')")
    assert film == {"type": "listenLocalVideo", "lang": "es", "title": "La película", "ms": 30000}, film
    wait_for(page, "() => E.sent.some((m) => m.type === 'readWords' && m.cc > 0)")
    subtitle = page.evaluate("() => E.sent.find((m) => m.type === 'readWords' && m.cc > 0)")
    assert subtitle["lang"] == "es" and subtitle["words"] == 0 and subtitle["cc"] >= 4

    # Sluka Vision: its words, put away and shown again, take nothing from the answers.
    page.evaluate("() => E.say('vision', { t: 'hello', v: 2, sub_lang: '' })")
    wait_for(page, "() => E.replies.some((r) => r.player === 'vision' && r.msg.t === 'ready')", 60000)
    page.evaluate("""() => {
        E.say('vision', { t: 'line', id: 1, text: 'Nueva partida\\nCargar partida' });
        E.say('vision', { t: 'shown', on: false });
        E.say('vision', { t: 'shown', on: true });
    }""")
    wait_for(page, "() => E.replies.some((r) => r.player === 'vision' && r.msg.t === 'tokens')", 60000)

    day = page.evaluate("() => E.today('es')")
    assert day["listenedMs"] == 30000 + 30000
    assert day["cc"] >= 4
    warnings = page.evaluate("() => E.logs.filter((l) => /lacks|not counted on its Home page/.test(l.text))")
    assert warnings == []
    assert not errors, errors
    # What Sluka itself looks for and may not have (a list of your own, an optional file) is no matter here.
    print("not found:", missing)
    page.close()


def test_a_slow_worker_never_holds_a_line_up(browser, site):
    page = browser.new_page()
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto(f"{site}/test.html")
    wait_for(page, "() => globalThis.E && E.replies !== undefined")
    page.evaluate("() => E.say('bar', { t: 'hello', v: 2, sub_lang: '' })")
    wait_for(page, "() => E.replies.some((r) => r.player === 'bar' && r.msg.t === 'ready')", 60000)
    page.evaluate("() => E.say('bar', { t: 'line', id: 1, text: 'Hola amigo, ¿cómo estás hoy?' })")
    wait_for(page, "() => E.replies.filter((r) => r.player === 'bar' && r.msg.t === 'tokens').length === 1", 60000)
    page.wait_for_timeout(1200)
    # Every write now takes eight seconds.  The bar goes (what it owes is written), comes back, and has a line.
    page.evaluate("() => { E.slow = 8000; }")
    started = page.evaluate("() => performance.now()")
    page.evaluate("() => { E.say('bar', { t: 'bye' }); E.say('bar', { t: 'hello', v: 2, sub_lang: '' }); }")
    wait_for(page, "() => E.replies.filter((r) => r.player === 'bar' && r.msg.t === 'ready').length === 2")
    page.evaluate("() => E.say('bar', { t: 'line', id: 2, text: 'Muy bien, gracias.' })")
    wait_for(page, "() => E.replies.some((r) => r.player === 'bar' && r.msg.t === 'tokens' && r.msg.id === 2)")
    took = page.evaluate("() => performance.now()") - started
    assert took < 4000, f"the line waited {took:.0f} ms"
    # The write that was slow lands all the same.
    wait_for(page, "() => E.sent.some((m) => m.type === 'readWords')")
    assert not errors, errors
    page.close()
