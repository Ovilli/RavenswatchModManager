"""Custom **game mode** (run chapter sequence) builder — SDK entry point.

Re-orders the chapters a run plays by rewriting the ``GameModeDefaultDefinition``
chapter list (Heredos #10 — sequential / custom map order). ``emit()`` clones the
shipped ``All_Chapters`` def and replaces its sequence, then writes the cooked
record; ``apply_mods`` registers it via ``UsedRscList``.

Confidence: ``guess``. The def cooks/loads, but the engine honouring a rewritten
sequence in-game is unproven, and some orders may be fragile (chapter 0 may be
coupled to first-run/tutorial setup). A FIXED order is data-safe; true per-run
randomization is out of scope (needs engine RNG + multiplayer determinism).

Fields:
    ``base`` (str, optional)        gamemode def id to clone (default ``All_Chapters``).
    ``chapters`` (list[int], req.)  the new chapter-index order, e.g. ``[2, 0, 1, 3]``
                                    (reorder), ``[0, 0, 0]`` (repeat), ``[3]`` (one chapter).

See ``docs/_re/kinds/maps-chapters.md``.
"""

from __future__ import annotations

import logging
from pathlib import Path

from ...engine import game_mode_cook as GMC
from ...engine.paths import DATA_DIR
from ..content import ContentDef, ContentError, SchemaNotMined
from . import _common as C

_log = logging.getLogger(__name__)

_GAMEMODE_DIR = DATA_DIR / "uncooked" / "Definitions" / "GameModes"
_ASSET_SUBDIR = "Definitions/GameModes"
_DEFAULT_BASE = "All_Chapters"


def emit(mod_id: str, defn: ContentDef, out_dir: Path) -> list[Path]:
    """Materialize a re-sequenced game-mode def."""
    C.validate_id("game_mode", defn.id)

    base = defn.fields.get("base", _DEFAULT_BASE)
    if not isinstance(base, str):
        raise ContentError(f"game_mode {defn.id}: 'base' must be a string id.")

    chapters = defn.fields.get("chapters")
    if not isinstance(chapters, (list, tuple)) or not chapters:
        raise ContentError(
            f"game_mode {defn.id}: needs a non-empty 'chapters' list of chapter "
            f"indices, e.g. chapters=[2, 0, 1, 3]. See docs/_re/kinds/maps-chapters.md."
        )

    base_gen = _GAMEMODE_DIR / f"{base}{GMC.GEN_SUFFIX}"
    if not base_gen.is_file():
        raise SchemaNotMined(
            f"game_mode {defn.id}: base {base!r} not found under {_GAMEMODE_DIR}."
        )

    try:
        new_cooked = GMC.set_chapter_sequence(base_gen.read_bytes(), list(chapters))
    except GMC.GameModeCookError as e:
        raise ContentError(f"game_mode {defn.id}: {e}") from e

    decoded_rel = f"{_ASSET_SUBDIR}/{defn.id}{GMC.GEN_SUFFIX}"
    dest = out_dir / Path(*decoded_rel.split("/"))
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(new_cooked)
    _log.info("game_mode %s/%s: re-sequenced chapters %s (base=%s)",
              mod_id, defn.id, list(chapters), base)
    return [dest]
