"""The map editor: named edits on a tile-generation recipe, the manifest that
carries them, the `tilegen` content kind that cooks them, and the local server.

Most of this runs on a small synthetic recipe so CI covers it without the
game-derived corpus. The legs that need a shipped recipe are marked.
"""

from __future__ import annotations

import copy
import json
import re
import threading
import urllib.error
import urllib.request

import pytest

from rsmm.engine import map_editor as ME
from rsmm.engine import tilegen as TG
from rsmm.engine.paths import DATA_DIR

needs_corpus = pytest.mark.skipif(
    not (DATA_DIR / "uncooked" / "Ot").is_dir(),
    reason="uncooked corpus absent (run scripts/extract_uncooked.py)")


def _recipe() -> TG.TileGen:
    """Two kinds, two footprint groups, one whole-map slot, two scenarios."""
    def ff(name):
        return TG.FlagFilter(required=[name])
    kinds = {
        1: TG.TileKind(filter=ff("Camp"), count=5, min_distance=100.0, footprints=[0, 1], rule=0),
        2: TG.TileKind(filter=ff("Start"), count=1, min_distance=0.0, footprints=[0, 1], rule=0),
    }
    sizes = {3: TG.SlotSize(width=6, height=6, filter=ff("6x6"), slots=[10]),
             4: TG.SlotSize(width=40, height=40, filter=ff("40x40"), slots=[11])}
    whole = TG.SlotSize(width=128, height=128, filter=ff("128x128"), slots=[12])
    slots = {
        10: TG.Slot(pos=(1.0, 0.0, 2.0), kinds=[1, 0], compat=[[2, 2], [2, 2]]),
        # Start is OFF in the mask but forced on in scenario 2, the shape the
        # shipped chapters use for their start tile.
        11: TG.Slot(pos=(50.0, 0.0, -40.0), kinds=[1, 0], compat=[[2, 2], [0, 1]]),
        12: TG.Slot(pos=(-500.0, 0.0, 500.0), kinds=[], compat=[]),
    }
    spawner = TG.SpawnerSettings(
        kind_ids=[1, 2], scenarios=[TG.Scenario("Scenario 01", "Easy"),
                                    TG.Scenario("Scenario 02", "Hard")],
        size_ids=[3, 4], whole_map=whole, mapdef=("Definitions", "Maps\\X.mapdef.ot"),
        quotas=[TG.FlagQuota(flags=["Wishing_Well"], limit=1),
                TG.FlagQuota(flags=["Boss", "Treants"], limit=2)],
        tail=(0,) * 8)
    tg = TG.TileGen(spawner=spawner, kinds=kinds, sizes=sizes, slots=slots)
    TG.validate(tg)
    return tg


# --------------------------------------------------------------------------
# editor JSON
# --------------------------------------------------------------------------

def test_to_json_names_everything_the_editor_draws():
    j = ME.to_json(_recipe())
    assert [k["name"] for k in j["kinds"]] == ["Camp", "Start"]
    assert j["kinds"][0]["footprints"] == {"6x6": False, "40x40": True}
    assert [g["name"] for g in j["groups"]] == ["6x6", "40x40"]
    assert j["whole_map"] == {"name": "128x128", "slots": [12]}
    assert [q["key"] for q in j["quotas"]] == ["Wishing_Well", "Boss+Treants"]
    s11 = next(s for s in j["slots"] if s["id"] == 11)
    assert s11["group"] == "40x40" and s11["allow"] == {"Camp": True, "Start": False}
    # 2 (defer to the mask) is left out; 1 and 0 are the overrides
    assert s11["overrides"] == [{}, {"Camp": 0, "Start": 1}]
    assert next(s for s in j["slots"] if s["id"] == 12)["whole_map"] is True


# --------------------------------------------------------------------------
# edits
# --------------------------------------------------------------------------

