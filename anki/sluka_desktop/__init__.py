# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (c) 2026 Sluka.  Part of Sluka Desktop.
#
# This program is free software: you can redistribute it and/or modify it under the terms of the GNU General Public
# License as published by the Free Software Foundation, either version 3 of the License, or (at your option) any later
# version.
#
# This program is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY; without even the implied
# warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License along with this program (LICENSES\GPL-3.0.txt, in
# Sluka Desktop's folder).  If not, see <https://www.gnu.org/licenses/>.
"""Sluka in Anki's review screen: Anki's half of it.

This add-on belongs to Sluka Desktop and does nothing without it.  It is put
here, and kept up to date, by the app itself:  ./sluka install-anki

What it does is three small things.

1.  It lets Anki's own little server hand out two folders of this add-on to
    the review screen: ``web`` (two scripts of the app's) and ``ext`` (a link
    to Sluka's own files, wherever the app keeps them; or a copy of them, if
    the app was asked for one).

2.  It puts one of those scripts into the page your cards are shown in.  That
    script brings in Sluka's page script -- but only once the app answers.

3.  It carries what that script says to the app, and the app's answers back:
    from the page by Anki's own bridge between a page and Python, and from
    here to the app through a socket in a folder only you can read.  (Windows
    has no such sockets: there it is a port on this computer's own address,
    which lets in only who says the word written in a file of yours first.)
    Nothing here goes out to the network.

It opens the socket and waits; the app finds it.  So it does not matter which
of the two you start first, and closing the app leaves Anki exactly as it is
without this add-on.

One more thing, which can be switched off (Tools > Add-ons > Config,
"grade_keys"): the keys 1 to 4 answer a card in Anki, and grade a word in
Sluka.  While a word's panel is open they go to Sluka; at every other moment
they are Anki's, as always.  ("grade_keys_on_hover" gives them to Sluka also
while the pointer rests on a word, as on a web page.)

Nothing of a card is written anywhere by this add-on: its notes
(user_files/log.txt) hold what happened to the connection, and no more.
"""

from __future__ import annotations

import atexit
import json
import os
import socket
import threading
import time

VERSION = "0.16.2"
PROTOCOL = 1
PREFIX = "sluka:"

try:
    from aqt import gui_hooks, mw
except Exception:  # not inside Anki: nothing to do (the tests bring an Anki of their own)
    gui_hooks = None
    mw = None

ADDON = __name__.split(".")[0]
HERE = os.path.dirname(os.path.abspath(__file__))
#: Lines of what went on, for a question about it: the newest few hundred, in user_files/log.txt.
_notes: list = []


def note(text: str) -> None:
    line = time.strftime("%Y-%m-%d %H:%M:%S ") + text
    _notes.append(line)
    del _notes[:-300]
    try:
        folder = os.path.join(HERE, "user_files")
        os.makedirs(folder, exist_ok=True)
        path = os.path.join(folder, "log.txt")
        if os.path.exists(path) and os.path.getsize(path) > 200_000:
            os.replace(path, path + ".old")
        with open(path, "a", encoding="utf-8") as handle:
            handle.write(line + "\n")
    except OSError:
        pass


def on_main(fn) -> None:
    """Run ``fn`` on Anki's own thread, which is the only one that may touch its windows."""
    try:
        mw.taskman.run_on_main(fn)
    except Exception as err:
        note(f"could not hand over to Anki's main thread: {err}")


# ------------------------------------------------------------------ where the socket is

def flatpak_id() -> str:
    found = os.environ.get("FLATPAK_ID") or ""
    if found:
        return found
    try:
        with open("/.flatpak-info", encoding="utf-8") as handle:
            for line in handle:
                if line.startswith("name="):
                    return line[5:].strip()
    except OSError:
        pass
    return ""


