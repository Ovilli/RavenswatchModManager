"""A talent's parts are written (``rsmm.engine.talent_writer``), not copied.

Each written part must be the shipped part the talent builder used to copy
(Beowulf's modifier, Wukong's rarity selector, Aladdin's "during" selector,
Romeo's Love Shield gate, Melusine's flag and caster reader, Carmilla's
multiply), apart from what it points at; and a talent built with every option
must name no other hero. The shipped files are only the reference here.
"""

from __future__ import annotations

import struct

import pytest

from rsmm.engine import cooked, corpus
from rsmm.engine import entity_graph as EG
from rsmm.engine import talent_add_stat as TA
from rsmm.engine import talent_range as TR
from rsmm.engine import talent_status as TS
from rsmm.engine import talent_values as TV
from rsmm.engine.entity_graph_edit import EntityFile

GEN = ".entity.ot.EntitySettingsResource.gen"
_B, _E = cooked.MARK_BEGIN, cooked.MARK_END


def entity(hero: str, name: str | None = None) -> bytes:
    name = name or f"Hero_{hero}"
    for f in corpus.files(f"EntitySettings/Heroes/Hero_{hero}"):
        if f.name == f"{name}{GEN}":
            return f.read_bytes()
    pytest.skip(f"{name} entity not available (no mirror or game install)")


def shape(raw: bytes, name: str, *, targets: bool = False) -> tuple:
    """``name``'s header flags and body with class names for class indices,
    sub-objects inlined and each reference reduced to nothing (or, with
    ``targets``, to the name it points at)."""
    ef = EntityFile(raw, "x")
    c = ef.component(name)
    cls = [k.name for k in ef.cf.classes]

    def walk(b: bytes) -> str:
        out, i = [], 0
        while i < len(b):
            if b[i:i + 4] == _B:
                nm = cls[struct.unpack_from("<I", b, i + 4)[0]]
                out.append("{" + nm)
                i += 8
                if nm == "oCEntityCpntPicker":
                    n = struct.unpack_from("<I", b, i + 16)[0]
                    path = b[i + 20:i + 20 + n].decode("latin-1")
                    out.append(f"<{path.rsplit(chr(92), 1)[-1] if targets else bool(path)}>")
                    i += 20 + n
                elif nm in ("oCEntityCollectorSelectorSettings", "oCCombinerCpntTestSettings"):
                    j = b.find(_E, i)
                    seg = b[i:j]
                    k = next(k for k in range(len(seg) - 3)
                             if k + 4 + 4 * struct.unpack_from("<I", seg, k)[0] == len(seg))
                    ids = struct.unpack_from(f"<{struct.unpack_from('<I', seg, k)[0]}I", seg, k + 4)
                    out.append(seg[:k].hex() + "[" + ",".join(
                        cls[struct.unpack_from("<I", ef.objects[x])[0]]
                        + walk(bytes(ef.objects[x][4:])) for x in ids) + "]")
                    i = j
            elif b[i:i + 4] == _E:
                out.append("}")
                i += 4
            else:
                j = min([x for x in (b.find(_B, i), b.find(_E, i)) if x >= 0] or [len(b)])
                out.append(b[i:j].hex())
                i = j
        return "".join(out)

    p = bytes(ef.objects[c.index - 1])
    head = len(p) - len(c.body)
    flags = struct.unpack_from("<I", p, head - 8 - len(c.group.encode("latin-1")))[0]
    return c.cls, flags, walk(c.body)


def comp(raw: bytes, name: str) -> EG.Component:
    return next(c for c in EG.parse(raw).components if c.name == name)


@pytest.fixture(scope="module")
def wukong() -> bytes:
    return entity("SunWukong")


def test_a_written_rarity_selector_is_the_talents_own():
    """Fiery Dragon's damage selector, rewritten from its own four numbers, is
    byte for byte the shipped one (same controller, same tier order)."""
    raw = entity("SunWukong")
    shipped = "Skill Trait Fire Damage Multiplier Selector"
    tiers = {t: v for t, (_i, v, _ty) in TV.tier_values(raw, shipped).items()}
    out, added = TA.add_stat(raw, talent="Trait Fire", stat="CD reduce trait", values=tiers)
    assert shape(out, added.selector, targets=True) == shape(raw, shipped, targets=True)


