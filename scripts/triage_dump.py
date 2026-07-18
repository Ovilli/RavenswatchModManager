#!/usr/bin/env python3
"""Triage a Ravenswatch crash minidump — one command, no pip deps.

The loader-crash loop this automates (hand-repeated ~5× this month): parse the
exception record, map the faulting address + every stack return-address to
either a game VA (imagebase 0x140000000) or a loader symbol (nm on the
byte-identical dist/winhttp.dll), and — for game frames — resolve them through
the local pattern DB back to a semantic symbol name where one exists.

    python scripts/triage_dump.py                 # newest dump in the game CrashDB
    python scripts/triage_dump.py <file.dmp>
    python scripts/triage_dump.py --game-dir <dir> --dll dist/winhttp.dll

Pure stdlib (parses the MINIDUMP container itself), so it works on a fresh
checkout with no `pip install minidump`. Reads the game exe path from the
module list to keep the imagebase honest across rebuilds.

Caveat: loader (winhttp.dll) frames are symbolized by nearest preceding `nm`
symbol with NO unwind info, so small static functions resolve to a neighboring
exported symbol — treat non-fault loader frames as approximate. The exception
address, RIP, and every Ravenswatch.exe frame's game VA are exact; game frames
also get an approximate `~SemanticName+off` from data/symbols.json (addresses
may be a build behind — confirm with scripts/verify_symbol_resolve.py).
"""

from __future__ import annotations

import argparse
import bisect
import struct
import subprocess
import sys
from pathlib import Path

GAME_IMAGEBASE = 0x140000000

# MINIDUMP stream types we care about.
_STREAM_THREAD_LIST = 3
_STREAM_MODULE_LIST = 4
_STREAM_MEMORY_LIST = 5
_STREAM_EXCEPTION = 6
_STREAM_MEMORY64_LIST = 9

# CONTEXT_AMD64 field offsets (bytes into the context blob).
_CTX = {
    "Rax": 0x78, "Rcx": 0x80, "Rdx": 0x88, "Rbx": 0x90, "Rsp": 0x98,
    "Rbp": 0xA0, "Rsi": 0xA8, "Rdi": 0xB0, "R8": 0xB8, "R9": 0xC0,
    "R10": 0xC8, "R11": 0xD0, "R12": 0xD8, "R13": 0xE0, "R14": 0xE8,
    "R15": 0xF0, "Rip": 0xF8,
}

_EXC_NAMES = {
    0xC0000005: "EXCEPTION_ACCESS_VIOLATION",
    0xC000001D: "EXCEPTION_ILLEGAL_INSTRUCTION",
    0xC0000094: "EXCEPTION_INT_DIVIDE_BY_ZERO",
    0xC00000FD: "EXCEPTION_STACK_OVERFLOW",
    0x80000003: "EXCEPTION_BREAKPOINT",
}


