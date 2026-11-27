"""Sluka Vision's page (web/vision.html) in a real Chromium, with a stand-in for the app and Sluka's engine: the words of
a game's window laid over it where they sit, tilted, in columns, underlined by level; the card, the panel, a grade; the
lines whose text has gone put away; the parts of the window drawn on.

Skipped where there is no Chrome and Playwright to drive it.
"""

from __future__ import annotations

import functools
import http.server
import json
import math
import os
import shutil
import threading
import time
from pathlib import Path

import pytest

APP = Path(os.environ.get("SLUKA_APP", "/home/claude/work/sluka-desktop/app"))
WEB = APP / "web"
STUB = Path(__file__).parent / "web" / "vision-stub.js"
SHOTS = Path(os.environ.get("SLUKA_SHOTS", "/home/claude/verify/vision"))
CHROME = shutil.which("google-chrome") or shutil.which("chromium")

playwright = pytest.importorskip("playwright.sync_api")
if not CHROME:
    pytest.skip("no Chrome here", allow_module_level=True)

# What ocrd.py's VisionWatch says it read, as a game shows it (a 1260 x 679 window, as the screenshots were): Persona's
# slanted replies with Google Lens' words, two lines of a speech box read without words (one paragraph), a column of
# vertical text, and a line with nothing Sluka knows in it.
LINES = [
    {"i": 0, "p": 0, "v": False, "rtl": False, "text": "わかった", "box": [771, 351, 112, 34, 0.05], "words": [[0, 4, 0, 112]]},
    {"i": 1, "p": 1, "v": False, "rtl": False, "text": "面倒くさい", "box": [832, 444, 132, 30, -0.03],
     "words": [[0, 2, 0, 52], [2, 5, 54, 132]]},
    {"i": 2, "p": 2, "v": False, "rtl": False, "text": "何で公衆電話に？", "box": [750, 497, 212, 32, -0.09],
     "words": [[0, 1, 0, 26], [1, 2, 26, 50], [2, 6, 52, 160], [6, 7, 160, 184], [7, 8, 186, 212]]},
    {"i": 3, "p": 3, "v": False, "rtl": False, "text": "戻るのも面倒なんでオマエやっ", "box": [400, 569, 336, 28, 0.0], "words": []},
    {"i": 4, "p": 3, "v": False, "rtl": False, "text": "といてくれ。", "box": [304, 600, 144, 28, 0.0], "words": []},
    {"i": 5, "p": 4, "v": True, "rtl": False, "text": "真面目な学生生活を送れ", "box": [1180, 200, 30, 330, 0.0], "words": []},
    {"i": 6, "p": 5, "v": False, "rtl": False, "text": "Lv 99", "box": [100, 40, 60, 20, 0.0], "words": []},
]


def still_bmp(w=1260, h=679) -> bytes:
    """A 24-bit BMP of a game's picture: dark blue at the top, warm at the bottom (bottom row first, as BMPs are)."""
    import struct

    stride = (w * 3 + 3) & ~3
    rows = []
    for y in range(h - 1, -1, -1):
        t = y / max(1, h - 1)
        pixel = bytes((int(80 - 50 * t), int(40 + 30 * t), int(30 + 150 * t)))
        rows.append(pixel * w + b"\0" * (stride - w * 3))
    data = b"".join(rows)
    head = struct.pack("<IiiHHIIiiII", 40, w, h, 1, 24, 0, len(data), 2835, 2835, 0, 0)
    return b"BM" + struct.pack("<IHHI", 14 + len(head) + len(data), 0, 0, 54) + head + data


class Site(http.server.SimpleHTTPRequestHandler):
    """/__sluka__/... from the app's web folder; /test.html is vision.html with the stand-in put before its own scripts."""

    def log_message(self, *args):
        pass

    def do_GET(self):  # noqa: N802
        path = self.path.split("?", 1)[0]
        if path == "/test.html":
            page = (WEB / "vision.html").read_text(encoding="utf-8")
            page = page.replace('<link rel="stylesheet" href="/__sluka__/bar.css">',
                                '<script src="/stub.js"></script><link rel="stylesheet" href="/__sluka__/bar.css">')
            if "ground" in self.path:
                # (for the pictures only: a game's colours under the words)
                page = page.replace("<body>", '<body style="background: linear-gradient(135deg, #1f2530, #3a2f2a 55%, #20262e)">')
            return self._send(page.encode("utf-8"), "text/html; charset=utf-8")
        if path == "/stub.js":
            return self._send(STUB.read_bytes(), "text/javascript")
        if path == "/__sluka__/api/vision/still":
            # The picture kept (vision.py): a game's colours, as the screen reader writes them (a BMP).
            return self._send(still_bmp(), "image/bmp")
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


