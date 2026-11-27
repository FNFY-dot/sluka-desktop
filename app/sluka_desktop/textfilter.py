# SPDX-License-Identifier: LicenseRef-Sluka
# Copyright (c) 2026 Sluka. Part of Sluka Desktop; see LICENSE.txt.
"""What a game's text needs before it is shown: the tidying a text hooker's lines want.

A game draws its text in its own ways, and a hook sees it as the game has it:
each letter sent two or more times (KiriKiri draws a line four times,
CatSystem2 three), the whole line twice, the game's own layout codes in it
([r], {w}, <color=...>, \\C[2]), the lines broken where the game's text box
ends.  These are the fixes LunaTranslator and Textractor offer, each a
setting of the game text menu.  Nothing here knows which game it is.
"""

from __future__ import annotations

import itertools
import re

#: Kana, CJK ideographs, half-width katakana, Hangul: the scripts written without spaces between words.
CJK = re.compile(r"[\u3040-\u30ff\u31f0-\u31ff\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff\uff66-\uff9f\uac00-\ud7af\u3005\u3006]")
#: Letters of the scripts Sluka teaches that are not written with spaces, and their punctuation.
_TIGHT = re.compile(r"[\u3000-\u30ff\u31f0-\u31ff\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff\uff00-\uffef]")

_INVISIBLE = re.compile(r"[\u200b-\u200f\u202a-\u202e\u2060-\u2064\ufeff\u00ad]")

# Ruby as some engines write it: a reading after the word, which is not part of the line.
_RUBY_BAR = re.compile(r"[｜|]([^《\n|｜]{1,24})《[^》\n]{1,40}》")
_RUBY_AFTER = re.compile(r"([\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff々〆ヵヶ]+)《[^》\n]{1,40}》")
_RUBY_RENPY = re.compile(r"\{rt\}.*?\{/rt\}", re.S)
_RUBY_TAG = re.compile(r"<rt>.*?</rt>", re.S | re.I)

# The engines' layout codes.
_CODES = (
    re.compile(r"<[/!]?[A-Za-z][^<>\n]{0,60}>"),                    # <color=#fff> <size=40> </b> <ruby=...> (Unity, HTML)
    re.compile(r"\{/?[A-Za-z][^{}\n]{0,60}\}"),                    # {i} {w=0.5} {/color} (Ren'Py)
    re.compile(r"\[/?[A-Za-z_][A-Za-z0-9_]*(?:[ =][^\[\]\n]{0,60})?\]"),  # [r] [l] [p] [ruby text=..] [color ..] (KiriKiri, Tyrano)
    re.compile(r"\\[A-Za-z]{1,3}\[[^\]\n]{0,10}\]"),               # \C[2] \N[1] \I[64] \V[3] (RPG Maker)
    re.compile(r"\\[{}\\!.|^<>$]"),                                # \{ \} \! \. \| \^ (RPG Maker)
    re.compile(r"(?<![A-Za-z])\\[nNkKpPrR](?![A-Za-z])"),          # \n \k \p written out as two letters
)
_LITERAL_BREAK = re.compile(r"\\n(?![A-Za-z])")
_SPACES = re.compile(r"[ \t]{2,}")

#: What "repeats" may be: worked out from the line itself, not at all, or each letter sent that many times.
REPEAT_CHOICES = ("auto", "off", "2", "3", "4")


def normalize(text: str) -> str:
    """Line ends made one kind, nothing invisible, no control characters but the line break."""
    text = str(text or "").replace("\r\n", "\n").replace("\r", "\n").replace("\u2028", "\n").replace("\u2029", "\n")
    text = _INVISIBLE.sub("", text)
    text = "".join(ch for ch in text if ch == "\n" or ch == "\t" or ord(ch) >= 32 and not 0x7F <= ord(ch) < 0xA0)
    text = text.replace("\t", " ")
    return "\n".join(line.strip() for line in text.split("\n")).strip("\n")


def remove_codes(text: str) -> str:
    """The game's own layout and ruby codes taken out, the words left."""
    text = _LITERAL_BREAK.sub("\n", text)
    text = _RUBY_RENPY.sub("", text)
    text = _RUBY_TAG.sub("", text)
    text = _RUBY_BAR.sub(r"\1", text)
    text = _RUBY_AFTER.sub(r"\1", text)
    for pattern in _CODES:
        text = pattern.sub("", text)
    return _SPACES.sub(" ", text)


