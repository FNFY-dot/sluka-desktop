# SPDX-License-Identifier: LicenseRef-Sluka
# Copyright (c) 2026 Sluka. Part of Sluka Desktop; see LICENSE.txt.
"""Between mpv and Sluka: a relay, and nothing more.

The mpv script (``mpv/sluka.lua``) draws the subtitles and asks questions:
which words are in this line, what does this one mean, file this one as known.
The answers come from Sluka's own code, running in the app's hidden page
(``web/mpv-engine.js``).  This module carries the questions one way and the
answers the other:

    mpv  <-- JSON IPC over a Unix socket -->  this  <-- the app's own channel -->  engine

The script opens mpv's IPC socket in a folder only the user can read
(``$XDG_RUNTIME_DIR/sluka-mpv``); this module watches that folder and connects
to every player that turns up.  No network socket is involved anywhere.

On Windows mpv's IPC is a named pipe (``\\\\.\\pipe\\sluka-mpv-<number>``), which
the script opens the same way and names in a small file in
``%LOCALAPPDATA%\\sluka-desktop\\mpv``; the pipes themselves are looked for too.
A pipe opened the plain way cannot be read and written at once, so each player
is given two connections: one only listened on, one only spoken on (``Player``).

A player that runs as a Flatpak -- Celluloid in Tails 7.10 and later -- sees
neither that folder nor the app folder.  Its script puts the socket in the one
folder such a player shares with the rest of the system,
``$XDG_RUNTIME_DIR/app/<its name>``, and this module looks there too, for the
players named in ``FLATPAK_PLAYERS`` and no others.
"""

from __future__ import annotations

import collections
import json
import logging
import os
import re
import shutil
import socket
import subprocess
import tempfile
import threading
import time
from pathlib import Path

from . import __version__
from .config import WINDOWS, Config, store_python
from .host import Request, Response, error_response, json_response

log = logging.getLogger("sluka.mpv")

#: How often the socket folder is looked at for players that came or went.
WATCH_SECONDS = 0.6
#: How long the engine's request for news is held open when there is none.
POLL_SECONDS = 25
#: Most questions kept for an engine that is not asking (it is still starting).
QUEUE_MOST = 400
#: A message mpv sends in one line; subtitles are short, so this is generous.
LINE_MOST = 4 * 1024 * 1024
#: The players that have mpv in them, by the name of their process.
PLAYER_PROCESSES = {"mpv": "mpv", "celluloid": "Celluloid", "gnome-mpv": "Celluloid"}
#: How long a player may run before its script is expected to have turned up.
STRAY_AFTER = 8.0
#: The script's own notes, beside its socket (see mpv/sluka.lua).
NOTE_FILES = ("script.log", "sluka-script.log")

#: Players that may run as Flatpaks, and where each looks for scripts, under ``~/.var/app/<name>/``.
FLATPAK_PLAYERS = {
    "io.github.celluloid_player.Celluloid": "config/celluloid/scripts",
    "io.mpv.Mpv": "config/mpv/scripts",
}


#: Where Windows keeps its named pipes, and how this app's script names the one it opens (mpv/sluka.lua).
PIPE_PREFIX = "\\\\.\\pipe\\"
PIPE_NAME = "sluka-mpv-"


def runtime_dir() -> Path:
    if WINDOWS:
        from .config import local_dir

        return local_dir()
    return Path(os.environ.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}")


def is_pipe(path: str) -> bool:
    return str(path).startswith(PIPE_PREFIX)


def open_pipe(path: str):
    """One connection to a named pipe, as a plain unbuffered file.  (A function of its own so that a test can stand in for Windows.)"""
    return open(path, "r+b", buffering=0)


def pipe_names() -> list[str]:
    """The names of the pipes there are on this computer."""
    try:
        return os.listdir(PIPE_PREFIX + "\\")
    except OSError:
        return []


def connect_pipe(path: str, tries: int = 12):
    """mpv makes the next place at its pipe a moment after the last was taken; so, asked again shortly."""
    last: OSError | None = None
    for attempt in range(tries):
        try:
            return open_pipe(path)
        except FileNotFoundError:
            raise
        except OSError as err:
            last = err
            time.sleep(0.05 + 0.03 * attempt)
    raise last or OSError("the pipe could not be opened")


def _close_aside(handle) -> None:
    """Close a pipe without waiting for it: Windows may hold a close back while another thread still reads there."""
    def close():
        try:
            if WINDOWS:
                import ctypes
                import msvcrt

                # Lets go of a read another thread is waiting in, which nothing else on Windows does.
                ctypes.windll.kernel32.CancelIoEx(ctypes.c_void_p(msvcrt.get_osfhandle(handle.fileno())), None)
        except Exception:
            pass
        try:
            handle.close()
        except Exception:
            pass

    threading.Thread(target=close, name="sluka-mpv-close", daemon=True).start()


