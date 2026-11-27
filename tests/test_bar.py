"""The floating subtitles: the app's side (bar.py), their window (winshell), and the way to them (the HTTP host)."""

from __future__ import annotations

import io
import json
import threading
import urllib.error
import urllib.request

import pytest

import fakes
from fakes import World
from test_winshell import free_port, make_app, post, wait_for

from sluka_desktop import winshell
from sluka_desktop.bar import Bar, command_bar, command_text


def get(port, path, headers=None):
    request = urllib.request.Request(f"http://127.0.0.1:{port}{path}", headers=headers or {})
    with urllib.request.urlopen(request, timeout=10) as answer:
        body = answer.read()
        kind = answer.headers.get("Content-Type", "")
    return json.loads(body) if kind.startswith("application/json") else body.decode("utf-8")


def kept(config) -> dict:
    """What the app has written down of the bar so far."""
    try:
        return json.loads((config.data_dir / "bar.json").read_text())
    except (OSError, ValueError):
        return {}


def bar_windows(world):
    return {h: w for h, w in world.win.windows.items() if w.get("class") == winshell.BAR_CLASS_NAME}


def view_of(world, hwnd):
    found = [w for w in world.webviews() if w.controller.hwnd == hwnd]
    return found[-1] if found else None


def test_the_floating_subtitles_end_to_end(tmp_path, monkeypatch):
    monkeypatch.setattr(winshell, "CLOSE_GRACE_MS", 60)
    monkeypatch.setattr(winshell, "QUIT_GRACE_MS", 60)
    port = free_port()
    config = make_app(tmp_path, port)
    # mpv is off in this app ([mpv] enabled = no): Sluka's engine runs for the bar all the same.
    assert config.bar_enabled and not config.mpv_enabled and config.bar_button == "bottom-left" and config.games_enabled
    world = World()
    failure = []
    W = world.win
    EX = winshell

    def driver():
        try:
            wait_for(lambda: len(world.webviews()) == 2 and world.webviews()[1].navigated, 10)
            main = world.webviews()[1].controller.hwnd
            # The window menu has it, and no mpv entry with mpv off.
            idents = [ident for _flags, ident, _text in W.menus[main]]
            assert EX.MENU_BAR in idents and EX.MENU_BAR_THROUGH in idents and EX.MENU_MPV not in idents
            boot = get(port, "/__sluka__/boot.js")
            assert '"bar": true' in boot and '"barButton": "bottom-left"' in boot and '"mpv": true' in boot
            assert '"games": true' in boot
            page = get(port, "/__sluka__/bar.html")
            assert "/__sluka__/shim.js" in page and "/__sluka__/bar.js" in page
            for name in ("bar.js", "bar.css", "dock.js"):
                assert get(port, f"/__sluka__/{name}")
            assert post(port, "bar/status", {})["on"] is False
            assert not bar_windows(world)

            # -- on, from the button of a window
            assert post(port, "bar/toggle", {}) == {"on": True}
            wait_for(lambda: bar_windows(world) and view_of(world, next(iter(bar_windows(world)))) is not None
                     and view_of(world, next(iter(bar_windows(world)))).navigated, 10)
            hwnd, window = next(iter(bar_windows(world).items()))
            view = view_of(world, hwnd)
            assert view.navigated == [f"http://127.0.0.1:{port}/__sluka__/bar.html"]
            # A frameless window over every other, with no taskbar button, that does not take the keyboard.
            assert window["ex"] & (EX.WS_EX_TOPMOST | EX.WS_EX_TOOLWINDOW | EX.WS_EX_NOACTIVATE) == \
                EX.WS_EX_TOPMOST | EX.WS_EX_TOOLWINDOW | EX.WS_EX_NOACTIVATE
            assert not window["ex"] & (EX.WS_EX_LAYERED | EX.WS_EX_TRANSPARENT)
            assert window["style"] == EX.WS_POPUP | EX.WS_CLIPCHILDREN
            # The screen of the app's window, all but its last row (never taken for a program gone full screen).
            assert (window["x"], window["y"], window["w"], window["h"]) == (0, 0, 2880, 1619)
            assert EX.SW_SHOWNOACTIVATE in window["shows"] and EX.SW_SHOWNORMAL not in window["shows"]
            # Nothing of it is seen until its page says what it draws; its ground is see-through, its page too.
            assert window["region"] == []
            assert W.blur[-1] == (hwnd, EX.DWM_BB_ENABLE | EX.DWM_BB_BLURREGION, 1, [])
            assert W.classes[EX.BAR_CLASS_NAME].hbrBackground == 0x4400 + EX.BLACK_BRUSH
            wait_for(lambda: view.controller.background == 0)
            assert view.controller.focus == 0
            assert world.settings[-1].values["IsZoomControlEnabled"] is False

            # -- its page: what it is set to, and Sluka's engine through the app
            got = post(port, "bar/poll", {"fresh": True})
            assert got["msgs"][0]["t"] == "state" and got["msgs"][0]["engine"] is True
            assert got["msgs"][0]["state"]["on"] is True
            assert post(port, "bar/say", {"msg": {"t": "hello", "v": 2, "sub_lang": ""}}) == {"ok": True}
            engine = post(port, "mpv/poll", {"fresh": True})
            assert {"player": "bar", "msg": {"t": "hello", "v": 2, "sub_lang": ""}} in engine["msgs"]
            assert post(port, "mpv/reply", {"player": "bar", "msg": {"t": "ready", "v": 2, "lang": "ja", "look": {"cjk": True}}})["ok"]
            said = [m for m in post(port, "bar/poll", {})["msgs"] if m["t"] == "engine"]
            assert said[-1]["msg"] == {"t": "ready", "v": 2, "lang": "ja", "look": {"cjk": True}}
            # The mpv bridge does not count it among its players.
            assert post(port, "mpv/status", {})["players"] == 0

            # -- a line from another program: by its address, by the command line, posted as plain text
            answer = get(port, "/__sluka__/api/bar/text?text=%E6%98%A5%E3%81%AE%E6%97%A5&lang=ja")
            assert answer["ok"] and answer["on"]
            msgs = post(port, "bar/poll", {})["msgs"]
            assert msgs[-1]["t"] == "text" and msgs[-1]["text"] == "春の日" and msgs[-1]["lang"] == "ja"
            out = io.StringIO()
            assert command_text(config, "  運命と\r\n出会い  ", out=out) == 0 and out.getvalue() == ""
            assert post(port, "bar/poll", {})["msgs"][-1]["text"] == "運命と\n出会い"
            request = urllib.request.Request(f"http://127.0.0.1:{port}/__sluka__/api/bar/text", data="plain words".encode(),
                                             headers={"Content-Type": "text/plain"})
            with urllib.request.urlopen(request, timeout=10) as reply:
                assert json.loads(reply.read())["ok"]
            assert post(port, "bar/poll", {})["msgs"][-1]["text"] == "plain words"
            # A web page may not: a browser says where the request comes from.
            with pytest.raises(urllib.error.HTTPError) as refused:
                get(port, "/__sluka__/api/bar/text?text=x", headers={"Sec-Fetch-Site": "cross-site"})
            assert refused.value.code == 403
            with pytest.raises(urllib.error.HTTPError) as refused:
                get(port, "/__sluka__/api/bar/state")
            assert refused.value.code == 405
            # A page that starts again has the last line at once.
            again = post(port, "bar/poll", {"fresh": True})["msgs"]
            assert again[-1] == {"t": "text", "text": "plain words", "at": again[-1]["at"]}

            # -- shaped to what the page draws, in the screen's pixels
            assert post(port, "bar/shape", {"rects": [[10, 20, 100, 50], [0, 0, 0, 5], ["x"]], "live": [[10, 20, 20, 20]],
                                            "all": False, "dpr": 1.5}) == {"ok": True}
            wait_for(lambda: window["region"] == [(15, 30, 165, 105)])
            post(port, "bar/shape", {"rects": [[10, 20, 100, 50]], "all": True, "dpr": 1.5})
            wait_for(lambda: window["region"] is None)
            post(port, "bar/shape", {"rects": [[10, 20, 100, 50]], "live": [[10, 20, 20, 20]], "dpr": 1.5})
            wait_for(lambda: window["region"] == [(15, 30, 165, 105)])

            # -- clicks through it, but where the page says, and anywhere on it with Ctrl
            W.cursor = (900, 900)
            assert post(port, "bar/state", {"state": {"through": True}})["state"]["through"] is True
            wait_for(lambda: window["ex"] & (EX.WS_EX_LAYERED | EX.WS_EX_TRANSPARENT) == EX.WS_EX_LAYERED | EX.WS_EX_TRANSPARENT)
            assert W.layered[-1] == (hwnd, 0, 0, 0)
            W.cursor = (20, 35)
            wait_for(lambda: not window["ex"] & EX.WS_EX_TRANSPARENT)
            assert window["ex"] & EX.WS_EX_LAYERED
            W.cursor = (100, 60)
            wait_for(lambda: window["ex"] & EX.WS_EX_TRANSPARENT)
            W.ctrl_down = True
            wait_for(lambda: not window["ex"] & EX.WS_EX_TRANSPARENT)
            W.ctrl_down = False
            wait_for(lambda: window["ex"] & EX.WS_EX_TRANSPARENT)
            post(port, "bar/state", {"state": {"through": False}})
            wait_for(lambda: not window["ex"] & (EX.WS_EX_LAYERED | EX.WS_EX_TRANSPARENT))
            assert hwnd in W.redrawn
            # Kept over every other window, now and then.
            wait_for(lambda: window["topmost"] >= 1, 5)

            # -- taken to the other screen
            answer = post(port, "bar/monitor", {"x": 2000, "y": 500, "dpr": 1.5})
            assert answer["ok"] and answer["fx"] == pytest.approx((3000 - 2880) / 1920) and answer["fy"] == pytest.approx(750 / 1080)
            assert (window["x"], window["y"], window["w"], window["h"]) == (2880, 0, 1920, 1079)
            assert post(port, "bar/monitor", {"x": 10, "y": 10, "dpr": 1}) == {"ok": False}  # the screen it is on
            wait_for(lambda: kept(config).get("monitor") == [2880, 0, 4800, 1080], 5)

            # -- the window menu says it is on, lets clicks through it and takes them back, and puts it away
            W.PostMessageW(main, EX.WM_INITMENU, 0x1234, 0)
            wait_for(lambda: (0x1234, EX.MENU_BAR, EX.MF_CHECKED) in W.checks)
            assert (0x1234, EX.MENU_BAR_THROUGH, 0) in W.checks
            W.system_command(main, EX.MENU_BAR_THROUGH)
            wait_for(lambda: window["ex"] & EX.WS_EX_TRANSPARENT)
            assert {"t": "set", "state": {"through": True}} in post(port, "bar/poll", {})["msgs"]
            W.PostMessageW(main, EX.WM_INITMENU, 0x1235, 0)
            wait_for(lambda: (0x1235, EX.MENU_BAR_THROUGH, EX.MF_CHECKED) in W.checks)
            W.system_command(main, EX.MENU_BAR_THROUGH)
            wait_for(lambda: not window["ex"] & EX.WS_EX_LAYERED)
            W.system_command(main, EX.MENU_BAR)
            wait_for(lambda: window["destroyed"], 5)
            assert post(port, "bar/status", {})["on"] is False
            wait_for(lambda: kept(config).get("on") is False, 5)
            # Sluka's engine is told the player is gone.
            assert {"player": "bar", "msg": {"t": "bye"}} in post(port, "mpv/poll", {})["msgs"]

            # -- on again from the command line: on the screen it was last on
            out = io.StringIO()
            assert command_bar(config, "on", out=out) == 0 and "on" in out.getvalue()
            wait_for(lambda: any(not w["destroyed"] for w in bar_windows(world).values()), 10)
            hwnd2, window2 = [(h, w) for h, w in bar_windows(world).items() if not w["destroyed"]][0]
            assert (window2["x"], window2["y"], window2["w"], window2["h"]) == (2880, 0, 1920, 1079)

            # -- the app's own window closed: the app ends, and the bar with it (to come back with it)
            W.close(main)
        except BaseException as err:
            failure.append(err)
            for h in list(W.app_windows()):
                W.close(h)

    thread = threading.Thread(target=driver, daemon=True)
    thread.start()
    code = winshell.run_app(config, api=world.win, entry=world.entry, runtime=fakes.runtime())
    thread.join(10)
    if failure:
        raise failure[0]
    assert code == 0
    assert not world.unexpected, world.unexpected
    assert all(w["destroyed"] for w in bar_windows(world).values())
    saved = json.loads((config.data_dir / "bar.json").read_text())
    assert saved["on"] is True and saved["monitor"] == [2880, 0, 4800, 1080] and saved["through"] is False
    assert command_bar(config, "toggle", out=io.StringIO()) == 1  # nothing running now


