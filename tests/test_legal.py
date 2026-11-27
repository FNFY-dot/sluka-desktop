"""What Sluka Desktop does to keep to the law, checked: its licence agreement and third-party notices (and that every
file they name is there), the licence each of its own files says it is under, the line between Sluka's own program and
the free software it runs (programs apart, never loaded into it), the Snipping Tool's OCR left out (and the copies that
earlier versions made taken away), Google Lens asked about before it first reads, ONNX Runtime's trace events turned
off, and the Anki add-on's own licence going into Anki with it."""

from __future__ import annotations

import ast
import json
import os
import re
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

import fakes  # (puts the app on the path)
from sluka_desktop import gametext, lensask, ocrd, ocrtext
from test_ocr import app, keys  # noqa: F401  (fixtures)

ROOT = Path(fakes.APP).parent
TOOLS = Path(__file__).resolve().parent.parent / "tools"


def text(path: Path) -> str:
    return path.read_bytes().decode("utf-8").replace("\r\n", "\n")


# ---------------------------------------------------------------- the licence files


def test_the_licence_agreement():
    agreement = text(ROOT / "LICENSE.txt")
    assert agreement.startswith("SLUKA DESKTOP: LICENCE AGREEMENT")
    assert "https://sluka.app/terms" in agreement and "Copyright (c) 2026 Sluka" in agreement
    flat = " ".join(agreement.split())
    # Where Sluka is made, and the law -- as the Sluka extension's site says it.
    assert "made in Gothenburg, Sweden" in flat and "Swedish law applies" in flat
    assert "mandatory rules of the country where you live" in flat and "Allmänna reklamationsnämnden (ARN)" in flat
    # Credit where it is due; free software needing no acceptance (the GPL, version 3, section 9), and not limited.
    for name in ("HIllya51", "LunaTranslator", "Textractor", "PaddleOCR", "OpenCV", "ONNX Runtime", "Go"):
        assert name in flat, name
    assert "you need not accept this agreement to receive, run, copy, change or share any of these" in flat
    assert "nothing in this agreement, or in Sluka's terms, limits what those licences let you do" in flat
    # Microsoft's terms for its runtime files, part of the agreement; and the rest in NOTICES.txt, beside it.
    assert "on Microsoft's terms instead, and those terms are part of this agreement" in flat
    assert "NOTICES.txt, beside this file, says the rest" in flat and (ROOT / "NOTICES.txt").is_file()
    # Setup shows it as it is: no line wider than its page.
    assert max(len(line) for line in agreement.splitlines()) <= 72


def test_the_notices():
    notices = text(ROOT / "NOTICES.txt")
    assert notices.startswith("SLUKA DESKTOP: NOTICES")
    # The free parts named, with their licence, and needing no acceptance (the GPL, version 3, section 9).
    for name in ("app\\sluka_desktop\\hookd.py", "app\\sluka_desktop\\ocrd.py", "mpv\\sluka.lua", "anki\\sluka_desktop\\"):
        assert name in notices, name
    flat = " ".join(notices.split())
    assert "You need not accept Sluka Desktop's licence agreement to receive, run, copy, change or share these parts" in flat
    # What Microsoft's terms for its C++ runtime files ask the agreement to say, and what Google Lens and games ask.
    for words in ("As part of Sluka Desktop's licence agreement", "licensed, not sold",
                  "reverse engineer, decompile or disassemble", "only with Sluka Desktop", "Google's terms of service",
                  "anti-cheat", "Sluka asks you before Google Lens first reads"):
        assert words in flat, words
    # Setup shows it, after the agreement: no line wider than its page.
    assert max(len(line) for line in notices.splitlines()) <= 72
    # The old name is gone (Setup takes the old file away: it is among the files it manages).
    assert not (ROOT / "THIRD-PARTY-NOTICES.txt").exists()
    for path in [ROOT / "README.txt", ROOT / "engine" / "ENGINE.txt", ROOT / "engine" / "ocr" / "OCR.txt"] + sorted(
            (ROOT / "app" / "sluka_desktop").glob("*.py")):
        assert "THIRD-PARTY-NOTICES" not in text(path), path


