# SPDX-License-Identifier: LicenseRef-Sluka
# Copyright (c) 2026 Sluka. Part of Sluka Desktop; see LICENSE.txt.
"""Folders you choose for Sluka: Settings → Sync & backup's backup folder, in a Google Drive folder or anywhere.

In Chrome, Sluka asks for its backup folder with the browser's own folder picker
and keeps what it is given -- a directory handle -- to write its backup there every
few minutes and read the other devices' (lib/backup.js).  That is what syncing
through Google Drive is: the folder is in My Drive, and Drive's own app does the
rest.  The app's web views either have no such picker (WebKitGTK) or one whose
permission does not outlast the app (WebView2), so the app gives Sluka one of its
own (web/shim.js showDirectoryPicker): the system's folder window, and a handle
that reads and writes through these calls.

Only a folder chosen in that window is reachable: each is known by a random
token, every path is checked to stay inside it, and nothing outside is ever
listed, read or written.  A file is written beside its place under a name of its
own and only put in place once whole, as the browser's own writes are.
"""

from __future__ import annotations

import json
import logging
import os
import re
import secrets
import shutil
import threading
import time
from pathlib import Path

from .host import Request, Response, error_response, json_response

log = logging.getLogger("sluka.folders")

#: The folders chosen, by token, kept across starts.
FOLDERS_FILE = "folders.json"
#: What a file being written is called meanwhile (and what a listing never shows).
PART = ".sluka-part"
#: A write begun and never finished is let go of after this long.
WRITE_FOR = 6 * 3600
TOKEN = re.compile(r"[0-9a-f]{32}")
BAD_NAME = re.compile(r'[\x00-\x1f<>:"|?*\\/]')


class Refused(ValueError):
    """A path or a token that is not one of a chosen folder's."""


