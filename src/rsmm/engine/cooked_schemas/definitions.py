"""oCDt*Definition / *Definition game-data-table classes → editable JSON.

These cooked `.yqz` files hold the game's balance / content data tables
(enemy tribes, rewards, achievements, ...). They all derive from a shared
`oCDtDefinition` base (`FUN_14030f880`, uid 0x1768ce8e) whose serialized
body is just two version-gated `u8` flags, then each leaf class appends its
own fields.

This module decodes the tractable leaf classes to byte-stable, field-level
editable JSON and rebuilds the cooked container deterministically from a
per-class framing template (every shipped file of a given class shares one
template — verified per class).

Implemented so far:
  - oCDtEnemyTribeDefinition (v1.1)

Each handler is small; adding a leaf class means adding a `_DefSpec` with
its body decode/encode and its container template. The bulk per-class work
is reversing that leaf body from the class `Serialize` (VAs in
`data/cooked_class_map.json`).
"""

from __future__ import annotations

import json
import struct
from collections.abc import Callable
from dataclasses import dataclass

from .. import cooked
from . import register
from .base import SchemaHandler

MARK_BEGIN = b"\x11\x11\xbb\xaa"
MARK_END = b"\x22\x22\xbb\xaa"


def _rd_lstr(b: bytes, o: int) -> tuple[str, int]:
    n = struct.unpack_from("<I", b, o)[0]
    return b[o + 4:o + 4 + n].decode("utf-8", errors="replace"), o + 4 + n


def _wr_lstr(s: str) -> bytes:
    e = s.encode("utf-8")
    return struct.pack("<I", len(e)) + e


@dataclass
class _DefSpec:
    """One leaf-definition class: how to (de)serialize its section body and
    how to frame the cooked container.

    When `embed_container` is True the cooked container's framing + class
    table is round-tripped through a `_container` block in the JSON instead
    of a fixed template — required for classes whose class table varies
    between files (e.g. an optional sub-object class appears only when a
    nested vector is non-empty).
    """
    class_name: str
    source_ext: str
    decode_body: Callable[[bytes], dict]
    encode_body: Callable[[dict], bytes]
    classes: list[cooked.ClassDef]
    variant: str = "A"
    hdr_a: int = 0x10
    flags: int = 0x01
    extra: int = 1
    type_tag: int = 0x31
    sec0: bytes = b"\x00\x00\x00\x00"
    embed_container: bool = False


# ---------------------------------------------------------------------------
# oCDtEnemyTribeDefinition (v1.1)
# ---------------------------------------------------------------------------
# Serialize FUN_14031b080:
#   1. oCDtDefinition base (FUN_14030f880): u32 res, then 2 u8 flags
#   2. FUN_140337a10 vector<TResourcePtr> at +0x2a0 (count==0 in corpus)
#   3. u8 at +0x2b0
#   4. (v>=1) SubObject<oCCustomFlagList> at +0x288:
#        u32 list_ver, u32 count, count x lstring (tribe flag names)

def _tribe_decode(body: bytes) -> dict:
    o = 0
    res = struct.unpack_from("<I", body, o)[0]
    o += 4
    base_a = body[o]
    base_b = body[o + 1]
    o += 2
    vec_count = struct.unpack_from("<I", body, o)[0]
    o += 4
    entries: list[list[str]] = []
    for _ in range(vec_count):
        s1, o = _rd_lstr(body, o)
        s2, o = _rd_lstr(body, o)
        entries.append([s1, s2])
    u2b0 = body[o]
    o += 1
    if body[o:o + 4] != MARK_BEGIN:
        raise ValueError("oCDtEnemyTribeDefinition: expected flag-list BEGIN")
    o += 4
    list_ver = struct.unpack_from("<I", body, o)[0]
    o += 4
    n = struct.unpack_from("<I", body, o)[0]
    o += 4
    flags: list[str] = []
    for _ in range(n):
        s, o = _rd_lstr(body, o)
        flags.append(s)
    if body[o:o + 4] != MARK_END:
        raise ValueError("oCDtEnemyTribeDefinition: expected flag-list END")
    o += 4
    tail = body[o:]
    return {
        "rsmm_class": "oCDtEnemyTribeDefinition",
        "tribe_flags": flags,
        "base_flags": [base_a, base_b],
        "_res": res,
        "_vec_entries": entries,
        "_u2b0": u2b0,
        "_flaglist_ver": list_ver,
        "_tail_b64": tail.hex(),
    }


