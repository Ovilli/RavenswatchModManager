"""oCGlobalEntityValueSettings (v1.1) — global gameplay value table.

204 `.yqz` files under `KlraglMzidisDglwqFqiidzyv` (cipher for
"GlobalEntityValueSettings"). Each holds a single named global value
("Hero Level", "Is_In_Epilog", "Altar pos", ...) plus an
`oCEntityValueUnion` carrying its default. These drive run-time game
logic checks, so exposing them as editable JSON unlocks balance / rule
mods without a hex editor.

Wire layout (from `FUN_1406de4e0` = oCGlobalEntityValueSettings::Serialize,
cross-checked byte-stable against all 204 shipped files)
-----------------------------------------------------------------------

Two container sections: `sec[0]` is the 4-byte oIResource parent prelude
(always `00 00 00 00`); `sec[1]` is the body below.

```
u32   res_prelude          (= 0)
lstring name               (vtbl +0x60 at this+0x68 — the value's key)
lstring string2            (vtbl +0x60 at this+0x78 — always empty in corpus)
SubObject<oCEntityValueUnion>   (vtbl +0xa0 at this+0x88, BEGIN/END framed)
u8 flag_be                 (vtbl +0x70 at this+0xbe)
u8 flag_bc                 (vtbl +0x70 at this+0xbc)
u8 flag_bf                 (vtbl +0x70 at this+0xbf — v >= 1, present in all)
```

`oCEntityValueUnion` (uid 0xd97f3e3, v1.6) body, inside the BEGIN/END:

```
u32 union_ver   (= 3 across corpus)
u32 type        0 = float, 1 = int, 2 = bool, 3 = vector3
u32 pad         (= 0 across corpus — a leading flag word, always zero)
value:
  type 0  f32           (4 B)
  type 1  i32           (4 B)
  type 2  u8            (1 B)
  type 3  3 × f32       (12 B)
```

Every shipped file shares one container framing template (variant A,
hdr_a 0x10, flags 0x1, extra 1, type_tag 0x31, fixed 4-class table), so
`encode_container` rebuilds the container deterministically from
`_TEMPLATE_CLASSES` — no original-bytes passthrough needed, the JSON is
fully self-describing and round-trips byte-stably.
"""

from __future__ import annotations

import json
import struct

from .. import cooked
from . import register
from .base import SchemaHandler

UID = 0x17929af2
CURRENT_VERSION = (1, 1)
UNION_VER = 3

MARK_BEGIN = b"\x11\x11\xbb\xaa"
MARK_END = b"\x22\x22\xbb\xaa"

# type tag -> name
_TYPE_NAMES = {0: "float", 1: "int", 2: "bool", 3: "vector"}
_TYPE_TAGS = {v: k for k, v in _TYPE_NAMES.items()}

# Fixed container framing shared by every shipped global-value file.
_TEMPLATE_CLASSES = [
    cooked.ClassDef("oCGlobalEntityValueSettings", 0x17929af2, 1, 1, 0x17b6),
    cooked.ClassDef("oIResource", 0x17b6, 1, 1, 0x1da16c),
    cooked.ClassDef("oISerializable", 0x1da16c, 1, 0, 0xffffffff),
    cooked.ClassDef("oCEntityValueUnion", 0xd97f3e3, 1, 6, 0x1da16c),
]


def _read_lstring(buf: bytes, pos: int) -> tuple[str, int]:
    n = struct.unpack_from("<I", buf, pos)[0]
    return buf[pos + 4:pos + 4 + n].decode("utf-8", errors="replace"), pos + 4 + n


def _decode_union(union: bytes) -> dict:
    ver, typ = struct.unpack_from("<II", union, 0)
    pad = struct.unpack_from("<I", union, 8)[0]
    val = union[12:]
    name = _TYPE_NAMES.get(typ)
    if name is None:
        raise ValueError(f"unknown oCEntityValueUnion type tag {typ}")
    if typ == 0:
        value: object = struct.unpack_from("<f", val, 0)[0]
    elif typ == 1:
        value = struct.unpack_from("<i", val, 0)[0]
    elif typ == 2:
        value = bool(val[0])
    else:  # vector3
        value = list(struct.unpack_from("<3f", val, 0))
    out = {"type": name, "value": value, "union_ver": ver}
    if pad != 0:
        out["_pad"] = pad
    return out


