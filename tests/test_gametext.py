"""Game text: the text filters, Sluka's engine (hookd.py) driving a stand-in LunaHost, and the menu's side end to end.

The stand-in host is a library of the same functions as LunaHost64.dll (fake_lunahost.c, built here with gcc): it is
loaded and called exactly as the real one is, and a pretend game behind it connects once the stand-in injector
(fake_inject.py) has "put the hook in".  The programs on the computer are stand-ins too.
"""

from __future__ import annotations

import hashlib
import io
import json
import struct
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

import fakes  # noqa: F401  (puts the app on the path)

from lunafake import ENGINE_FILES, INJECTOR, make_engine, write_script  # noqa: E402
from sluka_desktop import gametext, hookd, textfilter, texthook, winproc
from sluka_desktop.host import Request

HERE = Path(__file__).parent


def wait_for(check, timeout=8.0, step=0.02):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if check():
            return True
        time.sleep(step)
    raise AssertionError("waited too long")


def times(text, n):
    return "".join(ch * n for ch in text)


# ---------------------------------------------------------------- the filters


@pytest.mark.parametrize("raw, shown", [
    (times("今日はいい天気ですね", 4), "今日はいい天気ですね"),
    (times("こんにちは", 2), "こんにちは"),
    (times("「行くぞ」", 3), "「行くぞ」"),
    ("ああああ", "ああああ"),  # one run is not a pattern
    ("……ーー", "……ーー"),
    ("今日はいい天気ですね今日はいい天気ですね", "今日はいい天気ですね"),
    ("「おはよう」\n「おはよう」", "「おはよう」"),
    ("わーいわーい", "わーいわーい"),  # too short to be a line sent twice
    ("今日は[r]いい天気\nですね[p]", "今日はいい天気ですね"),
    ("<color=#ff0000>赤い</color>花{w=0.5}が咲く", "赤い花が咲く"),
    ("\\C[2]魔王\\C[0]が現れた\\!", "魔王が現れた"),
    ("｜漢字《かんじ》を読む", "漢字を読む"),
    ("{rb}漢字{/rb}{rt}かんじ{/rt}を読む", "漢字を読む"),
    ("ばっ\nかじゃないの", "ばっかじゃないの"),
    ("Hello\nworld", "Hello world"),
    ("  前後の空白\u200b  ", "前後の空白"),
    ("A\u0007B", "AB"),
])
def test_a_games_text_is_tidied(raw, shown):
    assert textfilter.clean(raw) == shown


def test_the_filters_do_what_their_settings_say():
    assert textfilter.clean(times("今日は", 2), repeats="off") == times("今日は", 2)
    assert textfilter.clean("ここここ", repeats="2") == "ここ"
    assert textfilter.clean("一行目\n二行目", join=False) == "一行目\n二行目"
    assert textfilter.clean("[r]一行", codes=False) == "[r]一行"
    assert textfilter.cjk_share("今日はabc") == 0.5


def test_what_looks_like_dialogue():
    talk = ["今日はいい天気ですね", "そうだね、散歩に行こうか"]
    assert textfilter.dialogue_score(talk, "KiriKiriZ") >= gametext.AUTO_PICK_SCORE
    assert textfilter.dialogue_score(talk, "GetGlyphOutlineW") < textfilter.dialogue_score(talk, "KiriKiriZ")
    assert textfilter.dialogue_score(talk, "KiriKiriZ", per_second=20) < 1.0
    assert textfilter.dialogue_score(["Load", "Save", "Config"]) == 0
    assert textfilter.dialogue_score(["今"] * 10) == 0


# ---------------------------------------------------------------- what is given to the engine


def test_hook_codes_are_checked_before_the_engine_sees_them():
    assert texthook.check_hook_code("/hs-4@1234:game.exe") == "HS-4@1234:game.exe"
    assert texthook.check_hook_code(" HQ-14*0@7ff6:GameAssembly.dll:Func ") == "HQ-14*0@7ff6:GameAssembly.dll:Func"
    assert texthook.check_hook_code("RS@0x12345") == "RS@0x12345"
    # LunaHook's other kinds: a breakpoint (B), a hook at the return (L...), an embedding one (E...).
    for good in ("BS-4@1234:game.exe", "LHW-8@1234", "EHS-4@1234:game.exe", "HQN36#-1@4E3EC8:JIT:YUZU"):
        assert texthook.check_hook_code(good) == good
    for bad in ("", "hello", "HS-4", "@1234", "X-4@1234", "HS-4@12\nHS-8@12", "H" + "x" * 500 + "@1"):
        assert texthook.check_hook_code(bad) == ""


def lunahook_strings():
    rows = (HERE / "data" / "lunahook-strings-12.1.3.12.txt").read_text(encoding="utf-8").splitlines()
    return dict(line.split("\t", 1) for line in rows if line and not line.startswith("#"))


def test_the_engine_speaks_english_with_the_same_placeholders():
    """The hook in the game formats some of its messages with printf: an English one with other placeholders than
    the Chinese one it stands for could read what is not there."""
    known = set(lunahook_strings().values())
    assert set(hookd.ENGLISH) <= known
    for chinese, english in hookd.ENGLISH.items():
        assert hookd.placeholders(chinese) == hookd.placeholders(english), chinese
        assert english.strip() and not any("\u4e00" <= ch <= "\u9fff" for ch in english)
    # Every message with a placeholder, and every one the host says, has its English.
    for name, chinese in lunahook_strings().items():
        if hookd.placeholders(chinese) or name in ("T_WARNING", "ALREADY_INJECTED", "INJECT_FAILED", "INVALID_CODEPAGE",
                                                   "PROC_CONN", "PROC_DISCONN", "UNMATCHABLEVERSION"):
            assert chinese in hookd.ENGLISH, name
    assert hookd.placeholders("%d of %zd at 0x%p (%f%%) %s") == ["%d", "%zd", "%p", "%f", "%%", "%s"]