def open_page(browser, site, dpr=1.0, query=""):
    # The window is as large as the game's inside: 1260 x 679 of the screen's pixels.
    context = browser.new_context(viewport={"width": round(1260 / dpr), "height": round(679 / dpr)}, device_scale_factor=dpr)
    page = context.new_page()
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto(f"{site}/test.html{query}")
    page.wait_for_function("() => globalThis.__shapes.length > 0 && globalThis.__calls.some(([n, b]) => n === 'vision/say' && b.msg.t === 'hello')")
    return page, errors


def calls(page, name):
    return page.evaluate(f"() => globalThis.__calls.filter(([n]) => n === {name!r}).map(([, b]) => b)")


def last_shape(page):
    return page.evaluate("() => globalThis.__shapes[globalThis.__shapes.length - 1]")


def show(page, lines=LINES, layout_id=1):
    page.evaluate("(m) => globalThis.__push(m)", {"t": "layout", "id": layout_id, "area": [0, 0, 1260, 679], "size": [1260, 679],
                                                  "lines": json.loads(json.dumps(lines)), "engine": "lens", "why": "key"})
    page.wait_for_function("() => document.querySelectorAll('.vw').length > 10")
    time.sleep(0.2)


def piece(page, text_index, word):
    """The boxes of the word (its number, from the left of the engine's words) as the page placed them."""
    return page.locator(f".vw[data-i='{text_index}']")


def after(page, locator, prop):
    return locator.evaluate(f"(n) => getComputedStyle(n, '::after').{prop}")


def test_words_are_laid_where_the_game_wrote_them(browser, site):
    page, errors = open_page(browser, site)
    assert last_shape(page)["rects"] == []  # nothing read yet: nothing of the window takes the pointer
    show(page)
    # The lines as one text for the engine: a paragraph's lines run on; each paragraph a line of its own.
    sent = [b["msg"] for b in calls(page, "vision/say") if b["msg"]["t"] == "line"]
    assert sent[-1]["text"] == "わかった\n面倒くさい\n何で公衆電話に？\n戻るのも面倒なんでオマエやっといてくれ。\n真面目な学生生活を送れ\nLv 99"
    assert page.locator(".vl").count() == 7
    # Each word's place along its line: where Lens put it, or spread over a line read without words.
    boxes = page.evaluate("""() => [...document.querySelectorAll('.vw')].map((n) => ({
        i: +n.dataset.i, line: +n.parentElement.dataset.line, st: n.dataset.st, g: n.hasAttribute('data-g'),
        left: parseFloat(n.style.left || 0), width: parseFloat(n.style.width || 0),
        top: parseFloat(n.style.top || 0), height: parseFloat(n.style.height || 0) }))""")
    by_line = {}
    for b in boxes:
        by_line.setdefault(b["line"], []).append(b)
    mendou, kusai = by_line[1]
    assert (mendou["left"], mendou["width"]) == pytest.approx((0, 52), abs=0.6)
    assert (kusai["left"], kusai["width"]) == pytest.approx((54, 78), abs=0.6)
    # 公衆電話: one of Lens' words; に, a word of its own; ？ is no word of Sluka's.
    phone = [b for b in by_line[2] if b["i"] == 6][0]
    assert (phone["left"], phone["width"]) == pytest.approx((52, 108), abs=0.6)
    assert len(by_line[2]) == 4
    # A line without words: its fourteen letters each a fourteenth of it (all as wide, in Japanese).
    first = by_line[3][0]
    assert first["left"] == pytest.approx(0, abs=0.5) and first["width"] == pytest.approx(336 * 2 / 14, abs=0.6)
    # A word may run from one line onto the next (やっ|と): a box on each, of the one word.
    yatto = [b for b in boxes if b["line"] in (3, 4) and b["i"] == by_line[4][0]["i"]]
    assert [b["line"] for b in yatto] == [3, 4]
    assert yatto[0]["left"] + yatto[0]["width"] == pytest.approx(336, abs=0.6) and yatto[1]["left"] == pytest.approx(0, abs=0.5)
    # The column: its words down it.
    column = by_line[5]
    assert all(b["height"] > 0 and b["width"] == 0 for b in column)
    assert column[0]["top"] == pytest.approx(0, abs=0.5) and column[0]["height"] == pytest.approx(330 * 3 / 11, abs=0.6)
    # Tilted as the game tilted it.
    tilt = page.locator(".vl[data-line='2']").evaluate("(n) => getComputedStyle(n).transform")
    a, b = (float(v) for v in tilt[len("matrix("):].split(",")[:2])
    assert math.atan2(b, a) == pytest.approx(-0.09, abs=0.002)
    assert page.locator(".vl[data-line='3']").evaluate("(n) => n.style.transform") == ""
    # Underlined in the colour of their levels: new in blue, level 3 in its line's amber; known words and grammar not.
    assert "59, 130, 246" in after(page, page.locator(".vw[data-i='2']"), "backgroundColor")
    assert "247, 168, 0" in after(page, page.locator(".vw[data-i='3']"), "backgroundColor")
    assert after(page, page.locator(".vw[data-i='4']"), "backgroundColor") == "rgba(0, 0, 0, 0)"
    assert after(page, page.locator(".vw[data-i='5']"), "backgroundColor") == "rgba(0, 0, 0, 0)"
    # Under the letters (beside them, in a column), as thick as the line is large.
    line_box = page.locator(".vl[data-line='1']").bounding_box()
    under = page.locator(".vw[data-i='2']").evaluate("(n) => { const s = getComputedStyle(n, '::after'); return [s.top, s.height] }")
    assert float(under[0][:-2]) > 30 and 2 <= float(under[1][:-2]) <= 6 and line_box["height"] > 28
    side = page.locator(".vl.v .vw").first.evaluate("(n) => { const s = getComputedStyle(n, '::after'); return [s.right, s.width] }")
    assert float(side[0][:-2]) > 30 and float(side[1][:-2]) >= 2
    # The window takes the pointer where the words are: a level line as one part, each word of a tilted line.
    rects = last_shape(page)["rects"]
    assert any(abs(r[0] - (400 - 168 - 2)) < 2 and r[2] > 300 for r in rects)
    tilted = [r for r in rects if 640 < r[0] + r[2] / 2 < 860 and 470 < r[1] + r[3] / 2 < 525]
    assert len(tilted) == 4
    assert not errors, errors


