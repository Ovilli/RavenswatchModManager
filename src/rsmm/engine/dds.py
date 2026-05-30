"""DDS 1.0 (with optional DX10 extension) file writer.

Pure format encoder — no Ravenswatch schema knowledge. The oCTexture
decoder calls into this module to wrap a raw pixel blob + format/width/
height/mipmap metadata into a valid .dds file readable by every common
image tool.

Reference: https://learn.microsoft.com/en-us/windows/win32/direct3ddds/dx-graphics-dds-pguide

Supported formats:
  Legacy (DDS_HEADER only):
    BC1 / DXT1, BC2 / DXT3, BC3 / DXT5, BC4U (R8 ATI1), BC5U (RG88 ATI2),
    RGBA8, BGRA8, R8, RG88
  Modern (DDS_HEADER + DDS_HEADER_DXT10):
    BC4S, BC5S, BC6H_UF16, BC6H_SF16, BC7, R16G16B16A16F, R32G32B32A32F
"""

from __future__ import annotations

import struct
from dataclasses import dataclass
from enum import IntEnum

DDS_MAGIC = b"DDS "

DDSD_CAPS = 0x1
DDSD_HEIGHT = 0x2
DDSD_WIDTH = 0x4
DDSD_PITCH = 0x8
DDSD_PIXELFORMAT = 0x1000
DDSD_MIPMAPCOUNT = 0x20000
DDSD_LINEARSIZE = 0x80000
DDSD_DEPTH = 0x800000

DDSCAPS_COMPLEX = 0x8
DDSCAPS_TEXTURE = 0x1000
DDSCAPS_MIPMAP = 0x400000

DDSCAPS2_CUBEMAP = 0x200
DDSCAPS2_CUBEMAP_ALL_FACES = 0xFC00  # all six bits set
DDSCAPS2_VOLUME = 0x200000

DDPF_ALPHAPIXELS = 0x1
DDPF_FOURCC = 0x4
DDPF_RGB = 0x40
DDPF_LUMINANCE = 0x20000

# DXGI_FORMAT enum (subset). Only the values we actually emit.
class DXGI(IntEnum):
    UNKNOWN = 0
    R32G32B32A32_FLOAT = 2
    R16G16B16A16_FLOAT = 10
    R8G8B8A8_UNORM = 28
    BC4_UNORM = 80
    BC4_SNORM = 81
    BC5_UNORM = 83
    BC5_SNORM = 84
    BC6H_UF16 = 95
    BC6H_SF16 = 96
    BC7_UNORM = 98


@dataclass
class TextureFormat:
    name: str               # canonical name for inspection ("BC1", "BC7", ...)
    fourcc: bytes | None    # 4-byte fourCC for legacy DDS_HEADER pixel format
    dxgi: int               # DXGI value for DX10 header (UNKNOWN if legacy-only)
    block_size_bytes: int   # 8 for BC1/BC4, 16 for BC2/BC3/BC5/BC6/BC7; 0 for non-block
    bits_per_pixel: int     # for non-block formats, 0 otherwise
    is_block: bool
    is_compressed: bool
    needs_dx10: bool


# Format registry. The texture decoder reads the Ravenswatch enum value and
# maps to one of these entries before calling `write`.
FORMATS: dict[str, TextureFormat] = {
    "BC1": TextureFormat("BC1", b"DXT1", DXGI.UNKNOWN, 8, 0, True, True, False),
    "BC2": TextureFormat("BC2", b"DXT3", DXGI.UNKNOWN, 16, 0, True, True, False),
    "BC3": TextureFormat("BC3", b"DXT5", DXGI.UNKNOWN, 16, 0, True, True, False),
    "BC4U": TextureFormat("BC4U", b"ATI1", DXGI.BC4_UNORM, 8, 0, True, True, False),
    "BC4S": TextureFormat("BC4S", None, DXGI.BC4_SNORM, 8, 0, True, True, True),
    "BC5U": TextureFormat("BC5U", b"ATI2", DXGI.BC5_UNORM, 16, 0, True, True, False),
    "BC5S": TextureFormat("BC5S", None, DXGI.BC5_SNORM, 16, 0, True, True, True),
    "BC6H_UF16": TextureFormat("BC6H_UF16", None, DXGI.BC6H_UF16, 16, 0, True, True, True),
    "BC6H_SF16": TextureFormat("BC6H_SF16", None, DXGI.BC6H_SF16, 16, 0, True, True, True),
    "BC7": TextureFormat("BC7", None, DXGI.BC7_UNORM, 16, 0, True, True, True),
    "RGBA8": TextureFormat("RGBA8", None, DXGI.R8G8B8A8_UNORM, 0, 32, False, False, True),
    "RGBA16F": TextureFormat("RGBA16F", None, DXGI.R16G16B16A16_FLOAT, 0, 64, False, False, True),
    "RGBA32F": TextureFormat("RGBA32F", None, DXGI.R32G32B32A32_FLOAT, 0, 128, False, False, True),
}


