"""What Steam says about the Ravenswatch install: build id and install state.

Read from ``steamapps/appmanifest_*.acf`` beside the install (the one whose
``installdir`` is Ravenswatch). Stdlib only, never raises: a non-Steam install,
an unreadable manifest or an odd layout all read as "unknown" (None fields).

Why it matters: rsmm detects a game update from a fingerprint of the binaries
and ``UsedRscList.ot``. A Steam patch that changes only cooked data files leaves
that fingerprint alone, so the backups taken before it still look current — and
restoring them would put old-version files over the patched ones. The build id
changes with every Steam update, data-only or not.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

#: StateFlags bit 4 = fully installed; anything else (updating, validating,
#: downloading, update queued) means Steam is or may be writing game files.
FULLY_INSTALLED = 4


@dataclass(frozen=True)
class AppState:
    buildid: str | None
    state_flags: int | None

    @property
    def steam_busy(self) -> bool:
        """Steam is (or may be) writing the game's files right now."""
        return self.state_flags is not None and self.state_flags != FULLY_INSTALLED


def app_state(game_dir: Path) -> AppState | None:
    """The install's Steam manifest fields, or None when there is no manifest."""
    steamapps = Path(game_dir).parent.parent
    try:
        manifests = sorted(steamapps.glob("appmanifest_*.acf"))
    except OSError:
        return None
    for acf in manifests:
        try:
            text = acf.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if not re.search(r'"installdir"\s*"Ravenswatch"', text, re.IGNORECASE):
            continue
        build = re.search(r'"buildid"\s*"(\d+)"', text)
        flags = re.search(r'"StateFlags"\s*"(\d+)"', text)
        return AppState(build.group(1) if build else None,
                        int(flags.group(1)) if flags else None)
    return None
