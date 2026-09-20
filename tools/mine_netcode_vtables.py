#!/usr/bin/env python3
"""Name the netcode vtable slots by matching shipped RTTI against open-source headers.

Ravenswatch statically links two libraries whose source is public: the Stormancer
C++ client SDK and RakNet. MSVC RTTI left every one of their polymorphic classes
NAMED in the exe (133 vftables), and for a pure-virtual interface the vtable slot
ORDER is fully determined by the header's declaration order. So a slot can be
named mechanically, with no reverse engineering at all — which is the opposite of
how every other symbol in `data/symbols.json` was won.

The catch, and the reason this tool is a gate rather than a rubber stamp: the
public source is not all the same age as the shipped build.

  * RakNet is frozen. FullyConnectedMesh2 = 17 inherited + 10 new = 27 slots,
    and the binary says 27. ConnectionGraph2 = 17, binary says 17. Exact.
  * `Stormancer/plugins` (branch `develop`) is current. GameSession = 11 slots,
    binary says 11. IPlatformSupportProvider = 11, binary says 11. Exact.
  * The Stormancer CORE SDK is only public as a 2018 third-party fork, and it
    has DRIFTED: IConnection declares 20 slots, the binary has 24;
    IConnectionManager declares 5, the binary has 9; ITransport declares 15,
    the binary has 14.

Naming a drifted class is how you get a confidently wrong symbol — slot 12 of a
20-slot plan is a different method in a 24-slot vtable, and it would resolve,
verify and sit at a real `.pdata` entry while meaning something else entirely
(the `NamedEvent_NetSend` false-ok, reproduced mechanically 24 times over). So
the count is a FAIL-CLOSED gate: a class whose binary slot count differs from
its plan is reported as SKEW and nothing about it is named.

Output is a hypothesis, not a symbol. Slots land in `data/symbols.json` only
through the usual discipline: pattern via gen_function_patterns.py, then
scripts/verify_symbol_resolve.py, then `status` is earned.

Usage:
  python tools/mine_netcode_vtables.py                    # report
  python tools/mine_netcode_vtables.py --json out.json    # machine-readable
  python tools/mine_netcode_vtables.py --check            # CI: assert no plan regressed
  python tools/mine_netcode_vtables.py --build-plan DIR   # regenerate the plan from headers
"""

from __future__ import annotations

import argparse
import bisect
import hashlib
import json
import re
import struct
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from mine_event_names import PE, _default_exe  # noqa: E402
from mine_event_payloads import Rtti, function_ranges  # noqa: E402

PLAN_PATH = REPO / "data/netcode_interfaces.json"

