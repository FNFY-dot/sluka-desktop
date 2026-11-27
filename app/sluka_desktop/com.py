# SPDX-License-Identifier: LicenseRef-Sluka
# Copyright (c) 2026 Sluka. Part of Sluka Desktop; see LICENSE.txt.
"""The little of COM that Windows' web view needs, with nothing but ctypes.

WebView2 is a set of COM interfaces: objects whose first field points to a
table of functions (the "vtable").  This module does two things with them:

*   calls a method of an object the engine made -- the function at a given
    place in its table (``call``) -- and lets go of it (``release``);
*   makes objects of its own the engine can call back (``ComObject``): the
    "handlers" WebView2 is given for everything that happens later, and the
    options it is started with.

Nothing here is particular to WebView2 or to Windows, so it can be tried
anywhere ctypes is: on Windows the functions are ``stdcall`` (WINFUNCTYPE),
elsewhere -- in the tests -- the platform's own convention, which on 64-bit
machines is the same thing.
"""

from __future__ import annotations

import ctypes
import logging
import sys
import threading
from ctypes import POINTER, Structure, byref, c_int32, c_size_t, c_ubyte, c_uint16, c_uint32, c_ulong, c_void_p, cast

log = logging.getLogger("sluka.com")

#: Functions COM calls, and COM functions called: stdcall on Windows.
FUNCTYPE = getattr(ctypes, "WINFUNCTYPE", ctypes.CFUNCTYPE)
#: A COM result: 0 and up is success, a negative number is the reason it failed.
HRESULT = c_int32


def _signed(value: int) -> int:
    return value - (1 << 32) if value & 0x80000000 else value


S_OK = 0
S_FALSE = 1
E_NOTIMPL = _signed(0x80004001)
E_NOINTERFACE = _signed(0x80004002)
E_POINTER = _signed(0x80004003)
E_ABORT = _signed(0x80004004)
E_FAIL = _signed(0x80004005)
E_UNEXPECTED = _signed(0x8000FFFF)
E_OUTOFMEMORY = _signed(0x8007000E)
E_INVALIDARG = _signed(0x80070057)


def hex_hresult(hr: int) -> str:
    return f"0x{int(hr) & 0xFFFFFFFF:08X}"


#: What some results mean, for the log and for what the user is told.
KNOWN = {
    _signed(0x80070002): "a file was not found",
    _signed(0x80070005): "access was refused (the data folder may not be writable)",
    _signed(0x8007139F): "the web view's data folder is in use with other settings (a copy of the app with other settings is running)",
    _signed(0x80070490): "the web view runtime was not found",
    _signed(0x8007007E): "a part of the web view runtime could not be loaded",
    _signed(0x800700AA): "the web view's data folder is in use",
    _signed(0x80010106): "this thread was already set up for COM in another way",
    E_ABORT: "it was stopped",
    E_FAIL: "it failed",
    E_UNEXPECTED: "something unexpected happened",
    E_INVALIDARG: "a wrong argument",
    E_NOINTERFACE: "the engine does not offer that",
    E_OUTOFMEMORY: "out of memory",
}


def describe(hr: int) -> str:
    said = KNOWN.get(int(hr))
    return f"{hex_hresult(hr)}, {said}" if said else hex_hresult(hr)


class ComError(OSError):
    """A COM call that answered with a failure."""

    def __init__(self, hr: int, what: str = ""):
        self.hresult = int(hr)
        super().__init__(f"{what or 'a COM call'} failed ({describe(hr)})")


# ---------------------------------------------------------------- GUIDs


class GUID(Structure):
    _fields_ = [("Data1", c_uint32), ("Data2", c_uint16), ("Data3", c_uint16), ("Data4", c_ubyte * 8)]

    @classmethod
    def parse(cls, text: str) -> "GUID":
        hexes = text.strip().strip("{}").replace("-", "")
        if len(hexes) != 32:
            raise ValueError(f"not a GUID: {text!r}")
        guid = cls()
        guid.Data1 = int(hexes[0:8], 16)
        guid.Data2 = int(hexes[8:12], 16)
        guid.Data3 = int(hexes[12:16], 16)
        for i in range(8):
            guid.Data4[i] = int(hexes[16 + 2 * i:18 + 2 * i], 16)
        return guid

    def text(self) -> str:
        rest = bytes(self.Data4).hex()
        return f"{{{self.Data1:08x}-{self.Data2:04x}-{self.Data3:04x}-{rest[:4]}-{rest[4:]}}}"

    def __str__(self) -> str:
        return self.text()


def norm_iid(text: str) -> str:
    return GUID.parse(text).text()


IID_IUnknown = "{00000000-0000-0000-c000-000000000046}"


# ---------------------------------------------------------------- memory the engine frees, or gives to be freed


