"""Assemble a **custom scenery prop** and the tile that shows it off.

`tile_cook` / `map_pool` let a mod place a tile the game already ships. This
module is the other half: building a structure the game does *not* ship, out of
a mod's own mesh and textures, and getting it standing in a generated map.

The engine reaches a visible structure through five hops, each one a reference
by *string path* inside a cooked asset:

```
mapdef pool ─► tiledef ─► tile prefab entity ─► tile level ─► prop entity
                                                                  │
                                              ┌───────────────────┴────┐
                                              ▼                        ▼
                                          geometry                material ─► textures
```

Every hop is a reference by string, so a mod splices itself in by cloning the
vanilla asset and rewriting the one string that points at the next one.

But a clone is not only its references. A tile **level** also carries a 16-byte
identity GUID, and all 228 shipped tile levels have a distinct one — so a copy
that keeps its donor's collides with it in the level registry and the tile
never appears in a generated map. Nothing reports this: the assets cook,
install, register and resolve perfectly, and every static check passes.
:func:`clone_tile_level` re-stamps it.

(The reverse trap is just as real. The prefab entity has a GUID-shaped field in
the same position, but 37 different tiles share one value — that is a type tag,
and re-stamping it would be inventing a type. The display name beside the level
GUID is not identity either: three separate levels all call themselves
`6x6_Healing_01`. Uniqueness across the corpus is what separates the three, and
it is the only reason to touch a field like this.)

Two different rewrite mechanisms are needed, because the assets are not the
same shape:

* **materials and levels** publish their references as a typed `asset_refs`
  list (`cooked_schemas.asset_refs`), so those are edited as data;
* **entity settings** keep theirs inline in an untyped payload, so those go
  through `entity_strings.replace_strings`, which rewrites a length-prefixed
  string in place (including to a different length) — safe because entity
  deserializers read strictly sequentially.

Reference form vs. cooked path
------------------------------
The engine refers to art by its *source* name and loads the cooked sibling:
a material asks for ``Scenery\\DarkHills\\T_Foo.tga`` and the loader opens
``3D\\Scenery\\DarkHills\\T_Foo.tga.Texture.dxt``. Every helper here takes the
reference form and derives the cooked path, so callers never hand-build either.

What the donors contribute
--------------------------
A clone inherits its donor's *structure* — component set, LOD wiring,
serialisation version, terrain patch, prop scatter. It does not inherit the
donor's art once the refs are rewritten. Picking a donor is therefore choosing
the skeleton the custom content hangs on, which is why the builders name their
donors explicitly instead of guessing.
"""

from __future__ import annotations

import json
from functools import lru_cache

from . import cooked, cooked_schemas, entity_strings

#: Cooked-path suffix per asset family, keyed by the reference form's extension.
GEOMETRY_SUFFIX = ".Geometry.gen"
MATERIAL_SUFFIX = ".Material.gen"
TEXTURE_SUFFIX = ".Texture.dxt"
#: Normal maps cook to their own suffix — 591 shipped textures use it.
TEXTURE_NORMAL_SUFFIX = ".Texture.nrm"
ENTITY_SUFFIX = ".EntitySettingsResource.gen"
LEVEL_SUFFIX = ".GameStream.gen"


class PropCookError(ValueError):
    pass


# --------------------------------------------------------------------------- #
# Source art -> cooked art
# --------------------------------------------------------------------------- #

def cook_texture(source_bytes: bytes) -> bytes:
    """Cook a PNG (or DDS) into a cooked ``oCTexture`` container."""
    from .cooked_schemas.texture import TextureHandler

    return TextureHandler().encode_container(source_bytes)


def cook_model(glb_bytes: bytes, donor_geometry_cooked: bytes,
               transform: dict | None = None) -> bytes:
    """Cook a glTF/GLB mesh into a cooked ``oCGeometry``.

    `cook_cache` can do this at apply time, but only for an asset that
    *overrides* an existing file — it finds the graft template at the
    destination path, and a brand-new asset has no destination. Here the
    template comes from the donor the caller already named, so a mod can ship a
    plain `.glb` for a mesh the game has never seen.

    The donor contributes vertex layout and material-slot count. Every
    position, normal and UV comes from `glb_bytes`.
    """
    from .geometry_cook import swap_geometry

    return swap_geometry(donor_geometry_cooked, glb_bytes, transform=transform)


# --------------------------------------------------------------------------- #
# Reference form <-> cooked decoded path
# --------------------------------------------------------------------------- #

