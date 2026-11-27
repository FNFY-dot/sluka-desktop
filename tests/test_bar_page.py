"""The floating subtitles' page (web/bar.html) in a real Chromium, with a stand-in for the app and Sluka's engine.

Skipped where there is no Chrome and Playwright to drive it.
"""

from __future__ import annotations

import functools
import http.server
import os
import shutil
import threading
import time
from pathlib import Path

import pytest

APP = Path(os.environ.get("SLUKA_APP", "/home/claude/work/sluka-desktop/app"))
WEB = APP / "web"
STUB = Path(__file__).parent / "web" / "bar-stub.js"
CHROME = shutil.which("google-chrome") or shutil.which("chromium")

playwright = pytest.importorskip("playwright.sync_api")
if not CHROME:
    pytest.skip("no Chrome here", allow_module_level=True)


class Site(http.server.SimpleHTTPRequestHandler):
    """/__sluka__/... from the app's web folder; /test.html is bar.html with the stand-in put before its own scripts."""

    def log_message(self, *args):
        pass

    def do_GET(self):  # noqa: N802
        path = self.path.split("?", 1)[0]
        if path == "/test.html":
            page = (WEB / "bar.html").read_text(encoding="utf-8")
            page = page.replace('<link rel="stylesheet" href="/__sluka__/bar.css">',
                                '<script src="/stub.js"></script><link rel="stylesheet" href="/__sluka__/bar.css">')
            return self._send(page.encode("utf-8"), "text/html; charset=utf-8")
        if path == "/stub.js":
            return self._send(STUB.read_bytes(), "text/javascript")
        if path.startswith("/__sluka__/"):
            file = WEB / path[len("/__sluka__/"):]
            if file.is_file():
                kind = {".js": "text/javascript", ".css": "text/css", ".html": "text/html"}.get(file.suffix, "application/octet-stream")
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


def open_bar(browser, site, query=""):
    context = browser.new_context(viewport={"width": 1536, "height": 864}, device_scale_factor=1.25)
    page = context.new_page()
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto(f"{site}/test.html{query}")
    page.wait_for_function("() => !document.getElementById('bar').hidden && globalThis.__shapes.length > 0")
    return page, errors


def calls(page, name):
    return page.evaluate(f"() => globalThis.__calls.filter(([n]) => n === {name!r}).map(([, b]) => b)")


def last_shape(page):
    return page.evaluate("() => globalThis.__shapes[globalThis.__shapes.length - 1]")


def say_line(page, text="（安芸倫也(あきともや)）\nある春の日俺は運命と出会い"):
    page.evaluate("(text) => globalThis.__push({ t: 'text', text })", text)
    page.wait_for_function("() => document.querySelectorAll('.cc .w').length > 5")
    time.sleep(0.15)


