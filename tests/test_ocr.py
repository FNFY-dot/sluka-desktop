"""The screen read (OCR): Sluka's screen reader (ocrd.py) with stand-ins for LunaTranslator's CVUtils.dll and
NativeUtils.dll (libraries of the same functions, built here with gcc), for Google Lens (a web server) and Tor (a
SOCKS5 proxy), on a pretend screen; and the Screen tab's side in the app (ocrtext.py), end to end.

What the real libraries would read off a picture, the stand-ins read off the picture's first row (fake_ocr.h): the
pictures, their sizes, the readers' settings and the way each is spoken to are the real ones'.
"""

from __future__ import annotations

import json
import subprocess
import sys
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

import fakes  # noqa: F401  (puts the app on the path)
import ocrfake
from sluka_desktop import gametext, ocrd, ocrtext
from test_gametext import FakeBar, FakeClipboard, FakeProcs, ask, wait_for

from conftest import BOX, CLIENT, IN_WINDOW  # noqa: E402  (the game's text box on the screen, its window's inside, the box in it)


def said(ocr, name):
    path = ocr.logs / f"{name}.log"
    return path.read_text(encoding="utf-8").splitlines() if path.exists() else []


class Reader:
    """ocrd.py, as the app runs it."""

    def __init__(self, ocr, *more, network="direct"):
        command = [sys.executable, "-I", "-X", "utf8", str(ocrtext.OCRD), str(ocr.engine), "--log", str(ocr.root / "ocrd.log"),
                   "--network", network, *ocr.args, *more]
        self.proc = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.events = []
        threading.Thread(target=self._read, daemon=True).start()
        wait_for(lambda: self.seen(ev="ready"))

    def _read(self):
        for line in self.proc.stdout:
            self.events.append(json.loads(line))

    def send(self, **command):
        self.proc.stdin.write((json.dumps(command) + "\n").encode())
        self.proc.stdin.flush()

    def seen(self, **match):
        return [e for e in list(self.events) if all(e.get(k) == v for k, v in match.items())]

    def texts(self):
        return [e["text"] for e in self.seen(ev="text")]

    def engines(self, lang="ja"):
        count = len(self.seen(ev="engines"))
        self.send(cmd="engines", lang=lang)
        wait_for(lambda: len(self.seen(ev="engines")) > count, timeout=15)
        return self.seen(ev="engines")[-1]["engines"]

    def read(self, engine, rect=BOX, **more):
        count = len(self.seen(ev="read"))
        self.send(cmd="read", rect=list(rect), engine=engine, **more)
        wait_for(lambda: len(self.seen(ev="read")) > count, timeout=15)
        return self.seen(ev="read")[-1]

    def close(self):
        self.send(cmd="quit")
        assert self.proc.wait(10) == 0


DIALOGUE = [(10, 10, 420, 36, "今日はいい天気ですね"), (10, 56, 300, 36, "散歩に行こうか")]


# ---------------------------------------------------------------- the readers


def test_which_readers_can_be_used_here(ocr, monkeypatch):
    r = Reader(ocr)
    ready = r.seen(ev="ready")[0]
    assert ready["protocol"] == 1 and ready["bits"] == 64
    found = r.engines()
    assert found["builtin"]["ok"] and "PP-OCRv5" in found["builtin"]["why"]
    assert found["windows"]["ok"] and found["windows"]["languages"] == [["ja", "日本語"], ["en-US", "English (United States)"]]
    assert found["lens"]["ok"] and "sent to Google" in found["lens"]["why"]
    # (no Snipping Tool: Sluka does not copy it out of Windows)
    assert set(found) == {"builtin", "windows", "lens"}
    # Windows without the OCR of a language: said, with how to add it.
    other = r.engines("ko")["windows"]
    assert not other["ok"] and "no OCR for ko" in other["why"] and "Language & region" in other["why"]
    r.close()
    # Sluka kept offline: no Google Lens.
    r = Reader(ocr, network="offline")
    found = r.engines()
    assert not found["lens"]["ok"] and "offline" in found["lens"]["why"]
    r.close()
    # ONNX Runtime that will not start (an old C++ runtime): said, and the others still read.
    monkeypatch.setenv("FAKE_ORT_FAIL", "1")
    r = Reader(ocr)
    found = r.engines()
    assert not found["builtin"]["ok"] and "ONNX Runtime" in found["builtin"]["why"]
    ocr.screen.text(BOX, DIALOGUE)
    read = r.read("auto")
    assert read["engine"] == "windows" and read["text"] == "今日はいい天気ですね\n散歩に行こうか"
    assert "ONNX Runtime" in r.read("builtin")["error"]
    r.close()
    # The engine folder's OCR files gone (an antivirus): said which.
    monkeypatch.delenv("FAKE_ORT_FAIL")
    (ocr.engine / "ocr" / "model" / "rec.onnx").unlink()
    r = Reader(ocr)
    assert "model/rec.onnx" in r.engines()["builtin"]["why"]
    r.close()


