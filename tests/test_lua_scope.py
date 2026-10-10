"""`rsmm.cli._lua_scope` — the late-local check `rsmm lint` runs on mod Lua."""

from __future__ import annotations

import pytest

from rsmm.cli._lua_scope import LuaSyntaxError, late_locals


def _names(src: str) -> list[tuple[str, int, int]]:
    return [(h.name, h.line, h.decl_line) for h in late_locals(src)]


def test_the_lobby_parse_bug_shape_is_caught():
    """A closure indexing `F` whose `local` sits below it: the detour that lost
    every ally's name for a session."""
    src = (
        "local R = require('rsmm')\n"
        "R.on('lobby:parse', function(blob)\n"
        "    F._note_blob(blob)\n"
        "end)\n"
        "local F = {}\n"
    )
    assert _names(src) == [("F", 3, 5)]


def test_a_local_declared_first_is_fine():
    src = "local F = {}\nlocal function g() return F.x end\n"
    assert _names(src) == []


@pytest.mark.parametrize("src", [
    # field and method names are not variable reads
    "local t = {}\nt.F = 1\nt:F()\nlocal F = 2\n",
    # table-constructor keys
    "local t = { F = 1, [1] = 2; G = 3 }\nlocal F, G = 1, 2\n",
    # a plain assignment writes the global, it does not read it
    "F = 1\nlocal F = 2\n",
    "a, F = 1, 2\nlocal F = 2\n",
    # names inside strings and comments
    "print('F') -- F\n--[[ F ]] local s = [[F]]\nlocal F = 1\n",
    # parameters, for variables and inner locals shadow
    "local function f(F) return F end\nlocal F = 1\n",
    "for F = 1, 2 do print(F) end\nlocal F = 1\n",
    "for _, F in ipairs({}) do print(F) end\nlocal F = 1\n",
    "do local F = 1; print(F) end\nlocal F = 2\n",
    # a method's implicit self
    "local M = {}\nfunction M:go() return self end\nlocal self = 1\n",
    # Lua's own globals cached late are harmless
    "print(pairs)\nlocal pairs = pairs\n",
    # goto targets and labels are not reads
    "goto F\n::F::\nlocal F = 1\n",
    # `local x = x` reads the OUTER x on purpose
    "local F = F\n",
])
def test_not_a_late_local(src):
    assert _names(src) == []


def test_a_field_write_still_reads_its_table():
    """`F.x = 1` indexes `F`, so it is as broken as reading it."""
    assert _names("F.x = 1\nlocal F = {}\n") == [("F", 1, 2)]


def test_function_statement_on_a_table_reads_the_table():
    assert _names("function M.go() end\nlocal M = {}\n") == [("M", 1, 2)]


def test_only_top_level_locals_count():
    """A later INNER local of the same name is a different variable; the
    earlier read is a deliberate global (or another file's), not this bug."""
    src = "print(Helper)\nlocal function f()\n  local Helper = 1\nend\n"
    assert _names(src) == []


def test_reads_after_a_block_closes_see_the_outer_scope():
    src = (
        "if x then\n  local F = 1\nelseif y then\n  print(F)\nelse\n  print(F)\nend\n"
        "repeat local G = 1 until G\n"
        "local F = 2\n"
    )
    assert [n for n, *_ in _names(src)] == ["F", "F"]


def test_call_arguments_with_a_function_body():
    src = "R.on('x', function()\n  return { a = F }\nend)\nlocal F = 1\n"
    assert _names(src) == [("F", 2, 4)]


@pytest.mark.parametrize("src", [
    "print('unterminated)\n",
    "local s = [[never closed\n",
    "if x then\n",
    "end\n",
])
def test_unwalkable_source_raises(src):
    with pytest.raises(LuaSyntaxError):
        late_locals(src)
