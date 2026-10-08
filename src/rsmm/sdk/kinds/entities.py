"""Edits to ONE shipped entity file, in place — SDK entry point.

``[[content]] kind = "entity"`` applies the same graph steps a hero's abilities
use (``set``, ``link``, ``add_link``, ``remove_link``; see
``engine/ability_edit.py``) to any shipped ``.entity.ot`` -- a boss spawner, a
camp, a UI -- and writes the patched copy into the mod's ``assets/`` tree, so
the applier installs it as a plain asset override and ``rsmm restore`` puts the
original back. Part names are the ones ``rsmm entity-graph`` shows.

Fields:
    ``entity``  (str, required)  the entity's path under EntitySettings, e.g.
                                 ``Objects/Map_Boss_Spawner/Map_Boss_Spawner_Graph_Model``
                                 (``.entity.ot`` optional, ``\\`` or ``/``).
    ``steps``   (list, required) ``[[content.steps]]`` tables, applied in order.

``clone`` steps are refused: a copied part adds resources only a custom-hero
build preloads. Several blocks may edit one file; each starts from what an
earlier block of this mod already wrote.
"""

from __future__ import annotations

import logging
from pathlib import Path

from ...engine import ability_edit as AE
from ...engine import corpus
from ..content import ContentDef, ContentError
from . import _common as C

_log = logging.getLogger(__name__)

_GEN_SUFFIX = ".entity.ot.EntitySettingsResource.gen"
_ROOT = "EntitySettings"


def _rel(entity: str) -> str:
    """``Objects\\X\\Y.entity.ot`` -> ``EntitySettings/Objects/X/Y`` + gen suffix."""
    p = entity.replace("\\", "/").strip("/")
    for cut in (_GEN_SUFFIX, ".entity.ot", ".entity"):
        p = p.removesuffix(cut)
    if p.startswith(_ROOT + "/"):
        p = p[len(_ROOT) + 1:]
    return f"{_ROOT}/{p}{_GEN_SUFFIX}"


def emit(mod_id: str, defn: ContentDef, out_dir: Path) -> list[Path]:
    """Write the edited entity file into the mod's ``assets/`` tree."""
    C.validate_id("entity", defn.id)
    entity = defn.fields.get("entity")
    if not entity or not isinstance(entity, str):
        raise ContentError(f"entity {defn.id}: needs 'entity', the file's path under "
                           f"EntitySettings (e.g. Objects/Map_Boss_Spawner/Map_Boss_Spawner_Model)")
    steps = defn.fields.get("steps")
    if not isinstance(steps, list) or not steps or not all(isinstance(s, dict) for s in steps):
        raise ContentError(f"entity {defn.id}: needs 'steps', a list of [[content.steps]] tables")
    if any("clone" in s for s in steps):
        raise ContentError(f"entity {defn.id}: clone steps are not supported here; "
                           f"use set / link / add_link / remove_link")

    rel = _rel(entity)
    shipped = corpus.read(rel)
    if shipped is None:
        raise ContentError(f"entity {defn.id}: no shipped entity {entity!r} ({rel}) — "
                           f"is the game install readable?")
    stem = Path(rel).name.removesuffix(_GEN_SUFFIX)
    dest = out_dir / Path(*rel.split("/"))
    before = dest.read_bytes() if dest.is_file() else shipped
    try:
        res = AE.apply({stem: before}, steps, main=stem, seed=f"{mod_id}:{defn.id}")
    except AE.AbilityEditError as e:
        raise ContentError(f"entity {defn.id}: {e}") from e
    for w in res.warnings:
        _log.warning("entity %s: %s", defn.id, w)
    blob = res.files.get(stem, before)
    if blob == before:
        _log.info("entity %s/%s: no change to %s", mod_id, defn.id, stem)
        return []
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(blob)
    _log.info("entity %s/%s: patched %s", mod_id, defn.id, rel)
    return [dest]
