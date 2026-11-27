"""The dock in the app's windows (web/dock.js): the subtitles button and the game text menu, in a real Chromium.

The app's side is a stand-in in the page (web/dock-stub.js).  Skipped where there is no Chrome and Playwright.
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
STUB = Path(__file__).parent / "web" / "dock-stub.js"
SHOTS = Path(os.environ.get("SLUKA_SHOTS", "/home/claude/verify/dock"))
CHROME = shutil.which("google-chrome") or shutil.which("chromium")

playwright = pytest.importorskip("playwright.sync_api")
if not CHROME:
    pytest.skip("no Chrome here", allow_module_level=True)

PAGE = """<!doctype html><html><head><meta charset="utf-8"><script src="/stub.js"></script>
<script src="/__sluka__/dock.js"></script></head>
<body style="margin:0;background:%s;color:%s;font:16px system-ui">
<div style="position:fixed;top:12px;right:12px;display:flex;gap:8px">
  <button>Library</button><button>Settings</button></div>
<main style="padding:80px 40px">今日は友達と映画を見に行きます。</main></body></html>"""


class Site(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):  # noqa: N802
        path = self.path.split("?", 1)[0]
        if path == "/page.html":
            dark = "dark" in self.path
            body = PAGE % (("#1b1b1a", "#eee") if dark else ("#ffffff", "#222"))
            return self._send(body.encode("utf-8"), "text/html; charset=utf-8")
        if path == "/stub.js":
            return self._send(STUB.read_bytes(), "text/javascript")
        if path.startswith("/__sluka__/"):
            file = WEB / path[len("/__sluka__/"):]
            if file.is_file():
                return self._send(file.read_bytes(), "text/javascript")
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


def open_page(browser, site, query=""):
    context = browser.new_context(viewport={"width": 1100, "height": 760})
    page = context.new_page()
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto(f"{site}/page.html{query}")
    page.wait_for_function("() => document.querySelector('sluka-desktop-dock')?.shadowRoot?.querySelector('.dock')")
    return page, errors


def calls(page, name):
    return page.evaluate(f"() => globalThis.__calls.filter(([n]) => n === {name!r}).map(([, b]) => b)")


def change(page, script):
    """The app's state changed as ``script`` says (a function of S), and said to the page."""
    page.evaluate(f"() => {{ const S = globalThis.__S; {script}; globalThis.__bump(); }}")


def shot(page, name):
    SHOTS.mkdir(parents=True, exist_ok=True)
    page.screenshot(path=str(SHOTS / f"{name}.png"))


def test_the_dock_sits_at_the_bottom_left(browser, site):
    page, errors = open_page(browser, site)
    dock = page.locator("sluka-desktop-dock .dock")
    box = dock.bounding_box()
    # Bottom left, away from Sluka's own buttons at the top.
    assert box["x"] == pytest.approx(12, abs=1) and box["y"] + box["height"] == pytest.approx(760 - 12, abs=1)
    assert page.locator("sluka-desktop-dock .b").count() == 2
    # The subtitles button turns them on and off, as before.
    page.locator("sluka-desktop-dock .b.sub").click()
    page.wait_for_function("() => globalThis.__calls.some(([n]) => n === 'bar/toggle')")
    page.wait_for_function("() => document.querySelector('sluka-desktop-dock').shadowRoot.querySelector('.b.sub').getAttribute('aria-pressed') === 'true'")
    # Dragged elsewhere, it stays there, and the drag turned nothing.
    sub = page.locator("sluka-desktop-dock .b.sub").bounding_box()
    page.mouse.move(sub["x"] + 15, sub["y"] + 15)
    page.mouse.down()
    page.mouse.move(400, 300, steps=8)
    page.mouse.up()
    time.sleep(0.5)
    place = page.evaluate("() => JSON.parse(localStorage.getItem('sluka-desktop:dock'))")
    assert place["x"] == pytest.approx((400 - 15 - 3) / 1100, abs=0.01) and place["y"] == pytest.approx((300 - 15 - 3) / 760, abs=0.01)
    assert len(calls(page, "bar/toggle")) == 1
    page.reload()
    page.wait_for_function("() => document.querySelector('sluka-desktop-dock')?.shadowRoot?.querySelector('.dock')")
    moved = page.locator("sluka-desktop-dock .dock").bounding_box()
    assert moved["x"] == pytest.approx(place["x"] * 1100, abs=2) and moved["y"] == pytest.approx(place["y"] * 760, abs=2)
    # 0.6.0's own place for its button is not used again.
    page.evaluate("() => { localStorage.clear(); localStorage.setItem('sluka-desktop:bar-button', JSON.stringify({x: .9, y: .02})); }")
    page.reload()
    page.wait_for_function("() => document.querySelector('sluka-desktop-dock')?.shadowRoot?.querySelector('.dock')")
    assert page.locator("sluka-desktop-dock .dock").bounding_box()["y"] > 700
    assert page.evaluate("() => localStorage.getItem('sluka-desktop:bar-button')") is None
    assert not errors, errors