def flatpak_installed(app: str) -> bool:
    """Whether the Flatpak ``app`` is on this computer: by the folders Flatpak keeps, or by its menu entry."""
    home = Path.home()
    if any((base / app).exists() for base in (Path("/var/lib/flatpak/app"), home / ".local/share/flatpak/app", home / ".var/app")):
        return True
    # A system may keep its Flatpaks elsewhere; the menu entry of one still starts it with "flatpak run".
    folders = [os.environ.get("XDG_DATA_HOME") or str(home / ".local/share")]
    folders += [d for d in (os.environ.get("XDG_DATA_DIRS") or "/usr/local/share:/usr/share").split(":") if d]
    folders += ["/var/lib/flatpak/exports/share", str(home / ".local/share/flatpak/exports/share")]
    for folder in folders:
        try:
            with open(Path(folder) / "applications" / f"{app}.desktop", encoding="utf-8", errors="replace") as handle:
                entry = handle.read(16000)
        except OSError:
            continue
        if re.search(r"(?m)^Exec=.*\bflatpak\b", entry):
            return True
    return False


def flatpak_players() -> list[str]:
    return [app for app in FLATPAK_PLAYERS if flatpak_installed(app)]


def _player_processes() -> dict[int, str]:
    """The players running now as this user: process number -> name."""
    found = {}
    me = os.getuid()
    try:
        entries = os.listdir("/proc")
    except OSError:
        return found
    for entry in entries:
        if not entry.isdigit():
            continue
        try:
            if os.stat(f"/proc/{entry}").st_uid != me:
                continue
            with open(f"/proc/{entry}/comm", encoding="utf-8", errors="replace") as handle:
                name = handle.read().strip()
        except OSError:
            continue
        if name in PLAYER_PROCESSES:
            found[int(entry)] = name
    return found


def _in_place(path: Path) -> bool:
    return path.is_file() or path.is_symlink()


def _process_start(pid: int) -> float:
    """When process ``pid`` was started, as a time of day; 0 when that cannot be told."""
    try:
        stat = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8", errors="replace")
        ticks = float(stat.rsplit(")", 1)[1].split()[19])
        uptime = float(Path("/proc/uptime").read_text().split()[0])
        return time.time() - (uptime - ticks / os.sysconf("SC_CLK_TCK"))
    except (OSError, ValueError, IndexError):
        return 0.0


VIDEO_SUFFIXES = {".mkv", ".mp4", ".webm", ".avi", ".mov", ".m4v", ".ts", ".ogv", ".flv", ".wmv", ".mpg", ".mpeg"}
SUBTITLE_SUFFIXES = {".srt", ".ass", ".ssa", ".vtt", ".sub"}