def test_the_bar_comes_back_where_it_was_left_on(tmp_path, monkeypatch):
    monkeypatch.setattr(winshell, "CLOSE_GRACE_MS", 60)
    monkeypatch.setattr(winshell, "QUIT_GRACE_MS", 60)
    port = free_port()
    config = make_app(tmp_path, port)
    (config.data_dir).mkdir(parents=True, exist_ok=True)
    (config.data_dir / "bar.json").write_text(json.dumps({"on": True, "x": 0.4, "y": 0.8, "scale": 9, "through": True,
                                                          "monitor": [2880, 0, 4800, 1080], "width": float("nan")}))
    world = World()
    failure = []

    def driver():
        try:
            wait_for(lambda: bar_windows(world), 10)
            hwnd, window = next(iter(bar_windows(world).items()))
            assert (window["x"], window["w"]) == (2880, 1920)
            # Clicks went through it when the app ended: they do again.
            wait_for(lambda: window["ex"] & (winshell.WS_EX_LAYERED | winshell.WS_EX_TRANSPARENT))
            state = post(port, "bar/poll", {"fresh": True})["msgs"][0]["state"]
            assert state["scale"] == 3.0 and "width" not in state and state["x"] == 0.4
        except BaseException as err:
            failure.append(err)
        finally:
            # The app's own window: the bar goes with it.
            for h, w in list(world.win.app_windows().items()):
                if w.get("class") != winshell.BAR_CLASS_NAME:
                    world.win.close(h)

    thread = threading.Thread(target=driver, daemon=True)
    thread.start()
    code = winshell.run_app(config, api=world.win, entry=world.entry, runtime=fakes.runtime())
    thread.join(10)
    if failure:
        raise failure[0]
    assert code == 0
    # Ended with the app, not put away: on at the next start.
    assert json.loads((config.data_dir / "bar.json").read_text())["on"] is True


