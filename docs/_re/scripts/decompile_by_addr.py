"""
Ghidra Jython post-script. Given runtime-call-site addresses (as link-time
VAs), find the containing function for each and decompile it.
"""
# @category RSMM

import os
from ghidra.app.decompiler import DecompInterface
from ghidra.util.task import ConsoleTaskMonitor

OUT_DIR = os.environ.get("RSMM_OUT", "/home/ovilli/Documents/Programming/RavenswatchModManager/re/out")
DEC_DIR = os.path.join(OUT_DIR, "decompiled")
if not os.path.exists(DEC_DIR):
    os.makedirs(DEC_DIR)

CALL_SITES = [
    (0x14048c520, "bookmenu_tab_handler"),
    (0x14048b4fc, "social_icons_setup"),
    (0x14048729c, "page_slot_iterator"),
    (0x14055d95c, "invite_friend_click"),
]

fm = currentProgram.getFunctionManager()
af = currentProgram.getAddressFactory()

di = DecompInterface()
di.openProgram(currentProgram)
monitor = ConsoleTaskMonitor()

for site_va, label in CALL_SITES:
    addr = af.getAddress("%x" % site_va)
    fn = fm.getFunctionContaining(addr)
    if fn is None:
        print("[RSMM] %s @ 0x%x: no containing function" % (label, site_va))
        continue
    print("[RSMM] %s @ 0x%x  -> fn=%s entry=0x%x  body=0x%x" % (
          label, site_va, fn.getName(), fn.getEntryPoint().getOffset(),
          fn.getBody().getNumAddresses()))
    res = di.decompileFunction(fn, 90, monitor)
    if not res.decompileCompleted():
        print("[RSMM]   FAILED: %s" % res.getErrorMessage())
        continue
    out_path = os.path.join(DEC_DIR, "%s__%s.c" % (label, fn.getName()))
    with open(out_path, "w") as f:
        f.write("// %s\n" % label)
        f.write("// caller site (link va): 0x%x\n" % site_va)
        f.write("// containing function: %s @ 0x%x\n\n" % (
                fn.getName(), fn.getEntryPoint().getOffset()))
        f.write(res.getDecompiledFunction().getC())
    print("[RSMM]   wrote %s" % out_path)
print("[RSMM] done")
