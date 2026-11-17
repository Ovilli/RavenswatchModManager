"""A NEW ingredient — the carried resource of a collect-and-deliver quest.

``[[content]] kind = "ingredient"`` adds an ingredient like the game's Straw,
Wood, Stone, Bean, Key and Note: something a hero picks up, carries (counted
on the HUD), and hands in at a delivery point.

Fields:
    ``name``  (str, required)  the ingredient's name, e.g. ``"Fish"``. The
              engine identifies an ingredient ONLY by the id of this name
              (:func:`rsmm.engine.named_id.of`): pickups and delivery points
              store that u32, never a path. So the name is the identity — two
              mods both adding ``"Fish"`` would be the same ingredient.
    ``base``  (str, default ``"Straw"``)  the shipped ingredient to clone.
    ``icon``  (str, optional)  a PNG in the mod (relative to the mod root),
              cooked as the ingredient's icon (HUD, delivery counter, and the
              pickups' minimap marker). Without it the base's icon is kept.
    ``pickups`` (list, optional)  things on the map that GIVE this ingredient:
              ``{ id = "fish", count = 1, look = "<shipped scenery entity>" }``.
              Each is a clone of the game's key pickup
              (:data:`PICKUP_BASE`: idle -> hold to interact -> collected ->
              despawn, with a minimap marker, and no quest gating, unlike the
              straw pickups that only exist while a pig's mission step asks
              for them) wearing ``look``'s mesh and material, granting
              ``count`` of this ingredient. A poi stands one with
              ``places = [{ entity = "ingredient:<name>/<id>", pos = [...] }]``.
    ``delivery`` (table, optional)  where the ingredient is HANDED IN:
              ``{ id = "catch", prices = [10, 20, 30], reward = "<entity>",
              reward_from = "<placed shipped entity>" }``. A clone of the Dark
              Hills wishing well's hand-in logic (:data:`WELL_T1` and its
              parents), made INVISIBLE (its mesh swapped for a 1 mm triangle) so
              it stands inside the mod's own art: deliver ``prices[0]`` of this
              ingredient and it spawns ``reward`` (default: the 3 Pigs house
              reward, a choose-a-magic-object chest), then ``prices[1]`` for a
              second, ``prices[2]`` for a third — the well's own rising price,
              re-priced in this ingredient. ``reward_from`` is a shipped,
              placed entity whose tile preloads the reward (default: the straw
              pig house). Placed the same way: ``entity = "ingredient:<name>/<id>"``.

How it is found: nothing references an ``.ingredientdef`` by path. The boot
stage ``InitialLoading_LoadAllDefinitions`` loads every definition file under
``Definitions/`` that ``UsedRscList.ot`` lists, which the apply step does for
every new asset — so the def registers by existing. Its preload cache (the def
and its icon, like the shipped ones) is written beside it.

Lua: ``R.ingredient.add("<name>", n)`` (proven on Key) finds an ingredient by
this name, which is the quickest in-game check that the def loaded.
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path

from ...engine import corpus, named_id
from ...engine import prop_cook as PC
from ...engine import rsc_cache as RC
from ...engine.cooked_schemas import definitions as DEFS
from ..content import ContentDef, ContentError

_log = logging.getLogger(__name__)

_DIR = "Definitions/Ingredients"
_SUFFIX = ".ingredientdef.ot.DtIngredientDefinition.gen"
_CLASS = "oCDtIngredientDefinition"
#: The shipped ingredients (their names are taken).
SHIPPED = ("Bean", "Key", "Note", "Stone", "Straw", "Wood")
_NAME = re.compile(r"[A-Z][A-Za-z0-9_]{1,30}")
_PID = re.compile(r"[a-z][a-z0-9_]{0,30}")

#: The pickup every ``pickups`` entry clones: the key a Key Keeper drops.
PICKUP_BASE = "Objects\\Key_Lock\\Collectible_Ingredient_Key.entity.ot"
_KEY_MESH = "Mechas\\LockKey\\Key_Geo_02.fbx"
_KEY_MATS = ("Mechas\\LockKey\\M_LockKeyTube.mat.ot", "Mechas\\LockKey\\M_LockKeyTube_XP.mat.ot",
             "Mechas\\LockKey\\M_LockKey_Static.mat.ot")
_KEY_ICONS = ("MiniMap\\Icons\\Map_Icon_Key.png", "MiniMap\\Icons\\High\\Map_IconHigh_Key.png")
_STEM = "Collectible_Ingredient_Key"

#: The hand-in a `delivery` clones: the Dark Hills tier-1 wishing well, a thin
#: child of `WELL_DH` (the Dark Hills dressing, only a parent link), itself a
#: child of `WELL_MODEL`, which holds the whole delivery -> reward logic.
WELL_T1 = "DarkHills\\Objects_DarkHills\\Wishing_Well_Dark_Hills_T1.entity.ot"
WELL_DH = "DarkHills\\Objects_DarkHills\\Wishing_Well_Dark_Hills.entity.ot"
WELL_MODEL = "Objects_Common\\Wishing_Well_Model.entity.ot"
_WELL_MESH = "Scenery\\DarkHills\\Wishing_Well.fbx"
#: What the well drops: a bag, or the tier's own bag (T1..T3 by Reward Tier).
_WELL_DROPS = ("Objects_Common\\Wishing_Well_Drop_Bag.entity.ot",
               *(f"Objects_Common\\Wishing_Well_Drop_Bag_T{t}.entity.ot" for t in (1, 2, 3)))
_DS_ICON = "HUD\\HUD_Dream_Shards_Icon.png"
_WELL_ICONS = ("MiniMap\\Icons\\High\\Minimap_IconHigh_Well.png",
               "MiniMap\\Icons\\High\\Minimap_IconHigh_Well_Outline.png",
               "MiniMap\\Icons\\Map_Icon_Wishing_Wel_Outline.png",
               "MiniMap\\Icons\\Map_Icon_Wishing_Well.png")
#: The 3 Pigs house reward (pick one of three magic objects) and a placed
#: entity whose shipped tile preloads it.
PIG_REWARD = "DarkHills\\Houses_3Pigs\\Pig_House_Reward_Spawner.entity.ot"
PIG_REWARD_FROM = "DarkHills\\Houses_3Pigs\\Straw_Pig_House.entity.ot"
INVISIBLE_MESH = "Scenery\\DarkHills\\Ingredient_Invisible.fbx"
PLACE_PREFIX = "ingredient:"

#: What a poi needs to stand an emitted pickup, by entity ref: the SHIPPED
#: entities whose preload closures cover it (the key pickup and the look) and
#: the files this kind emitted for it. Filled by `emit`; manifest blocks emit
#: before discovered pois, so a poi's places can name a pickup declared there.
EMITTED: dict[str, dict] = {}


def def_path(name: str) -> str:
    """Decoded cooked path of ingredient ``name``'s definition."""
    return f"{_DIR}/{name}{_SUFFIX}"


