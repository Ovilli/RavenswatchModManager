"""Run the loader SDK Lua unit tests (tests/lua/rsmm_spec.lua) under pytest.

rsmm.lua is 1900+ lines of engine-mutating pointer code loaded into the game at
runtime — the code most likely to crash a user's machine. It used to have zero
automated coverage. rsmm_spec.lua stands up a mocked native layer (fake
byte-memory + engine-call emulator) and exercises the stat / durable-stick path
end-to-end with no game.

Skipped (not failed) when no standalone Lua 5.4 interpreter is on PATH, so the
suite still runs everywhere; CI legs with lua installed get the real coverage.
"""

import re
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


# The stdlib names rsmm.lua is allowed to read out of _ENV. Everything the SDK
# defines itself is a local, so any OTHER global read is a bug of a specific and
# expensive kind: a closure defined ABOVE the `local` it means to capture. Lua
# resolves that lexically at compile time, so the name silently compiles to a
# global read and is nil forever.
_ALLOWED_GLOBALS = {
    "type", "ipairs", "pairs", "next", "pcall", "select", "tostring", "tonumber",
    "assert", "error", "require", "setmetatable", "rawget", "rawset", "string",
    "xpcall",
    "table", "math", "os", "_G",
}


def _sdk_lua_files() -> list[Path]:
    """Every Lua file planted into <game>/rsmm/lib, entrypoint and submodules.

    The submodules matter more than the entrypoint here, not less: a namespace
    lifted out of rsmm.lua takes its free variables through an env table, and a
    value the parent forgets to pass compiles to exactly the same silent nil
    global read this test exists to catch.
    """
    files = sorted((REPO / "src" / "loader" / "lib").glob("*.lua"))
    files += sorted((REPO / "src" / "loader" / "lua" / "rsmm").glob("*.lua"))
    return files


def test_rsmm_lua_reads_no_accidental_globals():
    """Guard the bug class that cost session 4c36 an entire playtest.

    The LobbyAttributes_Parse detour indexed `F`, whose `local` sat 800 lines
    BELOW the closure, so it compiled as a global read and was nil every time.
    The callback raised on all three of the local player's parses, the hook
    layer disabled it after 20 strikes, and every ally who joined afterwards was
    parsed by nobody -- four rows on the damage board, one name.

    Nothing caught it: the SDK spec drove `_note_blob` directly rather than the
    installed callback, and Lua reports an undefined global only when the line
    finally runs. This reads the compiled chunk instead, so a name that resolved
    to _ENV by accident fails here whether or not any test reaches it.
    """
    luac = shutil.which("luac5.4") or shutil.which("luac54") or shutil.which("luac")
    if luac is None:
        pytest.skip("no luac on PATH (luac5.4/luac)")
    files = _sdk_lua_files()
    assert any(f.name == "rsmm.lua" for f in files), "the SDK entrypoint was not scanned"
    any_globals = False
    problems: list[str] = []
    for path in files:
        proc = subprocess.run(
            [luac, "-p", "-l", "-l", str(path)],
            capture_output=True,
            text=True,
            cwd=str(REPO),
        )
        assert proc.returncode == 0, f"{path.name}: {proc.stderr}"
        found = set(
            re.findall(r'GETTABUP\s+\S+\s+\S+\s+\S+\s*;\s*_ENV "([A-Za-z_]\w*)"', proc.stdout)
        )
        any_globals = any_globals or bool(found)
        for name in sorted(found - _ALLOWED_GLOBALS):
            problems.append(f"{path.relative_to(REPO)}: {name}")
    assert any_globals, "parsed no global reads at all — the luac listing format changed"
    assert not problems, (
        "undeclared global read(s) in the SDK:\n  "
        + "\n  ".join(problems)
        + "\n— these are almost certainly locals declared below the closure that "
        "uses them (or, in a submodule, a value the parent never passed in), "
        "which Lua compiles to a nil global read"
    )
