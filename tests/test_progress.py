"""What the desktop's tools add to Sluka's Home page (web/progress.js): words read on the floating subtitles and in
Sluka Vision, minutes heard and subtitle words in mpv, half of a game's time as listening -- run in a real Chromium
against the Sluka extension's own modules (lib/stats.js, lib/reading.js, lib/listening.js, lib/languages.js), with a
stand-in for the browser's storage and for Sluka's worker that writes as the worker does.  What the Home page shows is
read back from the day records as the page reads them (dashboard.js renderToday: `read`, `listenedMs`).

Skipped where there is no Chrome and Playwright, or no Sluka extension to try it with (SLUKA_EXTENSION).
"""

from __future__ import annotations

import functools
import http.server
import json
import os
import re
import shutil
import threading
from pathlib import Path

import pytest

APP = Path(os.environ.get("SLUKA_APP", "/home/claude/work/sluka-desktop/app"))
WEB = APP / "web"
EXTENSION = Path(os.environ.get("SLUKA_EXTENSION", "/home/claude/untrusted/sluka-ext-0.7.4/sluka-extension"))
CHROME = shutil.which("google-chrome") or shutil.which("chromium")

playwright = pytest.importorskip("playwright.sync_api")
if not CHROME:
    pytest.skip("no Chrome here", allow_module_level=True)
if not (EXTENSION / "lib" / "stats.js").is_file():
    pytest.skip("no Sluka extension to try the counting with", allow_module_level=True)

PAGE = """<!doctype html><meta charset="utf-8"><title>progress</title>
<script type="module">
const store = {};
const heard = [];
const pick = (keys) => {
  if (keys == null) return structuredClone(store);
  const out = {};
  for (const k of [].concat(keys)) if (Object.hasOwn(store, k)) out[k] = structuredClone(store[k]);
  return out;
};
globalThis.chrome = {
  storage: {
    local: {
      get: async (keys) => pick(keys),
      set: async (items) => {
        for (const [k, v] of Object.entries(items)) store[k] = structuredClone(v);
        for (const f of heard) f({}, 'local');
      },
      remove: async (keys) => { for (const k of [].concat(keys)) delete store[k]; },
    },
    onChanged: { addListener: (f) => heard.push(f), removeListener: () => {} },
  },
  runtime: { sendMessage: async () => undefined, getURL: (p) => `/ext/${p}` },
};
const constants = await import('/ext/lib/constants.js');
const reading = await import('/ext/lib/reading.js');
const stats = await import('/ext/lib/stats.js');
const listening = await import('/ext/lib/listening.js');
const languages = await import('/ext/lib/languages.js');
const own = (mod, names) => Object.fromEntries(names.map((n) => [n, mod[n]]));
const S = {
  MSG: constants.MSG, KEY: constants.KEY,
  ...own(reading, ['paceUnit', 'paceFrom', 'withSamples', 'hashText', 'PACE_LIMITS', 'PACE_SAMPLES_NEEDED',
    'SAMPLE_MIN_MS', 'SAMPLE_MIN_UNITS', 'CUE_SHARE', 'CUE_MAX_STEP_S']),
  ...own(stats, ['recordReading', 'recordDayDeltas', 'readingMemory']),
  ...own(listening, ['textLanguage', 'sameLanguage', 'creditLocalVideo', 'retire', 'archive', 'startOfDay']),
  strongestLanguage: languages.strongestLanguage,
};
const progressModule = await import('/app/progress.js');
const { MSG, KEY } = constants;

// Sluka's worker, as it writes what it is sent (background/service-worker.js, background/tracking.js).
const sent = [];
let worker = 'sluka';
async function ask(msg) {
  sent.push(structuredClone(msg));
  if (worker === 'down') throw new Error('Could not establish connection. Receiving end does not exist.');
  if (worker === 'refuse') return { ok: false };
  if (worker === 'old') return { ok: false, error: `unknown message: ${msg.type}` };
  if (msg.type === MSG.READ_WORDS) {
    await stats.recordReading(msg.lang, { words: msg.words, cc: Number(msg.cc) > 0 ? Number(msg.cc) : 0,
      docs: msg.docs && typeof msg.docs === 'object' ? msg.docs : null, samples: null,
      unit: msg.unit === 'chars' ? 'chars' : 'words', timed: null });
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
  return { ok: false, error: `unknown message: ${msg.type}` };
}

let clock = 1700000000000;
const settings = { activeLang: 'ja', activeLanguages: ['ja'], countReading: 'everywhere' };
const TRACK = { ja: 'ja', jpn: 'ja', en: 'en', eng: 'en', zh: 'zh', chi: 'zh', es: 'es', spa: 'es' };
const errors = [];
const logs = [];
const make = () => progressModule.startProgress({
  S,
  settings: () => settings,
  studied: () => settings.activeLanguages,
  trackLanguage: (code) => TRACK[String(code || '').toLowerCase()] || null,
  ask,
  storage: chrome.storage.local,
  now: () => clock,
  report: (err) => errors.push(String(err?.stack || err)),
  log: (text) => logs.push(text),
});

/** A line's words as the engine's cut() gives them: each piece, at its place in the text. */
function words(text, pieces) {
  const out = [];
  let at = 0;
  for (const piece of pieces) {
    const found = text.indexOf(piece, at);
    if (found < 0) throw new Error(`no ${piece} in ${text}`);
    out.push({ text: piece, at: found });
    at = found + piece.length;
  }
  return out;
}

/** The day's record as the Home page reads it: today's, of this device's stats (renderToday). */
function today(lang) {
  const days = store[KEY.stats(lang)] || {};
  const keys = Object.keys(days);
  if (keys.length > 1) throw new Error('more than one day: ' + keys.join(', '));
  return keys.length ? days[keys[0]] : {};
}

const settle = () => new Promise((r) => setTimeout(r, 30));
globalThis.T = {
  make, words, today, settle, store, sent, errors, logs, settings, S, KEY, MSG, progressModule,
  set worker(v) { worker = v; },
  advance(ms) { clock += ms; },
  get now() { return clock; },
};
globalThis.__ready = true;
</script>
"""


