"""The Anki add-on in a stand-in Anki, met by the app's own Link: what happens when the app connects, and on which thread.

The stand-in's Qt refuses to make a web profile anywhere but on Anki's own
thread, as the real one cannot (it brought Anki 26 on Windows down).  The
add-on's port note is used as on Windows (SLUKA_ANKI_TRANSPORT=tcp).
"""

from __future__ import annotations

import importlib.util
import json
import logging
import os
import shutil
import socket
import sys
import threading
import time
import types
from pathlib import Path

import pytest

from fakes import APP
from sluka_desktop import ankibridge

ADDON = Path(APP).parent / "anki" / "sluka_desktop"
#: The add-on as 0.4.0 and 0.5.0 had it, where it is at hand (not shipped with the tests).
OLD_ADDON = Path("/home/claude/untrusted/zip/sluka-desktop/anki/sluka_desktop")


class StandInAnki:
    def __init__(self, monkeypatch, tmp_path: Path, chromium: bool = True):
        self.main = threading.current_thread()
        self.off_thread: list[tuple[str, str]] = []
        self.tasks: list = []
        anki = self

        class Profile:
            @staticmethod
            def defaultProfile():
                if threading.current_thread() is not anki.main:
                    anki.off_thread.append(("QWebEngineProfile.defaultProfile", threading.current_thread().name))
                    raise RuntimeError("a web profile made off Anki's thread")   # the real one takes Anki down
                return Profile()

            def httpUserAgent(self):
                return "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) QtWebEngine/6.11.2 Chrome/140.0.7339.214 Safari/537.36"

        qt = types.ModuleType("aqt.qt")
        qt.qVersion = lambda: "6.11.2"
        qt.QWebEngineProfile = Profile
        if chromium:
            qt.qWebEngineChromiumVersion = lambda: "140.0.7339.214"

        class TaskMan:
            def run_on_main(self, fn):
                anki.tasks.append(fn)

        class AddonManager:
            exports = None

            def setWebExports(self, module, pattern):
                self.exports = pattern

            def addonFromModule(self, module):
                return "sluka_desktop"

            def getConfig(self, module):
                return {}

        self.mw = types.SimpleNamespace(taskman=TaskMan(), addonManager=AddonManager(), state="deckBrowser", reviewer=None)
        self.hooks = types.SimpleNamespace(webview_will_set_content=[], webview_did_receive_js_message=[],
                                           state_did_change=[], state_shortcuts_will_change=[])
        aqt = types.ModuleType("aqt")
        aqt.mw, aqt.gui_hooks, aqt.qt, aqt.appVersion = self.mw, self.hooks, qt, "26.09.3"
        anki_pkg = types.ModuleType("anki")
        buildinfo = types.ModuleType("anki.buildinfo")
        buildinfo.version = "26.09.3"
        anki_pkg.buildinfo = buildinfo
        for name, module in {"aqt": aqt, "aqt.qt": qt, "anki": anki_pkg, "anki.buildinfo": buildinfo}.items():
            monkeypatch.setitem(sys.modules, name, module)
        monkeypatch.delitem(sys.modules, "PyQt6.QtWebEngineCore", raising=False)
        monkeypatch.setenv("SLUKA_ANKI_TRANSPORT", "tcp")
        monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path / "run"))
        (tmp_path / "run").mkdir(mode=0o700)
        self.tmp = tmp_path
        self.module = None

    def load(self, source: Path, monkeypatch):
        """The add-on, imported as Anki imports it -- on Anki's own thread, where it starts."""
        target = self.tmp / "addons21" / "sluka_desktop"
        shutil.copytree(source, target)
        name = "sluka_desktop_addon_under_test"
        spec = importlib.util.spec_from_file_location(name, target / "__init__.py", submodule_search_locations=[str(target)])
        module = importlib.util.module_from_spec(spec)
        monkeypatch.setitem(sys.modules, name, module)
        spec.loader.exec_module(module)
        self.module = module
        return module

    def run_main(self):
        """What was handed to Anki's thread, done there."""
        while self.tasks:
            self.tasks.pop(0)()

    def port_note(self) -> Path:
        return self.tmp / "run" / "sluka-anki" / f"{os.getpid()}.port"

    def close(self):
        if self.module is not None and getattr(self.module, "pipe", None) is not None:
            self.module.pipe.close()


class Bridge:
    """What a Link reports to, in the app."""

    def __init__(self):
        self.heard: list[dict] = []
        self.gone_links = []

    def incoming(self, link, message):
        self.heard.append(message)

    def gone(self, link):
        self.gone_links.append(link)


def wait_for(test, seconds=5.0):
    end = time.time() + seconds
    while time.time() < end:
        if test():
            return True
        time.sleep(0.02)
    return False


def connect(anki: StandInAnki) -> tuple[Bridge, ankibridge.Link]:
    said = json.loads(anki.port_note().read_text(encoding="utf-8"))
    bridge = Bridge()
    link = ankibridge.Link(bridge, "under-test", str(anki.port_note()), int(said["port"]), str(said["word"]))
    link.send({"t": "hello", "v": ankibridge.PROTOCOL, "app": "test"})
    return bridge, link