class Minidump:
    """Minimal MINIDUMP reader: modules, the exception record + context, and a
    fault-safe reader over the dumped memory ranges."""

    def __init__(self, path: Path):
        self.buf = path.read_bytes()
        sig, _ver, nstreams, dir_rva = struct.unpack_from("<4sIII", self.buf, 0)
        if sig != b"MDMP":
            raise ValueError(f"{path}: not a minidump (sig {sig!r})")
        self.streams: dict[int, tuple[int, int]] = {}
        for i in range(nstreams):
            stype, dsize, rva = struct.unpack_from("<III", self.buf, dir_rva + i * 12)
            self.streams.setdefault(stype, (dsize, rva))
        self.modules = self._read_modules()
        self._ranges = self._read_memory_ranges()  # sorted (start, size, file_off)
        self._range_starts = [r[0] for r in self._ranges]

    # -- strings / modules ---------------------------------------------------
    def _read_string(self, rva: int) -> str:
        (length,) = struct.unpack_from("<I", self.buf, rva)
        raw = self.buf[rva + 4: rva + 4 + length]
        return raw.decode("utf-16-le", "replace")

    def _read_modules(self) -> list[tuple[int, int, str]]:
        if _STREAM_MODULE_LIST not in self.streams:
            return []
        _dsize, rva = self.streams[_STREAM_MODULE_LIST]
        (count,) = struct.unpack_from("<I", self.buf, rva)
        mods = []
        base = rva + 4
        for i in range(count):
            # MINIDUMP_MODULE is 108 bytes; BaseOfImage@0, SizeOfImage@8,
            # CheckSum@12, TimeDateStamp@16, ModuleNameRva@20.
            off = base + i * 108
            base_addr, size = struct.unpack_from("<QI", self.buf, off)
            (name_rva,) = struct.unpack_from("<I", self.buf, off + 20)
            name = self._read_string(name_rva).split("\\")[-1]
            mods.append((base_addr, size, name))
        mods.sort()
        return mods

    def module_of(self, addr: int):
        for base_addr, size, name in self.modules:
            if base_addr <= addr < base_addr + size:
                return name, addr - base_addr
        return None

    # -- memory --------------------------------------------------------------
    def _read_memory_ranges(self) -> list[tuple[int, int, int]]:
        if _STREAM_MEMORY64_LIST in self.streams:
            _dsize, rva = self.streams[_STREAM_MEMORY64_LIST]
            count, base_rva = struct.unpack_from("<QQ", self.buf, rva)
            ranges = []
            cur = base_rva
            off = rva + 16
            for _ in range(count):
                start, size = struct.unpack_from("<QQ", self.buf, off)
                off += 16
                ranges.append((start, size, cur))
                cur += size
            ranges.sort()
            return ranges
        if _STREAM_MEMORY_LIST in self.streams:
            # MINIDUMP_MEMORY_DESCRIPTOR: StartOfMemoryRange u64, then a
            # location descriptor {DataSize u32, Rva u32}.
            _dsize, rva = self.streams[_STREAM_MEMORY_LIST]
            (count,) = struct.unpack_from("<I", self.buf, rva)
            ranges = []
            off = rva + 4
            for _ in range(count):
                start, dsz, drva = struct.unpack_from("<QII", self.buf, off)
                off += 16
                ranges.append((start, dsz, drva))
            ranges.sort()
            return ranges
        return []

    def read(self, addr: int, size: int) -> bytes | None:
        i = bisect.bisect_right(self._range_starts, addr) - 1
        if i < 0:
            return None
        start, rsize, foff = self._ranges[i]
        if not (start <= addr < start + rsize):
            return None
        avail = start + rsize - addr
        n = min(size, avail)
        off = foff + (addr - start)
        return self.buf[off: off + n]

    # -- exception -----------------------------------------------------------
    def exception(self):
        if _STREAM_EXCEPTION not in self.streams:
            return None
        _dsize, rva = self.streams[_STREAM_EXCEPTION]
        thread_id = struct.unpack_from("<I", self.buf, rva)[0]
        # MINIDUMP_EXCEPTION_STREAM: ThreadId u32, __align u32, then
        # MINIDUMP_EXCEPTION record at +8.
        er = rva + 8
        code, flags, _rec, addr, nparams = struct.unpack_from("<IIQQI", self.buf, er)
        params = struct.unpack_from("<15Q", self.buf, er + 8 + 8 + 8 + 4 + 4)
        # ThreadContext location descriptor follows the 152-byte exception record.
        ctx_off = er + 152
        ctx_size, ctx_rva = struct.unpack_from("<II", self.buf, ctx_off)
        ctx = self.buf[ctx_rva: ctx_rva + ctx_size]
        return {
            "thread_id": thread_id,
            "code": code,
            "addr": addr,
            "params": list(params[:nparams]),
            "ctx": ctx,
        }

    @staticmethod
    def reg(ctx: bytes, name: str) -> int:
        return struct.unpack_from("<Q", ctx, _CTX[name])[0]


def _load_nm_symbols(dll: Path):
    """(sorted addrs, names) for text symbols in the loader DLL, or None."""
    for tool in ("x86_64-w64-mingw32-nm", "nm"):
        try:
            out = subprocess.run(
                [tool, "--demangle", str(dll)],
                capture_output=True, text=True, check=True,
            ).stdout
        except (FileNotFoundError, subprocess.CalledProcessError):
            continue
        syms = []
        for ln in out.splitlines():
            p = ln.split(None, 2)
            if len(p) == 3 and p[1] in ("T", "t", "W", "w"):
                try:
                    syms.append((int(p[0], 16), p[2].strip()))
                except ValueError:
                    pass
        if syms:
            syms.sort()
            return [a for a, _ in syms], [n for _, n in syms]
    return None


def _dll_imagebase(syms) -> int:
    # nm prints absolute VAs against the DLL's own preferred base; the lowest
    # .text symbol sits just past the header, so round down to a page-aligned
    # base guess. The winhttp proxy links at 0x263040000 historically; derive
    # it from the min symbol to stay correct if that changes.
    lo = syms[0][0] if isinstance(syms[0], tuple) else syms[0]
    return lo & ~0xFFFFF


def _load_pattern_symbols(repo_root: Path):
    """{game_va: name} from data/symbols.json status=ok addresses, best-effort.

    Uses the stored raw FUN_<addr>/va so game frames get a semantic name even
    without a live resolve. Addresses may be a build behind — flagged as
    approximate in output.
    """
    import json
    sp = repo_root / "data" / "symbols.json"
    if not sp.exists():
        return {}
    try:
        doc = json.loads(sp.read_text())
    except (json.JSONDecodeError, OSError):
        return {}
    syms = doc.get("symbols", doc) if isinstance(doc, dict) else doc
    out = {}
    for s in syms:
        name = s.get("name")
        raw = s.get("raw") or ""
        va = s.get("va")
        addr = None
        if isinstance(raw, str) and raw.startswith("FUN_"):
            try:
                addr = int(raw[4:], 16)
            except ValueError:
                addr = None
        elif va:
            try:
                addr = int(va, 16) if isinstance(va, str) else int(va)
            except (ValueError, TypeError):
                addr = None
        if addr and name:
            out[addr] = name
    return out


