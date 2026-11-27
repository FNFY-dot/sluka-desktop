"""The doctor's lines about Windows' web view."""

import fakes  # noqa: F401

from sluka_desktop import doctor
import sluka_desktop.webview2 as wv2
import sluka_desktop.browsershell as browsershell


class C:
    webview_runtime = ""
    shell_auto = True


def rows(monkeypatch, code, out, err=(), runtime=True, browser=None):
    monkeypatch.setattr(wv2, "find_runtime", lambda override="": fakes.runtime() if runtime else None)
    monkeypatch.setattr(browsershell, "find_browser", lambda config: browser)
    monkeypatch.setattr(doctor, "_try_webview", lambda: (code, out, list(err)))
    said = []
    doctor._webview_rows(C(), lambda state, what, how="": said.append((state, what, how)))
    return said


def test_works(monkeypatch):
    said = rows(monkeypatch, 0, ["ok: WebView2 Runtime 142 (C:\\fake)", "ok: a script in the page answered: Mozilla/5.0 Edg/142", "ok: Windows' web view works for the app"])
    assert said[0][0] == doctor.OK and "WebView2 Runtime 142.0.3595.80" in said[0][1]
    assert said[1] == (doctor.OK, "a page was opened in it, and a script in the page answered", "Mozilla/5.0 Edg/142")


def test_fails_at_a_step(monkeypatch):
    said = rows(monkeypatch, 4, ["ok: the engine started: WebView2 142", "failed: a web view could not be made (0x80004005, it failed)"])
    assert said[1][0] == doctor.BAD and "a web view could not be made" in said[1][1] and "webview-check" in said[1][2]


def test_crashes(monkeypatch):
    said = rows(monkeypatch, 3221225477, ["ok: the engine started: WebView2 142"], ["Windows fatal exception: access violation", "  File ..."])
    assert said[1][0] == doctor.BAD and "0xc0000005" in said[1][1] and "after: the engine started" in said[1][1]
    assert "access violation" in said[1][2]


def test_missing_with_and_without_a_browser(monkeypatch):
    said = rows(monkeypatch, 0, [], runtime=False, browser=("Opera", "opera.exe"))
    assert said == [(doctor.WARN, "Windows' own web view (the WebView2 Runtime) was not found", said[0][2])] and "Opera" in said[0][2]
    said = rows(monkeypatch, 0, [], runtime=False, browser=None)
    assert said[0][0] == doctor.BAD and "Evergreen Bootstrapper" in said[0][2]


# ---------------------------------------------------------------- whom the running app is talking to

import json  # noqa: E402
import threading  # noqa: E402
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer  # noqa: E402

from sluka_desktop import APP_NAME, __version__  # noqa: E402


class Live:
    browser_port = 0
    mpv_enabled = True
    anki_enabled = True


def running_app(answers):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            name = self.path.split("/__sluka__/api/", 1)[-1]
            body = json.dumps(answers.get(name, {})).encode()
            self.send_response(200 if name in answers else 404)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def live_rows(answers):
    server = running_app(answers)
    try:
        config = Live()
        config.browser_port = server.server_address[1]
        said = []
        doctor._live_rows(config, lambda state, what, how="": said.append((state, what, how)))
        return said
    finally:
        server.shutdown()


INFO = {"app": {"name": APP_NAME, "version": __version__}}


def test_not_running():
    config = Live()
    config.browser_port = 9  # nothing listens there
    said = []
    doctor._live_rows(config, lambda state, what, how="": said.append((state, what, how)))
    assert said[0][:2] == (doctor.OK, "the app is not running now")


def test_a_player_that_does_not_answer_and_an_anki_that_does():
    said = live_rows({
        "info": INFO,
        "mpv/status": {"names": ["18032", "20940"], "answered": ["20940"], "engine": True},
        "anki/status": {"ankis": 1, "about": [{"anki": "26.09.3", "addon": __version__}], "older": []},
    })
    texts = [what for _state, what, _how in said]
    assert (doctor.WARN, "mpv players connected to the app: 2; answering: 1") == said[0][:2]
    assert "open the video again" in said[0][2]
    assert any(state == doctor.OK and what == f"Anki talking to the app: 1 (Anki 26.09.3, add-on {__version__})" for state, what, _ in said), texts


def test_an_anki_with_the_old_add_on_and_a_silent_engine():
    said = live_rows({
        "info": INFO,
        "mpv/status": {"names": ["5"], "answered": ["5"], "engine": False},
        "anki/status": {"ankis": 0, "about": [], "older": ["17528"]},
    })
    assert said[0][:2] == (doctor.OK, "mpv players talking to the app: 1")
    assert said[1][0] == doctor.WARN and "hidden page is not asking" in said[1][1]
    assert said[2][0] == doctor.WARN and "older Sluka Desktop" in said[2][1] and "start it again" in said[2][2]
    assert len(said) == 3


def test_another_version_running():
    said = live_rows({"info": {"app": {"name": APP_NAME, "version": "0.4.0"}}, "mpv/status": {"names": []}, "anki/status": {"ankis": 0}})
    assert said[0][0] == doctor.WARN and "0.4.0" in said[0][1]


