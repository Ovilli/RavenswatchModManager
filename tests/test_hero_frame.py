"""A hero written from scratch (engine/hero_frame.py): the FX frame inherits the
shared base through an alias, and a filled slot is exactly what a shipped hero
writes for it."""

from __future__ import annotations

import pytest

from rsmm.engine import cooked
from rsmm.engine import hero_frame as HF

_GEPPETTO = "Heroes\\Hero_Geppetto\\Hero_Geppetto.entity.ot"


def _read(ref: str):
    from rsmm.engine import corpus
    return corpus.read("EntitySettings/" + ref.replace("\\", "/") + ".EntitySettingsResource.gen")


def _install():
    from rsmm.cli.apply_mods import find_game_dir
    try:
        return find_game_dir()
    except Exception:  # noqa: BLE001 — no install reachable
        return None


def _corpus() -> bool:
    try:
        return _read(HF.HERO_COMMON) is not None
    except Exception:  # noqa: BLE001
        return False


needs_install = pytest.mark.skipif(_install() is None, reason="no game install")
needs_corpus = pytest.mark.skipif(not _corpus(), reason="no hero corpus")



def test_fx_frame_inherits_through_one_alias():
    alias, identity = bytes(range(16)), bytes(range(16, 32))
    raw = HF.fx_frame(alias, identity)
    cf = cooked.parse(raw)
    assert cooked.emit(cf) == raw
    names = [c.name for c in cf.classes]
    picker = names.index("AliasPicker")
    # One object, the picker, holding the alias; the trailer lists it as the
    # alias parent after an empty parent list (Hero_Geppetto_FX's shape).
    assert cf.sections[0].payload == bytes.fromhex("01000000") + picker.to_bytes(4, "little")
    assert cf.sections[1].payload == picker.to_bytes(4, "little") + alias
    t = cf.sections[-1].payload
    assert t.endswith(identity + bytes(4) + b"\xff" * 4 + bytes.fromhex("0100000000000000")
                      + bytes(4) + cooked.MARK_END)


@needs_corpus
@needs_install
@pytest.mark.parametrize("slot, fill", [
    ("Deathdoor Anim In", {"clip": "Characters\\Heroes\\Geppetto\\Animations\\"
                                   "Geppetto_Deathdoor_In.fbx", "duration": 1.7166666}),
    ("Portrait Picture", {"texture": ("Ui", "Heroes\\Geppetto\\Portrait_Geppetto_01.png")}),
])
def test_a_filled_slot_is_what_a_shipped_hero_writes(slot, fill):
    from rsmm.engine import entity_fields as EF
    from rsmm.engine import entity_graph as EG
    from rsmm.engine.entity_graph_edit import EntityFile
    ef = EntityFile(HF.main_frame("Heroes\\Hero_Jack\\Hero_Jack_FX.entity.ot",
                                  HF.guid("Jack", "main")), "Hero_Jack")
    HF.fill_slot(ef, HF.common(_read), slot, seed="t", **fill)
    mine = next(c for c in EG.parse(ef.to_bytes(), "Hero_Jack").components if c.name == slot)
    shipped = next(c for c in EG.parse(_read(_GEPPETTO), "Hero_Geppetto").components
                   if c.name == slot)
    assert mine.override.guid == shipped.override.guid
    assert mine.override.path == shipped.override.path
    assert [(f.name, f.text) for f in EF.fields(mine)] == \
        [(f.name, f.text) for f in EF.fields(shipped)]


@needs_corpus
@needs_install
def test_a_slot_is_filled_once_and_only_with_its_own_kind():
    from rsmm.engine.entity_graph_edit import EntityFile
    ef = EntityFile(HF.main_frame("Heroes\\Hero_Jack\\Hero_Jack_FX.entity.ot",
                                  HF.guid("Jack", "main")), "Hero_Jack")
    base = HF.common(_read)
    with pytest.raises(HF.FrameError, match="not an animation"):
        HF.fill_slot(ef, base, "Portrait Picture", clip="x.fbx", seed="t")
    ef = EntityFile(HF.main_frame("Heroes\\Hero_Jack\\Hero_Jack_FX.entity.ot",
                                  HF.guid("Jack", "main")), "Hero_Jack")
    HF.fill_slot(ef, base, "Deathdoor Anim In", clip="x.fbx", seed="t")
    with pytest.raises(HF.FrameError, match="already filled"):
        HF.fill_slot(ef, base, "Deathdoor Anim In", clip="y.fbx", seed="t")
    with pytest.raises(HF.FrameError, match="no slot"):
        HF.fill_slot(ef, base, "Nope", seed="t")


