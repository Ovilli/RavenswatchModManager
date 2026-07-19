"""``rsmm symbols`` — the engine symbol map (Minecraft-style mappings).

``data/symbols.json`` is the single source of truth: semantic name ->
engine function/global. Everything else is generated from it.

Subcommands:
  list                     Print the map, grouped by category.
  resolve <name>           Show one symbol's address + how it resolves.
  check                    Validate the map (CI-friendly; exits non-zero).
  gen                      Generate the loader C++ header + Python constants.
  ghidra-export [--json]   Emit a rename script for Ghidra (or a JSON
                           {addr: name} table for the MCP bridge) so the
                           functions stop showing up as FUN_xxxxxxxx.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

from rsmm.cli import _term
from rsmm.engine.paths import REPO_ROOT
from rsmm.engine.symbols import SymbolMap, load_symbol_map, validate

_ST = _term.Style()

# Generated artifacts — keep paths stable; CI --check compares against them.
LOADER_HEADER = REPO_ROOT / "src" / "loader" / "include" / "symbols.gen.h"
LOADER_API_HEADER = REPO_ROOT / "src" / "loader" / "include" / "symbols_api.gen.h"
LOADER_EVENT_TABLE = REPO_ROOT / "src" / "loader" / "src" / "event_table.gen.h"
LOADER_EVENT_PAYLOAD = REPO_ROOT / "src" / "loader" / "src" / "event_payload.gen.h"
LUA_ENGINE = REPO_ROOT / "src" / "loader" / "lib" / "engine_gen.lua"
PYTHON_CONSTS = REPO_ROOT / "src" / "rsmm" / "engine" / "_symbols_gen.py"
DOCS_PAGE = REPO_ROOT / "docs" / "SYMBOLS.md"
# Starlight docs-site mirror of DOCS_PAGE (same content + frontmatter).
SITE_DOCS_PAGE = (
    REPO_ROOT / "apps" / "docs" / "src" / "content" / "docs" / "reference" / "symbols.md"
)

_STATUS_GLYPH = {"ok": "OK ", "va": "VA ", "unverified": "?? "}


def _status(status: str, text: str) -> str:
    """Colour a status token by its rating: ok=green, va=yellow, else red.

    The rating is the whole point of the map, so it must be scannable at a
    glance. Callers pass the already-PADDED plain text — padding a styled
    string counts the escape bytes as width and breaks column alignment.
    """
    if status == "ok":
        return _ST.ok(text)
    if status == "va":
        return _ST.warn(text)
    return _ST.err(text)


def _cmd_list(smap: SymbolMap) -> int:
    for cat in smap.categories:
        print(f"\n{_ST.heading('# ' + cat)}")
        for s in sorted(smap.by_category(cat), key=lambda x: x.name):
            addr = s.preferred_addr(smap.preferred_base)
            glyph = _STATUS_GLYPH.get(s.status, "?? ")
            marker = _ST.dim("[") + _status(s.status, glyph) + _ST.dim("]")
            print(f"  {marker} {_ST.dim(f'0x{addr:09x}')}  {_ST.bold(s.name)}")
            if s.signature:
                print(f"              {_ST.dim(s.signature)}")
    print(f"\n{_ST.bold(str(len(smap.symbols)))} symbol(s).")
    return 0


def _cmd_resolve(smap: SymbolMap, name: str) -> int:
    s = smap.by_name(name)
    if s is None:
        print(f"no such symbol: {name}", file=sys.stderr)
        matches = [x.name for x in smap.symbols if name.lower() in x.name.lower()]
        if matches:
            print("did you mean: " + ", ".join(matches[:8]), file=sys.stderr)
        return 1
    addr = s.preferred_addr(smap.preferred_base)
    print(f"{_ST.heading(s.name)}")
    print(f"  {_ST.dim('address')}   {_ST.accent(f'0x{addr:x}')}  "
          f"{_ST.dim(f'(preferred base 0x{smap.preferred_base:x})')}")
    print(f"  {_ST.dim('kind')}      {s.kind}")
    print(f"  {_ST.dim('category')}  {s.category}")
    print(f"  {_ST.dim('status')}    {_status(s.status, s.status)}")
    if s.pattern_name:
        print(f"  {_ST.dim('pattern')}   {_ST.accent(s.pattern_name)}  "
              f"{_ST.dim('(version-resilient)')}")
    if s.signature:
        print(f"  {_ST.dim('signature')} {s.signature}")
    if s.note:
        print(f"  {_ST.dim('note')}      {_ST.dim(s.note)}")
    return 0


def _cmd_events(smap: SymbolMap) -> int:
    print(_ST.dim("Subscribe in a mod with R.on('<name>', cb). Gameplay events need "
                  "RSMM_ENABLE_GAME_EVENTS=1.") + "\n")

    print(_ST.heading("Lifecycle (always available):"))
    for name, desc in (
        ("setup", "all mods' init.lua ran; before overrides apply"),
        ("ready", "first frame; every mod loaded + overrides applied"),
        ("tick", "periodic (~500ms); poll sparingly"),
        ("exit", "DLL unloading; flush state here"),
    ):
        # Pad the PLAIN name, then style — padding a styled string would count
        # the ANSI escape bytes as width and skew every column.
        print(f"  {_ST.bold(f'{name:<22}')} {_ST.dim(desc)}")

    if smap.events:
        print(f"\n{_ST.heading('Typed gameplay events (decoded payload):')}")
        for s in sorted(smap.events, key=lambda x: x.lua_event or ""):
            addr = s.preferred_addr(smap.preferred_base)
            glyph = _STATUS_GLYPH.get(s.status, "?? ")
            marker = _ST.dim("[") + _status(s.status, glyph) + _ST.dim("]")
            fields = ", ".join(p["name"] for p in s.payload) if s.payload else "envelope"
            ev = _ST.accent(f"{s.lua_event:<18}")
            print(f"  {marker} {ev} {_ST.bold(f'{{{fields}}}')}  "
                  f"{_ST.dim(f'({s.name} 0x{addr:x})')}")

    cat = smap.event_catalog
    if cat:
        print(f"\n{_ST.heading('Analytics firehose (observation-grade, payload = name + seq):')}")
        for e in sorted(cat, key=lambda x: (x.get("category", ""), x["name"])):
            name = _ST.accent(f"{e['name']:<22}")
            tag = _ST.dim(f"[{e.get('category', '?')}]")
            print(f"  {name} {tag} {_ST.dim(e.get('note', ''))}")
        print(_ST.dim("  (+ any other name the game emits — the firehose forwards all)"))

    total = len(smap.events) + len(cat)
    print(f"\n{_ST.bold(str(total))} mapped event(s) + 4 lifecycle.")
    return 0


def _cmd_check(smap: SymbolMap) -> int:
    problems = validate(smap)
    if not problems:
        print(_ST.ok(f"symbols OK: {len(smap.symbols)} symbol(s), no problems."))
        return 0
    print(f"{len(problems)} problem(s):", file=sys.stderr)
    for p in problems:
        print(f"  {p}", file=sys.stderr)
    return 1


_PROLOGUE_FIRST = frozenset((
    "push", "sub", "mov", "lea", "xor", "test", "cmp", "and", "or", "ret",
    "jmp", "movss", "movaps", "movsxd", "movzx", "inc", "dec", "call", "lock",
    "xchg", "int3",
))


#: Below this share of agreeing samples the "slide" is not a rebase, it is
#: noise — fall back to assuming no relocation rather than inventing one.
_SLIDE_CONSENSUS = 0.5


def detect_image_slide(pairs: list[tuple[int, int]]) -> tuple[int, float]:
    """Infer the runtime image-base slide from (stored_va, runtime_va) pairs.

    Returns ``(slide, confidence)``. The loader's dump records absolute
    runtime VAs but no module base, and under Wine/Proton the exe is NOT
    loaded at its preferred 0x140000000 — in the 2026-07-19 dump every one of
    the 77 resolved symbols sat at +0x6ffebc670000. Comparing raw VAs there
    reports *every* symbol as drifted and tells the user to refresh
    symbols.json from the runtime VA, which would write Proton-specific
    addresses into the map and corrupt it.

    A relocation moves the whole image by one constant, so the true slide is
    the value the overwhelming majority of symbols agree on. Genuine drift is
    then a symbol that disagrees with that consensus.
    """
    if not pairs:
        return 0, 0.0
    counts = Counter(runtime - stored for stored, runtime in pairs)
    slide, n = counts.most_common(1)[0]
    confidence = n / len(pairs)
    if confidence < _SLIDE_CONSENSUS:
        return 0, confidence
    return slide, confidence


def _cmd_audit(smap: SymbolMap, dump_path: Path) -> int:
    """Diff the loader's RUNTIME ground-truth dump against the symbol map.

    `<game>/rsmm/resolved_symbols.json` is written by the loader itself
    (RSMM_DUMP_SYMBOLS=1) — {name, va, first-16-prologue-bytes} for every
    semantic pattern, resolved by the SAME code that runs in-game. This
    catches the false-ok class from the actual process, not a Python
    reimplementation: a status=ok symbol that resolved to null, or whose
    prologue bytes don't disassemble to a function start, is BROKEN.
    """
    if not dump_path.exists():
        print(f"no runtime dump at {dump_path}\n"
              "Launch the game once with RSMM_DUMP_SYMBOLS=1 in the loader flags "
              "(or Steam launch options) to produce it.", file=sys.stderr)
        return 2
    try:
        dump = {d["name"]: d for d in json.loads(dump_path.read_text())}
    except (json.JSONDecodeError, OSError, KeyError) as exc:
        print(f"cannot read dump: {exc}", file=sys.stderr)
        return 2

    md = None
    try:
        import capstone
        md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_64)
    except ImportError:
        pass  # prologue disasm skipped; null/mismatch checks still run

    by_name = {s.name: s for s in smap.symbols}

    # First pass: learn where the image actually loaded. Without this every
    # address comparison below is off by the relocation slide.
    pairs: list[tuple[int, int]] = []
    for name, s in by_name.items():
        if s.kind not in ("function", "event"):
            continue
        rec = dump.get(name)
        if not rec or not rec.get("va"):
            continue
        try:
            pairs.append((s.preferred_addr(0x140000000), int(rec["va"], 16)))
        except ValueError:
            continue
    slide, confidence = detect_image_slide(pairs)

    broken: list[tuple[str, str]] = []
    drift: list[tuple[str, str]] = []
    uncovered: list[str] = []
    ok = 0
    for name, s in by_name.items():
        if s.kind not in ("function", "event"):
            continue
        rec = dump.get(name)
        if rec is None:
            # An anchor symbol is a parent pattern + offset and has no pattern
            # entry of its own, so it can NEVER appear in the dump (the loader
            # iterates the pattern DB). Calling that "BROKEN" is the right
            # verdict only by accident; the check that actually validates an
            # anchor is the instruction-boundary one in verify_symbol_resolve.
            if getattr(s, "anchor", None):
                if s.status == "ok":
                    uncovered.append(name)
                continue
            if s.status == "ok":
                broken.append((name, "status=ok but ABSENT from the runtime dump"))
            continue
        va = rec.get("va")
        if va is None:
            if s.status == "ok":
                broken.append((name, "status=ok but the loader RESOLVED IT TO NULL "
                                     "(pattern missing / no hit) — capability dead in-game"))
            continue
        va_int = int(va, 16)
        # prologue check against the dumped bytes (no exe needed).
        raw = rec.get("bytes")
        if md and raw:
            code = bytes.fromhex(raw)
            ins = list(md.disasm(code, va_int, count=1))
            first = ins[0].mnemonic if ins else "?"
            if first not in _PROLOGUE_FIRST:
                broken.append((name, f"resolved 0x{va_int:x} but first insn '{first}' "
                                     "is not a prologue (mid-instruction / wrong fn)"))
                continue
        # Drift vs the stored raw address, measured AFTER removing the image
        # slide. A symbol that moved with the rest of the image has not
        # drifted; only one that disagrees with the consensus has.
        try:
            stored = s.preferred_addr(0x140000000) + slide
            if abs(stored - va_int) > 0x100000:
                drift.append((name, f"expected 0x{stored:x} vs runtime 0x{va_int:x} "
                                    f"(Δ0x{abs(stored - va_int):x})"))
        except ValueError:
            pass
        ok += 1

    print(f"audited {_ST.bold(str(len(dump)))} runtime-resolved symbols against the map; "
          f"{_ST.ok(str(ok))} clean.")
    if slide:
        print(_ST.dim(
            f"  image loaded at a slide of 0x{slide:x} from the preferred base "
            f"(agreed by {confidence:.0%} of symbols) — addresses compared "
            "relative to it, not raw."))
    elif pairs and confidence < _SLIDE_CONSENSUS:
        print(_ST.warn(
            f"  could not agree on an image base (best guess held by only "
            f"{confidence:.0%} of symbols) — comparing raw addresses; "
            "treat the drift list below with suspicion."), file=sys.stderr)
    if uncovered:
        print(_ST.dim(
            f"  {len(uncovered)} anchor symbol(s) are not covered by the runtime "
            "dump by construction (parent pattern + offset, no pattern of their "
            "own): " + ", ".join(sorted(uncovered)) +
            " — validated by scripts/verify_symbol_resolve.py instead."))
    if drift:
        # NB: never tell the user to copy the RUNTIME va into symbols.json.
        # Under Proton that address is a rebased, machine-specific value and
        # writing it into the map would poison it for everyone.
        print(f"\n{len(drift)} address drift (moved independently of the image "
              "— re-resolve with scripts/disasm.py --resolve NAME; do NOT copy "
              "the runtime VA into symbols.json, it is base-relative):",
              file=sys.stderr)
        for n, why in drift:
            print(f"  {n}: {why}", file=sys.stderr)
    if broken:
        print(f"\n{len(broken)} BROKEN symbol(s) — the loader is running these wrong:",
              file=sys.stderr)
        for n, why in broken:
            print(f"  {n}: {why}", file=sys.stderr)
        print("\nRecover the address (scripts/disasm.py --resolve NAME) or downgrade to "
              "'unverified' + strip the pattern so the loader fails closed. "
              "See the symbols-pipeline memory.", file=sys.stderr)
        return 1
    print(_ST.ok("OK: every status=ok symbol resolved in-game to a real function start."))
    return 0


def _cpp_ident(name: str) -> str:
    return name


def _gen_header(smap: SymbolMap) -> str:
    lines = [
        "// GENERATED by `rsmm symbols gen` from data/symbols.json — DO NOT EDIT.",
        "// Preferred-base addresses; the loader rebases by image-base delta and,",
        "// for `pattern`-backed symbols, re-resolves via data/function_patterns.json.",
        "#pragma once",
        "#include <cstdint>",
        "",
        "namespace Sym {",
        f"constexpr std::uintptr_t kPreferredBase = 0x{smap.preferred_base:x}ull;",
        "",
    ]
    for cat in smap.categories:
        lines.append(f"// --- {cat} ---")
        for s in sorted(smap.by_category(cat), key=lambda x: x.name):
            addr = s.preferred_addr(smap.preferred_base)
            pat = s.pattern_name or ""
            lines.append(f"constexpr std::uintptr_t {_cpp_ident(s.name)} = 0x{addr:x}ull;")
            if pat:
                lines.append(f'constexpr const char* {_cpp_ident(s.name)}_Pattern = "{pat}";')
        lines.append("")
    lines.append("}  // namespace Sym")
    lines.append("")
    return "\n".join(lines)


def _gen_python(smap: SymbolMap) -> str:
    lines = [
        '"""GENERATED by `rsmm symbols gen` from data/symbols.json — DO NOT EDIT."""',
        "from __future__ import annotations",
        "",
        f"PREFERRED_BASE = 0x{smap.preferred_base:x}",
        "",
        "# name -> preferred-base address",
        "ADDR: dict[str, int] = {",
    ]
    for s in sorted(smap.symbols, key=lambda x: x.name):
        addr = s.preferred_addr(smap.preferred_base)
        lines.append(f'    "{s.name}": 0x{addr:x},')
    lines.append("}")
    lines.append("")
    lines.append("# name -> function-pattern key (version-resilient), when available")
    lines.append("PATTERN: dict[str, str] = {")
    for s in sorted(smap.symbols, key=lambda x: x.name):
        if s.pattern_name:
            lines.append(f'    "{s.name}": "{s.pattern_name}",')
    lines.append("}")
    lines.append("")
    lines.append("# event name -> Lua event published to mods (R.on(<lua>, cb))")
    lines.append("EVENTS: dict[str, str] = {")
    for s in sorted(smap.events, key=lambda x: x.name):
        lines.append(f'    "{s.name}": "{s.lua_event}",')
    lines.append("}")
    lines.append("")
    return "\n".join(lines)


def _cabi_type(cabi: dict) -> str:
    params = ", ".join(cabi["params"]) if cabi["params"] else "void"
    return f'{cabi["ret"]}(*)({params})'


def _cabi_code(ctype: str) -> str:
    """Map a C type to the native caller's 1-char signature code
    (see script_lua.cpp::lua_call_native): v/i/u/p/l/f/d/s."""
    t = ctype.strip()
    if t == "void":
        return "v"
    if t in ("const char*", "char*"):
        return "s"  # pass a Lua string -> char*
    if t.endswith("*"):
        return "p"  # arbitrary pointer -> pass an integer address
    if t in ("int", "int32_t", "char", "short", "bool"):
        return "i"
    if t in ("unsigned", "unsigned int", "uint32_t"):
        return "u"
    if t in ("int64_t", "uint64_t", "long long", "size_t", "intptr_t", "uintptr_t"):
        return "l"
    if t == "float":
        return "f"
    if t == "double":
        return "d"
    return "p"  # default: pointer-width passthrough


def _cabi_sig(cabi: dict) -> str:
    """Full native signature string: ret code followed by one code per arg."""
    return _cabi_code(cabi["ret"]) + "".join(_cabi_code(p) for p in cabi["params"])


def _gen_api_header(smap: SymbolMap) -> str:
    """Typed, pattern-resolved C++ accessors — names become callable.

    ``engine::Resource_LookupByPath()`` returns a typed function pointer
    resolved at runtime via the byte pattern (version-resilient), so the
    loader/mods call named engine functions instead of casting raw addresses.
    """
    lines = [
        "// GENERATED by `rsmm symbols gen` from data/symbols.json — DO NOT EDIT.",
        "// Typed, pattern-resolved engine call accessors (the Minecraft-style",
        "// 'mappings become callable methods' layer). Each accessor resolves its",
        "// byte pattern via fn_resolve, so it survives game updates.",
        "#pragma once",
        '#include "fn_resolver.h"',
        '#include "symbols.gen.h"',
        "#include <cstdint>",
        "",
        "namespace engine {",
        "",
    ]
    for s in sorted(smap.callable_symbols, key=lambda x: x.name):
        fn_t = f"{s.name}_fn"
        typ = _cabi_type(s.cabi)
        lines.append(f"// {s.name}  ({s.pattern_name})")
        if s.signature:
            lines.append(f"//   {s.signature}")
        lines.append(f"using {fn_t} = {typ};")
        off = s.anchor_offset
        if off:
            lines.append(f"inline {fn_t} {s.name}() {{")
            lines.append(f"    std::uintptr_t a = rsmm::fn_resolve(Sym::{s.name}_Pattern);")
            lines.append(f"    return a ? reinterpret_cast<{fn_t}>(a + 0x{off:x}) : nullptr;")
            lines.append("}")
        else:
            lines.append(f"inline {fn_t} {s.name}() {{")
            lines.append(
                f"    return reinterpret_cast<{fn_t}>(rsmm::fn_resolve(Sym::{s.name}_Pattern));"
            )
            lines.append("}")
        lines.append("")
    lines.append("}  // namespace engine")
    lines.append("")
    return "\n".join(lines)


def _gen_event_table(smap: SymbolMap) -> str:
    """Entries spliced into hook_events.cpp's ``EventHook g_hooks[]`` via
    ``#include`` — the event catalog is sourced from the symbol map."""
    lines = [
        "// GENERATED by `rsmm symbols gen` from data/symbols.json — DO NOT EDIT.",
        "// Spliced into EventHook g_hooks[] in hook_events.cpp.",
        "// { pattern_name, lua_event, real=nullptr, va=0 }",
    ]
    for s in sorted(smap.events, key=lambda x: x.lua_event or ""):
        lines.append(f'{{ "{s.pattern_name}", "{s.lua_event}", nullptr, 0 }},')
    lines.append("")
    return "\n".join(lines)


