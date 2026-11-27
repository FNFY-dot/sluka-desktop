"""The Anki cards of a game's lines (ankicards.py, gamesound.py): the game's sound kept by the time each piece was
played, a line's clip cut from it -- from a little before the line came to where the next came, or to where its
voice stops -- the lines either side, the picture taken as the word is picked."""

from __future__ import annotations

import base64
import json
import math
import struct

from fakes import APP  # noqa: F401  (puts the app on the path)
from sluka_desktop import ankicards, gamesound

RATE = gamesound.RATE


def tone(seconds: float, loud: int = 10000, hz: float = 220.0) -> bytes:
    n = int(seconds * RATE)
    return struct.pack(f"<{n}h", *(int(loud * math.sin(2 * math.pi * hz * i / RATE)) for i in range(n)))


def hush(seconds: float) -> bytes:
    return bytes(int(seconds * RATE) * 2)


def loudness(pcm: bytes) -> float:
    n = len(pcm) // 2
    values = struct.unpack(f"<{n}h", pcm)
    return max((abs(v) for v in values), default=0)


def test_the_ring_keeps_each_piece_where_its_time_says():
    ring = gamesound.SoundRing(seconds=2)
    assert ring.span() is None and ring.cut(0, 1) == b""
    ring.write(10.0, tone(1.0))
    ring.write(11.5, tone(0.2))  # half a second of nothing between: silence there
    assert ring.span() == (10.0, 11.7)
    got = ring.cut(10.9, 11.6)
    assert len(got) == int(0.7 * RATE) * 2
    assert loudness(got[: int(0.1 * RATE) * 2]) > 5000
    assert loudness(got[int(0.12 * RATE) * 2: int(0.58 * RATE) * 2]) == 0
    assert loudness(got[int(0.62 * RATE) * 2:]) > 5000
    # Run on past its two seconds: what is older is gone, silence in a clip.
    ring.write(11.7, tone(1.5))
    start, end = ring.span()
    assert round(end - start, 3) == 2.0
    assert loudness(ring.cut(10.0, 11.0)[: int(0.5 * RATE) * 2]) == 0
    # A piece stamped a sample or two off where the last ended runs on from it.
    ring = gamesound.SoundRing(seconds=5)
    ring.write(1.0, tone(0.5))
    ring.write(1.5 + 2 / RATE, tone(0.5))
    assert ring.span() == (1.0, 2.0)


def test_where_a_voice_stops():
    # Said over nothing: a little after the voice.
    pcm = tone(1.0) + hush(2.0)
    assert abs(gamesound.speech_end(pcm) / RATE - 1.45) < 0.03
    # Said over music: the same.
    music = tone(3.0, loud=1200, hz=330)
    voice = tone(1.0) + hush(2.0)
    mixed = struct.pack(f"<{len(music) // 2}h", *(max(-32768, min(32767, a + b)) for a, b in zip(
        struct.unpack(f"<{len(music) // 2}h", music), struct.unpack(f"<{len(voice) // 2}h", voice))))
    assert abs(gamesound.speech_end(mixed) / RATE - 1.45) < 0.03
    # Nothing standing out (music alone, or silence): nothing cut.
    assert gamesound.speech_end(tone(3.0, loud=3000)) == 3 * RATE
    assert gamesound.speech_end(hush(3.0)) == 3 * RATE


def test_a_clip_is_a_wav_anki_plays():
    data = gamesound.wav(tone(0.1))
    assert data[:4] == b"RIFF" and data[8:12] == b"WAVE" and len(data) == 44 + int(0.1 * RATE) * 2
    assert struct.unpack("<HHII", data[20:32]) == (1, 1, RATE, RATE * 2)


class FakeSound:
    def __init__(self, rings):
        self.rings = rings
        self.followed = []

    def follow(self, who, pid):
        self.followed.append((who, pid))

    def ring(self, pid):
        return self.rings.get(pid)

    def error(self, pid):
        return "" if pid in self.rings else "no process loopback here"

    def status(self):
        return {}

    def close(self):
        pass


class Clock:
    def __init__(self, t):
        self.t = t

    def __call__(self):
        return self.t

    def sleep(self, s):
        self.t += s


GAME = {"pid": 4242, "pids": [4242], "title": "桜の詩", "exe": "sakura.exe"}


def cards_with(ring, clock, pictures=None):
    pictures = pictures if pictures is not None else []

    def picture(hwnd, how, area):
        pictures.append((hwnd, how, area))
        return b"BM-the-game"

    class G:
        class procs:
            @staticmethod
            def windows_of(pids):
                return [{"hwnd": 77, "pid": 4242, "minimized": False}]

        notes = []

        def note(self, text, level="info"):
            self.notes.append(text)

    return ankicards.Cards(G(), sound=FakeSound({4242: ring} if ring else {}), picture=picture, clock=clock,
                           sleep=clock.sleep)


