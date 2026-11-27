"""Sluka Vision: a game's whole window read (ocrd.py's VisionWatch, with a stand-in for Google that reads and answers
Google Lens' own protocol buffers), its words laid over it by the app (vision.py) in a window of their own
(winshell.py), as the Sluka Vision tab of the game text menu has it -- end to end on a pretend screen.

What Google "reads" off a picture the stand-in reads off its first row, as the other readers' stand-ins do (fake_ocr.h):
"@v;" before a line makes it a column of vertical text, "@a<radians>;" tilts it, "@p<n>;" puts lines in one paragraph.
"""

from __future__ import annotations

import io
import json
import math
import time
import urllib.request
from pathlib import Path
from types import SimpleNamespace

import pytest

import fakes  # (puts the app on the path)
import ocrfake
from sluka_desktop import gametext, ocrd, vision
from sluka_desktop.host import Request
from test_gametext import ask, wait_for
from test_ocr import FakeKeys, Reader, app, keys  # noqa: F401  (app, keys: fixtures)

from conftest import CLIENT  # noqa: E402  (the game window's inside, on the screen)

# What the game shows (in its window): a line with its furigana over it, a column of vertical text, and Persona's
# slanted reply.
SHOWN = [(20, 40, 240, 36, "今日はいい天気ですね"), (20, 20, 120, 14, "きょうは"), (300, 100, 30, 240, "@v;縦書きの行です"),
         (380, 300, 160, 32, "@a-0.09;何で公衆電話に")]
LATER = [(20, 40, 240, 36, "明日も晴れるといいね"), (300, 100, 30, 240, "@v;縦書きの行です"), (380, 300, 160, 32, "@a-0.09;何で公衆電話に")]


# ---------------------------------------------------------------- the pieces


def test_lens_is_asked_and_its_answer_read_as_chromium_defines_them():
    request = ocrd.lens_request(b"\x89PNG...", 640, 360, 2 ** 63 + 5, b"N" * 16)
    objects = ocrfake.pb_read(ocrfake.pb_read(request)[1][0])
    context, image = ocrfake.pb_read(objects[1][0]), ocrfake.pb_read(objects[3][0])
    request_id, client = ocrfake.pb_read(context[3][0]), ocrfake.pb_read(context[4][0])
    assert request_id[1] == [2 ** 63 + 5] and request_id[4] == [b"N" * 16]
    assert client[1] == [3] and client[2] == [4] and client[4] == [b""]  # the web, Chromium, a locale
    assert ocrfake.pb_read(ocrfake.pb_read(client[17][0])[1][0])[1] == [7]  # Lens' own filter
    assert ocrfake.pb_read(image[1][0])[1] == [b"\x89PNG..."]
    assert ocrfake.pb_read(image[3][0]) == {1: [640], 2: [360]}

    answer = ocrfake.lens_answer(["10,20,200,30,今日は いい天気", "300,40,20,200,@v;縦書きの行", "50,100,120,24,@a0.2;@p1;斜めの一行",
                                  "50,130,120,24,@p1;続きの行"], 640, 360)
    paragraphs = ocrd.lens_layout(answer, (640, 360), (640, 360))
    assert [p["dir"] for p in paragraphs] == [ocrd.LEFT_TO_RIGHT, ocrd.TOP_TO_BOTTOM, ocrd.LEFT_TO_RIGHT]
    first = paragraphs[0]["lines"][0]
    assert first["text"] == "今日は いい天気" and first["box"] == pytest.approx([110, 35, 200, 30, 0], abs=0.2)
    # Each word by where it is in the line's text (JavaScript's count), and where Lens saw it.
    assert [w[:2] for w in first["words"]] == [[0, 3], [4, 8]]
    assert first["words"][0][2] == pytest.approx([10 + 200 * 3 / 8 / 2, 35, 200 * 3 / 8, 30, 0], abs=0.2)
    tilted = paragraphs[2]["lines"]
    assert [line["text"] for line in tilted] == ["斜めの一行", "続きの行"] and tilted[0]["box"][4] == pytest.approx(0.2, abs=1e-4)
    # In a window twice as large as the picture sent, everything twice as far and as large.
    twice = ocrd.lens_layout(answer, (640, 360), (1280, 720))
    assert twice[0]["lines"][0]["box"] == pytest.approx([220, 70, 400, 60, 0], abs=0.3)
    # As the overlay has them: words along their lines, columns right to left, in reading order.
    lines = ocrd.vision_lines(paragraphs)
    assert [(line["i"], line["p"], line["v"], line["text"]) for line in lines] == [
        (0, 0, False, "今日は いい天気"), (1, 1, True, "縦書きの行"), (2, 2, False, "斜めの一行"), (3, 2, False, "続きの行")]
    assert lines[0]["words"] == [[0, 3, 0.0, 75.0], [4, 8, 100.0, 200.0]]
    assert lines[1]["words"][0][:2] == [0, 2] and lines[1]["words"][0][2:] == pytest.approx([0, 80], abs=0.2)
    assert lines[2]["words"][0][2:] == pytest.approx([0, 120 * 2 / 5], abs=0.3)  # (measured along the tilt)
    # An answer with an error and no text, and one cut short.
    with pytest.raises(RuntimeError, match="error"):
        ocrd.lens_layout(ocrfake.pb_bytes(1, ocrfake.pb_number(1, 1)), (1, 1), (1, 1))
    with pytest.raises(ValueError):
        ocrd.lens_layout(b"\x12\xff\x01", (1, 1), (1, 1))
    assert ocrd.lens_layout(b"", (1, 1), (1, 1)) == []


def test_furigana_and_columns():
    def line(text, box, v=False, p=0):
        return {"text": text, "box": box, "words": []}, {"dir": ocrd.TOP_TO_BOTTOM if v else 0, "p": p}

    para = lambda *lines, v=False: {"dir": ocrd.TOP_TO_BOTTOM if v else 0, "box": None, "lines": list(lines)}  # noqa: E731
    over = {"text": "きょう", "box": [60, 27, 80, 12, 0], "words": []}
    main = {"text": "今日は晴れ", "box": [120, 50, 200, 30, 0], "words": []}
    kana = {"text": "ひらがなだけの行", "box": [120, 90, 200, 30, 0], "words": []}
    small_ui = {"text": "セーブ", "box": [500, 20, 40, 12, 0], "words": []}
    # Tilted together, as Persona tilts them: the furigana measured as its line is.
    tilt = 0.2
    cx, cy = 400 + (-60) * math.cos(tilt) - (-22) * math.sin(tilt), 300 + (-60) * math.sin(tilt) + (-22) * math.cos(tilt)
    slanted = {"text": "面倒くさい", "box": [400, 300, 200, 30, tilt], "words": []}
    slanted_ruby = {"text": "めんどう", "box": [cx, cy, 80, 12, tilt], "words": []}
    # A column, its furigana right of it.
    column = {"text": "縦書き", "box": [700, 200, 30, 120, 0], "words": []}
    column_ruby = {"text": "たてが", "box": [722, 180, 12, 50, 0], "words": []}
    left_column = {"text": "二列目", "box": [650, 200, 30, 120, 0], "words": []}
    paragraphs = [para(over, main), para(kana), para(small_ui), para(slanted_ruby, slanted),
                  para(left_column, column, column_ruby, v=True)]
    kept = [line["text"] for line in ocrd.vision_lines(paragraphs)]
    assert kept == ["今日は晴れ", "ひらがなだけの行", "セーブ", "面倒くさい", "縦書き", "二列目"]
    every = [line["text"] for line in ocrd.vision_lines(paragraphs, furigana=False)]
    assert every == ["きょう", "今日は晴れ", "ひらがなだけの行", "セーブ", "めんどう", "面倒くさい", "たてが", "縦書き", "二列目"]