#: C printf spec + value-cast per payload field ctype.
_CTYPE_FMT = {
    "int": ("%d", "{expr}"),
    "int32_t": ("%d", "{expr}"),
    "unsigned": ("%u", "{expr}"),
    "uint32_t": ("%u", "{expr}"),
    "int64_t": ("%lld", "(long long)({expr})"),
    "float": ("%f", "(double)({expr})"),
    "double": ("%f", "(double)({expr})"),
}


def _gen_event_payload(smap: SymbolMap) -> str:
    """Generate ``rsmm::event_payload`` — fills the JSON published to mods.

    Events with a verified ``payload`` schema emit typed fields (decoded
    from ctx/arg by the expressions in data/symbols.json); every other
    event falls back to the safe envelope (seq + raw arg handles).
    """
    lines = [
        "// GENERATED by `rsmm symbols gen` from data/symbols.json — DO NOT EDIT.",
        "// Builds the JSON payload for each gameplay event. Field exprs are",
        "// RE-verified reads off ctx/arg; see the event's payload schema.",
        "#pragma once",
        "#include <cstdint>",
        "#include <cstdio>",
        "#include <cstring>",
        "",
        "namespace rsmm {",
        "inline void event_payload(const char* ev, char* buf, size_t n,",
        "                          unsigned seq, void* ctx, void* arg) {",
        "    (void)ctx; (void)arg;",
    ]
    for s in sorted(smap.events, key=lambda x: x.lua_event or ""):
        if not s.payload:
            continue
        ev = s.lua_event
        decls, fmts, args = [], [], []
        for p in s.payload:
            ctype, name, expr = p["ctype"], p["name"], p["expr"]
            spec, valtmpl = _CTYPE_FMT.get(ctype, ("%d", "{expr}"))
            decls.append(f"        {ctype} {name} = {expr};")
            fmts.append(f'\\"{name}\\":{spec}')
            args.append(valtmpl.format(expr=name))
        fmt = f'{{\\"event\\":\\"{ev}\\",\\"seq\\":%u,' + ",".join(fmts) + "}"
        arglist = ", ".join(["seq", *args])
        lines.append(f'    if (std::strcmp(ev, "{ev}") == 0) {{')
        lines.extend(decls)
        lines.append(f'        std::snprintf(buf, n, "{fmt}", {arglist});')
        lines.append("        return;")
        lines.append("    }")
    lines += [
        "    // default: safe envelope (no schema for this event yet)",
        "    std::snprintf(buf, n,",
        '                  "{\\"event\\":\\"%s\\",\\"seq\\":%u,'
        '\\"ctx\\":\\"0x%llx\\",\\"arg\\":\\"0x%llx\\"}",',
        "                  ev, seq,",
        "                  (unsigned long long)(std::uintptr_t)ctx,",
        "                  (unsigned long long)(std::uintptr_t)arg);",
        "}",
        "}  // namespace rsmm",
        "",
    ]
    return "\n".join(lines)


