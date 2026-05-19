"""Boss content builder. Clone-and-patch only at v3.0; full synthesis
blocked on boss-fight-controller schema RE."""

from __future__ import annotations

import json
from pathlib import Path

from ..content import ContentDef, SchemaNotMined


def emit(mod_id: str, defn: ContentDef, out_dir: Path) -> list[Path]:
    base = defn.fields.get("base")
    if not base:
        raise SchemaNotMined(
            f"boss {defn.id}: needs a 'base' (vanilla boss id) to clone."
        )
    marker = out_dir / "_pending_bosses" / f"{defn.id}.json"
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text(json.dumps({
        "kind": "boss", "id": defn.id, "mod": mod_id,
        "base": base, "fields": defn.fields,
        "schema_version": defn.schema_version,
    }, indent=2), encoding="utf-8")
    return [marker]
