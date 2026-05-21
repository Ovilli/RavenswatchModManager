"""Item (magical object) content builder.

Currently uses a **clone-and-patch** strategy:

  1. Read a vanilla item's cooked `.gen` bytes from `data/templates/item/`
     (extracted at SDK install time by `_schema_mining.extract_template`).
  2. Patch the few fields we know how to locate (id-string, text-bank
     keys, stat-globals). Unknown fields stay byte-for-byte identical
     to the donor.
  3. Write the patched bytes under a new asset path in the mod's
     `assets/` tree, plus a text-bank override for the visible name.

When `_schema_mining` finishes the magical-object schema, we replace the
clone-and-patch path with a true encoder. The public `emit()` signature
stays the same so mods don't need to change.
"""

from __future__ import annotations

from pathlib import Path

from ..content import ContentDef, SchemaNotMined

TEMPLATE_DIR_NAME = "templates/item"


def emit(mod_id: str, defn: ContentDef, out_dir: Path) -> list[Path]:
    """Materialize a single item def under `out_dir`.

    Required fields:
        base   — id of a vanilla item to clone (e.g. "VanillaSword")
        name   — display name (will be set as RSMM_<mod>_<id>_name in EN)
    Optional:
        damage, stats, icon (path to PNG.Texture)
    """
    base = defn.fields.get("base")
    if not base:
        raise SchemaNotMined(
            f"item {defn.id}: clone-and-patch requires a 'base' field "
            f"naming a vanilla item; a fully synthesized item builder "
            f"needs the oCEntityCpntMagicalObjectSettings schema, which "
            f"isn't mined yet. See docs/SDK_V3.md → Open work."
        )
    # Stub: the actual clone needs the template directory + asset_map
    # entry for `base`. We emit a placeholder marker so the manifest
    # carries the registration; the merge step is where the actual
    # bytes get written once the template extractor is wired.
    marker = out_dir / "_pending_items" / f"{defn.id}.json"
    marker.parent.mkdir(parents=True, exist_ok=True)
    import json
    marker.write_text(json.dumps({
        "kind": "item",
        "id": defn.id,
        "mod": mod_id,
        "base": base,
        "fields": defn.fields,
        "schema_version": defn.schema_version,
    }, indent=2), encoding="utf-8")
    return [marker]
