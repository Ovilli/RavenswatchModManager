"""Static gate: the loader loads Lua text only.

Lua 5.4 does not verify bytecode, so a precompiled chunk from a mod can corrupt
the VM inside the game process. ``luaL_loadfile`` / ``luaL_dofile`` pass a NULL
mode (text or binary), so the loader's own sources must use ``luaL_loadfilex``
with mode ``"t"``, and ``require`` must go through our searcher instead of the
stock Lua-file searcher. No game exe or compiler needed.
"""

from __future__ import annotations

import re
from pathlib import Path

LOADER = Path(__file__).resolve().parent.parent / "src" / "loader"
SOURCES = sorted(p for d in ("src", "include") for p in (LOADER / d).rglob("*")
                 if p.suffix in {".cpp", ".h", ".hpp", ".c"})


def _code(p: Path) -> str:
    text = p.read_text(encoding="utf-8", errors="replace")
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    return re.sub(r"//[^\n]*", "", text)


def test_sources_found():
    assert any(p.name == "script_lua.cpp" for p in SOURCES)


def test_no_bare_loadfile_or_dofile():
    bad = [p.name for p in SOURCES
           if re.search(r"\bluaL_(loadfile|dofile|loadbuffer)\s*\(", _code(p))]
    assert not bad, f"use luaL_loadfilex(..., \"t\") / loadbufferx: {bad}"


def test_every_loadfilex_is_text_only():
    for p in SOURCES:
        for m in re.finditer(r"\bluaL_load(?:file|buffer)x\s*\(([^;]*?)\)\s*[;!=)|&]",
                             _code(p), flags=re.S):
            assert m.group(1).rstrip().endswith('"t"'), f"{p.name}: {m.group(0)}"


def test_apply_sandbox_installs_our_searcher():
    src = _code(LOADER / "src" / "script_lua.cpp")
    assert "lua_pushcfunction(L, lua_sdk_searcher)" in src
    assert "prepend_sdk_path" not in src
