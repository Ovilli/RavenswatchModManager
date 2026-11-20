"""The game's persisted options (``<game>/_Save/GameSettings.ini``) a mod can
leave behind.

``R.options.set`` writes the engine's in-memory options registry, and the game
saves those values to ``GameSettings.ini``. The mod only runs while it is
enabled, so a value it pinned (a forced seed, the ``Dev`` flag the seed needs)
outlives the mod. A mod lists those options in ``[mod] restore_options`` and
``rsmm`` clears their lines when the mod is disabled or uninstalled, so the next
launch reads the game's own default again. That replaces each mod shipping its
own ``on_disable.py`` that did the same strip (#202 C3).
"""

from __future__ import annotations

import re
from pathlib import Path

#: Every option ``R.options`` knows (``_OPT`` in src/loader/lib/rsmm.lua; a test
#: keeps the two equal). The ini key is the option's name.
OPTION_NAMES: frozenset[str] = frozenset({
    "Forced seed", "Dev", "Test", "Dash at cursor", "Screen shake",
    "Pause during choices", "Show damage and healing numbers",
    "Select random skin when using random heroes", "Show enemy debug info",
    "Sectorize enemy camps", "Display fake unlock in recap", "Show social options debug",
    "Show hourglass debug info", "Force epilogue", "Force end credits",
})


def settings_ini(game_dir: Path) -> Path:
    return Path(game_dir) / "_Save" / "GameSettings.ini"


def unknown_options(names) -> list[str]:
    """The entries of ``names`` that are not option names (lint's check)."""
    return sorted(str(n) for n in names if n not in OPTION_NAMES)


def clear_options(game_dir: Path, names) -> int:
    """Remove the ``<name>=`` lines of ``names`` from GameSettings.ini, in any
    section; return how many went. A missing file, or no such line, is 0."""
    names = [n for n in names if n in OPTION_NAMES]
    ini = settings_ini(game_dir)
    if not names or not ini.is_file():
        return 0
    key = re.compile(r"^\s*(?:" + "|".join(re.escape(n).replace(r"\ ", r"\s+") for n in names)
                     + r")\s*=", re.IGNORECASE)
    text = ini.read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines(keepends=True)
    kept = [ln for ln in lines if not key.match(ln)]
    if len(kept) == len(lines):
        return 0
    from .safeio import atomic_write_text
    atomic_write_text(ini, "".join(kept))
    return len(lines) - len(kept)