def _gen_lua(smap: SymbolMap) -> str:
    """Lua name -> {pattern, offset} table so mods resolve engine functions
    by semantic name (R.engine.resolve('Resource_LookupByPath'))."""
    lines = [
        "-- GENERATED by `rsmm symbols gen` from data/symbols.json — DO NOT EDIT.",
        "-- Semantic name -> { pattern = <FUN_ for fn_resolve>, offset = <int>,",
        "--                    sig = <native call signature: ret code + arg codes> }.",
        "-- rsmm.lua's R.engine.call(name, ...) resolves the pattern, adds the",
        "-- offset, and passes `sig` to rsmm._internal.call so mods call by name",
        "-- with no manual signature. Codes: v=void i=int32 u=uint32 p/l=ptr/int64",
        "-- f=float d=double s=string (see script_lua.cpp::lua_call_native).",
        "return {",
    ]
    for s in sorted(smap.callable_symbols, key=lambda x: x.name):
        sig = _cabi_sig(s.cabi)
        lines.append(
            f'  ["{s.name}"] = {{ pattern = "{s.pattern_name}", '
            f'offset = 0x{s.anchor_offset:x}, sig = "{sig}" }},'
        )
    lines.append("}")
    lines.append("")
    return "\n".join(lines)


def _gen_docs(smap: SymbolMap) -> str:
    """Browsable engine-API reference (Javadoc analog) from the symbol map."""
    glyph = {"ok": "✅ ok", "va": "📍 va", "unverified": "❓ unverified"}
    lines = [
        "# Engine symbol reference",
        "",
        "> GENERATED by `rsmm symbols gen` from `data/symbols.json` — do not edit by hand.",
        "",
        "Canonical map of Ravenswatch engine functions/globals/events to stable",
        "semantic names. `status`: **ok** = resolvable by byte pattern in the current",
        "corpus (survives game updates); **va** = base-relative absolute (data globals);",
        "**unverified** = documented in an older corpus, address not re-confirmed.",
        "Functions tagged `callable` have a typed C++ accessor in `engine::` and a Lua",
        "resolver entry. See [CLAUDE.md] for the workflow.",
        "",
        f"Total: **{len(smap.symbols)}** symbols across {len(smap.categories)} categories.",
        "",
    ]
    for cat in smap.categories:
        lines.append(f"## {cat}")
        lines.append("")
        lines.append("| name | address | status | callable | signature / note |")
        lines.append("|------|---------|--------|----------|------------------|")
        for s in sorted(smap.by_category(cat), key=lambda x: x.name):
            addr = s.preferred_addr(smap.preferred_base)
            desc = s.signature or s.note
            if len(desc) > 90:
                desc = desc[:87] + "…"
            desc = desc.replace("|", "\\|")
            call = "✔" if s.callable else ""
            extra = f" → `{s.lua_event}`" if s.lua_event else ""
            lines.append(
                f"| `{s.name}`{extra} | `0x{addr:x}` | {glyph.get(s.status, s.status)} "
                f"| {call} | {desc} |"
            )
        lines.append("")
    return "\n".join(lines)


