"""The app's own variable-font instancer, against fontTools' (where both are at hand) and FreeType's rendering."""

from __future__ import annotations

import io
import os
import struct

import pytest

from fakes import APP  # noqa: F401  (puts the app on the path)
from sluka_desktop import varfont

FONTS = "/usr/share/fonts/truetype/google-fonts"
CASES = [
    ("ofl/sourcesans3/SourceSans3[wght].ttf", {"wght": 500}),
    ("ofl/sourcesans3/SourceSans3[wght].ttf", {"wght": 900}),
    ("ofl/montserrat/Montserrat[wght].ttf", {"wght": 500}),
    ("ofl/roboto/Roboto[wdth,wght].ttf", {"wdth": 87.5, "wght": 650}),
    ("Lora-Variable.ttf", {"wght": 600}),
    ("ofl/dmsans/DMSans[opsz,wght].ttf", {"opsz": 14, "wght": 500}),
]

fontTools = pytest.importorskip("fontTools")
from fontTools.ttLib import TTFont  # noqa: E402
from fontTools.varLib import instancer  # noqa: E402


def path_of(name):
    path = os.path.join(FONTS, name)
    if not os.path.exists(path):
        pytest.skip(f"{name} is not here")
    return path


def relative_points(font: TTFont, name: str):
    """A glyph's points (or its components' offsets) measured from its left side bearing point, and its width."""
    glyf, hmtx = font["glyf"], font["hmtx"]
    glyph = glyf[name]
    width, lsb = hmtx[name]
    if glyph.isComposite():
        return "c", [(c.glyphName, c.x, c.y) for c in glyph.components], width
    if glyph.numberOfContours <= 0:
        return "e", [], width
    coords = glyph.getCoordinates(glyf)[0]
    xmin = min(x for x, _ in coords)
    pp1 = xmin - lsb
    return "s", [(x - pp1, y) for x, y in coords], width


@pytest.mark.parametrize("name,location", CASES)
def test_the_same_points_as_fonttools(name, location):
    path = path_of(name)
    with open(path, "rb") as handle:
        data = handle.read()
    mine = TTFont(io.BytesIO(varfont.instance(data, location, family="Sluka Test")))
    theirs = instancer.instantiateVariableFont(TTFont(path), dict(location), inplace=False, updateFontNames=False)
    order = theirs.getGlyphOrder()
    assert mine.getGlyphOrder()[:len(order)] == order or len(mine.getGlyphOrder()) == len(order)
    off_points = off_widths = 0
    worst = 0
    for gid, glyph_name in enumerate(order):
        mine_name = mine.getGlyphOrder()[gid]
        kind_a, a, width_a = relative_points(mine, mine_name)
        kind_b, b, width_b = relative_points(theirs, glyph_name)
        assert kind_a == kind_b, glyph_name
        if abs(width_a - width_b) > 1:
            off_widths += 1
        if kind_a == "c":
            for (_, ax, ay), (_, bx, by) in zip(a, b):
                worst = max(worst, abs(ax - bx), abs(ay - by))
        else:
            assert len(a) == len(b), glyph_name
            for (ax, ay), (bx, by) in zip(a, b):
                d = max(abs(ax - bx), abs(ay - by))
                worst = max(worst, d)
                if d > 1:
                    off_points += 1
    # Rounding apart (fontTools rounds the same sums, at most a unit away), every point and every width is fontTools'.
    assert off_points == 0, f"{off_points} points more than a unit away (worst {worst})"
    assert off_widths == 0
    assert worst <= 1


def test_the_instance_is_a_plain_font_with_its_own_name():
    path = path_of(CASES[0][0])
    with open(path, "rb") as handle:
        out = varfont.instance(handle.read(), {"wght": 500}, family="Sluka Source Sans 3 500", weight_class=500)
    font = TTFont(io.BytesIO(out))
    for tag in ("fvar", "gvar", "avar", "HVAR", "MVAR", "STAT"):
        assert tag not in font
    assert font["name"].getDebugName(1) == "Sluka Source Sans 3 500"
    assert font["name"].getDebugName(16) == "Sluka Source Sans 3 500"
    assert font["OS/2"].usWeightClass == 500
    assert font["head"].indexToLocFormat == 1
    # fontTools reads it whole, and its checksums hold.
    for tag in font.keys():
        font[tag]
    raw = io.BytesIO()
    font.save(raw)


