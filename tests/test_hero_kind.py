"""`hero` kind: a clone is a new herodef + its own resource cache.

The hero-select roster is every registered oCDtHeroDefinition (FUN_140209b00
copies Registry_EnumInstances unfiltered), so these two files are the whole
contract — the same self-registration the enemy clone proved in game.
"""

from __future__ import annotations

import re

import pytest

from rsmm.engine import corpus
from rsmm.engine import enemy_pools as EP
from rsmm.engine import rsc_cache as RC
from rsmm.sdk.content import ContentDef, ContentError
from rsmm.sdk.kinds import heros

needs_corpus = pytest.mark.skipif(not heros.shipped_heroes(), reason="no hero corpus")


def _emit(tmp_path, id="Zz_Piper_Clone", **fields):
    return heros.emit("m", ContentDef(kind="hero", id=id, fields={"base": "Piper", **fields}),
                      tmp_path)


@needs_corpus
def test_clone_is_the_base_bytes_under_a_new_name_with_its_own_cache(tmp_path):
    gen, cache = _emit(tmp_path)
    assert gen.name == "Zz_Piper_Clone.herodef.ot.DtHeroDefinition.gen"
    from rsmm.engine import herodefs
    assert gen.read_bytes() == EP.corpus_read(herodefs.rel("Piper"))
    lines = RC.parse(cache.read_bytes())
    assert lines == sorted(lines)
    assert "Definitions|Heroes\\Zz_Piper_Clone.herodef.ot|oCDtHeroDefinition" in lines
    assert not any("Heroes\\Piper.herodef.ot" in ln for ln in lines)


@needs_corpus
@pytest.mark.parametrize("fields,msg", [
    ({"base": "Merlin"}, "paid DLC hero"),
    ({"base": "Merlin", "dlc_owner": True}, "unsupported field"),
    ({"base": "Nobody"}, "no shipped hero"),
    ({"display_name": "X"}, "unsupported field"),
])
def test_bad_clones_are_refused(tmp_path, fields, msg):
    with pytest.raises(ContentError, match=msg):
        _emit(tmp_path, **fields)


@needs_corpus
def test_a_paid_hero_is_never_a_base(tmp_path):
    """Merlin is paid DLC: a clone would play for anyone who installs the mod, so
    it is refused with no opt-out. Carmilla is not paid and clones normally."""
    with pytest.raises(ContentError, match="paid DLC hero"):
        _emit(tmp_path, base="Merlin")
    _emit(tmp_path, id="Zz_Carmilla_Clone", base="Carmilla")


def test_borrowing_a_paid_heros_art_is_refused():
    from rsmm.sdk.kinds import heros as H
    for ref in ("Heroes\\Hero_Merlin\\Merlin.entity.ot", "3D\\Characters\\Heroes\\Merlin\\M.mat"):
        with pytest.raises(ContentError, match="paid DLC hero"):
            H._refuse_paid("X", [ref])
    H._refuse_paid("X", ["Heroes\\Hero_Piper\\Piper.entity.ot", "Merlinesque\\x.ot"])


@needs_corpus
def test_a_shipped_id_is_refused(tmp_path):
    with pytest.raises(ContentError, match="collides"):
        _emit(tmp_path, id="Juliet")


@needs_corpus
def test_apply_appends_a_new_hero_to_the_versiondef_hero_vector():
    """A herodef registered only in UsedRscList never loads (12 live in game,
    2026-09-24): heroes load through the versiondef's hero vector."""
    from rsmm.cli import apply_mods as A
    from rsmm.engine import cooked

    rel = "Heroes\\Zz_Piper_Clone.herodef.ot"
    assert A._hero_versiondef_path(
        "Definitions/Heroes/Zz_Piper_Clone.herodef.ot.DtHeroDefinition.gen") == rel
    assert A._hero_versiondef_path("Definitions/Heroes/Piper.herodef.UsedRscCache.ot") is None
    vd = EP.corpus_read(f"Definitions/Versions/{A.VERSIONDEF_GEN_LEAF}")
    co, _, cnt = A._find_hero_vector(vd)
    assert cnt == 13                                    # Kintaro joined in Update 6
    out = A._patch_versiondef_heroes(vd, [rel])
    co2, _, cnt2 = A._find_hero_vector(out)
    entries = [e[2] for e in A._mo_vector_entries(out, co2, cnt2)]
    assert cnt2 == cnt + 1 and entries[-1] == rel and entries[:cnt] == [
        e[2] for e in A._mo_vector_entries(vd, co, cnt)]
    assert A._patch_versiondef_heroes(out, [rel]) == out      # idempotent
    cooked.parse(out)


def _install():
    from rsmm.cli.apply_mods import find_game_dir
    try:
        return find_game_dir()
    except Exception:  # noqa: BLE001 — no install reachable
        return None


needs_install = pytest.mark.skipif(_install() is None, reason="no game install")


@needs_corpus
@needs_install
def test_a_named_hero_points_its_herodef_at_its_own_text_keys(tmp_path):
    from rsmm.engine import entity_strings as ES
    files = _emit(tmp_path, id="Nyx", name="Nyx", description="Test.")
    names = {p.name for p in files}
    assert "Nyx.herodef.ot.DtHeroDefinition.gen" in names
    assert any(n.endswith(".LangEN") for n in names)          # values, or the game crashes
    gen = next(p for p in files if p.name.startswith("Nyx.herodef"))
    ts = [t for _s, _o, t in ES.list_strings(gen.read_bytes())]
    assert "Hero_Nyx_Name" in ts and "Hero_Nyx_Desc" in ts and "Hero_Name" not in ts
    # Name only: no entity family, no alias; the base's skins stay.
    assert "Heroes\\Hero_Piper\\Hero_Piper_Default.entity.ot" in ts
    assert not any("ApplicationSettings" in str(p) for p in files)


@needs_corpus
@needs_install
def test_an_own_entity_hero_clones_the_family_and_adds_an_alias(tmp_path):
    from rsmm.engine import entity_strings as ES
    from rsmm.engine import hero_cook as H
    files = _emit(tmp_path, id="Nyx", own_entity=True)
    ents = [p for p in files if p.name.endswith(H.ENTITY_SUFFIX)]
    assert ents and all(p.name.startswith("Hero_Nyx") for p in ents)
    app = next(p for p in files if p.name == "ApplicationSettings.ot").read_text()
    alias = H.aliases(app)[-1]
    assert alias.name == "Hero_Nyx" and alias.stream == "Heroes\\Hero_Piper\\Hero_Nyx.entity.ot"
    default = next(p for p in ents if p.name.startswith("Hero_Nyx_Default.entity"))
    assert H._alias_guid_of(default.read_bytes()) == alias.guid
    gen = next(p for p in files if p.name.startswith("Nyx.herodef"))
    ts = [t for _s, _o, t in ES.list_strings(gen.read_bytes())]
    assert "Heroes\\Hero_Piper\\Hero_Nyx_Default.entity.ot" in ts
    cache = RC.parse(next(p for p in files if p.name == "Nyx.herodef.UsedRscCache.ot")
                     .read_bytes())
    assert "EntitySettings|Heroes\\Hero_Piper\\Hero_Nyx.entity.ot|oCEntitySettingsResource" \
        in cache


@needs_corpus
def test_an_own_entity_hero_gets_its_own_life_bar_reading_its_names(tmp_path):
    """Scarlet's life bar reads ``] Hero_Red\\Life Bar\\...`` by name; a clone
    that keeps it shows no rage or combo (reported on a Red clone, 2026-11)."""
    from rsmm.engine import corpus
    from rsmm.engine import entity_strings as ES
    from rsmm.engine import hero_cook as H
    from rsmm.engine import prop_cook as PC
    files = heros.emit("m", ContentDef(kind="hero", id="Nyx",
                                       fields={"base": "Red", "own_entity": True}), tmp_path)
    bar = next(p for p in files if p.name.startswith("Life_Bar_Hero_Red_Nyx.entity.ot"))
    ts = [t for _s, _o, t in ES.list_strings(bar.read_bytes())]
    assert any(t.startswith("[") and "] Hero_Nyx\\" in t for t in ts)
    assert not any("] Hero_Red\\" in t or "] Life_Bar_Hero_Red\\" in t for t in ts)
    main = next(p for p in files if p.name.startswith("Hero_Nyx.entity.ot"))
    refs = [t for _s, _o, t in ES.list_strings(main.read_bytes())]
    assert "GameUis\\Common_Ui\\Life_Bar_Hero_Red_Nyx.entity.ot" in refs
    assert "GameUis\\Common_Ui\\Life_Bar_Hero_Red.entity.ot" not in refs
    shipped = set(PC.component_guids(corpus.read(
        H.entity_rel("GameUis\\Common_Ui\\Life_Bar_Hero_Red.entity.ot"))))
    assert not shipped & set(PC.component_guids(bar.read_bytes()))
    # Piper has no hero-specific UI: nothing outside her folder is cloned.
    piper = _emit(tmp_path / "p", id="Nyx", own_entity=True)
    assert not any("GameUis" in p.as_posix() for p in piper)


@needs_corpus
def test_a_custom_hero_id_must_be_a_plain_name(tmp_path):
    with pytest.raises(ContentError, match="letters and digits|reserved"):
        _emit(tmp_path, id="Alice", name="X")


@needs_corpus
@needs_install
def test_outfits_fill_the_skin_slots_after_default(tmp_path):
    from rsmm.engine import entity_strings as ES
    from rsmm.engine import image
    png = image.encode_png(4, 4, bytes([0, 200, 200, 255]) * 16)
    (tmp_path / "c.png").write_bytes(png)
    files = heros.emit("m", ContentDef(kind="hero", id="Nyx", fields={
        "base": "Piper", "outfits": [{"name": "Frost", "albedo": "c.png"}]}),
        tmp_path / "assets")
    gen = next(p for p in files if p.name.startswith("Nyx.herodef.ot"))
    ts = [t for _s, _o, t in ES.list_strings(gen.read_bytes())]
    skins = [t for t in ts if t.endswith(".entity.ot") and "LowRes" not in t
             and t.startswith("Heroes\\")]
    assert skins[:2] == ["Heroes\\Hero_Piper\\Hero_Nyx_Default.entity.ot",
                         "Heroes\\Hero_Piper\\Hero_Nyx_Outfit1.entity.ot"]
    assert "Hero_Nyx_Outfit1_Title" in ts
    outfit = next(p for p in files if p.name.startswith("Hero_Nyx_Outfit1.entity.ot"))
    assert "Characters\\Heroes\\Piper\\Textures\\M_Nyx_Outfit1.mat.ot" in [
        t for _s, _o, t in ES.list_strings(outfit.read_bytes())]


