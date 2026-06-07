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
    """Every `rsmm symbols gen` output must match its committed file."""
    smap = S.load_symbol_map()
    cases = [
        (cmd_symbols.LOADER_HEADER, cmd_symbols._gen_header),
        (cmd_symbols.LOADER_API_HEADER, cmd_symbols._gen_api_header),
        (cmd_symbols.LOADER_EVENT_TABLE, cmd_symbols._gen_event_table),
        (cmd_symbols.LUA_ENGINE, cmd_symbols._gen_lua),
        (cmd_symbols.PYTHON_CONSTS, cmd_symbols._gen_python),
        (cmd_symbols.DOCS_PAGE, cmd_symbols._gen_docs),
    ]
    for path, gen in cases:
        # Read as UTF-8 explicitly: the files are written UTF-8 (em-dash in the
        # header), but read_text() defaults to the locale encoding — cp1252 on
        # Windows CI — which mangles non-ASCII and fails this compare there.
        assert path.read_text(encoding="utf-8") == gen(smap), (
            f"{path.name} is stale; run `rsmm symbols gen`"
        )


def test_callable_symbols_have_pattern_and_cabi():
    smap = S.load_symbol_map()
    callables = smap.callable_symbols
    assert callables, "expected at least one callable symbol"
    for s in callables:
        assert s.cabi and s.pattern_name, f"{s.name}: callable needs cabi + pattern"
        assert isinstance(s.cabi["params"], list)


def test_events_have_lua_event_and_pattern():
    smap = S.load_symbol_map()
    events = smap.events
    assert events, "expected at least one event"
    luas = {e.lua_event for e in events}
    assert "level_up" in luas and "run_end" in luas
    for e in events:
        assert e.lua_event and e.pattern_name


def test_cabi_sig_codes():
    """_cabi_sig maps C types to the native caller's 1-char codes."""
    sig = cmd_symbols._cabi_sig
    assert sig({"ret": "void", "params": ["void*", "void*"]}) == "vpp"
    assert sig({"ret": "void*", "params": ["const char*", "void*", "void*", "void*"]}) == "psppp"
    assert sig({"ret": "void", "params": ["void*", "uint64_t", "uint32_t"]}) == "vplu"
    assert sig({"ret": "void*", "params": []}) == "p"
    assert sig({"ret": "float", "params": ["double"]}) == "fd"


def test_engine_gen_lua_sigs_valid():
    """Every callable in engine_gen.lua carries a sig of valid codes whose
    length matches its cabi arity (ret code + one per param)."""
    smap = S.load_symbol_map()
    valid = set("viuplfds")
    for s in smap.callable_symbols:
        sig = cmd_symbols._cabi_sig(s.cabi)
        assert sig and all(c in valid for c in sig), f"{s.name}: bad sig {sig!r}"
        assert len(sig) == 1 + len(s.cabi["params"]), f"{s.name}: sig arity mismatch"


def test_anchor_callable_carries_offset():
    """The inlined SpawnAllObjects accessor must add its +0x70 offset."""
    smap = S.load_symbol_map()
    s = smap.by_name("MagicalObject_SpawnAllObjects")
    assert s.callable and s.anchor_offset == 0x70
    api = cmd_symbols._gen_api_header(smap)
    assert "+ 0x70" in api
