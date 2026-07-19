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
    # anchor address is parent-raw + offset (values track the current build)
    parent = int(s.anchor["raw"].split("_", 1)[1], 16)
    off = int(s.anchor["offset"], 16)
    assert s.preferred_addr(smap.preferred_base) == parent + off
    # the version-resilient pattern name is SEMANTIC (stable across game
    # patches), not the address-derived FUN_ name — see Symbol.pattern_name.
    assert s.pattern_name == "MagicalObject_SpawnAllObjects.parent"


def test_raw_and_va_resolution():
    smap = S.load_symbol_map()
    # A raw symbol resolves to its literal (current-build) address, and its
    # pattern key is the semantic name.
    r = smap.by_name("Resource_LookupByPath")
    assert r.raw is not None
    assert r.preferred_addr(smap.preferred_base) == int(r.raw.split("_", 1)[1], 16)
    assert r.pattern_name == "Resource_LookupByPath"
    # A va (data global) symbol resolves to its stored absolute address.
    g = smap.by_name("g_MagicalObjectPool")
    assert g.va is not None
    assert g.preferred_addr(smap.preferred_base) == int(g.va, 16)


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


def test_event_catalog_loaded_and_listed():
    """The firehose catalog loads and `rsmm symbols events` lists it."""
    smap = S.load_symbol_map()
    cat = smap.event_catalog
    assert cat, "expected a non-empty event_catalog"
    names = {e["name"] for e in cat}
    assert "enemy_killed" in names and "unlock_hero" in names
    for e in cat:
        assert e.get("name") and e.get("category"), f"catalog entry missing fields: {e}"

    import contextlib
    import io

    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        cmd_symbols._cmd_events(smap)
    out = buf.getvalue()
    assert "enemy_killed" in out and "level_up" in out and "Lifecycle" in out


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


def test_audit_flags_null_and_nonprologue(tmp_path, capsys):
    """`symbols audit` must flag a status=ok symbol the loader resolved to null,
    and one whose dumped prologue bytes aren't a function start, while passing a
    genuine prologue. Guards the runtime false-ok gate."""
    import json

    smap = S.load_symbol_map()
    ok_names = [s.name for s in smap.symbols if s.status == "ok"
                and s.kind in ("function", "event")]
    # Build a dump that resolves EVERY ok symbol to a real prologue, then break
    # two so only those are reported.
    good = "48895c2408488968105657"          # mov [rsp+8],rbx; ... (real prologue)
    dump = [{"name": n, "va": "0x1400aa000", "bytes": good} for n in ok_names]
    dump[0] = {"name": ok_names[0], "va": None, "bytes": None}          # null
    dump[1] = {"name": ok_names[1], "va": "0x1400bb000", "bytes": "ff" * 16}  # garbage
    p = tmp_path / "resolved_symbols.json"
    p.write_text(json.dumps(dump))

    rc = cmd_symbols._cmd_audit(smap, p)
    err = capsys.readouterr().err
    # The null-resolve check needs no capstone and must always fire.
    assert rc == 1
    assert ok_names[0] in err and "NULL" in err.upper()
    # The non-prologue check needs capstone; only assert it when available.
    try:
        import capstone  # noqa: F401
        assert ok_names[1] in err
    except ImportError:
        pass


def test_audit_missing_dump_returns_2(tmp_path):
    smap = S.load_symbol_map()
    rc = cmd_symbols._cmd_audit(smap, tmp_path / "nope.json")
    assert rc == 2


# --- audit: image-base slide ----------------------------------------------
#
# The loader's dump records absolute runtime VAs and no module base. Under
# Wine/Proton the exe is NOT at its preferred 0x140000000: the 2026-07-19 dump
# had every one of 77 resolved symbols at +0x6ffebc670000. Comparing raw VAs
# reported all 77 as "address drift" and advised refreshing symbols.json from
# the runtime VA — which would have written Proton-specific, machine-local
# addresses into the shared map.

import json  # noqa: E402