class _TaskMemory:
    """CoTaskMemAlloc and CoTaskMemFree: how COM hands strings across.  (malloc and free outside Windows.)"""

    def __init__(self):
        self.alloc = None
        self.free = None

    def _load(self) -> None:
        if self.alloc is not None:
            return
        if sys.platform == "win32":
            ole32 = ctypes.WinDLL("ole32")
            alloc, free = ole32.CoTaskMemAlloc, ole32.CoTaskMemFree
        else:
            libc = ctypes.CDLL(None)
            alloc, free = libc.malloc, libc.free
        alloc.restype, alloc.argtypes = c_void_p, [c_size_t]
        free.restype, free.argtypes = None, [c_void_p]
        self.alloc, self.free = alloc, free


_memory = _TaskMemory()


def task_string(text: str) -> int:
    """``text`` in memory of COM's own, for an out-parameter: whoever receives it frees it."""
    _memory._load()
    buffer = ctypes.create_unicode_buffer(text or "")
    size = ctypes.sizeof(buffer)
    address = _memory.alloc(size)
    if not address:
        raise MemoryError("CoTaskMemAlloc")
    ctypes.memmove(address, buffer, size)
    return address


def take_string(address) -> str:
    """The text an out-parameter pointed to, and the memory it was in given back."""
    if not address:
        return ""
    _memory._load()
    try:
        return ctypes.wstring_at(address)
    finally:
        _memory.free(address)


def free_task_memory(address) -> None:
    if address:
        _memory._load()
        _memory.free(address)


# ---------------------------------------------------------------- calling the engine's objects

_prototypes: dict = {}


def _prototype(restype, argtypes: tuple):
    key = (restype, argtypes)
    found = _prototypes.get(key)
    if found is None:
        found = _prototypes[key] = FUNCTYPE(restype, c_void_p, *argtypes)
    return found


def method(ptr: int, index: int, argtypes: tuple = (), restype=HRESULT):
    """The function at ``index`` in the table of the object at ``ptr``, ready to be called with ``ptr`` first."""
    if not ptr:
        raise ComError(E_POINTER, f"method {index} of a null object")
    table = cast(c_void_p(ptr), POINTER(c_void_p))[0]
    address = cast(c_void_p(table), POINTER(c_void_p))[index]
    return _prototype(restype, tuple(argtypes))(address)


def call(ptr: int, index: int, argtypes: tuple = (), *args, what: str = "") -> int:
    """Call a method and raise ComError if it answers with a failure; the (successful) result otherwise."""
    hr = method(ptr, index, argtypes)(ptr, *args)
    if hr < 0:
        raise ComError(hr, what or f"method {index}")
    return hr


def add_ref(ptr: int) -> int:
    return method(ptr, 1, (), c_ulong)(ptr)


def release(ptr: int) -> int:
    return method(ptr, 2, (), c_ulong)(ptr)


def query(ptr: int, iid: str) -> int:
    """The object's interface ``iid`` (a reference that is the caller's to release), or 0 if it has none."""
    out = c_void_p()
    guid = GUID.parse(iid)
    hr = method(ptr, 0, (POINTER(GUID), POINTER(c_void_p)))(ptr, byref(guid), byref(out))
    return int(out.value or 0) if hr >= 0 else 0


class Interface:
    """An interface of an object of the engine's, of which this side holds one reference."""

    def __init__(self, ptr: int):
        self.ptr = int(ptr or 0)

    @classmethod
    def borrowed(cls, ptr: int):
        """One handed in as an argument: kept, so a reference of its own is taken."""
        if ptr:
            add_ref(int(ptr))
        return cls(ptr)

    def call(self, index: int, argtypes: tuple = (), *args, what: str = "") -> int:
        return call(self.ptr, index, argtypes, *args, what=what or f"{type(self).__name__} method {index}")

    def get_bool(self, index: int, what: str = "") -> bool:
        value = ctypes.c_int()
        self.call(index, (POINTER(ctypes.c_int),), byref(value), what=what)
        return bool(value.value)

    def set_bool(self, index: int, value: bool, what: str = "") -> None:
        self.call(index, (ctypes.c_int,), 1 if value else 0, what=what)

    def get_int(self, index: int, what: str = "") -> int:
        value = ctypes.c_int()
        self.call(index, (POINTER(ctypes.c_int),), byref(value), what=what)
        return int(value.value)

    def set_int(self, index: int, value: int, what: str = "") -> None:
        self.call(index, (ctypes.c_int,), int(value), what=what)

    def get_string(self, index: int, what: str = "") -> str:
        out = c_void_p()
        self.call(index, (POINTER(c_void_p),), byref(out), what=what)
        return take_string(out.value)

    def set_string(self, index: int, value: str, what: str = "") -> None:
        self.call(index, (ctypes.c_wchar_p,), value, what=what)

    def get_object(self, index: int, cls=None, what: str = ""):
        out = c_void_p()
        self.call(index, (POINTER(c_void_p),), byref(out), what=what)
        return (cls or Interface)(int(out.value or 0))

    def query(self, iid: str, cls=None):
        found = query(self.ptr, iid) if self.ptr else 0
        return (cls or Interface)(found) if found else None

    def release(self) -> None:
        ptr, self.ptr = self.ptr, 0
        if ptr:
            try:
                release(ptr)
            except Exception:  # an object already gone with its process
                log.debug("releasing an interface failed", exc_info=True)

    def __bool__(self) -> bool:
        return bool(self.ptr)


