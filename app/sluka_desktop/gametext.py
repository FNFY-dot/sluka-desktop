# SPDX-License-Identifier: LicenseRef-Sluka
# Copyright (c) 2026 Sluka. Part of Sluka Desktop; see LICENSE.txt.
"""Game text: lines from a running game (or the clipboard) into the floating subtitles -- or, with Sluka Vision, the
words of a game's whole window read and laid over it where they sit.

This is the side of the game text menu (web/dock.js, beside the subtitles
button in the app's windows) that does the work, as LunaTranslator does it:

  game        Sluka's engine (texthook.py, hookd.py: LunaHook, as
              LunaTranslator 12.1.3.12 has it, which comes with the app) is
              put into the game chosen in the menu -- from the list of
              programs with a window, or by clicking the game's window -- and
              into every program of the same file (games that draw in programs
              of their own).  Every place the game's text comes through is a
              "text thread"; the menu lists them with what each said last, and
              the one picked -- or more than one, put together as
              LunaTranslator puts them -- goes to the floating subtitles, each
              line as it comes.  What was picked, the hook codes given, and
              whether Windows' own text functions are hooked too are kept for
              that game (data/gametext.json) and used again the next time,
              when the game is hooked again by itself if asked.  Where nothing
              is picked yet, the thread that looks most like dialogue is taken
              (and a click changes it).
  clipboard   every text copied in another program.
  screen      the text in a box over the game's window, read off the screen
              (OCR: ocrtext.py, ocrd.py), for a game no hook reads.
  vision      Sluka Vision (vision.py): the game's whole window read off the
              screen, its words laid over it where they sit -- not the
              floating subtitles, which rest meanwhile.
  off         nothing is taken (the bar still shows what is sent to it).

Each line is tidied as the menu's settings say (textfilter.py) and shown by
the bar (bar.py); a game's lines may be put on the clipboard too.
"""

from __future__ import annotations

import collections
import json
import logging
import os
import re
import threading
import time
from pathlib import Path

from . import ankicards, hotkeys, lensask, ocrtext, playclock, popups, textfilter, texthook, vision, winproc
from .host import Request, error_response, json_response

log = logging.getLogger("sluka.games")

MODES = ("off", "game", "clipboard", "screen", "vision")
DEFAULTS = {
    "mode": "game",
    "flush_ms": 500,        # LunaHook's wait for the rest of a line: a thread's text is one line once this long is quiet
    "codepage": 932,        # how a game's text that is not Unicode is read (932: Japanese, Shift-JIS)
    "repeats": "auto",      # letters sent more than once: textfilter.REPEAT_CHOICES
    "join": True,           # the lines a game breaks, made one
    "codes": True,          # the engines' layout codes taken out
    "copy": False,          # a game's lines put on the clipboard too
    "auto_pick": True,      # the thread most like dialogue taken where none is picked
    "auto_hook": True,      # a game hooked before is hooked again when it starts
    "skip_own": True,       # text copied in Sluka's own windows is not taken from the clipboard
    "clip_most": 1000,      # longer copied text is not taken (a page, not a line)
    # The screen (ocrtext.py):
    "ocr_engine": "auto",       # which reader: ocrtext.READERS ("auto": the first offline one that works here)
    "ocr_mode": "auto",         # when the box is read: as its text changes and settles, every few seconds, after a click
    "ocr_interval_ms": 1500,    # (every few seconds: how often)
    "ocr_lang": "ja",           # the language Windows' OCR reads
    "ocr_vertical": "auto",     # the box's text written across ("h"), down ("v"), or either
    "ocr_furigana": True,       # the small kana that tell a word's reading left out
    "ocr_capture": "screen",    # what is read: what the screen shows there, or the game's window itself
    "ocr_front": True,          # read only while the game (or Sluka) is in front
    # Keys that work in every program, the game too, while the Screen tab is chosen ("Ctrl+Shift+R"; "": none)
    "ocr_key_read": "",         # read the box now
    "ocr_key_select": "",       # select the text box
    "ocr_key_once": "",         # drag a box, read it once
    "ocr_key_toggle": "",       # start or stop reading
    # Sluka Vision (vision.py): the whole window, its words laid over it
    "vision_engine": "lens",    # which reader: vision.READERS (Google Lens, the best at a whole window)
    "vision_auto": True,        # read again by itself as what the window shows changes and settles
    "vision_furigana": True,    # the small kana over a word that tell its reading left out
    "vision_capture": "screen", # what is read: what the screen shows there, or the game's window itself
    # (its keys, held while the Sluka Vision tab is chosen: YomiNinja's own, as it comes)
    "vision_key_read": "Alt+S",   # read the window in front
    "vision_key_auto": "",        # reading by itself on or off
    "vision_key_clear": "Alt+V",  # put the words away
    "vision_key_pause": "Alt+P",  # the game paused, its picture kept over it: on or off
    "vision_key_freeze": "Alt+F", # only its picture kept, the game going on behind it: on or off
    # Google Lens (lensask.py): asked about once, before Sluka first sends it a picture -- True once it has had its yes
    "lens_ok": False,
}
#: The screen's settings that are one of a few.
OCR_CHOICES = {"ocr_engine": ocrtext.READERS, "ocr_mode": ocrtext.MODES, "ocr_vertical": ocrtext.DIRECTIONS,
               "ocr_capture": ocrtext.CAPTURES, "vision_engine": vision.READERS, "vision_capture": vision.CAPTURES}
LANG_TAG = re.compile(r"^[A-Za-z]{2,3}(?:-[A-Za-z0-9]{2,8}){0,3}$")
FLUSH_CHOICES = (50, 100, 200, 300, 500, 800, 1200, 2000)
#: The code pages the menu offers, as LunaTranslator offers them (0: as each hook finds it).
CODEPAGES = (932, 65001, 936, 950, 949, 1258, 874, 1256, 1255, 1254, 1253, 1257, 1250, 1251, 1252, 437, 0)
#: How long a page may hold a request open for the next change.
POLL_SECONDS = 20
#: Lines kept for each thread, and the most threads kept.
THREAD_LINES = 20
THREADS_MOST = 400
#: Lines of more than one picked thread that come within this long of each other are shown together, in the
#: order the threads were picked (LunaTranslator waits 0.1 s, or the flush delay if shorter).
TOGETHER = 0.1
#: Longer text from a game is not shown (LunaTranslator's maxOutputSize): a thread that reads a whole script.
MOST_SHOWN = 10000
#: How long a game is given to connect after its hook is put in, before the menu says what may be wrong.
CONNECT_HINT_SECONDS = 12.0
#: How much a thread has to look like dialogue to be picked by itself (about two different sentences of it).
AUTO_PICK_SCORE = 2.0
#: How long a game's hook is given to leave it after it is let go, before it is hooked again.
LET_GO_SECONDS = 2.5
#: The menu's long polls are answered at most this often (a game's thread may send many lines a second).
ANSWER_EVERY = 0.15
#: How many times in a minute Sluka's engine is started again before it is left stopped.
RESTARTS_MOST = 3
URLISH = re.compile(r"^(?:[a-z][a-z0-9+.-]*://|www\.)\S+$|^[A-Za-z]:\\\S*$|^\\\\\S+$", re.I)


def game_key(path: str, exe: str) -> str:
    if path:
        return os.path.normcase(os.path.normpath(path)).lower()
    return "name:" + (exe or "").lower()