def test_the_engine_on_disk(tmp_path):
    config = type("C", (), {"engine_dir": tmp_path / "engine", "root": tmp_path})()
    missing = texthook.find_engine(config)
    assert not missing.ok and "folder is missing" in missing.error and missing.missing == ENGINE_FILES
    make_engine(tmp_path / "engine")
    found = texthook.find_engine(config)
    assert found.ok and found.missing == [] and found.describe()["kinds"] == [32, 64]
    assert found.describe()["version"] == "LunaTranslator 12.1.3.12"
    (tmp_path / "engine" / "LunaHook32.dll").unlink()
    (tmp_path / "engine" / "msvcp140.dll").unlink()
    gone = texthook.find_engine(config)
    assert not gone.ok and gone.missing == ["LunaHook32.dll", "msvcp140.dll"] and "Windows Security" in gone.error
    # The engine that comes with the app, where the config says no other.
    assert texthook.engine_dir(type("C", (), {"root": tmp_path})()) == tmp_path / "engine"


def test_the_engine_that_comes_with_the_app():
    """The engine folder of the working copy: LunaTranslator 12.1.3.12's files, as ENGINE.txt lists them."""
    folder = Path(fakes.APP).parent / "engine"
    notice = (folder / "ENGINE.txt").read_bytes().decode("utf-8")
    assert "\r\n" in notice and "GNU General Public License, version 3" in notice and "v12.1.3.12" in notice
    for name in ENGINE_FILES + ["LunaTmpFontLoader.dll", "source/LunaTranslator-12.1.3.12.zip"]:
        data = (folder / name).read_bytes()
        assert f"{hashlib.sha256(data).hexdigest()}  {name.replace('/', chr(92))}" in notice, name
    for name in ("LICENSE.LunaTranslator", "LICENSE.Artikash.Textractor"):
        assert "GNU GENERAL PUBLIC LICENSE" in (folder / "LICENSES" / name).read_text(encoding="utf-8")
    # The kinds of program they are: the host and the 64-bit ones for x64, the 32-bit ones for x86.
    def machine(name):
        data = (folder / name).read_bytes()
        pe = struct.unpack_from("<I", data, 0x3C)[0]
        assert data[pe:pe + 4] == b"PE\0\0"
        return struct.unpack_from("<H", data, pe + 4)[0]
    assert {name: machine(name) for name in ENGINE_FILES} == {
        "LunaHost64.dll": 0x8664, "LunaHook32.dll": 0x14C, "LunaHook64.dll": 0x8664, "LunaSubprocess32.exe": 0x14C,
        "LunaSubprocess64.exe": 0x8664, "msvcp140.dll": 0x8664, "vcruntime140.dll": 0x8664, "vcruntime140_1.dll": 0x8664}
    # What hookd.py calls is there, by those names.
    host = (folder / "LunaHost64.dll").read_bytes()
    for name in ("Luna_Start", "Luna_ResetLang", "Luna_Settings", "Luna_SettingsEx", "Luna_ConnectProcess",
                 "Luna_CheckIfNeedInject", "Luna_DetachProcess", "Luna_InsertHookCode", "Luna_InsertPCHooks",
                 "Luna_RemoveHook", "Luna_SyncThread", "Luna_AllocString"):
        assert name.encode() + b"\0" in host


# ---------------------------------------------------------------- the engine, as a program of its own


class Hookd:
    def __init__(self, engine, args, log):
        command = [sys.executable, "-I", "-X", "utf8", str(texthook.HOOKD), str(engine), "--log", str(log), *args]
        self.proc = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.events = []
        threading.Thread(target=self._read, daemon=True).start()

    def _read(self):
        for line in self.proc.stdout:
            self.events.append(json.loads(line))

    def send(self, **command):
        self.proc.stdin.write((json.dumps(command) + "\n").encode())
        self.proc.stdin.flush()

    def seen(self, **match):
        return [e for e in self.events if all(e.get(k) == v for k, v in match.items())]

    def said(self, start):
        return [e["text"] for e in self.events if e["ev"] == "info" and e["text"].startswith(start)]