def test_a_line_is_drawn_as_sluka_draws_it(browser, site):
    page, errors = open_bar(browser, site)
    # Nothing yet: the box says what it is, faintly.
    assert page.locator("#cc.idle").count() == 1
    shape = last_shape(page)
    assert shape["dpr"] == 1.25 and len(shape["rects"]) == 1 and not shape["all"]
    # The engine was greeted as a player is.
    assert calls(page, "bar/say")[0]["msg"] == {"t": "hello", "v": 2, "sub_lang": ""}
    say_line(page)
    words = page.locator(".cc .w")
    assert words.count() == 13
    assert page.locator(".cc .w[data-i='6']").inner_text() == "春"
    assert page.locator(".cc .w[data-g]").count() == 2
    # Each level wears what Sluka's settings say: a fill, a line under levels 3 and 4.
    spring = page.locator(".cc .w[data-i='6']").evaluate("(w) => getComputedStyle(w).backgroundImage")
    assert spring.count("linear-gradient") == 2 and "rgb(247, 168, 0)" in spring
    four = page.locator(".cc .w[data-i='9']").evaluate("(w) => getComputedStyle(w).backgroundImage")
    assert four.count("linear-gradient") == 2 and "0.2)" in four  # the line and the hairlines at its sides
    grammar = page.locator(".cc .w[data-i='7']").evaluate("(w) => getComputedStyle(w).backgroundImage")
    assert grammar == "none"
    style = page.locator("#cc").evaluate("(c) => { const s = getComputedStyle(c); return [s.fontWeight, s.borderTopLeftRadius, s.lang, c.lang] }")
    assert style[0] == "500" and style[3] == "ja"
    # Sluka's size for a screen this wide (13px + 1.65 % of it), on one row.
    size = page.locator("#cc").evaluate("(c) => parseFloat(getComputedStyle(c).fontSize)")
    assert size == pytest.approx(13 + 1536 * 0.0165, abs=0.6)
    box = page.locator("#cc").bounding_box()
    assert box["height"] < 2.2 * size
    # The line was sent with the words' places in UTF-8 bytes, as mpv's script counts.
    sent = [b["msg"] for b in calls(page, "bar/say") if b["msg"]["t"] == "line"]
    assert sent[-1]["text"] == "（安芸倫也(あきともや)）\nある春の日俺は運命と出会い"
    assert not errors, errors


def test_card_panel_grade(browser, site):
    page, errors = open_bar(browser, site)
    say_line(page)
    spring = page.locator(".cc .w", has_text="春")
    spring.hover()
    page.wait_for_selector("#card:not([hidden])")
    card = page.locator("#card")
    assert card.locator("ruby rt").inner_text() == "はる"
    assert card.locator(".lead").inner_text() == "spring"
    assert card.locator(".more").inner_text() == "springtime · New Year"
    assert card.locator(".chip").inner_text().strip() == "Level 3"
    assert card.locator(".beat.hi.drop").count() == 1 and card.locator(".pitch .n").inner_text() == "[1]"
    # Over the line, centred on its word.
    c, w, b = card.bounding_box(), spring.bounding_box(), page.locator("#cc").bounding_box()
    assert c["y"] + c["height"] <= b["y"] - 7 and abs((c["x"] + c["width"] / 2) - (w["x"] + w["width"] / 2)) < 2
    # The window takes the pointer over the card and its shadow too.
    rects = last_shape(page)["rects"]
    assert any(r[0] <= c["x"] and r[1] <= c["y"] and r[0] + r[2] >= c["x"] + c["width"] for r in rects)
    lookups = [b["msg"] for b in calls(page, "bar/say") if b["msg"]["t"] == "lookup"]
    assert lookups[-1]["key"] == "春" and lookups[-1]["tok"] == 6 and not lookups[-1].get("pin")

    spring.click()
    page.wait_for_selector("#panel:not([hidden])")
    panel = page.locator("#panel")
    assert panel.locator(".sense").count() == 5
    assert panel.locator(".levels button").count() == 6
    assert panel.locator(".levels button.lit").inner_text() == "3"
    # The keys in their caps, the words beside them a little apart (as Sluka spaces them, by 3.2 pixels).
    assert panel.locator(".legend .k").all_inner_texts() == ["1", "4", "K", "X", "0"]
    assert panel.locator(".legend").inner_text().replace("\n", "") == "1–4level·Kknown·Xignore·0back to new"
    assert page.locator("#card").is_hidden()
    lookups = [b["msg"] for b in calls(page, "bar/say") if b["msg"]["t"] == "lookup"]
    assert lookups[-1]["pin"] is True
    # The pointer may leave the word for the panel: the panel stays.
    page.mouse.move(5, 5)
    time.sleep(0.3)
    assert panel.is_visible()
    # Graded from the panel: the word and the panel follow.
    panel.locator(".levels button[data-st='4']").click()
    page.wait_for_function("() => document.querySelector('.cc .w[data-i=\"6\"]').dataset.st === '4'")
    assert panel.locator(".levels button.lit").inner_text() == "4"
    # Known puts it away, as Sluka does.
    panel.locator(".levels button[data-st='5']").click()
    page.wait_for_selector("#panel", state="hidden")
    grades = [b["msg"] for b in calls(page, "bar/say") if b["msg"]["t"] == "grade"]
    assert [g["status"] for g in grades] == [4, 5] and grades[-1]["key"] == "春" and grades[-1]["text"] == "春"
    # A key grades the word pointed at.
    page.locator(".cc .w", has_text="運命").hover()
    page.wait_for_selector("#card:not([hidden])")
    page.keyboard.press("2")
    page.wait_for_function("() => document.querySelector('.cc .w[data-i=\"11\"]').dataset.st === '2'")
    # Escape and a click beside put a panel away.
    page.locator(".cc .w", has_text="運命").click()
    page.wait_for_selector("#panel:not([hidden])")
    page.keyboard.press("Escape")
    page.wait_for_selector("#panel", state="hidden")
    assert not errors, errors


