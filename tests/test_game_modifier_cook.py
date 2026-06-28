"""Clone/remint of a custom game modifier ("negative mode").

Corpus-gated: the vanilla ``.gamemodifierdef.ot`` defs are game-derived and not
committed, so these skip when the local corpus is absent.
"""

from __future__ import annotations

import struct
from pathlib import Path

import pytest

from rsmm.engine import cooked
from rsmm.engine import game_modifier_cook as GMC
from rsmm.engine.cooked_schemas import definitions as _defs

_DIR = Path("data/uncooked/Definitions/GameModifiers")
_BASE = "NoBossTimer"
_BASE_GEN = _DIR / f"{_BASE}{GMC.GEN_SUFFIX}"
_BASE_KEY = 0x1A7945FC  # NoBossTimer behaviour entity-value id

requires_corpus = pytest.mark.skipif(
    not _BASE_GEN.exists(), reason="vanilla gamemodifier corpus not present"
)


def _tail(blob: bytes) -> bytes:
    cf = cooked.parse(blob)
    body = _defs._SPECS[GMC.CLASS].decode_body(cf.sections[-1].payload)
    return bytes.fromhex(body["_tail_hex"])


def test_rewrite_tail_strings_preserves_binary_and_renames():
    # <u32 8> | lstr "NoBossTimer" | 1111bbaa 04 <key> | lstr "Keep"
    tail = (
        struct.pack("<I", 8)
        + struct.pack("<I", len(_BASE)) + _BASE.encode()
        + GMC._BEHAVIOR_MARK + struct.pack("<I", _BASE_KEY)
        + struct.pack("<I", 4) + b"Keep"
    )
    out, hits = GMC._rewrite_tail_strings(tail, {_BASE: "CoolMod"})
    assert hits == 1
    # identity renamed, unrelated ascii string + binary key untouched
    assert b"CoolMod" in out and _BASE.encode() not in out
    assert b"Keep" in out
    assert GMC._behavior_key(out) == _BASE_KEY
    # length prefix of the renamed string is correct
    o = struct.unpack_from("<I", out, 0)[0]  # the leading u32(8) is copied raw
    assert o == 8


@requires_corpus
def test_clone_renames_identity_keeps_behavior():
    out, base_key = GMC.clone(_BASE_GEN.read_bytes(), _BASE, "CustomNegative")
    assert base_key == _BASE_KEY
    # re-parses as a valid cooked def
    tail = _tail(out)
    # the standalone identity lstr is renamed (length-prefixed exact match); the
    # base name still lives inside the unrenamed text keys (relabel_text=False).
    assert struct.pack("<I", len("CustomNegative")) + b"CustomNegative" in tail
    assert struct.pack("<I", len(_BASE)) + _BASE.encode() not in tail
    assert b"GameModifier_NoBossTimer_Title" in tail  # display reuses base text
    # behaviour preserved when no effect override
    assert GMC._behavior_key(tail) == _BASE_KEY


@requires_corpus
def test_clone_swaps_effect_key():
    nightonly = 0x1A8B53BC
    out, base_key = GMC.clone(
        _BASE_GEN.read_bytes(), _BASE, "CustomNegative", effect_key=nightonly
    )
    assert base_key == _BASE_KEY
    assert GMC._behavior_key(_tail(out)) == nightonly


@requires_corpus
def test_clone_relabel_renames_text_keys():
    out, _ = GMC.clone(
        _BASE_GEN.read_bytes(), _BASE, "CustomNegative", relabel_text=True
    )
    tail = _tail(out)
    assert b"GameModifier_CustomNegative_Title" in tail
    assert b"GameModifier_CustomNegative_Desc" in tail
    assert b"GameModifier_NoBossTimer_Title" not in tail


@requires_corpus
def test_clone_unknown_base_id_raises():
    with pytest.raises(GMC.GameModifierCookError):
        GMC.clone(_BASE_GEN.read_bytes(), "NotTheEmbeddedId", "CustomNegative")