class Site(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):  # noqa: N802
        path = self.path.split("?", 1)[0]
        if path == "/test.html":
            return self._send(PAGE.encode("utf-8"), "text/html; charset=utf-8")
        for prefix, root in (("/ext/", EXTENSION), ("/app/", WEB)):
            if path.startswith(prefix):
                parts = [p for p in path[len(prefix):].split("/") if p not in ("", ".", "..")]
                file = root.joinpath(*parts)
                if file.is_file() and root.resolve() in file.resolve().parents:
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


@pytest.fixture
def page(browser, site):
    page = browser.new_page()
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto(f"{site}/test.html")
    page.wait_for_function("() => globalThis.__ready === true", timeout=30000)
    yield page
    assert not errors, errors
    assert page.evaluate("() => T.errors") == []


def run(page, body: str):
    return page.evaluate(f"async () => {{ {body} }}")


# ---------------------------------------------------------------- the floating subtitles

LINE = "const text = '今日はいい天気ですね'; const w = T.words(text, ['今日', 'は', 'いい', '天気', 'です', 'ね']);"
BAR = "const bar = { key: 'bar', subLang: '' }; const L = { id: 'ja' };"


def test_a_line_is_read_at_the_readers_pace_and_written_as_words_read(page):
    got = run(page, LINE + BAR + """
        const P = T.make();
        await P.line(bar, 'bar', L, text, w);
        // Sluka's starting pace for Japanese, which counts characters: 100 a minute. 3 s: 5 of the 10.
        T.advance(3000); P.tick();
        const half = T.progressModule && P.peek().readers[0];
        T.advance(3000); P.tick();
        const whole = P.peek().readers[0];
        T.advance(60000); P.tick(); await T.settle();
        return { half, whole, day: T.today('ja'), sent: T.sent.map((m) => m.type), memory: T.store[T.KEY.readToday('ja')] };
    """)
    assert got["half"]["pace"] == 100
    assert got["half"]["screen"][0]["units"] == 10 and got["half"]["screen"][0]["words"] == 6
    assert abs(got["half"]["screen"][0]["paid"] - 5) < 1e-6 and got["half"]["owed"] == 3
    assert got["whole"]["owed"] == 6
    assert got["day"]["read"] == 6, got["day"]
    assert got["sent"] == ["readWords"]
    # What was read is in today's record under the bar's own document, so it is not counted again today.
    docs = got["memory"]["docs"]
    assert list(docs) == ["sluka-desktop:bar"] and list(docs["sluka-desktop:bar"].values()) == [10]


