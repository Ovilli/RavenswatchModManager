"""oCEntitySettingsResource → byte-stable JSON with editable entity path.

4699 `.yqz` files under `MzidisFqiidzyvLqvrwubq` (cipher for
"EntitySettingsResource"). Each wraps a single `oCEntitySettings`
sub-object (`oCEntitySettingsResource::Serialize` = `FUN_1406e5af0`, one
sub-object at +0x98). The settings body holds, for "spawnable" object
entities, a 16-byte GUID + a type string + the referenced `*.entity.ot`
asset path, followed by an arbitrarily nested component-value tree
(`oCEntityCpntValueSettings` / `oCEntityValueUnion`).

The family is heterogeneous: ~62% are spawnable entities carrying the
`EntitySettings` + entity-path pattern; the rest are component-only
variants with no model reference. Rather than fully type the recursive
component tree (deep, like the deferred VFX system), this handler:

- always round-trips **byte-stably** by preserving the raw stream as
  `_pre_hex` / `_post_hex` around the editable region plus the exact
  container framing + section split;
- exposes the editable **entity_path** (and type / guid) when the spawnable
  pattern is present, so mod authors can repoint an entity at a different
  model without a hex editor.

Container sections frequently split sub-objects mid-stream (a file can have
hundreds of sections, and a string may straddle a boundary), so all parsing
happens on the concatenated section bytes; on encode the concatenation is
re-split by the stored section lengths, with any length delta from an edit
absorbed into the section that contains the edit point.
"""

from __future__ import annotations

import json
import struct

from .. import cooked
from . import register
from .base import SchemaHandler

# Anchor for the spawnable-entity pattern: the GUID block is
# `u32(16) + 16 bytes guid + u32(1)`, immediately followed by `lstr type`
# and `lstr entity_path`. We locate it structurally so it works regardless
# of the (variable) type string.
_GUID_LEN_MARK = struct.pack("<I", 16)


def _find_entity_block(concat: bytes) -> tuple[int, str, str, int] | None:
    """Return (type_lstr_offset, type, path, end_offset) or None.

    `type_lstr_offset` is where the `u32 type_len` starts (right after the
    `u32(1)` that follows the 16-byte guid); `end_offset` is just past the
    entity path lstring.
    """
    n = len(concat)
    pos = 0
    while True:
        i = concat.find(_GUID_LEN_MARK, pos)
        if i < 0 or i + 24 + 4 > n:
            return None
        pos = i + 4
        # u32(1) must sit right after the 16-byte guid.
        if struct.unpack_from("<I", concat, i + 20)[0] != 1:
            continue
        toff = i + 24
        try:
            tlen = struct.unpack_from("<I", concat, toff)[0]
            if not (0 < tlen < 128) or toff + 4 + tlen + 4 > n:
                continue
            tbytes = concat[toff + 4:toff + 4 + tlen]
            poff = toff + 4 + tlen
            plen = struct.unpack_from("<I", concat, poff)[0]
            if poff + 4 + plen > n:
                continue
            pbytes = concat[poff + 4:poff + 4 + plen]
        except struct.error:
            continue
        if not all(32 <= c < 127 for c in tbytes):
            continue
        # Path should look like an asset path (printable, ends in ".ot").
        if not pbytes.endswith(b".ot"):
            continue
        return (toff,
                tbytes.decode("utf-8", errors="replace"),
                pbytes.decode("utf-8", errors="replace"),
                poff + 4 + plen)


def _decode(cooked_bytes: bytes) -> dict:
    cf = cooked.parse(cooked_bytes)
    concat = b"".join(s.payload for s in cf.sections)
    section_lens = [len(s.payload) for s in cf.sections]
    container = {
        "variant": cf.variant, "hdr_a": cf.hdr_a, "flags": cf.flags,
        "extra": cf.extra, "type_tag": cf.type_tag,
        "section_lens": section_lens,
        "classes": [
            [c.name, c.class_id, c.version_major, c.version_minor, c.parent_id]
            for c in cf.classes
        ],
    }
    doc: dict = {"rsmm_class": "oCEntitySettingsResource"}
    block = _find_entity_block(concat)
    if block is None:
        doc["entity_path"] = None
        doc["_pre_hex"] = concat.hex()
        doc["_post_hex"] = ""
    else:
        toff, tname, path, end = block
        doc["entity_type"] = tname
        doc["entity_path"] = path
        doc["_pre_hex"] = concat[:toff].hex()
        doc["_post_hex"] = concat[end:].hex()
    doc["_container"] = container
    return doc


def _encode(source: bytes) -> bytes:
    doc = json.loads(source)
    pre = bytes.fromhex(doc["_pre_hex"])
    post = bytes.fromhex(doc["_post_hex"])
    if doc.get("entity_path") is None:
        concat = pre + post
    else:
        tname = doc["entity_type"].encode("utf-8")
        path = doc["entity_path"].encode("utf-8")
        mid = (struct.pack("<I", len(tname)) + tname
               + struct.pack("<I", len(path)) + path)
        concat = pre + mid + post

    c = doc["_container"]
    section_lens = list(c["section_lens"])
    # Absorb any length delta (from an edited path/type) into the section that
    # contains the edit point (= len(pre)), so unedited files re-split exactly.
    total = sum(section_lens)
    delta = len(concat) - total
    if delta != 0:
        edit_at = len(pre)
        off = 0
        for idx, sl in enumerate(section_lens):
            if off + sl > edit_at or idx == len(section_lens) - 1:
                section_lens[idx] = sl + delta
                break
            off += sl
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


def decode_cooked_to_json(cooked_bytes: bytes) -> bytes:
    return json.dumps(_decode(cooked_bytes), indent=2).encode("utf-8")


def encode_json_to_cooked(source: bytes) -> bytes:
    return _encode(source)


class EntitySettingsHandler(SchemaHandler):
    """oCEntitySettingsResource <-> JSON. Byte-stable round-trip for the whole
    heterogeneous family; editable `entity_path` for spawnable entities."""

    def __init__(self) -> None:
        super().__init__(
            class_name="oCEntitySettingsResource",
            source_ext="entitysettings.json",
            decoded=True,
            encoded=True,
        )

    def decode_cooked(self, cooked_bytes: bytes) -> bytes:
        return decode_cooked_to_json(cooked_bytes)

    def encode_container(self, source: bytes) -> bytes:
        return encode_json_to_cooked(source)


register(EntitySettingsHandler())
