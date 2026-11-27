# SPDX-License-Identifier: LicenseRef-Sluka
# Copyright (c) 2026 Sluka. Part of Sluka Desktop; see LICENSE.txt.
"""Sluka Vision: the words of a game's whole window, read off the screen and laid over it where they sit, as
YomiNinja lays them -- each word underlined in the colour of its level, its card when it is pointed at, its panel
(and its grades) when it is clicked.

The game text menu's Sluka Vision tab (web/dock.js).  The window read is the one in front when Sluka Vision's key is
pressed -- the game, pressed in the game -- or the one clicked after "Choose the window"; Sluka's screen reader
(ocrd.py's VisionWatch, a program of its own) reads it whole, with Google Lens unless another reader is chosen, when
the key is pressed and, where "Read by itself" is on, each time what the window shows has changed and settled.  A
word whose text has gone from under it -- the next line, the camera turned -- is put away at once.

What was read is drawn by a page of its own (web/vision.html) in a see-through window laid over the game's
(winshell.py, kind "vision"): kept out of pictures of the screen while the screen is what is read (in them --
screenshots, recordings -- while the game's own window is), over every other window but taking the
keyboard from none, and taking the pointer only where there is a word, a card or a panel.  To Sluka's engine
(mpv-engine.js) the page is one more player, called "vision", as the floating subtitles are "bar": its words are cut,
looked up and graded by Sluka's own code, as in your books and films.

The keys of the tab work in every program, the game too (hotkeys.py), while the tab is chosen.  Two of them stop the
game where it is, to read it at leisure, each its own way -- for each game the one that suits it:

*   "Pause the game": the game itself paused (its every thread held, as Resource Monitor's "Suspend process" holds a
    program's: its picture, its sound, its cutscene, its timers stop), and its picture, taken the moment before, laid
    over its window meanwhile -- Windows fades a window whose program does not answer, and would offer to close it on a
    click.  Pressed again, the game goes on where it was.  Not every game can be: one run as administrator, or guarded
    by an anti-cheat, is not Sluka's to pause (online games are best left alone).
*   "Freeze the picture": only the picture kept over the game, which goes on behind it -- for a game that should not
    be paused.

Either way the words are those of the picture kept (read off it where they are not those shown already), and its
words' cards have that picture; the window itself is not looked at meanwhile.  And while a word's
panel is open over the game, Sluka's own grading keys -- 1 to 4, K, X, 0 back to New, as Sluka is set, and Esc to
close it -- are the panel's: the overlay never has the keyboard, so they are held for it while the game is in front,
and are the game's again the moment the panel closes.
"""

from __future__ import annotations

import collections
import json
import logging
import math
import os
import threading
import time
from pathlib import Path

from . import hotkeys, ocrtext, texthook
from .host import Request, Response, error_response, json_response

log = logging.getLogger("sluka.games")

#: The readers Sluka Vision may read with (ocrd.py's); Google Lens first, the best at a game's whole window.
READERS = ("lens", "builtin", "windows")
CAPTURES = ("screen", "window")
#: What can be done with a key, and what the menu calls it.
ACTIONS = {"read": "Read the window", "auto": "Read by itself: on or off", "clear": "Put the words away",
           "pause": "Pause the game: on or off", "freeze": "Freeze the picture: on or off"}
#: The two ways of stopping the game where it is (each with its key): the game paused, or its picture only.
FREEZE_MODES = {"pause": "pause", "freeze": "picture"}
#: How long the picture kept stays over the game once let go of, for the game to draw itself again (a window Windows
#: faded while its program was paused comes back as it was).
UNFREEZE_LAG = 0.15
#: The game paused, written down while it is: an app that ends without letting it go lets it go at its next start.
PAUSED_FILE = "vision-paused.json"
#: The picture kept, as the screen reader writes it for each request (read at once, and taken away).
STILL_FILE = "vision-still-{}.bmp"
#: How long a picture asked of the screen reader may take before it is asked for again.
FREEZE_WAIT = 5.0
KEY_SETTINGS = {action: f"vision_key_{action}" for action in ACTIONS}
#: The overlay's window (winshell.py), kept out of pictures of the screen with the app's other windows.
VISION_CLASS = "SlukaDesktopVision"
#: How long "Choose the window" waits for a window to be clicked.
PICK_SECONDS = 10.0
#: How long the menu may wait for a key to be pressed (the keys are let go of meanwhile).
LISTEN_SECONDS = 30.0
RESTARTS_MOST = 3
#: The overlay's page: how long it may hold a request open, what is kept for it meanwhile, the most it may send.
POLL_SECONDS = 25
QUEUE_MOST = 200
BODY_MOST = 512 * 1024
#: The most parts of its window the page may say it draws on.
RECTS_MOST = 600
#: The levels Sluka's grading keys give, as the engine names them (mpv-engine.js gradeKeys): 0 is back to New.
PANEL_LEVELS = (0, 1, 2, 3, 4, 5, 6)


class VisionPlayer:
    """The overlay, as the engine that answers mpv's script sees it: one more player, named "vision"."""

    key = "vision"

    def __init__(self, vision: "VisionText"):
        self.vision = vision
        self.alive = True
        self.said_hello = False
        self.pid = 0
        self.path = "vision"

    def send(self, message: dict) -> bool:
        return self.vision.to_page({"t": "engine", "msg": message})

    def close(self) -> None:
        self.alive = False


