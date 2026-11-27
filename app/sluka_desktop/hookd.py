# SPDX-License-Identifier: GPL-3.0-only
# Copyright (c) 2026 Sluka.  Part of Sluka Desktop.
#
# This program is free software: you can redistribute it and/or modify it under the terms of the GNU General Public
# License as published by the Free Software Foundation, version 3 of the License.
#
# This program is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY; without even the implied
# warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License along with this program (LICENSES\GPL-3.0.txt, in
# Sluka Desktop's folder).  If not, see <https://www.gnu.org/licenses/>.
#
# It drives LunaHook, LunaTranslator's text hooker (Copyright (C) 2026 HIllya51 and LunaTranslator's contributors, GNU
# GPL version 3: engine\LICENSES\LICENSE.LunaTranslator), declaring its functions as LunaTranslator's own
# src/LunaTranslator/textio/textsource/texthook.py declares them; hence version 3 of the licence, as LunaTranslator's.
"""Sluka's game text engine: LunaHook, the text hooker inside LunaTranslator, in a program of its own.

    python hookd.py ENGINE_FOLDER [--log FILE]

The app (texthook.EngineProcess) starts this as a program apart from itself,
so that whatever happens inside the hooker leaves the app standing, and it is
started again.  It loads LunaHost64.dll from the engine folder -- the
"host" half of LunaHook, as LunaTranslator 12.1.3.12 ships it -- and drives
it exactly as LunaTranslator's own textio/textsource/texthook.py does: the
same functions, declared the same way, called in the same order.  The other
half, LunaHook32.dll or LunaHook64.dll, is put into the game by
LunaSubprocess32.exe or LunaSubprocess64.exe ("dllinject"), as LunaTranslator
puts it there; it finds the game's engine, catches its text, and sends it to
the host, one "text thread" per place the text comes through.

It speaks with the app in lines of JSON (UTF-8), one object a line:

  in   {"cmd": "attach", "pids": [1234], "bits": 32, "elevate": false}
       {"cmd": "detach", "pid": 1234}
       {"cmd": "hookcode", "pid": 1234, "code": "HS-4@1234:game.exe"}
       {"cmd": "pchooks", "pid": 1234}
       {"cmd": "settings", "flush": 300, "codepage": 932}
       {"cmd": "sync", "id": 7, "on": true}
       {"cmd": "quit"}
  out  {"ev": "ready", ...}          the host is running
       {"ev": "fatal", "text": ...}  it could not be (and this program ends)
       {"ev": "inject", "pid", "ok", "how", "error"}
       {"ev": "connect", "pid"} / {"ev": "disconnect", "pid"}
       {"ev": "thread", "id", "pid", "addr", "ctx", "ctx2", "name", "code", "embed"}
       {"ev": "gone", "id"}
       {"ev": "text", "id", "text"}
       {"ev": "info", "type", "text"}  0 console, 1 warning, 2 emulator warning,
                                       3 emulator found, 4 the game's engine
       {"ev": "hook", "pid", "addr", "code"}
       {"ev": "emu", "id", "title", "version"}

This file stands alone (nothing of the app is imported), so that it runs as
a plain script under the app's own Python.
"""

from __future__ import annotations

import ctypes
import json
import os
import re
import struct
import subprocess
import sys
import threading
import time
import traceback
from ctypes import CFUNCTYPE, Structure, c_bool, c_char_p, c_float, c_int, c_uint8, c_uint32, c_uint64, c_void_p, c_wchar_p

PROTOCOL = 1
WINDOWS = sys.platform == "win32"
CREATE_NO_WINDOW = 0x08000000

#: What LunaTranslator 12.1.3.12 sets (texthook.py setsettings): how long a thread is to be quiet before its text
#: is sent as one line, the most kept per text before it is sent, and of the history the host keeps.
FLUSH_MS = 500
MAX_BUFFER = 3000
MAX_HISTORY = 1_000_000
#: And what it sets for each game as it connects (set_settings_ex), translations written into the game being off:
#: how long a game waits for one (ms), the font's character set (2: the system's) and whether it is changed, the
#: font (none), how a translation is shown (0), whether the game's fast-forward key skips that wait, whether the
#: game's own text is cleared, whether the font's size changes and by how much, whether a hook that cannot be
#: written into the game's code is made a breakpoint instead (VEH), and Unity's fonts (none).
SETTINGS_EX = (2000, 2, False, "", 0, True, False, False, 1.0, True, "")