@needs_corpus
@needs_install
def test_references_swap_inside_the_heros_own_files_and_borrow_their_preloads(tmp_path):
    from rsmm.engine import entity_strings as ES
    old = "Settings\\Heroes\\Hero_Piper_FX\\Piper_Note_Day_01.vfx.ot"
    new = "Settings\\Heroes\\Hero_Juliet_FX\\Juliet_Basic_Bullet_Trail_01.vfx.ot"
    files = _emit(tmp_path, id="Nyx", references={old: new})
    proj = next(p for p in files if p.name.startswith("Hero_Nyx_Projectile.entity.ot"))
    ts = [t for _s, _o, t in ES.list_strings(proj.read_bytes())]
    assert new in ts and old not in ts
    cache = RC.parse(next(p for p in files if p.name == "Nyx.herodef.UsedRscCache.ot")
                     .read_bytes())
    assert any(ln.split("|")[1] == new for ln in cache)       # or a null at load
    with pytest.raises(ContentError, match="never use"):
        _emit(tmp_path / "x", id="Nyx", references={"No\\Such.vfx.ot": new})


@needs_corpus
@needs_install
def test_the_clone_owns_its_component_identities_and_keeps_its_internal_links(tmp_path):
    """Measured in game 2026-09-25: a family clone carrying the base's component
    GUIDs spawned a body-less, light-less hero with no health, and the pause
    menu crashed on it. The links between members (and the herodef's 22) are
    GUIDs too, so they must follow the same mapping."""
    from rsmm.engine import corpus
    from rsmm.engine import hero_cook as H
    from rsmm.engine import prop_cook as PC
    files = _emit(tmp_path, id="Nyx", own_entity=True)
    base = [corpus.read(r) for r in corpus.rels("EntitySettings/Heroes/Hero_Piper/",
                                                H.ENTITY_SUFFIX)]
    piper = {g for raw in base for g in PC.component_guids(raw)}
    ours = [p.read_bytes() for p in files if p.name.endswith(H.ENTITY_SUFFIX)]
    owned = {g for raw in ours for g in PC.component_guids(raw)}
    assert owned and owned.isdisjoint(piper)
    assert not any(g in raw for raw in ours for g in piper)          # no stale link
    herodef = next(p for p in files if p.name == "Nyx.herodef.ot.DtHeroDefinition.gen")
    assert sum(g in herodef.read_bytes() for g in owned) >= 20


@needs_corpus
@needs_install
def test_a_weapon_keeps_its_authored_shape(tmp_path):
    """In game 2026-09-25 the prop fit's auto-upright turned Piper's flute on end
    and squeezed it to a sliver: no flute in the hero's hand."""
    from rsmm.engine import cooked, corpus
    from rsmm.engine import geometry_cook as GC
    from rsmm.engine.cooked_schemas import geometry as G
    from rsmm.sdk.kinds.poi import _mesh_glb
    ref = "Characters\\Heroes\\Piper\\Piper_Flute.fbx"
    glb = _mesh_glb(ref)
    if glb is None:
        pytest.skip("flute not in the corpus")
    (tmp_path / "flute.glb").write_bytes(glb)
    files = heros.emit("m", ContentDef(kind="hero", id="Nyx", fields={
        "base": "Piper", "weapons": {"Weapon In Left Hand Mesh": "flute.glb"}}),
        tmp_path / "assets")

    def verts(raw):
        cf = cooked.parse(raw)
        t = next(i for i, s in enumerate(cf.sections) if GC._find_records(s.payload))
        return [p for s in G._parse_meshbuffers(cf.sections[t].payload) for p in s.positions]
    ours = next(p for p in files if p.name.startswith("Nyx_Weapon1_GEO"))
    shipped = corpus.read("3D/Characters/Heroes/Piper/Piper_Flute.fbx.Geometry.gen")
    assert verts(ours.read_bytes()) == pytest.approx(verts(shipped), abs=1e-5)


@needs_corpus
@needs_install
def test_a_companion_material_takes_maps_but_no_model(tmp_path):
    """Beowulf's Wyrm has a material of its own but no attachment: `weapons`
    retextures it (Jack's Golden Hen) and refuses a model for it."""
    (tmp_path / "gold.png").write_bytes(_tiny_png())
    files = heros.emit("m", ContentDef(kind="hero", id="Jack", fields={
        "base": "Beowulf", "weapons": {"Chatacter Mesh Wyrm": {"albedo": "gold.png"}}}),
        tmp_path / "assets")
    default = next(p for p in files if p.name.startswith("Hero_Jack_Default.entity.ot"))
    assert b"M_Jack_Weapon1.mat.ot" in default.read_bytes()
    assert b"M_BeowulfWyrm.mat.ot" not in default.read_bytes()
    with pytest.raises(ContentError, match="maps only"):
        heros.emit("m", ContentDef(kind="hero", id="Jack", fields={
            "base": "Beowulf", "weapons": {"Chatacter Mesh Wyrm": {"model": "x.glb"}}}),
            tmp_path / "assets2")


def _tiny_png() -> bytes:
    import struct
    import zlib

    def chunk(tag, data):
        return (struct.pack(">I", len(data)) + tag + data
                + struct.pack(">I", zlib.crc32(tag + data) & 0xffffffff))
    raw = b"".join(b"\x00" + bytes([230, 180, 60, 255]) * 4 for _ in range(4))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 4, 4, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


_ECHO = [
    {"clone": "Ability Secondary", "as": "Echo"},
    {"set": "Primary Ability Shots Delay.value", "value": 0.2},
    {"link": "Primary Ability Shoot Timer.on_end", "to": "State Secondary Ability Echo"},
]


@needs_corpus
@needs_install
def test_ability_edits_land_in_the_heros_own_entity_under_its_names(tmp_path):
    from rsmm.engine import corpus
    from rsmm.engine import entity_fields as EF
    from rsmm.engine import entity_graph as EG
    from rsmm.engine import prop_cook as PC
    files = _emit(tmp_path, id="Nyx", abilities=_ECHO)
    main = next(p for p in files if p.name == "Hero_Nyx.entity.ot.EntitySettingsResource.gen")
    g = EG.parse(main.read_bytes(), "Hero_Nyx")
    echo = g.groups()["Echo"]
    piper = corpus.read("EntitySettings/Heroes/Hero_Piper/Hero_Piper.entity.ot"
                        ".EntitySettingsResource.gen")
    assert len(echo) == len(EG.parse(piper).groups()["Ability Secondary"])
    timer = next(c for c in g.components if c.name == "Primary Ability Shoot Timer")
    on_end = next(f for f in EF.fields(timer) if f.name == "on_end")
    assert on_end.text.endswith("Hero_Nyx\\Echo\\State Secondary Ability Echo")
    delay = next(c for c in g.components if c.name == "Primary Ability Shots Delay")
    assert next(f for f in EF.fields(delay) if f.name == "value").text == "f32 0.2"
    assert not set(PC.component_guids(main.read_bytes())) & set(PC.component_guids(piper))


@needs_corpus
@needs_install
def test_an_ability_edit_that_binds_to_nothing_is_refused(tmp_path):
    """Juliet's secondary links into Hero_Romeo_Juliet_Common, which a hero
    built on Piper does not carry: installed, it would do nothing."""
    with pytest.raises(ContentError, match="Hero_Romeo_Juliet_Common"):
        _emit(tmp_path, id="Nyx", abilities=[
            {"clone": "Ability Secondary", "as": "Kiss", "from": "Juliet"}])


@needs_corpus
@needs_install
@pytest.mark.parametrize("step,msg", [
    ({"clone": "Ability Secondary"}, "needs 'as'"),
    ({"set": "Primary Ability Shots Delay.value"}, "needs a value"),
    ({"set": "No Such Part.value", "value": 1}, "0 components named"),
    ({"link": "x", "to": "y", "set": "z"}, "exactly one of"),
])
def test_malformed_ability_steps_are_refused(tmp_path, step, msg):
    with pytest.raises(ContentError, match=msg):
        _emit(tmp_path, id="Nyx", abilities=[step])


_RED = "EntitySettings/Heroes/Hero_Red/Hero_Red.entity.ot.EntitySettingsResource.gen"


@needs_corpus
def test_a_third_combo_step_from_a_renamed_clone_and_a_copied_combo_entry():
    """The Blood Wolf combo (a community manifest): clone step 2 under exact
    names, then append a copy of the combo's second entry pointed at it."""
    from rsmm.engine import ability_edit as AE
    from rsmm.engine import entity_fields as EF
    from rsmm.engine.entity_graph_edit import EntityFile
    step2, step3 = "State Wolf Basic Attack Step 2", "State Wolf Basic Attack Step 3"
    out = AE.apply({"Hero_Red": corpus.read(_RED)}, [
        {"clone": [step2], "rename": {step2: step3}},
        {"add_subobject": "Wolf Basic Attack Combo.bytes_4", "donor_index": 1,
         "replace_ref": {step2: step3}},
    ], main="Hero_Red", seed="t")
    ef = EntityFile(out.files["Hero_Red"], "Hero_Red")
    combo = ef.component("Wolf Basic Attack Combo")
    f = next(x for x in EF.fields(combo) if x.name == "bytes_4")
    ids = f.text.split()
    assert ids[0] == "03"                     # three entries now
    new = int("".join(reversed(ids[-4:])), 16)
    assert ef.component(step3).guid in bytes(ef.objects[new])


_RED_BOMB = "EntitySettings/Heroes/Hero_Red/Hero_Red_Bomb.entity.ot.EntitySettingsResource.gen"
_ALT_FORM = "Heroes/Hero_Common/Hero_Alt_Form_Common"
_FORM_VALUE = "Initialize In Default Form Value"
_ORB = "Heroes/Hero_Carmilla/Hero_Carmilla_Power_Orb"


@needs_corpus
def test_an_override_replaces_the_ancestors_part_instead_of_adding_one():
    """Blood Wolf starts in wolf form: its own version of Hero_Alt_Form_Common's
    form value, marked as that part's override (a clone would be a second)."""
    from rsmm.engine import ability_edit as AE
    from rsmm.engine.entity_graph_edit import EntityFile
    out = AE.apply({"Hero_Red": corpus.read(_RED)}, [
        {"override": _FORM_VALUE, "from": _ALT_FORM},
        {"set": f"{_FORM_VALUE}.value", "value": False},
    ], main="Hero_Red", seed="t")
    mine = [c for c in EntityFile(out.files["Hero_Red"], "Hero_Red").graph().components
            if c.name == _FORM_VALUE]
    anc = EntityFile(corpus.read(f"EntitySettings/{_ALT_FORM}.entity.ot"
                                 ".EntitySettingsResource.gen"), "Hero_Alt_Form_Common")
    assert len(mine) == 1 and mine[0].override.guid == anc.component(_FORM_VALUE).guid
    assert mine[0].override.path.endswith(f"] Hero_Alt_Form_Common\\Base\\{_FORM_VALUE}")


