"""Fixtures shared by the tests: Sluka's engine with stand-ins for LunaHost64.dll and LunaSubprocess (lunafake.py), and
its screen reader with stand-ins for LunaTranslator's OCR libraries, Google and a screen (ocrfake.py)."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

import lunafake
import ocrfake

BOX = (100, 400, 600, 110)          # the game's text box on the screen
CLIENT = (50, 50, 700, 500)         # the game window's inside, on the screen
IN_WINDOW = [50, 350, 600, 110]     # the box, in the window


@pytest.fixture(scope="session")
def fake_library(tmp_path_factory):
    return lunafake.build_library(tmp_path_factory.mktemp("fakehost") / "fake_lunahost.so")


@pytest.fixture
def luna(tmp_path, monkeypatch, fake_library):
    """The pretend game's folder, the engine's folder, and the arguments that make hookd.py use the stand-ins (for
    every engine the app starts, too)."""
    from sluka_desktop import texthook

    folder = tmp_path / "luna"
    folder.mkdir()
    monkeypatch.setenv("FAKE_LUNA_DIR", str(folder))
    engine = lunafake.make_engine(tmp_path / "engine")
    args = lunafake.engine_args(fake_library)
    monkeypatch.setattr(texthook.EngineProcess, "extra_args", args)
    return type("Luna", (), {"folder": folder, "engine": engine, "args": args})


@pytest.fixture(scope="session")
def ocr_libs(tmp_path_factory):
    return ocrfake.build(tmp_path_factory.mktemp("fakeocr"))


@pytest.fixture
def ocr(tmp_path, monkeypatch, ocr_libs):
    """A pretend screen with a game's window on it, the engine folder's OCR files, a stand-in for Google, and the
    arguments that make ocrd.py use them all (for every screen reader the app starts, too)."""
    from sluka_desktop import ocrtext

    logs = tmp_path / "said"
    logs.mkdir()
    monkeypatch.setenv("FAKE_OCR_DIR", str(logs))
    engine = ocrfake.make_ocr_engine(tmp_path / "engine")
    screen = ocrfake.Screen(tmp_path / "desktop", 800, 600)
    screen.window(42420, 4242, CLIENT, title="桜の詩")
    screen.put(foreground=4242)
    lens = ocrfake.Lens()
    args = ocrfake.ocrd_args(ocr_libs, tmp_path / "desktop", lens.url)
    monkeypatch.setattr(ocrtext.OcrProcess, "extra_args", args)
    yield SimpleNamespace(engine=engine, screen=screen, lens=lens, args=args, logs=logs, libs=ocr_libs, root=tmp_path)
    lens.close()


