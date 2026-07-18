#!/usr/bin/env python3
"""Emit a Ghidra script that applies vtable STRUCT types from vftables.jsonl.

The #1 reading-cost bottleneck (measured 2026-07-17): 55k `code *` virtual-call
sites in the corpus — every function near a hook has ~7 opaque
`(**(code **)(*obj + 0xNN))()` dispatches. Offline resolution is IMPOSSIBLE
(measured: 0/55k statically resolvable — the vtable pointer flows through
struct/memory, not local vars, so only Ghidra's decompiler with applied struct
TYPES can follow it). data/vftables.jsonl already holds 5993 vtables with their
slot functions, sitting unused.

This generates a Ghidra Jython script that runs THREE phases:
  1. per vtable, build a struct `<Class>_vtbl` whose fields are pointers named
     by each slot's function (semantic name from data/symbols.json where known,
     else the FUN_ name) and stamp it on the vtable's data address (rebased by
     image-base delta like ghidra-export) — names the slots;
  2. per vtable, build an object-layout struct `<Class>` whose field 0 is
     `vftable: <Class>_vtbl*` (only +0 is known; a vcall needs nothing more);
  3. retype param_1 (this) of every slot function that lives in EXACTLY ONE game
     vtable to `<Class> *`, so its `(**(code**)(*this+0xNN))` finally decompiles
     as `this->vftable->SlotName()` instead of `code *`.

Phase 3 is the piece that actually reduces the `code *` count. Stamping structs
(phases 1-2) alone does NOT — measured: ApplyModifierEvent 11 code* -> 11,
GiveHandler 20 -> 20, because the decompiler can't follow the vtbl pointer until
the OBJECT param is typed.

    tools/gen_ghidra_vtables.py --game-only -o rsmm_vtables.py

Run the emitted script in Ghidra headless (project must be UNLOCKED — close the
GUI/MCP or process a .rep copy):
    analyzeHeadless <projdir> <proj> -process -noanalysis \\
      -scriptPath <dir> -postScript rsmm_vtables.py rsmm_vtables.json
`--game-only` keeps just oC/oI/oe/Stormancer engine classes (skips ~2400 CRT/std
vtables); `--named-only` restricts to vtables with >=1 slot our symbol map names.
Re-runnable / idempotent (skips a struct that already exists).

HONEST SCOPE (measured 2026-07-18): 3331 game vtables -> 2834 object structs and
12781 unambiguous this-retypes. Of those funcs, 666 actually vcall through
param_1, resolving ~1028 vcall SITES — vs ~55k corpus-wide. So this is the
mechanical ~2% that param_1-typing alone can reach; the rest vcall through OTHER
objects (fields/params) whose types we don't know beyond +0, and full call-
TARGET names still resolve only for slots named in data/symbols.json. Typing the
object structure is done here; naming slot functions + typing non-this object
params are the separate coverage grinds.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
VFT = REPO / "docs" / "_re" / "out_new" / "vftables.jsonl"
DEC = REPO / "docs" / "_re" / "out_new" / "decompiled_new.jsonl"
SYM = REPO / "data" / "symbols.json"
PREFERRED_BASE = 0x140000000


def _addr(a) -> int:
    return int(a, 16) if isinstance(a, str) else int(a)


def _ident(s: str, fallback: str) -> str:
    """A valid, readable C identifier for a struct/field name."""
    s = re.sub(r"::|<|>|,|\s", "_", s)
    s = re.sub(r"[^0-9A-Za-z_]", "_", s)
    s = re.sub(r"_+", "_", s).strip("_")
    if not s or s[0].isdigit():
        s = fallback + ("_" + s if s else "")
    return s


def _vtbl_struct_name(sym: str, addr) -> str:
    """`oCFoo::vftable` -> `oCFoo_vtbl` (the struct name used by every phase)."""
    cls = re.sub(r"(::vftable|_vftable)$", "", sym) if sym else f"vtbl_{addr}"
    return _ident(cls, f"vtbl_{addr}") + "_vtbl"


def _semantic_names():
    """slot-function VA -> semantic symbol name (from symbols.json raw)."""
    out = {}
    for s in json.loads(SYM.read_text())["symbols"]:
        raw = s.get("raw", "")
        if raw.startswith("FUN_"):
            out[int(raw[4:], 16)] = s["name"]
    return out


def load_vtables():
    vts = []
    for ln in VFT.open():
        try:
            d = json.loads(ln)
        except json.JSONDecodeError:
            continue
        vts.append(d)
    return vts


# Engine/game class prefixes worth typing — skips std::/pplx::/rxcpp:: and other
# C++ runtime/library vtables that carry no RE value (~2400 of 5993).
_GAME_PREFIXES = ("oC", "oI", "oe", "Stormancer", "o_")


def build(limit: int | None, named_only: bool, game_only: bool):
    sem = _semantic_names()
    vts = load_vtables()
    entries = []  # (vt_addr, struct_name, [(field_name, slot_va)], n_named)
    # slot_va -> set of vtbl struct names carrying it. A slot in exactly ONE
    # game vtable has an UNAMBIGUOUS this-type, so its owner function's param_1
    # can be safely retyped to that class (see build_retypes).
    slot_owners: dict[int, set[str]] = {}
    for d in vts:
        addr = d.get("addr")
        sym = d.get("sym", "")
        slots = d.get("slots", [])
        if not addr or not slots:
            continue
        if game_only and not sym.startswith(_GAME_PREFIXES):
            continue
        # sym is the RTTI label `<Class>_vftable` / `<Class>::vftable`; recover
        # the bare class so structs read `oCFoo` (object) + `oCFoo_vtbl` (vtable),
        # not `oCFoo_vftable_vtbl`.
        sname = _vtbl_struct_name(sym, addr)
        fields = []
        used = set()
        n_named = 0
        for i, sl in enumerate(slots):
            va = _addr(sl.get("va", "0x0"))
            semn = sem.get(va)
            if semn:
                n_named += 1
            raw = semn or sl.get("name") or f"slot_{i}"
            fn = _ident(raw, f"slot_{i}")
            if fn in used:
                fn = f"{fn}_{i}"
            used.add(fn)
            fields.append((fn, va))
            slot_owners.setdefault(va, set()).add(sname)
        if named_only and n_named == 0:
            continue
        entries.append((_addr(addr), sname, fields, n_named))
    entries.sort(key=lambda e: -e[3])  # most-named first (useful ones on top)
    if limit:
        entries = entries[:limit]
    return entries, slot_owners


def _obj_name(vtbl_name: str) -> str:
    """Object-layout struct name for a `<Class>_vtbl` struct name."""
    return vtbl_name[:-5] if vtbl_name.endswith("_vtbl") else vtbl_name + "_obj"


_FIELD_OFF = re.compile(r"param_1 \+ (0x[0-9a-f]+|\d+)\b")
_MAX_OBJ_SIZE = 0x4000


def mine_obj_sizes(retypes):
    """Class -> byte size, from the largest `param_1 + 0xNN` seen in its methods.

    Why size matters: Ghidra SCALES pointer arithmetic by the pointee size, so
    an 8-byte `<Class>` (vftable only) renders a real `param_1 + 0x288` byte
    offset as `param_1 + 0x51` — every offset silently divided by 8, which is
    poison for a codebase whose RE notes are all byte offsets. Sizing the struct
    past the offset makes it render as `->field_0x288` instead.

    Only observed offsets are used; a class with none keeps the bare 8 bytes
    rather than getting an invented size. `field_0xNN` names are placeholders
    derived from access sites, NOT from RTTI — they name a location, not a
    meaning.
    """
    if not DEC.exists():
        return {}
    rt = dict(retypes)
    sizes = {}
    for ln in DEC.open():
        try:
            d = json.loads(ln)
        except json.JSONDecodeError:
            continue
        obj = rt.get(_addr(d["addr"]))
        if obj is None:
            continue
        for m in _FIELD_OFF.findall(d.get("code", "")):
            off = int(m, 16) if m.startswith("0x") else int(m)
            if off > _MAX_OBJ_SIZE:
                continue        # array indexing / bogus, not a field offset
            if off + 8 > sizes.get(obj, 0):
                sizes[obj] = off + 8
    return sizes


def build_objs_and_retypes(entries, slot_owners):
    """The piece that actually kills `code *`.

    Stamping a vtbl struct onto vtable DATA names the slots but leaves every
    caller's vcall as `(**(code**)(*obj+0xNN))` — the decompiler can't follow
    the pointer until the OBJECT is typed. So we also:
      * emit an object-layout struct `<Class>` whose field 0 is `vftable:
        <Class>_vtbl*` (we only know +0; that's all a vcall needs), and
      * retype param_1 (this) of every slot function that lives in EXACTLY ONE
        game vtable to `<Class> *`. Ambiguous slots (shared vtables, thunks) are
        skipped — a wrong this-type is worse than none.

    Returns (objs, retypes):
      objs    = [(obj_name, vtbl_name), ...]           # struct <Class>{vftable}
      retypes = [(func_va, obj_name), ...]             # set param_1 = <Class>*
    Measured resolvable population (2026-07-18): 666 funcs / 1028 vcall sites.
    """
    vtbl_names = {sname for _a, sname, _f, _n in entries}
    objs = [(_obj_name(sn), sn) for sn in sorted(vtbl_names)]
    retypes = []
    for va, owners in slot_owners.items():
        owners = owners & vtbl_names  # only vtables we actually emit structs for
        if len(owners) != 1:
            continue  # ambiguous or filtered-out — don't guess a this-type
        (owner,) = tuple(owners)
        retypes.append((va, _obj_name(owner)))
    retypes.sort()
    return objs, retypes


# A ctor/dtor is recognisable in the decompiled corpus by the one thing only it
# does: assign a vtable symbol into the object. `*param_1 = &oCFoo::vftable;`
_VFT_ASSIGN = re.compile(r"=\s*&?([A-Za-z_][\w:<>,]*::vftable|[A-Za-z_][\w<>,]*_vftable)")


def build_ctors(entries):
    """`this`/return typing for constructors — the piece phase 3 can't reach.

    Phase 3 only helps a function that vcalls through its OWN param_1. The much
    larger population vcalls through a LOCAL (`plVar1 = FUN_x(); (**(code
    **)(*plVar1 + 0x30))(plVar1)`), which stays `code *` because nothing tells
    the decompiler what `FUN_x` returned. Constructors are where that type is
    knowable: a ctor is the function that writes `<Class>::vftable` into the
    object, and it returns that object. So typing a ctor's param_1 AND return as
    `<Class> *` propagates the type into every caller's local, and their vcalls
    resolve — the cascade phase 3 cannot produce.

    Only functions that mention EXACTLY ONE game vtable qualify; a function
    touching several (inlined sub-object ctors, dtor groups) has no single
    unambiguous `this`, and a wrong this-type is worse than none. The store must
    also land in `param_1` — 152 of the loose matches turned out to be GLOBAL
    static-initialisers (`_DAT_14143d8e0 = oe::MyNaconSteam::vftable`, a
    `void(void)` with no object param at all), where forcing a `this` param
    invents a parameter the function does not have.

    Returns [(func_va, obj_name), ...]. Needs the decompiled corpus; returns []
    when it is absent (the corpus is a large RE artifact, not always present).
    """
    return _mine_corpus(entries, ())[0]


# `*param_1 = &oCFoo::vftable;` / `*(longlong *)(param_1 + 8) = ...` — the store
# must be through param_1 for the function to be a ctor with a real `this`.
_VFT_INTO_THIS = re.compile(
    r"\*(?:\(\w+ \*+\))?\(?param_1(?:\s*\+\s*(?:0x[0-9a-f]+|\d+))?\)?\s*=\s*&?"
    r"([A-Za-z_][\w:<>,]*::vftable|[A-Za-z_][\w<>,]*_vftable)")
_RETURNS_THIS = re.compile(r"\breturn param_1;")


def _mine_corpus(entries, retypes):
    """One pass over the decompiled corpus -> (ctors, ret_self).

    ctors    = [(va, obj)] ctor/dtor: stores exactly one game vftable INTO param_1.
    ret_self = [(va, obj)] already-this-typed funcs whose body is `return param_1;`,
               so the RETURN type is known for free to equal the `this` type.

    ret_self matters more than it looks: corpus-wide only 10.8% of the 55235
    vcall sites go through param_1, while 44.2% go through a LOCAL — and a local
    only gets a type when the callee that produced it has a typed return.
    """
    if not DEC.exists():
        return [], []
    want = {}  # vtbl struct name -> obj struct name
    for _a, sname, _f, _n in entries:
        want[sname] = _obj_name(sname)
    rt = dict(retypes)
    ctors, ret_self = [], []
    for ln in DEC.open():
        try:
            d = json.loads(ln)
        except json.JSONDecodeError:
            continue
        code = d.get("code", "")
        va = _addr(d["addr"])
        if "vftable" in code:
            objs = {want[n] for n in
                    (_vtbl_struct_name(s, "") for s in _VFT_INTO_THIS.findall(code))
                    if n in want}
            if len(objs) == 1:
                ctors.append((va, objs.pop()))
        if va in rt and _RETURNS_THIS.search(code):
            ret_self.append((va, rt[va]))
    ctors.sort()
    ret_self.sort()
    return ctors, ret_self


# Fixed Jython loader — reads its table from a sidecar JSON passed as the
# postScript arg. The data is NOT inlined: thousands of structs as a Python
# literal blows Jython's 64KB per-method bytecode limit ("Module or method too
# large"). The data JSON is now a dict: {vtbls, objs, retypes}.
_LOADER = '''# -*- coding: utf-8 -*-
# GENERATED loader for tools/gen_ghidra_vtables.py. Reads its data JSON (same
# basename + .json) or the path given as the postScript arg. Three phases:
#   1. create a <Class>_vtbl struct per game vtable + stamp it on the vtable
#      data (names the slots),
#   2. create a <Class> object struct whose field 0 is vftable:<Class>_vtbl*,
#   3. retype param_1 (this) of each unambiguous slot function to <Class>* so
#      its `(**(code**)(*this+0xNN))` vcalls decompile as this->vftable->Slot().
# Idempotent. Run headless (project must be UNLOCKED):
#   analyzeHeadless <proj-dir> <proj> -process -noanalysis \\
#     -scriptPath <dir> -postScript rsmm_vtables.py rsmm_vtables.json
import json
from ghidra.program.model.data import (StructureDataType, PointerDataType,
    CategoryPath, DataTypeConflictHandler)
from ghidra.program.model.symbol import SourceType
from ghidra.program.model.pcode import HighFunctionDBUtil
from ghidra.app.decompiler import DecompInterface
from ghidra.util.task import ConsoleTaskMonitor

args = getScriptArgs()
if args:
    path = args[0]
else:
    src = getSourceFile().getAbsolutePath()
    path = src[:-3] + ".json" if src.endswith(".py") else src + ".json"
data = json.load(open(path))
vtbls = data['vtbls']
objs = data.get('objs', [])
retypes = data.get('retypes', [])
ctors = data.get('ctors', [])
ret_self = data.get('ret_self', [])

dtm = currentProgram.getDataTypeManager()
fm = currentProgram.getFunctionManager()
base = currentProgram.getImageBase()
pref = base.getNewAddress(__PREF__)
delta = base.getOffset() - pref.getOffset()
cat = CategoryPath('/rsmm_vtables')
ptr = PointerDataType.dataType


def get_or_make_struct(sname):
    st = dtm.getDataType(cat, sname)
    return st, (st is None)


# Phase 1: vtbl structs + stamp on vtable data.
made = stamped = 0
for vt_addr, sname, fields in vtbls:
    st, is_new = get_or_make_struct(sname)
    if is_new:
        st = StructureDataType(cat, sname, 0)
        for fn, va in fields:
            st.add(ptr, 8, str(fn), '0x%x' % va)
        st = dtm.addDataType(st, DataTypeConflictHandler.REPLACE_HANDLER)
        made += 1
    a = base.getNewAddress(vt_addr + delta)
    try:
        clearListing(a, a.add(st.getLength() - 1))
        createData(a, st)
        stamped += 1
    except Exception, e:
        print('skip vtbl 0x%x: %s' % (vt_addr, e))
print('phase1 vtbl structs: %d created, %d stamped' % (made, stamped))

# Phase 2: object-layout structs {vftable: <Class>_vtbl*} + cache <Class>* ptr.
obj_ptr = {}
omade = 0
for obj_name, vtbl_name, obj_size in objs:
    ost, is_new = get_or_make_struct(obj_name)
    if is_new:
        vst = dtm.getDataType(cat, vtbl_name)
        # Size the struct past the largest observed field offset: Ghidra scales
        # pointer arithmetic by pointee size, so an 8-byte object turns a real
        # `+0x288` byte offset into a misleading `+0x51`.
        ost = StructureDataType(cat, obj_name, obj_size)
        vt_ptr = PointerDataType(vst) if vst is not None else ptr
        ost.replaceAtOffset(0, vt_ptr, 8, 'vftable', '')
        ost = dtm.addDataType(ost, DataTypeConflictHandler.REPLACE_HANDLER)
        omade += 1
    obj_ptr[obj_name] = PointerDataType(ost)
print('phase2 object structs: %d created' % omade)

# Phases 3-5 (one pass). Slot funcs carry NO committed formal params — auto-
# analysis leaves the decompiler's this/args uncommitted, so getParameter(0) is
# None. The WRONG fix (used until 2026-07-18, and it damaged a real project) is
# updateFunction(..., DYNAMIC_STORAGE_FORMAL_PARAMS, [this]): that commits
# EXACTLY ONE parameter and locks storage, DELETING every other argument —
# `f(longlong param_1, longlong *param_2)` became `f(<Class> *this)` with
# param_2 demoted to a bare `in_RDX` and all call arguments erased.
#
# Correct fix: decompile the function, commit ALL of the decompiler's derived
# parameters via HighFunctionDBUtil.commitParamsToDatabase, and only THEN
# retype parameter 0 (plus, for ctors/return-this funcs, the return). Nothing
# is invented: a function whose decompiled form has no parameters is skipped.
#
# The three target sets overlap (ret_self is a subset of retypes, and ~800
# ctors are in it too), so they are merged and each function is decompiled once
# — ~13k decompiles, several minutes, vs 17.6k if run separately.
targets = {}
for func_va, obj_name in retypes:
    targets[func_va] = [obj_name, False]
for func_va, obj_name in list(ctors) + list(ret_self):
    t = targets.get(func_va)
    if t is None:
        targets[func_va] = [obj_name, True]
    else:
        t[1] = True          # same class, but now the RETURN is known too

dec = DecompInterface()
dec.openProgram(currentProgram)
mon = ConsoleTaskMonitor()
RET_COMMIT = HighFunctionDBUtil.ReturnCommitOption.NO_COMMIT

typed = ret_typed = missing = noparam = nodecomp = badp0 = failed = 0
for func_va in sorted(targets):
    obj_name, want_ret = targets[func_va]
    func = fm.getFunctionAt(base.getNewAddress(func_va + delta))
    if func is None:
        missing += 1
        continue
    objptr = obj_ptr[obj_name]
    try:
        res = dec.decompileFunction(func, 60, mon)
        if not res.decompileCompleted():
            nodecomp += 1
            continue
        hf = res.getHighFunction()
        if hf is None:
            nodecomp += 1
            continue
        # commit the decompiler's OWN parameter list first — this is the whole
        # point: keep param_2, param_3, ... instead of truncating to one.
        HighFunctionDBUtil.commitParamsToDatabase(hf, True, RET_COMMIT,
                                                 SourceType.USER_DEFINED)
        p0 = func.getParameter(0)
        if p0 is None:
            noparam += 1        # genuinely no object param — do NOT invent one
            continue
        if p0.getDataType().getLength() != 8:
            badp0 += 1          # first arg isn't pointer-sized; not a `this`
            continue
        p0.setDataType(objptr, SourceType.USER_DEFINED)
        typed += 1
        if want_ret:
            func.setReturnType(objptr, SourceType.USER_DEFINED)
            ret_typed += 1
    except Exception, e:
        failed += 1
        if failed <= 20:
            print('skip 0x%x: %s' % (func_va, e))
print('phases3-5: %d this-typed (%d also return-typed), %d no-func, '
      '%d no-params, %d non-ptr-param0, %d decompile-fail, %d failed'
      % (typed, ret_typed, missing, noparam, badp0, nodecomp, failed))
'''


def emit_loader() -> str:
    return _LOADER.replace("__PREF__", hex(PREFERRED_BASE))


def emit_data(entries, objs, retypes, ctors, ret_self) -> str:
    return json.dumps({
        "vtbls": [[vt, sname, [[fn, va] for fn, va in fields]]
                  for vt, sname, fields, _n in entries],
        "objs": objs,
        "retypes": [[va, obj] for va, obj in retypes],
        "ctors": [[va, obj] for va, obj in ctors],
        "ret_self": [[va, obj] for va, obj in ret_self],
    })


def emit_mcp_json(entries) -> str:
    """{vtable_addr_hex: struct_name} for the Ghidra MCP `rename_data` bridge.

    MCP cannot create struct datatypes (no DataTypeManager API — only
    rename_data / set_function_prototype / set_local_variable_type), so the
    struct TYPING stays a Jython job (default output). What MCP *can* do is name
    each vtable's data label so the vtables are identified in the live DB; this
    table drives that, symmetric with `rsmm symbols ghidra-export --json`.
    """
    # data label = the class vftable name: strip the `_vtbl` struct suffix and
    # re-attach `_vftable` (the RTTI convention for a vtable data address).
    def label(n):
        cls = n[:-5] if n.endswith("_vtbl") else n
        return cls + "_vftable"
    return json.dumps({f"0x{vt:x}": label(name) for vt, name, _f, _n in entries}, indent=2)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("-o", "--out", type=Path, default=None,
                    help="write the output here (default: stdout)")
    ap.add_argument("--limit", type=int, default=None, help="cap number of vtables")
    ap.add_argument("--game-only", action="store_true",
                    help="only oC/oI/oe/Stormancer game-class vtables (skip CRT/std)")
    ap.add_argument("--named-only", action="store_true",
                    help="only vtables with >=1 semantically-named slot")
    ap.add_argument("--mcp-json", action="store_true",
                    help="emit {vtable_addr: name} for the MCP rename_data bridge "
                         "instead of the Jython struct script (MCP can't make structs)")
    a = ap.parse_args(argv)

    import sys
    entries, slot_owners = build(a.limit, a.named_only, a.game_only)
    objs, retypes = build_objs_and_retypes(entries, slot_owners)
    ctors, ret_self = _mine_corpus(entries, retypes)
    sizes = mine_obj_sizes(retypes)
    objs = [(o, v, max(8, sizes.get(o, 8))) for o, v in objs]
    total_slots = sum(len(f) for _, _, f, _ in entries)
    named_slots = sum(n for _, _, _, n in entries)

    if a.mcp_json:
        text = emit_mcp_json(entries)
        (a.out.write_text(text, encoding="utf-8") if a.out else print(text))
        where = str(a.out) if a.out else "stdout"
    elif a.out:
        # loader .py + sidecar .json (data can't be inlined — Jython method limit)
        a.out.write_text(emit_loader(), encoding="utf-8")
        data_path = a.out.with_suffix(".json")
        data_path.write_text(emit_data(entries, objs, retypes, ctors, ret_self),
                             encoding="utf-8")
        where = f"{a.out} + {data_path}"
    else:
        print(emit_loader())
        where = "stdout (loader only; use -o to also write the .json data)"

    print(f"vtable structs: {len(entries)}  slots: {total_slots}  "
          f"semantically-named slots: {named_slots}  "
          f"obj structs: {len(objs)}  this-retypes: {len(retypes)}  "
          f"ctors: {len(ctors)}  ret-self: {len(ret_self)}  "
          f"sized objs: {sum(1 for _o, _v, sz in objs if sz > 8)}  -> {where}",
          file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