def test_the_same_line_again_the_same_day_counts_nothing_more(page):
    got = run(page, LINE + BAR + """
        let P = T.make();
        await P.line(bar, 'bar', L, text, w);
        T.advance(10000);
        await P.gone('bar');
        const first = T.today('ja').read;
        // The app started again: the same line, read again.
        P = T.make();
        await P.line(bar, 'bar', L, text, w);
        T.advance(10000);
        await P.gone('bar');
        // And again, after another line, in the same run.
        P = T.make();
        await P.line(bar, 'bar', L, text, w);
        T.advance(10000); P.tick();
        const other = '明日は雨です';
        await P.line(bar, 'bar', L, other, T.words(other, ['明日', 'は', '雨', 'です']));
        T.advance(10000); P.tick();
        await P.line(bar, 'bar', L, text, w);
        T.advance(10000);
        await P.gone('bar');
        return { first, after: T.today('ja').read };
    """)
    assert got["first"] == 6
    assert got["after"] == 6 + 4, got


def test_lines_skipped_through_count_for_almost_nothing(page):
    got = run(page, BAR + """
        const P = T.make();
        for (let i = 0; i < 30; i++) {
          // Ten letters of a different line each tenth of a second: a game skipping its text.
          const text = Array.from({ length: 5 }, (_, k) => String.fromCodePoint(0x4E00 + i * 10 + k * 2, 0x4E01 + i * 10 + k * 2)).join('');
          const pieces = Array.from({ length: 5 }, (_, k) => text.slice(k * 2, k * 2 + 2));
          await P.line(bar, 'bar', L, text, T.words(text, pieces));
          T.advance(100);
        }
        await P.gone('bar');
        return { day: T.today('ja'), samples: T.store['sluka-desktop:linePace'] || null };
    """)
    assert (got["day"].get("read") or 0) <= 2, got
    assert got["samples"] is None


def test_only_the_languages_own_writing_counts_and_count_words_read_is_obeyed(page):
    got = run(page, BAR + """
        const P = T.make();
        const mixed = 'HP 100 回復しました';
        await P.line(bar, 'bar', L, mixed, T.words(mixed, ['HP', '回復', 'し', 'ました']));
        const shown = P.peek().readers[0].screen[0];
        const english = 'Save game';
        await P.line(bar, 'bar', L, english, T.words(english, ['Save', 'game']));
        const none = P.peek().readers[0].screen.length;
        await P.gone('bar');
        const before = T.today('ja').read || 0;
        // Settings › Reading › Count words read: only in Sluka's own reader and books.
        T.settings.countReading = 'sluka';
        const Q = T.make();
        const text = '静かな夜です';
        await Q.line(bar, 'bar', L, text, T.words(text, ['静か', 'な', '夜', 'です']));
        T.advance(60000);
        await Q.gone('bar');
        return { shown, none, before, after: T.today('ja').read || 0 };
    """)
    assert got["shown"]["units"] == 6 and got["shown"]["words"] == 3
    assert got["none"] == 0
    assert got["after"] == got["before"]


