"""Talent (in-game "Skill") value content builder — SDK entry point.

``emit()`` turns one ``[[content]] kind="talent"`` declaration into a patched
copy of a vanilla hero **entity** file, written straight into the mod's
``assets/`` tree so the applier installs it as a plain asset override (no
re-cook, no registration — the hero entity already exists in ``asset_map``).

A talent's effect magnitude is an f32 (or int32 count) inside
``EntitySettings/Heroes/Hero_<hero>/*.entity.ot.EntitySettingsResource.gen``;
the writer is the shadowed-value-aware
:func:`rsmm.engine.talent_values.set_talent_value`. A hero has many entity
files, so each ``value_patches`` label is applied to whichever of the hero's
files actually contains it (or to ``file`` if given to disambiguate).

Fields:
    ``hero`` (str, required)   hero name, e.g. ``Juliet`` (matches the
                               ``EntitySettings/Heroes/Hero_<hero>`` dir).
    ``file`` (str, optional)   substring of the entity filename to restrict to,
                               when the same label exists in several files.
    ``value_patches``          list of ``[label, old, new]`` or
                               ``[label, old, new, clear_override]`` (or dicts
                               with ``label``/``old``/``new``/``clear_override``).
                               ``clear_override`` disables a shadowed node's
                               selector binding so the inline edit applies (it
                               unbinds the selector/curve — e.g. card-count
                               scaling becomes flat).

This replaces hand-coded talent mods (the older flow shipped a manually
byte-edited entity copy). See ``docs/MOD_AUTHORING.md`` and the
``talent-value-editing`` RE note.
"""

from __future__ import annotations

import logging
from pathlib import Path

from ...engine import talent_values as TV
from ...engine.paths import DATA_DIR
from ..content import ContentDef, ContentError, SchemaNotMined
from . import _common as C

_log = logging.getLogger(__name__)

#: Where vanilla hero entity files live in-repo (one subdir per hero).
_HEROES_DIR = DATA_DIR / "uncooked" / "EntitySettings" / "Heroes"
_GEN_GLOB = "*.entity.ot.EntitySettingsResource.gen"
#: Decoded asset-path prefix (forward-slash) the patched override is written at.
_ASSET_PREFIX = "EntitySettings/Heroes"


def _resolve_hero_dir(hero: str) -> Path | None:
    """Return the ``Hero_<hero>`` dir for a hero name, case-insensitively."""
    if not _HEROES_DIR.is_dir():
        return None
    low = hero.lower()
    for d in _HEROES_DIR.glob("Hero_*"):
        if not d.is_dir():
            continue
        stem = d.name[len("Hero_"):]
        if stem.lower() == low or d.name.lower() == low:
            return d
    return None


def _coerce_value_patches(raw) -> list[tuple[str, float, float, bool]]:
    """Normalise ``value_patches`` into ``(label, old, new, clear_override)``.

    Mirrors :func:`rsmm.sdk.kinds.items._coerce_value_patches`."""
    out: list[tuple[str, float, float, bool]] = []
    for vp in (raw or []):
        clear = False
        if isinstance(vp, dict):
            label, old, new = vp.get("label"), vp.get("old"), vp.get("new")
            clear = bool(vp.get("clear_override", vp.get("clear", False)))
        else:
            label, old, new = vp[0], vp[1], vp[2]
            clear = len(vp) > 3 and bool(vp[3])
        if not label or old is None or new is None:
            raise ContentError(
                f"value_patches entry needs label/old/new, got {vp!r}")
        out.append((str(label), float(old), float(new), clear))
    return out


def _label_in(cooked: bytes, label: str) -> bool:
    return any(tv.label == label
               for tv in TV.list_talent_values(cooked, include_spawner=True))


def _apply_patch(cooked: bytes, label: str, old: float, new: float,
                 clear: bool) -> bytes:
    """Apply one value patch, clearing a shadowing override first if asked."""
    if clear and TV.is_label_overridden(cooked, label):
        cooked = TV.clear_value_override(cooked, label)
    return TV.set_talent_value(cooked, label, new, expect=old)


def emit(mod_id: str, defn: ContentDef, out_dir: Path) -> list[Path]:
    """Materialize one talent def into the mod's ``assets/`` tree."""
    C.validate_id("talent", defn.id)
    hero = defn.fields.get("hero")
    if not hero or not isinstance(hero, str):
        raise SchemaNotMined(
            f"talent {defn.id}: needs a 'hero' name (e.g. Juliet) to locate "
            f"its entity files. See docs/MOD_AUTHORING.md.")

    hero_dir = _resolve_hero_dir(hero)
    if hero_dir is None:
        raise ContentError(
            f"talent {defn.id}: no vanilla hero dir for {hero!r} under "
            f"EntitySettings/Heroes (is data/uncooked present?)")

    file_filter = defn.fields.get("file")
    file_filter = str(file_filter).lower() if file_filter else None
    patches = _coerce_value_patches(defn.fields.get("value_patches"))
    if not patches:
        raise ContentError(f"talent {defn.id}: no value_patches given")

    # Candidate hero entity files (optionally narrowed by `file`).
    candidates = [p for p in sorted(hero_dir.glob(_GEN_GLOB))
                  if file_filter is None or file_filter in p.name.lower()]
    if not candidates:
        raise ContentError(
            f"talent {defn.id}: no entity files in {hero_dir.name}"
            + (f" matching {file_filter!r}" if file_filter else ""))

    # Group patches by the file that actually carries each label, applying them
    # to in-memory copies; only changed files are written.
    edited: dict[Path, bytes] = {}
    for label, old, new, clear in patches:
        targets = [p for p in candidates
                   if _label_in(edited.get(p) or p.read_bytes(), label)]
        if not targets:
            raise ContentError(
                f"talent {defn.id}: value label {label!r} not found in "
                f"{hero}'s entity files"
                + (f" matching {file_filter!r}" if file_filter else ""))
        for p in targets:
            cur = edited.get(p) or p.read_bytes()
            try:
                edited[p] = _apply_patch(cur, label, old, new, clear)
            except ValueError as e:
                raise ContentError(f"talent {mod_id}/{defn.id}: {e}") from e

    written: list[Path] = []
    for p, blob in edited.items():
        decoded = f"{_ASSET_PREFIX}/{hero_dir.name}/{p.name}"
        dest = out_dir / Path(*decoded.split("/"))
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(blob)
        written.append(dest)
    _log.info("talent %s/%s: patched %d hero file(s) for %s",
              mod_id, defn.id, len(written), hero)
    return written
