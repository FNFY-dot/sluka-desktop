# SPDX-License-Identifier: LicenseRef-Sluka
# Copyright (c) 2026 Sluka. Part of Sluka Desktop; see LICENSE.txt.
"""Screen text: what a game shows in a box of its window, read off the screen (OCR), for the floating subtitles.

The game text menu's Screen tab, for a game whose text Sluka's engine does not hook -- an emulator's, a browser's,
one whose engine LunaHook does not know, a film's subtitles: the box is dragged once over where the game writes its
text (LunaTranslator's own window for it, over the whole screen), and the window under it is the one read.  The box
is kept for that game, where it is in the window (data/screentext.json), and read again by itself when the game
starts again.  Each new text in the box goes to the floating subtitles, tidied as a game's lines are, and to the
clipboard too where the menu asks.

The reading is done by Sluka's screen reader, ocrd.py, a program of its own as the engine is (hookd.py), with one of
the readers LunaTranslator 12.1.3.12 has: its own (PaddleOCR's PP-OCRv5 model, in the engine folder's ocr folder),
Windows' OCR, or Google Lens (online, asked about once before it is first used: lensask.py).  "auto" takes the first
of the offline ones that works here.  (The Snipping Tool's OCR, which LunaTranslator also has, is not used: it is a
part of Microsoft's Snipping Tool app, which Microsoft has not licensed for other programs to copy out and run.
forget_snipping_tool takes away the copies that Sluka Desktop 0.12.3 and before made.)

While a box is read off the screen, Sluka's own windows are left out of every picture of the screen (Windows 10 2004
and later: they still show), so that the floating subtitles are never read back into themselves, and a box behind
Sluka's window is read all the same.  While the game's own window is read, they are not: nothing of Sluka's is in that
picture, and screenshots and recordings show them.

Keys that work in every program, the game too (hotkeys.py), do from the game what the Screen tab's buttons do: read
the box now, select the text box, read a box once (dragged, read, and forgotten), start or stop reading.  They are
held while the Screen tab is chosen.
"""

from __future__ import annotations

import collections
import json
import logging
import os
import threading
import time
from pathlib import Path

from . import hotkeys, textfilter, texthook

log = logging.getLogger("sluka.games")

OCRD = Path(__file__).with_name("ocrd.py")
#: The readers (ocrd.py's), and "auto": the first of the offline ones that works here.
READERS = ("auto", "builtin", "windows", "lens")
AUTO_ORDER = ("builtin", "windows")
READER_NAMES = {"builtin": "Sluka's own", "windows": "Windows'", "lens": "Google Lens"}
#: Said once, in a message box of its own, where the game's own window gives a picture that no longer changes (the
#: screen reader's WindowWays): what Sluka does instead, and what that means for screenshots and recordings.
FROZEN_TITLE = "Sluka Desktop: reading the screen"


def frozen_text(game: str, what: str) -> str:
    return (f"{what} has to read the screen for {game} to work properly: the game's own window, which you chose as "
            "what is read, gives Sluka only a picture that no longer changes (the game draws with the graphics card "
            "past it).\n\n"
            "So Sluka reads what the screen shows there instead, and keeps its own windows out of pictures of the "
            "screen meanwhile: the text Sluka reads and lays over the game does not show in screenshots or "
            "recordings of this game.\n\n"
            "Choosing the tab again tries the game's own window afresh.")


#: What Sluka Desktop 0.12.3 and before copied out of Windows 11's Snipping Tool (into data/ocr/SnippingTool).
SNIPPING_FILES = ("oneocr.dll", "oneocr.onemodel", "onnxruntime.dll")
_forgotten = False


def forget_snipping_tool(data_dir, engine_dir=None) -> None:
    """The copies of the Snipping Tool's OCR that Sluka Desktop 0.12.3 and before made, taken away: its three files
    (SNIPPING_FILES) in data/ocr/SnippingTool -- or, where the app gave no data folder, in the engine folder's
    ocr/cache/SnippingTool -- and those folders once empty.  Nothing else there is touched.  Once a run of the app."""
    global _forgotten
    if _forgotten:
        return
    _forgotten = True
    places = [Path(data_dir) / "ocr" / "SnippingTool"] if data_dir else []
    if engine_dir:
        places.append(Path(engine_dir) / "ocr" / "cache" / "SnippingTool")
    for folder in places:
        try:
            if not folder.is_dir():
                continue
            gone = []
            for name in SNIPPING_FILES:
                file = folder / name
                if file.is_file():
                    file.unlink()
                    gone.append(name)
            for empty in (folder, folder.parent):
                if empty.name in ("SnippingTool", "cache") and empty.is_dir() and not any(empty.iterdir()):
                    empty.rmdir()
            if gone:
                log.info("the Snipping Tool's OCR, copied there by an earlier Sluka Desktop, is taken away: %s (%s)",
                         folder, ", ".join(gone))
        except OSError as err:
            log.warning("the earlier copy of the Snipping Tool's OCR in %s could not be taken away: %s", folder, err)
