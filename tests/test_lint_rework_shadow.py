"""`rsmm lint` flags edits to a base hero file that an `_Update<N>` rework
redefines: the rework's same-name node is the one the game reads."""

from __future__ import annotations

import struct

import pytest

from rsmm.cli.lint import _rework_shadowed_edits
from rsmm.engine import corpus
from rsmm.engine import entity_graph as EG

_SFX = ".entity.ot.EntitySettingsResource.gen"
_DIR = "EntitySettings/Heroes/Hero_Red"
BASE, REWORK = f"Hero_Red{_SFX}", f"Hero_Red_Update6{_SFX}"
needs = pytest.mark.skipif(corpus.read(f"{_DIR}/{REWORK}") is None,
                           reason="no Update 6 hero corpus")


def _bump(raw: bytes, name: str) -> bytes | None:
    """``raw`` with the first value of node ``name`` changed in place."""
    c = next((c for c in EG.parse(raw).components if c.name == name), None)
    if c is None or raw.count(c.body) != 1:
        return None
    off = 0
    for t in EG.tokens(c):
        if t.kind == "value" and t.text.startswith("f32 "):
            tok = c.body[off:off + t.size]
            j = tok.rfind(struct.pack("<f", float(t.text[4:])))
            if j >= 0:  # flip the float's low mantissa byte
                i = raw.index(c.body) + off + j
                return raw[:i] + bytes([raw[i] ^ 1]) + raw[i + 1:]
        off += t.size
    return None


def _names(raw: bytes) -> set[str]:
    return {c.name for c in EG.parse(raw).components}


@pytest.fixture
def red(tmp_path):
    van, mod = tmp_path / "van", tmp_path / "mod"
    van.mkdir()
    mod.mkdir()
    base, rework = corpus.read(f"{_DIR}/{BASE}"), corpus.read(f"{_DIR}/{REWORK}")
    (van / BASE).write_bytes(base)
    (van / REWORK).write_bytes(rework)
    return van, mod, base, rework


def _pick(raw: bytes, names, also=None) -> tuple[str, bytes]:
    for n in sorted(names):
        cur = _bump(raw, n)
        if cur is not None and (also is None or _bump(also, n) is not None):
            return n, cur
    pytest.skip("no editable node")


@needs
def test_edit_to_a_node_the_rework_redefines_is_flagged(red):
    van, mod, base, rework = red
    node, cur = _pick(base, _names(base) & _names(rework))
    hits = _rework_shadowed_edits(mod / BASE, van / BASE, cur, base, None)
    assert ("Hero_Red_Update6", node) in hits


@needs
def test_editing_the_rework_too_clears_it(red):
    van, mod, base, rework = red
    node, cur = _pick(base, _names(base) & _names(rework), also=rework)
    (mod / REWORK).write_bytes(_bump(rework, node))
    assert _rework_shadowed_edits(mod / BASE, van / BASE, cur, base, None) == []


@needs
def test_edit_to_a_base_only_node_is_clean(red):
    van, mod, base, rework = red
    _node, cur = _pick(base, _names(base) - _names(rework))
    assert _rework_shadowed_edits(mod / BASE, van / BASE, cur, base, None) == []


@needs
def test_a_versiondef_that_unwires_the_rework_clears_it(red):
    """`rsmm values backport` ships an old versiondef with no rework aliases,
    which makes the base nodes live again."""
    van, mod, base, rework = red
    _node, cur = _pick(base, _names(base) & _names(rework))
    wired = b"..Heroes\\Hero_Red\\Hero_Red_Update6.entity.ot.."
    assert _rework_shadowed_edits(mod / BASE, van / BASE, cur, base, wired)
    assert _rework_shadowed_edits(mod / BASE, van / BASE, cur, base, b"old table") == []