def test_a_card_a_panel_and_a_grade(browser, site):
    page, errors = open_page(browser, site)
    show(page)
    page.locator(".vw[data-i='2']").first.hover()
    page.wait_for_selector("#card:not([hidden])")
    card = page.locator("#card")
    assert card.locator(".lead").inner_text() == "trouble; difficulty"
    assert card.locator("ruby rt").inner_text() == "めんどう"
    # Over the word, and part of the window that is drawn on.
    word = page.locator(".vw[data-i='2']").first.bounding_box()
    box = card.bounding_box()
    assert box["y"] + box["height"] <= word["y"] + 1
    assert page.locator(".vw.hov").count() == 1
    time.sleep(0.2)
    assert any(abs(r[0] - (box["x"] - 22)) < 2 for r in last_shape(page)["rects"])
    # A click: the panel, with the levels (and no keys: this window never has the keyboard).
    page.locator(".vw[data-i='2']").first.click()
    page.wait_for_selector("#panel:not([hidden])")
    panel = page.locator("#panel")
    assert panel.locator(".levels button").count() == 6 and panel.locator(".legend").count() == 0
    lookups = [b["msg"] for b in calls(page, "vision/say") if b["msg"]["t"] == "lookup"]
    assert lookups[-1]["pin"] is True and lookups[-1]["text"] == "面倒" and lookups[-1]["tok"] == 2
    panel.locator(".levels button[data-st='3']").click()
    page.wait_for_function("() => document.querySelector(\".vw[data-i='2']\").dataset.st === '3'")
    assert "247, 168, 0" in after(page, page.locator(".vw[data-i='2']").first, "backgroundColor")
    grades = [b["msg"] for b in calls(page, "vision/say") if b["msg"]["t"] == "grade"]
    assert grades[-1]["key"] == "面倒" and grades[-1]["status"] == 3
    # A word on two lines is lit on both.
    page.locator(".vl[data-line='4'] .vw").first.hover()
    page.wait_for_function("() => document.querySelectorAll('.vw.hov').length === 2")
    # Known: the panel goes, as Sluka's own does.
    panel.locator(".levels button[data-st='5']").click()
    page.wait_for_selector("#panel[hidden]", state="attached")
    assert after(page, page.locator(".vw[data-i='2']").first, "backgroundColor") == "rgba(0, 0, 0, 0)"
    assert not errors, errors