class VisionText:
    """The Sluka Vision tab's side in the app: which window, read by which reader, what was read, and the overlay's
    window and page."""

    def __init__(self, games, process_factory=None):
        self.g = games
        self.config = games.config
        self.procs = games.procs
        self._lock = games._lock  # (one lock with the game text's: the menu's state is read under it)
        self.runner = None
        self.error = ""
        self.engines: dict = {}
        self._active = False
        #: The window read: {"hwnd", "pid", "title", "class", "exe", "client"}.
        self.target: dict | None = None
        #: The last read, as the page was given it; None once its words are put away.
        self.layout: dict | None = None
        self.area: list | None = None
        self.front = True
        self.state_now = {"state": "", "text": ""}
        self.picking = 0.0
        self.last = {"at": 0.0, "ms": 0, "lines": 0, "engine": "", "why": "", "text": ""}
        self._restarts: collections.deque = collections.deque(maxlen=8)
        self._excluded: list[int] = []
        self.excluded_ok: bool | None = None
        self._next_exclude = 0.0
        self._exclude_lock = threading.Lock()
        #: How the window is read, as the screen reader last said ("screen", "window"; "" not yet): Sluka's windows --
        #: the overlay too -- are left out of pictures of the screen only while the screen is what is read.
        self.capture_how = ""
        self._noted_screen = 0
        #: The games told (once a run) that the screen has to be read for them: their own window's picture is frozen.
        self._told_frozen: set[str] = set()
        self._factory = process_factory or ocrtext.OcrProcess
        #: The keys, held while the tab is chosen (and let go of while the menu waits for a new one).
        self.keys = hotkeys.Hotkeys(self._key_pressed)
        self.listening = 0.0
        #: Sluka's grading keys, held for the overlay's open panel (_hold_panel_keys): what its page asked for, and
        #: whether the game itself (not only one of Sluka's windows) is in front.
        self.panel_keys = hotkeys.Hotkeys(self._panel_key_pressed)
        self._panel_wanted: dict | None = None
        self._panel_bindings: dict = {}
        self._panel_lock = threading.Lock()
        self.game_front = True
        #: The lines of the word pointed at, or of the one whose panel is open (the read's number, and theirs): what
        #: changes under them alone does not have the window read again by itself meanwhile.
        self._holding: tuple | None = None
        # The overlay: its window (the shell's: set by the app), its page, and Sluka's engine through the app.
        self.shell = None
        self.player: VisionPlayer | None = None
        self._queue: collections.deque = collections.deque(maxlen=QUEUE_MOST)
        self._waiting: list = []
        self._last_poll = 0.0
        self._shown = False
        #: Stopped where it is (its keys): {"mode": "pause" | "picture", "n", "size"}, the picture kept (a BMP), the
        #: game paused (winproc.Paused), and the way asked for while the picture is still to come.
        self.frozen: dict | None = None
        self._still: bytes | None = None
        self._paused = None
        self._freeze_asked = ""
        self._freeze_asked_at = 0.0
        self._freeze_n = 0
        #: Each picture asked for is numbered, and the screen reader's word about one says its number: a word about a
        #: picture since let go of is not taken for one about the picture asked for now.
        self._freeze_ask_n = 0
        #: One change of these at a time (its keys, the screen reader's word, letting go): a game is never paused twice.
        self._freeze_lock = threading.RLock()
        self._resume_left()
        for left in Path(self.config.data_dir).glob("vision-still*.bmp") if getattr(self.config, "data_dir", None) else ():
            try:
                left.unlink()
            except OSError:
                pass

    # ------------------------------------------------------------------ chosen, or not

    def activate(self) -> None:
        with self._lock:
            if self._active:
                return
            self._active = True
            self._next_exclude = 0.0
        self._apply_keys()
        runner = self._runner()
        if runner is not None:
            runner.engines(self.g.settings["ocr_lang"])
            self._start(runner)
        self.g._changed()

    def deactivate(self) -> None:
        self.unfreeze()
        with self._lock:
            was = self._active
            self._active = False
            self.picking = 0.0
            self.listening = 0.0
            self.layout = None
            self._panel_wanted = None
        self.keys.clear()
        self._hold_panel_keys()
        self._stop_runner()
        self._exclude(False)
        if was:
            self.to_page({"t": "clear"})
            self._close_overlay()
            self.page_gone()
        self.g._changed()

    def close(self) -> None:
        self.deactivate()
        self.keys.close()
        self.panel_keys.close()
        self._answer_all()

    # ------------------------------------------------------------------ the screen reader's program

    def _fail(self, text: str) -> None:
        with self._lock:
            self.error = text
        self.g.note(text, "error")

    def _runner(self):
        """Sluka's screen reader, running for Sluka Vision (started if it is not)."""
        with self._lock:
            runner = self.runner
            if runner is not None and runner.alive:
                return runner
        folder = texthook.engine_dir(self.config)
        if not folder.is_dir():
            self._fail(f"Sluka's engine folder is missing ({folder}): unpack Sluka Desktop's zip again, the engine folder "
                       "is in it.")
            return None
        logs = Path(getattr(self.config, "log_dir", "") or Path(self.config.data_dir) / "logs") / "ocrd-vision.log"
        ocrtext.forget_snipping_tool(self.config.data_dir, folder)
        args = ["--network", str(getattr(self.config, "network_mode", "") or "direct"),
                "--socks", str(getattr(self.config, "socks", "") or "127.0.0.1:9050")]
        args += list(getattr(self._factory, "extra_args", []) or [])
        runner = self._factory(texthook.Engine(folder), self._event, procs=self.procs, log_path=logs, extra_args=args)
        try:
            runner.start()
        except Exception as err:
            text = f"Sluka's screen reader could not be started ({err})."
            if getattr(err, "winerror", 0) == 225 or "virus" in str(err).lower():
                text += " Windows Security stopped it: allow it in Protection history, or add the engine folder to its exclusions."
            self._fail(text)
            return None
        with self._lock:
            self.runner = runner
            self.error = ""
        return runner

    def _start(self, runner) -> None:
        s = self.g.settings
        with self._lock:
            hwnd = (self.target or {}).get("hwnd") or 0
            self._holding = None  # (a reader started anew counts its reads from the first again)
        runner.send({"cmd": "vision-start", "engine": self._reader(), "lang": s["ocr_lang"],
                     "furigana": bool(s["vision_furigana"]), "capture": s["vision_capture"], "auto": bool(s["vision_auto"]),
                     "allow": sorted(self.g.screen._mine()), "hwnd": hwnd})

    def _reader(self) -> str:
        """The reader to read with: the one chosen, Google Lens only once it has had its yes (lensask.py)."""
        lens = getattr(self.g, "lens", None)
        return lens.reader("vision_engine") if lens is not None else self.g.settings["vision_engine"]

    def _stop_runner(self) -> None:
        with self._lock:
            runner, self.runner = self.runner, None
        if runner is not None:
            try:
                runner.send({"cmd": "vision-stop"})
                runner.stop()
            except Exception:
                log.exception("Sluka's screen reader could not be stopped")

    def _send(self, command: dict) -> bool:
        """A command for the screen reader: started (and told what to watch) where it is not running."""
        with self._lock:
            active = self._active
            runner = self.runner
        if not active:
            return False
        if runner is None or not runner.alive:
            runner = self._runner()
            if runner is None:
                return False
            self._start(runner)
        return bool(runner.send(command))

    def _event(self, kind: str, event: dict) -> None:
        if kind == "ready":
            self.g.note(f"Sluka Vision's reader is running (Python {event.get('python')}).")
        elif kind == "fatal":
            self._fail(f"Sluka's screen reader could not start: {event.get('text') or 'it said nothing'}")
        elif kind == "engines":
            with self._lock:
                self.engines = {name: dict(info) for name, info in (event.get("engines") or {}).items() if isinstance(info, dict)}
            self.g._changed()
        elif kind == "vision-window":
            self._window(event.get("window") if isinstance(event.get("window"), dict) else None)
        elif kind == "vision-picked":
            with self._lock:
                self.picking = 0.0
            if not event.get("window"):
                self.g.note("No window was clicked: choose it again, or press Sluka Vision's key in the game.")
            self.g._changed()
        elif kind == "vision-layout":
            self._layout(event)
        elif kind == "vision-area":
            area = [int(v) for v in event.get("area") or []][:4]
            if len(area) == 4:
                with self._lock:
                    self.area = area
                    shown = self._shown
                if shown and self.shell is not None:
                    self.shell.vision_place(area)
                self.to_page({"t": "area", "area": area})
        elif kind == "vision-front":
            on = bool(event.get("on"))
            with self._lock:
                self.front = on
                self.game_front = on and bool(event.get("game", True))
                shown = self._shown
            self.to_page({"t": "front", "on": on})
            if shown and self.shell is not None:
                self.shell.vision_visible(on)
            self._hold_panel_keys()
        elif kind == "vision-back":
            lines = [int(i) for i in event.get("lines") or [] if isinstance(i, int)]
            if lines:
                self.to_page({"t": "back", "lines": lines})
        elif kind == "vision-capture":
            how = "window" if event.get("how") == "window" else "screen"
            frozen = how == "screen" and event.get("why") == "frozen"
            with self._lock:
                self.capture_how = how
                target = dict(self.target) if self.target else None
                asked_window = self.g.settings.get("vision_capture") == "window"
                note = how == "screen" and asked_window and target is not None and self._noted_screen != target.get("hwnd")
                if note:
                    self._noted_screen = target.get("hwnd")
                game = (target or {}).get("exe") or (target or {}).get("title") or "the game"
                tell = frozen and asked_window and game not in self._told_frozen
                if tell:
                    self._told_frozen.add(game)
            self._keep_out_overlay()
            self._exclude(True)
            if tell:
                # (once a game, a run of the app: the switch is needed for the words to be right)
                self.g.popup(ocrtext.FROZEN_TITLE, ocrtext.frozen_text((target or {}).get("title") or game, "Sluka Vision"))
            if note:
                why = "gives only a picture that no longer changes" if frozen else "cannot be read as it shows"
                self.g.note(f"{target.get('title') or 'The game'}'s own window {why}: Sluka Vision reads "
                            "what the screen shows there, and keeps its words out of screenshots and recordings meanwhile.", "warn")
            self.g._changed()
        elif kind == "vision-stale":
            if event.get("all"):
                with self._lock:
                    self.layout = None
                self.to_page({"t": "stale", "all": True})
            else:
                lines = [int(i) for i in event.get("lines") or [] if isinstance(i, int)]
                if lines:
                    self.to_page({"t": "stale", "lines": lines})
        elif kind == "vision-status":
            state = {"state": str(event.get("state") or ""), "text": str(event.get("text") or "")}
            with self._lock:
                changed = state != self.state_now
                self.state_now = state
                area, front, shown, active = self.area, self.front, self._shown, self._active
            if state["state"] == "reading" and not shown and area and active:
                # The first read of a window: its window laid over the game at once, to say so (and what went
                # wrong, if something does) where you are looking.
                self._open_overlay(area, front)
            if changed:
                self.to_page({"t": "status", **state})
                self.g._changed()
        elif kind == "vision-error":
            text = str(event.get("text") or "")
            with self._lock:
                self.error = text
            self.g.note(text, "error")
            self.to_page({"t": "note", "text": text, "seconds": 6})
        elif kind == "vision-frozen":
            self._frozen_event(event)
        elif kind == "vision-gone":
            self.unfreeze(told=True)
            title = (event.get("window") or {}).get("title") or "The window"
            self.g.note(f"{title} has closed: Sluka Vision reads the window in front at the next press of its key.")
            with self._lock:
                self.target = None
                self.layout = None
            self.to_page({"t": "clear"})
            self._close_overlay()
            self.g._changed()
        elif kind == "note":
            text = str(event.get("text") or "")
            self.g.note(text, "warn" if "Error" in text or "Traceback" in text else "engine")
        elif kind == "ended":
            self._ended(event.get("code"))

    def _ended(self, code) -> None:
        with self._lock:
            runner = self.runner
            if runner is not None and runner.alive:
                return  # one started since has taken its place
            self.runner = None
            active = self._active
        # (a reader started again knows no picture kept: the game goes on, and is read as it is)
        self.unfreeze(told=True)
        if self.g._stop.is_set() or not active:
            return
        self.g.note(f"Sluka Vision's reader stopped (code {code}).", "warn")
        now = time.monotonic()
        self._restarts.append(now)
        if len([t for t in self._restarts if now - t < 60]) > RESTARTS_MOST:
            self._fail("Sluka Vision's reader keeps stopping; it is not started again. Its notes are in "
                       "data\\logs\\ocrd-vision.log: another reader may do (Read with, in the Sluka Vision tab).")
            self.g._changed()
            return

        def again() -> None:
            if self._active and self.runner is None:
                runner = self._runner()
                if runner is not None:
                    self._start(runner)

        self.g._later(1.0, again)

    # ------------------------------------------------------------------ what was read

    def _window(self, window: dict | None) -> None:
        if window is None:
            with self._lock:
                self.target = None
            self.g._changed()
            return
        pid = int(window.get("pid") or 0)
        try:
            path = self.procs.exe(pid) if pid else ""
        except Exception:
            path = ""
        exe = os.path.basename(path.replace("\\", "/")) if path else ""
        title = str(window.get("title") or exe or "the game")
        target = {"hwnd": int(window.get("hwnd") or 0), "pid": pid, "title": title, "class": str(window.get("class") or ""),
                  "exe": exe, "client": [int(v) for v in (window.get("client") or [0, 0, 0, 0])][:4]}
        with self._lock:
            same = self.target is not None and self.target.get("hwnd") == target["hwnd"]
            self.target = target
            self.layout = None
            if not same:
                self.capture_how = ""  # (said again at its first picture)
        if not same:
            self.unfreeze(told=True)
            self.g.note(f"Sluka Vision reads {title}{f' ({exe})' if exe and exe != title else ''}.")
            self.to_page({"t": "clear"})
        self.g._changed()

    def _layout(self, event: dict) -> None:
        try:
            area = [int(v) for v in event.get("area") or []][:4]
            size = [int(v) for v in event.get("size") or []][:2]
        except (TypeError, ValueError):
            return
        if len(area) != 4 or len(size) != 2 or area[2] <= 0 or area[3] <= 0:
            return
        lines = [line for line in event.get("lines") or [] if isinstance(line, dict) and isinstance(line.get("text"), str)]
        layout = {"t": "layout", "id": int(event.get("id") or 0), "area": area, "size": size, "lines": lines,
                  "engine": str(event.get("engine") or ""), "why": str(event.get("why") or "")}
        text = " / ".join(line["text"] for line in lines)
        with self._lock:
            if not self._active:
                return
            self.layout = layout
            self.area = area
            self.error = ""
            self.last = {"at": round(time.time(), 3), "ms": int(event.get("ms") or 0), "lines": len(lines),
                         "engine": layout["engine"], "why": layout["why"], "text": text[:500]}
            front = self.front
        if not lines and layout["why"] != "auto":
            self.to_page({"t": "note", "text": "Sluka Vision found no text in the window.", "seconds": 3})
        self._open_overlay(area, front)
        self.to_page(layout)
        if lines:
            self._keep_for_cards(layout, int(event.get("ms") or 0))
        self.g._changed()

    def _keep_for_cards(self, layout: dict, ms: int) -> None:
        """A read's text, with when it came -- before the read, by its reading and its settling (ankicards.py) -- and
        the window it is the game's of, for the cards of words picked on it."""
        cards = getattr(self.g, "cards", None)
        if cards is None:
            return
        with self._lock:
            target = dict(self.target) if self.target else None
        game = None
        if target:
            game = {"pid": int(target.get("pid") or 0), "hwnd": int(target.get("hwnd") or 0),
                    "title": str(target.get("title") or ""), "exe": str(target.get("exe") or "")}
        from . import ankicards

        try:
            at = cards.clock() - max(0, ms) / 1000 - ankicards.VISION_LEAD
            cards.line("vision", ankicards.join_lines(layout["lines"]), game, at=at, read=layout["id"])
        except Exception:
            log.exception("a read could not be kept for its cards")

    # ------------------------------------------------------------------ what the menu and the keys do

    def read_now(self, front: bool = False) -> dict:
        """Read the window: the one in front (``front``: its key, pressed in the game), else the one chosen."""
        with self._lock:
            active = self._active
            target = self.target
        if not active:
            return {"ok": False, "error": "The Sluka Vision tab is not chosen."}
        if not front and target is None:
            return {"ok": False, "error": "No window is chosen yet: press Sluka Vision's key in the game, or choose its window."}
        with self._lock:
            if self.frozen is not None or self._freeze_asked:
                front = False  # (the picture kept is what is read)
        if not self._send({"cmd": "vision-read", "front": front, "exclude": sorted(self.g.screen._mine())}):
            return {"ok": False, "error": self.error or "Sluka's screen reader could not be started."}
        return {"ok": True}

    def pick(self) -> dict:
        """"Choose the window": the next window put in front (clicked) is the one read, at once."""
        self.unfreeze()
        with self._lock:
            if self.picking:
                self.picking = 0.0
                cancel = True
            else:
                cancel = False
        if cancel:
            self._send({"cmd": "vision-cancel-pick"})
            self.g._changed()
            return {"ok": True, "picking": False}
        if not self._send({"cmd": "vision-pick", "seconds": PICK_SECONDS, "exclude": sorted(self.g.screen._mine())}):
            return {"ok": False, "error": self.error or "Sluka's screen reader could not be started."}
        with self._lock:
            self.picking = time.monotonic() + PICK_SECONDS
        self.g._changed()
        return {"ok": True, "picking": True}

    def clear(self) -> dict:
        """The words put away (the window stays chosen; read by itself, it is read again as it changes)."""
        with self._lock:
            self.layout = None
        self.to_page({"t": "clear"})
        self._send({"cmd": "vision-clear"})
        self.g._changed()
        return {"ok": True}

    def forget(self) -> dict:
        self.unfreeze()
        with self._lock:
            self.layout = None
            self.target = None
        self.to_page({"t": "clear"})
        self._send({"cmd": "vision-forget"})
        self._close_overlay()
        self.g._changed()
        return {"ok": True}

    def set_auto(self, on: bool) -> dict:
        self.g.update({"vision_auto": bool(on)})
        self.g.note("Sluka Vision reads the window by itself as it changes." if on else
                    "Sluka Vision reads the window when its key is pressed.")
        return {"ok": True, "auto": bool(on)}

    def settings_changed(self, before: dict, after: dict) -> None:
        if not self._active:
            return
        if any(before.get(k) != after.get(k) for k in KEY_SETTINGS.values()):
            self._apply_keys()
        changed = {}
        for key, name in (("vision_engine", "engine"), ("ocr_lang", "lang"), ("vision_furigana", "furigana"),
                          ("vision_capture", "capture")):
            if before.get(key) != after.get(key):
                changed[name] = after[key]
        if "engine" in changed or (before.get("lens_ok") != after.get("lens_ok") and after.get("vision_engine") == "lens"):
            changed["engine"] = self._reader()  # (Google Lens only once it has had its yes)
        if changed:
            self._send({"cmd": "vision-settings", **changed})
        if before.get("vision_auto") != after.get("vision_auto"):
            self._send({"cmd": "vision-auto", "on": bool(after["vision_auto"])})
            self.to_page({"t": "auto", "on": bool(after["vision_auto"])})
        if before.get("vision_capture") != after.get("vision_capture"):
            with self._lock:
                self.capture_how = ""  # (said again at the next picture)
                self._noted_screen = 0
            self._keep_out_overlay()
            self._exclude(True)

    # ------------------------------------------------------------------ the keys

    def _apply_keys(self) -> None:
        with self._lock:
            wanted = self._active and not self.listening
            bindings = {action: str(self.g.settings.get(name) or "") for action, name in KEY_SETTINGS.items()}
        if not wanted:
            self.keys.clear()
            return
        errors = self.keys.set(bindings)
        for action, why in errors.items():
            log.info("the key %s (%s) is not held: %s", bindings.get(action), action, why)

    def listen(self, on: bool) -> dict:
        with self._lock:
            self.listening = time.monotonic() if on else 0.0
        self._apply_keys()
        return {"ok": True}

    def set_key(self, action: str, vk=None, mods=(), clear: bool = False) -> dict:
        """A key for an action, from what was pressed in the menu (Windows' number for the key, and the modifiers);
        or none.  A key another program has is not kept: the one before stays."""
        name = KEY_SETTINGS.get(action)
        if name is None:
            return {"ok": False, "error": "no such action"}
        if clear:
            text = ""
        else:
            try:
                value = sum(dict((label.lower(), bit) for label, bit in hotkeys.MODIFIERS).get(str(m).lower(), 0) for m in set(mods))
                vk = int(vk)
                hotkeys.check(value, vk)
                text = hotkeys.spec(value, vk)
            except (hotkeys.KeyError_, TypeError, ValueError) as err:
                return {"ok": False, "error": str(err) or "that key cannot be one"}
            for other, other_name in KEY_SETTINGS.items():
                if other != action and self.g.settings.get(other_name) == text:
                    return {"ok": False, "error": f"{text} is the key of “{ACTIONS[other]}” already"}
        before = str(self.g.settings.get(name) or "")
        with self._lock:
            self.listening = 0.0
        self.g.update({name: text})
        error = self.keys.errors.get(action, "") if text and self._active else ""
        if error:
            self.g.update({name: before})
            self.g.note(f"{text} cannot be the key of “{ACTIONS[action]}”: {error}.", "warn")
            return {"ok": False, "error": f"{text}: {error}. Choose another key."}
        if text:
            note = hotkeys.altgr_note(text)
            self.g.note(f"{text}: {ACTIONS[action]}." + (f" {note}." if note else ""))
        return {"ok": True, "key": text}

    def _panel_key_pressed(self, action: str) -> None:
        with self._lock:
            wanted = self._active and self._panel_wanted is not None
        if not wanted:
            return
        if action == "close":
            self.to_page({"t": "key", "close": True})
        elif action == "anki":
            self.to_page({"t": "key", "anki": True})
        elif action == "say":
            self.to_page({"t": "key", "say": True})
        elif action == "ask":
            self.to_page({"t": "key", "ask": True})
        elif action.startswith("level-"):
            self.to_page({"t": "key", "st": int(action[6:])})

    def _looking(self, args: dict) -> dict:
        """What is being done with the overlay's words: a panel open (``panel``, with Sluka's grading keys as it is set:
        {"1": "1", "5": "k", "0": "0", ...}), and the lines of the read numbered ``read`` that the word pointed at, or
        the one whose panel is open, is on (``lines``)."""
        panel = bool(args.get("panel"))
        try:
            read = int(args.get("read") or 0)
        except (TypeError, ValueError):
            read = 0
        lines = sorted({i for i in args.get("lines") or [] if isinstance(i, int) and not isinstance(i, bool)})[:64]
        self._hold((read, tuple(lines)) if read and lines else None)
        wanted = None
        if panel:
            wanted = {}
            keys = args.get("keys") if isinstance(args.get("keys"), dict) else {}
            for level, key in keys.items():
                try:
                    level = int(level)
                except (TypeError, ValueError):
                    continue
                key = str(key or "")
                if level in PANEL_LEVELS and len(key) == 1 and key.isascii() and key.isalnum():
                    wanted[level] = key.upper()
            # The panel's Anki key (Settings → Keys, "Add to Anki"), where Settings → Anki has the panel's button on.
            anki = str(args.get("anki") or "")
            if len(anki) == 1 and anki.isascii() and anki.isalnum() and anki.upper() not in wanted.values():
                wanted["anki"] = anki.upper()
            # And the key that says the word (Settings → Keyboard, "Hear the word"), where there is a voice.
            say = str(args.get("say") or "")
            if len(say) == 1 and say.isascii() and say.isalnum() and say.upper() not in wanted.values():
                wanted["say"] = say.upper()
            # And the AI check's (Settings → Keyboard, "Ask AI"), where the check is on.
            ask = str(args.get("ask") or "")
            if len(ask) == 1 and ask.isascii() and ask.isalnum() and ask.upper() not in wanted.values():
                wanted["ask"] = ask.upper()
        with self._lock:
            self._panel_wanted = wanted
        self._hold_panel_keys()
        return {"ok": True, "held": sorted(self.panel_keys.held)}

    def _hold(self, hold: tuple | None) -> None:
        """The screen reader told of the lines being looked at (``(read, lines)``), or that none is: what changes under
        them alone does not have the window read again by itself (it is, once they are let go of, if it has changed)."""
        with self._lock:
            changed = hold != self._holding
            self._holding = hold
            runner = self.runner if self._active else None
        if changed and runner is not None and runner.alive:
            read, lines = hold or (0, ())
            runner.send({"cmd": "vision-hold", "read": read, "lines": list(lines)})

    def _hold_panel_keys(self) -> None:
        """Sluka's grading keys held for the overlay's open panel while the game is in front -- or given back."""
        with self._panel_lock:
            with self._lock:
                wanted = self._panel_wanted
                if not (self._active and self._shown and self.front and self.game_front and not self.listening):
                    wanted = None
            bindings = {}
            if wanted:
                bindings = {(level if level in ("anki", "say", "ask") else f"level-{level}"): key for level, key in wanted.items()}
                bindings["close"] = "Esc"
            if bindings == self._panel_bindings:
                return
            self._panel_bindings = bindings
            if not bindings:
                self.panel_keys.clear()
                log.debug("Sluka Vision: the grading keys are the game's again")
                return
            errors = self.panel_keys.set(bindings, alone=True)
            log.debug("Sluka Vision: the grading keys are the open panel's: %s", ", ".join(sorted(self.panel_keys.held.values())))
            for action, why in errors.items():
                log.info("Sluka Vision: the key %s is not the open panel's: %s", bindings.get(action), why)

    def _key_pressed(self, action: str) -> None:
        if not self._active:
            return
        log.info("Sluka Vision key: %s", action)
        if action == "read":
            answer = self.read_now(front=True)
            if not answer.get("ok"):
                self.g.note(answer.get("error") or "Nothing could be read.", "warn")
        elif action == "auto":
            self.set_auto(not bool(self.g.settings.get("vision_auto")))
        elif action == "clear":
            self.clear()
        elif action in FREEZE_MODES:
            answer = self.toggle_freeze(FREEZE_MODES[action])
            if not answer.get("ok"):
                self.g.note(answer.get("error") or "The game could not be stopped where it is.", "warn")

    # ------------------------------------------------------------------ the game stopped where it is

    def _key_of(self, mode: str) -> str:
        action = next((a for a, m in FREEZE_MODES.items() if m == mode), "")
        return str(self.g.settings.get(KEY_SETTINGS.get(action, ""), "") or "")

    def _game_name(self) -> str:
        with self._lock:
            target = dict(self.target) if self.target else {}
        return str(target.get("title") or target.get("exe") or "the game")

    def toggle_freeze(self, mode: str) -> dict:
        """Its keys (and the menu's buttons): the game paused, its picture kept over it ("pause"); or only its picture
        kept, the game going on behind it ("picture").  The same again: let go of.  The other while one is on: that
        one, the picture kept as it is."""
        if mode not in FREEZE_MODES.values():
            return {"ok": False, "error": "no such way"}
        with self._freeze_lock:
            return self._toggle_freeze(mode)

    def _toggle_freeze(self, mode: str) -> dict:
        with self._lock:
            if self._freeze_asked and time.monotonic() - self._freeze_asked_at > FREEZE_WAIT:
                self._freeze_asked = ""  # (never came: asked for again)
            active, target, frozen, asked = self._active, self.target, self.frozen, self._freeze_asked
            if active and asked and asked != mode:
                # (its picture is still on its way: the other key says it is to be kept the other way)
                self._freeze_asked = mode
                return {"ok": True, "frozen": mode}
        if not active:
            return {"ok": False, "error": "The Sluka Vision tab is not chosen."}
        if asked:
            # The same key again before its picture came: not wanted after all, as it is let go of once it has come.
            self.unfreeze()
            return {"ok": True, "frozen": ""}
        if frozen is not None:
            if frozen["mode"] == mode:
                self.unfreeze()
                return {"ok": True, "frozen": ""}
            if mode == "pause":
                if not self._pause_game():
                    return {"ok": True, "frozen": "picture"}
            else:
                self._resume_game()
                with self._lock:
                    if self.frozen is not None:
                        self.frozen["mode"] = "picture"
            self._tell_frozen()
            self.g._changed()
            return {"ok": True, "frozen": mode}
        if target is None:
            return {"ok": False, "error": "No window is chosen yet: press Sluka Vision's key in the game, or choose its window."}
        with self._lock:
            self._freeze_ask_n += 1
            n = self._freeze_ask_n
            self._freeze_asked = mode
            self._freeze_asked_at = time.monotonic()
        path = self._still_path(n)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
        except OSError:
            pass
        if not self._send({"cmd": "vision-freeze", "on": True, "path": str(path), "ask": n}):
            with self._lock:
                self._freeze_asked = ""
            return {"ok": False, "error": self.error or "Sluka's screen reader could not be started."}
        return {"ok": True, "frozen": mode}

    def _frozen_event(self, event: dict) -> None:
        """The screen reader's word: the picture kept (the game is paused now, where that was asked for), or let go of."""
        with self._freeze_lock:
            self._frozen_said(event)

    def _still_path(self, n: int) -> Path:
        return Path(self.config.data_dir) / STILL_FILE.format(int(n))

    def _frozen_said(self, event: dict) -> None:
        tag = event.get("ask")
        tagged = isinstance(tag, int) and not isinstance(tag, bool) and tag > 0
        if not event.get("on"):
            with self._lock:
                pending = bool(self._freeze_asked) and (not tagged or tag == self._freeze_ask_n)
                held = self.frozen is not None and (not tagged or tag == self.frozen.get("ask"))
                asked = self._freeze_asked if pending else ""
                if pending:
                    self._freeze_asked = ""
            if not pending and not held:
                return  # (about a picture, or a request for one, let go of since)
            if asked and event.get("error"):
                self.g.note(f"Sluka Vision could not keep the game's picture: {event.get('error')}", "warn")
                self.to_page({"t": "note", "text": str(event.get("error")), "seconds": 4})
            if held:
                self.unfreeze(told=True)
            return
        with self._lock:
            n = tag if tagged else self._freeze_ask_n
        path = self._still_path(n)  # (the one it was asked to write, whatever it says)
        try:
            data = path.read_bytes()
        except OSError:
            data = b""
        try:
            path.unlink()
        except OSError:
            pass
        try:
            size = [int(v) for v in event.get("size") or []][:2]
        except (TypeError, ValueError):
            size = []
        with self._lock:
            current = bool(self._freeze_asked) and (not tagged or tag == self._freeze_ask_n)
            mode = self._freeze_asked if current else ""
            if current:
                self._freeze_asked = ""
            newer = bool(self._freeze_asked)
            active = self._active
        if not mode or not active or not data.startswith(b"BM") or len(size) != 2:
            # (let go of before it came, or nothing to show: the screen reader looks at the window again -- unless a
            # picture asked for since is on its way, which it is taking now)
            if not newer:
                self._send_running({"cmd": "vision-freeze", "on": False})
            if mode and active:
                self.g.note("Sluka Vision could not keep the game's picture.", "warn")
            return
        with self._lock:
            self._freeze_n += 1
            self._still = data
            self.frozen = {"mode": "picture", "n": self._freeze_n, "size": size, "ask": n}
        if mode == "pause":
            self._pause_game()
        self._tell_frozen()
        self.g.note(f"{self._game_name()}: paused, its picture kept over it." if self.frozen and self.frozen["mode"] == "pause"
                    else f"{self._game_name()}: its picture frozen, the game going on behind it.")
        self.g._changed()

    def _tell_frozen(self) -> None:
        with self._lock:
            frozen = dict(self.frozen) if self.frozen else None
        if frozen is None:
            return
        self.to_page({"t": "freeze", "on": True, "mode": frozen["mode"], "n": frozen["n"], "size": frozen["size"],
                      "key": self._key_of(frozen["mode"])})

    def _pause_game(self) -> bool:
        """The game itself paused (the picture is kept over it already): False, and said why, where it cannot be."""
        with self._lock:
            target = dict(self.target) if self.target else {}
            already = self._paused is not None
        if already:
            return True
        pid = int(target.get("pid") or 0)
        pause = getattr(self.procs, "pause", None)
        own = int(getattr(self.procs, "own_pid", 0) or os.getpid())
        if not pid or pid == own or pause is None:
            why = "Windows here cannot pause a program" if pause is None else "no game"
        else:
            try:
                paused, why = pause(pid)
            except Exception as err:
                log.exception("the game could not be paused")
                paused, why = None, str(err)
            if paused is not None:
                with self._lock:
                    self._paused = paused
                    if self.frozen is not None:
                        self.frozen["mode"] = "pause"
                self._write_paused(paused)
                return True
        name = self._game_name()
        if why == "admin":
            text = (f"Windows does not let Sluka pause {name}: it runs as administrator, or an anti-cheat guards it. Its "
                    f"picture is frozen instead, the game going on behind it.")
        else:
            text = f"{name} could not be paused ({why}): its picture is frozen instead, the game going on behind it."
        self.g.note(text, "warn")
        self.to_page({"t": "note", "text": text, "seconds": 6})
        return False

    def _resume_game(self) -> None:
        with self._lock:
            paused, self._paused = self._paused, None
        if paused is None:
            return
        try:
            done = paused.resume()
        except Exception:
            log.exception("the game could not be let go")
            done = False
        if not done:
            self.g.note(f"{self._game_name()} may still be paused: Windows did not say it goes on.", "warn")
        try:
            (Path(self.config.data_dir) / PAUSED_FILE).unlink()
        except OSError:
            pass

    def unfreeze(self, told: bool = False) -> None:
        """The game going on, and its picture taken away a moment later (``told``: the screen reader has let go of it
        already)."""
        with self._freeze_lock:
            self._unfreeze(told)

    def _unfreeze(self, told: bool) -> None:
        with self._lock:
            frozen, self.frozen = self.frozen, None
            asked, self._freeze_asked = self._freeze_asked, ""
            self._still = None
        self._resume_game()
        if not told and (frozen is not None or asked):
            self._send_running({"cmd": "vision-freeze", "on": False})
        if frozen is not None:
            self.g._later(UNFREEZE_LAG, lambda: self.to_page({"t": "freeze", "on": False, "n": frozen["n"]}))
            self.g.note(f"{self._game_name()} goes on." if frozen["mode"] == "pause" else
                        f"{self._game_name()}: its picture is the game's own again.")
            self.g._changed()

    def _send_running(self, command: dict) -> None:
        """A command for the screen reader, where it runs (none is started for it)."""
        with self._lock:
            runner = self.runner
        if runner is not None and runner.alive:
            try:
                runner.send(command)
            except Exception:
                log.exception("the screen reader could not be told")

    def still(self) -> bytes | None:
        """The picture kept, while the game is stopped where it is (for the overlay, and a word's card)."""
        with self._lock:
            return self._still

    def _write_paused(self, paused) -> None:
        path = Path(self.config.data_dir) / PAUSED_FILE
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps({"pid": int(paused.pid), "started": int(getattr(paused, "started", 0) or 0)}),
                            encoding="utf-8")
        except OSError:
            log.warning("where the paused game is could not be written down")

    def _resume_left(self) -> None:
        """A game left paused by an app that ended without letting it go: let go of now (where it is the same program)."""
        path = Path(self.config.data_dir) / PAUSED_FILE
        try:
            left = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        try:
            path.unlink()
        except OSError:
            pass
        resume = getattr(self.procs, "resume_left", None)
        try:
            pid, started = int(left.get("pid") or 0), int(left.get("started") or 0)
        except (TypeError, ValueError, AttributeError):
            return
        if resume is not None and pid:
            try:
                if resume(pid, started):
                    log.info("a game Sluka Vision had paused (process %s) goes on again", pid)
            except Exception:
                log.exception("a game left paused could not be let go")

    # ------------------------------------------------------------------ Sluka's windows out of the pictures

    def _own_shown(self) -> list[dict]:
        """Sluka's own windows that show (the overlay's included)."""
        find = getattr(self.procs, "own_windows", None)
        if find is None:
            return []
        try:
            windows = list(find((ocrtext.MAIN_CLASS, ocrtext.BAR_CLASS, VISION_CLASS), visible=True))
        except Exception:
            log.exception("the app's windows could not be listed")
            return []
        return [w for w in windows if w.get("visible", True)]

    def reads_screen(self) -> bool:
        """Whether what the screen shows is read (rather than the game's own window): as the screen reader said, or,
        before it has, as the tab is set."""
        with self._lock:
            how = self.capture_how or str(self.g.settings.get("vision_capture") or "screen")
        return how != "window"

    def _keep_out_overlay(self) -> None:
        """The overlay left out of pictures of the screen while the screen is read -- or it would read its own words
        back --, and in them (screenshots, recordings) while the game's own window is."""
        shell = self.shell
        if shell is not None and hasattr(shell, "vision_keep_out"):
            shell.vision_keep_out(self.reads_screen())

    def _exclude(self, on: bool) -> None:
        """Sluka's own windows left out of the pictures of the screen while the window is read as the screen shows
        it (the overlay too: its window does that itself, _keep_out_overlay); or put back.  What is wanted is read
        here, under a lock of its own, so that the last call always has the last word.

        Only those that show: the app's never-shown window, its background worker's, is never touched -- told to
        stay out of pictures (or back in them), such a window came up as an empty white one that did nothing.
        """
        keep_out = getattr(self.procs, "keep_out_of_captures", None)
        if keep_out is None:
            return
        with self._exclude_lock:
            wanted = bool(on) and self._active and self.reads_screen()
            windows = [w for w in self._own_shown() if w.get("class") != VISION_CLASS]
            if not wanted:
                with self._lock:
                    had, self._excluded = self._excluded, []
                # (every one that shows, not only those this said were left out: none stays out of pictures by mistake)
                back = [w["hwnd"] for w in windows] if had or not on else []
                if back:
                    keep_out(back, False)
                return
            done = [w for w in windows if keep_out([w["hwnd"]], True)]
            with self._lock:
                self._excluded = [w["hwnd"] for w in done]
                self.excluded_ok = bool(done) and all(w in done for w in windows)

    def tick(self, now: float) -> None:
        if not self._active:
            return
        if self.listening and now - self.listening > LISTEN_SECONDS:
            self.listen(False)
        if self.picking and now > self.picking + 2.0:
            with self._lock:
                self.picking = 0.0
            self.g._changed()
        if now >= self._next_exclude:
            self._next_exclude = now + 2.0
            self._exclude(True)
        if (self._panel_bindings or self._holding) and not self.page_alive():
            # The page went without saying its panel closed: the keys are the game's again.
            with self._lock:
                self._panel_wanted = None
            self._hold_panel_keys()
            self._hold(None)
        self.expire()

    # ------------------------------------------------------------------ the overlay's window

    def _open_overlay(self, area: list, front: bool) -> None:
        shell = self.shell
        with self._lock:
            opened, self._shown = self._shown, True
        if shell is None:
            return
        self._keep_out_overlay()
        if not opened:
            shell.open_vision(area)
        else:
            shell.vision_place(area)
        shell.vision_visible(front)

    def _close_overlay(self) -> None:
        with self._lock:
            opened, self._shown = self._shown, False
            self._panel_wanted = None
        self._hold_panel_keys()
        if opened and self.shell is not None:
            self.shell.close_vision()

    def overlay_closed(self) -> None:
        """Its window went (the shell's side): the page is gone with it."""
        with self._lock:
            self._shown = False
        self.page_gone()

    # ------------------------------------------------------------------ the overlay's page, and the engine

    def to_page(self, message: dict) -> bool:
        with self._lock:
            self._queue.append(message)
            if not self._waiting:
                return True
            _deadline, respond = self._waiting.pop(0)
            items = list(self._queue)
            self._queue.clear()
        respond(json_response({"msgs": items}))
        return True

    def _engine(self):
        mpv = getattr(self.g.host, "mpv", None)
        return mpv if mpv is not None and hasattr(mpv, "add_player") else None

    def _player(self) -> VisionPlayer | None:
        engine = self._engine()
        if engine is None:
            return None
        with self._lock:
            if self.player is None or not self.player.alive:
                self.player = VisionPlayer(self)
                engine.add_player(self.player)
            return self.player

    def page_gone(self) -> None:
        with self._lock:
            player, self.player = self.player, None
            self._panel_wanted = None
        self._hold_panel_keys()
        self._hold(None)
        engine = self._engine()
        if player is not None and engine is not None:
            player.close()
            engine.player_gone(player)

    def showing(self) -> bool:
        """Whether a window is being read and the overlay is open over it (the play clock asks, playclock.py)."""
        with self._lock:
            return bool(self._active and self._shown and self.target is not None)

    def tell_engine(self, message: dict) -> bool:
        """A message to Sluka's engine as the overlay's own, from the app (the play clock): only while its page is there
        and has said hello to it."""
        with self._lock:
            player = self.player
        engine = self._engine()
        if player is None or not player.alive or not player.said_hello or engine is None:
            return False
        engine.incoming(player, message)
        return True

    def page_alive(self) -> bool:
        return time.time() - self._last_poll < POLL_SECONDS + 15

    def _answer_all(self) -> None:
        with self._lock:
            waiting, self._waiting = self._waiting, []
        for _deadline, respond in waiting:
            respond(json_response({"msgs": []}))

    def expire(self) -> None:
        now = time.monotonic()
        due = []
        with self._lock:
            keep = []
            for deadline, respond in self._waiting:
                (due if deadline <= now else keep).append((deadline, respond))
            self._waiting = keep
        for _deadline, respond in due:
            respond(json_response({"msgs": []}))

    def api(self, name: str, req: Request, respond) -> None:
        """The overlay page's calls (vision/...): only the app's own pages may make them."""
        site = str(req.headers.get("sec-fetch-site", "") or "").lower()
        if name == "still":
            # The picture kept, for the page to lay over the game (an image the page asks for by its address).
            if req.method not in ("GET", "POST") or (site and site not in ("same-origin", "none")):
                respond(error_response(403, "forbidden"))
                return
            data = self.still()
            if data is None:
                respond(error_response(404, "no picture is kept"))
                return
            respond(Response(content_type="image/bmp", body=data,
                             headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"}))
            return
        if req.method != "POST" or (site and site != "same-origin"):
            respond(error_response(403, "forbidden"))
            return
        body = req.body or b""
        if len(body) > BODY_MOST:
            respond(error_response(413, "too large"))
            return
        try:
            args = json.loads(body.decode("utf-8")) if body else {}
        except (ValueError, UnicodeDecodeError):
            respond(error_response(400, "not JSON"))
            return
        if not isinstance(args, dict):
            respond(error_response(400, "not an object"))
            return
        if name == "poll":
            self._poll(args, respond)
        elif name == "say":
            respond(self._say(args))
        elif name == "shape":
            respond(self._shape(args))
        elif name == "looking":
            respond(json_response(self._looking(args)))
        elif name == "status":
            respond(json_response(self.status()))
        else:
            respond(error_response(404, "no such Sluka Vision call"))

    def _poll(self, args: dict, respond) -> None:
        self._last_poll = time.time()
        if args.get("fresh"):
            # A page just (re)started: what it needs first -- whether there is an engine, the words read last, and
            # whether the game is in front.
            with self._lock:
                self._queue.clear()
                waiting, self._waiting = self._waiting, []
                layout = dict(self.layout) if self.layout else None
                front = self.front
                state = dict(self.state_now)
            for _deadline, old in waiting:
                old(json_response({"msgs": [], "superseded": True}))
            self.page_gone()
            first = [{"t": "state", "engine": self._engine() is not None, "auto": bool(self.g.settings.get("vision_auto")),
                      "front": front}, {"t": "status", **state}]
            if layout:
                first.append(layout)
            with self._lock:
                frozen = dict(self.frozen) if self.frozen else None
            if frozen is not None:
                first.append({"t": "freeze", "on": True, "mode": frozen["mode"], "n": frozen["n"], "size": frozen["size"],
                              "key": self._key_of(frozen["mode"])})
            respond(json_response({"msgs": first}))
            return
        with self._lock:
            if self._queue:
                items = list(self._queue)
                self._queue.clear()
            else:
                self._waiting.append((time.monotonic() + POLL_SECONDS, respond))
                return
        respond(json_response({"msgs": items}))

    def _say(self, args: dict):
        """What the overlay's page says to the engine (hello, line, lookup, grade), passed on as a player's."""
        message = args.get("msg")
        if not isinstance(message, dict) or not isinstance(message.get("t"), str):
            return error_response(400, "no message")
        player = self._player()
        engine = self._engine()
        if player is None or engine is None:
            return json_response({"ok": False, "engine": False})
        if message["t"] == "hello":
            player.said_hello = True
        engine.incoming(player, message)
        return json_response({"ok": True})

    @staticmethod
    def _rects(items) -> list:
        out = []
        for item in items if isinstance(items, list) else []:
            try:
                x, y, w, h = (float(v) for v in list(item)[:4])
            except (TypeError, ValueError):
                continue
            if all(math.isfinite(v) for v in (x, y, w, h)) and w > 0 and h > 0:
                out.append((x, y, w, h))
        return out[:RECTS_MOST]

    def _shape(self, args: dict):
        """The parts of the overlay's window its page draws on -- the words, the card, the panel: the rest is see-through
        and the pointer goes through it.  In the page's pixels, ``dpr`` of the screen's each."""
        try:
            dpr = float(args.get("dpr") or 1.0)
        except (TypeError, ValueError):
            dpr = 1.0
        if not math.isfinite(dpr) or not 0.25 <= dpr <= 8:
            dpr = 1.0
        shell = self.shell
        if shell is not None:
            shell.vision_shape(self._rects(args.get("rects")), dpr)
        return json_response({"ok": True})

    # ------------------------------------------------------------------ what the menu sees

    def state(self) -> dict:
        with self._lock:
            target = dict(self.target) if self.target else None
            return {
                "active": self._active,
                "running": bool(self.runner and self.runner.alive),
                "error": self.error,
                "engines": json.loads(json.dumps(self.engines)),
                "target": target,
                "status": dict(self.state_now),
                "picking": max(0.0, round(self.picking - time.monotonic(), 1)) if self.picking else 0,
                "shown": bool(self.layout) and self._shown,
                "front": self.front,
                "last": dict(self.last),
                "page": self.page_alive(),
                "excluded": self.excluded_ok if self._excluded else None,
                "keys": {action: {"key": str(self.g.settings.get(name) or ""), "error": self.keys.errors.get(action, ""),
                                  "held": action in self.keys.held,
                                  "note": hotkeys.altgr_note(str(self.g.settings.get(name) or ""))}
                         for action, name in KEY_SETTINGS.items()},
                "listening": bool(self.listening),
                "panel_keys": sorted(self.panel_keys.held.values()),
                "capture": self.capture_how,
                "frozen": (self.frozen or {}).get("mode", "") or ("asked" if self._freeze_asked else ""),
            }

    def brief(self) -> dict:
        with self._lock:
            return {"window": (self.target or {}).get("title") or "", "status": self.state_now.get("state", ""),
                    "words": bool(self.layout)}

    def status(self) -> dict:
        with self._lock:
            target = self.target
            return {
                "active": self._active,
                "running": bool(self.runner and self.runner.alive),
                "error": self.error,
                "target": {k: target.get(k) for k in ("exe", "title")} if target else None,
                "last": {k: self.last.get(k) for k in ("ms", "lines", "engine")},
                "page": self.page_alive(),
            }
