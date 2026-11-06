"""New skins appended to a herodef (engine.herodef_skins) + the `skin` kind.

The synthetic herodef below has the shape every shipped one has (object table,
sub-objects, root last listing its skins by id); the shipped files, when the
corpus is present, keep the reader honest about the real layout.
"""

from __future__ import annotations

import struct

import pytest

from rsmm.engine import cooked
from rsmm.engine import herodef_skins as HS

M_B, M_E = cooked.MARK_BEGIN, cooked.MARK_END


def _lstr(s: str) -> bytes:
    return struct.pack("<I", len(s)) + s.encode()


def _text(bank: str, row: int, key: str) -> bytes:
    return struct.pack("<I", 3) + _lstr("Text") + _lstr(bank) + struct.pack("<I", row) + _lstr(key)


def _skin(guid: int, name: str, conds: list[int]) -> bytes:
    lock = (M_B + struct.pack("<I", 7) + struct.pack(f"<{len(conds) + 1}I", len(conds), *conds)
            + b"\x00" + M_B + struct.pack("<I", 8) + b"\xff" * 4 + M_E + M_E)
    return (struct.pack("<I", 1) + bytes([guid]) * 16 + b"\x00" * 5
            + _text("Skins~GAM.xls", 10 + guid, f"{name}_Title")
            + _lstr("Ui") + _lstr(f"BookMenu\\Skins\\Icon_{name}.png")
            + _lstr("EntitySettings") + _lstr(f"Heroes\\Hero_X\\Hero_X_{name}.entity.ot")
            + lock + b"\x00" + _text("Skins~GAM.xls", 20 + guid, f"{name}_Desc"))


def _herodef() -> bytes:
    """Objects: 0 talent, 1 skin Default (free), 2 skin Dark (locked by 3),
    3 an unlock condition; root lists skins as ``2 | 1, 2``."""
    classes = [cooked.ClassDef("oCDtHeroDefinition", 1, 1, 1, 0),
               cooked.ClassDef("SkinProfileDataSettings", 2, 1, 5, 0),
               cooked.ClassDef("SkillProfileDataSettings", 3, 1, 4, 0),
               cooked.ClassDef("Cond", 4, 1, 0, 0)]
    table = [2, 1, 1, 3]
    objs = [struct.pack("<I", 2) + b"talent",
            _skin(1, "Default", []),
            _skin(2, "Dark", [3]),
            struct.pack("<I", 3) + b"cond"]
    root = b"\x00\x00\x00\x00rootstuff" + struct.pack("<3I", 2, 1, 2) + b"tail"
    cf = cooked.CookedFile(variant="A", hdr_a=0x10, flags=1, extra=1, classes=classes,
                           sections=[cooked.Section(struct.pack(f"<{len(table) + 1}I",
                                                                len(table), *table))]
                           + [cooked.Section(o) for o in objs] + [cooked.Section(root)])
    return cooked.emit(cf)


def _spec(n: int) -> HS.NewSkin:
    return HS.NewSkin(guid=bytes([0x40 + n]) * 16,
                      entity=f"Heroes\\Hero_X\\Hero_X_New{n}.entity.ot",
                      icon=f"BookMenu\\Skins\\Icon_New{n}.png",
                      title=HS.TextRef("Skins~GAM.xls", 100 + n, f"New{n}_Title"),
                      description=HS.TextRef("Skins~GAM.xls", 200 + n, f"New{n}_Desc"))


def test_reads_skins_in_root_order():
    ss = HS.skins(_herodef())
    assert [s.entity.rsplit("\\", 1)[-1] for s in ss] == ["Hero_X_Default.entity.ot",
                                                         "Hero_X_Dark.entity.ot"]
    assert ss[0].unlocked and ss[1].conditions == (3,)
    assert ss[0].title == HS.TextRef("Skins~GAM.xls", 11, "Default_Title")


def test_add_skins_appends_without_moving_any_object():
    blob = _herodef()
    out = HS.add_skins(blob, [_spec(1), _spec(2)])
    cf_in, cf = cooked.parse(blob), cooked.parse(out)
    # Every existing object is byte-identical at its old id: nothing renumbered.
    for k in range(4):
        assert cf.sections[k + 1].payload == cf_in.sections[k + 1].payload
    (n,) = struct.unpack_from("<I", cf.sections[0].payload)
    assert n == 6 and list(struct.unpack_from("<6I", cf.sections[0].payload, 4)) == \
        [2, 1, 1, 3, 1, 1]
    assert len(cf.sections) == n + 2                      # root still last
    assert struct.pack("<5I", 4, 1, 2, 4, 5) in cf.sections[-1].payload
    ss = HS.skins(out)
    assert [s.obj_id for s in ss] == [1, 2, 4, 5]
    new = ss[2]
    assert new.unlocked, "a new skin is copied from the FREE skin, never a locked one"
    assert new.guid == bytes([0x41]) * 16
    assert new.title == HS.TextRef("Skins~GAM.xls", 101, "New1_Title")
    assert new.icon.endswith("Icon_New1.png") and new.entity.endswith("Hero_X_New1.entity.ot")


def test_refuses_what_it_cannot_account_for():
    blob = _herodef()
    with pytest.raises(HS.HerodefSkinError):
        HS.add_skins(blob, [_spec(1), _spec(1)])            # same GUID twice
    with pytest.raises(HS.HerodefSkinError):
        HS.add_skins(blob, [_spec(1)], template=2)           # a locked template
    with pytest.raises(HS.HerodefSkinError):
        HS.add_skins(blob, [_spec(1)], template=0)          # not a skin
    cf = cooked.parse(blob)
    cf.sections[0] = cooked.Section(struct.pack("<4I", 3, 2, 1, 1))   # table disagrees
    with pytest.raises(HS.HerodefSkinError):
        HS.skins(cooked.emit(cf))


def test_shipped_herodefs_if_present():
    from rsmm.engine import corpus, herodefs
    found = 0
    for name in herodefs.names():
        raw = corpus.read(herodefs.rel(name))
        if raw is None:
            continue
        found += 1
        ss = HS.skins(raw)
        assert len(ss) >= 8 and ss[0].unlocked and ss[0].entity.endswith("_Default.entity.ot")
        out = HS.add_skins(raw, [_spec(1)])
        assert HS.skins(out)[:len(ss)] == ss and len(HS.skins(out)) == len(ss) + 1
    if not found:
        pytest.skip("no herodefs in the corpus")


def test_scarlet_is_found_by_her_display_name():
    from rsmm.engine import herodefs
    if not herodefs.names():
        pytest.skip("no herodefs in the corpus")
    assert herodefs.stem("Scarlet") == herodefs.stem("Red")


def test_skin_kind_is_registered_and_confirmed():
    from rsmm.sdk.content import KIND_CONFIDENCE, KINDS
    from rsmm.sdk.manifest_spec import CONTENT_FIELDS
    assert "skin" in KINDS and KIND_CONFIDENCE["skin"] == "confirmed"
    assert CONTENT_FIELDS["skin"] == frozenset({"hero", "skins"})


def test_skin_guid_is_stable_and_distinct():
    from rsmm.sdk.kinds.skins import skin_guid
    assert skin_guid("m", "Red_Update6", "Crimson") == skin_guid("m", "Red_Update6", "Crimson")
    assert skin_guid("m", "Red_Update6", "Crimson") != skin_guid("m", "Red_Update6", "Frost")
    assert len(skin_guid("m", "h", "s")) == 16