@needs_corpus
def test_a_relinked_number_takes_its_new_targets_accessor():
    """A modifier moved from a selector onto an operation must read it with the
    operation's accessor. set_ref learned accessors AFTER writing the link, so
    the half-edited link was counted as the file's own evidence and kept the
    selector's: Blood Wolf's 3rd hit dealt 0 bleed in game (2026-11-01)."""
    from rsmm.engine.entity_graph_edit import EntityFile
    ef = EntityFile(corpus.read(_RED), "Hero_Red")
    op = "Wolf Basic Attack Supposed Damage Operation"
    ef.clone([op], rename={op: "Bleed Op"}, seed="a")
    ef.clone(["Skill Primary Bleed Modifier"],
             rename={"Skill Primary Bleed Modifier": "Bleed Mod"}, seed="b")
    ef.set_ref("Bleed Mod", "amount", "Bleed Op")
    p = bytes(ef.objects[ef.component("Bleed Mod").index - 1])
    at = p.find(b"\\Bleed Op") + len(b"\\Bleed Op") + 4
    assert p[at:at + 4] == EntityFile.F32_ACCESSOR[
        "oCEntityCpntValueOperationsSettings"].to_bytes(4, "little")


@needs_corpus
def test_a_copy_across_class_versions_is_refused():
    """Character_Common's damage records are version 1.23, Scarlet's bomb's
    1.21: a copied record is read with the wrong layout and the bomb never
    loaded in game (2026-11-01). Copying the bomb's own record works."""
    from rsmm.engine import ability_edit as AE
    files = {"Hero_Red": corpus.read(_RED), "Hero_Red_Bomb": corpus.read(_RED_BOMB)}
    with pytest.raises(AE.AbilityEditError, match="version 1.21 of it, the source 1.23"):
        AE.apply(files, [{"entity": "Bomb", "clone": ["Bleed Damage"],
                          "from": "Character_Common/Character_Common"}],
                 main="Hero_Red", seed="t")
    AE.apply(files, [{"entity": "Bomb", "clone": ["Explosion Damage Heroes"],
                      "rename": {"Explosion Damage Heroes": "Bleed Damage"}}],
             main="Hero_Red", seed="t")


@needs_corpus
def test_a_one_byte_flag_field_can_be_set():
    """A damage record's bytes_30 is 1 on Scarlet's bomb and 0 on DoT damage;
    left at 1 the bomb's bleed ignored armour plates in game (2026-11-01)."""
    from rsmm.engine import ability_edit as AE
    from rsmm.engine import entity_fields as EF
    from rsmm.engine.entity_graph_edit import EntityFile
    files = {"Hero_Red": corpus.read(_RED), "Hero_Red_Bomb": corpus.read(_RED_BOMB)}
    out = AE.apply(files, [{"entity": "Bomb", "set": "Explosion Damage.bytes_30", "value": 0}],
                   main="Hero_Red", seed="t")
    ef = EntityFile(out.files["Hero_Red_Bomb"], "Hero_Red_Bomb")
    assert next(f.text for f in EF.fields(ef.component("Explosion Damage"))
                if f.name == "bytes_30") == "00"
    with pytest.raises(AE.AbilityEditError, match="one byte"):
        AE.apply(files, [{"entity": "Bomb", "set": "Explosion Damage.bytes_30", "value": 300}],
                 main="Hero_Red", seed="t")


@needs_corpus
def test_linking_a_literal_number_makes_it_read_the_target():
    from rsmm.engine import ability_edit as AE
    from rsmm.engine import entity_fields as EF
    from rsmm.engine.entity_graph_edit import EntityFile
    out = AE.apply({"Hero_Red": corpus.read(_RED), "Hero_Red_Bomb": corpus.read(_RED_BOMB)}, [
        {"entity": "Bomb", "link": "Explosion Damage Heroes.value_2",
         "to": "Explosion Damage Multiplier"},
    ], main="Hero_Red", seed="t")
    ef = EntityFile(out.files["Hero_Red_Bomb"], "Hero_Red_Bomb")
    f = next(x for x in EF.fields(ef.component("Explosion Damage Heroes")) if x.name == "value_2")
    assert f.text.endswith("Hero_Red_Bomb\\Explosion Damage Multiplier")


@needs_corpus
def test_sub_objects_copy_in_from_another_entity_and_replace_in_place():
    """The burst wears Carmilla's blood VFX: entry 0 of the bomb's Fx list
    becomes a copy of her orb's, in the same place; another is appended."""
    from rsmm.engine import ability_edit as AE
    from rsmm.engine import entity_fields as EF
    from rsmm.engine.entity_graph_edit import EntityFile
    def fx(raw):
        ef = EntityFile(raw, "Hero_Red_Bomb")
        c = ef.component("Fx_Explosion")
        f = next(x for x in EF.fields(c) if x.name == "bytes_1")
        n = int.from_bytes(c.body[f.offset:f.offset + 4], "little")
        ids = [int.from_bytes(c.body[f.offset + 4 + 4 * i:f.offset + 8 + 4 * i], "little")
               for i in range(n)]
        return [bytes(ef.objects[i]) for i in ids]
    before = fx(corpus.read(_RED_BOMB))
    out = AE.apply({"Hero_Red": corpus.read(_RED), "Hero_Red_Bomb": corpus.read(_RED_BOMB)}, [
        {"entity": "Bomb", "replace_subobject": "Fx_Explosion.bytes_1[0]", "from": _ORB,
         "donor": "Explosion Fx Active.bytes_1[0]",
         "replace_ref": {"Mesh": "Mesh", "Owner Explosion Radius Get Value": "Explosion Radius",
                         "Owner Current Radius Get Value": "Explosion Radius"}},
        {"entity": "Bomb", "add_subobject": "Fx_Explosion.bytes_1", "from": _ORB,
         "donor": "Explosion Fx Active.bytes_1[1]", "replace_ref": {"Mesh": "Mesh"}},
    ], main="Hero_Red", seed="t")
    after = fx(out.files["Hero_Red_Bomb"])
    assert len(after) == len(before) + 1 and after[1:3] == before[1:3]
    assert b"Carmilla_Power_Orb_Explosion_01" in after[0]
    assert b"RED_Bomb_Explosion_5m" not in after[0]
    assert b"Carmilla_Power_Orb_Core_Explosion_01" in after[-1]


@needs_corpus
@pytest.mark.parametrize("step,msg", [
    ({"clone": ["Wolf Basic Attack Combo"], "renme": {}}, "no key renme"),
    ({"clone": ["Wolf Basic Attack Combo"], "rename": {"Other": "X"}}, "does not copy"),
    ({"add_subobject": "Wolf Basic Attack Combo.bytes_4", "donor_index": 5}, "entries 0..1"),
    ({"override": _FORM_VALUE}, "needs from"),
    ({"override": "Explosion Damage", "from": "Heroes/Hero_Red/Hero_Red_Bomb"},
     "not an ancestor"),
    ({"replace_subobject": "Wolf Basic Attack Combo.bytes_4"}, "names one entry"),
    ({"add_subobject": "Wolf Basic Attack Combo.bytes_4", "from": _ORB}, "needs donor"),
])
def test_bad_new_steps_are_refused(step, msg):
    from rsmm.engine import ability_edit as AE
    with pytest.raises(AE.AbilityEditError, match=msg):
        AE.apply({"Hero_Red": corpus.read(_RED)}, [step], main="Hero_Red", seed="t")


@needs_corpus
@needs_install
def test_cards_of_its_own_repoint_its_controllers_and_leave_the_base_alone(tmp_path):
    """A card's text is read by the key its controller names: the hero's copy
    is pointed at Hero_<id>_ keys, appended to the bank with the name (one
    append; two would each write the whole bank and the second would win)."""
    from rsmm.engine import entity_strings as ES
    from rsmm.engine import text_patches as TP
    files = _emit(tmp_path, id="Nyx", name="Nyx", skills={
        "Dash Trap": {"name": "Echo Step", "description": "• #DASH@ sends &{0}~ notes"},
        "Ability Power": {"name": "Solo"}})
    main = next(p for p in files if p.name == "Hero_Nyx.entity.ot.EntitySettingsResource.gen")
    strings = {t for _s, _o, t in ES.list_strings(main.read_bytes())}
    assert {"Hero_Nyx_Skill_Dash_Trap_Name", "Hero_Nyx_Skill_Dash_Trap_Desc",
            "Hero_Nyx_Ability_Power_Name"} <= strings
    assert not {"Skill_Dash_Trap_Name", "Skill_Dash_Trap_Desc", "Ability_Power_Name"} & strings
    assert "Ability_Power_Desc" in strings                  # not asked for: kept
    bank = next(p for p in files if p.name == "Hero_Piper_Common~GAM.xls.LocalText.gen")
    en = next(p for p in files if p.name.endswith(".LocalText.gen.LangEN"))
    text = dict(zip(TP.parse_text_file(bank).entries, TP.parse_text_file(en).entries, strict=True))
    assert text["Hero_Nyx_Skill_Dash_Trap_Name"] == "Echo Step"
    assert text["Hero_Nyx_Ability_Power_Name"] == "Solo"
    assert text["Hero_Nyx_Name"] == "Nyx"
    assert text["Skill_Dash_Trap_Name"] == "Music of the Spheres"   # Piper's card
    # The book and the HUD read the row cached in front of the key, not the
    # key: every new key must carry ITS row, or those show Piper's text.
    import struct
    row = {k: i for i, k in enumerate(TP.parse_text_file(bank).entries)}
    herodef = next(p for p in files if p.name == "Nyx.herodef.ot.DtHeroDefinition.gen")
    for blob, key in ((main.read_bytes(), "Hero_Nyx_Skill_Dash_Trap_Name"),
                      (main.read_bytes(), "Hero_Nyx_Ability_Power_Name"),
                      (herodef.read_bytes(), "Hero_Nyx_Name")):
        k = key.encode()
        at = blob.find(struct.pack("<I", len(k)) + k)
        assert at != -1 and struct.unpack_from("<I", blob, at - 4)[0] == row[key], key


@needs_corpus
@needs_install
def test_a_card_the_base_does_not_have_is_refused(tmp_path):
    with pytest.raises(ContentError, match="no talent 'Fireball'"):
        _emit(tmp_path, id="Nyx", skills={"Fireball": {"name": "x"}})


