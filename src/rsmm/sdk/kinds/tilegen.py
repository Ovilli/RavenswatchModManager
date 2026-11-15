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
    ``add_quotas`` (table)       same shape, for a flag the recipe does not cap
                                 yet (e.g. an entrance that must appear at most
                                 once because each copy needs an off-map room).
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
    ``slots.<id>.move`` ([x, y, z])  move a slot; ``pos`` still anchors it.
    ``remove_slots`` (table)     ``{ "<object id>" = [x, y, z] }`` — the
                                 position anchors the removal like ``pos``.
    ``add_kinds`` (table)        ``{ "<Flag>" = { count, min_distance,
                                 footprints = { "<WxH>" = true } } }`` — a NEW
                                 kind placing ``count`` tiles carrying the
                                 flag. It starts off on every shipped slot, so
                                 pair it with ``add_slots`` allowing it: its
                                 tiles then fill new places of their own and
                                 replace nothing.
    ``add_slots`` (array)        ``[{ group = "<WxH>", pos = [x, y, z],
                                 allow = { "<Kind>" = true } }]``. Removing or
                                 adding slots changes the recipe's object
                                 count; the writer renumbers the graph.
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
    # Named here, not via ME.EDIT_SECTIONS, so the manifest-spec check sees each field read.
    edits = {k: defn.fields[k] for k in ("kinds", "quotas", "add_quotas", "slots", "fill",
                                         "remove_slots", "add_kinds", "add_slots")
             if k in defn.fields}
    if not edits:
        raise ContentError(f"tilegen {defn.id}: nothing to change (one of "
                           f"{', '.join(ME.EDIT_SECTIONS)})")
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
