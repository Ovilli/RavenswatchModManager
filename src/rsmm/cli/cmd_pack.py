"""rsmm pack — bundle a mod for distribution."""

from __future__ import annotations

import re
import sys
import zipfile
from pathlib import Path

from rsmm.engine.asset_map import decoded_to_encoded
from rsmm.engine.hashing import sha256_file as sha256
from rsmm.engine.paths import (
    COOKING_SUBDIR,
    DATA_DIR,
    DEFAULT_GAME_DIR,
    MODS_DIR,
    dist_out_dir,
)
from rsmm.sdk import archive

_ID_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_-]*$")

# `enabled = <bool>` as it appears in a manifest, alignment padding and all.
# Anchored to the line so a commented-out copy or an `enabled` key nested in
# another table is not what gets rewritten (the [mod] section is isolated
# first, see _stamp_enabled).
# CRLF-safe by construction: the manifest is read with newline="" so a Windows
# author's line endings survive the round trip, which means every pattern here
# has to tolerate a \r sitting where it expects end-of-line. `\s` would swallow
# it (and the blank lines after it), so runs of horizontal space are spelled
# [^\S\r\n] throughout.
_MOD_TABLE_RE = re.compile(r"^\[mod\][^\S\r\n]*\r?\n?", re.MULTILINE)
_TABLE_RE = re.compile(r"^\[", re.MULTILINE)
_ENABLED_RE = re.compile(
    r"^(?P<lhs>enabled[^\S\r\n]*=[^\S\r\n]*)(?:true|false)"
    r"(?P<rest>[^\S\r\n]*(?:#[^\r\n]*)?\r?)$",
    re.MULTILINE)


def _stamp_enabled(text: str) -> str | None:
    """Return `text` with `[mod].enabled` forced to true, or None if it
    already is (or the key is absent, which the loader reads as true).

    A mod's `enabled` flag is the PACKING user's local state, not a property
    of the mod -- the same class of thing as config.toml, which _is_local_only
    already drops. Shipping it meant an author who happened to pack with the
    mod switched off published an archive that installs, applies, and then
    does nothing: `_sync_mod_manifests` copies the manifest and DELETES
    init.lua for a disabled mod, so the game logs `scan_mods found=1` and no
    init line, which reads as a broken mod rather than an off one. That is
    exactly what happened to damage-meter 1.2.2 on 2026-08-24 -- installed
    into a desktop profile from a zip packed while it was disabled, and
    diagnosed through three game restarts.

    Only the `[mod]` table is touched: `enabled` is a plausible key name for a
    mod's own config schema or an [overlay] block, and rewriting one of those
    would change what the mod DOES.
    """
    start = _MOD_TABLE_RE.search(text)
    if not start:
        return None
    # The [mod] table runs to the next table header, or to EOF. Slicing on the
    # header rather than on the first "\n[" matters: a manifest may open with a
    # comment block, in which case the first bracket IS [mod] and a naive split
    # would search an empty section and stamp nothing.
    rest = text[start.end():]
    nxt = _TABLE_RE.search(rest)
    body = rest[:nxt.start()] if nxt else rest
    stamped, n = _ENABLED_RE.subn(
        lambda m: f"{m.group('lhs')}true{m.group('rest')}", body, count=1)
    if not n or stamped == body:
        return None
    return text[:start.end()] + stamped + (rest[nxt.start():] if nxt else "")


def _is_local_only(rel: Path) -> bool:
    """True for files that belong to the installing user, not the mod.

    config.toml holds the packing user's edited values (config_schema.toml
    ships the defaults); .rsmm_state* is the runtime KV store the loader
    writes next to init.lua; .rsmm_emitted.json is apply-time bookkeeping
    for stale-asset GC, regenerated on the installing machine.
    """
    if "__pycache__" in rel.parts:
        return True
    name = rel.name
    return (
        name == "config.toml"
        or name == ".rsmm_emitted.json"
        or name.startswith(".rsmm_state")
        or name.endswith(".tmp")
    )

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
    if not _ID_RE.match(mod_id):
        print(f"invalid mod id: {mod_id!r}", file=sys.stderr)
        return 1
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
    members: list[tuple[Path, str]] = []
    for f in sorted(src.rglob("*")):
        if not f.is_file():
            continue
        rel = f.relative_to(src)
        if _is_local_only(rel):
            continue
        members.append((f, f"{mod_id}/{rel.as_posix()}"))

    # Same policy the installers enforce, applied before anything is written.
    # Packing a mod that every user's `rsmm install` will refuse is a failure
    # the author should see here, not learn about from bug reports.
    blocked, overlays = archive.classify_members(name for _f, name in members)
    if blocked:
        print(f"refusing to pack: {archive.blocked_message(mod_id, blocked)}",
              file=sys.stderr)
        print("\nmods ship data, not executables. `rsmm install` and the desktop "
              "app both refuse these, so a published archive containing them "
              "cannot be installed by anyone.", file=sys.stderr)
        return 1
    for rel in overlays:
        print(f"  [WARN] {mod_id} overwrites game install root file: {rel}",
              file=sys.stderr)

    out_dir = dist_out_dir()
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"{mod_id}.zip"
    stamped = False
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
        for f, name in members:
            if f.name == "manifest.toml" and f.parent == src:
                try:
                    # newline="" disables translation in BOTH directions: the
                    # text keeps whatever the author wrote, so a manifest this
                    # function declines to stamp is byte-identical to the file
                    # on disk, and a stamped one differs only in the flag.
                    with f.open(encoding="utf-8", newline="") as fh:
                        text = fh.read()
                except (OSError, UnicodeDecodeError):
                    text = None
                fixed = _stamp_enabled(text) if text is not None else None
                if fixed is not None:
                    # Keep the source file's timestamp: the archive should differ
                    # from a pack of the same tree only where the flag differs.
                    info = zipfile.ZipInfo.from_file(f, name)
                    info.compress_type = zipfile.ZIP_DEFLATED
                    zf.writestr(info, fixed)
                    stamped = True
                    continue
            zf.write(f, name)
    if stamped:
        print(f"  [note] {mod_id} is disabled locally; packed as enabled "
              f"(the flag is your state, not the mod's)")
    print(f"Wrote {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
