"""Map (biome) content builder. Clone-and-patch only at v3.0."""

from __future__ import annotations

import json
from pathlib import Path

from ..content import ContentDef, SchemaNotMined


def emit(mod_id: str, defn: ContentDef, out_dir: Path) -> list[Path]:
    base = defn.fields.get("base")
    if not base:
        raise SchemaNotMined(
            f"map {defn.id}: needs a 'base' (vanilla biome/level id) to clone."
        )
    marker = out_dir / "_pending_maps" / f"{defn.id}.json"
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text(json.dumps({
        "kind": "map", "id": defn.id, "mod": mod_id,
        "base": base, "fields": defn.fields,
        "schema_version": defn.schema_version,
    }, indent=2), encoding="utf-8")
    return [marker]