#: When the box is read: when its text has changed and settled, every few seconds, or after a click or key in the game.
MODES = ("auto", "interval", "trigger")
DIRECTIONS = ("auto", "h", "v")
#: What is read: what the screen shows there, or the game's window itself (where something may be over it).
CAPTURES = ("screen", "window")
INTERVALS = (500, 1000, 1500, 2000, 3000, 5000)
#: How long the box may take to be dragged before the dragging window is closed.
SELECT_SECONDS = 90.0
#: The app's own windows (winshell.py): its windows, and the floating subtitles'.
MAIN_CLASS = "SlukaDesktopWindow"
BAR_CLASS = "SlukaDesktopBar"
RESTARTS_MOST = 3
#: The keys of the Screen tab: each action's setting.
KEY_SETTINGS = {action: f"ocr_key_{action}" for action in hotkeys.ACTIONS}
#: How long the menu may wait for a key to be pressed (the keys are let go of meanwhile).
LISTEN_SECONDS = 30.0


class OcrProcess(texthook.EngineProcess):
    """ocrd.py, running as hookd.py runs (texthook.EngineProcess): commands to it, and what it says passed on as
    ``events(kind, event)`` -- "ready", "fatal", "engines", "selected", "watching", "status", "capture", "text",
    "error", "stopped", and "note" and "ended" as the engine's."""

    script = OCRD
    #: (its own: the tests' stand-ins for the screen, the libraries and the readers)
    extra_args: list = []

    def engines(self, lang: str) -> bool:
        return self.send({"cmd": "engines", "lang": lang})

    def select(self, delay: float, exclude) -> bool:
        return self.send({"cmd": "select", "delay": round(float(delay), 2), "exclude": sorted(int(p) for p in exclude)})

    def cancel_select(self) -> bool:
        return self.send({"cmd": "cancel-select"})

    def watch(self, params: dict) -> bool:
        return self.send({"cmd": "watch", **params})

    def once(self) -> bool:
        return self.send({"cmd": "once"})

    def halt(self) -> bool:
        return self.send({"cmd": "stop"})


def _key(path: str, exe: str) -> str:
    from .gametext import game_key  # (gametext.py makes this; it is loaded by then)

    return game_key(path, exe)