class TextThread:
    """A place in the game that text comes through, as the engine numbers it, and what it said."""

    def __init__(self, event: dict, now: float):
        self.handle = int(event["id"])
        self.pid = int(event.get("pid") or 0)
        self.addr = int(event.get("addr") or 0)
        self.ctx = int(event.get("ctx") or 0)
        self.ctx2 = int(event.get("ctx2") or 0)
        self.name = str(event.get("name") or "")
        self.code = str(event.get("code") or "")
        self.lines: collections.deque[str] = collections.deque(maxlen=THREAD_LINES)
        self.raw_last = ""
        self.count = 0
        self.first = now
        self.last = now
        self._times: collections.deque[float] = collections.deque(maxlen=12)

    def add(self, raw: str, text: str, now: float) -> None:
        self.raw_last = raw
        self.count += 1
        self.last = now
        self._times.append(now)
        if text:
            self.lines.append(text)

    @property
    def per_second(self) -> float:
        if len(self._times) < 4:
            return 0.0
        span = self._times[-1] - self._times[0]
        return (len(self._times) - 1) / span if span > 0 else 99.0

    def score(self) -> float:
        return textfilter.dialogue_score(list(self.lines), self.name, self.per_second)

    def memo(self) -> dict:
        return {"code": self.code, "name": self.name, "ctx": self.ctx, "ctx2": self.ctx2}

    def matches(self, memo: dict) -> int:
        """As LunaTranslator matches a thread it picked before (texthook.py match_compatibility): 2, the same hook at
        the same place (the low 16 bits of the places, which stay where Windows loads a program elsewhere); 1, the
        same hook at another place; 0, another hook."""
        code = str(memo.get("code") or "")
        if not code or code != self.code:
            return 0
        try:
            ctx, ctx2 = int(memo.get("ctx") or 0), int(memo.get("ctx2") or 0)
        except (TypeError, ValueError):
            return 1
        if (ctx & 0xFFFF) == (self.ctx & 0xFFFF) and (ctx2 & 0xFFFF) == (self.ctx2 & 0xFFFF):
            return 2
        return 1

    def json(self) -> dict:
        last = self.lines[-1] if self.lines else ""
        return {
            "id": self.handle,
            "pid": self.pid,
            "name": self.name,
            "code": self.code,
            "text": last[:240],
            "more": len(last) > 240,
            "lines": [line[:240] for line in list(self.lines)[-4:]],
            "count": self.count,
            "last": round(self.last, 3),
        }