class Player:
    """One mpv, through its IPC socket.

    On Windows through its pipe, twice.  A pipe opened as a plain file lets
    only one thing happen on it at a time: a wait for mpv's next word would hold
    up everything said to mpv.  So one connection is only listened on -- mpv
    sends every client what its scripts say -- and the other only spoken on,
    with mpv told to send it no events: there each command is answered by one
    line, which is read before the next command is written.
    """

    def __init__(self, bridge: "MpvBridge", key: str, path: str):
        self.bridge = bridge
        self.key = key
        self.path = path
        self.sock = None
        self.ear = self.mouth = None
        self.alive = True
        self.said_hello = False
        #: The player's process, as its script said (hello).
        self.pid = 0
        #: The file it played when a word was last picked in it for Anki: read for the card's clip (``mpv/file``).
        self.media = ""
        self._write_lock = threading.Lock()
        self._serial = 0
        self._spoken = b""
        if is_pipe(path):
            self.ear = connect_pipe(path)
            try:
                self.mouth = connect_pipe(path)
                self._command(["disable_event", "all"])
            except OSError:
                for handle in (self.ear, self.mouth):
                    if handle is not None:
                        _close_aside(handle)
                raise
        else:
            self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            self.sock.settimeout(3)
            self.sock.connect(path)
            self.sock.settimeout(None)
        self.thread = threading.Thread(target=self._read, name=f"sluka-mpv-{key}", daemon=True)
        self.thread.start()

    def _command(self, command: list) -> None:
        """One command on the speaking connection, and mpv's one line in answer to it."""
        self._serial += 1
        number = self._serial
        rest = memoryview((json.dumps({"command": command, "request_id": number}) + "\n").encode("utf-8"))
        while rest:
            # A plain file's write says how much it took, which need not be all of it.
            took = self.mouth.write(rest)
            if not took:
                raise OSError("mpv's pipe takes no more")
            rest = rest[took:]
        while True:
            while b"\n" not in self._spoken:
                chunk = self.mouth.read(65536)
                if not chunk:
                    raise OSError("mpv closed its pipe")
                self._spoken += chunk
                if len(self._spoken) > LINE_MOST:
                    raise OSError("mpv's answer has no end")
            line, self._spoken = self._spoken.split(b"\n", 1)
            try:
                answer = json.loads(line.decode("utf-8", "replace"))
            except ValueError:
                continue
            # Anything else on this connection is an event from before mpv was told to send none.
            if isinstance(answer, dict) and answer.get("request_id") == number:
                return

    def send(self, message: dict) -> bool:
        """``message`` to the script, as a script-message every mpv client hears."""
        command = ["script-message", "sluka-app", json.dumps(message, ensure_ascii=False)]
        try:
            with self._write_lock:
                if self.mouth is not None:
                    self._command(command)
                else:
                    self.sock.sendall((json.dumps({"command": command}) + "\n").encode("utf-8"))
            return True
        except (OSError, ValueError):
            self.close()
            return False

    def _read(self) -> None:
        buffer = b""
        try:
            while self.alive:
                chunk = self.ear.read(65536) if self.ear is not None else self.sock.recv(65536)
                if not chunk:
                    break
                buffer += chunk
                if len(buffer) > LINE_MOST and b"\n" not in buffer:
                    buffer = b""
                    continue
                while b"\n" in buffer:
                    line, buffer = buffer.split(b"\n", 1)
                    self._line(line)
        except OSError:
            pass
        finally:
            self.close()

    def _line(self, line: bytes) -> None:
        if not line.strip():
            return
        try:
            event = json.loads(line.decode("utf-8", "replace"))
        except ValueError:
            return
        if not isinstance(event, dict) or event.get("event") != "client-message":
            return
        args = event.get("args")
        if not isinstance(args, list) or len(args) < 2 or args[0] != "sluka-mpv":
            return
        try:
            message = json.loads(args[1])
        except (ValueError, TypeError):
            return
        if isinstance(message, dict) and isinstance(message.get("t"), str):
            if message["t"] == "hello":
                self.said_hello = True
                try:
                    self.pid = int(message.get("pid") or 0)
                except (TypeError, ValueError):
                    self.pid = 0
            self.bridge.incoming(self, message)

    def close(self) -> None:
        if not self.alive:
            return
        self.alive = False
        for handle in (self.ear, self.mouth):
            if handle is not None:
                _close_aside(handle)
        try:
            if self.sock is not None:
                self.sock.close()
        except OSError:
            pass
        self.bridge.player_gone(self)


