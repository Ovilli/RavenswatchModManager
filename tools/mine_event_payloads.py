#!/usr/bin/env python3
"""Recover oCGameNamedEvent payload layouts from the shipped exe.

The gameplay bus publishes ~150 event NAMES, but the loader could only decode
three of them; everything else reached Lua as a bare envelope (dispatcher,
entity, seq). This recovers the rest — and, just as usefully, establishes how
many of them have a payload at all.

They mostly don't. MSVC RTTI names every polymorphic class in the binary, and
there are only ~18 event classes past the `oCGameNamedEvent` base. Every other
event name is dispatched AS the base class: header only (vftable, name string,
interned id), no fields. That is a property of the engine, not a gap in our
analysis, and it means "decode the remaining 147" is the wrong goal — the
right one is "decode the 18 classes that carry data, and say so for the rest".

Method, per class:

  1. RTTI type descriptor  ->  complete object locator  ->  vftable.
     The COL pointer sits one qword BEFORE the vftable, which is what lets us
     go from a demangled class name to a runtime vftable address.
  2. Find the constructor: a `lea rax, [rip+vftable]` whose value is stored
     into `[this]`. Track which register holds `this`.
  3. Walk the ctor and record every `mov [this+disp], src` past the 0x38-byte
     event header. The store WIDTH gives the field type (dword/qword), and an
     `xmm` source marks it as float.
  4. Cross-reference the event-name literals the ctor references, so a class
     can be tied to the names it is dispatched under.

Field NAMES are not recoverable this way — only offsets, widths and
float-ness. So the output is deliberately mechanical (`f40`, `p48`), and
semantic names are only attached where an offset is already confirmed by
hand-RE (see CONFIRMED). Inventing meaning here would be worse than useless.

Validation is built in: --verify checks the layouts we established by hand
(NETWORK_DAMAGE, GIVE_MAGICAL_OBJECT) come back out of the automated pass.

Usage:
  python tools/mine_event_payloads.py                 # report
  python tools/mine_event_payloads.py --verify        # assert known layouts
  python tools/mine_event_payloads.py --json out.json
"""

from __future__ import annotations

import argparse
import json
import re
import struct
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from mine_event_names import PE, _default_exe  # noqa: E402

# The event header every oCGameNamedEvent carries: vftable @+0, state @+8,
# name oCString @+0x20, interned id @+0x30. Payload starts after it.
HEADER_END = 0x38

# Layouts established by hand in docs/_re/kinds/events-bus.md. The miner must
# reproduce these; they are the acceptance test, not an input.
CONFIRMED: dict[str, dict[int, str]] = {
    "oCGameNamedEventNetworkDamage": {0x40: "value", 0x48: "source_id"},
    "NamedEventGiveMagicalObject": {0x50: "mo_guid_lo", 0x58: "mo_guid_hi"},
}

# Classes that are not dispatched as events (listeners, settings blobs,
# components). Excluded so the report is about payloads mods can receive.
SKIP_RE = re.compile(
    r"Tester|Listener|Settings|PersistentData|Sender|Receiver|SceneContext"
    r"|ConditionData|Cpnt"
)


def demangle(raw: str) -> str:
    """`.?AVNamedEventGiveMagicalObject@dt@oe@@` -> `NamedEventGiveMagicalObject`."""
    body = raw[4:]
    if body.endswith("@@"):
        body = body[:-2]
    return body.split("@")[0]


