#!/usr/bin/env python3
"""Mine the engine's ENTITY-VALUE REGISTRY: semantic name -> 32-bit key.

`R.stat.keys` is a dozen hand-RE'd keys plus a few derived families. The engine
itself registers every per-entity value at static init, with a display name, a
description, a default value and its key — so the whole catalog is readable off
the registry functions instead of being discovered one stat at a time.

WHY A STRUCTURAL PARSER AND NOT "the string nearest the immediate". The naive
pairing is off by one registration: a block loads its key into a register long
before it stores it, and several strings (name, description, editor icon) sit
between. That mis-paired `attack_power` with "Attack power basic" and armour
with a neighbour's key — the kind of confident-but-wrong answer the symbol
notes warn about. So this walks the block instead:

    rax = Registry_AllocDef()        # 0x1406f98d0 — starts a registration
    String_Assign(def+0x08, name)    # the display name
    String_Assign(def+0x20, desc)    # description / editor icon path
    EntityValueUnion_CopyAssign(def+0x48, default)
    mov [def+0x6c], <key>            # the key, often via a register
    call Registry_Insert             # 0x1406dea70

and reports (key, name, default) per registration. A key of 0 means the value
is NOT addressable through the store at all — armour is the notable one, which
is why no `R.stat` call can ever move it.

Usage:
    python tools/mine_stat_keys.py [--json out.json] [--verify] [--all]
"""

from __future__ import annotations

import argparse
import json
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import capstone  # noqa: E402
import gen_function_patterns as gen  # noqa: E402

# Three registration shapes, all seen in these functions:
#   A  Register_A(list, key, &name, desc)       key in edx, name staged for r8
#   B  Register_B(key, 0, &name, &category, …)  key in ecx, name staged for r8
#   C  def = AllocDef(); String_Assign(def+8, &name); … mov [def+0x6c], key
REGISTER_A = 0x1406DE840
# B-shape helpers (key in ecx). Several exist — same call shape, different
# value flavours (plain, ratio, toggle) — so they are a set, not one address.
REGISTER_B = (0x140209420, 0x140209550, 0x140209940)
ALLOC = 0x1406F98D0
STRING_ASSIGN = 0x140529860

# Keys the SDK already claims, to catch a parser that drifts by one block.
KNOWN = {
    0x188671A6: "max_health",
    0x15C9296D: "max_health_pct",
    0x15A486C4: "attack_power",
    0x15C7D482: "crit_chance",
    0x15C82D13: "crit_damage",
    0x044DADDE: "move_speed",
    0x15B45D80: "cooldown_reduction",
    0x15C028C2: "life_steal",
    0x1894F1A2: "life_on_hit",
    0x171C27B5: "dream_shards",
    0x187AFD1D: "xp_multiplier",
    0x19BDDB2E: "difficulty_xp_mult",
}


def load_exe(path: str):
    data = Path(path).read_bytes()
    img, secs = gen.parse_pe(data)
    return data, img, secs


