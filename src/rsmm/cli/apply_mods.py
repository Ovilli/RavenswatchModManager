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
import subprocess
import sys
import tomllib  # Python 3.11+
from pathlib import Path

from rsmm.engine import cipher, cook_cache, cooked_schemas
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


def parse_toml(p: Path) -> dict:
    return tomllib.loads(p.read_text(encoding="utf-8"))


COOKING_REL = Path("DarkTalesResources/_Cooking")
STATE_FILE_NAME = ".rsmm_state.json"
BACKUP_SUFFIX = ".rsmm.bak"


def find_game_dir() -> Path | None:
    """Best-effort autodetect across Linux/macOS/Windows.

    The cooked asset tree is the canonical marker (DarkTalesResources/_Cooking).
    Return the first install dir that contains it. Candidate list lives
    in `rsmm.engine.paths` so every CLI agrees.
    """
    for c in _game_dir_candidates():
        if (c / COOKING_REL).is_dir():
            return c
    return None


def sha256(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


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
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(json.dumps(self.data, indent=2, sort_keys=True),
                       encoding="utf-8")
        tmp.replace(self.path)

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


def resolve_special(decoded: str, dec2enc: dict[str, str]) -> str | None:
    """Resolve decoded paths that aren't directly in asset_map.

    Handled cases:

    * `_root/<rel>` — top-level files in the install dir (e.g.
      `_root/DarkTalesResources/ApplicationSettings.ot`). Rewritten as
      an internal `_root\\<rel>` key, NOT a cooked-path encoding.
    * `Text/<bank>~GAM.xls.LocalText.gen.Lang<XX>` — localization
      sibling whose base is in `asset_map` but the .Lang<XX> sibling
      isn't. Decoded -> base's encoded path + `.Ggzy<encoded-lang>`.
    """
    if decoded.startswith("_root/"):
        return ROOT_PREFIX + decoded[len("_root/"):].replace("/", "\\")
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
        except (OSError, ValueError) as e:
            print(f"  skip {entry.name}: {e}", file=sys.stderr)
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
        cr = ContentRegistry(mod_id=m.id)
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
        try:
            written = cr.emit(out_dir)
            total += len(written)
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


def plan_apply(mods: list[Mod],
               dec2enc: dict[str, str],
               cooking: Path,
               game_dir: Path,
               state: State,
               dry_run: bool) -> tuple[list[tuple[str, Path, Path, str]], list[str], set[str]]:
    """Compute (additions, removals, registrations) given current state and
    on-disk mods.

    additions    : list of (encoded_rel, src_file, dest_in_cooking, mod_id)
    removals     : list of encoded_rel to restore from .bak (no longer overridden)
    registrations: set of encoded paths that aren't in the vanilla asset_map
                   and must be added to UsedRscList.ot so the engine loads them
    """
    wanted: dict[str, tuple[Path, str]] = {}  # encoded -> (src, mod_id)
    registrations: set[str] = set()
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
                registrations.add(enc)
                print(f"  [new] {m.id}: registering new asset '{decoded}'")
            if enc in wanted:
                print(f"  [warn] conflict on '{decoded}' "
                      f"(mods: {wanted[enc][1]} vs {m.id}); "
                      f"keeping later mod {m.id}", file=sys.stderr)
            wanted[enc] = (src, m.id)

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
        if cur and cur.get("src_sha256") == src_sha and dest.exists():
            # already applied + unchanged
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


def apply_one(enc: str, src: Path, dest: Path, mod_id: str,
              state: State, dry_run: bool) -> None:
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
            print(f"  + backup {dest.name}")
            if not dry_run:
                shutil.copy2(dest, bak)
        else:
            orig_sha = (cur or {}).get("orig_sha256") or sha256(bak)
    else:
        # Engine expected this file but it isn't there; mod adds a new asset.
        orig_sha = ""
        print(f"  + new file (no original) {dest}")

    print(f"  + apply  {enc}  <- {mod_id}/{src.name}")
    if not dry_run:
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest)
    state.active[enc] = {
        "mod": mod_id,
        "src_sha256": sha256(src),
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
        print(f"  - restore {enc}")
        if not dry_run:
            # Two-phase: copy then remove — a crash mid-copy preserves the backup
            try:
                shutil.copy2(bak, dest)
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
            print(f"  - skip    {enc}  (no backup, no destination)")
            state.active.pop(enc, None)
        return True

    # No backup, no orig_sha1 → mod added this file. Safe to remove.
    print(f"  - drop    {enc}  (no backup -> added file removed)")
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

    # 3. Rebuild asset map if the resource list changed
    try:
        from rsmm.engine.find_iyg import main as rebuild_asset_map
        rebuild_asset_map()
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


def sync_usedrsclist(game_dir: Path, registrations: set[str],
                     dry_run: bool) -> int:
    """Ensure UsedRscList.ot registers exactly `registrations` on top of
    the pristine vanilla manifest.

    The original file is backed up once as ``UsedRscList.ot.rsmm.bak`` and
    every rewrite is computed from that pristine copy, so disabling a
    custom mod cleanly drops its registration lines. When `registrations`
    is empty the backup is restored and removed (see
    :func:`restore_usedrsclist`). Returns the number of lines added.
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
    new = [e for e in sorted(registrations) if e not in have]
    desired = ([header] if header is not None else []) + base_lines + new

    # Idempotent: if the manifest already reads exactly as desired, do
    # nothing (don't rewrite ~64k lines every apply / report false work).
    cur_header, cur_lines = _read_usedrsclist(path)
    current = ([cur_header] if cur_header is not None else []) + cur_lines
    if current == desired:
        return 0

    print(f"  [usedrsc] registering {len(new)} new asset(s) in UsedRscList.ot")
    if not dry_run:
        body = "\n".join(desired) + "\n"
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(body, encoding="utf-8")
        tmp.replace(path)
    return len(new) or 1


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
    usedrsc_changes = sync_usedrsclist(game_dir, registrations, args.dry_run)

    # Sync manifests so game knows which mods are enabled
    manifest_syncs = _sync_mod_manifests(mods, game_dir, args.dry_run)

    if (not additions and not removals and not manifest_syncs
            and not deact_ran and not usedrsc_changes):
        print("Mods already in sync.")
        return 0

    if additions or removals:
        print(f"Plan: {len(additions)} apply, {len(removals)} restore")
        failed_removals = 0
        for enc in removals:
            if not restore_one(enc, cooking, game_dir, state, args.dry_run):
                failed_removals += 1
        if failed_removals:
            print(f"  [WARN] {failed_removals} removal(s) failed; "
                  f"state entries preserved for retry", file=sys.stderr)
        for enc, src, dest, mod_id in additions:
            apply_one(enc, src, dest, mod_id, state, args.dry_run)

    if manifest_syncs:
        print(f"Synced {manifest_syncs} mod file(s) (manifests/lua) to game mods directory")

    if not args.dry_run:
        state.set_enabled_mods([m.id for m in mods if m.enabled])
        try:
            state.save()
            print(f"State written: {state.path}")
        except OSError as e:
            print(f"  [warn] failed to write state: {e}", file=sys.stderr)
    return 0


def cmd_restore_all(args, repo: Path, cooking: Path, game_dir: Path) -> int:
    state = State(cooking)
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
                    shutil.copy2(bak, dest)
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
    except OSError as e:
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
    mods = discover_mods(repo)
    if not mods:
        print("No mods found in", MODS_DIR)
        return 0
    state = State(cooking)
    dec2enc = load_asset_map(repo)
    for m in mods:
        n = len(m.files())
        flag = "on " if m.enabled else "off"
        print(f"  [{flag}] {m.id}  ({m.name} {m.version})  by {m.author or 'unknown'}  files={n}")
        for _src, decoded in m.files():
            enc = dec2enc.get(decoded) or resolve_special(decoded, dec2enc)
            here = "  active" if (enc and enc in state.active) else ""
            mark = "" if enc else "  [no asset_map match]"
            print(f"        {decoded}{mark}{here}")
    return 0


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
                   help="list discovered mods + their files")
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

    if args.list:
        return cmd_list(args, repo, cooking)
    if args.restore_all:
        return cmd_restore_all(args, repo, cooking, game_dir)

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

    return cmd_apply(args, repo, cooking, game_dir)


if __name__ == "__main__":
    sys.exit(main())
