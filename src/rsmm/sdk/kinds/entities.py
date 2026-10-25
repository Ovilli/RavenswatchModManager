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

A ``set`` step may read its value from the mod's config instead of ``value``:
``config = "<field>"``, plus ``times = <n>`` to multiply a number field by
``n`` (the shipped value, so a 1.0 multiplier leaves the game as it was).
Any step may carry ``when = "<bool field>"``: it applies only while that
switch is on (e.g. a ``link`` that forces a branch).

``clone`` steps are refused: a copied part adds resources only a custom-hero
build preloads. Several blocks may edit one file; each starts from what an
earlier block of this mod already wrote.
"""

from __future__ import annotations

import logging
from pathlib import Path

from ...engine import ability_edit as AE
from ...engine import corpus
from ..content import ContentDef, ContentError, written_this_run
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


def _resolve_config(defn: ContentDef, steps: list[dict], mod_root: Path) -> list[dict]:
    """A ``set`` step may take its value from the mod's config instead of a
    literal: ``config = "<field>"`` reads the player's value (or the schema
    default), and ``times = <n>`` multiplies a number by it — so one
    "health multiplier" field can scale every shipped value it names."""
    if not any("config" in s or "when" in s for s in steps):
        return steps
    from rsmm.sdk.config import ConfigError, ConfigStore, config_value
    try:
        store = ConfigStore(mod_root)
    except (OSError, ConfigError, ValueError) as e:
        raise ContentError(f"entity {defn.id}: config unreadable: {e}") from e
    out = []
    for s in steps:
        if "when" in s:
            try:
                on = config_value(store, s["when"])
            except ConfigError as e:
                raise ContentError(f"entity {defn.id}: when: {e}") from e
            if not isinstance(on, bool):
                raise ContentError(f"entity {defn.id}: when = {s['when']!r} must name an "
                                   f"on/off (bool) field")
            if not on:
                continue
            s = {k: v for k, v in s.items() if k != "when"}
        if "config" not in s:
            out.append(s)
            continue
        if "set" not in s or "value" in s:
            raise ContentError(f"entity {defn.id}: 'config' goes on a set step, "
                               f"in place of 'value'")
        try:
            value = config_value(store, s["config"], s.get("times"))
        except ConfigError as e:
            raise ContentError(f"entity {defn.id}: {e}") from e
        out.append({k: v for k, v in s.items() if k not in ("config", "times")}
                   | {"value": value})
    return out


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
                           f"use set / link / add_link / remove_link / percent")

    steps = _resolve_config(defn, steps, out_dir.parent)

    rel = _rel(entity)
    shipped = corpus.read(rel)
    if shipped is None:
        raise ContentError(f"entity {defn.id}: no shipped entity {entity!r} ({rel}) — "
                           f"is the game install readable?")
    stem = Path(rel).name.removesuffix(_GEN_SUFFIX)
    dest = out_dir / Path(*rel.split("/"))
    before = dest.read_bytes() if written_this_run(dest) else shipped
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