@needs_corpus
@needs_install
def test_a_placeholder_paints_every_borrowed_image_and_material(tmp_path):
    """Whatever the hero still borrows from its base (character materials,
    icons, book art) is swapped for its own copy of ONE image, so what is left
    to replace is visible; nothing of the base's own art stays referenced."""
    from rsmm.engine import entity_strings as ES
    from rsmm.engine import image
    (tmp_path / "pink.png").write_bytes(image.encode_png(4, 4, bytes([255, 0, 255, 255]) * 16))
    files = _emit(tmp_path, id="Nyx", placeholder="pink.png")
    left = set()
    for p in files:
        if p.name.endswith((".entity.ot.EntitySettingsResource.gen", ".DtHeroDefinition.gen")):
            for _s, _o, t in ES.list_strings(p.read_bytes()):
                if (t.lower().endswith(".png") and "Nyx_" not in t) or (
                        t.endswith(".mat.ot") and t.startswith("Characters\\Heroes\\Piper\\")
                        and "Nyx" not in t):
                    left.add(t)
    assert not left, sorted(left)[:5]
    assert any(p.name.startswith("Nyx_Skill") and p.name.endswith(".Texture.dxt") for p in files)


@needs_corpus
@needs_install
def test_story_pages_of_its_own_and_placeholders_for_the_rest(tmp_path):
    import struct

    from rsmm.engine import entity_strings as ES
    from rsmm.engine import image
    from rsmm.engine import text_patches as TP
    (tmp_path / "pink.png").write_bytes(image.encode_png(4, 4, bytes([255, 0, 255, 255]) * 16))
    files = _emit(tmp_path, id="Nyx", name="Nyx", placeholder="pink.png",
                  memoirs=[{"title": "The Flute", "text": "Nyx found a flute."}])
    herodef = next(p for p in files if p.name == "Nyx.herodef.ot.DtHeroDefinition.gen")
    blob = herodef.read_bytes()
    strings = [t for _s, _o, t in ES.list_strings(blob)]
    assert not any(re.fullmatch(r"Piper_Memoir\d_(Title|Desc)", t) for t in strings)
    bank = next(p for p in files if p.name == "Hero_Piper_Memoirs~GAM.xls.LocalText.gen")
    en = next(p for p in files if p.name == "Hero_Piper_Memoirs~GAM.xls.LocalText.gen.LangEN")
    keys = TP.parse_text_file(bank).entries
    text = dict(zip(keys, TP.parse_text_file(en).entries, strict=True))
    assert text["Hero_Nyx_Memoir1_Title"] == "The Flute"
    assert text["Hero_Nyx_Memoir2_Desc"].startswith("PLACEHOLDER: Nyx's story, page 2")
    for key in ("Hero_Nyx_Memoir1_Desc", "Hero_Nyx_Memoir3_Title"):
        k = key.encode()
        at = blob.find(struct.pack("<I", len(k)) + k)
        assert struct.unpack_from("<I", blob, at - 4)[0] == keys.index(key), key
    # The pages' voice-over is named after the hero (Voice_<lang>.bank holds
    # Piper_Memoir<n>_Desc): Piper must not read her story over Nyx's pages.
    assert "Nyx/Nyx_Memoir{}_Desc" in strings
    assert not any(t.endswith("_Memoir{}_Desc") and not t.startswith("Nyx/") for t in strings)
    # Skin slots no outfit takes read as skins still to design.
    skins = next(p for p in files if p.name.endswith("_Skins~GAM.xls.LocalText.gen"))
    skins_en = next(p for p in files if p.name.endswith("_Skins~GAM.xls.LocalText.gen.LangEN"))
    stext = dict(zip(TP.parse_text_file(skins).entries,
                     TP.parse_text_file(skins_en).entries, strict=True))
    assert stext["Hero_Nyx_Skin1_Title"] == "[Skin 1: to be designed]"
    assert "Hero_Nyx_Skin1_Title" in strings


