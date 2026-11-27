"""The Anki part of the engine that answers mpv, the floating subtitles and Sluka Vision (web/mpv-engine.js): the
panel's Anki key as a page's panel has it, a word picked with its sentence, and a game's clip and picture made into
the files the extension puts on its cards -- run in a real Chromium against the Sluka extension's own modules (its
Anki settings, its sentence cutter, its clip encoder), with a stand-in for its worker and for the app.

The engine's Anki part is taken from mpv-engine.js as it is, between its markers.  Skipped where there is no Chrome
and Playwright, or no Sluka extension whole (SLUKA_EXTENSION_FULL: its unpacked folder, offscreen/ included).
"""

from __future__ import annotations

import base64
import functools
import http.server
import json
import math
import os
import shutil
import struct
import threading
from pathlib import Path

import pytest

from fakes import APP as APP_PATH  # noqa: F401  (puts the app on the path)
from sluka_desktop import gamepicture, gamesound

APP = Path(os.environ.get("SLUKA_APP", "/home/claude/work/sluka-desktop/app"))
ENGINE = APP / "web" / "mpv-engine.js"
EXTENSION = Path(os.environ.get("SLUKA_EXTENSION_FULL", "/home/claude/untrusted/sluka-ext-0.7.4-full/sluka-extension"))
CHROME = shutil.which("google-chrome") or shutil.which("chromium")

playwright = pytest.importorskip("playwright.sync_api")
if not CHROME:
    pytest.skip("no Chrome here", allow_module_level=True)
if not (EXTENSION / "lib" / "anki-icon.js").is_file() or not (EXTENSION / "offscreen" / "m4a.js").is_file():
    pytest.skip("no Sluka extension with Anki cards to try it with", allow_module_level=True)

START = "// ------------------------------------------------------------ Anki"
END = "// ------------------------------------------------------------ the questions, as they come"


def engine_part() -> str:
    text = ENGINE.read_text(encoding="utf-8")
    part = text[text.index(START):text.index(END)]
    for root in ("lib", "content", "offscreen"):
        part = part.replace(f"'/{root}/", f"'/ext/{root}/")
    return part


PAGE = """<!doctype html><meta charset="utf-8"><title>anki</title><body>
<script type="module">
const store = {};
const heard = [];
const asked = (globalThis.__asked = []);
const said = (globalThis.__said = []);
const calls = (globalThis.__calls = []);
const graded = (globalThis.__graded = []);
globalThis.chrome = {
  storage: {
    local: {
      get: async (keys) => Object.fromEntries([].concat(keys).filter((k) => k in store).map((k) => [k, structuredClone(store[k])])),
      set: async (items) => {
        const changes = {};
        for (const [k, v] of Object.entries(items)) { changes[k] = { newValue: v }; store[k] = structuredClone(v); }
        for (const f of heard) f(changes, 'local');
      },
    },
    onChanged: { addListener: (f) => heard.push(f) },
  },
  runtime: {
    sendMessage: async (msg) => {
      asked.push(structuredClone(msg));
      if (msg.type === 'ankiPick') {
        // The worker puts it on the list of picks (lib/anki.js pickWord)...
        await chrome.storage.local.set({ [`ankiPicked:${msg.lang}`]: { [msg.word]: { at: 1 } } });
        return { ok: true, queued: true };
      }
      if (msg.type === 'ankiBrowse') return { ok: true, found: true };
      if (msg.type === 'translate') return { ok: true, text: 'Fate', alternatives: [{ pos: 'noun', terms: ['Fate', 'destiny'] }] };
      if (msg.type === 'translateSay') return globalThis.__google || { ok: false, error: 'no voice here' };
      if (msg.type === 'ttsSpeak') return globalThis.__cloud || { ok: false, error: 'The cloud voice is out of quota.', code: 'quota' };
      if (msg.type === 'speechStatus') return { ok: true, installed: null };
      return { ok: true };
    },
  },
};
globalThis.__store = store;
globalThis.__setStore = (k, v) => chrome.storage.local.set({ [k]: v });
const { KEY, STATUS } = await import('/ext/lib/constants.js');
const { COUNTING } = await import('/ext/lib/counting.js');
let settings = globalThis.__settings;
const S = { T: (text, vars) => String(text).replace(/\\{(\\w+)\\}/g, (_, k) => vars?.[k] ?? ''), surfaceKey: (_lang, text) => text,
  lookupBatch: async (words) => Object.fromEntries(words.map((w) => [w, { reading: 'うんめい' }])), pronunciationOf: (e) => e?.reading || '' };
const lookupKey = (_L, key) => key;
const players = new Map();
const report = (err) => { (globalThis.__errors ||= []).push(String(err?.stack || err)); };
let progress = null;
const tracked = async (fn) => fn();
const pickLanguage = () => 'ja';
const gradeKeys = () => ({ 1: '1', 2: '2', 3: '3', 4: '4', 5: 'k', 6: 'x', 0: '0' });
const pairOf = (L, key) => ({});
const L = { id: 'ja', mode: COUNTING.LEMMA, lang: {}, vocab: { get: (k) => (graded.includes(k) ? STATUS.L1 : STATUS.NEW) } };
const language = async () => L;
async function grade(player, m) { graded.push(m.key); }
function send(player, msg) { said.push([player.key, structuredClone(msg)]); return Promise.resolve(); }
async function api(name, body) {
  calls.push([name, structuredClone(body)]);
  if (name === 'cards/lines') return globalThis.__lines;
  if (name === 'cards/media') return globalThis.__media;
  if (name === 'mpv/shot') return globalThis.__shot;
  if (name === 'dict/installed') return { ok: true, installed: ['jmdict-ja'] };
  return { ok: true };
}
/*ENGINE*/
globalThis.__engine = { headTools, translateWord, lookUp, speakWord, sayLookKey, speakerThere, ankiStateOf, ankiNote, cardSentenceOf, withLines, anki, players, wavSamples, L, setSettings: (s) => { settings = s; }, A };
globalThis.__ready = true;
</script>
"""

