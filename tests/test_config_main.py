"""Settings carried over from 0.4.0, and the choice of windows in the command line."""

from __future__ import annotations

import json
from pathlib import Path

import fakes  # noqa: F401  (puts the app on the path)

from sluka_desktop import __main__ as main_module
from sluka_desktop import config as config_module
from sluka_desktop import winshell
from sluka_desktop.config import Config

OLD_040 = """# Sluka Desktop settings.  Lines starting with # are comments.
[network]
mode = direct
[links]
external = open
[browser]
path = C:\\Users\\FNAFYTB\\AppData\\Local\\Programs\\Opera GX\\opera.exe
port = 47822
web_security = off
pickers = no
hidden_worker = yes
args =
[window]
width = 1280
height = 860
[mpv]
enabled = no
attach = yes
[anki]
enabled = no
"""


def windows(monkeypatch):
    monkeypatch.setattr(config_module, "WINDOWS", True)


def test_a_config_of_040_is_read_and_brought_up_to_date(tmp_path, monkeypatch):
    windows(monkeypatch)
    (tmp_path / "config.ini").write_text(OLD_040, encoding="utf-8")
    config = Config(root=tmp_path, data=tmp_path / "data")
    assert config.shell == "webview2" and config.shell_auto
    assert config.port == 47822 and config.browser_port == 47822
    assert config.web_security is False and config.pickers is False
    assert config.webview_dir == (tmp_path / "data" / "webview2").resolve()
    assert config.devtools is False
    assert config.bring_up_to_date()
    text = (tmp_path / "config.ini").read_text(encoding="utf-8")
    assert "\n[app]\n" in text and "shell = auto" in text and "[webview2]" in text
    assert "\n[bar]\n" in text and "button = bottom-left" in text and text.count("[games]") == 1
    assert text.startswith(OLD_040.rstrip("\n"))  # nothing of the user's changed
    assert not config.bring_up_to_date()  # once
    again = Config(root=tmp_path, data=tmp_path / "data")
    assert again.port == 47822 and again.shell == "webview2" and again.shell_auto


def test_the_new_defaults(tmp_path, monkeypatch):
    windows(monkeypatch)
    config = Config(root=tmp_path, data=tmp_path / "data")
    assert config.write_default_config()
    config = Config(root=tmp_path, data=tmp_path / "data")
    assert config.port == 47821 and config.shell == "webview2" and config.shell_auto
    assert config.network_mode == "direct" and config.external_links == "open"
    assert not config.bring_up_to_date()  # a config.ini of 0.5.0 has its [app] already


def test_a_config_of_051_gets_the_floating_subtitles(tmp_path, monkeypatch):
    windows(monkeypatch)
    (tmp_path / "config.ini").write_text("[app]\nshell = auto\nport = 47821\n[mpv]\nenabled = yes\n", encoding="utf-8")
    config = Config(root=tmp_path, data=tmp_path / "data")
    assert config.bar_enabled and config.bar_button == "bottom-left" and config.games_enabled
    assert config.bring_up_to_date()
    text = (tmp_path / "config.ini").read_text(encoding="utf-8")
    assert text.startswith("[app]\nshell = auto\nport = 47821\n[mpv]\nenabled = yes\n") and text.count("[bar]") == 1
    assert text.count("[app]") == 1 and not config.bring_up_to_date()
    (tmp_path / "config.ini").write_text("[bar]\nenabled = no\nbutton = bottom-left\n", encoding="utf-8")
    config = Config(root=tmp_path, data=tmp_path / "data")
    assert not config.bar_enabled and config.bar_button == "bottom-left"
    (tmp_path / "config.ini").write_text("[bar]\nbutton = somewhere\n", encoding="utf-8")
    assert Config(root=tmp_path, data=tmp_path / "data").bar_button == "bottom-left"


def test_a_config_of_060_gets_its_button_at_the_bottom_and_the_game_text(tmp_path, monkeypatch):
    windows(monkeypatch)
    written = (Path(__file__).parent / "data" / "config-060.ini").read_text(encoding="utf-8")
    assert "button = top-right" in written and "[games]" not in written
    (tmp_path / "config.ini").write_text(written, encoding="utf-8")
    config = Config(root=tmp_path, data=tmp_path / "data")
    assert config.bar_button == "top-right"  # as it was written, until brought up to date
    assert config.bring_up_to_date()
    text = (tmp_path / "config.ini").read_text(encoding="utf-8")
    assert "button = top-right" not in text and text.count("button = bottom-left") == 1
    assert text.count("[games]") == 1 and text.count("[bar]") == 1 and "engine =" in text and "hooker" not in text
    assert not config.bring_up_to_date()
    again = Config(root=tmp_path, data=tmp_path / "data")
    assert again.bar_button == "bottom-left" and again.games_enabled and again.engine_dir == (tmp_path / "engine").resolve()
    # A place chosen by hand stays where it was put.
    (tmp_path / "config.ini").write_text(written.replace("bottom-right, bottom-left, or none.\nbutton = top-right",
                                                         "bottom-right, bottom-left, or none.\nbutton = top-left"), encoding="utf-8")
    config = Config(root=tmp_path, data=tmp_path / "data")
    assert config.bring_up_to_date()
    text = (tmp_path / "config.ini").read_text(encoding="utf-8")
    assert "button = top-left" in text and "[games]" in text
    assert Config(root=tmp_path, data=tmp_path / "data").bar_button == "top-left"
    # A game text switched off, and an engine folder of one's own (by its full path, or the app folder's).
    (tmp_path / "config.ini").write_text(f"[games]\nenabled = no\nengine = \"{tmp_path / 'other'}\"\n", encoding="utf-8")
    config = Config(root=tmp_path, data=tmp_path / "data")
    assert not config.games_enabled and config.engine_dir == (tmp_path / "other").resolve()
    (tmp_path / "config.ini").write_text("[games]\nengine = mine\n", encoding="utf-8")
    assert Config(root=tmp_path, data=tmp_path / "data").engine_dir == (tmp_path / "mine").resolve()
    (tmp_path / "config.ini").write_text("[bar]\nenabled = no\n", encoding="utf-8")
    assert not Config(root=tmp_path, data=tmp_path / "data").games_enabled  # no game text without the bar


