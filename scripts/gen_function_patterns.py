#!/usr/bin/env python3
"""
Build a per-function byte-pattern signature database from Ravenswatch.exe.

Inputs:
  - exe: <game>/Ravenswatch.exe
  - symbols: docs/_re/out/symbols.json  (function entry addresses)

For each function we disassemble its prologue (~32 bytes) with capstone,
classify each instruction by whether its operand is an absolute or
RIP-relative address, and emit a (pattern, mask) where relocation-
sensitive bytes are wildcarded ('?'). This is what `rsmm.call` will
scan for at runtime to re-locate the function after a game patch
shifts code by an unknown amount.

Output: data/function_patterns.json
   [{ "name", "addr", "pattern", "size_in_text" }]

The pattern is recorded as a hex string with '??' wildcards (IDA style)
so the loader DLL can parse it without external deps.
"""

import argparse
import json
import os
import re
import struct
import sys
from pathlib import Path

import capstone  # type: ignore

# Run from a plain `python3 scripts/...` with no activated venv too: an editable
# install puts `rsmm` on the path, but `./rsmm install-loader` shells this out
# via sys.executable, which is NOT necessarily the interpreter that has it.
# Without this the import dies and the caller reports it as a symbol failure.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from rsmm.engine.paths import default_game_dir

# Cross-platform game-dir resolver (honors RSMM_GAME_DIR + Steam autodetect
# on Windows/Linux); no user-specific path baked in.
DEFAULT_EXE = str(default_game_dir() / "Ravenswatch.exe")
PROLOGUE_BYTES_DEFAULT = 32
PROLOGUE_BYTES_MAX = 128
MIN_BYTES = 12  # signature must be at least this many bytes


def parse_pe(data: bytes):
    e_lfanew = struct.unpack_from("<I", data, 0x3C)[0]
    if data[e_lfanew:e_lfanew + 4] != b"PE\x00\x00":
        raise RuntimeError("not a PE file")
    coff_off = e_lfanew + 4
    n_sec = struct.unpack_from("<H", data, coff_off + 2)[0]
    opt_size = struct.unpack_from("<H", data, coff_off + 16)[0]
    opt_off = coff_off + 20
    img_base = struct.unpack_from("<Q", data, opt_off + 24)[0]
    sec_off = opt_off + opt_size
    sections = []
    for i in range(n_sec):
        o = sec_off + i * 40
        name = data[o:o + 8].rstrip(b"\x00").decode("ascii", "ignore")
        vsize = struct.unpack_from("<I", data, o + 8)[0]
        rva = struct.unpack_from("<I", data, o + 12)[0]
        raw_size = struct.unpack_from("<I", data, o + 16)[0]
        raw_off = struct.unpack_from("<I", data, o + 20)[0]
        sections.append({"name": name, "rva": rva, "vsize": vsize,
                         "raw_off": raw_off, "raw_size": raw_size})
    return img_base, sections


def va_to_offset(va: int, img_base: int, sections):
    rva = va - img_base
    for s in sections:
        if s["rva"] <= rva < s["rva"] + s["vsize"]:
            delta = rva - s["rva"]
            if delta >= s["raw_size"]:
                return None
            return s["raw_off"] + delta
    return None


def relocatable_operand_bytes(insn) -> set[int]:
    """Return offsets within this instruction whose bytes encode an
    address that will shift across rebuilds — those bytes get wildcarded
    in the pattern. Approach: any operand of type IMM or MEM that is
    RIP-relative, or any branch displacement, gets its 4-byte slot
    masked. We don't try to mask 1-byte short branches (jcc rel8) —
    those rarely appear in prologues.
    """
    masked: set[int] = set()
    if not insn.operands:
        return masked
    # Branches: jmp/call/jcc all encode rel32 immediately after the
    # opcode bytes. capstone records the imm value but not directly the
    # offset within the bytes — use insn.disp_offset / imm_offset which
    # are populated when capstone is built with detail=True. Fall back
    # to scanning common patterns.
    if hasattr(insn, "disp_offset") and insn.disp_offset != 0:
        size = insn.disp_size or 4
        for k in range(size):
            masked.add(insn.disp_offset + k)
    if hasattr(insn, "imm_offset") and insn.imm_offset != 0:
        size = insn.imm_size or 4
        # Only mask 4-byte immediates (address-typed). 1-byte / 8-byte
        # constants are usually plain numbers, keep them as anchors.
        if size == 4:
            for k in range(size):
                masked.add(insn.imm_offset + k)
    return masked


