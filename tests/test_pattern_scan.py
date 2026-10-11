"""The byte-pattern scanner every pattern script shares (scripts/gen_function_patterns.py).

It must count matches exactly as the loader's ``fn_resolver.cpp::scan_all`` does, or a
recorded ``match_index`` picks a different function at runtime than the one it was made
for: every start position, overlapping hits included, ascending."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

pytest.importorskip("capstone")          # the module disassembles with it at import
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import gen_function_patterns as gen


def loader_scan(text: bytes, pat: str) -> list[int]:
    """fn_resolver.cpp::scan_all, transcribed: anchor on the first fixed byte, step one
    byte past each candidate."""
    toks = pat.split()
    mask = [t != "??" for t in toks]
    want = [0 if t == "??" else int(t, 16) for t in toks]
    anchor = mask.index(True)
    out, i, last = [], anchor, len(text) - len(toks) + anchor
    while i <= last:
        pos = text.find(bytes([want[anchor]]), i, last + 1)
        if pos < 0:
            break
        b = pos - anchor
        if all(not m or text[b + k] == w for k, (m, w) in enumerate(zip(mask, want, strict=True))):
            out.append(b)
        i = pos + 1
    return out


@pytest.mark.parametrize("text,pat", [
    (b"\xcc" * 8, "cc cc cc"),                       # padding: every offset overlaps
    (b"\x48\x48\x48\x8b\x48\x48\x8b", "48 ?? 8b"),   # wildcard inside, overlapping
    (b"\x00\x2e\x2a\x5c\x2b\x00\x2e\x2a", "2e 2a"),  # regex metabytes . * \\ + taken literally
    (b"\x90\x48\x89\x5c\x24\x08\x90", "?? 48 89"),   # leading wildcard
    (b"\x01\x02\x03", "04 05"),                      # no hit
    (b"\x0a\x0d\x0a", "0a"),                         # newline bytes match under DOTALL
])
def test_the_scanner_counts_like_the_loader(text, pat):
    assert gen.scan_offsets(text, pat) == loader_scan(text, pat)


def test_overlapping_hits_are_counted_unlike_plain_finditer():
    import re
    text = b"\xcc" * 6
    assert gen.scan_offsets(text, "cc cc") == [0, 1, 2, 3, 4]
    assert [m.start() for m in re.finditer(b"\xcc\xcc", text)] == [0, 2, 4]   # the old bug


def test_scan_many_matches_scan_offsets_in_parallel():
    text = bytes(range(256)) * 50 + b"\xcc" * 300
    pats = ["cc cc cc", "00 01 ?? 03", "fe ff", "10 ?? ?? 13 14"] * 20   # >64: uses the pool
    pats += [f"{i:02x} {(i + 1) % 256:02x}" for i in range(80)]
    got = gen.scan_many(text, pats, workers=2)
    assert got == {p: gen.scan_offsets(text, p) for p in set(pats)}
