"""Folders chosen for Sluka (sluka_desktop/folders.py): Settings → Sync & backup's backup folder, in a Google Drive
folder or anywhere -- chosen in the system's folder window, kept across starts, and nothing outside it reachable."""

from __future__ import annotations

import io
import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from fakes import APP  # noqa: F401  (puts the app on the path)
from sluka_desktop import folders as F
from sluka_desktop.host import Request


def made(tmp_path, chosen):
    return F.Folders(SimpleNamespace(data_dir=tmp_path / "data"), picker=lambda title, remember="": str(chosen))


def call(f, name, body=None, query=None, raw=None, method="POST", site="same-origin", stream=False):
    data = raw if raw is not None else json.dumps(body or {}).encode()
    reader = io.BytesIO(data).read if stream else None
    req = Request(method=method, path=f"/__sluka__/api/{name}", query=query or {}, headers={"sec-fetch-site": site},
                  body=b"" if stream else data, body_reader=reader)
    got = []
    f.api(name, req, got.append)
    return got[0]


def answer(resp):
    return json.loads(resp.body.decode())


def test_a_folder_chosen_is_kept_and_its_files_read_and_written(tmp_path):
    drive = tmp_path / "My Drive" / "Sluka"
    drive.mkdir(parents=True)
    (drive / "sluka-phone.json").write_text('{"from": "the phone"}', encoding="utf-8")
    f = made(tmp_path, drive)
    got = answer(call(f, "folders", {"op": "pick", "id": "pharos-backup"}))
    assert got["ok"] and got["name"] == "Sluka" and F.TOKEN.fullmatch(got["folder"])
    token = got["folder"]
    # The same folder again is the same token; and it is still known after a new start.
    assert answer(call(f, "folders", {"op": "pick"}))["folder"] == token
    f = made(tmp_path, drive)
    assert answer(call(f, "folders", {"op": "state", "folder": token}))["state"] == "granted"

    listed = answer(call(f, "folders", {"op": "list", "folder": token, "path": []}))["entries"]
    assert [(e["name"], e["kind"]) for e in listed] == [("sluka-phone.json", "file")]
    resp = call(f, "folders/read", method="GET", query={"folder": token, "path": json.dumps(["sluka-phone.json"])})
    assert Path(resp.file[0]).read_text(encoding="utf-8") == '{"from": "the phone"}'

    # A file written in pieces, put in place only once whole.
    assert answer(call(f, "folders", {"op": "touch", "folder": token, "path": ["sluka-pc.json"]}))["ok"]
    write = answer(call(f, "folders", {"op": "begin", "folder": token, "path": ["sluka-pc.json"]}))["write"]
    assert answer(call(f, "folders/piece", raw=b'{"from": ', query={"write": write, "at": "0"}))["ok"]
    assert answer(call(f, "folders/piece", raw=b'"the pc"}', query={"write": write, "at": "9"}, stream=True))["ok"]
    assert (drive / "sluka-pc.json").read_bytes() == b""
    names = [e["name"] for e in answer(call(f, "folders", {"op": "list", "folder": token, "path": []}))["entries"]]
    assert names == ["sluka-pc.json", "sluka-phone.json"]  # (the write's own file is not shown)
    assert answer(call(f, "folders", {"op": "end", "write": write}))["ok"]
    assert (drive / "sluka-pc.json").read_text() == '{"from": "the pc"}'
    assert not [p for p in drive.iterdir() if p.name.endswith(F.PART)]

    # Folders in it, removed whole when asked.
    assert answer(call(f, "folders", {"op": "mkdir", "folder": token, "path": ["books", "b1"]}))["ok"]
    assert answer(call(f, "folders", {"op": "kind", "folder": token, "path": ["books"]}))["kind"] == "directory"
    assert answer(call(f, "folders", {"op": "remove", "folder": token, "path": ["books"]}))["error"] == "InvalidModificationError"
    assert answer(call(f, "folders", {"op": "remove", "folder": token, "path": ["books"], "recursive": True}))["ok"]
    assert answer(call(f, "folders", {"op": "stat", "folder": token, "path": ["books"]}))["error"] == "NotFoundError"

    # Drive not there (signed out, another letter): asked for again, not written blind.
    os.rename(drive, tmp_path / "elsewhere")
    assert answer(call(f, "folders", {"op": "state", "folder": token}))["state"] == "gone"


def test_nothing_outside_a_chosen_folder_is_reachable(tmp_path):
    drive = tmp_path / "Sluka"
    drive.mkdir()
    (tmp_path / "secret.txt").write_text("no")
    f = made(tmp_path, drive)
    token = answer(call(f, "folders", {"op": "pick"}))["folder"]
    for path in (["..", "secret.txt"], ["../secret.txt"], [str(tmp_path / "secret.txt")], ["a\\..\\..\\secret.txt"], [""]):
        resp = call(f, "folders", {"op": "stat", "folder": token, "path": path})
        assert resp.status == 403, path
    if hasattr(os, "symlink"):
        os.symlink(tmp_path, drive / "out")
        assert call(f, "folders", {"op": "list", "folder": token, "path": ["out"]}).status == 403
    assert call(f, "folders/read", method="GET", query={"folder": token, "path": json.dumps(["..", "secret.txt"])}).status == 403
    # A folder never chosen, and a page of another site.
    assert call(f, "folders", {"op": "list", "folder": "0" * 32, "path": []}).status == 403
    assert call(f, "folders", {"op": "list", "folder": token, "path": []}, site="cross-site").status == 403
    # The window closed without a folder.
    f.picker = lambda title, remember="": ""
    assert answer(call(f, "folders", {"op": "pick"})) == {"ok": False, "cancelled": True}
    f.picker = None
    assert answer(call(f, "folders", {"op": "pick"}))["ok"] is False
