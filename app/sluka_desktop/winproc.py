# SPDX-License-Identifier: LicenseRef-Sluka
# Copyright (c) 2026 Sluka. Part of Sluka Desktop; see LICENSE.txt.
"""The programs running on this computer, as the game text menu needs them (Windows only).

Which windows there are and whose they are, which program file each comes
from, whether a program is 32- or 64-bit (a text hooker's own half has to be
the game's kind), whether this app may reach into it at all (a game started
as administrator cannot be reached from a program that was not), which window
is in front, and whether a program is still running.  Also a "job" that
takes the hooker down with the app, however the app ends.

Everything is asked of Windows with ctypes; elsewhere ``Procs`` lists
nothing, and the tests put a stand-in in its place.
"""

from __future__ import annotations

import ctypes
import logging
import os
import sys
from ctypes import wintypes

log = logging.getLogger("sluka.games")

WINDOWS = sys.platform == "win32"

PROCESS_CREATE_THREAD = 0x0002
PROCESS_VM_OPERATION = 0x0008
PROCESS_VM_READ = 0x0010
PROCESS_VM_WRITE = 0x0020
PROCESS_QUERY_INFORMATION = 0x0400
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
SYNCHRONIZE = 0x00100000
PROCESS_SUSPEND_RESUME = 0x0800
#: What pausing a program takes (Sluka Vision's "Pause the game"): no more.
PAUSE_RIGHTS = PROCESS_SUSPEND_RESUME | PROCESS_QUERY_LIMITED_INFORMATION | SYNCHRONIZE
#: What injecting a hook into a program takes (what Textractor and LunaHook open it with, less what is not needed).
INJECT_RIGHTS = PROCESS_CREATE_THREAD | PROCESS_VM_OPERATION | PROCESS_VM_READ | PROCESS_VM_WRITE | PROCESS_QUERY_INFORMATION
ERROR_ACCESS_DENIED = 5
STILL_ACTIVE = 259
WAIT_TIMEOUT = 0x102
TH32CS_SNAPPROCESS = 0x00000002
GW_OWNER = 4
GWL_EXSTYLE = -20
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_NOACTIVATE = 0x08000000
DWMWA_CLOAKED = 14
JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000
JOB_OBJECT_LIMIT_BREAKAWAY_OK = 0x00000800
JOB_OBJECT_EXTENDED_LIMIT_INFORMATION_CLASS = 9
IMAGE_FILE_MACHINE_I386 = 0x014C
IMAGE_FILE_MACHINE_AMD64 = 0x8664
IMAGE_FILE_MACHINE_ARM64 = 0xAA64

#: Programs that are part of Windows or of this app, never a game.
NOT_GAMES = {
    "explorer.exe", "applicationframehost.exe", "textinputhost.exe", "systemsettings.exe", "shellexperiencehost.exe",
    "searchhost.exe", "searchapp.exe", "startmenuexperiencehost.exe", "lockapp.exe", "msedgewebview2.exe",
    "taskmgr.exe", "dwm.exe", "csrss.exe", "winlogon.exe", "sihost.exe", "ctfmon.exe", "runtimebroker.exe",
    "widgets.exe", "phoneexperiencehost.exe", "gamebar.exe", "gamebarftserver.exe", "nvidia share.exe",
    "lunahostcli32.exe", "lunahostcli64.exe", "textractorcli.exe", "conhost.exe", "openconsole.exe",
    "windowsterminal.exe", "securityhealthsystray.exe", "smartscreen.exe",
}


def pe_bits(path) -> int:
    """32 or 64 for a Windows program file, from its header; 0 where it is not one."""
    try:
        with open(path, "rb") as handle:
            head = handle.read(4096)
    except OSError:
        return 0
    if len(head) < 0x40 or head[:2] != b"MZ":
        return 0
    at = int.from_bytes(head[0x3C:0x40], "little")
    if at <= 0 or at + 6 > len(head) or head[at:at + 4] != b"PE\0\0":
        return 0
    machine = int.from_bytes(head[at + 4:at + 6], "little")
    return {IMAGE_FILE_MACHINE_I386: 32, IMAGE_FILE_MACHINE_AMD64: 64, IMAGE_FILE_MACHINE_ARM64: 64}.get(machine, 0)


