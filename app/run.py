"""Start of Sluka Desktop where no shell script starts it: Windows (Sluka.cmd, shortcuts, the app's own
restart without a console window).  Started as:  python -I run.py [arguments]

Python is started isolated (-I): it reads no PYTHON* settings from the environment and looks for modules
neither in the folder the user happens to be in nor beside this file.  Only the app's own folder is added.
"""

import os
import sys

if sys.version_info < (3, 9):
    sys.exit("sluka: Python 3.9 or newer is needed (this is %d.%d)." % sys.version_info[:2])

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

for stream in (sys.stdout, sys.stderr):
    # A console that cannot show a letter shows a mark in its place instead of ending the program.
    try:
        if stream is not None:
            stream.reconfigure(errors="replace")
    except (AttributeError, ValueError, OSError):
        pass

from sluka_desktop.__main__ import main  # noqa: E402

if __name__ == "__main__":
    try:
        code = main(sys.argv[1:])
    except KeyboardInterrupt:
        code = 130
    except Exception as err:  # nothing is to end without a word, least of all where no terminal shows it
        import traceback

        from sluka_desktop.tell import has_terminal, problem

        if has_terminal():
            traceback.print_exc()
        problem("Sluka Desktop stopped on an error (%s: %s)." % (type(err).__name__, err))
        code = 1
    sys.exit(code)
