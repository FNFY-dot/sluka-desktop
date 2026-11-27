"""Your own dictionaries and the AI check in the engine that answers mpv, the floating subtitles and Sluka Vision
(web/mpv-engine.js withOwnDicts, askTool, askAi): the meanings of the dictionaries you added to Sluka, drawn as
Sluka's own panel draws them, and the panel's ✦, which sends the word and its sentence to the AI check that
Settings → AI check sets up -- your own request there answered too -- run in a real Chromium against the Sluka
extension's own modules (its renderer, its settings, its providers), with a stand-in for its worker.

Skipped where there is no Chrome and Playwright, or no Sluka extension whole (SLUKA_EXTENSION_FULL).
"""

from __future__ import annotations

import functools
import http.server
import json
import threading

import pytest

import test_engine_anki as base

playwright = base.playwright

PAGE = (
    base.PAGE
    .replace("const S = { T:", "const S = { KEY, T:")
    .replace(
        "      if (msg.type === 'speechStatus') return { ok: true, installed: null };",
        "      if (msg.type === 'speechStatus') return { ok: true, installed: null };\n"
        "      if (msg.type === 'ownLookup') return globalThis.__own || { ok: true, dicts: [] };\n"
        "      if (msg.type === 'verifyWord') return globalThis.__verdict || { ok: false, error: 'nothing here' };",
    )
    .replace("globalThis.__engine = { headTools,",
             "globalThis.__engine = { withOwnDicts, askAi, askTool, aiThere, askLookKey, S, headTools,")
)
assert "withOwnDicts, askAi" in PAGE and "ownLookup" in PAGE and "{ KEY, T:" in PAGE


class Site(base.Site):
    def do_GET(self):  # noqa: N802
        if self.path.split("?", 1)[0] == "/test.html":
            return self._send(PAGE.replace("/*ENGINE*/", base.engine_part()).encode("utf-8"), "text/html; charset=utf-8")
        return super().do_GET()


SETTINGS = {**base.SETTINGS, "ai": {"enabled": True, "provider": "anthropic", "sendSentence": True}}


@pytest.fixture(scope="module")
def page():
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(Site))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    with playwright.sync_playwright() as p:
        chrome = p.chromium.launch(executable_path=base.CHROME, args=["--no-sandbox"])
        tab = chrome.new_page()
        tab.add_init_script(f"globalThis.__settings = {json.dumps(SETTINGS)};")
        tab.goto(f"http://127.0.0.1:{server.server_port}/test.html")
        tab.wait_for_function("() => globalThis.__ready || globalThis.__errors", timeout=20000)
        assert tab.evaluate("() => globalThis.__errors || null") is None
        yield tab
        chrome.close()
    server.shutdown()


def settings(page, **changes):
    page.evaluate("(s) => globalThis.__engine.setSettings(s)", {**SETTINGS, **changes})


JITENDEX = {"ok": True, "dicts": [{
    "id": "od-abc-1", "title": "Jitendex", "tags": {}, "css": ".x { color: red }",
    "hits": [{"h": "運命", "r": "うんめい", "d": ["fate; destiny", "one's lot"]},
             {"h": "運命", "d": [{"c": {"t": "a", "h": "https://jitendex.org/x", "c": "see the site"}}]}],
}]}


def own(page, entry, html=True):
    return page.evaluate("""async ([entry, html]) => {
      await globalThis.__engine.withOwnDicts(entry, globalThis.__engine.L, '運命', '運命', html);
      return entry;
    }""", [entry, html])


def test_your_own_dictionaries_in_the_panel(page):
    settings(page)
    page.evaluate("(own) => { globalThis.__own = own; globalThis.__asked.length = 0; }", JITENDEX)
    # Settings → Dictionary: none of yours for Japanese yet -- the worker is not even asked.
    got = own(page, {"lead": "Sluka's", "more": [], "none": "", "senses": ["Sluka's"]})
    assert "own" not in got and got["lead"] == "Sluka's"
    assert not any(m["type"] == "ownLookup" for m in page.evaluate("() => globalThis.__asked"))

    page.evaluate("() => globalThis.__setStore('ownDicts:ja', { on: true })")
    got = own(page, {"lead": "Sluka's", "more": [], "none": "No entry in the dictionary.", "senses": ["Sluka's"]})
    ask = next(m for m in page.evaluate("() => globalThis.__asked") if m["type"] == "ownLookup")
    assert ask["lang"] == "ja" and "運命" in ask["words"]
    # Instead of Sluka's meanings, the default: the small card says yours, and "no entry" is not said.
    assert got["own"]["place"] == "replace"
    assert got["own"]["dicts"][0]["title"] == "Jitendex"
    assert got["own"]["dicts"][0]["hits"][0] == {"head": "運命", "reading": "うんめい", "senses": ["fate; destiny", "one's lot"]}
    assert got["lead"] == "fate; destiny" and got["more"] == ["one's lot"] and got["none"] == ""
    # For the pages, as the extension draws them, the dictionary's own sheet held inside its block.
    assert 'class="reading-group rg-dict" data-dict="od-abc-1"' in got["own"]["html"]
    assert 'href="https://jitendex.org/x" data-link' in got["own"]["html"]
    assert got["own"]["css"].startswith('.rg-dict[data-dict="od-abc-1"] .od-sc')

    # Under Sluka's, as Settings → Dictionary may say: Sluka's small card as it was.
    settings(page, ownDictPlace={"ja": "below"})
    got = own(page, {"lead": "Sluka's", "more": [], "none": "", "senses": ["Sluka's"]})
    assert got["own"]["place"] == "below" and got["lead"] == "Sluka's"
    # For mpv, text alone.
    got = own(page, {"lead": "Sluka's", "more": [], "none": "", "senses": []}, html=False)
    assert "html" not in got["own"] and got["own"]["dicts"][0]["hits"][1]["senses"] == ["see the site"]
    # None of yours has the word: as it was.
    page.evaluate("() => { globalThis.__own = { ok: true, dicts: [{ id: 'od-2', title: 'Empty', hits: [] }] }; }")
    got = own(page, {"lead": "Sluka's", "more": [], "none": "", "senses": []})
    assert "own" not in got
    page.evaluate("() => globalThis.__setStore('ownDicts:ja', { on: false })")
    settings(page)


