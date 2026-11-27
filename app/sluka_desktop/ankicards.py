# SPDX-License-Identifier: LicenseRef-Sluka
# Copyright (c) 2026 Sluka. Part of Sluka Desktop; see LICENSE.txt.
"""The Anki cards of a game's lines: the sound and the picture of a line picked in the floating subtitles or in Sluka
Vision, for its card.

The card itself is Sluka's: the panel's Anki button (or its key) asks Sluka's engine (web/mpv-engine.js), which puts
the word on the list of picks with its sentence (MSG.ANKI_PICK) and then its sound and picture (MSG.ANKI_MEDIA), and
the extension's own round makes the card in Anki -- with your note type, into your deck, with what Settings → Anki
says goes on it: the clip, the picture (the picture again where the video is chosen, as the extension puts it where a
video cannot be made), the lines before and after.  What this side adds is what only it knows:

*   the lines, each with the time it came (``line``): the floating subtitles' from the game hooked (gametext.py), and
    each of Sluka Vision's reads (vision.py), whose text came a little before the read;
*   the game's own sound, its last minute (gamesound.py): kept while the game is hooked, or its window is the one
    Sluka Vision reads (``follow``);
*   a picture of the game's window (gamepicture.py), taken as the word is picked.

The engine asks for them in two calls: ``cards/lines`` as the word is picked -- which line it was, the lines either
side, whether there is sound, and the picture, taken then -- and ``cards/media`` for the clip, which may have to wait
for the rest of the line's sound to be played: from a little before the line came to where the next one came, or,
where none has yet, to where its voice stops (gamesound.speech_end), LINE_MOST at most, WAIT_MOST waited at most.
"""

from __future__ import annotations

import base64
import collections
import itertools
import json
import logging
import threading
import time

from . import gamepicture, gamesound
from .host import Request, error_response, json_response

log = logging.getLogger("sluka.cards")

WHO = ("bar", "vision")
LINES_KEPT = 40
#: Around a line's own times, as the extension pads a subtitle's (lib/clip-range.js).
PAD_BEFORE = 0.25
PAD_AFTER = 0.45
CLIP_MAX = 30.0
#: The longest a line's sound runs where the next line has not come, and how much of it a line picked at once waits
#: for; the longest the clip waits for sound still to come.
LINE_MOST = 12.0
LINE_LEAST = 2.0
WAIT_MOST = 8.0
#: How long the voice must have stopped, at the end of what is kept, to be taken as over.
QUIET_AFTER = 0.8
#: A read of Sluka Vision's comes this long after its text came, besides the reading itself (ocrd.py SETTLE).
VISION_LEAD = 0.8
TICKETS_KEPT = 16
BODY_MOST = 64 * 1024
TEXT_MOST = 4000


def _flat(text: str) -> str:
    return " ".join(str(text or "").split())


def _cjk(ch: str) -> bool:
    code = ord(ch) if ch else 0
    return (0x3000 <= code <= 0x30FF or 0x3400 <= code <= 0x9FFF or 0xF900 <= code <= 0xFAFF or 0xFF00 <= code <= 0xFFEF
            or 0xAC00 <= code <= 0xD7AF)


def join_lines(lines: list) -> str:
    """Sluka Vision's lines as its page joins them for the engine (web/vision.js joinLines): a paragraph's lines run on
    (with a space between letters that are not Chinese, Japanese or Korean), paragraphs a line each."""
    text = ""
    prev = None
    for ln in lines:
        piece = str(ln.get("text") or "")
        if prev is not None:
            if prev.get("p") != ln.get("p"):
                text += "\n"
            elif not (text and piece and _cjk(text[-1]) and _cjk(piece[0])):
                text += " "
        text += piece
        prev = ln
    return text


