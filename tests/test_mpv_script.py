"""The mpv script, run in a stand-in for mpv (tests/lua/fake_mpv.lua) under texlua."""

import os
import shutil
import subprocess
import tempfile

import pytest

from fakes import APP

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(os.path.dirname(APP), "mpv", "sluka.lua")
TEXLUA = shutil.which("texlua")

pytestmark = pytest.mark.skipif(not TEXLUA, reason="no Lua here (texlua)")


def run(platform: str, script: str = SCRIPT, one_value: bool = False, copy_here: bool = False) -> subprocess.CompletedProcess:
    with tempfile.TemporaryDirectory() as tmp:
        env = dict(os.environ, SLUKA_TEST_TMP=tmp, FAKE_COPY_HERE="1" if copy_here else "0")
        if one_value:
            env["FAKE_MPV_ONE_VALUE"] = "1"
        else:
            env.pop("FAKE_MPV_ONE_VALUE", None)
        return subprocess.run([TEXLUA, os.path.join(HERE, "lua", "flow.lua"), script, platform],
                              cwd=tmp, env=env, capture_output=True, text=True, timeout=60)


@pytest.mark.parametrize("platform", ["windows", "linux"])
@pytest.mark.parametrize("one_value", [False, True])
@pytest.mark.parametrize("copy_here", [False, True])
def test_the_whole_conversation(platform, one_value, copy_here):
    done = run(platform, one_value=one_value, copy_here=copy_here)
    assert done.returncode == 0, done.stdout + done.stderr
    assert "ALL GOOD" in done.stdout


def test_the_script_says_its_messages_whole():
    """mpv 0.36's format_json answers (text, nil): the message is the text alone."""
    with open(SCRIPT, encoding="utf-8") as handle:
        source = handle.read()
    assert "mp.commandv('script-message', 'sluka-mpv', utils.format_json(" not in source


def test_the_script_looks_at_the_player_for_the_time_heard():
    """A look a second while a file plays and at each change, none while paused; a last one before bye; a line's times."""
    with tempfile.TemporaryDirectory() as tmp:
        env = dict(os.environ, SLUKA_TEST_TMP=tmp)
        env.pop("FAKE_MPV_ONE_VALUE", None)
        done = subprocess.run([TEXLUA, os.path.join(HERE, "lua", "clock.lua"), SCRIPT],
                              cwd=tmp, env=env, capture_output=True, text=True, timeout=60)
    assert done.returncode == 0, done.stdout + done.stderr
    assert "ALL GOOD" in done.stdout