def test_the_lit_level_and_the_eyes(browser, site):
    page, errors = open_bar(browser, site)
    say_line(page)
    spring = page.locator(".cc .w", has_text="春")
    spring.click()
    page.wait_for_selector("#panel:not([hidden])")
    panel = page.locator("#panel")
    # How many times it was looked up, beside its rank, as in Sluka's panel.
    eyes = panel.locator(".sub .looks")
    assert eyes.inner_text() == "👀 12" and eyes.get_attribute("title") == "Looked up 12 times"
    # The word's own level, lit: pressed again, back to New (its title says so, with the key that does the same).
    lit = panel.locator(".levels button.lit")
    assert lit.inner_text() == "3" and lit.get_attribute("title") == "Back to new (0)"
    lit.click()
    page.wait_for_function("() => document.querySelector('.cc .w[data-i=\"6\"]').dataset.st === '0'")
    grades = [b["msg"] for b in calls(page, "bar/say") if b["msg"]["t"] == "grade"]
    assert [g["status"] for g in grades] == [0] and grades[-1]["key"] == "春"
    assert panel.locator(".levels button.lit").count() == 0 and panel.is_visible()
    # Graded by a double-click: its second click, on the button it lit, does not take the grade back.
    panel.locator(".levels button[data-st='2']").dblclick()
    page.wait_for_function("() => document.querySelector('.cc .w[data-i=\"6\"]').dataset.st === '2'")
    time.sleep(0.3)
    assert 0 not in [b["msg"]["status"] for b in calls(page, "bar/say") if b["msg"]["t"] == "grade"][1:]
    assert not errors, errors