def test_pictures_for_lens():
    w, h = 61, 37
    data = bytes((x * 7 + y * 13 + c * 50) % 256 for y in range(h) for x in range(w) for c in range(4))
    img = ocrd.Image(w, h, data)
    from PIL import Image as PILImage

    assert PILImage.open(io.BytesIO(ocrd.to_png_up(img))).convert("RGB").tobytes() == img.rgb()
    assert len(ocrd.to_png_up(ocrd.Image(1, 1, b"\1\2\3\0"))) > 0
    small = img.shrunk(20, 10)
    assert (small.w, small.h) == (20, 10)
    # Each pixel the one nearest it.
    x, y = 7, 4
    sx, sy = int((x + 0.5) * w / 20), int((y + 0.5) * h / 10)
    assert small.data[(y * 20 + x) * 4:(y * 20 + x) * 4 + 4] == data[(sy * w + sx) * 4:(sy * w + sx) * 4 + 4]
    assert img.shrunk(100, 100) is img and img.shrunk(1, 1).w == 1
    # A full HD window goes as it is; a larger one is made smaller (LensReader.layout).
    for size, sent in (((1920, 1080), (1920, 1080)), ((2560, 1440), (1920, 1080)), ((3840, 2160), (1920, 1080)),
                       ((1080, 1920), (1080, 1920)), ((2400, 1200), (1920, 960))):
        scale = min(1.0, ocrd.LENS_SIDE / max(size), math.sqrt(ocrd.LENS_AREA / (size[0] * size[1])))
        assert (round(size[0] * scale), round(size[1] * scale)) == sent
    # The likeness the watch compares: sixteen samples of a cell's green each.
    cols, rows, cells = ocrd.cells_of(ocrd.Image(100, 50, bytes(100 * 50 * 4)), 24, 4)
    assert (cols, rows, len(cells), len(cells[0])) == (4, 2, 8, 16)
    # Other readers' boxes: four corners (tilted as the first side is), or two.
    assert ocrd._quad_box((10, 10, 110, 10, 110, 40, 10, 40)) == [60.0, 25.0, 100.0, 30.0, 0.0]
    assert ocrd._quad_box((10, 10, 10, 110, -20, 110, -20, 10)) == [-5.0, 60.0, 30.0, 100.0, 0.0]
    assert ocrd._quad_box((0, 0, 50, 20)) == [25.0, 10.0, 50.0, 20.0, 0.0]
    assert ocrd._quad_box(("x",)) is None and ocrd._quad_box((5, 5, 5, 5)) is None
    found = ocrd.paragraphs_of([((10, 10, 40, 10, 40, 200, 10, 200), "縦の行"), ((0, 0, 100, 20), "横の行")])
    assert [p["dir"] for p in found] == [ocrd.TOP_TO_BOTTOM, ocrd.LEFT_TO_RIGHT]


# ---------------------------------------------------------------- the screen reader's side


def start(r, **more):
    params = {"engine": "lens", "auto": False, "allow": [1000], "furigana": True}
    params.update(more)
    r.send(cmd="vision-start", **params)


def layouts(r):
    return r.seen(ev="vision-layout")


def test_the_window_in_front_is_read_whole(ocr):
    r = Reader(ocr)
    ocr.screen.text(CLIENT, SHOWN)
    start(r)
    # Its key, pressed in the game: the window in front is the one, and is read.
    r.send(cmd="vision-read", front=True, exclude=[1000])
    wait_for(lambda: layouts(r), timeout=15)
    window = r.seen(ev="vision-window")[-1]["window"]
    assert window["hwnd"] == 42420 and window["pid"] == 4242 and window["client"] == list(CLIENT)
    layout = layouts(r)[-1]
    assert layout["area"] == list(CLIENT) and layout["size"] == [700, 500] and layout["engine"] == "lens" and layout["why"] == "key"
    lines = layout["lines"]
    # The furigana left out; the column a column; the slanted line slanted; each word where Lens saw it.
    assert [line["text"] for line in lines] == ["今日はいい天気ですね", "縦書きの行です", "何で公衆電話に"]
    assert lines[0]["box"] == pytest.approx([140, 58, 240, 36, 0], abs=0.3) and not lines[0]["v"]
    assert lines[1]["v"] and lines[1]["box"] == pytest.approx([315, 220, 30, 240, 0], abs=0.3)
    assert lines[2]["box"][4] == pytest.approx(-0.09, abs=1e-4)
    assert [w[:2] for w in lines[0]["words"]] == [[0, 2], [2, 4], [4, 6], [6, 8], [8, 10]]
    assert lines[0]["words"][1][2:] == pytest.approx([48, 96], abs=0.3)
    # Google was asked as Chromium asks: its own protocol buffers, the window's whole picture.
    asked = ocr.lens.requests[-1]
    assert asked["kind"] == "protobuf" and (asked["w"], asked["h"]) == (700, 500) and asked["png"] == (700, 500)
    assert (asked["platform"], asked["surface"], asked["filter"], asked["nonce"]) == (3, 4, 7, 16)
    assert asked["headers"]["X-Goog-Api-Key"] == ocrd.LensReader.KEY
    # Asked from Sluka's own window (the menu's button): the window chosen before.
    ocr.screen.put(foreground=1000)
    r.send(cmd="vision-read", front=True, exclude=[1000])
    wait_for(lambda: len(layouts(r)) == 2, timeout=15)
    assert layouts(r)[-1]["why"] == "key" and len(r.seen(ev="vision-window")) == 1
    r.close()


def test_read_again_as_the_window_changes(ocr):
    r = Reader(ocr)
    ocr.screen.text(CLIENT, SHOWN)
    start(r, auto=True)
    r.send(cmd="vision-read", front=True, exclude=[1000])
    wait_for(lambda: len(layouts(r)) == 1, timeout=15)
    first = layouts(r)[0]
    asked = len(ocr.lens.requests)
    # Nothing changes: nothing is read again.
    time.sleep(2.0)
    assert len(ocr.lens.requests) == asked and not r.seen(ev="vision-stale")
    # The next line: the words of the one before go at once (only its), and once the window has settled it is read again.
    ocr.screen.text(CLIENT, LATER)
    wait_for(lambda: r.seen(ev="vision-stale"), timeout=10)
    gone = r.seen(ev="vision-stale")[0]["lines"]
    assert 0 in gone and 1 not in gone
    wait_for(lambda: len(layouts(r)) == 2, timeout=15)
    second = layouts(r)[1]
    assert second["why"] == "auto" and second["id"] == first["id"] + 1
    assert [line["text"] for line in second["lines"]] == ["明日も晴れるといいね", "縦書きの行です", "何で公衆電話に"]
    # Turned off: a change is not read (its words still go).
    r.send(cmd="vision-auto", on=False)
    time.sleep(0.4)
    ocr.screen.text(CLIENT, SHOWN)
    wait_for(lambda: len(r.seen(ev="vision-stale")) == 2, timeout=10)
    time.sleep(2.0)
    assert len(layouts(r)) == 2
    r.close()


# The first line's place on the screen (SHOWN's, in the game's window at CLIENT).
FIRST_LINE = (CLIENT[0] + 20, CLIENT[1] + 40, 240, 36)
THIRD_LINE = (CLIENT[0] + 380, CLIENT[1] + 300, 160, 32)


def paint(screen, box, grey):
    """A patch of one grey over what the screen shows there (a game's button lit, or one frame of its animation)."""
    x, y, w, h = box
    for row in range(y, y + h):
        at = (row * screen.w + x) * 4
        screen.pixels[at:at + w * 4] = bytes((grey, grey, grey, 0)) * w
    screen.save()


