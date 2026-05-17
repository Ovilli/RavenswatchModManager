"""
Ghidra Jython post-analysis script.
Dumps target strings + their xrefs to JSON in $OUT_DIR.
Targets: button-spawn related strings from Friend_List_Recent page.
"""
# @category RSMM

import json
import os

OUT_DIR = os.environ.get("RSMM_OUT", "/home/ovilli/Documents/Programming/RavenswatchModManager/re/out")

TARGETS = [
    ".entity.ot",
    "entity.ot",
    "Resource load",
    "load failed",
    "Failed to load",
    "Cannot load",
    "Loading resource",
    "oCResource",
    "ResourceManager",
    "ResourceLoader",
    "PickerEntity",
    "oCPicker",
    "BookPage",
    "PageSlot",
    "spawn",
    "Spawn",
    "instantiate",
    "Click",
    "OnClick",
    "ButtonClicked",
]

def find_string_addrs(needle):
    """Scan defined strings + raw memory for needle. Return list of addresses."""
    hits = []
    listing = currentProgram.getListing()
    data_iter = listing.getDefinedData(True)
    while data_iter.hasNext():
        d = data_iter.next()
        try:
            v = d.getValue()
        except:
            v = None
        if v is None:
            continue
        s = str(v)
        if needle in s:
            hits.append((d.getAddress(), s))
    return hits

def xrefs_to(addr):
    """Return list of (from_addr, function_name)."""
    refs = []
    ref_iter = getReferencesTo(addr)
    fm = currentProgram.getFunctionManager()
    for r in ref_iter:
        from_a = r.getFromAddress()
        fn = fm.getFunctionContaining(from_a)
        fn_name = fn.getName() if fn else "<no_function>"
        fn_entry = str(fn.getEntryPoint()) if fn else ""
        refs.append({
            "from": str(from_a),
            "function": fn_name,
            "function_entry": fn_entry,
            "ref_type": str(r.getReferenceType()),
        })
    return refs

result = {}
for t in TARGETS:
    print("[RSMM] searching: %s" % t)
    hits = find_string_addrs(t)
    entries = []
    for addr, full_s in hits:
        entries.append({
            "string_addr": str(addr),
            "string_value": full_s,
            "xrefs": xrefs_to(addr),
        })
    result[t] = entries
    print("[RSMM]   hits=%d total_xrefs=%d" % (len(entries), sum(len(e["xrefs"]) for e in entries)))

if not os.path.exists(OUT_DIR):
    os.makedirs(OUT_DIR)
out_path = os.path.join(OUT_DIR, "xrefs.json")
with open(out_path, "w") as f:
    json.dump(result, f, indent=2)
print("[RSMM] wrote %s" % out_path)