def test_a_lines_clip_and_picture():
    ring = gamesound.SoundRing()
    # The first line said from 10.0 to 12.0, then quiet till the second line comes at 14.0, said to 15.0.
    ring.write(9.0, hush(1.0) + tone(2.0) + hush(2.0) + tone(1.0) + hush(1.0))
    clock = Clock(16.0)
    pictures = []
    cards = cards_with(ring, clock, pictures)
    cards.line("bar", "安芸倫也", GAME, at=8.0)
    cards.line("bar", "ある春の日", GAME, at=10.0)
    cards.line("bar", "俺は運命と出会い", GAME, at=14.0)
    cards.line("bar", "a line from elsewhere", None, at=15.5)
    got = cards.lines_for({"player": "bar", "text": "ある春の日", "picture": True})
    assert got["found"] and got["sound"] and got["picture"] and got["title"] == "桜の詩"
    assert got["before"] == ["安芸倫也"] and got["after"] == ["俺は運命と出会い"]
    # The picture is the game's window, as it is now (its process's window, found by its pid).
    assert pictures == [(77, "window", None)]
    media = cards.media_for({"ticket": got["ticket"], "audio": True, "picture": True})
    assert base64.b64decode(media["picture"]["bmp"]) == b"BM-the-game"
    wav = base64.b64decode(media["audio"]["wav"])
    # From a little before the line came to a little after its voice stopped -- not on to the next line's.
    assert abs(media["audio"]["seconds"] - (0.25 + 2.0 + 0.45)) < 0.05 and media["lines"] == ["ある春の日"]
    assert loudness(wav[44 + int(0.3 * RATE) * 2:]) > 5000
    # With the lines either side: from the line before to the end of the line after.
    media = cards.media_for({"ticket": got["ticket"], "audio": True, "context": True})
    assert media["lines"] == ["安芸倫也", "ある春の日", "俺は運命と出会い"] and media["first"] == -1
    assert media["picture"] is None and 7.4 < media["audio"]["seconds"] < 7.8
    # Text from elsewhere has no game: no sound, no picture.
    other = cards.lines_for({"player": "bar", "text": "a line from elsewhere", "picture": True})
    assert other["found"] and not other["sound"] and not other["picture"]
    # A line not there is not found; one only spaced otherwise is.
    assert cards.lines_for({"player": "bar", "text": "never shown"}) == {"ok": True, "found": False}
    assert cards.lines_for({"player": "bar", "text": "a  line from\nelsewhere"})["found"]
    assert cards.media_for({"ticket": "c999"}) == {"ok": False, "error": "gone"}


def test_the_last_lines_clip_waits_for_its_voice():
    ring = gamesound.SoundRing()
    clock = Clock(21.0)
    cards = cards_with(ring, clock)
    cards.line("bar", "ある春の日", GAME, at=20.0)
    ring.write(19.0, hush(1.0) + tone(1.0))  # picked a second into the line, still being said
    got = cards.lines_for({"player": "bar", "text": "ある春の日"})
    played = {"until": 21.0}

    def sleep(s):  # the game plays on as the clip waits: the voice to 23.0, then quiet
        clock.t += s
        while played["until"] < clock.t:
            piece = tone(0.25) if played["until"] < 23.0 else hush(0.25)
            ring.write(played["until"], piece)
            played["until"] += 0.25

    cards._sleep = sleep
    media = cards.media_for({"ticket": got["ticket"], "audio": True})
    assert abs(media["audio"]["seconds"] - (0.25 + 3.0 + 0.45)) < 0.05
    assert clock.t < 25.0  # it waited for the quiet after the voice, not for LINE_MOST
    # The next line coming ends the clip there, even while the voice goes on.
    clock2 = Clock(31.0)
    ring2 = gamesound.SoundRing()
    ring2.write(29.0, hush(1.0) + tone(1.0))
    cards2 = cards_with(ring2, clock2)
    cards2.line("vision", "一行目", {**GAME, "hwnd": 5}, at=30.0, read=7)
    got2 = cards2.lines_for({"player": "vision", "read": 7})
    assert got2["found"]

    def sleep2(s):
        clock2.t += s
        ring2.write(clock2.t - s, tone(s))
        if clock2.t >= 32.0 and len(cards2._lines["vision"]) == 1:
            cards2.line("vision", "二行目", {**GAME, "hwnd": 5}, at=32.0, read=8)

    cards2._sleep = sleep2
    media2 = cards2.media_for({"ticket": got2["ticket"], "audio": True})
    assert abs(media2["audio"]["seconds"] - 2.25) < 0.05


