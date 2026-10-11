"""UsedRscList.ot: the engine's manifest of loadable cooked paths.

A brand-new asset is only loadable once its encoded path is registered here.
Moved out of ``cli/apply_mods.py`` (2026-09-26) so the SDK kinds and
``doctor`` read it from the engine; ``apply_mods`` re-exports every name.
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

from . import cipher
from .paths import BACKUP_SUFFIX, USEDRSCLIST_REL

# UsedRscList.ot is the engine's master manifest: a newline list of
# cipher-encoded cooked paths. The engine only loads a resource if its
# encoded path appears here, so a brand-new asset (custom item / enemy /
# texture not present in the vanilla tree) must be *registered* by
# appending its encoded line, or it is silently never loaded.
# `asset_map.json` is itself derived from this file (see find_iyg.py).


def _asset_id_and_suffix(filename: str) -> tuple[str, str]:
    """Split a cooked filename into (id, suffix) at the first dot.

    e.g. ``Armor_Per_Object.entity.ot.EntitySettingsResource.gen`` ->
    ``("Armor_Per_Object", ".entity.ot.EntitySettingsResource.gen")``.
    Resource ids never contain a dot; everything from the first dot on is
    the kind/cook suffix that two siblings of the same kind share.
    """
    dot = filename.find(".")
    if dot == -1:
        return filename, ""
    return filename[:dot], filename[dot:]


def build_usedrsc_record(decoded: str, pristine_lines: list[str],
                         dec2enc: dict[str, str]) -> list[str] | None:
    """Build the 3-line UsedRscList.ot record for a new cooked asset.

    The engine parses UsedRscList.ot in fixed groups of THREE lines per
    resource (see FUN_140488f50): line 1 is the type root (e.g.
    ``EntitySettings``), line 2 the logical resource name, line 3 the
    cooked file path. Appending fewer than three lines desynchronises the
    reader and it runs off the end into an ``int3`` (hard crash).

    Rather than re-encode all three (each line collapses ``\\``/``!``
    differently per namespace), clone a same-kind sibling's actual record
    from the pristine manifest and swap the encoded id token. ``decoded``
    is the new asset's decoded cooked path (forward slashes). Returns the
    three encoded lines, or None if no structural sibling exists.
    """
    decoded = decoded.replace("\\", "/")
    if "/" not in decoded:
        return None
    parent, new_fname = decoded.rsplit("/", 1)
    new_id, new_suffix = _asset_id_and_suffix(new_fname)
    if not new_id:
        return None

    for dec, enc in dec2enc.items():
        sib = dec.replace("\\", "/")
        if sib == decoded or "/" not in sib:
            continue
        sib_parent, sib_fname = sib.rsplit("/", 1)
        if sib_parent != parent:
            continue
        old_id, old_suffix = _asset_id_and_suffix(sib_fname)
        # Same parent dir AND same kind/cook suffix => structurally
        # identical 3-line record we can clone.
        if old_suffix != new_suffix or not old_id:
            continue
        try:
            idx = pristine_lines.index(enc)
        except ValueError:
            continue
        if idx < 2:
            continue
        triple = pristine_lines[idx - 2: idx + 1]
        enc_old = cipher.encode(old_id)
        enc_new = cipher.encode(new_id)
        # Line 1 (type root) carries no id; lines 2/3 carry the encoded id —
        # in their LAST component only. A blanket replace also rewrote the
        # FOLDER whenever the sibling's id is the folder's name
        # (`Heroes\Hero_Piper\Hero_Piper.entity.ot`), registering the new asset
        # under a directory that does not exist: the file installed, the engine
        # looked elsewhere, and a custom hero spawned as a dark, empty shell.
        return [_swap_last_component(line, enc_old, enc_new) for line in triple]
    return None


def _swap_last_component(line: str, old: str, new: str) -> str:
    """Replace ``old`` with ``new`` only after the final ``\\`` or ``!``."""
    cut = max(line.rfind("\\"), line.rfind("!")) + 1
    return line[:cut] + line[cut:].replace(old, new)


def _read_usedrsclist(path: Path) -> tuple[str | None, list[str]]:
    """Parse UsedRscList.ot into (header, lines).

    The first line is a lone-digit format marker (observed value ``1``)
    that the engine expects to stay in place; everything after it is one
    obfuscated resource path per line. Returns the header verbatim (or
    None if absent) and the list of path lines with surrounding
    whitespace stripped and blanks dropped.
    """
    raw = [ln.strip() for ln in path.read_text(encoding="utf-8").splitlines()]
    raw = [ln for ln in raw if ln]
    header: str | None = None
    if raw and raw[0].isdigit():
        header, raw = raw[0], raw[1:]
    return header, raw


def sync_usedrsclist(game_dir: Path, registrations: dict[str, str],
                     dec2enc: dict[str, str], dry_run: bool) -> int:
    """Ensure UsedRscList.ot registers exactly `registrations` on top of
    the pristine vanilla manifest.

    `registrations` maps encoded-cooked-path -> decoded-path. The engine
    reads UsedRscList.ot in fixed groups of THREE lines per resource, so
    each new asset is appended as a full cloned 3-line record (see
    :func:`build_usedrsc_record`) — appending a single line desyncs the
    reader and crashes the game.

    The original file is backed up once as ``UsedRscList.ot.rsmm.bak`` and
    every rewrite is computed from that pristine copy, so disabling a
    custom mod cleanly drops its records. When `registrations` is empty
    the backup is restored and removed (see :func:`restore_usedrsclist`).
    Returns the number of resources newly registered.
    """
    path = game_dir / USEDRSCLIST_REL
    if not path.exists():
        if registrations:
            print(f"  [warn] cannot register {len(registrations)} new asset(s): "
                  f"{path} not found", file=sys.stderr)
        return 0
    if not registrations:
        return restore_usedrsclist(game_dir, dry_run)

    bak = path.with_name(path.name + BACKUP_SUFFIX)
    if not bak.exists() and not dry_run:
        shutil.copy2(path, bak)
    pristine = bak if bak.exists() else path
    header, base_lines = _read_usedrsclist(pristine)
    have = set(base_lines)

    new_lines: list[str] = []
    added = 0
    for enc in sorted(registrations):
        if enc in have:
            continue  # already a vanilla/registered resource
        record = build_usedrsc_record(registrations[enc], base_lines, dec2enc)
        if record is None:
            print(f"  [warn] cannot build UsedRscList record for "
                  f"'{registrations[enc]}' (no same-kind sibling); skipping",
                  file=sys.stderr)
            continue
        new_lines.extend(record)
        added += 1

    desired = ([header] if header is not None else []) + base_lines + new_lines

    # Idempotent: if the manifest already reads exactly as desired, do
    # nothing (don't rewrite ~64k lines every apply / report false work).
    cur_header, cur_lines = _read_usedrsclist(path)
    current = ([cur_header] if cur_header is not None else []) + cur_lines
    if current == desired:
        return 0

    print(f"  [usedrsc] registering {added} new asset(s) "
          f"({len(new_lines)} lines) in UsedRscList.ot")
    if not dry_run:
        body = "\n".join(desired) + "\n"
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(body, encoding="utf-8")
        tmp.replace(path)
    return added or 1


def restore_usedrsclist(game_dir: Path, dry_run: bool) -> int:
    """Roll UsedRscList.ot back to its pristine backup, dropping every
    custom registration. No-op if no backup exists. Returns 1 if a
    restore happened, else 0."""
    path = game_dir / USEDRSCLIST_REL
    bak = path.with_name(path.name + BACKUP_SUFFIX)
    if not bak.exists():
        return 0
    print("  [usedrsc] restoring pristine UsedRscList.ot")
    if not dry_run:
        try:
            shutil.copy2(bak, path)
            bak.unlink()
        except OSError as e:
            print(f"  [ERROR] failed to restore UsedRscList.ot: {e}",
                  file=sys.stderr)
    return 1