def test_edits_apply_by_name_and_report_what_changed():
    tg = _recipe()
    changes = ME.apply_edits(tg, {
        "kinds": {"Camp": {"count": 8, "min_distance": 80, "footprints": {"6x6": True}}},
        "quotas": {"Boss+Treants": 3},
        "slots": {"10": {"pos": [1.0, 0.0, 2.0], "allow": {"Start": True}}},
    })
    assert tg.kinds[1].count == 8 and tg.kinds[1].min_distance == 80.0
    assert tg.kinds[1].footprints == [1, 1]
    assert tg.spawner.quotas[1].limit == 3
    assert tg.slots[10].kinds == [1, 1]
    assert changes == ["Camp: count 5 -> 8", "Camp: min distance 100 -> 80",
                       "Camp: footprint 6x6 on", "quota Boss+Treants: 2 -> 3",
                       "slot 10: Start allowed"]


def test_a_value_already_shipped_is_not_a_change():
    assert ME.apply_edits(_recipe(), {"kinds": {"Camp": {"count": 5}}}) == []


@pytest.mark.parametrize("edits, msg", [
    ({"kinds": {"Nope": {"count": 1}}}, "no kind named"),
    ({"kinds": {"Camp": {"count": 1.5}}}, "whole number"),
    ({"kinds": {"Camp": {"count": float("nan")}}}, "whole number"),
    ({"kinds": {"Camp": {"count": True}}}, "whole number"),
    ({"kinds": {"Camp": {"count": 99999}}}, "outside"),
    ({"kinds": {"Camp": {"min_distance": -1}}}, "outside"),
    ({"kinds": {"Camp": {"colour": "red"}}}, "unknown field"),
    ({"kinds": {"Camp": {"footprints": {"9x9": True}}}}, "no footprint group"),
    ({"kinds": {"Camp": {"footprints": {"6x6": 1}}}}, "true or false"),
    ({"quotas": {"Nope": 1}}, "no flag quota"),
    ({"slots": {"99": {"allow": {"Camp": True}}}}, "no such slot"),
    ({"slots": {"x": {"allow": {"Camp": True}}}}, "not a slot id"),
    ({"slots": {"12": {"allow": {"Camp": True}}}}, "whole-map slot"),
    ({"slots": {"10": {"pos": [9.0, 0.0, 2.0], "allow": {"Start": True}}}}, "recipe changed"),
    ({"layout": {}}, "unknown edit section"),
])
def test_bad_edits_are_refused_and_change_nothing(edits, msg):
    """Every name and value is checked before anything is written, so a
    refusal halfway through a document cannot leave half of it applied."""
    tg = _recipe()
    before = copy.deepcopy(tg)
    # prepend a VALID edit, so a non-atomic apply would have written it
    doc = {"quotas": {"Wishing_Well": 4}, **edits} if "quotas" not in edits else edits
    with pytest.raises(ME.MapEditError, match=msg):
        ME.apply_edits(tg, doc)
    assert tg == before


def test_edits_json_errors_checks_without_touching_the_recipe():
    tg = _recipe()
    assert ME.edits_json_errors(tg, {"kinds": {"Camp": {"count": 9}}}) is None
    assert tg.kinds[1].count == 5
    assert "no kind named" in ME.edits_json_errors(tg, {"kinds": {"X": {"count": 1}}})


# --------------------------------------------------------------------------
# manifest
# --------------------------------------------------------------------------

@pytest.mark.parametrize("mod_id, ok", [
    ("dark-hills-camps", True), ("a_b", True), ("x", False), ("Upper", False),
    ("-lead", False), ("has space", False), ("../escape", False), ("a" * 65, False),
])
def test_mod_ids(mod_id, ok):
    assert ME.valid_mod_id(mod_id) is ok


def test_manifest_reads_back_as_exactly_its_edits():
    ch = ME.Chapter(key="DarkHills",
                    decoded="Ot/DarkHills/Map_Dark_Hills_X_TileGeneration.level.ot.GameStream.gen")
    edits = {
        "kinds": {"Camp": {"count": 8, "min_distance": 80.0, "footprints": {"6x6": True}},
                  'Odd "Quoted" Kind': {"count": 2}},
        "quotas": {"Boss+Treants": 3},
        "slots": {"11": {"pos": [50.0, 0.0, -40.0], "allow": {"Start": True}}},
    }
    text = ME.manifest_toml("more-camps", "More camps", ch, edits)
    assert text.startswith(ME.EDITOR_MARK)
    chapter, back = ME.read_manifest_edits(text)
    assert chapter == "DarkHills" and back == edits
    import tomllib

    mod = tomllib.loads(text)["mod"]
    assert "experimental" not in mod and mod["multiplayer_scope"] == "host-authoritative"
    with pytest.raises(ME.MapEditError, match="mod id"):
        ME.manifest_toml("Bad Id", "", ch, edits)


