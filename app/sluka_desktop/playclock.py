# SPDX-License-Identifier: LicenseRef-Sluka
# Copyright (c) 2026 Sluka. Part of Sluka Desktop; see LICENSE.txt.
"""How long a game is played: half of it is listening on Sluka's Home page (web/progress.js PLAYED_SHARE).

A game is being played while

  * the game text menu's Game or Screen tab, or Sluka Vision, is reading it -- the Game tab hooked into it, the Screen
    tab reading its box, Sluka Vision's words laid over its window;
  * its window is the one in front (the floating subtitles and Sluka Vision's words never take the front from it:
    the game is still in front while they are clicked); and
  * you did something in the last five minutes: a key, the mouse, a game controller -- or the game gave new text.

Each minute, the time played is told to Sluka's engine (web/mpv-engine.js) as a message of the player its text goes to:
the floating subtitles' for the Game and Screen tabs, Sluka Vision's for its own.  The engine counts it only while the
game's text is in a language you learn, and half of it, since a game's sound is part voices and part music.  Where the
text is shown nowhere (the floating subtitles off), the game is not counted: Sluka is not reading it with you.

The Clipboard tab is no game: what is copied may come from any program, so it is counted as reading alone.

On Windows only: elsewhere no window is known to be in front, and nothing is counted.
"""

from __future__ import annotations

import ctypes
import logging
import sys
import time

log = logging.getLogger("sluka.play")

WINDOWS = sys.platform == "win32"
#: How often it is looked whether the game is being played.
CHECK_SECONDS = 2.0
#: How often a controller is looked at: often enough to see a button pressed and let go.
PAD_SECONDS = 0.5
#: How often the time played is told to the engine.
REPORT_SECONDS = 60.0
#: Nothing done for this long -- no key, mouse, controller, nor new text from the game -- is not playing.
IDLE_SECONDS = 300.0
#: A gap between two looks longer than this is the computer asleep, or the app held up: not played.
GAP_SECONDS = CHECK_SECONDS * 3
#: The modes that read a game (gametext.MODES).
GAME_MODES = ("game", "screen", "vision")


class _LastInput(ctypes.Structure):
    _fields_ = [("cbSize", ctypes.c_uint), ("dwTime", ctypes.c_uint32)]


_input_calls = None


def _input_functions():
    global _input_calls
    if _input_calls is None:
        try:
            user32 = ctypes.WinDLL("user32")
            kernel32 = ctypes.WinDLL("kernel32")
            last = user32.GetLastInputInfo
            last.restype = ctypes.c_int
            last.argtypes = [ctypes.POINTER(_LastInput)]
            tick = kernel32.GetTickCount
            tick.restype = ctypes.c_uint32
            tick.argtypes = []
            _input_calls = (last, tick)
        except (OSError, AttributeError):
            _input_calls = False
    return _input_calls


def input_idle_seconds() -> float | None:
    """Seconds since the last key or mouse movement anywhere (GetLastInputInfo); None where that cannot be told."""
    if not WINDOWS:
        return None
    calls = _input_functions()
    if not calls:
        return None
    last, tick = calls
    info = _LastInput()
    info.cbSize = ctypes.sizeof(_LastInput)
    if not last(ctypes.byref(info)):
        return None
    return ((tick() - info.dwTime) & 0xFFFFFFFF) / 1000.0


class _Gamepad(ctypes.Structure):
    _fields_ = [("wButtons", ctypes.c_uint16), ("bLeftTrigger", ctypes.c_ubyte), ("bRightTrigger", ctypes.c_ubyte),
                ("sThumbLX", ctypes.c_int16), ("sThumbLY", ctypes.c_int16), ("sThumbRX", ctypes.c_int16),
                ("sThumbRY", ctypes.c_int16)]


class _PadState(ctypes.Structure):
    _fields_ = [("dwPacketNumber", ctypes.c_uint32), ("Gamepad", _Gamepad)]


#: A stick pushed further than this is being used (XInput's own XINPUT_GAMEPAD_LEFT_THUMB_DEADZONE); a trigger, this.
STICK_PUSHED = 7849
TRIGGER_MOVED = 30
#: How often every controller place is looked at for one plugged in since (a place with none is slow to ask).
PADS_SCAN_SECONDS = 10.0


