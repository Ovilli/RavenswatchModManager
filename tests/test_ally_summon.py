"""An enemy summoned as an ally (engine/ally_summon.py): Blood Wolf's wolf."""

from __future__ import annotations

import struct

import pytest

from rsmm.engine import corpus

_TIMBER = "Enemies\\Wolves\\Standard_Wolf_Timber.entity.ot"
needs_corpus = pytest.mark.skipif(
    corpus.read("EntitySettings/Enemies/Wolves/Wolves_Model.entity.ot"
                ".EntitySettingsResource.gen") is None, reason="no enemy corpus")


def _filters(raw: bytes) -> list[tuple[int, tuple, tuple]]:
    """(layer, list A, list B) of every attack filter in ``raw``."""
    from rsmm.engine import cooked
    cf = cooked.parse(raw)
    names = [c.name for c in cf.classes]
    tester = names.index("oCEntityGpnFlagMaskTesterSettings")
    tag = cooked.MARK_BEGIN + struct.pack("<I", names.index("oCGpnFilter"))
    out = []
    for sec in cf.sections:
        p = sec.payload
        if len(p) < 4 or struct.unpack_from("<I", p, 0)[0] != tester:
            continue
        o = p.find(tag) + len(tag)
        layer, n = struct.unpack_from("<II", p, o)
        a = struct.unpack_from(f"<{n}I", p, o + 8)
        m = struct.unpack_from("<I", p, o + 8 + 4 * n)[0]
        out.append((layer, a, struct.unpack_from(f"<{m}I", p, o + 12 + 4 * n)))
    return out


@needs_corpus
def test_a_summoned_wolf_fights_for_the_heroes():
    """Its model layer moves to Ally_Model and every attack filter is
    mirrored: a wolf bite hits ANY[Ally, Neutral]; the copy's hits ANY[Neutral,
    Enemy], the monkey clone's pattern. Identities are its own, under one
    mapping, so the variant still overrides the copied model's parts."""
    from rsmm.engine import ally_summon as AS
    from rsmm.engine import entity_components as EC
    from rsmm.engine import prop_cook as PC
    model, variant = "Heroes\\Hero_Red\\Hero_T_Summon1_Model.entity.ot", \
        "Heroes\\Hero_Red\\Hero_T_Summon1.entity.ot"
    out = AS.build(_TIMBER, model, variant, "t")
    assert EC.parents(out[model]) == [AS.ALLY_MODEL]
    assert EC.parents(out[variant]) == [model]
    filters = _filters(out[model])
    assert filters
    for layer, a, b in filters:
        for lst in (a, b):
            assert len(lst) < 3 or lst[AS.ALLY] in (0, 2), "an attack still targets heroes"
        assert layer != AS.HERO_LAYER
    assert any(len(a) > 2 and a[AS.ENEMY] == 1 for _l, a, _b in filters)
    shipped = corpus.read("EntitySettings/Enemies/Wolves/Wolves_Model.entity.ot"
                          ".EntitySettingsResource.gen")
    assert not set(PC.component_guids(out[model])) & set(PC.component_guids(shipped))


@needs_corpus
def test_a_hero_kit_summon_block_builds(tmp_path):
    from rsmm.sdk.content import ContentDef
    from rsmm.sdk.kinds import heros
    files = heros.emit("m", ContentDef(kind="hero", id="Caller", fields={
        "base": "Red", "kit": {"special": {"steps": [
            {"summon": "Enemies/Wolves/Standard_Wolf_Timber"}]}}}), tmp_path)
    names = {p.name for p in files}
    assert "Hero_Caller_Summon1.entity.ot.EntitySettingsResource.gen" in names
    assert "Hero_Caller_Summon1_Model.entity.ot.EntitySettingsResource.gen" in names