def test_without_game_text_and_in_another_corner(browser, site):
    page, errors = open_page(browser, site, "?games=no&corner=top-right")
    assert page.locator("sluka-desktop-dock .b").count() == 1
    box = page.locator("sluka-desktop-dock .dock").bounding_box()
    assert box["y"] == pytest.approx(12, abs=1) and box["x"] + box["width"] == pytest.approx(1100 - 12, abs=1)
    assert not errors, errors


def test_the_game_text_menu(browser, site):
    page, errors = open_page(browser, site)
    root = "sluka-desktop-dock"
    page.locator(f"{root} .b.game").click()
    panel = page.locator(f"{root} .panel")
    panel.wait_for(state="visible")
    assert panel.get_attribute("data-theme") == "light"
    # Above the dock, inside the window.
    box, dock = panel.bounding_box(), page.locator(f"{root} .dock").bounding_box()
    assert box["y"] + box["height"] <= dock["y"] and box["x"] >= 8 and box["y"] >= 0
    # The game first: Sluka's own engine is there, so the games are offered at once -- nothing to fetch.
    assert panel.locator(".tabs [aria-selected='true']").inner_text() == "Game"
    select = panel.locator("select[aria-label='The game']")
    select.wait_for()
    assert "Fetch" not in panel.inner_text()
    # The programs with a window, the one used before first.
    options = select.locator("option").all_inner_texts()
    assert options[1].startswith("★ 桜の詩 — sakura.exe") and "32-bit" in options[1] and "admingame.exe" in options[2]
    assert select.input_value() == "4242"

    # A game run as administrator: said so, and hooked as administrator when asked.
    select.select_option("77")
    panel.get_by_role("button", name="Hook", exact=True).click()
    panel.locator(".err:has-text('runs as administrator')").wait_for()
    admin = panel.get_by_role("button", name="Hook as administrator")
    admin.wait_for()
    shot(page, "menu-admin")
    admin.click()
    page.wait_for_function("() => globalThis.__calls.some(([n, b]) => n === 'games/attach' && b.pid === 77 && b.elevate === true)")
    panel.locator(".state .name").wait_for()
    assert "as administrator" in panel.locator(".state .how").inner_text()
    assert not admin.is_visible()
    panel.get_by_role("button", name="Let go").click()
    page.wait_for_function("() => globalThis.__calls.some(([n]) => n === 'games/detach')")

    select.select_option("4242")
    panel.get_by_role("button", name="Hook", exact=True).click()
    page.wait_for_function("() => globalThis.__calls.some(([n, b]) => n === 'games/attach' && b.pid === 4242)")
    panel.locator(".state .name:has-text('sakura.exe')").wait_for()
    assert panel.locator(".state .name").inner_text() == "桜の詩 — sakura.exe"
    assert "Hooking" in panel.locator(".state .how").inner_text()

    # The threads come: listed with what each said last, the one like dialogue marked; the game's engine is named.
    change(page, "S.game.state = 'attached'; S.game.engine = 'KiriKiri'; S.threads = ["
                 "{id: 1, name: 'KiriKiriZ', code: 'HW-4@55E0E:sakura.exe', text: '今日はいい天気ですね', lines: ['今日はいい天気ですね'], count: 3, last: 1},"
                 "{id: 2, name: 'GetGlyphOutlineW', code: 'HW@0:gdi32.dll:GetGlyphOutlineW', text: '今', lines: ['今'], count: 40, last: 1},"
                 "{id: 3, name: 'Menu', code: 'HS@1:sakura.exe', text: 'Load Save', lines: ['Load Save'], count: 9, last: 1}];"
                 "S.suggested = 1")
    rows = panel.locator("ol.threads > li")
    rows.nth(2).wait_for()
    assert rows.count() == 3
    assert rows.nth(0).locator(".line").inner_text() == "今日はいい天気ですね"
    assert rows.nth(0).locator(".tag").inner_text() == "looks like dialogue"
    assert rows.nth(1).locator(".nm").inner_text() == "GetGlyphOutlineW"
    assert "No thread is picked yet" in panel.inner_text()
    assert "KiriKiri" in panel.locator(".state .how").inner_text()
    shot(page, "menu-threads")
    # A click picks one; ticking another adds it.
    rows.nth(0).click()
    page.wait_for_function("() => globalThis.__calls.some(([n, b]) => n === 'games/select' && b.id === 1 && b.only)")
    page.wait_for_function(f"() => document.querySelector('{root}').shadowRoot.querySelector('li[data-id=\"1\"]').getAttribute('aria-selected') === 'true'")
    rows.nth(2).locator("input").check()
    page.wait_for_function("() => globalThis.__calls.some(([n, b]) => n === 'games/select' && b.id === 3 && b.on === true && !b.only)")
    page.wait_for_function(f"() => document.querySelector('{root}').shadowRoot.querySelectorAll('li[aria-selected=\"true\"]').length === 2")
    # More lines: the rows are the same rows, with the new text.
    change(page, "S.threads[0].text = '空がとても青い'; S.threads[0].count = 4; S.last = {text: '空がとても青い', at: Date.now() / 1000, from: 'game'}")
    page.wait_for_function(f"() => document.querySelector('{root}').shadowRoot.querySelector('li[data-id=\"1\"] .line').textContent === '空がとても青い'")
    assert panel.locator("footer .txt").inner_text() == "空がとても青い"
    shot(page, "menu-picked")

    # Windows' own text functions too, for this game.
    panel.locator("label:has-text('Read Windows’ text functions too') input").check()
    page.wait_for_function("() => globalThis.__calls.some(([n, b]) => n === 'games/pchooks' && b.on === true)")
    # The game's lines on the clipboard too: where it can be seen, under the threads.
    copy = panel.locator("label:has-text('Copy each line to the clipboard too') input")
    assert copy.is_visible()
    copy.check()
    page.wait_for_function("() => globalThis.__calls.some(([n, b]) => n === 'games/settings' && b.settings.copy === true)")

    # A hook code: a wrong one is said to be wrong, a right one is taken.
    code = panel.locator("input[aria-label='Hook code']")
    code.fill("HS 4@12")
    code.press("Enter")
    panel.locator(".err:has-text('not a hook code')").wait_for()
    code.fill("HS-4@1234:sakura.exe")
    panel.get_by_role("button", name="Add").click()
    page.wait_for_function("() => globalThis.__calls.some(([n, b]) => n === 'games/hookcode' && b.code === 'HS-4@1234:sakura.exe')")
    page.wait_for_function(f"() => document.querySelector('{root}').shadowRoot.querySelector(\"input[aria-label='Hook code']\").value === ''")

    # The settings: the engine's wait for the rest of a line, and the game's code page, as numbers.
    panel.locator("summary:has-text('Text settings')").click()
    panel.locator(".field:has-text('Wait for the rest of a line') select").select_option("800")
    page.wait_for_function("() => globalThis.__calls.some(([n, b]) => n === 'games/settings' && b.settings.flush_ms === 800)")
    codepage = panel.locator(".field:has-text('The game’s text is in') select")
    assert codepage.input_value() == "932" and "Japanese (Shift-JIS, 932)" in codepage.locator("option").all_inner_texts()
    codepage.select_option("936")
    page.wait_for_function("() => globalThis.__calls.some(([n, b]) => n === 'games/settings' && b.settings.codepage === 936)")
    text = panel.inner_text()
    assert "LunaHook, from LunaTranslator 12.1.3.12, in C:\\Sluka\\engine" in text and "running" in text
    shot(page, "menu-settings")

    # The clipboard.
    panel.locator(".tabs [data-mode='clipboard']").click()
    panel.locator("text=Watching the clipboard.").wait_for()

    panel.locator(".tabs [data-mode='off']").click()
    panel.locator("text=Sluka takes no text from games").wait_for()
    shot(page, "menu-off")

    # Escape closes it; the game button's dot says how it is going.
    page.keyboard.press("Escape")
    panel.wait_for(state="hidden")
    change(page, "S.mode = 'game'")
    page.wait_for_function(f"() => document.querySelector('{root}').shadowRoot.querySelector('.dot').dataset.tone === 'live'", timeout=8000)
    assert not errors, errors


