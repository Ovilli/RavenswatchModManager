#!/usr/bin/env python3
"""
Ravenswatch Mod Manager — install-time mod applier.

Asset overrides in Ravenswatch work without any DLL injection: the engine
loads cooked assets from `<install>/DarkTalesResources/_Cooking/<encoded>`
and is happy with any byte-compatible replacement at that path. So a mod
is just a tree of cooked files; this tool copies them into `_Cooking/`
with backups, and restores backups when mods are disabled.

Mod layout:

  mods/<ModId>/
    manifest.toml           # name, version, author, etc.
    assets/<decoded-path>   # decoded path; looked up in asset_map.json
                            # encoded path under _Cooking/.

State:

  <install>/DarkTalesResources/_Cooking/.rsmm_state.json
    Tracks which files are currently overridden so subsequent runs can
    cleanly diff and only touch what's changed.

Backups:

  Each overridden file gets sibling `<file>.rsmm.bak` containing the
  original cooked bytes. Restored when the mod is disabled or removed.

Usage:

  ./rsmm apply                 # apply current mods/ state to install
  ./rsmm apply --restore-all   # roll back all active overrides
  ./rsmm apply --dry-run       # print plan, change nothing
  ./rsmm apply --list          # show discovered mods
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import struct
import subprocess
import sys
import tomllib  # Python 3.11+
from contextlib import contextmanager
from pathlib import Path

from rsmm.cli import _term
from rsmm.engine import cipher, cook_cache, cooked_schemas
from rsmm.engine.hashing import sha256_file as sha256
from rsmm.engine.paths import (
    ASSET_MAP_JSON,
    MODS_DIR,
    _game_dir_candidates,
    game_fingerprint,
    load_stored_fingerprint,
    save_fingerprint,
)
from rsmm.engine.paths import (
    REPO_ROOT as REPO_DIR,
)
from rsmm.engine.safeio import (
    LockBusy,
    NotEnoughSpace,
    atomic_copy,
    atomic_write_text,
    ensure_free_space,
    install_lock,
    sweep_temp_files,
)


def parse_toml(p: Path) -> dict:
    return tomllib.loads(p.read_text(encoding="utf-8"))


COOKING_REL = Path("DarkTalesResources/_Cooking")
JOURNAL_FILE_NAME = ".rsmm_journal.jsonl"
STATE_FILE_NAME = ".rsmm_state.json"
BACKUP_SUFFIX = ".rsmm.bak"


def find_game_dir() -> Path | None:
    """Best-effort autodetect across Windows/Linux.

    The cooked asset tree is the canonical marker (DarkTalesResources/_Cooking).
    Return the first install dir that contains it. Candidate list lives
    in `rsmm.engine.paths` so every CLI agrees.
    """
    for c in _game_dir_candidates():
        if (c / COOKING_REL).is_dir():
            return c
    return None


class Journal:
    """Write-ahead record of files an apply is ABOUT to touch.

    The state file is written once, at the end of an apply. A crash before
    that leaves every already-applied override live but unrecorded. For a
    file that replaced a vanilla asset that is survivable — `restore --all`
    sweeps orphan `.rsmm.bak` files — but a file a mod *added* has no backup
    and no state entry, so nothing knew it existed and it stayed in the
    install forever.

    So each intent is appended (and fsynced) BEFORE the write. On the next
    apply or restore, leftover intents are folded into state as ordinary
    entries, which hands them to the existing, tested restore rules: an
    added file gets dropped, a replaced one gets restored from its backup.

    An intent for a write that never happened is harmless — restore checks
    the destination exists before touching it.
    """

    def __init__(self, cooking: Path):
        self.path = cooking / JOURNAL_FILE_NAME

    def record(self, enc: str, mod_id: str, *, added: bool) -> None:
        line = json.dumps({"enc": enc, "mod": mod_id, "added": added},
                          sort_keys=True)
        try:
            with open(self.path, "a", encoding="utf-8") as f:
                f.write(line + "\n")
                f.flush()
                os.fsync(f.fileno())
        except OSError as e:
            # Journalling is a safety net, not a gate: failing the apply
            # because the net could not be hung would be worse.
            print(f"  [warn] could not journal {enc}: {e}", file=sys.stderr)

    def clear(self) -> None:
        try:
            self.path.unlink()
        except FileNotFoundError:
            pass
        except OSError as e:
            print(f"  [warn] could not clear journal: {e}", file=sys.stderr)

    def pending(self) -> list[dict]:
        """Entries from a previous run that crashed before writing state."""
        if not self.path.exists():
            return []
        out: list[dict] = []
        try:
            for raw in self.path.read_text(encoding="utf-8").splitlines():
                raw = raw.strip()
                if not raw:
                    continue
                try:
                    rec = json.loads(raw)
                except ValueError:
                    continue  # torn final line — the rest is still good
                if isinstance(rec, dict) and rec.get("enc"):
                    out.append(rec)
        except OSError:
            return []
        return out


def reconcile_journal(cooking: Path, state: State) -> int:
    """Fold a crashed run's journal into state; return how many were adopted.

    Called at the start of apply and restore. Entries already tracked in
    state are dropped — they completed and were recorded.
    """
    journal = Journal(cooking)
    pending = journal.pending()
    if not pending:
        return 0
    adopted = 0
    for rec in pending:
        enc = str(rec["enc"])
        if enc in state.active:
            continue
        state.active[enc] = {
            "mod": str(rec.get("mod", "")),
            "src_sha256": "",
            # No recorded original means "added by a mod" to the restore
            # rules, which is exactly what `added` says. For a replaced file
            # the backup on disk is what restore keys on, and the vanilla
            # guard in restore_one still protects game-shipped paths.
            "orig_sha256": "" if rec.get("added") else "unknown",
        }
        adopted += 1
    if adopted:
        print(f"  [recover] adopted {adopted} unrecorded write(s) from an "
              f"interrupted run", file=sys.stderr)
        try:
            state.save()
        except OSError as e:
            print(f"  [warn] could not save recovered state: {e}", file=sys.stderr)
    journal.clear()
    return adopted


class State:
    """Tracks active overrides in <cooking>/.rsmm_state.json.

    Schema (v1):
      {
        "version": 1,
        "active": {
          "<encoded-relative-path>": {
            "mod": "<mod-id>",
            "src_sha256":  "<sha256 of mod file>",
            "orig_sha256": "<sha256 of pre-override game file>"
          }
        }
      }

    Migration note: pre-0.1.12 state files use `src_sha1` / `orig_sha1`.
    Those keys are ignored on read (treated as unknown / re-apply); the
    next apply rewrites the entry with the sha256 fields above. SHA-1
    is cryptographically broken — an attacker who can write a mod file
    could craft a colliding asset that bypasses the integrity check.
    """

    def __init__(self, cooking: Path):
        self.cooking = cooking
        self.path = cooking / STATE_FILE_NAME
        self.data: dict = {"version": 1, "active": {}}
        if self.path.exists():
            try:
                self.data = json.loads(self.path.read_text(encoding="utf-8"))
            except (OSError, ValueError) as e:
                print(f"  [warn] corrupt state file: {e}", file=__import__('sys').stderr)

    def save(self) -> None:
        """Write the state file atomically and durably.

        The old tmp+replace had no fsync, so a crash could land the rename
        with an empty file — losing the record of every live override while
        the overrides themselves stayed on disk.
        """
        atomic_write_text(
            self.path, json.dumps(self.data, indent=2, sort_keys=True)
        )

    @property
    def active(self) -> dict:
        return self.data.setdefault("active", {})

    @property
    def enabled_mods(self) -> list[str]:
        return self.data.setdefault("enabled_mods", [])

    def set_enabled_mods(self, ids: list[str]) -> None:
        self.data["enabled_mods"] = sorted(set(ids))


class Mod:
    def __init__(self, root: Path):
        self.root = root
        manifest = root / "manifest.toml"
        if not manifest.exists():
            raise FileNotFoundError(f"missing manifest: {manifest}")
        tbl = parse_toml(manifest)
        m = tbl.get("mod", {})
        self.id: str = m.get("id") or root.name
        self.name: str = m.get("name", self.id)
        self.version: str = m.get("version", "0.0.0")
        self.author: str = m.get("author", "")
        raw_enabled = m.get("enabled", True)
        self.enabled: bool = (
            raw_enabled if isinstance(raw_enabled, bool)
            else str(raw_enabled).lower() in ("1", "true", "yes", "on")
        )
        self.experimental: bool = bool(m.get("experimental", False))
        self.assets_dir = root / "assets"
        self.content_blocks: list[dict] = list(tbl.get("content", []) or [])

    def files(self) -> list[tuple[Path, str]]:
        out: list[tuple[Path, str]] = []
        if not self.assets_dir.is_dir():
            return out
        for f in self.assets_dir.rglob("*"):
            if not f.is_file():
                continue
            decoded = f.relative_to(self.assets_dir).as_posix()
            if is_skippable_asset(decoded):
                continue
            out.append((f, decoded))
        return out


def load_asset_map(_repo: Path | None = None) -> dict[str, str]:
    """decoded_path (forward-slash) -> encoded_path (with backslashes)."""
    p = ASSET_MAP_JSON
    raw = json.loads(p.read_text(encoding="utf-8"))
    out: dict[str, str] = {}
    for enc, dec in raw.items():
        dec_norm = dec.replace("\\", "/")
        if dec_norm in out:
            print(f"  [warn] duplicate decoded path {dec_norm!r} "
                  f"(old={out[dec_norm]!r}, new={enc!r})", file=sys.stderr)
        out[dec_norm] = enc
    return out


# Language-code translation between decoded and on-disk form. The cipher
# operates per character, so we cache only the codes we know about. New
# locale codes Ravenswatch ships can be added here.
LANG_DECODED_TO_ENCODED = {
    "EN": "MU", "JA": "EW", "KO": "IO", "RU": "LJ", "ES": "MF",
    "DE": "NM", "PL": "TG", "FR": "VL", "IT": "XQ", "RO": "LO",
    "PT-BR": "TQ-BL", "ZH-S": "YA-F", "ZH-T": "YA-Q",
    "RAW": "LWR",   # in-game pseudo-locale (`*marked text` for QA)
}

# Language suffixes doctor and other tools recognise as special-cased
# paths that bypass the normal asset-map lookup.
_LANG_SUFFIXES = tuple(
    f".Lang{c}" for c in sorted(LANG_DECODED_TO_ENCODED)
)


def is_skippable_asset(decoded: str) -> bool:
    """Return True for asset paths that are not raw cooked files and
    should be skipped by the applier / doctor / etc.

    ``_pending_*`` directories are SDK content-emission staging output
    consumed by the merge step — they are not raw cooked assets so the
    applier must not try to install them under ``_Cooking/`` directly.
    """
    top = decoded.split("/", 1)[0]
    if top.startswith("_pending_"):
        return True
    # Cook sidecars (orientation transforms) travel next to a custom mesh but
    # are consumed by the cooker, not installed into the game.
    if decoded.endswith(".rsmmcook"):
        return True
    return False


#: FMOD sound banks live under `Audio/` as opaque containers. Unlike every
#: other cooked asset they are NOT listed in `UsedRscList.ot`, so
#: `asset_map.json` (which is derived from that list) has no entry for them
#: and a `dec2enc` lookup always misses — see `resolve_audio_bank`.
AUDIO_DIR_DECODED = "Audio"
_AUDIO_BANK_RE = re.compile(r"^Audio/[^/\\]+\.bank$")


def resolve_audio_bank(decoded: str) -> str | None:
    """Resolve `Audio/<Name>.bank` to its `_Cooking` encoded path.

    Sound banks are the one asset family the engine loads by *path* rather
    than through the `UsedRscList.ot` manifest, so they never appear in
    `asset_map.json` and cannot be resolved by lookup. Their encoding is
    also the simple case — the `!` directory-collapse rule that complicates
    normal cooked paths does not apply at this depth, so the plaintext path
    ciphers straight through (`Audio/Music.bank` -> `Wwtdr\\Hwvdb.agzm`).

    Returns None for anything that is not a bank, so callers can keep
    falling through to their existing resolution chain.
    """
    if not _AUDIO_BANK_RE.match(decoded.replace("\\", "/")):
        return None
    return cipher.encode(decoded.replace("/", "\\"))


#: Encoded suffix marking a localization sibling: `<base-enc>.Ggzy<enc-lang>`.
#: `Ggzy` is `cipher.encode("Lang")`.
_LANG_ENC_SUFFIXES = tuple(
    f".Ggzy{c}" for c in sorted(LANG_DECODED_TO_ENCODED.values())
)


def is_vanilla_encoded(enc: str) -> bool:
    """True if `enc` names a file the game itself ships.

    Used to distinguish "this mod adds a brand-new asset" from "the vanilla
    file that belongs here has gone missing" — see `apply_one`. Localization
    siblings (`<base>.Ggzy<lang>`) are vanilla too even though only their
    BASE appears in `asset_map`, which is derived from `UsedRscList.ot`.
    Getting that second case wrong is not academic: in the 2026-07-11 data
    loss, 13 of the 14 files lost per text bank were lang siblings.
    """
    from rsmm.engine.asset_map import encoded_to_decoded

    known = encoded_to_decoded()
    if enc in known:
        return True
    for suffix in _LANG_ENC_SUFFIXES:
        if enc.endswith(suffix):
            return enc[: -len(suffix)] in known
    return False


def resolve_special(decoded: str, dec2enc: dict[str, str]) -> str | None:
    """Resolve decoded paths that aren't directly in asset_map.

    Handled cases:

    * `_root/<rel>` — top-level files in the install dir (e.g.
      `_root/DarkTalesResources/ApplicationSettings.ot`). Rewritten as
      an internal `_root\\<rel>` key, NOT a cooked-path encoding.
    * `Audio/<Name>.bank` — FMOD sound banks, absent from `UsedRscList.ot`
      and therefore from `asset_map` (see `resolve_audio_bank`).
    * `Text/<bank>~GAM.xls.LocalText.gen.Lang<XX>` — localization
      sibling whose base is in `asset_map` but the .Lang<XX> sibling
      isn't. Decoded -> base's encoded path + `.Ggzy<encoded-lang>`.
    """
    if decoded.startswith("_root/"):
        return ROOT_PREFIX + decoded[len("_root/"):].replace("/", "\\")
    bank = resolve_audio_bank(decoded)
    if bank:
        return bank
    m = re.match(r"^(.*\.LocalText\.gen)\.Lang(.+)$", decoded)
    if not m:
        return None
    base_dec, lang = m.group(1), m.group(2).upper()
    enc_lang = LANG_DECODED_TO_ENCODED.get(lang)
    if not enc_lang:
        return None
    base_enc = dec2enc.get(base_dec)
    if not base_enc:
        return None
    return base_enc + f".Ggzy{enc_lang}"


#: Line-lead tokens for the apply/restore log. Hoisted because Python 3.11
#: forbids backslash escapes inside f-string expressions, and because every
#: caller must use the same glyph for the same kind of event.
_ADD = "+"
_DEL = "-"
_WARN_TOK = "!"

#: Module-level style. Colour is auto-disabled when stdout is not a TTY, so
#: piping `rsmm apply` into a file still yields clean text.
_ST = _term.Style()

ROOT_PREFIX = "_root\\"

# UsedRscList.ot is the engine's master manifest: a newline list of
# cipher-encoded cooked paths. The engine only loads a resource if its
# encoded path appears here, so a brand-new asset (custom item / enemy /
# texture not present in the vanilla tree) must be *registered* by
# appending its encoded line, or it is silently never loaded.
# `asset_map.json` is itself derived from this file (see find_iyg.py).
USEDRSCLIST_REL = Path("DarkTalesResources/UsedRscList.ot")


def synthesize_encoded(decoded: str, dec2enc: dict[str, str]) -> str | None:
    """Derive the `_Cooking` encoded path for a *new* decoded asset that
    isn't in `asset_map` yet.

    The engine's path obfuscation collapses directory separators past a
    namespace-dependent depth into `!` inside the filename (see
    `cipher.py` and `asset_map.json`). That collapse rule has
    per-namespace exceptions, so rather than re-deriving it we clone the
    encoded *prefix* of an existing sibling (any asset already living in
    the same decoded parent directory) and re-encode only the final
    filename component. Returns None when no sibling exists to anchor the
    prefix (a genuinely new top-level directory), in which case the
    caller should fall back to warn-and-skip.
    """
    decoded = decoded.replace("\\", "/")
    if "/" not in decoded:
        # Top-level resource (e.g. `samples`): no collapse, encode whole.
        return cipher.encode(decoded)
    parent, _, fname = decoded.rpartition("/")
    for dec, enc in dec2enc.items():
        dec = dec.replace("\\", "/")
        if "/" not in dec:
            continue
        if dec.rsplit("/", 1)[0] != parent:
            continue
        # The sibling's final component begins after its last separator,
        # which may be a real `\` directory join or a collapsed `!`.
        cut = max(enc.rfind("\\"), enc.rfind("!"))
        if cut == -1:
            continue
        return enc[: cut + 1] + cipher.encode(fname)
    return None


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
        # Line 1 (type root) carries no id; lines 2/3 carry the encoded id.
        return [line.replace(enc_old, enc_new) for line in triple]
    return None


def encoded_to_dest(encoded: str, cooking: Path, game_dir: Path) -> Path:
    """Translate an internal encoded key into an on-disk path.

    Two forms:
      `<encoded\\path>`      -> <cooking>/<path>            (cooked asset)
      `_root\\<rel\\path>`    -> <game_dir>/<rel>            (top-level file)
    """
    # Defense in depth: the asset map ships with rsmm and should never contain
    # ".." segments, but a corrupted or maliciously crafted map could otherwise
    # let mod overrides escape the game directory. Reject any traversal up
    # front rather than at the copy site.
    if encoded.startswith(ROOT_PREFIX):
        rel = encoded[len(ROOT_PREFIX):]
        parts = rel.split("\\")
        if any(p in ("..", "") for p in parts):
            raise ValueError(f"refusing path with traversal segments: {encoded!r}")
        return game_dir / Path(*parts)
    parts = encoded.split("\\")
    if any(p == ".." for p in parts):
        raise ValueError(f"refusing path with traversal segments: {encoded!r}")
    return cooking / Path(*parts)


def discover_mods(repo: Path) -> list[Mod]:
    mods_dir = MODS_DIR
    if not mods_dir.is_dir():
        return []
    mods: list[Mod] = []
    for entry in sorted(mods_dir.iterdir()):
        if not entry.is_dir():
            continue
        # Allow `_merged` (rsmm's own composed output); skip every other
        # underscore/dot-prefixed directory.
        if entry.name != "_merged" and (
            entry.name.startswith("_") or entry.name.startswith(".")
        ):
            continue
        if not (entry / "manifest.toml").exists():
            continue
        try:
            mods.append(Mod(entry))
        except tomllib.TOMLDecodeError as e:
            print(f"  [warn] skipping mod '{entry.name}': manifest.toml is not "
                  f"valid TOML ({e}).\n"
                  f"         Fix {entry / 'manifest.toml'} "
                  f"(check it with: rsmm lint {entry.name})", file=sys.stderr)
        except (OSError, ValueError) as e:
            print(f"  [warn] skipping mod '{entry.name}': {e}", file=sys.stderr)
    return mods


def emit_content_blocks(mods: list[Mod]) -> int:
    """Materialize every mod's [[content]] block declarations under its
    own `assets/` tree. Idempotent — re-running just refreshes the
    emitted marker JSON files.

    Returns the number of declarations processed. Errors per-mod are
    logged + skipped; the applier still proceeds with the remaining
    mods so one bad content def doesn't break a batch.
    """
    try:
        from rsmm.sdk.content import ContentError, ContentRegistry, SchemaNotMined
    except ImportError as e:
        print(f"  [content] sdk import failed: {e}", file=sys.stderr)
        return 0
    total = 0
    for m in mods:
        if not m.enabled or not m.content_blocks:
            continue
        # Honor the manifest's `experimental = true` so non-confirmed content
        # kinds the author opted into actually emit (lint already respects it).
        cr = ContentRegistry(mod_id=m.id, experimental=m.experimental)
        for block in m.content_blocks:
            kind = block.get("kind")
            cid = block.get("id")
            if not kind or not cid:
                print(f"  [content] {m.id}: skip block missing kind/id: {block}",
                      file=sys.stderr)
                continue
            try:
                cr.register(kind, id=cid,
                            **{k: v for k, v in block.items()
                               if k not in ("kind", "id")})
            except ContentError as e:
                print(f"  [content] {m.id}: {e}", file=sys.stderr)
        out_dir = m.assets_dir
        # Track what content-emit produced so a later emit (e.g. after the
        # author renames/removes a content def) can delete the files it wrote
        # last time, instead of leaving ghost assets behind. The marker lives
        # in the mod root, outside assets/, so it isn't itself installed.
        marker = m.root / ".rsmm_emitted.json"
        try:
            prev = json.loads(marker.read_text(encoding="utf-8")) if marker.exists() else []
        except (OSError, ValueError):
            prev = []
        try:
            written = cr.emit(out_dir)
            total += len(written)
            new_rel = sorted(
                str(p.relative_to(out_dir).as_posix()) for p in written
                if out_dir in p.parents
            )
            for rel in set(prev) - set(new_rel):
                stale = out_dir / Path(rel)
                if stale.is_file():
                    stale.unlink()
                    print(f"  [content] {m.id}: removed stale {rel}")
            try:
                marker.write_text(json.dumps(new_rel, indent=2), encoding="utf-8")
            except OSError:
                pass
            if written:
                print(f"  [content] {m.id}: emitted {len(written)} file(s)")
        except SchemaNotMined as e:
            print(f"  [content] {m.id}: schema not mined yet: {e}",
                  file=sys.stderr)
        except (OSError, ValueError) as e:
            print(f"  [content] {m.id}: emit failed: {e}", file=sys.stderr)
    return total


def apply_health_quarantine(mods: list[Mod], cooking: Path) -> list[Mod]:
    """Disable mods the health system has quarantined (>= crash threshold).

    Idempotent: the on-disk manifest stays untouched. We flip `enabled`
    in-memory only so the applier skips them. `rsmm safe-mode --reset
    <id>` re-enables a mod after the user fixes it.
    """
    try:
        from rsmm.sdk.health import Health
        quarantined = Health(cooking).disabled_mods()
    except ImportError as e:
        print(f"  [health] skipped: {e}", file=sys.stderr)
        return mods
    if not quarantined:
        return mods
    out: list[Mod] = []
    for m in mods:
        if m.enabled and m.id in quarantined:
            print(f"  [health] quarantined {m.id} (crash threshold hit); "
                  f"`rsmm safe-mode --reset {m.id}` to re-enable")
            m.enabled = False
        out.append(m)
    return out


_TEXT_BANK_RE = re.compile(r"\.LocalText\.gen(\.Lang.+)?$")


def is_text_bank(decoded: str) -> bool:
    """True for a `~GAM.xls.LocalText.gen` base or a `.Lang<XX>` sibling — the
    index-aligned key/value text files that multiple item mods append to."""
    return bool(_TEXT_BANK_RE.search(decoded))


# Staging dir for merged text banks (one writer per apply; src must outlive the
# plan→copy step). Lives under the mods dir so it's cleaned by `restore --all`.
_TEXT_MERGE_DIR_NAME = ".rsmm_text_merge"


def _merge_text_bank(enc: str, srcs: list[Path], vanilla: Path) -> Path | None:
    """Merge several mods' versions of ONE text-bank file into vanilla + the
    union of each mod's appended tail, preserving index alignment.

    Each mod's file is vanilla + that mod's appended entries (``append_bank_keys``
    appends the same count to the base keys file and every language sibling), so
    concatenating each mod's tail — in a fixed mod order applied identically to
    the base and every sibling — keeps keys and values aligned. Returns the path
    to the written merged file, or ``None`` if it can't be parsed as a bank.
    """
    from rsmm.engine import text_patches as TP
    try:
        van = TP.parse_text_file(vanilla)
    except Exception:  # noqa: BLE001 — not a parseable bank; skip merge
        return None
    n = len(van.entries)
    merged = list(van.entries)
    for src in srcs:
        try:
            tf = TP.parse_text_file(src)
        except Exception:  # noqa: BLE001 — not a parseable bank; skip merge
            return None
        if len(tf.entries) >= n:
            merged.extend(tf.entries[n:])
    out_tf = TP.TextFile(path=vanilla, header=van.header, entries=merged,
                         footer=van.footer)
    out_dir = MODS_DIR / _TEXT_MERGE_DIR_NAME
    out_dir.mkdir(parents=True, exist_ok=True)
    # Encode the enc path into a flat, unique filename.
    flat = enc.replace("\\", "__").replace("/", "__")
    out_path = out_dir / flat
    out_path.write_bytes(TP.write_text_file(out_tf))
    return out_path


def plan_apply(mods: list[Mod],
               dec2enc: dict[str, str],
               cooking: Path,
               game_dir: Path,
               state: State,
               dry_run: bool,
               ) -> tuple[list[tuple[str, Path, Path, str]], list[str], dict[str, str]]:
    """Compute (additions, removals, registrations) given current state and
    on-disk mods.

    additions    : list of (encoded_rel, src_file, dest_in_cooking, mod_id)
    removals     : list of encoded_rel to restore from .bak (no longer overridden)
    registrations: {encoded_cooked_path: decoded_path} for assets not in the
                   vanilla asset_map; each needs a 3-line UsedRscList.ot record
                   (built later from the live manifest) so the engine loads it
    """
    # Collect every (src, mod_id) that targets each encoded path. Most targets
    # have one writer, but several item mods legitimately append to the SAME
    # shared text bank (e.g. Text/Magical_Objects~GAM.xls.LocalText) — those must
    # be MERGED, not won by the last mod (which silently drops the others' item
    # names). Non-text conflicts keep the prior last-writer-wins behaviour.
    collected: dict[str, list[tuple[Path, str, str]]] = {}  # enc -> [(src, mod, decoded)]
    registrations: dict[str, str] = {}        # encoded -> decoded
    for m in mods:
        if not m.enabled:
            continue
        for src, decoded in m.files():
            enc = dec2enc.get(decoded) or resolve_special(decoded, dec2enc)
            if not enc:
                # Not a known vanilla asset — treat as a brand-new resource.
                # Synthesize its encoded path and flag it for UsedRscList
                # registration so the engine will actually load it.
                enc = synthesize_encoded(decoded, dec2enc)
                if not enc:
                    print(f"  [warn] {m.id}: no asset_map entry for '{decoded}' "
                          f"and no sibling to anchor a new path; skipping",
                          file=sys.stderr)
                    continue
                registrations[enc] = decoded
                print(f"  [new] {m.id}: registering new asset '{decoded}'")
            collected.setdefault(enc, []).append((src, m.id, decoded))

    wanted: dict[str, tuple[Path, str]] = {}  # encoded -> (src, mod_id)
    for enc, writers in collected.items():
        if len(writers) == 1:
            src, mod_id, _ = writers[0]
            wanted[enc] = (src, mod_id)
            continue
        decoded = writers[0][2]
        if is_text_bank(decoded):
            # Merge all mods' appends into one bank so every item name survives.
            ordered = sorted(writers, key=lambda w: w[1])  # deterministic by mod id
            dest = encoded_to_dest(enc, cooking, game_dir)
            vanilla = dest.parent / (dest.name + BACKUP_SUFFIX)
            if not vanilla.exists():
                vanilla = dest if dest.exists() else None
            merged = _merge_text_bank(enc, [w[0] for w in ordered], vanilla) \
                if vanilla else None
            if merged is not None:
                ids = ", ".join(w[1] for w in ordered)
                print(f"  [merge] text bank '{decoded}' from {len(ordered)} "
                      f"mods ({ids})")
                wanted[enc] = (merged, ordered[-1][1])
                continue
            print(f"  [warn] text bank '{decoded}': no vanilla to merge against; "
                  f"keeping {ordered[-1][1]}", file=sys.stderr)
            wanted[enc] = (ordered[-1][0], ordered[-1][1])
        else:
            last = writers[-1]
            others = ", ".join(w[1] for w in writers[:-1])
            print(f"  [warn] conflict on '{decoded}' (mods: {others} vs "
                  f"{last[1]}); keeping later mod {last[1]}", file=sys.stderr)
            wanted[enc] = (last[0], last[1])

    active: dict[str, dict] = state.active
    additions: list[tuple[str, Path, Path, str]] = []
    removals: list[str] = []

    for enc, (src, mod_id) in wanted.items():
        dest = encoded_to_dest(enc, cooking, game_dir)
        cur = active.get(enc)
        # Auto-cook source-format inputs (.gltf/.dds/etc) into cached cooked
        # files. Pre-cooked inputs are returned unchanged. NotReversedError
        # surfaces as a skip + warning so the rest of the apply still runs.
        if cook_cache.is_source(src):
            # Custom meshes cook by swapping into the game's *original*
            # cooked file. Prefer the backup (pristine) over a dest that a
            # prior apply may already have overwritten.
            bak = dest.parent / (dest.name + BACKUP_SUFFIX)
            template = bak if bak.exists() else (dest if dest.exists() else None)
            try:
                src = cook_cache.maybe_cook(src, template=template)
            except cooked_schemas.NotReversedError as e:
                print(f"  [warn] {mod_id}: skipping {src.name} ({e})",
                      file=sys.stderr)
                continue
        src_sha = sha256(src)
        # Legacy `src_sha1` entries never match — they're treated as
        # "needs re-apply" which is a no-op shutil.copy2 plus a state
        # rewrite into the sha256 field. See the State docstring.
        #
        # Stale-install guard: don't trust the state file alone. The
        # installed copy can drift from what state says is applied (Steam
        # "verify integrity" restores vanilla bytes, a game update rewrites
        # the file, a crashed apply left old content behind) — so the skip
        # requires the *installed* bytes to actually hash-match the mod
        # source, not just the state entry.
        if (cur and cur.get("src_sha256") == src_sha and dest.exists()
                and sha256(dest) == src_sha):
            # already applied + unchanged on disk
            continue
        additions.append((enc, src, dest, mod_id))

    for enc in list(active.keys()):
        if enc not in wanted:
            removals.append(enc)

    return additions, removals, registrations


_DANGEROUS_ROOT_EXTS = frozenset({
    ".exe", ".dll", ".sys", ".drv", ".scr", ".cpl",
    ".vbs", ".vbe", ".ps1", ".bat", ".cmd", ".sh",
})


class VanillaMissing(RuntimeError):
    """A vanilla file that should be under a mod override is not on disk.

    Applying over it would record the override as an *added* file, and a later
    `disable`/`restore` deletes added files — destroying the vanilla asset.
    """


def apply_one(enc: str, src: Path, dest: Path, mod_id: str,
              state: State, dry_run: bool, force: bool = False,
              journal: Journal | None = None) -> None:
    if enc.startswith(ROOT_PREFIX):
        rel = dest.suffix.lower()
        if rel in _DANGEROUS_ROOT_EXTS:
            print(f"  [WARN] {mod_id} overwrites {dest.name} in game root "
                  f"(potentially dangerous)", file=sys.stderr)
    cur = state.active.get(enc)
    bak = dest.with_suffix(dest.suffix + BACKUP_SUFFIX) if dest.exists() else None
    if dest.exists():
        bak = dest.parent / (dest.name + BACKUP_SUFFIX)
        if not bak.exists():
            orig_sha = sha256(dest)
            print(f"  {_ST.ok(_ADD)} backup {_ST.dim(dest.name)}")
            if not dry_run:
                # Atomic: a torn backup is worse than no backup — restore
                # would put truncated bytes back over a working install.
                atomic_copy(dest, bak)
        else:
            orig_sha = (cur or {}).get("orig_sha256") or sha256(bak)
    elif is_vanilla_encoded(enc) and not force:
        # The game ships this file, so it should be sitting here. It isn't —
        # which means the vanilla copy (and its .rsmm.bak) were wiped, most
        # often by a game update that also wiped .rsmm_state.json.
        #
        # Applying anyway would record the override with orig_sha256="" i.e.
        # "this file was ADDED by a mod", and the next disable/restore deletes
        # added files. That is exactly the 2026-07-11 data loss: vanilla
        # Text/Tutorials~GAM and Hero_Aladdin_Common were destroyed and the
        # game showed "Default sentence" for every string. Fail closed.
        raise VanillaMissing(
            f"{mod_id}: refusing to apply over '{enc}' — the game ships this "
            f"file but it is not at {dest}, and no backup exists. Applying "
            "would record it as mod-added, so disabling would DELETE the "
            "vanilla asset.\n"
            "  Likely cause: a game update wiped the file and the rsmm state.\n"
            "  Fix: verify the game files via Steam (Properties > Installed "
            "Files > Verify integrity), then re-run `rsmm apply` and "
            "`rsmm install-loader`.\n"
            "  Override with --force only if you are certain this asset is "
            "genuinely new."
        )
    else:
        # Genuinely new asset (custom item, enemy, texture) — nothing here to
        # back up, and dropping it on restore is the correct behaviour.
        orig_sha = ""
        print(f"  {_ST.ok(_ADD)} new file {_ST.dim(f'(no original) {dest}')}")

    print(f"  {_ST.ok(_ADD)} apply  {enc}  {_ST.dim(f'<- {mod_id}/{src.name}')}")
    src_sha = sha256(src)
    if not dry_run:
        # Journal BEFORE the write: if we die between here and the state
        # save at the end of the run, the next apply/restore still knows
        # this file was touched. `orig_sha` is empty exactly when nothing
        # was backed up, i.e. the file is mod-added.
        if journal is not None:
            journal.record(enc, mod_id, added=not orig_sha)
        dest.parent.mkdir(parents=True, exist_ok=True)
        atomic_copy(src, dest)
        # Verify what actually landed. A short write (full disk, flaky
        # drive) otherwise gets recorded as a successful apply and the
        # engine loads the truncated asset.
        got = sha256(dest)
        if got != src_sha:
            raise OSError(
                f"{mod_id}: {enc} did not land intact (expected "
                f"{src_sha[:12]}, got {got[:12]}). The install may be out of "
                f"space or the drive is failing; run `rsmm restore --all`."
            )
    state.active[enc] = {
        "mod": mod_id,
        "src_sha256": src_sha,
        "orig_sha256": orig_sha,
    }


def restore_one(enc: str, cooking: Path, game_dir: Path,
                state: State, dry_run: bool) -> bool:
    """Restore one file from backup.

    Returns True if the file was fully handled (restored / dropped / skipped),
    False if the operation failed and the state entry should be kept for retry.
    """
    dest = encoded_to_dest(enc, cooking, game_dir)
    bak = dest.parent / (dest.name + BACKUP_SUFFIX)
    entry = state.active.get(enc) or {}
    # Accept the legacy `orig_sha1` field too; pre-0.1.12 state files
    # may still be on disk with that key. We don't compare against it
    # — it's just a "the backup was tracked once" signal.
    orig_sha = entry.get("orig_sha256") or entry.get("orig_sha1", "")

    if bak.exists():
        print(f"  {_ST.accent(_DEL)} restore {enc}")
        if not dry_run:
            # Two-phase: copy then remove — a crash mid-copy preserves the
            # backup, and the copy itself is atomic so `dest` is never a
            # half-written mixture of override and original.
            try:
                atomic_copy(bak, dest)
                bak.unlink()
            except OSError as e:
                print(f"  [ERROR] failed to restore {enc}: {e}",
                      file=sys.stderr)
                return False
            if not dest.exists():
                print(f"  [ERROR] {enc}: restore appeared to succeed but "
                      f"destination is missing", file=sys.stderr)
                return False
        state.active.pop(enc, None)
        return True

    # No backup on disk
    if orig_sha:
        # An original game file was backed up but the backup is gone.
        # NEVER delete dest — that would destroy the original game file.
        if dest.exists():
            print(f"  [WARN] {enc}: backup missing (orig_sha1 recorded); "
                  f"keeping destination", file=sys.stderr)
        else:
            print(f"  {_ST.dim(_DEL)} skip    {enc}  {_ST.dim('(no backup, no destination)')}")
            state.active.pop(enc, None)
        return True

    # No backup and no recorded original normally means "a mod added this
    # file", and dropping it is right. But if the GAME ships this path, that
    # inference is wrong however the state got into this shape — a wiped
    # state file, a stale entry, a `--force`d apply — and acting on it deletes
    # a vanilla asset. This is the last line of defence for the 2026-07-11
    # loss, and the one that actually holds: the apply-side guard alone still
    # let the file be dropped here, because this path fires even when there
    # is no state entry at all.
    if is_vanilla_encoded(enc):
        if dest.exists():
            print(f"  {_ST.warn(_WARN_TOK)} keep    {enc}  "
                  + _ST.dim("(game ships this file; not dropping it)"),
                  file=sys.stderr)
        state.active.pop(enc, None)
        return True

    # No backup, no orig_sha1 → mod added this file. Safe to remove.
    print(f"  {_ST.accent(_DEL)} drop    {enc}  {_ST.dim('(no backup -> added file removed)')}")
    if not dry_run and dest.exists():
        try:
            dest.unlink()
        except OSError as e:
            print(f"  [ERROR] failed to drop {enc}: {e}", file=sys.stderr)
            return False
    state.active.pop(enc, None)
    return True


DEACTIVATION_SCRIPT_NAME = "on_disable.py"
DEACTIVATION_TIMEOUT_SEC = 30


def _run_deactivation_hooks(mods: list[Mod],
                            state: State,
                            game_dir: Path,
                            cooking: Path,
                            dry_run: bool,
                            assume_yes: bool = False) -> tuple[list[str], list[str]]:
    """Fire on_disable.py for each mod that flipped enabled -> disabled.

    The mod's on_disable.py receives three env vars:
      RSMM_GAME_DIR  — Ravenswatch install directory
      RSMM_COOKING   — <game>/DarkTalesResources/_Cooking
      RSMM_MOD_DIR   — the mod's own root in mods/<id>/

    Used for cleanup that the loader DLL can't do at apply time:
      * resetting game-settings keys the mod wrote at runtime
        (e.g. ExampleSeedPin clears [Debug] Forced seed from
        _Save/GameSettings.ini),
      * deleting profile flags / cache entries the mod created.

    Security: on_disable.py runs as the current user with no sandbox.
    A malicious mod can do anything the user can do — read files,
    network out, execute binaries. We surface every hook by id BEFORE
    running and require explicit consent (`--yes` or an interactive
    "yes" reply). Set ``RSMM_NONINTERACTIVE=1`` to force `--yes` as
    the only acceptable trigger (CI, scripts).

    Returns (ran, missing) — mod ids whose hook fired vs flipped mods
    with no on_disable.py present (silent; not an error).
    """
    prev_enabled = set(state.enabled_mods)
    if not prev_enabled:
        return [], []

    cur_by_id = {m.id: m for m in mods}
    cur_enabled = {m.id for m in mods if m.enabled}
    flipped = sorted(prev_enabled - cur_enabled)

    # Compute the list of hooks that WOULD run so the user (or the
    # caller) can audit it before any code executes.
    pending: list[str] = []
    for mod_id in flipped:
        m = cur_by_id.get(mod_id)
        if m is not None and (m.root / DEACTIVATION_SCRIPT_NAME).is_file():
            pending.append(mod_id)

    ran: list[str] = []
    missing: list[str] = []

    if pending and not dry_run:
        print(
            "WARNING: the following deactivated mods include an "
            "on_disable.py hook that will run as your user with no sandbox:",
            file=sys.stderr,
        )
        for mod_id in pending:
            script = cur_by_id[mod_id].root / DEACTIVATION_SCRIPT_NAME
            print(f"  - {mod_id}  ({script})", file=sys.stderr)
        noninteractive = os.environ.get("RSMM_NONINTERACTIVE", "").strip() not in ("", "0")
        if assume_yes:
            print("--yes given; running hooks.", file=sys.stderr)
        elif noninteractive:
            print(
                "RSMM_NONINTERACTIVE is set and --yes was not passed; "
                "skipping all on_disable.py hooks.", file=sys.stderr,
            )
            return [], list(flipped)
        elif not sys.stdin.isatty():
            print(
                "stdin is not a TTY and --yes was not passed; "
                "skipping all on_disable.py hooks.", file=sys.stderr,
            )
            return [], list(flipped)
        else:
            try:
                reply = input("Run these hooks? [y/N] ").strip().lower()
            except EOFError:
                reply = ""
            if reply not in ("y", "yes"):
                print("Skipping on_disable.py hooks.", file=sys.stderr)
                return [], list(flipped)

    for mod_id in flipped:
        m = cur_by_id.get(mod_id)
        if m is None:
            missing.append(mod_id)
            continue
        script = m.root / DEACTIVATION_SCRIPT_NAME
        if not script.is_file():
            missing.append(mod_id)
            continue
        print(f"  ~ on_disable {mod_id}")
        if dry_run:
            ran.append(mod_id)
            continue
        env = os.environ.copy()
        env["RSMM_GAME_DIR"] = str(game_dir)
        env["RSMM_COOKING"] = str(cooking)
        env["RSMM_MOD_DIR"] = str(m.root)
        try:
            r = subprocess.run(
                [sys.executable, str(script)],
                env=env, cwd=str(m.root),
                timeout=DEACTIVATION_TIMEOUT_SEC,
                capture_output=True, text=True,
            )
            if r.returncode != 0:
                print(f"    on_disable {mod_id} exited {r.returncode}",
                      file=sys.stderr)
                if r.stdout:
                    print(r.stdout, file=sys.stderr)
                if r.stderr:
                    print(r.stderr, file=sys.stderr)
            else:
                if r.stdout.strip():
                    for ln in r.stdout.splitlines():
                        print(f"    {ln}")
            ran.append(mod_id)
        except subprocess.TimeoutExpired:
            print(f"    on_disable {mod_id} TIMEOUT after "
                  f"{DEACTIVATION_TIMEOUT_SEC}s", file=sys.stderr)
        except (OSError, ValueError) as e:
            print(f"    on_disable {mod_id} failed: {e}", file=sys.stderr)
    return ran, missing


_RUNTIME_EXTENSIONS = {".lua", ".json", ".toml", ".txt"}
_RUNTIME_BLOCKLIST  = {"manifest.toml", "config_schema.toml"}


def _sync_one_file(src: Path, dst: Path, dry_run: bool) -> bool:
    """Mtime-aware copy. Returns True if a write happened."""
    try:
        src_mtime = src.stat().st_mtime
        dst_mtime = dst.stat().st_mtime if dst.exists() else 0
        if src_mtime <= dst_mtime:
            return False
        if not dry_run:
            dst.parent.mkdir(parents=True, exist_ok=True)
            dst.write_bytes(src.read_bytes())
        return True
    except OSError:
        return False


def _sync_mod_manifests(mods: list[Mod], game_dir: Path, dry_run: bool) -> int:
    """Copy each mod's runtime sidecar files into the game's mods/ dir.

    Always copied: manifest.toml + init.lua (when enabled).
    Also copied: any top-level `.lua`, `.json`, `.toml`, `.txt` file that
    is not the manifest or config schema — lets Lua mods ship pointer
    tables, data caches, or auxiliary scripts and read them via
    `R.mod_dir()` at runtime.

    The game engine reads manifests to determine which mods are enabled.
    For Lua code mods, init.lua is removed when disabled to prevent
    execution. Auxiliary files are kept on disable (cheap, harmless).
    Returns the number of files synced.
    """
    game_mods = game_dir / "mods"
    game_mods.mkdir(exist_ok=True)
    synced = 0

    if not mods:
        return synced
    for mod in mods:
        mod_dir = mod.root
        manifest = mod_dir / "manifest.toml"
        if not manifest.is_file():
            continue

        enabled = mod.enabled
        dst_dir = game_mods / mod_dir.name
        dst_dir.mkdir(exist_ok=True)

        # Sync manifest (always).
        if _sync_one_file(manifest, dst_dir / "manifest.toml", dry_run):
            synced += 1

        # Sync or remove init.lua based on enabled flag.
        src_lua = mod_dir / "init.lua"
        dst_lua = dst_dir / "init.lua"
        if enabled and src_lua.is_file():
            if _sync_one_file(src_lua, dst_lua, dry_run):
                synced += 1
        elif not enabled and dst_lua.exists():
            if not dry_run:
                dst_lua.unlink()
            synced += 1

        # Sync top-level auxiliary files so mods can ship data alongside
        # init.lua (pointer tables, embedded configs, secondary scripts).
        # Only top-level — never recurse into assets/, _root/, lang/, etc.
        for src in mod_dir.iterdir():
            if not src.is_file():
                continue
            if src.suffix.lower() not in _RUNTIME_EXTENSIONS:
                continue
            if src.name in _RUNTIME_BLOCKLIST or src.name == "init.lua":
                continue
            if _sync_one_file(src, dst_dir / src.name, dry_run):
                synced += 1

    return synced


def clear_runtime_mods(game_dir: Path, dry_run: bool = False) -> int:
    """Remove the game-side `mods/` runtime sidecars so a vanilla launch
    starts without any mod manifests or Lua entrypoints loaded.

    Returns 1 on success (or nothing to clear), 0 on filesystem error.
    """
    game_mods = game_dir / "mods"
    if not game_mods.exists():
        return 1
    print(f"Clearing runtime mods dir: {game_mods}")
    if dry_run:
        return 1
    try:
        shutil.rmtree(game_mods)
    except OSError as e:
        print(f"  [warn] failed to clear {game_mods}: {e}", file=sys.stderr)
        return 0
    game_mods.mkdir(parents=True, exist_ok=True)
    return 1


def clear_loader_artifacts(game_dir: Path, dry_run: bool = False) -> int:
    """Best-effort removal of RSMM loader runtime files for vanilla mode.

    Returns 1 on success, 0 on hard filesystem failure.
    """
    loader_dll = game_dir / "winhttp.dll"
    real_dll = game_dir / "winhttp_real.dll"
    asset_map = game_dir / "asset_map.json"
    rsmm_dir = game_dir / "rsmm"

    try:
        if real_dll.exists():
            print(f"Restoring stock DLL: {real_dll} -> {loader_dll}")
            if not dry_run:
                if loader_dll.exists():
                    loader_dll.unlink()
                shutil.move(str(real_dll), str(loader_dll))
        elif loader_dll.exists():
            print(f"Removing loader DLL: {loader_dll}")
            if not dry_run:
                loader_dll.unlink()

        if asset_map.exists():
            print(f"Removing loader data: {asset_map}")
            if not dry_run:
                asset_map.unlink()

        if rsmm_dir.exists():
            print(f"Removing loader runtime dir: {rsmm_dir}")
            if not dry_run:
                shutil.rmtree(rsmm_dir)
    except OSError as e:
        print(f"  [warn] failed to clear loader artifacts: {e}", file=sys.stderr)
        return 0
    return 1


def clear_steam_launch_options_for_vanilla(dry_run: bool = False) -> int:
    """Clear Steam LaunchOptions for Ravenswatch across known userdata profiles.

    Returns 1 when the operation completed (or was a no-op), 0 on hard failure.
    """
    try:
        from rsmm.cli.run import (
            RAVENSWATCH_APP_ID,
            _is_steam_running,
            _localconfig_paths,
            _steam_root,
            _write_launch_options,
        )
    except ImportError as e:
        print(f"  [warn] could not import Steam launch-option helpers: {e}", file=sys.stderr)
        return 0

    steam_root = _steam_root()
    if steam_root is None:
        print("Steam install not found; skipping launch-options cleanup.")
        return 1

    vdfs = _localconfig_paths(steam_root)
    if not vdfs:
        print("No Steam localconfig.vdf files found; skipping launch-options cleanup.")
        return 1

    if _is_steam_running():
        print("  [warn] Steam appears to be running; launch-options edits may be overwritten.",
              file=sys.stderr)

    changed = 0
    for vdf in vdfs:
        try:
            if dry_run:
                changed += 1
                continue
            if _write_launch_options(vdf, RAVENSWATCH_APP_ID, ""):
                changed += 1
        except OSError as e:
            print(f"  [warn] failed to clear launch options in {vdf}: {e}", file=sys.stderr)

    print(f"Cleared Steam launch options in {changed}/{len(vdfs)} config(s).")
    return 1


def _recover_game_update(cooking: Path, game_dir: Path) -> bool:
    """Detect game update, clear stale state, and stage a fresh apply.

    Returns True if an update was detected and recovery was performed.
    """
    current = game_fingerprint(game_dir)
    stored = load_stored_fingerprint(game_dir)
    if current == stored:
        return False

    print("Game update detected. Recovering...", flush=True)

    # 1. Clear stale backups — they point to pre-update originals
    cleared = 0
    for bak in cooking.rglob("*.rsmm.bak"):
        try:
            bak.unlink()
            cleared += 1
        except OSError as e:
            print(f"  [warn] failed to delete stale backup {bak}: {e}", file=sys.stderr)
    if cleared:
        print(f"  + cleared {cleared} stale backup(s)")

    # 2. Clear applier state — force a full re-apply from scratch
    state_path = cooking / ".rsmm_state.json"
    if state_path.exists():
        try:
            state_path.unlink()
            print("  + cleared applier state")
        except OSError:
            pass

    # 3. Rebuild asset map if the resource list changed. Pass the
    # UsedRscList path explicitly — find_iyg.main() otherwise falls back
    # to sys.argv[1], which here is a leftover CLI flag like
    # `--game-dir`, not a file.
    try:
        from rsmm.engine.find_iyg import main as rebuild_asset_map
        rc = rebuild_asset_map(str(game_dir / "DarkTalesResources" / "UsedRscList.ot"))
        if rc:
            print("  [warn] asset map rebuild failed (see above); "
                  "keeping the previous map", file=sys.stderr)
        else:
            # Clear the LRU cache so the fresh map is picked up
            from rsmm.engine.asset_map import encoded_to_decoded
            encoded_to_decoded.cache_clear()
            print("  + rebuilt asset map")
    except (OSError, ImportError) as e:
        print(f"  [warn] asset map rebuild failed: {e}", file=sys.stderr)

    # 4. Reset health crash counters — crashes were caused by the update
    try:
        from rsmm.sdk.health import Health
        h = Health(cooking)
        st = h.load()
        for mid in list(st.mods.keys()):
            h.re_enable(mid)
        h.clear_canary()
        print("  + reset health/crash counters")
    except (OSError, ImportError) as e:
        print(f"  [warn] health reset failed: {e}", file=sys.stderr)

    # 5. Persist the new fingerprint so we don't loop
    save_fingerprint(game_dir, current)
    return True


# --- magical-object catalog (LiveOps version manifest) -------------------
#
# A new magical-object entity is only LOADED + SPAWNED into the in-game pool
# (so it drops and shows in the compendium) if it is referenced by the active
# LiveOps version manifest. UsedRscList.ot only makes the file loadable-by-path;
# the manifest is what triggers the load. Two install files must list it:
#   * LiveOps5.versiondef.ot.rsionDefinition.gen — a vector<TResourcePtr> of
#     magical-object refs (u32 count, then count x <lstr type><lstr path>).
#   * LiveOps5.versiondef.UsedRscCache.ot — plain text, one line per resource
#     ``<category>|<path>|<class>`` so the manifest's ref resolves at load.
# Verified in-game 2026-06-02 (pool count 104 -> 105, item visible).
VERSIONDEF_GEN_LEAF = "LiveOps5.versiondef.ot.rsionDefinition.gen"
VERSIONDEF_CACHE_LEAF = "LiveOps5.versiondef.UsedRscCache.ot"


def _locate_cooked_by_leaf(game_dir: Path, decoded_leaf: str) -> Path | None:
    """Find the real loose ``_Cooking`` file whose decoded *filename* equals
    ``decoded_leaf``. Matches on the decoded leaf rather than re-encoding the
    path: ``cipher.encode`` is ~98% accurate but four letters are genuinely
    ambiguous (``v``/``I``/``Y`` and the ``\\``-collapse), so for an *existing*
    file we decode-and-compare to be exact. (For a *new* asset with no shipped
    file, ``synthesize_encoded`` must rely on ``cipher.encode``.) Skips
    backups."""
    cooking = game_dir / COOKING_REL
    if not cooking.is_dir():
        return None
    for p in cooking.rglob("*"):
        if not p.is_file() or p.name.endswith(BACKUP_SUFFIX):
            continue
        try:
            if cipher.decode(p.name) == decoded_leaf:
                return p
        except (ValueError, KeyError):
            continue
    return None


def _mo_versiondef_path(decoded: str) -> str | None:
    """Map a magical-object entity's decoded cooked path to its versiondef
    reference form, or None if it isn't a magical-object entity.

    ``EntitySettings/Objects/Magical_Objects/<R>/<id>.entity.ot.EntitySettingsResource.gen``
    -> ``Objects\\Magical_Objects\\<R>\\<id>.entity.ot``
    """
    d = decoded.replace("/", "\\")
    if "Magical_Objects\\" not in d or ".entity.ot.EntitySettingsResource.gen" not in d:
        return None
    d = d.split("EntitySettings\\", 1)[-1]                 # drop leading EntitySettings\
    return d[: d.index(".entity.ot") + len(".entity.ot")]  # keep ...entity.ot


def _find_mo_vector(b: bytes) -> tuple[int, int, int] | None:
    """Locate the magical-object ``vector<TResourcePtr>`` in a versiondef .gen.

    Returns ``(count_off, vec_end, count)``: ``count_off`` is the u32 count
    field, entries (``<lstr type><lstr path>`` pairs) run to ``vec_end``. The
    vector is identified by structure (a sizable run whose every entry path
    contains ``Magical_Objects``), so it survives offset shifts across builds.
    """
    N = len(b)

    def rd(o: int):
        if o + 4 > N:
            return None
        ln = struct.unpack_from("<I", b, o)[0]
        if ln <= 0 or ln > 300 or o + 4 + ln > N:
            return None
        s = b[o + 4 : o + 4 + ln]
        if not all(32 <= c < 127 or c == 92 for c in s):
            return None
        return s, o + 4 + ln

    for co in range(0, N - 4):
        cnt = struct.unpack_from("<I", b, co)[0]
        if not (20 <= cnt <= 2000):
            continue
        o = co + 4
        ok = all_mo = True
        for _ in range(cnt):
            a = rd(o)
            if not a:
                ok = False
                break
            _t, o = a
            a = rd(o)
            if not a:
                ok = False
                break
            p, o = a
            if b"Magical_Objects" not in p:
                all_mo = False
                break
        if ok and all_mo:
            return co, o, cnt
    return None


def _patch_versiondef_gen(pristine: bytes, paths: list[str]) -> bytes | None:
    """Return ``pristine`` with each ``paths`` entry appended to the MO vector
    (count bumped), skipping any already present. None if the vector or any
    entry can't be located/encoded."""
    loc = _find_mo_vector(pristine)
    if loc is None:
        return None
    co, vec_end, cnt = loc
    existing = pristine[co + 4 : vec_end]
    add = b""
    added = 0
    for path in paths:
        pb = path.encode("latin1")
        if struct.pack("<I", len(pb)) + pb in existing:
            continue  # already referenced
        add += struct.pack("<I", len(b"EntitySettings")) + b"EntitySettings"
        add += struct.pack("<I", len(pb)) + pb
        added += 1
    if added == 0:
        return pristine
    out = bytearray(pristine[:vec_end] + add + pristine[vec_end:])
    struct.pack_into("<I", out, co, cnt + added)
    return bytes(out)