def test_sluka_own_ocr_is_driven_as_lunatranslator_drives_it(ocr):
    r = Reader(ocr)
    ocr.screen.text(BOX, DIALOGUE)
    read = r.read("builtin")
    assert read["text"] == "今日はいい天気ですね\n散歩に行こうか" and read["lines"] == 2 and read["error"] == ""
    # LunaTranslator's settings: 4 threads, the CPU; PP-OCRv5's three files; either way of writing (2) unless asked.
    lines = said(ocr, "cvutils")
    assert lines[:2] == ["runtime", "init det=det.onnx threads=4 gpu=0 luid=0 device=CPU"]
    assert lines[-1] == "detect mode=2 600x110"
    r.read("builtin", direction="v")
    assert said(ocr, "cvutils")[-1] == "detect mode=1 600x110"
    # Furigana over a word is left out; the line is the words, in reading order.
    ocr.screen.text(BOX, [(110, 30, 60, 30, "天気"), (10, 30, 100, 30, "今日はいい"), (112, 16, 40, 12, "てんき"),
                          (170, 30, 80, 30, "ですね")])
    assert r.read("builtin")["text"] == "今日はいい天気ですね"
    assert r.read("builtin", furigana=False)["text"] == "てんき\n今日はいい天気ですね"
    # Vertical text: columns, right to left (a word's reading beside it, to its right, left out).
    ocr.screen.text(BOX, [(300, 5, 30, 100, "縦書きの"), (260, 5, 30, 80, "文章です"), (332, 10, 12, 30, "たて")])
    assert r.read("builtin")["text"] == "縦書きの\n文章です"
    r.close()


def test_windows_ocr_reads_small_letters_made_bigger(ocr):
    r = Reader(ocr)
    small = (100, 400, 600, 24)
    ocr.screen.text(small, [(5, 4, 200, 16, "小さい字です"), (220, 4, 100, 16, "Hello")])
    read = r.read("windows", rect=small)
    # Windows reads no letters smaller than 40 pixels: the picture is made twice as big (as LunaTranslator does), the
    # lines' places brought back; the spaces Windows puts between Japanese words are taken out.
    assert said(ocr, "winocr")[-1] == "ocr lang=ja 1200x48 bits=24"
    assert read["text"] == "小さい字ですHello" and read["lines"] == 1
    r.read("windows", rect=BOX, lang="en-US")
    assert said(ocr, "winocr")[-1] == "ocr lang=en-US 600x110 bits=24"
    # A language Windows has no OCR of is never given to it.
    count = len(said(ocr, "winocr"))
    assert "no OCR for zh-Hans" in r.read("windows", rect=BOX, lang="zh-Hans")["error"]
    assert len(said(ocr, "winocr")) == count
    r.close()


def test_google_lens_directly_and_through_tor(ocr):
    r = Reader(ocr)
    ocr.screen.text(BOX, DIALOGUE)
    read = r.read("lens")
    assert read["text"] == "今日はいい天気ですね\n散歩に行こうか" and read["error"] == ""
    request = ocr.lens.requests[-1]
    assert request["path"] == "/v1/crupload" and request["headers"]["X-Goog-Api-Key"] == ocrd.LensReader.KEY
    assert request["headers"]["Content-Type"] == "application/x-protobuf"
    # Never by itself: "auto" takes an offline reader.
    assert r.read("auto")["engine"] == "builtin"
    r.close()
    socks = ocrfake.Socks()
    try:
        r = Reader(ocr, "--socks", f"127.0.0.1:{socks.port}", network="tor")
        assert "through Tor" in r.engines()["lens"]["why"]
        assert r.read("lens")["text"] == "今日はいい天気ですね\n散歩に行こうか"
        port = int(ocr.lens.url.split(":")[2].split("/")[0])
        assert socks.asked == [("127.0.0.1", port)]
        r.close()
    finally:
        socks.close()
    r = Reader(ocr, network="offline")
    assert "offline" in r.read("lens")["error"]
    r.close()


# ---------------------------------------------------------------- when the box is read


def watch(r, **more):
    params = {"hwnd": 42420, "pid": 4242, "box": IN_WINDOW, "client": [700, 500], "engine": "builtin", "mode": "auto"}
    params.update(more)
    r.send(cmd="watch", **params)
    wait_for(lambda: r.seen(ev="watching"))


def test_a_box_is_read_as_its_text_changes(ocr):
    r = Reader(ocr)
    ocr.screen.text(BOX, DIALOGUE)
    watch(r)
    wait_for(lambda: r.texts() == ["今日はいい天気ですね\n散歩に行こうか"])
    assert r.seen(ev="text")[0]["box"] == list(BOX) and r.seen(ev="capture", how="screen")
    # Drawn again, on another colour (the box fading): read again, and the same text not said again.
    count = len([line for line in said(ocr, "cvutils") if line.startswith("detect")])
    ocr.screen.text(BOX, DIALOGUE, fill=(90, 90, 120))
    wait_for(lambda: len([line for line in said(ocr, "cvutils") if line.startswith("detect")]) == count + 1)
    time.sleep(0.6)
    assert len(r.texts()) == 1
    # A picture as it was before (the arrow at the end of a line that blinks): not read again.
    ocr.screen.text(BOX, DIALOGUE)
    time.sleep(1.0)
    assert len([line for line in said(ocr, "cvutils") if line.startswith("detect")]) == count + 1
    # A line that comes a letter at a time is read once it is all there.
    line = "空がとても青いね、本当に"
    for n in range(2, len(line) + 1, 2):
        ocr.screen.text(BOX, [(10, 10, 30 * n, 36, line[:n])])
        time.sleep(0.12)
    wait_for(lambda: len(r.texts()) == 2)
    time.sleep(0.8)
    assert r.texts()[1:] == [line]
    # "Read now": read and said, though nothing changed.
    r.send(cmd="once")
    wait_for(lambda: len(r.texts()) == 3)
    assert r.seen(ev="text")[-1]["forced"] is True and r.texts()[-1] == line
    # The window made bigger: the box with it, where it was.
    ocr.screen.window(42420, 4242, (0, 0, 800, 600))
    r.send(cmd="once")
    wait_for(lambda: len(r.texts()) == 4)
    assert r.seen(ev="text")[-1]["box"] == [round(50 * 800 / 700), round(350 * 600 / 500), round(600 * 800 / 700), round(110 * 600 / 500)]
    r.close()