def art_cooked_path(ref: str) -> str:
    """``Scenery\\DarkHills\\T_Foo.tga`` -> ``3D/Scenery/DarkHills/T_Foo.tga.Texture.dxt``.

    Handles the three art families that live under the ``3D/`` cooked root:
    ``.tga``/``.png`` textures, ``.fbx`` geometry and ``.mat.ot`` materials.

    ``3D/`` is a *convention*, not a rule the engine enforces, and a handful of
    shipped assets sit elsewhere — ``Textures\\Black.png`` cooks to
    ``samples/Textures/Black.png.Texture.dxt``, and shader refs (``*.px.ot``)
    resolve through ``shaders/`` entirely. So this is the right derivation for
    art a MOD emits (which is what it is used for: checking the mod actually
    ships the files it references) and the wrong tool for resolving an
    arbitrary vanilla reference — look those up in ``asset_map.json`` instead.
    """
    p = ref.replace("\\", "/")
    low = p.lower()
    if low.endswith((".tga", ".png")):
        suffix = TEXTURE_SUFFIX
    elif low.endswith(".fbx"):
        suffix = GEOMETRY_SUFFIX
    elif low.endswith(".mat.ot"):
        suffix = MATERIAL_SUFFIX
    else:
        raise PropCookError(
            f"don't know the cooked form of {ref!r} — expected a .tga/.png "
            f"texture, .fbx mesh or .mat.ot material reference"
        )
    return f"3D/{p}{suffix}"


@lru_cache(maxsize=1)
def _cooked_paths() -> frozenset[str]:
    """Every decoded cooked path the game ships, from ``asset_map.json``."""
    from . import asset_map

    return frozenset(asset_map.encoded_to_decoded().values())


def vanilla_cooked_path(ref: str, root: str = "3D") -> str | None:
    """The cooked path the game ACTUALLY uses for a shipped reference.

    :func:`art_cooked_path` derives a cooked name by convention, which is right
    for art a mod invents and wrong for art the game already ships — its own
    docstring says so. The suffix is not a function of the reference: a normal
    map cooks to ``.Texture.nrm``, not ``.Texture.dxt`` (591 shipped textures
    do), so an in-place override derived by convention lands on a path nothing
    reads. The mod's normal map then silently never applies AND the bogus path
    gets registered in ``UsedRscList.ot`` as a new asset, next to the real
    record it was supposed to replace.

    Returns ``None`` when the reference is not a shipped asset, so callers can
    fall back to the convention for art the mod is inventing.
    """
    p = ref.replace("\\", "/")
    known = _cooked_paths()
    for suffix in (TEXTURE_SUFFIX, TEXTURE_NORMAL_SUFFIX, ".Texture.gen",
                   GEOMETRY_SUFFIX, MATERIAL_SUFFIX):
        cand = f"{root}/{p}{suffix}"
        if cand.replace("/", "\\") in known:
            return cand
    return None


def ui_cooked_path(ref: str) -> str:
    """``MiniMap\\Icons\\X.png`` -> ``Ui/MiniMap/Icons/X.png.Texture.dxt``.

    UI art (minimap icons, HUD) cooks under the ``Ui/`` root rather than
    ``3D/`` — the same texture class, a different namespace, which is why
    :func:`art_cooked_path` cannot serve both.
    """
    p = ref.replace("\\", "/")
    if not p.lower().endswith((".png", ".tga")):
        raise PropCookError(f"{ref!r} is not a UI texture reference")
    return f"Ui/{p}{TEXTURE_SUFFIX}"


def entity_cooked_path(ref: str) -> str:
    """``DarkHills\\Objects\\X.entity.ot`` ->
    ``EntitySettings/DarkHills/Objects/X.entity.ot.EntitySettingsResource.gen``."""
    p = ref.replace("\\", "/")
    if not p.lower().endswith(".entity.ot"):
        raise PropCookError(f"{ref!r} is not an .entity.ot reference")
    return f"EntitySettings/{p}{ENTITY_SUFFIX}"


def level_cooked_path(ref: str) -> str:
    """``DarkHills\\Tiles\\X.level.ot`` -> ``Ot/DarkHills/Tiles/X.level.ot.GameStream.gen``."""
    p = ref.replace("\\", "/")
    if not p.lower().endswith(".level.ot"):
        raise PropCookError(f"{ref!r} is not a .level.ot reference")
    return f"Ot/{p}{LEVEL_SUFFIX}"