def icon_ref(name: str) -> str:
    """The UI resource an ingredient's icon is cooked under (the NAME is the
    ingredient's identity, so it names its assets too)."""
    return f"MiniMap\\Icons\\Ingredient_{name}.png"


def pickup_ref(name: str, pid: str) -> str:
    """Entity reference of ingredient ``name``'s pickup ``pid``."""
    return f"Objects_Common\\Ingredient_{name}_{pid}.entity.ot"


def describe(fields: dict) -> dict[str, dict]:
    """What `emit` records in :data:`EMITTED` for an ingredient block, computed
    from its fields alone (nothing is written): the placed entity refs, with
    the shipped entities whose tile caches cover them and the files emitted
    for them. Lets a poi stand a pickup whatever order the blocks emit in."""
    name = fields.get("name")
    if not isinstance(name, str) or not _NAME.fullmatch(name):
        return {}
    icon = [PC.ui_cooked_path(icon_ref(name))] if fields.get("icon") is not None else []
    out = {}
    for p in fields.get("pickups") or []:
        if isinstance(p, dict) and isinstance(p.get("id"), str) and isinstance(p.get("look"), str):
            ref = pickup_ref(name, p["id"])
            out[ref] = {"borrow": [PICKUP_BASE, p["look"]],
                        "assets": [PC.entity_cooked_path(ref), *icon]}
    dv = fields.get("delivery")
    if isinstance(dv, dict) and isinstance(dv.get("id"), str):
        reward = dv.get("reward", PIG_REWARD)
        reward_from = dv.get("reward_from", PIG_REWARD_FROM if reward == PIG_REWARD else None)
        base = f"Objects_Common\\Ingredient_{name}_{dv['id']}"
        rels = [PC.entity_cooked_path(r) for r in
                (f"{base}_Model.entity.ot", f"{base}_Base.entity.ot", pickup_ref(name, dv["id"]))]
        out[pickup_ref(name, dv["id"])] = {
            "borrow": [WELL_T1, *([reward_from] if reward_from else [])],
            "assets": [*rels, PC.art_cooked_path(INVISIBLE_MESH), *icon]}
    return out