def test_text_that_moves_in_place_keeps_its_words(ocr):
    r = Reader(ocr)
    ocr.screen.text(CLIENT, SHOWN)
    start(r)
    r.send(cmd="vision-read", front=True, exclude=[1000])
    wait_for(lambda: layouts(r), timeout=15)
    # A button's animation over the first line, frame after frame (each of the five unlike the others): what is under
    # its words keeps changing, and they stay.
    frames = [None, 60, 110, 160, 210]
    end = time.monotonic() + 4.0
    n = 0
    while time.monotonic() < end:
        ocr.screen.text(CLIENT, SHOWN)
        if frames[n % 5] is not None:
            paint(ocr.screen, FIRST_LINE, frames[n % 5])
        n += 1
        time.sleep(0.1)
    assert not r.seen(ev="vision-stale")
    # It stops as it was read: nothing goes.
    ocr.screen.text(CLIENT, SHOWN)
    time.sleep(1.5)
    assert not r.seen(ev="vision-stale")
    # Moving again, and stopping otherwise than it was read: once it has kept still (and is no more taken for a
    # picture that moves by itself), its words go -- only its.
    end = time.monotonic() + 2.0
    while time.monotonic() < end:
        ocr.screen.text(CLIENT, SHOWN)
        paint(ocr.screen, FIRST_LINE, frames[1 + n % 4])
        n += 1
        time.sleep(0.1)
    paint(ocr.screen, FIRST_LINE, 200)
    wait_for(lambda: r.seen(ev="vision-stale"), timeout=10)
    assert r.seen(ev="vision-stale")[0]["lines"] == [0]
    r.close()


def test_a_line_lit_and_dark_again_goes_and_comes_back(ocr):
    r = Reader(ocr)
    ocr.screen.text(CLIENT, SHOWN)
    start(r)
    r.send(cmd="vision-read", front=True, exclude=[1000])
    wait_for(lambda: layouts(r), timeout=15)
    # Lit, and kept lit (a button the pointer is over): changed and still, its words go within a second ...
    lit = time.monotonic()
    paint(ocr.screen, FIRST_LINE, 200)
    wait_for(lambda: r.seen(ev="vision-stale"), timeout=5)
    assert time.monotonic() - lit < 2.0 and r.seen(ev="vision-stale")[0]["lines"] == [0]
    # ... and dark again, as it was read: they are back.
    ocr.screen.text(CLIENT, SHOWN)
    wait_for(lambda: r.seen(ev="vision-back"), timeout=5)
    assert r.seen(ev="vision-back")[0]["lines"] == [0]
    # Something else in its place (the next line): gone again, and not back.
    ocr.screen.text(CLIENT, LATER)
    wait_for(lambda: len(r.seen(ev="vision-stale")) == 2, timeout=5)
    assert r.seen(ev="vision-stale")[1]["lines"] == [0]
    time.sleep(1.0)
    assert len(r.seen(ev="vision-back")) == 1
    r.close()


def test_what_is_looked_at_alone_is_not_read_again_by_itself(ocr):
    r = Reader(ocr)
    ocr.screen.text(CLIENT, SHOWN)
    start(r, auto=True)
    r.send(cmd="vision-read", front=True, exclude=[1000])
    wait_for(lambda: len(layouts(r)) == 1, timeout=15)
    first = layouts(r)[0]
    asked = len(ocr.lens.requests)
    # The pointer on a word of the first line, whose button it lights: its words go (the page keeps the one pointed
    # at), and the window is not read again meanwhile.
    r.send(cmd="vision-hold", read=first["id"], lines=[0])
    time.sleep(0.3)
    paint(ocr.screen, FIRST_LINE, 200)
    wait_for(lambda: r.seen(ev="vision-stale"), timeout=5)
    time.sleep(2.5)
    assert len(ocr.lens.requests) == asked and len(layouts(r)) == 1
    # Let go of with the button still lit: what changed is read now.
    r.send(cmd="vision-hold", read=0, lines=[])
    wait_for(lambda: len(layouts(r)) == 2, timeout=10)
    second = layouts(r)[1]
    assert second["why"] == "auto"
    # Held again: what changes elsewhere is read all the same.
    r.send(cmd="vision-hold", read=second["id"], lines=[0])
    time.sleep(0.3)
    ocr.screen.text(CLIENT, SHOWN)
    paint(ocr.screen, FIRST_LINE, 200)
    paint(ocr.screen, THIRD_LINE, 90)
    wait_for(lambda: len(layouts(r)) == 3, timeout=10)
    # (a hold of a read before is no hold of this one's lines)
    r.send(cmd="vision-hold", read=first["id"], lines=[0])
    time.sleep(0.3)
    ocr.screen.text(CLIENT, SHOWN)
    paint(ocr.screen, FIRST_LINE, 120)
    wait_for(lambda: len(layouts(r)) == 4, timeout=10)
    r.close()


def test_how_the_window_is_read_is_said(ocr):
    r = Reader(ocr)
    ocr.screen.text(CLIENT, SHOWN)
    # Read off the screen: said so (Sluka's windows are then to be left out of its pictures).
    start(r)
    r.send(cmd="vision-read", front=True, exclude=[1000])
    wait_for(lambda: layouts(r), timeout=15)
    assert [e["how"] for e in r.seen(ev="vision-capture")] == ["screen"]
    r.close()
    # The game's own window: said so before its first read (and so before its words are laid over it).
    r = Reader(ocr)
    start(r, capture="window")
    r.send(cmd="vision-read", front=True, exclude=[1000])
    wait_for(lambda: layouts(r), timeout=15)
    events = [e["ev"] for e in r.events if e.get("ev") in ("vision-capture", "vision-layout")]
    assert events[:2] == ["vision-capture", "vision-layout"] and r.seen(ev="vision-capture")[0]["how"] == "window"
    # It gives no picture of itself for a while (a black screen, say): the screen is read, and said so at once ...
    ocr.screen.put(blank=["window"])
    wait_for(lambda: r.seen(ev="vision-capture")[-1]["how"] == "screen", timeout=5)
    # ... its own picture again: said once it has given one for a moment (no blinking in and out of recordings).
    ocr.screen.put(blank=[])
    back = time.monotonic()
    wait_for(lambda: r.seen(ev="vision-capture")[-1]["how"] == "window", timeout=8)
    assert time.monotonic() - back >= 1.5
    assert [e["how"] for e in r.seen(ev="vision-capture")] == ["window", "screen", "window"]
    # Set otherwise: said again.
    r.send(cmd="vision-settings", capture="screen")
    wait_for(lambda: r.seen(ev="vision-capture")[-1]["how"] == "screen", timeout=5)
    r.close()


def test_the_taskbar_is_never_the_game(ocr):
    r = Reader(ocr)
    ocr.screen.text(CLIENT, SHOWN)
    # The taskbar in front when the key is pressed (the game was just gone back to): no window yet, and so none read.
    ocr.screen.window(777, 9000, (0, 860, 1600, 40), title="", klass="Shell_TrayWnd")
    ocr.screen.put(foreground=9000)
    start(r)
    r.send(cmd="vision-read", front=True, exclude=[1000])
    wait_for(lambda: r.seen(ev="vision-error"), timeout=10)
    assert "no window to read" in r.seen(ev="vision-error")[-1]["text"] and not r.seen(ev="vision-window")
    # The game in front: it is the one; the taskbar in front again: still the game.
    ocr.screen.put(foreground=4242)
    r.send(cmd="vision-read", front=True, exclude=[1000])
    wait_for(lambda: layouts(r), timeout=15)
    ocr.screen.put(foreground=9000)
    r.send(cmd="vision-read", front=True, exclude=[1000])
    wait_for(lambda: len(layouts(r)) == 2, timeout=15)
    assert [w["window"]["hwnd"] for w in r.seen(ev="vision-window")] == [42420]
    # Nor is it ever the window "Choose the window" takes.
    r.send(cmd="vision-pick", seconds=1.5, exclude=[1000])
    wait_for(lambda: r.seen(ev="vision-picked"), timeout=5)
    assert r.seen(ev="vision-picked")[-1]["window"] is None
    r.close()


