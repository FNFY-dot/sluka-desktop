# SPDX-License-Identifier: LicenseRef-Sluka
# Copyright (c) 2026 Sluka. Part of Sluka Desktop; see LICENSE.txt.
"""Sluka inside Anki's review screen.

Anki shows its cards in a web page of its own.  A small add-on of this app's
(``anki/sluka_desktop``) puts Sluka's page script into that page -- the script
the extension puts into every web page, unchanged -- so that the words of a
card are coloured, pointed at and graded as they are anywhere else, with
Sluka's own card and panel.

That script needs what it has in a browser: Sluka's files, somewhere to keep
its word lists, and the extension's worker to ask for meanings.  The files it
gets from Anki itself, which hands out a folder of the add-on's.  The rest is
here, in the running app, and reaches the page by a road with no network in
it::

    the page  --(Anki's own bridge to Python)-->  the add-on
    the add-on  --(a socket in a folder only you can read)-->  this bridge
    this bridge  -->  the store on disk            (word lists, settings)
                 -->  the app's hidden page         (meanings, the worker)

The add-on opens the socket and this app finds it, as it finds an mpv player:
so it does not matter which of the two is started first, and an Anki in a
Flatpak sandbox is found in the one folder of its that this app can see.

What a page in Anki may ask for is less than what the app's own pages may: the
store and the log, nothing else.  It cannot ask for files, downloads, windows
or players.  Beside that it talks to Sluka's worker as any web page with the
extension in it talks to it.
"""

from __future__ import annotations

import collections
import json
import logging
import os
import re
import socket
import stat
import threading
import time
from pathlib import Path

from . import APP_NAME, __version__
from .config import WINDOWS, Config, local_dir
from .host import Request, Response, error_response, json_response

log = logging.getLogger("sluka.anki")

#: How often the folders are looked into for an Anki that has started.
WATCH_SECONDS = 1.0
#: How long the app's hidden page may hold a request open, waiting for a page in Anki to say something.
POLL_SECONDS = 25
#: Messages kept for the hidden page while it is not asking.
QUEUE_MOST = 2000
#: Lines one Anki may put into the app's log while it is connected.
LOG_LINES_MOST = 200
#: A line longer than this is not a message.
LINE_MOST = 32 * 1024 * 1024
#: What a page in Anki may ask of the host.
REMOTE_CALLS = ("storage", "log")
#: Anki as a Flatpak: the one folder of its sandbox this app sees too.
FLATPAKS = ("net.ankiweb.Anki",)
#: What the add-on and this bridge say to each other, counted up when it changes shape.
PROTOCOL = 1


def runtime_dir() -> Path:
    return Path(os.environ.get("XDG_RUNTIME_DIR") or f"/tmp/sluka-desktop-{os.getuid()}")


def meeting_folder() -> Path:
    """Where an Anki with the add-on says it is there: a socket in it, or (Windows) a file naming a port."""
    if WINDOWS:
        return local_dir() / "anki"
    return runtime_dir() / "sluka-anki"


class Link:
    """One Anki, through the socket its add-on opened."""

    def __init__(self, bridge: "AnkiBridge", key: str, path: str, port: int = 0, word: str = ""):
        self.bridge = bridge
        self.key = key
        self.path = path
        if port:
            # Windows: a port on this computer's own address, and the word from the add-on's file said first.
            self.sock = socket.create_connection(("127.0.0.1", port), timeout=3)
            self.sock.sendall((json.dumps({"t": "word", "word": word}) + "\n").encode("utf-8"))
        else:
            self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            self.sock.settimeout(3)
            self.sock.connect(path)
        self.sock.settimeout(None)
        self.alive = True
        #: What the add-on said of itself: Anki's version, its toolkit's.
        self.about: dict = {}
        #: The page in this Anki that has Sluka in it now, by the name it gave itself.
        self.client: str | None = None
        self.engine_told = False
        self.lines = 0
        self._write_lock = threading.Lock()
        self.thread = threading.Thread(target=self._read, name=f"sluka-anki-{key}", daemon=True)
        self.thread.start()

    def send(self, message: dict) -> bool:
        line = json.dumps(message, ensure_ascii=False, separators=(",", ":")) + "\n"
        try:
            with self._write_lock:
                self.sock.sendall(line.encode("utf-8"))
            return True
        except OSError:
            self.close()
            return False

    def _read(self) -> None:
        buffer = b""
        try:
            while self.alive:
                chunk = self.sock.recv(262144)
                if not chunk:
                    break
                buffer += chunk
                if len(buffer) > LINE_MOST and b"\n" not in buffer:
                    buffer = b""
                    continue
                while b"\n" in buffer:
                    line, buffer = buffer.split(b"\n", 1)
                    if not line.strip():
                        continue
                    try:
                        message = json.loads(line.decode("utf-8", "replace"))
                    except ValueError:
                        continue
                    if isinstance(message, dict) and isinstance(message.get("t"), str):
                        try:
                            self.bridge.incoming(self, message)
                        except Exception:
                            log.exception("while hearing Anki %s", self.key)
        except OSError:
            pass
        finally:
            self.close()

    def close(self) -> None:
        if not self.alive:
            return
        self.alive = False
        try:
            # Shut down first: a close alone does not end a read another thread is waiting in, nor tell the far end.
            self.sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        try:
            self.sock.close()
        except OSError:
            pass
        self.bridge.gone(self)