@needs_corpus
def test_a_kit_pets_block_follows_piper_and_takes_the_trait(tmp_path):
    """Pam's Blood Wolf design: one dire wolf on Hero_Pet_Model spawns at start,
    the trait (no cooldown) sends the attack order, leaving combat recalls."""
    from rsmm.engine import ally_summon as AS
    from rsmm.engine import entity_components as EC
    from rsmm.engine import entity_fields as EF
    from rsmm.engine.entity_graph_edit import EntityFile
    from rsmm.sdk.content import ContentDef
    from rsmm.sdk.kinds import heros
    files = heros.emit("m", ContentDef(kind="hero", id="Packer", fields={
        "base": "Red", "kit": {"pets": {"entity": "Enemies/Wolves/Standard_Wolf_Dire"}}}),
        tmp_path)
    by = {p.name: p for p in files}
    model = by["Hero_Packer_Summon1_Model.entity.ot.EntitySettingsResource.gen"].read_bytes()
    assert EC.parents(model) == [AS.PET_MODEL]
    # Tagged as Piper's rats, the tag the alive count's listener collects.
    flag = next(c for c in EntityFile(model, "m").graph().components
                if c.name == "Alive Additional Flags Value")
    assert [f.text for f in EF.fields(flag) if f.name == "value"] == ["text 'Rat_Pet'"]
    hero = EntityFile(by["Hero_Packer.entity.ot.EntitySettingsResource.gen"].read_bytes(), "h")

    def refs(part, fld):
        f = next(x for x in EF.fields(hero.component(part)) if x.name == fld)
        return [i.text.strip().rsplit("\\", 1)[-1] for i in f.items]
    assert refs("State Trait Ability", "activates") == ["Kit Pet Centre",
                                                        "Kit Pet Attack Order",
                                                        "Kit Pet Order Timer",
                                                        "Kit Pet Recount"]
    # The state ends itself again, or the trait stays in use (locked).
    timer = {f.name: f.text for f in EF.fields(hero.component("Kit Pet Order Timer"))}
    assert timer["on_end"].strip().endswith("\\Kit Pet Order End")
    assert refs("Kit Pet Order End", "deactivates?") == ["State Trait Ability"]
    # Piper's "alive / max" counter over the icon: alive through a whole-number
    # copy of her pet listener's count (the listener itself reads a position).
    alive = {f.name: f.text for f in EF.fields(hero.component("Kit Pet HUD Alive Label"))}
    assert alive["value_23"].startswith("int") and alive["value_23"].endswith("Kit Pet Alive Count")
    most = {f.name: f.text for f in EF.fields(hero.component("Kit Pet HUD Max Label"))}
    assert most["value_23"].endswith("Kit Pet Count Total")
    assert "Kit Pet Alive Listener" in refs("Kit Pet Spawn", "activates")
    # In a run only: the select screen's preview copy would drop it.
    assert "Kit Pet In Run Tester" in refs("Child Event Initialize", "activates")
    assert "Kit Pet Spread Pos" in refs("Kit Pet Spawn", "activates")
    tester = {f.name: f.text for f in EF.fields(hero.component("Kit Pet In Run Tester"))}
    assert tester["on_true"].strip().endswith("\\Kit Pet Start")
    # A tester tests once; at Initialize the hero is not in the world yet, so
    # a timer waits before the spawn, and the spawn switches the spawner on.
    assert "Kit Pet Start Timer" in refs("Kit Pet Start", "activates")
    timer = {f.name: f.text for f in EF.fields(hero.component("Kit Pet Start Timer"))}
    assert timer["on_end"].strip().endswith("\\Kit Pet Spawn")
    # Piper's orders reach what HER pet spawners spawned; ours must name ours.
    raw = by["Hero_Packer.entity.ot.EntitySettingsResource.gen"].read_bytes()
    assert b"Trait Ability Pet Spawner" not in raw
    assert b"Skill Defense Spawn Pets Spawner" not in raw
    # The spread runs the spawner per spot; switching it on too made two pets.
    assert "Kit Pet Spread Pos" in refs("Kit Pet Spawn", "activates")
    assert "Kit Pet Spawner" not in refs("Kit Pet Spawn", "activates")
    assert "Kit Pet Recall Order" in refs("Child State Is In Combat", "disables_while_active?")
    assert next(f.text for f in EF.fields(hero.component("Trait Ability Controller"))
                if f.name == "value_4") == "f32 0"


