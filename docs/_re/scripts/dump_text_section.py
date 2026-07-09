# -*- coding: utf-8 -*-
# Ghidra headless: dump the raw .text bytes + image base of the current
# program. Used by scripts/remap_symbols.py to rebuild byte patterns for
# functions of a PREVIOUS game build (this project keeps the old program
# even after Steam replaces the exe on disk).
# Output:
#   $RSMM_OUT/text_section.bin   raw .text bytes
#   $RSMM_OUT/text_section.json  {image_base, text_va, text_len}
# @category RSMM

import json
import os

OUT_DIR = os.environ.get(
    "RSMM_OUT",
    "/home/ovilli/Documents/Programming/RavenswatchModManager/docs/_re/out")

mem = currentProgram.getMemory()
block = None
for b in mem.getBlocks():
    if b.getName() == ".text":
        block = b
        break
if block is None:
    raise RuntimeError("no .text block")

size = int(block.getSize())
buf = bytearray(size)
# jarray for getBytes
from jarray import zeros  # noqa: E402
jbuf = zeros(size, 'b')
block.getBytes(block.getStart(), jbuf)
data = bytearray((x & 0xff) for x in jbuf)

with open(os.path.join(OUT_DIR, "text_section.bin"), "wb") as f:
    f.write(bytes(data))
with open(os.path.join(OUT_DIR, "text_section.json"), "w") as f:
    json.dump({
        "image_base": "0x%x" % currentProgram.getImageBase().getOffset(),
        "text_va": "0x%x" % block.getStart().getOffset(),
        "text_len": size,
        "program": currentProgram.getName(),
    }, f, indent=1)
print("[RSMM] dumped .text: %d bytes @ %s" % (size, block.getStart()))