def test_a_picture_kept_in_place_of_the_window(ocr, tmp_path):
    """Sluka Vision frozen (the game paused, or its picture only): the window's picture taken at once and kept, written
    for the app to lay over the game; looked at in place of the window, which may go on behind it unread; read where
    its words are not those shown; and once let go of, the window as it is compared with what was read off it."""
    r = Reader(ocr)
    ocr.screen.text(CLIENT, SHOWN)
    start(r, auto=True)
    r.send(cmd="vision-read", front=True, exclude=[1000])
    wait_for(lambda: len(layouts(r)) == 1, timeout=15)
    still = tmp_path / "still.bmp"
    r.send(cmd="vision-freeze", on=True, path=str(still))
    wait_for(lambda: r.seen(ev="vision-frozen"), timeout=10)
    told = r.seen(ev="vision-frozen")[-1]
    assert told["on"] is True and told["path"] == str(still) and told["size"] == [700, 500] and told["area"] == list(CLIENT)
    picture = ocrd.from_bmp(still.read_bytes())
    assert (picture.w, picture.h) == (700, 500) and not picture.blank()
    # What was read is what the picture shows: not read again.
    time.sleep(1.5)
    assert len(layouts(r)) == 1
    # The game goes on behind the picture: neither looked at nor read.
    asked = len(ocr.lens.requests)
    ocr.screen.text(CLIENT, LATER)
    time.sleep(2.0)
    assert len(ocr.lens.requests) == asked and not r.seen(ev="vision-stale") and len(layouts(r)) == 1
    # Its key: the picture read, not the window.
    r.send(cmd="vision-read", front=True, exclude=[1000])
    wait_for(lambda: len(layouts(r)) == 2, timeout=15)
    assert layouts(r)[-1]["lines"][0]["text"] == "今日はいい天気ですね"
    # Let go of: the window as it is now is not what was read -- its words go, and it is read again by itself.
    r.send(cmd="vision-freeze", on=False)
    wait_for(lambda: r.seen(ev="vision-frozen")[-1]["on"] is False, timeout=10)
    wait_for(lambda: r.seen(ev="vision-stale"), timeout=10)
    wait_for(lambda: len(layouts(r)) == 3, timeout=15)
    assert layouts(r)[-1]["why"] == "auto" and layouts(r)[-1]["lines"][0]["text"] == "明日も晴れるといいね"
    # Frozen where the words shown are not those of the window now (read by its key alone): the picture is read at once.
    r.send(cmd="vision-auto", on=False)
    time.sleep(0.4)
    ocr.screen.text(CLIENT, SHOWN)
    time.sleep(1.0)
    r.send(cmd="vision-freeze", on=True, path=str(still))
    wait_for(lambda: len(layouts(r)) == 4, timeout=15)
    assert layouts(r)[-1]["why"] == "freeze" and layouts(r)[-1]["lines"][0]["text"] == "今日はいい天気ですね"
    # The window gone meanwhile: the picture is let go of too.
    r.send(cmd="vision-freeze", on=False)
    r.close()


def test_the_game_behind_minimized_and_gone(ocr):
    r = Reader(ocr)
    ocr.screen.text(CLIENT, SHOWN)
    start(r)
    r.send(cmd="vision-read", front=True, exclude=[1000])
    wait_for(lambda: layouts(r), timeout=15)
    assert r.seen(ev="vision-front")[-1]["on"] is True and r.seen(ev="vision-area")[-1]["area"] == list(CLIENT)
    assert r.seen(ev="vision-front")[-1]["game"] is True
    # Another program in front: the words are not to be seen; Sluka's own window in front: they are (but it is not
    # the game itself, whose keys an open panel takes).
    ocr.screen.put(foreground=5)
    wait_for(lambda: r.seen(ev="vision-front")[-1]["on"] is False)
    assert r.seen(ev="vision-front")[-1]["game"] is False
    ocr.screen.put(foreground=1000)
    wait_for(lambda: r.seen(ev="vision-front")[-1]["on"] is True)
    assert r.seen(ev="vision-front")[-1]["game"] is False
    ocr.screen.put(foreground=4242)
    wait_for(lambda: r.seen(ev="vision-front")[-1] == {"ev": "vision-front", "on": True, "game": True, "why": ""})
    # Moved: told where (its words with it: what it shows is where it was in it); made larger: the words read before
    # go, all of them.  (This pretend screen does not move what a window shows with it.)
    ocr.screen.window(42420, 4242, (60, 70, 700, 500))
    wait_for(lambda: r.seen(ev="vision-area")[-1]["area"] == [60, 70, 700, 500])
    time.sleep(0.5)
    assert not r.seen(ev="vision-stale", all=True)
    ocr.screen.window(42420, 4242, (60, 70, 720, 500))
    wait_for(lambda: r.seen(ev="vision-stale", all=True))
    ocr.screen.window(42420, 4242, (60, 70, 720, 500), minimized=True)
    wait_for(lambda: r.seen(ev="vision-front")[-1] == {"ev": "vision-front", "on": False, "game": False, "why": "minimized"})
    ocr.screen.window(42420, 4242, (60, 70, 720, 500), minimized=False, gone=True)
    wait_for(lambda: r.seen(ev="vision-gone"))
    # No window now: a read is said to need one.
    ocr.screen.put(foreground=1000)
    r.send(cmd="vision-read", front=True, exclude=[1000])
    wait_for(lambda: r.seen(ev="vision-error"))
    assert "no window to read" in r.seen(ev="vision-error")[-1]["text"]
    r.close()


def test_the_window_chosen_by_a_click_and_other_readers(ocr):
    r = Reader(ocr)
    ocr.screen.text(CLIENT, [(20, 40, 240, 36, "今日はいい天気ですね")])
    ocr.screen.put(foreground=1000)
    start(r, engine="builtin")
    r.send(cmd="vision-pick", seconds=5, exclude=[1000])
    wait_for(lambda: r.seen(ev="vision-status", state="picking"))
    time.sleep(0.5)
    assert not r.seen(ev="vision-picked")
    ocr.screen.put(foreground=4242)
    wait_for(lambda: r.seen(ev="vision-picked"))
    assert r.seen(ev="vision-picked")[-1]["window"]["hwnd"] == 42420
    wait_for(lambda: layouts(r), timeout=15)
    layout = layouts(r)[-1]
    # Sluka's own reader: a line each, no words (the page spreads its letters over it).
    assert layout["engine"] == "builtin" and layout["why"] == "menu"
    assert [(line["text"], line["words"]) for line in layout["lines"]] == [("今日はいい天気ですね", [])]
    assert layout["lines"][0]["box"] == pytest.approx([140, 58, 240, 36, 0], abs=0.5)
    # Nothing clicked in time.
    r.send(cmd="vision-pick", seconds=1, exclude=[1000, 4242])
    wait_for(lambda: r.seen(ev="vision-picked", window=None), timeout=5)
    r.close()


def test_google_unreachable_or_offline(ocr):
    r = Reader(ocr)
    ocr.screen.text(CLIENT, SHOWN)
    ocr.lens.status = 429
    start(r)
    r.send(cmd="vision-read", front=True, exclude=[1000])
    wait_for(lambda: r.seen(ev="vision-error"), timeout=15)
    assert "Google Lens answered 429" in r.seen(ev="vision-error")[-1]["text"]
    assert r.seen(ev="vision-status", state="failed")
    r.close()
    ocr.lens.status = 200
    r = Reader(ocr, network="offline")
    start(r)
    r.send(cmd="vision-read", front=True, exclude=[1000])
    wait_for(lambda: r.seen(ev="vision-error"), timeout=15)
    assert "offline" in r.seen(ev="vision-error")[-1]["text"]
    r.close()