def test_the_pace_is_learned_from_how_fast_the_lines_go(page):
    got = run(page, BAR + """
        const P = T.make();
        const line = (i) => {
          // Forty letters, twenty words of two, none like another line's.
          const text = Array.from({ length: 20 }, (_, k) => String.fromCodePoint(0x4E00 + i * 40 + k * 2, 0x4E01 + i * 40 + k * 2)).join('');
          return [text, T.words(text, Array.from({ length: 20 }, (_, k) => text.slice(k * 2, k * 2 + 2)))];
        };
        const paces = [];
        for (let i = 0; i < 30; i++) {
          const [text, w] = line(i);
          await P.line(bar, 'bar', L, text, w);
          T.advance(6000); P.tick(); await T.settle();
          paces.push(P.peek().readers[0].pace);
        }
        await P.gone('bar');
        return { paces, samples: T.store['sluka-desktop:linePace'], pages: T.store[T.KEY.readPace] || null };
    """)
    # Forty letters every six seconds is 400 a minute: three measurements, and the pace is that with Sluka's margin.
    assert got["samples"]["ja"][:3] == [400, 400, 400], got["samples"]
    assert got["paces"][0] == 100
    assert got["paces"][-1] == pytest.approx(460)
    # The pages' own measurements are left as they were.
    assert got["pages"] is None


def test_a_line_typed_out_or_read_again_a_little_differently_is_one_line(page):
    got = run(page, BAR + """
        const P = T.make();
        const a = 'こんにちは元気', b = 'こんにちは元気ですか';
        await P.line(bar, 'bar', L, a, T.words(a, ['こんにちは', '元気']));
        T.advance(3000); P.tick();
        await P.line(bar, 'bar', L, b, T.words(b, ['こんにちは', '元気', 'ですか']));
        T.advance(10000); P.tick();
        const grown = P.peek().readers[0].screen;
        const c = '今日はいい天気ですね', d = '今日はいい天気ですわ';
        await P.line(bar, 'bar', L, c, T.words(c, ['今日', 'は', 'いい', '天気', 'です', 'ね']));
        T.advance(10000); P.tick();
        await P.line(bar, 'bar', L, d, T.words(d, ['今日', 'は', 'いい', '天気', 'です', 'わ']));
        T.advance(10000);
        await P.gone('bar');
        return { grown, read: T.today('ja').read };
    """)
    assert len(got["grown"]) == 1 and got["grown"][0]["units"] == 10 and got["grown"][0]["words"] == 3
    assert got["read"] == 3 + 6


# ---------------------------------------------------------------- Sluka Vision

def test_vision_reads_each_paragraph_once_and_only_while_shown(page):
    got = run(page, """
        const vision = { key: 'vision', subLang: '' }; const L = { id: 'ja' };
        const P = T.make();
        const one = 'メニュー\\n今日はいい天気ですね';
        await P.line(vision, 'vision', L, one, T.words(one, ['メニュー', '今日', 'は', 'いい', '天気', 'です', 'ね']));
        T.advance(9000); P.tick();
        const first = P.peek().readers[0];
        // The game moved on: the menu is still there, the dialogue is another.
        const two = 'メニュー\\n明日は雨です';
        await P.line(vision, 'vision', L, two, T.words(two, ['メニュー', '明日', 'は', '雨', 'です']));
        // The game not in front: nothing is read meanwhile.
        P.shown(vision, false);
        T.advance(60000); P.tick();
        const hidden = P.peek().readers[0];
        P.shown(vision, true);
        T.advance(60000);
        await P.gone('vision');
        return { first, hidden, read: T.today('ja').read, docs: Object.keys(T.store[T.KEY.readToday('ja')].docs) };
    """)
    assert [b["units"] for b in got["first"]["screen"]] == [4, 10]
    # Nine seconds at 100 a minute is 15 letters: the menu's four, and eleven of the dialogue's ten.
    assert got["first"]["owed"] == 1 + 6
    assert got["hidden"]["owed"] == 0 and got["hidden"]["screen"][1]["paid"] == 0
    assert got["read"] == 1 + 6 + 4
    assert got["docs"] == ["sluka-desktop:vision"]


# ---------------------------------------------------------------- mpv

def looks(start_at, start_pos, seconds, **extra):
    """A look each second, as mpv/sluka.lua sends them."""
    out = []
    for i in range(seconds + 1):
        look = {"t": "clock", "at": start_at + i, "pos": start_pos + i, "play": True, "sound": True, "title": "Film.mkv",
                "alang": "jpn"}
        look.update(extra)
        out.append(look)
    return out