DWORD = c_uint32  # (DWORD is 32 bits on Windows; ctypes.wintypes' is a C long, which is not elsewhere)


class ThreadParam(Structure):
    """Which text thread: LunaHook's include/types.h, and LunaTranslator's texthook.py."""

    _fields_ = [
        ("processId", c_uint32),
        ("addr", c_uint64),
        ("ctx", c_uint64),
        ("ctx2", c_uint64),
    ]

    def key(self) -> tuple:
        return (int(self.processId), int(self.addr), int(self.ctx), int(self.ctx2))


# The host's callbacks, as LunaHost/LunaHostDll.cpp has them (and texthook.py declares them).
ProcessEvent = CFUNCTYPE(None, DWORD)
ThreadEventMaybeEmbed = CFUNCTYPE(None, c_wchar_p, c_char_p, ThreadParam, c_bool)
ThreadEvent = CFUNCTYPE(None, c_wchar_p, c_char_p, ThreadParam)
OutputCallback = CFUNCTYPE(None, c_wchar_p, c_char_p, ThreadParam, c_wchar_p)
HostInfoHandler = CFUNCTYPE(None, c_int, c_wchar_p)
HookInsertHandler = CFUNCTYPE(None, DWORD, c_uint64, c_wchar_p)
EmbedCallback = CFUNCTYPE(None, c_wchar_p, ThreadParam)
I18NQueryCallback = CFUNCTYPE(c_void_p, c_wchar_p)
EmuGameInfoCallback = CFUNCTYPE(None, c_wchar_p, c_wchar_p, c_wchar_p)

#: LunaHook's own messages (include/InfoStrings.cpp) are in Chinese; the host asks for each in the language
#: wanted, as LunaTranslator answers in its own.  The hook in the game formats some of them with printf, so a
#: translation keeps the original's % placeholders, in the same order (a test sees to it).
ENGLISH = {
    # the host's
    "警告": "Warning",
    "已经注入": "Already hooked",
    "注入失败": "Could not hook it",
    "无法转换文本 (无效的代码页?)": "Could not read the text (another code page?)",
    "进程 %d 已连接": "Process %d connected",
    "进程 %d 已断开连接": "Process %d disconnected",
    "文件版本无法匹配，可能无法正常工作，请重新下载！": "The hook in the game is another version than the host: it may not work. Reinstall Sluka Desktop.",
    # the hook's, in the game
    "注入钩子: %s %p": "Inserting hook: %s %p",
    "移除钩子: %s": "Removing hook: %s",
    "钩子数量已达上限: 无法注入": "Too many hooks: no more can be inserted",
    "开始搜索钩子": "Searching for hooks",
    "初始化钩子搜索 (%f%%)": "Preparing the hook search (%f%%)",
    "文本长度不足, 无法精确搜索": "The text is too short to search for",
    "搜索初始化完成, 创建了 %zd 个钩子": "Hook search ready: %zd hooks made",
    "请点击游戏区域, 在接下来的 %d 秒内使游戏强制处理文本": "Click in the game so that it shows text within the next %d seconds",
    "钩子搜索完毕, 找到了 %d 条结果": "Hook search done: %d results",
    "搜索结果已达上限, 如果结果不理想, 请重试(默认最大记录数增加)": "Too many results; if they are no good, search again (with more records)",
    "函数不存在": "No such function",
    "模块不存在": "No such module",
    "内存一直在改变，无法有效读取": "The memory keeps changing: it cannot be read",
    "Sender 错误 (可能是由于错误或不稳定的 H-code) ： %s": "Sender error (a wrong or unsteady H-code?): %s",
    "Reader 错误 (可能是由于错误或不稳定的 R-code) ： %s": "Reader error (a wrong or unsteady R-code?): %s",
    "搜索钩子错误 : 内存溢出，尝试重新分配 %d": "Hook search error: out of memory, trying again with %d",
    "%d 个结果被找到": "%d results found",
    "无法找到文本": "The text was not found",
    "可能存在错误 (无效的文本长度 %d 出现在 %s)": "Possible error (a text length of %d at %s)",
    "钩子注入失败 %s": "Could not insert the hook %s",
    "匹配 %s 引擎时发生错误": "Error while matching the %s engine",
    "连接到 %s 引擎时发生错误": "Error while attaching to the %s engine",
    "匹配到 %s 引擎": "Found the %s engine",
    "确认是 %s 引擎": "It is the %s engine",
    "成功连接到 %s 引擎": "Attached to the %s engine",
    "获取到进程内存地址范围 0x%p 到 0x%p": "The program's memory: 0x%p to 0x%p",
    "警告，注入的进程内存很小，可能是无用进程!": "Warning: this program is very small; it may not be the game itself!",
    "不支持ryujinx，请使用yuzu/sudachi/Citron/Eden": "Ryujinx is not supported: use yuzu, Sudachi, Citron or Eden",
    "不支持当前模拟器版本": "This version of the emulator is not supported",
    "特殊码无效": "That hook code is not valid",
}