def sync_versiondef(game_dir: Path, registrations: dict[str, str],
                    dry_run: bool) -> int:
    """Ensure every new magical-object entity in ``registrations`` is listed in
    the active LiveOps version manifest (.gen vector) AND its resource cache,
    so the engine loads + spawns it. Both files are backed up once and rebuilt
    from the pristine backup each apply (idempotent; clean drop on removal).
    Returns the number of files changed."""
    mo_paths = sorted(
        {p for d in registrations.values() if (p := _mo_versiondef_path(d))}
    )
    gen = _locate_cooked_by_leaf(game_dir, VERSIONDEF_GEN_LEAF)
    cache = _locate_cooked_by_leaf(game_dir, VERSIONDEF_CACHE_LEAF)

    changed = 0
    # --- .gen vector ---
    if gen is not None:
        bak = gen.with_name(gen.name + BACKUP_SUFFIX)
        if not mo_paths:
            if bak.exists() and not dry_run:
                shutil.copy2(bak, gen)
                bak.unlink()
                changed += 1
                print("  [versiondef] restored pristine manifest")
        else:
            if not bak.exists() and not dry_run:
                shutil.copy2(gen, bak)
            pristine = (bak if bak.exists() else gen).read_bytes()
            patched = _patch_versiondef_gen(pristine, mo_paths)
            if patched is None:
                print("  [warn] could not locate magical-object vector in "
                      f"{gen.name}; new item won't spawn", file=sys.stderr)
            elif patched != gen.read_bytes():
                print(f"  [versiondef] registering {len(mo_paths)} item(s) in "
                      "LiveOps manifest")
                if not dry_run:
                    gen.write_bytes(patched)
                changed += 1
    elif mo_paths:
        print("  [warn] LiveOps versiondef .gen not found; new magical object "
              "won't enter the pool", file=sys.stderr)

    # --- UsedRscCache text ---
    if cache is not None:
        bak = cache.with_name(cache.name + BACKUP_SUFFIX)
        lines = [f"EntitySettings|{p}|oCEntitySettingsResource" for p in mo_paths]
        if not mo_paths:
            if bak.exists() and not dry_run:
                shutil.copy2(bak, cache)
                bak.unlink()
                changed += 1
        else:
            if not bak.exists() and not dry_run:
                shutil.copy2(cache, bak)
            pristine = (bak if bak.exists() else cache).read_bytes()
            add = b"".join(
                b"\n" + ln.encode("latin1") for ln in lines
                if ln.encode("latin1") not in pristine
            )
            if add:
                body = pristine + add + (b"" if pristine.endswith(b"\n") else b"\n")
                if body != cache.read_bytes():
                    if not dry_run:
                        cache.write_bytes(body)
                    changed += 1
    return changed


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


