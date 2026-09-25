"""What a `manifest.toml` may contain — the one list lint, the SDK and the
editor schema all check against.

Every key here is one some reader actually consumes. The reason this module
exists is the opposite case: a key NOTHING reads. A misspelled `valeu = 10` in a
stat patch, or `colour = "red"` on an enemy, used to parse, lint clean, install,
and change nothing, because each consumer only ever `.get()`s the keys it knows.
The mod was "installed" and did nothing, and nothing said why. So:

* :func:`rsmm.sdk.content.ContentRegistry.register` refuses an unknown content
  field (the SDK and `rsmm apply` both register through it);
* `rsmm lint` reports unknown keys in `[mod]`, `[[patch]]` and `[[content]]`,
  with the nearest valid name;
* :func:`json_schema` renders the same lists for editors (`rsmm docs-gen`
  writes it to the docs site), so the typo is underlined as it is typed.

Only TOP-LEVEL keys are listed. A nested table (`[content.transform]`,
`[content.kinds.Camp]`) belongs to its parent field and is validated by the
kind that reads it.

`tests/test_manifest_spec.py` keeps this honest in both directions: every
literal key a kind module reads must be declared here, and every key declared
here must be read somewhere, so a field cannot be added to a kind (or removed
from it) without this list following.
"""

from __future__ import annotations

import difflib

#: Keys every `[[content]]` block may carry, whatever its kind.
CONTENT_COMMON: frozenset[str] = frozenset({"kind", "id", "schema_version"})

#: Top-level fields each content kind reads, beyond :data:`CONTENT_COMMON`.
#: Modes are unioned: a kind that also checks per-mode (enemy, item ban,
#: boss, shop) still raises its own, more specific error at emit.
CONTENT_FIELDS: dict[str, frozenset[str]] = {
    "item": frozenset({
        "mode", "base", "name", "display_name", "description", "rarity", "icon",
        "value_patches", "unique_identity",
        "items",                                # mode = "ban"
        "tags", "drop_weight", "level",         # legacy manifest fallback
    }),
    "enemy": frozenset({
        # mode = "clone"
        "base", "name", "display_name", "tribe", "flags", "add_flags",
        "power", "weight", "entity",
        # mode = "override"
        "mode", "pools", "enemies", "exclude", "mix", "seed", "cross_biome",
        "imports", "repoint_pools", "casts",
    }),
    "boss": frozenset({"base", "becomes", "name"}),
    "map": frozenset({"base", "chapter", "tribe"}),
    "hero": frozenset({
        "base", "name", "description", "model", "transform", "albedo", "mra",
        "normal", "portrait", "own_entity", "weapons", "animations", "outfits",
        "values", "references", "abilities",
    }),
    "talent": frozenset({
        "hero", "file", "value_patches", "int_patches", "union_patches",
        "rewires", "clone_nodes",
    }),
    "skill": frozenset({
        "mode", "hero", "source", "controller", "name", "display_name",
        "description", "icon",
    }),
    "modifier": frozenset({"base", "name", "description", "effect"}),
    "game_mode": frozenset({"base", "chapters"}),
    "reward": frozenset({"base", "counts", "ban"}),
    "melody": frozenset({"base", "effect", "exclude"}),
    "poi": frozenset({
        "base", "chapters", "copies", "icon", "icon_source", "kinds",
        "own_level", "places", "prop", "replace_base", "swaps", "weight",
    }),
    "mesh": frozenset({"target", "model", "transform"}),
    "animation": frozenset({"target", "source", "clip", "strict"}),
    "tilegen": frozenset({"chapter", "kinds", "quotas", "slots", "fill"}),
    "shop": frozenset({"prices", "price_scale", "offers", "slots", "config"}),
}

#: `[[patch]]` kinds: required and optional top-level keys (besides `kind`).
#: A `stat` patch's settable fields depend on the value it names — `value` for
#: globals and modifiers, `min`/`max` for camp difficulty bands — so lint
#: narrows `STAT_VALUE_FIELDS` per name against the stat catalog.
STAT_VALUE_FIELDS: frozenset[str] = frozenset({"value", "min", "max"})
PATCH_FIELDS: dict[str, dict[str, frozenset[str]]] = {
    "stat": {"required": frozenset({"name"}), "optional": STAT_VALUE_FIELDS},
    "texture": {"required": frozenset({"target", "donor"}), "optional": frozenset()},
    "ot": {"required": frozenset({"selector", "field", "value"}),
           "optional": frozenset({"file", "selector_field"})},
}

