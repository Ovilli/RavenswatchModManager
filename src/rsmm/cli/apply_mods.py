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
import sys
from pathlib import Path
from typing import Optional

from rsmm.engine.paths import (
    REPO_ROOT as REPO_DIR,
    DATA_DIR,
    MODS_DIR,
    ASSET_MAP_JSON,
    ASSET_MAP_CSV,
    DEFAULT_GAME_DIR as DEFAULT_GAME,
    COOKING_SUBDIR,
)
# Optional toml parsing; fall back to a tiny manifest reader if tomllib/toml missing.
try:
    import tomllib   # Python 3.11+
    def parse_toml(p: Path) -> dict:
        return tomllib.loads(p.read_text(encoding="utf-8"))
except ImportError:
    try:
        import tomli
        def parse_toml(p: Path) -> dict:
            return tomli.loads(p.read_text(encoding="utf-8"))
    except ImportError:
        def parse_toml(p: Path) -> dict:
            # very small fallback: only [mod] section, key = "value"
            out: dict = {"mod": {}}
            section = None
            for line in p.read_text(encoding="utf-8").splitlines():
                s = line.strip()
                if not s or s.startswith("#"):
                    continue
                if s.startswith("[") and s.endswith("]"):
                    section = s[1:-1]
                    out.setdefault(section, {})
                    continue
                if "=" in s and section:
                    k, _, v = s.partition("=")
                    out[section][k.strip()] = v.strip().strip('"').strip("'")
            return out


COOKING_REL = Path("DarkTalesResources/_Cooking")
STATE_FILE_NAME = ".rsmm_state.json"
BACKUP_SUFFIX = ".rsmm.bak"


def find_game_dir() -> Optional[Path]:
    """Best-effort autodetect across Linux/macOS/Windows.

    The cooked asset tree is the canonical marker (DarkTalesResources/_Cooking).
    Return the first install dir that contains it.
    """
    home = Path.home()
    candidates: list[Path] = []
    if sys.platform.startswith("linux"):
        candidates += [
            home / ".var/app/com.valvesoftware.Steam/.local/share/Steam"
                   "/steamapps/common/Ravenswatch",
            home / ".steam/steam/steamapps/common/Ravenswatch",
            home / ".local/share/Steam/steamapps/common/Ravenswatch",
            Path("/mnt") / "Steam/steamapps/common/Ravenswatch",
        ]
    elif sys.platform == "darwin":
        candidates += [
            home / "Library/Application Support/Steam/steamapps/common/Ravenswatch",
        ]
    elif sys.platform == "win32":
        for drive in ("C:", "D:", "E:"):
            candidates += [
                Path(f"{drive}\\Program Files (x86)\\Steam\\steamapps\\common\\Ravenswatch"),
                Path(f"{drive}\\Program Files\\Steam\\steamapps\\common\\Ravenswatch"),
                Path(f"{drive}\\Steam\\steamapps\\common\\Ravenswatch"),
                Path(f"{drive}\\SteamLibrary\\steamapps\\common\\Ravenswatch"),
            ]
    for c in candidates:
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

    def files(self) -> list[tuple[Path, str]]:
        out: list[tuple[Path, str]] = []
        if not self.assets_dir.is_dir():
            return out
        for f in self.assets_dir.rglob("*"):
            if not f.is_file():
                continue
            decoded = f.relative_to(self.assets_dir).as_posix()
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


def cmd_apply(args, repo: Path, cooking: Path, game_dir: Path) -> int:
    dec2enc = load_asset_map(repo)
    mods = discover_mods(repo)
    state = State(cooking)
    additions, removals = plan_apply(mods, dec2enc, cooking, game_dir, state, args.dry_run)

    if not additions and not removals:
        print("Mods already in sync.")
        return 0

    print(f"Plan: {len(additions)} apply, {len(removals)} restore")
    for enc in removals:
        restore_one(enc, cooking, game_dir, state, args.dry_run)
    for enc, src, dest, mod_id in additions:
        apply_one(enc, src, dest, mod_id, state, args.dry_run)

    if not args.dry_run:
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
