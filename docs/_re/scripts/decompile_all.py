# Ghidra headless: decompile every function in Ravenswatch.exe to pseudo-C.
# One .c per function under $RSMM_OUT/decompiled_all/<bucket>/<name>__<addr>.c.
# Bucketed by first 4 hex digits of the entry-point address so no single
# directory holds more than a couple thousand files (filesystem-friendly).
# @category RSMM

import os
from ghidra.app.decompiler import DecompInterface, DecompileOptions
from ghidra.util.task import ConsoleTaskMonitor

OUT_DIR = os.environ.get("RSMM_OUT", "/home/ovilli/Documents/Programming/RavenswatchModManager/docs/_re/out")
DEC_DIR = os.path.join(OUT_DIR, "decompiled_all")
INDEX_PATH = os.path.join(OUT_DIR, "functions_index.tsv")

if not os.path.exists(DEC_DIR):
    os.makedirs(DEC_DIR)


def safe_name(s):
    out = []
    for ch in s:
        if ch.isalnum() or ch in "._-":
            out.append(ch)
        else:
            out.append("_")
    name = "".join(out)
    return name[:120] if len(name) > 120 else name


fm = currentProgram.getFunctionManager()
total = fm.getFunctionCount()
print("[RSMM] decompiling %d functions" % total)

di = DecompInterface()
opts = DecompileOptions()
di.setOptions(opts)
di.openProgram(currentProgram)
monitor = ConsoleTaskMonitor()

ok = 0
fail = 0
external = 0
idx_lines = []

it = fm.getFunctions(True)
i = 0
for fn in it:
    i += 1
    if fn.isExternal() or fn.isThunk():
        external += 1
        continue
    addr = fn.getEntryPoint().getOffset()
    name = safe_name(fn.getName())
    bucket = "%04x" % ((addr >> 12) & 0xFFFF)
    bdir = os.path.join(DEC_DIR, bucket)
    if not os.path.exists(bdir):
        os.makedirs(bdir)
    out_path = os.path.join(bdir, "%s__0x%x.c" % (name, addr))

    res = di.decompileFunction(fn, 60, monitor)
    if not res.decompileCompleted():
        fail += 1
        idx_lines.append("0x%x\t%s\tFAIL\t%s" % (addr, fn.getName(), res.getErrorMessage()))
        continue
    body = res.getDecompiledFunction().getC()
    sig = fn.getSignature().getPrototypeString(True)
    with open(out_path, "w") as f:
        f.write("// addr: 0x%x\n" % addr)
        f.write("// name: %s\n" % fn.getName())
        f.write("// signature: %s\n" % sig)
        f.write("// size:  %d bytes\n\n" % fn.getBody().getNumAddresses())
        f.write(body)
    idx_lines.append("0x%x\t%s\tOK\t%s\t%s" % (addr, fn.getName(), sig, out_path))
    ok += 1
    if ok % 500 == 0:
        print("[RSMM] decompiled %d / %d (fail=%d)" % (ok, total, fail))

with open(INDEX_PATH, "w") as f:
    f.write("addr\tname\tstatus\tdetail\tpath\n")
    f.write("\n".join(idx_lines) + "\n")

print("[RSMM] done: ok=%d fail=%d external_skipped=%d" % (ok, fail, external))
print("[RSMM] index: %s" % INDEX_PATH)