class PROCESSENTRY32W(ctypes.Structure):
    _fields_ = [
        ("dwSize", wintypes.DWORD),
        ("cntUsage", wintypes.DWORD),
        ("th32ProcessID", wintypes.DWORD),
        ("th32DefaultHeapID", ctypes.c_size_t),
        ("th32ModuleID", wintypes.DWORD),
        ("cntThreads", wintypes.DWORD),
        ("th32ParentProcessID", wintypes.DWORD),
        ("pcPriClassBase", ctypes.c_long),
        ("dwFlags", wintypes.DWORD),
        ("szExeFile", ctypes.c_wchar * 260),
    ]


class IO_COUNTERS(ctypes.Structure):
    _fields_ = [(name, ctypes.c_ulonglong) for name in (
        "ReadOperationCount", "WriteOperationCount", "OtherOperationCount", "ReadTransferCount", "WriteTransferCount",
        "OtherTransferCount")]


class JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("PerProcessUserTimeLimit", ctypes.c_int64),
        ("PerJobUserTimeLimit", ctypes.c_int64),
        ("LimitFlags", wintypes.DWORD),
        ("MinimumWorkingSetSize", ctypes.c_size_t),
        ("MaximumWorkingSetSize", ctypes.c_size_t),
        ("ActiveProcessLimit", wintypes.DWORD),
        ("Affinity", ctypes.c_size_t),
        ("PriorityClass", wintypes.DWORD),
        ("SchedulingClass", wintypes.DWORD),
    ]


class JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("BasicLimitInformation", JOBOBJECT_BASIC_LIMIT_INFORMATION),
        ("IoInfo", IO_COUNTERS),
        ("ProcessMemoryLimit", ctypes.c_size_t),
        ("JobMemoryLimit", ctypes.c_size_t),
        ("PeakProcessMemoryUsed", ctypes.c_size_t),
        ("PeakJobMemoryUsed", ctypes.c_size_t),
    ]


