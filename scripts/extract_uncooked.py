#!/usr/bin/env python3
"""
Extract Ravenswatch cooked assets to a readable mirror under data/uncooked/.

Reads data/asset_map.csv (encoded -> decoded paths). For each cooked file
in <game>/DarkTalesResources/_Cooking/<encoded>:

  - If the file is an oCTexture (.tpi container, decoded path ends in
    .png.Texture.dxt / .tga.Texture.dxt / .Texture.nrm): parse the
    container, decode BC1 / BC3 / RGBA8 pixel data, write as .png next
    to the decoded path with the .Texture.dxt suffix dropped.
  - Otherwise: copy the cooked bytes unchanged to the decoded path.

If a .rsmm.bak sits next to a cooked file (active rsmm-installed mod),
prefer the .bak so the mirror reflects pristine game state.
"""

import argparse
import csv
import os
import shutil
import struct
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

try:
    import texture2ddecoder
    from PIL import Image
except ImportError:
    sys.exit("missing deps: pip install --user texture2ddecoder Pillow")

# Repo importable (rsmm.engine.cooked_schemas) — script lives in scripts/.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from rsmm.engine import cooked as _cooked  # noqa: E402
from rsmm.engine import cooked_schemas as _schemas  # noqa: E402
from rsmm.engine.cooked_schemas import (  # noqa: E402
    animation as _anim_schema,
)
from rsmm.engine.cooked_schemas import (
    definitions as _def_schema,
)
from rsmm.engine.cooked_schemas import (
    entity_settings as _es_schema,
)
from rsmm.engine.cooked_schemas import (
    geometry as _geo_schema,
)
from rsmm.engine.cooked_schemas import (
    global_values as _gv_schema,
)

# Two fixed sentinel words (24 bytes). What follows: u32 extra-mip count,
# u32 width, u32 height, u32 unk, u32 format, u32 mip0_size, u32 mip0_size,
# then mip0 pixel data, then (if extra-mip count > 0) successive halved
# mips back-to-back.
TPI_SENTINEL = bytes.fromhex(
    "2222bbaa1111bbaa00000000"
    "2222bbaa1111bbaa00000000"
)

FMT_BC1 = 4    # DXT1
FMT_BC3 = 5    # DXT5
FMT_BC5 = 35   # ATI2 / 3Dc — used for .Texture.nrm normal maps
FMT_RGBA = 0   # uncompressed 4 bpp (BGRA order)

DEFAULT_GAME = Path.home() / ".var/app/com.valvesoftware.Steam/.local/share/Steam/steamapps/common/Ravenswatch"
TEXTURE_SUFFIXES = (".png.Texture.dxt", ".tga.Texture.dxt", ".png.Texture.nrm", ".tga.Texture.nrm")


def decode_tpi(raw: bytes):
    """Return (PIL.Image, w, h, fmt) or None if container shape unknown."""
    s = raw.find(TPI_SENTINEL)
    if s < 0:
        return None
    off = s + len(TPI_SENTINEL)
    if off + 28 > len(raw):
        return None
    _mips, w, h, _unk, fmt, sz1, _sz2 = struct.unpack_from("<7I", raw, off)
    if w == 0 or h == 0:
        return None
    px_off = off + 28
    px = raw[px_off:px_off + sz1]
    if len(px) < sz1:
        return None
    if fmt == FMT_BC1:
        rgba = texture2ddecoder.decode_bc1(px, w, h)
        return Image.frombytes("RGBA", (w, h), rgba, "raw", "BGRA"), w, h, fmt
    if fmt == FMT_BC3:
        rgba = texture2ddecoder.decode_bc3(px, w, h)
        return Image.frombytes("RGBA", (w, h), rgba, "raw", "BGRA"), w, h, fmt
    if fmt == FMT_BC5:
        # BC5 stores two channels (X,Y of a normal). Decoder returns RGBA
        # with R=X, G=Y, B=0, A=255. Reconstruct Z = sqrt(1 - X^2 - Y^2)
        # so the PNG actually looks like a normal map rather than a flat
        # red/green field.
        rgba = bytearray(texture2ddecoder.decode_bc5(px, w, h))
        for i in range(0, len(rgba), 4):
            nx = rgba[i + 2] / 127.5 - 1.0
            ny = rgba[i + 1] / 127.5 - 1.0
            nz2 = 1.0 - nx * nx - ny * ny
            nz = int((max(0.0, nz2) ** 0.5 + 1.0) * 127.5)
            rgba[i] = max(0, min(255, nz))
            rgba[i + 3] = 255
        return Image.frombytes("RGBA", (w, h), bytes(rgba), "raw", "BGRA"), w, h, fmt
    if fmt == FMT_RGBA and sz1 == w * h * 4:
        return Image.frombytes("RGBA", (w, h), px, "raw", "BGRA"), w, h, fmt
    return None