class GameText:
    def __init__(self, config, host, procs=None, clipboard_factory=None, engine_factory=None, ocr_factory=None,
                 lens_ask=None, popup=None, cards=None):
        self.config = config
        #: A message that is not to wait for the menu to be opened (popups.show: Windows' own message box).
        self.popup = popup or popups.show
        self.host = host
        self.procs = procs or winproc.Procs()
        self.file = Path(config.data_dir) / "gametext.json"
        self._lock = threading.RLock()
        self.settings, self.games = self._load()
        self.version = 0
        self._dirty = False
        self._waiting: list[tuple[float, object]] = []
        self._answered = 0.0
        self.log: collections.deque = collections.deque(maxlen=200)
        self.engine: texthook.Engine | None = None
        self.engine_error = ""
        self.runner: texthook.EngineProcess | None = None
        self._restarts: collections.deque = collections.deque(maxlen=8)
        self.game: dict | None = None
        self._watches: dict[int, object] = {}
        self.threads: "collections.OrderedDict[int, TextThread]" = collections.OrderedDict()
        self.selected: list[int] = []
        #: Picked as the same hook as one picked for this game before, at another place (and which of those it stands
        #: in for): given up for the very one when it comes.
        self._loose: dict[int, int] = {}
        self.picked = ""
        self.picking_until = 0.0
        self.last_attach: dict | None = None
        self._mine: set[int] = set()
        self._tried: dict[int, float] = {}
        self._let_go: dict[int, float] = {}
        self._collector: list[tuple[int, str]] = []
        self._collected_at = 0.0
        self._last_shown = ""
        self.last_line = {"text": "", "at": 0.0, "from": ""}
        self._jobs: list[tuple[float, object]] = []
        self._next_scan = 0.0
        self._next_alive = 0.0
        self._next_more = 0.0
        self._save_timer: threading.Timer | None = None
        self._stop = threading.Event()
        self._clipboard_factory = clipboard_factory
        self._engine_factory = engine_factory or texthook.EngineProcess
        self.clipboard = None
        #: Whether the floating subtitles were on when Sluka Vision was chosen (they come back after it).
        self._bar_was_on = False
        try:
            self.admin = bool(self.procs.is_admin())
        except Exception:
            self.admin = False
        #: Google Lens, asked about before it first reads (for the Screen tab and Sluka Vision alike).
        self.lens = lensask.LensQuestion(self, lens_ask)
        #: The screen: the text in a box over a game's window, read off it (the Screen tab).
        self.screen = ocrtext.ScreenText(self, ocr_factory)
        #: Sluka Vision: a game's whole window read, its words laid over it (the Sluka Vision tab).
        self.vision = vision.VisionText(self, ocr_factory)
        #: The lines shown and read, with their times, and the game's sound and picture, for their Anki cards.
        self.cards = cards if cards is not None else ankicards.Cards(self)
        #: How long a game is played, half of it listening on Sluka's Home page (told to the engine a minute at a time).
        try:
            self.play: playclock.PlayClock | None = playclock.PlayClock(self)
        except Exception:
            log.exception("game text: the time played cannot be looked at")
            self.play = None

    # ------------------------------------------------------------------ kept between starts

    def _load(self) -> tuple[dict, dict]:
        try:
            found = json.loads(self.file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            found = {}
        settings = dict(DEFAULTS)
        if isinstance(found, dict) and isinstance(found.get("settings"), dict):
            settings.update(self._clean_settings(found["settings"]))
        games = found.get("games") if isinstance(found, dict) and isinstance(found.get("games"), dict) else {}
        return settings, {str(k): v for k, v in games.items() if isinstance(v, dict)}

    @staticmethod
    def _clean_settings(given: dict) -> dict:
        out = {}
        for key, default in DEFAULTS.items():
            if key not in given:
                continue
            value = given[key]
            if key == "mode":
                if value in MODES:
                    out[key] = value
            elif key == "repeats":
                if str(value) in textfilter.REPEAT_CHOICES:
                    out[key] = str(value)
            elif key in ("flush_ms", "codepage", "clip_most", "ocr_interval_ms"):
                if isinstance(value, bool):
                    continue
                try:
                    number = int(value)
                except (TypeError, ValueError):
                    continue
                if key == "flush_ms":
                    out[key] = max(0, min(10000, number))
                elif key == "codepage":
                    if 0 <= number <= 65535:
                        out[key] = number
                elif key == "ocr_interval_ms":
                    out[key] = max(300, min(10000, number))
                else:
                    out[key] = max(50, min(20000, number))
            elif key in OCR_CHOICES:
                if value == "snipping" and key in ("ocr_engine", "vision_engine"):
                    # (the Snipping Tool's OCR, chosen before Sluka Desktop 0.12.4 left it out: an offline reader
                    # stays an offline one -- the Screen tab's "auto" never asks Google Lens)
                    value = "auto" if key == "ocr_engine" else "builtin"
                if value in OCR_CHOICES[key]:
                    out[key] = value
            elif key == "ocr_lang":
                if isinstance(value, str) and LANG_TAG.match(value.strip()):
                    out[key] = value.strip()
            elif key.startswith(("ocr_key_", "vision_key_")):
                try:
                    out[key] = hotkeys.normal(value) if isinstance(value, str) else None
                except hotkeys.KeyError_:
                    continue
                if out[key] is None:
                    del out[key]
            elif isinstance(default, bool):
                if isinstance(value, bool):
                    out[key] = value
            elif isinstance(default, str):
                if isinstance(value, str) and len(value) <= 2000:
                    out[key] = value.strip()
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
            data = {"settings": dict(self.settings), "games": json.loads(json.dumps(self.games))}
        try:
            self.file.parent.mkdir(parents=True, exist_ok=True)
            partial = self.file.with_suffix(".json.new")
            partial.write_text(json.dumps(data, indent=1, ensure_ascii=False), encoding="utf-8")
            partial.replace(self.file)
        except OSError as err:
            log.warning("the game text settings could not be kept (%s): %s", self.file, err)

    # ------------------------------------------------------------------ start, stop

    def start(self) -> None:
        self.find_engine()
        self._apply_mode()
        threading.Thread(target=self._ticker, name="sluka-games", daemon=True).start()

    def close(self) -> None:
        self._stop.set()
        try:
            self.detach(quiet=True)
        except Exception:
            log.exception("the game could not be let go")
        with self._lock:
            timer = self._save_timer
        if timer is not None:
            timer.cancel()
            self._save()
        self._stop_engine()
        try:
            self.screen.close()
        except Exception:
            log.exception("the screen reader could not be stopped")
        try:
            self.vision.close()
        except Exception:
            log.exception("Sluka Vision could not be stopped")
        try:
            self.cards.close()
        except Exception:
            log.exception("the games' sound could not be let go of")
        if self.clipboard is not None:
            try:
                self.clipboard.stop()
            except Exception:
                log.exception("the clipboard watch could not be stopped")
            self.clipboard = None
        with self._lock:
            waiting, self._waiting = self._waiting, []
            state = self.state()
        for _deadline, respond in waiting:
            respond(json_response(state))

    # ------------------------------------------------------------------ the log the menu shows

    def note(self, text: str, level: str = "info") -> None:
        text = str(text)[:600]
        with self._lock:
            self.log.append([round(time.time(), 3), level, text])
        (log.warning if level in ("warn", "error") else log.info)("game text: %s", text)
        self._changed()

    def _changed(self) -> None:
        with self._lock:
            self.version += 1
            self._dirty = True

    # ------------------------------------------------------------------ the engine

    def find_engine(self) -> texthook.Engine:
        engine = texthook.find_engine(self.config)
        with self._lock:
            self.engine = engine
        if not engine.ok:
            log.warning("game text: %s", engine.error)
        self._changed()
        return engine

    def _engine_runner(self) -> texthook.EngineProcess | None:
        """Sluka's engine, running (started if it is not)."""
        with self._lock:
            runner = self.runner
            if runner is not None and runner.alive:
                return runner
            engine = self.engine
        if engine is None or not engine.ok:
            engine = self.find_engine()
        if not engine.ok:
            return None
        logs = Path(getattr(self.config, "log_dir", "") or Path(self.config.data_dir) / "logs") / "hookd.log"
        runner = self._engine_factory(engine, self._engine_event, procs=self.procs, log_path=logs)
        try:
            runner.start()
        except Exception as err:
            text = f"Sluka's engine could not be started ({err})."
            if getattr(err, "winerror", 0) == 225 or "virus" in str(err).lower():
                text += " Windows Security stopped it: allow it in Protection history, or add the engine folder to its exclusions."
            with self._lock:
                self.engine_error = text
            self.note(text, "error")
            return None
        with self._lock:
            self.runner = runner
            self.engine_error = ""
        runner.settings(self.settings["flush_ms"], self.settings["codepage"])
        return runner

    def _stop_engine(self) -> None:
        with self._lock:
            runner, self.runner = self.runner, None
        if runner is not None:
            try:
                runner.stop()
            except Exception:
                log.exception("Sluka's engine could not be stopped")

    def _engine_event(self, kind: str, event: dict) -> None:
        if kind == "ready":
            self.note(f"Sluka's engine is running (LunaHook from {texthook.ENGINE_VERSION}, Python {event.get('python')}).")
        elif kind == "fatal":
            text = str(event.get("text") or "it could not start")
            with self._lock:
                self.engine_error = f"Sluka's engine could not start: {text}"
                if self.game is not None and self.game.get("state") == "attaching":
                    self.game["state"] = "failed"
                    self.game["error"] = self.engine_error
            self.note(self.engine_error, "error")
        elif kind == "inject":
            self._injected(event)
        elif kind == "connect":
            self._connected(int(event.get("pid") or 0))
        elif kind == "disconnect":
            self._disconnected(int(event.get("pid") or 0))
        elif kind == "thread":
            self._thread_made(event)
        elif kind == "gone":
            self._thread_gone(int(event.get("id") or 0))
        elif kind == "text":
            self._on_text(int(event.get("id") or 0), str(event.get("text") or ""))
        elif kind == "info":
            self._info(int(event.get("type") or 0), str(event.get("text") or ""))
        elif kind == "emu":
            self.note(f"Emulated game: {event.get('id')} {event.get('title')} {event.get('version')}".strip())
        elif kind == "note":
            text = str(event.get("text") or "")
            self.note(text, "warn" if "Error" in text or "Traceback" in text else "engine")
        elif kind == "ended":
            self._engine_ended(event.get("code"))

    def _info(self, kind: int, text: str) -> None:
        if kind == 4:  # the game's engine, as the hook found it
            with self._lock:
                if self.game is not None:
                    self.game["engine"] = text
            self.note(f"The game's engine: {text}.")
            return
        if kind == 3:
            self.note(f"Emulator found: {text}. Hook it before it loads the game, or the game's text is not found.")
            return
        for line in text.split("\n"):
            if line.strip():
                self.note(line.strip(), "warn" if kind in (1, 2) else "engine")

    def _engine_ended(self, code) -> None:
        with self._lock:
            runner = self.runner
            if runner is not None and runner.alive:
                return  # one started since has taken its place
            self.runner = None
            game = self.game
            ours = game is not None and game.get("state") in ("attaching", "attached")
        if self._stop.is_set():
            return
        self.note(f"Sluka's engine stopped (code {code}).", "warn" if ours else "info")
        if not ours:
            return
        now = time.monotonic()
        self._restarts.append(now)
        if len([t for t in self._restarts if now - t < 60]) > RESTARTS_MOST:
            with self._lock:
                if self.game is not None:
                    self.game["state"] = "failed"
                    self.game["error"] = "Sluka's engine keeps stopping on this game."
            self.note("Sluka's engine keeps stopping on this game; it is not started again. Its notes are in "
                      "data\\logs\\hookd.log. Meanwhile, LunaTranslator can read the game: Other program.", "error")
            return
        pid = game["pid"]
        # The hook in the game leaves when its host goes: a moment for it to be gone, then hooked again.
        self._later(LET_GO_SECONDS, lambda: self._reattach(pid))

    def _reattach(self, pid: int) -> None:
        with self._lock:
            game = self.game
            if game is None or game.get("pid") != pid:
                return
            self.threads.clear()
            self.selected = []
            self._loose.clear()
            self.picked = ""
            self._collector = []
            game["connected"] = set()
            pids = sorted(game["pids"])
            bits = game["bits"]
            elevate = game.get("elevated", False)
        self._changed()
        self._attach_now(pids, bits, elevate)

    # ------------------------------------------------------------------ attaching

    def attach(self, pid: int, elevate: bool = False) -> dict:
        """Hook the game ``pid`` (and the programs of its file): the menu's "Hook", the clicked window, a game hooked
        again by itself.  ``elevate``: put the hook in as administrator, for a game run as administrator.  Where it
        cannot be, why is kept for the menu to show (with "Hook as administrator" where that would do)."""
        result = self._attach(pid, elevate)
        with self._lock:
            self.last_attach = None if result.get("ok") else {**result, "pid": pid, "at": round(time.time(), 3)}
        self._changed()
        return result

    def _attach(self, pid: int, elevate: bool = False) -> dict:
        if self.settings["mode"] != "game":
            self.set_mode("game")
        # The engine's files looked at again: one an antivirus took away since is said at once, with what to do.
        engine = self.find_engine()
        if not engine.ok:
            return {"ok": False, "error": engine.error}
        if pid == self.procs.own_pid:
            return {"ok": False, "error": "That is Sluka itself."}
        path = self.procs.exe(pid)
        exe = os.path.basename(path.replace("\\", "/")) if path else ""
        if not path:
            return {"ok": False, "error": "That program is not running any more."}
        reachable, why = self.procs.can_reach(pid)
        if not reachable and not elevate:
            if why == "admin":
                error = (f"{exe} runs as administrator. Sluka can put its hook in as administrator: Windows asks you first "
                         "(or close Sluka and start it as administrator too).")
                self.note(error, "warn")
                return {"ok": False, "admin": True, "error": error}
            error = f"{exe} cannot be reached ({why})."
            self.note(error, "error")
            return {"ok": False, "error": error}
        with self._lock:
            current = self.game
            same = current is not None and current["pid"] == pid and current.get("state") in ("attaching", "attached")
        if same and not elevate:
            # Let go and hooked again at once, a game can be left half hooked: it stays as it is.
            return {"ok": True, "already": True}
        self.detach(quiet=True)
        bits = self.procs.bits(pid) or 32
        title = self.procs.title_of(pid) if hasattr(self.procs, "title_of") else ""
        pids = sorted(set(self.procs.pids_of(path)) | {pid})
        key = game_key(path, exe)
        with self._lock:
            self.game = {"pid": pid, "pids": set(pids), "connected": set(), "path": path, "exe": exe, "title": title or exe,
                         "bits": bits, "key": key, "state": "attaching", "since": time.time(), "t0": time.monotonic(),
                         "error": "", "engine": "", "elevated": bool(elevate)}
            self._last_shown = ""
            self._collector = []
            memo = self.games.setdefault(key, {})
            memo["name"] = title or exe
            memo["exe"] = exe
            memo.setdefault("auto", True)
            memo["seen"] = time.strftime("%Y-%m-%d %H:%M")
            self.threads.clear()
            self.selected = []
            self._loose.clear()
            self.picked = ""
            for watch in self._watches.values():
                watch.close()
            self._watches = {p: w for p in pids for w in [self.procs.watch(p)] if w is not None}
        self._save_soon()
        self.note(f"Hooking {exe} ({bits}-bit{', ' + str(len(pids)) + ' programs' if len(pids) > 1 else ''})"
                  f"{', as administrator' if elevate else ''}…")
        bar = getattr(self.host, "bar", None)
        if bar is not None and not bar.on:
            try:
                bar.set_on(True)
            except Exception:
                log.exception("the floating subtitles could not be turned on")
        threading.Thread(target=self._attach_now, args=(pids, bits, elevate), name="sluka-attach", daemon=True).start()
        return {"ok": True}

    def _attach_now(self, pids: list[int], bits: int, elevate: bool = False) -> None:
        wait = max((LET_GO_SECONDS - (time.monotonic() - self._let_go.get(p, -1e9)) for p in pids), default=0)
        if wait > 0:
            # Let go a moment ago: hooked again before its hook has left, a game can be left half hooked.
            time.sleep(wait)
        with self._lock:
            game = self.game
            if game is None or not set(pids) & game["pids"]:
                return
        runner = self._engine_runner()
        if runner is None:
            with self._lock:
                if self.game is game:
                    game["state"] = "failed"
                    game["error"] = self.engine_error or (self.engine.error if self.engine else "") or "Sluka's engine could not be started."
            self._changed()
            return
        runner.attach(pids, bits, elevate=elevate)
        self._changed()

    def _injected(self, event: dict) -> None:
        pid = int(event.get("pid") or 0)
        ok = bool(event.get("ok"))
        how = str(event.get("how") or "")
        with self._lock:
            game = self.game
            ours = game is not None and pid in game["pids"]
        if not ours:
            return
        if ok:
            if how == "already":
                self.note(f"Program {pid}: the hook was there already; it connects again.")
            elif how == "elevated":
                self.note(f"Program {pid}: the hook was put in as administrator.")
            else:
                self.note(f"Program {pid}: the hook was put in; waiting for it to connect.")
            return
        error = str(event.get("error") or how)
        if how == "denied":
            text = (f"The hook could not be put into {game.get('exe')} ({error}). If the game runs as administrator, use "
                    "\"Hook as administrator\".")
        elif how in ("missing", "blocked"):
            text = (f"The hook could not be put into {game.get('exe')}: {error}. Windows Security may have taken Sluka's "
                    "engine files: allow them in its Protection history, or add the engine folder to its exclusions.")
        else:
            text = f"The hook could not be put into {game.get('exe')}: {error}."
        with self._lock:
            if self.game is game and not game["connected"]:
                game["state"] = "failed"
                game["error"] = text
                game["admin"] = how in ("denied", "refused")
        self.note(text, "error")

    def _connected(self, pid: int) -> None:
        with self._lock:
            game = self.game
            if game is None or pid not in game["pids"]:
                return
            game["connected"].add(pid)
            game["state"] = "attached"
            game["error"] = ""
            memo = self.games.get(game["key"], {})
            codes = list(memo.get("codes") or [])
            pchooks = bool(memo.get("pchooks"))
            runner = self.runner
        self.note(f"{game.get('exe')} ({pid}) is connected: advance the game's text.")
        if runner is not None:
            # As LunaTranslator does as a game connects: its hook codes given, Windows' text functions hooked if asked.
            for code in codes:
                runner.hookcode(pid, code)
            if pchooks:
                runner.pchooks(pid)
        self._changed()

    def _disconnected(self, pid: int) -> None:
        with self._lock:
            game = self.game
            if game is None or pid not in game["pids"]:
                return
            game["connected"].discard(pid)
            for handle in [h for h, t in self.threads.items() if t.pid == pid]:
                del self.threads[handle]
                if handle in self.selected:
                    self.selected.remove(handle)
            # Its hook gone from every one of its programs, while it runs: not hooked any more.
            gone = not game["connected"] and game.get("state") == "attached"
            if gone:
                game["state"] = "failed"
                game["error"] = "The game's hook left it. Hook it again."
        self.note(f"{game.get('exe')} ({pid}) disconnected.", "warn" if gone else "info")
        self._changed()

    def detach(self, quiet: bool = False) -> dict:
        with self._lock:
            game, self.game = self.game, None
            if not quiet:
                self.last_attach = None
            runner = self.runner
            self.threads.clear()
            self.selected = []
            self._loose.clear()
            self.picked = ""
            self._collector = []
            watches, self._watches = self._watches, {}
        for watch in watches.values():
            watch.close()
        if game is not None:
            now = time.monotonic()
            for pid in game["pids"]:
                if runner is not None and runner.alive:
                    runner.detach(pid)
                self._let_go[pid] = now
                if not quiet:
                    # Not hooked again by itself while it runs: it was let go on purpose.
                    self._tried[pid] = float("inf")
            if not quiet:
                self.note(f"Let go of {game.get('exe') or game['pid']}.")
        self._changed()
        return {"ok": True}

    def add_code(self, code: str) -> dict:
        checked = texthook.check_hook_code(code)
        if not checked:
            return {"ok": False, "error": "That is not a hook code (they look like HS-4@1234:game.exe)."}
        with self._lock:
            game = self.game
            runner = self.runner
            connected = sorted(game["connected"]) if game else []
        if game is None or runner is None or not connected:
            return {"ok": False, "error": "Hook the game first (and wait for it to connect)."}
        for pid in connected:
            runner.hookcode(pid, checked)
        with self._lock:
            memo = self.games.setdefault(game["key"], {})
            codes = [c for c in memo.get("codes") or [] if c != checked]
            memo["codes"] = (codes + [checked])[-12:]
        self._save_soon()
        self.note(f"Hook code {checked} given to the game.")
        return {"ok": True, "code": checked}

    def pc_hooks(self, on: bool = True) -> dict:
        """Windows' own text functions hooked too (GetGlyphOutline, TextOut, DrawText ...), for a game whose engine
        LunaHook does not know: more threads to choose from.  Kept for the game."""
        with self._lock:
            game = self.game
            runner = self.runner
            connected = sorted(game["connected"]) if game else []
            if game is not None:
                self.games.setdefault(game["key"], {})["pchooks"] = bool(on)
        if game is None:
            return {"ok": False, "error": "Hook the game first."}
        self._save_soon()
        if on and runner is not None:
            for pid in connected:
                runner.pchooks(pid)
            self.note("Windows' text functions are hooked too: new threads come as the game draws text.")
        self._changed()
        return {"ok": True}

    # ------------------------------------------------------------------ what the game says

    def _thread_made(self, event: dict) -> None:
        now = time.monotonic()
        with self._lock:
            game = self.game
            if game is None or int(event.get("pid") or 0) not in game["pids"]:
                return
            handle = int(event["id"])
            if handle in self.threads:
                return
            if len(self.threads) >= THREADS_MOST:
                for old in list(self.threads):
                    if old not in self.selected:
                        del self.threads[old]
                        break
            thread = self.threads[handle] = TextThread(event, now)
            changed = self._remembered(thread)
            runner = self.runner
        if changed and runner is not None:
            for other in changed[:-1]:
                runner.sync(other, False)
            runner.sync(handle, True)
        self._changed()

    def _thread_gone(self, handle: int) -> None:
        with self._lock:
            self.threads.pop(handle, None)
            self._loose.pop(handle, None)
            if handle in self.selected:
                self.selected.remove(handle)
        self._changed()

    def _on_text(self, handle: int, raw: str) -> None:
        now = time.monotonic()
        s = self.settings
        text = textfilter.clean(raw, repeats=s["repeats"], join=s["join"], codes=s["codes"])
        route = None
        newly = None
        with self._lock:
            thread = self.threads.get(handle)
            if thread is None or self.game is None:
                return
            if self.game["state"] != "attached":
                self.game["state"] = "attached"
            thread.add(raw, text, now)
            if len(text) > MOST_SHOWN:
                pass  # (listed, not shown)
            elif handle in self.selected:
                route = (handle, text)
            else:
                picked = self._auto_pick(now)
                if picked is not None:
                    newly = picked.handle
                    route = (picked.handle, textfilter.clean(picked.raw_last, repeats=s["repeats"], join=s["join"], codes=s["codes"]))
            runner = self.runner
        if newly is not None and runner is not None:
            runner.sync(newly, True)
        if route is not None:
            self._route(*route)
        self._changed()

    def _remembered(self, thread: TextThread) -> list[int]:
        """A new thread that is one picked for this game before is picked again, in the place it had among them
        (called with the lock held).  What was given up for it, and it, are returned: [given up..., it], or [].

        As LunaTranslator does: the same hook at the same place (TextThread.matches 2) is picked again, every time it
        comes.  And where it does not come, the same hook at another place (1) stands in for it -- until it comes.
        """
        memo = self.games.get(self.game["key"], {}) if self.game else {}
        kept = memo.get("threads") or []
        if not kept or self.picked == "you":
            return []
        scores = [thread.matches(m) for m in kept]
        exact = [i for i, score in enumerate(scores) if score == 2]
        if exact:
            rank = exact[0]
        else:
            filled = set(self._loose.values())
            for handle in self.selected:
                other = self.threads.get(handle)
                if handle not in self._loose and other is not None:
                    filled |= {i for i, m in enumerate(kept) if other.matches(m) == 2}
            free = [i for i, score in enumerate(scores) if score == 1 and i not in filled]
            if not free:
                return []
            rank = free[0]
        dropped = []
        if self.picked == "auto":
            # Taken by itself, it gives way to what was picked for this game before.
            dropped, self.selected = list(self.selected), []
            self._loose.clear()
        if exact:
            for handle, at in list(self._loose.items()):
                if at in exact:
                    del self._loose[handle]
                    if handle in self.selected:
                        self.selected.remove(handle)
                        dropped.append(handle)
        else:
            self._loose[thread.handle] = rank

        def place(handle: int) -> int:
            if handle in self._loose:
                return self._loose[handle]
            other = self.threads.get(handle)
            found = [i for i, m in enumerate(kept) if other is not None and other.matches(m) == 2]
            return found[0] if found else len(kept)

        if thread.handle not in self.selected:
            at = next((i for i, h in enumerate(self.selected) if place(h) > rank), len(self.selected))
            self.selected.insert(at, thread.handle)
        self.picked = "remembered"
        return dropped + [thread.handle]

    def _auto_pick(self, now: float) -> TextThread | None:
        """The thread most like dialogue picked, where nothing is (called with the lock held); the one picked."""
        if self.selected or not self.settings["auto_pick"] or self.game is None:
            return None
        memo = self.games.get(self.game["key"], {})
        if memo.get("threads") and now - self.game.get("t0", 0.0) < 30:
            return None  # what was picked for this game before is waited for, a while
        ranked = sorted(((t.score(), t.handle) for t in self.threads.values()), key=lambda pair: -pair[0])
        if not ranked or ranked[0][0] < AUTO_PICK_SCORE:
            return None
        if len(ranked) > 1 and ranked[0][0] < 1.5 * ranked[1][0]:
            return None
        best = self.threads[ranked[0][1]]
        self.selected = [best.handle]
        self._loose.clear()
        self.picked = "auto"
        log.info("game text: picked %s (%s) as the dialogue", best.name, best.code)
        return best

    def suggested(self) -> int | None:
        with self._lock:
            ranked = sorted(((t.score(), t.handle) for t in self.threads.values()), key=lambda pair: -pair[0])
        return ranked[0][1] if ranked and ranked[0][0] >= 1.0 else None

    def select(self, handle: int, on: bool = True, only: bool = False) -> dict:
        with self._lock:
            thread = self.threads.get(handle)
            if thread is None:
                return {"ok": False, "error": "That text thread is gone."}
            before = list(self.selected)
            if only:
                self.selected = [handle] if on else []
            elif on and handle not in self.selected:
                self.selected.append(handle)
            elif not on and handle in self.selected:
                self.selected.remove(handle)
            self.picked = "you" if self.selected else ""
            self._loose.clear()
            self._collector = []
            if self.game is not None:
                memo = self.games.setdefault(self.game["key"], {})
                memo["threads"] = [self.threads[h].memo() for h in self.selected if h in self.threads]
            last = thread.raw_last if on else ""
            after = list(self.selected)
            runner = self.runner
        self._save_soon()
        if runner is not None:
            for h in before:
                if h not in after:
                    runner.sync(h, False)
            for h in after:
                if h not in before:
                    runner.sync(h, True)
        if on and last:
            self._deliver("game", self._clean(last), force=True)
        self._changed()
        return {"ok": True, "selected": after}

    def send(self, handle: int) -> dict:
        with self._lock:
            thread = self.threads.get(handle)
            raw = thread.raw_last if thread else ""
        if not raw:
            return {"ok": False, "error": "That thread has said nothing yet."}
        self._deliver("game", self._clean(raw), force=True)
        return {"ok": True}

    def forget(self) -> dict:
        with self._lock:
            game = self.game
            if game is None:
                return {"ok": False, "error": "No game is hooked."}
            self.games.pop(game["key"], None)
        self._save_soon()
        self.note(f"What was kept for {game.get('exe') or 'this game'} is forgotten.")
        return {"ok": True}

    # ------------------------------------------------------------------ into the bar

    def _clean(self, raw: str) -> str:
        s = self.settings
        return textfilter.clean(raw, repeats=s["repeats"], join=s["join"], codes=s["codes"])

    def _route(self, handle: int, text: str) -> None:
        """A picked thread's line: shown at once where one thread is picked; where more are, the lines that come
        together are gathered and shown as one, in the order the threads were picked."""
        if not text:
            return
        with self._lock:
            several = len(self.selected) > 1
            if several:
                if not self._collector:
                    self._collect_first = self.cards.clock()
                self._collector.append((handle, text))
                self._collected_at = time.monotonic()
                return
        self._deliver("game", text)

    def _flush_collector(self, now: float) -> None:
        with self._lock:
            if not self._collector or now - self._collected_at < min(TOGETHER, self.settings["flush_ms"] / 1000):
                return
            gathered, self._collector = self._collector, []
            order = {h: i for i, h in enumerate(self.selected)}
            first = getattr(self, "_collect_first", None)
        gathered.sort(key=lambda pair: order.get(pair[0], len(order)))
        text = "\n".join(t for _h, t in gathered if t)
        self._deliver("game", text, at=first)

    def _deliver(self, source: str, text: str, force: bool = False, at: float | None = None) -> None:
        """A line to show: to the bar, and to the clipboard where asked.  ``at``: when it came (ankicards.py's clock),
        where that was before now (the pieces of several threads gathered)."""
        if not text:
            return
        with self._lock:
            if not force and text == self._last_shown:
                return  # on the bar already: a game drawing its line again, a copy made twice
            self._last_shown = text
            self.last_line = {"text": text[:500], "at": time.time(), "from": source}
            copy = self.settings["copy"] and source in ("game", "screen")
        bar = getattr(self.host, "bar", None)
        if bar is not None:
            try:
                bar.inject(text)
            except Exception:
                log.exception("a line could not be shown")
            try:
                self.cards.line("bar", text, self._card_game() if source == "game" else None, at=at)
            except Exception:
                log.exception("a line could not be kept for its card")
        if copy:
            clipboard = self._clipboard()
            if clipboard is not None:
                clipboard.put(text)
        self._changed()

    # ------------------------------------------------------------------ the clipboard, another program

    def _clipboard(self):
        if self.clipboard is None:
            if self._clipboard_factory is not None:
                self.clipboard = self._clipboard_factory(self._on_clipboard, self.procs.own_pid)
            else:
                from .clipwatch import Clipboard

                self.clipboard = Clipboard(self._on_clipboard, self.procs.own_pid)
            if not self.clipboard.start():
                self.note(f"The clipboard cannot be used: {getattr(self.clipboard, 'error', '') or 'not here'}.", "error")
        return self.clipboard

    def _on_clipboard(self, text: str, mine: bool) -> None:
        s = self.settings
        if s["mode"] != "clipboard":
            return
        if mine and s["skip_own"]:
            return
        line = self._clean(text)
        if not line:
            return
        if len(line) > s["clip_most"]:
            self.note(f"Copied text of {len(line)} characters was not taken (more than {s['clip_most']}).")
            return
        if URLISH.match(line):
            return
        self._deliver("clipboard", line)

    # ------------------------------------------------------------------ modes and settings

    def set_mode(self, mode: str) -> dict:
        if mode not in MODES:
            return {"ok": False, "error": "no such mode"}
        with self._lock:
            before = self.settings["mode"]
            self.settings["mode"] = mode
        if before != mode:
            self._save_soon()
            self._apply_mode(before)
            bar = getattr(self.host, "bar", None)
            if bar is not None and mode == "vision":
                # Sluka Vision lays the words over the game itself: the floating subtitles are put away meanwhile.
                self._bar_was_on = bool(bar.on)
                if bar.on:
                    try:
                        bar.set_on(False)
                    except Exception:
                        log.exception("the floating subtitles could not be put away")
            elif bar is not None and not bar.on and (mode in ("clipboard", "screen") or (before == "vision" and self._bar_was_on)):
                try:
                    bar.set_on(True)
                except Exception:
                    log.exception("the floating subtitles could not be turned on")
            if before == "vision":
                self._bar_was_on = False
        self._changed()
        return {"ok": True, "mode": mode}

    def _apply_mode(self, before: str = "") -> None:
        mode = self.settings["mode"]
        if before == "game" and mode != "game":
            self.detach(quiet=True)
            self._stop_engine()
        if before == "screen" and mode != "screen":
            self.screen.deactivate()
        if before == "vision" and mode != "vision":
            self.vision.deactivate()
        if mode == "clipboard" or (mode in ("game", "screen") and self.settings["copy"]):
            self._clipboard()
        if mode == "game":
            self.find_engine()
        if mode == "screen":
            self.screen.activate()
        if mode == "vision":
            self.vision.activate()

    def update(self, changes: dict) -> dict:
        cleaned = self._clean_settings(changes)
        cleaned.pop("mode", None)
        with self._lock:
            before = dict(self.settings)
            self.settings.update(cleaned)
            after = dict(self.settings)
            runner = self.runner
        if after != before:
            self._save_soon()
            if after["copy"] and not before["copy"] and after["mode"] in ("game", "screen"):
                self._clipboard()
            if (after["flush_ms"], after["codepage"]) != (before["flush_ms"], before["codepage"]) and runner is not None:
                runner.settings(after["flush_ms"], after["codepage"])
            self.screen.settings_changed(before, after)
            self.vision.settings_changed(before, after)
        self._changed()
        return {"ok": True, "settings": after}

    # ------------------------------------------------------------------ the programs that could be games

    def processes(self) -> dict:
        found = winproc.candidates(self.procs)
        with self._lock:
            known = set(self.games)
            current = self.game["pids"] if self.game else set()
        for item in found:
            item["known"] = game_key(item.get("path", ""), item.get("exe", "")) in known
            item["current"] = item["pid"] in current
        found.sort(key=lambda item: (not item["current"], not item["known"]))
        return {"ok": True, "processes": found[:80], "admin": self.admin}

    def pick_window(self, seconds: float = 10.0) -> dict:
        """The next window brought to the front that is not Sluka's is hooked: the menu's "click the game"."""
        mine = {self.procs.own_pid}
        all_procs = self.procs.processes()
        changed = True
        while changed:
            changed = False
            for p in all_procs:
                if p["pid"] not in mine and p.get("parent") in mine:
                    mine.add(p["pid"])
                    changed = True
        with self._lock:
            self._mine = mine
            self.picking_until = time.monotonic() + max(2.0, min(30.0, seconds))
        if self.settings["mode"] != "game":
            self.set_mode("game")
        self._changed()
        return {"ok": True}

    def _check_picking(self, now: float) -> None:
        with self._lock:
            if not self.picking_until:
                return
            if now > self.picking_until:
                self.picking_until = 0.0
                self._changed()
                self.note("No game window was clicked.")
                return
            mine = set(self._mine)
        pid = self.procs.foreground_pid()
        if not pid or pid in mine:
            return
        path = self.procs.exe(pid)
        base = os.path.basename(path.replace("\\", "/")).lower() if path else ""
        if base in winproc.NOT_GAMES:
            return
        with self._lock:
            self.picking_until = 0.0
        self.attach(pid)

    # ------------------------------------------------------------------ in the background

    def _later(self, seconds: float, job) -> None:
        with self._lock:
            self._jobs.append((time.monotonic() + seconds, job))

    def _ticker(self) -> None:
        while not self._stop.wait(0.05):
            try:
                self._tick(time.monotonic())
            except Exception:
                log.exception("game text: a check failed")

    def _tick(self, now: float) -> None:
        self._flush_collector(now)
        with self._lock:
            due = [job for when, job in self._jobs if when <= now]
            self._jobs = [(when, job) for when, job in self._jobs if when > now]
        for job in due:
            try:
                job()
            except Exception:
                log.exception("game text: a job failed")
        if self.picking_until:
            self._check_picking(now)
        if now >= self._next_alive:
            self._next_alive = now + 1.0
            self._check_game()
            self._follow_sound()
        if now >= self._next_more:
            self._next_more = now + 3.0
            self._more_programs()
        if now >= self._next_scan:
            self._next_scan = now + 3.0
            self._auto_hook()
        try:
            self.screen.tick(now)
        except Exception:
            log.exception("game text: the screen could not be looked at")
        try:
            self.vision.tick(now)
        except Exception:
            log.exception("game text: Sluka Vision could not be looked at")
        play = self.play
        if play is not None:
            try:
                play.tick(now)
            except Exception:
                # Said once: the time played is then not looked at again until the app starts again.
                log.exception("game text: the time played could not be looked at, and is not looked at again")
                self.play = None
        self._answer(now)

    def _alive(self, pid: int) -> bool:
        watch = self._watches.get(pid)
        if watch is not None:
            return watch.alive()
        return self.procs.is_running(pid)

    def _card_game(self) -> dict | None:
        """The game hooked, as its lines' cards name it: {"pid", "pids", "title", "exe"}."""
        with self._lock:
            game = self.game
            if game is None:
                return None
            return {"pid": int(game.get("pid") or 0), "pids": sorted(int(p) for p in game.get("pids") or () if p),
                    "title": str(game.get("title") or ""), "exe": str(game.get("exe") or "")}

    def _follow_sound(self) -> None:
        """The game's sound kept, for its lines' cards, while the floating subtitles have it hooked (the Game tab), or
        Sluka Vision reads its window -- and let go of as soon as neither does (gamesound.py)."""
        with self._lock:
            game = self.game
            hooked = int(game.get("pid") or 0) if game is not None and game.get("state") == "attached" else 0
            if self.settings.get("mode") != "game":
                hooked = 0
        target = self.vision.target if self.vision._active else None
        read = int(target.get("pid") or 0) if target else 0
        try:
            self.cards.follow("bar", hooked)
            self.cards.follow("vision", read)
        except Exception:
            log.exception("a game's sound could not be followed")

    def _check_game(self) -> None:
        with self._lock:
            game = self.game
        if game is None or game.get("state") not in ("attaching", "attached", "failed"):
            return
        if (game.get("state") == "attaching" and not game.get("hinted")
                and time.monotonic() - game.get("t0", 0.0) > CONNECT_HINT_SECONDS):
            game["hinted"] = True
            self.note(f"{game.get('exe')} has not connected yet. If LunaTranslator, Textractor or another text hooker is "
                      "hooked into it, close that and hook the game again. Else Windows Security may be stopping the hook "
                      "(see its Protection history), or the game is still starting: wait, or hook it again.", "warn")
        living = {pid for pid in game["pids"] if self._alive(pid)}
        if living == game["pids"]:
            return
        with self._lock:
            if self.game is not game:
                return
            for pid in game["pids"] - living:
                watch = self._watches.pop(pid, None)
                if watch is not None:
                    watch.close()
            game["pids"] = living
            game["connected"] &= living
            for handle in [h for h, t in self.threads.items() if t.pid not in living]:
                del self.threads[handle]
                if handle in self.selected:
                    self.selected.remove(handle)
            ended = not living
            if ended:
                game["state"] = "ended"
                self.picked = ""
                self._collector = []
        if ended:
            self.note(f"{game.get('exe') or 'The game'} has closed.")
            self._tried[game["pid"]] = time.monotonic()
        self._changed()

    def _more_programs(self) -> None:
        """Programs of the hooked game's file that started since (games that draw in programs of their own start them
        a little after) are hooked too."""
        with self._lock:
            game = self.game
            if game is None or game.get("state") not in ("attaching", "attached"):
                return
            path, known, bits, elevate = game["path"], set(game["pids"]), game["bits"], game.get("elevated", False)
        fresh = [pid for pid in self.procs.pids_of(path) if pid not in known]
        if not fresh:
            return
        with self._lock:
            if self.game is not game:
                return
            game["pids"] |= set(fresh)
            for pid in fresh:
                watch = self.procs.watch(pid)
                if watch is not None:
                    self._watches[pid] = watch
            runner = self.runner
        if runner is not None:
            runner.attach(fresh, bits, elevate=elevate)
            self.note(f"{game.get('exe')} started another program ({', '.join(map(str, fresh))}): hooked too.")

    def _auto_hook(self) -> None:
        """A game hooked before, started again, is hooked by itself (where its "hook by itself" is on)."""
        if self.settings["mode"] != "game" or not self.settings["auto_hook"] or self.engine is None or not self.engine.ok:
            return
        with self._lock:
            if self.game is not None and self.game.get("state") in ("attaching", "attached"):
                return
            wanted = {}
            for key, memo in self.games.items():
                if memo.get("auto", True) and memo.get("exe") and not key.startswith("name:"):
                    wanted.setdefault(memo["exe"].lower(), set()).add(key)
        if not wanted:
            return
        now = time.monotonic()
        windowed = None
        for p in self.procs.processes():
            names = wanted.get(str(p.get("name") or "").lower())
            if not names or p["pid"] == self.procs.own_pid:
                continue
            if now - self._tried.get(p["pid"], -1e9) < 120:
                continue
            path = self.procs.exe(p["pid"])
            if game_key(path, p["name"]) not in names:
                continue
            if windowed is None:
                windowed = {w["pid"] for w in self.procs.windows()}
            same = set(self.procs.pids_of(path)) | {p["pid"]}
            if not same & windowed:
                continue  # not showing a window yet: still starting (LunaTranslator waits for the game's window too)
            main = sorted(same & windowed)[0]
            for pid in same:
                self._tried[pid] = now
            reachable, why = self.procs.can_reach(main)
            if not reachable:
                self.note(f"{p['name']} started, but {'runs as administrator' if why == 'admin' else 'cannot be reached'}: "
                          "hook it from the menu.", "warn")
                return
            self.note(f"{p['name']} started: hooking it, as before.")
            self.attach(main)
            return

    # ------------------------------------------------------------------ what the menu sees

    def state(self) -> dict:
        with self._lock:
            game = None
            if self.game:
                game = {k: v for k, v in self.game.items() if k not in ("key", "t0")}
                game["pids"] = sorted(self.game["pids"])
                game["connected"] = sorted(self.game["connected"])
                memo = self.games.get(self.game["key"], {})
                game["codes"] = list(memo.get("codes") or [])
                game["remembered"] = bool(memo.get("threads"))
                game["auto"] = bool(memo.get("auto", True))
                game["pchooks"] = bool(memo.get("pchooks"))
            threads = [t.json() for t in self.threads.values()]
            bar = getattr(self.host, "bar", None)
            engine = self.engine.describe() if self.engine else None
            if engine is not None and self.engine_error and not engine["error"]:
                engine["error"] = self.engine_error
            if engine is not None:
                engine["running"] = bool(self.runner and self.runner.alive)
            out = {
                "version": self.version,
                "mode": self.settings["mode"],
                "settings": dict(self.settings),
                "engine": engine,
                "game": game,
                "threads": threads,
                "selected": list(self.selected),
                "picked": self.picked,
                "picking": max(0.0, round(self.picking_until - time.monotonic(), 1)) if self.picking_until else 0,
                "attach": dict(self.last_attach) if self.last_attach else None,
                "clipboard": {"watching": bool(self.clipboard and getattr(self.clipboard, "watching", False)),
                              "error": getattr(self.clipboard, "error", "") if self.clipboard else ""},
                "last": dict(self.last_line),
                "log": list(self.log)[-50:],
                "bar": {"on": bool(bar and bar.on), "here": bar is not None},
                "admin": self.admin,
                "choices": {"flush": list(FLUSH_CHOICES), "codepages": list(CODEPAGES), "intervals": list(ocrtext.INTERVALS)},
                "screen": self.screen.state(),
                "vision": self.vision.state(),
            }
        out["suggested"] = self.suggested()
        return out

    def brief(self) -> dict:
        with self._lock:
            game = self.game
            return {
                "version": self.version,
                "mode": self.settings["mode"],
                "game": {"exe": game.get("exe"), "state": game.get("state")} if game else None,
                "selected": len(self.selected),
                "engine": bool(self.engine and self.engine.ok),
                "screen": self.screen.brief(),
                "vision": self.vision.brief(),
            }

    def status(self) -> dict:
        """For the app's info and the doctor."""
        with self._lock:
            return {
                "mode": self.settings["mode"],
                "engine": self.engine.describe() if self.engine else None,
                "running": bool(self.runner and self.runner.alive),
                "game": {k: self.game.get(k) for k in ("exe", "bits", "state", "engine")} if self.game else None,
                "threads": len(self.threads),
                "selected": len(self.selected),
                "screen": self.screen.status(),
                "vision": self.vision.status(),
            }

    def _answer(self, now: float) -> None:
        with self._lock:
            if not self._waiting:
                return
            due_all = self._dirty and now - self._answered >= ANSWER_EVERY
            expired = [w for w in self._waiting if w[0] <= now]
            if not due_all and not expired:
                return
            if due_all:
                waiting, self._waiting = self._waiting, []
                self._dirty = False
                self._answered = now
            else:
                waiting = expired
                self._waiting = [w for w in self._waiting if w[0] > now]
            state = self.state()
        for _deadline, respond in waiting:
            respond(json_response(state))

    # ------------------------------------------------------------------ the calls

    def api(self, name: str, req: Request, respond) -> None:
        # Only the app's own pages: no other program and no web page may hook games through the app.
        site = str(req.headers.get("sec-fetch-site", "") or "").lower()
        if req.method != "POST" or (site and site != "same-origin"):
            respond(error_response(403, "forbidden"))
            return
        try:
            args = json.loads(req.body.decode("utf-8")) if req.body else {}
        except (ValueError, UnicodeDecodeError):
            respond(error_response(400, "not JSON"))
            return
        if not isinstance(args, dict):
            respond(error_response(400, "not an object"))
            return
        if name == "state":
            if args.get("brief"):
                respond(json_response(self.brief()))
                return
            try:
                since = int(args.get("since", -1))
            except (TypeError, ValueError):
                since = -1
            with self._lock:
                if not args.get("wait") or since != self.version:
                    state = self.state()
                    if not self._waiting:
                        self._dirty = False
                else:
                    self._waiting.append((time.monotonic() + POLL_SECONDS, respond))
                    return
            respond(json_response(state))
            return

        def number(key):
            try:
                return int(args.get(key))
            except (TypeError, ValueError):
                return None

        if name == "processes":
            result = self.processes()
        elif name == "attach":
            pid = number("pid")
            result = self.attach(pid, elevate=bool(args.get("elevate"))) if pid else {"ok": False, "error": "no program"}
        elif name == "pick":
            result = self.pick_window(float(args.get("seconds") or 10))
        elif name == "cancel-pick":
            with self._lock:
                self.picking_until = 0.0
            self._changed()
            result = {"ok": True}
        elif name == "detach":
            result = self.detach()
        elif name == "select":
            handle = number("id")
            result = self.select(handle, bool(args.get("on", True)), bool(args.get("only"))) if handle is not None else {"ok": False}
        elif name == "send":
            handle = number("id")
            result = self.send(handle) if handle is not None else {"ok": False}
        elif name == "hookcode":
            result = self.add_code(str(args.get("code") or ""))
        elif name == "pchooks":
            result = self.pc_hooks(bool(args.get("on", True)))
        elif name == "mode":
            result = self.set_mode(str(args.get("mode") or ""))
        elif name == "settings":
            result = self.update(args.get("settings") if isinstance(args.get("settings"), dict) else args)
        elif name == "auto":
            result = self._set_auto(bool(args.get("on", True)))
        elif name == "rescan":
            with self._lock:
                self.engine_error = ""
            engine = self.find_engine()
            if self.settings["mode"] == "screen":
                self.screen.check()
            if self.settings["mode"] == "vision" and self.vision.runner is not None:
                self.vision.runner.engines(self.settings["ocr_lang"])
            result = {"ok": engine.ok, "engine": engine.describe()}
        elif name == "forget":
            result = self.forget()
        elif name == "ocr-engines":
            result = self.screen.check()
        elif name == "ocr-select":
            result = self.screen.select()
        elif name == "ocr-cancel":
            result = self.screen.cancel_select()
        elif name == "ocr-once":
            result = self.screen.read_now()
        elif name == "ocr-stop":
            result = self.screen.stop()
        elif name == "ocr-start":
            result = self.screen.start()
        elif name == "ocr-forget":
            result = self.screen.forget()
        elif name == "ocr-select-once":
            result = self.screen.select_once()
        elif name == "ocr-key":
            mods = [m for m in ("ctrl", "alt", "shift", "win") if args.get(m)]
            result = self.screen.set_key(str(args.get("action") or ""), args.get("vk"), mods, clear=bool(args.get("clear")))
        elif name == "ocr-keys-listen":
            result = self.screen.listen(bool(args.get("on")))
        elif name == "vision-engines":
            runner = self.vision._runner() if self.settings["mode"] == "vision" else None
            result = {"ok": bool(runner and runner.engines(self.settings["ocr_lang"]))}
        elif name == "vision-read":
            result = self.vision.read_now(front=False)
        elif name == "vision-pick":
            result = self.vision.pick()
        elif name == "vision-clear":
            result = self.vision.clear()
        elif name == "vision-forget":
            result = self.vision.forget()
        elif name == "vision-auto":
            result = self.vision.set_auto(bool(args.get("on", True)))
        elif name == "vision-key":
            mods = [m for m in ("ctrl", "alt", "shift", "win") if args.get(m)]
            result = self.vision.set_key(str(args.get("action") or ""), args.get("vk"), mods, clear=bool(args.get("clear")))
        elif name == "vision-freeze":
            result = self.vision.toggle_freeze(str(args.get("mode") or ""))
        elif name == "vision-keys-listen":
            result = self.vision.listen(bool(args.get("on")))
        else:
            respond(error_response(404, "no such game text call"))
            return
        respond(json_response(result))

    def _set_auto(self, on: bool) -> dict:
        with self._lock:
            game = self.game
            if game is None:
                return {"ok": False, "error": "No game is hooked."}
            self.games.setdefault(game["key"], {})["auto"] = on
        self._save_soon()
        self._changed()
        return {"ok": True}
