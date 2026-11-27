"""How long a game is played (playclock.py), told to Sluka's engine a minute at a time as a message of the player its
text goes to -- half of it is listening on Sluka's Home page (web/progress.js).  With stand-ins for the game text
menu's state, and once through the Sluka Vision tab on its pretend screen (test_vision.py's).
"""

from __future__ import annotations

import json
import threading
import time
from types import SimpleNamespace

import pytest

import fakes  # noqa: F401  (puts the app on the path)
from sluka_desktop import playclock
from sluka_desktop.bar import Bar
from sluka_desktop.playclock import Pads, PlayClock
from test_gametext import wait_for
from test_ocr import app, keys  # noqa: F401  (app, keys: fixtures)
from test_vision import CLIENT, SHOWN, FakeEngine, FakeShell, PageStub, page, vision_state
from test_gametext import ask


class Told:
    def __init__(self, ok=True):
        self.said = []
        self.ok = ok

    def tell_engine(self, message):
        self.said.append(message)
        return self.ok


class NoPads:
    def used(self):
        return False


def games(mode="game", foreground=4242):
    bar = Told()
    vision = Told()
    vision.showing = lambda: True
    vision.front = True
    vision.game_front = True
    vision.last = {"at": 0.0}
    g = SimpleNamespace(
        settings={"mode": mode},
        procs=SimpleNamespace(own_pid=1000, foreground=foreground),
        _lock=threading.RLock(),
        game={"pid": 4242, "pids": {4242, 4243}, "connected": {4242}, "state": "attached"},
        screen=SimpleNamespace(target={"pid": 4242, "state": "watching"}),
        vision=vision,
        last_line={"at": 0.0},
        host=SimpleNamespace(bar=bar),
    )
    g.procs.foreground_pid = lambda: g.procs.foreground
    return g


def stretch(clock, told, seconds, start, step=2.0):
    """`seconds` of looks from `start`, then what is owed told: the ms told meanwhile."""
    before = sum(m["ms"] for m in told.said)
    t = start
    while t <= start + seconds + 1e-9:
        clock.tick(t)
        t += step
    clock.report(t - step)
    return sum(m["ms"] for m in told.said) - before


def near(ms, seconds):
    """Within one look of `seconds`: where the stretch starts and ends is a look's worth either way."""
    return abs(ms - seconds * 1000) <= 2000


def test_a_game_played_is_told_a_minute_at_a_time():
    g = games()
    clock = PlayClock(g, idle=lambda: 3.0, pads=NoPads())
    t = 1000.0
    while t <= 1062:
        clock.tick(t)
        t += 2
    # A minute from the first look: told, as the bar's own message.
    assert g.host.bar.said == [{"t": "played", "ms": 60000}]
    # Its other programs count as the game (one that draws in a program of its own).
    g.procs.foreground = 4243
    assert near(stretch(clock, g.host.bar, 60, 1064.0), 62)


@pytest.mark.parametrize("change", ["another program", "sluka", "not hooked", "clipboard", "off"])
def test_not_played_where_the_game_is_not_in_front_or_not_read(change):
    g = games()
    if change == "another program":
        g.procs.foreground = 5
    elif change == "sluka":
        g.procs.foreground = 1000  # Sluka's own window (its Home page, the menu): not the game
    elif change == "not hooked":
        g.game["state"] = "ended"
    else:
        g.settings["mode"] = change
    clock = PlayClock(g, idle=lambda: 3.0, pads=NoPads())
    assert stretch(clock, g.host.bar, 130, 1000.0) == 0
    assert g.host.bar.said == [] and g.vision.said == []


def test_nothing_done_for_five_minutes_is_not_playing_but_a_key_a_controller_or_new_text_is():
    g = games()
    idle = {"s": 400.0}
    wall = {"t": 50000.0}
    clock = PlayClock(g, idle=lambda: idle["s"], pads=NoPads(), wall=lambda: wall["t"])
    assert stretch(clock, g.host.bar, 62, 1000.0) == 0
    # New text from the game, a minute ago.
    g.last_line["at"] = wall["t"] - 60
    assert near(stretch(clock, g.host.bar, 60, 1064.0), 62)
    # Six minutes on, the text old: a key pressed a moment ago.
    g.last_line["at"] = wall["t"] - 360
    idle["s"] = 2.0
    assert near(stretch(clock, g.host.bar, 60, 1128.0), 62)
    # A controller, where nothing else says anything: for five minutes after it was used.
    idle["s"] = 900.0

    class OnePress:
        def __init__(self):
            self.pressed = True

        def used(self):
            pressed, self.pressed = self.pressed, False
            return pressed

    clock = PlayClock(g, idle=lambda: idle["s"], pads=OnePress(), wall=lambda: wall["t"])
    assert near(stretch(clock, g.host.bar, 60, 2000.0), 60)
    assert stretch(clock, g.host.bar, 60, 2400.0) == 0


def test_the_computer_asleep_is_not_played():
    g = games()
    clock = PlayClock(g, idle=lambda: 0.0, pads=NoPads())
    for t in (1000.0, 1002.0, 4000.0, 4002.0, 4062.0):   # (asleep between the second and the third)
        clock.tick(t)
    clock.report(4062.0)
    assert sum(m["ms"] for m in g.host.bar.said) == 4000


def test_the_screen_tab_and_a_box_in_no_window():
    g = games("screen")
    clock = PlayClock(g, idle=lambda: 0.0, pads=NoPads())
    assert near(stretch(clock, g.host.bar, 60, 1000.0), 60)
    # A box where it is on the screen, in no window: whatever is in front but Sluka.
    g.screen.target = {"pid": 0, "state": "watching"}
    g.procs.foreground = 777
    assert near(stretch(clock, g.host.bar, 60, 1064.0), 62)
    g.procs.foreground = 1000
    assert stretch(clock, g.host.bar, 60, 1128.0) == 0


