"""Block-compressed texture decode + PNG encode (pure stdlib).

The DDS reader in `dds.py` hands back the raw on-disk pixel blob in its
native GPU format (BC1/BC3/BC5/BC7/…). glTF viewers (Blender, three.js)
cannot read those — they need PNG/JPEG. This module bridges the gap:

  decode_dds_to_rgba(img)  ->  (width, height, rgba8 bytes)   # mip 0 only
  encode_png(w, h, rgba)   ->  PNG file bytes

Only the base-level mip is decoded — previews don't need the chain. BCn
decompressors implemented inline (no third-party deps; runtime is
stdlib-only per project policy). BC6H (HDR) and BC7 are not yet decoded;
they raise a clear error so the caller can fall back to a flat material.
"""

from __future__ import annotations

import struct
import zlib

from .dds import DdsImage

# --- BCn block decoders. Each takes one block's bytes + returns 16 RGBA8
#     texels in row-major 4x4 order. -----------------------------------


def _rgb565(c: int) -> tuple[int, int, int]:
    r = (c >> 11) & 0x1F
    g = (c >> 5) & 0x3F
    b = c & 0x1F
    return (r << 3) | (r >> 2), (g << 2) | (g >> 4), (b << 3) | (b >> 2)


def _bc1_colors(block: bytes) -> list[tuple[int, int, int, int]]:
    """Decode the 8-byte BC1 color block to 16 RGBA texels (1-bit alpha)."""
    c0, c1 = struct.unpack_from("<HH", block, 0)
    bits = struct.unpack_from("<I", block, 4)[0]
    r0, g0, b0 = _rgb565(c0)
    r1, g1, b1 = _rgb565(c1)
    pal = [(r0, g0, b0, 255), (r1, g1, b1, 255)]
    if c0 > c1:
        pal.append(((2 * r0 + r1) // 3, (2 * g0 + g1) // 3, (2 * b0 + b1) // 3, 255))
        pal.append(((r0 + 2 * r1) // 3, (g0 + 2 * g1) // 3, (b0 + 2 * b1) // 3, 255))
    else:
        pal.append(((r0 + r1) // 2, (g0 + g1) // 2, (b0 + b1) // 2, 255))
        pal.append((0, 0, 0, 0))  # transparent black
    return [pal[(bits >> (2 * i)) & 0x3] for i in range(16)]


def _bc4_channel(block: bytes) -> list[int]:
    """Decode an 8-byte BC4 block to 16 single-channel u8 values."""
    a0, a1 = block[0], block[1]
    idx = int.from_bytes(block[2:8], "little")
    if a0 > a1:
        pal = [a0, a1,
               (6 * a0 + 1 * a1) // 7, (5 * a0 + 2 * a1) // 7,
               (4 * a0 + 3 * a1) // 7, (3 * a0 + 4 * a1) // 7,
               (2 * a0 + 5 * a1) // 7, (1 * a0 + 6 * a1) // 7]
    else:
        pal = [a0, a1,
               (4 * a0 + 1 * a1) // 5, (3 * a0 + 2 * a1) // 5,
               (2 * a0 + 3 * a1) // 5, (1 * a0 + 4 * a1) // 5, 0, 255]
    return [pal[(idx >> (3 * i)) & 0x7] for i in range(16)]


def _decode_bc1(block: bytes) -> list[tuple[int, int, int, int]]:
    return _bc1_colors(block)


def _decode_bc3(block: bytes) -> list[tuple[int, int, int, int]]:
    alpha = _bc4_channel(block[0:8])
    rgb = _bc1_colors(block[8:16])
    return [(rgb[i][0], rgb[i][1], rgb[i][2], alpha[i]) for i in range(16)]


def _decode_bc4(block: bytes) -> list[tuple[int, int, int, int]]:
    r = _bc4_channel(block)
    return [(r[i], r[i], r[i], 255) for i in range(16)]


def _decode_bc5(block: bytes) -> list[tuple[int, int, int, int]]:
    """RG normal map. Reconstruct B = sqrt(1 - r^2 - g^2)."""
    import math
    rch = _bc4_channel(block[0:8])
    gch = _bc4_channel(block[8:16])
    out = []
    for i in range(16):
        nx = rch[i] / 255.0 * 2 - 1
        ny = gch[i] / 255.0 * 2 - 1
        nz = math.sqrt(max(0.0, 1 - nx * nx - ny * ny))
        out.append((rch[i], gch[i], int((nz * 0.5 + 0.5) * 255), 255))
    return out


# Block byte size + decoder per format name.
_BLOCK_DECODERS = {
    "BC1": (8, _decode_bc1),
    "BC2": (16, None),  # DXT3 explicit alpha — rare, not implemented
    "BC3": (16, _decode_bc3),
    "BC4U": (8, _decode_bc4),
    "BC5U": (16, _decode_bc5),
}


def decode_dds_to_rgba(img: DdsImage) -> tuple[int, int, bytes]:
    """Decode the base mip of `img` to a tight RGBA8 buffer (w*h*4 bytes).

    Raises NotImplementedError for formats without a decoder yet (BC6H/BC7/
    BC2) so callers can fall back to a flat-color material.
    """
    w, h = img.width, img.height
    name = img.fmt.name

    if not img.fmt.is_block:
        return _decode_uncompressed(img)

    entry = _BLOCK_DECODERS.get(name)
    if entry is None or entry[1] is None:
        raise NotImplementedError(f"no RGBA decoder for texture format {name!r}")
    block_bytes, decode = entry

    bw = max(1, (w + 3) // 4)
    bh = max(1, (h + 3) // 4)
    out = bytearray(w * h * 4)
    src = img.pixels
    off = 0
    for by in range(bh):
        for bx in range(bw):
            if off + block_bytes > len(src):
                break
            texels = decode(src[off:off + block_bytes])
            off += block_bytes
            for ty in range(4):
                py = by * 4 + ty
                if py >= h:
                    continue
                row = (py * w) * 4
                for tx in range(4):
                    px = bx * 4 + tx
                    if px >= w:
                        continue
                    r, g, b, a = texels[ty * 4 + tx]
                    di = row + px * 4
                    out[di] = r
                    out[di + 1] = g
                    out[di + 2] = b
                    out[di + 3] = a
    return w, h, bytes(out)


def _decode_uncompressed(img: DdsImage) -> tuple[int, int, bytes]:
    """RGBA8 / BGRA8 base mip → RGBA8. Only 32bpp paths handled."""
    w, h = img.width, img.height
    need = w * h * 4
    px = img.pixels[:need]
    if len(px) < need:
        raise ValueError(f"uncompressed DDS short: have {len(px)}, need {need}")
    if img.fmt.name == "RGBA8":
        # dds.read maps both true RGBA8 and BGRA-masked 32bpp here. The
        # shipped corpus stores BGRA, so swap R/B to get display-correct RGBA.
        out = bytearray(px)
        for i in range(0, need, 4):
            out[i], out[i + 2] = out[i + 2], out[i]
        return w, h, bytes(out)
    raise NotImplementedError(f"no RGBA decoder for uncompressed format {img.fmt.name!r}")


# --- PNG encoder (filter type 0, single IDAT). ------------------------


def encode_png(width: int, height: int, rgba: bytes) -> bytes:
    """Encode a tight RGBA8 buffer (`width*height*4` bytes) to PNG bytes."""
    if len(rgba) != width * height * 4:
        raise ValueError(f"rgba len {len(rgba)} != {width * height * 4}")

    def chunk(tag: bytes, data: bytes) -> bytes:
        return (struct.pack(">I", len(data)) + tag + data
                + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))

    # IHDR: 8-bit, color type 6 (RGBA).
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)

    # Prepend filter byte 0 to each scanline.
    stride = width * 4
    raw = bytearray()
    for y in range(height):
        raw.append(0)
        raw += rgba[y * stride:(y + 1) * stride]

    idat = zlib.compress(bytes(raw), 9)
    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", ihdr)
            + chunk(b"IDAT", idat)
            + chunk(b"IEND", b""))


_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
# color type -> samples per pixel (8-bit). 3 (palette) is expanded to RGB(A).
_PNG_CHANNELS = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}


def _png_unfilter(raw: bytes, height: int, stride: int, bpp: int) -> bytearray:
    """Reverse PNG scanline filters (None/Sub/Up/Average/Paeth)."""
    out = bytearray()
    prev = bytearray(stride)
    pos = 0
    for _ in range(height):
        ftype = raw[pos]
        pos += 1
        line = bytearray(raw[pos:pos + stride])
        pos += stride
        if ftype == 1:  # Sub
            for i in range(bpp, stride):
                line[i] = (line[i] + line[i - bpp]) & 0xFF
        elif ftype == 2:  # Up
            for i in range(stride):
                line[i] = (line[i] + prev[i]) & 0xFF
        elif ftype == 3:  # Average
            for i in range(stride):
                a = line[i - bpp] if i >= bpp else 0
                line[i] = (line[i] + ((a + prev[i]) >> 1)) & 0xFF
        elif ftype == 4:  # Paeth
            for i in range(stride):
                a = line[i - bpp] if i >= bpp else 0
                b = prev[i]
                c = prev[i - bpp] if i >= bpp else 0
                p = a + b - c
                pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                pr = a if (pa <= pb and pa <= pc) else (b if pb <= pc else c)
                line[i] = (line[i] + pr) & 0xFF
        elif ftype != 0:
            raise ValueError(f"unsupported PNG filter type {ftype}")
        out += line
        prev = line
    return out


def decode_png(png_bytes: bytes) -> tuple[int, int, bytes]:
    """Decode an 8-bit PNG to (width, height, RGBA8 bytes).

    Supports color types 0 (grey), 2 (RGB), 3 (palette), 4 (grey+alpha),
    6 (RGBA) at bit depth 8 — the formats game-asset PNGs ship in. Raises
    ValueError on anything else (interlaced, 16-bit, etc.).
    """
    if png_bytes[:8] != _PNG_MAGIC:
        raise ValueError("not a PNG (bad magic)")
    pos = 8
    width = height = bit_depth = color_type = interlace = 0
    idat = bytearray()
    palette: bytes = b""
    trns: bytes = b""
    while pos < len(png_bytes):
        clen = struct.unpack_from(">I", png_bytes, pos)[0]
        tag = png_bytes[pos + 4:pos + 8]
        data = png_bytes[pos + 8:pos + 8 + clen]
        pos += 12 + clen
        if tag == b"IHDR":
            (width, height, bit_depth, color_type, _comp, _filt,
             interlace) = struct.unpack(">IIBBBBB", data)
        elif tag == b"PLTE":
            palette = data
        elif tag == b"tRNS":
            trns = data
        elif tag == b"IDAT":
            idat += data
        elif tag == b"IEND":
            break
    if bit_depth != 8:
        raise ValueError(f"unsupported PNG bit depth {bit_depth} (need 8)")
    if interlace != 0:
        raise ValueError("interlaced PNG not supported")
    if color_type not in _PNG_CHANNELS:
        raise ValueError(f"unsupported PNG color type {color_type}")

    ch = _PNG_CHANNELS[color_type]
    stride = width * ch
    bpp = ch  # bytes per pixel at 8-bit
    raw = zlib.decompress(bytes(idat))
    flat = _png_unfilter(raw, height, stride, bpp)

    rgba = bytearray(width * height * 4)
    n = width * height
    if color_type == 6:  # RGBA
        rgba[:] = flat
    elif color_type == 2:  # RGB
        for i in range(n):
            rgba[i * 4:i * 4 + 3] = flat[i * 3:i * 3 + 3]
            rgba[i * 4 + 3] = 255
    elif color_type == 0:  # grey
        for i in range(n):
            g = flat[i]
            rgba[i * 4] = rgba[i * 4 + 1] = rgba[i * 4 + 2] = g
            rgba[i * 4 + 3] = 255
    elif color_type == 4:  # grey + alpha
        for i in range(n):
            g = flat[i * 2]
            rgba[i * 4] = rgba[i * 4 + 1] = rgba[i * 4 + 2] = g
            rgba[i * 4 + 3] = flat[i * 2 + 1]
    elif color_type == 3:  # palette
        if not palette:
            raise ValueError("palette PNG missing PLTE chunk")
        for i in range(n):
            idx = flat[i]
            rgba[i * 4:i * 4 + 3] = palette[idx * 3:idx * 3 + 3]
            rgba[i * 4 + 3] = trns[idx] if idx < len(trns) else 255
    return width, height, bytes(rgba)