class ScreenText:
    """The Screen tab's side in the app: which box of which window, read by which reader, and what was read."""

    def __init__(self, games, process_factory=None):
        self.g = games
        self.config = games.config
        self.procs = games.procs
        self._lock = games._lock  # (one lock with the game text's: the menu's state is read under it)
        self.file = Path(self.config.data_dir) / "screentext.json"
        self.memo = self._load()
        self.runner: OcrProcess | None = None
        self.error = ""
        self.engines: dict = {}
        self.target: dict | None = None
        self.selecting: dict | None = None
        self.last = {"text": "", "engine": "", "ms": 0, "at": 0.0, "lines": 0}
        #: The games told (once a run) that the screen has to be read for them: their own window's picture is frozen.
        self._told_frozen: set[str] = set()
        self._active = False
        self._held: dict[str, int] = {}
        self._excluded: list[int] = []
        self.excluded_ok: bool | None = None
        self._exclude_lock = threading.Lock()
        self._restarts: collections.deque = collections.deque(maxlen=8)
        self._next_resume = 0.0
        self._next_exclude = 0.0
        self._save_timer: threading.Timer | None = None
        self._factory = process_factory or OcrProcess
        #: The keys, held while the Screen tab is chosen (and let go of while the menu waits for a new one).
        self.keys = hotkeys.Hotkeys(self._key_pressed)
        self.listening: float = 0.0
        #: A box dragged to be read once: waiting for its reading.
        self._once_pending = False

    # ------------------------------------------------------------------ kept between starts

    def _load(self) -> dict:
        try:
            found = json.loads(self.file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        games = found.get("games") if isinstance(found, dict) else None
        out = {}
        for key, memo in (games or {}).items():
            try:
                box = [int(v) for v in memo["box"]][:4]
                if len(box) == 4 and box[2] > 0 and box[3] > 0:
                    out[str(key)] = {**memo, "box": box}
            except (KeyError, TypeError, ValueError):
                continue
        return out

    def _save_soon(self) -> None:
        with self._lock:
            if self._save_timer is not None:
                self._save_timer.cancel()
            self._save_timer = threading.Timer(0.8, self._save)
            self._save_timer.daemon = True
            self._save_timer.start()

    def _save(self) -> None:
        with self._lock:
            self._save_timer = None
            data = {"games": json.loads(json.dumps(self.memo))}
        try:
            self.file.parent.mkdir(parents=True, exist_ok=True)
            partial = self.file.with_suffix(".json.new")
            partial.write_text(json.dumps(data, indent=1, ensure_ascii=False), encoding="utf-8")
            partial.replace(self.file)
        except OSError as err:
            log.warning("the boxes read on the screen could not be kept (%s): %s", self.file, err)

    # ------------------------------------------------------------------ the Screen tab chosen, and left

    def activate(self) -> None:
        with self._lock:
            if self._active:
                return
            self._active = True
            self._next_resume = 0.0  # a game whose box is kept, open already, is read at once
        self._apply_keys()
        if self._runner() is not None:
            self.check()

    def deactivate(self) -> None:
        with self._lock:
            self._active = False
            self.target = None
            selecting, self.selecting = self.selecting, None
            self._once_pending = False
            self.listening = 0.0
        if selecting is not None:
            self._step_back(selecting)
        self.keys.clear()
        self._stop_runner()
        self._exclude(False)
        self.g._changed()

    def close(self) -> None:
        with self._lock:
            timer = self._save_timer
        if timer is not None:
            timer.cancel()
            self._save()
        self.deactivate()
        self.keys.close()

    # ------------------------------------------------------------------ the screen reader's program

    def _fail(self, text: str) -> None:
        with self._lock:
            self.error = text
            if self.target is not None and self.target.get("state") in ("starting", "watching"):
                self.target["state"] = "failed"
                self.target["error"] = text
        self.g.note(text, "error")

    def _runner(self) -> OcrProcess | None:
        """Sluka's screen reader, running (started if it is not)."""
        with self._lock:
            runner = self.runner
            if runner is not None and runner.alive:
                return runner
        folder = texthook.engine_dir(self.config)
        if not folder.is_dir():
            self._fail(f"Sluka's engine folder is missing ({folder}): unpack Sluka Desktop's zip again, the engine folder "
                       "is in it.")
            return None
        logs = Path(getattr(self.config, "log_dir", "") or Path(self.config.data_dir) / "logs") / "ocrd.log"
        forget_snipping_tool(self.config.data_dir, folder)
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

    def _stop_runner(self) -> None:
        with self._lock:
            runner, self.runner = self.runner, None
        if runner is not None:
            try:
                runner.stop()
            except Exception:
                log.exception("Sluka's screen reader could not be stopped")

    def _event(self, kind: str, event: dict) -> None:
        if kind == "ready":
            self.g.note(f"Sluka's screen reader is running (Python {event.get('python')}).")
        elif kind == "fatal":
            self._fail(f"Sluka's screen reader could not start: {event.get('text') or 'it said nothing'}")
        elif kind == "engines":
            with self._lock:
                self.engines = {name: dict(info) for name, info in (event.get("engines") or {}).items() if isinstance(info, dict)}
            self.g._changed()
        elif kind == "selected":
            self._selected(event)
        elif kind == "watching":
            with self._lock:
                if self.target is not None:
                    self.target["state"] = "watching"
                    self.target["engine"] = str(event.get("engine") or "")
                    self.target["error"] = ""
            self.g._changed()
        elif kind == "status":
            with self._lock:
                if self.target is not None:
                    self.target["status"] = str(event.get("state") or "")
                    self.target["status_text"] = str(event.get("text") or "")
            self.g._changed()
        elif kind == "capture":
            how = str(event.get("how") or "")
            frozen = how == "screen" and event.get("why") == "frozen"
            with self._lock:
                target = self.target
                if target is not None:
                    target["how"] = how
                game = (target or {}).get("exe") or (target or {}).get("title") or "the game"
                tell = (frozen and target is not None and self.g.settings.get("ocr_capture") == "window"
                        and game not in self._told_frozen)
                if tell:
                    self._told_frozen.add(game)
            if tell:
                # (once a game, a run of the app: the switch is needed for the text to be right)
                self.g.popup(FROZEN_TITLE, frozen_text(target.get("title") or game, "The Screen tab"))
            if target is not None and how == "screen" and self.g.settings.get("ocr_capture") == "window" and target.get("hwnd"):
                why = "gives only a picture that no longer changes" if frozen else "cannot be read as it shows"
                self.g.note(f"The game's own window {why}: what the screen shows there is read, and "
                            "Sluka's windows are kept out of screenshots and recordings meanwhile.", "warn")
            # (the screen read: Sluka's windows out of its pictures; the game's own window: in them again)
            self._exclude(True)
            self.g._changed()
        elif kind == "text":
            self._text(event)
        elif kind == "read":
            self._read_once_done(event)
        elif kind == "error":
            text = str(event.get("text") or "")
            with self._lock:
                if self.target is not None:
                    self.target["error"] = text
            self.g.note(text, "error")
        elif kind == "stopped":
            self._stopped(str(event.get("why") or ""))
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
            target = self.target
            reading = target is not None and target.get("state") in ("starting", "watching")
            selecting, self.selecting = self.selecting, None
            self._once_pending = False
            active = self._active
        if selecting is not None:
            self._step_back(selecting)
        if self.g._stop.is_set() or not active:
            return
        self.g.note(f"Sluka's screen reader stopped (code {code}).", "warn" if reading else "info")
        if not reading:
            self.g._changed()
            return
        now = time.monotonic()
        self._restarts.append(now)
        if len([t for t in self._restarts if now - t < 60]) > RESTARTS_MOST:
            with self._lock:
                target["state"] = "failed"
                target["error"] = "Sluka's screen reader keeps stopping."
            self.g.note("Sluka's screen reader keeps stopping; it is not started again. Its notes are in data\\logs\\ocrd.log: "
                        "another reader may do (Read with, in the Screen tab).", "error")
            self.g._changed()
            return
        self.g._later(1.0, lambda: self._watch(target) if self.target is target and self._active else None)

    def check(self) -> dict:
        """Which readers can be used here, looked at again (the language Windows' OCR is to read counts)."""
        runner = self._runner() if self._active else None
        if runner is None:
            return {"ok": False, "error": self.error or "The Screen tab is not chosen."}
        runner.engines(self.g.settings["ocr_lang"])
        return {"ok": True}

    # ------------------------------------------------------------------ the box dragged over the screen

    def _own_windows(self) -> list[dict]:
        find = getattr(self.procs, "own_windows", None)
        if find is None:
            return []
        try:
            return list(find((MAIN_CLASS, BAR_CLASS), visible=False))
        except Exception:
            log.exception("the app's windows could not be listed")
            return []

    def _exclude(self, on: bool) -> None:
        """Sluka's own windows left out of the pictures of the screen while the screen is what is read (or put back
        in them: screenshots and recordings show them).  What is wanted is read here, under a lock of its own, so
        that the last call always has the last word.

        Only those that show: the app's never-shown window, its background worker's, is never touched -- told to
        stay out of pictures (or back in them), such a window came up as an empty white one that did nothing.
        """
        keep_out = getattr(self.procs, "keep_out_of_captures", None)
        if keep_out is None:
            return
        with self._exclude_lock:
            wanted = bool(on) and self._exclusion_wanted()
            windows = [w for w in self._own_windows() if w.get("visible", True)]
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
                # Every one that shows is left out: Sluka's own windows are never read, and may be in front of the game.
                self.excluded_ok = bool(done) and all(w in done for w in windows)

    def _exclusion_wanted(self) -> bool:
        """While a box is chosen, or read once, and while the box is read off the screen -- as set, or because the
        game's own window cannot be read as it shows -- but not while the game's own window is read."""
        with self._lock:
            if not self._active:
                return False
            if self.selecting is not None or self._once_pending:
                return True
            target = self.target
            return (target is not None and target.get("state") in ("starting", "watching")
                    and (self.g.settings.get("ocr_capture") == "screen" or target.get("how") == "screen"))

    def _mine(self) -> set[int]:
        """This app and its programs (the web view's): never the window read."""
        mine = {self.procs.own_pid}
        try:
            every = self.procs.processes()
        except Exception:
            return mine
        changed = True
        while changed:
            changed = False
            for p in every:
                if p["pid"] not in mine and p.get("parent") in mine:
                    mine.add(p["pid"])
                    changed = True
        return mine

    def select(self, purpose: str = "box") -> dict:
        """The menu's "Select the text box": LunaTranslator's box-dragging window over the whole screen.  (``once``: a
        box to be read once, the one kept staying as it is.)"""
        if self.g.settings["mode"] != "screen":
            self.g.set_mode("screen")
        runner = self._runner()
        if runner is None:
            return {"ok": False, "error": self.error or "Sluka's screen reader could not be started."}
        with self._lock:
            if self.selecting is not None:
                return {"ok": True, "already": True}
            self.selecting = {"since": time.monotonic(), "stepped": [], "purpose": purpose}
        self._exclude(True)
        stepped = []
        if not self.excluded_ok:
            # Where Windows cannot leave Sluka's windows out of its pictures (before Windows 10 2004), they step aside.
            show = getattr(self.procs, "show_window", None)
            for window in self._own_windows():
                if show is None or not window.get("visible", True) or window.get("minimized"):
                    continue
                if show(window["hwnd"], "hide" if window.get("class") == BAR_CLASS else "minimize"):
                    stepped.append(window)
        with self._lock:
            if self.selecting is not None:
                self.selecting["stepped"] = stepped
        runner.select(0.5 if stepped else 0.25, self._mine())
        self.g._changed()
        return {"ok": True}

    def cancel_select(self) -> dict:
        with self._lock:
            runner = self.runner
            selecting = self.selecting
        if selecting is None or runner is None:
            return {"ok": True}
        runner.cancel_select()
        return {"ok": True}

    def _step_back(self, selecting: dict) -> None:
        show = getattr(self.procs, "show_window", None)
        if show is None:
            return
        for window in selecting.get("stepped") or []:
            try:
                show(window["hwnd"], "show" if window.get("class") == BAR_CLASS else "restore")
            except Exception:
                log.exception("a window could not be put back")

    def select_once(self) -> dict:
        """A box dragged over anything on the screen, read once into the floating subtitles, and not kept."""
        return self.select("once")

    def _selected(self, event: dict) -> None:
        with self._lock:
            selecting, self.selecting = self.selecting, None
        if selecting is not None:
            self._step_back(selecting)
        if (selecting or {}).get("purpose") == "once" and event.get("rect") and not event.get("cancelled"):
            self._read_once(event)
            return
        if event.get("cancelled") or not event.get("rect"):
            if event.get("error"):
                self.g.note(f"The box could not be dragged: {event['error']}", "error")
            else:
                self.g.note("No box was dragged.")
            self._exclude(self._exclusion_wanted())
            self.g._changed()
            return
        x1, y1, x2, y2 = (int(v) for v in event["rect"][:4])
        window = event.get("window") if isinstance(event.get("window"), dict) else None
        if window and window.get("hwnd") and window.get("box"):
            pid = int(window.get("pid") or 0)
            path = self.procs.exe(pid) if pid else ""
            exe = os.path.basename(path.replace("\\", "/")) if path else ""
            key = _key(path, exe) if path else ""
            client = [int(v) for v in (window.get("client") or [0, 0, 0, 0])][2:4]
            title = str(window.get("title") or exe or "the game")
            target = {"hwnd": int(window["hwnd"]), "pid": pid, "title": title, "class": str(window.get("class") or ""),
                      "exe": exe, "path": path, "key": key, "box": [int(v) for v in window["box"]][:4], "client": client}
            if key:
                with self._lock:
                    self.memo[key] = {"box": target["box"], "client": client, "class": target["class"], "title": title,
                                      "exe": exe, "seen": time.strftime("%Y-%m-%d %H:%M")}
                    self._held.pop(key, None)
                self._save_soon()
            self.g.note(f"The box over {title}{f' ({exe})' if exe and exe != title else ''} is read: "
                        f"{target['box'][2]}×{target['box'][3]} pixels.")
        else:
            target = {"hwnd": 0, "pid": 0, "title": "The screen", "class": "", "exe": "", "path": "", "key": "",
                      "box": [x1, y1, max(1, x2 - x1), max(1, y2 - y1)], "client": None}
            self.g.note("No window is under the box: what the screen shows there is read.")
        self._watch(target)

    def _read_once(self, event: dict) -> None:
        x1, y1, x2, y2 = (int(v) for v in event["rect"][:4])
        s = self.g.settings
        with self._lock:
            runner = self.runner
            self._once_pending = runner is not None
        if runner is None:
            return
        self._exclude(True)  # (Sluka's windows still out of the picture: the floating subtitles may be over the box)
        runner.send({"cmd": "read", "rect": [x1, y1, max(1, x2 - x1), max(1, y2 - y1)], "engine": self._reader(),
                     "lang": s["ocr_lang"], "direction": s["ocr_vertical"], "furigana": bool(s["ocr_furigana"])})

    def _read_once_done(self, event: dict) -> None:
        with self._lock:
            asked, self._once_pending = self._once_pending, False
        self._exclude(self._exclusion_wanted())
        if not asked:
            return  # (sluka ocr-check's, or one asked before the Screen tab was left)
        if event.get("error"):
            self.g.note(f"The box could not be read: {event['error']}", "error")
            self.g._changed()
            return
        s = self.g.settings
        text = textfilter.clean(str(event.get("text") or ""), repeats="off", join=bool(s["join"]), codes=False)
        if not text:
            self.g.note("Nothing was read in the box.")
            self.g._changed()
            return
        with self._lock:
            self.last = {"text": text[:500], "engine": str(event.get("engine") or ""), "ms": int(event.get("ms") or 0),
                         "at": round(time.time(), 3), "lines": int(event.get("lines") or 0), "once": True}
        self.g._deliver("screen", text, force=True)

    # ------------------------------------------------------------------ the keys

    def _apply_keys(self) -> None:
        """The keys held as the settings have them -- while the Screen tab is chosen and no new key is awaited."""
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
        """The menu waits for a key to be pressed: the keys let go of meanwhile (so that one already held reaches it)."""
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
                    return {"ok": False, "error": f"{text} is the key of \u201c{hotkeys.ACTIONS[other]}\u201d already"}
        before = str(self.g.settings.get(name) or "")
        with self._lock:
            self.listening = 0.0
        self.g.update({name: text})
        error = self.keys.errors.get(action, "") if text and self._active else ""
        if error:
            self.g.update({name: before})
            self.g.note(f"{text} cannot be the key of \u201c{hotkeys.ACTIONS[action]}\u201d: {error}.", "warn")
            return {"ok": False, "error": f"{text}: {error}. Choose another key."}
        if text:
            self.g.note(f"{text}: {hotkeys.ACTIONS[action]}." + (" " + hotkeys.altgr_note(text) + "." if hotkeys.altgr_note(text) else ""))
        return {"ok": True, "key": text}

    def _key_pressed(self, action: str) -> None:
        """A key of the Screen tab pressed, in the game or anywhere."""
        with self._lock:
            active = self._active
            selecting = self.selecting is not None
            target = self.target
            reading = target is not None and target.get("state") in ("starting", "watching")
        if not active:
            return
        log.info("key: %s", action)
        if action in ("select", "once"):
            if selecting:
                self.cancel_select()  # (pressed again while the box is dragged: stopped)
            elif action == "select":
                self.select()
            else:
                self.select_once()
        elif action == "read":
            answer = self.read_now() if reading else self.start()
            if not answer.get("ok"):
                self.g.note(answer.get("error") or "Nothing could be read.", "warn")
        elif action == "toggle":
            answer = self.stop() if reading else self.start()
            if not answer.get("ok"):
                self.g.note(answer.get("error") or "Nothing could be read.", "warn")

    # ------------------------------------------------------------------ reading

    def _watch(self, target: dict) -> None:
        runner = self._runner()
        with self._lock:
            target.update(state="starting" if runner else "failed", status="", status_text="", engine="", how="",
                          since=round(time.time(), 3), error="" if runner else self.error)
            self.target = target
        if runner is None:
            self.g._changed()
            return
        s = self.g.settings
        self._exclude(self._exclusion_wanted())
        # Sluka's own window in front: read on where it is left out of the pictures (or the game's window is read).
        allow = [self.procs.own_pid] if s["ocr_capture"] == "window" or self.excluded_ok else []
        runner.watch({
            "hwnd": target["hwnd"], "pid": target["pid"], "box": list(target["box"]), "client": target.get("client"),
            "engine": self._reader(), "mode": s["ocr_mode"], "interval": s["ocr_interval_ms"] / 1000.0,
            "lang": s["ocr_lang"], "direction": s["ocr_vertical"], "furigana": bool(s["ocr_furigana"]),
            "capture": s["ocr_capture"], "front": bool(s["ocr_front"]), "allow": allow,
        })
        bar = getattr(self.g.host, "bar", None)
        if bar is not None and not bar.on:
            try:
                bar.set_on(True)
            except Exception:
                log.exception("the floating subtitles could not be turned on")
        self.g._changed()

    def _text(self, event: dict) -> None:
        s = self.g.settings
        # Tidied as a game's lines are: its lines made one where the menu says (no repeats or codes on a screen).
        text = textfilter.clean(str(event.get("text") or ""), repeats="off", join=bool(s["join"]), codes=False)
        with self._lock:
            if self.target is None or not self._active or not text:
                return
            self.last = {"text": text[:500], "engine": str(event.get("engine") or ""), "ms": int(event.get("ms") or 0),
                         "at": round(time.time(), 3), "lines": int(event.get("lines") or 0)}
            self.target["error"] = ""
        self.g._deliver("screen", text, force=bool(event.get("forced")))

    def _stopped(self, why: str) -> None:
        with self._lock:
            target = self.target
            if target is None:
                return
            if why == "gone":
                target["state"] = "ended"
            elif why in ("unavailable", "error"):
                target["state"] = "failed"
            elif target.get("state") in ("starting", "watching"):
                target["state"] = "stopped"
        if why == "gone":
            self.g.note(f"{target.get('title') or 'The window'} has closed: its box is read again when it is back.")
        self._exclude(self._exclusion_wanted())
        self.g._changed()

    def read_now(self) -> dict:
        with self._lock:
            target, runner = self.target, self.runner
        if target is None or runner is None or target.get("state") not in ("starting", "watching"):
            return {"ok": False, "error": "Nothing is being read: select the text box first."}
        runner.once()
        return {"ok": True}

    def stop(self) -> dict:
        with self._lock:
            target, runner = self.target, self.runner
            if target is None:
                return {"ok": False, "error": "Nothing is being read."}
            target["state"] = "stopped"
            if target.get("key") and target.get("pid"):
                # Not read again by itself while it runs: it was stopped on purpose.
                self._held[target["key"]] = target["pid"]
        if runner is not None:
            runner.halt()
        self._exclude(False)
        self.g.note("Reading the box stopped.")
        self.g._changed()
        return {"ok": True}

    def start(self) -> dict:
        """The menu's "Read": the box read again (the one kept for a game that is open, where there is none)."""
        if self.g.settings["mode"] != "screen":
            self.g.set_mode("screen")
        with self._lock:
            target = self.target
        if target is None or target.get("state") == "ended":
            target = self._find_kept()
            if target is None:
                return {"ok": False, "error": "Select the text box first (a game whose box is kept is read when it is open)."}
        with self._lock:
            self._held.pop(target.get("key") or "", None)
        self._watch(target)
        return {"ok": True}

    def forget(self) -> dict:
        with self._lock:
            target = self.target
            key = (target or {}).get("key") or ""
            if not key or key not in self.memo:
                return {"ok": False, "error": "No box is kept for this game."}
            del self.memo[key]
        self._save_soon()
        self.g.note(f"The box kept for {target.get('exe') or 'this game'} is forgotten.")
        self.g._changed()
        return {"ok": True}

    def _reader(self) -> str:
        """The reader to read with: the one chosen, Google Lens only once it has had its yes (lensask.py)."""
        lens = getattr(self.g, "lens", None)
        return lens.reader("ocr_engine") if lens is not None else self.g.settings["ocr_engine"]

    def settings_changed(self, before: dict, after: dict) -> None:
        if not self._active:
            return
        if before.get("ocr_lang") != after.get("ocr_lang"):
            self.check()
        if any(before.get(name) != after.get(name) for name in KEY_SETTINGS.values()):
            self._apply_keys()
        keys = ("ocr_engine", "ocr_mode", "ocr_interval_ms", "ocr_lang", "ocr_vertical", "ocr_furigana", "ocr_capture",
                "ocr_front")
        lens = before.get("lens_ok") != after.get("lens_ok") and after.get("ocr_engine") == "lens"
        if lens or any(before.get(k) != after.get(k) for k in keys):
            with self._lock:
                target = self.target
                again = target is not None and target.get("state") in ("starting", "watching", "failed")
            if again:
                self._watch(target)

    # ------------------------------------------------------------------ a game whose box is kept

    def _find_kept(self, running=None) -> dict | None:
        """The first game open whose box is kept (and not stopped by hand while it runs), with its window."""
        with self._lock:
            memo = {k: dict(v) for k, v in self.memo.items()}
            held = dict(self._held)
        wanted: dict[str, set] = {}
        for key, kept in memo.items():
            if kept.get("exe") and not key.startswith("name:"):
                wanted.setdefault(str(kept["exe"]).lower(), set()).add(key)
        if not wanted:
            return None
        windows_of = getattr(self.procs, "windows_of", None)
        if windows_of is None:
            return None
        for p in running if running is not None else self.procs.processes():
            keys = wanted.get(str(p.get("name") or "").lower())
            if not keys or p["pid"] == self.procs.own_pid:
                continue
            path = self.procs.exe(p["pid"])
            key = _key(path, str(p.get("name") or ""))
            if key not in keys or held.get(key) == p["pid"]:
                continue
            windows = [w for w in windows_of([p["pid"]]) if not w.get("minimized")]
            if not windows:
                continue  # (still starting: its window comes)
            kept = memo[key]
            window = next((w for w in windows if kept.get("class") and w.get("class") == kept["class"]), windows[0])
            return {"hwnd": int(window["hwnd"]), "pid": p["pid"], "title": window.get("title") or kept.get("title") or p["name"],
                    "class": window.get("class") or "", "exe": kept["exe"], "path": path, "key": key,
                    "box": list(kept["box"]), "client": list(kept.get("client") or []) or None}
        return None

    def _resume(self) -> None:
        with self._lock:
            if not self._active or self.selecting is not None:
                return
            target = self.target
            if target is not None and target.get("state") not in ("ended",):
                return
            if not self.memo:
                return
        try:
            running = self.procs.processes()
        except Exception:
            return
        alive = {p["pid"] for p in running}
        with self._lock:
            self._held = {k: pid for k, pid in self._held.items() if pid in alive}
        found = self._find_kept(running)
        if found is None:
            return
        self.g.note(f"{found['title']} is open: its box is read, as before.")
        self._watch(found)

    def tick(self, now: float) -> None:
        if not self._active:
            return
        with self._lock:
            selecting = self.selecting
            runner = self.runner
        if selecting is not None and now - selecting["since"] > SELECT_SECONDS and runner is not None:
            selecting["since"] = now
            runner.cancel_select()
        if self.listening and now - self.listening > LISTEN_SECONDS:
            self.listen(False)  # (the menu said nothing more: the keys back)
        if now >= self._next_exclude:
            self._next_exclude = now + 2.0
            # (a window of Sluka's opened since -- the floating subtitles turned on -- is left out too)
            self._exclude(self._exclusion_wanted())
        if now >= self._next_resume:
            self._next_resume = now + 3.0
            self._resume()

    # ------------------------------------------------------------------ what the menu sees

    def _auto_choice(self) -> str:
        for name in AUTO_ORDER:
            if (self.engines.get(name) or {}).get("ok"):
                return name
        return ""

    def state(self) -> dict:
        with self._lock:
            target = None
            if self.target is not None:
                target = {k: v for k, v in self.target.items() if k not in ("key", "path")}
                target["kept"] = bool(self.target.get("key")) and self.target["key"] in self.memo
            return {
                "active": self._active,
                "running": bool(self.runner and self.runner.alive),
                "error": self.error,
                "engines": json.loads(json.dumps(self.engines)),
                "auto": self._auto_choice(),
                "target": target,
                "selecting": self.selecting is not None,
                "last": dict(self.last),
                "excluded": self.excluded_ok if self._excluded else None,
                "kept": len(self.memo),
                "keys": {action: {"key": str(self.g.settings.get(name) or ""), "error": self.keys.errors.get(action, ""),
                                  "held": action in self.keys.held,
                                  "note": hotkeys.altgr_note(str(self.g.settings.get(name) or ""))}
                         for action, name in KEY_SETTINGS.items()},
                "listening": bool(self.listening),
            }

    def brief(self) -> dict:
        with self._lock:
            target = self.target or {}
            return {"state": target.get("state") or "", "status": target.get("status") or ""}

    def status(self) -> dict:
        with self._lock:
            target = self.target
            return {
                "active": self._active,
                "running": bool(self.runner and self.runner.alive),
                "error": self.error,
                "reader": (target or {}).get("engine") or "",
                "target": {k: target.get(k) for k in ("exe", "title", "state", "engine")} if target else None,
                "engines": {name: bool(info.get("ok")) for name, info in self.engines.items()},
            }


# ------------------------------------------------------------------------------------------- the doctor, ocr-check


def _check_runner(config, events, name: str):
    folder = texthook.engine_dir(config)
    data = Path(getattr(config, "data_dir", "") or Path(getattr(config, "log_dir", "data/logs")).parent)
    logs = Path(getattr(config, "log_dir", "") or data / "logs") / name
    forget_snipping_tool(data, folder)
    args = ["--network", str(getattr(config, "network_mode", "") or "direct"),
            "--socks", str(getattr(config, "socks", "") or "127.0.0.1:9050")] + list(OcrProcess.extra_args)
    runner = OcrProcess(texthook.Engine(folder), lambda kind, event: events.put((kind, event)), log_path=logs, extra_args=args)
    runner.start()
    return runner


def try_readers(config, lang: str = "ja", wait: float = 30.0):
    """Sluka's screen reader started, asked which readers can be used here, and stopped (for the doctor):
    (True, {reader: {"ok", "why"}}) or (False, why it did not answer)."""
    import queue

    folder = texthook.engine_dir(config)
    if not folder.is_dir():
        return False, f"the engine folder is missing ({folder})"
    events: queue.Queue = queue.Queue()
    try:
        runner = _check_runner(config, events, "ocrd-doctor.log")
    except OSError as err:
        return False, f"its program could not be started ({err})"
    notes: list[str] = []
    deadline = time.monotonic() + wait
    try:
        while time.monotonic() < deadline:
            try:
                kind, event = events.get(timeout=0.2)
            except queue.Empty:
                continue
            if kind == "ready":
                runner.engines(lang)
            elif kind == "engines":
                return True, dict(event.get("engines") or {})
            elif kind == "fatal":
                return False, str(event.get("text") or "it could not start")
            elif kind == "note":
                notes.append(str(event.get("text") or ""))
            elif kind == "ended":
                return False, "it ended at once" + (": " + " / ".join(notes[-3:]) if notes else "")
        return False, f"it said nothing in {wait:.0f} s"
    finally:
        runner.stop()


def command_check(config, read: bool = False, reader: str = "", lang: str = "ja", out=None) -> int:
    """``sluka ocr-check``: Sluka's screen reader started, what can read the screen here and why not; with --read, a
    box dragged over the screen read by each reader (Google Lens only when asked for by name: it sends the picture)."""
    import queue
    import sys

    out = out or sys.stdout
    read = read or bool(reader)

    def say(text: str) -> None:
        try:
            print(text, file=out, flush=True)
        except (OSError, ValueError):
            pass

    if not texthook.WINDOWS and not OcrProcess.extra_args:
        say("sluka: the screen is read on Windows.")
        return 2
    folder = texthook.engine_dir(config)
    if not folder.is_dir():
        say(f"failed: Sluka's engine folder is missing ({folder}): unpack Sluka Desktop's zip again")
        return 3
    events: queue.Queue = queue.Queue()
    try:
        runner = _check_runner(config, events, "ocrd-check.log")
    except OSError as err:
        say(f"failed: the screen reader's program could not be started: {err}")
        return 5

    def wait_for(kinds, seconds: float):
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            try:
                kind, event = events.get(timeout=0.2)
            except queue.Empty:
                continue
            if kind == "note":
                say(f"reader: {event.get('text')}")
            elif kind == "error":
                say(f"note: {event.get('text')}")
            elif kind in ("fatal", "ended"):
                return kind, event
            elif kind in kinds:
                return kind, event
        return "", {}

    code = 0
    try:
        kind, event = wait_for(("ready",), 20)
        if kind != "ready":
            say(f"failed: the screen reader did not start ({event.get('text') or event.get('code') or 'it said nothing in 20 s'})")
            return 5
        say(f"ok: Sluka's screen reader is running (Python {event.get('python')}, {event.get('bits')}-bit), in {folder}")
        runner.engines(lang)
        kind, event = wait_for(("engines",), 60)
        if kind != "engines":
            say("failed: the screen reader did not say which readers can be used")
            return 5
        engines = event.get("engines") or {}
        for name in READERS[1:]:
            info = engines.get(name) or {}
            say(f"{'ok' if info.get('ok') else 'not here'}: {READER_NAMES[name]} OCR ({name}): {info.get('why') or '?'}")
        if not read:
            say("(to have each read a box you drag over the screen:  sluka ocr-check --read)")
            return 0 if any((engines.get(n) or {}).get("ok") for n in AUTO_ORDER) else 1
        names = [reader] if reader else [n for n in AUTO_ORDER if (engines.get(n) or {}).get("ok")]
        if not names:
            say("failed: no reader can be used here")
            return 1
        say("Drag a box over some text on the screen (right-click, or click without dragging, to stop)…")
        runner.select(0.3, [])
        kind, event = wait_for(("selected",), 180)
        if kind != "selected" or event.get("cancelled"):
            say("note: no box was dragged")
            return 1
        x1, y1, x2, y2 = (int(v) for v in event["rect"][:4])
        window = event.get("window") or {}
        say(f"ok: the box {x2 - x1}×{y2 - y1} at {x1},{y1}" + (f", over {window.get('title') or window.get('class')}" if window else ""))
        for name in names:
            runner.send({"cmd": "read", "rect": [x1, y1, x2 - x1, y2 - y1], "engine": name, "lang": lang})
            kind, event = wait_for(("read",), 90)
            if kind != "read":
                say(f"failed: {READER_NAMES.get(name, name)} OCR said nothing in 90 s")
                code = 1
                continue
            if event.get("error"):
                say(f"failed: {READER_NAMES.get(name, name)} OCR: {event['error']}")
                code = 1
                continue
            text = str(event.get("text") or "")
            say(f"ok: {READER_NAMES.get(name, name)} OCR, {event.get('ms')} ms, {event.get('lines')} lines:")
            for line in (text or "(nothing read)").split("\n"):
                say(f"    {line}")
        return code
    finally:
        runner.stop()
