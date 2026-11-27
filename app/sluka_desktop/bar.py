# SPDX-License-Identifier: LicenseRef-Sluka
# Copyright (c) 2026 Sluka. Part of Sluka Desktop; see LICENSE.txt.
"""The floating subtitle bar: Sluka's subtitle box in a window of its own, over every other.

A line of text put into it -- from another program, by the app's local
address or by ``sluka bar-text`` -- is shown as Sluka shows a subtitle: its
words coloured by how well you know them, a card for the word pointed at, a
panel for the word clicked, the keys that grade.  Nothing here reads text
off the screen or out of a game; the bar only shows what it is given.

The words are cut, looked up and graded by the same page of Sluka's own code
that answers the script in mpv (mpv-engine.js): to it the bar is one more
player, called "bar", that says hello, sends a line and asks for a word.  The
bar's page (web/bar.html) draws what it is told, in Sluka's look, as the
script in mpv draws it, but with a browser's own layout and fonts.

This side keeps what the page and the engine say to each other moving, the
lines given to the bar until its page takes them, and the bar's place, size
and settings between starts (data/bar.json).  The window itself is the
shell's (winshell.py, kind "bar").
"""

from __future__ import annotations

import collections
import json
import logging
import math
import threading
import time
from pathlib import Path

from .host import Request, error_response, json_response

log = logging.getLogger("sluka.bar")

#: How long the bar's page may hold a request open, waiting for something to show.
POLL_SECONDS = 25
#: Messages kept for the page while it is not asking.
QUEUE_MOST = 500
#: The longest line taken (a subtitle, not a book).
TEXT_MOST = 4000
#: The most a call may send.
BODY_MOST = 256 * 1024
#: What of the bar's state is kept between starts, and what each may be.
STATE_KEYS = {
    "on": bool, "x": float, "y": float, "width": float, "scale": float, "lock": bool, "through": bool, "monitor": list,
}


class BarPlayer:
    """The bar, as the engine that answers mpv's script sees it: one more player, named "bar"."""

    key = "bar"

    def __init__(self, bar: "Bar"):
        self.bar = bar
        self.alive = True
        self.said_hello = False
        self.pid = 0
        self.path = "bar"

    def send(self, message: dict) -> bool:
        return self.bar.to_page({"t": "engine", "msg": message})

    def close(self) -> None:
        self.alive = False