#: Windows has no sockets in folders.  There the app is met on a port of this computer's own address,
#: whose number, with a word the app has to say first, is written into a file in the user's own folder.
WINDOWS = os.name == "nt"
OVER_TCP = WINDOWS or os.environ.get("SLUKA_ANKI_TRANSPORT") == "tcp"


def socket_folder() -> str:
    if WINDOWS:
        # The app has the same words for this folder (config.py, local_dir).
        base = os.environ.get("LOCALAPPDATA") or os.environ.get("TEMP") or os.path.expanduser("~")
        return os.path.join(base, "sluka-desktop", "anki")
    runtime = os.environ.get("XDG_RUNTIME_DIR") or ""
    if not runtime and os.path.isdir(f"/run/user/{os.getuid()}"):
        # Where it is on every Linux desktop, said or not; the app looks there too.
        runtime = f"/run/user/{os.getuid()}"
    app = flatpak_id()
    if app and runtime:
        # In a sandbox, the one folder of the runtime directory the rest of the system sees too.
        return os.path.join(runtime, "app", app, "sluka-anki")
    if runtime:
        return os.path.join(runtime, "sluka-anki")
    return f"/tmp/sluka-desktop-{os.getuid()}/sluka-anki"


def own_folder(folder: str) -> bool:
    """A folder of this user's that nobody else can look into: the only kind a socket is put in."""
    try:
        found = os.lstat(folder)
    except OSError:
        return False
    import stat

    return stat.S_ISDIR(found.st_mode) and found.st_uid == os.getuid() and not found.st_mode & 0o077


# ------------------------------------------------------------------ the app, at the other end of the socket