@contextmanager
def _install_lock_or_fail(cooking: Path, operation: str):
    """Hold the install lock for the duration, or explain who has it.

    Two rsmm processes writing the same install can interleave a backup
    against an apply and capture a MODDED file as the "original" — the one
    corruption no restore can undo, because the vanilla bytes are gone.
    A short wait covers the common case (the desktop app polling `json list`
    while the user hits Apply); beyond that, say who holds it.
    """
    try:
        with install_lock(cooking, operation, timeout=10.0):
            yield True
    except LockBusy as e:
        print(f"{_ST.err('[FAIL]')} {e}", file=sys.stderr)
        yield False


def cmd_apply(args, repo: Path, cooking: Path, game_dir: Path) -> int:
    _recover_game_update(cooking, game_dir)
    dec2enc = load_asset_map(repo)
    mods = discover_mods(repo)
    mods = apply_health_quarantine(mods, cooking)
    # Materialize [[content]] declarations before computing the asset
    # plan so the emitted files are picked up like any other asset.
    emit_content_blocks(mods)
    state = State(cooking)

    # If a previous apply crashed mid-write, the stage dir may still be
    # around. Clear/finish it before computing the new plan so we're
    # diffing against a clean install tree.
    try:
        from rsmm.sdk.transaction import ApplyTransaction
        tx_recover = ApplyTransaction(cooking).recover()
        if tx_recover != "clean":
            print(f"  [apply] recovered previous staging state: {tx_recover}")
    except (OSError, ImportError) as e:
        print(f"  [apply] recover skipped: {e}", file=sys.stderr)

    # Leftovers from a run that died mid-write: temp files the rename never
    # consumed, and journalled writes the state file never recorded.
    swept = sweep_temp_files(cooking)
    if swept:
        print(f"  [apply] cleared {swept} leftover temp file(s)")
    reconcile_journal(cooking, state)
    journal = Journal(cooking)

    # Run on_disable.py for any mod that flipped enabled -> disabled BEFORE
    # we touch assets, so the hook can read its own files / restore state
    # while the install tree is still in its previous shape.
    # `getattr` so legacy callers (and old tests) that pass a bare
    # SimpleNamespace without the new `yes` field don't crash.
    deact_ran, _ = _run_deactivation_hooks(
        mods, state, game_dir, cooking, args.dry_run,
        assume_yes=getattr(args, "yes", False),
    )

    additions, removals, registrations = plan_apply(
        mods, dec2enc, cooking, game_dir, state, args.dry_run)

    # Register/unregister brand-new assets in the engine's master manifest
    # so they're actually loaded (or cleanly dropped). Self-correcting:
    # always rebuilt from the pristine backup + current registrations.
    usedrsc_changes = sync_usedrsclist(game_dir, registrations, dec2enc, args.dry_run)

    # Register new magical objects in the LiveOps version manifest + resource
    # cache so the engine actually loads + spawns them (UsedRscList alone only
    # makes them loadable-by-path). See sync_versiondef.
    versiondef_changes = sync_versiondef(game_dir, registrations, args.dry_run)

    # Sync manifests so game knows which mods are enabled
    manifest_syncs = _sync_mod_manifests(mods, game_dir, args.dry_run)

    if (not additions and not removals and not manifest_syncs
            and not deact_ran and not usedrsc_changes and not versiondef_changes):
        print("Mods already in sync.")
        return 0

    if additions or removals:
        print(f"Plan: {len(additions)} apply, {len(removals)} restore")
        if not args.dry_run and additions:
            # Every override is written once and the file it replaces is
            # backed up alongside it, so budget for both. Failing here costs
            # nothing; running out of space mid-apply leaves a half-modded
            # install.
            need = 0
            for _enc, src, dest, _mod_id in additions:
                try:
                    need += src.stat().st_size * (2 if dest.exists() else 1)
                except OSError:
                    continue
            ensure_free_space(cooking, need)
        failed_removals = 0
        for enc in removals:
            if not restore_one(enc, cooking, game_dir, state, args.dry_run):
                failed_removals += 1
        if failed_removals:
            print(f"  [WARN] {failed_removals} removal(s) failed; "
                  f"state entries preserved for retry", file=sys.stderr)
        blocked = 0
        for enc, src, dest, mod_id in additions:
            try:
                apply_one(enc, src, dest, mod_id, state, args.dry_run,
                          force=bool(getattr(args, "force", False)),
                          journal=journal)
            except VanillaMissing as e:
                # Skip this file, keep applying the rest: one wiped vanilla
                # asset must not block every other mod, and skipping is the
                # safe direction (the override simply isn't installed).
                blocked += 1
                print(f"  {_ST.err(_WARN_TOK)} {e}", file=sys.stderr)
        if blocked:
            print(f"  {_ST.err(_WARN_TOK)} "
                  f"{_ST.err(f'{blocked} file(s) NOT applied')} — the vanilla "
                  "originals are missing (see above)", file=sys.stderr)

    if manifest_syncs:
        print(f"Synced {manifest_syncs} mod file(s) (manifests/lua) to game mods directory")

    if not args.dry_run:
        state.set_enabled_mods([m.id for m in mods if m.enabled])
        try:
            state.save()
            print(f"State written: {state.path}")
            # State now describes every write, so the write-ahead record has
            # done its job. Clear it only after the save succeeds.
            journal.clear()
        except OSError as e:
            print(f"  [warn] failed to write state: {e}", file=sys.stderr)
    return 0