# ---------------------------------------------------------------- objects of this side's, for the engine to call

_QUERY = FUNCTYPE(HRESULT, c_void_p, POINTER(GUID), POINTER(c_void_p))
_COUNT = FUNCTYPE(c_ulong, c_void_p)


class _Layout(Structure):
    _fields_ = [("vtable", c_void_p)]


_lock = threading.RLock()
#: Every object of this side's the engine may still call, by its address.
_live: dict = {}
#: Objects the engine has let go of, kept until no call into any of them can be under way.
_released: list = []
#: How many calls from the engine into this side's objects are under way right now (on any thread).
_inside = [0]


class ComObject:
    """A COM object written in Python: IUnknown, and the methods a subclass names.

    ``IIDS`` are the interfaces it is (besides IUnknown); ``METHODS`` are
    ``(name of a method of the subclass, its argument types)`` for each entry
    of its table after IUnknown's three, in order.  Each returns an HRESULT;
    a method that returns None answers S_OK.  An error inside one is logged
    and answered with ``ON_ERROR``: it is never let through into the engine.

    It starts with one reference, the maker's, which is given up with
    ``drop()`` once the engine has been handed the object.  An object the
    engine has let go of is freed later (``collect``), never while one of its
    own calls is still on the way back.
    """

    IIDS: tuple = ()
    METHODS: tuple = ()
    ON_ERROR = S_OK

    def __init__(self):
        self._refs = 1
        self._dropped = False
        self._kinds = {norm_iid(IID_IUnknown)} | {norm_iid(iid) for iid in self.IIDS}
        thunks = [_QUERY(self._guarded(self._query_interface)), _COUNT(self._guarded(self._add_ref, count=True)),
                  _COUNT(self._guarded(self._release, count=True))]
        for name, argtypes in self.METHODS:
            thunks.append(FUNCTYPE(HRESULT, c_void_p, *argtypes)(self._guarded(getattr(self, name), name=name)))
        self._thunks = thunks
        self._table = (c_void_p * len(thunks))(*[cast(t, c_void_p).value for t in thunks])
        self._layout = _Layout(ctypes.addressof(self._table))
        self.ptr = ctypes.addressof(self._layout)
        with _lock:
            _live[self.ptr] = self

    def _guarded(self, fn, name: str = "", count: bool = False):
        own = type(self).__name__

        def thunk(_this, *args):
            with _lock:
                _inside[0] += 1
            try:
                if count:
                    return fn()
                result = fn(*args)
                return S_OK if result is None else int(result)
            except BaseException:  # nothing raised here may reach the engine's code
                log.exception("%s.%s failed", own, name or getattr(fn, "__name__", "?"))
                return 0 if count else self.ON_ERROR
            finally:
                with _lock:
                    _inside[0] -= 1

        return thunk

    def _query_interface(self, riid, ppv):
        if not ppv:
            return E_POINTER
        asked = riid.contents.text() if riid else ""
        if asked in self._kinds:
            ppv[0] = self.ptr
            self._add_ref()
            return S_OK
        ppv[0] = None
        log.debug("%s was asked for %s, which it is not", type(self).__name__, asked)
        return E_NOINTERFACE

    def _add_ref(self) -> int:
        with _lock:
            self._refs += 1
            return self._refs

    def _release(self) -> int:
        with _lock:
            self._refs -= 1
            left = self._refs
            if left <= 0 and _live.get(self.ptr) is self:
                del _live[self.ptr]
                _released.append(self)
        return max(left, 0)

    def drop(self) -> None:
        """Give up the maker's reference (once)."""
        if not self._dropped:
            self._dropped = True
            self._release()

    @property
    def refs(self) -> int:
        return self._refs


def collect() -> int:
    """Free the objects the engine let go of, if no call into any of this side's objects is under way."""
    with _lock:
        if _inside[0] or not _released:
            return 0
        gone = len(_released)
        _released.clear()
    return gone


def live_objects() -> int:
    with _lock:
        return len(_live)
