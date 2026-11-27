"""Which face mpv is to ask for at each weight (winfonts.plan), and the plain copies made of variable faces."""

from __future__ import annotations

import glob
import io
import json
import os
import time

import pytest

from fakes import APP  # noqa: F401
from sluka_desktop import winfonts

CJK = sorted(glob.glob("/usr/share/fonts/opentype/noto/NotoSansCJK-*.ttc"))
VARIABLE = "/usr/share/fonts/truetype/google-fonts/ofl/sourcesans3/SourceSans3[wght].ttf"


def test_a_browser_s_choice_of_weight():
    have = [100, 300, 350, 400, 500, 700, 900]
    assert winfonts.css_weight(have, 500) == 500
    assert winfonts.css_weight([300, 400, 600, 700], 500) == 400       # 400..500: up to 500, then down
    assert winfonts.css_weight([300, 600, 700], 450) == 300
    assert winfonts.css_weight([400, 700], 600) == 700                 # above 500: up first
    assert winfonts.css_weight([300, 400], 600) == 400
    assert winfonts.css_weight([400, 700], 300) == 400                 # below 400: down, then up


def test_thickening_is_what_a_thin_default_lacks():
    assert winfonts.thickening(500, 500) == 0
    # Noto Sans JP drawn at its thinnest for 500: the strokes are the difference, less what libass adds itself.
    x = winfonts.thickening(100, 500)
    assert 0.05 < x < 0.06
    assert winfonts.thickening(400, 500) == pytest.approx(0.022, abs=0.001)


@pytest.mark.skipif(not CJK, reason="no Noto Sans CJK here")
def test_static_faces_are_asked_for_by_their_older_family_name():
    finder = winfonts.Finder(files=CJK)
    face = finder.face("Noto Sans CJK JP")
    assert face is not None and not face.variable
    assert finder.plan(face, 500) == {"n": "Noto Sans CJK JP Medium", "b": 500}
    assert finder.plan(face, 400) == {"n": "Noto Sans CJK JP", "b": 400}
    assert finder.plan(face, 600) == {"n": "Noto Sans CJK JP", "b": 700}     # no 600: a browser takes Bold
    assert finder.plan(face, 300) == {"n": "Noto Sans CJK JP Light", "b": 300}


@pytest.mark.skipif(not os.path.exists(VARIABLE), reason="no variable font here")
def test_a_variable_face_gets_a_plain_copy_in_mpv_s_fonts_folders(tmp_path):
    a, b = tmp_path / "mpv" / "fonts", tmp_path / "portable_config" / "fonts"
    state = tmp_path / "data" / "mpv-fonts.json"
    finder = winfonts.Finder(files=[VARIABLE], mpv_font_dirs=[a, b], state_file=state)
    face = finder.face("Source Sans 3")
    assert face.variable and face.wght == (200.0, 200.0, 900.0) and face.outlines == "glyf"
    # At its default weight the face is itself.
    assert finder.plan(face, 200) == {"n": face.legacy, "b": 200}
    plan = finder.plan(face, 500)
    assert plan["n"] == "Sluka Source Sans 3 500" and plan["b"] == 500
    assert plan["file"].startswith("Sluka-SourceSans3-500-") and plan["file"].endswith(".ttf")
    assert plan["via"]["n"] == face.legacy and plan["via"]["b"] == 500 and plan["via"]["x"] > 0
    deadline = time.time() + 60
    while time.time() < deadline and not ((a / plan["file"]).is_file() and (b / plan["file"]).is_file()):
        time.sleep(0.05)
    assert (a / plan["file"]).is_file() and (b / plan["file"]).is_file()
    from fontTools.ttLib import TTFont

    made = TTFont(io.BytesIO((a / plan["file"]).read_bytes()))
    assert made["name"].getDebugName(1) == "Sluka Source Sans 3 500" and made["OS/2"].usWeightClass == 500
    assert "fvar" not in made
    # Remembered, so that a later start makes it again where it went missing.
    assert plan["file"] in json.loads(state.read_text())
    (a / plan["file"]).unlink()
    again = winfonts.Finder(files=[VARIABLE], mpv_font_dirs=[a, b], state_file=state)
    again._load()
    again._make_remembered()
    deadline = time.time() + 60
    while time.time() < deadline and not (a / plan["file"]).is_file():
        time.sleep(0.05)
    assert (a / plan["file"]).is_file()


@pytest.mark.skipif(not os.path.exists(VARIABLE) or not CJK, reason="fonts missing here")
def test_faces_sends_the_plans_for_each_weight_of_each_use(tmp_path):
    finder = winfonts.Finder(files=[VARIABLE] + CJK, mpv_font_dirs=[tmp_path / "fonts"], state_file=tmp_path / "s.json")
    out = finder.faces({"cc": ["Source Sans 3", "sans-serif"], "ui": ["Noto Sans CJK JP"], "word": ["Noto Sans CJK JP"]}, "ja")
    assert set(out["cc"]["P"]["w"]) == {"500"} and out["cc"]["P"]["w"]["500"]["n"] == "Sluka Source Sans 3 500"
    assert set(out["ui"]["P"]["w"]) == {"400", "500", "600"}
    assert out["ui"]["P"]["w"]["500"] == {"n": "Noto Sans CJK JP Medium", "b": 500}
    assert out["word"]["P"]["w"] == {"400": {"n": "Noto Sans CJK JP", "b": 400}}
