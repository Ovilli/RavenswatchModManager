"""A clone enemy's ``ai`` table builds it an entity of its own
(`rsmm.engine.enemy_ai`): the base variant's copy with retuned numbers and a
reordered attack selector, streamed by the base's biome pool. Runs against the
real wolf corpus (skipped if absent)."""

from __future__ import annotations

from pathlib import Path

import pytest

from rsmm.engine import corpus
from rsmm.engine import enemy_ai as AI
from rsmm.engine import enemy_pools as EP
from rsmm.engine import entity_check as CK
from rsmm.engine import entity_graph as EG
from rsmm.engine import entity_parts as P
from rsmm.engine import level_placements as LP
from rsmm.sdk.content import ContentDef, ContentError, ContentRegistry
from rsmm.sdk.kinds import enemies

_BASE = "Standard_Wolf_Timber"
_BASE_REF = "Enemies\\Wolves\\Standard_Wolf_Timber.entity.ot"
_NPC = "EntitySettings/Enemies/NPC_Common/NPC_Common.entity.ot.EntitySettingsResource.gen"


def _emit(tmp_path: Path, ai: dict) -> dict[str, Path]:
    if not corpus.exists(_NPC):
        pytest.skip("vanilla enemy corpus not present")
    paths = enemies.emit("T", ContentDef("enemy", "Rabid_Wolf", {"base": _BASE, "ai": ai}),
                         tmp_path)
    return {p.name.split(".", 1)[1]: p for p in paths if "." in p.name}


def _entity(out: dict[str, Path]) -> EG.EntityGraph:
    return EG.parse(out["entity.ot.EntitySettingsResource.gen"].read_bytes(), "Rabid_Wolf")


def test_inherited_value_gets_an_override_of_the_original(tmp_path):
    g = _entity(_emit(tmp_path, {"leash": 80, "detect_radius": 12}))
    npc = {c.name: c for c in EG.parse(corpus.read(_NPC)).components}
    for name, want in (("Fighting Max Leash Distance", 80.0),
                       ("Wandering Target Detection Radius Default", 12.0)):
        c = next(c for c in g.components if c.name == name)
        # merged by the ORIGINAL part's GUID, the shape shipped overrides have
        assert c.override.guid == npc[name].guid
        assert c.override.path.endswith(f"NPC_Common\\{npc[name].group}\\{name}")
        assert P.decode(c)["value"].number() == want


def test_own_value_is_set_in_place(tmp_path):
    g = _entity(_emit(tmp_path, {"attack_max": 5}))
    hits = [c for c in g.components if c.name == "Fighting Seek Max Attack Distance"]
    assert len(hits) == 1 and P.decode(hits[0])["value"].number() == 5.0


def test_attacks_reorder_the_fighting_selector(tmp_path):
    g = _entity(_emit(tmp_path, {"attacks": ["Attack Giant Leap", "Attack Bite"]}))
    sel = next(c for c in g.components if c.name == "Bhv Fighting State Selector")
    states = [r.path.rsplit("\\", 1)[-1] for r in sel.refs if r.path.startswith("[State]")]
    assert states == ["State Fighting Leashed", "State Move UTurn", "State Attack Giant Leap",
                      "State Attack Bite", "State Fighting Seek Target Move",
                      "State Fighting Seek Target Idle", "State Fighting Target Lost"]


def test_copy_is_a_valid_entity_with_its_own_part_ids(tmp_path):
    out = _emit(tmp_path, {"leash": 80, "attacks": ["Attack Double Slash"]})
    raw = out["entity.ot.EntitySettingsResource.gen"].read_bytes()
    base = corpus.read(AI.entity_rel(_BASE_REF))
    assert not list(CK.errors(CK.check(raw, base, name="Rabid_Wolf")))
    assert not {c.guid for c in EG.parse(raw).components} & {
        c.guid for c in EG.parse(base).components}