SETTINGS = {
    "anki": {"pick": True, "send": False, "again": "update", "decks": {}, "pickDecks": {}, "back": {"source": True},
             "media": {"audio": True, "picture": True, "context": False, "video": False}, "models": {}, "langs": {}},
    "keys": {"ankiPick": "p"},
}


def film_sound(seconds=6.0):
    rate = 24000
    n = int(seconds * rate)
    pcm = struct.pack(f"<{n}h", *(int(9000 * math.sin(2 * math.pi * 220 * i / rate)) if 2.5 * rate <= i < 4 * rate else 0
                                   for i in range(n)))
    return gamesound.wav(pcm, rate)


FILM = film_sound()


class Site(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):  # noqa: N802
        path = self.path.split("?", 1)[0]
        if path == "/test.html":
            body = PAGE.replace("/*ENGINE*/", engine_part()).encode("utf-8")
            return self._send(body, "text/html; charset=utf-8")
        if path == "/__sluka__/api/mpv/file":
            # The film's file, a range at a time, as the app serves it (mpvbridge.py _file): here a sound file.
            data = FILM
            rng = self.headers.get("Range", "")
            start, end = 0, len(data) - 1
            if rng.startswith("bytes="):
                a, _, b = rng[6:].partition("-")
                start, end = int(a or 0), min(int(b) if b else len(data) - 1, len(data) - 1)
            self.send_response(206 if rng else 200)
            self.send_header("Content-Type", "application/octet-stream")
            self.send_header("Content-Range", f"bytes {start}-{end}/{len(data)}")
            self.send_header("Content-Length", str(end - start + 1))
            self.end_headers()
            self.wfile.write(data[start:end + 1])
            return
        if path.startswith("/ext/"):
            file = EXTENSION / path[len("/ext/"):]
            if file.is_file():
                return self._send(file.read_bytes(), "text/javascript" if file.suffix in (".js", ".mjs") else "application/json")
        self.send_error(404)

    def _send(self, body: bytes, kind: str):
        self.send_response(200)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


@pytest.fixture(scope="module")
def page():
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(Site))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    with playwright.sync_playwright() as p:
        chrome = p.chromium.launch(executable_path=CHROME, args=["--no-sandbox"])
        tab = chrome.new_page()
        tab.add_init_script(f"globalThis.__settings = {json.dumps(SETTINGS)};")
        tab.goto(f"http://127.0.0.1:{server.server_port}/test.html")
        tab.wait_for_function("() => globalThis.__ready || globalThis.__errors", timeout=20000)
        assert tab.evaluate("() => globalThis.__errors || null") is None
        yield tab
        chrome.close()
    server.shutdown()