def test_the_bar_is_moved_sized_and_set(browser, site):
    page, errors = open_bar(browser, site)
    say_line(page)
    box = page.locator("#cc").bounding_box()
    # Pointed at: its width and its buttons show, and the window takes the pointer over all of it.
    page.mouse.move(box["x"] + 4, box["y"] + box["height"] / 2)
    page.wait_for_function("() => document.getElementById('bar').classList.contains('on')")
    time.sleep(0.2)
    tools = page.locator("#tools").bounding_box()
    rects = last_shape(page)["rects"]
    assert any(r[1] <= tools["y"] and r[1] + r[3] >= box["y"] + box["height"] for r in rects)
    # Dragged by the subtitle itself: the whole window takes the pointer while it moves, and the place is kept.
    before = page.locator("#bar").bounding_box()
    page.mouse.move(box["x"] + 4, box["y"] + box["height"] / 2)
    page.mouse.down()
    page.mouse.move(box["x"] - 100, box["y"] - 200, steps=8)
    assert last_shape(page)["all"] is True
    page.mouse.up()
    time.sleep(0.4)
    after = page.locator("#bar").bounding_box()
    # (pressed at the middle of the box's height, let go 200 pixels over its top)
    assert after["x"] == pytest.approx(before["x"] - 104, abs=3) and after["y"] == pytest.approx(before["y"] - 200 - box["height"] / 2, abs=3)
    saved = calls(page, "bar/state")[-1]["state"]
    assert saved["x"] == pytest.approx((after["x"] + after["width"] / 2) / 1536, abs=0.003)
    assert last_shape(page)["all"] is False
    # No word was clicked by the drag.
    assert not [b for b in calls(page, "bar/say") if b["msg"]["t"] == "lookup" and b["msg"].get("pin")]
    # Larger, and kept.
    size = page.locator("#cc").evaluate("(c) => parseFloat(getComputedStyle(c).fontSize)")
    page.locator("#tools [data-act='larger']").click()
    time.sleep(0.4)
    bigger = page.locator("#cc").evaluate("(c) => parseFloat(getComputedStyle(c).fontSize)")
    assert bigger > size * 1.05 and calls(page, "bar/state")[-1]["state"]["scale"] == pytest.approx(1.1)
    # Kept in place: a drag is a click then.
    page.locator("#tools [data-act='lock']").click()
    assert calls(page, "bar/state")[-1]["state"]["lock"] is True
    assert page.locator("#tools [data-act='lock']").get_attribute("aria-pressed") == "true"
    # Clicks through: the button that takes them back shows, and is a part that takes the pointer.
    page.locator("#tools [data-act='through']").click()
    assert calls(page, "bar/state")[-1]["state"]["through"] is True
    page.wait_for_selector("#badge", state="visible")
    time.sleep(0.2)
    badge = page.locator("#badge").bounding_box()
    live = last_shape(page)["live"]
    assert any(r[0] <= badge["x"] and r[1] <= badge["y"] and r[0] + r[2] >= badge["x"] + badge["width"] for r in live)
    page.locator("#badge").click()
    assert calls(page, "bar/state")[-1]["state"]["through"] is False
    # Put away.
    page.locator("#cc").hover()
    page.locator("#tools [data-act='close']").click()
    page.wait_for_function("() => globalThis.__calls.some(([n]) => n === 'bar/hide')")
    assert not errors, errors


def test_a_message_and_a_light_card(browser, site):
    page, errors = open_bar(browser, site, "?theme=light")
    say_line(page)
    page.evaluate("() => globalThis.__push({ t: 'engine', msg: { t: 'say', text: 'The free allowance is used up.', seconds: 1 } })")
    page.wait_for_selector("#toast:not([hidden])")
    assert page.locator("#toast").inner_text() == "The free allowance is used up."
    page.wait_for_selector("#toast", state="hidden", timeout=3000)
    page.locator(".cc .w", has_text="春").hover()
    page.wait_for_selector("#card:not([hidden])")
    ground = page.locator("#card").evaluate("(c) => getComputedStyle(c).backgroundColor")
    assert ground == "rgba(255, 255, 255, 0.95)"
    # Text cleared: the box is idle again, and no card is left.
    page.evaluate("() => globalThis.__push({ t: 'text', text: '' })")
    page.wait_for_selector("#cc.idle")
    assert page.locator("#card").is_hidden()
    assert not errors, errors