def test_an_engine_an_antivirus_took_is_explained(browser, site):
    page, errors = open_page(browser, site, "?engine=broken")
    root = "sluka-desktop-dock"
    page.locator(f"{root} .b.game").click()
    panel = page.locator(f"{root} .panel")
    panel.wait_for(state="visible")
    panel.locator(".err:has-text('LunaHook32.dll')").wait_for()
    assert "GPL-3.0" in panel.inner_text() and "Protection history" in panel.inner_text()
    assert not panel.locator("select[aria-label='The game']").is_visible()
    page.wait_for_function("() => globalThis.__calls.some(([n]) => n === 'games/rescan')")  # looked at again as it opens
    shot(page, "menu-engine-missing")
    # Put back, and looked at again: the games are offered.
    page.evaluate("() => { globalThis.__fixed = true; }")
    panel.get_by_role("button", name="Look again").click()
    panel.locator("select[aria-label='The game']").wait_for()
    assert not panel.locator(".err:has-text('LunaHook32.dll')").is_visible()
    assert not errors, errors


def test_the_menu_on_a_dark_page(browser, site):
    page, errors = open_page(browser, site, "?dark=1")
    page.locator("sluka-desktop-dock .b.game").click()
    panel = page.locator("sluka-desktop-dock .panel")
    panel.wait_for(state="visible")
    assert panel.get_attribute("data-theme") == "dark"
    page.locator("sluka-desktop-dock select[aria-label='The game']").wait_for()
    shot(page, "menu-dark")
    # A click elsewhere in the page closes it.
    page.mouse.click(700, 200)
    panel.wait_for(state="hidden")
    assert not errors, errors