def describe_mod(mod_root: Path) -> None:
    """Fill :data:`EMITTED` from a mod's manifest `ingredient` blocks, for the
    refs no emit has recorded yet (a poi emitted on its own, e.g. by a check)."""
    import tomllib
    try:
        doc = tomllib.loads((mod_root / "manifest.toml").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return
    for block in doc.get("content") or []:
        if isinstance(block, dict) and block.get("kind") == "ingredient":
            for ref, rec in describe(block).items():
                EMITTED.setdefault(ref, rec)


def parse_place(entity: str) -> str | None:
    """``"ingredient:Fish/fish"`` -> the pickup's entity ref, else None."""
    if not entity.startswith(PLACE_PREFIX):
        return None
    name, _, pid = entity[len(PLACE_PREFIX):].partition("/")
    if not _NAME.fullmatch(name) or not _PID.fullmatch(pid):
        raise ContentError(f"{entity!r}: write an ingredient pickup as "
                           f"\"ingredient:<Name>/<pickup id>\"")
    return pickup_ref(name, pid)


def _look_art(look: str, what: str) -> tuple[str, str]:
    """(mesh, material) of a shipped scenery entity: its first non-LOD mesh."""
    from ...engine import entity_strings as ES
    raw = corpus.read(PC.entity_cooked_path(look))
    if raw is None:
        raise ContentError(f"{what}: look {look!r} is not a shipped entity")
    ss = [s for _a, _b, s in ES.list_strings(raw)]
    meshes = [s for s in ss if s.lower().endswith(".fbx") and "_lod" not in s.lower()]
    mats = [s for s in ss if s.lower().endswith(".mat.ot")]
    if not meshes or not mats:
        raise ContentError(f"{what}: look {look!r} has no mesh/material to borrow")
    return meshes[0], mats[0]


def _invisible_glb() -> bytes:
    """One 1 mm triangle: the hand-in's mesh, so only the mod's art shows."""
    import struct

    from ...engine import gltf
    binary = (struct.pack("<9f", 0, 0, 0, 0.001, 0, 0, 0, 0, 0.001)
              + struct.pack("<9f", 0, 1, 0, 0, 1, 0, 0, 1, 0)
              + struct.pack("<6f", 0, 0, 1, 0, 0, 1) + struct.pack("<3H", 0, 1, 2) + b"\0\0")
    views = [{"buffer": 0, "byteOffset": o, "byteLength": n}
             for o, n in ((0, 36), (36, 36), (72, 24), (96, 6))]
    doc = {"asset": {"version": "2.0"}, "scene": 0, "scenes": [{"nodes": [0]}],
           "nodes": [{"mesh": 0, "name": "invisible"}],
           "meshes": [{"primitives": [{"attributes": {"POSITION": 0, "NORMAL": 1,
                                                      "TEXCOORD_0": 2}, "indices": 3}]}],
           "buffers": [{"byteLength": len(binary)}], "bufferViews": views,
           "accessors": [{"bufferView": 0, "componentType": 5126, "count": 3, "type": "VEC3",
                          "min": [0, 0, 0], "max": [0.001, 0, 0.001]},
                         {"bufferView": 1, "componentType": 5126, "count": 3, "type": "VEC3"},
                         {"bufferView": 2, "componentType": 5126, "count": 3, "type": "VEC2"},
                         {"bufferView": 3, "componentType": 5123, "count": 3, "type": "SCALAR"}]}
    return gltf.write_glb(doc, binary)


def _clone(raw: bytes, old_stem: str, new_ref: str, swaps: dict[str, str],
           guid_map: dict[bytes, bytes] | None = None) -> tuple[bytes, dict[bytes, bytes]]:
    """``raw`` under ``new_ref``: string swaps (+ its own override labels), the
    parent's GUID map applied (a child's overrides bind to its parent's
    component GUIDs), then its own components restamped. Returns the bytes and
    this file's own GUID map, for its children."""
    from ...engine import cooked
    from ...engine import entity_strings as ES
    stem = new_ref.rsplit("\\", 1)[-1].removesuffix(".entity.ot")
    present = {s for _a, _b, s in ES.list_strings(raw)}
    swaps = {**swaps, **{x: x.replace(f"] {old_stem}\\", f"] {stem}\\", 1) for x in present
                         if x.startswith("[") and f"] {old_stem}\\" in x}}
    out = ES.replace_strings(raw, {k: v for k, v in swaps.items() if k in present})
    if guid_map:
        cf = cooked.parse(out)
        cf.sections = [cooked.Section(payload=PC._replace_all(sec.payload, guid_map))
                       for sec in cf.sections]
        out = cooked.emit(cf)
    own = {g: PC.derive_guid(f"{new_ref}#{g.hex()}") for g in PC.component_guids(out)
           if g != bytes(16)}
    return PC.restamp_entity_guids(out, new_ref), own


def _emit_delivery(name: str, dv: dict, icon: str | None, put, what: str) -> None:
    from ...engine import ability_edit as AE
    did, prices = dv.get("id"), dv.get("prices", [10, 20, 30])
    reward = dv.get("reward", PIG_REWARD)
    reward_from = dv.get("reward_from", PIG_REWARD_FROM if reward == PIG_REWARD else None)
    if not isinstance(did, str) or not _PID.fullmatch(did):
        raise ContentError(f"{what}.id must be a lower-case word, e.g. \"catch\"")
    if (not isinstance(prices, list) or not 1 <= len(prices) <= 3
            or not all(isinstance(v, int) and not isinstance(v, bool) and 1 <= v <= 999
                       for v in prices)):
        raise ContentError(f"{what}.prices is 1..3 counts (1..999), one per reward")
    if not isinstance(reward, str) or not reward.endswith(".entity.ot") \
            or corpus.read(PC.entity_cooked_path(reward)) is None:
        raise ContentError(f"{what}.reward names a shipped entity to spawn")
    if not isinstance(reward_from, str):
        raise ContentError(f"{what}.reward_from: a placed shipped entity whose tile "
                           f"preloads {reward!r}")
    prices = prices + [prices[-1]] * (3 - len(prices))
    reads = {r: corpus.read(PC.entity_cooked_path(r)) for r in (WELL_MODEL, WELL_DH, WELL_T1)}
    if any(v is None for v in reads.values()):
        raise ContentError(f"{what}: the game's wishing well is not readable")
    steps = [{"set": "Dt Delivery Point.bytes_1", "value": named_id.to_bytes(name).hex(" ")},
             # The well's own wall (a cylinder, extents 1.0 / 1.0, value 2.5): the
             # hand-in stands INSIDE the mod's art, which brings its own
             # collision, and the well's kept players off part of it (playtest
             # 2026-11-15). Shrunk to a token 5 cm rather than removed, so the
             # component layout stays the shipped one.
             {"set": "Collision volume.value_2", "value": 0.05},
             {"set": "Collision volume.bytes_3",
              "value": "02 00 00 00 02 00 00 00 cd cc 4c 3d cd cc 4c 3d"}]
    for t in ("T1", "T2", "T3"):
        for k, v in enumerate(prices):
            steps.append({"set": f"Price Switch Selector {t}.obj_{4 + k}[1]", "value": v})
    try:
        model = AE.apply({"m": reads[WELL_MODEL]}, steps, main="m", seed=what).files["m"]
    except AE.AbilityEditError as e:
        raise ContentError(f"{what}: {e}") from e
    base = f"Objects_Common\\Ingredient_{name}_{did}"
    m_ref, dh_ref, ref = f"{base}_Model.entity.ot", f"{base}_Base.entity.ot", pickup_ref(name, did)
    put(PC.art_cooked_path(INVISIBLE_MESH),
        PC.cook_model(_invisible_glb(), corpus.read(PC.art_cooked_path(_WELL_MESH)),
                      transform={"fit": "rig"}))
    look = {_WELL_MESH: INVISIBLE_MESH, **dict.fromkeys(_WELL_DROPS, reward)}
    if icon:
        look.update({_DS_ICON: icon, **dict.fromkeys(_WELL_ICONS, icon)})
    m_out, m_map = _clone(model, "Wishing_Well_Model", m_ref, look)
    dh_out, dh_map = _clone(reads[WELL_DH], "Wishing_Well_Dark_Hills", dh_ref,
                            {WELL_MODEL: m_ref}, m_map)
    t1_out, _ = _clone(reads[WELL_T1], "Wishing_Well_Dark_Hills_T1", ref,
                       {WELL_DH: dh_ref}, {**m_map, **dh_map})
    rels = [PC.entity_cooked_path(r) for r in (m_ref, dh_ref, ref)]
    for rel, data in zip(rels, (m_out, dh_out, t1_out), strict=True):
        put(rel, data)
    EMITTED[ref] = {"borrow": [WELL_T1, reward_from],
                    "assets": [*rels, PC.art_cooked_path(INVISIBLE_MESH)]
                    + ([PC.ui_cooked_path(icon)] if icon else [])}


def _emit_pickup(name: str, p: dict, icon: str | None, put, what: str) -> None:
    from ...engine import ability_edit as AE
    from ...engine import entity_strings as ES
    pid, count, look = p.get("id"), p.get("count", 1), p.get("look")
    if not isinstance(pid, str) or not _PID.fullmatch(pid):
        raise ContentError(f"{what}.id must be a lower-case word, e.g. \"fish\"")
    if not isinstance(count, int) or isinstance(count, bool) or not 1 <= count <= 99:
        raise ContentError(f"{what}.count must be 1..99")
    if not isinstance(look, str) or not look.endswith(".entity.ot"):
        raise ContentError(f"{what}.look names a shipped entity (…\\X.entity.ot) to look like")
    mesh, mat = _look_art(look, what)
    raw = corpus.read(PC.entity_cooked_path(PICKUP_BASE))
    if raw is None:
        raise ContentError(f"{what}: the game's key pickup is not readable")
    try:
        raw = AE.apply({"k": raw}, [
            {"set": "Dt Ingredient Gain.bytes_1", "value": named_id.to_bytes(name).hex(" ")},
            {"set": "Dt Ingredient Gain.value_2", "value": count},
            # The key spins (1.26 and 0.31 rad/s) and bobs (0.3 up and down);
            # a fish pile lies still on the ground (playtest 2026-11-15). Its
            # facing comes from the placement's yaw instead.
            {"set": "Key Rotation Angle Value.value_3", "value": 0.0},
            {"set": "Y Rotation Angle Value.value_3", "value": 0.0},
            {"set": "Mesh Y Translation Value Anim.value_2", "value": 0.0}],
            main="k", seed=what).files["k"]
    except AE.AbilityEditError as e:
        raise ContentError(f"{what}: {e}") from e
    ref = pickup_ref(name, pid)
    stem = ref.rsplit("\\", 1)[-1].removesuffix(".entity.ot")
    present = {s for _a, _b, s in ES.list_strings(raw)}
    swaps = {_KEY_MESH: mesh, **dict.fromkeys(_KEY_MATS, mat)}
    if icon:
        swaps.update(dict.fromkeys(_KEY_ICONS, icon))
    swaps.update({x: x.replace(f"] {_STEM}\\", f"] {stem}\\", 1) for x in present
                  if x.startswith("[") and f"] {_STEM}\\" in x})
    out = ES.replace_strings(raw, {k: v for k, v in swaps.items() if k in present})
    rel = PC.entity_cooked_path(ref)
    put(rel, PC.restamp_entity_guids(out, ref))
    EMITTED[ref] = {"borrow": [PICKUP_BASE, look],
                    "assets": [rel] + ([PC.ui_cooked_path(icon)] if icon else [])}


def _handler() -> DEFS.DefinitionHandler:
    return DEFS.DefinitionHandler(DEFS._SPECS[_CLASS])


def emit(mod_id: str, defn: ContentDef, out_dir: Path) -> list[Path]:
    f = defn.fields
    name = f.get("name")
    if not isinstance(name, str) or not _NAME.fullmatch(name):
        raise ContentError(f"ingredient {defn.id}: name must be a word starting with a capital "
                           f"letter, e.g. \"Fish\"")
    if name in SHIPPED:
        raise ContentError(f"ingredient {defn.id}: {name!r} is a shipped ingredient")
    base = f.get("base", "Straw")
    raw = corpus.read(def_path(base)) if isinstance(base, str) else None
    if raw is None:
        raise ContentError(f"ingredient {defn.id}: base must be one of {SHIPPED}")

    h = _handler()
    doc = json.loads(h.decode_cooked(raw))
    doc["name"] = name
    written: list[Path] = []

    def put(rel: str, data: bytes) -> None:
        dest = out_dir / Path(*rel.split("/"))
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)
        written.append(dest)

    icon = f.get("icon")
    if icon is not None:
        src = (out_dir.parent / icon) if isinstance(icon, str) else None
        if src is None or not src.is_file():
            raise ContentError(f"ingredient {defn.id}: icon {icon!r} is not a file in the mod")
        ref = icon_ref(name)
        put(PC.ui_cooked_path(ref), PC.cook_texture(src.read_bytes()))
        doc["icon_ref"] = ["Ui", ref]
    pickups = f.get("pickups") or []
    if not isinstance(pickups, list):
        raise ContentError(f"ingredient {defn.id}: pickups is a list of tables")
    for i, p in enumerate(pickups):
        if not isinstance(p, dict) or set(p) - {"id", "count", "look"}:
            raise ContentError(f"ingredient {defn.id}: pickups[{i}] takes id, count, look")
        _emit_pickup(name, p, doc["icon_ref"][1] if icon is not None else None, put,
                     f"ingredient {defn.id}: pickups[{i}]")
    dv = f.get("delivery")
    if dv is not None:
        if not isinstance(dv, dict) or set(dv) - {"id", "prices", "reward", "reward_from"}:
            raise ContentError(f"ingredient {defn.id}: delivery takes id, prices, reward, "
                               f"reward_from")
        _emit_delivery(name, dv, doc["icon_ref"][1] if icon is not None else None, put,
                       f"ingredient {defn.id}: delivery")
    rel = def_path(name)
    put(rel, h.encode_container(json.dumps(doc).encode("utf-8")))
    cache = [RC.entry_for(rel), f"Ui|{doc['icon_ref'][1]}|oCTexture"]
    put(RC.cache_path_for(rel), RC.render(cache))
    _log.info("ingredient %s/%s: %s (id 0x%08x, base %s)", mod_id, defn.id, name,
              named_id.of(name), base)
    return written
