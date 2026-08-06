"""Game-build pin + schema migration helper.

`<cooking>/.rsmm_game_build.json`:

    {"sha256": "...", "size": 12345678, "first_seen": 17161...}

On apply, the current EXE is hashed; mismatch -> warn + flag mods whose
`target_game_build` differs from the pin's recorded build. Mods using
raw VAs (versus pattern-resolved names) should be auto-disabled.
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass
from pathlib import Path

PIN_FILE_NAME = ".rsmm_game_build.json"


def pin_exists(cooking: Path) -> bool:
    """True when a pin file is present, readable or not."""
    return (cooking / PIN_FILE_NAME).exists()


@dataclass
class GameBuildPin:
    sha256: str
    size: int
    first_seen: int

    @classmethod
    def from_exe(cls, exe: Path) -> GameBuildPin:
        h = hashlib.sha256()
        size = 0
        with exe.open("rb") as f:
            for chunk in iter(lambda: f.read(1 << 16), b""):
                h.update(chunk)
                size += len(chunk)
        return cls(sha256=h.hexdigest(), size=size, first_seen=int(time.time()))

    @classmethod
    def load(cls, cooking: Path) -> GameBuildPin | None:
        """Read the pin, or None if the file is absent OR unreadable.

        Field coercion is inside the guard on purpose: only malformed JSON
        used to be caught, so a pin whose ``size`` was a string raised
        ValueError out of here and took the whole apply with it, while
        malformed JSON returned None. Same corruption, two behaviours.

        Callers must distinguish "no pin" from "bad pin" with
        :func:`pin_exists` — silently treating a corrupt pin as a first
        install re-pins the CURRENT exe and hides a game update.
        """
        p = cooking / PIN_FILE_NAME
        if not p.exists():
            return None
        try:
            raw = json.loads(p.read_text(encoding="utf-8"))
            return cls(
                sha256=str(raw["sha256"]),
                size=int(raw["size"]),
                first_seen=int(raw.get("first_seen", 0)),
            )
        except (OSError, ValueError, TypeError, KeyError, AttributeError):
            return None

    def save(self, cooking: Path) -> None:
        p = cooking / PIN_FILE_NAME
        tmp = p.with_suffix(p.suffix + ".tmp")
        tmp.write_text(
            json.dumps({"sha256": self.sha256, "size": self.size,
                        "first_seen": self.first_seen}, indent=2),
            encoding="utf-8",
        )
        tmp.replace(p)


def check_compat(exe: Path, cooking: Path) -> tuple[bool, str]:
    """Return (compat_ok, message).

    First call after a new install records the pin and reports `ok`.
    Subsequent calls compare and report any mismatch.
    """
    if not exe.exists():
        return False, f"EXE not found: {exe}"
    cur = GameBuildPin.from_exe(exe)
    pin = GameBuildPin.load(cooking)
    if pin is None and pin_exists(cooking):
        # Fail closed. Re-pinning here would record whatever is installed
        # right now as "the known-good build", which is exactly what a
        # corrupt pin must not be allowed to do after a game update.
        return False, (
            f"game build pin at {cooking / PIN_FILE_NAME} is unreadable. "
            f"Delete it to re-pin against the current install."
        )
    if pin is None:
        cur.save(cooking)
        return True, f"pinned build {cur.sha256[:12]} ({cur.size} bytes)"
    if pin.sha256 == cur.sha256:
        return True, f"build unchanged ({cur.sha256[:12]})"
    return False, (
        f"game updated: was {pin.sha256[:12]} ({pin.size} bytes), "
        f"now {cur.sha256[:12]} ({cur.size} bytes). "
        f"Mods using raw VAs may be unsafe; pattern-resolved fn calls "
        f"should keep working."
    )