def cmd_restore_all(args, repo: Path, cooking: Path, game_dir: Path) -> int:
    state = State(cooking)
    # A restore is the recovery path, so it must see writes an interrupted
    # apply never got to record — otherwise mod-added files (which have no
    # backup to sweep) survive the rollback.
    if not args.dry_run:
        sweep_temp_files(cooking)
        reconcile_journal(cooking, state)
    restored_stale = 0
    cleaned_residue = 0
    purged_known = 0

    # Detect game update BEFORE touching any files.
    # If the game version changed, backups from the previous version MUST NOT
    # be restored — they would corrupt the new install.
    current_fp = game_fingerprint(game_dir)
    stored_fp = load_stored_fingerprint(game_dir)
    game_updated = current_fp != stored_fp

    if game_updated:
        print("Game version changed since last apply. "
              "Old backups are incompatible and will NOT be restored.",
              flush=True)
        # Skip Phase 1 (stale backup recovery) and Phase 2 (state restore):
        # every backup on disk is from the previous game version.
        #
        # Mod-ADDED files are the exception. They are not game files, so the
        # version change says nothing about them, and leaving them behind
        # keeps stale modded assets in a freshly patched install with nothing
        # tracking them. restore_one's own guards still apply — a path the
        # game ships is never dropped, whatever state claims.
        added = [
            enc for enc, entry in state.active.items()
            if not (entry.get("orig_sha256") or entry.get("orig_sha1", ""))
        ]
        if added:
            print(f"Dropping {len(added)} mod-added file(s) "
                  f"(not game files — safe to remove after an update).")
            for enc in added:
                restore_one(enc, cooking, game_dir, state, args.dry_run)
            if not args.dry_run:
                try:
                    state.save()
                except OSError as e:
                    print(f"  [warn] failed to write state: {e}", file=sys.stderr)
        save_fingerprint(game_dir, current_fp)
    else:
        # Phase 1: Recover orphaned backups that have no state entry.
        # Backed-up files tracked in state.active are handled by Phase 2.
        for bak in cooking.rglob(f"*{BACKUP_SUFFIX}"):
            rel = str(bak.relative_to(cooking))
            enc_key = rel[: -len(BACKUP_SUFFIX)].replace("/", "\\")
            if enc_key in state.active:
                continue
            dest = bak.with_name(bak.name[: -len(BACKUP_SUFFIX)])
            print(f"  - restore {dest.relative_to(cooking)} (stale backup)")
            if not args.dry_run:
                dest.parent.mkdir(parents=True, exist_ok=True)
                try:
                    atomic_copy(bak, dest)
                    bak.unlink()
                except OSError as e:
                    print(f"  [ERROR] failed to restore stale backup {bak.name}: {e}",
                          file=sys.stderr)
                    continue
                if not dest.exists():
                    print(f"  [ERROR] stale backup restore appeared to "
                          f"succeed but {dest} is missing", file=sys.stderr)
                    continue
            restored_stale += 1

        # Phase 2: Restore every override recorded in state
        if state.active:
            print(f"Restoring {len(state.active)} overrides...")
            failed: list[str] = []
            for enc in list(state.active):
                ok = restore_one(enc, cooking, game_dir, state, args.dry_run)
                if not ok:
                    failed.append(enc)
            if failed and not args.dry_run:
                print(f"  [WARN] {len(failed)} file(s) could not be restored; "
                      f"their state entries are preserved for retry.",
                      file=sys.stderr)
                try:
                    state.save()
                except OSError as e:
                    print(f"  [warn] failed to save state: {e}", file=sys.stderr)
            elif not args.dry_run:
                try:
                    state.save()
                except OSError as e:
                    print(f"  [warn] failed to save state: {e}", file=sys.stderr)
        else:
            print("No active overrides in state.")

    # Fallback sweep: if state/backups got out of sync, detect residue by
    # hash-matching cooked files to current mod source files and drop them.
    try:
        dec2enc = load_asset_map(repo)
        mods = discover_mods(repo)
        for mod in mods:
            for src, decoded in mod.files():
                enc = dec2enc.get(decoded) or resolve_special(decoded, dec2enc)
                if not enc:
                    continue
                dest = encoded_to_dest(enc, cooking, game_dir)
                if not dest.exists() or not src.exists():
                    continue
                bak = dest.parent / (dest.name + BACKUP_SUFFIX)
                try:
                    if sha256(dest) != sha256(src):
                        continue
                except OSError:
                    continue

                if bak.exists():
                    print(f"  - restore {enc}  (residue via source hash + backup)")
                    if not args.dry_run:
                        try:
                            shutil.copy2(bak, dest)
                            bak.unlink()
                        except OSError as e:
                            print(f"  [ERROR] failed to restore {enc}: {e}",
                                  file=sys.stderr)
                            continue
                else:
                    print(f"  - drop    {enc}  (residue via source hash)")
                    if not args.dry_run:
                        try:
                            dest.unlink()
                        except OSError as e:
                            print(f"  [ERROR] failed to drop {enc}: {e}",
                                  file=sys.stderr)
                            continue
                cleaned_residue += 1

        if getattr(args, "purge_known_overrides", False):
            print("Aggressive purge enabled: removing known mod-mapped cooked files...")
            seen: set[tuple[str, str]] = set()
            for mod in mods:
                for src, decoded in mod.files():
                    enc = dec2enc.get(decoded) or resolve_special(decoded, dec2enc)
                    key = (enc or "", str(src))
                    if not enc or key in seen:
                        continue
                    seen.add(key)
                    dest = encoded_to_dest(enc, cooking, game_dir)
                    if not dest.exists():
                        continue
                    bak = dest.parent / (dest.name + BACKUP_SUFFIX)
                    if bak.exists():
                        print(f"  - restore {enc}  (aggressive purge + backup)")
                        if not args.dry_run:
                            try:
                                shutil.copy2(bak, dest)
                                bak.unlink()
                            except OSError as e:
                                print(f"  [ERROR] aggressive purge restore failed "
                                      f"for {enc}: {e}", file=sys.stderr)
                                continue
                        purged_known += 1
                        continue

                    # Only drop when we can prove the cooked file bytes are
                    # exactly the mod source bytes.
                    try:
                        if src.exists() and sha256(dest) == sha256(src):
                            print(f"  - drop    {enc}  (aggressive purge + source hash)")
                            if not args.dry_run:
                                dest.unlink()
                            purged_known += 1
                    except OSError:
                        continue

        # Final verification pass: flag any remaining cooked files that still
        # byte-match known mod assets so restore cannot silently claim success.
        residual_matches: set[str] = set()
        for mod in mods:
            for src, decoded in mod.files():
                enc = dec2enc.get(decoded) or resolve_special(decoded, dec2enc)
                if not enc:
                    continue
                dest = encoded_to_dest(enc, cooking, game_dir)
                if not dest.exists() or not src.exists():
                    continue
                try:
                    if sha256(dest) == sha256(src):
                        residual_matches.add(enc)
                except OSError:
                    continue

        if residual_matches:
            show = sorted(residual_matches)
            print(f"  [warn] {len(show)} residual override(s) still match mod asset bytes:",
                  file=sys.stderr)
            for enc in show[:20]:
                print(f"    - {enc}", file=sys.stderr)
            if len(show) > 20:
                print(f"    ... and {len(show) - 20} more", file=sys.stderr)
            return 2
    except (OSError, ValueError) as e:
        # ValueError covers a corrupt asset_map.json — restore must still
        # finish its filesystem cleanup even when the map can't be loaded.
        print(f"  [warn] residue sweep skipped: {e}", file=sys.stderr)

    # Drop custom UsedRscList.ot registrations. On a game update the backup
    # is from the old version, so discard it rather than restore — the new
    # install already ships its own (correct) manifest.
    upath = game_dir / USEDRSCLIST_REL
    ubak = upath.with_name(upath.name + BACKUP_SUFFIX)
    if game_updated:
        if ubak.exists() and not args.dry_run:
            try:
                ubak.unlink()
            except OSError as e:
                print(f"  [warn] failed to drop stale UsedRscList backup: {e}",
                      file=sys.stderr)
    else:
        restore_usedrsclist(game_dir, args.dry_run)

    runtime_cleared = clear_runtime_mods(game_dir, args.dry_run)
    if not runtime_cleared:
        print("Failed to clear runtime mods directory.", file=sys.stderr)
        return 1

    if not clear_loader_artifacts(game_dir, args.dry_run):
        print("Failed to clear loader artifacts.", file=sys.stderr)
        return 1

    # Best-effort: even if launch options fail to edit (e.g. Steam running),
    # restore should still perform all filesystem cleanup above.
    clear_steam_launch_options_for_vanilla(args.dry_run)

    if restored_stale:
        print(f"Recovered {restored_stale} stale backup(s).")
    if cleaned_residue:
        print(f"Cleaned {cleaned_residue} residual cooked override(s).")
    if purged_known:
        print(f"Purged {purged_known} known mod-mapped cooked file(s).")
    print("Runtime mods directory cleared.")
    return 0