class AnkiBridge:
    def __init__(self, config: Config, host):
        self.config = config
        self.host = host
        self.folder = meeting_folder()
        self._distrusted: set[str] = set()
        self.links: dict[str, Link] = {}
        self._lock = threading.RLock()
        self._queue: collections.deque = collections.deque(maxlen=QUEUE_MOST)
        self._waiting: list[tuple[float, callable]] = []
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._failed: dict[str, float] = {}
        #: Ankis left alone for the add-on they run (_older_addon), told of once each.
        self._older: set[str] = set()
        self._last_poll = 0.0
        self._gateway_seen = False

    # ------------------------------------------------------------ life

    def start(self) -> None:
        if self._thread:
            return
        self._thread = threading.Thread(target=self._watch, name="sluka-anki-watch", daemon=True)
        self._thread.start()
        log.info("watching %s for Anki with Sluka's add-on", self.folder)

    def close(self) -> None:
        self._stop.set()
        with self._lock:
            links = list(self.links.values())
        for link in links:
            link.send({"t": "down"})
            link.close()
        with self._lock:
            waiting, self._waiting = self._waiting, []
            items = list(self._queue)
            self._queue.clear()
        for at, (_deadline, respond) in enumerate(waiting):
            respond(json_response({"msgs": items if at == 0 else []}))

    def status(self) -> dict:
        with self._lock:
            return {
                "ankis": len(self.links),
                "pages": sum(1 for link in self.links.values() if link.client),
                "about": [dict(link.about) for link in self.links.values()],
                "folder": str(self.folder),
                "gateway": self.gateway_alive(),
                "older": sorted(self._older),
            }

    def gateway_alive(self) -> bool:
        return self._gateway_seen and time.time() - self._last_poll < POLL_SECONDS + 15

    # ------------------------------------------------------------ finding Anki

    def places(self) -> list[tuple[str, Path]]:
        """Every folder an add-on's socket may turn up in: ``(whose, folder)``."""
        found = [("", self.folder)]
        if WINDOWS:
            return found
        for app in FLATPAKS:
            found.append((app.rsplit(".", 1)[-1].lower(), runtime_dir() / "app" / app / "sluka-anki"))
        # Where the add-on goes when there is no runtime folder at all.
        found.append(("tmp", Path(f"/tmp/sluka-desktop-{os.getuid()}/sluka-anki")))
        return found

    @staticmethod
    def _own(folder: Path) -> bool:
        """A folder of this user's that nobody else can write a socket into: the only kind listened to."""
        if WINDOWS:
            return True  # under the user's own %LOCALAPPDATA%, which Windows keeps to the user
        try:
            found = os.lstat(folder)
        except OSError:
            return False
        return stat.S_ISDIR(found.st_mode) and found.st_uid == os.getuid() and not found.st_mode & 0o077

    def _watch(self) -> None:
        while not self._stop.wait(WATCH_SECONDS):
            try:
                self._look()
            except Exception:
                log.exception("while looking for Anki")
            self._expire()

    def _look(self) -> None:
        now = time.time()
        for who, folder in self.places():
            try:
                names = os.listdir(folder)
            except OSError:
                continue
            if not self._own(folder):
                if names and str(folder) not in self._distrusted:
                    self._distrusted.add(str(folder))
                    log.warning("%s is open to other users of this computer: an Anki waiting there is not answered", folder)
                continue
            for name in names:
                if not name.endswith((".sock", ".port")):
                    continue
                path = folder / name
                stem = name[:-5]
                key = f"{who}:{stem}" if who else stem
                with self._lock:
                    if key in self.links:
                        continue
                if now - self._failed.get(str(path), 0) < 3:
                    continue
                port, word = 0, ""
                if name.endswith(".port"):
                    # The add-on's note of where it listens (Windows): a port here, and the word to say there.
                    try:
                        said = json.loads(path.read_text(encoding="utf-8"))
                        port, word = int(said["port"]), str(said["word"])
                    except (OSError, ValueError, KeyError, TypeError):
                        continue
                    if not said.get("addon"):
                        self._older_addon(path, key, port, now)
                        continue
                try:
                    link = Link(self, key, str(path), port, word)
                except ConnectionRefusedError:
                    # Nothing listens on that port any more: the note was left by an Anki that is gone.
                    self._failed[str(path)] = now
                    if port:
                        try:
                            path.unlink()
                        except OSError:
                            pass
                    continue
                except OSError:
                    self._failed[str(path)] = now
                    # Left behind by an Anki that is gone: nothing answers there any more.
                    if not WINDOWS and not port and who in ("", "tmp") and stem.isdigit() and not os.path.exists(f"/proc/{stem}"):
                        try:
                            path.unlink()
                        except OSError:
                            pass
                    continue
                self._failed.pop(str(path), None)
                with self._lock:
                    self.links[key] = link
                log.info("Anki %s connected", key)
                link.send({"t": "hello", "v": PROTOCOL, "app": __version__})

    def _older_addon(self, path: Path, key: str, port: int, now: float) -> None:
        """An Anki whose add-on is from Sluka Desktop 0.5.0 or before (its note names no version): not connected to.

        That add-on asked Qt for a web profile from the thread a connection
        came in on, which brings Anki down on Windows as soon as the app
        connects.  It is only knocked at, without a word -- which that add-on
        turns away without doing anything -- to see whether it is still there.
        """
        if now - self._failed.get(str(path), 0) < 10:
            return
        self._failed[str(path)] = now
        try:
            socket.create_connection(("127.0.0.1", port), timeout=2).close()
        except OSError:
            # Nobody there: the note of an Anki that is gone.
            self._older.discard(key)
            try:
                path.unlink()
            except OSError:
                pass
            return
        if key not in self._older:
            self._older.add(key)
            log.warning("Anki %s is running the add-on of an older Sluka Desktop (0.5.0 or before), which brings Anki down "
                        "as soon as the app connects to it: it is left alone.  Restart Anki, and it loads the add-on "
                        "this app has put in place.", key)

    def gone(self, link: Link) -> None:
        with self._lock:
            if self.links.get(link.key) is not link:
                return
            del self.links[link.key]
            client, link.client = link.client, None
        log.info("Anki %s gone", link.key)
        if client:
            self._offer({"client": client, "gone": True})

    # ------------------------------------------------------------ what Anki says

    def boot(self) -> dict:
        """What a page is told so that it can bring Sluka's script in: what the extension's manifest puts into every page."""
        manifest = self.host.manifest
        scripts, sheets = [], []
        for entry in manifest.get("content_scripts") or []:
            # The entry for every page's top frame at rest: Sluka's reader itself.  The others are for
            # particular sites, for frames, or for the first moment of a page, which is long past here.
            if "<all_urls>" not in (entry.get("matches") or []) or entry.get("all_frames") or entry.get("world") == "MAIN":
                continue
            if entry.get("run_at", "document_idle") != "document_idle":
                continue
            scripts += [str(f) for f in entry.get("js") or []]
            sheets += [str(f) for f in entry.get("css") or []]
        return {
            "id": self.config.extension_id,
            "manifest": manifest,
            "app": {"name": APP_NAME, "version": __version__},
            "js": scripts,
            "css": sheets,
        }

    def incoming(self, link: Link, m: dict) -> None:
        kind = m["t"]
        if kind == "hello":
            link.about = {k: str(m.get(k) or "")[:80] for k in ("anki", "qt", "python", "addon", "engine")}
            log.info("the add-on in Anki %s answered: Anki %s, Qt %s%s, add-on %s", link.key, link.about["anki"] or "?", link.about["qt"] or "?",
                     f", web engine {link.about['engine']}" if link.about["engine"] else "", link.about["addon"] or "?")
            if link.about["addon"] and link.about["addon"] != __version__:
                log.warning("the add-on in Anki is version %s and this app %s: run  ./sluka install-anki  again, then restart Anki",
                            link.about["addon"], __version__)
        elif kind == "page":
            client = str(m.get("client") or "")[:80]
            if m.get("state") == "open" and client:
                with self._lock:
                    before, link.client = link.client, client
                if before and before != client:
                    self._offer({"client": before, "gone": True})
                if not link.engine_told:
                    link.engine_told = True
                    found = re.search(r"Chrom\w*/([\d.]+)", str(m.get("ua") or ""))
                    log.info("Anki's review screen is open (web engine: Chromium %s)", found.group(1) if found else "of an unknown version")
                    if not self.gateway_alive() and self._gateway_seen is False and time.time() - self.host.started > 45:
                        log.warning("but the app's hidden page is not passing messages on: Sluka's worker will not answer the page")
                link.send({"t": "boot", "to": client, "boot": self.boot()})
            else:
                with self._lock:
                    before, link.client = link.client, None
                if before:
                    self._offer({"client": before, "gone": True})
        elif kind == "api":
            self._call(link, m)
        elif kind == "bus":
            client = str(m.get("client") or "")
            if client and client == link.client and isinstance(m.get("m"), dict):
                self._offer({"client": client, "m": m["m"]})
        elif kind == "log":
            # Lines for the log are the add-on's and the app's own script's; whatever else is in the page
            # with them could write some too, so there is an end to them.
            link.lines += 1
            if link.lines > LOG_LINES_MOST:
                if link.lines == LOG_LINES_MOST + 1:
                    log.warning("no more lines from Anki %s are kept: there have been %d", link.key, LOG_LINES_MOST)
                return
            level = {"error": logging.ERROR, "warning": logging.WARNING, "warn": logging.WARNING}.get(str(m.get("level")), logging.INFO)
            text = " ".join(str(m.get("text") or "").split())[:600]
            log.log(level, "%s", text)

    def _call(self, link: Link, m: dict) -> None:
        """One question a page in Anki asks of the host: only the store and the log."""
        name = str(m.get("name") or "")
        reply = {"t": "reply", "to": str(m.get("client") or ""), "id": m.get("id")}
        body = m.get("body")
        if name not in REMOTE_CALLS or not isinstance(body, dict):
            link.send({**reply, "ok": False, "error": f"{name or 'that'} is not for a page outside the app"})
            return
        try:
            req = Request(method="POST", path=f"/__sluka__/api/{name}")
            if name == "log":
                body = {**body, "url": f"Anki: {str(body.get('url') or '')[:200]}"}
            response: Response = (self.host._api_storage if name == "storage" else self.host._api_log)(body, req)
            data = json.loads(response.body.decode("utf-8")) if response.body else {}
        except Exception as err:  # the page is told, and goes on
            log.exception("a question from Anki failed (%s)", name)
            link.send({**reply, "ok": False, "error": str(err)})
            return
        if response.status >= 400:
            link.send({**reply, "ok": False, "error": str(data.get("error") or response.status)})
        else:
            link.send({**reply, "ok": True, "data": data})

    # ------------------------------------------------------------ the hidden page's side

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
        try:
            args = json.loads(req.body.decode("utf-8")) if req.body else {}
        except (ValueError, UnicodeDecodeError):
            respond(error_response(400, "not JSON"))
            return
        if name == "poll":
            self._poll(args, respond)
        elif name == "push":
            respond(self._push(args))
        else:
            respond(error_response(404, "no such call"))

    def _poll(self, args: dict, respond) -> None:
        if self._stop.is_set():
            # Closed: nobody is left to answer a wait.
            respond(error_response(503, "the bridge to Anki is closed"))
            return
        self._last_poll = time.time()
        if not self._gateway_seen:
            self._gateway_seen = True
            log.info("the app's hidden page is passing messages between Anki and Sluka")
        if args.get("fresh"):
            # A page that has just started knows nobody: every page in Anki says who it is again.
            with self._lock:
                links = list(self.links.values())
                waiting, self._waiting = self._waiting, []
            for _deadline, old in waiting:
                old(json_response({"msgs": [], "superseded": True}))
            for link in links:
                link.send({"t": "up"})
        with self._lock:
            if self._queue:
                items = list(self._queue)
                self._queue.clear()
            else:
                self._waiting.append((time.monotonic() + POLL_SECONDS, respond))
                return
        respond(json_response({"msgs": items}))

    def _push(self, args: dict) -> Response:
        """What the app's pages said that concerns a page in Anki, handed to that page."""
        sent = 0
        with self._lock:
            by_client = {link.client: link for link in self.links.values() if link.client}
        for item in args.get("msgs") or []:
            if not isinstance(item, dict) or not isinstance(item.get("m"), dict):
                continue
            link = by_client.get(str(item.get("to") or ""))
            if link and link.send({"t": "bus", "to": link.client, "m": item["m"]}):
                sent += 1
        return json_response({"ok": True, "sent": sent})