def test_freetype_draws_the_instance_as_it_draws_the_variable_font_at_that_weight():
    from PIL import Image, ImageChops, ImageDraw, ImageFont

    path = path_of(CASES[0][0])
    with open(path, "rb") as handle:
        out = varfont.instance(handle.read(), {"wght": 600}, family="Sluka Test 600")
    text = "Hamburgefonstiv 0123"
    # Without the layout engine: kerning through GPOS keeps the default weight's values here (see varfont), the outlines are compared.
    variable = ImageFont.truetype(path, 120, layout_engine=ImageFont.Layout.BASIC)
    variable.set_variation_by_axes([600])
    plain = ImageFont.truetype(io.BytesIO(out), 120, layout_engine=ImageFont.Layout.BASIC)
    assert abs(variable.getlength(text) - plain.getlength(text)) <= 2

    def draw(font):
        image = Image.new("L", (1500, 180), 0)
        ImageDraw.Draw(image).text((10, 10), text, font=font, fill=255)
        return image

    a, b = draw(variable), draw(plain)
    diff = ImageChops.difference(a, b)
    histogram = diff.histogram()
    big = sum(histogram[96:])
    ink = sum(1 for v in a.tobytes() if v > 127)
    assert big < ink * 0.02, (big, ink)


def test_a_postscript_variable_font_is_refused():
    # The head of a font with 'fvar' and 'CFF2' and no 'glyf': refused, saying why.
    tables = {b"fvar": struct.pack(">HHHHHHHH", 1, 0, 16, 2, 0, 20, 0, 0), b"CFF2": b"\x00" * 8, b"head": b"\x00" * 54, b"maxp": b"\x00" * 6}
    data = varfont._sfnt(tables)
    with pytest.raises(varfont.FontError, match="TrueType"):
        varfont.instance(data, {"wght": 500}, family="x")
    assert varfont.variable_info(data)["outlines"] == "CFF2"


def _with(path, licence=None, fs_type=None):
    """The font at path, with its licence line (name 13) or its embedding licence (OS/2 fsType) changed."""
    font = TTFont(path)
    if licence is not None:
        font["name"].setName(licence, 13, 3, 1, 0x409)
    if fs_type is not None:
        font["OS/2"].fsType = fs_type
    raw = io.BytesIO()
    font.save(raw)
    return raw.getvalue()


def test_a_font_whose_licence_forbids_changed_copies_is_refused():
    path = path_of(CASES[0][0])
    # The words of the fonts Microsoft supplies with Windows (Segoe UI Variable's, for one): no copy at another weight.
    microsoft = ("Microsoft supplied font. You may use this font to create, display, and print content as permitted by the "
                 "license terms or terms of use, of the Microsoft product, service, or content in which this font was "
                 "included. You may only (i) embed this font in content as permitted by the embedding restrictions "
                 "included in this font; and (ii) temporarily download this font to a printer or other output device to "
                 "help print content. Any other use is prohibited.")
    with pytest.raises(varfont.FontError, match="licence lets no changed copy"):
        varfont.instance(_with(path, licence=microsoft), {"wght": 500}, family="x")
    # An embedding licence that is "restricted" (the OpenType specification: not to be modified), likewise.
    with pytest.raises(varfont.FontError, match="restricted"):
        varfont.instance(_with(path, fs_type=0x0002), {"wght": 500}, family="x")
    # The Open Font License's own line (Noto's, Source Sans'), and an editable embedding licence: made as before.
    ofl = ("This Font Software is licensed under the SIL Open Font License, Version 1.1. This license is available with a "
           "FAQ at: https://openfontlicense.org")
    out = varfont.instance(_with(path, licence=ofl, fs_type=0x0008), {"wght": 500}, family="Sluka Test 500")
    made = TTFont(io.BytesIO(out))
    assert made["name"].getDebugName(13) == ofl  # (its licence line kept, as the OFL asks)
    assert varfont.changes_forbidden(varfont.tables_of(out)) == ""
