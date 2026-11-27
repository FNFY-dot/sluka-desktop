"""The stand-ins for the screen reader (ocrd.py), for the tests: LunaTranslator's CVUtils.dll and NativeUtils.dll (two
libraries built with gcc, fake_cvutils.c and fake_nativeutils.c), Google (a small web server) and Tor (a SOCKS5 proxy), and a pretend screen (desktop.json and screen.bmp in a folder, which
ocrd.py's FileDesktop reads).

What a picture "says" is written in its first row (fake_ocr.h): ``Screen.text(box, lines)`` writes it, and fills the
rest of the box with a colour of its own for each text, so that a new text is a change on the screen.
"""

from __future__ import annotations

import http.server
import json
import math
import os
import socket
import struct
import subprocess
import sys
import threading
import zlib
from pathlib import Path

HERE = Path(__file__).parent
APP = os.environ.get("SLUKA_APP", "/home/claude/work/sluka-desktop/app")
if APP not in sys.path:
    sys.path.insert(0, APP)

from sluka_desktop import ocrd  # noqa: E402

#: Sluka's own OCR's files, in the engine folder's ocr folder (empty stand-ins: the library is the stand-in).
OCR_FILES = ("CVUtils.dll", "NativeUtils.dll", "onnxruntime.dll", "model/det.onnx", "model/rec.onnx", "model/dict.txt")


def build(out_dir: Path) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    built = {}
    for name in ("cvutils", "nativeutils"):
        target = out_dir / f"fake_{name}.so"
        subprocess.run(["gcc", "-shared", "-fPIC", "-O1", "-Wall", "-Wno-unused-function", "-o", str(target),
                        str(HERE / f"fake_{name}.c")], check=True)
        built[name] = str(target)
    return built


def make_ocr_engine(folder: Path) -> Path:
    """An engine folder with the OCR's files (empty) and LunaSubprocess64.exe (empty)."""
    for name in OCR_FILES + ("LunaSubprocess64.exe",):
        path = folder / ("ocr/" + name if name in OCR_FILES else name)
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            path.write_bytes(b"")
    return folder


def ocrd_args(libs: dict, desktop: Path, lens_url: str = "") -> list[str]:
    args = ["--desktop", str(desktop), "--cvutils", libs["cvutils"], "--nativeutils", libs["nativeutils"]]
    if lens_url:
        args += ["--lens-url", lens_url]
    return args


# ---------------------------------------------------------------- the pretend screen