@needs_corpus
@needs_install
def test_effects_of_its_own_recoloured_and_pink_under_a_placeholder(tmp_path):
    """Every effect in the base's own FX folder is copied under the hero's
    name with its own materials and textures; the hero's entities play only the
    copies; textures keep their alpha, recoloured (pink = still the base's)."""
    from rsmm.engine import cooked, icon_decode, image
    from rsmm.engine import entity_strings as ES
    from rsmm.engine.cooked_schemas.texture import TextureHandler
    (tmp_path / "pink.png").write_bytes(image.encode_png(4, 4, bytes([255, 0, 255, 255]) * 16))
    files = _emit(tmp_path, id="Nyx", placeholder="pink.png",
                  effects={"Piper_Note_Day_01": {"tint": "#00ff00"}})
    names = {p.name for p in files}
    ents = [p for p in files if p.name.endswith(".entity.ot.EntitySettingsResource.gen")]
    played = {t for p in ents for _s, _o, t in ES.list_strings(p.read_bytes())
              if t.endswith(".vfx.ot")}
    own = {t for t in played if "\\Hero_Piper_FX\\" in t}
    assert own and all(t.rsplit("\\", 1)[-1].startswith("Nyx_") for t in own), sorted(own)[:3]
    assert any(t.startswith("Settings\\FX\\Common_FX\\") for t in played)   # shared: kept
    assert "Nyx_Piper_Note_Day_01.vfx.ot.ScheduledVfxSettings.gen" in names

    def colour(name):
        raw = next(p for p in files if p.name == name).read_bytes()
        s = TextureHandler.parse_payload(cooked.parse(raw).sections[-1].payload)
        px = icon_decode.decode_to_rgba(s.pixels, s.width, s.height, s.format_name)
        lit = [px[i:i + 4] for i in range(0, len(px), 4) if px[i + 3] and max(px[i:i + 3]) > 60]
        return lit[len(lit) // 2], any(px[i] < 255 for i in range(3, len(px), 4))

    fx_tex = [p.name for p in files if "/FX/" in p.as_posix() and p.name.endswith(".Texture.dxt")]
    pink = next(n for n in fx_tex if n.startswith("Nyx_") and not n.startswith("Nyx_00ff00_"))
    (r, g, b, _a), has_alpha = colour(pink)
    assert r > 3 * g and b > 3 * g and has_alpha                         # pink, alpha kept
    green = next(n for n in fx_tex if n.startswith("Nyx_00ff00_"))
    (r, g, b, _a), _ = colour(green)
    assert g > 3 * r and g > 3 * b                                        # the named tint wins


@needs_corpus
@needs_install
def test_effect_colour_ramps_take_the_tint_at_their_own_brightness(tmp_path):
    """Fire is orange through the effect's colour ramps (HDR multipliers on
    the texture), not only the texture: a recolour must reach them too."""
    import struct

    from rsmm.engine import cooked, corpus
    from rsmm.sdk.kinds.heros import _RAMP_TAILS, _recolour_effect
    rel = "FX/Settings/Heroes/Hero_Piper_FX/"
    raw = next(corpus.read(r) for r in corpus.rels(rel, ".ScheduledVfxSettings.gen")
               if b"oC3dParticleEffectorColorRampSettings" in corpus.read(r))
    out, skipped = _recolour_effect(raw, (1.0, 0.0, 1.0))
    assert skipped == 0
    before, after = cooked.parse(raw), cooked.parse(out)
    names = [c.name for c in after.classes]
    ci = names.index("oC3dParticleEffectorColorRampSettings")
    keys = 0
    for s0, s1 in zip(before.sections[1:], after.sections[1:], strict=True):
        if struct.unpack_from("<I", s1.payload, 0)[0] != ci:
            assert s0.payload == s1.payload          # nothing else moves
            continue
        for k in range(struct.unpack_from("<I", s1.payload, 17)[0]):
            r0, g0, b0, a0 = struct.unpack_from("<4f", s0.payload, 25 + 20 * k)
            r1, g1, b1, a1 = struct.unpack_from("<4f", s1.payload, 25 + 20 * k)
            assert (r1, g1, b1, a1) == pytest.approx((max(r0, g0, b0), 0.0, max(r0, g0, b0), a0))
            keys += 1
    assert keys and "oC3dTrailEffectorColorRampSettings" in _RAMP_TAILS


@needs_corpus
@needs_install
def test_a_hidden_mesh_is_an_invisible_copy_on_the_same_skeleton(tmp_path):
    """Gretel has no dragon: `hide` swaps the mesh, in her entities only, for
    the same mesh shrunk to nothing, so its bones (the breath's origin) stay."""
    import json
    import struct

    from rsmm.engine import character_export as CE
    from rsmm.engine import entity_strings as ES
    files = _emit(tmp_path, id="Nyx", base="Beowulf", hide=["Wyrm_GEO"])
    geo = next(p for p in files if p.name == "Nyx_Hidden1_GEO.fbx.Geometry.gen")
    used = {t for p in files if p.name.endswith(".entity.ot.EntitySettingsResource.gen")
            for _s, _o, t in ES.list_strings(p.read_bytes())}
    assert "Characters\\Heroes\\Beowulf\\Nyx_Hidden1_GEO.fbx" in used
    assert "Characters\\Heroes\\Beowulf\\Wyrm_GEO.fbx" not in used
    glb = CE.export(geo.read_bytes(), textures=False)
    n = struct.unpack_from("<I", glb, 12)[0]
    gltf, binary = json.loads(glb[20:20 + n]), glb[20 + n + 8:]
    joints = gltf["skins"][0]["joints"]
    assert any(gltf["nodes"][j].get("name") == "DEF.HeadDragon" for j in joints)
    bound = set()
    for prim in (p for m in gltf["meshes"] for p in m["primitives"]):
        pos = gltf["accessors"][prim["attributes"]["POSITION"]]
        assert max(hi - lo for hi, lo in zip(pos["max"], pos["min"], strict=True)) < 0.01
        # Every vertex rides ONE bone: a skinned mesh merely shrunk toward
        # the origin scattered back out in game once the bones moved.
        ja = gltf["accessors"][prim["attributes"]["JOINTS_0"]]
        wa = gltf["accessors"][prim["attributes"]["WEIGHTS_0"]]
        jv, wv = gltf["bufferViews"][ja["bufferView"]], gltf["bufferViews"][wa["bufferView"]]
        for i in range(ja["count"]):
            js = struct.unpack_from("<4H", binary, jv.get("byteOffset", 0)
                                    + ja.get("byteOffset", 0) + 8 * i)
            ws = struct.unpack_from("<4f", binary, wv.get("byteOffset", 0)
                                    + wa.get("byteOffset", 0) + 16 * i)
            bound |= {j for j, w in zip(js, ws, strict=True) if w > 1e-3}
    assert len(bound) == 1
    with pytest.raises(ContentError, match="not a mesh"):
        _emit(tmp_path, id="Nyx", base="Beowulf", hide=["No_Such_GEO"])


@needs_corpus
def test_every_hero_tab_block_builds_on_scarlet():
    """The Hero tab's blocks (mods/hero-builder-test's kit): fire with fan,
    side offsets and per-shot numbers and status effects, a hit area, a heal,
    wait and repeat, all expand into steps that pass the ability check."""
    from rsmm.engine import ability_edit as AE
    from rsmm.engine import hero_kit as HK
    laser = "Enemies/Tentacle_Nightmares/Projectile_Tentacle_Nightmare_Laser_Shot"
    kit = {"form": "wolf", "dash": "none",
           "power": {"replace": True, "steps": [
               {"fire": "Heroes/Hero_Piper/Hero_Piper_Ghost_Note_Projectile",
                "offsets": [-1, 0, 1], "damage": 150, "burn": 4, "explode": 3},
               {"wait": 0.3}, {"hit": {"radius": 6, "damage": 200}}]},
           "special": {"replace": True, "steps": [
               {"heal": 30}, {"fire": laser, "angles": [-25, 0, 25], "poison": 3, "curse": True}]},
           "ultimate": {"replace": True, "steps": [
               {"repeat": 5, "every": 0.15, "steps": [{"fire": laser, "damage": 120}]},
               {"hit": {"radius": 9, "damage": 300, "delay": 0.5}}]}}
    steps = HK.expand(kit, corpus.read(_RED), "Hero_Red")
    out = AE.apply({"Hero_Red": corpus.read(_RED)}, steps, main="Hero_Red", seed="t")
    assert HK.HIT_ENTITY in out.resources
    names = " ".join(s.get("rename", {}).get(next(iter(s.get("rename") or {"": ""})), "")
                     for s in steps if "rename" in s)
    for part in ("Kit Power Shot 3", "Kit Power Hit 4 Radius", "Kit Special Heal",
                 "Kit Power Shot 1 Burn Time", "Kit Ultimate Moment 5 Timer"):
        assert part in names, part
    with pytest.raises(HK.KitError, match="0.5..30"):
        HK.expand({"power": {"steps": [{"hit": {"radius": 99}}]}}, corpus.read(_RED), "Hero_Red")


@needs_corpus
@needs_install
def test_hero_talents_are_rebuilt_from_generated_parts(tmp_path):
    """`talents`: a slot's base logic cut, a generated stat and an action that
    fires on a game event only while the talent is owned; `materials` repaints
    a material by name (Kintaro's boy is his "Alt Form" mesh, not `albedo`'s)."""
    from rsmm.engine import entity_graph as EG
    (tmp_path / "boy.png").write_bytes(_tiny_png())
    files = heros.emit("m", ContentDef(kind="hero", id="Jack", fields={
        "base": "Kintaro",
        "materials": {"M_Kintaro": {"albedo": "boy.png"}},
        "talents": {
            "Passive Move Speed": {
                "name": "Light Feet", "description": "• Gain &+{0}%~ #MOVE SPEED@",
                "add_stats": [{"stat": "Move Speed Ratio", "values": [0.1, 0.1, 0.1, 0.1]}]},
            "Dash Attack": {"actions": [{"on": "dash", "steps": [{"hit": {"radius": 3}}]}]},
        }}), tmp_path / "assets")
    main = next(p for p in files if p.name == "Hero_Jack.entity.ot.EntitySettingsResource.gen")
    names = {c.name for c in EG.parse(main.read_bytes(), "Hero_Jack").components}
    assert {"Skill Passive Move Speed Rebuilt", "Skill Dash Attack Rebuilt",
            "Skill Dash Attack Action 1"} <= names
    assert any(n.startswith("Kit Talent 1") for n in names)
    default = next(p for p in files if p.name.startswith("Hero_Jack_Default.entity.ot"))
    assert b"M_Jack_Mat1.mat.ot" in default.read_bytes()
    with pytest.raises(ContentError, match="not a material"):
        heros.emit("m", ContentDef(kind="hero", id="Jack", fields={
            "base": "Kintaro", "materials": {"M_Nope": {"albedo": "boy.png"}}}),
            tmp_path / "assets2")
    with pytest.raises(ContentError, match="on = "):
        heros.emit("m", ContentDef(kind="hero", id="Jack", fields={
            "base": "Kintaro", "talents": {"Dash Attack": {
                "actions": [{"on": "nope", "steps": [{"heal": 1}]}]}}}),
            tmp_path / "assets3")


@needs_corpus
@needs_install
def test_kit_talent_hooks_sit_beside_the_slots(tmp_path):
    """`talents` hangs timelines on talents' own events while the slots stay
    free for the buttons (Jack: both on Beowulf)."""
    from rsmm.engine import ability_edit as AE
    from rsmm.engine import corpus
    from rsmm.engine import hero_kit as HK
    beo = "EntitySettings/Heroes/Hero_Beowulf/Hero_Beowulf.entity.ot.EntitySettingsResource.gen"
    kit = {"defense": {"when": "Event Defensive Ability Attack Active",
                       "steps": [{"hit": {"radius": 3}}]},
           "talents": [{"when": "Event Skill Dash Attack Active",
                        "steps": [{"hit": {"radius": 3}}]},
                       {"when": "Event Skill Trait AOE Active", "steps": [{"heal": 40}]}]}
    steps = HK.expand(kit, corpus.read(beo), "Hero_Beowulf")
    AE.apply({"Hero_Beowulf": corpus.read(beo)}, steps, main="Hero_Beowulf", seed="t")
    names = " ".join(v for s in steps for v in (s.get("rename") or {}).values())
    for part in ("Kit Defense", "Kit Talent 1", "Kit Talent 2 Heal"):
        assert part in names, part
    with pytest.raises(HK.KitError, match="when is required"):
        HK.expand({"talents": [{"steps": [{"heal": 1}]}]}, corpus.read(beo), "Hero_Beowulf")


@needs_corpus
@needs_install
def test_a_projectile_that_reads_its_hero_fires_as_a_copy_reading_this_hero(tmp_path):
    """Return (Kintaro's axe: rebounds and timeout from Kintaro) and refresh
    (the Snow Queen's shard: seeking from her) on a Scarlet clone: each fires
    as a copy of the hero's own whose reads aim at numbers in this hero."""
    from rsmm.engine import entity_graph as EG
    kit = {"power": {"steps": [{"fire": "Heroes/Hero_Kintaro/Hero_Kintaro_Thrown_Axe",
                                "reads": {"Max Rebound": 4}}]},
           "special": {"steps": [{"fire": "Heroes/Hero_Snow_Queen/Hero_Snow_Queen_Projectile",
                                  "reads": {"Skill Seeking Available": True}}]}}
    heros.emit("m", ContentDef(kind="hero", id="Howler", fields={"base": "Red", "kit": kit}),
               tmp_path)
    copies = sorted(tmp_path.rglob("Hero_Howler_Kit*.EntitySettingsResource.gen"))
    assert [p.name.split(".")[0] for p in copies] == ["Hero_Howler_Kit1", "Hero_Howler_Kit2"]
    main = next(tmp_path.rglob("Hero_Howler.entity.ot.EntitySettingsResource.gen"))
    hero = {c.guid: c.name for c in EG.parse(main.read_bytes()).components}
    for p in copies:
        reads = [c for c in EG.parse(p.read_bytes()).components
                 if c.cls == "oCEntityCpntGetValueSettings" and c.name.startswith("Owner ")]
        assert reads
        for c in reads:
            assert "Heroes\\Hero_Red\\Hero_Howler.entity.ot" in c.literals, c.name
            assert hero.get(c.refs[-1].guid, "").startswith("Kit Copy"), c.name
    # Preloaded by every skin's cache (the hero's main entity has none of its own).
    caches = [p.read_text(errors="replace")
              for p in tmp_path.rglob("Hero_Howler_*.UsedRscCache.ot")]
    assert caches and all("Hero_Howler_Kit1.entity.ot" in t for t in caches)


@needs_corpus
@needs_install
def test_a_frame_hero_holds_no_other_heros_parts(tmp_path):
    """`frame`: main and FX written from scratch on the shared base; every
    herodef talent row reaches one of its own controllers."""
    import re

    from rsmm.engine import entity_components as EC
    from rsmm.engine import entity_graph as EG
    files = heros.emit("m", ContentDef(kind="hero", id="Self", fields={
        "base": "Kintaro", "frame": {
            "mesh": "Characters\\Heroes\\Kintaro\\Kintaro_GEO.fbx",
            "material": "Characters\\Heroes\\Kintaro\\Textures\\M_Kintaro.mat.ot"}}),
        tmp_path / "assets")
    main = next(p for p in files if p.name == "Hero_Self.entity.ot.EntitySettingsResource.gen")
    raw = main.read_bytes()
    assert EC.parents(raw) == ["Heroes\\Hero_Kintaro\\Hero_Self_FX.entity.ot"]
    assert set(re.findall(rb"\] (Hero_[A-Za-z_0-9]+)\\", raw)) <= {
        b"Hero_Common", b"Hero_Common_Update5", b"Hero_Self"}
    g = EG.parse(raw, "Hero_Self")
    assert {c.override.path.split("] ", 1)[1].split("\\")[0]
            for c in g.components if c.override} <= {"Hero_Common", "Character_Common"}
    herodef = next(p for p in files if p.name.startswith("Self.herodef.ot")).read_bytes()
    ctls = [c for c in g.components if c.name.startswith("Skill Controller ")]
    assert len(ctls) == 22 and all(c.guid in herodef for c in ctls)
    with pytest.raises(ContentError, match="from scratch"):
        heros.emit("m", ContentDef(kind="hero", id="Self", fields={
            "base": "Kintaro", "frame": True, "kit": {"dash": "none"}}), tmp_path / "a2")


@needs_corpus
@needs_install
def test_a_hero_with_no_base_copies_no_hero(tmp_path):
    """`frame` without `base`: entities, buttons and roster record written from
    data; the rig lends assets only (no hero entity file is written but its own)."""
    import re

    from rsmm.engine import herodef_frame as HDF
    files = heros.emit("m", ContentDef(kind="hero", id="Solo", fields={
        "name": "Solo", "frame": {
            "rig": "Hero_Kintaro", "mesh": "Characters\\Heroes\\Kintaro\\Kintaro_GEO.fbx",
            "material": "Characters\\Heroes\\Kintaro\\Textures\\M_Kintaro.mat.ot",
            "talents": [{"name": "Attack One", "title": "One"}],
            "abilities": {"power": {
                "clip": "Characters\\Heroes\\Kintaro\\Animations\\Kintaro_Power_Out.fbx",
                "duration": 0.9, "hits": [{"at": 0.3}]}}}}), tmp_path / "assets")
    entities = [p for p in files if p.name.endswith(".EntitySettingsResource.gen")]
    assert sorted(p.name.split(".")[0] for p in entities) == [
        "Hero_Solo", "Hero_Solo_Default", "Hero_Solo_Default_LowRes", "Hero_Solo_FX"]
    main = next(p for p in entities if p.name.startswith("Hero_Solo.entity")).read_bytes()
    assert set(re.findall(rb"\] (Hero_[A-Za-z_0-9]+)\\", main)) <= {
        b"Hero_Common", b"Hero_Common_Update5", b"Hero_Solo"}
    h = HDF.decode(next(p for p in files if p.name.startswith("Solo.herodef.ot")).read_bytes())
    rows = [d for c, d in h.objects if c == HDF.SKILL]
    assert rows[0]["name"] == "Skill Controller Attack One" and rows[0]["controller"] in main
    assert sum(1 for r in rows if r["tail"][5] == 1) == 6


@needs_corpus
@needs_install
def test_a_scratch_hero_links_original_parts_not_override_records(tmp_path):
    """Every link and override a from-scratch hero writes names a shared
    part's ORIGINAL GUID. A link to an override record's own GUID never
    resolves: talents linked to Hero_Common_Update5's Hero Controller record
    found no hero, joined no offer pool, and every pick window closed empty
    (Jack, playtest 2026-11-08)."""
    from rsmm.engine import corpus
    from rsmm.engine import entity_fields as EF
    from rsmm.engine.entity_graph_edit import EntityFile
    files = heros.emit("m", ContentDef(kind="hero", id="Solo", fields={
        "frame": {
            "rig": "Hero_Kintaro", "mesh": "Characters\\Heroes\\Kintaro\\Kintaro_GEO.fbx",
            "material": "Characters\\Heroes\\Kintaro\\Textures\\M_Kintaro.mat.ot",
            "talents": [{"name": "Attack One", "starter": True}, {"name": "Power Two"}]}}),
        tmp_path / "assets")
    records = set()
    for scope in ("Hero_Common", "Hero_Common_Update5"):
        ef = EntityFile(corpus.read(f"EntitySettings/Heroes/Hero_Common/{scope}.entity.ot"
                                    ".EntitySettingsResource.gen"), scope)
        records |= {c.guid for c in ef.graph().components if c.override is not None}
    hc = EntityFile(corpus.read("EntitySettings/Heroes/Hero_Common/Hero_Common.entity.ot"
                                ".EntitySettingsResource.gen"), "Hero_Common")
    original = hc.component("Hero Controller").guid
    main = next(p for p in files if p.name == "Hero_Solo.entity.ot.EntitySettingsResource.gen")
    raw = main.read_bytes()
    assert not [g.hex() for g in records if g in raw]
    ef = EntityFile(raw, "Hero_Solo")
    for name in ("Skill Controller Attack One", "Skill Controller Power Two"):
        c = ef.component(name)
        f = next(f for f in EF.fields(c) if f.name == "ref_2")
        assert original in c.body[f.offset:f.offset + f.size]


def _png(path, rgba=(200, 40, 40, 255), size=8):
    import struct
    import zlib
    row = b"\x00" + bytes(rgba) * size
    def chunk(t, d):
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"\x89PNG\r\n\x1a\n"
                     + chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0))
                     + chunk(b"IDAT", zlib.compress(row * size)) + chunk(b"IEND", b""))


