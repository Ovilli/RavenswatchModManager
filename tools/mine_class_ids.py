#!/usr/bin/env python3
"""Recover the engine's CLASS ID table (name -> 32-bit id) from the shipped exe.

Every polymorphic engine class is registered at startup by a small generated
routine that allocates a class descriptor, stamps the class SIZE, references
the class NAME as a plain string, and writes a 32-bit id:

    mov  edx, <size>                  ; 0x1e48 for the hero controller
    lea  rax, [rip+<"oCDtEntityCpntHeroController">]
    ...
    mov  dword ptr [rbx+0x28], 0x155aac59       <- the class id

That id is what the engine's own containers are keyed by. The one that matters
here: components on an `oCEntity` live in an F14/SwissTable map
(control bytes @entity+0x5e8, slots @+0x5f0 with stride 0x10 = {u32 id, cpnt*},
mask @+0x600) and `Entity_GetNetComponent` finds the network component by
looking up the literal 0x154fce5c. This miner resolves that literal to
`oCEntityCpntNetwork`, which is the acceptance test for the whole table.

WHY IT MATTERS: a class id is a hash of the class NAME, so it survives a game
patch that moves every address. Testing "does this entity carry an
EnemyController" by class id is therefore strictly more patch-stable than
comparing a vftable VA — and it needs no engine call, just reads.

⚠ The `+0x190` pointer array that `Entity_GetComponentByTester` walks belongs to
an `oCEntitySpawnerGo`, NOT to an `oCEntity`. Reading it off an entity yields
either nothing or an unrelated vector; that mistake cost one playtest.

Usage:
  python tools/mine_class_ids.py                  # report + write data/class_ids.json
  python tools/mine_class_ids.py --verify         # assert the known pairs
  python tools/mine_class_ids.py --lookup 0x1561073c oCDtEntityCpntHittable
"""

from __future__ import annotations

import argparse
import bisect
import json
import re
import struct
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))

import gen_function_patterns as gen  # noqa: E402

OUT = REPO / "data/class_ids.json"

# Pairs established by hand. The miner must reproduce them; they are the
# acceptance test, not an input. The first is the strongest: 0x154fce5c is the
# literal Entity_GetNetComponent hardcodes, so resolving it to the network
# component class proves the id semantics, not merely the parsing.
CONFIRMED = {
    "oCEntityCpntNetwork": 0x154FCE5C,
    "oCDtEntityCpntGroupLevel": 0x15888C02,
}

# mov dword ptr [rbx+0x28], imm32 — the class id store.
_ID_STORE = re.compile(rb"\xc7\x43\x28(....)", re.DOTALL)
# mov edx, imm32 — the class size passed to the descriptor allocator.
_SIZE = re.compile(rb"\xba(....)", re.DOTALL)
# Plain (non-RTTI) engine class names: oC*, oI*, oe*, oS*.
_NAME = re.compile(rb"\x00(o[CIeS][A-Za-z0-9_]{4,60})\x00")


class Image:
    def __init__(self, exe: Path):
        self.data = exe.read_bytes()
        self.base, self.secs = gen.parse_pe(self.data)
        text = self.secs[0]
        self.text = self.data[text["raw_off"]:text["raw_off"] + text["raw_size"]]
        self.tva = self.base + text["rva"]
        pdata = next(s for s in self.secs if s["name"].startswith(".pdata"))
        self.funcs = [
            struct.unpack_from("<III", self.data, pdata["raw_off"] + i * 12)[:2]
            for i in range(pdata["raw_size"] // 12)
        ]
        self._starts = [f[0] for f in self.funcs]

    def off_to_va(self, off: int) -> int | None:
        for s in self.secs:
            if s["raw_off"] <= off < s["raw_off"] + s["raw_size"]:
                return self.base + s["rva"] + (off - s["raw_off"])
        return None

    def va_to_off(self, va: int) -> int | None:
        for s in self.secs:
            start = self.base + s["rva"]
            if start <= va < start + s["raw_size"]:
                return s["raw_off"] + (va - start)
        return None

    def function_at(self, va: int) -> tuple[int, int] | None:
        """.pdata bounds of the function containing `va` (never a guess)."""
        rva = va - self.base
        i = bisect.bisect_right(self._starts, rva) - 1
        if i >= 0 and self.funcs[i][0] <= rva < self.funcs[i][1]:
            return self.base + self.funcs[i][0], self.base + self.funcs[i][1]
        return None


def mine(img: Image) -> dict[str, dict]:
    names: dict[int, str] = {}
    for m in _NAME.finditer(img.data):
        va = img.off_to_va(m.start() + 1)
        if va is not None:
            names[va] = m.group(1).decode()

    # rip-relative `lea r64, [rip+disp]` referencing one of those strings.
    refs: dict[int, list[int]] = {}
    text = img.text
    for i in range(len(text) - 7):
        if text[i] in (0x48, 0x4C) and text[i + 1] == 0x8D and (text[i + 2] & 0xC7) == 0x05:
            va = img.tva + i + 7 + struct.unpack_from("<i", text, i + 3)[0]
            if va in names:
                refs.setdefault(va, []).append(img.tva + i)

    out: dict[str, dict] = {}
    for va, name in names.items():
        for site in refs.get(va, []):
            bounds = img.function_at(site)
            if not bounds:
                continue
            start, end = bounds
            body = img.data[img.va_to_off(start):img.va_to_off(end)]
            store = _ID_STORE.search(body)
            if not store:
                continue
            size = _SIZE.search(body)
            out[name] = {
                "id": struct.unpack("<I", store.group(1))[0],
                "size": struct.unpack("<I", size.group(1))[0] if size else None,
                "registrar": f"0x{start:x}",
            }
            break
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--exe", default=gen.DEFAULT_EXE)
    ap.add_argument("--out", default=str(OUT))
    ap.add_argument("--verify", action="store_true", help="assert the known pairs")
    ap.add_argument("--lookup", nargs="+", default=[], help="ids (0x…) or class names")
    ap.add_argument("--no-write", action="store_true")
    args = ap.parse_args()

    img = Image(Path(args.exe))
    table = mine(img)
    print(f"{len(table)} registered class(es)")

    failed = False
    for name, want in CONFIRMED.items():
        got = table.get(name, {}).get("id")
        ok = got == want
        failed = failed or not ok
        print(f"  [{'OK ' if ok else 'BAD'}] {name} = 0x{(got or 0):x} (expected 0x{want:x})")

    by_id = {v["id"]: k for k, v in table.items()}
    for item in args.lookup:
        if item.lower().startswith("0x"):
            cid = int(item, 16)
            name = by_id.get(cid)
            print(f"  0x{cid:x} -> {name or 'UNKNOWN'}")
        else:
            entry = table.get(item)
            print(f"  {item} -> " + (f"0x{entry['id']:x} (size 0x{(entry['size'] or 0):x})"
                                     if entry else "UNKNOWN"))

    if not args.no_write:
        payload = {
            "_doc": "Engine class name -> 32-bit class id, mined from the class "
                    "registrars by tools/mine_class_ids.py. The id keys the "
                    "oCEntity component map (slots @entity+0x5f0, stride 0x10).",
            "classes": dict(sorted(table.items())),
        }
        Path(args.out).write_text(json.dumps(payload, indent=1) + "\n")
        print(f"wrote {args.out}")

    if args.verify and failed:
        print("VERIFY FAILED: a known class id did not survive the mine", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