class Screen:
    """A pretend screen of w x h: windows, which is in front, what each box says."""

    def __init__(self, folder: Path, w: int = 1600, h: int = 900):
        self.folder = folder
        folder.mkdir(parents=True, exist_ok=True)
        self.w, self.h = w, h
        self.pixels = bytearray(b"\x20\x20\x20\x00" * (w * h))
        self.state = {"windows": [], "foreground": 0, "screen": "screen.bmp", "select": None, "keys": [], "blank": []}
        self.save()

    def save(self) -> None:
        # Written aside and moved into place: the reader never sees half a screen.
        img = ocrd.Image(self.w, self.h, bytes(self.pixels))
        partial = self.folder / "screen.bmp.new"
        partial.write_bytes(ocrd.to_bmp(img))
        os.replace(partial, self.folder / "screen.bmp")
        partial = self.folder / "desktop.json.new"
        partial.write_text(json.dumps(self.state), encoding="utf-8")
        os.replace(partial, self.folder / "desktop.json")

    def window(self, hwnd: int, pid: int, client, title="", klass="GameWindow", **more) -> dict:
        found = next((w for w in self.state["windows"] if w["hwnd"] == hwnd), None)
        if found is None:
            found = {"hwnd": hwnd}
            self.state["windows"].append(found)
        found.update(pid=pid, client=list(client), title=title, **{"class": klass}, **more)
        self.save()
        return found

    def put(self, **changes) -> None:
        self.state.update(changes)
        self.save()

    def freeze(self, *ways) -> None:
        """The game's own window keeps the picture the screen shows now, taken those ways ("dc": from its device
        context, "print": as Windows itself draws it), whatever the screen shows from then on -- as the picture of a
        game that went on to draw past Windows does; none given: as it is again."""
        img = ocrd.Image(self.w, self.h, bytes(self.pixels))
        partial = self.folder / "frozen.bmp.new"
        partial.write_bytes(ocrd.to_bmp(img))
        os.replace(partial, self.folder / "frozen.bmp")
        self.state["frozen"] = {way: "frozen.bmp" for way in ways}
        self.save()

    BACKGROUND = (40, 44, 52)

    def text(self, box, lines, fill=None) -> None:
        """What the box at (x, y, w, h) on the screen says: [(x, y, w, h, text)] in the box, or [] for nothing.  Each
        letter is a patch of a colour of its own, where the line is (a new letter changes the picture as one does);
        the rest of the box is of one colour (``fill``, else always the same)."""
        x0, y0, bw, bh = box
        payload = "".join(f"{x},{y},{w},{h},{t}\n" for x, y, w, h, t in lines).encode("utf-8")
        assert len(payload) < bw, "the box is too narrow for what it says"
        r, g, b = fill or self.BACKGROUND
        for row in range(1, bh):
            at = ((y0 + row) * self.w + x0) * 4
            self.pixels[at:at + bw * 4] = bytes((b, g, r, 0)) * bw
        for x, y, w, h, t in lines:
            cell = max(2, w // max(1, len(t)))
            for i, ch in enumerate(t):
                c = ord(ch)
                colour = bytes((30 + c * 53 % 200, 30 + c * 91 % 200, 30 + c * 37 % 200, 0))
                for row in range(max(1, y), min(bh, y + h)):
                    at = ((y0 + row) * self.w + x0 + x + i * cell) * 4
                    width = max(0, min(cell, bw - x - i * cell))
                    self.pixels[at:at + width * 4] = colour * width
        at = (y0 * self.w + x0) * 4
        for i in range(bw):
            blue = payload[i] if i < len(payload) else 0
            green = 0x40 if i % 2 == 0 else 0xC0
            self.pixels[at + i * 4:at + i * 4 + 4] = bytes((blue, green, 0, 0))
        self.save()


# ---------------------------------------------------------------- Google, and Tor


def png_rows(png: bytes) -> tuple[int, int, list[bytes]]:
    """The rows of a PNG as ocrd.to_png writes them (RGB, 8 bits, no filters)."""
    assert png[:8] == b"\x89PNG\r\n\x1a\n"
    at, w, h, idat = 8, 0, 0, b""
    while at < len(png):
        n = struct.unpack(">I", png[at:at + 4])[0]
        kind, body = png[at + 4:at + 8], png[at + 8:at + 8 + n]
        if kind == b"IHDR":
            w, h = struct.unpack(">II", body[:8])
        elif kind == b"IDAT":
            idat += body
        at += 12 + n
    raw = zlib.decompress(idat)
    rows = []
    for y in range(h):
        row = raw[y * (1 + w * 3):(y + 1) * (1 + w * 3)]
        assert row[0] == 0
        rows.append(row[1:])
    return w, h, rows


# ---------------------------------------------------------------- Google Lens' own requests and answers (Sluka Vision)


def _pb_varint(value: int) -> bytes:
    out = bytearray()
    while value > 0x7F:
        out.append(value & 0x7F | 0x80)
        value >>= 7
    out.append(value)
    return bytes(out)


def pb_number(field: int, value: int) -> bytes:
    return _pb_varint(field << 3) + _pb_varint(value)


def pb_bytes(field: int, data: bytes) -> bytes:
    return _pb_varint(field << 3 | 2) + _pb_varint(len(data)) + data


def pb_float(field: int, value: float) -> bytes:
    return _pb_varint(field << 3 | 5) + struct.pack("<f", value)


def pb_read(data: bytes) -> dict:
    """A message's fields: {number: [value, ...]} (numbers as ints, the rest as bytes)."""
    out: dict = {}
    at = 0
    while at < len(data):
        key = shift = 0
        while True:
            byte = data[at]
            at += 1
            key |= (byte & 0x7F) << shift
            shift += 7
            if byte < 0x80:
                break
        field, wire = key >> 3, key & 7
        if wire == 0:
            value = shift = 0
            while True:
                byte = data[at]
                at += 1
                value |= (byte & 0x7F) << shift
                shift += 7
                if byte < 0x80:
                    break
        elif wire == 2:
            size = shift = 0
            while True:
                byte = data[at]
                at += 1
                size |= (byte & 0x7F) << shift
                shift += 7
                if byte < 0x80:
                    break
            value, at = data[at:at + size], at + size
        elif wire == 5:
            value, at = data[at:at + 4], at + 4
        elif wire == 1:
            value, at = data[at:at + 8], at + 8
        else:
            raise ValueError(f"wire type {wire}")
        out.setdefault(field, []).append(value)
    return out


def png_rgb_rows(png: bytes) -> tuple[int, int, list[bytes]]:
    """The rows of a PNG of 8-bit RGB, whatever its rows' filters (Sluka Vision's are "Up")."""
    from PIL import Image as PILImage
    import io

    img = PILImage.open(io.BytesIO(png)).convert("RGB")
    w, h = img.size
    raw = img.tobytes()
    return w, h, [raw[y * w * 3:(y + 1) * w * 3] for y in range(h)]


def lens_answer(lines: list[str], w: int, h: int) -> bytes:
    """Google Lens' answer (a LensOverlayServerResponse) for what a picture "says" (Screen.text's lines): a paragraph
    each -- "@p<n>;" puts lines in one paragraph, "@v;" makes it a column read down, "@a<radians>;" tilts it -- and
    each line in words: as its spaces part them, else two letters each."""
    paragraphs: list = []
    for text in lines:
        parts = text.split(",", 4)
        if len(parts) != 5:
            continue
        x, y, bw, bh = (float(v) for v in parts[:4])
        said = parts[4]
        group, vertical, angle = None, False, 0.0
        while said.startswith("@"):
            flag, said = said[1:].split(";", 1)
            if flag == "v":
                vertical = True
            elif flag.startswith("a"):
                angle = float(flag[1:])
            elif flag.startswith("p"):
                group = flag[1:]
        cx, cy = x + bw / 2, y + bh / 2
        if " " in said:
            pieces = [(word, " " if i < len(said.split(" ")) - 1 else "") for i, word in enumerate(said.split(" "))]
        else:
            pieces = [(said[i:i + 2], "") for i in range(0, len(said), 2)]
        letters = sum(len(word) + len(gap) for word, gap in pieces) or 1
        length = bh if vertical else bw
        ux, uy = (-math.sin(angle), math.cos(angle)) if vertical else (math.cos(angle), math.sin(angle))
        at = 0
        words = b""
        for word, gap in pieces:
            span = length * len(word) / letters
            middle = -length / 2 + (at + len(word) / 2) * length / letters
            wx, wy = cx + ux * middle, cy + uy * middle
            box = (wx / w, wy / h, (bw if vertical else span) / w, (span if vertical else bh) / h, angle)
            words += pb_bytes(1, pb_bytes(2, word.encode()) + pb_bytes(3, gap.encode()) + pb_bytes(4, _geometry(box)))
            at += len(word) + len(gap)
        line = words + pb_bytes(2, _geometry((cx / w, cy / h, bw / w, bh / h, angle)))
        found = next((p for p in paragraphs if group is not None and p["group"] == group), None)
        if found is None:
            paragraphs.append({"group": group, "lines": [line], "box": (cx / w, cy / h, bw / w, bh / h, angle), "v": vertical})
        else:
            found["lines"].append(line)
    layout = b"".join(pb_bytes(1, b"".join(pb_bytes(2, line) for line in p["lines"]) + pb_bytes(3, _geometry(p["box"]))
                                + pb_number(4, 2 if p["v"] else 0)) for p in paragraphs)
    return pb_bytes(2, pb_bytes(3, pb_bytes(1, layout) + pb_bytes(2, b"ja")))


def _geometry(box) -> bytes:
    cx, cy, bw, bh, angle = box
    return pb_bytes(1, pb_float(1, cx) + pb_float(2, cy) + pb_float(3, bw) + pb_float(4, bh) + pb_float(5, angle) + pb_number(6, 1))


class Lens:
    """Google Lens' address: as the stand-in NativeUtils' requests are written (fake_nativeutils.c), and as Google's own
    (a LensOverlayServerRequest, as Sluka Vision writes one)."""

    def __init__(self):
        self.requests = []
        #: How Google answers Sluka Vision's requests for now: 200, or another status.
        self.status = 200
        lens = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_POST(self):  # noqa: N802
                body = self.rfile.read(int(self.headers.get("Content-Length") or 0))
                lens.requests.append({"path": self.path, "headers": dict(self.headers), "size": len(body)})
                if body[:7] != b"LENSREQ":
                    self._protobuf(body)
                    return
                w, h, n = struct.unpack("<iiI", body[7:19])
                pw, ph, rows = png_rows(body[19:])
                assert (pw, ph) == (w, h) and n == 16
                row = rows[0]
                payload = bytearray()
                for i in range(w):
                    if not row[i * 3 + 2]:
                        break
                    payload.append(row[i * 3 + 2])
                out = b"LENSRES\n"
                for line in payload.decode("utf-8").split("\n"):
                    parts = line.split(",", 4)
                    if len(parts) == 5:
                        x, y, bw, bh = (float(v) for v in parts[:4])
                        out += f"{parts[4]}\t{(x + bw / 2) / w}\t{(y + bh / 2) / h}\t{bw / w}\t{bh / h}\n".encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/x-protobuf")
                self.send_header("Content-Length", str(len(out)))
                self.end_headers()
                self.wfile.write(out)

            def _protobuf(self, body: bytes):
                try:
                    objects = pb_read(pb_read(body)[1][0])
                    context = pb_read(objects[1][0])
                    request_id = pb_read(context[3][0])
                    client = pb_read(context[4][0])
                    image = pb_read(objects[3][0])
                    png = pb_read(image[1][0])[1][0]
                    meta = pb_read(image[3][0])
                    w, h = meta[1][0], meta[2][0]
                    pw, ph, rows = png_rgb_rows(png)
                except (KeyError, IndexError, ValueError, OSError) as err:
                    lens.requests[-1]["error"] = str(err)
                    self.send_response(400)
                    self.end_headers()
                    return
                lens.requests[-1].update(kind="protobuf", w=w, h=h, png=(pw, ph), nonce=len(request_id[4][0]),
                                         platform=client[1][0], surface=client[2][0],
                                         filter=pb_read(pb_read(client[17][0])[1][0])[1][0])
                if (pw, ph) != (w, h):
                    self.send_response(400)
                    self.end_headers()
                    return
                if lens.status != 200:
                    self.send_response(lens.status)
                    self.end_headers()
                    return
                payload = bytearray()
                for i in range(w):
                    if not rows[0][i * 3 + 2]:
                        break
                    payload.append(rows[0][i * 3 + 2])
                out = lens_answer(payload.decode("utf-8").split("\n"), w, h)
                self.send_response(200)
                self.send_header("Content-Type", "application/x-protobuf")
                self.send_header("Content-Length", str(len(out)))
                self.end_headers()
                self.wfile.write(out)

        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.server.server_port}/v1/crupload"

    def close(self):
        self.server.shutdown()


