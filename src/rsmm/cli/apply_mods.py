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
    assets/<decoded-path>   # e.g. assets/Ui/BookMenu/Heroes/UI_HeroPortrait_Romeo_Active.png.Texture.dxt
                            # The decoded path is what humans read; we look
                            # it up in asset_map.json and translate to the
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
from pathlib import Path
from typing import Optional

from rsmm.engine.paths import (
    REPO_ROOT as REPO_DIR,
    MODS_DIR,
    ASSET_MAP_JSON,
    _game_dir_candidates,
)
import tomllib   # Python 3.11+


def parse_toml(p: Path) -> dict:
    return tomllib.loads(p.read_text(encoding="utf-8"))


COOKING_REL = Path("DarkTalesResources/_Cooking")
STATE_FILE_NAME = ".rsmm_state.json"
BACKUP_SUFFIX = ".rsmm.bak"


def find_game_dir() -> Optional[Path]:
    """Best-effort autodetect across Linux/macOS/Windows.

    The cooked asset tree is the canonical marker (DarkTalesResources/_Cooking).
    Return the first install dir that contains it. Candidate list lives
    in `rsmm.engine.paths` so every CLI agrees.
    """
    for c in _game_dir_candidates():
        if (c / COOKING_REL).is_dir():
            return c
    return None


def sha1(p: Path) -> str:
    h = hashlib.sha1()
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
            "src_sha1": "<sha1 of mod file>",
            "orig_sha1": "<sha1 of pre-override game file>"
          }
        }
      }
    """

    def __init__(self, cooking: Path):
        self.cooking = cooking
        self.path = cooking / STATE_FILE_NAME
        self.data: dict = {"version": 1, "active": {}}
        if self.path.exists():
            try:
                self.data = json.loads(self.path.read_text(encoding="utf-8"))
            except Exception:
                pass

    def save(self) -> None:
        self.path.write_text(json.dumps(self.data, indent=2, sort_keys=True),
                             encoding="utf-8")

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
        self.enabled: bool = bool(m.get("enabled", True))
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
            # `_pending_*` dirs are SDK content-emission staging output
            # consumed by the merge step. They are not raw cooked assets
            # so the applier must not try to install them under
            # `_Cooking/` directly.
            if decoded.split("/", 1)[0].startswith("_pending_"):
                continue
            out.append((f, decoded))
        return out


def load_asset_map(repo: Path) -> dict[str, str]:
    """decoded_path (forward-slash) -> encoded_path (with backslashes)."""
    p = ASSET_MAP_JSON
    raw = json.loads(p.read_text(encoding="utf-8"))
    out: dict[str, str] = {}
    for enc, dec in raw.items():
        dec_norm = dec.replace("\\", "/")
        out[dec_norm] = enc
    return out


# Language-code translation between decoded and on-disk form. The cipher
# operates per character, so we cache only the codes we know about. New
# locale codes Ravenswatch ships can be added here.
LANG_DECODED_TO_ENCODED = {
    "EN": "MU", "JA": "EW", "KO": "IO", "RU": "LJ", "ES": "MF",
    "DE": "NM", "PL": "TG", "FR": "VL", "IT": "XQ",
    "PT-BR": "TQ-BL", "ZH-S": "YA-F", "ZH-T": "YA-Q",
    "RAW": "LWR",   # in-game pseudo-locale (`*marked text` for QA)
}


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


def encoded_to_dest(encoded: str, cooking: Path, game_dir: Path) -> Path:
    """Translate an internal encoded key into an on-disk path.

    Two forms:
      `<encoded\\path>`      -> <cooking>/<path>            (cooked asset)
      `_root\\<rel\\path>`    -> <game_dir>/<rel>            (top-level file)
    """
    if encoded.startswith(ROOT_PREFIX):
        rel = encoded[len(ROOT_PREFIX):]
        return game_dir / Path(*rel.split("\\"))
    return cooking / Path(*encoded.split("\\"))


def to_cooking_rel(encoded: str) -> Path:
    """Legacy helper. Use encoded_to_dest(...) instead."""
    return Path(*encoded.split("\\"))


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
        except Exception as e:
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
        from rsmm.sdk.content import ContentRegistry, ContentError, SchemaNotMined
    except Exception as e:
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
        except Exception as e:
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
    except Exception as e:
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
               dry_run: bool) -> tuple[list[tuple[str, Path, Path, str]], list[str]]:
    """Compute (additions, removals) given current state and on-disk mods.

    additions: list of (encoded_rel, src_file, dest_in_cooking, mod_id)
    removals : list of encoded_rel to restore from .bak (no longer overridden)
    """
    wanted: dict[str, tuple[Path, str]] = {}  # encoded -> (src, mod_id)
    for m in mods:
        if not m.enabled:
            continue
        for src, decoded in m.files():
            enc = dec2enc.get(decoded) or resolve_special(decoded, dec2enc)
            if not enc:
                print(f"  [warn] {m.id}: no asset_map entry for '{decoded}'",
                      file=sys.stderr)
                continue
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
        src_sha = sha1(src)
        if cur and cur.get("src_sha1") == src_sha and dest.exists():
            # already applied + unchanged
            continue
        additions.append((enc, src, dest, mod_id))

    for enc in list(active.keys()):
        if enc not in wanted:
            removals.append(enc)

    return additions, removals


def apply_one(enc: str, src: Path, dest: Path, mod_id: str,
              state: State, dry_run: bool) -> None:
    cur = state.active.get(enc)
    bak = dest.with_suffix(dest.suffix + BACKUP_SUFFIX) if dest.exists() else None
    if dest.exists():
        bak = dest.parent / (dest.name + BACKUP_SUFFIX)
        if not bak.exists():
            orig_sha = sha1(dest)
            print(f"  + backup {dest.name}")
            if not dry_run:
                shutil.copy2(dest, bak)
        else:
            orig_sha = (cur or {}).get("orig_sha1") or sha1(bak)
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
        "src_sha1": sha1(src),
        "orig_sha1": orig_sha,
    }


def restore_one(enc: str, cooking: Path, game_dir: Path,
                state: State, dry_run: bool) -> None:
    dest = encoded_to_dest(enc, cooking, game_dir)
    bak = dest.parent / (dest.name + BACKUP_SUFFIX)
    if bak.exists():
        print(f"  - restore {enc}")
        if not dry_run:
            shutil.move(str(bak), str(dest))
    else:
        print(f"  - drop    {enc}  (no backup -> added file removed)")
        if not dry_run and dest.exists():
            dest.unlink()
    state.active.pop(enc, None)


DEACTIVATION_SCRIPT_NAME = "on_disable.py"
DEACTIVATION_TIMEOUT_SEC = 30


def _run_deactivation_hooks(mods: list[Mod],
                            state: State,
                            game_dir: Path,
                            cooking: Path,
                            dry_run: bool) -> tuple[list[str], list[str]]:
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

    Returns (ran, missing) — mod ids whose hook fired vs flipped mods
    with no on_disable.py present (silent; not an error).
    """
    prev_enabled = set(state.enabled_mods)
    if not prev_enabled:
        return [], []

    cur_by_id = {m.id: m for m in mods}
    cur_enabled = {m.id for m in mods if m.enabled}
    flipped = sorted(prev_enabled - cur_enabled)

    ran: list[str] = []
    missing: list[str] = []
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
        except Exception as e:
            print(f"    on_disable {mod_id} failed: {e}", file=sys.stderr)
    return ran, missing


