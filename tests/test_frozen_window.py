"""The game's own window as what is read ("The game's own window", for screenshots and recordings), where its picture
no longer changes: a game that went on to draw with the graphics card past Windows keeps an old picture in its device
context -- Ace Attorney, its title menu -- however often it is read.  The screen reader (ocrd.py's WindowWays) puts
that picture beside Windows' own drawing of the window and takes the latter; where even that stays as it was while the
game goes on, it reads the screen, and the app says so, once, in a message of its own."""

from __future__ import annotations

import time

import pytest

import fakes  # noqa: F401  (puts the app on the path)
from sluka_desktop import ocrd, ocrtext
from test_gametext import ask, wait_for
from test_ocr import app, keys  # noqa: F401  (fixtures)
from test_vision import SHOWN, layouts, start
from test_ocr import Reader

from conftest import CLIENT

#: What the title menu shows: what a frozen picture keeps.
TITLE = [(20, 40, 240, 36, "タイトル画面"), (20, 120, 200, 30, "はじめから")]


def picture(fill: int, w: int = 96, h: int = 96, spot=None) -> ocrd.Image:
    """A picture of one colour (and, where asked, a square of another at spot: (x, y, size, colour))."""
    data = bytearray(bytes((fill, fill, fill, 0)) * (w * h))
    if spot is not None:
        x0, y0, size, colour = spot
        for y in range(y0, y0 + size):
            at = (y * w + x0) * 4
            data[at:at + size * 4] = bytes((colour, colour, colour, 0)) * size
    return ocrd.Image(w, h, bytes(data))


class Clock:
    def __init__(self):
        self.now = 100.0

    def __call__(self):
        return self.now


def ways_with(dc, drawn, screen, front=True):
    """A WindowWays over pictures given as callables: dc() its device context's, drawn() Windows' own drawing of
    it, screen() the screen's; front: the game in front."""
    clock = Clock()
    taken = []

    def take(way, hwnd, rect):
        taken.append(way)
        return dc() if way == "dc" else drawn()

    ways = ocrd.WindowWays(take, lambda rect: screen(), lambda hwnd: front, clock=clock)
    return ways, clock, taken


def test_a_device_context_that_follows_the_game_is_kept():
    live = picture(80)
    ways, clock, taken = ways_with(lambda: live, lambda: live, lambda: live)
    assert ways.grab(1, (0, 0, 96, 96)) is live and ways.way(1) == "dc"
    # Looked at again now and then, not each time (Windows' own drawing costs more).
    taken.clear()
    clock.now += 0.5
    ways.grab(1, (0, 0, 96, 96))
    assert taken == ["dc"]
    clock.now += ways.CHECK
    ways.grab(1, (0, 0, 96, 96))
    assert taken == ["dc", "dc", "print"] and ways.way(1) == "dc"


def test_a_device_context_that_keeps_an_old_picture_is_given_up_for_windows_own_drawing():
    title, game = picture(30), picture(200)
    ways, clock, taken = ways_with(lambda: title, lambda: game, lambda: game)
    # At once, the first time: the picture of the game as it is now.
    assert ways.grab(7, (0, 0, 96, 96)) is game and ways.way(7) == "print" and not ways.frozen(7)
    taken.clear()
    clock.now += 0.5
    assert ways.grab(7, (0, 0, 96, 96)) is game and taken == ["print"]
    # Another window, a way of its own.
    assert ways.way(8) == "dc"
    # Even a small part apart (only the text box changed since the old picture): not one picture.
    box = picture(30, spot=(24, 24, 24, 220))
    ways, clock, taken = ways_with(lambda: title, lambda: box, lambda: box)
    assert ways.grab(9, (0, 0, 96, 96)) is box and ways.way(9) == "print"


def test_where_windows_own_drawing_is_the_old_one_the_device_context_is_kept():
    title, game = picture(30), picture(200)
    ways, clock, taken = ways_with(lambda: game, lambda: title, lambda: game)
    assert ways.grab(4, (0, 0, 96, 96)) is game and ways.way(4) == "dc"
    # Not in front (the screen there may be another window): Windows' own drawing, which follows most games.
    ways, clock, taken = ways_with(lambda: game, lambda: title, lambda: game, front=False)
    assert ways.grab(4, (0, 0, 96, 96)) is title and ways.way(4) == "print"


