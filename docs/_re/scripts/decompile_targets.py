"""
Ghidra Jython post-script. Decompiles specific functions to .c files in $OUT_DIR.
Also dumps direct callers (xrefs to function entry) for downstream tracing.
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
    ("FUN_1402beff0", 0x1402beff0, "BookPageUiController_register"),
    ("FUN_1402bee30", 0x1402bee30, "BookPageUiControllerSettings_register"),
    ("FUN_1403f12c0", 0x1403f12c0, "HeroesBookPageUiCtl_register"),
    ("FUN_140180160", 0x140180160, "oCEntitySpawner_register"),
    ("FUN_14017f910", 0x14017f910, "oCSpawnablePool_register"),
    ("FUN_14017faa0", 0x14017faa0, "oCSpawnableSettings_register"),
]

fm = currentProgram.getFunctionManager()
af = currentProgram.getAddressFactory()
listing = currentProgram.getListing()

di = DecompInterface()
di.openProgram(currentProgram)
monitor = ConsoleTaskMonitor()

def get_function_at(addr_int):
    addr = af.getAddress("%x" % addr_int)
    fn = fm.getFunctionAt(addr)
    return fn

def list_callers(fn):
    """Return list of (caller_function_name, caller_address)."""
    callers = []
    seen = set()
    ref_iter = getReferencesTo(fn.getEntryPoint())
    for r in ref_iter:
        from_a = r.getFromAddress()
        caller = fm.getFunctionContaining(from_a)
        if caller is None:
            continue
        key = str(caller.getEntryPoint())
        if key in seen:
            continue
        seen.add(key)
        callers.append((caller.getName(), str(caller.getEntryPoint())))
    return callers

for name, addr_int, label in TARGETS:
    fn = get_function_at(addr_int)
    if fn is None:
        print("[RSMM] %s @ 0x%x: function not found" % (name, addr_int))
        continue

    print("[RSMM] decompiling %s @ 0x%x  body=0x%x" % (name, addr_int, fn.getBody().getNumAddresses()))
    res = di.decompileFunction(fn, 60, monitor)
    if not res.decompileCompleted():
        print("[RSMM]   FAILED: %s" % res.getErrorMessage())
        continue

    out_path = os.path.join(DEC_DIR, "%s__%s.c" % (label, name))
    code = res.getDecompiledFunction().getC()
    callers = list_callers(fn)

    with open(out_path, "w") as f:
        f.write("// %s @ 0x%x\n" % (name, addr_int))
        f.write("// purpose-guess: %s\n" % label)
        f.write("// callers (%d):\n" % len(callers))
        for cn, ca in callers[:50]:
            f.write("//   %s @ %s\n" % (cn, ca))
        f.write("\n")
        f.write(code)
    print("[RSMM]   wrote %s  callers=%d" % (out_path, len(callers)))

print("[RSMM] done")