def test_the_game_in_front_and_out_of_sight(ocr):
    r = Reader(ocr)
    ocr.screen.text(BOX, DIALOGUE)
    ocr.screen.put(foreground=777)  # another program in front
    watch(r)
    wait_for(lambda: r.seen(ev="status", state="behind"))
    time.sleep(0.8)
    assert r.texts() == []
    # Sluka's own window in front (where it is left out of the pictures): read on.
    watch(r, allow=[777])
    wait_for(lambda: r.texts() == ["今日はいい天気ですね\n散歩に行こうか"])
    # Minimized: waited for.
    ocr.screen.window(42420, 4242, CLIENT, minimized=True)
    wait_for(lambda: r.seen(ev="status", state="hidden"))
    ocr.screen.window(42420, 4242, CLIENT, minimized=False)
    # Closed: said, and the watch ends.
    ocr.screen.window(42420, 4242, CLIENT, gone=True)
    wait_for(lambda: r.seen(ev="stopped", why="gone"))
    # A box on the screen, in no window: read wherever it is.
    ocr.screen.text(BOX, [(10, 10, 200, 36, "画面の字")])
    r.send(cmd="watch", hwnd=0, box=list(BOX), engine="windows")
    wait_for(lambda: r.texts()[-1:] == ["画面の字"])
    r.close()


def test_every_few_seconds_and_after_a_click(ocr):
    r = Reader(ocr)
    ocr.screen.text(BOX, DIALOGUE)
    watch(r, mode="interval", interval=1.5)
    wait_for(lambda: len(r.texts()) == 1, timeout=5)
    first = time.monotonic()
    ocr.screen.text(BOX, [(10, 10, 200, 36, "二行目")])
    wait_for(lambda: len(r.texts()) == 2, timeout=5)
    assert time.monotonic() - first > 0.9  # not before the time is up
    # After a click (or Enter, or Space) in the game, once the box has settled.
    watch(r, mode="trigger")
    ocr.screen.text(BOX, [(10, 10, 200, 36, "三行目")])
    time.sleep(1.0)
    assert r.texts()[-1] == "二行目"
    ocr.screen.put(keys=["click"])
    time.sleep(0.3)
    ocr.screen.put(keys=[])
    wait_for(lambda: r.texts()[-1] == "三行目")
    # A key pressed while another program is in front is not the game's.
    ocr.screen.text(BOX, [(10, 10, 200, 36, "四行目")])
    ocr.screen.put(foreground=777, keys=["enter"])
    time.sleep(0.6)
    ocr.screen.put(foreground=4242, keys=[])
    time.sleep(0.8)
    assert r.texts()[-1] == "三行目"
    r.close()


def test_the_box_dragged_over_the_screen(ocr):
    r = Reader(ocr)
    ocr.screen.put(select=[100, 400, 700, 510])
    r.send(cmd="select", delay=0.1, exclude=[1000])
    wait_for(lambda: r.seen(ev="selected"))
    event = r.seen(ev="selected")[0]
    assert event["rect"] == [100, 400, 700, 510]
    assert event["window"] == {"hwnd": 42420, "pid": 4242, "title": "桜の詩", "class": "GameWindow", "client": list(CLIENT),
                               "box": IN_WINDOW}
    # Sluka's own window over the game is never the one read: the game's under it is.
    ocr.screen.state["windows"].insert(0, {"hwnd": 9, "pid": 1000, "client": [0, 0, 800, 600], "title": "Sluka", "class": "SlukaDesktopWindow"})
    ocr.screen.save()
    r.send(cmd="select", delay=0, exclude=[1000])
    wait_for(lambda: len(r.seen(ev="selected")) == 2)
    assert r.seen(ev="selected")[1]["window"]["hwnd"] == 42420
    # Over no window; and none dragged.
    ocr.screen.put(select=[720, 10, 790, 60])
    r.send(cmd="select", delay=0, exclude=[1000])
    wait_for(lambda: len(r.seen(ev="selected")) == 3)
    assert r.seen(ev="selected")[2]["window"] is None
    ocr.screen.put(select=None)
    r.send(cmd="select", delay=0, exclude=[])
    wait_for(lambda: len(r.seen(ev="selected")) == 4)
    assert r.seen(ev="selected")[3] == {"ev": "selected", "cancelled": True}
    r.close()


def test_a_reader_that_cannot_start_is_said(ocr, monkeypatch):
    monkeypatch.setenv("FAKE_ORT_FAIL", "1")
    r = Reader(ocr)
    ocr.screen.text(BOX, DIALOGUE)
    r.send(cmd="watch", hwnd=42420, pid=4242, box=IN_WINDOW, client=[700, 500], engine="builtin")
    wait_for(lambda: r.seen(ev="stopped", why="unavailable"))
    assert not r.seen(ev="watching")
    assert "ONNX Runtime" in r.seen(ev="error")[0]["text"]
    # "auto": the next one that works here.
    watch(r, engine="auto")
    wait_for(lambda: r.seen(ev="watching", engine="windows"))
    wait_for(lambda: r.texts() == ["今日はいい天気ですね\n散歩に行こうか"])
    r.close()