def make_pattern(prologue: bytes, base_va: int, target_len: int) -> tuple[str | None, int]:
    """Disassemble until ≥ target_len bytes consumed. Returns (pattern,
    actual_byte_length). Pattern is space-separated hex with '??' for
    relocation-sensitive bytes."""
    md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_64)
    md.detail = True
    masked_global: set[int] = set()
    consumed = 0
    for insn in md.disasm(prologue, base_va):
        if consumed >= target_len:
            break
        rel = relocatable_operand_bytes(insn)
        for off in rel:
            masked_global.add(consumed + off)
        consumed += insn.size
    if consumed < MIN_BYTES:
        return None, 0
    out = []
    for i in range(consumed):
        if i in masked_global:
            out.append("??")
        else:
            out.append(f"{prologue[i]:02x}")
    return " ".join(out), consumed


class _Overlapping:
    """A compiled pattern whose ``finditer`` yields every position it matches at, the way
    the loader counts them: ``fn_resolver.cpp::scan_all`` steps one byte past each hit,
    so matches may overlap, and plain ``re.finditer`` would skip those and rank
    ``match_index`` differently. Each search restarts one byte past the last hit, which
    keeps the regex engine's fast literal-prefix search (a lookahead would lose it)."""

    __slots__ = ("rx",)

    def __init__(self, rx: re.Pattern[bytes]):
        self.rx = rx

    def finditer(self, text: bytes):
        search, pos = self.rx.search, 0
        while (m := search(text, pos)) is not None:
            yield m
            pos = m.start() + 1


def pattern_regex(pat: str) -> _Overlapping:
    """``pat`` ("40 53 ?? 8d") compiled for loader-faithful scanning (see _Overlapping)."""
    body = b"".join(b"." if t == "??" else re.escape(bytes([int(t, 16)]))
                    for t in pat.split())
    return _Overlapping(re.compile(body, re.DOTALL))


def scan_offsets(text: bytes, pat: str) -> list[int]:
    """Every offset in ``text`` where ``pat`` matches, ascending, loader semantics."""
    return [m.start() for m in pattern_regex(pat).finditer(text)]


# Scanning ~50k patterns over ~15 MB of .text is minutes of CPU, so it is spread over
# processes. The text is handed to each worker once (inherited on fork, pickled once
# per worker elsewhere), not per pattern.
_SCAN_TEXT = b""


def _scan_init(text: bytes) -> None:
    global _SCAN_TEXT
    _SCAN_TEXT = text


def _scan_one(pat: str) -> tuple[str, list[int]]:
    return pat, scan_offsets(_SCAN_TEXT, pat)