def _hero(scope: str = "Hero_Geppetto"):
    from rsmm.engine.entity_graph_edit import EntityFile
    return EntityFile(HF.main_frame(f"Heroes\\{scope}\\{scope}_FX.entity.ot",
                                    HF.guid(scope, "main")), scope)


def _same(mine, shipped, names):
    from rsmm.engine import entity_fields as EF
    from rsmm.engine import entity_graph as EG
    a = {c.name: c for c in EG.parse(mine, "Hero_Geppetto").components}
    b = {c.name: c for c in EG.parse(shipped, "Hero_Geppetto").components}
    for n in names:
        assert [(f.name, f.text) for f in EF.fields(a[n])] == \
            [(f.name, f.text) for f in EF.fields(b[n])], n


@needs_corpus
@needs_install
def test_body_and_talent_card_are_what_a_shipped_hero_writes():
    """Geppetto's own values through the writers come out as Geppetto's parts."""
    from rsmm.engine import entity_graph as EG
    from rsmm.engine.entity_graph_edit import EntityFile
    ef = _hero()
    HF.fill_body(ef, HF.common(_read, "Character_Common"),
                 mesh="Characters\\Heroes\\Geppetto\\Geppetto_GEO.fbx",
                 material="Dt_SkinnedGreyColor.mat.ot", seed="t")
    HF.add_talent(ef, HF.common(_read), "Dash Deals Damage",
                  bank="Hero_Geppetto_Common~GAM.xls",
                  name_key="Skill_Dash_Deals_Damage_Name",
                  desc_key="Skill_Dash_Deals_Damage_Desc",
                  icon="Heroes\\Geppetto\\Skill Dash Deals Damage.png", seed="t",
                  pool=HF.POOL_STARTER)   # one of Geppetto's starting cards
    out = ef.to_bytes()
    filled = {c.override.guid: (c.override.path.split("]")[0][1:], c.path)
              for c in EG.parse(out, "Hero_Geppetto").components if c.override}
    ef = EntityFile(out, "Hero_Geppetto")
    assert HF.relabel_base_links(ef, filled, "Hero_Geppetto") == 1
    _same(ef.to_bytes(), _read(_GEPPETTO),
          ["Mesh Skeleton", "Character Mesh", "Skill Controller Dash Deals Damage"])


@needs_corpus
@needs_install
def test_a_skin_is_what_a_shipped_skin_is():
    import re

    from rsmm.engine import entity_fields as EF
    from rsmm.engine import entity_graph as EG
    raw = _read("Heroes\\Hero_Geppetto\\Hero_Geppetto_Default.entity.ot")
    alias = cooked.parse(raw).sections[5].payload[4:]
    shipped = EG.parse(raw, "Hero_Geppetto_Default").components
    values = []
    for c in shipped:
        root, path = re.findall(r"'([^']*)'",
                                next(f.text for f in EF.fields(c) if f.name == "value"))
        values.append((c.name, c.group, c.override.guid, c.override.path, root,
                       path.replace("\\\\", "\\")))
    out = HF.skin_frame(alias, bytes(16), values, seed="t")
    assert alias in out
    mine = {c.name: c for c in EG.parse(out, "Hero_Geppetto_Default").components}
    for c in shipped:
        assert mine[c.name].override.path == c.override.path
        assert [(f.name, f.text) for f in EF.fields(mine[c.name])] == \
            [(f.name, f.text) for f in EF.fields(c)]


