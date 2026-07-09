# Decompile a fixed list of candidate addresses (game-update symbol recovery).
# @category RSMM
import os

from ghidra.app.decompiler import DecompInterface
from ghidra.util.task import ConsoleTaskMonitor

OUT_DIR = os.environ.get("RSMM_OUT", "/home/ovilli/Documents/Programming/RavenswatchModManager/docs/_re/out_new")
DEC = os.path.join(OUT_DIR, "candidates")
if not os.path.exists(DEC):
    os.makedirs(DEC)

CANDS = [
    ("Definition_DeserializeBase", [0x1400c5780, 0x140189470, 0x140310180]),
    ("RewardDef_Deserialize",      [0x1401c9b80, 0x1402218a0, 0x1403244c0]),
    ("RewardType_Serialize",       [0x1401c9aa0, 0x1402216b0, 0x140324260]),
    ("CustomFlagFilter_Serialize", [0x1400c5940, 0x140189830]),
    ("EnemyDefinition_ctor",       [0x1401df260, 0x14022e240, 0x14031a430]),
]

fm = currentProgram.getFunctionManager()
af = currentProgram.getAddressFactory()
di = DecompInterface()
di.openProgram(currentProgram)
mon = ConsoleTaskMonitor()

for label, addrs in CANDS:
    for va in addrs:
        addr = af.getAddress("%x" % va)
        fn = fm.getFunctionContaining(addr)
        if fn is None:
            print("[RSMM] %s 0x%x: no fn" % (label, va))
            continue
        res = di.decompileFunction(fn, 90, mon)
        body = res.getDecompiledFunction().getC() if res.decompileCompleted() else "// decompile failed"
        path = os.path.join(DEC, "%s__0x%x.c" % (label, va))
        with open(path, "w") as f:
            f.write("// %s candidate @ 0x%x (entry 0x%x, %d bytes)\n" % (
                label, va, fn.getEntryPoint().getOffset(), fn.getBody().getNumAddresses()))
            f.write(body)
        print("[RSMM] wrote %s" % path)
