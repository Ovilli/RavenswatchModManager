# Define a FUNCTION at every symbol-map address Ghidra left undefined.
#
# BinExport can only export what Ghidra has defined as a function, so a symbol
# whose address never became one is unmatchable on patch day -- a gap in the
# remap pipeline, not a finding about the patch (CLAUDE.md, bindiff_remap.py).
# This closes that gap ahead of the patch instead of during it.
#
# Usage (project must be UNLOCKED -- close the GUI and the MCP bridge):
#   analyzeHeadless <projdir> <proj> -process Ravenswatch.exe -noanalysis \
#       -scriptPath tools/ghidra_scripts \
#       -postScript DefineSymbolFunctions.py <addrs.json> [dry]
#
# <addrs.json> is `rsmm symbols ghidra-export --json` ({addr: name}).
# @category RSMM
import json

args = getScriptArgs()
path = args[0]
dry = len(args) > 1 and args[1] == "dry"

data = json.load(open(path))
space = currentProgram.getAddressFactory().getDefaultAddressSpace()
fm = currentProgram.getFunctionManager()

defined, created, midfunc, failed = [], [], [], []

for addr_s, name in sorted(data.items()):
    a = space.getAddress(addr_s)
    if fm.getFunctionAt(a) is not None:
        defined.append(name)
        continue
    # A symbol that lands INSIDE another function is a different problem (a
    # stale address or an inlined routine), not a missing definition. Report it
    # rather than carving a second function out of the middle of one.
    containing = fm.getFunctionContaining(a)
    if containing is not None:
        midfunc.append([name, addr_s, containing.getName(),
                        "0x%x" % containing.getEntryPoint().getOffset()])
        continue
    if dry:
        created.append([name, addr_s])
        continue
    try:
        if getInstructionAt(a) is None:
            disassemble(a)
        f = createFunction(a, name)
        if f is None:
            failed.append([name, addr_s, "createFunction returned null"])
        else:
            created.append([name, addr_s])
    except Exception, e:
        failed.append([name, addr_s, str(e)])

print("RSMM_RESULT " + json.dumps({
    "dry": dry,
    "total": len(data),
    "already_defined": len(defined),
    "created": created,
    "mid_function": midfunc,
    "failed": failed,
}))