def test_the_engine_drives_lunahost_as_lunatranslator_does(luna, tmp_path):
    write_script(luna.folder, [
        (50, 0x455E0E, 0x7FF61234, 0, "KiriKiriZ", "HW-4@55E0E:sakura.exe", "今日はいい天気ですね"),
        (20, "engine", "KiriKiri"),
        (20, 0x402000, 0x33, 0, "Menu", "HS@1:sakura.exe", "Load\nSave"),
    ])
    h = Hookd(luna.engine, luna.args, tmp_path / "hookd.log")
    wait_for(lambda: h.seen(ev="ready"))
    ready = h.seen(ev="ready")[0]
    assert ready["protocol"] == 1 and ready["bits"] == 64
    # Started as LunaTranslator starts it: its own messages in English (all 7 of the host's), LunaTranslator's settings.
    assert h.said("lang ") == ["lang 7"]
    assert h.said("settings ") == ["settings flush=500 codepage=932 buffer=3000 history=1000000 pc=0"]
    h.send(cmd="settings", flush=300, codepage=936)
    h.send(cmd="attach", pids=[4242], bits=32)
    wait_for(lambda: h.seen(ev="text", id=2))
    assert h.said("settings flush=300 codepage=936")
    assert h.seen(ev="inject", pid=4242) == [{"ev": "inject", "pid": 4242, "ok": True, "how": "injected"}]
    assert (luna.folder / "injections.txt").read_text().split() == ["4242", str(luna.engine / "LunaHook32.dll")]
    assert h.seen(ev="connect", pid=4242) and h.said("Process 4242 connected")
    # As LunaTranslator sets each game as it connects (set_settings_ex), translations into the game off.
    wait_for(lambda: h.said("settingsex"))
    assert h.said("settingsex") == ["settingsex pid=4242 wait=2000 charset=2/0 font=[] mode=0 skip=1 clear=0 size=0/1.0 veh=1 unity=[]"]
    first = h.seen(ev="thread", id=1)[0]
    assert (first["pid"], first["addr"], first["ctx"], first["ctx2"], first["name"], first["code"]) == \
        (4242, 0x455E0E, 0x7FF61234, 0, "KiriKiriZ", "HW-4@55E0E:sakura.exe")
    assert h.seen(ev="text", id=1)[0]["text"] == "今日はいい天気ですね" and h.seen(ev="text", id=2)[0]["text"] == "Load\nSave"
    assert h.seen(ev="info", type=4, text="KiriKiri")
    # A picked thread is synced with the others (its whole place given back, as the host gave it).
    h.send(cmd="sync", id=1, on=True)
    wait_for(lambda: h.said("sync "))
    assert h.said("sync ") == ["sync pid=4242 addr=455e0e ctx=7ff61234 ctx2=0 on=1"]
    h.send(cmd="hookcode", pid=4242, code="HS-8@1234:sakura.exe")
    h.send(cmd="pchooks", pid=4242)
    wait_for(lambda: len(h.seen(ev="thread")) == 5)
    assert [e["name"] for e in h.seen(ev="thread")][2:] == ["UserHook0", "GetGlyphOutlineW", "TextOutW"]
    assert h.seen(ev="hook", pid=4242, code="HS-8@1234:sakura.exe")
    assert h.said("pchooks ") == ["pchooks pid=4242 which=0", "pchooks pid=4242 which=1"]
    # Let go: its threads go, it disconnects.
    h.send(cmd="detach", pid=4242)
    wait_for(lambda: h.seen(ev="disconnect", pid=4242))
    assert sorted(e["id"] for e in h.seen(ev="gone")) == [1, 2, 3, 4, 5] and h.said("Process 4242 disconnected")
    # Hooked again: put in again (its hook left), the same threads numbered anew.
    h.send(cmd="attach", pid=4242, bits=64)  # (one program, as 0.8.0's first protocol had it, is taken too)
    wait_for(lambda: len(h.seen(ev="connect")) == 2)
    assert (luna.folder / "injections.txt").read_text().splitlines()[-1] == f"4242 {luna.engine / 'LunaHook64.dll'}"
    wait_for(lambda: h.seen(ev="thread", id=6))
    h.send(cmd="nonsense")
    h.send(cmd="sync", id=999, on=True)  # gone: nothing
    h.proc.stdin.write(b"not json\n")
    h.send(cmd="quit")
    assert h.proc.wait(10) == 0
    log = (tmp_path / "hookd.log").read_text(encoding="utf-8")
    assert "injector (32-bit) gave 1" in log and "connected: 4242" in log and "ended" in log


def test_what_the_injector_cannot_do_is_said(luna, tmp_path):
    write_script(luna.folder, [(20, 1, 1, 0, "KiriKiriZ", "HW-4@1:a.exe", "一行")])
    (luna.folder / "deny-77").write_text("")
    (luna.folder / "hooked-88").write_text("")
    h = Hookd(luna.engine, luna.args, tmp_path / "hookd.log")
    wait_for(lambda: h.seen(ev="ready"))
    # Programs of one game together: those the hook is not in yet, put in in one go (as LunaTranslator does).
    h.send(cmd="attach", pids=[66, 77], bits=32)
    h.send(cmd="attach", pids=[88], bits=64)
    wait_for(lambda: h.seen(ev="inject", pid=77) and h.seen(ev="connect", pid=88) and h.seen(ev="connect", pid=66))
    assert (luna.folder / "injections.txt").read_text().splitlines()[0] == f"66 77 {luna.engine / 'LunaHook32.dll'}"
    denied = h.seen(ev="inject", pid=77)[0]
    assert denied["ok"] is False and denied["how"] == "denied" and "administrator" in denied["error"]
    # The hook was in it already (from before): not put in again, it connects to this host.
    assert h.seen(ev="inject", pid=88) == [{"ev": "inject", "pid": 88, "ok": True, "how": "already"}]
    assert h.said("Already hooked")
    assert "88" not in (luna.folder / "injections.txt").read_text()
    # The injector gone (an antivirus took it): said so.
    (luna.engine / "LunaHook32.dll").unlink()
    h.send(cmd="attach", pids=[99], bits=32)
    wait_for(lambda: h.seen(ev="inject", pid=99))
    assert h.seen(ev="inject", pid=99)[0]["how"] == "missing"
    h.proc.stdin.close()  # the app went away: it ends too
    assert h.proc.wait(10) == 0