def test_a_film_in_your_language_is_counted_by_the_your_videos_rule(page):
    got = run(page, f"""
        const P = T.make();
        const mpv = {{ key: '4242', subLang: 'jpn' }};
        for (const m of {json.dumps(looks(100, 10, 90))}) await P.clock(mpv, m);
        // Paused for a minute, then a seek ahead: no more than the second it took.
        await P.clock(mpv, {{ t: 'clock', at: 191, pos: 100, play: false, sound: false, title: 'Film.mkv', alang: 'jpn' }});
        await P.clock(mpv, {{ t: 'clock', at: 251, pos: 100, play: true, sound: true, title: 'Film.mkv', alang: 'jpn' }});
        await P.clock(mpv, {{ t: 'clock', at: 252, pos: 400, play: true, sound: true, title: 'Film.mkv', alang: 'jpn' }});
        // Muted: what a look says holds until the next, so the second up to it was heard, and the ten after it not.
        await P.clock(mpv, {{ t: 'clock', at: 253, pos: 401, play: true, sound: false, title: 'Film.mkv', alang: 'jpn' }});
        await P.clock(mpv, {{ t: 'clock', at: 263, pos: 411, play: true, sound: false, title: 'Film.mkv', alang: 'jpn' }});
        const owed = P.peek().films[0].owed;
        T.advance(61000); P.tick(); await T.settle();
        return {{ owed, day: T.today('ja'), rows: T.store[T.KEY.listenRecent], sent: T.sent }};
    """)
    assert got["owed"] == {"ja": 90000 + 1000 + 1000}
    assert got["day"]["listenedMs"] == 92000
    assert got["sent"][0]["type"] == "listenLocalVideo" and got["sent"][0]["title"] == "Film"
    assert got["rows"][0]["title"] == "Film" and got["rows"][0]["ms"] == 92000


def test_a_film_is_counted_only_where_something_says_it_is_in_your_language(page):
    got = run(page, f"""
        const out = {{}};
        // Its audio track is English.
        let P = T.make();
        let mpv = {{ key: 'a', subLang: 'jpn' }};
        for (const m of {json.dumps(looks(100, 0, 60, alang="eng"))}) await P.clock(mpv, m);
        out.english = P.peek().films[0].owed;
        await P.gone('a');
        // Nothing marked, its subtitles in English, its title says nothing.
        mpv = {{ key: 'b', subLang: 'eng' }};
        for (const m of {json.dumps(looks(100, 0, 60, alang="", title="Some Film.mkv"))}) await P.clock(mpv, m);
        out.subtitles = P.peek().films[0].owed;
        await P.gone('b');
        // Nothing marked: held until its subtitles turn out to be Japanese, then counted, the held time too.
        mpv = {{ key: 'c', subLang: '' }};
        for (const m of {json.dumps(looks(100, 0, 30, alang="", title="episode 01.mkv"))}) await P.clock(mpv, m);
        out.held = P.peek().films[0].held;
        const line = 'お前はもう死んでいる';
        await P.line(mpv, 'mpv', {{ id: 'ja' }}, line, T.words(line, ['お前', 'は', 'もう', '死ん', 'で', 'いる']), {{ start: 31, end: 33 }});
        for (const m of {json.dumps(looks(130, 30, 10, alang="", title="episode 01.mkv")[1:])}) await P.clock(mpv, m);
        out.text = P.peek().films[0];
        await P.gone('c');
        // A title written in Japanese.
        mpv = {{ key: 'd', subLang: '' }};
        for (const m of {json.dumps(looks(100, 0, 20, alang="", title="君の名は.mkv"))}) await P.clock(mpv, m);
        out.title = P.peek().films[0].owed;
        await P.gone('d');
        return {{ out, logs: T.logs, day: T.today('ja') }};
    """)
    out = got["out"]
    assert out["english"] == {} and out["subtitles"] == {}
    assert out["held"] == 30000
    assert out["text"]["byText"] == "ja" and out["text"]["held"] == 0 and out["text"]["owed"] == {"ja": 40000}
    assert out["title"] == {"ja": 20000}
    assert got["day"]["listenedMs"] == 40000 + 20000
    assert any("not counted: its audio track is in a language you do not learn" in line for line in got["logs"]), got["logs"]
    assert any("not counted: its subtitles are in a language you do not learn" in line for line in got["logs"]), got["logs"]
    assert not any("Film" in line or "episode" in line or "君の名" in line for line in got["logs"]), "no title in the log"


