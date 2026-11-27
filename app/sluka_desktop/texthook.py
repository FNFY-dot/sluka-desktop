# SPDX-License-Identifier: LicenseRef-Sluka
# Copyright (c) 2026 Sluka. Part of Sluka Desktop; see LICENSE.txt.
"""Text out of a running game: Sluka's engine, which is LunaHook as LunaTranslator 12.1.3.12 ships it.

The engine's files come with the app, in its engine folder:

    LunaHost64.dll          the "host": it is told which game to read, and
                            hears from the game what text goes through it
    LunaHook32.dll          the "hook", put into a 32-bit game ...
    LunaHook64.dll          ... or a 64-bit one: it knows how hundreds of game
                            engines hold their text, and catches each line
    LunaSubprocess32.exe    LunaTranslator's helpers that put the hook into a
    LunaSubprocess64.exe    game of their own kind ("dllinject")
    msvcp140.dll, vcruntime140.dll, vcruntime140_1.dll
                            the C++ runtime the host was built with

The host runs in a program of the app's own, hookd.py, under the app's own
Python: whatever happens in a game's hook, the app is not taken down with it,
and a helper that ends is started again.  EngineProcess here starts it and
speaks with it (lines of JSON); gametext.py decides what is hooked and where
the lines go.
"""

from __future__ import annotations

import json
import logging
import queue
import struct
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

log = logging.getLogger("sluka.games")

WINDOWS = sys.platform == "win32"
CREATE_NO_WINDOW = 0x08000000
HOOKD = Path(__file__).with_name("hookd.py")

#: The engine's files, and what each is for (said when one is missing).
ENGINE_FILES = {
    "LunaHost64.dll": "the host",
    "LunaHook32.dll": "the hook for 32-bit games",
    "LunaHook64.dll": "the hook for 64-bit games",
    "LunaSubprocess32.exe": "what puts the hook into 32-bit games",
    "LunaSubprocess64.exe": "what puts the hook into 64-bit games",
    "msvcp140.dll": "the C++ runtime",
    "vcruntime140.dll": "the C++ runtime",
    "vcruntime140_1.dll": "the C++ runtime",
}
#: Where the engine comes from.
ENGINE_VERSION = "LunaTranslator 12.1.3.12"
ENGINE_SOURCE = "https://github.com/HIllya51/LunaTranslator/tree/v12.1.3.12"


def check_hook_code(code: str) -> str:
    """A hook code as the hook is to be given it, or '' where it is not one.

    LunaHook reads H-codes ("HS-4@1234:game.exe", and B-, LH-, LB-codes like them), R-codes and E-codes
    (hookcode.cpp), and says so when one is wrong ("That hook code is not valid"); here only what cannot be a code
    at all is turned away: nothing, a line break, a page of text, another first letter, no "@" for the address.
    """
    code = str(code or "").strip()
    if code.startswith("/"):  # (as AGTH wrote them: /HS-4@1234)
        code = code[1:].strip()
    if not code or len(code) > 500 or "\n" in code or "\r" in code or "@" not in code:
        return ""
    if code[0].upper() not in "HBLRE":
        return ""
    # What comes before the address is LunaHook's letters and numbers, upper case; what comes after (a module's or a
    # function's name) is left as it is.
    kind, at, rest = code.partition("@")
    return kind.upper() + at + rest


# ------------------------------------------------------------------------------------------- the engine on disk


@dataclass
class Engine:
    folder: Path
    missing: list = field(default_factory=list)
    error: str = ""

    @property
    def ok(self) -> bool:
        return not self.error

    def describe(self) -> dict:
        return {
            "name": "LunaHook",
            "version": ENGINE_VERSION,
            "folder": str(self.folder),
            "source": ENGINE_SOURCE,
            "missing": list(self.missing),
            "error": self.error,
            "kinds": [32, 64],
        }


def engine_dir(config) -> Path:
    folder = getattr(config, "engine_dir", None)
    if folder:
        return Path(folder)
    return Path(getattr(config, "root", ".")) / "engine"


