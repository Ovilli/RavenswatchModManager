"""Guards on what the Lua SDK is allowed to hand to engine code.

Some engine functions dereference structures the loader cannot validate from
Lua. Calling one with a merely *plausible* pointer is not a nil return — it is
an access violation that takes the whole game down with it.

This is a regression test for a real crash: on 2026-08-15 `R.damage` called
`Entity_GetNetId` on a hero object whose component-store slot held the -1
sentinel, and `Entity_GetNetComponent` walked it unguarded
(EXCEPTION_ACCESS_VIOLATION reading 0xffffffffffffffff, dump a97c76fe). The
mistake was treating `is_grant_target(x) == true` as proof that some *other*
subsystem can traverse x.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
SDK = REPO / "src" / "loader" / "lib" / "rsmm.lua"

#: Symbols the SDK must not call. Each dereferences an entity's component map
#: with no guard of its own, so a wrong pointer is fatal rather than false.
#: If one of these ever becomes callable safely, it needs a validator that
#: proves the WHOLE traversal (control bytes at +0x5e8, slots at +0x5f0, mask
#: at +0x600), not just a plausible base pointer.
FORBIDDEN = ("Entity_GetNetComponent", "Entity_GetNetId")


def _code_lines(text: str) -> list[tuple[int, str]]:
    """Source lines with comment-only lines dropped.

    The ban is on CALLS, not on explaining why the ban exists — the comments
    naming these functions are the most useful thing in the file.
    """
    out: list[tuple[int, str]] = []
    for i, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if line.startswith("--"):
            continue
        out.append((i, raw.split("--", 1)[0]))
    return out


@pytest.mark.parametrize("symbol", FORBIDDEN)
def test_sdk_does_not_call_unguardable_engine_functions(symbol: str) -> None:
    pattern = re.compile(rf"""["']{re.escape(symbol)}["']""")
    hits = [(n, line.strip()) for n, line in _code_lines(SDK.read_text(encoding="utf-8"))
            if pattern.search(line)]
    assert not hits, (
        f"{SDK.name} passes {symbol!r} to an engine call at "
        + ", ".join(f"line {n}" for n, _ in hits)
        + f" — {symbol} dereferences the entity component map unconditionally "
        "and crashed the game on an object whose store slot was -1. Use a "
        "page-guarded read (e.g. the HUD mirror for local/remote) instead."
    )


def test_the_guard_would_notice_a_reintroduction() -> None:
    """The check must key on a CALL, not on the symbol appearing anywhere."""
    sample = '\n'.join([
        '-- Entity_GetNetId is unsafe; see the note.',   # comment: allowed
        'local x = R.engine.call_safe("Entity_GetNetId", { 1 }, e)',
    ])
    lines = _code_lines(sample)
    assert len(lines) == 1
    assert 'Entity_GetNetId' in lines[0][1]