@needs_corpus
@needs_install
def test_an_ability_is_written_from_data():
    """A button = the base's controller slot -> a state of the hero's own that
    aims, plays its clip, hits at its times and ends (hero_ability)."""
    from rsmm.engine import entity_fields as EF
    from rsmm.engine import entity_graph as EG
    from rsmm.engine import hero_ability as HA
    ef = _hero("Hero_T")
    ab = HA.Ability.parse("power", {
        "clip": "Characters\\Heroes\\Kintaro\\Animations\\Kintaro_Power_Out.fbx",
        "duration": 0.9, "cooldown": 6, "hits": [{"at": 0.35, "radius": 3.5, "damage": 150}]})
    assert HA.build(ef, HF.common(_read), ab, seed="t") == "State Power Ability"
    out = ef.to_bytes()
    g = {c.name: c for c in EG.parse(out, "Hero_T").components}

    def f(name):
        return {x.name: x.text for x in EF.fields(g[name])}
    ctl = f("Primary Ability Controller")
    assert ctl["ref_2"].endswith("\\State Power Ability") and ctl["value_4"] == "f32 6"
    assert g["Primary Ability Controller"].override.path.startswith("[Ability Controller]") \
        or g["Primary Ability Controller"].override is not None
    state = f("State Power Ability")
    assert "Power Ability Hit 1 Timer" in state["activates"]
    assert "Power Ability End Timer" in state["activates"]
    assert "Power Ability Clip Selector" in state["while_active"]
    assert f("Power Ability Hit 1 Timer")["on_end"].endswith("\\Event Power Ability Hit 1")
    assert f("Power Ability End Timer")["state"].endswith("\\State Power Ability")
    assert f("Power Ability Hit 1 Radius")["value"] == "f32 3.5"
    assert f("Power Ability Hit 1 Damage")["value_28"] == "f32 1.5"
    assert f("Power Ability Clip")["ref_11"].endswith("\\State Power Ability")
    # Nothing of any hero's: only the shared base and the hero itself.
    import re
    assert set(re.findall(rb"\] (Hero_[A-Za-z_0-9]+)\\", out)) <= {
        b"Hero_Common", b"Hero_Common_Update5", b"Hero_T"}
    with pytest.raises(HA.AbilityError, match="clip"):
        HA.Ability.parse("power", {"cooldown": 1})


@needs_corpus
def test_a_hit_can_stun_knock_back_stagger_and_apply_a_status():
    """A hit's extras land in its damage record: stun / knockback / stagger
    fields (``HIT_FIELDS``) and, for ``status``, a copied shipped debuff whose
    switch is the ability's own state (on only while the button runs)."""
    from rsmm.engine import entity_fields as EF
    from rsmm.engine import entity_graph as EG
    from rsmm.engine import entity_graph_edit as GE
    from rsmm.engine import hero_ability as HA
    ef = _hero("Hero_T")
    ab = HA.Ability.parse("power", {
        "clip": "Characters\\Heroes\\Kintaro\\Animations\\Kintaro_Power_Out.fbx",
        "duration": 0.9, "cooldown": 6,
        "hits": [{"at": 0.35, "radius": 3.5, "damage": 150, "stun": 1.5, "knockback": 40,
                  "stagger": 10, "status": "Rooted"}]})
    HA.build(ef, HF.common(_read), ab, seed="t")
    out = ef.to_bytes()
    g = {c.name: c for c in EG.parse(out, "Hero_T").components}
    dmg = {x.name: x.text for x in EF.fields(g["Power Ability Hit 1 Damage"])}
    assert dmg["value_27"] == "f32 1.5"
    assert dmg["value_4"] == "f32 40"
    assert dmg["value_31"] == "f32 10"
    mod = "Skill Power Ability Rooted On Power Ability Hit 1 Damage"
    assert mod in g
    # the damage's debuff list now holds a debuff naming that modifier
    ef2 = GE.EntityFile(out, "Hero_T")
    debuffs = [p for i, p in enumerate(ef2.objects)
               if ef2._class(i) == "oCDtDamageDebuffSettings" and g[mod].guid in p]
    assert debuffs
    with pytest.raises(HA.AbilityError, match="status"):
        HA.parse_hits([{"at": 0.1, "status": "Sleepy"}], "x")
    with pytest.raises(HA.AbilityError, match="stun"):
        HA.parse_hits([{"at": 0.1, "stun": 99}], "x")


