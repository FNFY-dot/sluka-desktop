"""A stand-in for LunaSubprocess32.exe and LunaSubprocess64.exe:  dllinject PID... DLL

It answers as LunaSubprocess's dllinject does (1: the library was put in, 0: a program could not be opened), and
leaves the mark the stand-in host (fake_lunahost.c) takes for the hook being in the game: injected-PID, in the
folder FAKE_LUNA_DIR says.  A program marked deny-PID there cannot be opened.  Each call is written down in
injections.txt.
"""

import os
import sys


def main(argv: list[str]) -> int:
    if len(argv) < 3 or argv[0] != "dllinject":
        return 2
    folder = os.environ.get("FAKE_LUNA_DIR", ".")
    with open(os.path.join(folder, "injections.txt"), "a", encoding="utf-8") as done:
        done.write(" ".join(argv[1:]) + "\n")
    for pid in argv[1:-1]:
        if os.path.exists(os.path.join(folder, f"deny-{pid}")):
            return 0
        with open(os.path.join(folder, f"injected-{pid}"), "w", encoding="utf-8"):
            pass
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
