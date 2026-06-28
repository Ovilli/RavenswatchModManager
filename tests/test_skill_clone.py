"""Tests for hero skill-row cloning (``rsmm.engine.skill_clone``).

Hermetic: builds a synthetic herodef blob mimicking the cooked skill-row grammar
(``docs/_re/kinds/skills-system.md``) so the suite never depends on game-derived
assets. A second, guarded check runs against a real local herodef if one is
present (skipped otherwise) to keep the parser honest about the real layout.
"""

from __future__ import annotations

import struct
from pathlib import Path

import pytest

from rsmm.engine import skill_clone as SC

_BEGIN = bytes.fromhex("1111bbaa")
_END = bytes.fromhex("2222bbaa")


def _row(name: str, g1: bytes, g2: bytes) -> bytes:
    """One synthetic skill row: BEGIN<4> 00 <name> <g1> <g2> 00*9 END."""
    enc = name.encode("ascii")
    return (_BEGIN + struct.pack("<I", 4) + b"\x00"
            + struct.pack("<I", len(enc)) + enc + g1 + g2 + b"\x00" * 9 + _END)


def _herodef(rows: list[bytes]) -> bytes:
    # a little leading header noise + the rows as top-level siblings
    return b"\x07\x00\x00\x00CookedHDR" + b"".join(rows) + b"\x00\x00\x00\x00"


# GUIDs chosen to avoid the marker byte-patterns so depth-match stays clean.
_G = {
    "dive1": bytes(range(0x10, 0x20)),
    "dive2": bytes(range(0x20, 0x30)),
    "dash1": bytes(range(0x30, 0x40)),
    "dash2": bytes(range(0x40, 0x50)),
}


@pytest.fixture
def blob() -> bytes:
    return _herodef([
        _row("Skill Controller Attack Dive", _G["dive1"], _G["dive2"]),
        _row("Skill Controller Defense Dash", _G["dash1"], _G["dash2"]),
    ])


def test_list_rows(blob):
    rows = SC.list_skill_rows(blob)
    assert [r.name for r in rows] == [
        "Skill Controller Attack Dive", "Skill Controller Defense Dash"]
    # identity GUID is the 16 bytes right after the name
    assert blob[rows[0].guid1_off:rows[0].guid1_off + 16] == _G["dive1"]
    # row blob is well-formed
    assert rows[0].raw(blob).startswith(_BEGIN)
    assert rows[0].raw(blob).endswith(_END)


def test_find_skill_short_and_full(blob):
    a = SC.find_skill(blob, "Attack Dive")
    b = SC.find_skill(blob, "Skill Controller Attack Dive")
    assert a == b
    with pytest.raises(SC.SkillCloneError):
        SC.find_skill(blob, "Nonexistent")


def test_repoint_in_place_is_count_neutral(blob):
    before = len(SC.list_skill_rows(blob))
    out = SC.repoint_skill(blob, "Attack Dive", "Custom Bleed",
                           new_guid1=b"\xAA" * 16)
    rows = SC.list_skill_rows(out)
    assert len(rows) == before  # no new row
    names = [r.name for r in rows]
    assert "Skill Controller Custom Bleed" in names
    assert "Skill Controller Attack Dive" not in names
    # identity reminted; the other row is untouched
    custom = SC.find_skill(out, "Custom Bleed")
    assert out[custom.guid1_off:custom.guid1_off + 16] == b"\xAA" * 16
    assert SC.find_skill(out, "Defense Dash").raw(out) == \
        SC.find_skill(blob, "Defense Dash").raw(blob)


def test_clone_adds_one_row_keeping_source_identity(blob):
    before = SC.list_skill_rows(blob)
    out, guid = SC.clone_skill(blob, "Attack Dive", "Attack Dive Plus")
    rows = SC.list_skill_rows(out)
    assert len(rows) == len(before) + 1
    names = [r.name for r in rows]
    assert names.count("Skill Controller Attack Dive") == 1  # source kept
    assert "Skill Controller Attack Dive Plus" in names
    # DEFAULT keeps the source identity (remint is the brick risk) + GUID#2 ref
    src = SC.find_skill(blob, "Attack Dive")
    new = SC.find_skill(out, "Attack Dive Plus")
    assert guid == blob[src.guid1_off:src.guid1_off + 16]
    assert out[new.guid1_off:new.guid1_off + 16] == guid
    # the spliced copy sits right after the source row
    assert new.begin == src.end


def test_clone_remint_gives_unique_identity(blob):
    src = SC.find_skill(blob, "Attack Dive")
    out, guid = SC.clone_skill(blob, "Attack Dive", "Repro", remint=True)
    assert guid != blob[src.guid1_off:src.guid1_off + 16]
    # deterministic mint from the new name
    _, g2 = SC.clone_skill(blob, "Attack Dive", "Repro", remint=True)
    assert guid == g2 and len(guid) == 16


def test_mint_guid():
    assert len(SC.mint_guid()) == 16
    assert SC.mint_guid(b"x") == SC.mint_guid(b"x")
    assert SC.mint_guid(b"x") != SC.mint_guid(b"y")


def test_override_bank_values(tmp_path):
    """Relabel an existing key's value in every lang sibling, count-neutral."""
    from rsmm.engine import text_patches as TP

    def write_bank(path, entries):
        tf = TP.TextFile(path=path, header=bytes(TP.HEADER_SIZE),
                         entries=entries, footer=b"")
        path.write_bytes(TP.write_text_file(tf))

    base = tmp_path / "Hero_Test_Common~GAM.xls.LocalText.gen"
    keys = ["Skill_Attack_Dive_Name", "Skill_Attack_Dive_Desc", "Other_Key"]
    write_bank(base, keys)
    for lang in ("EN", "FR"):
        write_bank(TP.lang_path_for(base, lang), ["Dive", "Dash forward.", "x"])

    out = TP.override_bank_values(base, {
        "Skill_Attack_Dive_Name": "Lightning Dash",
        "Skill_Attack_Dive_Desc": "Zaps.",
    })
    assert set(out) == {".LangEN", ".LangFR"}  # base (keys) untouched
    # decode the EN result via the module's own parser (count must be unchanged)
    en = tmp_path / "out.gen"
    en.write_bytes(out[".LangEN"])
    parsed = TP.parse_text_file(en)
    assert parsed.entries == ["Lightning Dash", "Zaps.", "x"]

    with pytest.raises(KeyError):
        TP.override_bank_values(base, {"No_Such_Key": "z"})


# --- guarded check against a real herodef, if one is present locally ----------

_REAL = Path("data/uncooked/Definitions/Heroes/Aladdin.herodef.ot.DtHeroDefinition.gen")


@pytest.mark.skipif(not _REAL.exists(), reason="real herodef not present")
def test_real_herodef_row_layout():
    d = _REAL.read_bytes()
    rows = SC.list_skill_rows(d)
    assert len(rows) == 28  # 24 base + 4 upgrade (Aladdin)
    assert any(r.name.endswith("Upgrade 1") for r in rows)
    # round-trip: cloning preserves every other row byte-for-byte
    out, _ = SC.clone_skill(d, "Attack Dive", "Attack Dive RSMM")
    assert len(SC.list_skill_rows(out)) == 29
    assert SC.find_skill(out, "Defense Dash").raw(out) == \
        SC.find_skill(d, "Defense Dash").raw(d)