def test_a_host_that_cannot_be_loaded_is_said(luna, tmp_path):
    args = ["--library", str(tmp_path / "nothing.so"), "--injector", json.dumps(INJECTOR)]
    h = Hookd(luna.engine, args, tmp_path / "hookd.log")
    assert h.proc.wait(10) == 3
    wait_for(lambda: h.events)
    assert h.events[0]["ev"] == "fatal" and "nothing.so" in h.events[0]["text"]


# ---------------------------------------------------------------- the menu's side


class FakeBar:
    def __init__(self):
        self.on = False
        self.lines = []

    def set_on(self, on):
        self.on = on
        return on

    def inject(self, text, lang=None):
        self.lines.append(text)
        return {"ok": True}


class FakeWatch:
    def __init__(self, procs, pid):
        self.procs, self.pid = procs, pid

    def alive(self):
        return self.pid in self.procs.running

    def close(self):
        pass


class FakeProcs:
    own_pid = 1000

    def __init__(self):
        self.running = {4242: ("C:\\Games\\Sakura\\sakura.exe", 32, "桜の詩")}
        self.windowless = set()
        self.foreground = 0
        self.reach = {}

    def exe(self, pid):
        return self.running.get(pid, ("",))[0]

    def bits(self, pid):
        return self.running.get(pid, ("", 0))[1]

    def can_reach(self, pid):
        if pid in self.reach:
            return self.reach[pid]
        return (True, "") if pid in self.running else (False, "error 87")

    def watch(self, pid):
        return FakeWatch(self, pid)

    def is_running(self, pid):
        return pid in self.running

    def processes(self):
        out = [{"pid": 1000, "parent": 1, "name": "python.exe"}, {"pid": 1001, "parent": 1000, "name": "msedgewebview2.exe"},
               {"pid": 1002, "parent": 1001, "name": "msedgewebview2.exe"}, {"pid": 5, "parent": 1, "name": "explorer.exe"}]
        out += [{"pid": pid, "parent": 1, "name": path.split("\\")[-1]} for pid, (path, _b, _t) in self.running.items()]
        return out

    def windows(self):
        out = [{"pid": 1002, "hwnd": 1, "title": "Sluka"}, {"pid": 5, "hwnd": 2, "title": "Explorer"}]
        out += [{"pid": pid, "hwnd": pid * 10, "title": title} for pid, (_p, _b, title) in self.running.items()
                if pid not in self.windowless]
        return out

    def foreground_pid(self):
        return self.foreground

    def pids_of(self, path):
        return [pid for pid, (p, _b, _t) in self.running.items() if p.lower() == str(path).lower()]

    def title_of(self, pid):
        return self.running.get(pid, ("", 0, ""))[2]

    def is_admin(self):
        return False

    def bind(self, handle):
        return True



class FakeClipboard:
    def __init__(self, on_text, own_pid):
        self.on_text, self.own_pid = on_text, own_pid
        self.put_lines = []
        self.watching = False
        self.error = ""

    def start(self):
        self.watching = True
        return True

    def stop(self):
        self.watching = False

    def put(self, text):
        self.put_lines.append(text)


def ask(gt, name, body=None, headers=None):
    got = []
    request = Request("POST", f"/__sluka__/api/games/{name}", headers={"sec-fetch-site": "same-origin", **(headers or {})},
                      body=json.dumps(body or {}).encode())
    gt.api(name, request, got.append)
    if not got:
        return None
    return json.loads(got[0].body) if got[0].status == 200 else {"status": got[0].status, **json.loads(got[0].body)}


DIALOGUE = ["今日はいい天気ですね", "そうだね、散歩に行こうか", "「待って！」と彼女は言った", "空がとても青い"]


def game_script():
    rows = [(150, 0x401000, 0x10, 0, "GetGlyphOutlineW", "HW@0:gdi32.dll:GetGlyphOutlineW", "今"),
            (20, 0x402000, 0x33, 0, "Menu", "HS@1:sakura.exe", "Load\nSave"),
            (10, "engine", "KiriKiri")]
    for line in DIALOGUE:
        rows.append((120, 0x455E0E, 0x7FF61234, 0, "KiriKiriZ", "HW-4@55E0E:sakura.exe", times(line, 4)))
        rows.append((20, 0x402000, 0x33, 0, "Menu", "HS@1:sakura.exe", "Load\nSave"))
    return rows


@pytest.fixture
def setup(tmp_path, luna):
    write_script(luna.folder, game_script())
    config = type("C", (), {"data_dir": tmp_path / "data", "log_dir": tmp_path / "data" / "logs", "network_mode": "direct",
                            "engine_dir": luna.engine, "root": tmp_path})()
    host = type("H", (), {})()
    host.bar = FakeBar()
    procs = FakeProcs()
    made = []

    def build():
        gt = gametext.GameText(config, host, procs=procs, clipboard_factory=FakeClipboard)
        gt.start()
        made.append(gt)
        return gt

    yield build, host, procs, config, luna
    for gt in made:
        gt.close()


def engine_said(gt, start):
    return [line[2] for line in ask(gt, "state")["log"] if line[2].startswith(start)]