def test_the_notices_name_only_what_is_there():
    notices = text(ROOT / "NOTICES.txt")
    flat = re.sub(r"\n\s+", " ", notices)
    named = set(re.findall(r"((?:engine\\)?LICENSES\\[A-Za-z0-9_.\-]+[A-Za-z0-9])", flat))
    assert len(named) >= 20
    for ref in named:
        assert (ROOT / ref.replace("\\", "/")).is_file(), ref
    # Every program file of the engine's is accounted for, each by name.
    for path in list((ROOT / "engine").glob("*.dll")) + list((ROOT / "engine").glob("*.exe")) + list(
            (ROOT / "engine" / "ocr").glob("*.dll")):
        assert path.name in notices, path.name
    # What LunaTranslator's own collection lacks, which is in these files, is in Sluka's.
    for name in ("protobuf.txt", "MeCab.txt", "WebView2-SDK.txt", "uchardet.txt", "zlib.txt", "ONNX-Runtime-notices.txt",
                 "Go.txt", "GPL-3.0.txt", "GPL-2.0.txt", "LGPL-2.1.txt"):
        assert (ROOT / "LICENSES" / name).stat().st_size > 1000, name
    # The GPL's text is the GPL's, the very one LunaTranslator ships.
    assert text(ROOT / "LICENSES" / "GPL-3.0.txt").strip() == text(ROOT / "engine" / "LICENSES" / "LICENSE.LunaTranslator").strip()
    # LunaTranslator's uchardet file is a web page saved by mistake: said, and the real licence given.
    assert "<!doctype html>" in text(ROOT / "engine" / "LICENSES" / "LICENSE.uchardet.uchardet")[:200].lower()
    assert "LICENSE.uchardet.uchardet, is a web page" in flat
    assert "MOZILLA PUBLIC LICENSE" in text(ROOT / "LICENSES" / "uchardet.txt")
    # The source of the GPL's parts, and where it is.
    assert (ROOT / "engine" / "source" / "LunaTranslator-12.1.3.12.zip").is_file()
    assert "engine\\source\\LunaTranslator-12.1.3.12.zip" in notices


SPDX = re.compile(r"SPDX-License-Identifier: (\S+)")


def own_files():
    app = ROOT / "app"
    files = sorted((app / "sluka_desktop").glob("*.py")) + sorted(
        p for p in (app / "web").iterdir() if p.suffix in (".js", ".html", ".css"))
    files += [ROOT / "mpv" / "sluka.lua", ROOT / "anki" / "sluka_desktop" / "__init__.py", ROOT / "Sluka.cmd"]
    if (TOOLS / "installer").is_dir():
        files += sorted((TOOLS / "installer").glob("*.go")) + [TOOLS / "build_installer.py"]
    return files


def test_each_of_slukas_own_files_says_its_licence():
    free = {ROOT / "app" / "sluka_desktop" / "hookd.py": "GPL-3.0-only", ROOT / "app" / "sluka_desktop" / "ocrd.py": "GPL-3.0-only",
            ROOT / "mpv" / "sluka.lua": "GPL-3.0-or-later", ROOT / "anki" / "sluka_desktop" / "__init__.py": "GPL-3.0-or-later"}
    for path in own_files():
        head = text(path)[:1500]
        found = SPDX.search(head)
        assert found, path
        assert found.group(1) == free.get(path, "LicenseRef-Sluka"), path
        assert "Copyright (c) 2026 Sluka" in head, path
        if path in free:
            assert "WITHOUT ANY WARRANTY" in head and "<https://www.gnu.org/licenses/>" in head, path
    # The add-on's own licence file, which goes into Anki with it.
    addon = text(ROOT / "anki" / "sluka_desktop" / "LICENSE.txt")
    assert "either version 3 of the License, or (at your option) any later version" in " ".join(addon.split())
    assert "shim.js and anki-page.js" in addon


