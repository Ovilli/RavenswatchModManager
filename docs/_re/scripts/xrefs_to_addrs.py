# -*- coding: utf-8 -*-
# Ghidra headless: for a list of target addresses (string literals,
# globals, function entries), find every code reference and decompile
# the containing function. Output: $RSMM_OUT/xref_targets/<label>.c
# @category RSMM

import os
import json
from ghidra.app.decompiler import DecompInterface
from ghidra.util.task import ConsoleTaskMonitor

OUT_DIR = os.environ.get("RSMM_OUT", "/home/ovilli/Documents/Programming/RavenswatchModManager/docs/_re/out")
DST = os.path.join(OUT_DIR, "xref_targets")
if not os.path.exists(DST):
    os.makedirs(DST)

# Targets discovered by grepping strings.json + symbols.json.
TARGETS = [
    (0x140f59758, "m_uRandomSeed"),
    (0x140eed8b8, "ForcedSeed"),
    (0x140eef7f0, "RoseSeed"),
    (0x140ef0698, "RandomSeed_str"),
    (0x140ef13a8, "CLEAR_ROSE_SEED"),
    (0x140ef1a70, "SeedFormat"),
    (0x140ef4068, "ForcedSeedFormat"),
    (0x140c92ef4, "Random_device"),
]

af = currentProgram.getAddressFactory()
ref_mgr = currentProgram.getReferenceManager()
fm = currentProgram.getFunctionManager()

di = DecompInterface()
di.openProgram(currentProgram)
monitor = ConsoleTaskMonitor()

summary = []
for va, label in TARGETS:
    addr = af.getAddress("%x" % va)
    refs = ref_mgr.getReferencesTo(addr)
    callers = []
    for r in refs:
        from_addr = r.getFromAddress()
        fn = fm.getFunctionContaining(from_addr)
        if fn is None:
            callers.append(("?", "0x%x" % from_addr.getOffset(), None))
            continue
        callers.append((fn.getName(), "0x%x" % fn.getEntryPoint().getOffset(), fn))
    print("[RSMM] %s @ 0x%x: %d xrefs" % (label, va, len(callers)))
    # Decompile each unique containing function once.
    seen = set()
    for cname, caddr, fn in callers:
        if fn is None or caddr in seen:
            continue
        seen.add(caddr)
        res = di.decompileFunction(fn, 90, monitor)
        if not res.decompileCompleted():
            continue
        body = res.getDecompiledFunction().getC()
        sig = fn.getSignature().getPrototypeString(True)
        out_path = os.path.join(DST, "%s__%s__%s.c" % (label, cname, caddr))
        with open(out_path, "w") as f:
            f.write("// xref target: %s @ 0x%x\n" % (label, va))
            f.write("// containing fn: %s @ %s\n" % (cname, caddr))
            f.write("// signature: %s\n\n" % sig)
            f.write(body)
    summary.append({
        "target_label": label,
        "target_addr": "0x%x" % va,
        "xrefs": [{"from": a, "fn": n} for n, a, _ in callers],
    })

with open(os.path.join(OUT_DIR, "xref_targets_summary.json"), "w") as f:
    json.dump(summary, f, indent=1)
print("[RSMM] summary -> %s" % os.path.join(OUT_DIR, "xref_targets_summary.json"))
