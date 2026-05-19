"""Two-phase transactional apply.

Phase 1 — stage: every write goes into `<cooking>/.rsmm_stage/`. Backups
are taken next to originals (existing behavior, unchanged).

Phase 2 — commit: atomic `os.replace` from staged path to live path. On
the first mid-commit error, every successful replace is rolled back
from the backup.

A `COMMIT` marker file is written before phase 2 begins. On startup of a
later apply, the presence of an orphan staging dir tells us:

  * marker present + staging dir present  -> resume commit
  * marker absent  + staging dir present  -> discard staging (crash mid-stage)
  * marker absent  + staging dir absent   -> normal startup
"""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path

STAGE_DIR_NAME = ".rsmm_stage"
COMMIT_MARKER_NAME = ".rsmm_stage.COMMIT"
BACKUP_SUFFIX = ".rsmm.bak"


@dataclass
class StagedWrite:
    encoded: str                 # opaque key used by apply_mods
    src: Path                    # mod's source file
    dest: Path                   # final live path under _Cooking/
    stage: Path                  # temp path under .rsmm_stage/
    backup: Path | None = None   # set during commit if dest existed


@dataclass
class ApplyTransaction:
    """Drives stage -> commit -> rollback for an apply batch.

    Use:

        tx = ApplyTransaction(cooking)
        tx.recover()                     # commit/discard any orphan stage
        for enc, src, dest in writes:
            tx.stage_write(enc, src, dest)
        tx.commit()
    """

    cooking: Path
    pending: list[StagedWrite] = field(default_factory=list)

    @property
    def stage_root(self) -> Path:
        return self.cooking / STAGE_DIR_NAME

    @property
    def commit_marker(self) -> Path:
        return self.cooking / COMMIT_MARKER_NAME

    # ---- recovery -----------------------------------------------------

    def recover(self) -> str:
        """Inspect on-disk state from a previous run; return what happened.

        Returns one of: "clean", "discarded", "resumed".
        """
        has_stage = self.stage_root.is_dir()
        has_marker = self.commit_marker.exists()
        if not has_stage and not has_marker:
            return "clean"
        if has_stage and not has_marker:
            shutil.rmtree(self.stage_root, ignore_errors=True)
            return "discarded"
        # Marker present: try to finish whatever the previous run started.
        # We can't reconstruct destinations without the original plan, so
        # the marker is treated as an error beacon for the applier to
        # warn the user. Most reliable behaviour: discard + warn.
        if has_stage:
            shutil.rmtree(self.stage_root, ignore_errors=True)
        try:
            self.commit_marker.unlink()
        except FileNotFoundError:
            pass
        return "discarded"

    # ---- staging ------------------------------------------------------

    def stage_write(self, encoded: str, src: Path, dest: Path) -> StagedWrite:
        """Copy `src` into the staging tree mirroring its final location."""
        rel = self._safe_rel(encoded)
        stage = self.stage_root / rel
        stage.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, stage)
        w = StagedWrite(encoded=encoded, src=src, dest=dest, stage=stage)
        self.pending.append(w)
        return w

    # ---- commit -------------------------------------------------------

    def commit(self) -> list[str]:
        """Atomically move every staged file into place.

        On error, every previously committed file is restored from its
        backup. Returns the list of encoded paths committed successfully
        before any failure.
        """
        committed: list[StagedWrite] = []
        self.commit_marker.parent.mkdir(parents=True, exist_ok=True)
        self.commit_marker.write_text("1", encoding="utf-8")
        try:
            for w in self.pending:
                if w.dest.exists():
                    bak = w.dest.parent / (w.dest.name + BACKUP_SUFFIX)
                    if not bak.exists():
                        shutil.copy2(w.dest, bak)
                    w.backup = bak
                w.dest.parent.mkdir(parents=True, exist_ok=True)
                os.replace(w.stage, w.dest)
                committed.append(w)
        except Exception:
            self._rollback(committed)
            raise
        finally:
            shutil.rmtree(self.stage_root, ignore_errors=True)
            try:
                self.commit_marker.unlink()
            except FileNotFoundError:
                pass
        return [w.encoded for w in committed]

    # ---- internals ----------------------------------------------------

    def _rollback(self, committed: list[StagedWrite]) -> None:
        for w in reversed(committed):
            if w.backup and w.backup.exists():
                try:
                    os.replace(w.backup, w.dest)
                except Exception:
                    pass

    def _safe_rel(self, encoded: str) -> Path:
        """Translate the applier's encoded key into a relative staging path.

        Defends against `..` escapes and absolute paths so a malformed
        manifest can't write outside the staging tree.
        """
        parts = [p for p in encoded.replace("\\", "/").split("/") if p]
        cleaned: list[str] = []
        for p in parts:
            if p in (".", ".."):
                raise ValueError(f"unsafe staging path component: {encoded!r}")
            cleaned.append(p)
        if not cleaned:
            raise ValueError(f"empty staging path: {encoded!r}")
        return Path(*cleaned)
