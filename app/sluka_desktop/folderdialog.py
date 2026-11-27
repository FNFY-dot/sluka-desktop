# SPDX-License-Identifier: LicenseRef-Sluka
# Copyright (c) 2026 Sluka. Part of Sluka Desktop; see LICENSE.txt.
"""Windows' own folder window (IFileOpenDialog, as a folder picker), for a folder chosen for Sluka (folders.py).

The same window Explorer and the browsers show, Google Drive (G:) and This PC on
its left.  It runs on a thread of its own, made a single-threaded apartment as
the shell's dialogs want, and the caller waits for its answer.
"""

from __future__ import annotations

import ctypes
import logging
import threading
import uuid
from ctypes import POINTER, byref, c_int32, c_uint32, c_void_p, c_wchar_p

from . import com

log = logging.getLogger("sluka.folderdialog")

CLSID_FileOpenDialog = "{dc1c5a9c-e88a-4dde-a5a1-60f82a20aef7}"
IID_IFileOpenDialog = "{d57c7288-d4ad-4768-be02-9d969532d960}"
COINIT_APARTMENTTHREADED = 0x2
CLSCTX_INPROC_SERVER = 0x1
FOS_NOCHANGEDIR = 0x8
FOS_PICKFOLDERS = 0x20
FOS_FORCEFILESYSTEM = 0x40
FOS_PATHMUSTEXIST = 0x800
SIGDN_FILESYSPATH = com._signed(0x80058000)
#: Show's answer when the window was closed without a folder: HRESULT_FROM_WIN32(ERROR_CANCELLED).
CANCELLED = com._signed(0x800704C7)

# Places in the tables (IUnknown 0-2, IModalWindow 3, IFileDialog 4-26; IShellItem 3-7).
SHOW, SET_OPTIONS, GET_OPTIONS, SET_TITLE, GET_RESULT, SET_CLIENT_GUID = 3, 9, 10, 17, 20, 24
GET_DISPLAY_NAME = 5


def _ask(title: str, owner: int, remember: str) -> str:
    ole32 = ctypes.WinDLL("ole32")
    ole32.CoInitializeEx(None, COINIT_APARTMENTTHREADED)
    try:
        dialog = c_void_p()
        clsid, iid = com.GUID.parse(CLSID_FileOpenDialog), com.GUID.parse(IID_IFileOpenDialog)
        hr = ole32.CoCreateInstance(byref(clsid), None, CLSCTX_INPROC_SERVER, byref(iid), byref(dialog))
        if hr < 0 or not dialog.value:
            raise com.ComError(hr, "the folder window")
        ptr = int(dialog.value)
        try:
            options = c_uint32()
            com.call(ptr, GET_OPTIONS, (POINTER(c_uint32),), byref(options), what="GetOptions")
            com.call(ptr, SET_OPTIONS, (c_uint32,),
                     options.value | FOS_PICKFOLDERS | FOS_FORCEFILESYSTEM | FOS_PATHMUSTEXIST | FOS_NOCHANGEDIR, what="SetOptions")
            com.call(ptr, SET_TITLE, (c_wchar_p,), title, what="SetTitle")
            if remember:
                # (the window remembers the last folder it was in, for this purpose apart from others)
                guid = com.GUID.parse(str(uuid.uuid5(uuid.NAMESPACE_URL, f"sluka-desktop:{remember}")))
                com.method(ptr, SET_CLIENT_GUID, (POINTER(com.GUID),))(ptr, byref(guid))
            hr = com.method(ptr, SHOW, (c_void_p,))(ptr, c_void_p(owner or None))
            if hr == CANCELLED:
                return ""
            if hr < 0:
                raise com.ComError(hr, "Show")
            item = c_void_p()
            com.call(ptr, GET_RESULT, (POINTER(c_void_p),), byref(item), what="GetResult")
            try:
                name = c_void_p()
                com.call(int(item.value), GET_DISPLAY_NAME, (c_int32, POINTER(c_void_p)), SIGDN_FILESYSPATH, byref(name),
                         what="GetDisplayName")
                return com.take_string(name.value)
            finally:
                com.release(int(item.value))
        finally:
            com.release(ptr)
    finally:
        ole32.CoUninitialize()


def pick_folder(title: str, owner: int = 0, remember: str = "") -> str:
    """The folder chosen, as a path; "" when the window was closed without one (or could not be shown)."""
    got = {"path": ""}

    def run():
        try:
            got["path"] = _ask(title, owner, remember) or ""
        except Exception:
            log.exception("the folder window could not be shown")

    thread = threading.Thread(target=run, name="sluka-folder-window", daemon=True)
    thread.start()
    thread.join()
    return got["path"]