@needs_corpus
@needs_install
def test_a_scratch_heros_effects_are_written_not_borrowed(tmp_path):
    """`frame.effects`: an effect written from its layers (the layer's texture
    in a material of the hero's own), named `fx:<name>` by a hit and by a
    projectile's trail; it decodes as the effect it describes and is preloaded
    with the hero."""
    from rsmm.engine import vfx_codec as V
    mod = tmp_path / "mod"
    _png(mod / "art" / "leaf.png")
    files = heros.emit("m", ContentDef(kind="hero", id="Solo", fields={
        "frame": {
            "rig": "Hero_Kintaro", "mesh": "Characters\\Heroes\\Kintaro\\Kintaro_GEO.fbx",
            "material": "Characters\\Heroes\\Kintaro\\Textures\\M_Kintaro.mat.ot",
            "effects": {"Leaves": {"layers": [
                {"texture": "art/leaf.png", "burst": 12, "lifetime": [0.4, 0.8],
                 "size": [0.5, 0.9], "speed": 6, "colors": [[0.6, 1, 0.4, 1], [0.6, 1, 0.4, 0]]},
                {"material": "Materials\\Glow_Orange_01.mat.ot", "size": 3, "lifetime": 0.2}]}},
            "abilities": {"power": {
                "clip": "Characters\\Heroes\\Kintaro\\Animations\\Kintaro_Power_Out.fbx",
                "duration": 0.9, "hits": [{"at": 0.3, "fx": "fx:Leaves"}]}},
            "projectiles": {"Bean": {"model": "art/bean.glb", "trail": "fx:Leaves"}}}}),
        mod / "assets") if (mod / "art" / "bean.glb").exists() else None
    if files is None:                 # no glb at hand: the effect and the hit alone
        files = heros.emit("m", ContentDef(kind="hero", id="Solo", fields={
            "frame": {
                "rig": "Hero_Kintaro", "mesh": "Characters\\Heroes\\Kintaro\\Kintaro_GEO.fbx",
                "material": "Characters\\Heroes\\Kintaro\\Textures\\M_Kintaro.mat.ot",
                "effects": {"Leaves": {"layers": [
                    {"texture": "art/leaf.png", "burst": 12, "lifetime": [0.4, 0.8],
                     "speed": 6, "colors": [[0.6, 1, 0.4, 1], [0.6, 1, 0.4, 0]]},
                    {"material": "Materials\\Glow_Orange_01.mat.ot", "size": 3}]}},
                "abilities": {"power": {
                    "clip": "Characters\\Heroes\\Kintaro\\Animations\\Kintaro_Power_Out.fbx",
                    "duration": 0.9, "hits": [{"at": 0.3, "fx": "fx:Leaves"}]}}}}),
            mod / "assets")
    names = {p.name for p in files}
    assert "Hero_Solo_Leaves.vfx.ot.ScheduledVfxSettings.gen" in names
    assert "Hero_Solo_Leaves_1.mat.ot.Material.gen" in names
    assert "Hero_Solo_Leaves_1.png.Texture.dxt" in names
    vfx = next(p for p in files if p.name == "Hero_Solo_Leaves.vfx.ot.ScheduledVfxSettings.gen")
    raw = vfx.read_bytes()
    v = V.decode(raw)
    assert V.encode(v) == raw
    mats = [o.fields["material"] for o in v.objects
            if o.cls == "oI3dBillboardParticleRendererSettings"]
    assert mats == ["Materials\\Hero_Solo_Leaves_1.mat.ot", "Materials\\Glow_Orange_01.mat.ot"]
    main = next(p for p in files
                if p.name == "Hero_Solo.entity.ot.EntitySettingsResource.gen").read_bytes()
    assert b"Settings\\FX\\Common_FX\\Hero_Solo_Leaves.vfx.ot" in main
    cache = next(p for p in files if p.name == "Solo.herodef.UsedRscCache.ot")
    text = cache.read_text(encoding="utf-8", errors="replace")
    assert "FX|Settings\\FX\\Common_FX\\Hero_Solo_Leaves.vfx.ot|oCScheduledVfxSettings" in text
    assert "FX|Materials\\Glow_Orange_01.mat.ot|oCMaterial" in text


@needs_corpus
@needs_install
def test_blood_wolf_special_howl_animation_walk_and_audio(tmp_path):
    """Blood Wolf special:
    - Alt Secondary Ability Controller does not disable movement (value_9 = false, value_10 = false)
    - Controller points directly to State Wolf Secondary Ability (starts 8s cooldown on exit)
    - Clip plays Wolf Secondary Howl Anim (cloned from Wolf Defensive Howl, on Top Move Anim player)
    - Clip has ref_11 cleared so it cannot re-activate State Wolf Secondary Ability on loop
    - Cinebloc 0 is unlinked so no moon/trails VFX play
    - State Wolf Secondary Ability.while_active enables upper/lower split, audio, and anim clip
    """
    from rsmm.engine import entity_fields as EF
    from rsmm.engine import entity_graph_edit as EE

    abilities = [
        {"set": "Alt Secondary Ability Controller.value_9", "value": False},
        {"set": "Alt Secondary Ability Controller.value_10", "value": False},
        {"link": "Alt Secondary Ability Controller.ref_2",
         "to": "State Wolf Secondary Ability"},
        {"clone": ["Wolf Defensive Ability Anim Default"],
         "rename": {"Wolf Defensive Ability Anim Default": "Wolf Secondary Howl Anim"}},
        {"link": "Wolf Secondary Howl Anim.cinebloc[0]", "to": ""},
        {"link": "Wolf Secondary Ability Default Clip.ref_3", "to": "Wolf Secondary Howl Anim"},
        {"link": "Wolf Secondary Ability Default Clip.ref_11", "to": ""},
        {"add_link": "State Wolf Secondary Ability.while_active",
         "from": "Heroes/Hero_Common/Hero_Alt_Form_Common",
         "to": "State Anim Split Alt Form Enable"},
        {"add_link": "State Wolf Secondary Ability.while_active",
         "to": "Wolf Defensive Ability Anim Default FMod Event"},
        {"add_link": "State Wolf Secondary Ability.while_active",
         "to": "Wolf Secondary Ability Default Clip"},
    ]
    kit = {
        "pets": {
            "entity": "Enemies/Wolves/Standard_Wolf_Dire",
            "button": "special",
            "when": "State Wolf Secondary Ability",
            "spawn": "button",
            "hold": 1.0,
        }
    }
    files = _emit(tmp_path, id="BloodWolfTest", base="Red", abilities=abilities, kit=kit)
    main = next(p for p in files
                if p.name == "Hero_BloodWolfTest.entity.ot.EntitySettingsResource.gen")
    ef = EE.EntityFile(main.read_bytes(), "Hero_BloodWolfTest")

    # 1. Controller settings
    c_ctrl = ef.component("Alt Secondary Ability Controller")
    assert next(f.text for f in EF.fields(c_ctrl) if f.name == "value_9") == "bool False"
    assert next(f.text for f in EF.fields(c_ctrl) if f.name == "value_10") == "bool False"
    assert next(f.text for f in EF.fields(c_ctrl) if f.name == "value_4") == "f32 8"
    f_ref2 = next(f.text for f in EF.fields(c_ctrl) if f.name == "ref_2")
    assert "State Wolf Secondary Ability" in f_ref2

    # 2. Clip wiring
    c_clip = ef.component("Wolf Secondary Ability Default Clip")
    f_ref3 = next(f.text for f in EF.fields(c_clip) if f.name == "ref_3")
    f_ref11 = next(f.text for f in EF.fields(c_clip) if f.name == "ref_11")
    assert "Wolf Secondary Howl Anim" in f_ref3
    assert f_ref11 == "(none)"

    # 3. Howl animatic (upper body player, unlinked cinebloc 0)
    c_anim = ef.component("Wolf Secondary Howl Anim")
    f_anim_ref2 = next(f.text for f in EF.fields(c_anim) if f.name == "ref_2")
    assert "Top Move Anim Alt Form Player" in f_anim_ref2
    _cls, b0 = ef._cinebloc("Wolf Secondary Howl Anim", 0)
    a, _ = ef._only_picker(b0, "cinebloc 0")
    assert ef.objects[b0][a + 8:a + 24] == bytes(16)

    # 4. State while_active (walking split + howl audio + howl anim clip)
    c_state = ef.component("State Wolf Secondary Ability")
    f_while = next((f.text or [i.text for i in f.items])
                   for f in EF.fields(c_state) if f.name == "while_active")
    while_text = " ".join(f_while) if isinstance(f_while, list) else f_while
    assert "State Anim Split Alt Form Enable" in while_text
    assert "Wolf Defensive Ability Anim Default FMod Event" in while_text
    assert "Wolf Secondary Ability Default Clip" in while_text

    # 5. Kit pets hold timer (holds State Wolf Secondary Ability for 1.0s animation duration)
    c_tm = ef.component("Kit Pet Order Timer")
    assert next(f.text for f in EF.fields(c_tm) if f.name == "duration") == "f32 1"