def test_two_films_at_once_are_one_minute_lived(page):
    got = run(page, """
        const P = T.make();
        const a = { key: 'p', subLang: 'jpn' }, b = { key: 'q', subLang: 'jpn' }, c = { key: 'r', subLang: 'eng' };
        const look = (player, i, alang = 'jpn') => P.clock(player, { t: 'clock', at: 100 + i, pos: i, play: true, sound: true, title: player.key + '.mkv', alang });
        // An English film first, then a Japanese one heard: the English one hides nothing.
        await look(c, 0, 'eng'); await look(a, 0);
        for (let i = 1; i <= 10; i++) { await look(c, i, 'eng'); await look(a, i); T.advance(1000); }
        // A second Japanese film starts while the first plays: the first is counted, not both.
        await look(b, 0);
        for (let i = 11; i <= 20; i++) { await look(a, i); await look(b, i - 10); T.advance(1000); }
        const both = P.peek().films.map((f) => [f.key, f.owed.ja || 0]);
        // The first stops: the second is counted from then on.
        T.advance(3000);
        for (let i = 11; i <= 20; i++) { await look(b, i); T.advance(1000); }
        return { both, after: P.peek().films.map((f) => [f.key, f.owed.ja || 0]) };
    """)
    assert dict(got["both"]) == {"r": 0, "p": 20000, "q": 0}
    assert dict(got["after"])["q"] == 10000


def test_subtitle_lines_half_played_are_subtitle_words_once(page):
    got = run(page, """
        const P = T.make();
        const mpv = { key: 'e', subLang: 'jpn' };
        const L = { id: 'ja' };
        const look = (at, pos, play = true) => P.clock(mpv, { t: 'clock', at, pos, play, sound: play, title: 'x.mkv', alang: 'jpn' });
        const text = '今日はいい天気ですね';
        await look(100, 9.5);
        await P.line(mpv, 'mpv', L, text, T.words(text, ['今日', 'は', 'いい', '天気', 'です', 'ね']), { start: 10, end: 12 });
        await look(101, 10.5);
        const quarter = P.peek().films[0].cc;
        await look(102, 11.5);
        const half = P.peek().films[0].cc;
        // Back to before it, and heard again: listening again, not more reading.
        await look(103, 30);
        await look(104, 9.5, true);
        await look(105, 10.5);
        await look(106, 11.5);
        await look(107, 12.5);
        // A line only a little of which played before a seek away.
        const other = '明日は雨です';
        await P.line(mpv, 'mpv', L, other, T.words(other, ['明日', 'は', '雨', 'です']), { start: 13, end: 17 });
        await look(108, 13.5);
        await look(109, 60);
        await look(110, 61);
        const after = P.peek().films[0].cc;
        await P.gone('e');
        return { quarter, half, after, day: T.today('ja') };
    """)
    assert got["quarter"] == {}
    assert got["half"] == {"ja": 6}
    assert got["after"] == {"ja": 6}
    assert got["day"]["cc"] == 6 and not got["day"].get("read")


# ---------------------------------------------------------------- a game, and the worker

def test_half_of_the_time_a_game_is_played_is_listening_while_its_text_is_in_your_language(page):
    got = run(page, LINE + BAR + """
        const P = T.make();
        // No text of the game's read yet: nothing.
        P.played(bar, { ms: 60000 });
        const before = P.peek().readers.length;
        await P.line(bar, 'bar', L, text, w);
        P.played(bar, { ms: 60000 });
        P.played(bar, { ms: 60000 });
        T.advance(61000); P.tick(); await T.settle();
        const day = T.today('ja');
        // Half an hour later, nothing of the game's in Japanese read since: not counted.
        T.advance(31 * 60000);
        P.played(bar, { ms: 60000 });
        const late = P.peek().readers[0].heardMs;
        return { before, day, late, sent: T.sent.filter((m) => m.type === T.MSG.LISTEN_NARRATED) };
    """)
    assert got["before"] == 0
    assert got["day"]["listenedMs"] == 60000
    assert [m["ms"] for m in got["sent"]] == [60000]
    assert got["late"] == 0