# Which headers back which RTTI class, and what each derives from. `bases` is
# outermost-last: the MSVC primary vtable is the first base's layout, with
# overrides replaced in place and new virtuals appended.
PLAN_SOURCES = {
    "FullyConnectedMesh2@RakNet": {
        "file": "rn_FullyConnectedMesh2.h", "cls": "FullyConnectedMesh2",
        "bases": [("rn_PluginInterface2.h", "PluginInterface2")],
        "url": "https://raw.githubusercontent.com/Stormancer/RakNet/master/Source/FullyConnectedMesh2.h",
    },
    "ConnectionGraph2@RakNet": {
        "file": "rn_ConnectionGraph2.h", "cls": "ConnectionGraph2",
        "bases": [("rn_PluginInterface2.h", "PluginInterface2")],
        "url": "https://raw.githubusercontent.com/Stormancer/RakNet/master/Source/ConnectionGraph2.h",
    },
    "GameSession@GameSessions@Stormancer": {
        "file": "GameSession.hpp", "cls": "GameSession", "bases": [],
        "url": "https://raw.githubusercontent.com/Stormancer/plugins/develop/"
               "src/Stormancer.Plugins/GameSession/cpp/GameSession.hpp",
    },
    "IPlatformSupportProvider@Platform@Party@Stormancer": {
        "file": "Party.hpp", "cls": "IPlatformSupportProvider", "bases": [],
        "url": "https://raw.githubusercontent.com/Stormancer/plugins/develop/"
               "src/Stormancer.Plugins/Party/cpp/Party.hpp",
    },
    "GameSession_Impl@details@GameSessions@Stormancer": {
        "file": "GameSession.hpp", "cls": "GameSession_Impl",
        "bases": [("GameSession.hpp", "GameSession")],
        "url": "https://raw.githubusercontent.com/Stormancer/plugins/develop/"
               "src/Stormancer.Plugins/GameSession/cpp/GameSession.hpp",
    },
    # Party_Impl's PRIMARY vtable is PartyApi's (it also carries a 1-slot
    # ClientAPI vtable, which the multi-vftable check below skips).
    "Party_Impl@details@Party@Stormancer": {
        "file": "Party.hpp", "cls": "Party_Impl",
        "bases": [("Party.hpp", "PartyApi")],
        "url": "https://raw.githubusercontent.com/Stormancer/plugins/develop/"
               "src/Stormancer.Plugins/Party/cpp/Party.hpp",
    },
    "RakPeerInterface@RakNet": {
        "file": "rn_RakPeerInterface.h", "cls": "RakPeerInterface", "bases": [],
        "url": "https://raw.githubusercontent.com/Stormancer/RakNet/master/Source/RakPeerInterface.h",
    },
    # RakPeer's PRIMARY vtable is RakPeerInterface's layout with every slot
    # overridden, so the interface's declaration order names the implementations.
    # The 87==87 count gate is what makes that safe to assert.
    "RakPeer@RakNet": {"alias_of": "RakPeerInterface@RakNet"},
    "Connection_RM3@RakNet": {
        "file": "rn_ReplicaManager3.h", "cls": "Connection_RM3", "bases": [],
        "url": "https://raw.githubusercontent.com/Stormancer/RakNet/master/Source/ReplicaManager3.h",
    },
    "NetworkIDObject@RakNet": {
        "file": "rn_NetworkIDObject.h", "cls": "NetworkIDObject", "bases": [],
        "url": "https://raw.githubusercontent.com/Stormancer/RakNet/master/Source/NetworkIDObject.h",
    },
    "ReplicaManager3@RakNet": {
        "file": "rn_ReplicaManager3.h", "cls": "ReplicaManager3",
        "bases": [("rn_PluginInterface2.h", "PluginInterface2")],
        "url": "https://raw.githubusercontent.com/Stormancer/RakNet/master/Source/ReplicaManager3.h",
    },
}

# Classes we deliberately do NOT plan, with the reason. Recorded so the next
# session does not re-derive the drift measurement from scratch.
KNOWN_SKEW = {
    "IConnection@Stormancer": "2018 fork declares 20 slots, build has 24",
    "IConnectionManager@Stormancer": "2018 fork declares 5 slots, build has 9",
    "ITransport@Stormancer": "2018 fork declares 15 slots, build has 14",
    "Replica3@RakNet": "RakNet header declares 38 slots, build has 44 — the "
                       "shipped fork or the game extended it; the 6 extra "
                       "slots are unidentified",
}


def _strip(txt: str) -> str:
    txt = re.sub(r"//[^\n]*", "", txt)
    return re.sub(r"/\*.*?\*/", "", txt, flags=re.S)


def class_body(txt: str, cls: str) -> str | None:
    m = re.search(r"\bclass\s+(?:RAK_DLL_EXPORT\s+)?" + re.escape(cls) + r"\b[^{;]*\{", txt)
    if not m:
        return None
    i, depth, out = m.end(), 1, []
    while i < len(txt) and depth:
        c = txt[i]
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
        if depth:
            out.append(c)
        i += 1
    return "".join(out)