def test_pool_streams_the_copy_and_the_def_points_at_it(tmp_path):
    out = _emit(tmp_path, {"leash": 80})
    rel = EP.pool_cooked_rel("Avalon")
    pool = (tmp_path / rel).read_bytes()
    count = len(LP._graph(LP._inner(pool)[2]).objects)
    assert count == len(LP._graph(LP._inner(EP.corpus_read(rel))[2]).objects) + 1
    assert b"Enemies\\Wolves\\Rabid_Wolf.entity.ot" in pool
    assert b"Rabid_Wolf_PoolingSettings" in pool
    cache = out["enemydef.UsedRscCache.ot"].read_text()
    assert "EntitySettings|Enemies\\Wolves\\Rabid_Wolf.entity.ot|oCEntitySettingsResource" in cache


def test_unknown_attack_lists_the_family(tmp_path):
    with pytest.raises(ContentError, match="Attack Bite"):
        _emit(tmp_path, {"attacks": ["Attack Fireball"]})


def test_ai_needs_experimental_opt_in():
    with pytest.raises(ContentError, match="experimental"):
        ContentRegistry(mod_id="T").register("enemy", id="Rabid_Wolf", base=_BASE,
                                             ai={"leash": 80})
    ContentRegistry(mod_id="T", experimental=True).register(
        "enemy", id="Rabid_Wolf", base=_BASE, ai={"leash": 80})


def test_reskin_copies_the_family_model_with_its_art_swapped(tmp_path):
    if not corpus.exists(_NPC):
        pytest.skip("vanilla enemy corpus not present")
    bite = "Characters\\Enemies\\Wolves\\Animations\\Wolf_DireTimber_Bite.fbx"
    leap = "Characters\\Heroes\\Kintaro\\Animations\\Bear_Kintaro_Leap.fbx"
    paths = enemies.emit("T", ContentDef("enemy", "Bear_Wolf", {
        "base": _BASE, "reskin": {bite: leap}}), tmp_path)
    model = tmp_path / AI.entity_rel("Enemies\\Wolves\\Bear_Wolf_Model.entity.ot")
    leaf = tmp_path / AI.entity_rel("Enemies\\Wolves\\Bear_Wolf.entity.ot")
    assert model in paths and leaf in paths
    assert bite.encode() not in model.read_bytes() and leap.encode() in model.read_bytes()
    from rsmm.engine import entity_components as ECM
    assert ECM.parents(leaf.read_bytes()) == ["Enemies\\Wolves\\Bear_Wolf_Model.entity.ot"]
    cache = (tmp_path / "Definitions/Enemies/Bear_Wolf.enemydef.UsedRscCache.ot").read_text()
    assert f"3D|{leap}|oCAnimation" in cache
    assert "EntitySettings|Enemies\\Wolves\\Bear_Wolf_Model.entity.ot|" in cache


def test_reskin_refuses_art_the_enemy_does_not_use(tmp_path):
    if not corpus.exists(_NPC):
        pytest.skip("vanilla enemy corpus not present")
    with pytest.raises(ContentError, match="does not use"):
        enemies.emit("T", ContentDef("enemy", "Bear_Wolf", {
            "base": _BASE, "reskin": {"Characters\\Nope.fbx": "Characters\\Other.fbx"}}),
            tmp_path)


