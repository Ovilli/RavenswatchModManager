"""Keep every magical-object record a profile ever had, and put back the ones
the game dropped.

The game writes `oCDtMagicalObjectProfileData` only for items whose entity it
loaded that session. An item absent from the LiveOps catalog for one session (an
item ban, a disabled mod's custom item) is therefore written out of the profile
on the next save, and restoring the catalog does not bring it back: the item
shows as never seen. Measured 2026-10-22: banning items, playing once and
restoring wiped 37 of 128 records.

So every apply and restore records each profile's item records here (latest
state wins) and appends any the save no longer has. A record put back while its
item is still banned is dropped again by the next game save and put back again
by the next apply, which is harmless: loading a record for an item that is not
registered is what the game already does on the first session after a ban.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from rsmm.engine import savefile as SF

LEDGER_NAME = "save_item_ledger.json"


def _ledger_path() -> Path:
    from rsmm.engine.paths import user_data_dir
    return user_data_dir() / LEDGER_NAME


def _key(p: Path) -> str:
    return p.stem.removesuffix("_Temp")


def _records(p: Path) -> dict[str, str] | None:
    try:
        return {r.guid.hex(): SF.item_body(r).hex() for r in SF.item_records(SF.load(p))}
    except (OSError, SF.SaveFormatError) as e:
        print(f"  [warn] save: {p.name} not read ({e}); its items are not protected",
              file=sys.stderr)
        return None


def _seed(ledger: dict[str, dict[str, str]]) -> None:
    """A first ledger also takes the Save tab's backups, oldest first, so a
    profile that already lost records before this existed can get them back."""
    from rsmm.engine.paths import user_data_dir
    root = user_data_dir() / "save_backups"
    if not root.is_dir():
        return
    for p in sorted(root.glob("*/Profile_*.ob"), key=lambda p: p.stat().st_mtime):
        if (recs := _records(p)) is not None:
            ledger.setdefault(_key(p), {}).update(recs)


def sync(game_dir: Path, dry_run: bool = False) -> int:
    """Record every profile's item records and re-add any missing ones.
    Returns the number of records put back. Never raises for a bad save."""
    saves = sorted(SF.find_saves(game_dir), key=lambda p: (_key(p), p.stem == _key(p)))
    if not saves:
        return 0
    path = _ledger_path()
    try:
        ledger = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None
    except (OSError, ValueError) as e:
        print(f"  [warn] save: unreadable {path.name} ({e}); starting a new one",
              file=sys.stderr)
        ledger = None
    if ledger is None:
        ledger = {}
        _seed(ledger)
    present: dict[Path, dict[str, str]] = {}
    for p in saves:                     # each `_Temp` first, so the real profile wins
        if (recs := _records(p)) is not None:
            present[p] = recs
            ledger.setdefault(_key(p), {}).update(recs)
    added = 0
    for p, recs in present.items():
        missing = [bytes.fromhex(b) for g, b in ledger.get(_key(p), {}).items() if g not in recs]
        if not missing:
            continue
        print(f"  [save] {p.name}: putting back {len(missing)} item record(s) the game dropped")
        added += len(missing)
        if dry_run:
            continue
        try:
            s = SF.load(p)
            SF.append_item_records(s, missing)
            SF.write(s)
        except (OSError, SF.SaveFormatError, ValueError) as e:
            print(f"  [warn] save: {p.name} not repaired ({e})", file=sys.stderr)
    if not dry_run:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(ledger, indent=1, sort_keys=True), encoding="utf-8")
        except OSError as e:
            print(f"  [warn] save: could not write {path} ({e})", file=sys.stderr)
    return added