@needs_corpus
def test_a_talent_gated_pets_block_waits_for_the_talent(tmp_path):
    """Pam's starter talent: the special summons until the talent is picked;
    then the wolves follow and the special orders them instead."""
    from rsmm.engine import entity_fields as EF
    from rsmm.engine.entity_graph_edit import EntityFile
    from rsmm.sdk.content import ContentDef
    from rsmm.sdk.kinds import heros
    when = "Event Wolf Secondary Ability Active"
    wolf = "Enemies/Wolves/Standard_Wolf_Dire"
    files = heros.emit("m", ContentDef(kind="hero", id="Packer", fields={"base": "Red", "kit": {
        "special": {"replace": True, "when": when, "steps": [{"summon": wolf}]},
        "pets": {"entity": wolf, "button": "special", "when": when,
                 "talent": "Skill Secondary Ignite"}}}), tmp_path)
    by = {p.name: p for p in files}
    hero = EntityFile(by["Hero_Packer.entity.ot.EntitySettingsResource.gen"].read_bytes(), "h")

    def refs(part, fld):
        f = next(x for x in EF.fields(hero.component(part)) if x.name == fld)
        return [i.text.strip().rsplit("\\", 1)[-1] for i in f.items]
    pressed = refs(when, "activates")
    assert "Kit Special Shot 1" in pressed and "Kit Pet Attack Order" in pressed
    assert "Kit Special Shot 1" in refs("Skill Secondary Ignite", "disables_while_active?")
    assert {"Kit Pet Spread Pos", "Kit Pet Alive Listener"} <= set(
        refs("Skill Secondary Ignite", "activates"))
    assert "Kit Pet Spread Pos" not in refs("Child Event Initialize", "activates")
    # The counter sits over the special, the button that orders them.
    layout = next(f.text for f in EF.fields(hero.component("Kit Pet HUD")) if f.name == "obj_6")
    assert "Secondary_Layout_Top" in layout


@needs_corpus
def test_a_summon_can_die_on_its_own_and_burst(tmp_path):
    """Pam's special: the wolf lives a while and, however it dies, leaves a
    bomb where it stood."""
    from rsmm.engine import entity_fields as EF
    from rsmm.engine import entity_graph as EG
    from rsmm.sdk.content import ContentDef
    from rsmm.sdk.kinds import heros
    bomb = "Heroes/Hero_Red/Hero_Red_Bomb"
    files = heros.emit("m", ContentDef(kind="hero", id="Packer", fields={"base": "Red", "kit": {
        "special": {"replace": True, "steps": [{"summon": "Enemies/Wolves/Standard_Wolf_Dire",
                                                "lifetime": 8, "burst": bomb}]}}}), tmp_path)
    by = {p.name: p for p in files}
    model = EG.parse(by["Hero_Packer_Summon1_Model.entity.ot.EntitySettingsResource.gen"]
                     .read_bytes())
    parts = {c.name: {f.name: f.text for f in EF.fields(c)} for c in model.components}
    assert parts["Kit Burst Spawner"]["template"].endswith("Hero_Red_Bomb.entity.ot'")
    assert parts["Child Behaviour Dying"]["activates"].endswith("Kit Burst Spawner")
    assert parts["Kit Life Timer"]["duration"] == "f32 8"
    assert parts["Kit Life Timer"]["on_end"].endswith("Bhv Dying\\Behaviour Dying")
    assert parts["Child Event Initialize"]["activates"].endswith("Kit Life Timer")


@needs_corpus
def test_an_ally_copy_searches_no_hero_layer(tmp_path):
    """Every filter AND every traverser's query layer is mirrored, the wolf's
    in-range checks and the inherited wandering search included: one left on
    the hero layer and the wolf stood next to enemies seeing only heroes."""
    import struct

    from rsmm.engine import ally_summon as AS
    from rsmm.sdk.content import ContentDef
    from rsmm.sdk.kinds import heros
    files = heros.emit("m", ContentDef(kind="hero", id="Packer", fields={"base": "Red", "kit": {
        "special": {"replace": True, "steps": [{"summon": "Enemies/Wolves/Standard_Wolf_Dire"}]},
        "pets": {"entity": "Enemies/Wolves/Standard_Wolf_Dire"}}}), tmp_path)
    from rsmm.engine import cooked
    from rsmm.engine import entity_graph as EG
    hero = struct.pack("<I", AS.HERO_LAYER)
    models = [p for p in files if "_Summon" in p.name and "_Model." in p.name]
    assert len(models) == 2
    searches = ("oCEntityGpnFlagMaskTesterSettings", "oCEntityCpntGpnTraverserSettings")
    for p in models:
        cf = cooked.parse(p.read_bytes())
        names = [c.name for c in cf.classes]
        ids = {names.index(n) for n in searches if n in names}
        for sec in cf.sections:
            if len(sec.payload) >= 4 and struct.unpack_from("<I", sec.payload, 0)[0] in ids:
                assert hero not in sec.payload, p.name
    # The summon (not the pet) stands ON the hero layer, as Sun Wukong's clone
    # does, so enemies attack it and it can die to burst.
    summon = next(p for p in models
                  if any(c.name == "Kit GPN Hero" for c in EG.parse(p.read_bytes()).components))
    assert summon


