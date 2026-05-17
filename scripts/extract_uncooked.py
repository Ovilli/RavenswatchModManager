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


def process_one(args):
    encoded, decoded, cooking_dir, out_dir = args
    enc_path = Path(cooking_dir) / encoded.replace("\\", "/")
    bak = enc_path.with_suffix(enc_path.suffix + ".rsmm.bak")
    src = bak if bak.exists() else enc_path
    if not src.exists() or src.is_dir():
        return ("skip", decoded)
    dst_rel = decoded.replace("\\", "/")
    png_target = decoded_to_png_path(dst_rel)
    try:
        raw = src.read_bytes()
    except Exception as e:
        return ("err", f"{decoded}: read {e}")

    if png_target:
        out = Path(out_dir) / png_target
        out.parent.mkdir(parents=True, exist_ok=True)
        result = decode_tpi(raw)
        if result is None:
            # Unknown format / font atlas — fall back to raw cooked bytes
            raw_out = Path(out_dir) / dst_rel
            raw_out.parent.mkdir(parents=True, exist_ok=True)
            raw_out.write_bytes(raw)
            return ("raw-tex", decoded)
        img, w, h, fmt = result
        img.save(out, "PNG", optimize=False)
        return ("png", decoded)

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