def test_the_panels_translate_and_look_up_keys(browser, site):
    """As in the floating subtitles' panel: Translate, Look up and Anki left of ✕; Google's translation in the panel; the
    menu of sites, each and its dictionary offline asked of the engine to open."""
    page, errors = open_page(browser, site, query="?tools")
    show(page)
    page.locator(".vw[data-i='2']").first.click()
    page.wait_for_selector("#panel:not([hidden]) .keys")
    acts = page.eval_on_selector_all("#panel .keys > button", "bs => bs.map(b => b.dataset.act)")
    assert acts == ["translate", "look", "anki"]
    assert page.locator("#panel .anki-key").count() == 1  # (one Anki key: in the head's keys)
    page.locator("#panel [data-act='translate']").click()
    page.wait_for_selector("#panel .gtr .gtr-text:not(.wait)")
    assert page.locator("#panel .gtr .gtr-text").inner_text() == "trouble"
    assert "nuisance" in page.locator("#panel .gtr").inner_text()
    page.locator("#panel [data-act='look']").click()
    page.wait_for_selector("#panel .look-menu")
    rows = page.eval_on_selector_all("#panel .look-menu .site", "rs => rs.map(r => r.textContent)")
    assert rows == ["Jisho", "Jisho · offline✓", "Weblio"]
    page.locator("#panel .look-menu .site", has_text="Weblio").click()
    page.wait_for_function("() => globalThis.__calls.some(([n, b]) => n === 'vision/say' && b.msg.t === 'look')")
    looks = [b["msg"] for b in calls(page, "vision/say") if b["msg"]["t"] == "look"]
    assert looks[0]["site"] == "weblio" and "offline" not in looks[0] and looks[0]["text"] == "面倒" and looks[0]["tok"] == 2
    assert page.locator("#panel .look-menu").count() == 0
    page.locator("#panel [data-act='look']").click()
    page.locator("#panel .look-menu .offline").click()
    page.wait_for_function("() => globalThis.__calls.filter(([n, b]) => n === 'vision/say' && b.msg.t === 'look').length === 2")
    looks = [b["msg"] for b in calls(page, "vision/say") if b["msg"]["t"] == "look"]
    assert looks[1]["site"] == "jisho" and looks[1]["offline"] is True
    assert page.locator("#panel .gtr").count() == 1
    assert not errors, errors


def test_the_panels_speaker(browser, site):
    """The speaker in the head's corner says the word; its key held with the panel's while the game is in front."""
    page, errors = open_page(browser, site, query="?tools")
    show(page)
    page.locator(".vw[data-i='2']").first.click()
    page.wait_for_selector("#panel:not([hidden]) .ph > .say")
    page.wait_for_function("() => globalThis.__calls.some(([n, b]) => n === 'vision/looking' && b.panel && b.say === 'v')")
    page.locator("#panel .ph > .say").click()
    page.wait_for_selector("#panel .ph > .say[data-active]")
    says = [b["msg"] for b in calls(page, "vision/say") if b["msg"]["t"] == "speak"]
    assert says[0]["text"] == "面倒" and says[0]["tok"] == 2
    page.wait_for_selector("#panel .ph > .say:not([data-active])")
    # The held key, pressed in the game: the app tells the page (vision.py _panel_key_pressed).
    page.evaluate("() => globalThis.__push({ t: 'key', say: true })")
    page.wait_for_function("() => globalThis.__calls.filter(([n, b]) => n === 'vision/say' && b.msg.t === 'speak').length === 2")
    assert not errors, errors