@needs_corpus
def test_a_shipped_pet_is_copied_with_its_reads_aimed_at_the_hero(tmp_path):
    """Piper's rat as the pet: copied into the hero's folder, every read of
    Piper aimed at this hero (her own values as copies here, a shared part's
    link kept), its attack point the hero's position."""
    from rsmm.engine import entity_fields as EF
    from rsmm.engine import entity_graph as EG
    from rsmm.sdk.content import ContentDef
    from rsmm.sdk.kinds import heros
    files = heros.emit("m", ContentDef(kind="hero", id="Packer", fields={
        "base": "Red", "kit": {"pets": {"entity": "Heroes/Hero_Piper/Hero_Piper_Rat_Pet"}}}),
        tmp_path)
    by = {p.name: p for p in files}
    pet = EG.parse(by["Hero_Packer_Pet.entity.ot.EntitySettingsResource.gen"].read_bytes())
    reads = {c.name: {f.name: f.text for f in EF.fields(c)} for c in pet.components
             if c.cls == "oCEntityCpntGetValueSettings"}
    for name, f in reads.items():
        assert "Hero_Piper.entity.ot" not in f["template"], name
    assert reads["Owner Max Attacks Get Value"]["value"].endswith("Kit Pet Read Max Attacks")
    assert reads["Owner AP Get Value"]["value"].endswith("Character_Common\\Base\\AP Value")
    assert reads["Attack Seed Position Get Value"]["value"].endswith("Kit Pet Centre")


@needs_corpus
def test_no_kit_part_is_an_override(tmp_path):
    """A copied override replaces its ancestor's part instead of adding one:
    every Kit Pet state copied from Scarlet's "Event Initialize Starting
    Modifiers" was missing from the live hero, so no pet ever spawned."""
    from rsmm.engine import entity_graph as EG
    from rsmm.sdk.content import ContentDef
    from rsmm.sdk.kinds import heros
    files = heros.emit("m", ContentDef(kind="hero", id="Packer", fields={"base": "Red", "kit": {
        "pets": {"entity": "Enemies/Wolves/Standard_Wolf_Dire"}}}), tmp_path)
    by = {p.name: p for p in files}
    hero = EG.parse(by["Hero_Packer.entity.ot.EntitySettingsResource.gen"].read_bytes())
    kit = [c for c in hero.components if c.name.startswith("Kit ")]
    assert kit
    assert [c.name for c in kit if c.override is not None] == []


def test_clone_refuses_an_override():
    import pytest as _pt

    from rsmm.engine import ability_edit as AE
    from rsmm.engine import corpus
    raw = corpus.read("EntitySettings/Heroes/Hero_Red/"
                      "Hero_Red.entity.ot.EntitySettingsResource.gen")
    if raw is None:
        _pt.skip("shipped heroes not available")
    with _pt.raises(AE.AbilityEditError, match="override"):
        AE.apply({"Hero_Red": raw}, [{"clone": ["Event Initialize Starting Modifiers"],
                                      "rename": {"Event Initialize Starting Modifiers": "X"}}],
                 main="Hero_Red", seed="t")


