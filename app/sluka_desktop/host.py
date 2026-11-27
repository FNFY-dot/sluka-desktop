# SPDX-License-Identifier: LicenseRef-Sluka
# Copyright (c) 2026 Sluka. Part of Sluka Desktop; see LICENSE.txt.
"""The native side of the app, behind one function: ``Host.handle(request)``.

Every page of the app talks to this and to nothing else.  It answers two
kinds of request:

* a file -- the extension's own pages, scripts and data, served exactly as
  they are on disk, with the extension's Content-Security-Policy on them and
  one ``<script>`` added to each page that provides ``chrome.*``;
* a call under ``/__sluka__/api/`` -- storage, downloads, windows, the log,
  and the mpv bridge.

It knows nothing about how the request arrived.  In the desktop app on Tails
that is a custom URL scheme inside the WebKit view (``gtkshell``), so no
network socket is opened at all; on Windows, and for development and tests,
it is a local HTTP server (``httpd``).
"""

from __future__ import annotations

import json
import logging
import mimetypes
import os
import re
import threading
import time
import urllib.parse
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

from . import APP_NAME, __version__
from .config import Config
from .storage import Store, free_bytes

log = logging.getLogger("sluka.host")

INTERNAL = "/__sluka__/"
API = INTERNAL + "api/"

MIME = {
    ".html": "text/html; charset=utf-8",
    ".htm": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".mjs": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".txt": "text/plain; charset=utf-8",
    ".md": "text/plain; charset=utf-8",
    ".tsv": "text/tab-separated-values; charset=utf-8",
    ".csv": "text/csv; charset=utf-8",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".ico": "image/x-icon",
    ".woff": "font/woff",
    ".woff2": "font/woff2",
    ".ttf": "font/ttf",
    ".otf": "font/otf",
    ".wasm": "application/wasm",
    # Left as it is on disk: the pages unpack these themselves.
    ".gz": "application/gzip",
    ".mp3": "audio/mpeg",
    ".ogg": "audio/ogg",
    ".opus": "audio/ogg",
    ".wav": "audio/wav",
    ".m4a": "audio/mp4",
    ".mp4": "video/mp4",
    ".webm": "video/webm",
}

#: Bodies larger than this are refused for JSON calls (a word list is a few MB).
MAX_JSON_BODY = 256 * 1024 * 1024
#: The calls that read a large body as it comes, a piece at a time: files written.
STREAMED = ("download", "folders/piece")

_HEAD_TAG = re.compile(rb"<head(\s[^>]*)?>", re.IGNORECASE)
_HTML_TAG = re.compile(rb"<html(\s[^>]*)?>", re.IGNORECASE)
_BAD_NAME = re.compile(r'[\x00-\x1f\x7f<>:"|?*]')


@dataclass
class Request:
    method: str
    path: str
    query: dict = field(default_factory=dict)
    headers: dict = field(default_factory=dict)  # lower-case names
    body: bytes = b""
    #: For large uploads: ``read(n) -> bytes`` (b"" at the end) instead of ``body``.
    body_reader: Optional[Callable[[int], bytes]] = None
    #: The app's own origin as this transport shows it to pages.
    origin: str = ""
    #: The web view that asked, where the transport knows it.
    view: object = None


@dataclass
class Response:
    status: int = 200
    content_type: str = "application/octet-stream"
    body: bytes = b""
    headers: dict = field(default_factory=dict)
    #: Serve this slice of a file instead of ``body``: (path, offset, length).
    file: Optional[tuple] = None

    @property
    def length(self) -> int:
        return self.file[2] if self.file else len(self.body)


def json_response(value, status: int = 200) -> Response:
    return Response(
        status=status,
        content_type="application/json; charset=utf-8",
        body=json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8"),
        headers={"Cache-Control": "no-store"},
    )


def error_response(status: int, message: str) -> Response:
    return json_response({"error": message}, status)