class Folders:
    """The folders chosen for Sluka, and the calls its handles make of them."""

    def __init__(self, config, picker=None):
        self.config = config
        #: picker(title, remember) -> a folder's path, or "" when the window was closed; None where there is none.
        self.picker = picker
        self._lock = threading.Lock()
        self._writes: dict = {}
        self._file = Path(config.data_dir) / FOLDERS_FILE
        try:
            got = json.loads(self._file.read_text(encoding="utf-8"))
            self._known = {t: p for t, p in got.items() if TOKEN.fullmatch(t) and isinstance(p, str)}
        except (OSError, ValueError, AttributeError):
            self._known = {}

    # ---- the folders

    def _save(self) -> None:
        try:
            self._file.parent.mkdir(parents=True, exist_ok=True)
            temp = self._file.with_name(self._file.name + ".tmp")
            temp.write_text(json.dumps(self._known, ensure_ascii=False, indent=1), encoding="utf-8")
            os.replace(temp, self._file)
        except OSError as err:
            log.warning("could not keep the folders chosen: %s", err)

    def pick(self, remember: str = "") -> dict:
        if not self.picker:
            return {"ok": False, "error": "This window cannot ask for a folder."}
        path = self.picker("Choose Sluka's folder", remember)
        if not path:
            return {"ok": False, "cancelled": True}
        root = os.path.realpath(path)
        if not os.path.isdir(root):
            return {"ok": False, "error": f"{path} is not a folder."}
        with self._lock:
            token = next((t for t, p in self._known.items() if os.path.normcase(p) == os.path.normcase(root)), "")
            if not token:
                token = secrets.token_hex(16)
                self._known[token] = root
                self._save()
        log.info("a folder was chosen for Sluka: %s", root)
        return {"ok": True, "folder": token, "name": os.path.basename(root.rstrip("\\/")) or root, "path": root}

    def root(self, token: str) -> str:
        with self._lock:
            root = self._known.get(token) if TOKEN.fullmatch(str(token or "")) else None
        if not root:
            raise Refused("not a folder chosen for Sluka")
        return root

    def place(self, token: str, parts) -> Path:
        """Where ``parts`` (names, from the folder down) is: never outside the folder."""
        root = self.root(token)
        if not isinstance(parts, list) or len(parts) > 32:
            raise Refused("not a path")
        names = []
        for part in parts:
            part = str(part)
            if not part or part in (".", "..") or BAD_NAME.search(part) or len(part) > 255 or part.endswith(PART):
                raise Refused(f"not a name: {part!r}")
            names.append(part)
        target = Path(root, *names)
        real = os.path.realpath(target)
        if os.path.normcase(real) != os.path.normcase(root) and not os.path.normcase(real).startswith(os.path.normcase(root.rstrip("\\/") + os.sep)):
            raise Refused("outside the folder")
        return target

    # ---- the calls

    def call(self, args: dict) -> dict:
        op = args.get("op")
        if op == "pick":
            return self.pick(str(args.get("id") or "")[:60])
        if op in ("end", "abort"):
            with self._lock:
                job = self._writes.pop(str(args.get("write") or ""), None)
            if not job:
                return {"ok": False, "error": "no such write"}
            if op == "abort":
                _gone(job["partial"])
                return {"ok": True}
            os.replace(job["partial"], job["target"])
            return {"ok": True}
        token = str(args.get("folder") or "")
        if op == "state":
            try:
                return {"ok": True, "state": "granted" if os.path.isdir(self.root(token)) else "gone"}
            except Refused:
                return {"ok": True, "state": "unknown"}
        path = args.get("path") or []
        target = self.place(token, path)
        if op == "kind":
            if target.is_dir():
                return {"ok": True, "kind": "directory"}
            if target.is_file():
                return {"ok": True, "kind": "file"}
            return {"ok": True, "kind": ""}
        if op == "mkdir":
            if target.is_file():
                return {"ok": False, "error": "TypeMismatchError"}
            target.mkdir(parents=True, exist_ok=True)
            return {"ok": True}
        if op == "touch":
            if target.is_dir():
                return {"ok": False, "error": "TypeMismatchError"}
            if not target.parent.is_dir():
                return {"ok": False, "error": "NotFoundError"}
            if not target.exists():
                open(target, "ab").close()
            return {"ok": True}
        if op == "list":
            if not target.is_dir():
                return {"ok": False, "error": "NotFoundError"}
            out = []
            with os.scandir(target) as found:
                for entry in found:
                    if entry.name.endswith(PART):
                        continue
                    try:
                        if entry.is_dir():
                            out.append({"name": entry.name, "kind": "directory"})
                        elif entry.is_file():
                            st = entry.stat()
                            out.append({"name": entry.name, "kind": "file", "size": st.st_size, "at": int(st.st_mtime * 1000)})
                    except OSError:
                        continue
            return {"ok": True, "entries": sorted(out, key=lambda e: e["name"])}
        if op == "stat":
            if not target.is_file():
                return {"ok": False, "error": "NotFoundError"}
            st = target.stat()
            return {"ok": True, "size": st.st_size, "at": int(st.st_mtime * 1000)}
        if op == "remove":
            if target.is_dir():
                if args.get("recursive"):
                    shutil.rmtree(target)
                else:
                    try:
                        target.rmdir()
                    except OSError:
                        return {"ok": False, "error": "InvalidModificationError"}
            elif target.is_file():
                target.unlink()
            else:
                return {"ok": False, "error": "NotFoundError"}
            return {"ok": True}
        if op == "begin":
            if target.is_dir():
                return {"ok": False, "error": "TypeMismatchError"}
            if not target.parent.is_dir():
                return {"ok": False, "error": "NotFoundError"}
            write = secrets.token_hex(16)
            _left_behind(target.parent)
            partial = target.with_name(f".{target.name}.{write[:8]}{PART}")
            with open(partial, "wb") as out:
                if args.get("keep") and target.is_file():
                    with open(target, "rb") as src:
                        shutil.copyfileobj(src, out)
            self._sweep()
            with self._lock:
                self._writes[write] = {"target": target, "partial": partial, "at": time.time()}
            return {"ok": True, "write": write}
        return {"ok": False, "error": f"no such call: {op}"}

    def _sweep(self) -> None:
        now = time.time()
        with self._lock:
            old = [w for w, job in self._writes.items() if now - job["at"] > WRITE_FOR]
            jobs = [self._writes.pop(w) for w in old]
        for job in jobs:
            _gone(job["partial"])

    def piece(self, req: Request) -> Response:
        """Bytes of a write begun, appended (``?write=&at=``), as the request's own body."""
        with self._lock:
            job = self._writes.get(str(req.query.get("write") or ""))
        if not job:
            return error_response(404, "no such write")
        try:
            at = int(req.query.get("at") or 0)
        except ValueError:
            return error_response(400, "at")
        with open(job["partial"], "r+b") as out:
            out.seek(0, os.SEEK_END)
            if out.tell() != at:
                out.seek(at)
                out.truncate()
            if req.body_reader:
                while True:
                    chunk = req.body_reader(1024 * 1024)
                    if not chunk:
                        break
                    out.write(chunk)
            else:
                out.write(req.body or b"")
        with self._lock:
            job["at"] = time.time()
        return json_response({"ok": True})

    def read(self, req: Request) -> Response:
        """A file of a chosen folder, as it is (``?folder=&path=`` the names as JSON)."""
        try:
            target = self.place(str(req.query.get("folder") or ""), json.loads(req.query.get("path") or "[]"))
        except (Refused, ValueError) as err:
            return error_response(403, str(err))
        if not target.is_file():
            return error_response(404, "NotFoundError")
        return Response(content_type="application/octet-stream", file=(str(target), 0, target.stat().st_size),
                        headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"})

    def api(self, name: str, req: Request, respond) -> None:
        """folders, folders/piece, folders/read."""
        if req.headers.get("sec-fetch-site", "same-origin") not in ("same-origin", "none"):
            respond(error_response(403, "not from Sluka's own pages"))
            return
        if name == "folders/read":
            respond(self.read(req))
            return
        if req.method != "POST":
            respond(error_response(405, "POST"))
            return
        if name == "folders/piece":
            respond(self.piece(req))
            return
        try:
            args = json.loads((req.body or b"{}").decode("utf-8"))
            if not isinstance(args, dict):
                raise ValueError("not an object")
        except (ValueError, UnicodeDecodeError):
            respond(error_response(400, "not JSON"))
            return
        try:
            respond(json_response(self.call(args)))
        except Refused as err:
            respond(json_response({"ok": False, "error": "NotAllowedError", "why": str(err)}, 403))
        except OSError as err:
            respond(json_response({"ok": False, "error": "NotReadableError", "why": str(err)}))


def _left_behind(folder: Path) -> None:
    """Writes of an app that ended halfway, a while ago: not left in a folder Drive copies everywhere."""
    now = time.time()
    try:
        for entry in os.scandir(folder):
            if entry.name.endswith(PART) and now - entry.stat().st_mtime > WRITE_FOR:
                _gone(entry.path)
    except OSError:
        pass


def _gone(path) -> None:
    try:
        os.unlink(path)
    except OSError:
        pass