class Pipe:
    """A socket the Sluka Desktop app connects to; one app at a time."""

    def __init__(self, on_line, on_change):
        self.on_line = on_line        # a line from the app (called on the reading thread)
        self.on_change = on_change    # the app came (True) or went (False)
        self.path = ""
        self.server = None
        self.conn = None
        self.word = ""                # what the app has to say first, where anybody on this computer could knock
        self._lock = threading.Lock()
        self._stop = False

    @property
    def connected(self) -> bool:
        return self.conn is not None

    def _start_on_port(self, folder: str) -> bool:
        """Windows: a port on this computer's own address, and a file saying which, with the word to say."""
        try:
            os.makedirs(folder, mode=0o700, exist_ok=True)
            import secrets

            self.word = secrets.token_hex(16)
            self.server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
                self.server.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            self.server.bind(("127.0.0.1", 0))
            self.server.listen(4)
            port = self.server.getsockname()[1]
            self.path = os.path.join(folder, f"{os.getpid()}.port")
            partial = self.path + ".new"
            with open(partial, "w", encoding="utf-8") as handle:
                # With the add-on's version: the app leaves alone an Anki whose note has none (0.5.0 and before).
                json.dump({"port": port, "word": self.word, "addon": VERSION, "v": PROTOCOL}, handle)
            if not WINDOWS:
                os.chmod(partial, 0o600)
            os.replace(partial, self.path)
        except OSError as err:
            note(f"no port for Sluka Desktop could be opened (said in {folder}): {err}")
            self.server = None
            return False
        threading.Thread(target=self._accept, name="sluka-anki-accept", daemon=True).start()
        note(f"waiting for Sluka Desktop on this computer's port {port} (said in {self.path})")
        return True

    def start(self) -> bool:
        folder = socket_folder()
        if OVER_TCP:
            return self._start_on_port(folder)
        try:
            os.makedirs(folder, mode=0o700, exist_ok=True)
            if os.path.islink(folder) or os.lstat(folder).st_uid != os.getuid():
                raise OSError("it is not a folder of yours")
            os.chmod(folder, 0o700)
            if not own_folder(folder):
                raise OSError("it cannot be closed to other users")
            self.path = os.path.join(folder, f"{os.getpid()}.sock")
            if os.path.exists(self.path):
                os.unlink(self.path)
            self.server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            self.server.bind(self.path)
            os.chmod(self.path, 0o600)
            self.server.listen(2)
        except OSError as err:
            note(f"the socket for Sluka Desktop could not be opened in {folder}: {err}")
            self.server = None
            return False
        threading.Thread(target=self._accept, name="sluka-anki-accept", daemon=True).start()
        note(f"waiting for Sluka Desktop at {self.path}")
        return True

    def _accept(self) -> None:
        while not self._stop:
            try:
                conn, _ = self.server.accept()
            except OSError:
                return
            if self.word:
                threading.Thread(target=self._admit, args=(conn,), name="sluka-anki-admit", daemon=True).start()
            else:
                self._take(conn, b"")

    def _admit(self, conn) -> None:
        """Who knocks on the port says the word from the file first, or is not let in."""
        try:
            conn.settimeout(4)
            first = b""
            while b"\n" not in first:
                chunk = conn.recv(4096)
                if not chunk or len(first) > 4096:
                    raise OSError("nothing said")
                first += chunk
            line, rest = first.split(b"\n", 1)
            said = json.loads(line.decode("utf-8", "replace"))
            import hmac

            if not isinstance(said, dict) or not hmac.compare_digest(str(said.get("word") or ""), self.word):
                raise ValueError("not the word")
            conn.settimeout(None)
        except (OSError, ValueError):
            try:
                conn.close()
            except OSError:
                pass
            return
        self._take(conn, rest)

    def _take(self, conn, rest: bytes) -> None:
        with self._lock:
            old, self.conn = self.conn, conn
        if old is not None:
            for end in (lambda: old.shutdown(socket.SHUT_RDWR), old.close):
                try:
                    end()
                except OSError:
                    pass
        threading.Thread(target=self._read, args=(conn, rest), name="sluka-anki-read", daemon=True).start()
        self.on_change(True)

    def _read(self, conn, buffer: bytes = b"") -> None:
        try:
            while b"\n" in buffer:
                line, buffer = buffer.split(b"\n", 1)
                if line.strip():
                    self.on_line(line.decode("utf-8", "replace"))
            while True:
                chunk = conn.recv(262144)
                if not chunk:
                    break
                buffer += chunk
                while b"\n" in buffer:
                    line, buffer = buffer.split(b"\n", 1)
                    if line.strip():
                        self.on_line(line.decode("utf-8", "replace"))
        except OSError:
            pass
        finally:
            with self._lock:
                mine = self.conn is conn
                if mine:
                    self.conn = None
            try:
                conn.close()
            except OSError:
                pass
            if mine:
                self.on_change(False)

    def send(self, line: str) -> bool:
        with self._lock:
            conn = self.conn
            if conn is None:
                return False
            try:
                conn.sendall(line.encode("utf-8") + b"\n")
                return True
            except OSError:
                return False

    def close(self) -> None:
        self._stop = True
        for thing in (self.conn, self.server):
            if thing is None:
                continue
            for end in (lambda: thing.shutdown(socket.SHUT_RDWR), thing.close):
                try:
                    end()
                except OSError:
                    pass
        try:
            if self.path and os.path.exists(self.path):
                os.unlink(self.path)
        except OSError:
            pass


# ------------------------------------------------------------------ the page

def review_page():
    """The page the cards are shown in, while cards are being shown."""
    try:
        if mw.state != "review":
            return None
        return mw.reviewer.web
    except Exception:
        return None


def deliver(line: str) -> None:
    """One line from the app, to Sluka's script in the review screen (on Anki's own thread)."""
    web = review_page()
    if web is None:
        return
    try:
        web.eval("window.__slukaAnki&&window.__slukaAnki.deliver(%s);" % json.dumps(line))
    except Exception as err:
        note(f"a message could not be handed to the review screen: {err}")


def engine_version() -> str:
    """The Chromium Anki's pages run in, by Qt's own function for it, which touches no page and no profile."""
    for where in ("aqt.qt", "PyQt6.QtWebEngineCore"):
        try:
            module = __import__(where, fromlist=["qWebEngineChromiumVersion"])
            found = str(module.qWebEngineChromiumVersion() or "").strip()
            if found:
                return f"Chromium {found}"
        except Exception:
            continue
    return ""


