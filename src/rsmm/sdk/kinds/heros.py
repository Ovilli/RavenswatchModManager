"""Hero content builder.

Heroes are the hardest playable kind: ``oCDtHeroDefinition`` has **no**
registered class UID and is created/destroyed by the deserializer of its
parent ``SkillProfileDataSettings`` record
(UID ``0x186adbdf``, size ``0xd0``). See ``docs/_re/kinds/heroes.md``
for the per-offset field map, named-slot owner table, and the
``oCTLibrary<oCDtHeroDefinition>`` singleton search criteria.

Note: the kind name registered by ``ContentRegistry`` is ``"hero"`` — the
module is ``heros.py`` (plural ``heros`` = ``"hero" + "s"``) to match the
``f"{kind}s"`` lazy-import fallback in :mod:`rsmm.sdk.content`.

Until the hero library singleton is located and TLS injection lands,
this builder stages a manifest under ``<out>/_pending_heros/<id>/``
mirroring the chain documented in the RE notes:

* ``hero.json``         — top-level manifest (display name, clone base,
                          ability roster).
* ``skillprofile.json`` — parent settings record (UID ``0x186adbdf``)
                          metadata + named-slot owner table.
* ``i18n.json``         — text-bank overrides for the display name +
                          per-ability description keys.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Final

from ..content import ContentDef, SchemaNotMined
from . import _common as C

#: ``SkillProfileDataSettings`` — the *parent* record that owns a hero
#: definition as a typed-field child. Confirmed via ``FUN_140192330``
#: (registrar) and ``FUN_1403122f0`` (schema callback). The hero itself
#: has no UID because it's never serialized standalone.
SKILL_PROFILE_SETTINGS_UID: Final[int] = 0x186ADBDF
SKILL_PROFILE_SETTINGS_SIZE: Final[int] = 0xD0

#: Per-slot ``oCMetaClass*`` owner pointers used by the hero ctor when
#: writing the ``&DAT_140eb46d0`` sentinel into each named slot. The
#: loader uses these to know *which library* to look the name up in
#: once the cooked record provides a string. Confirmed via
#: ``FUN_1403143b0`` (hero ctor walk, heroes.md). Values are addresses
#: in the game's data segment.
HERO_NAMED_SLOT_OWNERS: Final[dict[str, int]] = {
    "animation":  0x141447250,
    "ability":    0x141446E18,
    "ui_spawner": 0x141446F38,
    "voice":      0x1414470F0,
}

#: Per-hero ability roster cardinality. Read off the ctor body, which
#: emits exactly four ability blocks at ``[0x65]/[0x73]/[0x81]/[0x8f]``.
ABILITY_COUNT: Final[int] = 4

#: Per-hero melody / talent slot cardinality (ctor blocks at
#: ``[0xbb]/[0xc2]/[0xc9]/[0xd0]``).
MELODY_COUNT: Final[int] = 4


def emit(mod_id: str, defn: ContentDef, out_dir: Path) -> list[Path]:
    """Materialize a hero clone manifest under ``out_dir``.

    Required fields:
        ``base``  — id of a vanilla hero to clone for fields the
                    SDK can't synthesize yet (model, anim refs, AI
                    skill profile, etc.).

    Optional fields:
        ``name``         short identifier (defaults to ``defn.id``).
        ``display_name`` user-facing string; seeded into the EN text bank
                         as ``RSMM_<mod>_<id>_name``.
        ``abilities``    list of up to ``ABILITY_COUNT`` ability dicts
                         with optional ``id``, ``name``, ``description``
                         keys. Descriptions become
                         ``RSMM_<mod>_<id>_ability<n>_desc`` text keys.

    Returns the list of paths written under
    ``out_dir/_pending_heros/<id>/``.
    """
    C.validate_id("hero", defn.id)
    base = defn.fields.get("base")
    if not base or not isinstance(base, str):
        raise SchemaNotMined(
            f"hero {defn.id}: needs a 'base' (vanilla hero id) to clone — "
            f"oCDtHeroDefinition has no registered UID and the "
            f"oCTLibrary<oCDtHeroDefinition> singleton address is still "
            f"unknown. See docs/_re/kinds/heroes.md."
        )

    short_name = str(defn.fields.get("name") or defn.id)
    display_name = str(
        defn.fields.get("display_name")
        or defn.fields.get("name")
        or defn.id
    )
    abilities_raw = defn.fields.get("abilities") or []
    if not isinstance(abilities_raw, list):
        raise ValueError(
            f"hero {defn.id}: 'abilities' must be a list, got "
            f"{type(abilities_raw).__name__}."
        )
    if len(abilities_raw) > ABILITY_COUNT:
        raise ValueError(
            f"hero {defn.id}: at most {ABILITY_COUNT} abilities supported "
            f"(per heroes.md ctor walk); got {len(abilities_raw)}."
        )

    text_key_name = f"RSMM_{mod_id}_{defn.id}_name"
    strings: dict[str, str] = {text_key_name: display_name}
    abilities: list[dict[str, Any]] = []
    for i, ab in enumerate(abilities_raw):
        if not isinstance(ab, dict):
            raise ValueError(
                f"hero {defn.id}: ability #{i} must be a dict, got "
                f"{type(ab).__name__}."
            )
        desc_key = f"RSMM_{mod_id}_{defn.id}_ability{i + 1}_desc"
        description = ab.get("description") or ab.get("desc")
        if description is not None:
            strings[desc_key] = str(description)
        abilities.append({
            "id":           ab.get("id"),
            "name":         ab.get("name"),
            "description":  description,
            "description_key": desc_key,
        })

    out_root = out_dir / "_pending_heros" / defn.id
    written: list[Path] = []

    written.append(C.write_json(out_root / "hero.json", {
        "schema": "rsmm.hero.v1",
        "kind": "hero",
        "id": defn.id,
        "mod": mod_id,
        "name": short_name,
        "display_name": display_name,
        "display_name_key": text_key_name,
        "base": base,
        "abilities": abilities,
        "schema_version": defn.schema_version,
        "pieces": {
            "skillprofile": "skillprofile.json",
            "i18n":         "i18n.json",
        },
    }))
    written.append(C.write_json(out_root / "skillprofile.json", {
        "schema": "rsmm.skillprofile.v1",
        "id": defn.id,
        "cloned_from": base,
        "settings_uid": hex(SKILL_PROFILE_SETTINGS_UID),
        "settings_size": hex(SKILL_PROFILE_SETTINGS_SIZE),
        "ability_count": ABILITY_COUNT,
        "melody_count": MELODY_COUNT,
        "named_slot_owners": {k: hex(v) for k, v in HERO_NAMED_SLOT_OWNERS.items()},
        "empty_string_sentinel": hex(C.EMPTY_STRING_SENTINEL),
        "unresolved_name_hash": hex(C.UNRESOLVED_NAME_HASH),
        "notes": [
            "oCDtHeroDefinition has no UID — it is constructed inline by"
            " the SkillProfileDataSettings deserializer (FUN_1403122f0).",
            "Until oCTLibrary<oCDtHeroDefinition> singleton is located,"
            " runtime injection is not possible; apply pipeline must emit"
            " cooked asset bytes through LoadUsedRscList_or_Archive.",
            "Hero pool patch (Map+0x720..0x728 random / +0x738..0x748"
            " played) is still TODO — see heroes.md step 5.",
        ],
    }))
    written.append(C.write_json(out_root / "i18n.json", {
        "schema": "rsmm.hero_i18n.v1",
        "mod": mod_id,
        "hero_id": defn.id,
        "strings": strings,
        "fallback_locale": "EN",
    }))
    return written