def test_a_write_that_fails_is_offered_again_and_never_counted_twice(page):
    got = run(page, LINE + BAR + """
        const P = T.make();
        await P.line(bar, 'bar', L, text, w);
        T.advance(10000);
        T.worker = 'down';
        T.advance(30000); P.tick(); await T.settle();
        const down = { day: T.today('ja'), owed: P.peek().readers[0].owed };
        T.worker = 'refuse';
        T.advance(30000); P.tick(); await T.settle();
        T.worker = 'sluka';
        T.advance(30000); P.tick(); await T.settle();
        T.advance(30000); P.tick(); await T.settle();
        return { down, day: T.today('ja') };
    """)
    assert not got["down"]["day"].get("read") and got["down"]["owed"] == 6
    assert got["day"]["read"] == 6


def test_a_sluka_whose_worker_does_not_know_the_message_is_written_to_directly(page):
    got = run(page, LINE + BAR + """
        T.worker = 'old';
        const P = T.make();
        await P.line(bar, 'bar', L, text, w);
        T.advance(10000);
        await P.gone('bar');
        const mpv = { key: 'f', subLang: 'jpn' };
        for (let i = 0; i <= 10; i++) await P.clock(mpv, { t: 'clock', at: 100 + i, pos: i, play: true, sound: true, title: 'A film.mp4', alang: 'jpn' });
        await P.gone('f');
        return { day: T.today('ja'), rows: T.store[T.KEY.listenRecent] };
    """)
    assert got["day"]["read"] == 6 and got["day"]["listenedMs"] == 10000
    assert got["rows"][0]["title"] == "A film"


def test_what_is_owed_goes_out_with_the_page(page):
    got = run(page, LINE + BAR + """
        const P = T.make();
        await P.line(bar, 'bar', L, text, w);
        T.advance(10000);
        const mpv = { key: 'g', subLang: 'jpn' };
        for (let i = 0; i <= 5; i++) await P.clock(mpv, { t: 'clock', at: 100 + i, pos: i, play: true, sound: true, title: 'B.mkv', alang: 'jpn' });
        P.out();
        await T.settle();
        return { day: T.today('ja'), sent: T.sent.map((m) => m.type).sort() };
    """)
    assert got["day"]["read"] == 6 and got["day"]["listenedMs"] == 5000
    assert got["sent"] == ["listenLocalVideo", "readWords"]


# ---------------------------------------------------------------- the engine's list of Sluka's modules

def test_every_module_and_name_the_engine_asks_for_is_in_this_sluka(page):
    engine = (WEB / "mpv-engine.js").read_text(encoding="utf-8")
    match = re.search(r"const TRACKS = (\{.*?\n\});", engine, re.S)
    assert match, "the engine's TRACKS list"
    got = page.evaluate("""async (source) => {
        const tracks = Function(`return (${source})`)();
        const lacking = [];
        for (const [path, names] of Object.entries(tracks)) {
          const mod = await import('/ext' + path);
          for (const name of names) if (!(name in mod)) lacking.push(`${name} (${path})`);
        }
        const { MSG, KEY } = await import('/ext/lib/constants.js');
        for (const name of ['READ_WORDS', 'LISTEN_LOCAL_VIDEO', 'LISTEN_NARRATED']) if (!MSG[name]) lacking.push('MSG.' + name);
        for (const name of ['listenRecent', 'listenHistory']) if (!KEY[name]) lacking.push('KEY.' + name);
        const languages = await import('/ext/lib/languages.js');
        if (typeof languages.strongestLanguage !== 'function') lacking.push('strongestLanguage');
        return lacking;
    }""", match.group(1).rstrip(";"))
    assert got == []