@needs_corpus
@needs_install
def test_a_scratch_heros_ui_art_is_its_own(tmp_path):
    """Portrait, book portraits, new-hero picture, skin icon, codex, HUD banner
    and talent/ultimate icons: a PNG in the mod is cooked as the hero's own
    picture, named in its herodef/entity and listed in its preload cache; an
    absent one keeps the rig's."""
    from rsmm.engine import herodef_frame as HDF
    mod = tmp_path / "mod"
    for n in ("portrait", "book", "new", "skin", "c1", "banner", "icon", "ult"):
        _png(mod / "art" / f"{n}.png")
    files = heros.emit("m", ContentDef(kind="hero", id="Solo", fields={
        "frame": {
            "rig": "Hero_Kintaro", "mesh": "Characters\\Heroes\\Kintaro\\Kintaro_GEO.fbx",
            "material": "Characters\\Heroes\\Kintaro\\Textures\\M_Kintaro.mat.ot",
            "portrait": "art/portrait.png", "book": {"standard": "art/book.png"},
            "new_hero": "art/new.png", "skin_icon": "art/skin.png", "codex": ["art/c1.png"],
            "banner": "art/banner.png",
            "talents": [{"name": "Attack One", "icon": "art/icon.png"}],
            "ultimates": {"Ultimate Power 1": {"title": "U", "icon": "art/ult.png"}}}}),
        mod / "assets")
    ui = sorted(p.name for p in files if p.name.endswith(".png.Texture.dxt"))
    assert ui == sorted(f"Hero_Solo_{n}.png.Texture.dxt" for n in (
        "Portrait", "Book_Standard", "NewHero", "Skin_Default", "Codex_1", "HUD_Banner",
        "Skill_Attack_One", "Skill_Ultimate_Power_1"))
    h = HDF.decode(next(p for p in files if p.name.startswith("Solo.herodef.ot")).read_bytes())
    r = h.root
    assert r["portrait"][1].endswith("\\Hero_Solo_Portrait.png")
    assert r["book_standard"][1].endswith("\\Hero_Solo_Book_Standard.png")
    assert "Kintaro" in r["book_active"][1]                     # not given: the rig's
    assert all(c[1].endswith("\\Hero_Solo_Codex_1.png") for c in r["codex"])
    main = next(p for p in files
                if p.name == "Hero_Solo.entity.ot.EntitySettingsResource.gen").read_bytes()
    for n in ("Portrait", "HUD_Banner", "Skill_Attack_One", "Skill_Ultimate_Power_1"):
        assert f"Hero_Solo_{n}.png".encode() in main
    cache = next(p for p in files if p.name == "Solo.herodef.UsedRscCache.ot")
    text = cache.read_text(encoding="utf-8", errors="replace")
    assert all(f"Hero_Solo_{n}.png|oCTexture" in text for n in ("Portrait", "Codex_1",
                                                                 "Skill_Attack_One"))


@needs_corpus
@needs_install
def test_a_scratch_heros_talents_take_effects(tmp_path):
    """A from-scratch talent takes a rarity stat (card {0}) and an action
    (area hits each time its event fires while owned)."""
    from rsmm.engine import entity_fields as EF
    from rsmm.engine import entity_graph as EG
    files = heros.emit("m", ContentDef(kind="hero", id="Solo", fields={
        "frame": {
            "rig": "Hero_Kintaro", "mesh": "Characters\\Heroes\\Kintaro\\Kintaro_GEO.fbx",
            "material": "Characters\\Heroes\\Kintaro\\Textures\\M_Kintaro.mat.ot",
            "talents": [
                {"name": "Attack Edge", "description": "• +{0}",
                 "add_stats": [{"stat": "Crit chance basic", "values": [0.1, 0.1, 0.1, 0.1]}]},
                {"name": "Dash Burst",
                 "actions": [{"on": "dash", "hits": [{"at": 0.2, "radius": 3}]}]}]}}),
        tmp_path / "assets")
    main = next(p for p in files if p.name == "Hero_Solo.entity.ot.EntitySettingsResource.gen")
    g = {c.name: c for c in EG.parse(main.read_bytes(), "Hero_Solo").components}
    fmt = g["Skill String Desc Attack Edge"]
    assert sum(1 for f in EF.fields(fmt) if f.name.startswith("obj_")) == 1
    action = g["Skill Dash Burst Action 1"]
    acts = next(f.text for f in EF.fields(action) if f.name == "activates")
    assert "Dash Burst Action 1 Hit 1 Timer" in acts
    owned = next(f.text for f in EF.fields(g["Skill Dash Burst"]) if f.name == "while_active")
    assert "Listener" in owned


@needs_corpus
@needs_install
def test_blood_wolf_pet_talent_upgrade_branching(tmp_path):
    """Blood Wolf pet upgrade:
    - Base pet (DirewolfClaw) spawns by default, bursts on death after 8s
    - Rabid Direwolf (Skill Secondary Can Hold) upgrades spawn to DirewolfBite (20s, burst on hit)
    - Kit Pet Spawn Selector branches between base spread pos and upgrade spread pos
    - Both spawners receive PET_MASTER_ATTACK_MOVE_ORDER and PET_MASTER_RECALL_ORDER
    """
    from rsmm.engine import entity_fields as EF
    from rsmm.engine import entity_graph as EG
    from rsmm.engine import entity_graph_edit as EE

    kit = {
        "pets": {
            "entity": "Enemies/Wolves/Standard_Wolf_Dire",
            "name": "DirewolfClaw",
            "button": "special",
            "when": "State Wolf Secondary Ability",
            "spawn": "button",
            "hold": 1.0,
            "burst": "Heroes/Hero_Red/Hero_BloodWolf_Bomb",
            "burst_on_hit": False,
            "lifetime": 8,
            "talent": "Skill Secondary Can Hold",
            "upgrade": {
                "name": "DirewolfBite",
                "attack": "Bite",
                "attack_area": 1.2,
                "attack_reach": 2.0,
                "attack_range": 1.0,
                "attack_targets": 0,
                "attack_speed": 1.35,
                "attack_debuffs": False,
                "attack_cooldown": 0.5,
                "burst": "Heroes/Hero_Red/Hero_BloodWolf_Bomb",
                "burst_on_hit": True,
                "lifetime": 20,
            },
        }
    }
    skills = {
        "Secondary Can Hold": {
            "name": "Rabid Direwolf",
            "description": "Your Special calls a rabid dire wolf.",
        }
    }
    files = _emit(tmp_path, id="BloodWolfUpgradeTest", base="Red", kit=kit, skills=skills)
    main = next(p for p in files
                if p.name == "Hero_BloodWolfUpgradeTest.entity.ot.EntitySettingsResource.gen")
    ef = EE.EntityFile(main.read_bytes(), "Hero_BloodWolfUpgradeTest")

    # 1. Spawners point to their respective entities
    s_base = ef.component("Kit Pet Spawner")
    s_up = ef.component("Kit Pet Spawner Upgrade")
    assert "Hero_BloodWolfUpgradeTest_DirewolfClaw.entity.ot" in next(
        f.text for f in EF.fields(s_base) if "template" in f.name)
    assert "Hero_BloodWolfUpgradeTest_DirewolfBite.entity.ot" in next(
        f.text for f in EF.fields(s_up) if "template" in f.name)

    # 2. Tester branches between Spread Pos Upgrade and Base Spread Pos
    c_test, f_test, at = ef._field("Kit Pet Upgrade Tester", "test")
    f_true = next(f.text for f in EF.fields(c_test) if f.name == "on_true")
    f_false = next(f.text for f in EF.fields(c_test) if f.name == "on_false")
    assert "Kit Pet Spread Pos Upgrade" in f_true
    assert "Kit Pet Spread Pos" in f_false
    test_sub = ef._pointee(c_test, f_test, at)
    cls_picker = ef.cf.classes.index(
        next(x for x in ef.cf.classes if x.name == "oCEntityCpntPicker"))
    sub_bytes = bytes(ef.objects[test_sub])
    test_refs = [r.path for _pos, r in EG._pickers(sub_bytes, cls_picker)]
    assert any("Skill Secondary Can Hold" in p for p in test_refs)
    assert b"\x2a\x83\xd2\x0f" in sub_bytes

    # 3. Trigger activates Kit Pet Upgrade Tester
    c_state = ef.component("State Wolf Secondary Ability")
    f_act = next((f.text or [i.text for i in f.items])
                 for f in EF.fields(c_state) if f.name == "activates")
    act_text = " ".join(f_act) if isinstance(f_act, list) else f_act
    assert "Kit Pet Upgrade Tester" in act_text
    assert "Kit Pet Attack Order" in act_text

    # 4. Attack and Recall orders target both spawners
    owned, _ = ef.pointers()
    c_atk = ef.component("Kit Pet Attack Order")
    subs = [x for x, ptr in owned.items() if ptr.owner == c_atk.index - 1]
    pickers = []
    cls_picker = ef.cf.classes.index(
        next(x for x in ef.cf.classes if x.name == "oCEntityCpntPicker"))
    for s in subs:
        for _pos, r in EG._pickers(bytes(ef.objects[s]), cls_picker):
            pickers.append(r.path)
    assert any(p.endswith("Kit Pet Spawner") for p in pickers)
    assert any(p.endswith("Kit Pet Spawner Upgrade") for p in pickers)

    # 5. Check emitted summon entities exist
    assert any("Hero_BloodWolfUpgradeTest_DirewolfClaw.entity.ot" in p.name for p in files)
    assert any("Hero_BloodWolfUpgradeTest_DirewolfBite.entity.ot" in p.name for p in files)