@needs_corpus
def test_a_hit_counts_as_its_buttons_damage():
    """Per-ability stats key on the damage record's type (value_35): a button's
    hits carry its ability's, not the donor explosion's -1 (none)."""
    from rsmm.engine import entity_fields as EF
    from rsmm.engine import entity_graph as EG
    from rsmm.engine import hero_ability as HA
    for slot, want in (("attack", 0), ("special", 2), ("trait", 4), ("ultimate2", 5)):
        ef = _hero("Hero_T")
        ab = HA.Ability.parse(slot, {
            "clip": "Characters\\Heroes\\Kintaro\\Animations\\Kintaro_Power_Out.fbx",
            "duration": 0.9, "hits": [{"at": 0.3}]})
        HA.build(ef, HF.common(_read), ab, seed="t")
        g = {c.name: c for c in EG.parse(ef.to_bytes(), "Hero_T").components}
        word = slot.title()
        dmg = {x.name: x.text for x in EF.fields(g[f"{word} Ability Hit 1 Damage"])}
        assert dmg["value_35"] == f"int {want}", slot


@needs_corpus
def test_a_talent_card_is_dealt_at_level_up():
    """A talent controller's ``bytes_4`` is its offer pool: 1 = the level-up
    pool, as on every ordinary shipped talent; 0 = the starting pick. All-0 cards
    gave an empty level-up pick in game; none in 0, an empty starting pick."""
    from rsmm.engine import entity_fields as EF
    from rsmm.engine import entity_graph as EG
    ef = _hero("Hero_T")
    hc = HF.common(_read)
    HF.add_talent(ef, hc, "Attack Sharp", bank="B", name_key="n", desc_key="d", icon="", seed="t")
    HF.add_talent(ef, hc, "Attack Quest", bank="B", name_key="n", desc_key="d", icon="",
                  seed="t", pool=HF.POOL_STARTER)
    g = {c.name: c for c in EG.parse(ef.to_bytes(), "Hero_T").components}

    def pool(n):
        return next(f.text for f in EF.fields(g[f"Skill Controller {n}"]) if f.name == "bytes_4")
    assert pool("Attack Sharp") == "01 00 00 00"
    assert pool("Attack Quest") == "00 00 00 00"


@needs_corpus
def test_a_projectile_of_the_heros_own_wears_its_own_look():
    """attack_build.projectile_entity: the generic hero projectile with the
    mod's mesh, material, trail, impact and lifetime (no base hero needed)."""
    import re

    from rsmm.engine import attack_build as AB
    from rsmm.engine import entity_fields as EF
    from rsmm.engine import entity_graph as EG
    raw = AB.projectile_entity(
        {"model": "bean.glb", "albedo": "bean.png", "lifetime": 0.6,
         "trail": "Settings\\Heroes\\Hero_Kintaro_FX\\Kintaro_Skill_Forest_Spirit_Trail.vfx.ot"},
        stem="Hero_T_Bean", tag="T_Bean", what="projectiles.Bean",
        mesh=lambda *a: "Characters\\Heroes\\T\\T_Bean_GEO.fbx",
        material=lambda *a: "Characters\\Heroes\\T\\Textures\\M_T_Bean.mat.ot")
    names = {m.decode() for m in re.findall(rb"[ -~]+?\.(?:fbx|mat\.ot|vfx\.ot)", raw)}
    assert "Characters\\Heroes\\T\\T_Bean_GEO.fbx" in names
    assert "Characters\\Heroes\\T\\Textures\\M_T_Bean.mat.ot" in names
    assert "Settings\\Heroes\\Hero_Kintaro_FX\\Kintaro_Skill_Forest_Spirit_Trail.vfx.ot" in names
    assert AB.TEMPLATE_MESH not in names and AB.TEMPLATE_MAT not in names
    g = EG.parse(raw)
    life = next(c for c in g.components if c.name == "Lifetime Duration")
    assert next(f.text for f in EF.fields(life) if f.name == "value") == "f32 0.6"
    with pytest.raises(AB.AttackError, match="model"):
        AB.projectile_entity({}, stem="x", tag="x", what="x", mesh=None, material=None)