# ---------------------------------------------------------------- the pieces


def test_pictures_and_lines():
    img = ocrd.Image(3, 2, bytes(range(24)))
    assert ocrd.from_bmp(ocrd.to_bmp(img)).bgr() == img.bgr()
    assert ocrd.Image(4, 4, b"\0" * 64).blank() and ocrd.Image(4, 4, b"\xff" * 64).blank()
    assert not ocrd.Image(4, 4, b"\x30" * 64).blank()  # one colour, not black or white: a text box with nothing in it yet
    assert ocrd.tidy("今日 は いい 天気 ですね  Hello  world") == "今日はいい天気ですね Hello world"
    assert ocrd.same_text("今日はいい天気ですね", "今日はいい天気ですわ") and not ocrd.same_text("はい", "いいえ")
    assert ocrd.arrange([((0, 0, 50, 20), "Hello"), ((60, 0, 110, 20), "world"), ((0, 30, 40, 50), "again")]) == ("Hello world\nagain", 2)
    assert ocrd.place((100, 100, 800, 600), (10, 400, 780, 150), (800, 600)) == (110, 500, 780, 150)
    assert ocrd.place((0, 0, 1600, 1200), (10, 400, 780, 150), (800, 600)) == (20, 800, 1560, 300)


# ---------------------------------------------------------------- the Screen tab, in the app


class ScreenProcs(FakeProcs):
    """The programs, with what the screen reader asks of them too: Sluka's own windows, and a game's."""

    def __init__(self):
        super().__init__()
        self.own = [{"hwnd": 9, "class": "SlukaDesktopWindow", "visible": True, "minimized": False},
                    {"hwnd": 8, "class": "SlukaDesktopBar", "visible": True, "minimized": False},
                    {"hwnd": 7, "class": "SlukaDesktopWindow", "visible": False, "minimized": False}]
        self.can_leave_out = True
        self.left_out = {}
        self.shown = []

    def own_windows(self, classes=(), visible=True):
        return [dict(w) for w in self.own if w["visible"] or not visible]

    def keep_out_of_captures(self, hwnds, on):
        if not self.can_leave_out:
            return 0
        for hwnd in hwnds:
            self.left_out[hwnd] = on
        return len(hwnds)

    def show_window(self, hwnd, how):
        self.shown.append((hwnd, how))
        return True

    # Sluka Vision's "Pause the game" (winproc.Procs.pause): the programs paused, and why one may not be.
    paused: list = []
    refuse_pause = ""

    def pause(self, pid):
        if self.refuse_pause:
            return None, self.refuse_pause
        procs = self
        procs.paused = procs.paused + [pid]
        procs.pause_log = getattr(procs, "pause_log", []) + [("pause", pid)]

        class Paused:
            started = 777

            def __init__(self):
                self.pid = pid

            def resume(self):
                procs.paused = [p for p in procs.paused if p != pid]
                procs.pause_log = procs.pause_log + [("resume", pid)]
                return True

        return Paused(), ""

    def resume_left(self, pid, started):
        self.pause_log = getattr(self, "pause_log", []) + [("left", pid, started)]
        return True

    def windows_of(self, pids):
        return [{"hwnd": pid * 10, "pid": pid, "title": title, "class": "GameWindow", "minimized": False}
                for pid, (_p, _b, title) in self.running.items() if pid in pids and pid not in self.windowless]


@pytest.fixture
def app(tmp_path, ocr):
    config = type("C", (), {"data_dir": tmp_path / "data", "log_dir": tmp_path / "data" / "logs", "network_mode": "direct",
                            "socks": "127.0.0.1:9050", "engine_dir": ocr.engine, "root": tmp_path})()
    host = type("H", (), {})()
    host.bar = FakeBar()
    procs = ScreenProcs()
    made = []

    def build(lens_ok=True, lens_ask=None, popup=None):
        """The game text, as the app has it; Google Lens as if it had had its yes before (lens_ok), or asked by
        lens_ask (lensask.py); its messages that pop up, to popup (none shown)."""
        gt = gametext.GameText(config, host, procs=procs, clipboard_factory=FakeClipboard, lens_ask=lens_ask,
                               popup=popup or (lambda title, text: None))
        if lens_ok:
            gt.settings["lens_ok"] = True
        gt.start()
        made.append(gt)
        return gt

    yield SimpleNamespace(build=build, host=host, procs=procs, config=config, ocr=ocr)
    for gt in made:
        gt.close()


def screen_state(gt):
    return ask(gt, "state")["screen"]