# ---------------------------------------------------------------- the app's side


class FakeShell:
    def __init__(self):
        self.calls = []

    def open_vision(self, area):
        self.calls.append(("open", list(area)))

    def close_vision(self):
        self.calls.append(("close",))

    def vision_place(self, area):
        self.calls.append(("place", list(area)))

    def vision_visible(self, on):
        self.calls.append(("visible", on))

    def vision_shape(self, rects, dpr):
        self.calls.append(("shape", rects, dpr))

    def vision_keep_out(self, on):
        self.calls.append(("keep_out", on))


class FakeEngine:
    def __init__(self):
        self.players = {}
        self.said = []
        self.gone = []

    def add_player(self, player):
        self.players[player.key] = player

    def incoming(self, player, message):
        self.said.append((player.key, message))

    def player_gone(self, player):
        self.gone.append(player.key)


def page(gt, name, body=None, site="same-origin"):
    got = []
    request = Request("POST", f"/__sluka__/api/vision/{name}", headers={"sec-fetch-site": site}, body=json.dumps(body or {}).encode())
    gt.vision.api(name, request, got.append)
    return json.loads(got[0].body) if got else None


class PageStub:
    """The overlay's page as it asks the app for news: again as soon as it is answered; all it was told, kept."""

    def __init__(self, gt):
        self.gt = gt
        self.msgs = []
        self._ask(True)

    def _ask(self, fresh=False):
        request = Request("POST", "/__sluka__/api/vision/poll", headers={"sec-fetch-site": "same-origin"},
                          body=json.dumps({"fresh": fresh}).encode())
        self.gt.vision.api("poll", request, self._answer)

    def _answer(self, response):
        data = json.loads(response.body)
        self.msgs.extend(data.get("msgs") or [])
        if not data.get("superseded"):
            self._ask()

    def told(self, kind):
        return [m for m in list(self.msgs) if m["t"] == kind]


def vision_state(gt):
    return ask(gt, "state")["vision"]


def test_the_sluka_vision_tab_end_to_end(app, keys):  # noqa: F811  (the fixtures)
    ocr, host = app.ocr, app.host
    host.mpv = FakeEngine()
    host.bar.on = True
    gt = app.build()
    shell = FakeShell()
    gt.vision.shell = shell
    # The tab: in place of the Other program tab, which is no more.
    assert ask(gt, "mode", {"mode": "socket"}) == {"ok": False, "error": "no such mode"}
    assert ask(gt, "mode", {"mode": "vision"}) == {"ok": True, "mode": "vision"}
    assert host.bar.on is False  # (the floating subtitles rest meanwhile)
    wait_for(lambda: vision_state(gt)["engines"])
    state = vision_state(gt)
    assert state["active"] and state["running"] and state["target"] is None and state["engines"]["lens"]["ok"]
    # Its keys, YomiNinja's as it comes: held while the tab is chosen.
    assert gt.settings["vision_key_read"] == "Alt+S" and gt.settings["vision_key_clear"] == "Alt+V"
    assert set(keys.held) == {"Alt+S", "Alt+V", "Alt+P", "Alt+F"}
    assert state["keys"]["read"] == {"key": "Alt+S", "error": "", "held": True, "note": ""}
    assert ask(gt, "vision-key", {"action": "auto", "vk": 0x41, "alt": True}) == {"ok": True, "key": "Alt+A"}
    assert "already" in ask(gt, "vision-key", {"action": "auto", "vk": 0x53, "alt": True})["error"]
    # Sluka's windows left out of the pictures (and the overlay's own, which does it itself) -- those that show: the
    # never-shown one (7, the background worker's) is left as it is.
    wait_for(lambda: app.procs.left_out == {9: True, 8: True})
    time.sleep(2.5)
    assert 7 not in app.procs.left_out

    # The key, in the game: the window in front is read, and laid over.
    ocr.screen.text(CLIENT, SHOWN)
    keys.press("Alt+S")
    wait_for(lambda: vision_state(gt)["last"]["lines"] == 3, timeout=15)
    state = vision_state(gt)
    assert state["target"]["title"] == "桜の詩" and state["target"]["exe"] == "sakura.exe" and state["shown"]
    assert state["last"]["engine"] == "lens" and state["last"]["why"] == "key"
    assert ("open", list(CLIENT)) in shell.calls and ("visible", True) in shell.calls
    # The overlay's page, starting: what it needs first, then Sluka's engine as one more player.
    stub = PageStub(gt)
    first = stub.msgs
    assert first[0] == {"t": "state", "engine": True, "auto": True, "front": True}
    shown = stub.told("layout")[0]
    assert shown["area"] == list(CLIENT) and [line["text"] for line in shown["lines"]][0] == "今日はいい天気ですね"
    assert page(gt, "say", {"msg": {"t": "hello", "v": 2, "sub_lang": ""}}) == {"ok": True}
    assert host.mpv.said[-1] == ("vision", {"t": "hello", "v": 2, "sub_lang": ""})
    host.mpv.players["vision"].send({"t": "ready", "v": 2, "lang": "ja"})
    assert stub.told("engine")[-1]["msg"]["t"] == "ready"
    # A panel open, with Sluka's keys as it is set: they are the panel's while the game itself is in front.
    sluka_keys = {"1": "1", "2": "2", "3": "3", "4": "4", "5": "k", "6": "x", "0": "0"}
    assert page(gt, "looking", {"panel": True, "read": shown["id"], "lines": [0], "keys": sluka_keys})["ok"]
    wait_for(lambda: {"1", "2", "3", "4", "K", "X", "0", "Esc"} <= set(keys.held))
    assert {"Alt+S", "Alt+V", "Alt+A", "Alt+P", "Alt+F"} <= set(keys.held) and gt.vision._holding == (shown["id"], (0,))
    keys.press("3")
    wait_for(lambda: stub.told("key") and stub.told("key")[-1] == {"t": "key", "st": 3})
    keys.press("0")
    wait_for(lambda: stub.told("key")[-1] == {"t": "key", "st": 0})
    keys.press("Esc")
    wait_for(lambda: stub.told("key")[-1] == {"t": "key", "close": True})
    # The panel's Anki key, where Settings → Anki has the panel's button on: held with them, told to the page.
    assert page(gt, "looking", {"panel": True, "read": shown["id"], "lines": [0], "keys": sluka_keys, "anki": "p"})["ok"]
    wait_for(lambda: "P" in keys.held)
    keys.press("P")
    wait_for(lambda: stub.told("key")[-1] == {"t": "key", "anki": True})
    # Not where it is one of the grading keys already.
    assert page(gt, "looking", {"panel": True, "read": shown["id"], "lines": [0], "keys": sluka_keys, "anki": "k"})["ok"]
    wait_for(lambda: "P" not in keys.held)
    assert page(gt, "looking", {"panel": True, "read": shown["id"], "lines": [0], "keys": sluka_keys})["ok"]
    # Each read is kept for the cards of words picked on it: its text as the page joins it, its game, before the read.
    kept = list(gt.cards._lines["vision"])
    assert kept[-1]["read"] == shown["id"] and kept[-1]["text"].startswith("今日はいい天気ですね")
    assert kept[-1]["game"]["pid"] == 4242 and kept[-1]["game"]["title"] == "桜の詩" and kept[-1]["game"]["hwnd"]
    # And the game's sound is followed while its window is the one read.
    wait_for(lambda: gt.cards.status()["following"]["vision"] == 4242, timeout=5)
    # One of Sluka's windows in front, not the game: the keys are given back (the overlay still shows); the game: again.
    ocr.screen.put(foreground=1000)
    wait_for(lambda: "K" not in keys.held)
    assert "Alt+S" in keys.held
    ocr.screen.put(foreground=4242)
    wait_for(lambda: "K" in keys.held)
    # The panel closed: the game has them back at once.
    page(gt, "looking", {"panel": False, "read": shown["id"], "lines": []})
    wait_for(lambda: set(keys.held) == {"Alt+S", "Alt+V", "Alt+A", "Alt+P", "Alt+F"})
    assert gt.vision._holding is None
    # Keys asked for that are not Sluka's kind (a plain letter or digit) are not held.
    page(gt, "looking", {"panel": True, "read": shown["id"], "lines": [0], "keys": {"1": "F5", "2": "ab", "9": "q", "3": "3"}})
    wait_for(lambda: "3" in keys.held)
    assert "F5" not in keys.held and "Q" not in keys.held
    page(gt, "looking", {"panel": False, "read": 0, "lines": []})
    wait_for(lambda: "3" not in keys.held)
    # Lines whose text is back as it was read (the reader says so): back on the page.
    gt.vision._event("vision-back", {"lines": [1]})
    wait_for(lambda: stub.told("back") and stub.told("back")[-1] == {"t": "back", "lines": [1]})
    # The parts drawn on, for the window's shape; no other site may ask.
    assert page(gt, "shape", {"rects": [[10, 20, 30, 40], ["x"]], "dpr": 1.25}) == {"ok": True}
    assert shell.calls[-1] == ("shape", [(10.0, 20.0, 30.0, 40.0)], 1.25)
    refused = []
    gt.vision.api("poll", Request("POST", "/__sluka__/api/vision/poll", headers={"sec-fetch-site": "cross-site"}, body=b"{}"),
                  refused.append)
    assert refused[0].status == 403

    # The game moves on: the words of what is gone go at once; the window settles, and is read again by itself.
    ocr.screen.text(CLIENT, LATER)
    wait_for(lambda: stub.told("stale"), timeout=10)
    wait_for(lambda: vision_state(gt)["last"]["why"] == "auto", timeout=15)
    assert vision_state(gt)["last"]["text"].startswith("明日も晴れるといいね")
    assert stub.told("layout")[-1]["why"] == "auto"
    # Another program in front: out of sight; the game again: back.
    ocr.screen.put(foreground=5)
    wait_for(lambda: ("visible", False) in shell.calls)
    ocr.screen.put(foreground=4242)
    wait_for(lambda: shell.calls[-1] == ("visible", True) or ("visible", True) in shell.calls[-3:])
    # The words put away: by the menu, and by their key.
    assert ask(gt, "vision-clear") == {"ok": True}
    assert stub.told("clear")
    assert not vision_state(gt)["shown"]
    keys.press("Alt+S")
    wait_for(lambda: vision_state(gt)["shown"], timeout=15)
    keys.press("Alt+V")
    wait_for(lambda: not vision_state(gt)["shown"])
    # Reading by itself, off by its key.
    keys.press("Alt+A")
    wait_for(lambda: gt.settings["vision_auto"] is False)

    # Another tab: the overlay goes, the engine is told, and the floating subtitles come back.
    assert ask(gt, "mode", {"mode": "game"})["ok"]
    wait_for(lambda: ("close",) in shell.calls)
    assert host.mpv.gone == ["vision"] and host.bar.on is True and keys.held == {}
    assert not vision_state(gt)["active"] and not vision_state(gt)["running"]
    # Kept: the settings.
    saved = json.loads((app.config.data_dir / "gametext.json").read_text(encoding="utf-8"))["settings"] if (
        app.config.data_dir / "gametext.json").exists() else {}
    if saved:
        assert saved["vision_key_auto"] == "Alt+A" and "socket_url" not in saved