def test_the_panels_anki_key(browser, site):
    """Settings → Anki's panel button on: the pinned panel has the Anki key, which asks the engine to add the word --
    by a click or by its key -- and shows how the word stands as it is told.  Off, no key: the panel as it was."""
    page, errors = open_bar(browser, site)
    say_line(page)
    page.locator(".cc .w", has_text="春").click()
    page.wait_for_selector("#panel:not([hidden])")
    assert page.locator("#panel .anki-key").count() == 0
    page.close()

    page, errors = open_bar(browser, site, "?anki")
    say_line(page)
    spring = page.locator(".cc .w", has_text="春")
    spring.hover()
    page.wait_for_selector("#card:not([hidden])")
    assert page.locator("#card .anki-key").count() == 0  # (a card only hovered has none, as a page's)
    spring.click()
    page.wait_for_selector("#panel:not([hidden]) .anki-key[data-state='add']")
    key = page.locator("#panel .anki-key")
    assert key.get_attribute("title") == "Add to Anki, into Sluka::Japanese (P)"
    # Not over the word's head: the head leaves room for it, left of the close button.
    k, close = key.bounding_box(), page.locator("#panel .close").bounding_box()
    assert k["x"] + k["width"] <= close["x"] + 1
    key.click()
    page.wait_for_selector("#panel .anki-key[data-state='in']")
    picks = [b["msg"] for b in calls(page, "bar/say") if b["msg"]["t"] == "anki"]
    assert picks == [{"t": "anki", "id": picks[0]["id"], "tok": 6, "key": "春", "text": "春"}]
    # Its key on the keyboard, while the bar has it.
    page.keyboard.press("p")
    page.wait_for_function("() => globalThis.__calls.filter(([n, b]) => n === 'bar/say' && b.msg.t === 'anki').length === 2")
    assert not errors, errors


def test_the_panels_translate_and_look_up_keys(browser, site):
    """The head's keys as a page's panel has them: Translate (Google's translation shown in the panel), Look up (the
    menu of sites, each and its dictionary offline asked of the engine to open), Anki -- in that order, left of ✕."""
    page, errors = open_bar(browser, site, "?anki&tools")
    say_line(page)
    page.locator(".cc .w", has_text="春").click()
    page.wait_for_selector("#panel:not([hidden]) .keys")
    acts = page.eval_on_selector_all("#panel .keys > button", "bs => bs.map(b => b.dataset.act)")
    assert acts == ["translate", "look", "anki"]
    assert page.locator("#panel .keys .tr-key svg[data-mark='tr']").count() == 1
    # Translate: waiting, then Google's translation under the head.
    page.locator("#panel [data-act='translate']").click()
    page.wait_for_selector("#panel .gtr .gtr-text:not(.wait)")
    assert page.locator("#panel .gtr .gtr-text").inner_text() == "spring"
    assert "springtime" in page.locator("#panel .gtr").inner_text()
    # Look up: the menu, its site and that site's dictionary offline.
    page.locator("#panel [data-act='look']").click()
    page.wait_for_selector("#panel .look-menu")
    rows = page.eval_on_selector_all("#panel .look-menu .site", "rs => rs.map(r => r.textContent)")
    assert rows == ["Jisho", "Jisho · offlineInstall", "Weblio"]
    page.locator("#panel .look-menu .offline").click()
    page.wait_for_function("() => globalThis.__calls.some(([n, b]) => n === 'bar/say' && b.msg.t === 'look')")
    looks = [b["msg"] for b in calls(page, "bar/say") if b["msg"]["t"] == "look"]
    assert looks[0]["site"] == "jisho" and looks[0]["offline"] is True and looks[0]["text"] == "春"
    assert page.locator("#panel .look-menu").count() == 0  # (closed once a site is chosen)
    page.locator("#panel [data-act='look']").click()
    page.locator("#panel .look-menu .site", has_text="Weblio").click()
    page.wait_for_function("() => globalThis.__calls.filter(([n, b]) => n === 'bar/say' && b.msg.t === 'look').length === 2")
    looks = [b["msg"] for b in calls(page, "bar/say") if b["msg"]["t"] == "look"]
    assert looks[1]["site"] == "weblio" and "offline" not in looks[1]
    # The translation stays with the word while the panel is open.
    assert page.locator("#panel .gtr").count() == 1
    assert not errors, errors