def test_kit_forward_is_checked():
    from rsmm.engine import hero_kit as HK
    assert HK.timeline([{"hit": {"radius": 3}, "forward": 2.5}])[0][1]["forward"] == 2.5
    with pytest.raises(HK.KitError, match="forward"):
        HK.timeline([{"hit": {"radius": 3}, "forward": 99}])


@needs_corpus
def test_a_talent_controller_starts_active_like_a_shipped_one():
    """Only ultimate upgrades start inactive; a talent copied from one must not,
    or it never registers in the offer pools (empty pick, compendium crash)."""
    from rsmm.engine import talent_add_stat as TA
    ef = _hero("Hero_T")
    HF.add_talent(ef, HF.common(_read), "Attack Sharp", bank="B", name_key="n", desc_key="d",
                  icon="", seed="t")
    assert TA._flags_of(ef, "Skill Controller Attack Sharp") == 0x1000101   # = Kintaro's talents


@needs_corpus
def test_an_attack_slot_is_switched_like_a_shipped_basic_attack():
    """A state-driven attack is interruptible, has no cooldown and takes the
    basic-attack input, as Carmilla's and Melusine's are; the base's empty slot
    has all three the other way (the hero could not attack)."""
    from rsmm.engine import entity_fields as EF
    from rsmm.engine import entity_graph as EG
    from rsmm.engine import hero_ability as HA
    ef = _hero("Hero_T")
    ab = HA.Ability.parse("attack", {
        "clip": "Characters\\Heroes\\Kintaro\\Animations\\Kintaro_Power_Out.fbx",
        "duration": 0.6, "cooldown": 0.1, "hits": [{"at": 0.3}]})
    HA.build(ef, HF.common(_read), ab, seed="t")
    g = {c.name: c for c in EG.parse(ef.to_bytes(), "Hero_T").components}
    ctl = {x.name: x.text for x in EF.fields(g["Basic Attack Controller"])}
    assert (ctl["value_4"], ctl["value_8"], ctl["value_11"], ctl["value_14"]) == \
        ("f32 0", "bool True", "bool False", "bool True")


@needs_corpus
def test_a_hit_wears_its_own_look():
    """`fx` swaps the donor explosion's look (Red's bomb) in that hit's own
    effect copies only; another hit keeps the default."""
    import re

    from rsmm.engine import hero_ability as HA
    ef = _hero("Hero_T")
    vfx = "Settings\\Heroes\\Hero_Kintaro_FX\\Kintaro_Axe_impact_01.vfx.ot"
    ab = HA.Ability.parse("power", {
        "clip": "Characters\\Heroes\\Kintaro\\Animations\\Kintaro_Power_Out.fbx",
        "duration": 0.9, "hits": [{"at": 0.2, "fx": vfx}, {"at": 0.5}]})
    HA.build(ef, HF.common(_read), ab, seed="t")
    names = [m.decode() for m in re.findall(rb"[ -~]+?\.vfx\.ot", ef.to_bytes())]
    assert names.count(vfx) == 1 and names.count(HA.DONOR_FX) == 1
    with pytest.raises(HA.AbilityError, match="fx"):
        HA.parse_hits([{"at": 0.1, "fx": "fire.png"}], "x")