def _tribe_encode(d: dict) -> bytes:
    out = bytearray()
    out += struct.pack("<I", int(d.get("_res", 0)))
    ba, bb = d.get("base_flags", [0, 0])
    out += bytes([int(ba) & 0xFF, int(bb) & 0xFF])
    entries = d.get("_vec_entries", [])
    out += struct.pack("<I", len(entries))
    for s1, s2 in entries:
        out += _wr_lstr(s1) + _wr_lstr(s2)
    out += bytes([int(d.get("_u2b0", 0)) & 0xFF])
    out += MARK_BEGIN
    flags = d["tribe_flags"]
    out += struct.pack("<II", int(d.get("_flaglist_ver", 4)), len(flags))
    for s in flags:
        out += _wr_lstr(s)
    out += MARK_END
    out += bytes.fromhex(d.get("_tail_b64", ""))
    return bytes(out)


_TRIBE = _DefSpec(
    class_name="oCDtEnemyTribeDefinition",
    source_ext="enemytribedef.json",
    decode_body=_tribe_decode,
    encode_body=_tribe_encode,
    classes=[
        cooked.ClassDef("oCDtEnemyTribeDefinition", 0x176dc2eb, 1, 1, 0x1768ce8e),
        cooked.ClassDef("oCDtDefinition", 0x1768ce8e, 1, 1, 0x17b6),
        cooked.ClassDef("oIResource", 0x17b6, 1, 1, 0x1da16c),
        cooked.ClassDef("oISerializable", 0x1da16c, 1, 0, 0xffffffff),
        cooked.ClassDef("oCCustomFlagList", 0x15a9d9be, 1, 0, 0x1da16c),
    ],
)


# ---------------------------------------------------------------------------
# oCDtEnemyDefinition (v1.6)
# ---------------------------------------------------------------------------
# Serialize FUN_140319b30:
#   1. oCDtDefinition base: u32 res + 2 u8 flags
#   2. TResourcePtr entity_ref (FUN_1401c8720) at +0x288: 2 lstrings
#      (settings-class-name + entity asset path)
#   3. SubObject<oCCustomFlagList> at +0x2c0: combat/role flag names
#   4. f32 spawn_weight at +0x2dc
#   5. TResourcePtr tribe_ref (FUN_1401c8720) at +0x2e8: 2 lstrings
#   6. trailing version-gated scalars + sub-object vectors (MaxOccurence,
#      FUN_140337e50). Preserved verbatim as an opaque `_tail` — byte-stable
#      without fully typing every v1.0..1.6 migration field.

def _enemy_decode(body: bytes) -> dict:
    o = 0
    res = struct.unpack_from("<I", body, o)[0]
    o += 4
    base_a = body[o]
    base_b = body[o + 1]
    o += 2
    e1, o = _rd_lstr(body, o)
    e2, o = _rd_lstr(body, o)
    if body[o:o + 4] != MARK_BEGIN:
        raise ValueError("oCDtEnemyDefinition: expected flag-list BEGIN")
    o += 4
    list_ver = struct.unpack_from("<I", body, o)[0]
    o += 4
    n = struct.unpack_from("<I", body, o)[0]
    o += 4
    flags: list[str] = []
    for _ in range(n):
        s, o = _rd_lstr(body, o)
        flags.append(s)
    if body[o:o + 4] != MARK_END:
        raise ValueError("oCDtEnemyDefinition: expected flag-list END")
    o += 4
    spawn_weight = struct.unpack_from("<f", body, o)[0]
    o += 4
    t1, o = _rd_lstr(body, o)
    t2, o = _rd_lstr(body, o)
    return {
        "rsmm_class": "oCDtEnemyDefinition",
        "entity_ref": [e1, e2],
        "tribe_ref": [t1, t2],
        "flags": flags,
        "spawn_weight": spawn_weight,
        "base_flags": [base_a, base_b],
        "_res": res,
        "_flaglist_ver": list_ver,
        "_tail_hex": body[o:].hex(),
    }


def _enemy_encode(d: dict) -> bytes:
    out = bytearray()
    out += struct.pack("<I", int(d.get("_res", 0)))
    ba, bb = d.get("base_flags", [0, 0])
    out += bytes([int(ba) & 0xFF, int(bb) & 0xFF])
    out += _wr_lstr(d["entity_ref"][0]) + _wr_lstr(d["entity_ref"][1])
    out += MARK_BEGIN
    out += struct.pack("<II", int(d.get("_flaglist_ver", 4)), len(d["flags"]))
    for s in d["flags"]:
        out += _wr_lstr(s)
    out += MARK_END
    out += struct.pack("<f", float(d["spawn_weight"]))
    out += _wr_lstr(d["tribe_ref"][0]) + _wr_lstr(d["tribe_ref"][1])
    out += bytes.fromhex(d.get("_tail_hex", ""))
    return bytes(out)


