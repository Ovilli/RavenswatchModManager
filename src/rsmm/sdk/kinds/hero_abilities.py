"""Ability edits to a SHIPPED hero, in place — SDK entry point.

``emit()`` turns one ``[[content]] kind="ability"`` block into patched copies of
the hero's own entity files, written straight into the mod's ``assets/`` tree so
the applier installs them as plain asset overrides, as the ``talent`` kind does.
No second hero is made: the shipped hero itself changes, for everyone who runs
with the mod, and ``rsmm restore`` puts the originals back. To change a hero
without touching the original, build a custom hero (``kind = "hero"`` with
``[[content.abilities]]``) instead.

Fields:
    ``hero``       (str, required)  a shipped hero: ``Beowulf``, ``SunWukong``.
                                    A paid hero (Merlin) is edited, not cloned,
                                    so nothing needs declaring.
    ``abilities``  (list, required) the same ``[[content.abilities]]`` steps a
                                    custom hero takes (``set``, ``link``,
                                    ``add_link``, ``remove_link``; see
                                    ``engine/ability_edit.py``), each naming
                                    its entity file with ``entity = "..."``.

``clone`` steps are refused: a copied ability adds parts and resources that only
the custom-hero build preloads, so it needs a custom hero.

Several blocks may edit one hero (even one file); each starts from what an
earlier block of this mod already wrote.
"""

from __future__ import annotations

import logging
from pathlib import Path

from ...engine import ability_edit as AE
from ..content import ContentDef, ContentError
from . import _common as C
from .talents import _ASSET_PREFIX, _GEN_SUFFIX, _resolve_hero_dir

_log = logging.getLogger(__name__)


def emit(mod_id: str, defn: ContentDef, out_dir: Path) -> list[Path]:
    """Write the hero's edited entity files into the mod's ``assets/`` tree."""
    C.validate_id("ability", defn.id)
    hero = defn.fields.get("hero")
    if not hero or not isinstance(hero, str):
        raise ContentError(f"ability {defn.id}: needs a 'hero' (a shipped hero, e.g. Beowulf)")
    steps = defn.fields.get("abilities")
    if not isinstance(steps, list) or not steps or not all(isinstance(s, dict) for s in steps):
        raise ContentError(
            f"ability {defn.id}: needs 'abilities', a list of [[content.abilities]] steps")
    if any("clone" in s for s in steps):
        raise ContentError(
            f"ability {defn.id}: a clone step adds new parts, which only a custom hero "
            f"(kind = \"hero\" with abilities) builds; edit numbers and links here")
    hero_dir = _resolve_hero_dir(hero)
    if hero_dir is None:
        raise ContentError(
            f"ability {defn.id}: no shipped hero {hero!r} under EntitySettings/Heroes — "
            f"is the game install readable?")

    # The hero's family, starting from a copy an earlier block of this mod wrote.
    files: dict[str, bytes] = {}
    paths: dict[str, Path] = {}
    for p in hero_dir.entity_files():
        stem = p.name.removesuffix(_GEN_SUFFIX)
        dest = out_dir / Path(*f"{_ASSET_PREFIX}/{hero_dir.name}/{p.name}".split("/"))
        files[stem] = dest.read_bytes() if dest.is_file() else p.read_bytes()
        paths[stem] = dest
    try:
        res = AE.apply(files, steps, main=hero_dir.name, seed=f"{mod_id}:{defn.id}")
    except AE.AbilityEditError as e:
        raise ContentError(f"ability {defn.id}: {e}") from e
    for w in res.warnings:
        _log.warning("ability %s: %s", defn.id, w)

    written: list[Path] = []
    for stem, blob in res.files.items():
        if blob == files[stem]:
            continue                    # only the files a step changed
        dest = paths[stem]
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(blob)
        written.append(dest)
    _log.info("ability %s/%s: patched %d file(s) of %s", mod_id, defn.id, len(written), hero)
    return written