def _gen_docs_site(smap: SymbolMap) -> str:
    """Same content as `_gen_docs`, wrapped for the Starlight docs site.

    Drops the leading `# Engine symbol reference` H1 (Starlight renders the
    frontmatter title) and prepends frontmatter.
    """
    body = _gen_docs(smap)
    lines = body.splitlines()
    if lines and lines[0].startswith("# "):
        lines = lines[1:]
        if lines and lines[0].strip() == "":
            lines = lines[1:]
    fm = (
        "---\n"
        "title: Engine symbol reference\n"
        "description: The canonical engine symbol map and how to use it.\n"
        "---\n\n"
    )
    # Site-only: a generation-pipeline diagram (the plain SYMBOLS.md stays
    # diagram-free so its `--check` diff is pure data).
    diagram = (
        "One human-authored source (`data/symbols.json`) generates every "
        "downstream artifact:\n\n"
        "```mermaid\n"
        "flowchart LR\n"
        '    S["data/symbols.json<br/>(canonical, hand-authored)"]\n'
        '    S -->|"rsmm symbols gen"| H["loader C++<br/>symbols.gen.h + API"]\n'
        "    S -->|gen| E[\"event bus<br/>event_table.gen.h\"]\n"
        "    S -->|gen| L[\"Lua resolver<br/>engine_gen.lua\"]\n"
        '    S -->|gen| P["Python consts<br/>_symbols_gen.py"]\n'
        '    S -->|gen| D["this page<br/>+ docs/SYMBOLS.md"]\n'
        '    S -->|"ghidra-export"| G["Ghidra DB names"]\n'
        "```\n\n"
    )
    return fm + diagram + "\n".join(lines)


