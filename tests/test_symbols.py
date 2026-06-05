"""Symbol-map contract tests.

data/symbols.json is the canonical engine mappings file. These tests keep
it honest: schema valid, addresses resolve, status=ok never lies about a
pattern existing, and the generated loader header / python constants stay
in lockstep with the source (mirrors the docs-gen --check guard).
"""

from __future__ import annotations

from rsmm.cli import cmd_symbols
from rsmm.engine import symbols as S


def test_symbol_map_validates_clean():
    smap = S.load_symbol_map()
    problems = S.validate(smap)
    assert not problems, f"{len(problems)} problem(s): {problems[:5]}"
    assert len(smap.symbols) > 0


def test_anchor_resolution_math():
    smap = S.load_symbol_map()
    s = smap.by_name("MagicalObject_SpawnAllObjects")
    assert s is not None
    # parent FUN_1402586f0 + offset 0x70
    assert s.preferred_addr(smap.preferred_base) == 0x1402586F0 + 0x70
    # the version-resilient pattern is the parent's
    assert s.pattern_name == "FUN_1402586f0"


def test_raw_and_va_resolution():
    smap = S.load_symbol_map()
    assert smap.by_name("Resource_LookupByPath").preferred_addr(smap.preferred_base) == 0x140487040
    assert smap.by_name("g_MagicalObjectPool").preferred_addr(smap.preferred_base) == 0x1414365D0


def test_status_ok_implies_real_pattern():
    """Any symbol claiming status=ok must have its pattern in the shipped
    function_patterns.json, or the 'resilient' promise is a lie."""
    smap = S.load_symbol_map()
    pats = S._pattern_names()
    if not pats:
        return  # pattern DB absent in this checkout
    for s in smap.symbols:
        if s.status == "ok":
            assert s.pattern_name in pats, f"{s.name}: ok but {s.pattern_name} missing"


def test_names_are_unique_and_c_safe():
    smap = S.load_symbol_map()
    names = [s.name for s in smap.symbols]
    assert len(names) == len(set(names)), "duplicate symbol names"
    for n in names:
        assert n[0].isalpha() or n[0] == "_", f"{n}: bad leading char for a C identifier"
        assert all(c.isalnum() or c == "_" for c in n), f"{n}: non-identifier char"


def test_generated_files_in_sync():
    """`rsmm symbols gen` output must match the committed files."""
    smap = S.load_symbol_map()
    assert cmd_symbols.LOADER_HEADER.read_text() == cmd_symbols._gen_header(smap), (
        "src/loader/src/symbols.gen.h is stale; run `rsmm symbols gen`"
    )
    assert cmd_symbols.PYTHON_CONSTS.read_text() == cmd_symbols._gen_python(smap), (
        "src/rsmm/engine/_symbols_gen.py is stale; run `rsmm symbols gen`"
    )