def test_the_ai_check_offered_as_the_panel_offers_it(page):
    settings(page, ai={"enabled": False})
    assert page.evaluate("() => globalThis.__engine.aiThere()") is False
    assert page.evaluate("() => globalThis.__engine.askLookKey()") == ""
    settings(page)
    assert page.evaluate("() => globalThis.__engine.aiThere()") is True
    # F, Settings → Keyboard's key for it.
    assert page.evaluate("() => globalThis.__engine.askLookKey()") == "f"
    tool = page.evaluate("() => globalThis.__engine.askTool(globalThis.__engine.L, '運命', {})")
    # The dictionary has the word: a second opinion, a quiet key in the head, with what pressing it sends.
    assert tool["wanted"] is False
    assert tool["title"] == "Ask AI to double-check. (F) Sends this word and its sentence to Anthropic."
    assert tool["label"] == "Ask AI if this is a real word (F)" and tool["wait"] == "Checking…"
    # Nothing of Sluka's nor yours: the button, in the meanings.
    page.evaluate("() => { globalThis.__lookup = globalThis.__engine.S.lookupBatch; globalThis.__engine.S.lookupBatch = async () => ({}); }")
    try:
        assert page.evaluate("() => globalThis.__engine.askTool(globalThis.__engine.L, '運命', {})")["wanted"] is True
        assert page.evaluate("() => globalThis.__engine.askTool(globalThis.__engine.L, '運命', { own: { dicts: [1] } })")["wanted"] is False
    finally:
        page.evaluate("() => { globalThis.__engine.S.lookupBatch = globalThis.__lookup; }")
    # A key that grades is not taken for it.
    settings(page, keys={**SETTINGS["keys"], "askWord": "k"})
    assert page.evaluate("() => globalThis.__engine.askLookKey()") == ""
    settings(page)


ANSWER = {"ok": True, "result": {
    "verdict": "established", "confidence": "high", "reading": "うんめい", "meaning": "fate, destiny",
    "gloss": "fate", "example": "運命の人に出会った。", "exampleTranslation": "I met the one.", "register": "neutral",
    "breakdown": "", "explanation": "A common word.", "ownAnswer": "Here, 運命 is the fate he meets.\nIn general, fate.",
}}


def ask(page, **m):
    page.evaluate("() => { globalThis.__asked.length = 0; globalThis.__said.length = 0; }")
    page.evaluate("(m) => globalThis.__engine.askAi(globalThis.__engine.players.get('bar'), m)",
                  {"t": "ask", "id": 3, "tok": 2, "key": "運命", "text": "運命", **m})
    return page.evaluate("() => globalThis.__asked"), [m for k, m in page.evaluate("() => globalThis.__said") if k == "bar"]


def test_asking_the_ai_check_about_the_word_in_its_sentence(page):
    settings(page)
    base.put_player(page)
    page.evaluate("(a) => { globalThis.__verdict = a; }", ANSWER)
    asked, said = ask(page)
    check = next(m for m in asked if m["type"] == "verifyWord")
    # The word, the sentence it stands in (Settings → AI check sends it, where it says so), its language.
    assert check == {"type": "verifyWord", "word": "運命", "sentence": "俺は運命と出会い。", "language": "ja"}
    assert said[0] == {"t": "verdict", "id": 3, "tok": 2, "status": "loading", "label": "Checking…"}
    done = said[1]
    assert done["status"] == "done" and done["result"]["verdict"] == "established"
    assert done["result"]["ownAnswer"].startswith("Here, 運命 is the fate he meets.")
    assert done["labels"]["tag"] == "Real word" and done["labels"]["confidence"] == "high confidence"
    assert done["labels"]["own"] == "Your question" and done["labels"]["breakdown"] == "Actually"
    # What the worker says went wrong, said in the panel.
    page.evaluate("() => { globalThis.__verdict = { ok: false, error: 'The AI check is turned off in Settings.' }; }")
    _asked, said = ask(page)
    assert said[-1] == {"t": "verdict", "id": 3, "tok": 2, "status": "error", "error": "The AI check is turned off in Settings."}
    # With the check off, nothing is sent at all.
    settings(page, ai={"enabled": False})
    asked, said = ask(page)
    assert not asked and not said
    settings(page)
