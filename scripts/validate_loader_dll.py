#!/usr/bin/env python3
"""Static smoke-test for the built loader ``winhttp.dll``.

The loader can only be *run* inside Ravenswatch.exe, so CI cannot prove the
detours fire. But CI *can* prove the artifact is a well-formed winhttp proxy
DLL — which is exactly the regression that silently shipped in 0.1.11 (the
DLL was written to the wrong path, the build "succeeded", and every release
sidecar was missing it; `rsmm doctor` reported "loader DLL not built" on
every user install). See CLAUDE.md "Loader DLL bundling gotcha".

This validator parses the PE export table with the stdlib only (no pefile,
no objdump) so it runs identically on the Linux mingw build leg and the
Windows release leg. It asserts:

  * file exists and is a non-trivial size,
  * it is a 64-bit PE DLL (PE32+, IMAGE_FILE_DLL),
  * its export table forwards the winhttp API surface (so the game's
    real winhttp calls don't break when our proxy is loaded first).

Usage:  python scripts/validate_loader_dll.py dist/winhttp.dll
Exit 0 on success; non-zero with a diagnostic on any failure.
"""

from __future__ import annotations

import struct
import sys
from pathlib import Path

# A handful of forwarders that MUST be present for the winhttp proxy to be
# a drop-in. If the .def stopped being applied (the failure mode that ships
# an exportless DLL), these vanish and the game's networking breaks.
REQUIRED_EXPORTS = {
    "WinHttpOpen",
    "WinHttpCloseHandle",
    "WinHttpConnect",
    "WinHttpOpenRequest",
    "WinHttpSendRequest",
    "WinHttpReceiveResponse",
    "WinHttpCrackUrl",
}

MIN_SIZE = 4096  # a real proxy DLL is tens of KB; anything tiny is a stub.


class ValidationError(Exception):
    pass


def _rva_to_off(rva: int, sections: list[tuple[int, int, int]]) -> int:
    """Map a relative virtual address to a file offset via the section table."""
    for va, vsize, raw_off in sections:
        if va <= rva < va + vsize:
            return raw_off + (rva - va)
    raise ValidationError(f"RVA 0x{rva:x} not inside any section")


def parse_exports(data: bytes) -> set[str]:
    """Return the set of exported symbol names from a PE image."""
    if data[:2] != b"MZ":
        raise ValidationError("not a PE image (missing MZ header)")
    e_lfanew = struct.unpack_from("<I", data, 0x3C)[0]
    if data[e_lfanew : e_lfanew + 4] != b"PE\0\0":
        raise ValidationError("not a PE image (missing PE signature)")

    coff = e_lfanew + 4
    machine, n_sections = struct.unpack_from("<HH", data, coff)
    characteristics = struct.unpack_from("<H", data, coff + 18)[0]
    if not characteristics & 0x2000:  # IMAGE_FILE_DLL
        raise ValidationError("PE is not marked as a DLL")

    opt = coff + 20
    magic = struct.unpack_from("<H", data, opt)[0]
    if magic != 0x20B:  # PE32+ (64-bit)
        raise ValidationError(f"expected PE32+ (0x20b), got 0x{magic:x}")

    # Data directories start at offset 112 in the PE32+ optional header;
    # entry 0 is the export table (RVA, size).
    exp_rva, exp_size = struct.unpack_from("<II", data, opt + 112)
    if exp_rva == 0:
        raise ValidationError("no export directory (DLL exports nothing)")

    opt_size = struct.unpack_from("<H", data, coff + 16)[0]
    sect_off = opt + opt_size
    sections: list[tuple[int, int, int]] = []
    for i in range(n_sections):
        base = sect_off + i * 40
        vsize, vaddr = struct.unpack_from("<II", data, base + 8)
        raw_off = struct.unpack_from("<I", data, base + 20)[0]
        sections.append((vaddr, vsize, raw_off))

    exp_off = _rva_to_off(exp_rva, sections)
    n_names = struct.unpack_from("<I", data, exp_off + 24)[0]
    names_rva = struct.unpack_from("<I", data, exp_off + 32)[0]
    names_off = _rva_to_off(names_rva, sections)

    names: set[str] = set()
    for i in range(n_names):
        name_rva = struct.unpack_from("<I", data, names_off + i * 4)[0]
        off = _rva_to_off(name_rva, sections)
        end = data.index(b"\0", off)
        names.add(data[off:end].decode("ascii", "replace"))
    return names


def validate(path: Path) -> None:
    if not path.is_file():
        raise ValidationError(f"{path} does not exist")
    size = path.stat().st_size
    if size < MIN_SIZE:
        raise ValidationError(f"{path} is only {size} bytes (looks like a stub)")
    exports = parse_exports(path.read_bytes())
    missing = REQUIRED_EXPORTS - exports
    if missing:
        raise ValidationError(
            f"export table missing required winhttp forwarders: "
            f"{', '.join(sorted(missing))} (found {len(exports)} exports)"
        )
    print(f"OK: {path} — valid winhttp proxy DLL ({size} bytes, "
          f"{len(exports)} exports)")


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: validate_loader_dll.py <path-to-winhttp.dll>",
              file=sys.stderr)
        return 2
    try:
        validate(Path(argv[1]))
    except ValidationError as e:
        print(f"FAIL: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