def test_a_game_end_to_end(setup):
    build, host, procs, config, luna = setup
    gt = build()
    state = ask(gt, "state")
    assert state["mode"] == "game" and state["game"] is None
    assert state["engine"]["kinds"] == [32, 64] and state["engine"]["error"] == "" and not state["engine"]["running"]
    assert state["settings"]["flush_ms"] == 500 and state["settings"]["codepage"] == 932

    # The programs that could be games: not Sluka's own, nor Windows' Explorer.
    listed = ask(gt, "processes")["processes"]
    assert [p["pid"] for p in listed] == [4242] and listed[0]["exe"] == "sakura.exe" and listed[0]["bits"] == 32

    # Hooked: the floating subtitles come on, the engine starts, the threads come, the dialogue is picked by itself.
    assert ask(gt, "attach", {"pid": 4242}) == {"ok": True}
    assert host.bar.on and ask(gt, "state")["mode"] == "game"
    # Hooked again while it is: left as it is (let go and hooked at once, a game can be left half hooked).
    assert ask(gt, "attach", {"pid": 4242}) == {"ok": True, "already": True}
    wait_for(lambda: ask(gt, "state")["game"]["state"] == "attached")
    assert ask(gt, "state")["engine"]["running"]
    wait_for(lambda: host.bar.lines, timeout=10)
    state = ask(gt, "state")
    picked = [t for t in state["threads"] if t["id"] in state["selected"]]
    assert state["picked"] == "auto" and [t["name"] for t in picked] == ["KiriKiriZ"]
    assert host.bar.lines[0] in DIALOGUE  # every letter was sent four times
    wait_for(lambda: host.bar.lines[-1] == DIALOGUE[-1], timeout=10)
    assert all(line in DIALOGUE for line in host.bar.lines) and len(host.bar.lines) == len(set(host.bar.lines))
    state = ask(gt, "state")
    names = {t["name"]: t for t in state["threads"]}
    assert set(names) == {"KiriKiriZ", "GetGlyphOutlineW", "Menu"} and names["Menu"]["text"] == "Load Save"
    assert state["game"]["engine"] == "KiriKiri"  # the game's engine, as the hook found it
    # The engine's own messages, in English, and the thread picked synced with the host.
    assert engine_said(gt, "Process 4242 connected") and engine_said(gt, "sync pid=4242 addr=455e0e")

    # Another thread picked by hand: what it said last is shown at once, and kept for the game.
    menu, dialogue = names["Menu"]["id"], names["KiriKiriZ"]["id"]
    assert ask(gt, "select", {"id": menu, "only": True})["selected"] == [menu]
    assert host.bar.lines[-1] == "Load Save"
    wait_for(lambda: engine_said(gt, "sync pid=4242 addr=455e0e ctx=7ff61234 ctx2=0 on=0"))
    wait_for(lambda: (config.data_dir / "gametext.json").exists())
    gt._save()
    kept = json.loads((config.data_dir / "gametext.json").read_text())
    memo = kept["games"]["c:\\games\\sakura\\sakura.exe"]
    assert memo["threads"][0]["code"] == "HS@1:sakura.exe" and memo["exe"] == "sakura.exe" and kept["settings"]["mode"] == "game"
    # Two threads together, in the order picked.
    assert ask(gt, "select", {"id": dialogue, "on": True})["selected"] == [menu, dialogue]

    # A hook code: checked, given to the game, kept for it.
    assert ask(gt, "hookcode", {"code": "HS 8"})["ok"] is False
    assert ask(gt, "hookcode", {"code": "hs-8@1234:sakura.exe"}) == {"ok": True, "code": "HS-8@1234:sakura.exe"}
    wait_for(lambda: any(t["name"].startswith("UserHook") for t in ask(gt, "state")["threads"]))

    # Let go, and hooked again: what was picked is picked again as the threads come back, in the order it was picked,
    # and the code is given again.
    assert ask(gt, "detach") == {"ok": True}
    assert ask(gt, "state")["game"] is None
    host.bar.lines.clear()
    assert ask(gt, "attach", {"pid": 4242})["ok"]
    wait_for(lambda: ask(gt, "state")["picked"] == "remembered", timeout=12)
    wait_for(lambda: any(t["name"].startswith("UserHook") for t in ask(gt, "state")["threads"]), timeout=10)
    wait_for(lambda: len(ask(gt, "state")["selected"]) == 2, timeout=10)
    state = ask(gt, "state")
    by_id = {t["id"]: t["name"] for t in state["threads"]}
    assert [by_id[i] for i in state["selected"]] == ["Menu", "KiriKiriZ"]
    assert state["game"]["codes"] == ["HS-8@1234:sakura.exe"] and state["game"]["remembered"]
    # A line of each that come together: shown together, the menu's first (as picked).
    wait_for(lambda: any(line.startswith("Load Save\n") for line in host.bar.lines), timeout=10)

    # The game closes; started again, it is hooked again by itself.
    del procs.running[4242]
    wait_for(lambda: ask(gt, "state")["game"]["state"] == "ended", timeout=5)
    assert ask(gt, "state")["threads"] == []
    procs.running[4343] = ("C:\\Games\\Sakura\\sakura.exe", 32, "桜の詩")
    wait_for(lambda: (ask(gt, "state")["game"] or {}).get("pid") == 4343, timeout=8)
    wait_for(lambda: ask(gt, "state")["picked"] == "remembered", timeout=12)
    # Let go by hand, it is not hooked again by itself while it runs.
    ask(gt, "detach")
    time.sleep(3.5)
    assert ask(gt, "state")["game"] is None
    # Forgotten, it is not hooked again when it starts.
    ask(gt, "attach", {"pid": 4343})
    assert ask(gt, "forget")["ok"]
    assert "c:\\games\\sakura\\sakura.exe" not in gt.games


