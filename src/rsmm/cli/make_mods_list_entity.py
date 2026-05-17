#!/usr/bin/env python3
"""Phase 5 Stage B: ship Mods_List.entity.ot.EntitySettingsResource.gen as a
proper mod asset.

Stage A wrote directly to _Cooking/ to prove the redirect resolves. Stage B
makes the new entity a first-class mod file AND registers it in the
engine's startup manifest so the real resource-lookup returns a non-zero
handle (without this step the engine ignores our cooked file because its
encoded path is not in UsedRscList.ot).

  1. Source = Friend_List_Recent.entity.ot.EntitySettingsResource.gen
     (chosen because the friend-list family already renders cleanly at
     the slot 7 position; Modal_Social_Options_Menu is the cleaner
     static-button shape but its oC2dElementDesc bounds are fullscreen
     and need RE work before it slots correctly).
  2. Bytes are cloned verbatim into
     mods/<id>/assets/EntitySettings/GameUis/All_Book_Pages/Social/Mods_List.entity.ot.EntitySettingsResource.gen
  3. asset_map.json is extended with the encoded↔decoded pair so
     apply_mods.py resolves the decoded mod-asset path to the new cooked
     destination.
  4. UsedRscList.ot — the engine's startup resource manifest — gets a
     3-line triplet appended for the new entity. The file is shipped via
     the apply_mods.py `_root/` channel (top-level install-dir override
     with the same backup/restore semantics as cooked overrides). Without
     this, the engine's resource-hashmap lookup (FUN_140487040) returns
     0 for the new path and slot 7 falls through to the live-loader
     substitute. With it, the lookup returns a real handle and slot 7
     renders our owned cooked file.
  5. Engine cache keys by path. The new path is distinct, so the file
     becomes an independent instance — every subsequent edit to it
     leaves the original Friend_List_Recent untouched.

Why no GUID regeneration: the engine resolves picker target-GUIDs scoped
to the spawn parent (verified Phase 1 — two slots pointing at the same
GUID coexist cleanly). So byte-cloning is safe and the live redirect in
loader/src/hook_engine.cpp falls through to the real handle once the file
exists.

Follow-up (next session):
  - identify oC2dElementDesc bounds in this file and shrink to slot
  - strip / rebind FriendsListUiControllerEntityCpntSettings so rows show
    mod names instead of Steam friends
  - per-row click identity (Steam ID -> mod ID mapping)
"""

from __future__ import annotations

from rsmm.engine.paths import (
    REPO_ROOT as REPO_DIR,
    DATA_DIR,
    MODS_DIR,
    ASSET_MAP_JSON,
    ASSET_MAP_CSV,
    DEFAULT_GAME_DIR as DEFAULT_GAME,
    COOKING_SUBDIR,
)
import argparse
import json
import shutil
import sys
from pathlib import Path


# Source: Friend_List_Recent — slot-positioned layout (renders cleanly
# inside the Mods slot, not as a centered fullscreen modal like
# Friend_List_Invite did). The recent-players row list is usually empty
# for solo play, but the bottom action buttons (Add/Report/Block/Back)
# remain interactive and fire their own engine methods. The
# `"Invite friend to party"` click-signal does not fire here; the click
# pipeline relies on the multi-signal detection added in
# loader/src/hook_engine.cpp.
SRC_ENCODED = (
    "MzidisFqiidzyv/KgxqJdv/"
    "Wll_Brrm_Tgyqv!Frbdgl!Vudqzt_Gdvi_Lqbqzi"
    ".qzidis.ri.MzidisFqiidzyvLqvrwubq.yqz"
)

# Destination: Mods_List under the same Social/ subtree. Encoded via
# src/rsmm/engine/cipher.py — verified round-trip against the asset-map.
DEST_ENCODED = (
    "MzidisFqiidzyv\\KgxqJdv\\"
    "Wll_Brrm_Tgyqv!Frbdgl!Hrtv_Gdvi"
    ".qzidis.ri.MzidisFqiidzyvLqvrwubq.yqz"
)
DEST_DECODED = (
    "EntitySettings\\GameUis\\All_Book_Pages\\Social\\"
    "Mods_List.entity.ot.EntitySettingsResource.gen"
)

# Path inside the mod's assets/ tree (forward slashes — apply_mods.py
# normalizes via .as_posix()).
MOD_ASSET_REL = (
    "EntitySettings/GameUis/All_Book_Pages/Social/"
    "Mods_List.entity.ot.EntitySettingsResource.gen"
)

# UsedRscList.ot — engine's startup resource manifest. Lives at the
# top of the install dir (DarkTalesResources/UsedRscList.ot). apply_mods.py
# treats paths starting with `_root/` as install-dir overrides.
USEDRSCLIST_GAME_REL = "DarkTalesResources/UsedRscList.ot"
USEDRSCLIST_MOD_REL  = "_root/DarkTalesResources/UsedRscList.ot"