@needs_corpus
@needs_install
def test_a_scratch_hero_cooks_and_uses_its_own_clips(tmp_path):
    """`frame.animations`: a glb cooked into a NEW clip of the hero's own beside
    the rig's; `anim:<name>` puts it in a slot or a button and its preload."""
    from rsmm.engine import cooked
    from rsmm.engine.cooked_schemas import animation as A
    rel = "3D/Characters/Heroes/Kintaro/Animations/Kintaro_BasicAttack01.fbx.Animation.gen"
    payload = b"".join(s.payload for s in cooked.parse(corpus.read(rel)).sections)
    (tmp_path / "chop.glb").write_bytes(A._build_glb_preview(A.parse_payload(payload), payload))
    files = heros.emit("m", ContentDef(kind="hero", id="Solo", fields={
        "frame": {
            "rig": "Hero_Kintaro", "mesh": "Characters\\Heroes\\Kintaro\\Kintaro_GEO.fbx",
            "material": "Characters\\Heroes\\Kintaro\\Textures\\M_Kintaro.mat.ot",
            "animations": {"Chop": {"source": "chop.glb", "template": "Kintaro_BasicAttack01"}},
            "slots": {"Default Idle Anim": {"clip": "anim:Chop"}},
            "abilities": {"attack": {"clip": "anim:Chop", "hits": [{"at": 0.2}]}}}}),
        tmp_path / "assets")
    clip = next(p for p in files if p.name == "Hero_Solo_Chop.fbx.Animation.gen")
    assert b"".join(s.payload for s in cooked.parse(clip.read_bytes()).sections) == payload
    main = next(p for p in files if p.name == "Hero_Solo.entity.ot.EntitySettingsResource.gen")
    assert main.read_bytes().count(b"Hero_Solo_Chop.fbx") == 2
    cache = next(p for p in files if p.name == "Solo.herodef.UsedRscCache.ot").read_bytes()
    assert b"Animations\\Hero_Solo_Chop.fbx|oCAnimation" in cache
    with pytest.raises(ContentError, match="no animations.Nope"):
        heros.emit("m", ContentDef(kind="hero", id="Solo", fields={"frame": {
            "rig": "Hero_Kintaro", "mesh": "Characters\\Heroes\\Kintaro\\Kintaro_GEO.fbx",
            "material": "Characters\\Heroes\\Kintaro\\Textures\\M_Kintaro.mat.ot",
            "slots": {"Default Idle Anim": {"clip": "anim:Nope"}}}}), tmp_path / "a2")


@needs_corpus
@needs_install
def test_a_scratch_heros_own_body_carries_its_own_skeleton(tmp_path):
    """`frame.model`: the glb is cooked onto the rig mesh and the skeleton is
    rewritten with the glb armature's rest pose (here: the rig's own, so it
    must come back as the game's)."""
    from rsmm.cli.cmd_export_character import main as export
    from rsmm.engine import skeleton_codec as SK
    glb = tmp_path / "body.glb"
    try:
        export(["Kintaro", "--clips", "", "-o", str(glb)])
    except SystemExit:
        pass
    if not glb.exists():
        pytest.skip("character export unavailable")
    files = heros.emit("m", ContentDef(kind="hero", id="Solo", fields={"frame": {
        "rig": "Hero_Kintaro", "mesh": "Characters\\Heroes\\Kintaro\\Kintaro_GEO.fbx",
        "material": "Characters\\Heroes\\Kintaro\\Textures\\M_Kintaro.mat.ot",
        "model": "body.glb"}}), tmp_path / "assets")
    geo = next(p for p in files if p.name == "Hero_Solo_GEO.fbx.Geometry.gen")
    mine = {b.name: b for b in SK.decode(geo.read_bytes()).bones}
    rig = SK.decode(corpus.read("3D/Characters/Heroes/Kintaro/Kintaro_GEO.fbx.Geometry.gen"))
    for b in rig.bones:
        assert max(abs(x - y) for x, y in zip(mine[b.name].local, b.local, strict=True)) < 1e-4
    main = next(p for p in files if p.name == "Hero_Solo.entity.ot.EntitySettingsResource.gen")
    assert b"Hero_Solo_GEO.fbx" in main.read_bytes()


@needs_corpus
@needs_install
@pytest.mark.parametrize("pets, msg", [
    ({"name": "..\\..\\Evil"}, "name is letters"),
    ({"talent": "Skill Secondary Can Hold", "upgrade": {"count": 3}}, "upgrade has no count"),
    ({"entity": "Heroes/Hero_Piper/Hero_Piper_Rat_Pet", "talent": "Skill Secondary Can Hold",
      "upgrade": {"lifetime": 5}}, "only an enemy copy"),
])
def test_kit_pets_name_and_upgrade_are_checked(tmp_path, pets, msg):
    kit = {"pets": {"entity": "Enemies/Wolves/Standard_Wolf_Dire", "button": "special",
                    "when": "State Wolf Secondary Ability", **pets}}
    with pytest.raises(ContentError, match=msg):
        _emit(tmp_path, id="PetCheck", base="Red", kit=kit)


@needs_corpus
@needs_install
def test_a_scratch_hero_keeps_each_class_in_one_run(tmp_path):
    """Every entity file a hero from scratch writes groups its components one
    run per class, as all 4,769 shipped entities do (Jack's main had 23 of 25
    classes split, its states in 66 runs, while his buttons froze)."""
    from rsmm.engine import entity_append as EA
    files = heros.emit("m", ContentDef(kind="hero", id="Solo", fields={
        "frame": {
            "rig": "Hero_Kintaro", "mesh": "Characters\\Heroes\\Kintaro\\Kintaro_GEO.fbx",
            "material": "Characters\\Heroes\\Kintaro\\Textures\\M_Kintaro.mat.ot",
            "talents": [{"name": "Attack One", "starter": True}, {"name": "Power Two"}],
            "abilities": {"power": {
                "clip": "Characters\\Heroes\\Kintaro\\Animations\\Kintaro_Power_Out.fbx",
                "duration": 0.9, "hits": [{"at": 0.3}]}}}}), tmp_path / "assets")
    ents = [p for p in files if p.name.endswith(".EntitySettingsResource.gen")]
    assert ents
    assert {p.name: EA.class_runs_split(p.read_bytes()) for p in ents} == \
        {p.name: [] for p in ents}


@needs_corpus
@needs_install
def test_a_scratch_heros_fan_turns_each_shot_through_a_yaw_value(tmp_path):
    """A fan (`angles`) turns each shot through a VALUE its aim node reads, the
    way Piper fans her notes: an inline yaw is ignored by the game (Jack's six
    beans all flew one way, playtest 2026-11-12)."""
    from rsmm.engine import entity_fields as EF
    from rsmm.engine.entity_graph_edit import EntityFile
    files = heros.emit("m", ContentDef(kind="hero", id="Solo", fields={
        "frame": {
            "rig": "Hero_Kintaro", "mesh": "Characters\\Heroes\\Kintaro\\Kintaro_GEO.fbx",
            "material": "Characters\\Heroes\\Kintaro\\Textures\\M_Kintaro.mat.ot",
            "abilities": {"special": {
                "clip": "Characters\\Heroes\\Kintaro\\Animations\\Kintaro_Power_Out.fbx",
                "duration": 0.9,
                "steps": [{"fire": "Heroes/Hero_Red/Hero_Red_Projectile_Spike",
                           "angles": [0, 90, 180]}]}}}}), tmp_path / "assets")
    main = next(p for p in files if p.name == "Hero_Solo.entity.ot.EntitySettingsResource.gen")
    ef = EntityFile(main.read_bytes(), "Hero_Solo")
    aims = sorted(c.name for c in ef.graph().components
                  if c.name.endswith(" Aim") and " Shot " in c.name)
    assert len(aims) == 3
    reads = []
    for name in aims:
        f = next(x for x in EF.fields(ef.component(name)) if x.name == "obj_4")
        yaw = f.text.rsplit("<- [Value] ", 1)[-1]
        reads.append(yaw.rsplit("\\", 1)[-1])
        assert "Hero_Piper" not in f.text
    values = {r: next(x.text for x in EF.fields(ef.component(r)) if x.name == "value")
              for r in reads if r != "Kit Aim Y Angle"}
    assert sorted(values.values()) == ["f32 1.5708", "f32 3.14159"]


@needs_corpus
@needs_install
def test_a_scratch_button_without_an_icon_wears_the_rigs(tmp_path):
    """No `icon`: the button shows the rig hero's own picture for it (a blank
    HUD button otherwise), as the rig lends its other art."""
    from rsmm.engine import hero_ability as HA
    from rsmm.engine.entity_graph_edit import EntityFile
    files = heros.emit("m", ContentDef(kind="hero", id="Solo", fields={
        "frame": {
            "rig": "Hero_Kintaro", "mesh": "Characters\\Heroes\\Kintaro\\Kintaro_GEO.fbx",
            "material": "Characters\\Heroes\\Kintaro\\Textures\\M_Kintaro.mat.ot",
            "abilities": {"power": {
                "clip": "Characters\\Heroes\\Kintaro\\Animations\\Kintaro_Power_Out.fbx",
                "duration": 0.9}}}}), tmp_path / "assets")
    main = next(p for p in files if p.name == "Hero_Solo.entity.ot.EntitySettingsResource.gen")
    pairs = HA.icons_of(EntityFile(main.read_bytes(), "Hero_Solo"), "Primary Ability Controller")
    assert pairs == [(("Ui", "Heroes\\Kintaro\\Ability_Kintaro_Mounted_Power.png"),
                      ("Ui", "Heroes\\Kintaro\\Ability_Kintaro_Mounted_Power_Disabled.png"))]
