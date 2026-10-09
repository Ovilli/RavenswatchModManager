"""An ability's hits putting a status on enemies (`rsmm.engine.talent_status`).

Skips when the game data is not on disk."""

from __future__ import annotations

import struct

import pytest

from rsmm.engine import corpus
from rsmm.engine import entity_check as EC
from rsmm.engine import entity_fields as EF
from rsmm.engine import entity_graph as EG
from rsmm.engine import entity_graph_edit as GE
from rsmm.engine import talent_add_stat as TA
from rsmm.engine import talent_status as TS

GEN = ".entity.ot.EntitySettingsResource.gen"
OWNER = "Heroes\\Hero_Melusine\\Hero_Melusine.entity.ot"


def entity(stem: str) -> bytes:
    for f in corpus.files("EntitySettings/Heroes/Hero_Melusine"):
        if f.name == stem + GEN:
            return f.read_bytes()
    pytest.skip(f"{stem} not available (no mirror or game install)")


@pytest.fixture(scope="module")
def mel() -> bytes:
    return entity("Hero_Melusine")


@pytest.fixture(scope="module")
def caster() -> bytes:
    return entity("Hero_Melusine_Power_Caster_Model")


def debuffs(raw: bytes, damage: str) -> tuple[GE.EntityFile, list[int]]:
    ef = GE.EntityFile(raw)
    c = ef.component(damage)
    f = next(x for x in EF.fields(c) if x.name == "bytes_36")
    n = struct.unpack_from("<I", c.body, f.offset)[0]
    return ef, list(struct.unpack_from(f"<{n}I", c.body, f.offset + 4))


@pytest.mark.parametrize("status", TS.STATUSES)
def test_every_donor_is_found_and_self_contained(status):
    d = TS.DONORS[status]
    raw = corpus.read(d.rel)
    if raw is None:
        pytest.skip("no game data")
    obj = TS.debuff_of(raw, d.modifier)
    assert GE.EntityFile(raw).subtree({obj}) == []


def test_power_hits_apply_a_status_while_the_talent_is_owned(mel, caster):
    hero, flag = TS.add_flag(mel, mel, talent="Attack Speed")
    fg = next(c for c in EG.parse(hero).components if c.name == flag)
    assert [r.path.rsplit("\\", 1)[-1] for r in fg.refs] == ["Skill Attack Speed"]
    out = TS.reader(caster, caster, flag_guid=fg.guid,
                    flag_label=f"[Value] Hero_Melusine\\{fg.group}\\{fg.name}",
                    owner_resource=OWNER, name="Owner Flag")
    out = TS.apply_status(out, corpus.read(TS.DONORS["Ignite"].rel),
                          damage="Primary Ability Damage", status="Ignite",
                          switch="Owner Flag", talent="Attack Speed")
    before = debuffs(caster, "Primary Ability Damage")[1]
    ef, ids = debuffs(out, "Primary Ability Damage")
    assert ids[:-1] == before and len(ids) == len(before) + 1
    owned, _ = ef.pointers()
    assert owned[ids[-1]].owner == ef.component("Primary Ability Damage").index - 1
    sub = EG.Component(0, "x", "", "", b"", None, body=bytes(ef.objects[ids[-1]]),
                       classes=[c.name for c in ef.cf.classes])
    refs = [t.text for t in EG.tokens(sub) if t.kind == "ref" and t.text != "(none)"]
    assert refs == ["[Entity Get Value] Hero_Melusine_Power_Caster_Model\\Owner Flag",
                    "[Modifier] Hero_Melusine_Power_Caster_Model\\"
                    "Skill Attack Speed Ignite On Primary Ability Damage"]
    # The reader is switched on first thing by the caster's start-up state.
    init = ef.component("Event Initialize Power Caster")
    first = next(f for f in EF.fields(init) if f.name == "activates").items[0]
    assert first.text.endswith("\\Owner Flag")
    issues = [i for i in EC.check(out, caster, name="Hero_Melusine_Power_Caster_Model")
              if "exists nowhere" not in i.message]       # the flag is new in the hero file
    assert issues == []


def test_a_hit_in_the_hero_file_switches_on_the_owned_state(mel):
    g = EG.parse(mel)
    ctl = next(c for c in g.components if c.name == "Skill Controller Attack Speed")
    state = TA.owned_state(g, ctl, "Attack Speed").name
    out = TS.apply_status(mel, corpus.read(TS.DONORS["Bleed"].rel),
                          damage="Skill Defense Block Attack Damage", status="Bleed",
                          switch=state, talent="Attack Speed")
    assert EC.check(out, mel, name="Hero_Melusine") == []


def test_a_status_without_a_donor_or_a_wrong_record_is_refused(mel):
    with pytest.raises(TS.StatusError, match="unknown status"):
        TS.apply_status(mel, mel, damage="Skill Defense Block Attack Damage", status="Marked",
                        switch="Skill Attack Speed", talent="Attack Speed")
    with pytest.raises(TS.StatusError, match="not a damage"):
        TS.apply_status(mel, corpus.read(TS.DONORS["Ignite"].rel), damage="Skill Attack Speed",
                        status="Ignite", switch="Skill Attack Speed", talent="Attack Speed")


def test_damages_name_the_ability():
    files = [(f.name.split(".")[0], f.read_bytes())
             for f in corpus.files("EntitySettings/Heroes/Hero_Melusine") if f.name.endswith(GEN)]
    if not files:
        pytest.skip("no game data")
    got = {(d["file"], d["damage"]): d for d in TS.damages(files, "Melusine")}
    power = got[("Hero_Melusine_Power_Caster_Model", "Primary Ability Damage")]
    assert (power["ability"], power["where"]) == ("POWER", "Power_Caster_Model")


def test_the_talent_kind_applies_on_hit(tmp_path):
    from rsmm.sdk.content import ContentDef
    from rsmm.sdk.kinds import talents

    entity("Hero_Melusine")
    defn = ContentDef(kind="talent", id="hits", fields={"hero": "Melusine", "on_hit": [
        {"talent": "Attack Speed", "damage": "Primary Ability Damage", "status": "Ignite"},
        {"talent": "Attack Speed", "damage": "Primary Ability Damage Geyser",
         "status": "Ignite"}]})
    paths = {p.name.split(".")[0]: p.read_bytes() for p in talents.emit("t", defn, tmp_path)}
    flag = next(c for c in EG.parse(paths["Hero_Melusine"]).components
                if c.name == "Skill Attack Speed Owned")
    cast = EG.parse(paths["Hero_Melusine_Power_Caster_Model"])
    readers = [c for c in cast.components if c.name == "Owner Skill Attack Speed Owned"]
    assert len(readers) == 1 and [r.guid for r in readers[0].refs] == [flag.guid]