def test_the_screen_tab(browser, site):
    page, errors = open_page(browser, site)
    root = "sluka-desktop-dock"
    page.locator(f"{root} .b.game").click()
    panel = page.locator(f"{root} .panel")
    panel.wait_for(state="visible")
    # Five tabs, the screen's next to the game's, all in the menu's width.
    assert panel.locator(".tabs button").all_inner_texts() == ["Game", "Screen", "Clipboard", "Sluka Vision", "Off"]
    assert page.evaluate(f"() => {{ const t = document.querySelector('{root}').shadowRoot.querySelector('.tabs'); return t.scrollWidth <= t.clientWidth; }}")
    panel.locator(".tabs [data-mode='screen']").click()
    page.wait_for_function("() => globalThis.__calls.some(([n, b]) => n === 'games/mode' && b.mode === 'screen')")
    page.wait_for_function("() => globalThis.__calls.some(([n]) => n === 'games/ocr-engines')")
    readers = panel.locator("select[aria-label='Read with']")
    readers.wait_for()
    assert readers.locator("option").all_inner_texts() == [
        "Auto (the best one here)", "Sluka’s own — offline", "Windows’ OCR — offline", "Google Lens — online"]
    panel.locator(".note:has-text('Here: Sluka’s own OCR, offline, in the engine folder')").wait_for()
    assert panel.locator(".pill").inner_text() == "no box"
    shot(page, "screen-first")

    # The box: dragged, then read; what was read, and by which reader.
    select = panel.get_by_role("button", name="Select the text box", exact=True)
    select.click()
    page.wait_for_function("() => globalThis.__calls.some(([n]) => n === 'games/ocr-select')")
    panel.get_by_role("button", name="Dragging the box… (click here to stop)").wait_for()
    card = panel.locator("[data-pane='screen'] .card")
    card.locator(".name:has-text('桜の詩 — sakura.exe')").wait_for()
    how = card.locator(".how").inner_text()
    assert how.startswith("Reading · Sluka’s own OCR · 600×110 px"), how
    assert card.locator(".read").inner_text() == "今日はいい天気ですね\n散歩に行こうか"
    assert "Read just now in 0.1 s by Sluka’s own OCR." in card.inner_text()
    assert panel.locator(".pill").inner_text() == "reading"
    assert panel.get_by_role("button", name="Select another box").is_visible()
    assert "left out of screenshots and recordings" in panel.inner_text()
    assert "To have them in your recordings, read the game’s own window (Reading settings)" in panel.inner_text()
    change(page, "S.settings.ocr_capture = 'window'; S.screen.target.how = 'window'")
    panel.locator("p:has-text('The game’s own window is read: Sluka’s windows, the floating subtitles too, show in screenshots')").wait_for()
    change(page, "S.settings.ocr_capture = 'screen'; S.screen.target.how = 'screen'")
    shot(page, "screen-reading")
    panel.get_by_role("button", name="Read now").click()
    page.wait_for_function("() => globalThis.__calls.some(([n]) => n === 'games/ocr-once')")
    card.locator(".read:has-text('空がとても青い')").wait_for()
    panel.get_by_role("button", name="Stop", exact=True).click()
    page.wait_for_function("() => globalThis.__calls.some(([n]) => n === 'games/ocr-stop')")
    panel.get_by_role("button", name="Read", exact=True).wait_for()
    assert panel.get_by_role("button", name="Read now").is_disabled()
    panel.get_by_role("button", name="Read", exact=True).click()
    page.wait_for_function("() => globalThis.__calls.some(([n]) => n === 'games/ocr-start')")
    panel.get_by_role("button", name="Forget this box").click()
    page.wait_for_function("() => globalThis.__calls.some(([n]) => n === 'games/ocr-forget')")
    panel.get_by_role("button", name="Forget this box").wait_for(state="hidden")

    # The settings: when to read (and how often, every few seconds), the reader, Windows' OCR's language.
    panel.locator("summary:has-text('Reading settings')").click()
    often = panel.locator(".field:has-text('How often')")
    assert not often.is_visible()
    panel.locator(".field:has-text('When to read') select").select_option("interval")
    page.wait_for_function("() => globalThis.__calls.some(([n, b]) => n === 'games/settings' && b.settings.ocr_mode === 'interval')")
    often.wait_for()
    often.locator("select").select_option("3000")
    page.wait_for_function("() => globalThis.__calls.some(([n, b]) => n === 'games/settings' && b.settings.ocr_interval_ms === 3000)")
    language = panel.locator(".field:has-text('Windows’ OCR reads')")
    assert not language.is_visible()
    readers.select_option("windows")
    page.wait_for_function("() => globalThis.__calls.some(([n, b]) => n === 'games/settings' && b.settings.ocr_engine === 'windows')")
    language.wait_for()
    assert language.locator("option").all_inner_texts() == ["日本語 (ja)", "English (United States) (en-US)"]
    language.locator("select").select_option("en-US")
    page.wait_for_function("() => globalThis.__calls.some(([n, b]) => n === 'games/settings' && b.settings.ocr_lang === 'en-US')")
    panel.locator(".field:has-text('What is read') select").select_option("window")
    page.wait_for_function("() => globalThis.__calls.some(([n, b]) => n === 'games/settings' && b.settings.ocr_capture === 'window')")
    panel.locator("label:has-text('Leave out furigana') input").uncheck()
    page.wait_for_function("() => globalThis.__calls.some(([n, b]) => n === 'games/settings' && b.settings.ocr_furigana === false)")
    readers.select_option("lens")
    panel.locator(".note:has-text('Online: each picture of the box is sent to Google.')").wait_for()
    # The copy setting is the game's too: ticked here, ticked there.
    panel.locator("label:has-text('Copy each text read to the clipboard too') input").check()
    page.wait_for_function("() => globalThis.__calls.some(([n, b]) => n === 'games/settings' && b.settings.copy === true)")
    panel.locator(".tabs [data-mode='game']").click()
    page.wait_for_function(f"() => document.querySelector('{root}').shadowRoot.querySelector(\"[data-pane='game']\").textContent.includes('Copy each line')")
    assert panel.locator("label:has-text('Copy each line to the clipboard too') input").is_checked()
    panel.locator(".tabs [data-mode='screen']").click()
    shot(page, "screen-settings")
    page.keyboard.press("Escape")
    panel.wait_for(state="hidden")
    assert not errors, errors


