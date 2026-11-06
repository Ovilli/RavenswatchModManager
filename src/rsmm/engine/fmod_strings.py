"""Read every FMOD path (events, buses, VCAs, snapshots, banks) out of the
game's strings bank.

`Audio/Master.strings.bank` is a RIFF ``FEV `` file whose ``STDT`` chunk holds
the project's path table as a radix trie (decoded 2026-11-06 against the
Update 6 bank, 3,744 paths):

* nodes are 8 bytes — ``u24 label_offset | u8 first_char | u24 first_child |
  u8 child_count``; node 0 is the root (label ``0xffffff``), children of a node
  are contiguous;
* ``label_offset`` points into a pool of NUL-terminated edge labels, and the
  node's ``first_char`` is that label's first byte LOWER-CASED (FMOD path
  lookup is case-insensitive, so the trie branches on the folded character);
* a path ends at a leaf (``child_count == 0``). A path that is also a prefix
  of another (``bus:/`` and ``bus:/Music``) is a branch with an empty-label
  leaf child.

The chunk header in front of the nodes and the pool's position are not decoded:
the pool is found by the one invariant above — every node's ``first_char``
equals ``pool[label_offset]`` — which is checked for EVERY node before any path
is returned, so a format change raises instead of producing plausible garbage.
"""

from __future__ import annotations

import struct
from functools import cache
from pathlib import Path

from rsmm.engine import cipher

STRINGS_BANK = "Audio/Master.strings.bank"
_NO_LABEL = 0xFFFFFF


class FmodStringsError(ValueError):
    """The strings bank is missing or not in the layout this module reads."""


def _chunk(data: bytes, tag: bytes) -> bytes:
    i = data.find(tag)
    if i < 0:
        raise FmodStringsError(f"no {tag.decode()} chunk in strings bank")
    (n,) = struct.unpack_from("<I", data, i + 4)
    return data[i + 8:i + 8 + n]


def _node(c: bytes, k: int) -> tuple[int, int, int, int]:
    a, b = struct.unpack_from("<II", c, 8 + 8 * k)
    return a & 0xFFFFFF, a >> 24, b & 0xFFFFFF, b >> 24


def _reachable(c: bytes) -> list[int]:
    """Every node index reachable from the root, bounds-checked."""
    limit = (len(c) - 8) // 8
    seen, stack, out = set(), [0], []
    while stack:
        k = stack.pop()
        if k in seen or k >= limit:
            raise FmodStringsError(f"trie node {k} out of range or revisited")
        seen.add(k)
        out.append(k)
        _, _, child, nc = _node(c, k)
        if child + nc > limit:
            raise FmodStringsError(f"trie node {k} children out of range")
        stack.extend(range(child, child + nc))
    return out


def _find_pool(c: bytes, nodes: list[int]) -> int:
    labelled = [(lo, ch) for lo, ch, _, _ in (_node(c, k) for k in nodes)
                if lo != _NO_LABEL and ch]
    fold = bytes(b + 32 if 65 <= b <= 90 else b for b in range(256))
    if not labelled:
        raise FmodStringsError("trie has no labelled nodes")
    probe = labelled[:64]
    hi = max(lo for lo, _ in labelled)
    first_lo, first_ch = probe[0]
    for base in range(len(c) - hi):
        if fold[c[base + first_lo]] != first_ch:
            continue
        if all(fold[c[base + lo]] == ch for lo, ch in probe) and \
                all(fold[c[base + lo]] == ch for lo, ch in labelled):
            return base
    raise FmodStringsError("no label pool satisfies every node's first character")


def parse(data: bytes) -> list[str]:
    """All paths in a strings bank, sorted."""
    if data[:4] != b"RIFF":
        raise FmodStringsError("not a RIFF file")
    c = _chunk(data, b"STDT")
    nodes = _reachable(c)
    pool = _find_pool(c, nodes)

    def label(lo: int) -> str:
        if lo == _NO_LABEL:
            return ""
        s = pool + lo
        return c[s:c.index(b"\0", s)].decode("utf-8", "replace")

    out: list[str] = []
    stack = [(0, "")]
    while stack:
        k, prefix = stack.pop()
        lo, _, child, nc = _node(c, k)
        s = prefix + label(lo)
        if nc == 0:
            out.append(s)
        else:
            stack.extend((child + j, s) for j in range(nc))
    return sorted(set(out))


def bank_path(game_dir: Path) -> Path:
    enc = cipher.encode(STRINGS_BANK.replace("/", "\\")).replace("\\", "/")
    return Path(game_dir) / "DarkTalesResources" / "_Cooking" / enc


@cache
def _paths_cached(path: str, mtime: float) -> tuple[str, ...]:
    return tuple(parse(Path(path).read_bytes()))


def paths(game_dir: Path) -> list[str]:
    """Every FMOD path the installed game defines."""
    p = bank_path(game_dir)
    if not p.is_file():
        raise FmodStringsError(f"strings bank not found: {p}")
    return list(_paths_cached(str(p), p.stat().st_mtime))