def find_engine(config) -> Engine:
    """The engine that came with the app, and what keeps it from working, if anything does."""
    folder = engine_dir(config)
    engine = Engine(folder)
    if not folder.is_dir():
        engine.missing = list(ENGINE_FILES)
        engine.error = (f"Sluka's engine folder is missing ({folder}). Unpack Sluka Desktop's zip again: the engine "
                        "folder is in it.")
        return engine
    engine.missing = [name for name in ENGINE_FILES if not (folder / name).is_file()]
    if engine.missing:
        engine.error = (f"Some of the engine's files are missing from {folder}: {', '.join(engine.missing)}. An antivirus "
                        "(Windows Security) may have taken them away, as text hookers reach into games: allow them in "
                        "its Protection history, or add the engine folder to its exclusions, then unpack Sluka Desktop's "
                        "zip again.")
    elif WINDOWS and struct.calcsize("P") != 8:
        engine.error = ("Sluka's engine needs a 64-bit Python, and this one is 32-bit. Install the 64-bit Python from "
                        "https://www.python.org/downloads/windows/ .")
    return engine


# ------------------------------------------------------------------------------------------- the engine, running


def helper_python() -> str:
    """The Python to run hookd.py with: the app's own (with a console of its own kind, for its pipes)."""
    exe = sys.executable or "python"
    if WINDOWS:
        path = Path(exe)
        if path.name.lower() == "pythonw.exe" and path.with_name("python.exe").is_file():
            return str(path.with_name("python.exe"))
    return exe