# Triplet appended for the new entity. Format mirrors existing entries
# (see lines around Friend_List_Recent in UsedRscList.ot): top-level
# dir name, short encoded path (decoded `\` preserved), full encoded
# path under EntitySettings (sub-dirs collapsed with `!`).
TRIPLET_LINES = [
    "MzidisFqiidzyv",
    "KgxqJdv\\Wll_Brrm_Tgyqv\\Frbdgl\\Hrtv_Gdvi.qzidis.ri",
    "MzidisFqiidzyv\\KgxqJdv\\Wll_Brrm_Tgyqv!Frbdgl!Hrtv_Gdvi.qzidis.ri.MzidisFqiidzyvLqvrwubq.yqz",
]
TRIPLET_PROBE = TRIPLET_LINES[2]   # uniquely identifies our triplet


def patch_usedrsclist(game_dir: Path, mod_dir: Path,
                       dry_run: bool) -> bool:
    """Read the game's UsedRscList.ot, append our triplet if not present,
    write the patched copy under the mod's _root/ tree so apply_mods.py
    installs it on top of the real file (with backup).

    Returns True if a patched copy was produced (or would be in dry-run).
    """
    src = game_dir / USEDRSCLIST_GAME_REL
    if not src.is_file():
        print(f"  warning: UsedRscList.ot missing at {src}", file=sys.stderr)
        return False

    text = src.read_text(encoding="utf-8", errors="replace")
    if not text.endswith("\n"):
        text += "\n"
    if TRIPLET_PROBE in text:
        # Source already has our triplet (e.g. previous apply pass left
        # our patched copy installed and the user hasn't run
        # --restore-all). Don't re-append — duplicate lines would
        # accumulate. Just ship the current source as-is so the mod
        # remains reproducible against the patched install.
        print("  UsedRscList: triplet already present, no append")
        patched = text
    else:
        patched = text + "\n".join(TRIPLET_LINES) + "\n"

    out = mod_dir / "assets" / Path(USEDRSCLIST_MOD_REL)
    if dry_run:
        print(f"  (dry-run) would write {out} ({len(patched)} bytes)")
        return True
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(patched, encoding="utf-8")
    print(f"  UsedRscList: wrote {out} ({len(patched)} bytes; "
          f"appended +{len(patched) - len(text) + 1} bytes)")
    return True


def update_asset_map(repo: Path, encoded: str, decoded: str,
                     dry_run: bool) -> bool:
    """Add the encoded→decoded pair to asset_map.json + asset_map.csv.

    Returns True if the map was changed.
    """
    j = ASSET_MAP_JSON
    raw = json.loads(j.read_text(encoding="utf-8"))
    if raw.get(encoded) == decoded:
        print(f"  asset_map.json already has {encoded}")
        return False
    if encoded in raw:
        print(f"  asset_map.json conflict on {encoded}: "
              f"{raw[encoded]!r} vs {decoded!r}", file=sys.stderr)
        return False
    raw[encoded] = decoded
    if dry_run:
        print(f"  (dry-run) would add asset_map.json: {encoded} -> {decoded}")
        return True
    j.write_text(json.dumps(raw, indent=2, sort_keys=True), encoding="utf-8")
    print(f"  asset_map.json + {encoded}")

    # Mirror into the CSV if present (some tools rebuild from it).
    c = ASSET_MAP_CSV
    if c.exists():
        with c.open("a", encoding="utf-8") as f:
            f.write(f"{encoded},{decoded}\n")
        print(f"  asset_map.csv  + {encoded}")
    return True


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--game-dir", type=Path, default=DEFAULT_GAME)
    ap.add_argument("--mod-id", default="SocialModsPage")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    cooking = args.game_dir / COOKING_SUBDIR
    src = cooking / SRC_ENCODED
    if not src.is_file():
        print(f"source missing: {src}", file=sys.stderr)
        return 1
    src_size = src.stat().st_size

    mod_dir = MODS_DIR / args.mod_id
    if not mod_dir.is_dir():
        print(f"mod dir missing: {mod_dir}", file=sys.stderr)
        return 1

    dest = mod_dir / "assets" / Path(MOD_ASSET_REL)
    print(f"src        : {src}  ({src_size} bytes)")
    print(f"mod asset  : {dest}")
    print(f"decoded    : {DEST_DECODED}")
    print(f"encoded    : {DEST_ENCODED}")

    if args.dry_run:
        update_asset_map(REPO_DIR, DEST_ENCODED, DEST_DECODED, dry_run=True)
        patch_usedrsclist(args.game_dir, mod_dir, dry_run=True)
        print("(dry-run) no files written")
        return 0

    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(src, dest)
    print(f"wrote {dest} ({dest.stat().st_size} bytes)")

    update_asset_map(REPO_DIR, DEST_ENCODED, DEST_DECODED, dry_run=False)
    patch_usedrsclist(args.game_dir, mod_dir, dry_run=False)

    print()
    print("Next:")
    print("  1) ./rsmm apply            # installs cooked file + UsedRscList")
    print("  2) Launch game, Social -> Mods (slot 7).")
    print("     Loader trace should show:")
    print("       redirect path='...Mods_List...' real=0x<nonzero>")
    print("     i.e. real handle wins over substitute (file now exists).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