_ENEMY = _DefSpec(
    class_name="oCDtEnemyDefinition",
    source_ext="enemydef.json",
    decode_body=_enemy_decode,
    encode_body=_enemy_encode,
    classes=[],          # class table varies; round-tripped via _container
    embed_container=True,
)


# ---------------------------------------------------------------------------
# Field-DSL: declarative body codec for the simpler definition classes.
# ---------------------------------------------------------------------------
# A class body is: u32 res, u8 base_a, u8 base_b, then an ordered list of
# (name, type) fields, then an opaque `_tail_hex` capturing everything else
# (version-gated trailing scalars / sub-object vectors we don't type).
# Field types: tresptr (2 lstrings), lstr, f32, u32, u8, flaglist
# (oCCustomFlagList = BEGIN, u32 ver, u32 count, count x lstring, END).

def _read_field(b: bytes, o: int, t: str):
    if t == "tresptr":
        s1, o = _rd_lstr(b, o)
        s2, o = _rd_lstr(b, o)
        return [s1, s2], o
    if t == "lstr":
        return _rd_lstr(b, o)
    if t == "f32":
        return struct.unpack_from("<f", b, o)[0], o + 4
    if t == "u32":
        return struct.unpack_from("<I", b, o)[0], o + 4
    if t == "u8":
        return b[o], o + 1
    if t == "blob16":
        return b[o:o + 16].hex(), o + 16
    if t == "flaglist":
        if b[o:o + 4] != MARK_BEGIN:
            raise ValueError("flaglist: expected BEGIN")
        o += 4
        ver, cnt = struct.unpack_from("<II", b, o)
        o += 8
        flags = []
        for _ in range(cnt):
            s, o = _rd_lstr(b, o)
            flags.append(s)
        if b[o:o + 4] != MARK_END:
            raise ValueError("flaglist: expected END")
        o += 4
        return {"ver": ver, "flags": flags}, o
    raise ValueError(f"unknown field type {t}")


def _write_field(t: str, v) -> bytes:
    if t == "tresptr":
        return _wr_lstr(v[0]) + _wr_lstr(v[1])
    if t == "lstr":
        return _wr_lstr(v)
    if t == "f32":
        return struct.pack("<f", float(v))
    if t == "u32":
        return struct.pack("<I", int(v))
    if t == "u8":
        return bytes([int(v) & 0xFF])
    if t == "blob16":
        return bytes.fromhex(v)
    if t == "flaglist":
        out = bytearray(MARK_BEGIN)
        out += struct.pack("<II", int(v["ver"]), len(v["flags"]))
        for s in v["flags"]:
            out += _wr_lstr(s)
        out += MARK_END
        return bytes(out)
    raise ValueError(f"unknown field type {t}")


def _make_dsl(class_name: str, fields: list[tuple[str, str]]):
    def decode(body: bytes) -> dict:
        o = 0
        res = struct.unpack_from("<I", body, o)[0]
        o += 4
        base_a, base_b = body[o], body[o + 1]
        o += 2
        doc: dict = {"rsmm_class": class_name}
        for name, t in fields:
            v, o = _read_field(body, o, t)
            doc[name] = v
        doc["base_flags"] = [base_a, base_b]
        doc["_res"] = res
        doc["_tail_hex"] = body[o:].hex()
        return doc

    def encode(d: dict) -> bytes:
        out = bytearray(struct.pack("<I", int(d.get("_res", 0))))
        ba, bb = d.get("base_flags", [0, 0])
        out += bytes([int(ba) & 0xFF, int(bb) & 0xFF])
        for name, t in fields:
            out += _write_field(t, d[name])
        out += bytes.fromhex(d.get("_tail_hex", ""))
        return bytes(out)

    return decode, encode


def _dsl_spec(class_name: str, ext: str, fields: list[tuple[str, str]]) -> _DefSpec:
    dec, enc = _make_dsl(class_name, fields)
    return _DefSpec(
        class_name=class_name, source_ext=ext,
        decode_body=dec, encode_body=enc, classes=[], embed_container=True,
    )


