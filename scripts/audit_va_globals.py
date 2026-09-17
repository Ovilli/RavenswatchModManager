#!/usr/bin/env python3
"""Audit every ``status="va"`` data symbol against the live game exe.

Why this exists. A ``va`` symbol is a raw base-relative address: unlike a
``raw``/``anchor`` symbol it carries no byte pattern, so nothing re-finds it
after a game update and nothing notices when it is wrong. It fails SILENTLY --
a stale vftable VA makes the event-payload decode match nothing, a stale global
reads zeros -- which is why `va_globals_trusted` gates their use. CI cannot
catch any of this (the exe is not in the repo), so it is a local audit.

Two independent checks, one per symbol shape:

* ``*_vftable`` -- resolved from MSVC RTTI (type descriptor -> complete object
  locator -> vftable), the same walk `tools/mine_event_payloads.py` uses. The
  RTTI class name is ground truth: if the recorded VA is a vftable at all, this
  prints WHOSE. A VA that no COL points at is a hard FAIL.
* every other global -- proven by USE, not by shape: scan `.text` for
  RIP-relative references to the address and report how many sites there are
  and which named functions they sit in. A global nothing references is either
  wrong or dead; a global referenced from the very function its note names is
  confirmed.

Both checks are read-only and need only the shipped exe.

Usage:
  python scripts/audit_va_globals.py            # table
  python scripts/audit_va_globals.py --json out.json
  python scripts/audit_va_globals.py --quiet    # only problems
Exit code 1 if any symbol FAILs.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "tools"))

import numpy as np  # noqa: E402
from mine_event_names import PE, _default_exe  # noqa: E402
from mine_event_payloads import Rtti, demangle, function_ranges  # noqa: E402

from rsmm.engine.symbols import load_symbol_map  # noqa: E402


def rip_ref_sites(pe: PE, targets: set[int]) -> dict[int, list[int]]:
    """VA -> [site VAs] for every RIP-relative disp32 in .text aiming at it.

    Every byte offset is a candidate displacement, so this reads .text at all
    four alignments rather than only aligned ones. False positives are possible
    (a disp32 that is really an immediate), which is exactly why the caller
    reports the site COUNT and the function it lands in instead of trusting a
    single hit.
    """
    sec = pe.section(".text")
    blob = pe.data[sec["raw"] : sec["raw"] + sec["rawsize"]]
    base = sec["va"]
    hits: dict[int, list[int]] = {t: [] for t in targets}
    wanted = np.fromiter(sorted(targets), dtype=np.int64)
    for shift in range(4):
        body = blob[shift:]
        n = len(body) // 4
        if not n:
            continue
        disp = np.frombuffer(body[: n * 4], dtype="<i4").astype(np.int64)
        site = base + shift + np.arange(n, dtype=np.int64) * 4
        # disp32 sits at the END of the instruction, so next_ip == site + 4.
        target = site + 4 + disp
        idx = np.nonzero(np.isin(target, wanted))[0]
        for i in idx:
            hits[int(target[i])].append(int(site[i]))
    return hits


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--exe")
    ap.add_argument("--json")
    ap.add_argument("--quiet", action="store_true", help="only WARN/FAIL rows")
    args = ap.parse_args()

    exe = Path(args.exe) if args.exe else _default_exe()
    if not exe or not exe.exists():
        print("Ravenswatch.exe not found (pass --exe PATH)", file=sys.stderr)
        return 2
    pe = PE(exe.read_bytes())

    smap = load_symbol_map()
    va_syms = [s for s in smap.symbols if s.status == "va" and s.va]
    # Named function bounds, so a reference site can be attributed to a symbol
    # we already trust rather than to a bare address.
    ranges = sorted(function_ranges(pe))
    fn_name = {}
    for s in smap.symbols:
        if s.raw:
            fn_name[int(s.raw.split("_")[-1], 16)] = s.name

    def owner(site: int) -> str:
        lo, hi = 0, len(ranges) - 1
        while lo <= hi:
            mid = (lo + hi) // 2
            start, end = ranges[mid]
            if site < start:
                hi = mid - 1
            elif site >= end:
                lo = mid + 1
            else:
                return fn_name.get(start, f"0x{start:x}")
        return "?"

    vft_by_va: dict[int, str] = {}
    for cls, vas in Rtti(pe).vftables().items():
        for va in vas:
            vft_by_va[va] = demangle(cls)

    targets = {int(s.va, 16) if isinstance(s.va, str) else int(s.va) for s in va_syms}
    refs = rip_ref_sites(pe, targets)

    rows, fails, warns = [], 0, 0
    for s in sorted(va_syms, key=lambda x: x.name):
        va = int(s.va, 16) if isinstance(s.va, str) else int(s.va)
        sec = next((x["name"] for x in pe.sections
                    if x["va"] <= va < x["va"] + max(x["vsize"], x["rawsize"])), None)
        sites = refs.get(va, [])
        owners = sorted({owner(x) for x in sites})
        named = [o for o in owners if not o.startswith("0x") and o != "?"]

        if s.name.endswith("_vftable"):
            cls = vft_by_va.get(va)
            if cls:
                verdict, detail = "OK", f"RTTI class {cls}"
            else:
                verdict, detail = "FAIL", "no RTTI complete-object-locator points here"
        else:
            if not sec:
                verdict, detail = "FAIL", "address is outside the image"
            elif not sites:
                verdict, detail = "WARN", "no RIP-relative reference in .text"
            else:
                verdict = "OK"
                detail = f"{len(sites)} ref site(s)"
                if named:
                    detail += " in " + ", ".join(named[:3])
                    if len(named) > 3:
                        detail += f" +{len(named) - 3}"
        fails += verdict == "FAIL"
        warns += verdict == "WARN"
        rows.append({"name": s.name, "va": f"0x{va:x}", "section": sec,
                     "verdict": verdict, "detail": detail,
                     "ref_sites": len(sites), "ref_owners": owners})

    for r in rows:
        if args.quiet and r["verdict"] == "OK":
            continue
        print(f'{r["verdict"]:<6} {r["name"]:<46} {r["va"]:<12} '
              f'{r["section"] or "-":<8} {r["detail"]}')
    ok = len(rows) - warns - fails
    print(f"\n{len(rows)} va symbols: {ok} ok, {warns} warn, {fails} fail (exe {exe.name})")

    if args.json:
        Path(args.json).write_text(json.dumps(rows, indent=1))
        print("wrote", args.json)
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