def test_a_window_whose_every_picture_is_frozen_is_read_off_the_screen():
    title = picture(30)
    shown = {"fill": 100}
    ways, clock, _taken = ways_with(lambda: title, lambda: title, lambda: picture(shown["fill"]))
    rect = (0, 0, 96, 96)
    for look in range(ways.FROZEN_LOOKS):
        assert ways.grab(3, rect) is title and not ways.frozen(3), look
        shown["fill"] += 40  # (the game goes on: the screen changes; the window's picture does not)
        clock.now += ways.CHECK
    assert ways.grab(3, rect) is None and ways.frozen(3)
    assert ways.grab(3, rect) is None  # (the screen from then on ...)
    ways.forget()                      # (... until what is read is chosen again)
    assert ways.grab(3, rect) is title and not ways.frozen(3)


@pytest.mark.parametrize("case", ["behind", "still", "overlay", "panel"])
def test_a_window_is_never_taken_for_frozen_wrongly(case):
    """Not while another window is in front (the screen there is not the game), nor where the game itself stands still
    (both pictures as they were), nor where only Sluka's own words, card or panel over it change the screen -- a panel
    kept open over a still scene included."""
    frame = picture(30, 192, 192)
    looks = {"n": 0}

    def screen():
        looks["n"] += 1
        if case == "still":
            return frame
        if case == "overlay":  # (Sluka's card over a word, a sixteenth of the window, here and gone)
            return picture(30, 192, 192, spot=(48, 48, 48, 220)) if looks["n"] % 2 else frame
        if case == "panel":  # (a word's panel opened over two fifths of a small window, and left open)
            return picture(30, 192, 192, spot=(24, 24, 120, 220)) if looks["n"] > 1 else frame
        return picture(30 + looks["n"] * 40 % 200, 192, 192)

    ways, clock, _taken = ways_with(lambda: frame, lambda: frame, screen, front=case != "behind")
    for _ in range(ways.FROZEN_LOOKS * 4):
        assert ways.grab(5, (0, 0, 192, 192)) is frame
        clock.now += ways.CHECK
    assert not ways.frozen(5) and ways.way(5) == "dc"


def test_a_window_whose_picture_changes_is_never_frozen():
    """However much the screen changes, a window picture that changes too follows the game."""
    n = {"i": 0}

    def live():
        return picture(30 + n["i"] * 50 % 200)

    ways, clock, _taken = ways_with(live, live, live)
    for _ in range(10):
        n["i"] += 1
        assert ways.grab(6, (0, 0, 96, 96)) is not None
        clock.now += ways.CHECK
    assert not ways.frozen(6)


# ---------------------------------------------------------------- through the screen reader, on its pretend screen


def go_on(ocr, until=None, seconds: float = 15.0) -> None:
    """The game going on (its whole window changing, every few tenths of a second) until until() is so -- or, with
    no until, for that many seconds."""
    deadline = time.monotonic() + seconds
    step = 0
    while until is None or not until():
        if time.monotonic() >= deadline:
            assert until is None, "not so in time"
            return
        step += 1
        ocr.screen.text(CLIENT, [(20, 40, 240, 36, f"第{step}場面")], fill=(90, 40 + step * 37 % 180, 60))
        time.sleep(0.35)


def test_sluka_vision_reads_the_game_where_its_device_context_keeps_the_title_menu(ocr):
    ocr.screen.text(CLIENT, TITLE)
    ocr.screen.freeze("dc")  # (Windows' own drawing of the window follows the game)
    ocr.screen.text(CLIENT, SHOWN)
    r = Reader(ocr)
    start(r, capture="window")
    r.send(cmd="vision-read", front=True, exclude=[1000])
    wait_for(lambda: layouts(r), timeout=15)
    assert [line["text"] for line in layouts(r)[-1]["lines"]] == ["今日はいい天気ですね", "縦書きの行です", "何で公衆電話に"]
    # Still the game's own window: Sluka's words stay in screenshots and recordings.
    assert [e["how"] for e in r.seen(ev="vision-capture")] == ["window"]
    r.close()
    assert "is taken as Windows itself draws it" in (ocr.root / "ocrd.log").read_text(encoding="utf-8")