class _Api:
    """The functions of Windows used here, each with the types it takes and gives (pointers stay whole on 64-bit)."""

    def __init__(self):
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        HWND, HANDLE, DWORD, BOOL = wintypes.HWND, wintypes.HANDLE, wintypes.DWORD, wintypes.BOOL
        self.WNDENUMPROC = ctypes.WINFUNCTYPE(BOOL, HWND, wintypes.LPARAM)

        def fn(lib, name, restype, *argtypes, optional=False):
            try:
                f = getattr(lib, name)
            except AttributeError:
                if optional:
                    return None
                raise
            f.restype = restype
            f.argtypes = argtypes
            return f

        self.EnumWindows = fn(user32, "EnumWindows", BOOL, self.WNDENUMPROC, wintypes.LPARAM)
        self.IsWindowVisible = fn(user32, "IsWindowVisible", BOOL, HWND)
        self.GetWindowTextLengthW = fn(user32, "GetWindowTextLengthW", ctypes.c_int, HWND)
        self.GetWindowTextW = fn(user32, "GetWindowTextW", ctypes.c_int, HWND, wintypes.LPWSTR, ctypes.c_int)
        self.GetWindowThreadProcessId = fn(user32, "GetWindowThreadProcessId", DWORD, HWND, ctypes.POINTER(DWORD))
        self.GetWindow = fn(user32, "GetWindow", HWND, HWND, wintypes.UINT)
        self.GetForegroundWindow = fn(user32, "GetForegroundWindow", HWND)
        if ctypes.sizeof(ctypes.c_void_p) == 8:
            self.GetWindowLongPtrW = fn(user32, "GetWindowLongPtrW", ctypes.c_ssize_t, HWND, ctypes.c_int)
        else:
            self.GetWindowLongPtrW = fn(user32, "GetWindowLongW", ctypes.c_long, HWND, ctypes.c_int)
        try:
            dwmapi = ctypes.WinDLL("dwmapi")
            self.DwmGetWindowAttribute = fn(dwmapi, "DwmGetWindowAttribute", ctypes.c_long, HWND, DWORD, ctypes.c_void_p, DWORD)
        except OSError:
            self.DwmGetWindowAttribute = None
        self.OpenProcess = fn(kernel32, "OpenProcess", HANDLE, DWORD, BOOL, DWORD)
        self.CloseHandle = fn(kernel32, "CloseHandle", BOOL, HANDLE)
        self.QueryFullProcessImageNameW = fn(kernel32, "QueryFullProcessImageNameW", BOOL, HANDLE, DWORD, wintypes.LPWSTR,
                                             ctypes.POINTER(DWORD))
        self.IsWow64Process = fn(kernel32, "IsWow64Process", BOOL, HANDLE, ctypes.POINTER(BOOL))
        self.IsWow64Process2 = fn(kernel32, "IsWow64Process2", BOOL, HANDLE, ctypes.POINTER(wintypes.USHORT),
                                  ctypes.POINTER(wintypes.USHORT), optional=True)
        self.GetExitCodeProcess = fn(kernel32, "GetExitCodeProcess", BOOL, HANDLE, ctypes.POINTER(DWORD))
        self.WaitForSingleObject = fn(kernel32, "WaitForSingleObject", DWORD, HANDLE, DWORD)
        self.CreateToolhelp32Snapshot = fn(kernel32, "CreateToolhelp32Snapshot", HANDLE, DWORD, DWORD)
        self.Process32FirstW = fn(kernel32, "Process32FirstW", BOOL, HANDLE, ctypes.POINTER(PROCESSENTRY32W))
        self.Process32NextW = fn(kernel32, "Process32NextW", BOOL, HANDLE, ctypes.POINTER(PROCESSENTRY32W))
        self.GetCurrentProcess = fn(kernel32, "GetCurrentProcess", HANDLE)
        self.CreateJobObjectW = fn(kernel32, "CreateJobObjectW", HANDLE, ctypes.c_void_p, wintypes.LPCWSTR)
        self.SetInformationJobObject = fn(kernel32, "SetInformationJobObject", BOOL, HANDLE, ctypes.c_int, ctypes.c_void_p, DWORD)
        self.AssignProcessToJobObject = fn(kernel32, "AssignProcessToJobObject", BOOL, HANDLE, HANDLE)
        try:
            shell32 = ctypes.WinDLL("shell32")
            self.IsUserAnAdmin = fn(shell32, "IsUserAnAdmin", BOOL, optional=True)
        except OSError:
            self.IsUserAnAdmin = None
        # (for the screen reader: this app's own windows kept out of its pictures, and out of the way)
        self.GetClassNameW = fn(user32, "GetClassNameW", ctypes.c_int, HWND, wintypes.LPWSTR, ctypes.c_int, optional=True)
        self.IsIconic = fn(user32, "IsIconic", BOOL, HWND, optional=True)
        self.SetWindowDisplayAffinity = fn(user32, "SetWindowDisplayAffinity", BOOL, HWND, DWORD, optional=True)
        self.ShowWindowAsync = fn(user32, "ShowWindowAsync", BOOL, HWND, ctypes.c_int, optional=True)
        # (Sluka Vision's "Pause the game": a program's every thread held, and let go, as Resource Monitor's "Suspend
        # process" does -- and its start, so that a number Windows gives again is never taken for it)
        self.GetProcessTimes = fn(kernel32, "GetProcessTimes", BOOL, HANDLE, ctypes.POINTER(wintypes.FILETIME),
                                  ctypes.POINTER(wintypes.FILETIME), ctypes.POINTER(wintypes.FILETIME),
                                  ctypes.POINTER(wintypes.FILETIME), optional=True)
        try:
            ntdll = ctypes.WinDLL("ntdll")
            self.NtSuspendProcess = fn(ntdll, "NtSuspendProcess", ctypes.c_long, HANDLE, optional=True)
            self.NtResumeProcess = fn(ntdll, "NtResumeProcess", ctypes.c_long, HANDLE, optional=True)
        except OSError:
            self.NtSuspendProcess = self.NtResumeProcess = None