def _runs(text: str) -> list[tuple[str, int]]:
    return [(ch, len(list(group))) for ch, group in itertools.groupby(text)]


def undo_repeats(text: str, mode: str = "auto") -> str:
    """Each letter sent ``mode`` times (2, 3, 4), or as many as the line itself shows ("auto"), sent once.

    "auto" only acts where every run of one letter in the line is as long as the others' or a multiple of it,
    over three runs or more: a line as written never looks like that.
    """
    mode = str(mode or "auto")
    if mode == "off" or len(text) < 2:
        return text
    runs = [(ch, n) for ch, n in _runs(text)]
    letters = [(ch, n) for ch, n in runs if not ch.isspace()]
    if mode == "auto":
        if len(letters) < 3:
            return text
        times = 0
        for candidate in (4, 3, 2):
            if all(n % candidate == 0 for _ch, n in letters):
                times = candidate
                break
        if not times:
            return text
    else:
        try:
            times = max(1, min(8, int(mode)))
        except ValueError:
            return text
        if times == 1:
            return text
    out = []
    for ch, n in runs:
        if ch.isspace():
            out.append(ch * n)
        else:
            out.append(ch * max(1, -(-n // times)))
    return "".join(out)


def undo_repeated_line(text: str) -> str:
    """A line sent two or more times in one ("ABCABC", or the same line under itself), sent once."""
    lines = [line for line in text.split("\n") if line.strip()]
    if len(lines) >= 2 and all(line == lines[0] for line in lines):
        return lines[0]
    flat = text.replace("\n", "")
    for times in (2, 3, 4):
        if len(flat) % times:
            continue
        part = flat[: len(flat) // times]
        # (A run of one letter -- "…………", "ーーーー" -- is not a line said twice.)
        if len(part) >= 4 and len(set(part)) >= 2 and part * times == flat:
            return part
    return text


def join_lines(text: str) -> str:
    """The lines a game broke where its text box ends, made one: with nothing between Japanese or Chinese
    letters, with a space between words of other languages."""
    if "\n" not in text:
        return text
    parts = [line for line in text.split("\n") if line]
    out = parts[0] if parts else ""
    for line in parts[1:]:
        before, after = out[-1:], line[:1]
        tight = bool(_TIGHT.match(before) or _TIGHT.match(after))
        out += line if tight or before in "-—" else " " + line
    return out


def clean(text: str, *, repeats: str = "auto", join: bool = True, codes: bool = True) -> str:
    """A line of a game's text as it is to be shown: each of the fixes the settings ask for, in turn."""
    text = normalize(text)
    if codes:
        text = normalize(remove_codes(text))
    if repeats != "off":
        text = "\n".join(undo_repeats(line, repeats) for line in text.split("\n"))
    text = undo_repeated_line(text)
    if join:
        text = join_lines(text)
    return text.strip()


def cjk_share(text: str) -> float:
    """How much of a line is in a script without spaces (kana, kanji, hangul), from 0 to 1."""
    letters = [ch for ch in text if not ch.isspace()]
    if not letters:
        return 0.0
    return sum(1 for ch in letters if CJK.match(ch)) / len(letters)


#: Hooks on Windows' own text drawing: they see every text the game draws, menus and all, often letter by letter.
SYSTEM_HOOKS = re.compile(r"(?i)(textout|drawtext|getglyphoutline|gettextextent|exttextout|getcharabcwidths|"
                          r"charnext|charprev|lstr|multibytetowidechar|widechartomultibyte|createfont)")


def dialogue_score(lines: list[str], name: str = "", per_second: float = 0.0) -> float:
    """How much a text thread looks like the game's dialogue, from the lines it sent last.

    Lines that are mostly kana and kanji, of a sentence's length, and different from each other count; a
    hook on Windows' text drawing counts less (it has the menus too), a thread that sends many lines a
    second counts less (a clock, a line drawn again every frame).
    """
    seen = set()
    score = 0.0
    for line in reversed(lines[-16:]):
        if line in seen:
            continue
        seen.add(line)
        n = len(line)
        if n < 2 or n > 400:
            continue
        share = cjk_share(line)
        if share >= 0.5:
            score += 1.0 + min(n, 60) / 60.0
        elif share >= 0.2:
            score += 0.3
    if name and SYSTEM_HOOKS.search(name):
        score *= 0.6
    if per_second > 4:
        score *= 0.3
    return round(score, 3)