def pdata_bounds(data: bytes):
    """(start_rva, end_rva) pairs from the exception table, sorted."""
    pe = struct.unpack_from("<I", data, 0x3C)[0]
    opt, optsz = pe + 24, struct.unpack_from("<H", data, pe + 20)[0]
    nsec = struct.unpack_from("<H", data, pe + 6)[0]
    exc_rva, exc_sz = struct.unpack_from("<II", data, opt + 112 + 3 * 8)
    secs = [struct.unpack_from("<8sIIII", data, opt + optsz + i * 40) for i in range(nsec)]
    off = next(
        ro + exc_rva - va for _, vs, va, rs, ro in secs if va <= exc_rva < va + max(vs, rs)
    )
    return sorted(struct.unpack_from("<II", data, off + i * 12) for i in range(exc_sz // 12))


def cstring(data, img, secs, va: int) -> str | None:
    off = gen.va_to_offset(va, img, secs)
    if off is None:
        return None
    raw = data[off : off + 96].split(b"\0")[0]
    if not 2 <= len(raw) <= 72 or not all(32 <= c < 127 for c in raw):
        return None
    return raw.decode()


def mine(data, img, secs, start: int, end: int):
    """Walk one registry function, yielding {key, name, desc} per registration.

    The canonical call is Registry_RegisterValue(list, key, &name, desc):

        lea  rax, [rip + name]          ; the display name
        mov  [rbp + SLOT], rax          ; staged as a StringDesc {ptr, len|0x80000000}
        mov  dword [rbp + SLOT + 8], 0x80000000 | len
        lea  r9, [rip + desc]           ; description (a plain C string)
        lea  r8, [rbp + SLOT]           ; -> the staged name
        mov  edx, KEY
        call Registry_RegisterValue

    The name is staged BEFORE the call and several strings can sit between two
    registrations, so the slot is what ties a name to its key. Pairing on "the
    nearest string" is off by one whole registration.
    """
    md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_64)
    md.detail = True
    X = capstone.x86
    code = data[gen.va_to_offset(start, img, secs) : gen.va_to_offset(end, img, secs)]

    reg_str: dict[str, str] = {}     # register -> string literal it points at
    imm_reg: dict[str, int] = {}     # register -> last constant (shape C keys)
    slot_str: dict[int, str] = {}    # stack slot -> staged string
    slot_len: dict[int, int] = {}    # stack slot -> declared length
    key = key_c = None
    name_slot = rdx_slot = None
    desc = None
    pending_def, def_name = False, None
    out: list[dict] = []

    def emit(acc, k, name, desc, declared):
        rec = {"key": k & 0xFFFFFFFF, "name": name, "desc": desc}
        # the staged length is a free integrity check on the pairing
        if declared is not None and declared != len(name):
            rec["length_mismatch"] = declared
        acc.append(rec)

    for ins in md.disasm(code, start):
        ops, mn = ins.operands, ins.mnemonic
        if mn == "lea" and len(ops) == 2 and ops[1].type == X.X86_OP_MEM:
            m, dst = ops[1].mem, ins.reg_name(ops[0].reg)
            if m.base == X.X86_REG_RIP:
                s = cstring(data, img, secs, ins.address + ins.size + m.disp)
                reg_str[dst] = s
                if dst == "r9":
                    desc = s
            elif m.base and not m.index:
                # lea r8, [rbp + SLOT] — the argument pointing at a staged name
                if dst == "r8":
                    name_slot = m.disp
                elif dst == "rdx":
                    rdx_slot = m.disp
                reg_str.pop(dst, None)
        elif (mn == "mov" and len(ops) == 2
                and ops[0].type == X.X86_OP_MEM and ops[1].type == X.X86_OP_REG):
            s = reg_str.get(ins.reg_name(ops[1].reg))
            if s:
                slot_str[ops[0].mem.disp] = s
            if pending_def and ops[0].mem.disp == 0x6C:
                k = imm_reg.get(ins.reg_name(ops[1].reg))
                if k is not None and def_name:
                    emit(out, k, def_name, None, None)
                pending_def, def_name = False, None
        elif (mn == "mov" and len(ops) == 2
                and ops[0].type == X.X86_OP_MEM and ops[1].type == X.X86_OP_IMM):
            v = ops[1].imm
            if 0x80000000 <= v <= 0x8000007F:
                slot_len[ops[0].mem.disp - 8] = v & 0x7FFFFFFF
            elif pending_def and ops[0].mem.disp == 0x6C and def_name:
                # shape C with the key inlined: mov [def+0x6c], 0x188671a6
                emit(out, v, def_name, None, None)
                pending_def, def_name = False, None
        elif (mn == "mov" and len(ops) == 2
                and ops[0].type == X.X86_OP_REG and ops[1].type == X.X86_OP_IMM):
            r = ins.reg_name(ops[0].reg)
            imm_reg[r] = ops[1].imm & 0xFFFFFFFF
            if r in ("edx", "rdx"):
                key = ops[1].imm & 0xFFFFFFFF
            elif r in ("ecx", "rcx"):
                key_c = ops[1].imm & 0xFFFFFFFF
        elif (mn == "xor" and len(ops) == 2 and ops[0].type == ops[1].type == X.X86_OP_REG
                and ops[0].reg == ops[1].reg):
            r0 = ins.reg_name(ops[0].reg)
            imm_reg[r0] = 0
            if r0 in ("edx", "rdx"):
                key = 0
            elif r0 in ("ecx", "rcx"):
                key_c = 0
        elif mn == "call" and ops and ops[0].type == X.X86_OP_IMM:
            target = ops[0].imm
            if target == REGISTER_A or target in REGISTER_B:
                k = key if target == REGISTER_A else key_c
                name = slot_str.get(name_slot)
                if name is not None and k is not None:
                    emit(out, k, name, desc, slot_len.get(name_slot))
                key = key_c = name_slot = desc = None
            elif target == ALLOC:
                # shape C: the def is fresh; its name is assigned next
                pending_def, def_name = True, None
            elif target == STRING_ASSIGN and pending_def and def_name is None:
                def_name = slot_str.get(rdx_slot)
    return out


def find_registries(data, img, secs):
    """Every function that calls a registration helper, with its call count.

    Hard-coding the registry entry points misses whole families: the day/night
    values and a couple of others live in their own functions, and a game patch
    is free to add more. Finding the callers instead keeps the catalog whole.
    """
    import bisect

    t = secs[0]
    text = data[t["raw_off"] : t["raw_off"] + t["raw_size"]]
    tva = img + t["rva"]
    bounds = pdata_bounds(data)
    starts = [b[0] for b in bounds]
    hosts: dict[tuple[int, int], int] = {}
    for target in (REGISTER_A, *REGISTER_B, ALLOC):
        i = text.find(b"\xe8")
        while i != -1:
            va = tva + i
            if va + 5 + struct.unpack_from("<i", text, i + 1)[0] == target:
                j = bisect.bisect_right(starts, va - img) - 1
                s_rva, e_rva = bounds[j]
                if va - img < e_rva:
                    fn = (img + s_rva, img + e_rva)
                    hosts[fn] = hosts.get(fn, 0) + 1
            i = text.find(b"\xe8", i + 1)
    return dict(sorted(hosts.items(), key=lambda kv: -kv[1]))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--exe", default=None, help="Ravenswatch.exe (default: the installed game)")
    ap.add_argument("--json", help="write the catalog here")
    ap.add_argument(
        "--verify", action="store_true", help="cross-check keys the SDK already claims"
    )
    ap.add_argument(
        "--all", action="store_true", help="list every registration, not just a summary"
    )
    args = ap.parse_args(argv)

    exe = args.exe
    if exe is None:
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
        from rsmm.engine.paths import default_game_dir  # noqa: E402

        exe = str(Path(default_game_dir()) / "Ravenswatch.exe")

    data, img, secs = load_exe(exe)

    catalog: list[dict] = []
    for (s, e), calls in find_registries(data, img, secs).items():
        found = mine(data, img, secs, s, e)
        for rec in found:
            rec["registry"] = f"0x{s:x}"
        catalog.extend(found)
        missed = calls - len(found)
        note = "" if missed <= 0 else f"   ({missed} skipped: key computed in a loop)"
        print(f"0x{s:x}  {len(found):3d}/{calls} registration(s){note}")

    named = [r for r in catalog if r["name"]]
    unkeyed = [r for r in named if r["key"] == 0]
    print(
        f"\n{len(catalog)} registrations, {len(named)} named, "
        f"{len(unkeyed)} with key 0 (not addressable)"
    )

    if args.verify:
        by_key = {r["key"]: r for r in named}
        ok = bad = 0
        print("\ncross-check against R.stat.keys:")
        for key, sdk in sorted(KNOWN.items()):
            rec = by_key.get(key)
            if rec is None:
                print(f"  [MISS] 0x{key:08x} {sdk}: not registered here")
                bad += 1
            else:
                print(f"  [ ok ] 0x{key:08x} {sdk:20s} = {rec['name']!r}")
                ok += 1
        print(f"  {ok} matched, {bad} missing")

    if args.all:
        print("\ncatalog:")
        for r in sorted(named, key=lambda r: r["name"].lower()):
            print(f"  0x{r['key']:08x}  {r['name']!r}")

    if args.json:
        Path(args.json).write_text(json.dumps(catalog, indent=1) + "\n")
        print(f"\nwrote {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
