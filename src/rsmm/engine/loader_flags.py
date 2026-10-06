"""The script loader's feature flags: what the desktop "Loader features" panel
lists, what a mod may ask for (`[mod] loader_flags`), and the flags file.

The loader reads `<game>/rsmm_loader_flags.json` (a JSON array of flag names)
or the matching environment variable, once at start. Only flags marked
``safe`` may be switched on from the app or by a mod.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

# Loader feature flags surfaced in the desktop "Loader features" panel.
# The loader reads these from <game_dir>/rsmm_loader_flags.json (a JSON array
# of enabled flag names) OR from a matching environment variable. Only flags
# marked safe=True are user-togglable; the rest are documented but locked so
# the UI can explain why (e.g. RSMM_ENABLE_ITEM_INJECT crashes the game).
LOADER_FLAGS: list[dict[str, Any]] = [
    # Both event buses are ON by default (the loader skips publishing entirely
    # when no mod has subscribed, so an asset-only install pays nothing). These
    # entries are the opt-OUT switches, for isolating a suspected event-bus
    # problem without uninstalling the loader.
    {
        "name": "RSMM_DISABLE_GAMEPLAY_EVENTS",
        "label": "Disable gameplay event bus",
        "description": "Stop bridging the in-game oCGameNamedEvent bus to Lua "
                       "(R.on(\"gameplay:<NAME>\")). Event-driven mods break "
                       "while this is on — troubleshooting only.",
        "safe": True,
    },
    {
        "name": "RSMM_DISABLE_GAME_EVENTS",
        "label": "Disable analytics event bridge",
        "description": "Stop bridging the analytics firehose (run_start, "
                       "enemy_killed, ...) to R.on. Troubleshooting only.",
        "safe": True,
    },
    {
        "name": "RSMM_EVENT_PROBE",
        "label": "Event payload probe",
        "description": "Attach a raw field window (ev.w38..ev.w70) to every "
                       "gameplay event, for reverse-engineering an undecoded "
                       "payload. Verbose; developers only.",
        "safe": True,
    },
    {
        "name": "RSMM_ENABLE_SKILL_HOOK",
        "label": "Skill hook (read-only)",
        "description": "Log the herodef skill vector at load. Experimental; "
                       "may fail to resolve under Proton on some builds.",
        "safe": True,
    },
    {
        "name": "RSMM_ENABLE_UI_HOOK",
        "label": "UI button events",
        "description": "Emit R.on(\"ui:press\") when a native UI button is "
                       "clicked. Needed by mods that add in-game menu actions.",
        "safe": True,
    },
    {
        "name": "RSMM_ENABLE_HERO_CAPTURE",
        "label": "Hero capture",
        "description": "Find your hero in memory so mods can read and change "
                       "it: R.entity, R.stat, R.combat, R.xp, R.camera and the "
                       "talent grants. Needed by the camera and stat mods; a mod "
                       "that needs it switches it on while it is enabled "
                       "(`loader_flags` in its manifest). Off by default: these "
                       "are the newest engine hooks.",
        "safe": True,
    },
    {
        "name": "RSMM_ENABLE_ITEM_INJECT",
        "label": "Item pool injection",
        "description": "Disabled: crashes the game. Custom items already load "
                       "via UsedRscList — no injection needed.",
        "safe": False,
    },
    {
        "name": "RSMM_ENABLE_SKILL_INJECT",
        "label": "Skill injection (proof-of-path)",
        "description": "Disabled: experimental loader path that duplicates a "
                       "skill slot. For development only.",
        "safe": False,
    },
    {
        "name": "RSMM_DUMP_SYMBOLS",
        "label": "Dump resolved symbols (RE/dev)",
        "description": "At boot, write <game>/rsmm/resolved_symbols.json — the "
                       "addresses the loader actually resolved every semantic "
                       "pattern to. Feeds `rsmm symbols audit`. Read-only; adds "
                       "~1s to load. Dev/RE aid.",
        "safe": True,
    },
]

FLAGS_FILE = "rsmm_loader_flags.json"
SAFE_FLAG_NAMES = frozenset(f["name"] for f in LOADER_FLAGS if f["safe"])
KNOWN_FLAG_NAMES = frozenset(f["name"] for f in LOADER_FLAGS)


def read_flags(flags_path: Path) -> list[str]:
    """Read the enabled-flag list, tolerating a missing/garbage file."""
    if not flags_path.exists():
        return []
    try:
        data = json.loads(flags_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    if not isinstance(data, list):
        return []
    return [x for x in data if isinstance(x, str) and x in KNOWN_FLAG_NAMES]


def write_flags(flags_path: Path, names: list[str]) -> None:
    """Write the enabled-flag list; an empty one removes the file so the loader
    logs cleanly."""
    names = sorted(set(names))
    if names:
        flags_path.write_text(json.dumps(names, indent=2) + "\n", encoding="utf-8")
    elif flags_path.exists():
        flags_path.unlink()


def sync_mod_flags(flags_path: Path, requested: set[str],
                   previously_added: set[str]) -> tuple[list[str], set[str]]:
    """Make the flags file hold every flag the enabled mods ask for, without
    touching the player's own choices.

    ``previously_added`` is what the last apply switched on for mods; anything
    else in the file is the player's. Returns ``(the file's new list, what is
    now switched on for mods)``; the caller keeps the second for next time.
    Flags a mod asks for that are not safe are ignored (lint reports them)."""
    current = set(read_flags(flags_path))
    raw = set()
    if flags_path.exists():
        try:
            data = json.loads(flags_path.read_text(encoding="utf-8"))
            raw = {x for x in data if isinstance(x, str)} if isinstance(data, list) else set()
        except (OSError, ValueError):
            raw = set()
    wanted = {f for f in requested if f in SAFE_FLAG_NAMES}
    # The player's flags: everything not put there for a mod, including names
    # this table does not know (a newer loader's, or a hand-written one).
    player = (raw | current) - set(previously_added)
    new = sorted(player | wanted)
    added = wanted - player
    if set(new) != raw:
        write_flags(flags_path, new)
    return new, added