PLACEHOLDER = re.compile(r"%(?:%|[-+ #0]*\d*(?:\.\d+)?(?:hh|h|ll|l|z|j|t|I64|I32|L)?[diouxXeEfgGcspn])")


def placeholders(text: str) -> list[str]:
    """The printf placeholders of a message, in order (%% included)."""
    return PLACEHOLDER.findall(text)


class Hookd:
    """The host, loaded and started, and what it says turned into lines for the app."""

    def __init__(self, folder: str, write, log=None, library: str = "", injector: list | None = None):
        self.folder = os.path.abspath(folder)
        self.write = write
        self.log = log or (lambda text: None)
        self._out = threading.Lock()
        self._ids: dict[tuple, int] = {}
        self._tps: dict[int, ThreadParam] = {}
        self._next = 1
        self._ids_lock = threading.Lock()
        self.connected: set[int] = set()
        self.injector = injector
        self.library = library or os.path.join(self.folder, "LunaHost64.dll")
        self.dll = self._load()
        self._bind()
        self._keep = [
            ProcessEvent(self._on_connect),
            ProcessEvent(self._on_disconnect),
            ThreadEventMaybeEmbed(self._on_create),
            ThreadEvent(self._on_destroy),
            OutputCallback(self._on_output),
            HostInfoHandler(self._on_info),
            HookInsertHandler(self._on_hook),
            EmbedCallback(self._on_embed),
            I18NQueryCallback(self._on_i18n),
            EmuGameInfoCallback(self._on_emu),
        ]
        self.dll.Luna_Start(*self._keep)
        # The host's own messages, and the hook's in each game, in English from now on.
        self.dll.Luna_ResetLang()
        self.settings(FLUSH_MS, 932)

    # ---------------------------------------------------------------- the library

    def _load(self):
        if WINDOWS:
            if struct.calcsize("P") != 8:
                raise OSError("Sluka's engine (LunaHost64.dll) needs a 64-bit Python, and this one is 32-bit")
            # What LunaHost64.dll needs that Python has not loaded already (msvcp140.dll, the C++ runtime) is looked
            # for in the engine folder, where it comes with the app: a library loaded by its full path has its own
            # folder searched first for what it needs, and the folder is added for good measure.
            try:
                os.add_dll_directory(self.folder)
            except (AttributeError, OSError):
                pass
        return ctypes.CDLL(self.library)

    def _bind(self) -> None:
        """Every function as LunaTranslator 12.1.3.12 declares it (texthook.py initdll), checked against
        LunaHost/LunaHostDll.cpp."""
        d = self.dll

        def fn(name, argtypes, restype=None):
            f = getattr(d, name)
            f.argtypes = argtypes
            f.restype = restype
            return f

        fn("Luna_Start", (ProcessEvent, ProcessEvent, ThreadEventMaybeEmbed, ThreadEvent, OutputCallback, HostInfoHandler,
                          HookInsertHandler, EmbedCallback, I18NQueryCallback, EmuGameInfoCallback))
        fn("Luna_ResetLang", ())
        fn("Luna_Settings", (c_int, c_int, c_int, c_int, c_bool))
        fn("Luna_ConnectProcess", (DWORD,))
        fn("Luna_CheckIfNeedInject", (DWORD,), c_bool)
        fn("Luna_DetachProcess", (DWORD,))
        fn("Luna_InsertHookCode", (DWORD, c_wchar_p))
        fn("Luna_InsertPCHooks", (DWORD, c_int))
        fn("Luna_RemoveHook", (DWORD, c_uint64))
        fn("Luna_SyncThread", (ThreadParam, c_bool))
        fn("Luna_AllocString", (c_wchar_p,), c_void_p)
        fn("Luna_SettingsEx", (DWORD, c_uint32, c_uint8, c_bool, c_wchar_p, c_uint32, c_bool, c_bool, c_bool, c_float, c_bool,
                               c_wchar_p))

    # ---------------------------------------------------------------- to the app

    def emit(self, event: dict) -> None:
        line = json.dumps(event, ensure_ascii=False, separators=(",", ":")) + "\n"
        with self._out:
            try:
                self.write(line.encode("utf-8", "replace"))
            except (OSError, ValueError):
                pass

    def _id(self, tp: ThreadParam, create: bool = True) -> tuple[int, bool]:
        key = tp.key()
        with self._ids_lock:
            known = self._ids.get(key)
            if known is not None or not create:
                return (known or 0), False
            ident = self._next
            self._next += 1
            self._ids[key] = ident
            copy = ThreadParam()
            copy.processId, copy.addr, copy.ctx, copy.ctx2 = key
            self._tps[ident] = copy
            return ident, True

    @staticmethod
    def _name(raw) -> str:
        if not raw:
            return ""
        try:
            return raw.decode("utf-8")
        except UnicodeDecodeError:
            return raw.decode("mbcs" if WINDOWS else "latin-1", "replace")

    # ---------------------------------------------------------------- the host's callbacks (its threads)

    def _guard(func):  # noqa: N805
        def run(self, *args):
            try:
                return func(self, *args)
            except Exception:
                self.log("a callback failed:\n" + traceback.format_exc())
                return None
        return run

    @_guard
    def _on_connect(self, pid):
        self.connected.add(int(pid))
        self.log(f"connected: {pid}")
        self.emit({"ev": "connect", "pid": int(pid)})
        # As LunaTranslator does, from a thread of its own (this one is the host's, which waits for it).
        threading.Thread(target=self._settings_ex, args=(int(pid),), name=f"settings-{pid}", daemon=True).start()

    def _settings_ex(self, pid: int) -> None:
        try:
            self.dll.Luna_SettingsEx(pid, *SETTINGS_EX)
        except Exception:
            self.log("the game's settings could not be set:\n" + traceback.format_exc())

    @_guard
    def _on_disconnect(self, pid):
        self.connected.discard(int(pid))
        self.log(f"disconnected: {pid}")
        self.emit({"ev": "disconnect", "pid": int(pid)})

    def _thread_event(self, ident: int, code, name, tp: ThreadParam, embed: bool) -> dict:
        return {"ev": "thread", "id": ident, "pid": int(tp.processId), "addr": int(tp.addr), "ctx": int(tp.ctx),
                "ctx2": int(tp.ctx2), "name": self._name(name), "code": code or "", "embed": bool(embed)}

    @_guard
    def _on_create(self, code, name, tp, embed):
        ident, _new = self._id(tp)
        event = self._thread_event(ident, code, name, tp, embed)
        self.log(f"thread {ident}: {event['name']} {event['code']}")
        self.emit(event)

    @_guard
    def _on_destroy(self, code, name, tp):
        key = tp.key()
        with self._ids_lock:
            ident = self._ids.pop(key, None)
            if ident is not None:
                self._tps.pop(ident, None)
        if ident is not None:
            self.emit({"ev": "gone", "id": ident})

    @_guard
    def _on_output(self, code, name, tp, text):
        ident, new = self._id(tp)
        if new:  # (the host says "created" first; should it not, the app hears of the thread all the same)
            self.emit(self._thread_event(ident, code, name, tp, False))
        self.emit({"ev": "text", "id": ident, "text": text or ""})

    @_guard
    def _on_info(self, kind, text):
        self.log(f"info {kind}: {text}")
        self.emit({"ev": "info", "type": int(kind), "text": text or ""})

    @_guard
    def _on_hook(self, pid, addr, code):
        self.emit({"ev": "hook", "pid": int(pid), "addr": int(addr), "code": code or ""})

    @_guard
    def _on_embed(self, text, tp):
        # Translations written back into the game are LunaTranslator's; Sluka only reads.
        return None

    @_guard
    def _on_i18n(self, text):
        english = ENGLISH.get(text or "")
        if not english:
            return None
        # The host frees what it is given: it has to come from its own heap (Luna_AllocString).
        return self.dll.Luna_AllocString(english)

    @_guard
    def _on_emu(self, ident, title, version):
        self.emit({"ev": "emu", "id": ident or "", "title": title or "", "version": version or ""})

    # ---------------------------------------------------------------- the app's commands

    def settings(self, flush: int, codepage: int) -> None:
        flush = max(0, min(10000, int(flush)))
        codepage = max(0, min(65535, int(codepage)))
        # Windows' own text functions are hooked only when asked for, game by game ("pchooks"), as LunaTranslator does.
        self.dll.Luna_Settings(flush, codepage, MAX_BUFFER, MAX_HISTORY, False)
        self.log(f"settings: flush {flush} ms, code page {codepage}")

    def attach(self, pids, bits: int, elevate: bool = False) -> None:
        """As LunaTranslator's start_unsafe: the host made ready for the hook of each of the game's programs
        (Luna_ConnectProcess), and the hook put, in one go, into those it is not in yet -- in a thread of its own,
        as it takes a moment, and may wait for the person to say yes to Windows."""
        need = []
        for pid in [int(p) for p in (pids if isinstance(pids, (list, tuple)) else [pids])]:
            self.dll.Luna_ConnectProcess(pid)
            if self.dll.Luna_CheckIfNeedInject(pid):
                need.append(pid)
            else:
                self.log(f"{pid}: its hook is there already; it connects to this host")
                self._injected([pid], True, "already")
        if need:
            threading.Thread(target=self._inject, args=(need, bits, elevate), name="inject", daemon=True).start()

    def _injected(self, pids: list[int], ok: bool, how: str, error: str = "") -> None:
        for pid in pids:
            event = {"ev": "inject", "pid": pid, "ok": ok, "how": how}
            if error:
                event["error"] = error
            self.emit(event)

    def _inject_command(self, bits: int) -> tuple[list[str], str]:
        bits = 64 if int(bits) == 64 else 32
        dll = os.path.join(self.folder, f"LunaHook{bits}.dll")
        if self.injector:
            return list(self.injector) + ["dllinject"], dll
        return [os.path.join(self.folder, f"LunaSubprocess{bits}.exe"), "dllinject"], dll

    def _inject(self, pids: list[int], bits: int, elevate: bool) -> None:
        """LunaSubprocess{32|64}.exe dllinject PID... DLL, as LunaTranslator runs it (LunaSubProcess.py)."""
        command, dll = self._inject_command(bits)
        if not os.path.isfile(dll):
            self._injected(pids, False, "missing", f"{os.path.basename(dll)} is missing")
            return
        if elevate and WINDOWS and not self.injector:
            self._inject_elevated(pids, command, dll)
            return
        started = time.monotonic()
        try:
            done = subprocess.run(command + [str(pid) for pid in pids] + [dll], creationflags=CREATE_NO_WINDOW if WINDOWS else 0,
                                  stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                  timeout=30 + 15 * len(pids))
            code = done.returncode
        except FileNotFoundError:
            self._injected(pids, False, "missing", f"{os.path.basename(command[0])} is missing (taken away by an antivirus?)")
            return
        except OSError as err:
            # 225: "the file contains a virus" -- Windows Security will not run it.
            self._injected(pids, False, "blocked" if getattr(err, "winerror", 0) == 225 else "error", str(err))
            return
        except subprocess.TimeoutExpired:
            self._injected(pids, False, "timeout", "the injector did not finish")
            return
        self.log(f"{' '.join(map(str, pids))}: injector ({bits}-bit) gave {code} in {time.monotonic() - started:.1f} s")
        # dllinject answers 1 when it put the library in (every program), 0 when it could not open one.
        if code == 1:
            self._injected(pids, True, "injected")
        elif code == 0:
            self._injected(pids, False, "denied", "the game could not be opened (it may run as administrator)")
        else:
            self._injected(pids, False, "crashed", f"the injector ended with {code & 0xFFFFFFFF:#x}")

    def _inject_elevated(self, pids: list[int], command: list[str], dll: str) -> None:
        """The injector run as administrator (Windows asks the person first), for a game run as administrator: the
        hook it puts in can still connect to this host, which is not (LunaTranslator's dllinject_elevated)."""
        params = subprocess.list2cmdline(command[1:] + [str(pid) for pid in pids] + [dll])
        shell32 = ctypes.WinDLL("shell32")
        shell32.ShellExecuteW.argtypes = (c_void_p, c_wchar_p, c_wchar_p, c_wchar_p, c_wchar_p, c_int)
        shell32.ShellExecuteW.restype = c_void_p
        result = shell32.ShellExecuteW(None, "runas", command[0], params, None, 0) or 0
        if result > 32:
            self.log(f"{' '.join(map(str, pids))}: the injector was started as administrator")
            self._injected(pids, True, "elevated")
        else:
            # 5: access denied, or the person said no.
            self._injected(pids, False, "refused", "Windows did not run the injector as administrator"
                           + (" (cancelled)" if result in (5, 1223) else f" ({result})"))

    def detach(self, pid: int) -> None:
        self.dll.Luna_DetachProcess(int(pid))

    def hookcode(self, pid: int, code: str) -> None:
        self.dll.Luna_InsertHookCode(int(pid), str(code))

    def pchooks(self, pid: int) -> None:
        self.dll.Luna_InsertPCHooks(int(pid), 0)
        self.dll.Luna_InsertPCHooks(int(pid), 1)

    def sync(self, ident: int, on: bool) -> None:
        """A picked thread's text is waited for together with the other picked ones' (LunaTranslator does this for
        each thread it shows)."""
        with self._ids_lock:
            tp = self._tps.get(int(ident))
        if tp is not None:
            self.dll.Luna_SyncThread(tp, bool(on))

    def remove(self, pid: int, addr: int) -> None:
        self.dll.Luna_RemoveHook(int(pid), int(addr))

    def quit(self) -> None:
        for pid in list(self.connected):
            try:
                self.dll.Luna_DetachProcess(pid)
            except Exception:
                pass
        # The host sends "detach" from threads of its own: a moment for it to go out.
        time.sleep(0.3 if self.connected else 0)

    def run(self, lines) -> None:
        """The app's commands, one a line, until it says quit or goes away."""
        for raw in lines:
            try:
                command = json.loads(raw.decode("utf-8") if isinstance(raw, bytes) else raw)
            except ValueError:
                continue
            if not isinstance(command, dict):
                continue
            what = command.get("cmd")
            self.log(f"command: {json.dumps(command, ensure_ascii=False)[:300]}")
            try:
                if what == "attach":
                    self.attach(command.get("pids") or [command["pid"]], command.get("bits", 32), bool(command.get("elevate")))
                elif what == "detach":
                    self.detach(command["pid"])
                elif what == "hookcode":
                    self.hookcode(command["pid"], command["code"])
                elif what == "pchooks":
                    self.pchooks(command["pid"])
                elif what == "settings":
                    self.settings(command.get("flush", FLUSH_MS), command.get("codepage", 932))
                elif what == "sync":
                    self.sync(command["id"], command.get("on", True))
                elif what == "remove":
                    self.remove(command["pid"], command["addr"])
                elif what == "quit":
                    break
            except Exception as err:
                self.log("a command failed:\n" + traceback.format_exc())
                self.emit({"ev": "info", "type": 1, "text": f"Sluka's engine could not do {what!r}: {err}"})
        self.quit()