@pytest.mark.parametrize("dpr", [1.0, 1.5])
def test_the_game_stopped_where_it_is(browser, site, dpr):
    """Sluka Vision's keys that stop the game (vision.py): the picture kept laid over the whole window, under the words,
    as wide as the game's inside; the window taking the pointer all over meanwhile; a pill saying which way, and its
    key; let go of, taken away (a word for an older picture is not this one's)."""
    page, errors = open_page(browser, site, dpr=dpr)
    show(page)
    page.evaluate("(m) => globalThis.__push(m)", {"t": "freeze", "on": True, "mode": "pause", "n": 1, "size": [1260, 679], "key": "Alt+P"})
    page.wait_for_selector("#still:not([hidden])")
    box = page.locator("#still").bounding_box()
    assert box["x"] == 0 and box["y"] == 0 and abs(box["width"] - 1260 / dpr) < 0.6 and abs(box["height"] - 679 / dpr) < 0.6
    assert page.locator("#frozen").inner_text() == "Game paused · Alt+P to go on"
    # The words over it, where they were.
    word = page.locator(".vw[data-i='2']").first.bounding_box()
    under = page.evaluate("([x, y]) => document.elementFromPoint(x, y)?.className", [word["x"] + word["width"] / 2, word["y"] + word["height"] / 2])
    assert "vw" in under
    # The whole window drawn on, and taking the pointer.
    page.wait_for_function("(w) => { const s = globalThis.__shapes.at(-1); return s && s.rects[0][2] >= w - 1; }", arg=1260 / dpr)
    shape = page.evaluate("() => globalThis.__shapes.at(-1)")
    assert shape["rects"][0][:2] == [0, 0] and abs(shape["rects"][0][3] - 679 / dpr) < 1
    # A panel open, then a click on the picture off the words: put away (the game gets no click).
    page.locator(".vw[data-i='2']").first.click()
    page.wait_for_selector("#panel:not([hidden])")
    page.mouse.click(30, 300 / dpr)
    page.wait_for_selector("#panel", state="hidden")
    # The other way, the same picture: only the pill says so.
    page.evaluate("(m) => globalThis.__push(m)", {"t": "freeze", "on": True, "mode": "picture", "n": 1, "size": [1260, 679], "key": "Alt+F"})
    page.wait_for_function("() => document.querySelector('#frozen').innerText === 'Picture frozen · Alt+F to let go'")
    assert page.locator("#frozen").get_attribute("data-mode") == "picture"
    # A word for an older picture: not this one's.
    page.evaluate("(m) => globalThis.__push(m)", {"t": "freeze", "on": False, "n": 0})
    time.sleep(0.3)
    assert page.locator("#still").is_visible()
    # Let go of: taken away, and the window is the words' alone again.
    page.evaluate("(m) => globalThis.__push(m)", {"t": "freeze", "on": False, "n": 1})
    page.wait_for_selector("#still", state="hidden")
    assert page.locator("#frozen").is_hidden()
    page.wait_for_function("(w) => { const s = globalThis.__shapes.at(-1); return s && s.rects.every((r) => r[2] < w - 1); }", arg=1260 / dpr)
    if dpr == 1.0:
        page.evaluate("(m) => globalThis.__push(m)", {"t": "freeze", "on": True, "mode": "pause", "n": 2, "size": [1260, 679], "key": "Alt+P"})
        page.wait_for_selector("#still:not([hidden])")
        SHOTS.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(SHOTS / "vision-paused.png"))
    assert not errors, errors


def test_what_is_gone_goes_and_the_game_behind_hides_all(browser, site):
    page, errors = open_page(browser, site)
    show(page)
    page.locator(".vw[data-i='6']").hover()
    page.wait_for_selector("#card:not([hidden])")
    # The game moved on under line 0: its words go at once.
    page.evaluate("() => globalThis.__push({ t: 'stale', lines: [0] })")
    page.wait_for_selector(".vl[data-line='0'].gone", state="attached")
    # Under line 2, the one pointed at (its button lit, say): its words stay, and the card, while the pointer is there.
    page.evaluate("() => globalThis.__push({ t: 'stale', lines: [2] })")
    time.sleep(0.4)
    assert page.locator(".vl[data-line='2'].gone").count() == 0 and page.locator("#card").is_visible()
    # Left: they go, and the card.
    page.mouse.move(5, 660)
    page.wait_for_selector(".vl[data-line='2'].gone", state="attached")
    page.wait_for_selector("#card[hidden]", state="attached")
    time.sleep(0.2)
    assert not [r for r in last_shape(page)["rects"] if 640 < r[0] + r[2] / 2 < 860 and 470 < r[1] + r[3] / 2 < 525]
    # What was under line 0 is back as it was read: so are its words.
    page.evaluate("() => globalThis.__push({ t: 'back', lines: [0] })")
    page.wait_for_function("() => !document.querySelector(\".vl[data-line='0']\").classList.contains('gone')")
    assert page.locator(".vl[data-line='2'].gone").count() == 1
    # Reading: said at the game's corner.
    page.evaluate("() => globalThis.__push({ t: 'status', state: 'reading', text: '' })")
    page.wait_for_selector("#badge:not([hidden])")
    assert "reading" in page.locator("#badge").inner_text()
    page.evaluate("() => globalThis.__push({ t: 'status', state: 'waiting', text: '' })")
    page.wait_for_selector("#badge[hidden]", state="attached")
    # Another program in front: nothing of it is seen, nor takes the pointer.
    page.evaluate("() => globalThis.__push({ t: 'front', on: false })")
    page.wait_for_function("() => document.body.hidden")
    time.sleep(0.2)
    assert last_shape(page)["rects"] == []
    page.evaluate("() => globalThis.__push({ t: 'front', on: true })")
    page.wait_for_function("() => !document.body.hidden")
    time.sleep(0.2)
    assert len(last_shape(page)["rects"]) > 4
    # All of it put away.
    page.evaluate("() => globalThis.__push({ t: 'clear' })")
    page.wait_for_function("() => !document.querySelector('.vl')")
    time.sleep(0.2)
    assert last_shape(page)["rects"] == []
    assert not errors, errors