def test_the_screen_tab_where_slukas_own_ocr_cannot_start(browser, site):
    page, errors = open_page(browser, site, "?ocr=old&mode=screen&dark=1")
    page.locator("sluka-desktop-dock .b.game").click()
    panel = page.locator("sluka-desktop-dock .panel")
    panel.wait_for(state="visible")
    assert panel.locator(".tabs [aria-selected='true']").inner_text() == "Screen"
    panel.locator(".note:has-text('Here: Windows’ OCR')").wait_for()
    readers = panel.locator("select[aria-label='Read with']")
    assert readers.locator("option").all_inner_texts()[1] == "Sluka’s own — offline (not here)"
    readers.select_option("builtin")
    note = panel.locator(".note[data-tone='bad']")
    note.wait_for()
    assert "14.40 or later" in note.inner_text()
    shot(page, "screen-old-runtime")
    assert not errors, errors


def test_keys_for_the_screen(browser, site):
    """The Screen tab's keys: set by pressing them in the menu, cleared, and what cannot be one said."""
    page, errors = open_page(browser, site, "?mode=screen")
    page.locator("sluka-desktop-dock .b.game").click()
    panel = page.locator("sluka-desktop-dock .panel")
    panel.wait_for(state="visible")
    keys = panel.locator("[data-pane='screen'] .keys")
    keys.wait_for()
    assert keys.locator(".keyrow > span").all_inner_texts() == ["Read the box now", "Select the text box", "Read a box once",
                                                                "Start or stop reading"]
    assert keys.locator(".key").all_inner_texts() == ["Set a key"] * 4
    assert "the game too" in keys.locator(".keyshead").inner_text()
    read = panel.get_by_role("button", name="Key: Read the box now")
    read.click()
    page.wait_for_function("() => globalThis.__calls.some(([n, b]) => n === 'games/ocr-keys-listen' && b.on === true)")
    assert read.inner_text() == "Press the keys… (Esc: none)"
    page.keyboard.press("Control+Shift+KeyR")
    page.wait_for_function("() => globalThis.__calls.some(([n, b]) => n === 'games/ocr-key' && b.action === 'read' && b.vk === 82 && b.ctrl && b.shift && !b.alt)")
    panel.get_by_role("button", name="Key: Read the box now").filter(has_text="Ctrl+Shift+R").wait_for()
    assert panel.get_by_role("button", name="No key for Read the box now").is_visible()
    # Escape while a key is awaited: none set, and the menu stays open.
    once = panel.get_by_role("button", name="Key: Read a box once")
    once.click()
    page.keyboard.press("Escape")
    page.wait_for_function("() => globalThis.__calls.some(([n, b]) => n === 'games/ocr-keys-listen' && b.on === false)")
    assert panel.is_visible() and once.inner_text() == "Set a key"
    # A key alone that types: said why not.
    panel.get_by_role("button", name="Key: Start or stop reading").click()
    page.keyboard.press("KeyP")
    panel.locator(".keys .note[data-tone='bad']:has-text('P alone types: take it with Ctrl or Alt.')").wait_for()
    # A function key alone is one; Ctrl+Alt with a letter is AltGr with it on many keyboards: said.
    once.click()
    page.keyboard.press("F8")
    once.filter(has_text="F8").wait_for()
    select = panel.get_by_role("button", name="Key: Select the text box")
    select.click()
    page.keyboard.press("Control+Alt+KeyS")
    select.filter(has_text="Ctrl+Alt+S").wait_for()
    panel.locator(".keys .note:has-text('AltGr+S types nothing')").wait_for()
    shot(page, "screen-keys")
    # None again.
    panel.get_by_role("button", name="No key for Read the box now").click()
    page.wait_for_function("() => globalThis.__calls.some(([n, b]) => n === 'games/ocr-key' && b.action === 'read' && b.clear)")
    panel.get_by_role("button", name="Key: Read the box now").filter(has_text="Set a key").wait_for()
    page.keyboard.press("Escape")
    panel.wait_for(state="hidden")
    assert not errors, errors