def test_sluka_vision_reads_the_screen_where_the_game_s_every_picture_is_frozen(ocr):
    ocr.screen.text(CLIENT, TITLE)
    ocr.screen.freeze("dc", "print")
    r = Reader(ocr)
    start(r, capture="window")
    r.send(cmd="vision-read", front=True, exclude=[1000])
    wait_for(lambda: layouts(r), timeout=15)
    assert layouts(r)[-1]["lines"][0]["text"] == "タイトル画面"  # (what the frozen picture has: the title menu)
    go_on(ocr, lambda: any(e.get("why") == "frozen" for e in r.seen(ev="vision-capture")))
    assert r.seen(ev="vision-capture")[-1] == {"ev": "vision-capture", "how": "screen", "why": "frozen"}
    # Read now: what the screen shows, the game as it is.
    ocr.screen.text(CLIENT, SHOWN)
    count = len(layouts(r))
    time.sleep(0.6)
    r.send(cmd="vision-read", front=True, exclude=[1000])
    wait_for(lambda: len(layouts(r)) > count and layouts(r)[-1]["lines"][0]["text"] == "今日はいい天気ですね", timeout=15)
    # The game's own window chosen again (set otherwise, and back): tried afresh.
    r.send(cmd="vision-settings", capture="screen")
    r.send(cmd="vision-settings", capture="window")
    ocr.screen.freeze()
    wait_for(lambda: r.seen(ev="vision-capture")[-1] == {"ev": "vision-capture", "how": "window"}, timeout=10)
    r.close()
    assert "gives only a picture that no longer changes" in (ocr.root / "ocrd.log").read_text(encoding="utf-8")


def test_the_screen_tab_reads_the_screen_where_the_game_s_every_picture_is_frozen(ocr):
    from conftest import BOX, IN_WINDOW

    ocr.screen.text(BOX, [(5, 5, 200, 20, "タイトル画面")])
    ocr.screen.freeze("dc", "print")
    r = Reader(ocr)
    r.send(cmd="watch", hwnd=42420, pid=4242, box=IN_WINDOW, client=[700, 500], engine="builtin", capture="window",
           mode="interval", interval=0.5)
    go_on(ocr, lambda: any(e.get("why") == "frozen" for e in r.seen(ev="capture")))
    assert r.seen(ev="capture")[0]["how"] == "window" and r.seen(ev="capture")[-1]["why"] == "frozen"
    r.close()


def test_the_app_says_so_once_in_a_message_of_its_own(app, keys):  # noqa: F811
    from test_vision import FakeShell

    told = []
    ocr = app.ocr
    gt = app.build(popup=lambda title, text: told.append((title, text)))
    gt.vision.shell = FakeShell()
    assert ask(gt, "settings", {"vision_capture": "window"})["ok"]
    assert ask(gt, "mode", {"mode": "vision"}) == {"ok": True, "mode": "vision"}
    ocr.screen.text(CLIENT, TITLE)
    ocr.screen.freeze("dc", "print")
    keys.press("Alt+S")
    wait_for(lambda: ask(gt, "state")["vision"]["last"]["lines"] > 0, timeout=15)
    go_on(ocr, lambda: told)
    assert len(told) == 1
    title, text = told[0]
    assert title == ocrtext.FROZEN_TITLE and "Sluka Vision has to read the screen for 桜の詩 to work properly" in text
    assert "does not show in screenshots or recordings" in text
    # Said in the menu too; and not again, however long the game goes on.
    wait_for(lambda: any("no longer changes" in line[2] for line in ask(gt, "state")["log"]))
    go_on(ocr, seconds=2.5)
    assert len(told) == 1
