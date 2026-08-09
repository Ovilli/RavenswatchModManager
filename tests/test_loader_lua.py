"""Run the loader SDK Lua unit tests (tests/lua/rsmm_spec.lua) under pytest.

rsmm.lua is 1900+ lines of engine-mutating pointer code loaded into the game at
runtime — the code most likely to crash a user's machine. It used to have zero
automated coverage. rsmm_spec.lua stands up a mocked native layer (fake
byte-memory + engine-call emulator) and exercises the stat / durable-stick path
end-to-end with no game.

Skipped (not failed) when no standalone Lua 5.4 interpreter is on PATH, so the
suite still runs everywhere; CI legs with lua installed get the real coverage.
"""

import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
SPEC = REPO / "tests" / "lua" / "rsmm_spec.lua"
LIB = REPO / "src" / "loader" / "lib"


def _lua_bin() -> str | None:
    for name in ("lua5.4", "lua54", "lua"):
        found = shutil.which(name)
        if found:
            return found
    return None


def test_rsmm_lua_spec():
    lua = _lua_bin()
    if lua is None:
        pytest.skip("no standalone lua interpreter on PATH (lua5.4/lua)")
    proc = subprocess.run(
        [lua, str(SPEC), str(LIB)],
        capture_output=True,
        text=True,
        cwd=str(REPO),
    )
    # Spec prints a summary and exits nonzero on the first failed assertion.
    assert proc.returncode == 0, (
        f"rsmm_spec.lua failed (exit {proc.returncode}):\n"
        f"{proc.stdout}\n{proc.stderr}"
    )
    assert "0 failed" in proc.stdout, proc.stdout


MODS_SPEC = REPO / "tests" / "lua" / "mods_spec.lua"


def test_example_mods_spec():
    """Load every shipped example mod and drive its event handlers.

    `rsmm lint` reads a mod statically; it cannot tell that a handler calls an
    R.* function that does not exist, or subscribes to a misspelled event. Both
    are SILENT in-game — the dispatcher pcalls handlers, so an error is
    swallowed and the mod simply appears to do nothing. This loads each
    init.lua for real against the mocked native layer and fires the events it
    subscribes to.
    """
    lua = _lua_bin()
    if lua is None:
        pytest.skip("no standalone lua interpreter on PATH (lua5.4/lua)")
    mods = REPO / "mods"
    if not mods.is_dir():
        pytest.skip("mods/ is untracked and absent in this checkout")
    proc = subprocess.run(
        [lua, str(MODS_SPEC), str(LIB), str(mods)],
        capture_output=True,
        text=True,
        cwd=str(REPO),
    )
    assert proc.returncode == 0, (
        f"mods_spec.lua failed (exit {proc.returncode}):\n"
        f"{proc.stdout}\n{proc.stderr}"
    )
    assert "0 failed" in proc.stdout, proc.stdout