def looking(page):
    return calls(page, "vision/looking")


def test_the_lit_level_the_keys_and_the_eyes(browser, site):
    page, errors = open_page(browser, site)
    show(page)
    # Pointed at: the app is told the word's line (and no panel: no keys).
    page.locator(".vw[data-i='1']").hover()
    page.wait_for_selector("#card:not([hidden])")
    page.wait_for_function("() => globalThis.__calls.some(([n, b]) => n === 'vision/looking' && b.lines.length)")
    assert looking(page)[-1] == {"panel": False, "read": 1, "lines": [0]}
    # Clicked: its panel, with Sluka's keys for the app to hold meanwhile.
    page.locator(".vw[data-i='1']").click()
    page.wait_for_selector("#panel:not([hidden])")
    page.wait_for_function("() => globalThis.__calls.some(([n, b]) => n === 'vision/looking' && b.panel)")
    told = looking(page)[-1]
    assert told["panel"] is True and told["lines"] == [0] and told["keys"]["0"] == "0" and told["keys"]["5"] == "k"
    panel = page.locator("#panel")
    lit = panel.locator(".levels button.lit")
    # The word's own level, lit: pressed again, back to New, as in Sluka (and its title says so, with its key).
    assert lit.inner_text() == "1" and lit.get_attribute("title") == "Back to new (0)"
    assert panel.locator(".levels button[data-st='2']").get_attribute("title") == "Level 2 (2)"
    lit.click()
    page.wait_for_function("() => document.querySelector(\".vw[data-i='1']\").dataset.st === '0'")
    grades = [b["msg"] for b in calls(page, "vision/say") if b["msg"]["t"] == "grade"]
    assert grades[-1]["key"] == "わかった" and grades[-1]["status"] == 0
    assert panel.locator(".levels button.lit").count() == 0 and panel.is_visible()
    # A double-click on a level: the second click lands on it lit, and does not take it back.
    panel.locator(".levels button[data-st='3']").dblclick()
    page.wait_for_function("() => document.querySelector(\".vw[data-i='1']\").dataset.st === '3'")
    time.sleep(0.3)
    grades = [b["msg"]["status"] for b in calls(page, "vision/say") if b["msg"]["t"] == "grade"]
    assert grades[-1] == 3 and 0 not in grades[1:]
    # The keys, pressed in the game while the panel is open (the app holds them): a level, back to New, and Esc.
    page.evaluate("() => globalThis.__push({ t: 'key', st: 2 })")
    page.wait_for_function("() => document.querySelector(\".vw[data-i='1']\").dataset.st === '2'")
    page.evaluate("() => globalThis.__push({ t: 'key', st: 0 })")
    page.wait_for_function("() => document.querySelector(\".vw[data-i='1']\").dataset.st === '0'")
    page.mouse.move(5, 660)
    page.evaluate("() => globalThis.__push({ t: 'key', close: true })")
    page.wait_for_selector("#panel[hidden]", state="attached")
    # Closed: the keys given back at once; the pointer gone from the words: its lines let go of a moment later.
    page.wait_for_function("() => { const l = globalThis.__calls.filter(([n]) => n === 'vision/looking'); return l.length && !l[l.length - 1][1].panel; }")
    page.wait_for_function("() => { const l = globalThis.__calls.filter(([n]) => n === 'vision/looking'); return !l[l.length - 1][1].lines.length; }",
                           timeout=3000)
    # A key with no panel open is nothing.
    page.evaluate("() => globalThis.__push({ t: 'key', st: 5 })")
    time.sleep(0.3)
    assert page.locator(".vw[data-i='1']").first.get_attribute("data-st") == "0"
    # How many times a word was looked up, from the third: 👀 in its panel, as in Sluka (not in the card a hover shows).
    page.locator(".vw[data-i='2']").first.hover()
    page.wait_for_selector("#card:not([hidden])")
    assert page.locator("#card .looks").count() == 0
    page.locator(".vw[data-i='2']").first.click()
    page.wait_for_selector("#panel:not([hidden])")
    eyes = panel.locator(".sub .looks")
    assert eyes.inner_text() == "👀 4" and eyes.get_attribute("title") == "Looked up 4 times"
    page.locator(".vw[data-i='6']").click()  # (one looked up less often: none)
    page.wait_for_function("() => document.querySelector('#panel .ph .head').textContent === '公衆電話'")
    assert panel.locator(".looks").count() == 0
    assert not errors, errors