class EngineProcess:
    """hookd.py, running: commands to it, and what it says passed on as ``events(kind, event)`` -- "ready",
    "fatal", "inject", "connect", "disconnect", "thread", "gone", "text", "info", "hook", "emu", and also "note"
    (anything it wrote that was not an event) and "ended" (it is gone)."""

    #: The program run: hookd.py (the screen reader's process runs ocrd.py the same way: ocrtext.OcrProcess).
    script = HOOKD
    #: More for hookd.py's command line (the tests' stand-ins for the engine's library and injector).
    extra_args: list = []

    def __init__(self, engine: Engine, events, procs=None, popen=None, log_path=None, python=None, extra_args=None):
        self.engine = engine
        self.events = events
        self.procs = procs
        self._popen = popen or subprocess.Popen
        self.log_path = Path(log_path) if log_path else None
        self.python = python or helper_python()
        self.args = list(self.extra_args if extra_args is None else extra_args)
        self.proc = None
        self.ready = threading.Event()
        self.about: dict = {}
        self.started = 0.0
        self._ended = False
        #: What is to be said to it, written by a thread of its own: whoever says something never waits on the engine
        #: (the thread that reads what it says least of all, or the two could wait on each other).
        self._outbox: queue.Queue = queue.Queue()
        self._writer: threading.Thread | None = None

    def start(self) -> None:
        command = [self.python, "-I", "-X", "utf8", str(self.script), str(self.engine.folder)]
        if self.log_path is not None:
            _trim(self.log_path)
            command += ["--log", str(self.log_path)]
        command += self.args
        self.proc = self._popen(command, cwd=str(self.engine.folder), stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, creationflags=CREATE_NO_WINDOW if WINDOWS else 0, bufsize=0)
        self.started = time.monotonic()
        if self.procs is not None:
            handle = getattr(self.proc, "_handle", None)
            if handle is not None:
                self.procs.bind(handle)
        threading.Thread(target=self._read, name="sluka-engine-out", daemon=True).start()
        threading.Thread(target=self._read_errors, name="sluka-engine-err", daemon=True).start()
        self._writer = threading.Thread(target=self._write, name="sluka-engine-in", daemon=True)
        self._writer.start()
        log.info("Sluka's engine started (pid %s): %s", getattr(self.proc, "pid", "?"), " ".join(command[3:5]))

    @property
    def alive(self) -> bool:
        return self.proc is not None and not self._ended and self.proc.poll() is None

    def _tell(self, kind: str, event: dict) -> None:
        try:
            self.events(kind, event)
        except Exception:
            log.exception("what Sluka's engine said (%s) could not be handled", kind)

    def _read(self) -> None:
        stream = self.proc.stdout
        try:
            for raw in iter(stream.readline, b""):
                line = raw.decode("utf-8", "replace").strip()
                if not line:
                    continue
                try:
                    event = json.loads(line)
                except ValueError:
                    self._tell("note", {"text": line})
                    continue
                if not isinstance(event, dict) or not isinstance(event.get("ev"), str):
                    continue
                if event["ev"] == "ready":
                    self.about = event
                    self.ready.set()
                self._tell(event["ev"], event)
        except (OSError, ValueError):
            pass
        code = None
        try:
            code = self.proc.wait(timeout=5)
        except Exception:
            pass
        self._ended = True
        self.ready.set()
        self._tell("ended", {"code": code})

    def _read_errors(self) -> None:
        try:
            for raw in iter(self.proc.stderr.readline, b""):
                line = raw.decode("utf-8", "replace").rstrip()
                if line.strip():
                    self._tell("note", {"text": line})
        except (OSError, ValueError):
            pass

    def _write(self) -> None:
        while True:
            data = self._outbox.get()
            if data is None:
                return
            try:
                self.proc.stdin.write(data)
                self.proc.stdin.flush()
            except (OSError, ValueError) as err:
                log.warning("Sluka's engine could not be told something: %s", err)
                return

    def send(self, command: dict) -> bool:
        if not self.alive:
            return False
        self._outbox.put((json.dumps(command, ensure_ascii=False) + "\n").encode("utf-8"))
        return True

    def attach(self, pids, bits: int, elevate: bool = False) -> bool:
        """The game's programs (one, or all of the same file), hooked together as LunaTranslator hooks them."""
        pids = [int(p) for p in (pids if isinstance(pids, (list, tuple, set)) else [pids])]
        return self.send({"cmd": "attach", "pids": sorted(pids), "bits": int(bits), "elevate": bool(elevate)})

    def detach(self, pid: int) -> bool:
        return self.send({"cmd": "detach", "pid": int(pid)})

    def hookcode(self, pid: int, code: str) -> bool:
        return self.send({"cmd": "hookcode", "pid": int(pid), "code": code})

    def pchooks(self, pid: int) -> bool:
        return self.send({"cmd": "pchooks", "pid": int(pid)})

    def settings(self, flush: int, codepage: int) -> bool:
        return self.send({"cmd": "settings", "flush": int(flush), "codepage": int(codepage)})

    def sync(self, ident: int, on: bool) -> bool:
        return self.send({"cmd": "sync", "id": int(ident), "on": bool(on)})

    def stop(self, wait: float = 1.5) -> None:
        proc = self.proc
        if proc is None:
            return
        # It lets go of every game it hooked (their hooks leave them), and ends.
        self.send({"cmd": "quit"})
        self._outbox.put(None)
        if self._writer is not None:
            self._writer.join(timeout=wait)
        try:
            if proc.stdin:
                proc.stdin.close()
        except OSError:
            pass
        try:
            proc.wait(timeout=wait)
        except Exception:
            try:
                proc.kill()
            except OSError:
                pass


def try_engine(engine: Engine, log_path=None, wait: float = 15.0) -> tuple[bool, str]:
    """Sluka's engine started, and stopped again: whether it runs here, and what it said (for the doctor)."""
    events: queue.Queue = queue.Queue()
    runner = EngineProcess(engine, lambda kind, event: events.put((kind, event)), log_path=log_path)
    try:
        runner.start()
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
                return True, f"Python {event.get('python')}, {event.get('bits')}-bit"
            if kind == "fatal":
                return False, str(event.get("text") or "it could not start")
            if kind == "note":
                notes.append(str(event.get("text") or ""))
            elif kind == "ended":
                return False, "it ended at once" + (": " + " / ".join(notes[-3:]) if notes else "")
        return False, f"it said nothing in {wait:.0f} s"
    finally:
        runner.stop()


def _trim(path: Path, most: int = 2 * 1024 * 1024) -> None:
    """The engine's log kept small: past its size, the old one is moved aside."""
    try:
        if path.is_file() and path.stat().st_size > most:
            old = path.with_suffix(path.suffix + ".1")
            if old.exists():
                old.unlink()
            path.rename(old)
    except OSError:
        pass


# ------------------------------------------------------------------------------------------- sluka hook-check