@pytest.mark.parametrize("chromium", [True, False])
def test_the_add_on_answers_without_touching_qt_off_ankis_thread(monkeypatch, tmp_path, chromium):
    anki = StandInAnki(monkeypatch, tmp_path, chromium=chromium)
    try:
        addon = anki.load(ADDON, monkeypatch)
        note = json.loads(anki.port_note().read_text(encoding="utf-8"))
        assert note["addon"] == addon.VERSION and note["v"] == addon.PROTOCOL
        bridge, link = connect(anki)
        assert wait_for(lambda: any(m.get("t") == "hello" for m in bridge.heard)), bridge.heard
        hello = next(m for m in bridge.heard if m["t"] == "hello")
        assert hello["addon"] == addon.VERSION
        assert hello["anki"] == "26.09.3" and hello["qt"] == "6.11.2"
        assert hello["engine"] == ("Chromium 140.0.7339.214" if chromium else "")
        assert anki.off_thread == []
        # The page is told on Anki's own thread, which is where it is reached from.
        assert anki.tasks
        anki.run_main()
        link.close()
        assert wait_for(lambda: not addon.pipe.connected)
        assert anki.off_thread == []
    finally:
        anki.close()


@pytest.mark.skipif(not OLD_ADDON.is_dir(), reason="the add-on of 0.5.0 is not at hand")
def test_the_old_add_on_asked_qt_for_a_profile_off_ankis_thread(monkeypatch, tmp_path):
    """What brought Anki down: the add-on of 0.4.0 and 0.5.0, asked for its greeting, made Qt's default profile on its own thread."""
    anki = StandInAnki(monkeypatch, tmp_path)
    try:
        anki.load(OLD_ADDON, monkeypatch)
        bridge, link = connect(anki)
        assert wait_for(lambda: anki.off_thread)
        assert anki.off_thread[0][0] == "QWebEngineProfile.defaultProfile"
        assert anki.off_thread[0][1] != "MainThread"
        link.close()
    finally:
        anki.close()


def bridge_on(folder: Path) -> ankibridge.AnkiBridge:
    bridge = ankibridge.AnkiBridge(types.SimpleNamespace(), types.SimpleNamespace(started=time.time()))
    bridge.folder = folder
    bridge.places = lambda: [("", folder)]
    return bridge


class OldAddOn:
    """A listener as the add-on of 0.5.0 had it: it waits for the word, and once it has it, Anki is brought down."""

    def __init__(self):
        self.server = socket.socket()
        self.server.bind(("127.0.0.1", 0))
        self.server.listen(4)
        self.port = self.server.getsockname()[1]
        self.word = "0123456789abcdef"
        self.knocks = 0
        self.taken = False
        threading.Thread(target=self._serve, daemon=True).start()

    def _serve(self):
        while True:
            try:
                conn, _ = self.server.accept()
            except OSError:
                return
            self.knocks += 1
            conn.settimeout(2)
            try:
                if self.word.encode() in conn.recv(4096):
                    self.taken = True
            except OSError:
                pass
            conn.close()

    def close(self):
        # Shut down first: a listener another thread waits on in accept() goes on listening after a close alone (Linux).
        try:
            self.server.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        self.server.close()


def test_the_app_leaves_an_anki_with_the_old_add_on_alone(tmp_path, caplog):
    folder = tmp_path / "anki"
    folder.mkdir(mode=0o700)
    old = OldAddOn()
    try:
        note = folder / "1234.port"
        note.write_text(json.dumps({"port": old.port, "word": old.word}), encoding="utf-8")
        bridge = bridge_on(folder)
        with caplog.at_level(logging.INFO, logger="sluka.anki"):
            bridge._look()
            assert wait_for(lambda: old.knocks >= 1)
            bridge._failed.clear()
            bridge._look()
        assert wait_for(lambda: old.knocks >= 2)
        time.sleep(0.1)
        assert not old.taken, "the word was said to an add-on that falls over once it hears it"
        assert bridge.links == {}
        warnings = [r for r in caplog.records if "older Sluka Desktop" in r.getMessage()]
        assert len(warnings) == 1
        assert bridge.status()["older"] == ["1234"]
        assert note.exists()
        # Gone: its note goes too.
        old.close()
        bridge._failed.clear()
        bridge._look()
        assert not note.exists()
        assert bridge.status()["older"] == []
    finally:
        old.close()


def test_the_app_connects_to_the_new_add_on(monkeypatch, tmp_path):
    anki = StandInAnki(monkeypatch, tmp_path)
    try:
        anki.load(ADDON, monkeypatch)
        bridge = bridge_on(anki.port_note().parent)
        bridge._look()
        assert list(bridge.links) == [str(os.getpid())]
        link = bridge.links[str(os.getpid())]
        assert wait_for(lambda: link.about.get("addon") == anki.module.VERSION)
        assert anki.off_thread == []
        link.close()
    finally:
        anki.close()