def test_a_written_modifier_is_beowulfs():
    beowulf = entity("Beowulf")
    out, added = TA.add_stat(beowulf, talent="Attack Fire Cone", stat="CD reduce trait",
                             values=0.1)
    ours, theirs = shape(out, added.modifier), shape(
        beowulf, "Skill Trait Quest Complete CD Reduction Modifier")
    # Only the amount's fallback differs: 0 here, Beowulf's leftover 0.005 there.
    assert ours[:2] == theirs[:2]
    assert ours[2].replace("0ad7a33b", "00000000") == theirs[2].replace("0ad7a33b", "00000000")


def test_a_written_cooldown_gate_is_romeos(wukong):
    out, _ = TA.add_stat(wukong, talent="Trait Fire", stat="Attack power", values=0.3,
                         after="DEFENSE", seconds=4, cooldown=8)
    tag = next(c.name for c in EG.parse(out).components if c.name.endswith(" Cooldown Tester"))
    romeo = entity("Juliet", "Hero_Romeo_Juliet_Common")
    assert shape(out, tag) == shape(romeo, "Skill Special Invulnerable Active Tester")


def test_written_flag_reader_and_multiply_are_the_shipped_ones():
    mel, caster = entity("Melusine"), entity("Melusine", "Hero_Melusine_Power_Caster_Model")
    hero, flag = TS.add_flag(mel, talent="Attack Speed")
    assert shape(hero, flag) == shape(mel, "Skill Power Chill Available")
    owner = "Heroes\\Hero_Melusine\\Hero_Melusine.entity.ot"
    fg = comp(hero, flag)
    out = TR.reader(caster, factor_guid=fg.guid, factor_label="[Value] Hero_Melusine\\G\\F",
                    owner_resource=owner, name="Owner F")
    assert shape(out, "Owner F") == shape(caster, "Owner Skill Power Chill Extra Radius")
    out = TR.scale_node(out, node="Primary Ability Default Radius", factor="Owner F")
    carmilla = entity("Carmilla")
    ours = shape(out, "Primary Ability Default Radius Scaled")
    theirs = shape(carmilla, "Primary Ability Radius Operation")
    # Carmilla multiplies by a literal 1.0; ours reads the factor there.
    assert ours[:2] == theirs[:2]
    assert ours[2].count("oCEntityCpntPicker<True>") == 2


def test_a_talent_built_with_every_option_names_no_other_hero(wukong):
    out = wukong
    for kw in ({"values": [0.1, 0.2, 0.3, 0.4]},
               {"values": 0.3, "during": "DEFENSE"},
               {"values": 0.3, "after": "DEFENSE", "seconds": 4, "cooldown": 8,
                "next_ability": "ATTACK"}):
        stat = "Attack power" if len(kw) > 1 else "CD reduce trait"
        out, _ = TA.add_stat(out, talent="Trait Fire", stat=stat, **kw)
    mine = {c.guid for c in EG.parse(out).components}
    before = {c.name for c in EG.parse(wukong).components}
    for c in EG.parse(out).components:
        if c.name in before:
            continue
        for r in c.refs:
            assert r.scope in ("Hero_SunWukong", *TA.SHARED_SCOPES), (c.name, r.path)
            assert r.guid in mine or r.scope in TA.SHARED_SCOPES, (c.name, r.path)


def test_a_talent_with_only_whole_numbers_takes_a_decimal_stat():
    """Nothing is copied from the talent any more, so a card whose own numbers
    are all counts (no decimal selector to copy) takes a decimal bonus."""
    for hero in ("SunWukong", "Beowulf", "Aladdin", "Melusine", "Carmilla", "Red"):
        raw = entity(hero)
        g = EG.parse(raw)
        for ctl in (c for c in g.components if c.name.startswith("Skill Controller ")):
            talent = ctl.name[len("Skill Controller "):]
            sels = [c for c in g.components if c.cls.endswith("ValueSelectorSettings")
                    and any(r.guid == ctl.guid for r in c.refs)]
            if sels and all(t[2] != TV.TYPE_F32 for s in sels
                            for t in TV.tier_values(raw, s.name).values()):
                try:
                    out, added = TA.add_stat(raw, talent=talent, stat="Crit chance",
                                             values=[0.1, 0.15, 0.2, 0.25])
                except TA.AddStatError:
                    continue
                got = TV.tier_values(out, added.selector)
                assert pytest.approx(got["Legendary"][1]) == 0.25
                return
    pytest.skip("no talent with only whole-number rarity values on these heroes")