@needs_corpus
def test_a_bomber_pet_spawns_per_press_and_fights_on_its_own(tmp_path):
    """Pam's bomber wolf: one pet per press of the trait (its own cooldown),
    no counter, the attack order on entering combat, a burst when it dies, and
    standing where enemies can hit it."""
    from rsmm.engine import entity_fields as EF
    from rsmm.engine import entity_graph as EG
    from rsmm.engine.entity_graph_edit import EntityFile
    from rsmm.sdk.content import ContentDef
    from rsmm.sdk.kinds import heros
    files = heros.emit("m", ContentDef(kind="hero", id="Packer", fields={"base": "Red", "kit": {
        "pets": {"entity": "Enemies/Wolves/Standard_Wolf_Dire", "button": "trait",
                 "spawn": "button", "counter": "none", "aggro": True,
                 "burst": "Heroes/Hero_Red/Hero_Red_Bomb", "lifetime": 20}}}), tmp_path)
    by = {p.name: p for p in files}
    hero = EntityFile(by["Hero_Packer.entity.ot.EntitySettingsResource.gen"].read_bytes(), "h")

    def refs(part, fld):
        f = next(x for x in EF.fields(hero.component(part)) if x.name == fld)
        return [i.text.strip().rsplit("\\", 1)[-1] for i in f.items]
    assert "Kit Pet Spread Pos" in refs("State Trait Ability", "activates")
    assert "Kit Pet Attack Order" in refs("Child State Is In Combat", "activates")
    names = {c.name for c in hero.graph().components}
    assert "Kit Pet HUD" not in names and "Kit Pet In Run Tester" not in names
    cd = next(f.text for f in EF.fields(hero.component("Trait Ability Controller"))
              if f.name == "value_4")
    assert "<-" in cd                       # the base's own cooldown, not 0
    model = EG.parse(by["Hero_Packer_Summon1_Model.entity.ot.EntitySettingsResource.gen"]
                     .read_bytes())
    kit = {c.name for c in model.components}
    assert {"Kit Burst Spawner", "Kit GPN Hero"} <= kit
    # One burst per life: dying stops its timers once (never "while active":
    # that switched them back on after dying and the wolf burst forever).
    dying = next(c for c in model.components if c.name == "Child Behaviour Dying")
    fields = {f.name: f.text for f in EF.fields(dying)}
    assert "Kit Life Timer" in fields["deactivates?"]
    assert "Kit Life Timer" not in fields["disables_while_active?"]
    # Its "Targetable" flag (what enemies' target searches require) reads
    # Character_Common's "Is Alive Condition", not Sun Wukong's clone's hero
    # condition (Behaviour Default, which an NPC never enters: no enemy ever
    # aggroed the wolf, playtest 2026-11-05).
    raw = by["Hero_Packer_Summon1_Model.entity.ot.EntitySettingsResource.gen"].read_bytes()
    assert b"Hero_SunWukong_Ultimate_1_AI_Clone\\Base\\Is Targetable" not in raw
    assert b"[Cpnt Value Tester] Character_Common\\Base\\Is Alive Condition" in raw


@needs_corpus
def test_a_summons_bite_is_tuned_for_a_moving_target(tmp_path):
    """Pam 2026-11-05: the bite's cone twice as wide and twice as long (not
    the distance it bites from), its clips 35% faster, no rooted on what it bites,
    a 0.5 s retry; and no summon plays the enemy wind-up glow."""
    import struct

    from rsmm.engine import entity_fields as EF
    from rsmm.engine.entity_graph_edit import _B, EntityEditError, EntityFile
    from rsmm.sdk.content import ContentDef
    from rsmm.sdk.kinds import heros
    files = heros.emit("m", ContentDef(kind="hero", id="Biter", fields={"base": "Red", "kit": {
        "pets": {"entity": "Enemies/Wolves/Standard_Wolf_Dire", "attack": "Bite",
                 "attack_area": 2.0, "attack_speed": 1.35, "attack_debuffs": False,
                 "attack_cooldown": 0.5, "attack_reach": 2.0, "attack_range": 3.0,
                 "attack_targets": 0}}}),
        tmp_path)
    by = {p.name: p for p in files}
    ef = EntityFile(by["Hero_Biter_Summon1_Model.entity.ot.EntitySettingsResource.gen"]
                    .read_bytes(), "m")

    def val(part, fld="value"):
        return next(f.text for f in EF.fields(ef.component(part)) if f.name == fld)
    # Reach and width apart: radius x2 (reach), cone angle x2 (area).
    assert val("Attack Bite Attack Traverser Radius").endswith(" 9.2")
    cone = next(x for x in ef.subtree({ef.component("Attack Bite Traverser").index - 1})
                if ef._class(x) == "oCEntityGpnInConeTraverserSettings")
    from rsmm.engine.hero_kit import _cone_angle
    at = _cone_angle(ef.objects[cone], [x.name for x in ef.cf.classes])
    assert abs(struct.unpack_from("<f", ef.objects[cone], at)[0] - 2 * 0.5236) < 1e-3
    assert val("Attack Bite Cooldown", "duration").startswith("f32 0.5")
    assert "f32 0.5" in val("Attack Bite Cooldown Value Selector", "entries")
    assert "f32 2" not in val("Attack Bite Cooldown Value Selector", "entries")
    assert val("Fighting All Attack Cooldown", "duration").startswith("f32 0.5")
    # Every enemy in the cone, not the best-scored one.
    assert val("Attack Bite Gpn Target Best One Computer ", "value_5") == "int 0"
    # It commits to a bite from 3 m (a dire wolf: 4.5), aiming for 2 m.
    var = EntityFile(by["Hero_Biter_Summon1.entity.ot.EntitySettingsResource.gen"]
                     .read_bytes(), "v")
    vv = {c.name: c for c in var.graph().components}
    assert next(f.text for f in EF.fields(vv["Fighting Seek Max Attack Distance"])
                if f.name == "value").startswith("f32 3")
    assert next(f.text for f in EF.fields(vv["Fighting Seek Best Attack Distance"])
                if f.name == "value").startswith("f32 2")
    assert val("Attack Bite No Root Motion Traverser Radius Value").endswith(" 4.2")
    assert val("Attack Bite In Anim", "value_9").startswith("f32 1.35")
    dmg = ef.component("Attack Bite Damage")
    f = next(x for x in EF.fields(dmg) if x.name == "bytes_36")
    (oid,) = struct.unpack_from("<I", dmg.body, f.offset + 4)
    names = [x.name for x in ef.cf.classes]
    p = ef.objects[oid]
    u = p.find(_B + struct.pack("<I", names.index("oCEntityValueUnion")))
    assert struct.unpack_from("<I", p, u + 8)[0] == 2 and p[u + 16] == 0
    # The warm-up bloc now starts the inert timer, not the glow.
    warm = ef.component("Attack Bite Warmup FX").guid
    noop = ef.component("Kit No Warning").guid
    targets = []
    for c in ef.graph().components:
        if c.cls != "oCEntityCpntAnimaticSettings":
            continue
        i = 0
        while True:
            try:
                _c, sub = ef._cinebloc(c.name, i)
            except EntityEditError:
                break
            q = ef.objects[sub]
            at = q.find(_B + struct.pack("<I", names.index("oCEntityCpntPicker")))
            if at >= 0:
                targets.append(bytes(q[at + 8:at + 24]))
            i += 1
    assert warm not in targets and noop in targets