def test_what_cannot_be_hooked_is_said(setup):
    build, host, procs, config, luna = setup
    gt = build()
    procs.reach[4242] = (False, "admin")
    answer = ask(gt, "attach", {"pid": 4242})
    assert not answer["ok"] and answer["admin"] is True and "administrator" in answer["error"]
    assert ask(gt, "state")["game"] is None
    assert ask(gt, "attach", {"pid": 1000})["ok"] is False  # Sluka itself
    assert ask(gt, "attach", {"pid": 9})["ok"] is False
    assert ask(gt, "select", {"id": 77})["ok"] is False
    assert ask(gt, "hookcode", {"code": "HS-4@1:x.exe"})["ok"] is False  # nothing hooked
    # Put in as administrator, it is hooked (here the stand-in injector stands in for Windows' "run as administrator").
    assert ask(gt, "attach", {"pid": 4242, "elevate": True}) == {"ok": True}
    wait_for(lambda: ask(gt, "state")["game"]["state"] == "attached", timeout=10)
    assert ask(gt, "state")["game"]["elevated"] is True
    ask(gt, "detach")
    # The engine's files gone: said so, with what to do.
    (luna.engine / "LunaHook32.dll").unlink()
    procs.reach.clear()
    answer = ask(gt, "attach", {"pid": 4242})
    assert not answer["ok"] and "LunaHook32.dll" in answer["error"] and "Windows Security" in answer["error"]
    assert ask(gt, "state")["engine"]["missing"] == ["LunaHook32.dll"]
    (luna.engine / "LunaHook32.dll").write_bytes(b"")
    assert ask(gt, "rescan")["ok"] and ask(gt, "state")["engine"]["error"] == ""
    # Only the app's own pages, and only by POST.
    got = []
    gt.api("state", Request("POST", "/x", headers={"sec-fetch-site": "cross-site"}, body=b"{}"), got.append)
    assert got[0].status == 403
    got = []
    gt.api("state", Request("GET", "/x"), got.append)
    assert got[0].status == 403


def test_a_game_that_cannot_be_opened_asks_for_administrator(setup):
    build, host, procs, config, luna = setup
    (luna.folder / "deny-4242").write_text("")
    gt = build()
    assert ask(gt, "attach", {"pid": 4242}) == {"ok": True}
    wait_for(lambda: ask(gt, "state")["game"]["state"] == "failed", timeout=10)
    game = ask(gt, "state")["game"]
    assert game["admin"] is True and "Hook as administrator" in game["error"]


def test_a_game_hooked_already_connects_again(setup):
    build, host, procs, config, luna = setup
    (luna.folder / "hooked-4242").write_text("")
    gt = build()
    ask(gt, "attach", {"pid": 4242})
    wait_for(lambda: host.bar.lines, timeout=10)
    assert any("the hook was there already" in line[2] for line in ask(gt, "state")["log"])
    assert not (luna.folder / "injections.txt").exists()


def test_a_game_that_does_not_connect_is_explained(setup, monkeypatch):
    build, host, procs, config, luna = setup
    monkeypatch.setattr(gametext, "CONNECT_HINT_SECONDS", 0.5)
    (luna.folder / "noconnect-4242").write_text("")
    gt = build()
    ask(gt, "attach", {"pid": 4242})
    wait_for(lambda: any("has not connected yet" in line[2] for line in ask(gt, "state")["log"]), timeout=6)
    assert ask(gt, "state")["game"]["state"] == "attaching"


def test_programs_of_the_same_file_are_hooked_too(setup):
    build, host, procs, config, luna = setup
    # A game that draws in programs of its own (NW.js, CEF): the same file, more than one program, some without a window.
    procs.running[4243] = ("C:\\Games\\Sakura\\sakura.exe", 32, "")
    procs.windowless.add(4243)
    gt = build()
    ask(gt, "attach", {"pid": 4242})
    wait_for(lambda: (luna.folder / "injected-4243").exists() and (luna.folder / "injected-4242").exists(), timeout=10)
    assert ask(gt, "state")["game"]["pids"] == [4242, 4243]
    # One more, started a while after: hooked too.
    procs.running[4244] = ("C:\\Games\\Sakura\\sakura.exe", 32, "")
    procs.windowless.add(4244)
    wait_for(lambda: (luna.folder / "injected-4244").exists(), timeout=8)
    wait_for(lambda: 4244 in ask(gt, "state")["game"]["connected"], timeout=8)
    # One of them ends: the game goes on.
    del procs.running[4243]
    wait_for(lambda: ask(gt, "state")["game"]["pids"] == [4242, 4244], timeout=5)
    assert ask(gt, "state")["game"]["state"] == "attached"


def test_settings_and_windows_text_functions_go_to_the_engine(setup):
    build, host, procs, config, luna = setup
    gt = build()
    ask(gt, "attach", {"pid": 4242})
    wait_for(lambda: ask(gt, "state")["game"]["state"] == "attached", timeout=10)
    assert ask(gt, "settings", {"settings": {"flush_ms": 800, "codepage": 936}})["settings"]["codepage"] == 936
    wait_for(lambda: engine_said(gt, "settings flush=800 codepage=936"))
    # Windows' own text functions, for a game whose engine is not known: more threads, and kept for the game.
    assert ask(gt, "pchooks", {"on": True}) == {"ok": True}
    wait_for(lambda: {"GetGlyphOutlineW", "TextOutW"} <= {t["name"] for t in ask(gt, "state")["threads"]})
    assert ask(gt, "state")["game"]["pchooks"] is True
    ask(gt, "detach")
    ask(gt, "attach", {"pid": 4242})
    wait_for(lambda: len(engine_said(gt, "pchooks pid=4242 which=1")) == 2, timeout=12)
    # They are there for the engine started again too.
    gt.close()
    again = build()
    ask(again, "attach", {"pid": 4242})
    wait_for(lambda: engine_said(again, "settings flush=800 codepage=936"), timeout=10)