class Rtti:
    """Maps RTTI class names to vftable addresses."""

    def __init__(self, pe: PE):
        self.pe = pe
        self.base = pe.image_base
        self.rdata = pe.section(".rdata")
        self.data = pe.section(".data")
        self._td_by_name: dict[str, int] = {}
        self._scan_type_descriptors()

    def _read(self, va: int, n: int) -> bytes | None:
        for sec in self.pe.sections:
            if sec["va"] <= va < sec["va"] + sec["rawsize"]:
                off = sec["raw"] + (va - sec["va"])
                return self.pe.data[off : off + n]
        return None

    def _scan_type_descriptors(self) -> None:
        blob = self.pe.data
        for m in re.finditer(rb"\.\?AV[A-Za-z0-9_@?$]{3,120}@@\x00", blob):
            raw_off = m.start()
            # The name lives at TypeDescriptor+0x10.
            td_off = raw_off - 0x10
            va = None
            for sec in self.pe.sections:
                if sec["raw"] <= td_off < sec["raw"] + sec["rawsize"]:
                    va = sec["va"] + (td_off - sec["raw"])
                    break
            if va is None:
                continue
            self._td_by_name[m.group(0)[:-1].decode()] = va

    def vftables(self) -> dict[str, list[int]]:
        """class name -> [vftable VA, ...] (a class can have several)."""
        out: dict[str, list[int]] = {}
        # Index every COL by the type descriptor it names, then find pointers
        # to those COLs; the vftable starts one qword later.
        td_rva_to_name = {
            va - self.base: name for name, va in self._td_by_name.items()
        }
        col_va_to_name: dict[int, str] = {}
        for sec in (self.rdata, self.data):
            if not sec:
                continue
            blob = self.pe.data[sec["raw"] : sec["raw"] + sec["rawsize"]]
            for off in range(0, len(blob) - 24, 4):
                sig, _o, _cd, td_rva = struct.unpack_from("<IIII", blob, off)
                if sig != 1:                       # x64 COL signature
                    continue
                name = td_rva_to_name.get(td_rva)
                if name:
                    col_va_to_name[sec["va"] + off] = name

        for sec in (self.rdata, self.data):
            if not sec:
                continue
            blob = self.pe.data[sec["raw"] : sec["raw"] + sec["rawsize"]]
            for off in range(0, len(blob) - 8, 8):
                ptr, = struct.unpack_from("<Q", blob, off)
                name = col_va_to_name.get(ptr)
                if name:
                    out.setdefault(name, []).append(sec["va"] + off + 8)
        return out


def function_ranges(pe: PE) -> list[tuple[int, int]]:
    """(start, end) VAs from .pdata's RUNTIME_FUNCTION table.

    Exact function bounds matter here: a linear walk of N bytes from the
    vftable store runs off the end of the constructor and into whatever code
    follows, which is how the base class first came back with 32 "fields"
    reaching +0x238.
    """
    sec = pe.section(".pdata")
    if not sec:
        return []
    blob = pe.data[sec["raw"] : sec["raw"] + sec["rawsize"]]
    out = []
    for off in range(0, len(blob) - 12, 12):
        begin, end, _unwind = struct.unpack_from("<III", blob, off)
        if begin and end > begin:
            out.append((pe.image_base + begin, pe.image_base + end))
    out.sort()
    return out


def _containing(ranges: list[tuple[int, int]], va: int) -> tuple[int, int] | None:
    import bisect
    i = bisect.bisect_right(ranges, (va, 1 << 62)) - 1
    if i >= 0 and ranges[i][0] <= va < ranges[i][1]:
        return ranges[i]
    return None