#: `[mod]` keys some reader consumes (apply, the dependency graph, the store,
#: the desktop app). Unknown keys here are a lint WARNING, not an error: the
#: table is read by more tools than any other, so a key missing from this list
#: is likelier than for content.
MOD_FIELDS: dict[str, str] = {
    "id": "Mod id — the folder name under mods/.",
    "name": "Display name.",
    "version": "Semantic version, e.g. 1.2.0.",
    "author": "Who made it.",
    "enabled": "Whether `rsmm apply` installs it.",
    "sdk_version": "SDK range this mod was written against, e.g. \">=3.0,<4\".",
    "experimental": "Opt in to content kinds not yet confirmed in game.",
    "summary": "One-line tagline for the store (≤512 chars).",
    "description": "Long description for the store (≤8192 chars).",
    "license": "SPDX id or licence name.",
    "repo_url": "Source repository URL.",
    "homepage_url": "Homepage URL.",
    "tags": "Store discovery tags (≤16, each ≤32 chars).",
    "game_build": "Game build this mod needs.",
    "min_loader": "Oldest loader version this mod works with.",
    "load_order": "Lower loads first (default 100); later wins a conflict.",
    "priority": "Tie-breaker within one load_order.",
    "requires": "Mods that must be installed: [\"other-mod >=1.0\"].",
    "recommends": "Mods worth installing alongside.",
    "suggests": "Mods that go well with this one.",
    "conflicts": "Mods that must not be enabled with this one.",
    "replaces": "Mod ids this one supersedes.",
    "multiplayer_scope": "cosmetic | deterministic-shared | host-authoritative | local-only.",
}

#: Top-level tables a manifest may contain.
TOP_LEVEL: frozenset[str] = frozenset({
    "mod", "content", "patch", "overlay", "experiment", "config", "provides",
})


def content_fields(kind: str) -> frozenset[str] | None:
    """Every key a `[[content]]` block of ``kind`` may carry, or None for an
    unknown kind."""
    fields = CONTENT_FIELDS.get(kind)
    return None if fields is None else fields | CONTENT_COMMON


def unknown_keys(keys, allowed) -> list[tuple[str, str | None]]:
    """``(key, nearest valid key or None)`` for each key not in ``allowed``."""
    allowed = sorted(allowed)
    out = []
    for k in sorted(set(keys) - set(allowed)):
        near = difflib.get_close_matches(k, allowed, n=1, cutoff=0.6)
        out.append((k, near[0] if near else None))
    return out


def describe_unknown(found: list[tuple[str, str | None]]) -> str:
    """``"colour (did you mean 'color'?), foo"`` for an error message."""
    return ", ".join(f"{k} (did you mean {near!r}?)" if near else k
                     for k, near in found)


SCHEMA_URL = "https://docs.rsmm.me/manifest.schema.json"


def json_schema() -> dict:
    """JSON Schema (draft-07) for `manifest.toml`, for TOML editor support
    (Taplo / Even Better TOML: put ``#:schema <SCHEMA_URL>`` on line 1).

    Unknown keys are rejected in `[[content]]` and `[[patch]]` — the same rule
    `rsmm lint` and the SDK apply — and flagged in `[mod]`.
    """
    def keys(names) -> dict:
        return {k: {} for k in sorted(names)}

    content_branches = []
    for kind in sorted(CONTENT_FIELDS):
        content_branches.append({
            "if": {"properties": {"kind": {"const": kind}}, "required": ["kind"]},
            "then": {"properties": keys(content_fields(kind)),
                     "additionalProperties": False},
        })
    patch_branches = []
    for kind in sorted(PATCH_FIELDS):
        spec = PATCH_FIELDS[kind]
        patch_branches.append({
            "if": {"properties": {"kind": {"const": kind}}, "required": ["kind"]},
            "then": {"properties": keys(spec["required"] | spec["optional"] | {"kind"}),
                     "required": sorted(spec["required"]),
                     "additionalProperties": False},
        })

    return {
        "$schema": "http://json-schema.org/draft-07/schema#",
        "$id": SCHEMA_URL,
        "title": "RSMM mod manifest",
        "description": "manifest.toml of a Ravenswatch Mod Manager mod. "
                       "Generated by `rsmm docs-gen` from rsmm.sdk.manifest_spec.",
        "type": "object",
        "properties": {
            "mod": {
                "type": "object",
                "properties": {
                    **{k: {"description": d} for k, d in MOD_FIELDS.items()},
                    "id": {"type": "string", "description": MOD_FIELDS["id"]},
                    "name": {"type": "string", "description": MOD_FIELDS["name"]},
                    "version": {"type": "string", "description": MOD_FIELDS["version"]},
                    "enabled": {"type": "boolean", "description": MOD_FIELDS["enabled"]},
                    "experimental": {"type": "boolean",
                                     "description": MOD_FIELDS["experimental"]},
                    "tags": {"type": "array", "items": {"type": "string"},
                             "description": MOD_FIELDS["tags"]},
                    "load_order": {"type": "integer",
                                   "description": MOD_FIELDS["load_order"]},
                    "priority": {"type": "integer", "description": MOD_FIELDS["priority"]},
                    "multiplayer_scope": {
                        "enum": ["cosmetic", "deterministic-shared",
                                 "host-authoritative", "local-only"],
                        "description": MOD_FIELDS["multiplayer_scope"]},
                },
                "additionalProperties": False,
            },
            "content": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "kind": {"enum": sorted(CONTENT_FIELDS),
                                 "description": "Content kind."},
                        "id": {"type": "string",
                               "description": "Unique within this mod and kind."},
                    },
                    "required": ["kind", "id"],
                    "allOf": content_branches,
                },
            },
            "patch": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {"kind": {"enum": sorted(PATCH_FIELDS)}},
                    "required": ["kind"],
                    "allOf": patch_branches,
                },
            },
        },
        "required": ["mod"],
    }
