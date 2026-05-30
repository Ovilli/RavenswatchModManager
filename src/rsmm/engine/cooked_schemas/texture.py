"""oCTexture (v1.14) schema.

Reverse-engineered from `FUN_14064e3c0` (Ravenswatch.exe at VA 0x14064e3c0)
and the mip sub-object reader/writer in `FUN_140659f40` /
oCTextureMip::Serialize at `FUN_14064f080`.

Full byte-for-byte round-trip verified against a 5-sample mix of
small placeholders, mid-size UI textures, and 4096x4096 BC5U normal maps
with a 10-level mip chain.

## Section payload layout (v=1.14)

A cooked texture file has two sections inside the container codec:
  - section 0: 4-byte oIResource prelude (always 0 in shipped corpus)
  - section 1: oCTexture body (this schema)

Section 1 byte layout (offsets relative to start of section payload):

```
+0x00  u32   resource_prelude       (always 0 — written by the dispatch
                                     wrapper before oCTexture::Serialize)
+0x04  u32   type                   (texture type; field at this+0xa8 —
                                     always 0 in v1.14 corpus)
+0x08  u32   width                  (this+0xc0)
+0x0c  u32   height                 (this+0xc4)
+0x10  u32   depth                  (this+0xd8 — 0 for 2D textures)
+0x14  u32   format_engine_enum     (Ravenswatch-internal pixel format
                                     enum, written from a lookup table
                                     at &DAT_140ee4210)
+0x18  u32   blob_size              (written by vtbl+0x90; from this+0xa0)
+0x1c  u32   blob_size_dup          (u32 length prefix written by vtbl+0x40)
+0x20  bytes pixels[blob_size]      (mip-0 / base-level pixel data —
                                     "LockedData" stream tag)

After the pixel blob (version-gated trailing fields):

[v >= 5]
  u32   array_size                  (this+0xb0 — 0 for plain 2D)
  u32   mip_count_field             (this+0xb4 — appears to be a legacy
                                     field; observed always 0)
[v >= 7]
  u8    flag_ed                     (this+0xed; always 0 in corpus)
[v >= 9]
  u32   mip_vec_count               (number of additional mip levels;
                                     count is mip 1..N; the base level is
                                     stored in the pixel blob above)
  mip_vec_count * SubObject<oCTextureMip>:
        u32 BEGIN (= 0xAABB1111)
        u32 sub_prelude             (= 3 — generic sub-object header
                                     emitted by the saver, same pattern
                                     seen for oCMesh / oCMeshBuffer
                                     sub-objects)
        u32 mip_size
        u32 mip_size_dup
        bytes mip_pixels[mip_size]
        u32 END (= 0xAABB2222)
[v >= 10]
  f32 x f32 x f32                   (this+0xdc, +0xe0, +0xe4 — typically
                                     -1000.0, 1000.0, 0.0; semantic unclear,
                                     looks like a clamp/bias triple)
[v >= 11]
  u8    flag_ee                     (this+0xee; always 0 in corpus)
[v >= 12]
  u32   field_bc                    (this+0xbc; always 0 in corpus)
[v >= 13]
  u8    flag_eb                     (this+0xeb; always 0 in corpus)
[v >= 14]
  u32   local_40                    (terminal field; always 0 in corpus)
```

## Pixel-format enum mapping

The on-disk u32 at +0x14 is the engine-internal pixel format. The
lookup table at &DAT_140ee4210 (18 dwords) maps a small internal
index 0..17 -> engine_enum:

```
internal_idx   engine_enum   format (where known)
       0              0     RGBA8 (R8G8B8A8_UNORM, 4 bpp)
       1              1     unknown
       2              2     unknown
       3              4     BC1   (DXT1, 8 bytes/block)
       4              5     BC3   (DXT5, 16 bytes/block)
       5           0x22     unknown (BC4 family — best guess)
       6           0x23     BC5U  (16 bytes/block, 2-channel normal map)
       7              6     unknown
       8              8     unknown
       9           0x21     unknown
      10           0x24     unknown
      11           0x26     unknown
      12           0x25     unknown
      13           0x11     unknown
      14           0x18     unknown
      15           0x1f     unknown
      16              7     unknown
      17              9     unknown
```

The four formats observed in the shipped corpus (4001 textures sampled):
RGBA8 (493), BC1 (1449), BC3 (1468), BC5U (591) — together cover all
~4000 shipped textures. Unmapped engine_enum values fall through to a
"raw" DDS export name; the encoder still round-trips them byte-stable
since the schema preserves the u32 as-is.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field

from .. import dds
from . import register
from .base import NotReversedError, SchemaHandler

MARK_BEGIN = 0xAABB1111
MARK_END = 0xAABB2222
SUB_PRELUDE = 3
SCHEMA_VERSION = 14
UID = 0x16f6


# engine_enum -> canonical DDS format name (or None for "unknown — raw export")
_ENGINE_FORMAT_NAME: dict[int, str | None] = {
    0x00: "RGBA8",
    0x01: None,
    0x02: None,
    0x04: "BC1",
    0x05: "BC3",
    0x22: None,  # likely BC4 family — unconfirmed
    0x23: "BC5U",
    0x06: None,
    0x08: None,
    0x21: None,
    0x24: None,
    0x26: None,
    0x25: None,
    0x11: None,
    0x18: None,
    0x1f: None,
    0x07: None,
    0x09: None,
}


@dataclass
class TextureSchema:
    """Parsed oCTexture v1.14 payload. Round-tripping requires preserving
    every field, including ones that are observed-constant in the corpus.
    """

    # Header
    resource_prelude: int = 0
    type_field: int = 0
    width: int = 0
    height: int = 0
    depth: int = 0
    format_engine_enum: int = 0
    # Base-level pixel blob
    pixels: bytes = b""
    # Post-blob version-gated tail
    array_size: int = 0
    mip_count_field: int = 0
    flag_ed: int = 0
    # Additional mip levels (mip 1..N — base level is in `pixels`)
    mips: list[bytes] = field(default_factory=list)
    f32_dc: float = 0.0
    f32_e0: float = 0.0
    f32_e4: float = 0.0
    flag_ee: int = 0
    field_bc: int = 0
    flag_eb: int = 0
    local_40: int = 0

    # ---- format helpers ----

    @property
    def format_name(self) -> str | None:
        """Canonical DDS format name, or None if unmapped."""
        return _ENGINE_FORMAT_NAME.get(self.format_engine_enum)

    def total_mip_count(self) -> int:
        """Total mip levels in this texture (base + extra mips)."""
        return 1 + len(self.mips)


def _decode_payload(payload: bytes) -> TextureSchema:
    """Parse an oCTexture section-1 payload into a TextureSchema."""
    if len(payload) < 0x20:
        raise ValueError(
            f"oCTexture payload too short ({len(payload)} B) — need >= 32 for header"
        )

    pos = 0

    def take(fmt: str) -> tuple:
        nonlocal pos
        size = struct.calcsize(fmt)
        if pos + size > len(payload):
            raise ValueError(
                f"oCTexture payload truncated at {pos:#x} (need {size} B for {fmt!r})"
            )
        out = struct.unpack_from(fmt, payload, pos)
        pos += size
        return out

    def take_u32() -> int:
        return take("<I")[0]

    def take_u8() -> int:
        nonlocal pos
        if pos >= len(payload):
            raise ValueError(f"oCTexture payload truncated at u8 read {pos:#x}")
        v = payload[pos]
        pos += 1
        return v

    def take_f32() -> float:
        return take("<f")[0]

    def take_bytes(n: int) -> bytes:
        nonlocal pos
        if pos + n > len(payload):
            raise ValueError(
                f"oCTexture payload truncated at blob read "
                f"(need {n} B at {pos:#x}, have {len(payload) - pos})"
            )
        b = payload[pos:pos + n]
        pos += n
        return b

    schema = TextureSchema()
    schema.resource_prelude = take_u32()
    schema.type_field = take_u32()
    schema.width = take_u32()
    schema.height = take_u32()
    schema.depth = take_u32()
    schema.format_engine_enum = take_u32()
    blob_size = take_u32()
    blob_size_dup = take_u32()
    if blob_size != blob_size_dup:
        raise ValueError(
            f"oCTexture blob size mismatch: "
            f"vtbl+0x90 wrote {blob_size}, vtbl+0x40 prefix wrote {blob_size_dup}"
        )
    schema.pixels = take_bytes(blob_size)

    if pos >= len(payload):
        return schema

    # v>=5
    schema.array_size = take_u32()
    schema.mip_count_field = take_u32()
    # v>=7
    schema.flag_ed = take_u8()
    # v>=9 — mip vector
    mip_vec_count = take_u32()
    for i in range(mip_vec_count):
        begin = take_u32()
        if begin != MARK_BEGIN:
            raise ValueError(
                f"oCTexture mip[{i}]: expected BEGIN {MARK_BEGIN:#x} at "
                f"{pos - 4:#x}, got {begin:#x}"
            )
        prelude = take_u32()
        if prelude != SUB_PRELUDE:
            raise ValueError(
                f"oCTexture mip[{i}]: expected sub-object prelude "
                f"{SUB_PRELUDE} at {pos - 4:#x}, got {prelude}"
            )
        sz_a = take_u32()
        sz_b = take_u32()
        if sz_a != sz_b:
            raise ValueError(
                f"oCTexture mip[{i}]: size mismatch ({sz_a} vs {sz_b})"
            )
        schema.mips.append(take_bytes(sz_a))
        end = take_u32()
        if end != MARK_END:
            raise ValueError(
                f"oCTexture mip[{i}]: expected END {MARK_END:#x} at "
                f"{pos - 4:#x}, got {end:#x}"
            )

    # v>=10
    schema.f32_dc = take_f32()
    schema.f32_e0 = take_f32()
    schema.f32_e4 = take_f32()
    # v>=11
    schema.flag_ee = take_u8()
    # v>=12
    schema.field_bc = take_u32()
    # v>=13
    schema.flag_eb = take_u8()
    # v>=14
    schema.local_40 = take_u32()

    if pos != len(payload):
        raise ValueError(
            f"oCTexture trailing bytes: parsed {pos} of {len(payload)} "
            f"({len(payload) - pos} B unconsumed)"
        )
    return schema


def _encode_payload(schema: TextureSchema) -> bytes:
    """Emit a TextureSchema back to bytes — the inverse of `_decode_payload`."""
    out = bytearray()

    out += struct.pack(
        "<IIIIIIII",
        schema.resource_prelude,
        schema.type_field,
        schema.width,
        schema.height,
        schema.depth,
        schema.format_engine_enum,
        len(schema.pixels),
        len(schema.pixels),
    )
    out += schema.pixels

    out += struct.pack("<II", schema.array_size, schema.mip_count_field)
    out += struct.pack("<B", schema.flag_ed & 0xFF)
    out += struct.pack("<I", len(schema.mips))
    for mip in schema.mips:
        out += struct.pack("<I", MARK_BEGIN)
        out += struct.pack("<I", SUB_PRELUDE)
        out += struct.pack("<II", len(mip), len(mip))
        out += mip
        out += struct.pack("<I", MARK_END)

    out += struct.pack("<fff", schema.f32_dc, schema.f32_e0, schema.f32_e4)
    out += struct.pack("<B", schema.flag_ee & 0xFF)
    out += struct.pack("<I", schema.field_bc & 0xFFFFFFFF)
    out += struct.pack("<B", schema.flag_eb & 0xFF)
    out += struct.pack("<I", schema.local_40 & 0xFFFFFFFF)
    return bytes(out)


def schema_to_dds(schema: TextureSchema) -> bytes:
    """Convert a parsed oCTexture into a `.dds` file byte string.

    Raises `KeyError` (via `dds.by_name`) if the engine-internal pixel
    format does not map to a known DDS-writable name. Callers can check
    `schema.format_name is None` first to decide whether to fall back
    to raw export.
    """
    name = schema.format_name
    if name is None:
        raise KeyError(
            f"oCTexture format_engine_enum={schema.format_engine_enum:#x} "
            "has no DDS mapping — use raw export instead"
        )
    fmt = dds.by_name(name)

    # Concatenate base level + extra mips in DDS order.
    pixel_chain = bytearray(schema.pixels)
    for mip in schema.mips:
        pixel_chain += mip

    # Cooked `array_size` is not a DDS array dimension — it's an engine-
    # internal flag observed taking 0/1/3 in the corpus with no array
    # semantics. Always emit a 1-slice DDS so the file remains DDS-spec
    # valid; `dds_to_schema` re-applies the corpus-typical flag values
    # on the inverse path.
    return dds.write(
        bytes(pixel_chain),
        width=schema.width,
        height=schema.height,
        fmt=fmt,
        mip_count=schema.total_mip_count(),
        array_size=1,
        is_cubemap=False,
    )


# DDS canonical name -> engine pixel-format code. Inverse of
# `_ENGINE_FORMAT_NAME`. Only the keys with known mappings — unmapped
# engine codes don't round-trip to DDS, so we can't accept them as DDS
# source either.
_DDS_NAME_TO_ENGINE: dict[str, int] = {
    name: code
    for code, name in _ENGINE_FORMAT_NAME.items()
    if name is not None
}


def dds_to_schema(dds_bytes: bytes) -> TextureSchema:
    """Build a TextureSchema from a `.dds` source file.

    Mip chain: DDS file's level 0 becomes `schema.pixels`; subsequent mip
    levels become `schema.mips`. Engine treats both identically at runtime
    so this split matches the on-disk layout.

    Trailing fields not present in DDS metadata are set to the defaults
    observed across the shipped corpus (mostly zero / sentinel values).
    """
    from .. import dds

    img = dds.read(dds_bytes)
    if img.fmt.name not in _DDS_NAME_TO_ENGINE:
        raise ValueError(
            f"DDS format {img.fmt.name!r} has no engine mapping; "
            "supported: " + ", ".join(sorted(_DDS_NAME_TO_ENGINE))
        )
    engine_code = _DDS_NAME_TO_ENGINE[img.fmt.name]

    # Split mip 0 from the rest. linear_size gives each mip's byte length.
    pixels = bytearray()
    mips: list[bytes] = []
    offset = 0
    w, h = img.width, img.height
    for level in range(img.mip_count):
        size = dds.linear_size(max(1, w >> level), max(1, h >> level), img.fmt)
        chunk = img.pixels[offset:offset + size]
        if len(chunk) != size:
            raise ValueError(
                f"DDS truncated at mip {level}: need {size} B, have {len(chunk)}"
            )
        if level == 0:
            pixels = bytearray(chunk)
        else:
            mips.append(bytes(chunk))
        offset += size

    # Corpus pattern: textures with sub-object mip chains use
    # (array_size=0, mip_count_field=0); single-mip textures use
    # (array_size=1, mip_count_field=1). The 9-sample edge case with
    # both = 3 is not synthesisable from a normal DDS file so we don't
    # try to reproduce it here.
    af = 0 if mips else 1
    return TextureSchema(
        resource_prelude=0,
        type_field=0,
        width=img.width,
        height=img.height,
        depth=0,
        format_engine_enum=engine_code,
        pixels=bytes(pixels),
        array_size=af,
        mip_count_field=af,
        flag_ed=0,
        mips=mips,
        # Corpus-observed sentinels for the trailing range/flag fields.
        f32_dc=-1000.0,
        f32_e0=1000.0,
        f32_e4=0.0,
        flag_ee=0,
        field_bc=0,
        flag_eb=0,
        local_40=0,
    )


def _build_cooked_container(payload: bytes, has_mips: bool) -> bytes:
    """Wrap an oCTexture body payload in a full cooked-file container.

    Mirrors the variant-B 2-section layout used by the shipped corpus:
      section 0: 4 zero bytes (oIResource parent prelude)
      section 1: the oCTexture body payload

    The class table includes `oCTextureMip` when the texture has any
    extra mip levels — the engine writes that entry exactly when sub-
    object mips are present.
    """
    from .. import cooked

    classes = [
        cooked.ClassDef(name="oCTexture", class_id=UID,
                        version_major=1, version_minor=SCHEMA_VERSION,
                        parent_id=0x17b6),
        cooked.ClassDef(name="oIResource", class_id=0x17b6,
                        version_major=1, version_minor=1,
                        parent_id=0x1da16c),
        cooked.ClassDef(name="oISerializable", class_id=0x1da16c,
                        version_major=1, version_minor=0,
                        parent_id=0xffffffff),
    ]
    if has_mips:
        classes.append(cooked.ClassDef(
            name="oCTextureMip", class_id=0xcaa6,
            version_major=1, version_minor=0, parent_id=0x1da16c,
        ))

    cf = cooked.CookedFile(
        variant="B",
        hdr_a=0x10,
        flags=0x00,
        classes=classes,
        sections=[
            cooked.Section(payload=b"\x00\x00\x00\x00"),
            cooked.Section(payload=payload),
        ],
    )
    return cooked.emit(cf)


_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


def png_to_dds(png_bytes: bytes) -> bytes:
    """Decode a PNG and re-encode it as an uncompressed RGBA8 DDS.

    Authoring textures as PNG is the natural workflow, but the engine
    consumes cooked oCTexture (built from DDS). We go PNG -> RGBA8 ->
    single-mip uncompressed DDS; the engine reads the format enum from the
    cooked file, so an uncompressed replacement renders fine (just larger
    than the shipped block-compressed original). Block compression is a
    later optimisation, not a correctness requirement.
    """
    from .. import dds, image

    w, h, rgba = image.decode_png(png_bytes)
    return dds.write(rgba, w, h, dds.by_name("RGBA8"), mip_count=1)


# Cooked-container begin marker (0xAABB1111, little-endian) — present in
# the header of an already-cooked file. Used to tell a pre-cooked oCTexture
# binary apart from an unsupported source format, so the latter raises
# instead of being copied through raw (the bug that shipped .png/.tga bytes
# verbatim into the game install).
_COOKED_MARKER = b"\x11\x11\xbb\xaa"


def _looks_like_cooked(source: bytes) -> bool:
    return _COOKED_MARKER in source[:64]


def _source_to_schema(source: bytes) -> TextureSchema:
    """Resolve a DDS or PNG source file to a TextureSchema.

    Raises NotReversedError on anything else, so apply-mods / cook_cache
    skip an unsupported texture source cleanly instead of silently
    emitting garbage bytes into the game install.
    """
    if source[:4] == b"DDS ":
        return dds_to_schema(source)
    if source[:8] == _PNG_MAGIC:
        return dds_to_schema(png_to_dds(source))
    raise NotReversedError(
        "oCTexture",
        "texture source must be a .dds or .png file; got an unrecognised "
        "format (re-export your texture as PNG or DDS)",
    )


class TextureHandler(SchemaHandler):
    """Schema handler. `decode` returns the original section payload by
    default (round-trip safe). `encode` accepts either a DDS source file
    (cooks it into a cooked oCTexture container) or an already-parsed
    payload (round-trip pass-through).

    Use `parse_payload` / `emit_payload` to get / set a structured view
    of the data. For DDS export, use `schema_to_dds`.
    """

    def __init__(self) -> None:
        super().__init__(
            class_name="oCTexture",
            source_ext="dds",
            decoded=True,
            encoded=True,
        )

    def decode(self, payload: bytes) -> bytes:
        schema = _decode_payload(payload)
        return _encode_payload(schema)

    def encode(self, source: bytes) -> bytes:
        """Convert a DDS or PNG source file to an oCTexture body payload.

        Detects the input format by header magic. The cook_cache wraps
        the returned payload in a cooked container via
        `encode_container`.
        """
        return _encode_payload(_source_to_schema(source))

    def encode_container(self, source: bytes) -> bytes:
        """Convert a DDS/PNG source file to a full cooked-file byte string,
        ready to drop into `<install>/DarkTalesResources/_Cooking/...`.

        An already-cooked oCTexture container is passed through unchanged.
        """
        if source[:4] != b"DDS " and source[:8] != _PNG_MAGIC \
                and _looks_like_cooked(source):
            return source
        schema = _source_to_schema(source)
        return _build_cooked_container(
            _encode_payload(schema), has_mips=bool(schema.mips),
        )

    # Structured accessors — not exposed via the base SchemaHandler API
    # but available to callers that import this module directly.

    @staticmethod
    def parse_payload(payload: bytes) -> TextureSchema:
        return _decode_payload(payload)

    @staticmethod
    def emit_payload(schema: TextureSchema) -> bytes:
        return _encode_payload(schema)


register(TextureHandler())