_DSL_SPECS = [
    _dsl_spec("oCDtDreamShardDefinition", "dreamsharddef.json",
              [("entity_ref", "tresptr")]),
    _dsl_spec("oCDtEnemyCampDifficultyDefinition", "enemycampdifficultydef.json",
              [("field_a", "u32"), ("value_a", "f32"), ("value_b", "f32")]),
    _dsl_spec("oCDtEnemyCampTierDefinition", "enemycamptierdef.json",
              [("value_a", "f32"), ("value_b", "f32"), ("field_a", "u32")]),
    _dsl_spec("oCDtIngredientDefinition", "ingredientdef.json",
              [("icon_ref", "tresptr"), ("name", "lstr")]),
    _dsl_spec("oCDtMapDefinition", "mapdef.json",
              [("level_ref", "tresptr"), ("field_a", "u32"), ("tribe_ref", "tresptr")]),
    _dsl_spec("MelodyDefinition", "melodydef.json",
              [("field_a", "u32"), ("entity_ref", "tresptr")]),
    # Leading editable refs exposed; remaining version-gated / sub-object
    # data preserved verbatim in `_tail_hex`.
    _dsl_spec("oCDtTileDefinition", "tiledef.json",
              [("entity_ref", "tresptr")]),
    _dsl_spec("GameModifierDefinition", "gamemodifierdef.json",
              [("icon_ref", "tresptr"), ("field_a", "u32"), ("text_ref", "tresptr")]),
    _dsl_spec("ChallengeDefinition", "challengedef.json",
              [("field_a", "u32"), ("text_ref", "tresptr")]),
    _dsl_spec("AchievementDefinition", "achievementdef.json",
              [("guid", "blob16"), ("field_a", "u32"), ("flag_a", "u8"),
               ("flag_b", "u8"), ("name", "lstr")]),
    _dsl_spec("oCDtHeroDefinition", "herodef.json", []),
    _dsl_spec("oCDtRewardDefinition", "rewarddef.json", []),
    _dsl_spec("GameModeDefaultDefinition", "gamemodedefaultdef.json",
              [("field_a", "u32")]),
    _dsl_spec("VersionDefinition", "versiondef.json", []),
]


_SPECS: dict[str, _DefSpec] = {
    s.class_name: s for s in (_TRIBE, _ENEMY, *_DSL_SPECS)
}


class DefinitionHandler(SchemaHandler):
    """Generic handler bound to one `_DefSpec`. Byte-stable JSON round-trip;
    the container is rebuilt deterministically from the spec's template."""

    def __init__(self, spec: _DefSpec) -> None:
        super().__init__(
            class_name=spec.class_name,
            source_ext=spec.source_ext,
            decoded=True,
            encoded=True,
        )
        self._spec = spec

    def decode(self, payload: bytes) -> bytes:
        # Flat section concatenation: sec0 prelude + body.
        body = payload[len(self._spec.sec0):]
        return json.dumps(self._spec.decode_body(body), indent=2).encode("utf-8")

    def decode_cooked(self, cooked_bytes: bytes) -> bytes:
        cf = cooked.parse(cooked_bytes)
        doc = self._spec.decode_body(cf.sections[-1].payload)
        if self._spec.embed_container:
            doc["_container"] = {
                "variant": cf.variant, "hdr_a": cf.hdr_a, "flags": cf.flags,
                "extra": cf.extra, "type_tag": cf.type_tag,
                # All sections except the last (the editable body) pass through
                # verbatim — multi-section definition files split nested
                # sub-objects into their own sections.
                "lead_sections_hex": [s.payload.hex() for s in cf.sections[:-1]],
                "classes": [
                    [c.name, c.class_id, c.version_major, c.version_minor,
                     c.parent_id]
                    for c in cf.classes
                ],
            }
        return json.dumps(doc, indent=2).encode("utf-8")

    def encode(self, source: bytes) -> bytes:
        return self._spec.encode_body(json.loads(source))

    def encode_container(self, source: bytes) -> bytes:
        spec = self._spec
        doc = json.loads(source)
        body = spec.encode_body(doc)
        c = doc.get("_container")
        if spec.embed_container and c is not None:
            lead = [cooked.Section(payload=bytes.fromhex(h))
                    for h in c["lead_sections_hex"]]
            cf = cooked.CookedFile(
                variant=c["variant"], hdr_a=c["hdr_a"], flags=c["flags"],
                extra=c["extra"], type_tag=c["type_tag"],
                classes=[
                    cooked.ClassDef(n, i, vmaj, vmin, p)
                    for n, i, vmaj, vmin, p in c["classes"]
                ],
                sections=[*lead, cooked.Section(payload=body)],
            )
            return cooked.emit(cf)
        cf = cooked.CookedFile(
            variant=spec.variant, hdr_a=spec.hdr_a, flags=spec.flags,
            extra=spec.extra, type_tag=spec.type_tag,
            classes=list(spec.classes),
            sections=[
                cooked.Section(payload=spec.sec0),
                cooked.Section(payload=body),
            ],
        )
        return cooked.emit(cf)


def decode_cooked_to_json(class_name: str, cooked_bytes: bytes) -> bytes:
    spec = _SPECS[class_name]
    cf = cooked.parse(cooked_bytes)
    return json.dumps(spec.decode_body(cf.sections[-1].payload), indent=2).encode("utf-8")


for _spec in _SPECS.values():
    register(DefinitionHandler(_spec))
