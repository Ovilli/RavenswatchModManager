# -*- coding: utf-8 -*-
# Ghidra headless: dump every function symbol + every defined string to
# JSON. Lets a developer grep without re-opening Ghidra.
# Output:
#   $RSMM_OUT/symbols.json  — [{addr, name, sig, size}]
#   $RSMM_OUT/strings.json  — [{addr, value, length}]
# @category RSMM

import os
import json

OUT_DIR = os.environ.get("RSMM_OUT", "/home/ovilli/Documents/Programming/RavenswatchModManager/docs/_re/out")

fm = currentProgram.getFunctionManager()
syms = []
for fn in fm.getFunctions(True):
    if fn.isExternal() or fn.isThunk():
        continue
    syms.append({
        "addr": "0x%x" % fn.getEntryPoint().getOffset(),
        "name": fn.getName(),
        "sig": fn.getSignature().getPrototypeString(True),
        "size": fn.getBody().getNumAddresses(),
    })
with open(os.path.join(OUT_DIR, "symbols.json"), "w") as f:
    json.dump(syms, f, indent=1)
print("[RSMM] symbols: %d" % len(syms))

listing = currentProgram.getListing()
strs = []
for d in listing.getDefinedData(True):
    t = d.getDataType().getName()
    if t in ("string", "unicode", "TerminatedCString", "TerminatedUnicode"):
        try:
            v = d.getValue()
            if v is None:
                continue
            sv = unicode(v)
            if len(sv) < 3:
                continue
            strs.append({
                "addr": "0x%x" % d.getAddress().getOffset(),
                "value": sv,
                "length": len(sv),
                "type": t,
            })
        except Exception:
            pass
with open(os.path.join(OUT_DIR, "strings.json"), "w") as f:
    json.dump(strs, f, indent=1, ensure_ascii=False)
print("[RSMM] strings: %d" % len(strs))
