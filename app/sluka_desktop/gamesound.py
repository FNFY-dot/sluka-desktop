# SPDX-License-Identifier: LicenseRef-Sluka
# Copyright (c) 2026 Sluka. Part of Sluka Desktop; see LICENSE.txt.
"""A game's own sound, its last minute kept in memory: for the sound of a line on the line's Anki card (ankicards.py).

Windows 10 version 2004 and later hand a program the sound of one other program -- and of the programs it started --
and of nothing else ("process loopback", as OBS's Application Audio Capture takes a game's sound): not your music, not
a call, not Sluka's own voice.  While the floating subtitles have a game hooked (the Game tab), or Sluka Vision has a
window chosen, that game's sound is taken so, in the form Sluka's clips are made from (one channel, 24 kHz, 16 bits,
as the extension keeps a video's sound: offscreen/clip-host.js), and kept for a minute (SoundRing).  Nothing of it is
written to disk or sent anywhere: a clip goes only onto a card you add, and the rest is let go of as the minute moves
on, and all of it when the game is (unhooked, another window chosen, the tab left, the app closed).

Each piece of sound is put where its own time says it was played (Windows stamps each with the clock it reads,
QueryPerformanceCounter, which ``now`` reads too): while the game is silent nothing comes, and that stretch is silence
in a clip.  A clip is cut by the times the lines came at (ankicards.py).
"""

from __future__ import annotations

import array
import ctypes
import logging
import sys
import threading
import time

log = logging.getLogger("sluka.sound")

#: The sound kept: one channel of 16-bit samples, at the rate Sluka's own clips are cut from.
RATE = 24000
WIDTH = 2
SECONDS = 60
#: A piece of sound this near where the last one ended runs on from it (the stamps of two pieces may be a sample or
#: two apart); further on, the stretch between is silence; further back, it is written where it says it belongs.
JOIN = 0.005

IS_WINDOWS = sys.platform == "win32"


# ---------------------------------------------------------------- the clock

def _qpc_clock():
    kernel32 = ctypes.WinDLL("kernel32")
    freq = ctypes.c_int64()
    kernel32.QueryPerformanceFrequency(ctypes.byref(freq))
    count = ctypes.c_int64()
    per = float(freq.value or 1)

    def read() -> float:
        kernel32.QueryPerformanceCounter(ctypes.byref(count))
        return count.value / per

    return read


#: The clock lines and sound are timed by, in seconds: Windows' performance counter, which its sound is stamped by.
now = _qpc_clock() if IS_WINDOWS else time.monotonic


# ---------------------------------------------------------------- what is kept

class SoundRing:
    """The last ``seconds`` of a game's sound, each sample where its time says it was played."""

    def __init__(self, rate: int = RATE, seconds: float = SECONDS):
        self.rate = int(rate)
        self.size = int(self.rate * seconds)
        self._buf = bytearray(self.size * WIDTH)
        self._lock = threading.Lock()
        self._origin: float | None = None  # the time sample 0 was played at
        self._end = 0  # one past the newest sample kept (counted from sample 0)
        self._start = 0  # the oldest sample kept

    def _index(self, at: float) -> int:
        return int(round((at - self._origin) * self.rate))

    def _put(self, index: int, data: bytes) -> None:
        """``data`` written from sample ``index`` on, round the ring."""
        n = len(data) // WIDTH
        if n > self.size:
            data = data[(n - self.size) * WIDTH:]
            index += n - self.size
            n = self.size
        at = (index % self.size) * WIDTH
        first = min(len(data), len(self._buf) - at)
        self._buf[at:at + first] = data[:first]
        if first < len(data):
            self._buf[:len(data) - first] = data[first:]

    def write(self, at: float, data: bytes) -> None:
        """A piece of sound that started being played at ``at`` (seconds, by ``now``'s clock)."""
        data = bytes(data[: len(data) - len(data) % WIDTH])
        n = len(data) // WIDTH
        if not n:
            return
        with self._lock:
            if self._origin is None:
                self._origin = float(at)
            index = self._index(at)
            join = int(self.rate * JOIN)
            if abs(index - self._end) <= join or (self._end == 0 and self._start == 0 and index <= 0):
                index = self._end
            elif index > self._end:
                # Silence between: nothing came, the game played nothing.
                gap = min(index - self._end, self.size)
                self._put(index - gap, bytes(gap * WIDTH))
            elif index + n <= self._end - self.size:
                return  # older than anything kept
            self._put(index, data)
            self._end = max(self._end, index + n)
            self._start = max(self._start, self._end - self.size)

    def span(self) -> tuple[float, float] | None:
        """The times of the oldest sound kept and of where the newest ends; None before any."""
        with self._lock:
            if self._origin is None:
                return None
            return self._origin + self._start / self.rate, self._origin + self._end / self.rate

    def cut(self, t_from: float, t_to: float) -> bytes:
        """The sound from ``t_from`` to ``t_to``: silence where nothing is kept for a part of it."""
        with self._lock:
            if self._origin is None or t_to <= t_from:
                return b""
            i0, i1 = self._index(t_from), self._index(t_to)
            i1 = min(i1, i0 + self.size)
            out = bytearray((i1 - i0) * WIDTH)
            have0, have1 = max(i0, self._start), min(i1, self._end)
            if have1 > have0:
                at = (have0 % self.size) * WIDTH
                length = (have1 - have0) * WIDTH
                first = min(length, len(self._buf) - at)
                piece = self._buf[at:at + first] + self._buf[: length - first]
                out[(have0 - i0) * WIDTH:(have1 - i0) * WIDTH] = piece
            return bytes(out)