LINE = "ある春の日。俺は運命と出会い。"


def put_player(page, text=LINE):
    word = text.index("運命")
    page.evaluate("""([text, a]) => {
      const L = globalThis.__engine.L;
      globalThis.__engine.players.set('bar', { key: 'bar', line: { id: 3, text, lang: 'ja',
        toks: [{ s: 0, e: 6, key: '春', st: 0 }, { s: 1, e: 2, key: '運命', st: 0 }],
        extra: [{ a: text.indexOf('春'), b: text.indexOf('春') + 1 }, { a, b: a + 2 }] } });
    }""", [text, word])


def test_the_sentence_a_word_stands_in(page):
    got = page.evaluate("([t, a]) => globalThis.__engine.cardSentenceOf(globalThis.__engine.L, t, a, a + 2)", [LINE, LINE.index("運命")])
    assert got == {"t": "俺は運命と出会い。", "a": 2, "l": 2}
    # A paragraph is a block no sentence crosses (Sluka Vision's reads).
    text = "名前\n俺は運命と出会い"
    got = page.evaluate("([t, a]) => globalThis.__engine.cardSentenceOf(globalThis.__engine.L, t, a, a + 2)", [text, text.index("運命")])
    assert got["t"] == "俺は運命と出会い" and got["a"] == 2
    # With the lines either side (Settings → Anki, "With the sentence before and after").
    got = page.evaluate("() => globalThis.__engine.withLines({ t: '俺は運命と出会い', a: 2, l: 2 }, ['ある春の日'], ['そして'])")
    assert got == {"t": "ある春の日俺は運命と出会いそして", "a": 7, "l": 2}
    got = page.evaluate("() => globalThis.__engine.withLines({ t: 'met fate', a: 4, l: 4 }, ['One spring day,'], [])")
    assert got == {"t": "One spring day, met fate", "a": 20, "l": 4}


def test_the_panels_anki_key_as_a_page_has_it(page):
    note = page.evaluate("() => globalThis.__engine.ankiNote(globalThis.__engine.L, '運命', '運命')")
    assert note["state"] == "add" and note["key"] == "p"
    assert note["title"] == "Add to Anki, into Sluka::Japanese (P)" and note["icon"].startswith("<svg")
    page.evaluate("() => globalThis.__setStore('ankiSent:ja', { '運命': { n: 1700000000000 } })")
    assert page.evaluate("() => globalThis.__engine.ankiStateOf('ja', '運命')")["state"] == "in"
    page.evaluate("() => globalThis.__setStore('ankiSent:ja', {})")
    # Settings → Anki's panel button off: no key.
    off = json.loads(json.dumps(SETTINGS))
    off["anki"]["pick"] = False
    page.evaluate("(s) => globalThis.__engine.setSettings(s)", off)
    assert page.evaluate("() => globalThis.__engine.ankiNote(globalThis.__engine.L, '運命', '運命')") is None
    page.evaluate("(s) => globalThis.__engine.setSettings(s)", SETTINGS)


def tone_wav(seconds=0.5):
    n = int(seconds * gamesound.RATE)
    pcm = struct.pack(f"<{n}h", *(int(9000 * math.sin(2 * math.pi * 220 * i / gamesound.RATE)) for i in range(n)))
    return base64.b64encode(gamesound.wav(pcm)).decode("ascii")


def picture_bmp(w=80, h=45):
    stride = (w * 3 + 3) & ~3
    rows = b"".join(bytes([(x * 3) % 256, 90, 200] * 1)[:3] * 1 for x in range(w))
    rows = b"".join((bytes(sum(([(x * 3) % 256, 90, (y * 5) % 256] for x in range(w)), [])) + bytes(stride - w * 3)) for y in range(h))
    return base64.b64encode(gamepicture.bmp(w, h, rows)).decode("ascii")