@needs_corpus
def test_hits_do_not_shake_unless_asked_and_a_button_shows_its_range():
    """Every hit shook the camera (the donor explosion's shake); now none does
    unless `shake` says so. `indicator` adds Red's warning disc, sized, placed
    ahead and tinted, shown while the button's state runs."""
    import re

    from rsmm.engine import entity_fields as EF
    from rsmm.engine import entity_graph as EG
    from rsmm.engine import hero_ability as HA
    ef = _hero("Hero_T")
    ab = HA.Ability.parse("power", {
        "clip": "Characters\\Heroes\\Kintaro\\Animations\\Kintaro_Power_Out.fbx",
        "duration": 0.9, "hits": [{"at": 0.2}, {"at": 0.5, "shake": "light"}],
        "indicator": {"radius": 3.5, "forward": 2.5, "color": [0.5, 0.9, 0.3, 1]}})
    HA.build(ef, HF.common(_read), ab, seed="t")
    out = ef.to_bytes()
    from rsmm.engine import projectile_frame as PF
    played = []                          # each hit's Fx part: the effects it plays
    for c in ef.graph().components:
        if c.cls == "oCEntityCpntFxSettings" and c.name.endswith(" Fx"):
            played.append(sorted(m.decode() for i in PF._fx_ids(ef, c.name)
                                 for m in re.findall(rb"[ -~]+?\.vfx\.ot", ef.objects[i])))
    shakes = [[n for n in p if "Camera_Shake" in n] for p in played]
    assert sorted(shakes) == [[], [HA.SHAKES["light"]]]
    assert not any("Kintaro" in n for p in played for n in p)
    g = {c.name: c for c in EG.parse(out, "Hero_T").components}
    disc = {f.name: f.text for f in EF.fields(g["Power Ability Indicator"])}
    assert disc["obj_3"].count("Power Ability Indicator Size") == 2 and "f32 2.5" in disc["obj_4"]
    assert "Kintaro" not in disc["obj_3"] + disc["obj_4"] and disc["value_10"] == "f32 3.5"
    size = {f.name: f.text for f in EF.fields(g["Power Ability Indicator Size"])}
    assert size["value"] == "f32 7"
    assert "Power Ability Indicator" in {f.name: f.text for f in
                                         EF.fields(g["State Power Ability"])}["while_active"]
    with pytest.raises(HA.AbilityError, match="shake"):
        HA.parse_hits([{"at": 0.1, "shake": "huge"}], "x")


@needs_corpus
def test_ultimate_cards_and_hand_weapon_are_the_heros_own():
    """The six ultimate cards are overrides of Hero_Common's (as Kintaro's are),
    with the hero's text (power cards: through their name format too) and an
    upgrade's own state; the hand weapon is a shipped hero's override hung on
    the shared Character Mesh at the donor's bone."""
    from rsmm.engine import entity_fields as EF
    from rsmm.engine import entity_graph as EG
    from rsmm.engine.entity_graph_edit import EntityFile
    ef = _hero("Hero_T")
    hc, cc = HF.common(_read), HF.common(_read, "Character_Common")
    for n in HF.ULTIMATES:
        HF.fill_ultimate(ef, hc, n, bank="B", name_key=f"{n}_N", desc_key=f"{n}_D", seed="t")
    kin = EntityFile(_read("Heroes\\Hero_Kintaro\\Hero_Kintaro.entity.ot"), "Hero_Kintaro")
    HF.add_weapon(ef, kin, cc, seed="t")
    g = {c.name: c for c in EG.parse(ef.to_bytes(), "Hero_T").components}

    def f(n):
        return {x.name: x.text for x in EF.fields(g[n])}
    for n in HF.ULTIMATES:
        assert g[f"Skill Controller {n}"].override is not None
        assert f"'{n}_D'" in f(f"Skill String Desc {n}")["value_2"]
    upgrade = f("Skill Controller Ultimate 1 Upgrade 1")
    assert upgrade["ref_3"].endswith("\\Skill Ultimate 1 Upgrade 1")
    assert "'Ultimate Power 1_N'" in f("Skill String Name Ultimate Power 1")["value_2"]
    w = f(HF.WEAPON_SLOT)
    assert w["obj_2"].startswith("<- [3d graphic object] Character_Common\\Base\\Character Mesh")
    assert "'DEF.Weapon.R'" in w["obj_2"] and b"Kintaro_Axe_GEO.fbx" in g[HF.WEAPON_SLOT].body
    with pytest.raises(HF.FrameError, match="one of"):
        HF.fill_ultimate(ef, hc, "Ultimate 3", bank="B", name_key="n", desc_key="d")
