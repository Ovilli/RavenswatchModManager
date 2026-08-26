"""Health system — boot canary + crash history, as written by the LOADER.

The loader is the only process that can observe a crashy boot, so it owns the
file. `src/loader/src/health.cpp` opens `<game>/mods/_health.json` before any
mod code runs, stamps `canary.step` as each `init.lua` executes, and closes the
canary ~2 s after `ready`. A canary still open at the next launch means the
previous run died at that step, so the crash is attributed to that mod; three
consecutive failed boots disable it.

    {
      "version": 1,
      "canary": {"open": false, "step": "boot_ok", "session": "fd1d"},
      "mods": {
        "Foo": {"crashes": 2, "last_error": "...",
                "disabled": false, "disabled_reason": ""}
      }
    }

This module is the read/write side for the CLI. It used to describe — and
address — a completely different pair of files: `.rsmm_boot.json` and
`.rsmm_health.json` under `_Cooking`, with `last_step` instead of
`canary.step` and `disabled_by_health` instead of `disabled`. Nothing has ever
written those, so every consumer silently no-opped: `rsmm doctor` reported "no
crash records" while the loader had a mod disabled, `apply`'s quarantine pass
never quarantined anything, and `safe-mode --bisect` wrote its findings where
the loader would never read them. Two health systems that never met.

Writes are read-modify-write on the whole document so the CLI can never clobber
the canary node the loader is keeping, and land via temp-file + rename — the
whole point of this file is to survive a process that dies at an arbitrary
instant, so it must never be observed truncated.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path

from .api import sdk_export

#: Written by the loader, next to the mods it describes.
HEALTH_FILE_NAME = "_health.json"

#: Mirrors `kStrikeLimit` in src/loader/src/health.cpp. The loader does the
#: disabling; this is here so the CLI can explain the rule and so
#: `record_crash` (safe-mode bisect) reaches the same verdict.
DEFAULT_THRESHOLD = 3


@dataclass
class ModHealth:
    crashes: int = 0
    last_error: str = ""
    disabled: bool = False
    disabled_reason: str = ""
    last_seen: int = 0


@dataclass
class HealthState:
    threshold: int = DEFAULT_THRESHOLD
    mods: dict[str, ModHealth] = field(default_factory=dict)


def _resolve_game_dir(path: Path) -> Path:
    """Accept the game dir or the `_Cooking` dir; return the game dir.

    Every existing caller passes `<game>/DarkTalesResources/_Cooking`, because
    that is where this class used to keep its own files. Rather than touch each
    one, normalise here.
    """
    path = Path(path)
    if (path / "Ravenswatch.exe").exists() or (path / "mods").is_dir():
        return path
    # <game>/DarkTalesResources/_Cooking -> <game>
    if path.name == "_Cooking" and len(path.parents) >= 2:
        return path.parents[1]
    return path


class Health:
    """Read/write the loader's crash history and inspect its boot canary."""

    def __init__(self, path: Path):
        self.game_dir = _resolve_game_dir(path)
        self.mods_dir = self.game_dir / "mods"
        self.health_path = self.mods_dir / HEALTH_FILE_NAME
        #: Kept for callers that still speak in terms of the cooking dir.
        self.cooking = Path(path)

    # ---- raw document --------------------------------------------------

    def _read_doc(self) -> dict:
        try:
            raw = json.loads(self.health_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        return raw if isinstance(raw, dict) else {}

    def _write_doc(self, doc: dict) -> None:
        self.mods_dir.mkdir(parents=True, exist_ok=True)
        tmp = self.health_path.with_suffix(self.health_path.suffix + ".tmp")
        tmp.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
        os.replace(tmp, self.health_path)

    # ---- health sidecar -----------------------------------------------

    def load(self) -> HealthState:
        doc = self._read_doc()
        st = HealthState()
        mods = doc.get("mods")
        if not isinstance(mods, dict):
            return st
        for mid, body in mods.items():
            if not isinstance(body, dict):
                continue
            st.mods[str(mid)] = ModHealth(
                crashes=int(body.get("crashes", 0) or 0),
                last_error=str(body.get("last_error", "") or ""),
                disabled=bool(body.get("disabled", False)),
                disabled_reason=str(body.get("disabled_reason", "") or ""),
                last_seen=int(body.get("last_seen", 0) or 0),
            )
        return st

    def save(self, st: HealthState) -> None:
        # Read-modify-write: `canary` and `version` belong to the loader and
        # must survive a CLI write. Rebuilding the document from HealthState
        # alone would drop the canary mid-session and lose the attribution for
        # a crash that had already happened.
        #
        # This makes a CLI write safe against the file on disk, which is only
        # half the race: the loader keeps the whole document in memory for the
        # session, so it used to overwrite a CLI edit landing mid-launch (the
        # desktop app running `safe-mode --reset <id>` with the game open saw
        # the mod re-quarantine itself). health.cpp::save_locked now merges
        # onto the current file and only writes back the quarantine fields for
        # mods THAT session quarantined, so both directions hold.
        doc = self._read_doc()
        doc["version"] = doc.get("version", 1)
        doc["mods"] = {
            mid: {
                "crashes": h.crashes,
                "last_error": h.last_error,
                "disabled": h.disabled,
                "disabled_reason": h.disabled_reason,
                **({"last_seen": h.last_seen} if h.last_seen else {}),
            }
            for mid, h in sorted(st.mods.items())
        }
        self._write_doc(doc)

    # ---- boot canary --------------------------------------------------

    def read_canary(self) -> dict | None:
        """Return the canary node if one is OPEN, else None.

        An open canary is itself the crash signal: the loader closes it once a
        launch has demonstrably survived boot. A closed one is not interesting,
        so it reads the same as no canary at all.
        """
        canary = self._read_doc().get("canary")
        if not isinstance(canary, dict) or not canary.get("open", False):
            return None
        return canary

    def clear_canary(self) -> None:
        doc = self._read_doc()
        canary = doc.get("canary")
        if not isinstance(canary, dict):
            return
        canary["open"] = False
        doc["canary"] = canary
        self._write_doc(doc)

    def attribute_crash(self, canary: dict) -> str | None:
        """Given an open canary, return the mod id we hold responsible."""
        step = str(canary.get("step", ""))
        if step.startswith("per_mod:"):
            return step[len("per_mod:"):]
        return None  # crash before any mod ran -> not a mod's fault

    @sdk_export("Health.record_crash")
    def record_crash(self, mod_id: str, error: str = "") -> HealthState:
        """Bump the mod's crash counter, persist, return the updated state.

        At `threshold` the mod is marked disabled, which the loader honours at
        load and the applier honours at apply.
        """
        st = self.load()
        h = st.mods.setdefault(mod_id, ModHealth())
        h.crashes += 1
        h.last_error = error[:512]
        h.last_seen = int(time.time())
        if h.crashes >= st.threshold and not h.disabled:
            h.disabled = True
            h.disabled_reason = f"failed to boot {h.crashes} times in a row"
        self.save(st)
        return st

    @sdk_export("Health.disabled_mods")
    def disabled_mods(self) -> set[str]:
        """Ids of mods the loader (or a bisect) has quarantined.

        These were disabled after a crashy launch; the user re-enables each
        with :meth:`re_enable` once fixed.
        """
        return {mid for mid, h in self.load().mods.items() if h.disabled}

    @sdk_export("Health.re_enable")
    def re_enable(self, mod_id: str) -> None:
        """User manually re-enables after fixing the crash."""
        st = self.load()
        h = st.mods.get(mod_id)
        if not h:
            return
        h.crashes = 0
        h.disabled = False
        h.disabled_reason = ""
        h.last_error = ""
        self.save(st)