@needs_corpus
def test_talents_raise_the_pet_count_and_the_card_shows_it(tmp_path):
    """A talent adds pets per press (count_talents, Geppetto's selector + Piper's
    add); the spread and the special's card ({0}) read the running total."""
    from rsmm.engine import entity_fields as EF
    from rsmm.engine.entity_graph_edit import EntityFile
    from rsmm.sdk.content import ContentDef
    from rsmm.sdk.kinds import heros
    files = heros.emit("m", ContentDef(kind="hero", id="Counter", fields={"base": "Red", "kit": {
        "pets": {"entity": "Enemies/Wolves/Standard_Wolf_Dire", "button": "special",
                 "spawn": "button", "counter": "none", "count": 1,
                 "count_talents": {"Skill Secondary Quick Bombs": 1,
                                   "Skill Secondary Ignite": 2},
                 "count_card": "Wolf Secondary Ability Desc Format"}}}), tmp_path)
    by = {p.name: p for p in files}
    hero = EntityFile(by["Hero_Counter.entity.ot.EntitySettingsResource.gen"].read_bytes(), "h")

    def text(part, fld):
        return next(str(f.text) for f in EF.fields(hero.component(part)) if f.name == fld)
    assert "Skill Secondary Quick Bombs" in text("Kit Pet Talent Count 1", "entries")
    assert "int 1" in text("Kit Pet Talent Count 1", "entries")
    assert "int 2" in text("Kit Pet Talent Count 2", "entries")
    assert "Kit Pet Count Add 1" in text("Kit Pet Count Add 2", "b")
    assert "Kit Pet Count Add 2" in text("Kit Pet Count Total", "a")
    assert "Kit Pet Count Total" in text("Kit Pet Spread Pos", "value_2")
    assert "Kit Pet Count Total" in text("Wolf Secondary Ability Desc Format", "obj_4")


@needs_corpus
def test_a_summons_look_replaces_the_body_its_variant_draws():
    """`look` swaps the body the leaf sets (a dire wolf's own, not the Alpha
    wolf its model names) and refuses a table with nothing to change."""
    from rsmm.engine import entity_check as CK
    from rsmm.engine.hero_kit import KitError, _Ctx, _summon_for
    from rsmm.sdk.kinds.heros import _body_refs
    fbx, mat = _body_refs(CK._corpus_reader("Enemies\\Wolves\\Standard_Wolf_Dire.entity.ot"))
    assert fbx.endswith("Wolf_Dire_Timber_GEO.fbx") and mat.endswith("M_WolfDire.mat.ot")
    ctx = _Ctx(hid="Looker", folder="Hero_Red")
    with pytest.raises(KitError, match="look"):
        _summon_for("Enemies/Wolves/Standard_Wolf_Dire", ctx, "pets", look={"colour": "red"})
    _summon_for("Enemies/Wolves/Standard_Wolf_Dire", ctx, "pets", look={"model": "a.glb"})
    assert all(c.look == {"model": "a.glb"} for c in ctx.copies)