def test_its_words_in_screenshots_and_recordings(app, keys):  # noqa: F811  (the fixtures)
    ocr, host = app.ocr, app.host
    host.mpv = FakeEngine()
    gt = app.build()
    shell = FakeShell()
    gt.vision.shell = shell
    # The game's own window read: nothing of Sluka's is left out of pictures of the screen -- its words, the floating
    # subtitles and its menu show in screenshots and recordings.
    assert ask(gt, "settings", {"settings": {"vision_capture": "window"}})["ok"]
    assert ask(gt, "mode", {"mode": "vision"})["ok"]
    wait_for(lambda: vision_state(gt)["running"])
    ocr.screen.text(CLIENT, SHOWN)
    keys.press("Alt+S")
    wait_for(lambda: vision_state(gt)["last"]["lines"] == 3, timeout=15)
    assert vision_state(gt)["capture"] == "window"
    opened = shell.calls.index(("open", list(CLIENT)))
    assert ("keep_out", False) in shell.calls[:opened]  # (said before its window is made)
    time.sleep(2.5)
    assert True not in app.procs.left_out.values()
    # The game's window gives no picture of itself (a black screen, say): the screen is read, and Sluka's windows
    # are left out of its pictures meanwhile -- the overlay too --, and the menu says why once.
    ocr.screen.put(blank=["window"])
    wait_for(lambda: shell.calls[-1] == ("keep_out", True) or ("keep_out", True) in shell.calls[opened:])
    wait_for(lambda: app.procs.left_out == {9: True, 8: True})
    notes = [line[2] for line in ask(gt, "state")["log"] if "cannot be read as it shows" in line[2]]
    assert len(notes) == 1 and "screenshots and recordings" in notes[0]
    # Its own picture again: in them again.
    ocr.screen.put(blank=[])
    wait_for(lambda: shell.calls[-1] == ("keep_out", False), timeout=8)
    wait_for(lambda: app.procs.left_out == {9: False, 8: False})
    assert vision_state(gt)["capture"] == "window"
    # What the screen shows, set: out of pictures again, and said once (not again for the same window).
    assert ask(gt, "settings", {"settings": {"vision_capture": "screen"}})["ok"]
    wait_for(lambda: shell.calls[-1] == ("keep_out", True))
    wait_for(lambda: app.procs.left_out == {9: True, 8: True})
    assert len([line for line in ask(gt, "state")["log"] if "cannot be read as it shows" in line[2]]) == 1
    # Another tab: every window of Sluka's that shows is in pictures again, whatever was left out before.
    app.procs.left_out[8] = True
    assert ask(gt, "mode", {"mode": "game"})["ok"]
    wait_for(lambda: app.procs.left_out == {9: False, 8: False})
    assert 7 not in app.procs.left_out  # (the never-shown window, never touched)


def test_the_settings_of_the_tab(tmp_path):
    clean = gametext.GameText._clean_settings
    assert clean({"mode": "socket"}) == {}
    assert clean({"mode": "vision", "vision_engine": "lens", "vision_capture": "window", "vision_auto": False}) == {
        "mode": "vision", "vision_engine": "lens", "vision_capture": "window", "vision_auto": False}
    assert clean({"vision_engine": "auto", "vision_capture": "both", "socket_url": "ws://x"}) == {}
    assert clean({"vision_key_read": "ctrl+shift+v"}) == {"vision_key_read": "Ctrl+Shift+V"}
    assert clean({"vision_key_pause": "pause", "vision_key_freeze": "alt+f"}) == {"vision_key_pause": "Pause", "vision_key_freeze": "Alt+F"}
    assert vision.READERS[0] == "lens" and set(vision.ACTIONS) == {"read", "auto", "clear", "pause", "freeze"}
    assert vision.FREEZE_MODES == {"pause": "pause", "freeze": "picture"}


# ---------------------------------------------------------------- its window (winshell), with the app around it