def about() -> dict:
    """What the add-on says of itself and of this Anki: the versions of its parts.

    Read once, as the add-on starts (on Anki's own thread), and said from the
    thread the app's connection is taken on.  So nothing here may be one of
    Qt's objects: those belong to Anki's thread alone.  (Until 0.5.0 this asked
    Qt for its default web profile, from the connection's thread, where Qt
    may have to make it there and then -- which it does not survive: Anki 26
    on Windows went down a moment after the app connected, before this
    greeting ever reached the app.)
    """
    said = {"t": "hello", "v": PROTOCOL, "addon": VERSION, "pid": os.getpid(), "anki": "", "qt": "", "python": "", "engine": ""}
    try:
        import platform

        said["python"] = platform.python_version()
    except Exception:
        pass
    try:
        from anki.buildinfo import version

        said["anki"] = str(version)
    except Exception:
        try:
            import aqt

            said["anki"] = str(getattr(aqt, "appVersion", ""))
        except Exception:
            pass
    try:
        from aqt.qt import qVersion

        said["qt"] = str(qVersion())
    except Exception:
        pass
    said["engine"] = engine_version()
    return said


pipe = None
#: about(), as it was read when the add-on started.
_about: dict = {}


def app_line(line: str) -> None:
    # The app's own greeting stays here; everything else is for the page.
    if line.startswith('{"t":"hello"'):
        note("Sluka Desktop is here")
        return
    on_main(lambda: deliver(line))


def app_changed(there: bool) -> None:
    # On the thread the connection came or went on: what is said needs nothing of Qt's, and the page is reached
    # through Anki's own thread.
    if there:
        note("Sluka Desktop connected")
        pipe.send(json.dumps(_about or about(), separators=(",", ":")))
        on_main(lambda: deliver('{"t":"up"}'))
    else:
        note("Sluka Desktop went away")
        on_main(lambda: deliver('{"t":"down"}'))


# ------------------------------------------------------------------ Anki's hooks

def is_reviewer(context) -> bool:
    try:
        from aqt.reviewer import Reviewer

        return isinstance(context, Reviewer)
    except Exception:
        return False


#: How long the review screen may take to speak, and to be made, before something is thought to be wrong (seconds).
SILENT_AFTER = 15.0
UNASKED_AFTER = 5.0
#: When the review screen was last made with the app's script in it, and when that script last spoke.
_made = 0.0
_heard = 0.0
_told: set = set()


def tell(key: str, text: str) -> None:
    """Something worth knowing about this Anki, once: into the notes here and, if it is there, the app's log."""
    if key in _told:
        return
    _told.add(key)
    note(text)
    if pipe is not None:
        pipe.send(json.dumps({"t": "log", "level": "warning", "text": text}, separators=(",", ":")))


def later(seconds: float, fn) -> None:
    timer = threading.Timer(seconds, lambda: on_main(fn))
    timer.daemon = True
    timer.start()


def on_content(web_content, context) -> None:
    """The review screen is being made: the app's script goes into it."""
    global _made
    if not is_reviewer(context):
        return
    try:
        package = mw.addonManager.addonFromModule(__name__)
    except Exception:
        package = ADDON
    web_content.js.append(f"/_addons/{package}/web/anki-page.js")
    # A page of before, if there was one, is gone with this one's making.
    if pipe is not None:
        pipe.send('{"t":"page","state":"closed"}')
    _made = made = time.time()

    def silent():
        if _heard < made and _made == made and review_page() is not None:
            tell("silent", "Anki's review screen was given Sluka's script, and the script has not spoken from it: "
                           "this Anki's pages may not let an add-on's script talk to the add-on")

    later(SILENT_AFTER, silent)


def settings() -> dict:
    try:
        return dict(mw.addonManager.getConfig(__name__) or {})
    except Exception:
        return {}