def virtuals(body: str) -> list[str]:
    """Virtual member names in declaration order — which IS vtable slot order."""
    out = []
    for m in re.finditer(r"\bvirtual\b([^;{]*)", body):
        sig = " ".join(m.group(1).split())
        nm = re.search(r"(~?\w+)\s*\(", sig)
        if nm:
            out.append(nm.group(1))
    return out


def linearize(headers: Path, spec: dict) -> list[str]:
    """Base layout, overrides replaced in place, new virtuals appended."""
    slots: list[str] = []
    for bfile, bcls in spec["bases"]:
        body = class_body(_strip((headers / bfile).read_text(errors="replace")), bcls)
        if body is None:
            raise SystemExit(f"base {bcls} not found in {bfile}")
        slots = list(virtuals(body))
    body = class_body(_strip((headers / spec["file"]).read_text(errors="replace")), spec["cls"])
    if body is None:
        raise SystemExit(f"class {spec['cls']} not found in {spec['file']}")
    # Only a name inherited from a BASE is an override. A name repeated within
    # one class is an OVERLOAD and gets a slot of its own — collapsing those
    # silently shortened RakPeerInterface from 87 slots to 84, which would have
    # shifted every name past the first overload onto the wrong function.
    inherited = set(slots)
    for name in virtuals(body):
        if name.startswith("~"):
            if slots and slots[0].startswith("~"):
                slots[0] = name
            else:
                slots.insert(0, name)
            continue
        if name in inherited:      # override: keeps the base's slot
            continue
        slots.append(name)
    return slots


def build_plan(headers: Path) -> dict:
    classes = {}
    for rtti, spec in PLAN_SOURCES.items():
        if "alias_of" in spec:
            continue
        src = headers / spec["file"]
        classes[rtti] = {
            "class": spec["cls"],
            "source": spec["url"],
            "sha256": hashlib.sha256(src.read_bytes()).hexdigest(),
            "slots": linearize(headers, spec),
        }
    for rtti, spec in PLAN_SOURCES.items():
        if "alias_of" not in spec:
            continue
        base = classes[spec["alias_of"]]
        classes[rtti] = dict(base, alias_of=spec["alias_of"])
    return {
        "_note": "Generated by tools/mine_netcode_vtables.py --build-plan. "
                 "Slot order is the header's virtual declaration order; a binary "
                 "vtable whose slot COUNT differs is reported SKEW and never named.",
        "known_skew": KNOWN_SKEW,
        "classes": classes,
    }


class Image:
    def __init__(self, exe: str):
        self.pe = PE(Path(exe).read_bytes())
        self.rtti = Rtti(self.pe)
        self.vfts = self.rtti.vftables()
        self.starts = [a for a, _ in function_ranges(self.pe)]
        t = self.pe.section(".text")
        self.tlo, self.thi = t["va"], t["va"] + t["rawsize"]
        self.boundaries = {v for vs in self.vfts.values() for v in vs}

    def read(self, va: int, n: int) -> bytes | None:
        for s in self.pe.sections:
            if s["va"] <= va < s["va"] + s["rawsize"]:
                o = s["raw"] + (va - s["va"])
                return self.pe.data[o:o + n]
        return None

    def slots(self, vft: int, cap: int = 256) -> list[int]:
        out = []
        for i in range(cap):
            va = vft + i * 8
            if i and va in self.boundaries:
                break
            b = self.read(va, 8)
            if not b or len(b) < 8:
                break
            p, = struct.unpack("<Q", b)
            if not (self.tlo <= p < self.thi):
                break
            out.append(p)
        return out

    def is_fn_start(self, p: int) -> bool:
        i = bisect.bisect_left(self.starts, p)
        return i < len(self.starts) and self.starts[i] == p