def test_its_window_over_the_game(tmp_path, monkeypatch, ocr):
    import threading

    from fakes import World
    from sluka_desktop import texthook, winshell
    from test_winshell import free_port, make_app, post

    monkeypatch.setattr(winshell, "CLOSE_GRACE_MS", 60)
    monkeypatch.setattr(winshell, "QUIT_GRACE_MS", 60)
    port = free_port()
    config = make_app(tmp_path / "app", port)
    config.network_mode = "direct"  # (as on Windows; this is Linux, where Sluka stays offline unless told)
    ocrfake.make_ocr_engine(texthook.engine_dir(config))
    ocr.screen.text(CLIENT, SHOWN)
    world = World()
    W = world.win
    EX = winshell
    failure = []

    def vision_windows():
        return {h: w for h, w in W.windows.items() if w.get("class") == winshell.VISION_CLASS_NAME}

    def driver():
        try:
            wait_for(lambda: len(world.webviews()) == 2 and world.webviews()[1].navigated, 10)
            main = world.webviews()[1].controller.hwnd
            for name in ("vision.html", "vision.js", "vision.css"):
                with urllib.request.urlopen(f"http://127.0.0.1:{port}/__sluka__/{name}", timeout=10) as answer:
                    assert answer.status == 200
            assert post(port, "games/mode", {"mode": "vision"}) == {"ok": True, "mode": "vision"}
            wait_for(lambda: post(port, "games/state", {})["vision"]["running"], 10)
            # The window clicked is the one read; its words laid over it, in a window of their own.
            assert post(port, "games/vision-pick", {}) == {"ok": True, "picking": True}
            wait_for(lambda: vision_windows(), 15)
            hwnd, window = next(iter(vision_windows().items()))
            wait_for(lambda: world.webviews()[-1].navigated, 10)
            view = [w for w in world.webviews() if w.controller.hwnd == hwnd][0]
            assert view.navigated == [f"http://127.0.0.1:{port}/__sluka__/vision.html"]
            # Over every window, with no taskbar button, never taking the keyboard; just where the game's inside is.
            assert window["ex"] & (EX.WS_EX_TOPMOST | EX.WS_EX_TOOLWINDOW | EX.WS_EX_NOACTIVATE) == \
                EX.WS_EX_TOPMOST | EX.WS_EX_TOOLWINDOW | EX.WS_EX_NOACTIVATE
            assert window["style"] == EX.WS_POPUP | EX.WS_CLIPCHILDREN
            assert (window["x"], window["y"], window["w"], window["h"]) == tuple(CLIENT)
            # Never in a picture of the screen; nothing of it seen until its page says where its words are.
            assert window["affinity"] == EX.WDA_EXCLUDEFROMCAPTURE
            assert all(shown for _, shown in window["affinities"])  # (told once it shows)
            assert window["region"] == [] and EX.SW_SHOWNOACTIVATE in window["shows"]
            wait_for(lambda: view.controller.background == 0)
            assert view.controller.focus == 0
            # Its page: shaped to its words, in the screen's pixels.
            assert post(port, "vision/shape", {"rects": [[10, 20, 100, 50]], "dpr": 1.5}) == {"ok": True}
            wait_for(lambda: window["region"] == [(15, 30, 165, 105)])
            # Another program in front: out of sight; the game again: shown, over all.
            ocr.screen.put(foreground=5)
            wait_for(lambda: window["shows"][-1] == EX.SW_HIDE, 10)
            ocr.screen.put(foreground=4242)
            wait_for(lambda: window["shows"][-1] == EX.SW_SHOWNOACTIVATE, 10)
            # The game's own window read: in pictures of the screen (screenshots, recordings) -- and only told so while
            # it shows; behind, then the screen read again: told as it shows again.
            assert post(port, "games/settings", {"settings": {"vision_capture": "window"}})["ok"]
            wait_for(lambda: window["affinities"][-1] == (EX.WDA_NONE, True), 10)
            ocr.screen.put(foreground=5)
            wait_for(lambda: window["shows"][-1] == EX.SW_HIDE, 10)
            told = len(window["affinities"])
            assert post(port, "games/settings", {"settings": {"vision_capture": "screen"}})["ok"]
            time.sleep(1.0)
            assert len(window["affinities"]) == told and window["affinity"] == EX.WDA_NONE
            ocr.screen.put(foreground=4242)
            wait_for(lambda: window["affinities"][-1] == (EX.WDA_EXCLUDEFROMCAPTURE, True), 10)
            assert all(shown for _, shown in window["affinities"])
            # The game's window moved: so is this one.
            ocr.screen.window(42420, 4242, (80, 90, 700, 500))
            wait_for(lambda: (window["x"], window["y"]) == (80, 90), 10)
            # A whole screen covered: all of it but its last row (never taken for a program gone full screen).
            like = SimpleNamespace(api=W)
            assert winshell.Shell._vision_frame_of(like, (0, 0, 2880, 1620)) == (0, 0, 2880, 1619)
            assert winshell.Shell._vision_frame_of(like, (2880, 0, 1920, 1080)) == (2880, 0, 1920, 1079)
            assert winshell.Shell._vision_frame_of(like, (100, 100, 1280, 720)) == (100, 100, 1280, 720)
            # Another tab: the window goes.
            assert post(port, "games/mode", {"mode": "off"})["ok"]
            wait_for(lambda: window["destroyed"], 10)
            W.close(main)
        except BaseException as err:
            failure.append(err)
            for h in list(W.app_windows()):
                W.close(h)

    thread = threading.Thread(target=driver, daemon=True)
    thread.start()
    code = winshell.run_app(config, api=world.win, entry=world.entry, runtime=fakes.runtime())
    thread.join(15)
    if failure:
        raise failure[0]
    assert code == 0
    assert not world.unexpected, world.unexpected


def still_of(gt):
    got = []
    gt.vision.api("still", Request("GET", "/__sluka__/api/vision/still?n=1", headers={"sec-fetch-site": "same-origin"}), got.append)
    return got[0]


