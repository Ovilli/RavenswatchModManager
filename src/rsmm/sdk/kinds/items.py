"""Item (magical-object) content builder.

Public ``emit()`` entry point for the ``item`` content kind. Produces a
manifest derived from the magical-object / reward chain reverse-engineered
in ``docs/_re/kinds/items.md``.

Pipeline:

1. Take the mod author's ``ContentDef`` (``name``, ``rarity``,
   ``drop_weight``, ``tags``, ``base`` for cloning, etc.).
2. Synthesize per-record patch tables for the three pieces of the
   magical-object chain (``oCDtRewardDefinition``,
   ``oCDtRewardEntitySelectorToSpawnEntityCpntSettings``,
   ``oCDtEntityCpntMagicalObject``). See
   :mod:`rsmm.sdk.kinds.item.builder` for per-record assembly and
   :mod:`rsmm.sdk.kinds.item.schema` for the byte offsets.
3. Write a text-bank override for the EN display name (the i18n
   merger later layers locale-specific overrides on top).
4. Persist the manifest under ``<out>/_pending_items/<id>.json``.

Genuine-schema vs synthesized vs cloned-and-patched
---------------------------------------------------

* **Genuine schema** — offsets reverse-engineered out of the binary
  and trusted. Tagged ``source="schema"`` in the manifest.
* **TODO-confirm** — offsets we *think* we know (e.g. which int signal
  on the runtime component carries "rarity") but haven't byte-diffed
  against a known-good save. Tagged ``source="todo_confirm"``.
* **Cloned-and-patched** — every byte we haven't mined falls through
  to a copy of the ``base`` item's cooked bytes; only the fields above
  are overwritten.

The apply layer audits the breakdown so authors see, per item, which
fields are real vs inherited.
"""

from __future__ import annotations

import logging
from pathlib import Path

from ..content import ContentDef, SchemaNotMined
from . import _common as C
from .item import schema as item_schema
from .item.builder import ItemManifest, build_manifest

_log = logging.getLogger(__name__)

#: Directory (under ``out_dir``) collecting every pending item manifest.
PENDING_ITEMS_SUBDIR = "_pending_items"

#: Directory (under ``out_dir``) where per-locale text-bank overrides land.
#: Prefixed ``_pending_`` so the applier's asset walk (see
#: :class:`rsmm.cli.apply_mods.Mod.files`) skips it — these are SDK
#: staging output, not cooked assets.
TEXT_BANK_OVERRIDES_SUBDIR = "_pending_text_overrides"


def emit(mod_id: str, defn: ContentDef, out_dir: Path) -> list[Path]:
    """Materialize a single item def under ``out_dir``.

    Required fields:
        ``base``  — id of a vanilla item to clone for unmined bytes.
                    Without it the manifest can't be applied because
                    most of the 0x298-byte ``oCDtRewardDefinition``
                    record isn't synthesized yet.

    Optional fields:
        ``name``         human-readable display name; defaults to
                         ``defn.id``. Becomes the EN seed for
                         ``RSMM_<mod>_<id>_name``.
        ``rarity`` / ``drop_weight`` / ``level`` (int) — initial values
                         for the three int signals on
                         ``oCDtEntityCpntMagicalObject``
                         (``+0x1f8/+0x218/+0x238``). Label mapping is
                         provisional; see ``items.md``.
        ``tags`` (list[str]) — feed into the selector's
                         ``oCCustomFlagList`` (``+0x130..+0x148``).
        ``icon`` (str) — relative path to a PNG.Texture override.

    Returns the list of files written under ``out_dir``.
    """
    C.validate_id("item", defn.id)
    base = defn.fields.get("base")
    if not base or not isinstance(base, str):
        raise SchemaNotMined(
            f"item {defn.id}: needs a 'base' (vanilla item id) to clone "
            f"for the unmined bytes of the 0x298-byte oCDtRewardDefinition "
            f"record. See docs/_re/kinds/items.md."
        )

    display_name = str(
        defn.fields.get("name")
        or defn.fields.get("display_name")
        or defn.id
    )
    fields = {**defn.fields, "name": display_name}

    manifest = build_manifest(
        mod_id=mod_id,
        item_id=defn.id,
        fields=fields,
        schema_version=max(
            int(defn.schema_version or 1),
            item_schema.ITEM_MANIFEST_SCHEMA_VERSION,
        ),
    )

    written: list[Path] = []
    written.append(C.write_json(
        out_dir / PENDING_ITEMS_SUBDIR / f"{defn.id}.json",
        manifest.to_json(),
    ))
    written.append(_write_text_override(
        out_dir, mod_id, defn.id, display_name, manifest.text_keys["name"],
    ))

    for note in manifest.notes:
        _log.info("item %s/%s: %s", mod_id, defn.id, note)

    return written


# --------------------------------------------------------------------------- #
# Internals — keep small + side-effect-only.
# --------------------------------------------------------------------------- #

def _write_text_override(out_dir: Path, mod_id: str, item_id: str,
                         display_name: str, key: str) -> Path:
    """Drop a minimal EN-locale text-bank override for the display name.

    The i18n merger (``rsmm.sdk.i18n.merge_bundles``) later folds these
    into the per-locale text bank. We emit only the EN seed here; if
    the mod ships a richer ``lang/<locale>.toml``, the merger wins.
    """
    return C.write_json(
        out_dir / TEXT_BANK_OVERRIDES_SUBDIR / f"{mod_id}__{item_id}__EN.json",
        {
            "locale": "EN",
            "mod": mod_id,
            "id": item_id,
            "strings": {key: display_name},
            "note": (
                "Seeded by rsmm.sdk.kinds.items.emit; mod's "
                "lang/<locale>.toml entries override this."
            ),
        },
    )
