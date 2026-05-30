"""Generic byte-stable decoder for nested settings/stream classes whose
deep recursive schema isn't fully typed, but whose moddable payload is a
set of embedded asset-path references.

Covers `oCScheduledVfxSettings` (VFX → material paths), `oCGameStream`
(level object streams) and `oCCollisionMesh`. The full recursive trees
(`oIRsSettingsGroup` particle params, level object graphs) are left
untouched; instead every length-prefixed string that looks like an asset
reference (`Materials\\Foo.mat.ot`, `Objects\\Bar.entity.ot`, ...) is lifted
out as an editable `asset_refs` entry. Everything between the refs is kept
verbatim as `_literals`, so the file round-trips byte-stably and a mod
author can repoint an effect at a different material / texture without a
hex editor.

On encode the concatenated stream is reassembled by interleaving the
literal chunks with the (possibly edited) refs, then re-split by the stored
section lengths; any length delta from an edited ref is absorbed into the
section that contains that ref, so unedited files reproduce the original
bytes exactly and edits stay localized.
"""

from __future__ import annotations

import json
import struct

from .. import cooked
from . import register
from .base import SchemaHandler

# A length-prefixed string is treated as an editable asset reference when it
# is printable, a sensible length, and looks path-like (has a separator or a
# known asset extension). Conservative on purpose — anything not matched stays
# in the verbatim literal stream, so misclassification can only *miss* a ref,
# never corrupt bytes.
_MIN_REF = 4
_MAX_REF = 300
_ASSET_EXTS = (".ot", ".png", ".tga", ".dds", ".mat", ".gen", ".yqz", ".xls")


def _looks_like_ref(s: bytes) -> bool:
    if not (_MIN_REF <= len(s) <= _MAX_REF):
        return False
    if not all(32 <= c < 127 for c in s):
        return False
    low = s.lower()
    if b"\\" in s or b"/" in s:
        return True
    return any(low.endswith(e.encode()) for e in _ASSET_EXTS)


def _split_refs(concat: bytes) -> tuple[list[str], list[str], list[int]]:
    """Return (literals_hex, refs, ref_offsets).

    `literals_hex[i]` is the verbatim chunk before `refs[i]`; the final
    literal (len == len(refs)+1) is the trailing chunk. `ref_offsets[i]` is
    the byte offset of `refs[i]`'s string data within `concat` (for mapping
    edits back to a section).
    """
    literals: list[str] = []
    refs: list[str] = []
    offsets: list[int] = []
    n = len(concat)
    i = 0
    lit_start = 0
    while i + 4 <= n:
        ln = struct.unpack_from("<I", concat, i)[0]
        if 0 < ln <= _MAX_REF and i + 4 + ln <= n:
            cand = concat[i + 4:i + 4 + ln]
            if _looks_like_ref(cand):
                literals.append(concat[lit_start:i].hex())
                refs.append(cand.decode("utf-8", errors="replace"))
                offsets.append(i + 4)
                i = i + 4 + ln
                lit_start = i
                continue
        i += 1
    literals.append(concat[lit_start:].hex())
    return literals, refs, offsets


def _decode(cooked_bytes: bytes, class_name: str) -> dict:
    cf = cooked.parse(cooked_bytes)
    concat = b"".join(s.payload for s in cf.sections)
    literals, refs, offsets = _split_refs(concat)
    return {
        "rsmm_class": class_name,
        "asset_refs": refs,
        "_literals": literals,
        "_container": {
            "variant": cf.variant, "hdr_a": cf.hdr_a, "flags": cf.flags,
            "extra": cf.extra, "type_tag": cf.type_tag,
            "section_lens": [len(s.payload) for s in cf.sections],
            "ref_offsets": offsets,
            "ref_orig_lens": [len(r.encode("utf-8")) for r in refs],
            "classes": [
                [c.name, c.class_id, c.version_major, c.version_minor,
                 c.parent_id]
                for c in cf.classes
            ],
        },
    }


def _encode(source: bytes) -> bytes:
    doc = json.loads(source)
    literals = [bytes.fromhex(h) for h in doc["_literals"]]
    refs = [r.encode("utf-8") for r in doc["asset_refs"]]
    c = doc["_container"]
    offsets = c["ref_offsets"]
    orig_lens = c["ref_orig_lens"]
    section_lens = list(c["section_lens"])

    # Reassemble the concatenated stream: literal, ref, literal, ref, ...
    out = bytearray(literals[0])
    for idx, ref in enumerate(refs):
        out += struct.pack("<I", len(ref)) + ref
        out += literals[idx + 1]
    concat = bytes(out)

    # Map each ref's byte delta (new - original length) to the section that
    # originally held it, so unedited files reproduce exactly and each edit
    # stays in its own section.
    if len(concat) != sum(section_lens):
        bounds = []
        acc = 0
        for sl in section_lens:
            bounds.append((acc, acc + sl))
            acc += sl

        def sec_of(off: int) -> int:
            for si, (a, b) in enumerate(bounds):
                if a <= off < b:
                    return si
            return len(section_lens) - 1

        for idx, ref in enumerate(refs):
            delta = len(ref) - orig_lens[idx]
            if delta:
                section_lens[sec_of(offsets[idx])] += delta

    sections = []
    off = 0
    for sl in section_lens:
        sections.append(cooked.Section(payload=concat[off:off + sl]))
        off += sl
    cf = cooked.CookedFile(
        variant=c["variant"], hdr_a=c["hdr_a"], flags=c["flags"],
        extra=c["extra"], type_tag=c["type_tag"],
        classes=[cooked.ClassDef(n, i, vmaj, vmin, p)
                 for n, i, vmaj, vmin, p in c["classes"]],
        sections=sections,
    )
    return cooked.emit(cf)


class AssetRefsHandler(SchemaHandler):
    """Byte-stable passthrough that lifts embedded asset paths into an
    editable `asset_refs` list. Bound to one class name."""

    def __init__(self, class_name: str, source_ext: str) -> None:
        super().__init__(class_name=class_name, source_ext=source_ext,
                         decoded=True, encoded=True)

    def decode_cooked(self, cooked_bytes: bytes) -> bytes:
        return json.dumps(_decode(cooked_bytes, self.class_name),
                          indent=2).encode("utf-8")

    def encode_container(self, source: bytes) -> bytes:
        return _encode(source)


_HANDLERS = [
    AssetRefsHandler("oCScheduledVfxSettings", "vfxsettings.json"),
    AssetRefsHandler("oCGameStream", "gamestream.json"),
    AssetRefsHandler("oCCollisionMesh", "collisionmesh.json"),
    AssetRefsHandler("oCMaterial", "material.json"),
]

for _h in _HANDLERS:
    register(_h)
