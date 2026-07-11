"""`rsmm enable` / `rsmm disable` — toggle mods from the terminal.

    rsmm enable  <id>... [--only] [--no-apply] [--mods-dir DIR]
    rsmm enable  --all   [--no-apply] [--mods-dir DIR]
    rsmm disable <id>... [--no-apply] [--mods-dir DIR]
    rsmm disable --all   [--no-apply] [--mods-dir DIR]

Flips `enabled` in each mod's `manifest.toml` (same edit the in-game mod
menu performs via `rsmm intents apply`), then re-runs `rsmm apply` so the
game install reflects the change. `--no-apply` skips that final step.

`rsmm enable <id> --only` is the "test exactly this mod" shortcut: it
enables the listed mods and disables every other mod in one pass.

Mod ids are the directory names under `mods/` (case-sensitive).
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

from ..engine import paths as P
from .cmd_intents import set_mod_enabled


def _all_mod_ids(mods_dir: Path) -> list[str]:
    """Every directory under mods/ that carries a manifest.toml."""
    if not mods_dir.is_dir():
        return []
    return sorted(
        d.name for d in mods_dir.iterdir()
        if d.is_dir() and (d / "manifest.toml").is_file()
    )


def _flip(mods_dir: Path, mod_id: str, enabled: bool) -> bool:
    """Toggle one mod, print the outcome, return True unless it failed."""
    status = set_mod_enabled(mods_dir, mod_id, enabled)
    verb = "enable" if enabled else "disable"
    print(f"{verb:<8} {mod_id}: {status}")
    return status in ("ok", "unchanged")


def _run_apply() -> int:
    cmd = P.self_cmd(["apply"])
    print(f"running: {' '.join(cmd)}")
    return subprocess.run(cmd, cwd=P.REPO_ROOT, check=False).returncode


def main(argv: list[str] | None = None) -> int:
    if argv is None:
        argv = sys.argv[1:]
    # Dispatch passes the verb through as argv[0] (like `rsmm repo`).
    prog_verb = sys.argv[0] if sys.argv else "enable"
    verb = argv[0] if argv and argv[0] in ("enable", "disable") else prog_verb

    ap = argparse.ArgumentParser(
        prog=f"rsmm {verb}",
        description=f"{verb} mods by flipping `enabled` in their manifest.toml",
    )
    ap.add_argument("ids", nargs="*", metavar="mod-id",
                    help="mod directory name(s) under mods/")
    ap.add_argument("--all", action="store_true",
                    help=f"{verb} every mod under mods/")
    if verb == "enable":
        ap.add_argument("--only", action="store_true",
                        help="also disable every mod NOT listed")
    ap.add_argument("--no-apply", action="store_true",
                    help="flip manifests but skip the final `rsmm apply`")
    ap.add_argument("--mods-dir", help="mods directory (default: repo mods/)")

    args = ap.parse_args(argv[1:] if argv and argv[0] == verb else argv)
    enabled = verb == "enable"
    only = bool(getattr(args, "only", False))

    if args.all and (args.ids or only):
        ap.error("--all cannot be combined with mod ids or --only")
    if not args.all and not args.ids:
        ap.error("give at least one mod id, or --all")

    mods_dir = Path(args.mods_dir) if args.mods_dir else P.mods_dir()
    known = _all_mod_ids(mods_dir)
    if not known:
        print(f"error: no mods found under {mods_dir}", file=sys.stderr)
        return 2

    targets = known if args.all else list(dict.fromkeys(args.ids))
    unknown = [i for i in targets if i not in known]
    if unknown:
        print(f"error: unknown mod id(s): {', '.join(unknown)}", file=sys.stderr)
        print(f"known: {', '.join(known)}", file=sys.stderr)
        return 2

    failures = 0
    for mod_id in targets:
        failures += 0 if _flip(mods_dir, mod_id, enabled) else 1
    if only:
        for mod_id in known:
            if mod_id not in targets:
                failures += 0 if _flip(mods_dir, mod_id, False) else 1

    if failures:
        print(f"{failures} mod(s) failed; skipping apply", file=sys.stderr)
        return 1
    if args.no_apply:
        return 0
    rc = _run_apply()
    if rc != 0:
        print(f"error: rsmm apply exited {rc}", file=sys.stderr)
    return rc


if __name__ == "__main__":
    sys.exit(main())
