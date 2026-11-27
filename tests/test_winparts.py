"""The Windows-only parts of game text (winproc.py, clipwatch.py) run against stand-ins for Windows' functions."""

from __future__ import annotations

import ctypes
import time

import pytest

import fakes  # noqa: F401  (puts the app on the path)
import fakewin

from sluka_desktop import clipwatch, winproc


def wait_for(check, timeout=5.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if check():
            return True
        time.sleep(0.01)
    raise AssertionError("waited too long")


@pytest.fixture
def world(monkeypatch):
    w = fakewin.World()
    dlls = fakewin.install(monkeypatch, w)
    monkeypatch.setattr(winproc, "WINDOWS", True)
    monkeypatch.setattr(winproc, "_api", None)
    monkeypatch.setattr(clipwatch, "WINDOWS", True)
    w.dlls = dlls
    return w


def test_the_programs_and_their_windows(world, monkeypatch):
    own = 1000
    world.procs = {
        own: ("C:\\Python\\python.exe", 1, False, True),
        1001: ("C:\\Program Files\\EdgeWebView\\msedgewebview2.exe", own, False, True),
        4242: ("C:\\Games\\Sakura\\sakura.exe", 1, True, True),
        5000: ("C:\\Games\\Admin\\admin.exe", 1, False, False),
        5: ("C:\\Windows\\explorer.exe", 1, False, True),
    }
    world.windows = [
        [11, 1001, "Sluka", 1, 0, 0, 0],
        [12, 4242, "桜の詩", 1, 0, 0, 0],
        [13, 4242, "a second window of the game", 1, 0, 0, 0],
        [14, 5000, "Admin game", 1, 0, 0, 0],
        [15, 5, "File Explorer", 1, 0, 0, 0],
        [16, 4242, "hidden", 0, 0, 0, 0],
        [17, 4242, "owned", 1, 12, 0, 0],
        [18, 5000, "tool", 1, 0, 0x80, 0],
        [19, 5000, "cloaked", 1, 0, 0, 1],
    ]
    procs = winproc.Procs()
    procs.own_pid = own
    assert [w["title"] for w in procs.windows()] == ["Sluka", "桜の詩", "Admin game", "File Explorer"]
    assert procs.exe(4242) == "C:\\Games\\Sakura\\sakura.exe" and procs.exe(9) == ""
    assert procs.bits(4242) == 32 and procs.bits(5000) == 64
    assert procs.can_reach(4242) == (True, "") and procs.can_reach(5000) == (False, "admin")
    assert procs.can_reach(9) == (False, "error 87")
    assert [p["pid"] for p in procs.processes()] == sorted(world.procs)
    found = winproc.candidates(procs)
    assert [(p["pid"], p["exe"], p["bits"], p["title"]) for p in found] == [(4242, "sakura.exe", 32, "桜の詩"), (5000, "admin.exe", 64, "Admin game")]
    world.foreground = 12
    assert procs.foreground_pid() == 4242 and procs.title_of(5000) == "Admin game"
    watch = procs.watch(4242)
    assert watch.alive()
    del world.procs[4242]
    assert not watch.alive()
    watch.close()
    assert procs.bind(77) and procs.bind(78)
    assert world.jobs[0] == ("limits", winproc.JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE | winproc.JOB_OBJECT_LIMIT_BREAKAWAY_OK)
    assert [j for j in world.jobs if j[0] == "assigned"] == [("assigned", 77), ("assigned", 78)]
    assert procs.is_admin() is False
    # A Windows without IsWow64Process2 (before Windows 10 1709).
    monkeypatch.setattr(winproc, "_api", None)
    for dll in world.dlls.values():
        dll._missing.add("IsWow64Process2")
    world.procs[4242] = ("C:\\Games\\Sakura\\sakura.exe", 1, True, True)
    assert procs.bits(4242) == 32 and procs.bits(5000) in (32, 64)


def test_the_clipboard(world):
    world.procs = {1000: ("C:\\Python\\python.exe", 1, False, True), 4242: ("C:\\Games\\game.exe", 1, True, True)}
    world.windows = [[11, 1000, "Sluka", 1, 0, 0, 0], [12, 4242, "Game", 1, 0, 0, 0]]
    got = []
    board = clipwatch.Clipboard(lambda text, mine: got.append((text, mine)), own_pid=1000)
    assert board.start() and board.watching and board.hwnd
    world.foreground = 12
    world.copy("ゲームの一行", owner=999)
    wait_for(lambda: got)
    assert got == [("ゲームの一行", False)]
    # Copied in one of Sluka's own windows: said to be so.
    world.foreground = 11
    world.copy("Sluka's own line", owner=998)
    wait_for(lambda: len(got) == 2)
    assert got[1] == ("Sluka's own line", True)
    # Put there by the app: on the clipboard, kept out of Windows' clipboard history, and not read back.
    board.put("ゲームの二行目")
    wait_for(lambda: world.clipboard.get(13) == ("ゲームの二行目\0").encode("utf-16-le"))
    history = world.formats["CanIncludeInClipboardHistory"]
    assert world.clipboard[history] == b"\0\0\0\0" and world.clipboard_owner == board.hwnd
    world.PostMessageW(board.hwnd, 0x031D, 0, 0)
    time.sleep(0.2)
    assert len(got) == 2
    # The same copy said twice by Windows is passed on once.
    world.foreground = 12
    world.copy("twice", owner=999)
    world.PostMessageW(board.hwnd, 0x031D, 0, 0)
    wait_for(lambda: len(got) >= 3)
    time.sleep(0.2)
    assert [t for t, _ in got].count("twice") == 1
    board.stop()
    assert not board.watching and board.hwnd is None
    # A second watch gets a window class of its own.
    again = clipwatch.Clipboard(lambda text, mine: None, own_pid=1000)
    assert again.start()
    again.stop()
    assert len(world.classes) == 2