def test_the_floating_subtitles_of_the_running_app():
    rows = live_rows({"info": {**INFO, "bar": {"on": True, "engine": True, "page": True}},
                      "mpv/status": {"names": [], "answered": [], "engine": True}, "anki/status": {"ankis": 0, "older": []}})
    assert (doctor.OK, "the floating subtitles are on") == rows[-1][:2] and "bar-text" in rows[-1][2]
    rows = live_rows({"info": {**INFO, "bar": {"on": True, "engine": False, "page": True}}})
    assert rows[-1][0] == doctor.WARN and "without Sluka's engine" in rows[-1][1]
    rows = live_rows({"info": {**INFO, "bar": {"on": False}}})
    assert rows[-1][:2] == (doctor.OK, "the floating subtitles are off")
    # An app with no bar (another shell) says nothing of it.
    assert not [r for r in live_rows({"info": INFO}) if "floating" in r[1]]


def test_the_game_text_of_the_running_app():
    rows = live_rows({"info": {**INFO, "bar": {"on": False}}})
    assert "at the bottom left" in rows[-1][2]
    rows = live_rows({"info": {**INFO, "games": {"mode": "game", "game": {"exe": "sakura.exe", "bits": 32, "state": "attached"},
                                                  "threads": 5, "selected": 0}}})
    assert rows[-1][0] == doctor.OK and "sakura.exe (32-bit) is attached" in rows[-1][1] and "pick the thread" in rows[-1][2]
    rows = live_rows({"info": {**INFO, "games": {"mode": "game", "game": {"exe": "sakura.exe", "bits": 32, "state": "failed"},
                                                  "threads": 0, "selected": 0}}})
    assert rows[-1][0] == doctor.WARN
    rows = live_rows({"info": {**INFO, "games": {"mode": "clipboard", "game": None}}})
    assert rows[-1][1] == "game text comes from the clipboard"
    assert not [r for r in live_rows({"info": {**INFO, "games": {"mode": "off"}}}) if "game text" in r[1]]


def test_the_engine_for_game_text(tmp_path, luna, monkeypatch):
    """The doctor looks at Sluka's engine on disk, and starts it once (here with a stand-in LunaHost64.dll)."""
    from sluka_desktop import texthook

    class G:
        games_enabled = True
        engine_dir = tmp_path / "nowhere"
        root = tmp_path
        log_dir = tmp_path / "logs"

    def rows():
        said = []
        doctor._games_rows(G(), lambda state, what, how="": said.append((state, what, how)))
        return said

    said = rows()
    assert said[0][0] == doctor.WARN and "cannot be used" in said[0][1] and "folder is missing" in said[0][2]
    G.engine_dir = luna.engine
    said = rows()
    assert said[0][0] == doctor.OK and "Sluka's engine (LunaHook from LunaTranslator 12.1.3.12) starts (Python" in said[0][1]
    assert "64-bit" in said[0][1] and "hook-check --list" in said[0][2]
    assert (G.log_dir / "hookd-doctor.log").is_file()
    # A host that cannot be loaded: said, with where its notes are.
    monkeypatch.setattr(texthook.EngineProcess, "extra_args", ["--library", str(tmp_path / "nothing.so")])
    said = rows()
    assert said[0][0] == doctor.WARN and "does not start" in said[0][1] and "nothing.so" in said[0][1]
    assert "hookd-doctor.log" in said[0][2]


def test_the_screen_of_the_running_app():
    rows = live_rows({"info": {**INFO, "games": {"mode": "screen", "screen": {"target": {"title": "桜の詩", "exe": "sakura.exe",
                                                                                         "state": "watching", "engine": "builtin"}}}}})
    assert rows[-1][:2] == (doctor.OK, "game text is read off the screen: a box of 桜の詩 is read, by builtin")
    rows = live_rows({"info": {**INFO, "games": {"mode": "screen", "screen": {"target": None}}}})
    assert rows[-1][0] == doctor.OK and "no box is chosen" in rows[-1][1] and "Select the text box" in rows[-1][2]
    rows = live_rows({"info": {**INFO, "games": {"mode": "screen", "screen": {"error": "Sluka's engine folder is missing"}}}})
    assert rows[-1][0] == doctor.WARN and "ocrd.log" in rows[-1][2]


def test_the_readers_of_the_screen(tmp_path, ocr, monkeypatch):
    """The doctor starts Sluka's screen reader once, and says which readers can be used here (stand-ins here)."""

    class G:
        engine_dir = ocr.engine
        root = tmp_path
        data_dir = tmp_path / "data"
        log_dir = tmp_path / "data" / "logs"
        network_mode = "direct"

    def rows():
        said = []
        doctor._screen_rows(G(), lambda state, what, how="": said.append((state, what, how)))
        return said

    said = rows()
    assert said == [(doctor.OK, "screen text: the screen can be read here by Sluka's own OCR, "
                                "Windows' OCR, and Google Lens (online)", f"try one on a box of the screen with  {doctor.SLUKA} ocr-check --read")]
    assert (G.log_dir / "ocrd-doctor.log").is_file()
    # Sluka's own not starting (an old C++ runtime), offline: said why.
    monkeypatch.setenv("FAKE_ORT_FAIL", "1")
    G.network_mode = "offline"
    said = rows()
    assert said[0][0] == doctor.OK and said[0][1] == "screen text: the screen can be read here by Windows' OCR"
    assert "Sluka's own OCR: its ONNX Runtime" in said[0][2] and "Snipping Tool" not in said[0][2]
    # None at all: a warning.
    monkeypatch.setenv("FAKE_OCR_LANGS", "en-US")
    said = rows()
    assert said[0][0] == doctor.WARN and "none of the offline readers" in said[0][1] and "no OCR for ja" in said[0][2]
    # Files an antivirus took: said which.
    (ocr.engine / "ocr" / "onnxruntime.dll").unlink()
    said = rows()
    assert said[0][0] == doctor.WARN and "onnxruntime.dll" in said[0][1] and "unpack Sluka Desktop's zip again" in said[0][2]