def command_check(config, pid: int = 0, seconds: int = 40, show_list: bool = False, elevate: bool = False, out=None) -> int:
    """``sluka hook-check [PID]``: Sluka's engine tried step by step, each step said as it is reached; with a game's
    PID, what the game's text threads say for a while, as the engine hears it."""
    out = out or sys.stdout

    def say(text: str) -> None:
        try:
            print(text, file=out, flush=True)
        except (OSError, ValueError):
            pass

    if not WINDOWS:
        say("sluka: game text is for Windows.")
        return 2
    from .winproc import Procs, candidates

    procs = Procs()
    if show_list:
        for p in candidates(procs):
            say(f"{p['pid']:>7}  {str(p['bits'] or '?'):>2}-bit  {p['exe']}  {p['title']}")
        if not pid:
            return 0
    engine = find_engine(config)
    if not engine.ok:
        say(f"failed: {engine.error}")
        return 3
    say(f"ok: Sluka's engine (LunaHook from {ENGINE_VERSION}) in {engine.folder}")
    bits = 0
    if pid:
        path = procs.exe(pid)
        if not path:
            say(f"failed: there is no program {pid} running")
            return 4
        reachable, why = procs.can_reach(pid)
        if not reachable and not elevate:
            say(f"failed: program {pid} cannot be reached: "
                f"{'it runs as administrator; add --admin to put the hook in as administrator' if why == 'admin' else why}")
            return 4
        bits = procs.bits(pid) or 32
        say(f"ok: program {pid} is {path} ({bits}-bit)")
    events: queue.Queue = queue.Queue()
    engine_dir_ = engine.folder
    logs = Path(getattr(config, "log_dir", engine_dir_)) / "hookd-check.log"
    runner = EngineProcess(engine, lambda kind, event: events.put((kind, event)), procs=procs, log_path=logs)
    try:
        runner.start()
    except OSError as err:
        say(f"failed: the engine's program could not be started: {err}")
        return 5
    names: dict[int, str] = {}

    def drain(until: float) -> bool:
        while time.monotonic() < until:
            try:
                kind, event = events.get(timeout=0.2)
            except queue.Empty:
                continue
            if kind == "ready":
                say(f"ok: the engine is running (Python {event.get('python')}, {event.get('bits')}-bit)")
            elif kind == "fatal":
                say(f"failed: {event.get('text')}")
                return False
            elif kind == "note":
                say(f"engine: {event.get('text')}")
            elif kind == "inject":
                ok = event.get("ok")
                say(f"{'ok' if ok else 'failed'}: the hook {'is in' if ok else 'could not be put in'} program {event.get('pid')}"
                    f" ({event.get('how')}{': ' + event['error'] if event.get('error') else ''})")
            elif kind == "connect":
                say(f"ok: program {event.get('pid')} is connected; advance the game's text")
            elif kind == "disconnect":
                say(f"note: program {event.get('pid')} disconnected")
            elif kind == "thread":
                names[event["id"]] = f"{event.get('name')}  {event.get('code')}"
                say(f"thread {event['id']}: {names[event['id']]}")
            elif kind == "text":
                text = str(event.get("text", "")).replace("\n", "⏎")
                say(f"[{event.get('id')}] {text[:300]}")
            elif kind == "info":
                say(f"hook: {event.get('text')}")
            elif kind == "ended":
                say(f"note: the engine's program ended (code {event.get('code')})")
                return False
        return True

    if not runner.ready.wait(15):
        say("note: the engine has said nothing in 15 s")
    alive = drain(time.monotonic() + 0.5)
    if not pid:
        runner.stop()
        say("ok: the engine starts. Give a game's PID to read its text:  sluka hook-check PID  (--list shows them)")
        return 0 if alive else 5
    if alive:
        same = sorted(set(procs.pids_of(procs.exe(pid))) | {pid})
        runner.attach(same, bits, elevate=elevate)
        say(f"Hooking {', '.join(map(str, same))}; play the game (advance its text) for {seconds} s…")
        alive = drain(time.monotonic() + max(5, seconds))
    if alive:
        runner.detach(pid)
        drain(time.monotonic() + 1.0)
    runner.stop()
    say(f"(the engine's own notes: {logs})")
    return 0