def test_a_game_word_picked_goes_to_anki_with_its_sound_and_picture(page):
    put_player(page)
    page.evaluate("""([wav, bmp]) => {
      globalThis.__lines = { ok: true, found: true, ticket: 'c1', sound: true, picture: true, title: '桜の詩', before: ['前の行'], after: [] };
      globalThis.__media = { ok: true, audio: { wav, rate: 24000, seconds: 0.5 }, picture: { bmp } };
      globalThis.__asked.length = 0; globalThis.__said.length = 0; globalThis.__calls.length = 0;
    }""", [tone_wav(), picture_bmp()])
    page.evaluate("() => globalThis.__engine.anki(globalThis.__engine.players.get('bar'), { t: 'anki', id: 3, tok: 2, key: '運命', text: '運命' })")
    page.wait_for_function("() => globalThis.__asked.some((m) => m.type === 'ankiMedia')", timeout=15000)
    asked = page.evaluate("() => globalThis.__asked")
    pick = next(m for m in asked if m["type"] == "ankiPick")
    # Its sentence, its form, where it was met; the clip is on its way (the voice leaves the sentence to it).
    assert pick["word"] == "運命" and pick["lang"] == "ja" and pick["clip"] is True
    assert pick["sentence"]["t"] == "俺は運命と出会い。" and pick["sentence"]["a"] == 2 and pick["sentence"]["l"] == 2
    assert pick["sentence"]["src"] == {"n": "桜の詩"} and pick["noteType"] == "" and pick["deck"] == ""
    # A blue word is filed at level 1 on the way, as a page's pick files it.
    assert "運命" in page.evaluate("() => globalThis.__graded")
    # The picture asked for as it was picked; the clip and the picture made into the extension's own files.
    calls = page.evaluate("() => globalThis.__calls")
    assert calls[0] == ["cards/lines", {"player": "bar", "text": LINE, "picture": True}]
    assert calls[1] == ["cards/media", {"ticket": "c1", "audio": True, "picture": True, "context": False}]
    media = next(m for m in asked if m["type"] == "ankiMedia")
    assert media["word"] == "運命" and media["audio"]["ext"] in ("m4a", "wav") and media["picture"]["ext"] == "jpg"
    audio = base64.b64decode(media["audio"]["b64"])
    assert audio[4:8] == b"ftyp" if media["audio"]["ext"] == "m4a" else audio[:4] == b"RIFF"
    jpeg = base64.b64decode(media["picture"]["b64"])
    assert jpeg[:3] == b"\xff\xd8\xff"
    # The player told: being added, and the open panel's key waiting for Anki.
    said = page.evaluate("() => globalThis.__said")
    assert any(m["t"] == "say" and "Adding 運命 to Anki" in m["text"] for _k, m in said)


def test_with_the_lines_either_side_and_with_video_chosen(page):
    put_player(page)
    settings = json.loads(json.dumps(SETTINGS))
    settings["anki"]["media"] = {"audio": True, "picture": True, "context": True, "video": True}
    page.evaluate("(s) => globalThis.__engine.setSettings(s)", settings)
    page.evaluate("""([wav, bmp]) => {
      globalThis.__lines = { ok: true, found: true, ticket: 'c2', sound: true, picture: true, title: '桜の詩', before: ['前の行'], after: ['次の行'] };
      globalThis.__media = { ok: true, audio: { wav, rate: 24000 }, picture: { bmp } };
      globalThis.__asked.length = 0; globalThis.__calls.length = 0;
    }""", [tone_wav(), picture_bmp()])
    page.evaluate("() => globalThis.__engine.anki(globalThis.__engine.players.get('bar'), { t: 'anki', id: 3, tok: 2, key: '運命', text: '運命' })")
    page.wait_for_function("() => globalThis.__asked.some((m) => m.type === 'ankiMedia')", timeout=15000)
    asked = page.evaluate("() => globalThis.__asked")
    pick = next(m for m in asked if m["type"] == "ankiPick")
    assert pick["sentence"]["t"] == "前の行俺は運命と出会い。次の行" and pick["sentence"]["a"] == 5
    calls = page.evaluate("() => globalThis.__calls")
    # A video cannot be made of a game: the picture goes instead, as the extension puts one where a video cannot be made.
    assert calls[1] == ["cards/media", {"ticket": "c2", "audio": True, "picture": True, "context": True}]
    media = next(m for m in asked if m["type"] == "ankiMedia")
    assert media["picture"]["ext"] == "jpg" and "video" not in media
    page.evaluate("(s) => globalThis.__engine.setSettings(s)", SETTINGS)
    assert page.evaluate("() => globalThis.__errors || null") is None