class MpvBridge:
    def __init__(self, config: Config, players: bool = True):
        self.config = config
        #: Whether mpv players are looked for: without ([mpv] enabled = no), Sluka's engine answers the floating
        #: subtitles alone (bar.py), which are a player to it as well.
        self.watch_players = players
        self.folder = Path(config.mpv_socket_dir)
        self.script = config.mpv_dir / "sluka.lua"
        self.players: dict[str, Player] = {}
        self._lock = threading.RLock()
        self._queue: collections.deque = collections.deque(maxlen=QUEUE_MOST)
        self._waiting: list[tuple[float, callable]] = []
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._failed: dict[str, float] = {}
        #: When Sluka's own code (the engine, in the app's hidden page) last asked for news.
        self._last_poll = 0.0
        self._engine_seen = False
        self._started = time.time()
        #: How far each of the script's note files has been read.
        self._notes_read: dict[str, int] = {}
        #: Player processes seen running: when first seen, and whether they were spoken of.
        self._strays: dict[int, dict] = {}
        self._rounds = 0

    # ------------------------------------------------------------ life

    def start(self) -> None:
        if self._thread:
            return
        if not self.watch_players:
            # The engine's questions are still answered, and its waits ended in time.
            self._thread = threading.Thread(target=self._watch, name="sluka-mpv-watch", daemon=True)
            self._thread.start()
            log.info("Sluka's engine is there for the floating subtitles; mpv is off ([mpv] enabled = no)")
            return
        try:
            # (Not by a Python from the Microsoft Store: the folder it made would be a private one, hiding from
            # the app the real one, which the script in the player makes and writes into.)
            if not store_python():
                self.folder.mkdir(parents=True, exist_ok=True)
                os.chmod(self.folder, 0o700)
        except OSError as err:
            log.warning("the folder for mpv's sockets could not be made (%s): %s", self.folder, err)
        # Of what players noted before this start, only the last few lines are
        # passed on: a player opened first is still waiting, and says so there.
        for path in self._note_files():
            try:
                with open(path, "rb") as handle:
                    size = handle.seek(0, os.SEEK_END)
                    start = max(0, size - 1200)
                    handle.seek(start)
                    tail = handle.read()
                # From the start of a line, not the middle of one.
                self._notes_read[str(path)] = start + (tail.find(b"\n") + 1 if start else 0)
            except OSError:
                pass
        self._thread = threading.Thread(target=self._watch, name="sluka-mpv-watch", daemon=True)
        self._thread.start()
        log.info("watching %s for mpv players", self.folder)
        if WINDOWS:
            log.info("and the pipes named %s%s<number>", PIPE_PREFIX, PIPE_NAME)
        for who, folder, own in self.places()[1:]:
            if own and folder.parent.is_dir():
                log.info("and %s, for %s as a Flatpak", folder, who)

    def close(self) -> None:
        self._stop.set()
        with self._lock:
            players = list(self.players.values())
            waiting, self._waiting = self._waiting, []
        for player in players:
            player.send({"t": "bye"})
            player.close()
        for _deadline, respond in waiting:
            respond(json_response({"msgs": []}))

    def add_player(self, player) -> None:
        """One more player that is no mpv (the floating bar, bar.py): it says and is told what a script is."""
        with self._lock:
            old = self.players.get(player.key)
            self.players[player.key] = player
        if old is not None and old is not player:
            old.close()

    def status(self) -> dict:
        with self._lock:
            mpvs = {key: player for key, player in self.players.items() if isinstance(player, Player)}
            return {
                "players": len(mpvs),
                "names": sorted(mpvs),
                # The players whose script has said hello: connected to is not yet talking to.
                "answered": sorted(key for key, player in mpvs.items() if player.said_hello),
                "folder": str(self.folder),
                "script": str(self.script),
                "engineWaiting": bool(self._waiting),
                "engine": self.engine_alive(),
            }

    # ------------------------------------------------------------ players

    def _watch(self) -> None:
        while not self._stop.wait(WATCH_SECONDS):
            self._rounds += 1
            if self.watch_players:
                try:
                    self._look()
                    self._pass_on_notes()
                    if self._rounds % 5 == 0:
                        self._notice_strays()
                except Exception:
                    log.exception("while looking for mpv players")
            self._expire()

    # ------------------------------------------------------------ what went wrong, in the app's log

    def _note_files(self) -> list[Path]:
        return [folder / name for _who, folder, _own in self.places() for name in NOTE_FILES]

    def _pass_on_notes(self) -> None:
        """The script's own notes, into the app's log: a player opened from the desktop has nowhere else to say them."""
        for path in self._note_files():
            key = str(path)
            try:
                size = path.stat().st_size
            except OSError:
                continue
            done = self._notes_read.get(key, 0)
            if size < done:
                done = 0  # a new file under the old name
            if size == done:
                continue
            try:
                with open(path, "rb") as handle:
                    handle.seek(done)
                    fresh = handle.read(64 * 1024)
            except OSError:
                continue
            # Only whole lines; the rest is read once it has been finished.
            cut = fresh.rfind(b"\n")
            if cut < 0:
                continue
            self._notes_read[key] = done + cut + 1
            for line in fresh[:cut].decode("utf-8", "replace").splitlines()[-60:]:
                if line.strip():
                    log.info("mpv script: %s", line.strip()[:400])

    def _notice_strays(self) -> None:
        """Say so, once, when a player is running and its script has not turned up."""
        if WINDOWS:
            return  # which programs are running is not read there; the script's own notes say what it met
        now = time.time()
        running = _player_processes()
        for pid in [p for p in self._strays if p not in running]:
            del self._strays[pid]
        with self._lock:
            connected = set(self.players)
        for pid, name in running.items():
            seen = self._strays.setdefault(pid, {"since": now, "told": False})
            if seen["told"]:
                continue
            if str(pid) in connected:
                seen["told"] = True
                continue
            if now - seen["since"] < STRAY_AFTER:
                continue
            # A player in a sandbox numbers itself; it is known by whose it is.
            here = str(pid) in connected or any(key.startswith(f"{name}:") for key in connected)
            if here:
                # Sluka has been in this one: its going quiet later is the player closing, not a fault.
                seen["told"] = True
                continue
            seen["told"] = True
            where = self._script_place(name)
            if not _in_place(where) and self.config.mpv_attach:
                # A player met for the first time (a Flatpak makes its own folder when it first runs).
                try:
                    from .install import hook_players

                    hook_players(self.config, quiet=True)
                except Exception:
                    log.exception("could not put the mpv script in place")
                if _in_place(where):
                    log.warning("%s is running (process %d) and had no script of Sluka's; it is in place now (%s): "
                                "close the video and open it again", PLAYER_PROCESSES[name], pid, where)
                    continue
            log.warning("%s is running (process %d), but Sluka's script in it has not turned up: %s",
                        PLAYER_PROCESSES[name], pid, self._why_not(pid, name))

    def _script_place(self, name: str) -> Path:
        """Where the player whose process is called ``name`` looks for Sluka's script."""
        home = Path.home()
        for app, folder in FLATPAK_PLAYERS.items():
            if app.rsplit(".", 1)[-1].lower() == name and flatpak_installed(app):
                return home / ".var/app" / app / folder / "sluka.lua"
        return home / ".config" / ("mpv" if name == "mpv" else "celluloid") / "scripts/sluka.lua"

    def _why_not(self, pid: int, name: str) -> str:
        """The likeliest reason a running player has no script of Sluka's, from what can be seen of it."""
        where = self._script_place(name)
        try:
            args = Path(f"/proc/{pid}/cmdline").read_bytes().split(b"\0")
        except OSError:
            args = []
        flags = [a.decode("utf-8", "replace") for a in args if a.startswith(b"--")]
        if not _in_place(where):
            return f"the script is not in {where.parent} ([mpv] attach in config.ini puts it there at each start)"
        for flag in flags:
            if flag in ("--no-config", "--load-scripts=no") or flag.startswith("--config-dir"):
                return f"it was started with {flag}, which keeps it from loading scripts"
        try:
            placed = where.lstat().st_mtime
        except OSError:
            placed = 0.0
        began = _process_start(pid)
        if began and placed and began < placed:
            return "it was opened before the script was put in place; close the video and open it again"
        return "the script is in place, so it either failed to load or could not open its socket; lines marked 'mpv script:' above say which, if it got that far"

    def engine_alive(self) -> bool:
        return self._engine_seen and time.time() - self._last_poll < POLL_SECONDS + 15

    def places(self) -> list[tuple[str, Path, bool]]:
        """Every folder a player's socket may turn up in: ``(whose, folder, the script's alone)``."""
        found = [("", self.folder, True)]
        if WINDOWS:
            return found
        for app in FLATPAK_PLAYERS:
            who = app.rsplit(".", 1)[-1].lower()
            shared = runtime_dir() / "app" / app
            found.append((who, shared / "sluka-mpv", True))
            found.append((who, shared, False))
        return found

    def _look_at_pipes(self, now: float) -> None:
        """Windows: the players whose script opened a pipe, by the pipes there are -- and the notes of those that are gone, away."""
        pipes = set(pipe_names())
        if not pipes and not self.pipes_listed:
            return  # this system does not say which pipes it has: the notes in the folder are gone by alone
        self.pipes_listed = True
        try:
            for name in os.listdir(self.folder):
                if not name.endswith(".path"):
                    continue
                try:
                    target = (self.folder / name).read_text(encoding="utf-8").strip()
                except OSError:
                    continue
                if is_pipe(target) and target[len(PIPE_PREFIX):] not in pipes:
                    # Left behind by an mpv that is gone.
                    try:
                        (self.folder / name).unlink()
                    except OSError:
                        pass
        except OSError:
            pass
        for name in sorted(pipes):
            if not name.startswith(PIPE_NAME):
                continue
            key, target = name[len(PIPE_NAME):], PIPE_PREFIX + name
            with self._lock:
                if key in self.players or any(p.path == target for p in self.players.values()):
                    continue
            if now - self._failed.get(target, 0) < 3:
                continue
            try:
                player = Player(self, key, target)
            except OSError:
                self._failed[target] = now
                continue
            self._failed.pop(target, None)
            with self._lock:
                self.players[key] = player
            log.info("mpv player %s connected", key)
            player.send({"t": "hello", "app": __version__})

    pipes_listed = False

    def _look(self) -> None:
        now = time.time()
        if WINDOWS or self.pipes_listed:
            self._look_at_pipes(now)
        for who, folder, own in self.places():
            try:
                names = os.listdir(folder)
            except OSError:
                continue
            for name in names:
                # In a folder that holds other things too, only what the script named as its own.
                if not own and not name.startswith("sluka-"):
                    continue
                path = folder / name
                if name.endswith(".sock"):
                    target = str(path)
                elif name.endswith(".path"):
                    # mpv was started with a socket of its own; the script wrote down where.
                    try:
                        target = path.read_text(encoding="utf-8").strip()
                    except OSError:
                        continue
                else:
                    continue
                stem = name.rsplit(".", 1)[0]
                key = f"{who}:{stem}" if who else stem
                with self._lock:
                    if key in self.players or any(p.path == target for p in self.players.values()):
                        continue
                if now - self._failed.get(target, 0) < 3:
                    continue
                try:
                    player = Player(self, key, target)
                except OSError:
                    self._failed[target] = now
                    # Left behind by an mpv that is gone: nothing answers there any more.
                    # (Inside a sandbox the number in the name is not one this system knows.)
                    if not who:
                        self._forget_stale(path, stem)
                    continue
                self._failed.pop(target, None)
                with self._lock:
                    self.players[key] = player
                log.info("mpv player %s connected", key)
                player.send({"t": "hello", "app": __version__})

    def _forget_stale(self, path: Path, key: str) -> None:
        if WINDOWS:
            return  # there the pipes themselves say who is gone (_look_at_pipes)
        if not key.isdigit() or os.path.exists(f"/proc/{key}"):
            return
        try:
            path.unlink()
        except OSError:
            pass

    def player_gone(self, player: Player) -> None:
        with self._lock:
            if self.players.get(player.key) is player:
                del self.players[player.key]
            else:
                return
        log.info("mpv player %s gone", player.key)
        self._offer({"player": player.key, "msg": {"t": "bye"}})

    def incoming(self, player: Player, message: dict) -> None:
        if message.get("t") == "anki":
            # The file the word was picked in, for its card's clip: kept here, and read only through ``mpv/file``,
            # for this player -- the engine is never handed a path.
            path = message.pop("path", None)
            if isinstance(path, str) and path and os.path.isfile(path):
                player.media = path
        if message.get("t") == "hello":
            log.info("the script in mpv player %s answered", player.key)
            if not self.engine_alive() and time.time() - self._started > 45:
                log.warning("but Sluka's own code in the app's hidden page is not asking for news: "
                            "nothing will be drawn until it does (see the errors above, if any)")
        self._offer({"player": player.key, "msg": message})

    # ------------------------------------------------------------ the engine's side

    def _offer(self, item: dict) -> None:
        with self._lock:
            self._queue.append(item)
            if not self._waiting:
                return
            _deadline, respond = self._waiting.pop(0)
            items = list(self._queue)
            self._queue.clear()
        respond(json_response({"msgs": items}))

    def _expire(self) -> None:
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
        if name == "status":
            respond(json_response(self.status()))
            return
        if name in ("file", "shot"):
            # Sluka's engine, cutting a card's clip and picture: never a web page.
            site = str(req.headers.get("sec-fetch-site", "") or "").lower()
            if site and site not in ("same-origin", "none"):
                respond(error_response(403, "forbidden"))
                return
        if name == "file" and req.method in ("GET", "HEAD"):
            respond(self._file(str(req.query.get("player", "")), req))
            return
        try:
            args = json.loads(req.body.decode("utf-8")) if req.body else {}
        except (ValueError, UnicodeDecodeError):
            respond(error_response(400, "not JSON"))
            return
        if name == "poll":
            self._poll(args, respond)
        elif name == "reply":
            respond(self._reply(args))
        elif name == "play":
            files = [str(f) for f in args.get("files") or [] if isinstance(f, str)]
            problem = self.play(files)
            respond(json_response({"ok": not problem, "error": problem}))
        elif name == "shot":
            respond(json_response(self._shot(args)))
        else:
            respond(error_response(404, "no such mpv call"))

    #: The picture of the frame on screen a player's script takes as a word is picked for Anki (sluka.lua pick_anki).
    SHOT_NAME = re.compile(r"sluka-shot-\d+-\d+\.(?:jpg|png)")
    SHOT_MOST = 16 * 1024 * 1024

    def _file(self, key: str, req: Request) -> Response:
        """The file player ``key`` played when a word was picked in it, a range of it at a time (as the extension reads
        a video file of yours for a clip: offscreen/file-clip.js)."""
        with self._lock:
            player = self.players.get(key)
        path = getattr(player, "media", "") if player is not None else ""
        if not path or not os.path.isfile(path):
            return error_response(404, "no file")
        size = os.path.getsize(path)
        start, length, partial = 0, size, False
        headers = {"Accept-Ranges": "bytes", "Cache-Control": "no-store"}
        match = re.match(r"bytes=(\d*)-(\d*)$", str(req.headers.get("range", "") or "").strip())
        if match and (match.group(1) or match.group(2)):
            if match.group(1):
                start = int(match.group(1))
                end = int(match.group(2)) if match.group(2) else size - 1
            else:
                start, end = max(0, size - int(match.group(2))), size - 1
            end = min(end, size - 1)
            if start > end or start >= size:
                return Response(status=416, headers={"Content-Range": f"bytes */{size}"})
            length, partial = end - start + 1, True
            headers["Content-Range"] = f"bytes {start}-{end}/{size}"
        return Response(status=206 if partial else 200, content_type="application/octet-stream", headers=headers,
                        file=(path, start, length))

    def _shot(self, args: dict) -> dict:
        """The picture a player's script took of the frame on screen (a file of its own in the temporary folder),
        handed over and deleted."""
        import base64

        name = str(args.get("name") or "")
        if not self.SHOT_NAME.fullmatch(name):
            return {"ok": False, "error": "name"}
        path = os.path.join(tempfile.gettempdir(), name)
        try:
            if os.path.getsize(path) > self.SHOT_MOST:
                return {"ok": False, "error": "too large"}
            with open(path, "rb") as handle:
                data = handle.read()
        except OSError:
            return {"ok": False, "error": "none"}
        finally:
            try:
                os.remove(path)
            except OSError:
                pass
        return {"ok": True, "b64": base64.b64encode(data).decode("ascii")}

    def _poll(self, args: dict, respond) -> None:
        self._last_poll = time.time()
        if not self._engine_seen:
            self._engine_seen = True
            log.info("Sluka's own code is listening for mpv players")
        if args.get("fresh"):
            # An engine that has just started knows no player: each says hello to it again.
            with self._lock:
                players = list(self.players.values())
                # One engine at a time: an older one's wait is ended.
                waiting, self._waiting = self._waiting, []
            for _deadline, old in waiting:
                old(json_response({"msgs": [], "superseded": True}))
            for player in players:
                player.send({"t": "hello", "app": __version__})
        with self._lock:
            if self._queue:
                items = list(self._queue)
                self._queue.clear()
            else:
                self._waiting.append((time.monotonic() + POLL_SECONDS, respond))
                return
        respond(json_response({"msgs": items}))

    def _reply(self, args: dict) -> Response:
        key = str(args.get("player") or "")
        message = args.get("msg")
        if not isinstance(message, dict):
            return error_response(400, "no message")
        with self._lock:
            targets = list(self.players.values()) if key == "*" else [p for p in [self.players.get(key)] if p]
        if not targets:
            return json_response({"ok": False, "gone": True})
        if message.get("t") == "ready" and isinstance(message.get("look"), dict) and WINDOWS:
            # What Windows has each player's screen at: an mpv that does not scale itself says nothing of it.
            sent = []
            for player in targets:
                scale = display_scale_of(getattr(player, "pid", 0))
                own = dict(message, look=dict(message["look"], dpi=scale)) if scale else message
                sent.append(player.send(own))
            return json_response({"ok": any(sent)})
        sent = [player.send(message) for player in targets]
        return json_response({"ok": any(sent)})

    # ------------------------------------------------------------ starting a player

    def play(self, files: list[str]) -> str | None:
        """Start mpv (or Celluloid) on ``files`` with the script loaded; an error to show, or None."""
        return start_player(self.config, files, self.folder)


