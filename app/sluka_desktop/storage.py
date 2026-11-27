# SPDX-License-Identifier: LicenseRef-Sluka
# Copyright (c) 2026 Sluka. Part of Sluka Desktop; see LICENSE.txt.
"""What ``chrome.storage.local`` is kept in: one SQLite file in the data folder.

The word list is the one thing in this app that cannot be rebuilt, so it does
not live in the web engine's own storage, where an engine update or a full
disk can take it.  It lives here, in a file that is written atomically (a
write either lands whole or not at all, also when the USB stick is pulled),
that any SQLite tool can open, and that is copied aside once a day.

Values are stored as the JSON text the page sent.  They are never parsed here:
a word list is megabytes, and Python has no reason to look inside it.
"""

from __future__ import annotations

import os
import shutil
import sqlite3
import threading
import time
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS kv (
    area  TEXT NOT NULL,
    key   TEXT NOT NULL,
    value TEXT NOT NULL,
    PRIMARY KEY (area, key)
) WITHOUT ROWID;

CREATE TABLE IF NOT EXISTS downloads (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    rel     TEXT NOT NULL,
    path    TEXT NOT NULL,
    size    INTEGER NOT NULL DEFAULT 0,
    started REAL NOT NULL DEFAULT 0,
    state   TEXT NOT NULL DEFAULT 'complete',
    error   TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
) WITHOUT ROWID;
"""

#: Daily copies of the storage file kept beside it.
SNAPSHOTS_KEPT = 7


class Store:
    """Persistent areas in SQLite, and a ``session`` area that lives in memory."""

    PERSISTENT = ("local", "sync")

    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._db = sqlite3.connect(str(self.path), check_same_thread=False, isolation_level=None, timeout=30)
        # WAL keeps readers and the writer out of each other's way; FULL makes
        # every commit reach the disk before it is acknowledged.
        try:
            self._db.execute("PRAGMA journal_mode=WAL")
        except sqlite3.DatabaseError:
            pass
        self._db.execute("PRAGMA synchronous=FULL")
        self._db.executescript(SCHEMA)
        self._session: dict[str, str] = {}
        try:
            os.chmod(self.path, 0o600)
        except OSError:
            pass

    # -- key/value --------------------------------------------------------

    def get(self, area: str, keys: list[str] | None = None) -> dict[str, str]:
        """Raw JSON text by key; every key when ``keys`` is None."""
        with self._lock:
            if area == "session":
                if keys is None:
                    return dict(self._session)
                return {k: self._session[k] for k in keys if k in self._session}
            if keys is None:
                rows = self._db.execute("SELECT key, value FROM kv WHERE area = ?", (area,)).fetchall()
                return dict(rows)
            out: dict[str, str] = {}
            for start in range(0, len(keys), 500):
                chunk = keys[start:start + 500]
                marks = ",".join("?" * len(chunk))
                rows = self._db.execute(
                    f"SELECT key, value FROM kv WHERE area = ? AND key IN ({marks})", (area, *chunk)
                ).fetchall()
                out.update(rows)
            return out

    def keys(self, area: str) -> list[str]:
        with self._lock:
            if area == "session":
                return list(self._session)
            return [row[0] for row in self._db.execute("SELECT key FROM kv WHERE area = ?", (area,))]

    def set(self, area: str, items: dict[str, str]) -> dict[str, str]:
        """Write ``items`` (raw JSON text); answers what each key held before."""
        if not items:
            return {}
        with self._lock:
            old = self.get(area, list(items))
            if area == "session":
                self._session.update(items)
                return old
            self._db.execute("BEGIN IMMEDIATE")
            try:
                self._db.executemany(
                    "INSERT INTO kv (area, key, value) VALUES (?, ?, ?) "
                    "ON CONFLICT (area, key) DO UPDATE SET value = excluded.value",
                    [(area, k, v) for k, v in items.items()],
                )
                self._db.execute("COMMIT")
            except BaseException:
                self._db.execute("ROLLBACK")
                raise
            return old

    def remove(self, area: str, keys: list[str]) -> dict[str, str]:
        if not keys:
            return {}
        with self._lock:
            old = self.get(area, keys)
            if area == "session":
                for k in keys:
                    self._session.pop(k, None)
                return old
            self._db.execute("BEGIN IMMEDIATE")
            try:
                self._db.executemany("DELETE FROM kv WHERE area = ? AND key = ?", [(area, k) for k in keys])
                self._db.execute("COMMIT")
            except BaseException:
                self._db.execute("ROLLBACK")
                raise
            return old

    def clear(self, area: str) -> dict[str, str]:
        with self._lock:
            old = self.get(area, None)
            if area == "session":
                self._session.clear()
            else:
                self._db.execute("DELETE FROM kv WHERE area = ?", (area,))
            return old

    def bytes_in_use(self, area: str, keys: list[str] | None = None) -> int:
        items = self.get(area, keys)
        return sum(len(k.encode("utf-8")) + len(v.encode("utf-8")) for k, v in items.items())

    # -- meta -------------------------------------------------------------

    def meta_get(self, key: str, default: str = "") -> str:
        with self._lock:
            row = self._db.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
            return row[0] if row else default

    def meta_set(self, key: str, value: str) -> None:
        with self._lock:
            self._db.execute(
                "INSERT INTO meta (key, value) VALUES (?, ?) ON CONFLICT (key) DO UPDATE SET value = excluded.value",
                (key, value),
            )

    # -- downloads --------------------------------------------------------

    def download_add(self, rel: str, path: str, size: int, state: str = "complete", error: str = "") -> int:
        with self._lock:
            cur = self._db.execute(
                "INSERT INTO downloads (rel, path, size, started, state, error) VALUES (?, ?, ?, ?, ?, ?)",
                (rel, path, size, time.time(), state, error),
            )
            return int(cur.lastrowid)

    def download_get(self, ident: int) -> dict | None:
        with self._lock:
            row = self._db.execute(
                "SELECT id, rel, path, size, started, state, error FROM downloads WHERE id = ?", (ident,)
            ).fetchone()
        return _download_row(row) if row else None

    def download_list(self, limit: int = 200) -> list[dict]:
        with self._lock:
            rows = self._db.execute(
                "SELECT id, rel, path, size, started, state, error FROM downloads ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
        return [_download_row(row) for row in rows]

    def download_forget(self, ident: int) -> None:
        with self._lock:
            self._db.execute("DELETE FROM downloads WHERE id = ?", (ident,))

    # -- safety copies ----------------------------------------------------

    def snapshot_daily(self, folder: Path) -> Path | None:
        """Copy the storage file aside, at most once a day; keeps the last few.

        Uses SQLite's own backup, so the copy is consistent even while the app
        is writing.  Returns the new copy, or None when today's already exists.
        """
        folder.mkdir(parents=True, exist_ok=True)
        target = folder / f"storage-{time.strftime('%Y-%m-%d')}.sqlite"
        if target.exists():
            return None
        with self._lock:
            has_rows = self._db.execute("SELECT 1 FROM kv LIMIT 1").fetchone()
            if not has_rows:
                return None
            partial = target.with_suffix(".partial")
            try:
                copy = sqlite3.connect(str(partial))
                try:
                    self._db.backup(copy)
                finally:
                    copy.close()
                os.replace(partial, target)
                os.chmod(target, 0o600)
            except (sqlite3.Error, OSError):
                try:
                    partial.unlink()
                except OSError:
                    pass
                return None
        kept = sorted(folder.glob("storage-*.sqlite"))
        for stale in kept[:-SNAPSHOTS_KEPT]:
            try:
                stale.unlink()
            except OSError:
                pass
        return target

    def close(self) -> None:
        with self._lock:
            try:
                self._db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            except sqlite3.Error:
                pass
            self._db.close()


def _download_row(row) -> dict:
    ident, rel, path, size, started, state, error = row
    return {
        "id": ident,
        "rel": rel,
        "path": path,
        "size": size,
        "started": started,
        "state": state,
        "error": error,
        "exists": os.path.isfile(path),
    }


def free_bytes(path: Path) -> int:
    try:
        return shutil.disk_usage(str(path)).free
    except OSError:
        return -1