def test_a_word_picked_in_mpv_gets_its_lines_clip_and_the_frame(page):
    """The film's own sound, read out of its file a range at a time (the extension's offscreen/file-clip.js, through
    the app's mpv/file), padded as SlukaCC pads a subtitle (lib/clip-range.js); the frame the script took."""
    page.evaluate("""([text, bmp]) => {
      const a = text.indexOf('運命');
      globalThis.__engine.players.set('mpv:1', { key: 'mpv:1', line: { id: 2, text, lang: 'ja',
        toks: [{ s: 0, e: 3, key: '春', st: 0 }, { s: 1, e: 2, key: '運命', st: 0 }],
        extra: [{ a: text.indexOf('春'), b: text.indexOf('春') + 1 }, { a, b: a + 2 }] },
        history: [{ id: 1, text: '前の行', start: 1.0, end: 2.0 }, { id: 2, text, start: 2.5, end: 4.0 }] });
      globalThis.__shot = { ok: true, b64: bmp };
      globalThis.__asked.length = 0; globalThis.__calls.length = 0;
    }""", [LINE, picture_bmp()])
    assert page.evaluate("() => Object.keys(globalThis.__engine.A).includes('openFileClip')")
    page.evaluate("""() => globalThis.__engine.anki(globalThis.__engine.players.get('mpv:1'),
      { t: 'anki', id: 2, tok: 2, key: '運命', text: '運命', start: 2.5, end: 4.0, title: 'A film', shot: 'sluka-shot-1-1.jpg' })""")
    page.wait_for_function("() => globalThis.__asked.some((m) => m.type === 'ankiMedia')", timeout=20000)
    asked = page.evaluate("() => globalThis.__asked")
    pick = next(m for m in asked if m["type"] == "ankiPick")
    assert pick["clip"] is True and pick["sentence"]["src"] == {"n": "A film", "s": 2}
    media = next(m for m in asked if m["type"] == "ankiMedia")
    assert media["picture"]["ext"] == "jpg" and base64.b64decode(media["picture"]["b64"])[:3] == b"\xff\xd8\xff"
    audio = base64.b64decode(media["audio"]["b64"])
    assert media["audio"]["ext"] in ("m4a", "wav")
    if media["audio"]["ext"] == "wav":
        # From a quarter second before the line to a little after it, as SlukaCC cuts a subtitle's.
        seconds = (len(audio) - 44) / 2 / 24000
        assert abs(seconds - (1.5 + 0.25 + 0.45)) < 0.05
    calls = page.evaluate("() => globalThis.__calls")
    assert ["mpv/shot", {"name": "sluka-shot-1-1.jpg"}] in calls
    assert page.evaluate("() => globalThis.__errors || null") is None


