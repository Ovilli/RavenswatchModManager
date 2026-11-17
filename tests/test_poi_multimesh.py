"""A poi prop with more meshes than one model can hold: `model_2.glb`,
`model_3.glb`, ... each drawn by an ENTITY of its own (the donor prop cloned
with only the mesh swapped), stood wherever the prop stands.

A cloned graphic component on one entity was tried first and did not draw in
game (fishermans-camp v0.4.0, 2026-11-14): only the first mesh rendered."""

from __future__ import annotations

from types import SimpleNamespace

from rsmm.sdk.kinds import poi


def test_discovery_collects_numbered_models(tmp_path):
    d = tmp_path / "pois" / "dock"
    d.mkdir(parents=True)
    (d / "poi.toml").write_text('chapters = ["Dark_Hills"]\nreplaces = "A.entity.ot"\n',
                                encoding="utf-8")
    for n in ("model.glb", "model_3.glb", "model_2.glb", "model_x.glb"):
        (d / n).write_bytes(b"glTF")
    block = next(b for b in poi.discover(tmp_path) if b["id"] == "dock")
    assert block["prop"]["extra_models"] == ["pois/dock/model_2.glb", "pois/dock/model_3.glb"]


def test_each_extra_mesh_gets_an_entity_of_its_own():
    defn = SimpleNamespace(id="dock", fields={"prop": {
        "entity_base": "DarkHills\\SceneryObjects_DarkHills\\Wall_Ruins_Block_Small_A.entity.ot",
        "extra_models": ["pois/dock/model_2.glb", "pois/dock/model_3.glb"]}})
    assert poi._extra_entity_refs("my-mod", defn) == [
        "DarkHills\\SceneryObjects_DarkHills\\my_mod_dock_Prop_2.entity.ot",
        "DarkHills\\SceneryObjects_DarkHills\\my_mod_dock_Prop_3.entity.ot"]
    defn.fields["prop"]["extra_models"] = []
    assert poi._extra_entity_refs("my-mod", defn) == []


# --- parts: a kit of the mod's own entities, placed as "@<name>" ------------

def _poi_folder(tmp_path, cfg: str, parts=("rack", "catch")):
    d = tmp_path / "pois" / "dock"
    d.mkdir(parents=True)
    (d / "poi.toml").write_text(cfg, encoding="utf-8")
    (d / "model.glb").write_bytes(b"glTF")
    for p in parts:
        (d / "parts" / p).mkdir(parents=True)
        (d / "parts" / p / "model.glb").write_bytes(b"glTF")
    return d


def test_parts_are_discovered_with_their_collision(tmp_path):
    _poi_folder(tmp_path, 'chapters = ["Dark_Hills"]\nreplaces = "A.entity.ot"\n'
                          '[parts.rack]\n'
                          'collision = [{ size = [1.0, 1.0, 1.0], at = [0.0, 0.5, 0.0] }]\n')
    block = next(b for b in poi.discover(tmp_path) if b["id"] == "dock")
    parts = block["prop"]["parts"]
    assert parts["catch"] == {"model": "pois/dock/parts/catch/model.glb"}
    assert parts["rack"]["collision"][0]["size"] == [1.0, 1.0, 1.0]


def test_a_part_setting_without_its_model_is_refused(tmp_path):
    import pytest

    from rsmm.sdk.content import ContentError
    _poi_folder(tmp_path, 'chapters = ["Dark_Hills"]\nreplaces = "A.entity.ot"\n'
                          '[parts.boat]\ncollision = []\n')
    with pytest.raises(ContentError, match="no parts/boat/model.glb"):
        poi.discover(tmp_path)


def test_part_references():
    defn = SimpleNamespace(id="dock", fields={"prop": {
        "entity_base": "DarkHills\\SceneryObjects_DarkHills\\Wall_Ruins_Block_Small_A.entity.ot"}})
    assert poi._part_name("@rack") == "rack"
    assert poi._part_name("@prop") is None and poi._part_name("A.entity.ot") is None
    assert poi._part_entity_ref("my-mod", defn, "rack") == \
        "DarkHills\\SceneryObjects_DarkHills\\my_mod_dock_rack.entity.ot"