class Pads:
    """Game controllers (XInput): whether one was used since the last look.  A button pressed or let go, a trigger
    moved, a stick pushed past its dead zone is use; a stick at rest, however it trembles, is not."""

    def __init__(self, get_state=None, now=time.monotonic):
        self._get = get_state
        self._now = now
        self._last: dict[int, tuple] = {}
        self._places: list[int] = []
        self._next_scan = 0.0
        self.failed = False
        if self._get is None and WINDOWS:
            try:
                self._get = self._load()
            except Exception:
                log.exception("game controllers cannot be looked at")
                self._get = None

    def _load(self):
        for name in ("xinput1_4", "xinput1_3", "xinput9_1_0"):
            try:
                dll = ctypes.WinDLL(name)
                f = dll.XInputGetState
            except (OSError, AttributeError):
                continue
            f.restype = ctypes.c_uint32
            f.argtypes = [ctypes.c_uint32, ctypes.POINTER(_PadState)]

            def get(index, f=f):
                state = _PadState()
                if f(index, ctypes.byref(state)) != 0:
                    return None
                p = state.Gamepad
                return (int(p.wButtons), int(p.bLeftTrigger), int(p.bRightTrigger),
                        int(p.sThumbLX), int(p.sThumbLY), int(p.sThumbRX), int(p.sThumbRY))

            return get
        return None

    def used(self) -> bool:
        """Whether a controller was used since this was last asked."""
        if self._get is None or self.failed:
            return False
        now = self._now()
        if now >= self._next_scan:
            self._next_scan = now + PADS_SCAN_SECONDS
            places = range(4)
        else:
            places = self._places
        seen = []
        used = False
        try:
            for index in places:
                state = self._get(index)
                if state is None:
                    self._last.pop(index, None)
                    continue
                seen.append(index)
                before = self._last.get(index)
                self._last[index] = state
                if before is None:
                    continue
                buttons, left, right, *sticks = state
                if (buttons != before[0] or abs(left - before[1]) > TRIGGER_MOVED or abs(right - before[2]) > TRIGGER_MOVED
                        or any(abs(v) > STICK_PUSHED for v in sticks)):
                    used = True
        except Exception:
            self.failed = True
            log.exception("game controllers could not be looked at")
            return False
        if places is not self._places:
            self._places = seen
        return used


class PlayClock:
    """The time a game is played (see the top of this file), told to Sluka's engine a minute at a time."""

    def __init__(self, games, idle=input_idle_seconds, pads=None, wall=time.time):
        self.g = games
        self._idle = idle
        self._pads = pads if pads is not None else Pads()
        self._wall = wall
        self._last_check = 0.0
        self._next_check = 0.0
        self._next_pad = 0.0
        self._pad_used_at = -1e9
        self._last_report = None
        self._mode = ""
        self._played = 0.0

    # ------------------------------------------------------------------ is it being played

    def _front(self, mode: str) -> bool:
        g = self.g
        if mode == "vision":
            return bool(g.vision.showing() and g.vision.front and g.vision.game_front)
        try:
            in_front = int(g.procs.foreground_pid() or 0)
        except Exception:
            return False
        if not in_front:
            return False
        if mode == "game":
            with g._lock:
                game = g.game
                return (game is not None and game.get("state") == "attached" and bool(game.get("connected"))
                        and in_front in game["pids"])
        target = g.screen.target
        if target is None or target.get("state") not in ("starting", "watching"):
            return False
        pid = int(target.get("pid") or 0)
        # A box read where it is on the screen, in no window: whatever is in front, if it is not Sluka itself.
        return in_front == pid if pid else in_front != g.procs.own_pid

    def _active(self, now: float) -> bool:
        if now - self._pad_used_at <= IDLE_SECONDS:
            return True
        texts = [float(self.g.last_line.get("at") or 0)]
        if self._mode == "vision":
            texts.append(float(self.g.vision.last.get("at") or 0))
        if self._wall() - max(texts) <= IDLE_SECONDS:
            return True
        try:
            idle = self._idle() if self._idle else None
        except Exception:
            idle = None
        return idle is not None and idle <= IDLE_SECONDS

    def playing(self, now: float) -> bool:
        mode = self.g.settings.get("mode")
        return mode in GAME_MODES and self._front(mode) and self._active(now)

    # ------------------------------------------------------------------ the clock

    def tick(self, now: float) -> None:
        """From the game text's own ticker (gametext.py _tick), many times a second; looks every CHECK_SECONDS."""
        if now >= self._next_pad:
            self._next_pad = now + PAD_SECONDS
            if self.g.settings.get("mode") in GAME_MODES and self._pads.used():
                self._pad_used_at = now
        if now < self._next_check:
            return
        self._next_check = now + CHECK_SECONDS
        if self._last_report is None:
            self._last_report = now
        gap = now - self._last_check if self._last_check else 0.0
        self._last_check = now
        mode = str(self.g.settings.get("mode") or "")
        if mode != self._mode:
            # Another tab: what the last one played is its own.
            self.report(now)
            self._mode = mode
        if 0 < gap <= GAP_SECONDS and self.playing(now):
            self._played += gap
        if now - self._last_report >= REPORT_SECONDS:
            self.report(now)

    def report(self, now: float) -> bool:
        """The time played since the last report, to the engine; true where it was told."""
        self._last_report = now
        played, self._played = self._played, 0.0
        if played < 1.0 or self._mode not in GAME_MODES:
            return False
        message = {"t": "played", "ms": int(round(played * 1000))}
        try:
            if self._mode == "vision":
                return bool(self.g.vision.tell_engine(message))
            bar = getattr(self.g.host, "bar", None)
            return bool(bar is not None and bar.tell_engine(message))
        except Exception:
            log.exception("the time played could not be told to Sluka's engine")
            return False