class NullShell:
    """Stands in where there are no windows to manage (tests, the HTTP server)."""

    def __init__(self):
        self.calls: list[dict] = []

    def request(self, op: str, args: dict, view=None) -> dict:
        self.calls.append({"op": op, **args})
        del self.calls[:-200]
        return {"ok": True, "handled": False}

    def register(self, info: dict, view=None) -> None:
        pass


class Host:
    def __init__(self, config: Config, shell=None):
        self.config = config
        self.manifest = config.manifest or config.load_manifest()
        config.ensure_dirs()
        self.store = Store(config.db_path)
        self.shell = shell or NullShell()
        self.mpv = None  # set by the app when the mpv bridge is on
        self.anki = None  # and the bridge to Anki's review screen
        self.bar = None  # and the floating subtitles (bar.py)
        self.games = None  # and the game text that goes into them (gametext.py)
        self.engine = ""  # the window toolkit and web engine, as the shell describes them
        # The family the desktop itself is set in, which is what a page's system-ui means: for the look in mpv.
        self.ui_font = ""
        self.started = time.time()
        self._lock = threading.RLock()
        self._ext_root = os.path.realpath(str(config.ext_dir))
        self._web_root = os.path.realpath(str(config.web_dir))
        self._page_errors: list[dict] = []
        #: Files being written in pieces, by token.
        self._uploads: dict[str, dict] = {}
        #: Text replacements applied to served scripts.  Empty in the app; the
        #: test server uses it to stand in for the ``chrome-extension:`` scheme.
        self.dev_rewrites: list[tuple[str, bytes, bytes]] = []
        #: What the shell wants every page to know besides (which kind of windows it has).
        self.boot_extra: dict = {}
        #: The folders chosen for Sluka (folders.py); a shell with a folder window gives it its picker.
        from .folders import Folders
        self.folders = Folders(config)
        #: Looks faces up for the script in mpv where it cannot do so itself (winfonts.Finder, on Windows).
        self.fonts = None
        #: The Look up key's dictionaries on this computer, and its small windows (dictionaries.py).
        from .dictionaries import Dictionaries

        self.dictionaries = Dictionaries(config.data_dir / "dictionaries", host=self)
        self._lifecycle_done = False
        try:
            self.store.snapshot_daily(config.data_dir / "snapshots")
        except Exception:  # a safety copy must never stop the app
            log.exception("could not write the daily copy of the storage file")

    # ------------------------------------------------------------ entry

    def handle(self, req: Request, respond: Callable[[Response], None]) -> None:
        """Answer ``req`` by calling ``respond`` once, now or later."""
        try:
            path = req.path or "/"
            if path.startswith(API):
                self._api(path[len(API):], req, respond)
                return
            if req.method not in ("GET", "HEAD"):
                respond(error_response(405, "method not allowed"))
                return
            if path == INTERNAL + "boot.js":
                respond(self._boot_script(req))
            elif path.startswith(INTERNAL):
                respond(self._serve_file(self._web_root, path[len(INTERNAL):], req, internal=True))
            else:
                respond(self._serve_file(self._ext_root, path.lstrip("/"), req, internal=False))
        except Exception as err:  # never let a request take the app down
            log.exception("request failed: %s %s", req.method, req.path)
            respond(error_response(500, f"{type(err).__name__}: {err}"))

    # ------------------------------------------------------------ files

    def _resolve(self, root: str, rel: str) -> Optional[str]:
        """``rel`` inside ``root``, or None when it is not a file in there."""
        rel = rel.split("?", 1)[0].split("#", 1)[0]
        parts = [p for p in rel.replace("\\", "/").split("/") if p not in ("", ".")]
        if any(p == ".." or "\x00" in p for p in parts):
            return None
        candidate = os.path.realpath(os.path.join(root, *parts)) if parts else root
        # Resolved, so a symlink inside the folder cannot lead out of it.
        if candidate != root and not candidate.startswith(root + os.sep):
            return None
        return candidate if os.path.isfile(candidate) else None

    def _serve_file(self, root: str, rel: str, req: Request, internal: bool) -> Response:
        full = self._resolve(root, rel)
        if not full:
            return Response(status=404, content_type="text/plain; charset=utf-8", body=b"Not found")
        ext = os.path.splitext(full)[1].lower()
        ctype = MIME.get(ext) or mimetypes.guess_type(full)[0] or "application/octet-stream"
        headers = {
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
            "Accept-Ranges": "bytes",
        }
        if ext in (".html", ".htm"):
            with open(full, "rb") as handle:
                body = self._prepare_page(handle.read())
            if self.config.csp:
                headers["Content-Security-Policy"] = self.config.csp_policy
            headers.pop("Accept-Ranges")
            return Response(status=200, content_type=ctype, body=body, headers=headers)

        if self.dev_rewrites and ext in (".js", ".mjs"):
            with open(full, "rb") as handle:
                body = handle.read()
            rel_norm = rel.replace("\\", "/")
            for suffix, old, new in self.dev_rewrites:
                if rel_norm.endswith(suffix):
                    body = body.replace(old, new)
            headers.pop("Accept-Ranges")
            return Response(status=200, content_type=ctype, body=body, headers=headers)

        size = os.path.getsize(full)
        start, length, partial = 0, size, False
        rng = req.headers.get("range", "")
        match = re.match(r"bytes=(\d*)-(\d*)$", rng.strip()) if rng else None
        if match and (match.group(1) or match.group(2)):
            if match.group(1):
                start = int(match.group(1))
                end = int(match.group(2)) if match.group(2) else size - 1
            else:  # the last N bytes
                start = max(0, size - int(match.group(2)))
                end = size - 1
            end = min(end, size - 1)
            if start > end or start >= size:
                return Response(status=416, content_type=ctype, headers={"Content-Range": f"bytes */{size}"})
            length, partial = end - start + 1, True
            headers["Content-Range"] = f"bytes {start}-{end}/{size}"
        return Response(
            status=206 if partial else 200,
            content_type=ctype,
            headers=headers,
            file=(full, start, length),
        )

    def _prepare_page(self, html: bytes) -> bytes:
        """The page as it is on disk, with the shim put in before anything runs.

        The two scripts are files, not inline code, so the page still passes the
        extension's own policy -- which is repeated in a <meta> for a web engine
        that does not take the header from this kind of address.
        """
        tags = b""
        if self.config.csp:
            policy = self.config.csp_policy.replace('"', "&quot;").encode("utf-8")
            tags += b'<meta http-equiv="Content-Security-Policy" content="' + policy + b'">'
        tags += (
            b'<script src="/__sluka__/boot.js"></script>'
            b'<script src="/__sluka__/shim.js"></script>'
        )
        for pattern in (_HEAD_TAG, _HTML_TAG):
            match = pattern.search(html)
            if match:
                return html[:match.end()] + tags + html[match.end():]
        return tags + html

    def _boot_script(self, req: Request) -> Response:
        boot = {
            "id": self.config.extension_id,
            "manifest": self.manifest,
            "app": {"name": APP_NAME, "version": __version__},
            "network": self.config.network_mode,
            "mpv": bool(self.mpv),
            "anki": bool(self.anki),
            "bar": bool(self.bar),
            "games": bool(self.games),
        }
        boot.update(self.boot_extra)
        text = "globalThis.__SLUKA_BOOT__ = " + json.dumps(boot, ensure_ascii=False) + ";\n"
        return Response(
            content_type="text/javascript; charset=utf-8",
            body=text.encode("utf-8"),
            headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"},
        )

    # -------------------------------------------------------------- api

    def _api(self, name: str, req: Request, respond: Callable[[Response], None]) -> None:
        # Only the app's own pages may call in.  Where the engine sends an
        # Origin it has to be ours; a page from anywhere else never has it.
        origin = req.headers.get("origin", "")
        if origin and req.origin and origin != req.origin:
            respond(error_response(403, "forbidden"))
            return

        # A body over httpd's STREAM_ABOVE comes to be read rather than read already.  Only the calls that write
        # files read it as it comes; for every other one -- a restore's storage write of a large backup, above all --
        # it is read whole here, as a smaller one is.  (Answered unread, the page was told only "Failed to fetch".)
        if req.body_reader and not (name in STREAMED or name.startswith("dict/file")):
            body = bytearray()
            while len(body) <= MAX_JSON_BODY:
                chunk = req.body_reader(1024 * 1024)
                if not chunk:
                    break
                body += chunk
            if len(body) > MAX_JSON_BODY:
                while req.body_reader(1024 * 1024):
                    pass
                respond(error_response(413, "too large"))
                return
            req.body, req.body_reader = bytes(body), None

        if name.startswith("mpv/"):
            if not self.mpv:
                respond(error_response(404, "the mpv bridge is off"))
                return
            self.mpv.api(name[4:], req, respond)
            return

        if name.startswith("bar/"):
            if not self.bar:
                respond(error_response(404, "the floating subtitles are not to be had here"))
                return
            self.bar.api(name[4:], req, respond)
            return

        if name.startswith("games/"):
            if not self.games:
                respond(error_response(404, "game text is not to be had here"))
                return
            self.games.api(name[6:], req, respond)
            return

        if name.startswith("dict/"):
            self.dictionaries.api(name[5:], req, respond)
            return

        if name.startswith("cards/"):
            cards = getattr(self.games, "cards", None) if self.games else None
            if cards is None:
                respond(error_response(404, "a game's sound and picture are not to be had here"))
                return
            cards.api(name[6:], req, respond)
            return

        if name.startswith("vision/"):
            vision = getattr(self.games, "vision", None) if self.games else None
            if vision is None:
                respond(error_response(404, "Sluka Vision is not to be had here"))
                return
            vision.api(name[7:], req, respond)
            return

        if name.startswith("anki/"):
            if not self.anki:
                respond(error_response(404, "the bridge to Anki is off"))
                return
            self.anki.api(name[5:], req, respond)
            return

        if name == "download":
            respond(self._api_download(req))
            return

        # Folders chosen for Sluka, Settings → Sync & backup's backup folder above all (folders.py).
        if name in ("folders", "folders/piece", "folders/read"):
            self.folders.api(name, req, respond)
            return

        handler = {
            "storage": self._api_storage,
            "lifecycle": self._api_lifecycle,
            "downloads": self._api_downloads,
            "shell": self._api_shell,
            "hello": self._api_hello,
            "log": self._api_log,
            "info": self._api_info,
            "selftest": self._api_selftest,
            "shell-log": self._api_shell_log,
            "fonts": self._api_fonts,
        }.get(name)
        if not handler:
            respond(error_response(404, f"no such call: {name}"))
            return
        if req.method == "GET":
            args = {}
        else:
            if len(req.body) > MAX_JSON_BODY:
                respond(error_response(413, "too large"))
                return
            try:
                args = json.loads(req.body.decode("utf-8")) if req.body else {}
            except (ValueError, UnicodeDecodeError):
                respond(error_response(400, "not JSON"))
                return
            if not isinstance(args, dict):
                respond(error_response(400, "not an object"))
                return
        respond(handler(args, req))

    # ---- storage

    def _api_storage(self, args: dict, req: Request) -> Response:
        area = args.get("area", "local")
        if area not in ("local", "session", "sync"):
            return error_response(400, "no such storage area")
        op = args.get("op")
        if op == "get":
            keys = args.get("keys")
            if keys is not None and not _is_string_list(keys):
                return error_response(400, "keys must be strings")
            return json_response({"items": self.store.get(area, keys)})
        if op == "set":
            items = args.get("items")
            if not isinstance(items, dict) or not all(isinstance(v, str) for v in items.values()):
                return error_response(400, "items must be JSON text by key")
            try:
                old = self.store.set(area, items)
            except Exception as err:
                log.exception("storage write failed")
                return error_response(507, _storage_error(err, self.config.data_dir))
            return json_response({"old": old})
        if op == "remove":
            keys = args.get("keys")
            if not _is_string_list(keys):
                return error_response(400, "keys must be strings")
            return json_response({"old": self.store.remove(area, keys)})
        if op == "clear":
            return json_response({"old": self.store.clear(area)})
        if op == "keys":
            return json_response({"keys": self.store.keys(area)})
        if op == "bytes":
            keys = args.get("keys")
            if keys is not None and not _is_string_list(keys):
                return error_response(400, "keys must be strings")
            return json_response({"bytes": self.store.bytes_in_use(area, keys)})
        return error_response(400, "no such storage call")

    # ---- install / update / startup

    def _api_lifecycle(self, args: dict, req: Request) -> Response:
        """What the background page should be told as it starts.

        Once per run: ``install`` the very first time, ``update`` when the
        extension folder holds a different version than last time, otherwise
        nothing but the startup every run gets.
        """
        with self._lock:
            if self._lifecycle_done:
                # The background page was started again in this run (it had
                # stopped): it sets its alarms up as at any start, and is not
                # told a second time that Sluka was installed or updated.
                return json_response({"reason": None, "startup": True})
            self._lifecycle_done = True
            current = self.config.extension_version
            previous = self.store.meta_get("extension_version", "")
            reason = "install" if not previous else ("update" if previous != current else None)
            self.store.meta_set("extension_version", current)
            return json_response({"reason": reason, "previousVersion": previous or None, "startup": True})

    # ---- downloads

    def _download_target(self, name: str, conflict: str) -> tuple[str, Path]:
        parts = []
        for piece in re.split(r"[\\/]+", name or ""):
            piece = _BAD_NAME.sub("_", piece).strip().strip(".")
            if piece and piece not in (".", ".."):
                parts.append(piece[:200])
        if not parts:
            parts = ["download"]
        rel = "/".join(parts)
        target = self.config.downloads_dir.joinpath(*parts)
        if conflict != "overwrite" and target.exists():
            stem, suffix = target.stem, target.suffix
            for n in range(1, 10000):
                candidate = target.with_name(f"{stem} ({n}){suffix}")
                if not candidate.exists():
                    target = candidate
                    rel = "/".join(parts[:-1] + [candidate.name])
                    break
        return rel, target

    def _api_download(self, req: Request) -> Response:
        """Write a file into the downloads folder: in one request, or in pieces.

        ``stage=begin`` names the file and answers a token, ``stage=piece``
        appends to it, ``stage=end`` puts it in place.  Either way the file
        only appears under its own name once it is whole.
        """
        if req.method != "POST":
            return error_response(405, "POST")
        stage = req.query.get("stage", "")
        if stage in ("piece", "end"):
            return self._upload_step(stage, req)

        name = req.query.get("filename", "")
        conflict = req.query.get("conflict", "uniquify")
        rel, target = self._download_target(name, conflict)
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
        except OSError as err:
            return self._download_failed(rel, target, err)
        partial = target.with_name(target.name + ".part")

        if stage == "begin":
            token = os.urandom(16).hex()
            try:
                open(partial, "wb").close()
            except OSError as err:
                return self._download_failed(rel, target, err)
            with self._lock:
                self._uploads[token] = {"rel": rel, "target": target, "partial": partial, "size": 0, "at": time.time()}
            return json_response({"token": token})

        size = 0
        try:
            with open(partial, "wb") as out:
                if req.body_reader:
                    while True:
                        chunk = req.body_reader(1024 * 1024)
                        if not chunk:
                            break
                        out.write(chunk)
                        size += len(chunk)
                else:
                    out.write(req.body)
                    size = len(req.body)
                out.flush()
                os.fsync(out.fileno())
            os.replace(partial, target)  # in place only when whole
        except OSError as err:
            _unlink_quietly(partial)
            return self._download_failed(rel, target, err)
        return self._download_done(rel, target, size)

    def _upload_step(self, stage: str, req: Request) -> Response:
        token = req.query.get("token", "")
        with self._lock:
            upload = self._uploads.get(token)
        if not upload:
            return error_response(404, "no such upload")
        partial, target, rel = upload["partial"], upload["target"], upload["rel"]
        try:
            if stage == "piece":
                at = int(req.query.get("at", "-1"))
                if at != upload["size"]:
                    return error_response(409, f"expected the piece at {upload['size']}, not {at}")
                data = req.body
                if req.body_reader:
                    pieces = []
                    while True:
                        chunk = req.body_reader(1024 * 1024)
                        if not chunk:
                            break
                        pieces.append(chunk)
                    data = b"".join(pieces)
                with open(partial, "ab") as out:
                    out.write(data)
                upload["size"] += len(data)
                upload["at"] = time.time()
                return json_response({"size": upload["size"]})
            # end
            with open(partial, "ab") as out:
                out.flush()
                os.fsync(out.fileno())
            os.replace(partial, target)
        except (OSError, ValueError) as err:
            with self._lock:
                self._uploads.pop(token, None)
            _unlink_quietly(partial)
            return self._download_failed(rel, target, err)
        with self._lock:
            self._uploads.pop(token, None)
        return self._download_done(rel, target, upload["size"])

    def _download_done(self, rel: str, target: Path, size: int) -> Response:
        ident = self.store.download_add(rel, str(target), size)
        log.info("saved %s (%d bytes)", target, size)
        return json_response({"id": ident, "filename": str(target), "size": size})

    def _download_failed(self, rel: str, target: Path, err: Exception) -> Response:
        log.error("could not save %s: %s", target, err)
        ident = self.store.download_add(rel, str(target), 0, state="interrupted", error="FILE_FAILED")
        return json_response({"id": ident, "error": "FILE_FAILED", "detail": str(err)})

    def _download_item(self, row: dict) -> dict:
        return {
            "id": row["id"],
            "filename": row["path"],
            "state": row["state"],
            "exists": row["exists"],
            "error": row["error"] or None,
            "fileSize": row["size"],
            "totalBytes": row["size"],
            "bytesReceived": row["size"],
            "startTime": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(row["started"])) + "Z",
            "paused": False,
            "canResume": False,
            "danger": "safe",
            "incognito": False,
        }

    def _api_downloads(self, args: dict, req: Request) -> Response:
        op = args.get("op")
        if op == "search":
            query = args.get("query") or {}
            if isinstance(query.get("id"), int):
                row = self.store.download_get(query["id"])
                return json_response({"items": [self._download_item(row)] if row else []})
            return json_response({"items": [self._download_item(r) for r in self.store.download_list()]})
        if op in ("removeFile", "erase"):
            ident = args.get("id")
            row = self.store.download_get(ident) if isinstance(ident, int) else None
            if not row:
                return error_response(404, "no such download")
            if op == "removeFile":
                path = os.path.realpath(row["path"])
                root = os.path.realpath(str(self.config.downloads_dir))
                # Only ever a file this app wrote, in the folder it writes to.
                if path.startswith(root + os.sep) and os.path.isfile(path):
                    try:
                        os.remove(path)
                    except OSError as err:
                        return error_response(500, str(err))
            else:
                self.store.download_forget(ident)
            return json_response({"ok": True})
        if op == "folder":
            return json_response({"folder": str(self.config.downloads_dir)})
        return error_response(400, "no such downloads call")

    # ---- windows

    def _api_shell(self, args: dict, req: Request) -> Response:
        op = str(args.get("op") or "")
        if op not in ("open", "focus", "close", "state", "external", "title", "bounds", "media-failed", "alive"):
            return error_response(400, "no such window call")
        payload = {k: v for k, v in args.items() if k != "op"}
        try:
            return json_response(self.shell.request(op, payload, req.view) or {"ok": True})
        except Exception as err:
            log.exception("window call failed: %s", op)
            return error_response(500, str(err))

    def _api_hello(self, args: dict, req: Request) -> Response:
        try:
            self.shell.register(args, req.view)
        except Exception:
            log.exception("could not register a page")
        return json_response({"ok": True})

    def _api_shell_log(self, args: dict, req: Request) -> Response:
        return json_response({"calls": getattr(self.shell, "calls", [])})

    def _api_fonts(self, args: dict, req: Request) -> Response:
        """The faces a page's font lists come to on this computer, for the look in mpv; null where mpv's script finds them itself."""
        stacks = args.get("stacks")
        if not self.fonts or not isinstance(stacks, dict):
            return json_response({"faces": None})
        try:
            return json_response({"faces": self.fonts.faces(stacks, str(args.get("lang") or ""), self.ui_font)})
        except Exception:
            log.exception("the faces for mpv could not be looked up")
            return json_response({"faces": None})

    # ---- log and diagnostics

    def _api_log(self, args: dict, req: Request) -> Response:
        level = str(args.get("level") or "error")
        text = str(args.get("text") or "")[:4000]
        where = str(args.get("url") or "")[:300]
        entry = {"at": time.time(), "level": level, "text": text, "url": where}
        with self._lock:
            self._page_errors.append(entry)
            del self._page_errors[:-300]
        logging.getLogger("sluka.page").log(
            logging.ERROR if level == "error" else logging.WARNING if level == "warn" else logging.INFO,
            "%s  [%s]", text, where,
        )
        return json_response({"ok": True})

    def _api_info(self, args: dict, req: Request) -> Response:
        cfg = self.config
        return json_response({
            "app": {"name": APP_NAME, "version": __version__},
            # For a second start of the app, which may let this one bring its new window to the front.
            "pid": os.getpid(),
            "extension": {"version": cfg.extension_version, "id": cfg.extension_id, "folder": str(cfg.ext_dir)},
            "data": str(cfg.data_dir),
            "downloads": str(cfg.downloads_dir),
            "network": cfg.network_mode,
            "engine": self.engine,
            "ui_font": self.ui_font,
            "mpv_scale": getattr(cfg, "mpv_scale", 1.0),
            "freeBytes": free_bytes(cfg.data_dir),
            "mpv": self.mpv.status() if self.mpv else None,
            "anki": self.anki.status() if self.anki else None,
            "bar": self.bar.status() if self.bar else None,
            "games": self.games.status() if self.games else None,
            "errors": self._page_errors[-50:],
        })

    def _api_selftest(self, args: dict, req: Request) -> Response:
        """What the self-test page found, kept as a file that can be sent along with a question."""
        cfg = self.config
        found = args.get("lines") if isinstance(args.get("lines"), list) else []
        head = [
            f"{APP_NAME} {__version__} self-test, {time.strftime('%Y-%m-%d %H:%M:%S')}",
            f"Sluka {cfg.extension_version}",
            self.engine or "(no window toolkit: the test server)",
            f"network mode: {cfg.network_mode}",
            f"engine says: {str(args.get('agent') or '')[:300]}",
            "",
        ]
        path = cfg.log_dir / "selftest.txt"
        try:
            cfg.log_dir.mkdir(parents=True, exist_ok=True)
            path.write_text("\n".join(head + [str(line)[:2000] for line in found[:200]]) + "\n", encoding="utf-8")
        except OSError as err:
            return error_response(500, str(err))
        log.info("self-test written to %s", path)
        return json_response({"path": str(path)})

    def close(self) -> None:
        for upload in list(self._uploads.values()):
            _unlink_quietly(upload["partial"])
        self._uploads.clear()
        if self.mpv:
            try:
                self.mpv.close()
            except Exception:
                log.exception("closing the mpv bridge")
        if self.anki:
            try:
                self.anki.close()
            except Exception:
                log.exception("closing the bridge to Anki")
        if self.games:
            try:
                self.games.close()
            except Exception:
                log.exception("closing the game text")
        if self.bar:
            try:
                self.bar.close()
            except Exception:
                log.exception("closing the floating subtitles")
        self.store.close()


def _unlink_quietly(path) -> None:
    try:
        os.unlink(path)
    except OSError:
        pass


def _is_string_list(value) -> bool:
    return isinstance(value, list) and all(isinstance(v, str) for v in value)


def _storage_error(err: Exception, folder: Path) -> str:
    free = free_bytes(folder)
    if 0 <= free < 5 * 1024 * 1024:
        return "The disk holding Sluka's data is full."
    return f"Could not write Sluka's data: {err}"


def parse_query(raw: str) -> dict:
    return {k: v[-1] for k, v in urllib.parse.parse_qs(raw or "", keep_blank_values=True).items()}