def on_js_message(handled, message, context):
    """What Sluka's script in the page says: passed on to the app as it is."""
    if message == "sluka-config":
        # The page asks how this add-on is set.
        return (True, {"read_every_card": settings().get("read_every_card", True) is not False})
    if not isinstance(message, str) or not message.startswith(PREFIX):
        return handled
    global _heard
    _heard = time.time()
    if not is_reviewer(context):
        return (True, None)
    if pipe is None or not pipe.send(message[len(PREFIX):]):
        deliver('{"t":"down"}')
    return (True, None)


def on_state(new_state, old_state) -> None:
    if old_state == "review" and new_state != "review" and pipe is not None:
        pipe.send('{"t":"page","state":"closed"}')
    if new_state == "review":
        began = time.time()

        def unasked():
            # Anki asks its add-ons what goes into a page as it makes the page, a moment before it says "review".
            if _made < began - 30 and review_page() is not None:
                tell("unasked", "Anki opened its review screen without asking its add-ons what to put into it, so Sluka is not in it: "
                                "this add-on is made for Anki's review screen as it has been so far, not for an experimental one "
                                "that may be switched on in Anki's preferences")

        later(UNASKED_AFTER, unasked)


def grade_keys_on() -> bool:
    return settings().get("grade_keys", True) is not False


def hover_keys_on() -> bool:
    return settings().get("grade_keys_on_hover", False) is True


def on_shortcuts(state, shortcuts) -> None:
    """1 to 4 go to Sluka while a word's panel is open, and to Anki otherwise."""
    if state != "review" or not grade_keys_on():
        return

    def shared(key, anki_does):
        def pressed():
            web = review_page()
            # Without the app there is no Sluka in the page to ask.
            if web is None or pipe is None or not pipe.connected:
                anki_does()
                return

            def answered(taken):
                if taken is not True:
                    anki_does()

            try:
                web.evalWithCallback("(window.__slukaAnki&&window.__slukaAnki.key(%s,%s))===true"
                                     % (json.dumps(key), "true" if hover_keys_on() else "false"), answered)
            except Exception:
                anki_does()

        return pressed

    for at, entry in enumerate(list(shortcuts)):
        try:
            key, action = entry[0], entry[1]
        except Exception:
            continue
        if key in ("1", "2", "3", "4") and callable(action):
            shortcuts[at] = (key, shared(key, action)) + tuple(entry[2:])


def start() -> None:
    global pipe
    if mw is None or gui_hooks is None:
        return
    note(f"Sluka Desktop's add-on {VERSION} starting")
    if not os.path.exists(os.path.join(HERE, "ext", "manifest.json")):
        note("Sluka's own files are not linked here (ext/): run  ./sluka install-anki  in the Sluka Desktop folder")
    try:
        mw.addonManager.setWebExports(__name__, r"(web|ext)/.*")
    except Exception as err:
        note(f"this Anki does not let an add-on hand files to its pages: {err}")
        return
    hooks = (
        ("webview_will_set_content", on_content),
        ("webview_did_receive_js_message", on_js_message),
        ("state_did_change", on_state),
        ("state_shortcuts_will_change", on_shortcuts),
    )
    for name, fn in hooks:
        hook = getattr(gui_hooks, name, None)
        if hook is None:
            note(f"this Anki is too old for Sluka's add-on: it has no {name}")
            if name in ("webview_will_set_content", "webview_did_receive_js_message"):
                return
            continue
        hook.append(fn)
    # Read here, on Anki's own thread, before anything can connect.
    _about.update(about())
    note("this Anki: {anki}, Qt {qt}, Python {python}{web}".format(web=f", {_about['engine']}" if _about.get("engine") else "", **{
        k: _about.get(k) or "?" for k in ("anki", "qt", "python")}))
    pipe = Pipe(app_line, app_changed)
    if pipe.start():
        atexit.register(pipe.close)


start()