def cmd_list(args, repo: Path, cooking: Path) -> int:
    """Print the installed mods.

    The per-file dump is behind `--files`: it is the useful view when
    debugging one mod's asset resolution, but it buried the mod list itself
    under thousands of lines on any real install.
    """
    st = _term.Style()
    mods = discover_mods(repo)
    if not mods:
        print(st.dim(f"no mods found in {MODS_DIR}"))
        return 0

    only_enabled = bool(getattr(args, "enabled", False))
    show_files = bool(getattr(args, "files", False))
    shown = [m for m in mods if m.enabled] if only_enabled else mods

    state = State(cooking)
    dec2enc = load_asset_map(repo)

    total_files = unresolved_total = active_total = 0
    id_w = min(max((len(m.id) for m in shown), default=8), 34)

    for m in shown:
        files = m.files()
        resolved = [
            (decoded, dec2enc.get(decoded) or resolve_special(decoded, dec2enc))
            for _src, decoded in files
        ]
        unresolved = [d for d, enc in resolved if not enc]
        active = [d for d, enc in resolved if enc and enc in state.active]
        total_files += len(files)
        unresolved_total += len(unresolved)
        active_total += len(active)

        box = st.ok("[on ]") if m.enabled else st.dim("[off]")
        # Pad the PLAIN id — padding a styled string counts the ANSI escapes
        # as width and silently mis-aligns every coloured row.
        padded = f"{m.id[:id_w]:<{id_w}}"
        name = st.bold(padded) if m.enabled else padded
        meta = st.dim(f"{m.name} {m.version} · by {m.author or 'unknown'}")
        counts = st.dim(f"{len(files)} file(s)")
        if active:
            counts += st.dim(" · ") + st.ok(f"{len(active)} active")
        if unresolved:
            counts += st.dim(" · ") + st.warn(f"{len(unresolved)} unmapped")
        print(f"  {box} {name}  {counts}")
        print(f"        {meta}")

        if not show_files:
            continue
        for decoded, enc in resolved:
            if not enc:
                tag = "  " + st.warn(_WARN_TOK + " no asset_map match")
            elif enc in state.active:
                tag = "  " + st.ok(_ADD + " active")
            else:
                tag = ""
            print(f"        {st.dim(decoded)}{tag}")

    print()
    summary = (f"{len(shown)} mod(s)"
               + (st.dim(f" of {len(mods)}") if only_enabled else "")
               + st.dim(" · ") + f"{total_files} file(s)")
    if active_total:
        summary += st.dim(" · ") + st.ok(f"{active_total} active")
    if unresolved_total:
        summary += st.dim(" · ") + st.warn(f"{unresolved_total} unmapped")
    print("  " + summary)
    if unresolved_total and not show_files:
        print("  " + st.dim("run with --files to see which paths are unmapped"))
    return 0


