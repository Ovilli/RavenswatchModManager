#!/usr/bin/env python3
"""
Deactivation hook for SeedRunsChapter3.

When the mod ran it set the in-memory GameOptions "Forced seed" value and
the "Dev" flag (via R.options; the engine only honours a forced seed while
Dev is true). The game then persisted those values to
<game>/_Save/GameSettings.ini under `[Debug]`. The mod itself only runs
while enabled, so it has no way to unpin them when the user disables it —
the ini lines outlive the mod.

This hook fires from `./rsmm apply` whenever SeedRunsChapter3 flips
enabled -> disabled in any manifest scan. It strips the `Forced seed=`
and `Dev=` lines from `[Debug]` so the next launch starts with the game's
default seed source (and retail behaviour) again.

Env contract (set by rsmm.cli.apply_mods._run_deactivation_hooks):

    RSMM_GAME_DIR  — Ravenswatch install directory
    RSMM_MOD_DIR   — this mod's root (mods/SeedRunsChapter3/)

Idempotent: missing line / missing file / missing section -> no-op.
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

SEED_KEY_RE = re.compile(r"^\s*(Forced\s+seed|Dev)\s*=", re.IGNORECASE)


def main() -> int:
    game = os.environ.get("RSMM_GAME_DIR")
    if not game:
        print("RSMM_GAME_DIR not set; refusing to guess", file=sys.stderr)
        return 1
    ini = Path(game) / "_Save" / "GameSettings.ini"
    if not ini.is_file():
        print(f"no GameSettings.ini at {ini} — nothing to clear")
        return 0

    text = ini.read_text(encoding="utf-8", errors="replace")
    out_lines: list[str] = []
    removed = 0
    for line in text.splitlines(keepends=True):
        if SEED_KEY_RE.match(line):
            removed += 1
            continue
        out_lines.append(line)

    if removed == 0:
        print("no `Forced seed=` / `Dev=` line present; ini already clean")
        return 0

    ini.write_text("".join(out_lines), encoding="utf-8")
    print(f"cleared {removed} `Forced seed=` / `Dev=` line(s) from {ini}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
