# SPDX-License-Identifier: LicenseRef-Sluka
# Copyright (c) 2026 Sluka. Part of Sluka Desktop; see LICENSE.txt.
"""Google Lens, asked about once: before Sluka first sends a picture to Google.

Google Lens reads a picture online: it is Sluka Vision's first reader, and one the Screen tab can be set to.  Each
picture it reads goes to Google, whose terms and privacy policy then apply to it.  And Google Lens is not a service
Google offers to other programs: Sluka reaches it the way Google's own Lens web page does (as LunaTranslator does),
which Google has not agreed to, and which Google may stop at any time.  So before the first picture is sent, a
message box of Windows' own says so and asks:

  Yes   Google Lens reads, and the question is not put again.  (The game text menu's licences note can have it put
        again: forget.)
  No    an offline reader reads instead -- Sluka's own OCR for Sluka Vision, the best offline one ("auto") for the
        Screen tab -- and the choice is changed to it, so that the question comes again only once Google Lens is
        chosen again.

Until the answer, the offline reader reads: nothing goes to Google before a yes.  The answer is kept with the game
text menu's settings (lens_ok, in data/gametext.json).
"""

from __future__ import annotations

import logging
import sys
import threading

log = logging.getLogger("sluka.games")

#: What reads in Google Lens' place, before (or without) a yes: an offline reader.
INSTEAD = {"vision_engine": "builtin", "ocr_engine": "auto"}
#: Where Google Lens was chosen.
WHERE = {"vision_engine": "Sluka Vision", "ocr_engine": "The Screen tab of the game text menu"}

TITLE = "Sluka Desktop: Google Lens"


def question(key: str) -> str:
    """The message box's text, for the setting that chose Google Lens."""
    instead = ("Sluka's own OCR reads instead, on this computer." if key == "vision_engine"
               else "the best offline reader here reads instead, on this computer.")
    return (f"{WHERE.get(key, 'Sluka')} is set to read with Google Lens.\n\n"
            "Google Lens works online: each picture it reads is sent to Google, and Google's terms of service and "
            "privacy policy apply to it.\n\n"
            "Google Lens is not a service that Google offers to other programs. Sluka reaches it the way Google's own "
            "Lens web page does, which Google has not agreed to, and Google may stop it at any time.\n\n"
            "Use Google Lens?\n\n"
            "Yes: Google Lens reads, and Sluka does not ask again.\n"
            f"No: {instead}")


def ask_windows(key: str) -> bool:
    """Windows' own message box, above every window: True for Yes.  No is the button chosen at first (an Enter
    pressed by chance sends nothing).  Where there is no such box, the answer is No."""
    if sys.platform != "win32":
        return False
    import ctypes

    MB_YESNO, MB_ICONQUESTION, MB_DEFBUTTON2 = 0x4, 0x20, 0x100
    MB_SETFOREGROUND, MB_TOPMOST = 0x10000, 0x40000
    IDYES = 6
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.MessageBoxW.argtypes = (ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_uint)
    user32.MessageBoxW.restype = ctypes.c_int
    flags = MB_YESNO | MB_ICONQUESTION | MB_DEFBUTTON2 | MB_SETFOREGROUND | MB_TOPMOST
    return user32.MessageBoxW(None, question(key), TITLE, flags) == IDYES


class LensQuestion:
    """The question, for the game text menu (games: its GameText): which reader is to read for a setting that may
    choose Google Lens, and the question put where it does and has had no yes."""

    def __init__(self, games, ask=None):
        self.g = games
        self._ask = ask or ask_windows
        self._asking = False
        self._lock = threading.Lock()

    def allowed(self) -> bool:
        """Whether Google Lens has had its yes."""
        return bool(self.g.settings.get("lens_ok"))

    def reader(self, key: str) -> str:
        """The reader that is to read for this setting (ocr_engine, vision_engine): the one chosen -- Google Lens only
        once it has had its yes.  Until then the offline one reads, and the question is put (once at a time)."""
        chosen = str(self.g.settings.get(key) or "")
        if chosen != "lens" or self.allowed():
            return chosen
        self._put(key)
        return INSTEAD.get(key, "builtin")

    def _put(self, key: str) -> None:
        with self._lock:
            if self._asking:
                return
            self._asking = True
        threading.Thread(target=self._question, args=(key,), name="sluka-lens-question", daemon=True).start()

    def _question(self, key: str) -> None:
        try:
            yes = bool(self._ask(key))
        except Exception:
            log.exception("game text: the question about Google Lens could not be put")
            yes = False
        finally:
            with self._lock:
                self._asking = False
        if yes:
            self.g.update({"lens_ok": True})
            self.g.note("Google Lens reads from now on: each picture it reads is sent to Google.")
        elif self.g.settings.get(key) == "lens":
            self.g.update({key: INSTEAD.get(key, "builtin")})
            name = "Sluka's own OCR" if key == "vision_engine" else "the best offline reader here"
            self.g.note(f"Google Lens is not used: {name} reads instead, on this computer.")

    def forget(self) -> dict:
        """The yes taken back: the question is put again the next time Google Lens is to read."""
        self.g.update({"lens_ok": False})
        self.g.note("Google Lens is asked about again before it next reads.")
        return {"ok": True}