def test_a_config_of_070_has_its_fetched_hooker_replaced_by_the_engine(tmp_path, monkeypatch):
    windows(monkeypatch)
    written = (Path(__file__).parent / "data" / "config-070.ini").read_text(encoding="utf-8")
    assert "hooker =" in written and "fetches into data\\tools\\LunaHook" in written
    (tmp_path / "config.ini").write_text(written, encoding="utf-8")
    config = Config(root=tmp_path, data=tmp_path / "data")
    assert config.bring_up_to_date()
    text = (tmp_path / "config.ini").read_text(encoding="utf-8")
    # Just as 0.8.0 writes it from scratch.
    assert text == config_module.DEFAULT_CONFIG_WINDOWS and "Sluka's own engine" in text and "fetches" not in text
    assert not config.bring_up_to_date()
    # A folder written there by hand stays as it is (read no more); the lines about the game text are 0.8.0's.
    (tmp_path / "config.ini").write_text(written.replace("hooker =\n", "hooker = C:\\Tools\\Textractor\n"), encoding="utf-8")
    assert Config(root=tmp_path, data=tmp_path / "data").bring_up_to_date()
    text = (tmp_path / "config.ini").read_text(encoding="utf-8")
    assert "hooker = C:\\Tools\\Textractor" in text and "Sluka's own engine" in text and "engine =" not in text
    again = Config(root=tmp_path, data=tmp_path / "data")
    assert again.games_enabled and again.engine_dir == (tmp_path / "engine").resolve()


def test_app_port_wins_over_browser_port(tmp_path, monkeypatch):
    windows(monkeypatch)
    (tmp_path / "config.ini").write_text("[app]\nport = 47830\nshell = browser\n[browser]\nport = 47822\n", encoding="utf-8")
    config = Config(root=tmp_path, data=tmp_path / "data")
    assert config.port == 47830 and config.shell == "browser" and not config.shell_auto
    (tmp_path / "config.ini").write_text("[app]\nshell = webview\n", encoding="utf-8")
    config = Config(root=tmp_path, data=tmp_path / "data")
    assert config.shell == "webview2" and not config.shell_auto


def test_engine_switches_from_a_real_config(tmp_path, monkeypatch):
    windows(monkeypatch)
    (tmp_path / "config.ini").write_text("[network]\nmode = tor\nsocks = 127.0.0.1:9150\n[webview2]\nargs = --lang=ro --x\n", encoding="utf-8")
    config = Config(root=tmp_path, data=tmp_path / "data")
    switches = winshell.wv2.engine_arguments(config)
    assert "--proxy-server=socks5://127.0.0.1:9150" in switches and switches[-2:] == ["--lang=ro", "--x"]
    assert "--disable-web-security" in switches


def extension(root: Path) -> Path:
    ext = root / "extension"
    ext.mkdir(parents=True)
    (ext / "manifest.json").write_text(json.dumps({"manifest_version": 3, "name": "Sluka", "version": "0.7.4"}))
    return ext


def test_main_falls_back_to_a_browser_only_where_it_chose(tmp_path, monkeypatch):
    windows(monkeypatch)
    extension(tmp_path)
    (tmp_path / "config.ini").write_text("[mpv]\nenabled = no\n[anki]\nenabled = no\n", encoding="utf-8")
    ran = []

    def no_webview(config, page=""):
        ran.append("webview2")
        raise winshell.Unavailable("Windows' own web view was not found.")

    monkeypatch.setattr(winshell, "run_app", no_webview)
    import sluka_desktop.browsershell as browsershell

    monkeypatch.setattr(browsershell, "run_app", lambda config, page="": ran.append("browser") or 0)
    monkeypatch.setattr(browsershell, "find_browser", lambda config: ("Opera", "opera.exe"))
    said = []
    monkeypatch.setattr(main_module, "problem", lambda text: said.append(text))
    assert main_module._main(["--root", str(tmp_path), "--foreground"]) == 0
    assert ran == ["webview2", "browser"]

    # Asked for by name: no browser instead, but the reason, and what to do.
    ran.clear()
    assert "[app]" in (tmp_path / "config.ini").read_text(encoding="utf-8")  # put there by the first start
    assert Config(root=tmp_path).set_option("app", "shell", "webview2")
    assert main_module._main(["--root", str(tmp_path), "--foreground"]) == 3
    assert ran == ["webview2"]
    assert "WebView2" in said[-1] and "shell = browser" in said[-1]


def test_can_show_windows(tmp_path, monkeypatch):
    windows(monkeypatch)
    import sluka_desktop.browsershell as browsershell
    import sluka_desktop.webview2 as wv2

    config = Config(root=tmp_path, data=tmp_path / "data")
    monkeypatch.setattr(wv2, "find_runtime", lambda override="": None)
    monkeypatch.setattr(browsershell, "find_browser", lambda config: None)
    assert not main_module.can_show_windows(config)
    monkeypatch.setattr(browsershell, "find_browser", lambda config: ("Opera", "opera.exe"))
    assert main_module.can_show_windows(config)
    monkeypatch.setattr(wv2, "find_runtime", lambda override="": fakes.runtime())
    monkeypatch.setattr(browsershell, "find_browser", lambda config: None)
    assert main_module.can_show_windows(config)