# --------------------------------------------------------------------------- #
# Clone helpers
# --------------------------------------------------------------------------- #

def _refs_doc(class_name: str, cooked_bytes: bytes) -> tuple[object, dict]:
    handler = cooked_schemas.get(class_name)
    return handler, json.loads(handler.decode_cooked(cooked_bytes))


def _emit(handler, doc: dict) -> bytes:
    return handler.encode_container(json.dumps(doc).encode("utf-8"))


def clone_material(donor_cooked: bytes, textures: dict[str, str]) -> bytes:
    """Clone a material, repointing texture references.

    ``textures`` maps an existing reference in the donor to its replacement,
    both in reference form. A key the donor does not use raises rather than
    silently doing nothing — a typo'd texture slot otherwise ships a material
    still pointing at the donor's art, which looks like the custom texture
    "not applying" and is miserable to diagnose in-game.
    """
    handler, doc = _refs_doc("oCMaterial", donor_cooked)
    have = set(doc.get("asset_refs") or [])
    missing = [k for k in textures if k not in have]
    if missing:
        raise PropCookError(
            f"material donor has no reference {missing!r}; it uses: "
            f"{sorted(have)}"
        )
    doc["asset_refs"] = [textures.get(r, r) for r in doc["asset_refs"]]
    return _emit(handler, doc)


#: Marker that closes a component's parent-link block. The component's own
#: 16-byte identity GUID is the field immediately after it, followed by the
#: length-prefixed component name.
_COMPONENT_MARK_END = b'""\xbb\xaa'
_ENTITY_GUID_LEN = 16
#: Longest plausible component name; used only to reject a false marker hit.
_MAX_COMPONENT_NAME = 256


def component_guids(cooked_bytes: bytes) -> list[bytes]:
    """Every component's own identity GUID, in section order.

    An ``oCEntitySettingsResource`` is one section per component, each laid out
    as ``<parent link> 2222bbaa <16-byte own GUID> <u32 len> <name>``. The name
    is what makes this recognisable rather than guessed: a candidate is only
    accepted when the four bytes after the GUID are a length that lands on
    printable ASCII, so a section with a different shape is skipped instead of
    having sixteen arbitrary bytes rewritten.
    """
    out: list[bytes] = []
    for sec in cooked.parse(cooked_bytes).sections:
        pl = sec.payload
        j = pl.find(_COMPONENT_MARK_END)
        if j < 0:
            continue
        g = j + len(_COMPONENT_MARK_END)
        if g + _ENTITY_GUID_LEN + 4 > len(pl):
            continue
        n = int.from_bytes(pl[g + _ENTITY_GUID_LEN:g + _ENTITY_GUID_LEN + 4], "little")
        name = pl[g + _ENTITY_GUID_LEN + 4:g + _ENTITY_GUID_LEN + 4 + n]
        if not (0 < n <= _MAX_COMPONENT_NAME and len(name) == n):
            continue
        if not all(0x20 <= c < 0x7F for c in name):
            continue
        out.append(pl[g:g + _ENTITY_GUID_LEN])
    return out


def restamp_entity_guids(cooked_bytes: bytes, seed: str) -> bytes:
    """Give a cloned entity resource its own component identity GUIDs.

    Same lesson as :func:`_restamp_level_guid`, one asset further down: a clone
    that keeps the donor's identity is a second resource claiming the donor's
    place. Nothing about it fails a static check — the bytes cook, the file
    installs, the name registers, every reference resolves — and the engine
    still cannot instantiate it.

    Components also reference *each other* by GUID inside the same file (a
    child's parent link is the parent's own GUID), so re-stamping one field at
    a time would sever the component tree. Every own-GUID is therefore mapped
    first and then substituted **everywhere in the payload**, which carries the
    internal links across by construction. A GUID that is not one of this
    file's own — the external entity a picker points at, for instance — is not
    in the map and is left exactly as it was.

    ``seed`` should be the clone's new reference, so the result is derived, not
    random: every peer in a multiplayer lobby has to cook the same bytes.
    """
    cf = cooked.parse(cooked_bytes)
    # Substitution is blind (`bytes.replace` over the whole payload), which is
    # what carries the internal parent links across — and also what makes a
    # DEGENERATE key catastrophic. An all-zero GUID matches every 16-byte run
    # of zeros in the file: padding, zeroed floats, empty vectors. The result
    # would still parse and install, silently corrupt. No shipped entity has
    # one (checked across 1500 of them), so this costs nothing and closes the
    # class rather than relying on that staying true.
    mapping = {old: derive_guid(f"{seed}#{old.hex()}")
               for old in component_guids(cooked_bytes)
               if old != bytes(_ENTITY_GUID_LEN)}
    if not mapping:
        return cooked_bytes
    cf.sections = [
        cooked.Section(payload=_replace_all(sec.payload, mapping))
        for sec in cf.sections
    ]
    return cooked.emit(cf)