class Bar:
    def __init__(self, config, host):
        self.config = config
        self.host = host
        self.file = Path(config.data_dir) / "bar.json"
        self.state = self._load()
        #: The window's side (winshell.Shell): open_bar, close_bar, bar_shape, bar_through, bar_to_monitor.  Set by the app.
        self.shell = None
        self.player: BarPlayer | None = None
        self._lock = threading.RLock()
        self._queue: collections.deque = collections.deque(maxlen=QUEUE_MOST)
        self._waiting: list[tuple[float, callable]] = []
        self._last_poll = 0.0
        self._last_text = ""
        self._last_lang: str | None = None
        self._save_timer: threading.Timer | None = None
        self._stopped = threading.Event()

    # ------------------------------------------------------------ state

    def _load(self) -> dict:
        try:
            found = json.loads(self.file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            found = {}
        state = {"on": False, "scale": 1.0, "lock": False, "through": False}
        if isinstance(found, dict):
            state.update(self._clean(found))
        return state

    @staticmethod
    def _clean(given: dict) -> dict:
        out = {}
        for key, kind in STATE_KEYS.items():
            if key not in given:
                continue
            value = given[key]
            try:
                if kind is bool and isinstance(value, bool):
                    out[key] = value
                elif kind is float and not isinstance(value, bool):
                    number = float(value)
                    if math.isfinite(number):
                        out[key] = number
                elif kind is list and isinstance(value, list) and len(value) == 4:
                    out[key] = [int(v) for v in value]
            except (TypeError, ValueError, OverflowError):
                continue
        if "scale" in out:
            out["scale"] = min(3.0, max(0.5, out["scale"]))
        if "width" in out:
            # Nought is "as the page sees fit" (six tenths of the screen).
            out["width"] = 0.0 if out["width"] <= 0 else min(8000.0, max(160.0, out["width"]))
        for key in ("x", "y"):
            if key in out:
                out[key] = min(1.5, max(-0.5, out[key]))
        return out

    def _save_soon(self) -> None:
        """Written a moment after the last change: a bar being dragged changes many times a second."""
        with self._lock:
            if self._save_timer is not None:
                self._save_timer.cancel()
            self._save_timer = threading.Timer(0.8, self._save)
            self._save_timer.daemon = True
            self._save_timer.start()

    def _save(self) -> None:
        with self._lock:
            state = dict(self.state)
            self._save_timer = None
        try:
            self.file.parent.mkdir(parents=True, exist_ok=True)
            partial = self.file.with_suffix(".json.new")
            partial.write_text(json.dumps(state, indent=1), encoding="utf-8")
            partial.replace(self.file)
        except OSError as err:
            log.warning("the bar's place could not be kept (%s): %s", self.file, err)

    def start(self) -> None:
        def watch() -> None:
            while not self._stopped.wait(1.0):
                self.expire()

        threading.Thread(target=watch, name="sluka-bar", daemon=True).start()

    def close(self) -> None:
        self._stopped.set()
        with self._lock:
            timer = self._save_timer
        if timer is not None:
            timer.cancel()
            self._save()
        self.page_gone()
        self._answer_all()

    # ------------------------------------------------------------ on and off

    @property
    def on(self) -> bool:
        return bool(self.state.get("on"))

    def set_on(self, on: bool) -> bool:
        with self._lock:
            changed = self.on != on
            self.state["on"] = on
        if changed:
            self._save_soon()
            log.info("the floating subtitles are %s", "on" if on else "off")
        shell = self.shell
        if shell is not None:
            (shell.open_bar if on else shell.close_bar)()
        if not on:
            self.page_gone()
        return on

    def set_through(self, on: bool) -> bool:
        """Clicks through the bar, or not (from the window menu; the bar's own button says it through _state)."""
        with self._lock:
            changed = bool(self.state.get("through")) != on
            self.state["through"] = on
        if changed:
            self._save_soon()
            shell = self.shell
            if shell is not None:
                shell.bar_through(on)
            self.to_page({"t": "set", "state": {"through": on}})
        return on

    # ------------------------------------------------------------ the page and the engine

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
        mpv = getattr(self.host, "mpv", None)
        return mpv if mpv is not None and hasattr(mpv, "add_player") else None

    def _player(self) -> BarPlayer | None:
        """The bar as a player of the engine's, made when its page first speaks."""
        engine = self._engine()
        if engine is None:
            return None
        with self._lock:
            if self.player is None or not self.player.alive:
                self.player = BarPlayer(self)
                engine.add_player(self.player)
            return self.player

    def page_gone(self) -> None:
        with self._lock:
            player, self.player = self.player, None
        engine = self._engine()
        if player is not None and engine is not None:
            player.close()
            engine.player_gone(player)

    def tell_engine(self, message: dict) -> bool:
        """A message to Sluka's engine as the bar's own, from the app (the play clock, playclock.py): only while the
        bar's page is there and has said hello to it."""
        with self._lock:
            player = self.player
        engine = self._engine()
        if player is None or not player.alive or not player.said_hello or engine is None:
            return False
        engine.incoming(player, message)
        return True

    def inject(self, text: str, lang: str | None = None) -> dict:
        """A line from another program, for the bar to show; ``lang`` (ja, zh, ...) where it is in another of the
        languages you learn than the one Sluka is set to.  Empty text clears the bar."""
        text = str(text or "").replace("\r\n", "\n").replace("\r", "\n").strip()[:TEXT_MOST]
        message = {"t": "text", "text": text, "at": time.time()}
        if lang and isinstance(lang, str) and len(lang) <= 16 and lang.replace("-", "").replace("_", "").isalnum():
            message["lang"] = lang
        with self._lock:
            self._last_text = text
            self._last_lang = message.get("lang")
        self.to_page(message)
        return {"ok": True, "on": self.on, "shown": self.on and self.page_alive()}

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

    # ------------------------------------------------------------ the calls

    def status(self) -> dict:
        engine = self._engine()
        return {"on": self.on, "engine": engine is not None, "page": self.page_alive(), "state": dict(self.state)}

    #: What may be asked for by opening an address (a program that can do no more, a link, a shortcut).
    BY_ADDRESS = ("status", "text", "toggle", "show", "hide")

    def api(self, name: str, req: Request, respond) -> None:
        # Another program on this computer may put text in, and so may you, typing the address: a web page may
        # not (a browser says where a request comes from; a page of the app's own is "same-origin").
        site = str(req.headers.get("sec-fetch-site", "") or "").lower()
        if site and site not in ("same-origin", "none"):
            respond(error_response(403, "forbidden"))
            return
        if req.method == "GET":
            if name not in self.BY_ADDRESS:
                respond(error_response(405, "ask with POST"))
                return
            if name == "text":
                # /__sluka__/api/bar/text?text=...&lang=ja
                respond(json_response(self.inject(req.query.get("text", ""), req.query.get("lang"))))
            elif name == "status":
                respond(json_response(self.status()))
            else:
                on = (not self.on) if name == "toggle" else (name == "show")
                respond(json_response({"on": self.set_on(on)}))
            return
        if name == "status":
            respond(json_response(self.status()))
            return
        body = req.body or b""
        if len(body) > BODY_MOST:
            respond(error_response(413, "too large"))
            return
        args: dict = {}
        if body:
            try:
                args = json.loads(body.decode("utf-8"))
            except (ValueError, UnicodeDecodeError):
                if name == "text":
                    # Plain text posted as it is.
                    respond(json_response(self.inject(body.decode("utf-8", "replace"))))
                    return
                respond(error_response(400, "not JSON"))
                return
        if not isinstance(args, dict):
            if name == "text" and isinstance(args, str):
                respond(json_response(self.inject(args)))
                return
            respond(error_response(400, "not an object"))
            return
        if name == "text":
            lang = args.get("lang")
            respond(json_response(self.inject(args.get("text", ""), lang if isinstance(lang, str) else None)))
        elif name in ("toggle", "show", "hide"):
            on = (not self.on) if name == "toggle" else (name == "show")
            respond(json_response({"on": self.set_on(on)}))
        elif name == "poll":
            self._poll(args, respond)
        elif name == "say":
            respond(self._say(args))
        elif name == "state":
            respond(self._state(args))
        elif name == "shape":
            respond(self._shape(args, req))
        elif name == "monitor":
            respond(self._monitor(args))
        else:
            respond(error_response(404, "no such bar call"))

    def _poll(self, args: dict, respond) -> None:
        self._last_poll = time.time()
        if args.get("fresh"):
            # A page just (re)started: what it needs before anything else -- its settings, the last line, and
            # whether there is an engine to read words with.
            with self._lock:
                self._queue.clear()
                waiting, self._waiting = self._waiting, []
                last = self._last_text
            for _deadline, old in waiting:
                old(json_response({"msgs": [], "superseded": True}))
            self.page_gone()
            first = [{"t": "state", "state": dict(self.state), "engine": self._engine() is not None}]
            if last:
                again = {"t": "text", "text": last, "at": time.time()}
                if self._last_lang:
                    again["lang"] = self._last_lang
                first.append(again)
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
        """What the bar's page says to the engine (hello, line, lookup, grade), passed on as a player's."""
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

    def _state(self, args: dict):
        changes = self._clean(args.get("state") if isinstance(args.get("state"), dict) else args)
        changes.pop("on", None)
        with self._lock:
            before = dict(self.state)
            self.state.update(changes)
            after = dict(self.state)
        if after != before:
            self._save_soon()
            shell = self.shell
            if shell is not None and after.get("through") != before.get("through"):
                shell.bar_through(bool(after.get("through")))
        return json_response({"ok": True, "state": after})

    @staticmethod
    def _rects(items) -> list[tuple[float, float, float, float]]:
        out = []
        for item in items if isinstance(items, list) else []:
            try:
                x, y, w, h = (float(v) for v in list(item)[:4])
            except (TypeError, ValueError):
                continue
            if all(math.isfinite(v) for v in (x, y, w, h)) and w > 0 and h > 0:
                out.append((x, y, w, h))
        return out[:24]

    def _shape(self, args: dict, req: Request):
        """The parts of the bar's window that are drawn on: the rest is see-through, and the pointer goes through it.

        ``rects`` are drawn on, ``live`` take the pointer even when clicks go through the bar (the button that
        takes them back, an open panel), ``all`` is the whole window (while the bar is moved); in the page's
        pixels, ``dpr`` of the screen's each.
        """
        try:
            dpr = float(args.get("dpr") or 1.0)
        except (TypeError, ValueError):
            dpr = 1.0
        if not math.isfinite(dpr) or not 0.25 <= dpr <= 8:
            dpr = 1.0
        shell = self.shell
        if shell is not None:
            shell.bar_shape(self._rects(args.get("rects")), self._rects(args.get("live")), bool(args.get("all")), dpr)
        return json_response({"ok": True})

    def _monitor(self, args: dict):
        """The bar was taken off its screen: the window goes to the screen the point is on (the page's pixels)."""
        shell = self.shell
        if shell is None:
            return json_response({"ok": False})
        try:
            x, y, dpr = float(args.get("x")), float(args.get("y")), float(args.get("dpr") or 1.0)
        except (TypeError, ValueError):
            return error_response(400, "no point")
        moved = shell.bar_to_monitor(x, y, dpr)
        if not isinstance(moved, dict):
            return json_response({"ok": False})
        return json_response({"ok": True, "fx": moved.get("fx"), "fy": moved.get("fy")})

    def remember_screen(self, screen: list) -> None:
        """The screen the bar's window covers, for the next start."""
        cleaned = self._clean({"monitor": screen}).get("monitor")
        if not cleaned:
            return
        with self._lock:
            if self.state.get("monitor") == cleaned:
                return
            self.state["monitor"] = cleaned
        self._save_soon()


# ---------------------------------------------------------------- the command line: sluka bar, sluka bar-text


def _ask_app(port: int, name: str, body: dict | None = None, timeout: float = 5.0):
    """A call to the app that is running, as another program would make it; None where nothing answers."""
    import urllib.error
    import urllib.request

    straight = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    request = urllib.request.Request(f"http://127.0.0.1:{port}/__sluka__/api/bar/{name}",
                                     data=json.dumps(body or {}).encode("utf-8"),
                                     headers={"Content-Type": "application/json"}, method="POST")
    try:
        with straight.open(request, timeout=timeout) as answer:
            return json.loads(answer.read(200000).decode("utf-8", "replace") or "{}")
    except urllib.error.HTTPError as err:
        return {"error": f"the app answered {err.code}"}
    except (OSError, ValueError, urllib.error.URLError):
        return None


def command_bar(config, what: str = "toggle", out=None) -> int:
    """``sluka bar [on|off|toggle]``: the floating subtitles of the app that is running."""
    import sys

    out = out or sys.stdout
    name = {"on": "show", "show": "show", "off": "hide", "hide": "hide"}.get(what, "toggle")
    answer = _ask_app(config.browser_port, name)
    if answer is None:
        print("sluka: Sluka Desktop is not running (start it first).", file=sys.stderr)
        return 1
    if "on" not in answer:
        print(f"sluka: the floating subtitles are not to be had ({answer.get('error') or 'Windows only, with its web view'}).",
              file=sys.stderr)
        return 1
    print(f"The floating subtitles are {'on' if answer['on'] else 'off'}.", file=out)
    return 0


def command_text(config, text: str, lang: str = "", out=None) -> int:
    """``sluka bar-text TEXT``: a line for the floating subtitles ("-" reads it from what is piped in)."""
    import sys

    out = out or sys.stdout
    if text == "-":
        data = sys.stdin.buffer.read() if sys.stdin is not None else b""
        text = data.decode("utf-8", "replace")
    answer = _ask_app(config.browser_port, "text", {"text": text, **({"lang": lang} if lang else {})})
    if answer is None:
        print("sluka: Sluka Desktop is not running (start it first).", file=sys.stderr)
        return 1
    if not answer.get("ok"):
        print(f"sluka: the line was not taken ({answer.get('error') or 'the floating subtitles are not to be had here'}).", file=sys.stderr)
        return 1
    if not answer.get("on"):
        print("The line is kept, but the floating subtitles are off: turn them on with the button in Sluka's window, "
              "or  sluka bar on", file=out)
    return 0