_api: _Api | None = None


def api() -> _Api:
    global _api
    if _api is None:
        _api = _Api()
    return _api


INVALID_HANDLE = ctypes.c_void_p(-1).value


class Watch:
    """A running program, held by a handle of its own so that a number Windows gives again to another
    program is never mistaken for it."""

    def __init__(self, pid: int, handle):
        self.pid = pid
        self.handle = handle

    def alive(self) -> bool:
        if not self.handle:
            return False
        a = api()
        return a.WaitForSingleObject(self.handle, 0) == WAIT_TIMEOUT

    def close(self) -> None:
        if self.handle:
            api().CloseHandle(self.handle)
            self.handle = None


def _started(handle) -> int:
    """When a program started (Windows' own count of 100 ns), 0 where that cannot be read."""
    a = api()
    if a.GetProcessTimes is None:
        return 0
    times = [wintypes.FILETIME() for _ in range(4)]
    if not a.GetProcessTimes(handle, *(ctypes.byref(t) for t in times)):
        return 0
    return (times[0].dwHighDateTime << 32) | times[0].dwLowDateTime


class Paused:
    """A program Sluka has paused, held by a handle of its own: let go of by it, whatever number Windows gives which
    program meanwhile.  ``started``: when it started, for a pause left behind by an app that ended without letting go."""

    def __init__(self, pid: int, handle, started: int):
        self.pid = pid
        self.handle = handle
        self.started = started

    def resume(self) -> bool:
        """The program let go of (its threads run again): True where Windows said so."""
        if not self.handle:
            return False
        a = api()
        try:
            return a.NtResumeProcess is not None and a.NtResumeProcess(self.handle) == 0
        finally:
            a.CloseHandle(self.handle)
            self.handle = None