def test_a_game_whose_sound_cannot_be_had():
    clock = Clock(5.0)
    cards = cards_with(None, clock)
    cards.line("bar", "ある春の日", GAME, at=4.0)
    got = cards.lines_for({"player": "bar", "text": "ある春の日"})
    assert got["found"] and not got["sound"] and got["sound_error"] == "no process loopback here"
    assert cards.media_for({"ticket": got["ticket"], "audio": True}) == {"ok": True, "audio": None, "picture": None}
    # Said once in the menu, not at every pick.
    cards.lines_for({"player": "bar", "text": "ある春の日"})
    assert len(cards.g.notes) == 1 and "without its sound" in cards.g.notes[0]


def test_whose_sound_is_kept():
    made = []

    class Rec:
        def __init__(self, pid, ring):
            self.pid, self.ring, self.error, self.stopped = pid, ring, "", False
            made.append(self)

        def start(self):
            pass

        def stop(self):
            self.stopped = True

    sound = gamesound.GameSound(factory=Rec)
    sound.follow("bar", 4242)
    sound.follow("vision", 4242)  # the same game: one recorder
    assert len(made) == 1 and sound.ring(4242) is made[0].ring
    sound.leave("bar")
    assert not made[0].stopped  # Sluka Vision still reads its window
    sound.follow("vision", 5151)
    assert made[0].stopped and sound.ring(4242) is None and len(made) == 2
    # One that could not be had is not tried again, and says why.
    made[1].error = "E_NOTIMPL"
    assert sound.ring(5151) is None and sound.error(5151) == "E_NOTIMPL"
    sound.follow("vision", 0)
    sound.follow("vision", 5151)
    assert len(made) == 2
    sound.close()
    assert sound.status()["kept"] == []


def test_visions_lines_are_joined_as_its_page_joins_them():
    lines = [{"p": 0, "text": "戻るのも面倒なんでオマエやっ"}, {"p": 0, "text": "といてくれ。"}, {"p": 1, "text": "Lv"},
             {"p": 1, "text": "99"}]
    assert ankicards.join_lines(lines) == "戻るのも面倒なんでオマエやっといてくれ。\nLv 99"


def test_mpvs_file_and_frame_for_a_card(tmp_path, monkeypatch):
    """A word picked in mpv: the file it plays kept for that player (never handed to the engine), read a range at a
    time; the frame the script took handed over once and deleted; nothing else in the temporary folder."""
    import tempfile
    import types

    from sluka_desktop import mpvbridge
    from sluka_desktop.host import Request

    config = types.SimpleNamespace(mpv_socket_dir=str(tmp_path / "sockets"), mpv_dir=tmp_path / "mpv")
    bridge = mpvbridge.MpvBridge(config, players=False)
    film = tmp_path / "a film.mkv"
    film.write_bytes(bytes(range(256)) * 4)
    player = types.SimpleNamespace(key="mpv:1", media="")
    bridge.players["mpv:1"] = player
    offered = []
    bridge._offer = offered.append
    bridge.incoming(player, {"t": "anki", "key": "運命", "path": str(film)})
    assert player.media == str(film) and "path" not in offered[-1]["msg"]
    bridge.incoming(player, {"t": "anki", "key": "x", "path": str(tmp_path / "none.mkv")})
    assert player.media == str(film)  # (not a file: not taken)

    answers = []

    def ask(name, method="GET", query=None, headers=None, body=b""):
        bridge.api(name, Request(method=method, path="/", query=query or {}, headers=headers or {}, body=body), answers.append)
        return answers[-1]

    got = ask("file", query={"player": "mpv:1"}, headers={"range": "bytes=10-19", "sec-fetch-site": "same-origin"})
    assert got.status == 206 and got.file == (str(film), 10, 10) and got.headers["Content-Range"] == "bytes 10-19/1024"
    assert ask("file", query={"player": "mpv:1"}).status == 200
    assert ask("file", query={"player": "mpv:2"}).status == 404
    assert ask("file", query={"player": "mpv:1"}, headers={"sec-fetch-site": "cross-site"}).status == 403

    monkeypatch.setattr(tempfile, "gettempdir", lambda: str(tmp_path))
    (tmp_path / "sluka-shot-12-3.jpg").write_bytes(b"\xff\xd8\xff-frame")
    (tmp_path / "secret.txt").write_text("no")
    shot = ask("shot", method="POST", body=json.dumps({"name": "sluka-shot-12-3.jpg"}).encode())
    assert json.loads(shot.body) == {"ok": True, "b64": base64.b64encode(b"\xff\xd8\xff-frame").decode()}
    assert not (tmp_path / "sluka-shot-12-3.jpg").exists()
    for name in ("secret.txt", "../secret.txt", "sluka-shot-1-1.jpg/../../secret.txt"):
        assert json.loads(ask("shot", method="POST", body=json.dumps({"name": name}).encode()).body)["ok"] is False
    assert (tmp_path / "secret.txt").exists()