def ctor_field_stores(pe: PE, text, vft: int, ranges, limit: int = 0x400):
    """Find code storing `vft` into an object and collect its field writes.

    Handles both shapes the engine uses: a real constructor writing through a
    register `this`, and an event built inline in a stack frame (the vftable
    goes to `[rsp+K]` and the fields follow at `[rsp+K+disp]`) — the latter is
    how NETWORK_DAMAGE is emitted, and missing it is why an earlier pass could
    not reproduce its hand-RE'd +0x40/+0x48.

    Returns (fields, name_refs): fields maps offset -> {"width", "float"},
    name_refs is the set of rip-relative targets the code also loaded (used to
    tie a class to its event-name literals).
    """
    import capstone

    md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_64)
    md.detail = True

    blob = pe.data[text["raw"] : text["raw"] + text["rawsize"]]
    base = text["va"]

    # Sites doing `lea r64, [rip+disp]` == vft.
    sites: list[int] = []
    i = 0
    while i < len(blob) - 7:
        j = blob.find(b"\x8d", i)
        if j < 0 or j >= len(blob) - 7:
            break
        rex, modrm = (blob[j - 1] if j else 0), blob[j + 1]
        if rex in (0x48, 0x4C) and (modrm & 0xC7) == 0x05:
            disp, = struct.unpack_from("<i", blob, j + 2)
            if base + (j - 1) + 7 + disp == vft:
                sites.append(j - 1)
        i = j + 1

    MEM = capstone.x86.X86_OP_MEM
    per_site: list[dict[int, dict]] = []
    name_refs: set[int] = set()
    for site in sites:
        site_va = base + site
        rng = _containing(ranges, site_va)
        if rng:
            start, end = rng
            code = blob[start - base : end - base]
            pc = start
        else:
            code, pc = blob[site : site + limit], site_va

        # `this` is either a register (base=reg, anchor=0) or a stack slot
        # (base=rsp/rbp, anchor=the displacement the vftable went to). The
        # vftable LEA names a register; the store of THAT register is what
        # anchors the object, which is order-independent — keying off "the
        # store immediately follows the lea" missed every ctor with a couple
        # of instructions in between.
        fields: dict[int, dict] = {}
        this_base, anchor, vft_reg = None, 0, None
        for ins in md.disasm(code, pc):
            m = ins.mnemonic
            ops = ins.operands
            if m == "lea" and len(ops) == 2 and ops[1].type == MEM \
                    and ops[1].mem.base == capstone.x86.X86_REG_RIP:
                # Compute the target from the operand. (Parsing it out of
                # op_str does not work: capstone prints "[rip + 0x1234]" with
                # no resolved-address comment, so every parse raised and the
                # anchor register was never learned.)
                tgt = ins.address + ins.size + ops[1].mem.disp
                name_refs.add(tgt)
                if tgt == vft:
                    vft_reg = ops[0].reg
                continue
            if len(ops) != 2:
                continue
            dst, src = ops[0], ops[1]

            if (this_base is None and m == "mov" and dst.type == MEM
                    and vft_reg is not None and src.reg == vft_reg):
                this_base, anchor = dst.mem.base, dst.mem.disp
                continue

            if this_base is None or dst.type != MEM or dst.mem.base != this_base:
                continue
            off = dst.mem.disp - anchor
            if off < HEADER_END or off > 0x200:
                continue
            if m in ("movss", "movsd"):
                fields[off] = {"width": 4 if m == "movss" else 8, "float": True}
            elif m in ("mov", "movzx", "movsx"):
                fields[off] = {"width": dst.size, "float": False}
        if this_base is not None:
            per_site.append(fields)

    # A field is real if ANY construction site writes it: the constructor
    # initialises some fields and the EMITTER fills the rest in place (the
    # give path writes the object GUID after construction, which is why a
    # ctor-only or majority-vote pass cannot see it).
    #
    # The cost of a union is the BASE class, whose vftable every derived
    # constructor stores first — it would inherit every subclass's fields.
    # Site count separates them: a leaf event class is built in a handful of
    # places, a base class in dozens. The caller applies that cutoff, so it
    # gets the count back rather than a silently-filtered answer.
    merged: dict[int, dict] = {}
    for f in per_site:
        merged.update(f)
    return merged, name_refs, len(per_site)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--exe", type=Path, default=None)
    ap.add_argument("--json", type=Path, default=None)
    ap.add_argument("--verify", action="store_true")
    ap.add_argument("--max-sites", type=int, default=30,
                    help="skip classes constructed in more places than this "
                         "(that is what a base class looks like: its vftable "
                         "is stored by every derived ctor, so a union of the "
                         "writes inherits all their fields)")
    args = ap.parse_args()

    exe = args.exe or _default_exe()
    if not exe or not exe.exists():
        print("Ravenswatch.exe not found (pass --exe PATH)", file=sys.stderr)
        return 2

    pe = PE(exe.read_bytes())
    text = pe.section(".text")
    rtti = Rtti(pe)
    vfts = rtti.vftables()
    ranges = function_ranges(pe)

    event_classes = {
        demangle(raw): vs
        for raw, vs in vfts.items()
        if ("NamedEvent" in raw or "GameEvent" in raw) and not SKIP_RE.search(raw)
    }
    print(f"{exe}")
    print(f"  RTTI classes with a vftable: {len(vfts)}")
    print(f"  event payload classes:       {len(event_classes)}\n")

    results: dict[str, dict] = {}
    for cls in sorted(event_classes):
        merged: dict[int, dict] = {}
        sites_total = 0
        for vft in event_classes[cls]:
            fields, _, n = ctor_field_stores(pe, text, vft, ranges)
            merged.update(fields)
            sites_total += n
        base_like = sites_total > args.max_sites
        results[cls] = {
            "vftables": [f"0x{v:x}" for v in sorted(event_classes[cls])],
            "sites": sites_total,
            "base_like": base_like,
            "fields": {} if base_like else
                      {f"0x{off:x}": info for off, info in sorted(merged.items())},
        }
        if base_like:
            desc = f"(base class — {sites_total} construction sites, skipped)"
        else:
            desc = ", ".join(
                f"+0x{off:x}:{'f' if i['float'] else 'u'}{i['width'] * 8}"
                for off, i in sorted(merged.items())
            ) or "(header only — no payload)"
        print(f"  {cls:<40} [{sites_total:3d} sites] {desc}")

    ok = True
    print()
    for cls, expect in CONFIRMED.items():
        got = results.get(cls, {}).get("fields", {})
        for off, label in expect.items():
            hit = f"0x{off:x}" in got
            print(f"  check {cls}.{label} @+0x{off:x}: {'OK' if hit else 'MISSING'}")
            ok = ok and hit

    if args.json:
        args.json.write_text(json.dumps(results, indent=1, sort_keys=True) + "\n")
        print(f"\nwrote {args.json}")

    if args.verify and not ok:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