# --------------------------------------------------------------------------
# the local server: refusals that need no corpus
# --------------------------------------------------------------------------

@pytest.fixture
def editor(tmp_path, monkeypatch):
    monkeypatch.setenv("RSMM_MODS_DIR", str(tmp_path / "mods"))
    from rsmm.cli.editor import server as CM

    srv = CM.serve(0, mods=tmp_path / "mods")
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    port = srv.server_address[1]

    def call(path, body=None, token=None, host=None, ctype="application/json"):
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/map{path}",
            data=None if body is None else json.dumps(body).encode(),
            method="GET" if body is None else "POST")
        if body is not None:
            req.add_header("Content-Type", ctype)
        if token:
            req.add_header("X-RSMM-Token", token)
        if host:
            req.add_header("Host", host)
        try:
            # A painted map's check/save rebuilds a 26 MB terrain level: allow it.
            with urllib.request.urlopen(req, timeout=120) as r:
                return r.status, r.read()
        except urllib.error.HTTPError as e:
            return e.code, e.read()

    yield call, port, srv
    srv.shutdown()
    srv.server_close()


def test_page_embeds_a_token_and_writes_demand_it(editor):
    call, _port, srv = editor
    code, page = call("/")                     # the map page, at /map/
    assert code == 200
    token = re.search(rb'const TOKEN = "([^"]+)"', page).group(1).decode()
    assert token == srv.token and token != "__RSMM_TOKEN__"
    body = {"chapter": "DarkHills", "mod_id": "x-y", "edits": {}}
    assert call("/api/save", body)[0] == 403
    assert call("/api/save", body, token="wrong")[0] == 403
    assert call("/api/save", body, token=token, ctype="text/plain")[0] == 415


def test_a_rebound_hostname_is_refused(editor):
    """A foreign site pointing its own name at 127.0.0.1 still sends that name."""
    call, port, srv = editor
    assert call("/api/state", host=f"attacker.example:{port}")[0] == 403
    assert call("/api/save", {"chapter": "DarkHills"}, token=srv.token,
                host=f"attacker.example:{port}")[0] == 403
    assert call("/api/state", host=f"localhost:{port}")[0] == 200


# --------------------------------------------------------------------------
# shipped recipes
# --------------------------------------------------------------------------

@needs_corpus
def test_start_is_placed_by_a_scenario_override_not_the_mask():
    """The evidence behind reading the compatibility table as overrides: in
    Dark Hills no 40x40 slot allows Start by mask, and every scenario forces
    exactly one — a different one."""
    tg = ME.load(ME.find_chapter("DarkHills"))
    j = ME.to_json(tg)
    start = next(k for k in j["kinds"] if k["name"] == "Start")
    fits = {g for g, on in start["footprints"].items() if on}
    in_fp = [s for s in j["slots"] if s["group"] in fits]
    assert in_fp and not any(s["allow"]["Start"] for s in in_fp)
    per_scen = []
    for i in range(len(j["scenarios"])):
        per_scen.append([s["id"] for s in in_fp if s["overrides"][i].get("Start") == 1])
    assert all(len(ids) == 1 for ids in per_scen)
    assert len({ids[0] for ids in per_scen}) == len(per_scen)