def test_the_screen_tab_end_to_end(app):
    ocr, procs, host = app.ocr, app.procs, app.host
    gt = app.build()
    assert ask(gt, "mode", {"mode": "screen"}) == {"ok": True, "mode": "screen"}
    assert host.bar.on  # (the floating subtitles come on)
    wait_for(lambda: screen_state(gt)["engines"])
    state = screen_state(gt)
    assert state["active"] and state["running"] and state["auto"] == "builtin" and state["target"] is None
    assert state["engines"]["windows"]["ok"] and state["engines"]["lens"]["ok"]

    # The box dragged over the game: Sluka's windows left out of the pictures meanwhile, the window under it read.
    ocr.screen.text(BOX, DIALOGUE)
    ocr.screen.put(select=[100, 400, 700, 510])
    assert ask(gt, "ocr-select") == {"ok": True}
    wait_for(lambda: (screen_state(gt)["target"] or {}).get("state") == "watching")
    assert procs.left_out == {9: True, 8: True} and procs.shown == []  # (the never-shown window 7 left as it is)
    target = screen_state(gt)["target"]
    assert (target["hwnd"], target["pid"], target["exe"], target["box"], target["engine"]) == (42420, 4242, "sakura.exe", IN_WINDOW, "builtin")
    assert target["kept"] and screen_state(gt)["excluded"] is True
    wait_for(lambda: host.bar.lines == ["今日はいい天気ですね散歩に行こうか"])  # (its lines made one, as the menu says)
    assert screen_state(gt)["last"]["text"] == "今日はいい天気ですね散歩に行こうか"
    assert ask(gt, "state")["last"]["from"] == "screen"
    # Kept for the game, where it is in its window.
    gt.screen._save()
    kept = json.loads((app.config.data_dir / "screentext.json").read_text(encoding="utf-8"))["games"]
    assert kept["c:\\games\\sakura\\sakura.exe"]["box"] == IN_WINDOW and kept["c:\\games\\sakura\\sakura.exe"]["client"] == [700, 500]

    # On the clipboard too, where asked; the lines as they are, where they are not to be made one.
    ask(gt, "settings", {"settings": {"copy": True, "join": False}})
    ocr.screen.text(BOX, [(10, 10, 300, 36, "空がとても青い"), (10, 56, 200, 36, "本当に")])
    wait_for(lambda: host.bar.lines[-1:] == ["空がとても青い\n本当に"])
    assert gt.clipboard.put_lines == ["空がとても青い\n本当に"]
    # Read now.
    assert ask(gt, "ocr-once") == {"ok": True}
    wait_for(lambda: len(host.bar.lines) == 3)
    # Another reader, chosen: read with it from then on.
    ask(gt, "settings", {"settings": {"ocr_engine": "windows"}})
    wait_for(lambda: screen_state(gt)["target"]["engine"] == "windows")
    ask(gt, "ocr-once")
    wait_for(lambda: screen_state(gt)["last"]["engine"] == "windows")
    assert any(line.startswith("ocr lang=ja 600x110") for line in said(ocr, "winocr"))

    # Stopped: Sluka's windows back in the pictures; not read again by itself while the game runs.
    assert ask(gt, "ocr-stop") == {"ok": True}
    assert screen_state(gt)["target"]["state"] == "stopped" and procs.left_out == {9: False, 8: False}
    time.sleep(3.5)
    assert screen_state(gt)["target"]["state"] == "stopped"
    assert ask(gt, "ocr-start") == {"ok": True}
    wait_for(lambda: screen_state(gt)["target"]["state"] == "watching")

    # The game closes: said. Started again, its box is read again by itself, in its new window.
    del procs.running[4242]
    ocr.screen.window(42420, 4242, CLIENT, gone=True)
    wait_for(lambda: screen_state(gt)["target"]["state"] == "ended")
    procs.running[4343] = ("C:\\Games\\Sakura\\sakura.exe", 32, "桜の詩")
    ocr.screen.window(43430, 4343, CLIENT, title="桜の詩")
    ocr.screen.put(foreground=4343)
    ocr.screen.text(BOX, [(10, 10, 300, 36, "また会ったね")])
    wait_for(lambda: (screen_state(gt)["target"] or {}).get("pid") == 4343, timeout=10)
    wait_for(lambda: host.bar.lines[-1:] == ["また会ったね"])
    assert any("its box is read, as before" in line[2] for line in ask(gt, "state")["log"])

    # Forgotten: not read by itself the next time.
    assert ask(gt, "ocr-forget") == {"ok": True}
    assert not screen_state(gt)["target"]["kept"] and screen_state(gt)["kept"] == 0
    # Another tab: the screen reader stops, Sluka's windows are back in the pictures.
    runner = gt.screen.runner
    ask(gt, "mode", {"mode": "clipboard"})
    assert screen_state(gt)["running"] is False and not runner.alive and set(procs.left_out.values()) == {False}


def test_the_game_own_window_read_keeps_slukas_windows_in_pictures(app):
    ocr, procs, host = app.ocr, app.procs, app.host
    gt = app.build()
    # The game's own window read: Sluka's windows -- the floating subtitles -- stay in screenshots and recordings
    # while its box is read (only the box dragged over the screen leaves them out, for the time it is dragged).
    ask(gt, "settings", {"settings": {"ocr_capture": "window"}})
    assert ask(gt, "mode", {"mode": "screen"})["ok"]
    wait_for(lambda: screen_state(gt)["engines"])
    ocr.screen.text(BOX, DIALOGUE)
    ocr.screen.put(select=[100, 400, 700, 510])
    assert ask(gt, "ocr-select") == {"ok": True}
    wait_for(lambda: (screen_state(gt)["target"] or {}).get("how") == "window")
    wait_for(lambda: host.bar.lines == ["今日はいい天気ですね散歩に行こうか"])
    wait_for(lambda: procs.left_out == {9: False, 8: False})
    time.sleep(2.5)
    assert procs.left_out == {9: False, 8: False}
    # The game's window gives no picture of itself: the screen is read there, Sluka's windows left out of it
    # meanwhile (else the floating subtitles over the box would be read back), and the menu says why.
    ocr.screen.put(blank=["window"])
    wait_for(lambda: screen_state(gt)["target"]["how"] == "screen", timeout=10)
    wait_for(lambda: procs.left_out == {9: True, 8: True})
    assert any("cannot be read as it shows" in line[2] for line in ask(gt, "state")["log"])
    # Its own picture again: in them again.
    ocr.screen.put(blank=[])
    wait_for(lambda: screen_state(gt)["target"]["how"] == "window", timeout=10)
    wait_for(lambda: procs.left_out == {9: False, 8: False})
    assert 7 not in procs.left_out
    assert ask(gt, "ocr-stop") == {"ok": True}