class Cards:
    """The lines of the floating subtitles and of Sluka Vision, with their times; the games' sound; their pictures."""

    def __init__(self, games=None, sound=None, picture=None, clock=None, sleep=time.sleep):
        self.g = games
        self.sound = sound if sound is not None else gamesound.GameSound()
        self._picture = picture or gamepicture.take
        self.clock = clock or gamesound.now
        self._sleep = sleep
        self._lock = threading.Lock()
        self._lines = {who: collections.deque(maxlen=LINES_KEPT) for who in WHO}
        self._tickets: "collections.OrderedDict[str, dict]" = collections.OrderedDict()
        self._seq = itertools.count(1)
        self._following = {who: 0 for who in WHO}

    # ------------------------------------------------------------------ what this side is told

    def line(self, who: str, text: str, game: dict | None = None, at: float | None = None, read: int | None = None) -> None:
        """A line shown in the floating subtitles (``"bar"``) or read by Sluka Vision (``"vision"``), with the game it
        came from (``{"pid", "pids", "hwnd", "title", "exe"}``, None for text from elsewhere) and when it came."""
        if who not in self._lines:
            return
        entry = {"text": str(text or "")[:TEXT_MOST], "at": self.clock() if at is None else float(at),
                 "game": dict(game) if game else None, "read": read}
        with self._lock:
            self._lines[who].append(entry)

    def follow(self, who: str, pid: int) -> None:
        """The game whose sound is kept for ``who``: process ``pid`` (0: none any more)."""
        pid = int(pid or 0)
        with self._lock:
            if self._following.get(who) == pid:
                return
            self._following[who] = pid
        self.sound.follow(who, pid)

    def status(self) -> dict:
        with self._lock:
            lines = {who: len(q) for who, q in self._lines.items()}
            following = dict(self._following)
        return {"lines": lines, "following": following, "sound": self.sound.status()}

    def close(self) -> None:
        with self._lock:
            self._following = {who: 0 for who in WHO}
        self.sound.close()

    # ------------------------------------------------------------------ the engine's calls

    def api(self, name: str, req: Request, respond) -> None:
        """The engine's calls (cards/...): only the app's own pages may make them."""
        site = str(req.headers.get("sec-fetch-site", "") or "").lower()
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
        if name == "lines":
            respond(json_response(self.lines_for(args)))
        elif name == "media":
            threading.Thread(target=lambda: respond(json_response(self.media_for(args))), name="sluka-card-media",
                             daemon=True).start()
        elif name == "status":
            respond(json_response(self.status()))
        else:
            respond(error_response(404, "no such call"))

    def _find(self, who: str, args: dict) -> tuple[list, int | None]:
        with self._lock:
            lines = list(self._lines.get(who) or ())
        if not lines:
            return lines, None
        read = args.get("read")
        if who == "vision" and isinstance(read, int) and not isinstance(read, bool):
            for i in range(len(lines) - 1, -1, -1):
                if lines[i].get("read") == read:
                    return lines, i
        text = str(args.get("text") or "")
        if text:
            for match in (lambda t: t == text, lambda t: _flat(t) == _flat(text)):
                for i in range(len(lines) - 1, -1, -1):
                    if match(lines[i]["text"]):
                        return lines, i
            return lines, None
        return lines, len(lines) - 1

    def lines_for(self, args: dict) -> dict:
        """The line a word was picked on (``player``, its ``text``, Sluka Vision's ``read``), the lines either side,
        whether its game's sound is kept, and -- where ``picture`` is asked for -- the game's window as it is now."""
        who = str(args.get("player") or "")
        if who not in self._lines:
            return {"ok": True, "found": False}
        lines, i = self._find(who, args)
        if i is None:
            return {"ok": True, "found": False}
        entry = lines[i]
        game = entry.get("game") or None
        pid = int(game.get("pid") or 0) if game else 0
        ring = self.sound.ring(pid) if pid else None
        picture = None
        if game and args.get("picture"):
            picture = self._take_picture(who, game)
        ticket = f"c{next(self._seq)}"
        with self._lock:
            self._tickets[ticket] = {"who": who, "lines": lines, "index": i, "pid": pid, "picture": picture,
                                     "at": self.clock()}
            while len(self._tickets) > TICKETS_KEPT:
                self._tickets.popitem(last=False)
        out = {"ok": True, "found": True, "ticket": ticket, "index": i, "sound": ring is not None,
               "picture": picture is not None, "title": (game or {}).get("title") or (game or {}).get("exe") or "",
               "before": [ln["text"] for ln in lines[max(0, i - 1):i]], "after": [ln["text"] for ln in lines[i + 1:i + 2]]}
        if pid and ring is None:
            why = self.sound.error(pid)
            if why:
                out["sound_error"] = why
                self._say_once(pid, why)
        return out

    def _say_once(self, pid: int, why: str) -> None:
        """The game text menu told, once a game, that its cards go without its sound."""
        with self._lock:
            told = getattr(self, "_told", set())
            self._told = told
            if pid in told:
                return
            told.add(pid)
        note = getattr(self.g, "note", None)
        if callable(note):
            note("Anki cards of this game go without its sound: Windows here cannot give Sluka one program's sound "
                 f"(Windows 10 version 2004 or later can). ({why})", "warn")

    def _take_picture(self, who: str, game: dict) -> bytes | None:
        hwnd = int(game.get("hwnd") or 0)
        how, area = "window", None
        if who == "vision" and self.g is not None:
            vision = getattr(self.g, "vision", None)
            # The game stopped where it is (Sluka Vision's keys): the picture kept is the one looked at -- and a paused
            # game's own window is not asked for one.
            still = vision.still() if vision is not None and hasattr(vision, "still") else None
            if still:
                return gamepicture.smaller(still)
            if vision is not None and getattr(vision, "capture_how", "") == "screen":
                how, area = "screen", getattr(vision, "area", None)
        if not hwnd and self.g is not None:
            pids = game.get("pids") or [game.get("pid")]
            try:
                windows = [w for w in self.g.procs.windows_of([p for p in pids if p]) if not w.get("minimized")]
            except Exception:
                windows = []
            hwnd = int(windows[0]["hwnd"]) if windows else 0
        if not hwnd and not area:
            return None
        return self._picture(hwnd, how, area)

    def media_for(self, args: dict) -> dict:
        """The picked line's sound (``audio``: from a little before it came to its end, or with the lines either side
        where ``context`` is asked for) and the picture taken as it was picked (``picture``)."""
        with self._lock:
            ticket = self._tickets.get(str(args.get("ticket") or ""))
        if ticket is None:
            return {"ok": False, "error": "gone"}
        out: dict = {"ok": True, "audio": None, "picture": None}
        if args.get("picture") and ticket["picture"]:
            out["picture"] = {"bmp": base64.b64encode(ticket["picture"]).decode("ascii")}
        if args.get("audio") and ticket["pid"]:
            ring = self.sound.ring(ticket["pid"])
            if ring is not None:
                clip = self._clip(ticket, ring, bool(args.get("context")))
                if clip is not None:
                    pcm, first, last = clip
                    out["audio"] = {"wav": base64.b64encode(gamesound.wav(pcm, ring.rate)).decode("ascii"),
                                    "rate": ring.rate, "seconds": round(len(pcm) / gamesound.WIDTH / ring.rate, 3)}
                    out["lines"] = [ln["text"] for ln in ticket["lines"][first:last + 1]]
                    out["first"] = first - ticket["index"]
        return out

    def _next_at(self, who: str, after: float) -> float | None:
        """When the first line after ``after`` came, of ``who``'s (it may have come since the word was picked)."""
        with self._lock:
            for entry in self._lines.get(who) or ():
                if entry["at"] > after + 1e-6:
                    return entry["at"]
        return None

    def _clip(self, ticket: dict, ring, context: bool):
        lines, i = ticket["lines"], ticket["index"]
        first = last = i
        if context:
            if i > 0 and lines[i]["at"] - lines[i - 1]["at"] <= CLIP_MAX / 2:
                first = i - 1
            if i + 1 < len(lines):
                last = i + 1
        start = lines[first]["at"] - PAD_BEFORE
        last_at = lines[last]["at"]
        end = lines[last + 1]["at"] if last + 1 < len(lines) else None
        waited_from = self.clock()
        while end is None:
            # The last line's own end: where the next came, since; where its voice stops; LINE_MOST at most.
            came = self._next_at(ticket["who"], last_at)
            if came is not None:
                end = came
                break
            kept = ring.span()
            newest = kept[1] if kept else self.clock()
            if newest >= last_at + LINE_MOST:
                end = last_at + LINE_MOST
                break
            if newest >= last_at + LINE_LEAST:
                heard = ring.cut(last_at, newest)
                stop = gamesound.speech_end(heard, ring.rate, after=PAD_AFTER)
                said = len(heard) // gamesound.WIDTH
                if stop < said and (said - stop) / ring.rate >= QUIET_AFTER - PAD_AFTER:
                    end = last_at + stop / ring.rate
                    break
            if self.clock() - waited_from >= WAIT_MOST:
                end = newest
                break
            self._sleep(0.25)
        end = min(end, start + CLIP_MAX)
        if end - start < 0.3:
            return None
        kept = ring.span()
        if not kept or kept[1] <= start or kept[0] >= end:
            return None
        pcm = ring.cut(start, end)
        # Where the voice stopped well before the next line came: the quiet after it left out.
        tail_from = max(0, int((last_at - start) * ring.rate)) * gamesound.WIDTH
        stop = gamesound.speech_end(pcm[tail_from:], ring.rate, after=PAD_AFTER)
        pcm = pcm[: tail_from + stop * gamesound.WIDTH]
        return pcm, first, last