@needs_corpus
def test_tilegen_kind_cooks_only_the_named_changes():
    import tempfile
    from pathlib import Path

    from rsmm.sdk.content import KIND_CONFIDENCE, ContentDef, ContentError, _load_kind

    assert KIND_CONFIDENCE["tilegen"] == "confirmed"
    kind = _load_kind("tilegen")
    out = Path(tempfile.mkdtemp())
    ch = ME.find_chapter("DarkHills")
    vanilla = ME.load(ch)
    defn = ContentDef(kind="tilegen", id="camps", fields={
        "chapter": "DarkHills", "kinds": {"Camp": {"count": 8}},
        "quotas": {"Wishing_Well": 2}})
    [dest] = kind.emit("m", defn, out)
    assert dest == out / Path(*ch.decoded.split("/"))
    cooked = TG.read(dest.read_bytes())
    # exactly the two edits, nothing else in the recipe moved
    expect = copy.deepcopy(vanilla)
    ME.apply_edits(expect, {"kinds": {"Camp": {"count": 8}}, "quotas": {"Wishing_Well": 2}})
    assert cooked == expect
    assert len(dest.read_bytes()) == len(ME.vanilla_level(ch))

    with pytest.raises(ContentError, match="already matches"):
        kind.emit("m", ContentDef(kind="tilegen", id="noop", fields={
            "chapter": "DarkHills", "kinds": {"Camp": {"count": vanilla.kinds[
                next(i for i in vanilla.spawner.kind_ids if vanilla.kinds[i].name == "Camp")
            ].count}}}), out)
    with pytest.raises(ContentError, match="no kind named"):
        kind.emit("m", ContentDef(kind="tilegen", id="bad", fields={
            "chapter": "DarkHills", "kinds": {"Nope": {"count": 1}}}), out)


@needs_corpus
def test_save_through_the_server_writes_a_mod_that_lints_and_reopens(editor, tmp_path):
    call, _port, srv = editor
    state = json.loads(call("/api/state")[1])
    assert {c["key"] for c in state["chapters"]} >= {"DarkHills", "Avalon"}
    recipe = json.loads(call("/api/recipe?chapter=DarkHills")[1])["recipe"]
    slot = next(s for s in recipe["slots"] if not s["whole_map"])
    edits = {"kinds": {"Camp": {"count": 8}},
             "slots": {str(slot["id"]): {"pos": slot["pos"],
                                         "allow": {"Crystal": not slot["allow"]["Crystal"]}}}}

    code, body = call("/api/check", {"chapter": "DarkHills", "edits": edits}, token=srv.token)
    assert code == 200 and len(json.loads(body)["changes"]) == 2

    code, body = call("/api/save", {"chapter": "DarkHills", "mod_id": "camps", "name": "Camps",
                                    "edits": edits}, token=srv.token)
    assert code == 200, body
    man = tmp_path / "mods" / "camps" / "manifest.toml"
    assert man.is_file()
    assert json.loads(call("/api/mod?id=camps")[1])["edits"] == edits
    assert json.loads(call("/api/state")[1])["mods"] == [
        {"id": "camps", "chapter": "DarkHills", "map": False}]

    # never overwrite a mod the editor did not write
    hand = tmp_path / "mods" / "handmade"
    hand.mkdir()
    (hand / "manifest.toml").write_text('[mod]\nid = "handmade"\n')
    code, _ = call("/api/save", {"chapter": "DarkHills", "mod_id": "handmade",
                                 "edits": edits}, token=srv.token)
    assert code == 409
    assert (hand / "manifest.toml").read_text() == '[mod]\nid = "handmade"\n'


@needs_corpus
def test_fill_edit_empties_a_group_and_survives_a_write():
    """The fill pass (not a kind's count) is where most camps come from: the
    40x40/64x64 groups fill every leftover slot with "Camp". `fill = []` turns
    that off, and the recipe must still round-trip through the writer."""
    ch = ME.find_chapter("DarkHills")
    level, changes = ME.build_level(ch, {"fill": {"40x40": [], "64x64": []}})
    assert changes == ["fill 40x40: ['Camp'] -> nothing", "fill 64x64: ['Camp'] -> nothing"]
    tg = TG.read(level)
    fills = {n: tg.sizes[i].filter.required
             for n, i in zip(tg.size_names, tg.spawner.size_ids, strict=True)}
    assert fills == {"3x3": ["Blocker"], "6x6": ["Blocker"], "40x40": [], "64x64": []}
    with pytest.raises(ME.MapEditError, match="no footprint group"):
        ME.build_level(ch, {"fill": {"99x99": []}})


