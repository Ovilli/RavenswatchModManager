"""Enemy content builder.

Same clone-and-patch shape as `items.py`. Schema mining for enemy
entities is open work; until it lands, only clone-from-base is allowed.
"""

from __future__ import annotations

import json
from pathlib import Path

from ..content import ContentDef, SchemaNotMined


def emit(mod_id: str, defn: ContentDef, out_dir: Path) -> list[Path]:
    base = defn.fields.get("base")
    if not base:
        raise SchemaNotMined(
            f"enemy {defn.id}: needs a 'base' (vanilla enemy id) to clone. "
            f"Full synthesis blocked on enemy-entity schema RE."
        )
    marker = out_dir / "_pending_enemies" / f"{defn.id}.json"
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text(json.dumps({
        "kind": "enemy",
        "id": defn.id,
        "mod": mod_id,
        "base": base,
        "fields": defn.fields,
        "schema_version": defn.schema_version,
    }, indent=2), encoding="utf-8")
    return [marker]