def test_where_windows_cannot_leave_slukas_windows_out(app):
    ocr, procs = app.ocr, app.procs
    procs.can_leave_out = False
    gt = app.build()
    ask(gt, "mode", {"mode": "screen"})
    wait_for(lambda: screen_state(gt)["running"])
    ocr.screen.text(BOX, DIALOGUE)
    ocr.screen.put(select=[100, 400, 700, 510])
    ask(gt, "ocr-select")
    wait_for(lambda: (screen_state(gt)["target"] or {}).get("state") == "watching")
    # They step aside while the box is dragged (the subtitles hidden, the windows minimized), and come back.
    assert procs.shown == [(9, "minimize"), (8, "hide"), (9, "restore"), (8, "show")]
    assert screen_state(gt)["excluded"] is None
    wait_for(lambda: app.host.bar.lines)
    # Sluka in front: not read (its window could be over the box), as another program's.
    ocr.screen.put(foreground=1000)
    ocr.screen.text(BOX, [(10, 10, 300, 36, "読まれない")])
    wait_for(lambda: screen_state(gt)["target"]["status"] == "behind")
    assert app.host.bar.lines[-1] != "読まれない"
    # The game's own window read instead: Sluka in front does not matter.
    ask(gt, "settings", {"settings": {"ocr_capture": "window"}})
    wait_for(lambda: app.host.bar.lines[-1:] == ["読まれない"])
    assert screen_state(gt)["target"]["how"] == "window"


def test_a_box_over_no_window_and_none_dragged(app):
    ocr = app.ocr
    gt = app.build()
    ocr.screen.text((720, 10, 70, 60), [])
    ocr.screen.put(select=None)
    assert ask(gt, "ocr-select") == {"ok": True}  # (the Screen tab chosen by it)
    assert ask(gt, "state")["mode"] == "screen"
    wait_for(lambda: any("No box was dragged" in line[2] for line in ask(gt, "state")["log"]))
    assert screen_state(gt)["target"] is None and not screen_state(gt)["selecting"]
    assert set(app.procs.left_out.values()) == {False}
    big = (300, 0, 480, 40)
    ocr.screen.text(big, [(5, 5, 200, 30, "字幕の行")])
    ocr.screen.put(select=[300, 0, 780, 40])
    ask(gt, "ocr-select")
    wait_for(lambda: app.host.bar.lines == ["字幕の行"])
    target = screen_state(gt)["target"]
    assert target["hwnd"] == 0 and target["box"] == list(big) and not target["kept"]
    # Settings that are not what they may be are not taken.
    assert ask(gt, "settings", {"settings": {"ocr_engine": "tesseract", "ocr_lang": "ja; del", "ocr_interval_ms": 1}})["settings"]["ocr_engine"] == "auto"
    assert gt.settings["ocr_lang"] == "ja" and gt.settings["ocr_interval_ms"] == 300


def test_the_reader_that_stops_is_started_again(app):
    ocr = app.ocr
    gt = app.build()
    ocr.screen.text(BOX, DIALOGUE)
    ocr.screen.put(select=[100, 400, 700, 510])
    ask(gt, "ocr-select")
    wait_for(lambda: app.host.bar.lines)
    first = gt.screen.runner
    first.proc.kill()
    wait_for(lambda: gt.screen.runner is not None and gt.screen.runner is not first and gt.screen.runner.alive, timeout=10)
    wait_for(lambda: screen_state(gt)["target"]["state"] == "watching", timeout=10)
    assert any("screen reader stopped" in line[2] for line in ask(gt, "state")["log"])


def test_ocr_check_from_the_command_line(app):
    ocr = app.ocr
    ocr.screen.text(BOX, DIALOGUE)
    ocr.screen.put(select=[100, 400, 700, 510])
    out = __import__("io").StringIO()
    assert ocrtext.command_check(app.config, read=True, out=out) == 0
    text = out.getvalue()
    assert "ok: Sluka's own OCR (builtin): offline" in text and "ok: Windows' OCR (windows)" in text
    assert "ok: the box 600×110 at 100,400, over 桜の詩" in text
    assert text.count("    今日はいい天気ですね") == 2 and "Google Lens OCR," not in text  # (only when asked for by name)
    out = __import__("io").StringIO()
    assert ocrtext.command_check(app.config, reader="lens", out=out) == 0
    assert "ok: Google Lens OCR," in out.getvalue() and len(ocr.lens.requests) == 1