# --- a bonus started by a game event (`on`) ----------------------------------

@pytest.mark.parametrize("on, hero, shipped", [
    ("damage_taken", "Romeo", "Skill Attack Panache Damage Received Event Listener"),
    ("day_start", "SunWukong", "Skill Passive Reveal Day Start Event Listener"),
    ("night_start", "SunWukong", "Skill Passive Reveal Night Start Event Listener"),
])
def test_a_talent_listens_as_the_shipped_talents_do(wukong, on, hero, shipped):
    """The listener is the one a shipped talent has for that event (its event,
    flag filter and header), apart from the mode and what it fires."""
    out, _ = TA.add_stat(wukong, talent="Trait Fire", stat="Attack power", values=0.3,
                         on=on, seconds=4)
    ours = next(c.name for c in EG.parse(out).components
                if c.cls == "oCGameEventListenerEntityCpntSettings" and "Added" in c.name)
    theirs = entity(hero)
    a, b = shape(out, ours), shape(theirs, shipped)
    assert (a[0], a[1], a[2][14:]) == (b[0], b[1], b[2][14:])


def test_an_on_bonus_is_held_by_the_owned_state_and_restarts_the_window(wukong):
    out, _ = TA.add_stat(wukong, talent="Trait Fire", stat="Attack power", values=0.3,
                         on="damage_taken", seconds=4, cooldown=8, next_ability="ATTACK")
    g = EG.parse(out)
    lis = next(c for c in g.components
               if c.cls == "oCGameEventListenerEntityCpntSettings" and "Added" in c.name)
    owned = comp(out, "Skill Trait Fire")
    assert any(r.guid == lis.guid for r in owned.refs)
    assert [r.path.rsplit("\\", 1)[-1] for r in lis.refs] == [
        "Skill Trait Fire Added 15a486c4 On damage_taken Next ATTACK Cooldown Tester"]


@pytest.mark.parametrize("kw, msg", [
    ({"on": "damage_taken"}, "seconds"),
    ({"on": "nope", "seconds": 3}, "one of"),
    ({"on": "damage_taken", "after": "DEFENSE", "seconds": 3}, "not several"),
])
def test_a_bad_on_is_refused(wukong, kw, msg):
    with pytest.raises(TA.AddStatError, match=msg):
        TA.add_stat(wukong, talent="Trait Fire", stat="Attack power", values=0.3, **kw)


def test_the_editor_offers_and_builds_every_trigger():
    entity("SunWukong")
    from rsmm.cli.editor import content as C
    info = next(c for c in C.talent_cards("SunWukong") if c["source"] == "Trait Fire")["addStat"]
    assert set(info["on"]) == set(TA.TRIGGERS)
    for on in TA.TRIGGERS:
        req = {"rebuild": ["Trait Fire"], "addStats": [
            {"talent": "Trait Fire", "stat": "Attack power", "values": [0.1, 0.2, 0.3, 0.4],
             "on": on, "seconds": 4}]}
        assert all(r["ok"] for r in _editor_check("SunWukong", req)), on


# --- what the editor offers builds (the talent kind, as `check` runs it) -------

def _editor_check(hero: str, req: dict) -> list[dict]:
    from rsmm.cli.editor import content as C
    return C.check(C.talent_defs({"hero": hero, "prefix": "t", **req}))


def test_a_rebuilt_card_with_no_slot_to_copy_takes_a_stat():
    """Kintaro's Attack Bite: once rebuilt its card has no slot, and the one
    copied from another card held a plain number with nothing to re-point."""
    entity("Kintaro")
    req = {"rebuild": ["Attack Bite"], "addStats": [
        {"talent": "Attack Bite", "stat": "Attack power", "values": [0.1, 0.2, 0.3, 0.4]}]}
    assert all(r["ok"] for r in _editor_check("Kintaro", req)), _editor_check("Kintaro", req)