def test_the_bar_alone_with_no_window_shell(tmp_path):
    """Where nothing can show it (no window side), it is still asked and answered, and keeps its settings."""

    class Host:
        mpv = None

    config = make_app(tmp_path, free_port())
    bar = Bar(config, Host())
    answers = []

    class Req:
        def __init__(self, method="POST", body=b"", query=None, headers=None):
            self.method, self.body, self.query, self.headers = method, body, query or {}, headers or {}

    bar.api("say", Req(body=json.dumps({"msg": {"t": "hello", "v": 2}}).encode()), answers.append)
    assert json.loads(answers[-1].body) == {"ok": False, "engine": False}
    bar.api("toggle", Req(), answers.append)
    assert json.loads(answers[-1].body) == {"on": True}
    bar.api("state", Req(body=json.dumps({"state": {"x": "0.2", "y": 7, "lock": "yes", "on": False}}).encode()), answers.append)
    state = json.loads(answers[-1].body)["state"]
    assert state["x"] == 0.2 and state["y"] == 1.5 and state["on"] is True and state["lock"] is False
    bar.api("poll", Req(body=b'{"fresh": true}'), answers.append)
    assert json.loads(answers[-1].body)["msgs"][0]["engine"] is False
    bar.api("text", Req(body=json.dumps({"text": "x" * 9000}).encode()), answers.append)
    assert json.loads(answers[-1].body)["ok"]
    waiting = []
    bar.api("poll", Req(body=b"{}"), waiting.append)
    assert len(json.loads(waiting[-1].body)["msgs"][-1]["text"]) == 4000
    bar.api("nonsense", Req(body=b"{}"), answers.append)
    assert answers[-1].status == 404
    bar.close()
    assert json.loads((config.data_dir / "bar.json").read_text())["x"] == 0.2