def _cmd_gen(smap: SymbolMap, check: bool) -> int:
    targets = [
        (LOADER_HEADER, _gen_header(smap)),
        (LOADER_API_HEADER, _gen_api_header(smap)),
        (LOADER_EVENT_TABLE, _gen_event_table(smap)),
        (LOADER_EVENT_PAYLOAD, _gen_event_payload(smap)),
        (LUA_ENGINE, _gen_lua(smap)),
        (PYTHON_CONSTS, _gen_python(smap)),
        (DOCS_PAGE, _gen_docs(smap)),
        (SITE_DOCS_PAGE, _gen_docs_site(smap)),
    ]
    if check:
        stale = [p for p, content in targets if not p.is_file() or p.read_text() != content]
        if stale:
            print("generated symbol files are stale; run `rsmm symbols gen`:", file=sys.stderr)
            for p in stale:
                print(f"  {p.relative_to(REPO_ROOT)}", file=sys.stderr)
            return 1
        print(_ST.ok("generated symbol files up to date."))
        return 0
    for p, content in targets:
        p.write_text(content, encoding="utf-8")
        print(f"wrote {_ST.dim(str(p.relative_to(REPO_ROOT)))}")
    return 0


def _cmd_ghidra_export(
    smap: SymbolMap, as_json: bool, out: Path | None, include_unverified: bool
) -> int:
    """Emit something that renames the live Ghidra DB so symbols are no
    longer FUN_xxxxxxxx. ``--json`` prints an {addr_hex: name} table (for the
    Ghidra MCP bridge); otherwise a runnable Ghidra Python (Jython) script.

    ``unverified`` symbols carry addresses from an older corpus that may
    point at the wrong function in the current DB, so they are skipped
    unless ``--include-unverified`` is passed."""
    chosen = [
        s
        for s in smap.symbols
        if include_unverified or s.status != "unverified"
    ]
    rows = [
        (s.preferred_addr(smap.preferred_base), s.name, s.kind)
        for s in sorted(chosen, key=lambda x: x.preferred_addr(smap.preferred_base))
    ]
    if as_json:
        table = {f"0x{addr:x}": name for addr, name, _ in rows}
        text = json.dumps(table, indent=2)
        if out:
            out.write_text(text, encoding="utf-8")
            print(f"wrote {_ST.dim(str(out))}")
        else:
            print(text)
        return 0
    script = [
        "# GENERATED by `rsmm symbols ghidra-export` — run inside Ghidra (Script Manager).",
        "# Renames functions/data at the preferred base so they stop reading as FUN_xxxxxxxx.",
        "from ghidra.program.model.symbol import SourceType",
        "fm = currentProgram.getFunctionManager()",
        "base = currentProgram.getImageBase()",
        f"pref = base.getNewAddress(0x{smap.preferred_base:x})",
        "delta = base.getOffset() - pref.getOffset()",
        "renamed = 0",
        "for addr_int, name, kind in [",
    ]
    for addr, name, kind in rows:
        script.append(f'    (0x{addr:x}, "{name}", "{kind}"),')
    script += [
        "]:",
        "    a = base.getNewAddress(addr_int + delta)",
        '    if kind == "function":',
        "        fn = fm.getFunctionAt(a)",
        "        if fn is not None:",
        "            fn.setName(name, SourceType.USER_DEFINED); renamed += 1",
        "    else:",
        "        createLabel(a, name, True); renamed += 1",
        'print("renamed %d symbol(s)" % renamed)',
        "",
    ]
    text = "\n".join(script)
    if out:
        out.write_text(text, encoding="utf-8")
        print(f"wrote {_ST.dim(str(out))}")
    else:
        print(text)
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="rsmm symbols", description="Engine symbol map")
    sub = ap.add_subparsers(dest="cmd")
    sub.add_parser("list", help="print the map grouped by category")
    pr = sub.add_parser("resolve", help="show one symbol")
    pr.add_argument("name")
    sub.add_parser("events", help="list gameplay events mods can subscribe to")
    sub.add_parser("check", help="validate the map (exits non-zero on problems)")
    pg = sub.add_parser("gen", help="generate loader header + python constants")
    pg.add_argument("--check", action="store_true", help="fail if generated files are stale")
    pe = sub.add_parser("ghidra-export", help="emit a Ghidra rename script (or --json table)")
    pe.add_argument("--json", action="store_true", help="emit {addr: name} JSON instead")
    pe.add_argument("-o", "--out", type=Path, default=None, help="write to file instead of stdout")
    pe.add_argument(
        "--include-unverified",
        action="store_true",
        help="also rename symbols whose address is from an older corpus (risky)",
    )
    pa = sub.add_parser("audit", help="diff the loader's runtime resolved_symbols.json "
                                      "against the map (needs a launch with RSMM_DUMP_SYMBOLS=1)")
    pa.add_argument("--dump", type=Path, default=None,
                    help="path to resolved_symbols.json (default: <game>/rsmm/…)")
    args = ap.parse_args(argv)

    smap = load_symbol_map()
    if args.cmd in (None, "list"):
        return _cmd_list(smap)
    if args.cmd == "resolve":
        return _cmd_resolve(smap, args.name)
    if args.cmd == "events":
        return _cmd_events(smap)
    if args.cmd == "check":
        return _cmd_check(smap)
    if args.cmd == "gen":
        return _cmd_gen(smap, args.check)
    if args.cmd == "ghidra-export":
        return _cmd_ghidra_export(smap, args.json, args.out, args.include_unverified)
    if args.cmd == "audit":
        dump = args.dump
        if dump is None:
            from rsmm.engine.paths import DEFAULT_GAME_DIR
            dump = DEFAULT_GAME_DIR / "rsmm" / "resolved_symbols.json"
        return _cmd_audit(smap, dump)
    ap.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