def test_a_file_name_picks_that_file_not_every_file_it_is_part_of():
    """`Hero_SunWukong_Beads` is also part of `Hero_SunWukong_Beads_Explosion`."""
    entity("SunWukong")
    req = {"rebuild": ["Special Beads Increase"], "onHit": [
        {"talent": "Special Beads Increase", "damage": "Attack Damage", "status": "Ignite",
         "file": "Hero_SunWukong_Beads"}]}
    assert all(r["ok"] for r in _editor_check("SunWukong", req))


def test_an_entity_that_names_nothing_of_its_own_is_scaled():
    """Snow Queen's FROST references nothing of its own, so its scope comes
    from its file name."""
    entity("Snow_Queen")
    from rsmm.cli.editor import content as C
    hit = next((s for s in C.scalable("Snow_Queen") if s["node"] == "Radius Value"), None)
    if hit is None:
        pytest.skip("Snow Queen's FROST radius is not offered")
    t = next(c["source"] for c in C.talent_cards("Snow_Queen") if c["addStat"]["ok"])
    req = {"rebuild": [t], "scale": [{"talent": t, "node": hit["node"], "file": hit["file"],
                                      "values": [0.1, 0.2, 0.3, 0.4]}]}
    assert all(r["ok"] for r in _editor_check("Snow_Queen", req))


def test_hits_no_reader_could_switch_are_not_offered():
    """Merlin's meteor reads the hero but its start-up state switches no reader
    on, so a status on its hit could never tell the talent is owned."""
    entity("Merlin")
    from rsmm.cli.editor import content as C
    files = {d["file"] for d in C.hit_damages("Merlin")["damages"]}
    assert "Hero_Merlin_DarkMeteor" not in files


@pytest.mark.slow
@pytest.mark.parametrize("hero", ["Aladdin", "Beowulf", "Carmilla", "Geppetto", "Juliet",
                                  "Kintaro", "Melusine", "Merlin", "Piper", "Red", "Romeo",
                                  "Snow_Queen", "SunWukong"])
def test_every_option_the_editor_offers_builds(hero):
    """2026-10-23: 65 offers failed to build (rebuild clones, a copied card slot,
    file names matched as parts, entities with no scope, unreachable hits)."""
    from rsmm.cli.editor import content as C
    if not corpus.rels("EntitySettings/Heroes/", GEN):
        pytest.skip("hero entities not available (no mirror or game install)")
    cards = [c for c in C.talent_cards(hero) if c["addStat"]["ok"] and c["addStat"].get("rebuild")]
    if not cards:
        pytest.skip(f"{hero} has no rebuildable card")
    t, info = cards[0]["source"], cards[0]["addStat"]
    reqs = [{"scale": [{"talent": t, "node": s["node"], "file": s["file"],
                        "values": [0.1, 0.2, 0.3, 0.4]}]} for s in C.scalable(hero)]
    hits = C.hit_damages(hero)
    reqs += [{"onHit": [{"talent": t, "damage": d["damage"], "status": "Ignite",
                         "file": d["file"]}]} for d in hits["damages"]]
    if hits["damages"]:
        d = hits["damages"][0]
        reqs += [{"onHit": [{"talent": t, "damage": d["damage"], "status": st, "file": d["file"]}]}
                 for st in hits["statuses"]]
    stat = {"talent": t, "stat": "Attack power", "values": [0.1, 0.2, 0.3, 0.4]}
    reqs += [{"addStats": [{**stat, "during": a}]} for a in info["during"]]
    reqs += [{"addStats": [{**stat, "after": a, "seconds": 3, "cooldown": 6}]}
             for a in info["after"]]
    reqs += [{"addStats": [{**stat, "on": t, "seconds": 3, "cooldown": 6}]} for t in info["on"]]
    failed = [(req, r["error"]) for req in reqs
              for r in _editor_check(hero, {"rebuild": [t], **req}) if not r["ok"]]
    assert not failed, failed[:5]