def test_a_screen_at_125_percent(browser, site):
    # The window's pixels are the screen's: at 125 % the page's are a fifth fewer, and the words follow.
    page, errors = open_page(browser, site, dpr=1.25)
    show(page)
    mendou = page.locator(".vl[data-line='1'] .vw").first
    assert float(mendou.evaluate("(n) => n.style.width")[:-2]) == pytest.approx(52 / 1.25, abs=0.6)
    line = page.locator(".vl[data-line='3']").bounding_box()
    assert line["x"] == pytest.approx((400 - 168) / 1.25, abs=0.6) and line["width"] == pytest.approx(336 / 1.25, abs=0.6)
    assert last_shape(page)["dpr"] == 1.25
    assert not errors, errors


def test_pictures(browser, site):
    """For a person to look at: the words over a game's colours, one pointed at, one clicked."""
    SHOTS.mkdir(parents=True, exist_ok=True)
    page, errors = open_page(browser, site, query="?ground=1")
    show(page)
    page.screenshot(path=str(SHOTS / "vision-words.png"))
    page.locator(".vw[data-i='3']").hover()
    page.wait_for_selector("#card:not([hidden])")
    time.sleep(0.15)
    page.screenshot(path=str(SHOTS / "vision-card.png"))
    page.locator(".vw[data-i='6']").click()
    page.wait_for_selector("#panel:not([hidden])")
    time.sleep(0.15)
    page.screenshot(path=str(SHOTS / "vision-panel.png"))
    assert not errors, errors


def test_your_own_dictionaries_and_the_ai_check(browser, site):
    """As in the floating subtitles' panel: your own dictionaries' meanings in their place, a link in them opened by
    the engine; the AI check's ✦, its key held with the panel's while the game is in front, its answer under the
    meanings."""
    page, errors = open_page(browser, site, query="?own=above&ai")
    show(page)
    page.locator(".vw[data-i='2']").first.click()
    page.wait_for_selector("#panel:not([hidden]) .own-dicts .rg-dict")
    order = page.eval_on_selector_all("#panel .body > *", "els => els.map(e => e.className.split(' ')[0])")
    assert order[0] == "own-dicts" and order.count("sense") == 2
    page.locator("#panel .rg-dict a[data-link]").click()
    page.wait_for_function("() => (globalThis.__opened || []).length === 1")
    assert len(page.context.pages) == 1
    # F, held while the panel is open (vision.py), pressed in the game.
    page.wait_for_function("() => globalThis.__calls.some(([n, b]) => n === 'vision/looking' && b.panel && b.ask === 'f')")
    assert page.locator("#panel .keys .ai-key").count() == 1
    page.evaluate("() => globalThis.__push({ t: 'key', ask: true })")
    page.wait_for_selector("#panel .ask .verdict")
    asks = page.evaluate("() => globalThis.__asks")
    assert len(asks) == 1 and asks[0]["key"] == "面倒" and asks[0]["tok"] == 2
    assert page.locator("#panel .ai-key").count() == 0
    assert page.locator("#panel .vd-own b").inner_text() == "Your question"
    assert page.eval_on_selector_all("#panel .body > *", "els => els.map(e => e.className)")[-1] == "ask secondary"
    assert not errors, errors