def test_the_readers_that_come_with_the_app():
    """The engine folder's ocr folder of the working copy: LunaTranslator 12.1.3.12's files, as OCR.txt lists them, with
    the functions ocrd.py calls in them."""
    import hashlib
    import struct

    folder = Path(fakes.APP).parent / "engine" / "ocr"
    notice = (folder / "OCR.txt").read_bytes().decode("utf-8")
    assert "\r\n" in notice and "LunaTranslator 12.1.3.12" in notice and "GNU General Public License, version 3" in notice
    names = ["CVUtils.dll", "NativeUtils.dll", "onnxruntime.dll", "concrt140.dll", "msvcp140.dll", "msvcp140_1.dll",
             "vcruntime140.dll", "vcruntime140_1.dll", "model/det.onnx", "model/rec.onnx", "model/dict.txt", "model/info.json"]
    for name in names:
        data = (folder / name).read_bytes()
        assert f"{hashlib.sha256(data).hexdigest()}  {name.replace('/', chr(92))}" in notice, name
    assert json.loads((folder / "model" / "info.json").read_text())["name"] == "PP-OCRv5_mobile"
    for name in names[:8]:
        data = (folder / name).read_bytes()
        pe = struct.unpack_from("<I", data, 0x3C)[0]
        assert data[pe:pe + 4] == b"PE\0\0" and struct.unpack_from("<H", data, pe + 4)[0] == 0x8664, name
    cv = (folder / "CVUtils.dll").read_bytes()
    for name in ("OcrLoadRuntime", "OcrInit", "OcrDetect", "OcrDestroy", "cvMatFromBGR888", "cvMatDestroy"):
        assert name.encode() + b"\0" in cv, name
    native = (folder / "NativeUtils.dll").read_bytes()
    for name in ("winrt_OCR", "winrt_OCR_check_language_valid", "winrt_OCR_get_AvailableRecognizerLanguages",
                 "glens_create_request", "glens_parse_response", "CreateSelectRangeWindow"):
        assert name.encode() + b"\0" in native, name
    assert (folder.parent / "LICENSES" / "LICENSE.microsoft.onnxruntime").read_text().startswith("MIT License")


# ---------------------------------------------------------------- the keys


def test_keys_as_they_are_written():
    from sluka_desktop import hotkeys

    assert hotkeys.normal("ctrl + shift + r") == "Ctrl+Shift+R" and hotkeys.normal("") == ""
    assert hotkeys.parse("Ctrl+Shift+R") == (hotkeys.MOD_CONTROL | hotkeys.MOD_SHIFT, 0x52)
    assert hotkeys.parse("F8") == (0, 0x77) and hotkeys.parse("Alt+Num-") == (hotkeys.MOD_ALT, 0x6D)
    assert hotkeys.parse("Ctrl+F12") == (hotkeys.MOD_CONTROL, 0x7B)
    assert hotkeys.spec(hotkeys.MOD_ALT | hotkeys.MOD_SHIFT, 0xBD) == "Alt+Shift+-"
    for bad, why in (("R", "types"), ("Shift+5", "types"), ("Win+L", "Windows' own"), ("Hyper+R", "is not Ctrl"),
                     ("Ctrl+Foo", "not a key"), ("F12", "debuggers")):
        with pytest.raises(hotkeys.KeyError_, match=why):
            hotkeys.parse(bad)
    # Ctrl+Alt with a letter is AltGr with it on many keyboards (ș, ț on a Romanian one): said.
    assert "AltGr+S" in hotkeys.altgr_note("Ctrl+Alt+S") and hotkeys.altgr_note("Ctrl+Alt+F5") == ""
    assert hotkeys.altgr_note("Ctrl+Shift+S") == ""
    # Sluka's own keys, held for a moment (Sluka Vision's open panel), may be ones that type: never one you choose.
    assert hotkeys.parse("1", alone=True) == (0, 0x31) and hotkeys.parse("K", alone=True) == (0, 0x4B)
    assert hotkeys.parse("Esc", alone=True) == (0, 0x1B)
    with pytest.raises(hotkeys.KeyError_, match="types"):
        hotkeys.parse("1")


class FakeKeys:
    """Windows' hotkeys, as hotkeys.WindowsBackend holds them for one of the app's threads (each Hotkeys has a thread
    of its own): which are held, and a key pressed.  A key another thread holds is taken, as Windows has it."""

    def __init__(self, keyboard=None):
        self.keyboard = keyboard
        self.taken = keyboard.taken if keyboard is not None else set()
        self.applied = []
        self.held = {}
        self.on_press = None

    def start(self, on_press):
        self.on_press = on_press

    def apply(self, wanted):
        from sluka_desktop import hotkeys

        self.applied.append({number: hotkeys.spec(*key) for number, key in wanted.items()})
        others = set()
        if self.keyboard is not None:
            for backend in self.keyboard.backends:
                if backend is not self:
                    others |= set(backend.held)
        errors = {n: "it is taken by another program, or by Windows" for n, key in wanted.items()
                  if hotkeys.spec(*key) in self.taken or hotkeys.spec(*key) in others}
        self.held = {hotkeys.spec(*key): n for n, key in wanted.items() if n not in errors}
        return errors

    def close(self):
        self.held = {}

    def press(self, key):
        number = self.held[key]
        self.on_press(number)


class FakeKeyboard:
    """The keys of every thread of the app's that holds some (hotkeys.make_backend makes one each): all those held,
    those another program has, and a key pressed -- for the thread that holds it."""

    def __init__(self):
        self.taken = set()
        self.backends = []

    def make(self):
        backend = FakeKeys(self)
        self.backends.append(backend)
        return backend

    @property
    def held(self):
        out = {}
        for backend in self.backends:
            out.update(backend.held)
        return out

    def press(self, key):
        for backend in self.backends:
            if key in backend.held:
                backend.press(key)
                return
        raise KeyError(key)