def _replace_all(payload: bytes, mapping: dict[bytes, bytes]) -> bytes:
    for old, new in mapping.items():
        payload = payload.replace(old, new)
    return payload


def clone_prop_entity(donor_cooked: bytes, replacements: dict[str, str],
                      new_self_ref: str | None = None) -> bytes:
    """Clone a scenery-prop entity, repointing its mesh / material strings.

    Every replacement must actually fire: a prop whose mesh ref did not get
    rewritten renders the donor's model, which reads as "my model was ignored".

    ``new_self_ref`` is the reference the clone will be filed under. Passing it
    re-stamps the component identity GUIDs (:func:`restamp_entity_guids`); it
    is optional only so the low-level "rewrite these strings" use stays
    available, and every builder in this repo passes it.
    """
    present = {s for _sec, _off, s in entity_strings.list_strings(donor_cooked)}
    missing = [k for k in replacements if k not in present]
    if missing:
        raise PropCookError(
            f"prop-entity donor does not reference {missing!r}; "
            f"art strings it does use: "
            f"{sorted(s for s in present if '.fbx' in s or '.mat' in s)}"
        )
    out = entity_strings.replace_strings(donor_cooked, replacements)
    return restamp_entity_guids(out, new_self_ref) if new_self_ref else out


#: Byte offset of a level's identity GUID inside its second literal chunk.
#: `oCGameLevelIdentifierRFI` serialises the GUID first, then the display name.
_LEVEL_GUID_LITERAL = 1
_LEVEL_GUID_OFF = 0
_LEVEL_GUID_LEN = 16


def level_guid(cooked_or_doc) -> str | None:
    """The level's identity GUID as hex, or None if the shape is unexpected."""
    import json as _json

    doc = cooked_or_doc
    if isinstance(cooked_or_doc, (bytes, bytearray)):
        doc = _json.loads(
            cooked_schemas.get("oCGameStream").decode_cooked(bytes(cooked_or_doc)))
    lits = doc.get("_literals") or []
    if len(lits) <= _LEVEL_GUID_LITERAL:
        return None
    raw = bytes.fromhex(lits[_LEVEL_GUID_LITERAL])
    if len(raw) < _LEVEL_GUID_OFF + _LEVEL_GUID_LEN:
        return None
    return raw[_LEVEL_GUID_OFF:_LEVEL_GUID_OFF + _LEVEL_GUID_LEN].hex()


def derive_guid(seed: str) -> bytes:
    """A stable 16-byte GUID for `seed`, shaped like a v4 UUID.

    Deterministic on purpose. Map generation is part of the seeded run state, so
    every peer has to derive the same bytes for the same content — a random GUID
    would desync multiplayer and break reproducible builds.
    """
    import hashlib

    h = bytearray(hashlib.sha256(seed.encode("utf-8")).digest()[:16])
    h[6] = (h[6] & 0x0F) | 0x40      # version 4
    h[8] = (h[8] & 0x3F) | 0x80      # RFC-4122 variant
    return bytes(h)


def _restamp_level_guid(doc: dict, seed: str) -> None:
    """Give a cloned level its own identity.

    Every one of the 228 shipped tile levels has a distinct GUID here, so it is
    an instance identity, not a type tag — and a clone that keeps the donor's
    collides with it in the level registry. That is invisible in the emitted
    bytes and in every static check: the assets install, register and resolve
    perfectly, and the tile simply never appears in a generated map.

    (The display name that follows the GUID is NOT identity: three different
    levels all call themselves `6x6_Healing_01`, a copy-paste in the shipped
    data, so it is left alone. The prefab entity has a GUID-shaped field too,
    but 37 different tiles share one value — that one is a type tag, so it is
    also left alone.)
    """
    lits = doc.get("_literals") or []
    if len(lits) <= _LEVEL_GUID_LITERAL:
        raise PropCookError("level has no literal chunk to carry an identity GUID")
    raw = bytearray(bytes.fromhex(lits[_LEVEL_GUID_LITERAL]))
    if len(raw) < _LEVEL_GUID_OFF + _LEVEL_GUID_LEN:
        raise PropCookError("level literal too short to hold an identity GUID")
    raw[_LEVEL_GUID_OFF:_LEVEL_GUID_OFF + _LEVEL_GUID_LEN] = derive_guid(seed)
    lits[_LEVEL_GUID_LITERAL] = bytes(raw).hex()
    doc["_literals"] = lits