def _nearest(sorted_keys, table, addr, max_delta=0x4000):
    i = bisect.bisect_right(sorted_keys, addr) - 1
    if i < 0:
        return None
    k = sorted_keys[i]
    if addr - k > max_delta:
        return None
    return table[k], addr - k


def _annotate(md, addr, nm, dll_base, patt_keys, patt):
    m = md.module_of(addr)
    if not m:
        return None
    name, off = m
    if name.lower() == "ravenswatch.exe":
        game_va = off + GAME_IMAGEBASE
        sym = _nearest(patt_keys, patt, game_va)
        tag = f" ~{sym[0]}+{hex(sym[1])}" if sym else ""
        return f"game_va={hex(game_va)}{tag}"
    if name.lower() == "winhttp.dll" and nm:
        addrs, names = nm
        va = dll_base + off
        j = bisect.bisect_right(addrs, va) - 1
        if j >= 0:
            return f"LOADER {names[j]}+{hex(va - addrs[j])}"
        return f"winhttp+{hex(off)}"
    return f"{name}+{hex(off)}"


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    repo_root = Path(__file__).resolve().parent.parent
    ap = argparse.ArgumentParser(prog="triage_dump", description=__doc__)
    ap.add_argument("dump", nargs="?", help="dump file (default: newest in CrashDB)")
    ap.add_argument("--game-dir", help="game install dir (to locate CrashDB)")
    ap.add_argument("--dll", default=str(repo_root / "dist" / "winhttp.dll"),
                    help="loader DLL to symbolize against (must match the crash build)")
    ap.add_argument("--stack-bytes", type=lambda x: int(x, 0), default=0x800,
                    help="how many bytes of stack to scan (default 0x800)")
    a = ap.parse_args(argv)

    dump = Path(a.dump) if a.dump else None
    if dump is None:
        gd = a.game_dir
        if not gd:
            try:
                sys.path.insert(0, str(repo_root / "src"))
                from rsmm.engine.paths import DEFAULT_GAME_DIR
                gd = str(DEFAULT_GAME_DIR)
            except (ImportError, OSError, AttributeError):
                print("no dump given and could not resolve the game dir; pass a file or --game-dir",
                      file=sys.stderr)
                return 2
        reports = Path(gd) / "CrashDB" / "reports"
        dumps = sorted(reports.glob("*.dmp"), key=lambda p: p.stat().st_mtime, reverse=True)
        if not dumps:
            print(f"no dumps in {reports}", file=sys.stderr)
            return 1
        dump = dumps[0]

    md = Minidump(dump)
    dll = Path(a.dll)
    nm = _load_nm_symbols(dll) if dll.exists() else None
    dll_base = 0
    if nm:
        dll_base = nm[0][0] & ~0xFFFFF
    patt = _load_pattern_symbols(repo_root)
    patt_keys = sorted(patt)

    print(f"dump: {dump}")
    if not dll.exists():
        print(f"  (loader DLL {dll} missing — loader frames stay raw offsets)")
    exc = md.exception()
    if not exc:
        print("no exception stream")
        return 0
    cname = _EXC_NAMES.get(exc["code"], hex(exc["code"]))
    print(f"\nexception: {cname}")
    print(f"  fault addr: {hex(exc['addr'])}  ",
          _annotate(md, exc["addr"], nm, dll_base, patt_keys, patt) or "(unmapped)")
    if exc["params"]:
        rw = {0: "read", 1: "write", 8: "execute"}.get(exc["params"][0], exc["params"][0])
        if len(exc["params"]) > 1:
            print(f"  access:     {rw} @ {hex(exc['params'][1])}")

    ctx = exc["ctx"]
    rip = md.reg(ctx, "Rip")
    rsp = md.reg(ctx, "Rsp")
    print(f"\n  rip {hex(rip)}  ",
          _annotate(md, rip, nm, dll_base, patt_keys, patt) or "(unmapped)")
    for r in ("Rax", "Rcx", "Rdx", "Rbx", "Rbp", "Rsi", "Rdi", "R8", "R9"):
        print(f"  {r.lower():<4} {hex(md.reg(ctx, r))}")

    print(f"\nstack scan from rsp={hex(rsp)} (game + loader return addresses):")
    data = b""
    a_ = rsp
    remaining = a.stack_bytes
    while remaining > 0:
        chunk = md.read(a_, min(0x400, remaining))
        if chunk is None:
            data += b"\x00" * min(0x400, remaining)
        else:
            data += chunk
        a_ += min(0x400, remaining)
        remaining -= min(0x400, remaining)
    for i in range(0, len(data) - 7, 8):
        (v,) = struct.unpack_from("<Q", data, i)
        note = _annotate(md, v, nm, dll_base, patt_keys, patt)
        if note and ("game_va" in note or "LOADER" in note):
            print(f"  rsp+{i:04x}  {hex(v)}  {note}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