# --------------------------------------------------------------------------
# fill, and saving as a new map (the `map` kind)
# --------------------------------------------------------------------------

_DH = ME.Chapter(key="DarkHills",
                 decoded="Ot/DarkHills/Map_Dark_Hills_X_TileGeneration.level.ot.GameStream.gen")
_BORROWED = "Tiles\\Avalon\\64x64_Ponds_And_Fountains_Camp.tiledef.ot"


def test_a_fill_edit_reads_back():
    edits = {"fill": {"40x40": [], "6x6": ["Blocker", "Props"]}}
    text = ME.manifest_toml("no-fill", "", _DH, edits)
    assert ME.read_manifest_edits(text) == ("DarkHills", edits)


@pytest.mark.parametrize("play", [True, False])
def test_a_map_manifest_reads_back_as_its_clone(play):
    import tomllib

    edits = {"kinds": {"Camp": {"count": 2}}, "fill": {"40x40": []}}
    as_map = {"id": "Twilight_Hills", "play": play,
              "pool": {"add": [_BORROWED],
                       "remove": ["Tiles\\Dark_Hills\\3x3_Blocker_Props_01.tiledef.ot"]},
              "place": {"30": "Dark_Hills/40x40_Dark_Hills_Start_Update3",
                        "new0": "Avalon/64x64_Ponds_And_Fountains_Camp"},
              "terrain": [{"op": "raise", "x": 1.5, "z": -2.0, "radius": 12, "amount": 3,
                           "falloff": "smooth"},
                          {"op": "flatten", "x": 0, "z": 0, "radius": 8, "falloff": "constant"}]}
    text = ME.manifest_toml("twilight", "Twilight", _DH, edits, as_map)
    assert ME.read_manifest(text) == {"chapter": "DarkHills", "edits": edits, "map": as_map}
    data = tomllib.loads(text)
    assert data["mod"]["experimental"] is True
    [block] = data["content"]
    assert block["kind"] == "map" and block["base"] == "Dark_Hills"
    assert ("chapter" in block) is play and block.get("chapter", 0) == 0
    assert block["pool"]["add"] == ["Avalon/64x64_Ponds_And_Fountains_Camp"]
    assert block["tilegen"] == edits
    assert block["place"]["new0"] == "Avalon/64x64_Ponds_And_Fountains_Camp"
    assert block["terrain"][0]["op"] == "raise"


@pytest.mark.parametrize("map_id", ["", "1abc", "has space", "a-b", "x"])
def test_bad_map_ids_are_refused(map_id):
    with pytest.raises(ME.MapEditError, match="map id"):
        ME.manifest_toml("m-x", "", _DH, {}, {"id": map_id, "play": True, "pool": {}})


def test_a_bare_pool_name_means_the_base_biome():
    text = ME.manifest_toml("m-x", "", _DH, {}, {"id": "Hills_B", "play": True, "pool": {}})
    text = text.replace('base    = "Dark_Hills"',
                        'base    = "Dark_Hills"\npool    = { remove = ["3x3_Crystal_01"] }')
    got = ME.read_manifest(text)
    assert got["map"]["pool"]["remove"] == ["Tiles\\Dark_Hills\\3x3_Crystal_01.tiledef.ot"]


@needs_corpus
def test_the_catalog_lists_every_biome_and_previews_a_borrowed_tile():
    cat = ME.tile_catalog_json()
    assert {t["biome"] for t in cat} == {"Avalon", "Dark_Hills", "Storm_Island"}
    assert _BORROWED in {t["path"] for t in cat}
    ch = ME.find_chapter("DarkHills")
    assert _BORROWED not in {t["path"] for t in ME.tile_pool_json(ch)}
    assert "instances" in ME.tile_json(ch, _BORROWED)
    with pytest.raises(ME.MapEditError):
        ME.tile_json(ch, "Tiles\\Nowhere\\X.tiledef.ot")
    groups = {g["name"]: g["fill"] for g in ME.to_json(ME.load(ch))["groups"]}
    assert groups["40x40"] == ["Camp"]