def override_tile_level(donor_cooked: bytes, object_swaps: dict[str, str]) -> bytes:
    """Swap placed objects in a tile level, leaving it otherwise untouched.

    The in-place counterpart to :func:`clone_tile_level`: the level keeps its
    own resource path, its bare identifier and — critically — its identity
    GUID, because it is still the same level. Only which entity stands at a
    given transform changes.

    Use this when overriding a *shipped* tile rather than adding a new one.
    Cloning would mean a second level under a new name, a new GUID, and a
    prefab override to point at it — three extra moving parts on an asset the
    engine may reach through references the mod does not control. The Dark
    Hills starting tile is the case that proves it: cloning its level crashed
    the game at load, while the additive path in the same build did not.
    """
    handler, doc = _refs_doc("oCGameStream", donor_cooked)
    refs = list(doc.get("asset_refs") or [])
    missing = [k for k in object_swaps if k not in refs]
    if missing:
        raise PropCookError(
            f"level places no object {missing!r}; it places: "
            f"{sorted({r for r in refs if r.lower().endswith('.entity.ot')})}"
        )
    doc["asset_refs"] = [object_swaps.get(r, r) for r in refs]
    return _emit(handler, doc)


def clone_tile_level(donor_cooked: bytes, self_ref: str, new_self_ref: str,
                     object_swaps: dict[str, str]) -> bytes:
    """Clone a tile level: rename it, and swap object references inside it.

    A level names itself in two forms — the full ``…\\X.level.ot`` resource path
    and a bare ``…\\X`` identifier — and BOTH have to move to the new name or
    the clone collides with the original in the level registry.

    ``object_swaps`` maps a placed object's entity reference to its
    replacement, which is how a custom prop takes over the transform (position,
    rotation, scale) the donor's object occupied. Everything else in the level —
    terrain patch, grass scatter, props — is untouched, so the custom structure
    lands in a finished-looking tile instead of on a bare plane.

    The clone is also given a fresh identity GUID (see :func:`_restamp_level_guid`)
    — without it the copy collides with its donor in the level registry and the
    tile never appears, with nothing anywhere reporting a problem.
    """
    handler, doc = _refs_doc("oCGameStream", donor_cooked)
    refs = list(doc.get("asset_refs") or [])
    bare, new_bare = self_ref.removesuffix(".level.ot"), new_self_ref.removesuffix(".level.ot")

    if self_ref not in refs:
        raise PropCookError(
            f"level does not name itself {self_ref!r}; refs[0] is {refs[0]!r}"
        )
    missing = [k for k in object_swaps if k not in refs]
    if missing:
        raise PropCookError(
            f"level places no object {missing!r}; it places: "
            f"{sorted({r for r in refs if r.lower().endswith('.entity.ot')})}"
        )

    out = []
    for r in refs:
        if r == self_ref:
            out.append(new_self_ref)
        elif r == bare:
            out.append(new_bare)
        else:
            out.append(object_swaps.get(r, r))
    doc["asset_refs"] = out
    _restamp_level_guid(doc, new_self_ref)
    return _emit(handler, doc)


def clone_tile_prefab(donor_cooked: bytes, level_ref: str,
                      new_level_ref: str, new_self_ref: str | None = None) -> bytes:
    """Clone a tile's prefab entity, repointing it at a different level.

    This is an ``oCEntitySettingsResource`` like any prop, so it needs its own
    component identity GUIDs for the same reason — see
    :func:`restamp_entity_guids`.
    """
    present = {s for _sec, _off, s in entity_strings.list_strings(donor_cooked)}
    if level_ref not in present:
        raise PropCookError(
            f"tile prefab does not reference {level_ref!r}; level refs found: "
            f"{sorted(s for s in present if s.lower().endswith('.level.ot'))}"
        )
    out = entity_strings.replace_strings(donor_cooked, {level_ref: new_level_ref})
    return restamp_entity_guids(out, new_self_ref) if new_self_ref else out