@pytest.fixture
def keys(monkeypatch):
    from sluka_desktop import hotkeys

    keyboard = FakeKeyboard()
    monkeypatch.setattr(hotkeys, "make_backend", keyboard.make)
    return keyboard


def press(gt, keys, key):
    keys.press(key)


def test_keys_from_the_game(app, keys):
    ocr = app.ocr
    gt = app.build()
    ask(gt, "mode", {"mode": "screen"})
    wait_for(lambda: screen_state(gt)["running"])
    # Set in the menu: what was pressed there (Windows' number for the key, and the modifiers).
    assert ask(gt, "ocr-key", {"action": "select", "vk": 0x53, "ctrl": True, "shift": True}) == {"ok": True, "key": "Ctrl+Shift+S"}
    assert ask(gt, "ocr-key", {"action": "read", "vk": 0x52, "ctrl": True, "shift": True}) == {"ok": True, "key": "Ctrl+Shift+R"}
    assert ask(gt, "ocr-key", {"action": "once", "vk": 0x77}) == {"ok": True, "key": "F8"}
    assert ask(gt, "ocr-key", {"action": "toggle", "vk": 0x50, "alt": True, "shift": True}) == {"ok": True, "key": "Alt+Shift+P"}
    assert set(keys.held) == {"Ctrl+Shift+S", "Ctrl+Shift+R", "F8", "Alt+Shift+P"}
    state = screen_state(gt)["keys"]
    assert state["read"] == {"key": "Ctrl+Shift+R", "error": "", "held": True, "note": ""}
    assert gt.settings["ocr_key_once"] == "F8"
    # Not to be had: a letter alone, a key another action has, a key another program has (the one before stays).
    assert ask(gt, "ocr-key", {"action": "read", "vk": 0x52})["error"] == "R alone types: take it with Ctrl or Alt"
    assert "is the key of “Select the text box” already" in ask(gt, "ocr-key", {"action": "read", "vk": 0x53, "ctrl": True, "shift": True})["error"]
    keys.taken.add("Ctrl+Shift+Q")
    answer = ask(gt, "ocr-key", {"action": "read", "vk": 0x51, "ctrl": True, "shift": True})
    assert answer == {"ok": False, "error": "Ctrl+Shift+Q: it is taken by another program, or by Windows. Choose another key."}
    assert gt.settings["ocr_key_read"] == "Ctrl+Shift+R" and "Ctrl+Shift+R" in keys.held
    # While the menu waits for a key, the keys are let go of (one of them pressed reaches the menu), then held again.
    ask(gt, "ocr-keys-listen", {"on": True})
    assert keys.held == {} and screen_state(gt)["listening"]
    ask(gt, "ocr-keys-listen", {"on": False})
    assert len(keys.held) == 4

    # In the game: the box selected...
    ocr.screen.text(BOX, DIALOGUE)
    ocr.screen.put(select=[100, 400, 700, 510])
    press(gt, keys, "Ctrl+Shift+S")
    wait_for(lambda: (screen_state(gt)["target"] or {}).get("state") == "watching")
    wait_for(lambda: app.host.bar.lines == ["今日はいい天気ですね散歩に行こうか"])
    # ... read now ...
    press(gt, keys, "Ctrl+Shift+R")
    wait_for(lambda: len(app.host.bar.lines) == 2)
    # ... a box read once, anywhere (the one kept stays) ...
    ocr.screen.text((300, 0, 480, 40), [(5, 5, 200, 30, "看板の字")])
    ocr.screen.put(select=[300, 0, 780, 40])
    press(gt, keys, "F8")
    wait_for(lambda: app.host.bar.lines[-1:] == ["看板の字"])
    state = screen_state(gt)
    assert state["target"]["box"] == IN_WINDOW and state["last"]["once"] is True and state["last"]["text"] == "看板の字"
    assert not gt.screen._once_pending and set(app.procs.left_out.values()) == {True}  # (still reading its box)
    # ... stopped and started again.
    press(gt, keys, "Alt+Shift+P")
    wait_for(lambda: screen_state(gt)["target"]["state"] == "stopped")
    press(gt, keys, "Alt+Shift+P")
    wait_for(lambda: screen_state(gt)["target"]["state"] == "watching")
    # A box dragged once, none: said; the key pressed again while the box is dragged stops it.
    ocr.screen.put(select=None)
    press(gt, keys, "F8")
    wait_for(lambda: any("No box was dragged" in line[2] for line in ask(gt, "state")["log"]))
    # None for an action: let go of.
    assert ask(gt, "ocr-key", {"action": "once", "clear": True}) == {"ok": True, "key": ""}
    assert "F8" not in keys.held
    # Another tab: no keys held; back, they are.
    ask(gt, "mode", {"mode": "clipboard"})
    assert keys.held == {}
    ask(gt, "mode", {"mode": "screen"})
    assert set(keys.held) == {"Ctrl+Shift+S", "Ctrl+Shift+R", "Alt+Shift+P"}


def test_keys_where_there_are_none(app):
    """Not Windows: keys are kept as set, and said not to be held."""
    gt = app.build()
    ask(gt, "mode", {"mode": "screen"})
    answer = ask(gt, "ocr-key", {"action": "read", "vk": 0x52, "ctrl": True, "shift": True})
    assert answer == {"ok": False, "error": "Ctrl+Shift+R: keys that work in every program are Windows'. Choose another key."}
    assert gt.settings["ocr_key_read"] == ""