def test_a_hook_that_leaves_the_game_is_said(setup):
    build, host, procs, config, luna = setup
    write_script(luna.folder, [(100, 0x455E0E, 0x7FF61234, 0, "KiriKiriZ", "HW-4@55E0E:sakura.exe", DIALOGUE[0]),
                               (300, "leave")])
    gt = build()
    ask(gt, "attach", {"pid": 4242})
    wait_for(lambda: ask(gt, "state")["game"]["state"] == "failed", timeout=10)
    game = ask(gt, "state")["game"]
    assert "hook left" in game["error"] and game["connected"] == [] and ask(gt, "state")["threads"] == []
    # Hooked again from the menu: it is.
    write_script(luna.folder, game_script())
    assert ask(gt, "attach", {"pid": 4242}) == {"ok": True}
    wait_for(lambda: ask(gt, "state")["game"]["state"] == "attached", timeout=10)


def test_an_engine_that_stops_is_started_again(setup):
    build, host, procs, config, luna = setup
    write_script(luna.folder, [(100, 0x455E0E, 0x7FF61234, 0, "KiriKiriZ", "HW-4@55E0E:sakura.exe", DIALOGUE[0]),
                               (200, "crash")])
    gt = build()
    ask(gt, "attach", {"pid": 4242})
    wait_for(lambda: any("Sluka's engine stopped" in line[2] for line in ask(gt, "state")["log"]), timeout=10)
    first = gt.runner
    write_script(luna.folder, game_script())  # the next time, the game goes on
    wait_for(lambda: gt.runner is not None and gt.runner is not first and gt.runner.alive, timeout=10)
    wait_for(lambda: host.bar.lines and host.bar.lines[-1] == DIALOGUE[-1], timeout=12)
    assert ask(gt, "state")["game"]["state"] == "attached"


def test_an_engine_that_keeps_stopping_is_left(setup, monkeypatch):
    build, host, procs, config, luna = setup
    monkeypatch.setattr(gametext, "LET_GO_SECONDS", 0.2)
    write_script(luna.folder, [(50, "crash")])
    gt = build()
    ask(gt, "attach", {"pid": 4242})
    wait_for(lambda: ask(gt, "state")["game"]["state"] == "failed", timeout=25)
    assert "keeps stopping" in ask(gt, "state")["game"]["error"]


def test_the_window_clicked_is_hooked(setup):
    build, host, procs, config, luna = setup
    gt = build()
    assert ask(gt, "pick", {"seconds": 5})["ok"]
    assert ask(gt, "state")["picking"] > 0
    procs.foreground = 1002  # Sluka's own window: not a game
    time.sleep(0.3)
    assert ask(gt, "state")["game"] is None
    procs.foreground = 4242
    wait_for(lambda: (ask(gt, "state")["game"] or {}).get("pid") == 4242)
    assert ask(gt, "state")["picking"] == 0


def test_the_clipboard_and_another_program(setup):
    build, host, procs, config, luna = setup
    gt = build()
    assert ask(gt, "mode", {"mode": "clipboard"}) == {"ok": True, "mode": "clipboard"}
    assert host.bar.on and gt.clipboard.watching
    gt.clipboard.on_text("コピーした一文", False)
    gt.clipboard.on_text("Sluka's own", True)
    gt.clipboard.on_text("https://example.com/page", False)
    gt.clipboard.on_text("".join(f"{i}番目の文。" for i in range(300)), False)  # a page, not a line
    gt.clipboard.on_text("コピーした一文", False)  # the same again, at once
    assert host.bar.lines == ["コピーした一文"]
    ask(gt, "settings", {"settings": {"skip_own": False}})
    gt.clipboard.on_text("Sluka's own", True)
    assert host.bar.lines[-1] == "Sluka's own"

    # A game's lines put on the clipboard too, where asked (not taken back from it).
    ask(gt, "settings", {"settings": {"copy": True}})
    ask(gt, "attach", {"pid": 4242})
    wait_for(lambda: gt.clipboard.put_lines, timeout=10)
    assert gt.clipboard.put_lines[0] in DIALOGUE
    gt.clipboard.on_text("from elsewhere", False)
    assert host.bar.lines[-1] != "from elsewhere"  # the game is the source now


def test_the_menu_waits_for_a_change(setup):
    build, host, procs, config, luna = setup
    gt = build()
    first = ask(gt, "state")
    got = []
    request = Request("POST", "/x", headers={"sec-fetch-site": "same-origin"},
                      body=json.dumps({"since": first["version"], "wait": True}).encode())
    gt.api("state", request, got.append)
    time.sleep(0.3)
    assert not got  # nothing changed yet
    ask(gt, "settings", {"settings": {"repeats": "3"}})
    wait_for(lambda: got)
    answer = json.loads(got[0].body)
    assert answer["version"] > first["version"] and answer["settings"]["repeats"] == "3"
    assert ask(gt, "state", {"brief": True})["mode"] == "game"
    # Settings are checked.
    ask(gt, "settings", {"settings": {"repeats": "9", "flush_ms": "x", "codepage": 99999, "copy": "yes", "clip_most": 5}})
    s = ask(gt, "state")["settings"]
    assert s["repeats"] == "3" and s["flush_ms"] == 500 and s["codepage"] == 932 and s["copy"] is False and s["clip_most"] == 50
    assert ask(gt, "state")["choices"]["codepages"][0] == 932 and 0 in ask(gt, "state")["choices"]["codepages"]
    assert ask(gt, "mode", {"mode": "nonsense"})["ok"] is False
    assert ask(gt, "nonsense")["status"] == 404
    # They are there again at the next start; 0.7.0's own settings that are no more are left out.
    gt._save()
    kept = json.loads((config.data_dir / "gametext.json").read_text())
    kept["settings"]["line_delay"] = 300
    (config.data_dir / "gametext.json").write_text(json.dumps(kept))
    again = gametext.GameText(config, host, procs=procs, clipboard_factory=FakeClipboard)
    assert again.settings["repeats"] == "3" and again.settings["clip_most"] == 50 and "line_delay" not in again.settings


