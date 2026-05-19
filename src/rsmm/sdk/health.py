"""Health system — boot canary + crash-history bisect.

Loader writes `<cooking>/.rsmm_boot.json` at DllMain:

    {"started_at": 1716120000, "mods": [...], "last_step": "init"}

Each step transition is `init -> per_mod:A -> per_mod:B -> ready`.
Clean shutdown deletes the file. Crashy boot leaves a stale canary
which we inspect on the next launch.

Crash history lives in `<cooking>/.rsmm_health.json`:

    {
      "version": 1,
      "threshold": 3,
      "mods": {
        "Foo": {"crashes": 2, "last_error": "...", "last_seen": 17161...,
                "disabled_by_health": false}
      }
    }
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from .api import sdk_export

BOOT_CANARY_NAME = ".rsmm_boot.json"
HEALTH_FILE_NAME = ".rsmm_health.json"

DEFAULT_THRESHOLD = 3


@dataclass
class ModHealth:
    crashes: int = 0
    last_error: str = ""
    last_seen: int = 0
    disabled_by_health: bool = False


@dataclass
class HealthState:
    threshold: int = DEFAULT_THRESHOLD
    mods: dict[str, ModHealth] = field(default_factory=dict)


class Health:
    """Read/write the crash-history sidecar + interpret the boot canary.

    Pure file IO. Loader writes the canary; this class writes only the
    health sidecar. Keeping the surfaces separate avoids a race where
    the loader and the CLI both touch the same file.
    """

    def __init__(self, cooking: Path):
        self.cooking = cooking
        self.health_path = cooking / HEALTH_FILE_NAME
        self.canary_path = cooking / BOOT_CANARY_NAME

    # ---- health sidecar -----------------------------------------------

    def load(self) -> HealthState:
        if not self.health_path.exists():
            return HealthState()
        try:
            raw = json.loads(self.health_path.read_text(encoding="utf-8"))
        except Exception:
            return HealthState()
        st = HealthState(threshold=int(raw.get("threshold", DEFAULT_THRESHOLD)))
        for mid, body in (raw.get("mods") or {}).items():
            st.mods[mid] = ModHealth(
                crashes=int(body.get("crashes", 0)),
                last_error=str(body.get("last_error", "")),
                last_seen=int(body.get("last_seen", 0)),
                disabled_by_health=bool(body.get("disabled_by_health", False)),
            )
        return st

    def save(self, st: HealthState) -> None:
        body = {
            "version": 1,
            "threshold": st.threshold,
            "mods": {
                mid: {
                    "crashes": h.crashes,
                    "last_error": h.last_error,
                    "last_seen": h.last_seen,
                    "disabled_by_health": h.disabled_by_health,
                }
                for mid, h in sorted(st.mods.items())
            },
        }
        tmp = self.health_path.with_suffix(self.health_path.suffix + ".tmp")
        tmp.write_text(json.dumps(body, indent=2), encoding="utf-8")
        tmp.replace(self.health_path)

    # ---- boot canary --------------------------------------------------

    def read_canary(self) -> Optional[dict]:
        """Return the canary if one is on disk, else None.

        The loader is responsible for deleting it on a clean shutdown,
        so seeing one here is itself the crash signal.
        """
        if not self.canary_path.exists():
            return None
        try:
            return json.loads(self.canary_path.read_text(encoding="utf-8"))
        except Exception:
            return {"corrupt": True, "raw": self.canary_path.read_text(
                encoding="utf-8", errors="replace"
            )}

    def clear_canary(self) -> None:
        try:
            self.canary_path.unlink()
        except FileNotFoundError:
            pass

    def attribute_crash(self, canary: dict) -> Optional[str]:
        """Given a stale canary, return the mod id we hold responsible."""
        step = str(canary.get("last_step", ""))
        if step.startswith("per_mod:"):
            return step[len("per_mod:"):]
        return None  # crash before any mod ran -> not a mod's fault

    @sdk_export("Health.record_crash")
    def record_crash(self, mod_id: str, error: str = "") -> HealthState:
        """Bump the mod's crash counter, persist, return the updated state.

        If the mod hits `threshold`, mark `disabled_by_health=True`. The
        applier consults this on the next run.
        """
        st = self.load()
        h = st.mods.setdefault(mod_id, ModHealth())
        h.crashes += 1
        h.last_error = error[:512]
        h.last_seen = int(time.time())
        if h.crashes >= st.threshold:
            h.disabled_by_health = True
        self.save(st)
        return st

    @sdk_export("Health.disabled_mods")
    def disabled_mods(self) -> set[str]:
        st = self.load()
        return {mid for mid, h in st.mods.items() if h.disabled_by_health}

    @sdk_export("Health.re_enable")
    def re_enable(self, mod_id: str) -> None:
        """User manually re-enables after fixing the crash."""
        st = self.load()
        h = st.mods.get(mod_id)
        if not h:
            return
        h.crashes = 0
        h.disabled_by_health = False
        h.last_error = ""
        self.save(st)