def test_the_panels_speaker(browser, site):
    """In the head's top left corner, the word beside it (content/ui.js .head > .say): a click or V says the word,
    lit while the engine says it is being said."""
    page, errors = open_bar(browser, site, "?tools")
    say_line(page)
    page.locator(".cc .w", has_text="春").click()
    page.wait_for_selector("#panel:not([hidden]) .ph > .say")
    box = page.locator("#panel .ph > .say").bounding_box()
    head = page.locator("#panel .ph .head").bounding_box()
    # Left of the word, level with the word itself (centred on its em box, not lifted by its furigana).
    base = page.evaluate("""() => { const r = document.createRange(); const h = document.querySelector('#panel .ph .head');
      const t = [...h.childNodes].map((n) => n.nodeType === 1 && n.tagName === 'RUBY' ? n.firstChild : n).find((n) => n && n.nodeType === 3);
      r.selectNodeContents(t); const b = r.getBoundingClientRect(); return { top: b.top, bottom: b.bottom }; }""")
    assert box["x"] < head["x"] and abs((box["y"] + box["height"] / 2) - (base["top"] + base["bottom"]) / 2) < 5
    page.locator("#panel .ph > .say").click()
    page.wait_for_selector("#panel .ph > .say[data-active]")
    spoken = page.evaluate("() => globalThis.__spoken")
    assert spoken[0]["key"] == "春" and spoken[0]["t"] == "speak"
    page.wait_for_selector("#panel .ph > .say:not([data-active])")
    page.keyboard.press("v")
    page.wait_for_function("() => globalThis.__spoken.length === 2")
    assert not errors, errors


@pytest.mark.parametrize("place", ["replace", "above", "below"])
def test_your_own_dictionaries_in_the_panel(browser, site, place):
    """Your own dictionaries' meanings (Settings → Dictionary → Your own dictionaries), drawn as Sluka's panel draws
    them, each under its name: instead of Sluka's meanings, above them or under them, as Settings says.  A link in
    them opens in a small window of Sluka's (the engine's), never in the floating subtitles' page."""
    page, errors = open_bar(browser, site, f"?own={place}")
    say_line(page)
    page.locator(".cc .w", has_text="春").click()
    page.wait_for_selector("#panel:not([hidden]) .own-dicts .rg-dict")
    order = page.eval_on_selector_all("#panel .body > *", "els => els.map(e => e.className.split(' ')[0])")
    senses = [c for c in order if c == "sense"]
    if place == "replace":
        assert order == ["own-dicts"]
    elif place == "above":
        assert order[0] == "own-dicts" and len(senses) == 5
    else:
        assert order[-1] == "own-dicts" and len(senses) == 5
    assert page.locator("#panel .rg-tag").inner_text() == "Jitendex"
    assert page.locator("#panel .od-reading").inner_text() == "はる"
    assert page.eval_on_selector_all("#panel .od-defs li", "ls => ls.length") == 2
    # Its own stylesheet, as the extension holds it inside the dictionary's block.
    assert page.evaluate("() => [...document.querySelectorAll('head style')].some((s) => s.textContent.includes('[data-dict=\"od-1\"] .od-sc'))")
    with _no_page(page):
        page.locator("#panel .rg-dict a[data-link]").click()
    page.wait_for_function("() => (globalThis.__opened || []).length === 1")
    assert page.evaluate("() => globalThis.__opened") == ["https://jitendex.org/haru"]
    assert page.url.endswith(f"?own={place}")
    assert not errors, errors


class _no_page:
    """No window opened by what is clicked within."""

    def __init__(self, page):
        self.page = page

    def __enter__(self):
        self.before = len(self.page.context.pages)

    def __exit__(self, *exc):
        time.sleep(0.3)
        assert len(self.page.context.pages) == self.before