def _encode_union(v: dict) -> bytes:
    typ = _TYPE_TAGS[v["type"]]
    ver = int(v.get("union_ver", UNION_VER))
    pad = int(v.get("_pad", 0))
    out = struct.pack("<III", ver, typ, pad)
    val = v["value"]
    if typ == 0:
        out += struct.pack("<f", float(val))
    elif typ == 1:
        out += struct.pack("<i", int(val))
    elif typ == 2:
        out += struct.pack("<B", 1 if val else 0)
    else:
        out += struct.pack("<3f", *[float(c) for c in val])
    return out


def _parse_body(body: bytes) -> dict:
    o = 0
    res = struct.unpack_from("<I", body, o)[0]
    o += 4
    name, o = _read_lstring(body, o)
    string2, o = _read_lstring(body, o)
    if body[o:o + 4] != MARK_BEGIN:
        raise ValueError("expected oCEntityValueUnion BEGIN marker")
    o += 4
    ue = body.find(MARK_END, o)
    if ue < 0:
        raise ValueError("unterminated oCEntityValueUnion")
    value = _decode_union(body[o:ue])
    o = ue + 4
    flags = list(body[o:o + 3])
    return {
        "rsmm_class": "oCGlobalEntityValueSettings",
        "name": name,
        "string2": string2,
        "value": value,
        "flags": flags,
        "_res": res,
    }


def _build_body(doc: dict) -> bytes:
    out = bytearray()
    out += struct.pack("<I", int(doc.get("_res", 0)))
    name = doc["name"].encode("utf-8")
    out += struct.pack("<I", len(name)) + name
    s2 = doc.get("string2", "").encode("utf-8")
    out += struct.pack("<I", len(s2)) + s2
    out += MARK_BEGIN
    out += _encode_union(doc["value"])
    out += MARK_END
    flags = doc.get("flags", [0, 0, 0])
    out += bytes(int(f) & 0xFF for f in flags[:3]).ljust(3, b"\x00")
    return bytes(out)


def decode_cooked_to_json(cooked_bytes: bytes) -> bytes:
    cf = cooked.parse(cooked_bytes)
    doc = _parse_body(cf.sections[-1].payload)
    return json.dumps(doc, indent=2).encode("utf-8")


def encode_json_to_cooked(source: bytes) -> bytes:
    doc = json.loads(source)
    cf = cooked.CookedFile(
        variant="A",
        hdr_a=0x10,
        flags=0x01,
        extra=1,
        type_tag=0x31,
        classes=[
            cooked.ClassDef(c.name, c.class_id, c.version_major,
                            c.version_minor, c.parent_id)
            for c in _TEMPLATE_CLASSES
        ],
        sections=[
            cooked.Section(payload=b"\x00\x00\x00\x00"),
            cooked.Section(payload=_build_body(doc)),
        ],
    )
    return cooked.emit(cf)


class GlobalValuesHandler(SchemaHandler):
    """oCGlobalEntityValueSettings <-> editable JSON. Full byte-stable
    round-trip and field-level editability (no opaque passthrough)."""

    def __init__(self) -> None:
        super().__init__(
            class_name="oCGlobalEntityValueSettings",
            source_ext="globalvalue.json",
            decoded=True,
            encoded=True,
        )

    def decode(self, payload: bytes) -> bytes:
        # `payload` is the flat section concatenation (sec0 4-byte prelude +
        # body). Slice the prelude off and parse the body.
        return json.dumps(_parse_body(payload[4:]), indent=2).encode("utf-8")

    def decode_cooked(self, cooked_bytes: bytes) -> bytes:
        return decode_cooked_to_json(cooked_bytes)

    def encode(self, source: bytes) -> bytes:
        return _build_body(json.loads(source))

    def encode_container(self, source: bytes) -> bytes:
        return encode_json_to_cooked(source)


register(GlobalValuesHandler())