def demangle(raw: str) -> str:
    body = raw[4:]
    return body[:-2] if body.endswith("@@") else body


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--exe", default=_default_exe())
    ap.add_argument("--json", metavar="OUT")
    ap.add_argument("--check", action="store_true",
                    help="fail if a planned class no longer matches the binary")
    ap.add_argument("--build-plan", metavar="HEADER_DIR",
                    help="regenerate data/netcode_interfaces.json from local headers")
    args = ap.parse_args()

    if args.build_plan:
        plan = build_plan(Path(args.build_plan))
        PLAN_PATH.write_text(json.dumps(plan, indent=1) + "\n")
        for name, c in plan["classes"].items():
            print(f"  {demangle('.?AV' + name + '@@'):<46} {len(c['slots'])} slots")
        print(f"\nwrote {PLAN_PATH.relative_to(REPO)}")
        return 0

    if not PLAN_PATH.exists():
        print(f"missing {PLAN_PATH} — run --build-plan first", file=sys.stderr)
        return 2
    plan = json.loads(PLAN_PATH.read_text())

    img = Image(args.exe)
    targets = sorted(n for n in img.vfts
                     if n.endswith("@Stormancer@@") or n.endswith("@RakNet@@"))

    named, skew, unplanned, failures = {}, [], [], []
    for raw in targets:
        key = demangle(raw)
        for vft in img.vfts[raw]:
            s = img.slots(vft)
            entry = plan["classes"].get(key)
            if entry is None:
                unplanned.append((key, vft, len(s)))
                continue
            want = entry["slots"]
            if len(s) != len(want):
                # A class can emit several vftables (multiple inheritance); only
                # the one matching the plan's length is the primary.
                if any(len(img.slots(v)) == len(want) for v in img.vfts[raw]):
                    continue
                skew.append((key, vft, len(s), len(want)))
                failures.append(key)
                continue
            named[key] = {
                "vftable": hex(vft),
                "source": entry["source"],
                "slots": [
                    {"slot": i, "name": nm, "addr": hex(a),
                     "fn_start": img.is_fn_start(a)}
                    for i, (nm, a) in enumerate(zip(want, s, strict=True))
                ],
            }

    print(f"exe: {args.exe}")
    print(f"{len(img.vfts)} RTTI classes with vftables; "
          f"{len(targets)} in Stormancer/RakNet\n")

    print(f"== NAMED ({len(named)} classes) ==")
    for key, c in sorted(named.items()):
        bad = [s for s in c["slots"] if not s["fn_start"]]
        flag = f"  ⚠ {len(bad)} slot(s) not a .pdata function start" if bad else ""
        print(f"\n  {key}   vft={c['vftable']}  {len(c['slots'])} slots{flag}")
        for s in c["slots"]:
            mark = "" if s["fn_start"] else "  <- not a function start"
            print(f"     [{s['slot']:2d}] {s['name']:<42} {s['addr']}{mark}")

    if skew:
        print(f"\n== SKEW — NOT NAMED ({len(skew)}) ==")
        for key, vft, got, want in skew:
            print(f"  {key:<46} vft={hex(vft)} binary={got} plan={want}")

    ks = plan.get("known_skew", {})
    if ks:
        print(f"\n== KNOWN SKEW, deliberately unplanned ({len(ks)}) ==")
        for k, why in sorted(ks.items()):
            print(f"  {k:<46} {why}")

    print(f"\n== UNPLANNED ({len(unplanned)} vftables) ==")
    print("  no header plan; slot counts only. Highest-value first:")
    for key, vft, n in sorted(unplanned, key=lambda r: -r[2])[:15]:
        print(f"    {key:<52} vft={hex(vft)} slots={n}")

    if args.json:
        Path(args.json).write_text(json.dumps(
            {"named": named,
             "skew": [{"class": k, "vftable": hex(v), "binary": g, "plan": w}
                      for k, v, g, w in skew],
             "unplanned": [{"class": k, "vftable": hex(v), "slots": n}
                           for k, v, n in unplanned]}, indent=1) + "\n")
        print(f"\nwrote {args.json}")

    if args.check and failures:
        print(f"\nFAIL: {len(failures)} planned class(es) no longer match the "
              f"binary — the game updated, or a header moved.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
