"""Manifest builder for the ``item`` content kind.

Takes a :class:`rsmm.sdk.content.ContentDef` and produces the dict that
will be persisted as ``_pending_items/<id>.json``. Pure data; no I/O.

The output is intentionally additive: every byte we *can* synthesize
from mined schema lives under ``synthesized``, and everything else
delegates to ``cloned_from`` (a vanilla item id whose cooked bytes are
copied verbatim and patched at the known offsets). As more offsets are
mined, the ``synthesized`` map grows and ``cloned_from`` becomes
optional. The apply layer can audit which fields are real vs cloned
because each entry tags itself with a ``source`` of either
``"schema"`` or ``"todo_confirm"``.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from .. import _common as C
from . import schema as S

#: Community rarity vocab -> numeric tier the runtime int-signal carries.
#: Mapping is provisional (see ``items.md`` "TODO: confirm" on the three
#: int signals of ``oCDtEntityCpntMagicalObject``). Lowercased lookup so
#: ``"common"``, ``"Common"``, ``"COMMON"`` all resolve identically.
_RARITY_NAMES: dict[str, int] = {
    "common":    0,
    "rare":      1,
    "epic":      2,
    "legendary": 3,
    "cursed":    4,
}


def _coerce_int(value: Any, *, names: Mapping[str, int] | None = None,
                default: int = 0) -> int:
    """Best-effort int coerce for fields that accept either ints or strings.

    * ``None``                  → ``default``
    * ``bool``                  → ``int(value)`` (Python semantics)
    * ``int``                   → returned as-is
    * digit / hex / signed str  → ``int(value, 0)``
    * named string (via ``names``) → looked up case-insensitively
    """
    if value is None:
        return default
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        text = value.strip()
        if names is not None:
            key = text.lower()
            if key in names:
                return names[key]
        if text:
            try:
                return int(text, 0)
            except ValueError:
                pass
        raise ValueError(
            f"expected int (or one of {sorted(names or ())}), got {value!r}"
        )
    raise ValueError(f"expected int, got {type(value).__name__}: {value!r}")


# ----------------------------------------------------------------------------
# Public data shapes — kept JSON-serialisable.
# ----------------------------------------------------------------------------

@dataclass
class FieldPatch:
    """One byte-level overwrite into the cloned base bytes.

    ``offset`` is the byte offset into the cooked record. ``kind`` is
    one of ``u8|u16|u32|f32|cstr|ptr`` (the apply layer maps each to
    an encoder). ``source`` records whether this came from genuinely
    mined RE (``"schema"``) or from a placeholder that still needs
    cross-validation (``"todo_confirm"``).
    """

    name: str
    offset: int
    kind: str
    value: Any
    source: str = "schema"   # one of: "schema", "todo_confirm"

    def to_json(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "offset": self.offset,
            "kind": self.kind,
            "value": self.value,
            "source": self.source,
        }


@dataclass
class ItemManifest:
    """Serialisable manifest written to ``_pending_items/<id>.json``."""

    kind: str
    id: str
    mod: str
    schema_version: int
    cloned_from: str | None
    text_keys: dict[str, str]              # locale-neutral i18n keys we own
    reward_def: dict[str, Any]             # `oCDtRewardDefinition` synth + patches
    selector: dict[str, Any]               # selector record (per drop site)
    magical_object: dict[str, Any]         # runtime `oCDtEntityCpntMagicalObject`
    raw_fields: dict[str, Any]             # whatever the mod author passed in
    notes: list[str] = field(default_factory=list)

    def to_json(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "id": self.id,
            "mod": self.mod,
            "schema_version": self.schema_version,
            "cloned_from": self.cloned_from,
            "text_keys": dict(self.text_keys),
            "reward_def": dict(self.reward_def),
            "selector": dict(self.selector),
            "magical_object": dict(self.magical_object),
            "raw_fields": dict(self.raw_fields),
            "notes": list(self.notes),
        }


# ----------------------------------------------------------------------------
# Helpers.
# ----------------------------------------------------------------------------

def _resource_name(mod_id: str, item_id: str) -> str:
    """Logical name that the resource manager will see for this reward."""
    return f"rwd_{mod_id}_{item_id}"


def _patches_to_json(patches: list[FieldPatch]) -> list[dict[str, Any]]:
    return [p.to_json() for p in patches]


# ----------------------------------------------------------------------------
# Per-record synthesizers.
# ----------------------------------------------------------------------------

def build_reward_def(
    *,
    mod_id: str,
    item_id: str,
    display_name_key: str,
) -> tuple[list[FieldPatch], dict[str, Any]]:
    """Synthesize the patch list for an `oCDtRewardDefinition` record."""
    name = _resource_name(mod_id, item_id)
    patches: list[FieldPatch] = [
        FieldPatch("name", S.REWARD_DEF.name_ptr, "cstr", name),
        FieldPatch("name_hash", S.REWARD_DEF.name_hash, "u32", C.name_hash(name)),
        # `display_name` carries the text-bank key, not the literal name.
        # The text bank is merged elsewhere; we just plant the key here.
        FieldPatch("display_name_key", S.REWARD_DEF.display_name_ptr,
                   "cstr", display_name_key),
        FieldPatch("flags", S.REWARD_DEF.flags_word, "u16",
                   S.REWARD_DEF_DEFAULT_FLAGS),
        FieldPatch("entries_ptr", S.REWARD_DEF.entries_ptr, "ptr", 0),
        FieldPatch("entries_length", S.REWARD_DEF.entries_length, "u32", 0),
        FieldPatch("entries_capacity", S.REWARD_DEF.entries_capacity, "u32", 0),
    ]
    meta = {
        "uid": S.REWARD_DEF_UID,
        "size": S.REWARD_DEF_SIZE,
        "library_global": S.REWARD_DEF_LIBRARY_GLOBAL,
        "meta_global": S.REWARD_DEF_META_GLOBAL,
        "resource_extension": S.REWARD_DEF_RESOURCE_EXT,
        "resource_name": name,
        "patches": _patches_to_json(patches),
    }
    return patches, meta


def build_selector(
    *,
    mod_id: str,
    item_id: str,
    tags: list[str],
) -> tuple[list[FieldPatch], dict[str, Any]]:
    """Synthesize a `oCDtRewardEntitySelectorToSpawnEntityCpntSettings`."""
    target_name = _resource_name(mod_id, item_id)
    patches: list[FieldPatch] = [
        FieldPatch("target_name", S.REWARD_SELECTOR.target_name_ptr,
                   "cstr", target_name),
        FieldPatch("target_name_hash", S.REWARD_SELECTOR.target_name_hash,
                   "u32", C.name_hash(target_name)),
        FieldPatch("target_resolved", S.REWARD_SELECTOR.target_resolved_flag,
                   "u32", 1),
        # Parent path stays the engine sentinel until apply resolves it.
        FieldPatch("parent_name_hash", S.REWARD_SELECTOR.parent_name_hash,
                   "u32", S.UNRESOLVED_NAME_HASH),
        FieldPatch("enabled", S.REWARD_SELECTOR.enabled_byte, "u8", 1),
    ]
    meta = {
        "target_resource_name": target_name,
        "tags": list(tags),
        "patches": _patches_to_json(patches),
    }
    return patches, meta


def build_magical_object(
    *,
    rarity: int,
    count: int,
    level: int,
    tags: list[str],
) -> tuple[list[FieldPatch], dict[str, Any]]:
    """Synthesize the runtime `oCDtEntityCpntMagicalObject` int-signal
    initial values plus its flag-list tags.

    The rarity/count/level mapping is TODO_CONFIRM — we annotate each
    patch with ``source="todo_confirm"`` so the apply layer can decide
    whether to write them or skip them on a strict pass.
    """
    patches: list[FieldPatch] = [
        FieldPatch("signal_rarity", S.MAGICAL_OBJECT.signal_rarity,
                   "u32", rarity, source="todo_confirm"),
        FieldPatch("signal_count", S.MAGICAL_OBJECT.signal_count,
                   "u32", count, source="todo_confirm"),
        FieldPatch("signal_level", S.MAGICAL_OBJECT.signal_level,
                   "u32", level, source="todo_confirm"),
    ]
    meta = {
        "runtime_size": S.MAGICAL_OBJECT_RUNTIME_SIZE,
        "tags": list(tags),
        "patches": _patches_to_json(patches),
    }
    return patches, meta


# ----------------------------------------------------------------------------
# Top-level entry point.
# ----------------------------------------------------------------------------

def build_manifest(
    *,
    mod_id: str,
    item_id: str,
    fields: Mapping[str, Any],
    schema_version: int,
) -> ItemManifest:
    """Synthesize the full :class:`ItemManifest` for one item.

    ``fields`` is the raw kwargs dict the mod author passed to
    ``ContentRegistry.register("item", ...)``. Recognised keys:

    * ``name`` (str, required) — display name used as the EN locale
      seed.
    * ``base`` (str, optional) — vanilla item id whose cooked bytes
      are cloned for any field we can't synthesize yet.
    * ``rarity`` / ``drop_weight`` / ``level`` (int, default 0).
    * ``tags`` (list[str], default ``[]``).
    * ``icon`` (str, optional) — relative path to a PNG.Texture.
    """
    display_name = fields.get("name")
    if not display_name:
        raise ValueError(
            f"item {item_id}: 'name' is required (becomes the EN locale "
            f"display string and the RSMM_<mod>_<id>_name text key)"
        )
    base = fields.get("base")
    tags = list(fields.get("tags") or [])
    rarity = _coerce_int(fields.get("rarity"), names=_RARITY_NAMES)
    drop_weight = _coerce_int(fields.get("drop_weight"))
    level = _coerce_int(fields.get("level"))
    icon = fields.get("icon")

    text_key_name = f"RSMM_{mod_id}_{item_id}_name"
    text_key_desc = f"RSMM_{mod_id}_{item_id}_desc"

    reward_patches, reward_meta = build_reward_def(
        mod_id=mod_id, item_id=item_id, display_name_key=text_key_name,
    )
    sel_patches, sel_meta = build_selector(
        mod_id=mod_id, item_id=item_id, tags=tags,
    )
    obj_patches, obj_meta = build_magical_object(
        rarity=rarity, count=drop_weight, level=level, tags=tags,
    )

    notes: list[str] = []
    if base is None:
        notes.append(
            "no 'base' provided — apply layer must refuse this manifest "
            "until a vanilla template is registered for cloning."
        )
    todo_count = sum(
        1 for p in (*reward_patches, *sel_patches, *obj_patches)
        if p.source == "todo_confirm"
    )
    if todo_count:
        notes.append(
            f"{todo_count} field(s) are placeholders with "
            f"source='todo_confirm'; verify via a save-game diff before "
            f"trusting their semantics."
        )
    if icon is not None:
        notes.append(
            "icon override path recorded but not yet emitted — texture "
            "swap is handled by the apply pipeline, not the kind builder."
        )

    return ItemManifest(
        kind="item",
        id=item_id,
        mod=mod_id,
        schema_version=schema_version,
        cloned_from=base,
        text_keys={"name": text_key_name, "desc": text_key_desc},
        reward_def=reward_meta,
        selector=sel_meta,
        magical_object=obj_meta,
        raw_fields=dict(fields),
        notes=notes,
    )