def imports_of(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found |= {a.name for a in node.names}
        elif isinstance(node, ast.ImportFrom):
            found.add("." * node.level + (node.module or ""))
    return found


def test_the_free_programs_stand_apart_from_slukas_own():
    """hookd.py and ocrd.py, which load LunaTranslator's libraries, are programs of their own: they import nothing of the
    app's, and nothing of the app's imports them or loads those libraries (they are run, and spoken with in lines of
    JSON) -- so Sluka's own program is never one with the GPL's."""
    package = ROOT / "app" / "sluka_desktop"
    for name in ("hookd.py", "ocrd.py"):
        found = imports_of(package / name)
        assert not any(m.startswith(".") or m.startswith("sluka_desktop") for m in found), (name, found)
    luna = ("LunaHost64", "LunaHook32", "LunaHook64", "CVUtils", "NativeUtils", "onnxruntime", "LunaSubprocess")
    for path in package.glob("*.py"):
        if path.name in ("hookd.py", "ocrd.py"):
            continue
        found = imports_of(path)
        assert not any(m.endswith(("hookd", "ocrd")) for m in found), path
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and getattr(node.func, "attr", getattr(node.func, "id", "")) in ("CDLL", "WinDLL", "LoadLibrary"):
                for arg in node.args:
                    if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                        assert not any(n.lower() in arg.value.lower() for n in luna), (path, arg.value)


# ---------------------------------------------------------------- the Snipping Tool's OCR


def test_the_snipping_tools_ocr_is_left_out_and_old_copies_go(tmp_path, monkeypatch):
    assert "snipping" not in ocrd.READERS and "snipping" not in ocrtext.READERS
    assert not hasattr(ocrd, "SnippingReader") and "GetPackagePathByPackageFamily" not in text(Path(ocrd.__file__))
    # What Sluka Desktop 0.12.3 copied out of the Snipping Tool: taken away, and nothing else.
    data, engine = tmp_path / "data", tmp_path / "engine"
    copies = data / "ocr" / "SnippingTool"
    copies.mkdir(parents=True)
    for name in ocrtext.SNIPPING_FILES:
        (copies / name).write_bytes(b"Microsoft's")
    (data / "ocr" / "keep.txt").write_text("not the Snipping Tool's")
    other = engine / "ocr" / "cache" / "SnippingTool"
    other.mkdir(parents=True)
    (other / "oneocr.dll").write_bytes(b"Microsoft's")
    (other / "mine.txt").write_text("someone's own")
    monkeypatch.setattr(ocrtext, "_forgotten", False)
    ocrtext.forget_snipping_tool(data, engine)
    assert not copies.exists() and (data / "ocr" / "keep.txt").is_file()
    assert sorted(p.name for p in other.iterdir()) == ["mine.txt"]  # (only its three files; the folder kept, not empty)
    # Once a run of the app.
    copies.mkdir()
    (copies / "oneocr.dll").write_bytes(b"x")
    ocrtext.forget_snipping_tool(data, engine)
    assert (copies / "oneocr.dll").is_file()


def test_a_choice_of_the_snipping_tool_becomes_an_offline_reader():
    clean = gametext.GameText._clean_settings
    assert clean({"ocr_engine": "snipping", "vision_engine": "snipping"}) == {"ocr_engine": "auto", "vision_engine": "builtin"}
    assert clean({"vision_engine": "lens", "lens_ok": True}) == {"vision_engine": "lens", "lens_ok": True}
    assert gametext.DEFAULTS["lens_ok"] is False


# ---------------------------------------------------------------- Google Lens, asked about once


class Games:
    """Enough of gametext.GameText for the question: its settings, update and note."""

    def __init__(self, **settings):
        self.settings = {"ocr_engine": "auto", "vision_engine": "lens", "lens_ok": False, **settings}
        self.updates, self.notes = [], []
        self.updated = threading.Event()

    def update(self, changes):
        self.settings.update(changes)
        self.updates.append(dict(changes))
        self.updated.set()
        return {"ok": True}

    def note(self, text, level="info"):
        self.notes.append(text)


def test_google_lens_reads_only_after_a_yes():
    asked, answer = [], threading.Event()

    def ask(key):
        asked.append(key)
        answer.wait(5)
        return True

    games = Games()
    question = lensask.LensQuestion(games, ask)
    # Until the answer: the offline reader, and the question put once, however often the reader is wanted.
    assert question.reader("vision_engine") == "builtin"
    assert question.reader("vision_engine") == "builtin"
    time.sleep(0.2)
    assert asked == ["vision_engine"] and games.updates == []
    answer.set()
    assert games.updated.wait(5)
    assert games.updates == [{"lens_ok": True}] and question.allowed()
    assert question.reader("vision_engine") == "lens" and asked == ["vision_engine"]
    # Taken back: asked again the next time.
    question.forget()
    assert games.settings["lens_ok"] is False


def test_a_no_to_google_lens_leaves_an_offline_reader_chosen():
    games = Games(ocr_engine="lens")
    question = lensask.LensQuestion(games, lambda key: False)
    assert question.reader("ocr_engine") == "auto"
    assert games.updated.wait(5)
    assert games.updates == [{"ocr_engine": "auto"}] and not question.allowed()
    assert "Google Lens is not used" in games.notes[0]
    # A reader that is not Google Lens is never asked about.
    games = Games(vision_engine="builtin")
    question = lensask.LensQuestion(games, lambda key: pytest.fail("asked"))
    assert question.reader("vision_engine") == "builtin"


def test_the_question_says_what_goes_where():
    words = lensask.question("vision_engine")
    for part in ("sent to Google", "terms of service", "privacy policy", "not a service that Google offers to other programs",
                 "Yes: Google Lens reads", "No: Sluka's own OCR reads instead"):
        assert part in words, part
    assert "the best offline reader" in lensask.question("ocr_engine")
    assert lensask.ask_windows("vision_engine") is False or os.name == "nt"  # (no message box but Windows': a no)


def test_sluka_vision_sends_nothing_to_google_before_the_yes(app, keys):  # noqa: F811
    from conftest import CLIENT
    from test_gametext import ask, wait_for
    from test_vision import SHOWN, FakeShell

    asked, answer = [], threading.Event()

    def question(key):
        asked.append(key)
        answer.wait(20)
        return True

    ocr = app.ocr
    gt = app.build(lens_ok=False, lens_ask=question)
    gt.vision.shell = FakeShell()
    assert ask(gt, "mode", {"mode": "vision"}) == {"ok": True, "mode": "vision"}
    wait_for(lambda: asked == ["vision_engine"])
    ocr.screen.text(CLIENT, SHOWN)
    keys.press("Alt+S")
    wait_for(lambda: ask(gt, "state")["vision"]["last"]["lines"] > 0, timeout=15)
    assert ask(gt, "state")["vision"]["last"]["engine"] == "builtin" and ocr.lens.requests == []
    # The yes: Google Lens reads from then on, and the yes is kept.
    answer.set()
    wait_for(lambda: gt.settings["lens_ok"] is True)
    keys.press("Alt+S")
    wait_for(lambda: len(ocr.lens.requests) >= 1, timeout=15)
    wait_for(lambda: (app.config.data_dir / "gametext.json").is_file()
             and json.loads((app.config.data_dir / "gametext.json").read_text(encoding="utf-8"))["settings"].get("lens_ok") is True)


# ---------------------------------------------------------------- ONNX Runtime's trace events


def test_onnx_runtimes_trace_events_are_turned_off_through_its_own_c_api():
    import ctypes
    import glob

    found = sorted(glob.glob("/usr/local/lib/python3*/dist-packages/onnxruntime/capi/libonnxruntime.so*")
                   + glob.glob("/usr/lib/python3*/site-packages/onnxruntime/capi/libonnxruntime.so*"))
    if not found:
        pytest.skip("no ONNX Runtime library here")
    said = ocrd.trace_events_off(ctypes.CDLL(found[0]))
    assert re.fullmatch(r"ONNX Runtime 1\.\d+\.\d+: its trace events are off", said), said
    # On Windows it is done once ONNX Runtime is loaded, before the OCR starts; elsewhere not at all.
    source = text(Path(ocrd.__file__))
    assert len(re.findall(r"^\s+quiet_onnxruntime\(\)$", source, re.M)) == 2  # (BuiltinReader.check and .prepare)


# ---------------------------------------------------------------- the add-on's licence, in Anki


def test_the_addons_licence_goes_into_anki_with_it(tmp_path):
    from sluka_desktop import install

    config = SimpleNamespace(anki_dir=ROOT / "anki", web_dir=ROOT / "app" / "web", anki_copy=False,
                             extension_present=lambda: False, ext_dir=tmp_path / "ext")
    target = tmp_path / "addons21" / "sluka_desktop"
    changed, _problem = install.put_anki_addon(config, target)
    assert "LICENSE.txt" in changed and (target / "LICENSE.txt").read_bytes() == (ROOT / "anki" / "sluka_desktop" / "LICENSE.txt").read_bytes()
