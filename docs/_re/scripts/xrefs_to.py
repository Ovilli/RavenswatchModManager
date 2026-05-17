"""
Ghidra Jython script: dump callers of a target function.
"""
# @category RSMM

import os
from ghidra.app.decompiler import DecompInterface
from ghidra.util.task import ConsoleTaskMonitor

OUT_DIR = os.environ.get("RSMM_OUT", "/home/ovilli/Documents/Programming/RavenswatchModManager/re/out")
DEC_DIR = os.path.join(OUT_DIR, "decompiled")
if not os.path.exists(DEC_DIR):
    os.makedirs(DEC_DIR)

TARGETS = [
    (0x14055d850, "text_localizer"),
]

fm = currentProgram.getFunctionManager()
af = currentProgram.getAddressFactory()
ref = currentProgram.getReferenceManager()

di = DecompInterface()
di.openProgram(currentProgram)
monitor = ConsoleTaskMonitor()

for target_va, label in TARGETS:
    addr = af.getAddress("%x" % target_va)
    fn = fm.getFunctionAt(addr)
    if fn is None:
        print("[RSMM] %s @ 0x%x: not a function entry" % (label, target_va))
        continue

    callers = set()
    for r in ref.getReferencesTo(addr):
        from_addr = r.getFromAddress()
        caller_fn = fm.getFunctionContaining(from_addr)
        if caller_fn is not None:
            callers.add((caller_fn.getEntryPoint().getOffset(),
                         caller_fn.getName(),
                         from_addr.getOffset()))

    print("[RSMM] callers of %s @ 0x%x: %d" % (label, target_va, len(callers)))
    sorted_callers = sorted(callers)
    for entry, name, site in sorted_callers[:50]:
        print("  fn=%s entry=0x%x site=0x%x" % (name, entry, site))

    # Decompile top 5 callers
    for entry, name, site in sorted_callers[:5]:
        caller_fn = fm.getFunctionAt(af.getAddress("%x" % entry))
        res = di.decompileFunction(caller_fn, 90, monitor)
        if not res.decompileCompleted():
            continue
        out_path = os.path.join(DEC_DIR,
                                 "caller_of_%s__%s.c" % (label, name))
        with open(out_path, "w") as f:
            f.write("// caller of %s\n" % label)
            f.write("// target: 0x%x\n" % target_va)
            f.write("// caller fn: %s @ 0x%x\n\n" % (name, entry))
            f.write(res.getDecompiledFunction().getC())
        print("    wrote %s" % out_path)

print("[RSMM] done")
