"""Stand-ins for the Windows functions winproc.py and clipwatch.py call, so their Windows-only code runs on Linux.

ctypes.WinDLL("user32") gives a FakeDLL here, whose functions are Python stand-ins that answer as Windows
does: buffers are filled, values behind byref() set, callbacks called, a window's messages queued and handed to
its window procedure.  The prototypes the app's code sets (restype, argtypes) are kept, and checked against
what the functions are called with: a call with another number of arguments than its argtypes fails here as
it would mislead the real function there.
"""

from __future__ import annotations

import ctypes
import queue
import threading
from ctypes import wintypes


class FakeFunc:
    def __init__(self, dll, name, impl):
        self.dll, self.name, self.impl = dll, name, impl
        self.restype = ctypes.c_int
        self.argtypes = None
        self.calls = []

    def __call__(self, *args):
        if self.argtypes is not None and len(args) != len(self.argtypes):
            raise TypeError(f"{self.name} takes {len(self.argtypes)} arguments, was given {len(args)}")
        self.calls.append(args)
        return self.impl(*args)


def deref(arg):
    """What byref() points at."""
    return getattr(arg, "_obj", arg)


class World:
    """One computer: its windows, programs, clipboard, and the message queues of the windows made here."""

    WM_QUIT = 0x0012

    def __init__(self):
        self.windows = []        # [hwnd, pid, title, visible, owner, exstyle, cloaked]
        self.procs = {}          # pid -> (path, parent, wow64, reachable)
        self.foreground = 0
        self.last_error = 0
        self.handles = {}
        self.next_handle = 100
        self.classes = {}
        self.window_procs = {}
        self.queues = {}
        self.clipboard = {}      # format -> bytes
        self.clipboard_owner = 0
        self.globals = {}
        self.formats = {}
        self.jobs = []
        self.lock = threading.Lock()

    def handle(self, what):
        with self.lock:
            self.next_handle += 4
            self.handles[self.next_handle] = what
            return self.next_handle

    # ------------------------------------------------------------ the programs (user32, kernel32)

    def EnumWindows(self, callback, lparam):
        for window in list(self.windows):
            if not callback(window[0], lparam):
                break
        return 1

    def _window(self, hwnd):
        return next((w for w in self.windows if w[0] == hwnd), None)

    def IsWindowVisible(self, hwnd):
        return int(bool(self._window(hwnd)[3]))

    def GetWindowTextLengthW(self, hwnd):
        return len(self._window(hwnd)[2])

    def GetWindowTextW(self, hwnd, buffer, size):
        text = self._window(hwnd)[2][: size - 1]
        buffer.value = text
        return len(text)

    def GetWindowThreadProcessId(self, hwnd, pid):
        window = self._window(hwnd)
        deref(pid).value = window[1] if window else 0
        return 1

    def GetWindow(self, hwnd, kind):
        return self._window(hwnd)[4]

    def GetWindowLongPtrW(self, hwnd, index):
        return self._window(hwnd)[5]

    def GetForegroundWindow(self):
        return self.foreground

    def DwmGetWindowAttribute(self, hwnd, attribute, out, size):
        deref(out).value = self._window(hwnd)[6]
        return 0

    def OpenProcess(self, access, inherit, pid):
        proc = self.procs.get(pid)
        if proc is None:
            self.last_error = 87
            return None
        if access & 0x0002 and not proc[3]:  # the rights to inject
            self.last_error = 5
            return None
        return self.handle(("process", pid))

    def CloseHandle(self, handle):
        self.handles.pop(handle, None)
        return 1

    def QueryFullProcessImageNameW(self, handle, flags, buffer, size):
        pid = self.handles[handle][1]
        buffer.value = self.procs[pid][0]
        deref(size).value = len(self.procs[pid][0])
        return 1

    def IsWow64Process(self, handle, wow):
        deref(wow).value = int(self.procs[self.handles[handle][1]][2])
        return 1

    def IsWow64Process2(self, handle, machine, native):
        deref(machine).value = 0x14C if self.procs[self.handles[handle][1]][2] else 0
        deref(native).value = 0x8664
        return 1

    def GetExitCodeProcess(self, handle, code):
        deref(code).value = 259
        return 1

    def WaitForSingleObject(self, handle, ms):
        what = self.handles.get(handle)
        return 0x102 if what and what[1] in self.procs else 0

    def CreateToolhelp32Snapshot(self, flags, pid):
        return self.handle(("snapshot", sorted(self.procs.items()), [0]))

    def _entry(self, snapshot, entry):
        items, at = self.handles[snapshot][1], self.handles[snapshot][2]
        if at[0] >= len(items):
            return 0
        pid, (path, parent, _wow, _reach) = items[at[0]]
        at[0] += 1
        e = deref(entry)
        assert e.dwSize == ctypes.sizeof(e)
        e.th32ProcessID, e.th32ParentProcessID, e.szExeFile = pid, parent, path.split("\\")[-1]
        return 1

    def Process32FirstW(self, snapshot, entry):
        self.handles[snapshot][2][0] = 0
        return self._entry(snapshot, entry)

    def Process32NextW(self, snapshot, entry):
        return self._entry(snapshot, entry)

    def GetCurrentProcess(self):
        return -1

    def CreateJobObjectW(self, attributes, name):
        return self.handle(("job",))

    def SetInformationJobObject(self, job, kind, info, size):
        assert kind == 9 and size == ctypes.sizeof(deref(info))
        self.jobs.append(("limits", deref(info).BasicLimitInformation.LimitFlags))
        return 1

    def AssignProcessToJobObject(self, job, process):
        self.jobs.append(("assigned", process.value if hasattr(process, "value") else process))
        return 1

    def IsUserAnAdmin(self):
        return 0

    # ------------------------------------------------------------ windows of the app's own, and the clipboard

    def GetModuleHandleW(self, name):
        return 0x400000

    def RegisterClassW(self, klass):
        k = deref(klass)
        if k.lpszClassName in self.classes:
            self.last_error = 1410
            return 0
        self.classes[k.lpszClassName] = k.lpfnWndProc
        return len(self.classes)

    def CreateWindowExW(self, ex, klass, title, style, x, y, w, h, parent, menu, instance, param):
        hwnd = self.handle(("window", klass))
        self.window_procs[hwnd] = self.classes[klass]
        self.queues[hwnd] = queue.Queue()
        self.windows_thread = hwnd
        return hwnd

    def DestroyWindow(self, hwnd):
        proc = self.window_procs.pop(hwnd)
        proc(hwnd, 0x0002, 0, 0)  # WM_DESTROY
        return 1

    def DefWindowProcW(self, hwnd, message, wparam, lparam):
        return 0

    def GetMessageW(self, msg, hwnd, low, high):
        q = self.queues[self.windows_thread]
        message = q.get()
        m = deref(msg)
        m.hwnd, m.message, m.wParam, m.lParam = message
        return 0 if message[1] == self.WM_QUIT else 1

    def TranslateMessage(self, msg):
        return 0

    def DispatchMessageW(self, msg):
        m = deref(msg)
        proc = self.window_procs.get(m.hwnd)
        return proc(m.hwnd, m.message, m.wParam, m.lParam) if proc else 0

    def PostMessageW(self, hwnd, message, wparam, lparam):
        q = self.queues.get(hwnd)
        if q is None:
            return 0
        q.put((hwnd, message, wparam, lparam))
        return 1

    def PostQuitMessage(self, code):
        self.queues[self.windows_thread].put((None, self.WM_QUIT, code, 0))

    def AddClipboardFormatListener(self, hwnd):
        self.listener = hwnd
        return 1

    def RemoveClipboardFormatListener(self, hwnd):
        self.listener = 0
        return 1

    def OpenClipboard(self, hwnd):
        self.opened_by = hwnd
        return 1

    def CloseClipboard(self):
        self.opened_by = None
        return 1

    def EmptyClipboard(self):
        self.clipboard = {}
        self.clipboard_owner = self.opened_by
        return 1

    def GlobalAlloc(self, flags, size):
        buffer = ctypes.create_string_buffer(size)
        handle = self.handle(("global",))
        self.globals[handle] = buffer
        return handle

    def GlobalFree(self, handle):
        self.globals.pop(handle, None)
        return None

    def GlobalLock(self, handle):
        return ctypes.addressof(self.globals[handle])

    def GlobalUnlock(self, handle):
        return 1

    def GlobalSize(self, handle):
        return ctypes.sizeof(self.globals[handle])

    def SetClipboardData(self, fmt, handle):
        assert self.opened_by is not None
        self.clipboard[fmt] = bytes(self.globals[handle])
        return handle

    def GetClipboardData(self, fmt):
        data = self.clipboard.get(fmt)
        if data is None:
            return None
        handle = self.GlobalAlloc(0, len(data))
        ctypes.memmove(self.globals[handle], data, len(data))
        return handle

    def GetClipboardOwner(self):
        return self.clipboard_owner

    def RegisterClipboardFormatW(self, name):
        return self.formats.setdefault(name, 0xC000 + len(self.formats))

    # ------------------------------------------------------------ what another program does

    def copy(self, text, owner=0):
        """Another program copies text: the clipboard changes, and the listening window is told."""
        self.clipboard = {13: (text + "\0").encode("utf-16-le")}
        self.clipboard_owner = owner
        self.PostMessageW(self.listener, 0x031D, 0, 0)


class FakeDLL:
    OPTIONAL = {"IsWow64Process2"}

    def __init__(self, world, name, missing=()):
        self._world, self._name, self._missing = world, name, set(missing)
        self._funcs = {}

    def __getattr__(self, name):
        if name.startswith("_"):
            raise AttributeError(name)
        if name in self._missing:
            raise AttributeError(name)
        if name not in self._funcs:
            impl = getattr(self._world, name, None)
            if impl is None:
                raise AttributeError(f"{self._name} has no {name} here")
            self._funcs[name] = FakeFunc(self, name, impl)
        return self._funcs[name]


def install(monkeypatch, world, missing=()):
    """ctypes as on Windows, with ``world`` behind it."""
    dlls = {}

    def windll(name, use_last_error=False):
        return dlls.setdefault(name, FakeDLL(world, name, missing))

    monkeypatch.setattr(ctypes, "WinDLL", windll, raising=False)
    monkeypatch.setattr(ctypes, "WINFUNCTYPE", ctypes.CFUNCTYPE, raising=False)
    monkeypatch.setattr(ctypes, "get_last_error", lambda: world.last_error, raising=False)
    return dlls
