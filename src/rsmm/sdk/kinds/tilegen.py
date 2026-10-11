"""Chapter map-generation recipe content builder — SDK entry point.

``emit()`` turns one ``[[content]] kind = "tilegen"`` declaration into an edited
copy of a chapter's shipped tile-generation level, written at its own decoded
path so ``apply`` installs it as a plain in-place override: same object count,
no new resource name, nothing to register.

The edits are keyed by NAME and applied to the SHIPPED recipe every time, so a
mod carries only what it changes and survives a patch that moves bytes around.
A name the recipe no longer has fails the emit rather than landing on whatever
now sits at that index. See :mod:`rsmm.engine.map_editor` for the vocabulary;
``rsmm map-editor`` writes these declarations for you.

Fields:
    ``chapter`` (str, required)  biome key (``DarkHills``, ``Avalon``,
                                 ``Storm_Island``) or the full level name.
    ``kinds``   (table)          ``{ "<Kind>" = { count, min_distance,
                                 footprints = { "<WxH>" = bool } } }``
    ``quotas``  (table)          ``{ "<Flag>[+<Flag>]" = limit }``
    ``slots``   (table)          ``{ "<object id>" = { pos = [x, y, z],
                                 allow = { "<Kind>" = bool } } }`` — ``pos`` is
                                 checked against the recipe so an edit made
                                 against one build cannot silently move.
    ``fill``    (table)          ``{ "<WxH>" = ["<Flag>", ...] }`` — what a
                                 footprint group fills its still-empty slots
                                 with after the kinds are placed; ``[]`` = no
                                 fill. Dark Hills fills 40x40/64x64 with
                                 ``Camp``, which is where most camps come from:
                                 a kind's ``count`` only covers the placements
                                 made before this pass.
"""

from __future__ import annotations

from pathlib import Path

from ...engine import map_editor as ME
from ...engine import tilegen as TG
from ..content import ContentDef, ContentError, SchemaNotMined
from . import _common as C


def emit(mod_id: str, defn: ContentDef, out_dir: Path) -> list[Path]:
    """Materialize one tilegen def into the mod's ``assets/`` tree."""
    C.validate_id("tilegen", defn.id)
    chapter = defn.fields.get("chapter")
    if not chapter or not isinstance(chapter, str):
        raise SchemaNotMined(
            f"tilegen {defn.id}: needs a 'chapter' (one of "
            + ", ".join(c.key for c in ME.chapters()) + ")")
    edits = {k: defn.fields[k] for k in ("kinds", "quotas", "slots", "fill")
             if k in defn.fields}
    if not edits:
        raise ContentError(f"tilegen {defn.id}: no kinds, quotas, slots or fill to change")
    try:
        ch = ME.find_chapter(chapter)
        level, changes = ME.build_level(ch, edits)
    except (ME.MapEditError, TG.TileGenError) as e:
        raise ContentError(f"tilegen {mod_id}/{defn.id}: {e}") from e
    if not changes:
        raise ContentError(
            f"tilegen {defn.id}: every edit already matches the shipped recipe")
    dest = out_dir / Path(*ch.decoded.split("/"))
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(level)
    return [dest]