def test_sluka_vision_is_told_as_its_own_and_another_tab_is_told_apart():
    g = games("vision")
    clock = PlayClock(g, idle=lambda: 0.0, pads=NoPads())
    for t in range(1000, 1031, 2):
        clock.tick(float(t))
    g.vision.game_front = False   # one of Sluka's windows in front, not the game
    for t in range(1032, 1053, 2):
        clock.tick(float(t))
    g.vision.game_front = True
    g.settings["mode"] = "game"   # another tab: what Vision played is told as Vision's, at once
    clock.tick(1054.0)
    assert g.vision.said == [{"t": "played", "ms": 30000}]
    assert near(stretch(clock, g.host.bar, 60, 1056.0), 62)
    assert len(g.vision.said) == 1


def test_a_controller_at_rest_is_not_use_and_a_button_is():
    states = {0: (0, 0, 0, 1200, -900, 300, 0)}

    def get(index):
        return states.get(index)

    now = {"t": 0.0}
    pads = Pads(get_state=get, now=lambda: now["t"])
    assert not pads.used()   # (first seen)
    states[0] = (0, 0, 0, 1500, -1100, 250, 40)   # a stick trembling in its dead zone
    assert not pads.used()
    states[0] = (0x1000, 0, 0, 1500, -1100, 250, 40)   # A
    assert pads.used()
    assert not pads.used()
    states[0] = (0x1000, 0, 0, 20000, 0, 0, 0)   # a stick pushed
    assert pads.used()
    states[0] = (0x1000, 200, 0, 0, 0, 0, 0)   # a trigger
    assert pads.used()
    # Controller places with none in them are asked again only now and then.
    asked = []

    def counting(index):
        asked.append(index)
        return states.get(index)

    pads = Pads(get_state=counting, now=lambda: now["t"])
    pads.used()
    asked.clear()
    now["t"] = 1.0
    pads.used()
    assert asked == [0]
    now["t"] = 20.0
    asked.clear()
    pads.used()
    assert asked == [0, 1, 2, 3]


def test_the_bar_tells_the_engine_only_once_its_page_said_hello(tmp_path):
    engine = FakeEngine()

    class Host:
        mpv = engine

    config = SimpleNamespace(data_dir=tmp_path)
    bar = Bar(config, Host())
    assert bar.tell_engine({"t": "played", "ms": 1000}) is False

    class Req:
        def __init__(self, body):
            self.method, self.body, self.query, self.headers = "POST", body, {}, {}

    answers = []
    bar.api("say", Req(json.dumps({"msg": {"t": "hello", "v": 2}}).encode()), answers.append)
    assert json.loads(answers[-1].body) == {"ok": True}
    assert bar.tell_engine({"t": "played", "ms": 1000}) is True
    assert engine.said[-1] == ("bar", {"t": "played", "ms": 1000})
    bar.close()


def test_through_the_sluka_vision_tab(app, keys):  # noqa: F811  (the fixtures)
    ocr, host = app.ocr, app.host
    host.mpv = FakeEngine()
    gt = app.build()
    gt.vision.shell = FakeShell()
    assert ask(gt, "mode", {"mode": "vision"})["ok"]
    wait_for(lambda: vision_state(gt)["engines"])
    ocr.screen.text(CLIENT, SHOWN)
    keys.press("Alt+S")
    wait_for(lambda: vision_state(gt)["last"]["lines"] == 3, timeout=15)
    PageStub(gt)
    clock = PlayClock(gt, idle=lambda: 0.0, pads=NoPads())
    played = lambda: [m for _k, m in host.mpv.said if m.get("t") == "played"]  # noqa: E731
    for t in range(1000, 1063, 2):
        clock.tick(float(t))
    assert played() == [], "not before the overlay's page says hello"
    assert page(gt, "say", {"msg": {"t": "hello", "v": 2, "sub_lang": ""}}) == {"ok": True}
    assert gt.vision.showing() and gt.vision.front and gt.vision.game_front
    for t in range(1064, 1125, 2):
        clock.tick(float(t))
    assert host.mpv.said[-1][0] == "vision" and played() and near(played()[-1]["ms"], 60)
    # Another program in front: not played.
    ocr.screen.put(foreground=5)
    wait_for(lambda: not gt.vision.game_front)
    clock.report(1126.0)
    count = len(played())
    for t in range(1128, 1250, 2):
        clock.tick(float(t))
    clock.report(1250.0)
    assert len(played()) == count
    assert ask(gt, "mode", {"mode": "game"})["ok"]


def test_the_game_text_menu_keeps_a_clock_ticks_it_and_lets_it_go_if_it_fails(tmp_path):
    from sluka_desktop import gametext
    from test_gametext import FakeClipboard, FakeProcs

    config = SimpleNamespace(data_dir=tmp_path / "data", log_dir=tmp_path / "data" / "logs", network_mode="direct",
                             engine_dir=tmp_path / "engine", root=tmp_path)
    host = SimpleNamespace(bar=None)
    gt = gametext.GameText(config, host, procs=FakeProcs(), clipboard_factory=FakeClipboard)
    assert isinstance(gt.play, PlayClock)
    ticked = []

    class Broken:
        def tick(self, now):
            ticked.append(now)
            raise RuntimeError("broken")

    gt.play = Broken()
    gt._tick(100.0)
    gt._tick(100.05)
    assert ticked == [100.0] and gt.play is None   # said once, then let go: the rest of the menu goes on
    assert playclock.REPORT_SECONDS == 60 and playclock.IDLE_SECONDS == 300