def _sync_mod_manifests(mods: list[Mod], game_dir: Path, dry_run: bool) -> int:
    """Copy manifest.toml from each mod to the game's mods/ directory.
    Also sync/remove init.lua based on enabled flag.

    The game engine reads manifests to determine which mods are enabled.
    For Lua code mods, we remove init.lua when disabled to prevent execution.
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

        # Sync manifest
        dst_manifest = dst_dir / "manifest.toml"
        try:
            src_mtime = manifest.stat().st_mtime
            dst_mtime = dst_manifest.stat().st_mtime if dst_manifest.exists() else 0
            if src_mtime > dst_mtime:
                if not dry_run:
                    dst_manifest.write_bytes(manifest.read_bytes())
                synced += 1
        except OSError:
            pass

        # Sync or remove init.lua based on enabled flag
        src_lua = mod_dir / "init.lua"
        dst_lua = dst_dir / "init.lua"

        if enabled and src_lua.is_file():
            # Mod is enabled: sync init.lua
            try:
                src_mtime = src_lua.stat().st_mtime
                dst_mtime = dst_lua.stat().st_mtime if dst_lua.exists() else 0
                if src_mtime > dst_mtime:
                    if not dry_run:
                        dst_lua.write_bytes(src_lua.read_bytes())
                    synced += 1
            except OSError:
                pass
        elif not enabled and dst_lua.exists():
            # Mod is disabled: remove init.lua to prevent execution
            if not dry_run:
                dst_lua.unlink()
            synced += 1

    return synced


def cmd_apply(args, repo: Path, cooking: Path, game_dir: Path) -> int:
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
    except Exception as e:
        print(f"  [apply] recover skipped: {e}", file=sys.stderr)

    # Run on_disable.py for any mod that flipped enabled -> disabled BEFORE
    # we touch assets, so the hook can read its own files / restore state
    # while the install tree is still in its previous shape.
    deact_ran, _ = _run_deactivation_hooks(mods, state, game_dir, cooking, args.dry_run)

    additions, removals = plan_apply(mods, dec2enc, cooking, game_dir, state, args.dry_run)

    # Sync manifests so game knows which mods are enabled
    manifest_syncs = _sync_mod_manifests(mods, game_dir, args.dry_run)

    if not additions and not removals and not manifest_syncs and not deact_ran:
        print("Mods already in sync.")
        return 0

    if additions or removals:
        print(f"Plan: {len(additions)} apply, {len(removals)} restore")
        for enc in removals:
            restore_one(enc, cooking, game_dir, state, args.dry_run)
        for enc, src, dest, mod_id in additions:
            apply_one(enc, src, dest, mod_id, state, args.dry_run)

    if manifest_syncs:
        print(f"Synced {manifest_syncs} mod file(s) (manifests/lua) to game mods directory")

    if not args.dry_run:
        state.set_enabled_mods([m.id for m in mods if m.enabled])
        state.save()
        print(f"State written: {state.path}")
    return 0


def cmd_restore_all(args, repo: Path, cooking: Path, game_dir: Path) -> int:
    state = State(cooking)
    if not state.active:
        print("No active overrides.")
        return 0
    print(f"Restoring {len(state.active)} overrides...")
    for enc in list(state.active):
        restore_one(enc, cooking, game_dir, state, args.dry_run)
    if not args.dry_run:
        state.save()
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
        for src, decoded in m.files():
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
    ap.add_argument("--no-merge", action="store_true",
                    help="skip auto-merging [[patch]] blocks into mods/_merged/")
    ap.add_argument("--force", action="store_true",
                    help="apply even if the compatibility graph has errors")
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
    except Exception as e:
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
        except Exception as e:
            print(f"  [merge] skipped: {e}", file=sys.stderr)

    return cmd_apply(args, repo, cooking, game_dir)


if __name__ == "__main__":
    sys.exit(main())
