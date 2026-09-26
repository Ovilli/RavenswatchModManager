"""`hero` kind: a clone is a new herodef + its own resource cache.

The hero-select roster is every registered oCDtHeroDefinition (FUN_140209b00
copies Registry_EnumInstances unfiltered), so these two files are the whole
contract — the same self-registration the enemy clone proved in game.
"""

from __future__ import annotations

import re

import pytest

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
    assert gen.read_bytes() == EP.corpus_read(
        "Definitions/Heroes/Piper.herodef.ot.DtHeroDefinition.gen")
    lines = RC.parse(cache.read_bytes())
    assert lines == sorted(lines)
    assert "Definitions|Heroes\\Zz_Piper_Clone.herodef.ot|oCDtHeroDefinition" in lines
    assert not any("Heroes\\Piper.herodef.ot" in ln for ln in lines)


@needs_corpus
@pytest.mark.parametrize("fields,msg", [
    ({"base": "Carmilla"}, "paid DLC"),
    ({"base": "Merlin"}, "paid DLC"),
    ({"base": "Nobody"}, "no shipped hero"),
    ({"display_name": "X"}, "unsupported field"),
])
def test_bad_clones_are_refused(tmp_path, fields, msg):
    with pytest.raises(ContentError, match=msg):
        _emit(tmp_path, **fields)


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
    vd = EP.corpus_read("Definitions/Versions/LiveOps5.versiondef.ot.rsionDefinition.gen")
    co, _, cnt = A._find_hero_vector(vd)
    assert cnt == 12
    out = A._patch_versiondef_heroes(vd, [rel])
    co2, _, cnt2 = A._find_hero_vector(out)
    entries = [e[2] for e in A._mo_vector_entries(out, co2, cnt2)]
    assert cnt2 == 13 and entries[-1] == rel and entries[:12] == [
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
def test_a_custom_hero_id_must_be_a_plain_name(tmp_path):
    with pytest.raises(ContentError, match="letters and digits|reserved"):
        _emit(tmp_path, id="Kintaro", name="X")


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