def test_the_sluka_vision_tab(browser, site):
    """Sluka Vision's tab: its reader (Google Lens first), how to begin, the window read and what was read, its keys."""
    page, errors = open_page(browser, site)
    root = "sluka-desktop-dock"
    page.locator(f"{root} .b.game").click()
    panel = page.locator(f"{root} .panel")
    panel.wait_for(state="visible")
    panel.locator(".tabs [data-mode='vision']").click()
    page.wait_for_function("() => globalThis.__calls.some(([n, b]) => n === 'games/mode' && b.mode === 'vision')")
    page.wait_for_function("() => globalThis.__calls.some(([n]) => n === 'games/vision-engines')")
    pane = panel.locator("[data-pane='vision']")
    readers = pane.locator("select[aria-label='Sluka Vision reads with']")
    readers.wait_for()
    assert readers.input_value() == "lens"
    pane.locator("option:has-text('Windows’ OCR — offline (not here)')").wait_for(state="attached")
    assert readers.locator("option").all_inner_texts() == ["Google Lens — online (best)", "Sluka’s own — offline",
                                                           "Windows’ OCR — offline (not here)"]
    # Google Lens not yet said yes to (lensask.py): the note says the question comes first.
    assert "Sluka asks first, before any picture of the game’s window goes to Google" in pane.locator(".note").first.inner_text()
    # How to begin: its key, pressed in the game, or the window chosen by a click.
    pane.locator("p.start:has-text('Press Alt+S in the game')").wait_for()
    assert panel.locator(".pill").inner_text() == "no window"
    keys = pane.locator(".keys")
    assert keys.locator(".keyrow > span").all_inner_texts() == ["Read the window", "Read by itself: on or off", "Put the words away",
                                                                "Pause the game: on or off", "Freeze the picture: on or off"]
    assert keys.locator(".key").all_inner_texts() == ["Alt+S", "Set a key", "Alt+V", "Alt+P", "Alt+F"]
    assert pane.locator("label:has-text('Read again by itself as the window changes') input").is_checked()
    assert "exclusive full screen" in pane.inner_text()
    # Read off the screen: its words are left out of screenshots and recordings, and the menu says how to have them.
    assert "To have them in your recordings, read the game’s own window" in pane.inner_text()
    # (and its setting says what reading the game's own window does)
    assert pane.locator("small:has-text('The game’s own window: its words show in screenshots and recordings')").count() == 1
    change(page, "S.settings.vision_capture = 'window'; S.vision.capture = 'window'")
    pane.locator("p:has-text('The game’s own window is read: Sluka Vision’s words show in screenshots and recordings')").wait_for()
    change(page, "S.vision.capture = 'screen'")  # (its own window gives no picture of itself: the screen is read)
    pane.locator("p:has-text('left out of screenshots and recordings')").wait_for()
    change(page, "S.settings.vision_capture = 'screen'; S.vision.capture = ''")
    shot(page, "vision-first")
    pane.get_by_role("button", name="Choose the window", exact=True).click()
    page.wait_for_function("() => globalThis.__calls.some(([n]) => n === 'games/vision-pick')")
    pane.locator("button:has-text('Click on the game’s window now')").wait_for()

    # A window read: its name, how it is read, what was read last.
    change(page, "S.vision.picking = 0; S.vision.target = {hwnd: 42420, pid: 4242, title: '桜の詩', exe: 'sakura.exe', class: 'GameWindow', "
                 "client: [0, 0, 1280, 720]}; S.vision.status = {state: 'waiting', text: ''}; S.vision.shown = true; "
                 "S.vision.last = {at: Date.now() / 1000 - 3, ms: 840, lines: 4, engine: 'lens', why: 'key', "
                 "text: '今日はいい天気ですね / 縦書きの行です / 何で公衆電話に？ / わかった'}")
    pane.locator(".name:has-text('桜の詩 — sakura.exe')").wait_for()
    how = pane.locator(".boxstate .how").inner_text()
    assert "Watching the window" in how and "reads by itself as it changes" in how
    assert pane.locator(".read").inner_text().startswith("今日はいい天気ですね")
    assert "4 lines read" in pane.locator(".card .small").inner_text() and "by Google Lens" in pane.locator(".card .small").inner_text()
    assert panel.locator(".pill").inner_text() == "watching"
    pane.get_by_role("button", name="Read again", exact=True).click()
    page.wait_for_function("() => globalThis.__calls.some(([n]) => n === 'games/vision-read')")
    # The game stopped where it is, from the menu as by its keys: paused, or only its picture kept.
    pane.get_by_role("button", name="Pause the game (Alt+P)", exact=True).click()
    page.wait_for_function("() => globalThis.__calls.some(([n, b]) => n === 'games/vision-freeze' && b.mode === 'pause')")
    change(page, "S.vision.frozen = 'pause'")
    pane.get_by_role("button", name="Go on (Alt+P)", exact=True).wait_for()
    assert "the game is paused" in pane.locator(".boxstate .how").inner_text()
    shot(page, "vision-paused")
    change(page, "S.vision.frozen = 'picture'")
    pane.get_by_role("button", name="Let the picture go (Alt+F)", exact=True).click()
    page.wait_for_function("() => globalThis.__calls.some(([n, b]) => n === 'games/vision-freeze' && b.mode === 'picture')")
    assert "its picture is frozen" in pane.locator(".boxstate .how").inner_text()
    change(page, "S.vision.frozen = ''")
    pane.get_by_role("button", name="Put away", exact=True).click()
    page.wait_for_function("() => globalThis.__calls.some(([n]) => n === 'games/vision-clear')")
    # Reading by itself turned off from the menu.
    pane.locator("label:has-text('Read again by itself as the window changes') input").uncheck()
    page.wait_for_function("() => globalThis.__calls.some(([n, b]) => n === 'games/settings' && b.settings.vision_auto === false)")
    # A key set by pressing it, sent as Sluka Vision's.
    pane.get_by_role("button", name="Key: Read by itself: on or off").click()
    page.wait_for_function("() => globalThis.__calls.some(([n, b]) => n === 'games/vision-keys-listen' && b.on === true)")
    page.keyboard.press("Alt+KeyA")
    page.wait_for_function("() => globalThis.__calls.some(([n, b]) => n === 'games/vision-key' && b.action === 'auto' && b.vk === 65 && b.alt)")
    shot(page, "vision-window")
    # Reading: said; a reader that failed: said, in red.
    change(page, "S.vision.status = {state: 'failed', text: 'Google Lens answered 429'}; S.vision.error = 'The window could not be read: Google Lens answered 429'")
    pane.locator(".boxstate .how[data-tone='bad']").wait_for()
    assert "429" in pane.locator(".boxstate .how").inner_text()
    shot(page, "vision-failed")
    page.keyboard.press("Escape")
    panel.wait_for(state="hidden")
    assert not errors, errors
