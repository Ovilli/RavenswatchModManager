"""Chapter scenery content builder — SDK entry point.

``emit()`` turns one ``[[content]] kind = "scenery"`` declaration into an edited
copy of one of a chapter's shipped SCENERY levels (the levels that place the
rocks, trees, bushes and ruins every run of that chapter shows), written at its
own decoded path so ``apply`` installs it as a plain in-place override and
``restore`` puts it back. The map editor's Objects tool writes these for you.

Edits are applied to the SHIPPED level every time and each one is anchored on
the object's entity and shipped position, so a game patch that renumbers the
level fails the emit instead of moving some other object.

Fields:
    ``chapter`` (str, required)  biome key (``DarkHills``, ``Avalon``,
                                 ``Storm_Island``).
    ``level``   (str, required)  the scenery level's decoded path, e.g.
                                 ``Ot/DarkHills/Map_Dark_Hills_Scenery_NorthEast.level.ot.GameStream.gen``.
    ``moves``   (table)          ``{ "<object id>" = { entity, at = [x, y, z],
                                 pos = [x, y, z], yaw = deg | quat = [x, y, z, w],
                                 scale = s | [sx, sy, sz] } }`` — ``entity`` and
                                 ``at`` (the shipped position) anchor the object.
    ``removes`` (table)          ``{ "<object id>" = { entity, at } }`` — sinks
                                 the object far under the map (it stops showing
                                 and blocking); true removal is not proven yet.
    ``adds``    (array)          ``[{ entity, pos = [x, y, z], yaw, scale }]`` —
                                 only entities the chapter already places, so its
                                 resource cache preloads them.
"""

from __future__ import annotations

from pathlib import Path

from ...engine import level_placements as LP
from ...engine import map_editor as ME
from ...engine import scenery_edit as SE
from ..content import ContentDef, ContentError, SchemaNotMined
from . import _common as C


def emit(mod_id: str, defn: ContentDef, out_dir: Path) -> list[Path]:
    """Materialize one scenery def into the mod's ``assets/`` tree."""
    C.validate_id("scenery", defn.id)
    chapter = defn.fields.get("chapter")
    level = defn.fields.get("level")
    if not chapter or not isinstance(chapter, str):
        raise SchemaNotMined(f"scenery {defn.id}: needs a 'chapter' (one of "
                             + ", ".join(c.key for c in ME.chapters()) + ")")
    if not level or not isinstance(level, str):
        raise ContentError(f"scenery {defn.id}: needs the 'level' it edits")
    edits = {k: defn.fields[k] for k in ("moves", "removes", "adds") if k in defn.fields}
    if not edits:
        raise ContentError(f"scenery {defn.id}: nothing to change (moves, removes or adds)")
    try:
        ch = ME.find_chapter(chapter)
        data, _notes = SE.apply(ch, level, edits)
    except (ME.MapEditError, SE.SceneryEditError, LP.LevelPlacementError) as e:
        raise ContentError(f"scenery {mod_id}/{defn.id}: {e}") from e
    dest = out_dir / Path(*level.split("/"))
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(data)
    return [dest]
