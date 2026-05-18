"""
Ghidra Jython post-script. Decompiles the .bind protector + the two TLS
callbacks so we know whether the protector installs a runtime integrity
monitor (would block MinHook on .text) or is a one-shot unpacker (would
not). Outputs .c files into RSMM_OUT/protector/.
"""
# @category RSMM

import os
from ghidra.app.decompiler import DecompInterface
from ghidra.util.task import ConsoleTaskMonitor

OUT_DIR = os.environ.get(
    "RSMM_OUT",
    "/home/ovilli/Documents/Programming/RavenswatchModManager/docs/_re/out")
DEC_DIR = os.path.join(OUT_DIR, "protector")
if not os.path.exists(DEC_DIR):
    os.makedirs(DEC_DIR)

# (link-va, label) -- link VA is exe ImageBase 0x140000000 + RVA.
TARGETS = [
    (0x14155a310, "entry_stub"),
    (0x14155a315, "entry_stub_inner"),
    (0x14155a3d0, "protector_main"),
    (0x140c93e2c, "tls_callback_0"),
    (0x140c9457c, "tls_callback_1"),
]

fm = currentProgram.getFunctionManager()
af = currentProgram.getAddressFactory()

di = DecompInterface()
di.openProgram(currentProgram)
monitor = ConsoleTaskMonitor()

for site_va, label in TARGETS:
    addr = af.getAddress("%x" % site_va)
    fn = fm.getFunctionContaining(addr)
    if fn is None:
        fn = fm.getFunctionAt(addr)
    if fn is None:
        print("[RSMM] %s @ 0x%x: no function" % (label, site_va))
        continue
    print("[RSMM] %s @ 0x%x  -> fn=%s entry=0x%x  body=%d" % (
          label, site_va, fn.getName(), fn.getEntryPoint().getOffset(),
          fn.getBody().getNumAddresses()))
    res = di.decompileFunction(fn, 300, monitor)
    if not res.decompileCompleted():
        print("[RSMM]   FAILED: %s" % res.getErrorMessage())
        continue
    out_path = os.path.join(DEC_DIR, "%s__%s.c" % (label, fn.getName()))
    f = open(out_path, "w")
    try:
        f.write("// %s\n" % label)
        f.write("// link va: 0x%x\n" % site_va)
        f.write("// containing function: %s @ 0x%x (size=%d)\n\n" % (
                fn.getName(), fn.getEntryPoint().getOffset(),
                fn.getBody().getNumAddresses()))
        f.write(res.getDecompiledFunction().getC())
    finally:
        f.close()
    print("[RSMM]   wrote %s" % out_path)
print("[RSMM] done")