def decoded_to_png_path(decoded: str) -> str | None:
    """Strip the .Texture.dxt-style suffix so the output is <name>.png."""
    low = decoded.lower()
    for suf in TEXTURE_SUFFIXES:
        if low.endswith(suf.lower()):
            return decoded[:-len(suf)] + ".png"
    return None


_GEOMETRY_SUFFIXES = (".Geometry.gen", ".gen.Geometry.gen", ".geometry.gen")
_ANIMATION_SUFFIXES = (".Animation.gen", ".anim.Animation.gen", ".animation.gen")


def decoded_to_glb_path(decoded: str) -> str | None:
    """Strip a .Geometry.gen / .Animation.gen suffix so output is <name>.glb.

    Returns None if the path doesn't look like a mesh or animation.
    """
    low = decoded.lower()
    for suf in _GEOMETRY_SUFFIXES + _ANIMATION_SUFFIXES:
        if low.endswith(suf.lower()):
            return decoded[:-len(suf)] + ".glb"
    return None


_GLOBALVALUE_SUFFIX = ".globalvalue.ot.globalentityvaluesettings.gen"


def decoded_to_gv_path(decoded: str) -> str | None:
    """Map a GlobalEntityValueSettings decoded path to a .globalvalue.json."""
    low = decoded.lower()
    if low.endswith(_GLOBALVALUE_SUFFIX):
        return decoded[:-len(_GLOBALVALUE_SUFFIX)] + ".globalvalue.json"
    if low.endswith(".globalentityvaluesettings.gen"):
        return decoded[:-len(".globalentityvaluesettings.gen")] + ".globalvalue.json"
    return None


def _try_decode_globalvalues(raw: bytes) -> bytes | None:
    try:
        cf = _cooked.parse(raw)
        if not any(c.name == "oCGlobalEntityValueSettings" for c in cf.classes):
            return None
        return _gv_schema.decode_cooked_to_json(raw)
    except Exception:
        return None


def decoded_to_def_path(decoded: str) -> str | None:
    """Map a `*Definition.gen` decoded path to its `<class>.json` source.

    Only classes with an implemented schema in `definitions._SPECS` are
    routed here; anything else falls through to a raw copy.
    """
    low = decoded.lower()
    if not low.endswith("definition.gen"):
        return None
    # Strip the trailing `.<ClassName>.gen` envelope, keep the `*def.ot` stem.
    base = decoded.rsplit(".", 2)[0]  # drop ".DtFooDefinition.gen"
    if base.lower().endswith(".ot"):
        base = base[:-3]
    return base + ".json"


# root class name -> (decoded `.gen` suffix, output extension)
_ASSETREFS_CLASSES = {
    "oCScheduledVfxSettings": (".scheduledvfxsettings.gen", ".vfx.json"),
    "oCGameStream": (".gamestream.gen", ".level.json"),
    "oCCollisionMesh": (".collisionmesh.gen", ".collisionmesh.json"),
    "oCMaterial": (".material.gen", ".material.json"),
}


def decoded_to_assetrefs_path(decoded: str) -> str | None:
    low = decoded.lower()
    for _cls, (suf, ext) in _ASSETREFS_CLASSES.items():
        if low.endswith(suf):
            base = decoded[:-len(suf)]
            if base.lower().endswith(".ot"):
                base = base[:-3]
            return base + ext
    return None


def _try_decode_assetrefs(raw: bytes) -> bytes | None:
    try:
        cf = _cooked.parse(raw)
        root = cf.classes[0].name if cf.classes else ""
        if root not in _ASSETREFS_CLASSES:
            return None
        return _schemas.get(root).decode_cooked(raw)
    except Exception:
        return None


_ENTITYSETTINGS_SUFFIX = ".entitysettingsresource.gen"


def decoded_to_es_path(decoded: str) -> str | None:
    """Map an EntitySettingsResource decoded path to a .entitysettings.json."""
    low = decoded.lower()
    if not low.endswith(_ENTITYSETTINGS_SUFFIX):
        return None
    base = decoded[:-len(".EntitySettingsResource.gen")]
    if base.lower().endswith(".ot"):
        base = base[:-3]
    return base + ".entitysettings.json"


def _try_decode_entitysettings(raw: bytes) -> bytes | None:
    try:
        cf = _cooked.parse(raw)
        if not cf.classes or cf.classes[0].name != "oCEntitySettingsResource":
            return None
        return _es_schema.decode_cooked_to_json(raw)
    except Exception:
        return None


def _try_decode_definition(raw: bytes) -> bytes | None:
    try:
        cf = _cooked.parse(raw)
        root = cf.classes[0].name if cf.classes else ""
        if root not in _def_schema._SPECS:
            return None
        return _def_schema.decode_cooked_to_json(root, raw)
    except Exception:
        return None