def display_scale_of(pid: int) -> float:
    """Windows: what the screen a process's window is on is set to (1.25 for 125 %); 0 where that cannot be told."""
    if not WINDOWS or not pid:
        return 0.0
    try:
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.windll.user32
        found: list[int] = []

        @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        def each(hwnd, _param):
            owner = wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
            if owner.value == pid and user32.IsWindowVisible(hwnd):
                found.append(hwnd)
                return False
            return True

        user32.EnumWindows(each, 0)
        if not found:
            return 0.0
        user32.MonitorFromWindow.restype = ctypes.c_void_p
        monitor = user32.MonitorFromWindow(wintypes.HWND(found[0]), 2)  # MONITOR_DEFAULTTONEAREST
        dpi_x, dpi_y = wintypes.UINT(), wintypes.UINT()
        if ctypes.windll.shcore.GetDpiForMonitor(ctypes.c_void_p(monitor), 0, ctypes.byref(dpi_x), ctypes.byref(dpi_y)) != 0:
            return 0.0
        return round(dpi_x.value / 96.0, 3) if dpi_x.value else 0.0
    except Exception:
        return 0.0


def player_command(config: Config, files: list[str], folder: Path) -> tuple[list[str] | None, str | None]:
    script = config.mpv_dir / "sluka.lua"
    if not script.is_file():
        return None, f"The mpv script is missing: {script}"
    videos = [f for f in files if Path(f).suffix.lower() not in SUBTITLE_SUFFIXES]
    subtitles = [f for f in files if Path(f).suffix.lower() in SUBTITLE_SUFFIXES]
    if WINDOWS:
        mpv = find_windows_player(config)
        if not mpv:
            return None, (
                "mpv.exe was not found.\n"
                "Say where it is in config.ini:  [mpv]  player = C:\\path\\to\\mpv.exe\n"
                "(or open the video in mpv yourself: with the app running, Sluka is in it)"
            )
        cmd = [mpv, f"--script={script}"] + [f"--sub-file={s}" for s in subtitles]
        return cmd + ["--"] + (videos or files), None
    mpv = shutil.which("mpv")
    if mpv:
        cmd = [mpv, f"--script={script}", f"--script-opts-append=sluka-socket_dir={folder}"]
        cmd += [f"--sub-file={s}" for s in subtitles]
        return cmd + ["--"] + (videos or files), None
    celluloid = shutil.which("celluloid")
    sandboxed = flatpak_players()
    if celluloid and "io.github.celluloid_player.Celluloid" not in sandboxed:
        # Celluloid passes --mpv-NAME=VALUE on to the mpv inside it.
        cmd = [celluloid, "--new-window", f"--mpv-script={script}", f"--mpv-script-opts-append=sluka-socket_dir={folder}"]
        cmd += [f"--mpv-sub-file={s}" for s in subtitles]
        return cmd + (videos or files), None
    if sandboxed:
        # A Flatpak reads neither the app folder nor an option naming a file in
        # it: the script is put inside the player's own folder instead, and the
        # files are handed over the way the desktop hands them (--file-forwarding).
        from .install import hook_players

        hook_players(config, quiet=True)
        flatpak = shutil.which("flatpak")
        if flatpak:
            return [flatpak, "run", "--file-forwarding", sandboxed[0], "@@"] + list(files) + ["@@"], None
        if celluloid:
            return [celluloid] + list(files), None
        return None, (
            f"{sandboxed[0]} is installed as a Flatpak, but the flatpak command was not found.\n"
            "Open the video from the player itself: Sluka's script is in it."
        )
    return None, (
        "Neither mpv nor Celluloid was found.\n"
        "Install mpv with:  sudo apt install mpv\n"
        "(on Tails, choose \"Install Every Time\" when asked)"
    )