class Procs:
    """What the game text menu asks of Windows about running programs."""

    def __init__(self):
        self.own_pid = os.getpid()
        self._job = None

    # ---------------------------------------------------------------- one program

    def exe(self, pid: int) -> str:
        """The full path of the program file ``pid`` runs, or '' where it cannot be read."""
        if not WINDOWS or not pid:
            return ""
        a = api()
        handle = a.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not handle:
            return ""
        try:
            size = wintypes.DWORD(32768)
            buffer = ctypes.create_unicode_buffer(size.value)
            if a.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(size)):
                return buffer.value
            return ""
        finally:
            a.CloseHandle(handle)

    def bits(self, pid: int) -> int:
        """32 or 64: the kind of program ``pid`` is (0 where that cannot be told)."""
        if not WINDOWS or not pid:
            return 0
        a = api()
        handle = a.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not handle:
            return 0
        try:
            if a.IsWow64Process2 is not None:
                machine, native = wintypes.USHORT(0), wintypes.USHORT(0)
                if a.IsWow64Process2(handle, ctypes.byref(machine), ctypes.byref(native)):
                    if machine.value == IMAGE_FILE_MACHINE_I386:
                        return 32
                    if machine.value == 0:
                        # Not under WOW64: the computer's own kind (an x64 program on ARM is not WOW64 either).
                        return 64 if native.value in (IMAGE_FILE_MACHINE_AMD64, IMAGE_FILE_MACHINE_ARM64) else 32
            wow = wintypes.BOOL(0)
            if a.IsWow64Process(handle, ctypes.byref(wow)):
                if wow.value:
                    return 32
                return 64 if ctypes.sizeof(ctypes.c_void_p) == 8 or os.environ.get("PROCESSOR_ARCHITEW6432") else 32
            return 0
        finally:
            a.CloseHandle(handle)

    def can_reach(self, pid: int) -> tuple[bool, str]:
        """Whether a hook may be put into ``pid`` from here, and why not."""
        if not WINDOWS:
            return False, "not Windows"
        a = api()
        handle = a.OpenProcess(INJECT_RIGHTS, False, pid)
        if handle:
            a.CloseHandle(handle)
            return True, ""
        error = ctypes.get_last_error()
        if error == ERROR_ACCESS_DENIED:
            return False, "admin"
        return False, f"error {error}"

    def pause(self, pid: int) -> tuple[Paused | None, str]:
        """Every thread of ``pid`` held where it is (Sluka Vision's "Pause the game"), and the program to let go of
        again; or None and why not: "admin" (run as administrator, or protected -- an anti-cheat's), else Windows' own."""
        if not WINDOWS or not pid:
            return None, "not Windows"
        a = api()
        if a.NtSuspendProcess is None or a.NtResumeProcess is None:
            return None, "Windows here cannot pause a program"
        handle = a.OpenProcess(PAUSE_RIGHTS, False, pid)
        if not handle:
            error = ctypes.get_last_error()
            return None, "admin" if error == ERROR_ACCESS_DENIED else f"error {error}"
        status = a.NtSuspendProcess(handle)
        if status != 0:
            a.CloseHandle(handle)
            return None, "admin" if status & 0xFFFFFFFF == 0xC0000022 else f"status 0x{status & 0xFFFFFFFF:08X}"
        return Paused(pid, handle, _started(handle)), ""

    def resume_left(self, pid: int, started: int) -> bool:
        """A program paused by an app that ended without letting it go (``started``: when it started, so that another
        program given the same number is never touched): let go of now."""
        if not WINDOWS or not pid or not started:
            return False
        a = api()
        if a.NtResumeProcess is None:
            return False
        handle = a.OpenProcess(PAUSE_RIGHTS, False, pid)
        if not handle:
            return False
        try:
            return _started(handle) == started and a.NtResumeProcess(handle) == 0
        finally:
            a.CloseHandle(handle)

    def watch(self, pid: int) -> Watch | None:
        if not WINDOWS or not pid:
            return None
        handle = api().OpenProcess(SYNCHRONIZE | PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        return Watch(pid, handle) if handle else None

    def is_admin(self) -> bool:
        if not WINDOWS:
            return False
        try:
            a = api()
            return bool(a.IsUserAnAdmin and a.IsUserAnAdmin())
        except Exception:
            return False

    # ---------------------------------------------------------------- all of them

    def processes(self) -> list[dict]:
        """Every program running: [{pid, parent, name}] (the file's name only, which needs no rights)."""
        if not WINDOWS:
            return []
        a = api()
        snap = a.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
        if not snap or snap == INVALID_HANDLE:
            return []
        out = []
        try:
            entry = PROCESSENTRY32W()
            entry.dwSize = ctypes.sizeof(PROCESSENTRY32W)
            ok = a.Process32FirstW(snap, ctypes.byref(entry))
            while ok:
                out.append({"pid": int(entry.th32ProcessID), "parent": int(entry.th32ParentProcessID), "name": entry.szExeFile})
                ok = a.Process32NextW(snap, ctypes.byref(entry))
        finally:
            a.CloseHandle(snap)
        return out

    def windows(self) -> list[dict]:
        """The windows a person can see and switch to, front first: [{pid, hwnd, title}], one per program."""
        if not WINDOWS:
            return []
        a = api()
        found: list[dict] = []
        seen: set[int] = set()

        def each(hwnd, _lparam):
            try:
                if not a.IsWindowVisible(hwnd) or a.GetWindow(hwnd, GW_OWNER):
                    return True
                style = a.GetWindowLongPtrW(hwnd, GWL_EXSTYLE) or 0
                if style & WS_EX_TOOLWINDOW:
                    return True
                if a.DwmGetWindowAttribute is not None:
                    cloaked = wintypes.DWORD(0)
                    if a.DwmGetWindowAttribute(hwnd, DWMWA_CLOAKED, ctypes.byref(cloaked), ctypes.sizeof(cloaked)) == 0 and cloaked.value:
                        return True
                length = a.GetWindowTextLengthW(hwnd)
                if length <= 0:
                    return True
                buffer = ctypes.create_unicode_buffer(length + 1)
                a.GetWindowTextW(hwnd, buffer, length + 1)
                pid = wintypes.DWORD(0)
                a.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
                if pid.value and pid.value not in seen:
                    seen.add(pid.value)
                    found.append({"pid": int(pid.value), "hwnd": int(hwnd or 0), "title": buffer.value})
            except Exception:
                log.exception("a window could not be looked at")
            return True

        callback = a.WNDENUMPROC(each)
        a.EnumWindows(callback, 0)
        return found

    def foreground_pid(self) -> int:
        """The program whose window is in front (0 where there is none)."""
        if not WINDOWS:
            return 0
        a = api()
        hwnd = a.GetForegroundWindow()
        if not hwnd:
            return 0
        pid = wintypes.DWORD(0)
        a.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        return int(pid.value)

    def pids_of(self, path: str) -> list[int]:
        """Every running program from the same file (a game that draws in programs of its own, as NW.js and CEF
        games do, has more than one)."""
        if not path:
            return []
        base = os.path.basename(path.replace("\\", "/")).lower()
        wanted = os.path.normcase(path)
        found = []
        for p in self.processes():
            if str(p.get("name") or "").lower() != base:
                continue
            full = self.exe(p["pid"])
            if full and os.path.normcase(full) == wanted:
                found.append(p["pid"])
        return found

    def is_running(self, pid: int) -> bool:
        """Whether ``pid`` is still running (for a program that cannot be held, as one run as administrator)."""
        return any(p["pid"] == pid for p in self.processes())

    def title_of(self, pid: int) -> str:
        for window in self.windows():
            if window["pid"] == pid:
                return window["title"]
        return ""

    # ---------------------------------------------------------------- this app's own windows (the screen reader)

    #: The app's main windows, and the floating subtitles' (winshell.py).
    OWN_CLASSES = ("SlukaDesktopWindow", "SlukaDesktopBar")

    def own_windows(self, classes=OWN_CLASSES, visible: bool = True) -> list[dict]:
        """This app's own windows (those that show, or all of them): [{hwnd, class, visible, minimized}]."""
        if not WINDOWS:
            return []
        a = api()
        if a.GetClassNameW is None:
            return []
        found: list[dict] = []

        def each(hwnd, _lparam):
            try:
                pid = wintypes.DWORD(0)
                a.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
                if pid.value != self.own_pid:
                    return True
                shows = bool(a.IsWindowVisible(hwnd))
                if visible and not shows:
                    return True
                name = ctypes.create_unicode_buffer(256)
                a.GetClassNameW(hwnd, name, 256)
                if classes and name.value not in classes:
                    return True
                found.append({"hwnd": int(hwnd or 0), "class": name.value, "visible": shows,
                              "minimized": bool(a.IsIconic(hwnd)) if a.IsIconic else False})
            except Exception:
                log.exception("a window could not be looked at")
            return True

        callback = a.WNDENUMPROC(each)
        a.EnumWindows(callback, 0)
        return found

    def windows_of(self, pids) -> list[dict]:
        """The windows of these programs that show, as one is read off the screen: [{hwnd, pid, title, class,
        minimized}], front first (a game's own; not tool windows, nor ones Windows keeps hidden)."""
        if not WINDOWS:
            return []
        a = api()
        wanted = {int(p) for p in pids}
        found: list[dict] = []

        def each(hwnd, _lparam):
            try:
                pid = wintypes.DWORD(0)
                a.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
                if pid.value not in wanted or not a.IsWindowVisible(hwnd):
                    return True
                style = a.GetWindowLongPtrW(hwnd, GWL_EXSTYLE) or 0
                if style & WS_EX_TOOLWINDOW:
                    return True
                if a.DwmGetWindowAttribute is not None:
                    cloaked = wintypes.DWORD(0)
                    if a.DwmGetWindowAttribute(hwnd, DWMWA_CLOAKED, ctypes.byref(cloaked), ctypes.sizeof(cloaked)) == 0 and cloaked.value:
                        return True
                length = max(0, a.GetWindowTextLengthW(hwnd))
                title = ctypes.create_unicode_buffer(length + 1)
                a.GetWindowTextW(hwnd, title, length + 1)
                name = ctypes.create_unicode_buffer(256)
                if a.GetClassNameW is not None:
                    a.GetClassNameW(hwnd, name, 256)
                found.append({"hwnd": int(hwnd or 0), "pid": int(pid.value), "title": title.value, "class": name.value,
                              "minimized": bool(a.IsIconic(hwnd)) if a.IsIconic else False})
            except Exception:
                log.exception("a window could not be looked at")
            return True

        callback = a.WNDENUMPROC(each)
        a.EnumWindows(callback, 0)
        return found

    def keep_out_of_captures(self, hwnds, on: bool) -> int:
        """This app's windows left out of pictures of the screen (they still show on it: Windows 10 2004 and later),
        so that the screen reader never reads the floating subtitles' own line -- or put back."""
        if not WINDOWS:
            return 0
        a = api()
        if a.SetWindowDisplayAffinity is None:
            return 0
        done = 0
        for hwnd in hwnds:
            if a.SetWindowDisplayAffinity(hwnd, 0x11 if on else 0):  # WDA_EXCLUDEFROMCAPTURE, WDA_NONE
                done += 1
        return done

    def show_window(self, hwnd, how: str) -> bool:
        """One of this app's windows out of the way, or back (without waiting on it): "minimize", "restore", "hide",
        "show" (shown again without taking the keyboard, as the floating subtitles are)."""
        if not WINDOWS:
            return False
        a = api()
        if a.ShowWindowAsync is None:
            return False
        command = {"minimize": 6, "restore": 9, "hide": 0, "show": 4}.get(how, 9)  # SW_MINIMIZE, SW_RESTORE, ...
        return bool(a.ShowWindowAsync(hwnd, command))

    # ---------------------------------------------------------------- the hooker goes when the app goes

    def bind(self, process_handle) -> bool:
        """Have a program end with this app, however this app ends (a job that kills what is in it as it closes)."""
        if not WINDOWS or not process_handle:
            return False
        a = api()
        try:
            if self._job is None:
                job = a.CreateJobObjectW(None, None)
                if not job:
                    return False
                info = JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
                info.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE | JOB_OBJECT_LIMIT_BREAKAWAY_OK
                if not a.SetInformationJobObject(job, JOB_OBJECT_EXTENDED_LIMIT_INFORMATION_CLASS, ctypes.byref(info),
                                                 ctypes.sizeof(info)):
                    a.CloseHandle(job)
                    return False
                self._job = job
            return bool(a.AssignProcessToJobObject(self._job, wintypes.HANDLE(int(process_handle))))
        except Exception:
            log.exception("the hooker could not be tied to the app")
            return False


def candidates(procs, own_pid: int | None = None) -> list[dict]:
    """The programs a game could be, for the menu: those with a window, front first, with their files and kinds.

    Sluka's own windows, its web view's helpers and Windows' own programs are left out.
    """
    own = own_pid if own_pid is not None else getattr(procs, "own_pid", os.getpid())
    all_procs = {p["pid"]: p for p in procs.processes()}
    # The app's own helpers: the web view's programs are children (and grandchildren) of the app.
    mine = {own}
    changed = True
    while changed:
        changed = False
        for pid, p in all_procs.items():
            if pid not in mine and p.get("parent") in mine:
                mine.add(pid)
                changed = True
    out = []
    for window in procs.windows():
        pid = window["pid"]
        if pid in mine:
            continue
        name = (all_procs.get(pid, {}).get("name") or "").strip()
        path = procs.exe(pid)
        base = os.path.basename(path.replace("\\", "/")) if path else name
        if not base or base.lower() in NOT_GAMES:
            continue
        out.append({
            "pid": pid,
            "title": window.get("title") or base,
            "exe": base,
            "path": path,
            "bits": procs.bits(pid),
        })
    return out