def scan_many(text: bytes, patterns, workers: int | None = None) -> dict[str, list[int]]:
    """``{pattern: offsets}`` for every distinct pattern, scanned in parallel."""
    import multiprocessing as mp
    pats = sorted(set(patterns))
    if not pats:
        return {}
    workers = workers or max(1, (os.cpu_count() or 2) - 1)
    if workers == 1 or len(pats) < 64:
        return {p: scan_offsets(text, p) for p in pats}
    with mp.Pool(workers, initializer=_scan_init, initargs=(text,)) as pool:
        return dict(pool.imap_unordered(_scan_one, pats, chunksize=64))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--exe", default=DEFAULT_EXE)
    ap.add_argument("--symbols", default="docs/_re/out/symbols.json")
    ap.add_argument("--out", default="data/function_patterns.json")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--workers", type=int, help="processes for the .text scans (default: cores-1)")
    args = ap.parse_args()

    with open(args.exe, "rb") as f:
        data = f.read()
    img_base, sections = parse_pe(data)
    print(f"image_base=0x{img_base:x}, .text at rva=0x{sections[0]['rva']:x}", file=sys.stderr)

    with open(args.symbols) as f:
        syms = json.load(f)

    # Pass 1: generate default-length patterns.
    out = []
    fail = 0
    for i, s in enumerate(syms):
        if args.limit and i >= args.limit:
            break
        va = int(s["addr"], 16)
        off = va_to_offset(va, img_base, sections)
        if off is None:
            fail += 1
            continue
        prologue = data[off:off + PROLOGUE_BYTES_MAX + 16]
        pat, used = make_pattern(prologue, va, PROLOGUE_BYTES_DEFAULT)
        if pat is None:
            fail += 1
            continue
        out.append({
            "name": s["name"], "addr": s["addr"], "size": s["size"],
            "pattern": pat, "used_bytes": used, "_file_off": off,
        })
        if (i + 1) % 5000 == 0:
            print(f"  pass1 {i + 1}/{len(syms)} ok={len(out)} fail={fail}", file=sys.stderr)

    # Pass 2: any pattern that's not unique gets extended. Iterate until
    # every pattern is unique or we hit the max length.
    from collections import Counter
    extended = 0
    for round_no in range(6):
        counts = Counter(x["pattern"] for x in out)
        dupes = {p for p, n in counts.items() if n > 1}
        if not dupes:
            break
        new_len = PROLOGUE_BYTES_DEFAULT + (round_no + 1) * 16
        if new_len > PROLOGUE_BYTES_MAX:
            new_len = PROLOGUE_BYTES_MAX
        print(f"  pass2 round={round_no} dupes={sum(counts[p] for p in dupes)} "
              f"extending to {new_len}b", file=sys.stderr)
        for entry in out:
            if entry["pattern"] in dupes:
                prologue = data[entry["_file_off"]:entry["_file_off"] + PROLOGUE_BYTES_MAX + 16]
                pat, used = make_pattern(prologue, int(entry["addr"], 16), new_len)
                if pat:
                    entry["pattern"] = pat
                    entry["used_bytes"] = used
                    extended += 1
        if new_len == PROLOGUE_BYTES_MAX:
            break

    counts = Counter(x["pattern"] for x in out)
    unique = sum(1 for v in counts.values() if v == 1)
    print(f"final: {len(out)} total, {unique} unique "
          f"({100 * unique / len(out):.1f}%), extended={extended}", file=sys.stderr)

    # For non-unique patterns, the loader will scan the entire .text and
    # take the Nth match. So we must record the same Nth — counting
    # against the FULL .text scan, not just our symbol list, because the
    # binary also contains thunks/unidentified functions with identical
    # prologues that Ghidra doesn't expose. Mismatch here makes the
    # runtime pick the wrong VA.
    print("  computing match_index against full .text scan...", file=sys.stderr)
    text = sections[0]
    text_bytes = data[text["raw_off"]:text["raw_off"] + text["raw_size"]]
    text_va = img_base + text["rva"]

    # Every pattern is scanned, not only the ones that repeat inside our symbol
    # list: the binary holds thunks and unlisted functions with the same
    # prologue, and a pattern unique in the list but not in .text, recorded
    # as index 0, resolves to whichever copy comes first.
    hits = scan_many(text_bytes, (e["pattern"] for e in out), args.workers)

    # A pattern that still matches more than once is lengthened, once, as far
    # as its own function goes (at most the longest prologue): a unique pattern
    # survives a patch that shifts the other copies, an index does not. It
    # never runs into the next function, whose own changes would break it.
    # Kept only if it matches fewer places.
    def room(e) -> int:
        return min(PROLOGUE_BYTES_MAX, int(e.get("size") or 0))

    multi = [e for e in out if len(hits[e["pattern"]]) > 1 and e["used_bytes"] < room(e)]
    longer = {}
    for e in multi:
        prologue = data[e["_file_off"]:e["_file_off"] + PROLOGUE_BYTES_MAX + 16]
        pat, used = make_pattern(prologue, int(e["addr"], 16), room(e))
        if pat and pat != e["pattern"] and e["used_bytes"] < used <= room(e):
            longer[id(e)] = (pat, used)
    print(f"  {len(multi)} entries match more than once in .text; "
          f"rescanning {len(longer)} lengthened patterns", file=sys.stderr)
    hits.update(scan_many(text_bytes, (p for p, _u in longer.values()), args.workers))
    lengthened = 0
    for e in multi:
        if id(e) in longer:
            pat, used = longer[id(e)]
            if len(hits[pat]) < len(hits[e["pattern"]]):
                e["pattern"], e["used_bytes"] = pat, used
                lengthened += 1

    for e in out:
        va_to_idx = {text_va + o: i for i, o in enumerate(hits[e["pattern"]])}
        e["match_index"] = va_to_idx.get(int(e["addr"], 16), -1)
    still = sum(1 for e in out if len(hits[e["pattern"]]) > 1)
    print(f"  lengthened {lengthened}; {still} entries still resolve by index",
          file=sys.stderr)
    # Drop entries whose match_index never found a hit (rare — extremely
    # short patterns that fell off both ends).
    before = len(out)
    out = [e for e in out if e.get("match_index", -1) >= 0]
    print(f"  dropped {before - len(out)} unresolvable entries", file=sys.stderr)

    # Drop the file-offset helper before writing.
    for x in out:
        x.pop("_file_off", None)
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    with open(args.out, "w") as f:
        json.dump(out, f)
    print(f"wrote {args.out}: {len(out)} patterns, {fail} failed")

    # Stamp a sidecar meta file recording which game build these patterns
    # were generated against. `rsmm update-data` and `rsmm doctor` compare
    # this against the user's exe to decide freshness, and the sha256 of
    # the patterns file doubles as the download integrity check.
    import datetime
    import hashlib
    out_path = Path(args.out)
    meta = {
        "schema": 1,
        "generated": datetime.datetime.now(datetime.UTC)
                             .isoformat(timespec="seconds"),
        "game_exe_sha256": hashlib.sha256(data).hexdigest(),
        "game_exe_size": len(data),
        "pattern_count": len(out),
        "patterns_sha256": hashlib.sha256(out_path.read_bytes()).hexdigest(),
    }
    meta_path = out_path.with_name(out_path.stem + ".meta.json")
    meta_path.write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {meta_path}")


if __name__ == "__main__":
    main()