def _behind_shim(program: str) -> str:
    """The program a Scoop "shim" stands for (it says so in a file beside it), or the program itself."""
    try:
        with open(os.path.splitext(program)[0] + ".shim", encoding="utf-8", errors="replace") as handle:
            for line in handle:
                key, _, value = line.partition("=")
                if key.strip().lower() == "path" and value.strip():
                    return value.strip().strip('"')
    except OSError:
        pass
    return program


def windows_players(config: Config, env=None, exists=os.path.isfile, which=shutil.which) -> list[str]:
    """Every mpv.exe (or mpv.net) there is to find: the one named in config.ini, those on the PATH, those in
    the places a player is often put.  The first is the one this app starts."""
    env = os.environ if env is None else env
    found: list[str] = []

    def add(program: str) -> None:
        if program and os.path.normcase(program) not in [os.path.normcase(f) for f in found]:
            found.append(program)

    named = os.path.expandvars(config.mpv_player) if config.mpv_player else ""
    if named:
        if os.path.isdir(named):
            named = os.path.join(named, "mpv.exe")
        if exists(named):
            add(named)
    for program in ("mpv.exe", "mpv.com", "mpvnet.exe"):
        hit = which(program)
        if hit:
            add(hit)
            # Where it really is: a link of winget's, a shim of Scoop's or Chocolatey's lead elsewhere.
            for true in (_behind_shim(hit), os.path.realpath(hit)):
                if os.path.normcase(true) != os.path.normcase(hit) and exists(true):
                    add(true)
    places = []
    scoop = env.get("SCOOP") or (os.path.join(env["USERPROFILE"], "scoop") if env.get("USERPROFILE") else "")
    for base, rest in (("LOCALAPPDATA", r"Programs\mpv"), ("LOCALAPPDATA", "mpv"), ("ProgramFiles", "mpv"), ("ProgramFiles(x86)", "mpv"),
                       ("LOCALAPPDATA", r"Programs\mpv.net"), ("ProgramFiles", "mpv.net")):
        if env.get(base):
            places.append(os.path.join(env[base], rest))
    if scoop:
        places += [os.path.join(scoop, "apps", name, "current") for name in ("mpv", "mpv-git", "mpv.net")]
    if env.get("ProgramData"):
        places.append(os.path.join(env["ProgramData"], "chocolatey", "bin"))
    for place in places:
        for program in ("mpv.exe", "mpvnet.exe"):
            if exists(os.path.join(place, program)):
                add(os.path.join(place, program))
    return found