def test_the_heads_translate_and_look_up_keys(page):
    """Translate as a page asks it (MSG.TRANSLATE, from the language into Settings' own); Look up's sites as Settings
    lists them for the language (lib/dict-links.js), each in a Sluka window, and beside the free ones their
    dictionary offline -- installed or not, as the app says."""
    put_player(page)
    tools = page.evaluate("() => globalThis.__engine.headTools(globalThis.__engine.L)")
    assert tools["translate"]["icon"].startswith("<svg") and tools["look"]["icon"].startswith("<svg")
    links = {l["id"]: l for l in tools["look"]["links"]}
    assert links["jisho"]["offline"] == "jmdict" and links["jisho"]["installed"] is True
    if "wiktionary" in links:
        assert links["wiktionary"]["offline"] == "wiktionary" and links["wiktionary"]["installed"] is False
    assert all("offline" not in l for i, l in links.items() if i not in ("jisho", "wiktionary"))
    page.evaluate("() => { globalThis.__said.length = 0; globalThis.__asked.length = 0; globalThis.__calls.length = 0; }")
    page.evaluate("() => globalThis.__engine.translateWord(globalThis.__engine.players.get('bar'), { t: 'translate', id: 3, tok: 2, key: '運命', text: '運命' })")
    asked = page.evaluate("() => globalThis.__asked")
    assert asked[0]["type"] == "translate" and asked[0]["text"] == "運命" and asked[0]["from"] == "ja"
    said = [m for _k, m in page.evaluate("() => globalThis.__said")]
    assert said[-1] == {"t": "translation", "id": 3, "tok": 2, "ok": True, "text": "Fate",
                        "alternatives": [{"pos": "noun", "terms": ["destiny"]}], "error": ""}
    page.evaluate("() => globalThis.__engine.lookUp(globalThis.__engine.players.get('bar'), { t: 'look', id: 3, tok: 2, key: '運命', text: '運命', site: 'jisho' })")
    page.evaluate("() => globalThis.__engine.lookUp(globalThis.__engine.players.get('bar'), { t: 'look', id: 3, tok: 2, key: '運命', text: '運命', site: 'jisho', offline: true })")
    opened = [b for n, b in page.evaluate("() => globalThis.__calls") if n == "dict/open"]
    assert opened[0] == {"url": "https://jisho.org/search/%E9%81%8B%E5%91%BD"}
    assert opened[1] == {"url": "/__sluka__/dict.html?d=jmdict&lang=ja&q=%E9%81%8B%E5%91%BD", "offline": True}
    # A site not on the menu opens nothing.
    page.evaluate("() => globalThis.__engine.lookUp(globalThis.__engine.players.get('bar'), { t: 'look', id: 3, tok: 2, key: '運命', text: '運命', site: 'evil' })")
    assert len([1 for n, _b in page.evaluate("() => globalThis.__calls") if n == "dict/open"]) == 2
    assert page.evaluate("() => globalThis.__errors || null") is None


def test_the_panels_speaker_says_the_word_with_googles_voice(page):
    """No cloud voice set up: Google Translate's voice says the word (MSG.TRANSLATE_SAY, as the extension's translation
    box says its texts), lit in the panel while it plays; with a cloud voice that fails, Google's answers before the
    device's."""
    import base64
    put_player(page)
    sound = base64.b64encode(film_sound(0.4)).decode()
    page.evaluate("(b64) => { globalThis.__google = { ok: true, audio: [b64] }; globalThis.__said.length = 0; globalThis.__asked.length = 0; }", sound)
    assert page.evaluate("() => globalThis.__engine.speakerThere()") is True
    assert page.evaluate("() => globalThis.__engine.sayLookKey()") == "v"
    page.evaluate("() => globalThis.__engine.speakWord(globalThis.__engine.players.get('bar'), { t: 'speak', id: 3, tok: 2, key: '運命', text: '運命' })")
    page.wait_for_function("() => globalThis.__said.some(([, m]) => m.t === 'speaking' && m.on === false)", timeout=10000)
    asked = [m for m in page.evaluate("() => globalThis.__asked") if m["type"] in ("translateSay", "ttsSpeak")]
    assert asked == [{"type": "translateSay", "text": "運命", "lang": "ja"}]
    lit = [m for _k, m in page.evaluate("() => globalThis.__said") if m["t"] == "speaking"]
    assert lit[0] == {"t": "speaking", "id": 3, "tok": 2, "on": True} and lit[-1] == {"t": "speaking", "id": 3, "tok": 2, "on": False}
    # A cloud voice set up (Settings → Voice) and out of quota: Google's voice, and no robot.
    page.evaluate("""() => { globalThis.__engine.A.cloudProvider = () => 'gemini'; globalThis.__said.length = 0; globalThis.__asked.length = 0; }""")
    page.evaluate("() => globalThis.__engine.speakWord(globalThis.__engine.players.get('bar'), { t: 'speak', id: 3, tok: 1, key: '春', text: '春' })")
    page.wait_for_function("() => globalThis.__said.some(([, m]) => m.t === 'speaking' && m.on === false)", timeout=10000)
    asked = [m["type"] for m in page.evaluate("() => globalThis.__asked") if m["type"] in ("translateSay", "ttsSpeak")]
    assert asked == ["ttsSpeak", "translateSay"]
    assert page.evaluate("() => globalThis.__errors || null") is None