def test_the_game_paused_or_its_picture_frozen(app, keys):  # noqa: F811  (the fixtures)
    """Its two keys, each a way of stopping the game where it is: the game paused and its picture kept over it (Alt+P),
    or only its picture kept, the game going on behind it (Alt+F); the one, then the other; let go of, the game goes on
    and is read as it is.  A game Windows will not let Sluka pause has its picture frozen instead; one left paused by an
    app that ended is let go of at the next start."""
    ocr, host, procs = app.ocr, app.host, app.procs
    host.mpv = FakeEngine()
    gt = app.build()
    shell = FakeShell()
    gt.vision.shell = shell
    assert ask(gt, "mode", {"mode": "vision"})["ok"]
    assert gt.settings["vision_key_pause"] == "Alt+P" and gt.settings["vision_key_freeze"] == "Alt+F"
    wait_for(lambda: {"Alt+P", "Alt+F"} <= set(keys.held))
    # Nothing to stop before a window is read.
    assert ask(gt, "vision-freeze", {"mode": "pause"})["ok"] is False
    ocr.screen.text(CLIENT, SHOWN)
    keys.press("Alt+S")
    wait_for(lambda: vision_state(gt)["last"]["lines"] == 3, timeout=15)
    stub = PageStub(gt)
    asked = len(ocr.lens.requests)

    # The game paused: its picture taken the moment before, then the game itself.
    keys.press("Alt+P")
    wait_for(lambda: vision_state(gt)["frozen"] == "pause", timeout=10)
    assert procs.paused == [4242]
    told = stub.told("freeze")[-1]
    assert told == {"t": "freeze", "on": True, "mode": "pause", "n": 1, "size": [700, 500], "key": "Alt+P"}
    answer = still_of(gt)
    assert answer.status == 200 and answer.content_type == "image/bmp" and answer.headers["Cache-Control"] == "no-store"
    picture = ocrd.from_bmp(answer.body)
    assert (picture.w, picture.h) == (700, 500)
    assert not list(app.config.data_dir.glob("vision-still*.bmp"))  # (read at once, and taken away)
    paused = json.loads((app.config.data_dir / vision.PAUSED_FILE).read_text(encoding="utf-8"))
    assert paused == {"pid": 4242, "started": 777}
    # The words shown are those of the picture: not read again.
    time.sleep(1.0)
    assert len(ocr.lens.requests) == asked
    # A word's card has the picture kept (a paused game's own window is not asked for one).
    assert gt.cards._take_picture("vision", {"hwnd": 42420, "pid": 4242}) == answer.body
    # Another site may not have the picture.
    refused = []
    gt.vision.api("still", Request("GET", "/__sluka__/api/vision/still", headers={"sec-fetch-site": "cross-site"}),
                  refused.append)
    assert refused[0].status == 403
    # The page, starting again meanwhile, is told at once.
    again = PageStub(gt)
    assert again.told("freeze")[-1]["mode"] == "pause"
    # Windows puts its stand-in in place of the paused game's window (it does not answer): still the game in front --
    # the picture stays laid over it.  Another program in front: out of sight, as ever.
    shown_before = len([c for c in shell.calls if c == ("visible", False)])
    ocr.screen.put(foreground=6, ghost=True)
    time.sleep(1.0)
    assert len([c for c in shell.calls if c == ("visible", False)]) == shown_before
    ocr.screen.put(foreground=5, ghost=False)
    wait_for(lambda: len([c for c in shell.calls if c == ("visible", False)]) > shown_before)
    ocr.screen.put(foreground=4242)
    wait_for(lambda: ("visible", True) in shell.calls[-3:])

    # The other key: the game goes on behind its picture, kept as it is.
    keys.press("Alt+F")
    wait_for(lambda: vision_state(gt)["frozen"] == "picture", timeout=10)
    assert procs.paused == [] and not (app.config.data_dir / vision.PAUSED_FILE).exists()
    wait_for(lambda: again.told("freeze")[-1]["mode"] == "picture")
    assert again.told("freeze")[-1]["n"] == 1
    ocr.screen.text(CLIENT, LATER)
    time.sleep(1.5)
    assert len(ocr.lens.requests) == asked and not again.told("stale")
    # Its key again: let go of -- the picture taken away a moment later, the window read as it is now.
    keys.press("Alt+F")
    wait_for(lambda: vision_state(gt)["frozen"] == "", timeout=10)
    wait_for(lambda: again.told("freeze")[-1] == {"t": "freeze", "on": False, "n": 1}, timeout=5)
    assert still_of(gt).status == 404
    wait_for(lambda: vision_state(gt)["last"]["text"].startswith("明日も晴れるといいね"), timeout=15)

    # A game Windows will not let Sluka pause (run as administrator, or an anti-cheat's): its picture frozen instead.
    procs.refuse_pause = "admin"
    keys.press("Alt+P")
    wait_for(lambda: vision_state(gt)["frozen"] == "picture", timeout=10)
    assert procs.paused == [] and "administrator" in again.told("note")[-1]["text"]
    # Allowed again, its key while the picture is frozen: the game paused under it.
    procs.refuse_pause = ""
    assert ask(gt, "vision-freeze", {"mode": "pause"}) == {"ok": True, "frozen": "pause"}
    assert procs.paused == [4242] and vision_state(gt)["frozen"] == "pause"
    # Another tab: the game goes on.
    assert ask(gt, "mode", {"mode": "game"})["ok"]
    assert procs.paused == [] and not (app.config.data_dir / vision.PAUSED_FILE).exists()

    # An app that ended with a game paused: the game let go of at the next start, where it is the same program.
    (app.config.data_dir / vision.PAUSED_FILE).write_text(json.dumps({"pid": 4242, "started": 777}), encoding="utf-8")
    app.build()
    assert procs.pause_log[-1] == ("left", 4242, 777)
    assert not (app.config.data_dir / vision.PAUSED_FILE).exists()


def test_its_keys_pressed_quickly(app, keys):  # noqa: F811  (the fixtures)
    """Its key pressed twice before the picture came: one pause (the last key says which way); pressed while it goes
    on, the game is never paused twice -- nor left paused."""
    ocr, host, procs = app.ocr, app.host, app.procs
    host.mpv = FakeEngine()
    gt = app.build()
    gt.vision.shell = FakeShell()
    assert ask(gt, "mode", {"mode": "vision"})["ok"]
    ocr.screen.text(CLIENT, SHOWN)
    keys.press("Alt+S")
    wait_for(lambda: vision_state(gt)["last"]["lines"] == 3, timeout=15)
    keys.press("Alt+F")
    keys.press("Alt+P")
    wait_for(lambda: vision_state(gt)["frozen"] == "pause", timeout=10)
    assert procs.paused == [4242] and [e for e in procs.pause_log if e[0] == "pause"] == [("pause", 4242)]
    for _ in range(3):
        keys.press("Alt+P")
        keys.press("Alt+P")
    keys.press("Alt+P")
    wait_for(lambda: vision_state(gt)["frozen"] == "", timeout=10)
    assert procs.paused == []
    pauses = [e for e in procs.pause_log if e[0] == "pause"]
    resumes = [e for e in procs.pause_log if e[0] == "resume"]
    assert len(pauses) == len(resumes)


def test_a_word_about_a_picture_let_go_of_is_not_taken_for_one_asked_for_now(app, keys):  # noqa: F811  (the fixtures)
    """The screen reader's words come when they come: about a picture asked for, let go of and asked for again, its
    word about the first (taken, or let go of) is not the second's -- which is taken when its own word comes; and the
    same key pressed again before a picture came lets it go."""
    ocr, host, procs = app.ocr, app.host, app.procs
    host.mpv = FakeEngine()
    gt = app.build()
    gt.vision.shell = FakeShell()
    assert ask(gt, "mode", {"mode": "vision"})["ok"]
    ocr.screen.text(CLIENT, SHOWN)
    keys.press("Alt+S")
    wait_for(lambda: vision_state(gt)["last"]["lines"] == 3, timeout=15)
    v = gt.vision
    sent = []
    v._send = lambda command: sent.append(command) or True
    v._send_running = lambda command: sent.append(command)
    bmp = ocrd.to_bmp(ocrd.Image(4, 4, bytes(4 * 4 * 4)))

    assert v.toggle_freeze("pause") == {"ok": True, "frozen": "pause"}
    first = sent[-1]
    assert first["cmd"] == "vision-freeze" and first["on"] is True and first["path"].endswith(f"vision-still-{first['ask']}.bmp")
    # Pressed again before its picture came: not wanted after all.
    assert v.toggle_freeze("pause") == {"ok": True, "frozen": ""}
    assert sent[-1] == {"cmd": "vision-freeze", "on": False}
    assert v.toggle_freeze("pause") == {"ok": True, "frozen": "pause"}
    second = sent[-1]
    assert second["ask"] == first["ask"] + 1
    before = len(sent)
    # The first one's picture, and its letting go, come only now: neither is the second's.
    Path(first["path"]).write_bytes(bmp)
    v._frozen_event({"ev": "vision-frozen", "on": True, "size": [4, 4], "ask": first["ask"]})
    v._frozen_event({"ev": "vision-frozen", "on": False, "ask": first["ask"]})
    assert v.frozen is None and v._freeze_asked == "pause" and procs.paused == []
    assert len(sent) == before  # (and the second is not let go of on the first's account)
    assert not Path(first["path"]).exists()
    # The second's own word: the game paused.
    Path(second["path"]).write_bytes(bmp)
    v._frozen_event({"ev": "vision-frozen", "on": True, "size": [4, 4], "ask": second["ask"]})
    assert v.frozen["mode"] == "pause" and procs.paused == [4242]
    # A word about the first picture, late as it is, does not let the second go.
    v._frozen_event({"ev": "vision-frozen", "on": False, "ask": first["ask"]})
    assert v.frozen is not None and procs.paused == [4242]
    # Its own does (the window gone, say).
    v._frozen_event({"ev": "vision-frozen", "on": False, "ask": second["ask"]})
    assert v.frozen is None and procs.paused == []