@needs_corpus
def test_save_as_a_new_map_writes_a_mod_that_lints_and_reopens(editor, tmp_path, monkeypatch):
    call, _port, srv = editor
    as_map = {"id": "Twilight_Hills", "play": True,
              "pool": {"add": [_BORROWED], "remove": []}, "place": {}, "terrain": []}
    body = {"chapter": "DarkHills", "mod_id": "twilight", "edits": {"fill": {"40x40": []}},
            "map": as_map}
    code, out = call("/api/check", body, token=srv.token)
    assert code == 200, out
    assert json.loads(out)["changes"] == ["fill 40x40: ['Camp'] -> nothing",
                                          f"pool: + {_BORROWED}"]
    code, out = call("/api/save", body, token=srv.token)
    assert code == 200, out
    got = json.loads(call("/api/mod?id=twilight")[1])
    assert got["map"] == as_map and got["edits"] == {"fill": {"40x40": []}}
    assert json.loads(call("/api/state")[1])["mods"] == [
        {"id": "twilight", "chapter": "DarkHills", "map": True}]

    import sys

    from rsmm.cli import lint

    monkeypatch.setattr("rsmm.cli.lint.MODS_DIR", tmp_path / "mods")
    monkeypatch.setattr(sys, "argv", ["lint", "twilight"])
    assert lint.main() == 0

    # The map kind's own refusals reach the page: removing the only Start tile.
    bad = {**body, "map": {**as_map, "pool": {"add": [], "remove": [
        "Tiles\\Dark_Hills\\40x40_Dark_Hills_Start_Update3.tiledef.ot"]}}}
    code, out = call("/api/check", bad, token=srv.token)
    assert code == 400 and b"Start" in out


# --------------------------------------------------------------------------
# moving, adding and removing slots
# --------------------------------------------------------------------------

def test_slots_move_add_and_remove_by_name():
    tg = _recipe()
    changes = ME.apply_edits(tg, {
        "slots": {"10": {"pos": [1.0, 0.0, 2.0], "move": [5.0, 1.0, 6.0]}},
        "remove_slots": {"11": [50.0, 0.0, -40.0]},
        "add_slots": [{"group": "40x40", "pos": [7.0, 0.0, 8.0], "allow": {"Start": True}}],
    })
    assert changes == ["slot 10: moved to [5.0, 1.0, 6.0]", "slot 11: removed",
                       "slot added: 40x40 at [7.0, 0.0, 8.0]"]
    by_pos = {s.pos: s for s in tg.slots.values()}
    assert (5.0, 1.0, 6.0) in by_pos and (50.0, 0.0, -40.0) not in by_pos
    assert by_pos[(7.0, 0.0, 8.0)].kinds == [0, 1]


@pytest.mark.parametrize("edits, msg", [
    ({"remove_slots": {"11": [0.0, 0.0, 0.0]}}, "made against"),
    ({"remove_slots": {"12": [-500.0, 0.0, 500.0]}}, "whole-map"),
    ({"add_slots": [{"group": "99x99", "pos": [0, 0, 0]}]}, "footprint group"),
    ({"add_slots": [{"group": "40x40", "pos": [0, 0, 1e9]}]}, "outside"),
    ({"add_slots": [{"group": "40x40", "pos": [0, 0, 0], "allow": {"Nope": True}}]}, "no kind"),
    ({"slots": {"12": {"pos": [-500.0, 0.0, 500.0], "move": [0, 0, 0]}}}, "whole-map"),
])
def test_bad_slot_layout_edits_change_nothing(edits, msg):
    tg = _recipe()
    before = copy.deepcopy(tg)
    with pytest.raises(ME.MapEditError, match=msg):
        ME.apply_edits(tg, edits)
    assert tg == before


def test_slot_layout_edits_read_back_from_a_manifest():
    edits = {"slots": {"10": {"pos": [1.0, 0.0, 2.0], "move": [5.0, 1.0, 6.0]}},
             "remove_slots": {"11": [50.0, 0.0, -40.0]},
             "add_slots": [{"group": "40x40", "pos": [7.0, 0.0, 8.0], "allow": {"Start": True}},
                           {"group": "6x6", "pos": [1.5, 0.0, 1.5]}]}
    text = ME.manifest_toml("layout", "", _DH, edits)
    assert ME.read_manifest_edits(text) == ("DarkHills", edits)
    as_map = {"id": "Hills_B", "play": True, "pool": {"add": [], "remove": []},
              "place": {}, "terrain": []}
    assert ME.read_manifest(ME.manifest_toml("layout", "", _DH, edits, as_map))["edits"] == edits


