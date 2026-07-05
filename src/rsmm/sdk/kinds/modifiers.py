"""Custom **game modifier** ("negative mode") content builder — SDK entry point.

Game modifiers are the toggleable run mutators on the New Game Plus / challenge
screen (*No boss timer*, *No minimap*, *More experience*, *Day only*, ...).
``emit()`` clones a vanilla ``.gamemodifierdef.ot`` under a new id, optionally
relabels its display text and repoints it at a different existing behaviour, and
writes the cooked record into the mod's ``assets/`` tree. ``apply_mods.py``
registers the new stem in ``UsedRscList`` so the engine loads it additively —
the same path proven for custom items / enemies.

Confidence: ``guess``. The def cooks and loads, but a NET-NEW modifier *appearing
in the selection UI* is unproven — the challenge-UI slot count looks data-driven
and may be pre-sized to the vanilla set (see docs/_re/kinds/game-modifiers.md,
"#16 cap"). Ghidra 2026-07-05: the challenge UI rows are SPAWNED, not fixed
entities — ``Dt Challenge Ui Controller`` registers ``m_oGameModifierUiSpawner``
(property id 0x1871e0aa) plus ``m_bDisplayEmptySlots`` (0x1871e0ab), so the cap
question reduces to what feeds the spawner (challengedef modifier list vs
library) — still unresolved. A modifier's EFFECT is hardcoded C++ keyed by an entity-value id, so a
clone reuses an existing effect; brand-new behaviour is layered in Lua via
``R.modifier`` gating.

Fields:
    ``base`` (str, required)      vanilla modifier id to clone (its filename
                                  stem, e.g. ``NoMinimap`` / ``MoreExperience``).
    ``name`` (str, optional)      display title (relabels ``GameModifier_<id>_Title``).
    ``description`` (str, optional) display description (``_Desc``).
    ``effect`` (str, optional)    reuse another modifier's behaviour by name
                                  (e.g. ``"Game Difficulty"``); see ``EFFECT_KEYS``.

See ``docs/_re/kinds/game-modifiers.md``.
"""

from __future__ import annotations

import logging
from pathlib import Path

from ...engine import game_modifier_cook as GMC
from ...engine import text_patches as TP
from ...engine.paths import DATA_DIR
from ..content import ContentDef, ContentError, SchemaNotMined
from . import _common as C

_log = logging.getLogger(__name__)

_MODIFIER_DIR = DATA_DIR / "uncooked" / "Definitions" / "GameModifiers"
_ASSET_SUBDIR = "Definitions/GameModifiers"
_TEXT_BANK_GEN = DATA_DIR / "uncooked" / "Text" / "ChallengesAndGameModifiers~GAM.xls.LocalText.gen"
_TEXT_BANK_DECODED = "Text/ChallengesAndGameModifiers~GAM.xls.LocalText.gen"

#: Modifier / difficulty behaviours selectable via ``effect``. The keys are the
#: literal entity-value ids the engine registers them under (Ghidra:
#: EntityValueRegistry_RegisterAll, FUN_1401d9b70) — the same map the loader's
#: ``R.modifier`` reads. See docs/_re/kinds/game-modifiers.md.
EFFECT_KEYS: dict[str, int] = {
    "No boss timer": 0x1A7945FC,
    "Less day/night half cycle": 0x1A77D42D,
    "More experience": 0x1A77E2E4,
    "No revive token": 0x1A793D1A,
    "No minimap": 0x99F27EAC,
    "One chapter": 0x1A8A3688,
    "Day only": 0x1A8B53B4,
    "Night only": 0x1A8B53BC,
    "Random hero at map start": 0x1AB183AB,
    "All same heroes": 0x1AB58780,
    "Game Difficulty": 0x18700873,
    "Difficulty Xp Modifier": 0x19BDDB2E,
    "Global Xp Modifier": 0x187AFD1D,
    "Rare Skill Chance Modifier": 0x1871C2FA,
    "Dream Shard Costs Modifier": 0x187310EC,
    "Half Cycle Count Before Boss Awakens": 0x187443DE,
    "Camp Difficulty Modifier": 0x187AAECF,
    "Camp Difficulty Modifier Chance To Apply": 0x187AB36E,
}


def _write_bank_files(files: dict[str, bytes], out_dir: Path) -> list[Path]:
    """Write a bank-patch result ({token -> bytes}) into the mod assets. ``token``
    is ``.Lang<XX>`` for a language sibling, or ``__base__`` for the keys file."""
    written: list[Path] = []
    for token, blob in files.items():
        decoded = _TEXT_BANK_DECODED if token == "__base__" else f"{_TEXT_BANK_DECODED}{token}"
        dest = out_dir / Path(*decoded.split("/"))
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(blob)
        written.append(dest)
    return written


def emit(mod_id: str, defn: ContentDef, out_dir: Path) -> list[Path]:
    """Materialize a single custom game modifier as a cooked def (+ optional text)."""
    C.validate_id("modifier", defn.id)

    base = defn.fields.get("base")
    if not base or not isinstance(base, str):
        raise ContentError(
            f"modifier {defn.id}: needs a 'base' (vanilla modifier id) to clone, "
            f'e.g. base="NoMinimap". See docs/_re/kinds/game-modifiers.md.'
        )

    base_gen = _MODIFIER_DIR / f"{base}{GMC.GEN_SUFFIX}"
    if not base_gen.is_file():
        raise SchemaNotMined(
            f"modifier {defn.id}: base {base!r} not found under {_MODIFIER_DIR} — "
            f"pass a vanilla modifier id whose cooked def is present."
        )

    effect = defn.fields.get("effect")
    effect_key: int | None = None
    if effect is not None:
        if effect not in EFFECT_KEYS:
            raise ContentError(
                f"modifier {defn.id}: unknown effect {effect!r}. Known effects: "
                f"{', '.join(sorted(EFFECT_KEYS))}."
            )
        effect_key = EFFECT_KEYS[effect]

    name = defn.fields.get("name")
    description = defn.fields.get("description")
    relabel = name is not None or description is not None

    try:
        new_cooked, base_key = GMC.clone(
            base_gen.read_bytes(), base, defn.id,
            effect_key=effect_key, relabel_text=relabel,
        )
    except GMC.GameModifierCookError as e:
        raise ContentError(f"modifier {defn.id}: {e}") from e

    decoded_rel = f"{_ASSET_SUBDIR}/{defn.id}{GMC.GEN_SUFFIX}"
    dest = out_dir / Path(*decoded_rel.split("/"))
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(new_cooked)
    written = [dest]

    if relabel:
        if not _TEXT_BANK_GEN.is_file():
            raise SchemaNotMined(
                f"modifier {defn.id}: text bank {_TEXT_BANK_GEN.name} not present, "
                f"so the display name/description can't be set — drop 'name'/"
                f"'description' to emit the def alone, or supply the corpus."
            )
        pairs: dict[str, str] = {}
        if name is not None:
            pairs[f"GameModifier_{defn.id}_Title"] = str(name)
        if description is not None:
            pairs[f"GameModifier_{defn.id}_Desc"] = str(description)
        files = TP.append_bank_keys(_TEXT_BANK_GEN, pairs)
        written += _write_bank_files(files, out_dir)

    _log.info(
        "modifier %s/%s: emitted cooked def (base=%s, effect=%s, base_key=%s, relabel=%s)",
        mod_id, defn.id, base, effect,
        f"0x{base_key:x}" if base_key is not None else None, relabel,
    )
    return written
