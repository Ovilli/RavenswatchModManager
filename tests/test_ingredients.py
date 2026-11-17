"""The `ingredient` kind: a new carried resource, its pickups and its hand-in."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from rsmm.engine import corpus, named_id
from rsmm.engine import entity_fields as EF
from rsmm.engine import entity_strings as ES
from rsmm.engine import prop_cook as PC
from rsmm.engine.entity_graph_edit import EntityFile
from rsmm.sdk.content import ContentError, ContentRegistry
from rsmm.sdk.kinds import ingredients as ING


def _needs(rel: str) -> bytes:
    raw = corpus.read(rel)
    if raw is None:
        pytest.skip(f"{rel} not readable (no mirror or install)")
    return raw


def _field(raw: bytes, comp: str, name: str) -> str:
    fl = {f.name: f.text for f in EF.fields(EntityFile(raw, "x").component(comp))}
    return fl[name]


def test_ingredient_ids_are_the_engine_name_hash():
    # The u32 every pickup / delivery point stores is NamedEvent_Id_FromCrc(0, crc32(name)).
    assert named_id.of("Straw") == 0xE9F9A52E
    assert named_id.of("Stone") == 0x51F94A7C
    assert named_id.of("Wood") == 0x48B35820
    assert named_id.of("Key") == 0xC4CB986E
    assert named_id.of("Bean") == 0xF0D7307D


@pytest.mark.parametrize("name", ["Straw", "Stone", "Wood"])
def test_shipped_pickups_store_the_named_id(name):
    raw = _needs(PC.entity_cooked_path(
        f"DarkHills\\Objects_3Pigs\\Collectible_Material_{name}.entity.ot"))
    assert named_id.to_bytes(name) in raw


def _emit(tmp_path: Path, **fields) -> tuple[list[Path], Path]:
    _needs(ING.def_path("Straw"))
    out = tmp_path / "assets"
    out.mkdir()
    cr = ContentRegistry(mod_id="test-mod", experimental=True)
    cr.register("ingredient", id="fish", **fields)
    return cr.emit(out), out


def test_new_ingredient_def_and_cache(tmp_path):
    files, out = _emit(tmp_path, name="Fish")
    gen = out / ING.def_path("Fish")
    assert gen in files
    doc = json.loads(ING._handler().decode_cooked(gen.read_bytes()))
    assert doc["name"] == "Fish"
    cache = (out / "Definitions/Ingredients/Fish.ingredientdef.UsedRscCache.ot").read_text()
    assert cache.startswith(
        "Definitions|Ingredients\\Fish.ingredientdef.ot|oCDtIngredientDefinition\n")


def test_base_ingredient_round_trips_byte_identical():
    raw = _needs(ING.def_path("Straw"))
    h = ING._handler()
    assert h.encode_container(h.decode_cooked(raw)) == raw


def test_shipped_names_are_refused(tmp_path):
    with pytest.raises(ContentError, match="shipped"):
        _emit(tmp_path, name="Straw")


def test_pickup_clone_grants_the_new_ingredient(tmp_path):
    _needs(PC.entity_cooked_path(ING.PICKUP_BASE))
    _files, out = _emit(tmp_path, name="Fish", pickups=[
        {"id": "pile", "count": 4,
         "look": "DarkHills\\SceneryObjects_DarkHills\\Fishes_Ground_A.entity.ot"}])
    ref = ING.pickup_ref("Fish", "pile")
    raw = (out / PC.entity_cooked_path(ref)).read_bytes()
    assert _field(raw, "Dt Ingredient Gain", "bytes_1") == named_id.to_bytes("Fish").hex(" ")
    assert _field(raw, "Dt Ingredient Gain", "value_2") == "int 4"
    # still on the ground, not spinning and bobbing like the key it is cloned from
    assert _field(raw, "Key Rotation Angle Value", "value_3") == "f32 0"
    assert _field(raw, "Y Rotation Angle Value", "value_3") == "f32 0"
    assert _field(raw, "Mesh Y Translation Value Anim", "value_2") == "f32 0"
    ss = {s for _a, _b, s in ES.list_strings(raw)}
    assert "Scenery\\DarkHills\\Fishes_Ground_A.fbx" in ss
    assert not any("Key_Geo" in s or "] Collectible_Ingredient_Key\\" in s for s in ss)
    assert ING.EMITTED[ref]["borrow"][0] == ING.PICKUP_BASE


def test_delivery_clone_takes_the_ingredient_and_spawns_the_reward(tmp_path):
    for r in (ING.WELL_MODEL, ING.WELL_DH, ING.WELL_T1):
        _needs(PC.entity_cooked_path(r))
    _files, out = _emit(tmp_path, name="Fish", delivery={"id": "catch", "prices": [8, 12, 20]})
    model = (out / PC.entity_cooked_path(
        "Objects_Common\\Ingredient_Fish_catch_Model.entity.ot")).read_bytes()
    assert _field(model, "Dt Delivery Point", "bytes_1") == named_id.to_bytes("Fish").hex(" ")
    for t in ("T1", "T2", "T3"):
        assert _field(model, f"Price Switch Selector {t}", "obj_4") == "int 0  int 8"
        assert _field(model, f"Price Switch Selector {t}", "obj_6") == "int 2  int 20"
    # its own wall shrunk to a token: the mod's art does the blocking
    assert _field(model, "Collision volume", "value_2") == "f32 0.05"
    assert _field(model, "Collision volume", "bytes_3").endswith("cd cc 4c 3d cd cc 4c 3d")
    ss = [s for _a, _b, s in ES.list_strings(model)]
    assert not any("Wishing_Well_Drop_Bag" in s for s in ss)
    assert ss.count(ING.PIG_REWARD) == 4
    assert ING.INVISIBLE_MESH in ss and "Scenery\\DarkHills\\Wishing_Well.fbx" not in ss
    # the child chain points at the clones, and T1's override follows the
    # cloned model's restamped component GUIDs
    t1 = (out / PC.entity_cooked_path(ING.pickup_ref("Fish", "catch"))).read_bytes()
    assert "Objects_Common\\Ingredient_Fish_catch_Base.entity.ot" in {
        s for _a, _b, s in ES.list_strings(t1)}
    assert any(g in t1 for g in PC.component_guids(model))


def test_describe_matches_what_emit_records(tmp_path):
    for r in (ING.PICKUP_BASE, ING.WELL_MODEL, ING.WELL_DH, ING.WELL_T1):
        _needs(PC.entity_cooked_path(r))
    fields = {"name": "Fish", "pickups": [
        {"id": "pile", "count": 4,
         "look": "DarkHills\\SceneryObjects_DarkHills\\Fishes_Ground_A.entity.ot"}],
        "delivery": {"id": "catch", "prices": [8]}}
    ING.EMITTED.clear()
    _emit(tmp_path, **fields)
    assert ING.describe(fields) == ING.EMITTED