def test_new_attack_is_a_renamed_copy_with_its_own_animation(tmp_path):
    if not corpus.exists(_NPC):
        pytest.skip("vanilla enemy corpus not present")
    clap = "Characters\\Heroes\\Kintaro\\Animations\\Bear_Kintaro_Nekodamashi.fbx"
    paths = enemies.emit("T", ContentDef("enemy", "Clap_Wolf", {"base": _BASE, "ai": {
        "new_attacks": [{"name": "Attack Clap", "from": "Attack Double Slash",
                         "animations": {"Attack Double Combo Anim": clap},
                         "values": {"Attack Double Slash Traverser Base Radius Value": 4.5}}],
        "attacks": ["Attack Clap", "Attack Bite"]}}), tmp_path)
    model = tmp_path / AI.entity_rel("Enemies\\Wolves\\Clap_Wolf_Model.entity.ot")
    assert model in paths
    g = EG.parse(model.read_bytes(), "Clap_Wolf_Model")
    clone = {c.name: c for c in g.components if c.group == "Attack Clap"}
    src = [c for c in g.components if c.group == "Attack Double Slash"]
    assert len(clone) == len(src)                      # the whole group, nothing shared
    assert {"State Attack Clap", "Attack Clap Condition"} <= set(clone)
    anim = clone["Attack Double Combo Anim Attack Clap"]
    assert any(lit == clap for lit in anim.literals)
    assert not {c.guid for c in clone.values()} & {c.guid for c in src}
    radius = clone["Attack Clap Traverser Base Radius Value"]
    assert P.decode(radius)["value"].number() == 4.5
    leaf = EG.parse((tmp_path / AI.entity_rel("Enemies\\Wolves\\Clap_Wolf.entity.ot"))
                    .read_bytes(), "Clap_Wolf")
    sel = next(c for c in leaf.components if c.name == "Bhv Fighting State Selector")
    assert clone["State Attack Clap"].guid in {r.guid for r in sel.refs}


def test_new_attack_from_an_unknown_group_lists_the_family(tmp_path):
    if not corpus.exists(_NPC):
        pytest.skip("vanilla enemy corpus not present")
    with pytest.raises(ContentError, match="Attack Giant Leap"):
        enemies.emit("T", ContentDef("enemy", "X_Wolf", {"base": _BASE, "ai": {
            "new_attacks": [{"name": "Attack Clap", "from": "Attack Fireball"}]}}), tmp_path)


def _hit_times(entity: bytes, stem: str, part: str, event: bytes) -> list[float]:
    import struct

    from rsmm.engine.entity_graph_edit import EntityFile
    ef = EntityFile(entity, stem)
    c = ef.component(part)
    owned, _ = ef.pointers()
    return [struct.unpack_from("<f", ef.objects[x], 4)[0] for x, p in owned.items()
            if p.owner == c.index - 1 and event in bytes(ef.objects[x])]


def test_a_swapped_animation_keeps_its_hits_inside_the_new_clip(tmp_path):
    """The hit is a timed activation in seconds and the state ends with the
    clip, so a shorter animation on the old timeline never hits (a fish slam on
    the leap's 1.45 s, in game 2026-10-29). Times scale by the clip lengths."""
    if not corpus.exists(_NPC):
        pytest.skip("vanilla enemy corpus not present")
    wolf = "Characters\\Enemies\\Wolves\\Animations\\Wolf_Alpha_GiantLeap.fbx"
    fish = "Characters\\Heroes\\Kintaro\\Animations\\Kintaro_Bear_FishSlam_Ultimate1_In.fbx"
    a, b = AI.anim_duration(wolf), AI.anim_duration(fish)
    assert a and b and b < a
    enemies.emit("T", ContentDef("enemy", "Fish_Wolf", {"base": _BASE, "ai": {
        "new_attacks": [{"name": "Attack Fish", "from": "Attack Giant Leap",
                         "animations": {"Attack Giant Leap Anim": fish}}]},
        "reskin": {wolf: fish}}), tmp_path)
    model = (tmp_path / AI.entity_rel("Enemies\\Wolves\\Fish_Wolf_Model.entity.ot")).read_bytes()
    shipped = corpus.read(AI.entity_rel("Enemies\\Wolves\\Wolves_Model.entity.ot"))
    (before,) = _hit_times(shipped, "Wolves_Model", "Attack Giant Leap Anim",
                           b"Event Attack Giant Leap")
    assert before > b                                   # the bug: past the end of the clip
    for part, ev in (("Attack Giant Leap Anim", b"Event Attack Giant Leap"),   # reskin
                     ("Attack Fish Anim", b"Event Attack Fish")):              # new attack
        (t,) = _hit_times(model, "Fish_Wolf_Model", part, ev)
        assert abs(t - before * b / a) < 1e-3 and t < b
