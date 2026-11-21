"""Put back an install a modded session left behind — only when that is certain.

The restore watcher undoes a modded launch once the game exits. When the
watcher itself is gone before that (the PC shut down or the player logged off
while playing, or it crashed), nothing restores: the install stays modded and
every plain Steam launch runs mods until the next modded launch finishes. The
desktop calls `heal()` once at start-up to close that gap.

An unattended restore can do real damage, so it runs only when every one of
these holds, and otherwise reports why it did nothing:

1. there is something to undo (active overrides, or mod files in the game's
   `mods/` dir);
2. it was left by a modded LAUNCH — an explicit "Apply mods" is the player's
   choice and is never undone here (state ``applied_for``; an install applied
   before this existed is left alone);
3. no restore watcher is alive (it will restore itself) and no modded launch
   started recently (one may be starting, or Steam may be slow to start it);
4. the game is definitely not running: several probes, each of which must
   SUCCEED and say "not running" — a failed probe counts as "maybe running";
5. Steam is not writing the game's files, and the Steam build is the one the
   mods were applied to: a data-only patch leaves rsmm's fingerprint unchanged,
   and restoring the pre-patch backups would put old files over the patch.

The restore itself runs in-process under the install lock, after re-reading the
launch generation inside it: a modded launch that began after the checks has
bumped it and wins; one that begins after the lock is taken waits for the lock
and applies after this restore, which is the order it needs.
"""

from __future__ import annotations

import contextlib
import sys
import time
from pathlib import Path
from types import SimpleNamespace

#: A modded launch younger than this may still be starting (Steam can take
#: minutes): leave it to its watcher.
RECENT_LAUNCH_S = 600.0


def _runtime_mods_present(game_dir: Path) -> bool:
    from rsmm.cli.apply_mods import _LOADER_OWNED_RUNTIME_FILES

    mods = game_dir / "mods"
    try:
        return any(c.name not in _LOADER_OWNED_RUNTIME_FILES for c in mods.iterdir())
    except OSError:
        return False


def _skip(reason: str, detail: str) -> dict:
    return {"ok": True, "action": "skipped", "reason": reason, "detail": detail}


def heal(game_dir: Path, *, probes: int = 3, probe_interval: float = 1.0,
         recent_launch_s: float = RECENT_LAUNCH_S) -> dict:
    """Restore a modded install left behind by a launch, if it is safe.

    Returns ``{"ok", "action": "restored" | "skipped", "reason", "detail"}``
    and, after a restore, ``"code"`` (0, or 2 when residue remained).
    """
    from rsmm.cli import apply_mods as A
    from rsmm.cli import watch_restore as W
    from rsmm.engine import game_proc
    from rsmm.engine.paths import COOKING_REL
    from rsmm.engine.safeio import LockBusy, install_lock
    from rsmm.engine.steam_app import app_state

    cooking = game_dir / COOKING_REL
    if not cooking.is_dir():
        return _skip("no-game", f"no _Cooking dir under {game_dir}")
    state = A.State(cooking)
    if not state.active and not _runtime_mods_present(game_dir):
        return _skip("clean", "nothing is applied")
    applied_for = state.data.get("applied_for")
    if applied_for != "launch":
        return _skip("manual", "mods were applied outside a launch ("
                     f"{applied_for or 'unrecorded'}); leaving them as the player set them")
    if W.watcher_alive():
        return _skip("watcher", "a restore watcher is running and will restore")
    age = W.launch_generation_age()
    if age is not None and age < recent_launch_s:
        return _skip("recent-launch", f"a modded launch started {age:.0f}s ago")
    for i in range(probes):
        seen = game_proc.probe_game()
        if seen is not False:
            return _skip("game-running" if seen else "probe-failed",
                         "Ravenswatch is running" if seen
                         else "could not tell whether Ravenswatch is running")
        if i + 1 < probes:
            time.sleep(probe_interval)
    steam = app_state(game_dir)
    if steam is not None:
        if steam.steam_busy:
            return _skip("steam-busy", f"Steam is updating or validating the game "
                         f"(StateFlags {steam.state_flags})")
        applied_on = state.data.get("steam_buildid")
        if applied_on and steam.buildid and applied_on != steam.buildid:
            return _skip("game-updated", f"Steam updated the game (build {applied_on} "
                         f"-> {steam.buildid}) since the mods were applied; the "
                         "update repair handles this")

    generation = W.read_launch_generation()
    try:
        with install_lock(cooking, "self-heal", timeout=0):
            if W.read_launch_generation() != generation:
                return _skip("recent-launch", "a modded launch started during the checks")
            if game_proc.probe_game() is not False:
                return _skip("game-running", "Ravenswatch started during the checks")
            # restore prints its progress; stdout belongs to the JSON answer.
            with contextlib.redirect_stdout(sys.stderr):
                code = A.cmd_restore_all(SimpleNamespace(dry_run=False), A.REPO_DIR,
                                         cooking, game_dir)
                A._protect_save_items(game_dir, False)
    except LockBusy as e:
        return _skip("busy", f"another rsmm operation holds the install: {e}")
    if code not in (0, 2):
        return {"ok": False, "action": "skipped", "reason": "restore-failed",
                "detail": f"restore exited {code}", "code": code}
    return {"ok": True, "action": "restored", "reason": "left-behind",
            "detail": "a modded session ended without restoring (the PC shut down "
                      "or the restore watcher stopped)" +
                      ("; some modded files could not be restored" if code == 2 else ""),
            "code": code}
