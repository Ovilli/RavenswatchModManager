# rsmm.sdk.builder

## `Mod.asset(self, decoded_path: 'str', source: 'str | Path') -> 'None'`

Stage a source asset to override the game file at `decoded_path`.

`decoded_path` is the plaintext asset path as it appears in
`data/asset_map.json` (forward slashes), e.g.
``3D/Characters/Heroes/Melusine/Textures/T_Melusine_ALB.png``.
The file is copied verbatim into ``mods/<id>/assets/<decoded_path>``;
`rsmm apply` auto-cooks source formats (.glb/.png/.dds/...) into the
cooked container and installs them. Pre-cooked inputs pass through.

## `Mod.boss(self, id: 'str', *, base: 'str', name: 'str | None' = None, **fields)`

Register a custom boss cloned from vanilla ``base``.

## `Mod.enemy(self, id: 'str', *, base: 'str', name: 'str | None' = None, **fields)`

Register a custom enemy cloned from vanilla ``base``.

## `Mod.hero(self, id: 'str', *, base: 'str', name: 'str | None' = None, abilities: 'list | None' = None, **fields)`

Register a custom hero cloned from vanilla ``base``.

## `Mod.item(self, id: 'str', *, base: 'str', name: 'str | None' = None, **fields)`

Register a custom item cloned from vanilla ``base``.

## `Mod.map(self, id: 'str', *, base: 'str', **fields)`

Register a custom map/level cloned from vanilla ``base``.

## `Mod.model(self, decoded_path: 'str', source: 'str | Path', rotate_deg: 'tuple[float, float, float] | None' = None) -> 'None'`

Override a mesh asset. Source must be a `.glb`/`.gltf`.

A custom mesh is cooked at apply-time by retargeting it onto the
game asset's skeleton (`engine.geometry_cook`). It is auto-scaled and
recentered into the original's space; orientation defaults to an
auto-upright guess (tallest axis -> up). If the mesh comes out turned
or upside down, pass `rotate_deg=(x, y, z)` — a rigid rotation in
degrees applied before the fit (e.g. `(90, 0, 0)` to flip upright,
`(0, 180, 0)` to face the other way).

## `Mod.skinpack(self, name: 'str', key: 'int', *, ac_id: 'str' = '', al_id: 'str' = '', base_id: 'str' = '') -> 'None'`

Register a custom selectable skin-pack slot.

The skin roster is hardcoded in the engine (a fixed 9 `oCAdditionalContent`
"SkinPack" entries); see `docs/_re/kinds/skins.md`. A new slot can only be
added at runtime, so this is realized by the native loader DLL
(`src/loader/src/hook_skins.cpp`), which post-detours the roster builder and
appends a standalone entry per def. Defs are staged to
``mods/<id>/skinpacks.json``; the loader aggregates them across enabled mods.

Args:
    name:    display name shown in the skin grid.
    key:     pack key (int) the engine matches against a hero's pack-id
             field (entry ``+0x3c``). Must be unique across packs.
    ac_id:   AC content id (entry ``+0x50``), e.g. ``RW000PSAC000000A``.
    al_id:   AL content id (entry ``+0x60``), e.g. ``RW000PSAL000000A``.
    base_id: base content id (entry ``+0x70``).

Note: registering the slot is verified; whether a brand-new slot surfaces
per-hero and resolves to a custom model/material is not yet confirmed
in-game (see the "OPEN / UNVERIFIED" section of `docs/_re/kinds/skins.md`).
Stage the per-skin cooked assets the resolver expects with
:meth:`asset`/:meth:`texture`/:meth:`model` alongside this call.

## `Mod.summary(self) -> 'dict'`

Snapshot of everything staged so far — print before :meth:`commit`
to see exactly what the mod will write (no disk writes).

## `Mod.tag(self, tag_id: 'str', members) -> 'None'`

Group content into a named, cross-mod-extensible tag (Minecraft
``#namespace:path`` tags analog).

``members`` is a ContentRef / id string, or an iterable of them.
Calling ``tag()`` again with the same id **appends** (de-duped,
order-preserved), so several mods — or several call sites — can grow
one tag. Members are deref'd to raw ids, so you can pass the handles
returned by :meth:`item`/:meth:`enemy`/… directly::

    dagger = m.item("RubyDagger", base="Knife")
    m.tag("daggers", [dagger, "VanillaKnife"])

Tags are written to ``mods/<id>/tags.json``; downstream tooling/mods
aggregate them (same model as ``skinpacks.json``).

## `Mod.texture(self, decoded_path: 'str', source: 'str | Path') -> 'None'`

Override a texture asset. Source must be a `.png`/`.dds`/`.tga`.

## `Mod.validate(self) -> 'list[str]'`

Return human-readable warnings about the current state (does not
raise). Empty list = clean. Called automatically by :meth:`commit`;
run it yourself for a fast pre-flight.
