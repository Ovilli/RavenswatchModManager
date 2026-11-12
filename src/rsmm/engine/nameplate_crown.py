"""Native overhead crown layout prototype, explicitly NOT host selection.

The live 2026-11-11 capture confirmed Life Bar Spawner +0x88 -> the overhead
entity and its GameUi/Top Bar label widgets. The cooked entity embeds its
native widget descriptions. Append a stock picture description to the name
frame's child vector so the game's existing builder creates/owns/draws it.
No overlay, replacement text, executable patches, or bundled game artwork.

The geometry codec below is specific to oC2dElementDesc v1.14 and
oC2dPictureDesc v1.6. Serializer recon: 0x140570920 / 0x140574920 on b9c3.
Those addresses are documentation, never runtime call targets. Layout and
visibility still need an in-game visual check; SDK confidence is experimental.
"""
from __future__ import annotations

import math
import struct

from . import cooked
from .entity_append import validate_layout

TARGET = "EntitySettings/GameUis/Common_Ui/Life_Bar_Hero_Common.entity.ot.EntitySettingsResource.gen"
SOURCE = "EntitySettings/GameUis/All_Book_Pages/Hero_Display.entity.ot.EntitySettingsResource.gen"
WIDGET = "RSMM_Host_Crown"
FRAME = "Top_Bar_Text_Frame"


def _u32(blob: bytes, offset: int) -> int:
    return struct.unpack_from("<I", blob, offset)[0]


def _header(blob: bytes) -> tuple[int, int, str, int]:
    """Return child count, name-length offset, name, and end of name.

    v1.14 base: 2 bools, xy, 3 bools, wh, 2 bools, pivot xy,
    2 bools, 2 floats; then child ids, edition string, widget identifier.
    """
    if len(blob) < 57:
        raise ValueError("native UI descriptor is too short")
    count = _u32(blob, 45)
    if count > 512:
        raise ValueError("native UI child count is implausible")
    pos = 49 + count * 4
    if pos + 4 > len(blob):
        raise ValueError("truncated native UI children")
    edition_len = _u32(blob, pos)
    pos += 4 + edition_len
    if pos + 4 > len(blob):
        raise ValueError("truncated native UI edition string")
    size = _u32(blob, pos)
    end = pos + 4 + size
    if size > 256 or end > len(blob):
        raise ValueError("truncated native UI identifier")
    return count, pos, blob[pos + 4:end].decode("ascii"), end


def _class(cf: cooked.CookedFile, name: str, version: int) -> int:
    matches = [(i, c) for i, c in enumerate(cf.classes) if c.name == name]
    if len(matches) != 1 or (matches[0][1].version_major, matches[0][1].version_minor) != (1, version):
        raise ValueError(f"unsupported {name} version")
    return matches[0][0]


def _find(cf: cooked.CookedFile, cls: int, name: str) -> int:
    hits = []
    for i, section in enumerate(cf.sections[1:-1], 1):
        if len(section.payload) >= 4 and _u32(section.payload, 0) == cls:
            if _header(section.payload)[2] == name:
                hits.append(i)
    if len(hits) != 1:
        raise ValueError(f"expected one native widget {name!r}, found {len(hits)}")
    return hits[0]


def add_crown(target: bytes, source: bytes, *, preview: bool = False,
              width: float = 0.20, y: float = -0.12) -> bytes:
    """Append the game's crown to the overhead name frame.

    Default hidden. `preview=True` displays it on EVERY applicable nameplate
    for a solo geometry test. It must never be described as host detection.
    All pre-existing object ids and component links stay unchanged.
    """
    if type(preview) is not bool:
        raise ValueError("preview must be boolean")
    if not all(type(v) in (int, float) and math.isfinite(v) for v in (width, y)):
        raise ValueError("geometry must be finite numbers")
    if not 0.05 <= width <= 0.5 or not -1 <= y <= 0:
        raise ValueError("crown geometry outside the supported range")
    dst, src = cooked.parse(target), cooked.parse(source)
    count = validate_layout(dst)
    validate_layout(src)
    element = _class(dst, "oC2dElementDesc", 14)
    _class(src, "oC2dElementDesc", 14)
    picture = _class(dst, "oC2dPictureDesc", 6)
    source_picture = _class(src, "oC2dPictureDesc", 6)
    for sec in dst.sections[1:-1]:
        if _u32(sec.payload, 0) == picture and _header(sec.payload)[2] == WIDGET:
            raise ValueError("nameplate already contains the crown; start from pristine bytes")
    frame_index = _find(dst, element, FRAME)
    source_index = _find(src, source_picture, "Host_Picture")
    blob = src.sections[source_index].payload
    children, name_offset, _, end = _header(blob)
    if children != 0 or b"BookMenu\\LeaderPins.png" not in blob:
        raise ValueError("stock host picture no longer has the expected resource/leaf shape")
    new_name = WIDGET.encode("ascii")
    clone = bytearray(blob[:name_offset] + struct.pack("<I", len(new_name)) + new_name + blob[end:])
    struct.pack_into("<I", clone, 0, picture)
    struct.pack_into("<ff", clone, 6, 0.5, y)
    # Stock picture's zero height and preserved aspect flags derive its height
    # from width and the texture ratio. Center/bottom pivot puts it above name.
    struct.pack_into("<ff", clone, 17, width, 0.0)
    struct.pack_into("<ff", clone, 27, 0.5, 1.0)
    clone[35] = int(preview)
    frame = dst.sections[frame_index].payload
    child_count = _header(frame)[0]
    child_end = 49 + 4 * child_count
    dst.sections[frame_index].payload = (
        frame[:45] + struct.pack("<I", child_count + 1) + frame[49:child_end]
        + struct.pack("<I", count) + frame[child_end:]
    )
    directory = dst.sections[0].payload
    if len(directory) != 4 + count * 4:
        raise ValueError("unexpected object table suffix")
    dst.sections[0].payload = struct.pack("<I", count + 1) + directory[4:] + struct.pack("<I", picture)
    dst.sections.insert(-1, cooked.Section(bytes(clone)))
    validate_layout(dst)
    return cooked.emit(dst)