def _try_decode_geometry(raw: bytes) -> bytes | None:
    try:
        return _geo_schema.decode_cooked_to_glb(raw)
    except Exception:
        return None


def _try_decode_animation(raw: bytes) -> bytes | None:
    try:
        cf = _cooked.parse(raw)
        if not any(c.name == "oCAnimation" for c in cf.classes):
            return None
        payload = b"".join(s.payload for s in cf.sections)
        anim = _anim_schema.parse_payload(payload)
        return _anim_schema._build_glb_preview(anim, payload)
    except Exception:
        return None


def process_one(args):
    encoded, decoded, cooking_dir, out_dir = args
    enc_path = Path(cooking_dir) / encoded.replace("\\", "/")
    bak = enc_path.with_suffix(enc_path.suffix + ".rsmm.bak")
    src = bak if bak.exists() else enc_path
    if not src.exists() or src.is_dir():
        return ("skip", decoded)
    dst_rel = decoded.replace("\\", "/")
    png_target = decoded_to_png_path(dst_rel)
    glb_target = decoded_to_glb_path(dst_rel)
    gv_target = decoded_to_gv_path(dst_rel)
    def_target = decoded_to_def_path(dst_rel)
    es_target = decoded_to_es_path(dst_rel)
    ar_target = decoded_to_assetrefs_path(dst_rel)
    try:
        raw = src.read_bytes()
    except Exception as e:
        return ("err", f"{decoded}: read {e}")

    if ar_target:
        js = _try_decode_assetrefs(raw)
        if js is not None:
            out = Path(out_dir) / ar_target
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(js)
            return ("json", decoded)

    if es_target:
        js = _try_decode_entitysettings(raw)
        if js is not None:
            out = Path(out_dir) / es_target
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(js)
            return ("json", decoded)
        # else fall through to raw copy

    if def_target:
        js = _try_decode_definition(raw)
        if js is not None:
            out = Path(out_dir) / def_target
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(js)
            return ("json", decoded)
        # else fall through to raw copy

    if gv_target:
        js = _try_decode_globalvalues(raw)
        if js is not None:
            out = Path(out_dir) / gv_target
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(js)
            return ("json", decoded)
        # else fall through to raw copy

    if png_target:
        out = Path(out_dir) / png_target
        out.parent.mkdir(parents=True, exist_ok=True)
        result = decode_tpi(raw)
        if result is None:
            raw_out = Path(out_dir) / dst_rel
            raw_out.parent.mkdir(parents=True, exist_ok=True)
            raw_out.write_bytes(raw)
            return ("raw-tex", decoded)
        img, w, h, fmt = result
        img.save(out, "PNG", optimize=False)
        return ("png", decoded)

    if glb_target:
        glb = _try_decode_geometry(raw) or _try_decode_animation(raw)
        if glb is not None:
            out = Path(out_dir) / glb_target
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(glb)
            return ("glb", decoded)
        # Fall through: write raw cooked bytes so the decoded path still
        # mirrors the cooked tree.

    out = Path(out_dir) / dst_rel
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(raw)
    return ("copy", decoded)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--game-dir", default=str(DEFAULT_GAME))
    ap.add_argument("--asset-map", default="data/asset_map.csv")
    ap.add_argument("--out", default="data/uncooked")
    ap.add_argument("--limit", type=int, help="process only first N entries (testing)")
    ap.add_argument("--jobs", type=int, default=os.cpu_count() or 4)
    ap.add_argument("--filter", help="substring filter on decoded path")
    args = ap.parse_args()

    cooking = Path(args.game_dir) / "DarkTalesResources" / "_Cooking"
    if not cooking.exists():
        sys.exit(f"no _Cooking at {cooking}")

    pairs = []
    with open(args.asset_map, newline="") as f:
        r = csv.reader(f)
        next(r)
        for row in r:
            if len(row) < 2:
                continue
            enc, dec = row[0].strip(), row[1].strip()
            if not enc or not dec:
                continue
            if args.filter and args.filter not in dec:
                continue
            pairs.append((enc, dec, str(cooking), args.out))
            if args.limit and len(pairs) >= args.limit:
                break

    print(f"processing {len(pairs)} entries with {args.jobs} workers...", flush=True)
    counts = {"png": 0, "copy": 0, "raw-tex": 0, "skip": 0, "err": 0}
    with ProcessPoolExecutor(max_workers=args.jobs) as ex:
        for i, fut in enumerate(as_completed(ex.submit(process_one, p) for p in pairs), 1):
            tag, _ = fut.result()
            counts[tag] = counts.get(tag, 0) + 1
            if i % 1000 == 0:
                print(f"  {i}/{len(pairs)}  {counts}", flush=True)
    print("done:", counts)


if __name__ == "__main__":
    main()
