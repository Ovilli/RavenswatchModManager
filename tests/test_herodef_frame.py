"""The roster record codec (engine/herodef_frame.py): every shipped herodef
re-encodes byte for byte, and a record built from data decodes as written."""

from __future__ import annotations

import pytest

from rsmm.engine import herodef_frame as HDF


def _herodefs():
    from rsmm.engine import corpus
    try:
        return sorted(corpus.rels("Definitions/Heroes/", ".DtHeroDefinition.gen"))
    except Exception:  # noqa: BLE001 — no corpus
        return []


@pytest.mark.skipif(not _herodefs(), reason="no hero corpus")
@pytest.mark.parametrize("rel", _herodefs())
def test_every_shipped_herodef_round_trips(rel):
    from rsmm.engine import corpus
    raw = corpus.read(rel)
    h = HDF.decode(raw)
    assert HDF.encode(h) == raw
    assert len(h.root["rows"]) == sum(1 for c, _ in h.objects if c == HDF.SKILL)


@pytest.mark.skipif(not _herodefs(), reason="no hero corpus")
def test_a_record_written_from_data():
    from rsmm.engine import corpus
    T = HDF.Text.of
    rec = HDF.Record(
        hid="X", sort=14000, name=T("Common~GAM.xls", "X_Name"), desc=T("Common~GAM.xls", "X_D"),
        portrait=("Ui", "p.png"), book=(("Ui", "a"), ("Ui", "b"), ("Ui", "c"), ("Ui", "d")),
        new_hero=("Ui", "n.png"), codex=[("Ui", f"c{i}.png") for i in range(5)],
        talents=[HDF.Talent(f"Skill Controller Attack {i}", bytes([i]) * 16) for i in range(3)]
        + [HDF.Talent("Skill Controller Ultimate Power 1", bytes([9]) * 16, True),
           HDF.Talent("Skill Controller Ultimate 2 Upgrade 2", bytes([8]) * 16, True)],
        pages=[HDF.Page(T("b", "t"), T("b", "d"), ("Ui", "f"), ("Ui", "g"), ("Ui", "h"))],
        skins=[HDF.Skin("Heroes\\Hero_Common\\Hero_X_Default.entity.ot", ("Ui", "i.png"))],
        lowres="Heroes\\Hero_Common\\Hero_X_Default_LowRes.entity.ot")
    raw = HDF.build(rec, corpus.read(_herodefs()[0]))
    h = HDF.decode(raw)
    assert HDF.encode(h) == raw
    assert h.root["rows"] == [0, 1, 2, 3, 4] and h.root["stories"] == [5]
    assert h.root["skins"] == [6]
    rows = [d for c, d in h.objects if c == HDF.SKILL]
    # tail 01 only on "Ultimate 2 Upgrade 2", as 12 of 13 shipped heroes
    assert [r["tail"][5] for r in rows] == [0, 0, 0, 0, 1]
    # an unlocked hero: no locked-condition text, no unlock message (4/4 shipped)
    assert h.root["locked_text"] == HDF.Text() and h.root["unlock_message"] == HDF.Text()
    assert h.root["lock"].ids == [] and h.root["sort"] == 14000
