"""Hero content builder: clone a shipped hero into a new roster entry.

How the roster works (static RE, 2026-09-24):

* The hero-select screen (``oCDtEntityCpntPlayBookPageUiController``, vftable
  ``0x140f35820``) fills its hero vector at ``controller+0x210`` through
  ``FUN_140209b00``: clear it, then copy **every registered instance** of the
  hero-definition class out of the definition registry (``Registry_EnumInstances``
  with the class key at ``0x141475f50``). No filter, no sort, no count: a
  hero's index is its position in that list.
* Unlike enemies, a herodef is NOT loaded by the boot directory scan: a clone
  registered in ``UsedRscList.ot`` alone never loaded (12 defs live, measured
  in game 2026-09-24). Heroes load through the LiveOps versiondef's hero
  vector, so ``apply`` appends each new herodef there
  (``apply_mods._patch_versiondef_heroes``), the same way new magic items join
  the versiondef's MO vector.

So a new hero is a new ``.herodef`` file, its resource cache and one
versiondef entry: no library singleton to find, no roster table to patch. A herodef never
names itself (its strings are memoir text keys, codex art, entity refs), so a
byte copy under a new file name is a distinct definition, the same identity
rule as an enemy or map clone.

PROVEN IN GAME 2026-09-24: a Piper clone appeared as a 13th hero, was picked,
and a run started as it with no crash; the save the game wrote checks out. A
clone takes the next index, which no save has unlocked, so it may need
``R.hero.unlock_progression()`` (the ``unlock-heroes`` mod) to be selectable.

Fields:
    ``base``  (str, required)  a shipped hero to clone, e.g. ``Piper``. Paid
                               DLC heroes are refused: a clone would hand out
                               a hero the player has not bought.

The clone is its base in every respect (model, abilities, name, portrait);
changing those is the next layer, not this one.
"""

from __future__ import annotations

from pathlib import Path
from typing import Final

from ...engine import enemy_pools as EP
from ...engine import rsc_cache as RC
from ..content import ContentDef, ContentError, SchemaNotMined
from . import _common as C

_HEROES_DIR = "Definitions/Heroes"
_GEN_SUFFIX = ".herodef.ot.DtHeroDefinition.gen"
_HERO_CLASS = "oCDtHeroDefinition"

#: Paid DLC heroes. Never a clone base: cloning one would unlock it for
#: players who have not bought it.
DLC_HEROES: Final[frozenset[str]] = frozenset({"Carmilla", "Merlin"})


def _rel(hero: str) -> str:
    return f"{_HEROES_DIR}/{hero}{_GEN_SUFFIX}"


def _self_line(hero: str) -> str:
    return f"Definitions|Heroes\\{hero}.herodef.ot|{_HERO_CLASS}"


def shipped_heroes() -> list[str]:
    """Hero ids the game ships, from the corpus (mirror or install)."""
    return sorted(r.rsplit("/", 1)[-1][: -len(_GEN_SUFFIX)]
                  for r in EP.corpus_rels(prefix=_HEROES_DIR, suffix=_GEN_SUFFIX))


def emit(mod_id: str, defn: ContentDef, out_dir: Path) -> list[Path]:
    """Write ``<id>.herodef`` (a copy of the base) and its resource cache."""
    C.validate_id("hero", defn.id)
    unknown = sorted(set(defn.fields) - {"base"})
    if unknown:
        raise ContentError(
            f"hero {defn.id}: unsupported field(s) {unknown}. A hero clone is its "
            f"base for now: renaming and new abilities are not built yet.")
    base = defn.fields.get("base")
    if not isinstance(base, str) or not base:
        raise ContentError(f"hero {defn.id}: needs a 'base' (a shipped hero, e.g. Piper)")
    if base in DLC_HEROES:
        raise ContentError(
            f"hero {defn.id}: {base} is a paid DLC hero and cannot be cloned — the "
            f"clone would give it to players who have not bought it.")
    shipped = shipped_heroes()
    if defn.id in shipped:
        raise ContentError(f"hero {defn.id}: the id collides with a shipped hero")

    raw = EP.corpus_read(_rel(base))
    cache = EP.corpus_read(RC.cache_path_for(_rel(base)))
    if raw is None or cache is None:
        if shipped and base not in shipped:
            raise ContentError(
                f"hero {defn.id}: no shipped hero {base!r}; have {', '.join(shipped)}")
        raise SchemaNotMined(
            f"hero {defn.id}: {base}'s herodef or resource cache is not in the "
            f"corpus or the game install")

    dest = out_dir / Path(*_rel(defn.id).split("/"))
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(raw)

    # 12 of 12 shipped herodefs carry a cache listing their own def line; a new
    # name has none unless it is written (the enemy/tile lesson).
    lines = set(RC.parse(cache)) - {_self_line(base)}
    lines.add(_self_line(defn.id))
    cache_dest = out_dir / Path(*RC.cache_path_for(_rel(defn.id)).split("/"))
    cache_dest.write_bytes(RC.render(sorted(lines)))
    return [dest, cache_dest]
