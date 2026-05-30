"""oCSkeleton schema (decode-side metadata).

Findings (see docs/RE_NOTES.md "Stage 5e"):
  - Class UID: 0x1617, current saved version 1.1
  - oCSkeleton::Serialize @ 0x1405b4c40 reads a bone vector at this+0x98
    via FUN_1405cb350.
  - Per-bone struct = 304 (0x130) bytes in-memory; bones are emitted as
    embedded BEGIN/END-bracketed sub-objects via stream slot +0xa0.
  - Bone payload format: oCBone::Serialize (UID 0x1614, v1.1). Bind-pose
    translation at bone+0x118 (3 floats).
  - AABB at oCSkeleton+0xa8..+0xbc (6 floats), version-gated.

Decoder here exposes bone count + raw payload so the Author UI inspector
can surface skeleton metadata without a full glTF-ready bone-graph
reconstruction. Encode (cooker quantization path) is TBD.
"""

from __future__ import annotations

from . import register
from .base import SchemaHandler

UID = 0x1617
CURRENT_VERSION = (1, 1)
BONE_UID = 0x1614
BONE_STRUCT_SIZE = 0x130

MARK_BEGIN = b"\x11\x11\xbb\xaa"
MARK_END = b"\x22\x22\xbb\xaa"


def count_bone_subobjects(payload: bytes) -> int:
    """Count top-level BEGIN/END sub-objects within the section payload.

    Each per-bone Serialize emits one bracketed sub-object via stream
    slot +0xa0. Scanner walks u32-aligned to avoid false positives in
    f32 fields whose bytes happen to spell a marker.
    """
    depth = 0
    count = 0
    pos = 0
    n = len(payload)
    while pos + 4 <= n:
        tag = payload[pos:pos + 4]
        if tag == MARK_BEGIN:
            if depth == 0:
                count += 1
            depth += 1
            pos += 4
            continue
        if tag == MARK_END:
            depth -= 1
            pos += 4
            continue
        pos += 1
    return count


class SkeletonHandler(SchemaHandler):
    def __init__(self) -> None:
        super().__init__(class_name="oCSkeleton", source_ext="json",
                         decoded=False, encoded=False)

    def bone_count(self, payload: bytes) -> int:
        return count_bone_subobjects(payload)


register(SkeletonHandler())