@needs_corpus
def test_a_layout_edit_cooks_through_both_kinds(tmp_path):
    from rsmm.sdk.content import ContentDef
    from rsmm.sdk.kinds import maps, tilegen

    ch = ME.find_chapter("DarkHills")
    tg = ME.load(ch)
    sid = next(i for i in sorted(tg.slots) if tg.slots[i].kinds)
    edits = {"remove_slots": {str(sid): list(tg.slots[sid].pos)},
             "add_slots": [{"group": "40x40", "pos": [10.0, 0.0, 10.0], "allow": {"Camp": True}}]}
    [dest] = tilegen.emit("m", ContentDef("tilegen", "dh", {"chapter": "DarkHills", **edits}),
                          tmp_path / "a")
    back = TG.read(dest.read_bytes())
    assert len(back.slots) == len(tg.slots)
    assert (10.0, 0.0, 10.0) in {s.pos for s in back.slots.values()}
    maps.emit("m", ContentDef("map", "Hills_B", {"base": "Dark_Hills", "tilegen": edits}),
              tmp_path / "b")


@needs_corpus
def test_a_full_chapter_edit_saves_lints_and_reopens(editor, tmp_path, monkeypatch):
    """Everything the chapter editor makes, in one mod: a moved and a removed
    spot, a new spot with a tile pinned on it, a pinned shipped spot, paint."""
    import sys

    from rsmm.cli import lint

    call, _port, srv = editor
    recipe = json.loads(call("/api/recipe?chapter=DarkHills")[1])["recipe"]
    big = [s for s in recipe["slots"] if s["group"] == "40x40"]
    edits = {"slots": {str(big[0]["id"]): {"pos": big[0]["pos"], "move": [10.0, 0.0, 12.0]}},
             "remove_slots": {str(big[1]["id"]): big[1]["pos"]},
             "add_slots": [{"group": "64x64", "pos": [40.0, 0.0, -30.0]}]}
    as_map = {"id": "Twilight_Hills", "play": True, "pool": {"add": [], "remove": []},
              "place": {"new0": "Avalon/64x64_Ponds_And_Fountains_Camp",
                        str(big[2]["id"]): "Dark_Hills/40x40_Dark_Hills_Start_Update3"},
              "terrain": [{"op": "raise", "x": 40, "z": -30, "radius": 20, "amount": 4,
                           "falloff": "smooth"}]}
    body = {"chapter": "DarkHills", "mod_id": "full", "edits": edits, "map": as_map}
    code, out = call("/api/check", body, token=srv.token)
    assert code == 200, out
    changes = json.loads(out)["changes"]
    assert "terrain: 1 brush strokes" in changes and len(changes) == 6
    assert call("/api/save", body, token=srv.token)[0] == 200
    got = json.loads(call("/api/mod?id=full")[1])
    assert got["map"] == as_map and got["edits"] == edits
    monkeypatch.setattr("rsmm.cli.lint.MODS_DIR", tmp_path / "mods")
    monkeypatch.setattr(sys, "argv", ["lint", "full"])
    assert lint.main() == 0


def test_full_precision_floats_read_back():
    """A spot added on painted ground carries the terrain's own height, to the
    last digit; rounding it on write failed the manifest's read-back check."""
    edits = {"add_slots": [{"group": "40x40", "pos": [-77.2, 4.000018119812012, -3.4]}]}
    as_map = {"id": "Hills_B", "play": True, "pool": {"add": [], "remove": []}, "place": {},
              "terrain": [{"op": "raise", "x": -58.37, "z": 12.123456789, "radius": 24,
                           "amount": 3, "falloff": "smooth"}]}
    got = ME.read_manifest(ME.manifest_toml("prec", "", _DH, edits, as_map))
    assert got["edits"] == edits and got["map"] == as_map