from rsmm.cli.cmd_symbols import detect_image_slide  # noqa: E402

_PROTON_SLIDE = 0x6FFEBC670000


def test_slide_is_detected_when_the_whole_image_moved():
    pairs = [(0x140000000 + i * 0x1000, 0x140000000 + i * 0x1000 + _PROTON_SLIDE)
             for i in range(77)]
    slide, confidence = detect_image_slide(pairs)
    assert slide == _PROTON_SLIDE
    assert confidence == 1.0


def test_no_slide_reported_when_the_image_is_at_its_preferred_base():
    """Windows without relocation must behave exactly as before."""
    pairs = [(0x140000000 + i * 0x1000, 0x140000000 + i * 0x1000) for i in range(20)]
    assert detect_image_slide(pairs) == (0, 1.0)


def test_one_moved_symbol_does_not_shift_the_consensus():
    """The point of the fix: real drift must survive, not be absorbed."""
    pairs = [(0x140000000 + i * 0x1000, 0x140000000 + i * 0x1000 + _PROTON_SLIDE)
             for i in range(50)]
    pairs.append((0x140900000, 0x140900000 + _PROTON_SLIDE + 0x4000))  # genuinely moved
    slide, confidence = detect_image_slide(pairs)
    assert slide == _PROTON_SLIDE
    assert confidence < 1.0
    # and the odd one out is still detectable as drift
    stored, runtime = pairs[-1]
    assert abs((stored + slide) - runtime) == 0x4000


def test_falls_back_to_no_slide_when_there_is_no_consensus():
    """Garbage in must not produce a confident, invented relocation."""
    pairs = [(0x140000000 + i, 0x140000000 + i * 7919) for i in range(30)]
    slide, confidence = detect_image_slide(pairs)
    assert slide == 0
    assert confidence < 0.5


def test_empty_input_is_safe():
    assert detect_image_slide([]) == (0, 0.0)


def test_audit_reports_no_drift_for_a_uniformly_rebased_image(tmp_path, capsys):
    """End-to-end through _cmd_audit with a synthetic Proton-style dump."""
    from rsmm.cli.cmd_symbols import _cmd_audit
    from rsmm.engine.symbols import load_symbol_map

    smap = load_symbol_map()
    records = []
    for s in smap.symbols:
        if s.kind not in ("function", "event"):
            continue
        try:
            addr = s.preferred_addr(0x140000000)
        except ValueError:
            continue
        records.append({"name": s.name, "va": hex(addr + _PROTON_SLIDE),
                        "bytes": ""})
    assert records, "symbol map should yield function symbols"

    dump = tmp_path / "resolved_symbols.json"
    dump.write_text(json.dumps(records), encoding="utf-8")
    _cmd_audit(smap, dump)

    out = capsys.readouterr()
    assert "address drift" not in out.err, "rebase misreported as per-symbol drift"
    assert f"slide of {hex(_PROTON_SLIDE)}" in out.out


def test_audit_never_tells_the_user_to_copy_a_runtime_va(tmp_path, capsys):
    """That advice would poison symbols.json with machine-local addresses."""
    from rsmm.cli.cmd_symbols import _cmd_audit
    from rsmm.engine.symbols import load_symbol_map

    smap = load_symbol_map()
    records = []
    for i, s in enumerate(smap.symbols):
        if s.kind not in ("function", "event"):
            continue
        try:
            addr = s.preferred_addr(0x140000000)
        except ValueError:
            continue
        # Move one symbol independently so the drift branch actually prints.
        extra = 0x400000 if i == 0 else 0
        records.append({"name": s.name, "va": hex(addr + _PROTON_SLIDE + extra),
                        "bytes": ""})
    dump = tmp_path / "resolved_symbols.json"
    dump.write_text(json.dumps(records), encoding="utf-8")
    _cmd_audit(smap, dump)

    err = capsys.readouterr().err
    if "address drift" in err:
        assert "do NOT copy" in err
        assert "refresh symbols.json" not in err