def linear_size(width: int, height: int, fmt: TextureFormat) -> int:
    """Bytes required for one mip level at `width x height` in `fmt`."""
    if fmt.is_block:
        # Block-compressed formats round up to 4x4 blocks.
        bw = max(1, (width + 3) // 4)
        bh = max(1, (height + 3) // 4)
        return bw * bh * fmt.block_size_bytes
    return max(1, width * height * fmt.bits_per_pixel // 8)


def write(
    pixels: bytes,
    width: int,
    height: int,
    fmt: TextureFormat,
    mip_count: int = 1,
    array_size: int = 1,
    is_cubemap: bool = False,
) -> bytes:
    """Pack `pixels` + metadata into a DDS file byte string.

    `pixels` must hold all mip levels (and array slices for arrays/cubemaps)
    concatenated in standard DDS order. Caller is responsible for the
    correct payload size; this function does not pad or recompute pixel
    data. See `linear_size()` for per-mip sizing.
    """
    if mip_count < 1:
        raise ValueError("mip_count must be >= 1")
    if array_size < 1:
        raise ValueError("array_size must be >= 1")
    if is_cubemap and array_size % 6 != 0:
        raise ValueError("cubemap array_size must be a multiple of 6")

    flags = DDSD_CAPS | DDSD_HEIGHT | DDSD_WIDTH | DDSD_PIXELFORMAT
    if mip_count > 1:
        flags |= DDSD_MIPMAPCOUNT
    if fmt.is_block:
        flags |= DDSD_LINEARSIZE
        pitch_or_linear = linear_size(width, height, fmt)
    else:
        flags |= DDSD_PITCH
        pitch_or_linear = max(1, (width * fmt.bits_per_pixel + 7) // 8)

    caps = DDSCAPS_TEXTURE
    if mip_count > 1 or is_cubemap or array_size > 1:
        caps |= DDSCAPS_COMPLEX
    if mip_count > 1:
        caps |= DDSCAPS_MIPMAP

    caps2 = 0
    if is_cubemap:
        caps2 |= DDSCAPS2_CUBEMAP | DDSCAPS2_CUBEMAP_ALL_FACES

    use_dx10 = fmt.needs_dx10 or array_size > 1
    if fmt.fourcc is not None and not use_dx10:
        pf_flags = DDPF_FOURCC
        pf_fourcc = fmt.fourcc
        pf_bit_count = 0
        masks = (0, 0, 0, 0)
    elif use_dx10:
        pf_flags = DDPF_FOURCC
        pf_fourcc = b"DX10"
        pf_bit_count = 0
        masks = (0, 0, 0, 0)
    else:
        # Uncompressed RGBA fallback path (no fourCC, explicit masks). Only
        # hit for the rare case where a legacy-only DDS reader is targeted
        # and the format happens to have no fourCC mapping.
        pf_flags = DDPF_RGB | DDPF_ALPHAPIXELS
        pf_fourcc = b"\0\0\0\0"
        pf_bit_count = fmt.bits_per_pixel
        masks = (0x00FF0000, 0x0000FF00, 0x000000FF, 0xFF000000)

    # DDS_PIXELFORMAT struct (32 bytes)
    ddspf = struct.pack(
        "<II4sIIIII",
        32,                # dwSize
        pf_flags,          # dwFlags
        pf_fourcc,         # dwFourCC
        pf_bit_count,      # dwRGBBitCount
        *masks,            # R/G/B/A bit masks (4 u32)
    )

    # DDS_HEADER struct (124 bytes including dwSize)
    header = struct.pack(
        "<I I I I I I I",
        124,                # dwSize
        flags,              # dwFlags
        height,             # dwHeight
        width,              # dwWidth
        pitch_or_linear,    # dwPitchOrLinearSize
        0,                  # dwDepth (volumes set this; we don't here)
        mip_count,          # dwMipMapCount
    )
    header += b"\0" * 44  # dwReserved1[11]
    header += ddspf
    header += struct.pack(
        "<I I I I",
        caps,               # dwCaps
        caps2,              # dwCaps2
        0,                  # dwCaps3
        0,                  # dwCaps4
    )
    header += b"\0" * 4     # dwReserved2

    out = bytearray(DDS_MAGIC)
    out += header
    if use_dx10:
        # DDS_HEADER_DXT10 (20 bytes)
        resource_dim = 3  # D3D10_RESOURCE_DIMENSION_TEXTURE2D
        misc_flag = 0x4 if is_cubemap else 0
        out += struct.pack(
            "<I I I I I",
            int(fmt.dxgi),
            resource_dim,
            misc_flag,
            array_size,
            0,              # miscFlags2
        )
    out += pixels
    return bytes(out)


def by_name(name: str) -> TextureFormat:
    """Look up a format by canonical name. Raises KeyError on miss."""
    return FORMATS[name]


# Inverse lookup: legacy 4-CC -> canonical name (best-effort for old DDS files).
_FOURCC_TO_NAME = {f.fourcc: f.name for f in FORMATS.values() if f.fourcc is not None}

# DXGI value -> canonical name (DX10 extension path).
_DXGI_TO_NAME = {int(f.dxgi): f.name for f in FORMATS.values() if int(f.dxgi) != 0}


@dataclass
class DdsImage:
    """Parsed DDS file. Pixels is the entire on-disk payload (all mips + slices
    concatenated), exactly as the DDS spec orders them."""
    width: int
    height: int
    fmt: TextureFormat
    pixels: bytes
    mip_count: int
    array_size: int
    is_cubemap: bool


def read(data: bytes) -> DdsImage:
    """Parse a DDS file into a DdsImage. Supports legacy DDS_HEADER and the
    DDS_HEADER_DXT10 extension. Format-mask uncompressed fallback parsing
    is not implemented (uncommon in modder content).
    """
    if len(data) < 128:
        raise ValueError(f"DDS too short ({len(data)} B); need at least 128")
    if data[:4] != DDS_MAGIC:
        raise ValueError(f"not a DDS file (magic {data[:4]!r} != 'DDS ')")

    dw_size, dw_flags, height, width, _pitch, _depth, mip_count = struct.unpack_from(
        "<7I", data, 4
    )
    if dw_size != 124:
        raise ValueError(f"DDS header size {dw_size} != 124")
    if mip_count < 1:
        mip_count = 1

    # DDS_PIXELFORMAT lives at file offset 76 (= magic 4 + header pre-pf 72).
    # Header pre-pf = 7 u32 fields (28 B) + dwReserved1 (44 B) = 72 B.
    pf_size, pf_flags = struct.unpack_from("<II", data, 4 + 72)
    pf_fourcc = data[4 + 80:4 + 84]
    pf_bit_count = struct.unpack_from("<I", data, 4 + 84)[0]
    if pf_size != 32:
        raise ValueError(f"DDS pixelformat size {pf_size} != 32")

    array_size = 1
    is_cubemap = False
    pixel_offset = 128

    fmt: TextureFormat | None = None
    if pf_flags & DDPF_FOURCC and pf_fourcc == b"DX10":
        if len(data) < 148:
            raise ValueError("DDS DX10 ext requires >= 148 bytes")
        dxgi, _dim, misc, arr, _ = struct.unpack_from("<5I", data, 128)
        pixel_offset = 148
        array_size = max(1, arr)
        is_cubemap = bool(misc & 0x4)
        name = _DXGI_TO_NAME.get(dxgi)
        if name is None:
            raise ValueError(f"DDS DXGI format {dxgi:#x} not in registry")
        fmt = FORMATS[name]
    elif pf_flags & DDPF_FOURCC:
        name = _FOURCC_TO_NAME.get(pf_fourcc)
        if name is None:
            raise ValueError(f"DDS fourCC {pf_fourcc!r} not in registry")
        fmt = FORMATS[name]
    elif pf_flags & DDPF_RGB and pf_bit_count == 32:
        # Uncompressed BGRA / RGBA — use the generic RGBA8 mapping. Mask-
        # based channel ordering disambiguation is intentionally not done
        # here; modder content uses BC1/3/5/7 or DXGI in practice.
        fmt = FORMATS["RGBA8"]
    else:
        raise ValueError(
            f"DDS pixel format unsupported (flags={pf_flags:#x}, fourCC={pf_fourcc!r})"
        )

    pixels = data[pixel_offset:]
    return DdsImage(
        width=width, height=height, fmt=fmt, pixels=pixels,
        mip_count=mip_count, array_size=array_size, is_cubemap=is_cubemap,
    )
