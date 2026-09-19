"""Boss content builder — make a boss arena fight a different boss.

A boss is an ordinary ``oCDtEnemyDefinition`` whose flag list carries
``Boss`` plus a boss-specific flag (``BossCrab``, ``Boss_Marsh_Ghoul``, ...).
Measured over the shipped corpus (2026-09-19): for the den and shrine bosses
that per-boss flag is referenced by exactly one ARENA — a den level
(``Underground_Crab_Mini_Boss_Den``, ``Ghoul_Underground_Boss_Den``,
``Underground_Wolf_Boss_Den``) or a shrine entity (``Boss_Shrine_White_Lady``)
— and the boss's ENTITY is referenced by nothing but its own definition. So
the arena selects its boss by FLAG, then spawns whatever that definition's
``entity_ref`` names. Repointing ``entity_ref`` is the whole
swap: the arena, its trigger and its flag stay exactly as shipped.

That is the same one-field edit the enemy kind's ``mode = "override"`` makes
(proven in game for camp enemies, 2026-08-28), and it goes through the same
writer: :func:`rsmm.sdk.kinds.enemies._override_one`, which also writes the
definition's resource cache as the union of its own and the donor's, so the
new boss's mesh and animations are preloaded wherever the arena loads. The
enemy override refuses bosses on purpose (a scripted placement is not a camp
roll); this kind is the place that knows which boss placements are safe.

Fields:
    ``base``     (str, required) the boss definition to rewrite — one of
                 :data:`SWAPPABLE`. Its arena keeps working as before.
    ``becomes``  (str, required) the boss definition whose ENTITY the arena
                 should spawn instead. Any shipped definition carrying the
                 ``Boss`` flag, other than ``base`` itself.

Refused as ``base``, with the reason in :data:`REFUSED`: the quest bosses
and the Jinn (something besides the definition names their entity, so a swap
would split the fight from whatever holds that reference), the three-part
witch fight (three definitions, one encounter), and every definition without
the ``Boss`` flag (the final bosses, which their own levels place by entity).

The swap is global and install-time: every run, every peer that installs the
mod, the arena fights ``becomes``. Rated ``experimental`` until a swapped
arena has been fought in game.
"""

from __future__ import annotations

from pathlib import Path

from ...engine import enemy_pools as EP
from ..content import ContentDef, ContentError, SchemaNotMined
from . import _common as C
from .enemies import _override_one

#: Boss definitions whose arena selects them by flag and nothing else — the
#: ones a swap cannot desynchronise from a script. See the module docstring
#: for the corpus measurement; `tests/test_boss_kind.py` re-asserts it.
SWAPPABLE: dict[str, str] = {
    "Boss_Crab": "Storm Island crab den (Underground_Crab_Mini_Boss_Den)",
    "Boss_Marsh_Ghoul": "Dark Hills ghoul den (Ghoul_Underground_Boss_Den)",
    "Boss_Wolf": "wolf den (Underground_Wolf_Boss_Den)",
    "Boss_White_Lady": "Dark Hills White Lady shrine (Boss_Shrine_White_Lady)",
}

_WITCH = "one third of the three-part witch fight (Crone/Stake/Young share a shrine)"

#: Boss definitions a swap would break, and why.
REFUSED: dict[str, str] = {
    "Boss_Jinn": "Jinns_Model names the boss entity directly, so the shrine flag is not "
                 "the only thing that reaches it",
    "Boss_Dullahan_Arthur": "a quest boss: its quest manager references the entity directly",
    "Boss_Roc_Bird": "a quest boss: its quest manager and attacks reference the entity directly",
    "Boss_Witch_Crone": _WITCH,
    "Boss_Witch_Stake": _WITCH,
    "Boss_Witch_Young": _WITCH,
}

_FIELDS = ("base", "becomes")


def _boss_defs() -> dict[str, str]:
    """``boss definition id -> entity ref`` for every shipped def flagged ``Boss``."""
    from ...engine import cooked
    from ...engine.cooked_schemas import definitions as _defs

    spec = _defs._SPECS["oCDtEnemyDefinition"]
    out: dict[str, str] = {}
    for eid, row in EP.enemy_index().items():
        raw = EP.corpus_read(EP.cooked_rel_for(eid))
        if raw is None:
            continue
        try:
            body = spec.decode_body(cooked.parse(raw).sections[-1].payload)
        except (ValueError, IndexError, KeyError):
            continue
        if "Boss" in (body.get("flags") or []):
            out[eid] = row["entity"]
    return out


def emit(mod_id: str, defn: ContentDef, out_dir: Path) -> list[Path]:
    """Rewrite one boss definition so its arena spawns another boss."""
    C.validate_id("boss", defn.id)
    unknown = sorted(set(defn.fields) - set(_FIELDS) - {"name"})
    if unknown:
        raise ContentError(
            f"boss {defn.id}: unknown field(s) {', '.join(unknown)}; accepted: "
            f"{', '.join(_FIELDS)}. (The old phases/music_cue/intro/reward fields "
            f"were never written to the game and have been removed.)"
        )
    base = defn.fields.get("base")
    becomes = defn.fields.get("becomes")
    for key, val in (("base", base), ("becomes", becomes)):
        if not val or not isinstance(val, str):
            raise ContentError(
                f"boss {defn.id}: needs '{key}' — a boss definition id, e.g. "
                f'base = "Boss_Marsh_Ghoul", becomes = "Boss_Crab".'
            )
    if base in REFUSED:
        raise ContentError(f"boss {defn.id}: {base} cannot be swapped — {REFUSED[base]}.")
    if base not in SWAPPABLE:
        raise ContentError(
            f"boss {defn.id}: {base!r} is not a swappable boss; choose one of "
            f"{', '.join(sorted(SWAPPABLE))}."
        )
    if becomes == base:
        raise ContentError(f"boss {defn.id}: 'becomes' names the same boss as 'base'.")

    bosses = _boss_defs()
    if not bosses:
        raise SchemaNotMined(
            f"boss {defn.id}: no enemy definitions in the corpus or the game "
            f"install, so the boss roster cannot be read."
        )
    if base not in bosses:
        raise SchemaNotMined(f"boss {defn.id}: {base} is missing from this game build.")
    if becomes not in bosses:
        raise ContentError(
            f"boss {defn.id}: 'becomes' must be a boss definition; have "
            f"{', '.join(sorted(bosses))}."
        )
    return _override_one(base, bosses[becomes], None, out_dir, defn.id)