def _ensure_asset_map() -> bool:
    """Pre-flight: the asset map must exist and parse before apply/list can
    resolve any mod path. Print an actionable message instead of letting a
    FileNotFoundError / JSONDecodeError traceback reach the user."""
    p = ASSET_MAP_JSON
    try:
        json.loads(p.read_text(encoding="utf-8"))
        return True
    except FileNotFoundError:
        print(f"asset map not found: {p}\n"
              "  Run: ./rsmm rebuild-asset-map   (requires the game install)\n"
              "  If you installed a packaged rsmm build, reinstall it — the "
              "asset map ships with it.", file=sys.stderr)
    except (OSError, ValueError) as e:
        print(f"asset map is unreadable: {p}\n  ({e})\n"
              "  Run: ./rsmm rebuild-asset-map to regenerate it.",
              file=sys.stderr)
    return False


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--game-dir", type=Path, default=None,
                    help="Ravenswatch install dir (autodetected if omitted)")
    ap.add_argument("--dry-run", action="store_true",
                    help="show what would happen; touch nothing")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--restore-all", action="store_true",
                   help="restore every active override and clear state")
    g.add_argument("--list", action="store_true",
                   help="list discovered mods")
    ap.add_argument("--files", action="store_true",
                    help="with --list: also print every file each mod ships")
    ap.add_argument("--enabled", action="store_true",
                    help="with --list: show only enabled mods")
    ap.add_argument("--purge-known-overrides", action="store_true",
                    help="aggressively remove cooked files mapped from "
                         "known mod assets during restore")
    ap.add_argument("--no-merge", action="store_true",
                    help="skip auto-merging [[patch]] blocks into mods/_merged/")
    ap.add_argument("--force", action="store_true",
                    help="apply even if the compatibility graph has errors")
    ap.add_argument("--yes", action="store_true",
                    help="auto-confirm execution of on_disable.py hooks "
                         "(otherwise prompts interactively; set "
                         "RSMM_NONINTERACTIVE=1 to require --yes)")
    args = ap.parse_args()

    repo = REPO_DIR
    game_dir = args.game_dir or find_game_dir()
    if not game_dir:
        print("Could not autodetect Ravenswatch install. "
              "Pass --game-dir /path/to/Ravenswatch.", file=sys.stderr)
        return 1
    cooking = game_dir / COOKING_REL
    if not cooking.is_dir():
        print(f"_Cooking not found at {cooking}", file=sys.stderr)
        return 1

    if args.restore_all:
        # restore tolerates a missing/corrupt asset map (its residue sweep
        # already guards itself) — never block a rollback on it.
        with _install_lock_or_fail(cooking, "restore") as held:
            if not held:
                return 1
            return cmd_restore_all(args, repo, cooking, game_dir)
    if not _ensure_asset_map():
        return 1
    if args.list:
        return cmd_list(args, repo, cooking)

    # Compatibility graph: refuse to apply on hard conflict / cycle /
    # unmet require unless the user passes --force.
    try:
        from rsmm.cli.compat import analyze
        rep = analyze()
        if rep.has_errors and not getattr(args, "force", False):
            print("  [compat] manifest graph has errors; refusing to apply.",
                  file=sys.stderr)
            for mid, msg in rep.unmet_requires:
                print(f"    [unmet]    {mid}: {msg}", file=sys.stderr)
            for a, b in rep.hard_conflicts:
                print(f"    [conflict] {a} <-> {b}", file=sys.stderr)
            for c in rep.cycles:
                print(f"    [cycle]    {' -> '.join(c)}", file=sys.stderr)
            print("  Re-run with --force to ignore.", file=sys.stderr)
            return 1
        for mid, why in rep.auto_disabled.items():
            print(f"  [compat] auto-disabling {mid}: {why}")
    except ImportError as e:
        print(f"  [compat] skipped: {e}", file=sys.stderr)

    # Auto-merge [[patch]] blocks across mods before applying so two
    # mods touching different fields of the same cooked file both take
    # effect. Disable with --no-merge.
    if not args.no_merge:
        try:
            from rsmm.cli.merge import build_merged_mod
            out, conflicts = build_merged_mod(game_dir)
            if out is not None:
                print(f"  [merge] composed {out.name}/ "
                      f"({len(conflicts)} conflict(s))")
                for kind, key, m in conflicts:
                    print(f"    [conflict] [{kind}] {key}  {m}")
        except ImportError as e:
            print(f"  [merge] skipped: {e}", file=sys.stderr)

    with _install_lock_or_fail(cooking, "apply") as held:
        if not held:
            return 1
        try:
            return cmd_apply(args, repo, cooking, game_dir)
        except NotEnoughSpace as e:
            print(f"{_ST.err('[FAIL]')} {e}", file=sys.stderr)
            return 1


if __name__ == "__main__":
    sys.exit(main())