def _option(argv: list[str], name: str) -> str:
    if name in argv[1:]:
        at = argv.index(name, 1)
        if at + 1 < len(argv):
            return argv[at + 1]
    return ""


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0].startswith("--"):
        print("usage: hookd.py ENGINE_FOLDER [--log FILE]", file=sys.stderr)
        return 2
    folder = argv[0]
    log_file = None
    if _option(argv, "--log"):
        try:
            os.makedirs(os.path.dirname(os.path.abspath(_option(argv, "--log"))), exist_ok=True)
            log_file = open(_option(argv, "--log"), "a", encoding="utf-8")
        except OSError:
            log_file = None
    lock = threading.Lock()

    def log(text: str) -> None:
        if log_file is None:
            return
        with lock:
            try:
                log_file.write(time.strftime("%Y-%m-%d %H:%M:%S ") + text + "\n")
                log_file.flush()
            except (OSError, ValueError):
                pass

    # The pipe to the app is for the events alone: what the host's own C code may print (it does, on an error)
    # goes nowhere, rather than into the middle of a line.
    try:
        events = os.dup(1)
        nowhere = os.open(os.devnull, os.O_WRONLY)
        os.dup2(nowhere, 1)
        os.close(nowhere)
        out = os.fdopen(events, "wb", buffering=0)
    except (OSError, ValueError):
        out = sys.stdout.buffer if sys.stdout is not None else os.fdopen(1, "wb", buffering=0)
    stdin = sys.stdin.buffer if sys.stdin is not None else os.fdopen(0, "rb")

    def write(data: bytes) -> None:
        view = memoryview(data)
        while view:
            done = out.write(view)
            view = view[done or 0:]
        out.flush()

    # (The tests' stand-ins for LunaHost64.dll and LunaSubprocess: another library, another injector.)
    injector = json.loads(_option(argv, "--injector")) if _option(argv, "--injector") else None
    log(f"Sluka's engine starting: Python {sys.version.split()[0]} ({struct.calcsize('P') * 8}-bit), folder {folder}")
    try:
        hookd = Hookd(folder, write, log, library=_option(argv, "--library"), injector=injector)
    except Exception as err:
        log("the host could not be started:\n" + traceback.format_exc())
        text = str(err)
        if WINDOWS and isinstance(err, OSError) and getattr(err, "winerror", 0) == 126:
            text = (f"{err} -- a file LunaHost64.dll needs is missing from {folder} (msvcp140.dll, vcruntime140.dll, "
                    "vcruntime140_1.dll): unpack Sluka Desktop's zip again, or allow them in Windows Security")
        line = json.dumps({"ev": "fatal", "text": text}, ensure_ascii=False) + "\n"
        try:
            write(line.encode("utf-8"))
        except OSError:
            pass
        return 3
    hookd.emit({"ev": "ready", "protocol": PROTOCOL, "library": hookd.library, "python": sys.version.split()[0],
                "bits": struct.calcsize("P") * 8, "pid": os.getpid()})
    log("ready")
    try:
        hookd.run(iter(stdin.readline, b""))
    finally:
        log("ended")
        if log_file is not None:
            log_file.close()
    return 0


if __name__ == "__main__":
    code = main()
    try:
        sys.stdout.flush()
    except (OSError, ValueError, AttributeError):
        pass
    # Out at once: the host's own threads may still be calling in, and a Python closing down is not to be called.
    os._exit(code)