# ---------------------------------------------------------------- what is done with a clip

def wav(pcm: bytes, rate: int = RATE) -> bytes:
    """A 16-bit, one-channel PCM WAV file of ``pcm``."""
    import struct

    data = bytes(pcm[: len(pcm) - len(pcm) % WIDTH])
    return (b"RIFF" + struct.pack("<I", 36 + len(data)) + b"WAVE"
            + b"fmt " + struct.pack("<IHHIIHH", 16, 1, 1, rate, rate * WIDTH, WIDTH, 16)
            + b"data" + struct.pack("<I", len(data)) + data)


def levels(pcm: bytes, rate: int = RATE, step: float = 0.02) -> list[float]:
    """How loud each ``step`` of the sound is (its RMS, 0 to 32768)."""
    samples = array.array("h")
    samples.frombytes(bytes(pcm[: len(pcm) - len(pcm) % WIDTH]))
    if sys.byteorder != "little":
        samples.byteswap()
    n = max(1, int(rate * step))
    out = []
    for i in range(0, len(samples), n):
        part = samples[i:i + n]
        out.append((sum(x * x for x in part) / len(part)) ** 0.5 if part else 0.0)
    return out


def speech_end(pcm: bytes, rate: int = RATE, step: float = 0.02, after: float = 0.45, least: float = 1.0) -> int:
    """Where to end a clip whose voice stops before its end, in samples: a little after the last stretch clearly
    louder than the quiet under it (a line said over music, or over nothing), where the quiet after it runs on.  The
    whole of it where no part stands out so (the music as loud as the voice, a clip all sound): nothing is cut then."""
    total = len(pcm) // WIDTH
    level = levels(pcm, rate, step)
    if len(level) < 10:
        return total
    ordered = sorted(level)
    floor = ordered[int(len(ordered) * 0.2)]
    peak = ordered[min(len(ordered) - 1, int(len(ordered) * 0.95))]
    if peak < 200 or peak < 2 * floor:  # silence, or nothing that stands out of what is under it
        return total
    loud = floor + (peak - floor) * 0.25
    last = max(i for i, v in enumerate(level) if v >= loud)
    end = int(((last + 1) * step + after) * rate)
    return total if end >= total else max(end, int(least * rate))


# ---------------------------------------------------------------- Windows' process loopback

class _Recorder:
    """What the game's sound is taken with: ``start()``, ``stop()``, and ``error`` once it could not be."""

    def __init__(self, pid: int, ring: SoundRing):
        self.pid = int(pid)
        self.ring = ring
        self.error = ""
        self.running = False

    def start(self) -> None:  # pragma: no cover - the platform's
        raise NotImplementedError

    def stop(self) -> None:  # pragma: no cover - the platform's
        raise NotImplementedError


