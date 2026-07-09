"""`rsmm intents` — consume in-game mod-menu intents written by the loader.

    rsmm intents list  [--game-dir DIR]                 show pending intents
    rsmm intents apply [--game-dir DIR] [--mods-dir DIR] [--no-apply] [--keep]
    rsmm intents clear [--game-dir DIR]                 drop pending intents

The loader (rsmm._internal.intent_write, surfaced as R.mods.request) appends
one JSON object per line to `<cooking>/.rsmm_intents.jsonl` — the game runs
under Proton and cannot invoke the host CLI itself. `apply` executes each
intent (enable/disable flip the mod's manifest `enabled`; uninstall removes
the mod folder), re-runs `rsmm apply` so the install reflects the change, and
deletes the intent file. Ops the loader already validated are re-validated
here; the file is user-writable and not trusted.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

from ..engine import paths as P

INTENTS_FILE = ".rsmm_intents.jsonl"
_OPS = ("enable", "disable", "uninstall")
_MOD_ID_RE = re.compile(r"^(?!\.)(?!.*\.\.)[A-Za-z0-9._-]{1,63}$")


def intents_path(game_dir: Path) -> Path:
    return game_dir / "DarkTalesResources" / "_Cooking" / INTENTS_FILE


def read_intents(path: Path) -> tuple[list[dict], list[str]]:
    """Parse the JSONL file -> (valid intents, rejected-line descriptions)."""
    intents: list[dict] = []
    rejected: list[str] = []
    if not path.is_file():
        return intents, rejected
    for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            rejected.append(f"line {i}: not JSON")
            continue
        op = obj.get("op") if isinstance(obj, dict) else None
        mod = obj.get("mod") if isinstance(obj, dict) else None
        if op not in _OPS or not isinstance(mod, str) or not _MOD_ID_RE.match(mod):
            rejected.append(f"line {i}: invalid intent {line[:80]!r}")
            continue
        intents.append({"op": op, "mod": mod, "ts": obj.get("ts")})
    return intents, rejected


def set_mod_enabled(mods_dir: Path, mod_id: str, enabled: bool) -> str:
    """Flip `enabled` in mods/<id>/manifest.toml. Returns a status word."""
    manifest = mods_dir / mod_id / "manifest.toml"
    if not manifest.is_file():
        return "missing"
    text = manifest.read_text(encoding="utf-8")
    want = f"enabled = {'true' if enabled else 'false'}"
    # Replace an existing top-level `enabled` assignment (any spacing)…
    new, n = re.subn(r"(?m)^(enabled\s*=\s*)(true|false)\s*$",
                     lambda m: m.group(1) + ("true" if enabled else "false"),
                     text, count=1)
    if n == 0:
        # …or insert one right after the [mod] header.
        new, n = re.subn(r"(?m)^\[mod\]\s*$", "[mod]\n" + want, text, count=1)
        if n == 0:
            return "no-mod-table"
    if new == text:
        return "unchanged"
    manifest.write_text(new, encoding="utf-8")
    return "ok"


def uninstall_mod(mods_dir: Path, mod_id: str) -> str:
    target = (mods_dir / mod_id).resolve()
    try:
        target.relative_to(mods_dir.resolve())
    except ValueError:
        return "invalid"
    if not target.is_dir():
        return "missing"
    shutil.rmtree(target)
    return "ok"


def _game_dir(args: argparse.Namespace) -> Path | None:
    game_dir = Path(args.game_dir) if args.game_dir else P.default_game_dir()
    if not (game_dir / "DarkTalesResources" / "_Cooking").is_dir():
        print(f"error: cooking dir not found under {game_dir}", file=sys.stderr)
        return None
    return game_dir


def cmd_list(args: argparse.Namespace) -> int:
    game_dir = _game_dir(args)
    if game_dir is None:
        return 2
    path = intents_path(game_dir)
    intents, rejected = read_intents(path)
    if not intents and not rejected:
        print("no pending intents.")
        return 0
    for it in intents:
        print(f"{it['op']:<9} {it['mod']}")
    for r in rejected:
        print(f"rejected  {r}", file=sys.stderr)
    return 0


def cmd_clear(args: argparse.Namespace) -> int:
    game_dir = _game_dir(args)
    if game_dir is None:
        return 2
    path = intents_path(game_dir)
    if path.is_file():
        path.unlink()
        print(f"cleared {path}")
    else:
        print("no pending intents.")
    return 0


def cmd_apply(args: argparse.Namespace) -> int:
    game_dir = _game_dir(args)
    if game_dir is None:
        return 2
    mods_dir = Path(args.mods_dir) if args.mods_dir else P.mods_dir()
    path = intents_path(game_dir)
    intents, rejected = read_intents(path)
    for r in rejected:
        print(f"rejected  {r}", file=sys.stderr)
    if not intents:
        print("no pending intents.")
        return 0

    # Last intent per mod wins (a menu toggle flipped twice = the final state).
    latest: dict[str, dict] = {}
    for it in intents:
        latest[it["mod"]] = it

    failures = 0
    changed = False
    for it in latest.values():
        op, mod = it["op"], it["mod"]
        if op == "uninstall":
            status = uninstall_mod(mods_dir, mod)
        else:
            status = set_mod_enabled(mods_dir, mod, op == "enable")
        ok = status in ("ok", "unchanged")
        changed = changed or status == "ok"
        failures += 0 if ok else 1
        print(f"{op:<9} {mod}: {status}")

    if changed and not args.no_apply:
        # Refresh the in-game menu page first so the new enabled states are
        # what the rebuilt page shows, then re-apply everything.
        if (mods_dir / "RSMMMenu").is_dir():
            menu_cmd = P.self_cmd(["menu", "build", "--game-dir", str(game_dir),
                                   "--mods-dir", str(mods_dir)])
            print(f"running: {' '.join(menu_cmd)}")
            if subprocess.run(menu_cmd, cwd=P.REPO_ROOT, check=False).returncode != 0:
                print("warning: rsmm menu build failed; page list may be stale",
                      file=sys.stderr)
        cmd = P.self_cmd(["apply"])
        print(f"running: {' '.join(cmd)}")
        rc = subprocess.run(cmd, cwd=P.REPO_ROOT, check=False).returncode
        if rc != 0:
            print(f"error: rsmm apply exited {rc}", file=sys.stderr)
            return rc

    if not args.keep and failures == 0:
        path.unlink(missing_ok=True)
    elif failures:
        print(f"{failures} intent(s) failed; keeping {path}", file=sys.stderr)
    return 1 if failures else 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="rsmm intents",
                                 description="Consume in-game mod-menu intents")
    sub = ap.add_subparsers(dest="cmd", required=True)

    ls = sub.add_parser("list", help="show pending intents")
    ls.add_argument("--game-dir", help="Ravenswatch install dir (auto-detected)")
    ls.set_defaults(fn=cmd_list)

    app = sub.add_parser("apply", help="execute pending intents, then rsmm apply")
    app.add_argument("--game-dir", help="Ravenswatch install dir (auto-detected)")
    app.add_argument("--mods-dir", help="mods directory (default: repo mods/)")
    app.add_argument("--no-apply", action="store_true",
                     help="perform the ops but skip the final `rsmm apply`")
    app.add_argument("--keep", action="store_true",
                     help="do not delete the intent file afterwards")
    app.set_defaults(fn=cmd_apply)

    cl = sub.add_parser("clear", help="drop pending intents without applying")
    cl.add_argument("--game-dir", help="Ravenswatch install dir (auto-detected)")
    cl.set_defaults(fn=cmd_clear)

    args = ap.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