class Socks:
    """A SOCKS5 proxy, as Tor's: what it was asked to connect to, and the bytes passed on."""

    def __init__(self):
        self.asked = []
        self.listener = socket.socket()
        self.listener.bind(("127.0.0.1", 0))
        self.listener.listen(8)
        self.port = self.listener.getsockname()[1]
        threading.Thread(target=self._accept, daemon=True).start()

    def _accept(self):
        while True:
            try:
                conn, _ = self.listener.accept()
            except OSError:
                return
            threading.Thread(target=self._serve, args=(conn,), daemon=True).start()

    @staticmethod
    def _take(conn, n):
        data = b""
        while len(data) < n:
            more = conn.recv(n - len(data))
            if not more:
                raise OSError("closed")
            data += more
        return data

    def _serve(self, conn):
        try:
            head = self._take(conn, 2)
            self._take(conn, head[1])
            conn.sendall(b"\x05\x00")
            request = self._take(conn, 4)
            assert request[:2] == b"\x05\x01" and request[3] == 3, request
            name = self._take(conn, self._take(conn, 1)[0]).decode()
            port = struct.unpack(">H", self._take(conn, 2))[0]
            self.asked.append((name, port))
            upstream = socket.create_connection((name, port))
            conn.sendall(b"\x05\x00\x00\x01" + socket.inet_aton("127.0.0.1") + struct.pack(">H", port))

            def pipe(a, b):
                try:
                    while True:
                        data = a.recv(65536)
                        if not data:
                            break
                        b.sendall(data)
                except OSError:
                    pass
                for s in (a, b):
                    try:
                        s.shutdown(socket.SHUT_RDWR)
                    except OSError:
                        pass

            threading.Thread(target=pipe, args=(upstream, conn), daemon=True).start()
            pipe(conn, upstream)
        except (OSError, AssertionError):
            conn.close()

    def close(self):
        self.listener.close()
