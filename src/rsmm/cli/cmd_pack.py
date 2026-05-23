"""rsmm pack — bundle a mod for distribution."""

from __future__ import annotations

import hashlib
import shutil
import sys
from pathlib import Path

from rsmm.engine.asset_map import decoded_to_encoded
from rsmm.engine.paths import COOKING_SUBDIR, DATA_DIR, DEFAULT_GAME_DIR, DIST_DIR, MODS_DIR

_USAGE = (
    "usage: rsmm pack <id> [--allow-vanilla]\n"
    "\n"
    "Bundle mods/<id>/ into dist/<id>.zip.\n"
    "\n"
    "  <id>              mod folder name under mods/\n"
    "  --allow-vanilla   skip the copyright safety check (personal backups only)\n"
)


def _vanilla_offenders(mod_dir: Path) -> list[tuple[str, str]]:
    """Return [(relpath, reason)] for mod files that are byte-identical to
    the original game asset they sit at.
    """
    def sha256(p: Path) -> str:
        h = hashlib.sha256()
        with open(p, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h.update(chunk)
        return h.hexdigest()

    cooking = DEFAULT_GAME_DIR / COOKING_SUBDIR
    uncooked = DATA_DIR / "uncooked"
    enc_map = decoded_to_encoded() if cooking.exists() else {}
    offenders: list[tuple[str, str]] = []

    assets = mod_dir / "assets"
    if assets.is_dir():
        for f in assets.rglob("*"):
            if not f.is_file():
                continue
            rel = f.relative_to(assets).as_posix()
            mod_hash = sha256(f)
            encoded = enc_map.get(rel)
            if encoded:
                orig = cooking / encoded.replace("\\", "/")
                bak = orig.with_suffix(orig.suffix + ".rsmm.bak")
                src = bak if bak.exists() else orig
                if src.exists() and sha256(src) == mod_hash:
                    offenders.append((f"assets/{rel}", "matches original cooked asset"))
                    continue
            mirror = uncooked / rel
            if mirror.exists() and mirror.is_file() and sha256(mirror) == mod_hash:
                offenders.append((f"assets/{rel}", "matches data/uncooked/ mirror"))

    root = mod_dir / "_root"
    if root.is_dir():
        game_root = DEFAULT_GAME_DIR
        for f in root.rglob("*"):
            if not f.is_file():
                continue
            rel = f.relative_to(root).as_posix()
            orig = game_root / rel
            if orig.exists() and orig.is_file() and sha256(orig) == sha256(f):
                offenders.append((f"_root/{rel}", "matches game install file"))

    return offenders


def main(argv: list[str] | None = None) -> int:
    if argv is None:
        argv = sys.argv[1:]
    allow_vanilla = False
    args = []
    for a in argv:
        if a in ("-h", "--help"):
            print(_USAGE)
            return 0
        if a == "--allow-vanilla":
            allow_vanilla = True
        else:
            args.append(a)
    if len(args) != 1:
        print(_USAGE, file=sys.stderr)
        return 2
    mod_id = args[0]
    src = MODS_DIR / mod_id
    if not src.is_dir():
        print(f"no such mod: {src}", file=sys.stderr)
        return 1
    if not allow_vanilla:
        offenders = _vanilla_offenders(src)
        if offenders:
            print(
                f"refusing to pack {mod_id}: contains files byte-identical to original "
                f"game assets — that's redistribution of copyrighted content, not a mod.",
                file=sys.stderr,
            )
            for rel, why in offenders[:20]:
                print(f"  {rel}  ({why})", file=sys.stderr)
            if len(offenders) > 20:
                print(f"  ... and {len(offenders) - 20} more", file=sys.stderr)
            print(
                "\nfix: replace each listed file with your own modified bytes, or "
                "delete it from the mod. authors must ship only their changes, not "
                "the originals. override with --allow-vanilla only for personal "
                "backups never distributed publicly.",
                file=sys.stderr,
            )
            return 1
    DIST_DIR.mkdir(exist_ok=True)
    out_base = DIST_DIR / mod_id
    archive = shutil.make_archive(str(out_base), "zip", root_dir=MODS_DIR, base_dir=mod_id)
    print(f"Wrote {archive}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