if IS_WINDOWS:  # pragma: no cover - Windows' own, tried on Windows
    from ctypes import POINTER, Structure, Union, byref, c_int, c_int64, c_uint16, c_uint32, c_uint64, c_ulong, c_void_p
    from ctypes import wintypes

    from . import com

    IID_IAudioClient = "{1CB9AD4C-DBFA-4c32-B178-C2F568A703B2}"
    IID_IAudioCaptureClient = "{C8ADBD64-E71E-48a0-A4DE-185C395CD317}"
    IID_IActivateAudioInterfaceCompletionHandler = "{41D949AB-9862-444A-80F6-C261334DA5EB}"
    IID_IAgileObject = "{94EA2B94-E9CC-49E0-C0FF-EE64CA8F5B90}"
    PROCESS_LOOPBACK = "VAD\\Process_Loopback"
    AUDIOCLIENT_ACTIVATION_TYPE_PROCESS_LOOPBACK = 1
    PROCESS_LOOPBACK_MODE_INCLUDE_TARGET_PROCESS_TREE = 0
    VT_BLOB = 65
    AUDCLNT_SHAREMODE_SHARED = 0
    AUDCLNT_STREAMFLAGS_LOOPBACK = 0x00020000
    AUDCLNT_STREAMFLAGS_EVENTCALLBACK = 0x00040000
    AUDCLNT_STREAMFLAGS_SRC_DEFAULT_QUALITY = 0x08000000
    AUDCLNT_STREAMFLAGS_AUTOCONVERTPCM = 0x80000000
    AUDCLNT_BUFFERFLAGS_SILENT = 0x2
    AUDCLNT_BUFFERFLAGS_TIMESTAMP_ERROR = 0x4
    AUDCLNT_S_BUFFER_EMPTY = 0x08890001
    #: The forms the sound is asked in: as it is kept (Windows converts it); else as most sound is played, two
    #: channels at 48 kHz, made one channel at 24 kHz here.
    FORMS = ((1, RATE), (2, 2 * RATE))
    COINIT_MULTITHREADED = 0x0
    WAIT_OBJECT_0 = 0

    class _LoopbackParams(Structure):
        _fields_ = [("TargetProcessId", wintypes.DWORD), ("ProcessLoopbackMode", c_int)]

    class _ActivationParams(Structure):
        _fields_ = [("ActivationType", c_int), ("ProcessLoopbackParams", _LoopbackParams)]

    class _Blob(Structure):
        _fields_ = [("cbSize", c_ulong), ("pBlobData", c_void_p)]

    class _PropVariant(Structure):
        _fields_ = [("vt", c_uint16), ("r1", c_uint16), ("r2", c_uint16), ("r3", c_uint16), ("blob", _Blob)]

    class _WaveFormat(Structure):
        _pack_ = 1
        _fields_ = [("wFormatTag", c_uint16), ("nChannels", c_uint16), ("nSamplesPerSec", c_uint32),
                    ("nAvgBytesPerSec", c_uint32), ("nBlockAlign", c_uint16), ("wBitsPerSample", c_uint16),
                    ("cbSize", c_uint16)]

    class _Activated(com.ComObject):
        """IActivateAudioInterfaceCompletionHandler: told when Windows has made the game's sound ready to take.  Agile,
        as Windows asks of it: it is called on a thread of Windows' own."""

        IIDS = (IID_IActivateAudioInterfaceCompletionHandler, IID_IAgileObject)
        METHODS = (("completed", (c_void_p,)),)

        def __init__(self):
            self.done = threading.Event()
            self.hr = com.E_FAIL
            self.client = 0
            super().__init__()

        def completed(self, operation):
            hr = com.HRESULT()
            unknown = c_void_p()
            try:
                com.call(int(operation or 0), 3, (POINTER(com.HRESULT), POINTER(c_void_p)), byref(hr), byref(unknown),
                         what="GetActivateResult")
                self.hr = int(hr.value)
                if self.hr >= 0 and unknown.value:
                    self.client = com.query(int(unknown.value), IID_IAudioClient)
                    com.release(int(unknown.value))
            finally:
                self.done.set()

    class ProcessLoopback(_Recorder):
        """A game's sound, and its children's, from Windows (process loopback), on a thread of its own."""

        def __init__(self, pid: int, ring: SoundRing):
            super().__init__(pid, ring)
            self._stop = threading.Event()
            self._thread: threading.Thread | None = None
            self._form = (1, RATE)

        def start(self) -> None:
            self._thread = threading.Thread(target=self._run, name=f"sluka-sound-{self.pid}", daemon=True)
            self.running = True
            self._thread.start()

        def stop(self) -> None:
            self._stop.set()
            thread = self._thread
            if thread is not None and thread is not threading.current_thread():
                thread.join(timeout=2.0)
            self.running = False

        def _run(self) -> None:
            ole32 = ctypes.WinDLL("ole32")
            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            ole32.CoInitializeEx.restype = com.HRESULT
            ole32.CoInitializeEx.argtypes = (c_void_p, wintypes.DWORD)
            initialized = ole32.CoInitializeEx(None, COINIT_MULTITHREADED) >= 0
            client = capture = None
            event = None
            try:
                flags = (AUDCLNT_STREAMFLAGS_LOOPBACK | AUDCLNT_STREAMFLAGS_EVENTCALLBACK
                         | AUDCLNT_STREAMFLAGS_AUTOCONVERTPCM | AUDCLNT_STREAMFLAGS_SRC_DEFAULT_QUALITY)
                for n, (channels, rate) in enumerate(FORMS):
                    client = self._activate()
                    fmt = _WaveFormat(1, channels, rate, rate * channels * WIDTH, channels * WIDTH, 16, 0)
                    try:
                        client.call(3, (c_int, wintypes.DWORD, c_int64, c_int64, c_void_p, c_void_p), AUDCLNT_SHAREMODE_SHARED,
                                    flags, 2_000_000, 0, ctypes.addressof(fmt), None, what="IAudioClient.Initialize")
                    except com.ComError:
                        client.release()
                        client = None
                        if n + 1 == len(FORMS):
                            raise
                        continue
                    self._form = (channels, rate)
                    break
                kernel32.CreateEventW.restype = wintypes.HANDLE
                kernel32.CreateEventW.argtypes = (c_void_p, wintypes.BOOL, wintypes.BOOL, wintypes.LPCWSTR)
                event = kernel32.CreateEventW(None, False, False, None)
                if not event:
                    raise OSError(ctypes.get_last_error(), "CreateEvent")
                client.call(13, (wintypes.HANDLE,), event, what="IAudioClient.SetEventHandle")
                guid = com.GUID.parse(IID_IAudioCaptureClient)
                out = c_void_p()
                client.call(14, (POINTER(com.GUID), POINTER(c_void_p)), byref(guid), byref(out), what="IAudioClient.GetService")
                capture = com.Interface(int(out.value or 0))
                client.call(10, (), what="IAudioClient.Start")
                log.info("the sound of process %d is being kept, for Anki cards (its last %d seconds)", self.pid, SECONDS)
                kernel32.WaitForSingleObject.restype = wintypes.DWORD
                kernel32.WaitForSingleObject.argtypes = (wintypes.HANDLE, wintypes.DWORD)
                while not self._stop.is_set():
                    kernel32.WaitForSingleObject(event, 200)
                    self._drain(capture)
                client.call(11, (), what="IAudioClient.Stop")
            except Exception as err:
                self.error = str(err) or type(err).__name__
                log.warning("the sound of process %d cannot be had: %s", self.pid, self.error)
            finally:
                self.running = False
                for held in (capture, client):
                    if held is not None:
                        held.release()
                if event:
                    kernel32.CloseHandle(event)
                if initialized:
                    ole32.CoUninitialize()

        def _activate(self):
            mmdevapi = ctypes.WinDLL("mmdevapi")
            activate = mmdevapi.ActivateAudioInterfaceAsync
            activate.restype = com.HRESULT
            activate.argtypes = (wintypes.LPCWSTR, POINTER(com.GUID), POINTER(_PropVariant), c_void_p, POINTER(c_void_p))
            params = _ActivationParams(AUDIOCLIENT_ACTIVATION_TYPE_PROCESS_LOOPBACK,
                                       _LoopbackParams(self.pid, PROCESS_LOOPBACK_MODE_INCLUDE_TARGET_PROCESS_TREE))
            prop = _PropVariant(VT_BLOB, 0, 0, 0, _Blob(ctypes.sizeof(params), ctypes.addressof(params)))
            handler = _Activated()
            operation = c_void_p()
            iid = com.GUID.parse(IID_IAudioClient)
            try:
                hr = activate(PROCESS_LOOPBACK, byref(iid), byref(prop), handler.ptr, byref(operation))
                if hr < 0:
                    raise com.ComError(hr, "ActivateAudioInterfaceAsync (Windows 10 version 2004 or later is needed)")
                if not handler.done.wait(10.0):
                    raise TimeoutError("Windows did not make the game's sound ready")
                if handler.hr < 0 or not handler.client:
                    raise com.ComError(handler.hr, "the game's sound")
                return com.Interface(handler.client)
            finally:
                if operation.value:
                    com.release(int(operation.value))
                handler.drop()

        def _drain(self, capture) -> None:
            data = POINTER(ctypes.c_ubyte)()
            frames = c_uint32()
            flags = wintypes.DWORD()
            device = c_uint64()
            qpc = c_uint64()
            size = c_uint32()
            while True:
                capture.call(5, (POINTER(c_uint32),), byref(size), what="GetNextPacketSize")
                if not size.value:
                    return
                hr = capture.call(3, (POINTER(POINTER(ctypes.c_ubyte)), POINTER(c_uint32), POINTER(wintypes.DWORD),
                                      POINTER(c_uint64), POINTER(c_uint64)),
                                  byref(data), byref(frames), byref(flags), byref(device), byref(qpc), what="GetBuffer")
                if hr == AUDCLNT_S_BUFFER_EMPTY:
                    return
                n = int(frames.value)
                channels, rate = self._form
                try:
                    if n:
                        if flags.value & AUDCLNT_BUFFERFLAGS_SILENT or not data:
                            raw = bytes(n * channels * WIDTH)
                        else:
                            raw = ctypes.string_at(data, n * channels * WIDTH)
                        piece = raw if (channels, rate) == (1, RATE) else _one_channel(raw, channels, rate // RATE)
                        stamp = qpc.value / 1e7 if qpc.value and not flags.value & AUDCLNT_BUFFERFLAGS_TIMESTAMP_ERROR else now() - n / rate
                        self.ring.write(stamp, piece)
                finally:
                    capture.call(4, (c_uint32,), n, what="ReleaseBuffer")


def _one_channel(raw: bytes, channels: int, step: int) -> bytes:
    """Sound of ``channels`` channels at ``step`` times the rate kept, as it is kept: one channel, each sample the mean
    of the ``channels * step`` it stands for."""
    samples = array.array("h")
    samples.frombytes(raw[: len(raw) - len(raw) % (WIDTH * channels * step)])
    if sys.byteorder != "little":
        samples.byteswap()
    k = channels * step
    out = array.array("h", (sum(samples[i:i + k]) // k for i in range(0, len(samples), k)))
    if sys.byteorder != "little":
        out.byteswap()
    return out.tobytes()


def _default_recorder(pid: int, ring: SoundRing):
    if not IS_WINDOWS:
        return None
    return ProcessLoopback(pid, ring)


# ---------------------------------------------------------------- whose sound is kept

class GameSound:
    """Whose sound is kept, and its ring: the game the floating subtitles have hooked (``"bar"``), and the program of
    the window Sluka Vision reads (``"vision"``) -- one recorder for each program, while anything asks for it."""

    def __init__(self, factory=None, rate: int = RATE, seconds: float = SECONDS):
        self._factory = factory or _default_recorder
        self.rate = rate
        self.seconds = seconds
        self._lock = threading.Lock()
        self._holders: dict[str, int] = {}
        self._recorders: dict[int, object] = {}
        self._failed: dict[int, str] = {}

    def follow(self, who: str, pid: int) -> None:
        """``who`` (``"bar"``, ``"vision"``) wants the sound of process ``pid`` kept; 0 or less: no longer any."""
        pid = int(pid or 0)
        start = None
        with self._lock:
            if pid <= 0:
                self._holders.pop(who, None)
            else:
                self._holders[who] = pid
            wanted = set(self._holders.values())
            stop = [rec for p, rec in self._recorders.items() if p not in wanted]
            self._recorders = {p: rec for p, rec in self._recorders.items() if p in wanted}
            if pid > 0 and pid not in self._recorders and pid not in self._failed:
                start = self._factory(pid, SoundRing(self.rate, self.seconds))
                if start is not None:
                    self._recorders[pid] = start
        for rec in stop:
            try:
                rec.stop()
            except Exception:
                log.exception("a game's sound could not be let go of")
        if start is not None:
            try:
                start.start()
            except Exception as err:
                log.warning("the sound of process %d cannot be had: %s", pid, err)
                with self._lock:
                    self._recorders.pop(pid, None)
                    self._failed[pid] = str(err)

    def leave(self, who: str) -> None:
        self.follow(who, 0)

    def ring(self, pid: int) -> SoundRing | None:
        """The sound kept of process ``pid``: None where it is not kept (not asked for, or it could not be had)."""
        with self._lock:
            rec = self._recorders.get(int(pid or 0))
        if rec is None:
            return None
        if getattr(rec, "error", ""):
            with self._lock:
                self._failed[int(pid)] = rec.error
                self._recorders.pop(int(pid), None)
            return None
        return rec.ring

    def error(self, pid: int) -> str:
        with self._lock:
            return self._failed.get(int(pid or 0), "")

    def status(self) -> dict:
        with self._lock:
            return {"kept": sorted(self._recorders), "holders": dict(self._holders), "failed": dict(self._failed)}

    def close(self) -> None:
        with self._lock:
            recs, self._recorders, self._holders = list(self._recorders.values()), {}, {}
        for rec in recs:
            try:
                rec.stop()
            except Exception:
                log.exception("a game's sound could not be let go of")