def test_programs_that_could_be_games():
    procs = FakeProcs()
    procs.running[77] = ("C:\\Windows\\explorer.exe", 64, "File Explorer")
    found = winproc.candidates(procs)
    assert [p["pid"] for p in found] == [4242]


def test_remembered_threads_are_matched_as_lunatranslator_matches_them():
    t = gametext.TextThread({"id": 1, "pid": 1, "addr": 0x10, "ctx": 0x7FF6_1234, "ctx2": 0x5_0000, "code": "HS-4@1:a.exe",
                             "name": "N"}, 0.0)
    assert t.matches({"code": "HS-4@1:a.exe", "ctx": 0x1234, "ctx2": 0}) == 2  # the low 16 bits of the places
    assert t.matches({"code": "HS-4@1:a.exe", "ctx": 0x1235, "ctx2": 0}) == 1
    assert t.matches({"code": "HS-8@1:a.exe", "ctx": 0x1234, "ctx2": 0}) == 0
    assert t.matches({"code": "", "ctx": 0x1234}) == 0


def test_hook_check_from_the_command_line(tmp_path, luna, monkeypatch):
    write_script(luna.folder, [(100, 0x455E0E, 0, 0, "KiriKiriZ", "HW-4@55E0E:sakura.exe", "一行目\n二行目")])
    config = type("C", (), {"data_dir": tmp_path, "log_dir": tmp_path / "logs", "engine_dir": luna.engine, "root": tmp_path})()
    monkeypatch.setattr(texthook, "WINDOWS", True)
    monkeypatch.setattr(texthook, "CREATE_NO_WINDOW", 0)  # (as Popen takes it here)
    monkeypatch.setattr(winproc, "Procs", FakeProcs)
    out = io.StringIO()
    assert texthook.command_check(config, show_list=True, out=out) == 0
    assert "4242" in out.getvalue() and "sakura.exe" in out.getvalue()
    out = io.StringIO()
    assert texthook.command_check(config, out=out) == 0
    assert "ok: the engine is running (Python" in out.getvalue() and "ok: the engine starts" in out.getvalue()
    out = io.StringIO()
    assert texthook.command_check(config, pid=4242, seconds=2, out=out) == 0
    text = out.getvalue()
    assert "ok: program 4242 is C:\\Games\\Sakura\\sakura.exe (32-bit)" in text
    assert "ok: the hook is in program 4242 (injected)" in text and "ok: program 4242 is connected" in text
    assert "hook: Process 4242 connected" in text
    assert "thread 1: KiriKiriZ  HW-4@55E0E:sakura.exe" in text and "[1] 一行目⏎二行目" in text
    out = io.StringIO()
    assert texthook.command_check(config, pid=9, out=out) == 4 and "no program 9" in out.getvalue()
    reach = {4242: (False, "admin")}
    monkeypatch.setattr(FakeProcs, "can_reach", lambda self, pid: reach.get(pid, (True, "")))
    out = io.StringIO()
    assert texthook.command_check(config, pid=4242, out=out) == 4 and "--admin" in out.getvalue()
    (luna.engine / "LunaHost64.dll").unlink()
    out = io.StringIO()
    assert texthook.command_check(config, out=out) == 3 and "LunaHost64.dll" in out.getvalue()


def test_a_hooked_games_lines_and_sound_are_kept_for_cards(setup):
    """While the floating subtitles have a game hooked, its sound is followed (gamesound.py) and each line it shows is
    kept with when it came and which game it is (ankicards.py), for the Anki cards of words picked on it; let go of,
    neither is."""
    build, host, procs, config, luna = setup
    gt = build()
    assert gt.cards.status()["following"] == {"bar": 0, "vision": 0}
    assert ask(gt, "attach", {"pid": 4242}) == {"ok": True}
    wait_for(lambda: ask(gt, "state")["game"]["state"] == "attached")
    wait_for(lambda: gt.cards.status()["following"]["bar"] == 4242, timeout=5)
    assert gt.cards.sound.status()["holders"] == {"bar": 4242}
    wait_for(lambda: host.bar.lines, timeout=10)
    kept = list(gt.cards._lines["bar"])
    assert kept and kept[-1]["text"] == host.bar.lines[-1]
    assert kept[-1]["game"]["pid"] == 4242 and kept[-1]["game"]["exe"] == "sakura.exe" and kept[-1]["at"] > 0
    found = gt.cards.lines_for({"player": "bar", "text": host.bar.lines[-1]})
    assert found["found"] and found["title"] and not found["sound"]  # (no Windows here to give the sound)
    assert ask(gt, "detach") == {"ok": True}
    wait_for(lambda: gt.cards.status()["following"]["bar"] == 0, timeout=5)
    assert gt.cards.sound.status()["holders"] == {}