def find_windows_player(config: Config, env=None, exists=os.path.isfile) -> str:
    """mpv.exe: the one named in config.ini, one on the PATH, or one in a place it is often put; '' if none."""
    found = windows_players(config, env=env, exists=exists)
    return found[0] if found else ""


def start_player(config: Config, files: list[str], folder: Path) -> str | None:
    if not files:
        return "No file was chosen."
    cmd, problem = player_command(config, files, folder)
    if problem:
        return problem
    try:
        # Its own from here on: closing the app (or the terminal it was started from) leaves the film playing.
        apart = {"creationflags": getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)} if WINDOWS \
            else {"start_new_session": True}
        subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **apart)
    except OSError as err:
        return f"The player could not be started: {err}"
    # Which player, and no more: what is being watched is nobody's business, a log file's least of all.
    log.info("started %s", os.path.basename(cmd[0]))
    return None


def launch_player(config: Config, files: list[str]) -> int:
    """``sluka mpv FILE…``: the player, with the script; the app answers it if it is running."""
    if not files:
        print("usage: sluka mpv VIDEO [SUBTITLES]")
        return 2
    problem = start_player(config, [os.path.abspath(f) for f in files], Path(config.mpv_socket_dir))
    if problem:
        print(f"sluka: {problem}")
        return 1
    print("Started the player. Sluka's subtitles appear once Sluka Desktop is running.")
    return 0