def test_the_panels_ai_check(browser, site):
    """The AI check's ✦ (Settings → AI check), as a page's panel has it: a quiet key in the head where the dictionary
    answered; pressed, or F, the word and its sentence asked of it once -- the key then gone -- and what it says drawn
    under the meanings, your own request's answer under "Your question"."""
    page, errors = open_bar(browser, site, "?ai")
    say_line(page)
    page.locator(".cc .w", has_text="春").click()
    page.wait_for_selector("#panel:not([hidden]) .keys .ai-key")
    assert page.eval_on_selector_all("#panel .keys > button", "bs => bs.map(b => b.dataset.act)") == ["ask"]
    key = page.locator("#panel .ai-key")
    assert key.get_attribute("title") == "Ask AI to double-check. (F) Sends this word and its sentence to Anthropic."
    assert key.inner_text() == "✦"
    key.click()
    page.wait_for_selector("#panel .ask .verdict")
    asks = page.evaluate("() => globalThis.__asks")
    assert len(asks) == 1 and asks[0]["key"] == "春" and asks[0]["text"] == "春"
    assert page.locator("#panel .ai-key").count() == 0
    assert page.eval_on_selector_all("#panel .body > *", "els => els.map(e => e.className)")[-1] == "ask secondary"
    assert page.locator("#panel .vd-tag").inner_text() == "Real word"
    assert "vd-established" in page.locator("#panel .vd-tag").get_attribute("class")
    assert page.locator("#panel .vd-conf").inner_text() == "high confidence"
    assert page.locator("#panel .vd-meaning").inner_text() == "spring, the season"
    assert page.locator("#panel .vd-ex b").inner_text() == "春"
    assert page.locator("#panel .vd-ex-tr").inner_text() == "Spring has come."
    lines = page.eval_on_selector_all("#panel .vd-line", "ls => ls.map(l => l.textContent)")
    assert lines == ["Reading: はる", "Used in: neutral", "Why: A common word."]
    assert page.locator("#panel .vd-own b").inner_text() == "Your question"
    own = page.locator("#panel .vd-own-text").inner_text()
    assert own.splitlines() == ["Here it is the season the story starts in.", "It can also mean the prime of life."]
    # Asked once: F again is nothing more.
    page.keyboard.press("f")
    time.sleep(0.3)
    assert len(page.evaluate("() => globalThis.__asks")) == 1
    # Graded, the panel told again: its answer stays.
    page.keyboard.press("2")
    page.wait_for_function("() => globalThis.__calls.some(([n, b]) => n === 'bar/say' && b.msg.t === 'grade')")
    time.sleep(0.2)
    assert page.locator("#panel .ask .verdict").count() == 1
    assert not errors, errors


def test_the_panels_ai_check_for_a_word_no_dictionary_has(browser, site):
    """Where neither Sluka's dictionary nor yours has the word, asking is the main thing to do: a button in the
    meanings, with what it sends, as a page's panel has it; F asks too.  What went wrong is said where it would be."""
    page, errors = open_bar(browser, site, "?ai=wanted")
    say_line(page)
    page.locator(".cc .w", has_text="春").click()
    page.wait_for_selector("#panel:not([hidden]) .ask .ask-go")
    assert page.locator("#panel .ai-key").count() == 0
    assert page.locator("#panel .ask-go").inner_text() == "Ask AI if this is a real word (F)"
    assert page.locator("#panel .ask .why").inner_text() == "Sends this word and its sentence to Anthropic."
    page.keyboard.press("f")
    page.wait_for_selector("#panel .ask .verdict")
    assert page.locator("#panel .ask-go").count() == 0 and page.locator("#panel .ask .why").count() == 0
    assert len(page.evaluate("() => globalThis.__asks")) == 1
    assert not errors, errors

    page, errors = open_bar(browser, site, "?ai&aierror")
    say_line(page)
    page.locator(".cc .w", has_text="春").click()
    page.wait_for_selector("#panel .keys .ai-key")
    page.locator("#panel .ai-key").click()
    page.wait_for_selector("#panel .ask .err")
    assert page.locator("#panel .ask .err").inner_text() == "The AI check is turned off in Settings."
    # (an answer that did not come is asked again)
    assert page.locator("#panel .ai-key").count() == 1
    assert not errors, errors
