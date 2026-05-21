"""
rsmm watch — live re-apply on mods/ change.

Polls mods/ + dist/winhttp.dll mtimes every <interval> seconds. On
change: rebuilds mods/_merged/ from [[patch]] blocks, then runs the
applier. Interrupt with Ctrl-C.

For headless / desktop use; not meant to run as a service.
"""

from __future__ import annotations

import argparse
import signal
import subprocess
import sys
import time
from pathlib import Path

from rsmm.engine.paths import (
    DEFAULT_GAME_DIR as DEFAULT_GAME,
)
from rsmm.engine.paths import (
    DIST_DIR,
    MODS_DIR,
    REPO_ROOT,
)


def _scan(roots: list[Path]) -> dict[str, float]:
    out: dict[str, float] = {}
    for r in roots:
        if not r.exists():
            continue
        if r.is_file():
            out[str(r)] = r.stat().st_mtime
            continue
        for p in r.rglob("*"):
            if p.is_file():
                # Skip applier state + merged output (causes feedback loop).
                rel = str(p)
                if rel.endswith(".rsmm.bak") or rel.endswith(".rsmm_state.json"):
                    continue
                if "/_merged/" in rel.replace("\\", "/"):
                    continue
                try:
                    out[rel] = p.stat().st_mtime
                except OSError:
                    pass
    return out


def _run_apply(game_dir: Path, dry_run: bool, log) -> int:
    cmd = [sys.executable, str(REPO_ROOT / "rsmm"), "apply"]
    if dry_run:
        cmd.append("--dry-run")
    cmd += ["--game-dir", str(game_dir)]
    log(f"  + running: {' '.join(cmd)}")
    return subprocess.call(cmd)


def _sync_lua_and_manifest(game_dir: Path, log) -> int:
    """Copy each mod's init.lua + manifest.toml to <game>/mods/<id>/
    so the loader's hot-reload watcher sees the fresh files. Returns
    the number of files updated.
    """
    game_mods = game_dir / "mods"
    game_mods.mkdir(exist_ok=True)
    updated = 0
    if not MODS_DIR.is_dir():
        return 0
    for mod_dir in MODS_DIR.iterdir():
        if not mod_dir.is_dir() or mod_dir.name.startswith("_"):
            continue
        manifest = mod_dir / "manifest.toml"
        if not manifest.is_file():
            continue
        dst_dir = game_mods / mod_dir.name
        dst_dir.mkdir(exist_ok=True)
        for f in (manifest, mod_dir / "init.lua"):
            if not f.is_file():
                continue
            dst = dst_dir / f.name
            if not dst.is_file() or dst.stat().st_mtime < f.stat().st_mtime:
                dst.write_bytes(f.read_bytes())
                updated += 1
                log(f"  + synced {f.name} -> mods/{mod_dir.name}/")
    return updated


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Watch mods/ + rebuild + reapply on change"
    )
    ap.add_argument("--game-dir", type=Path, default=DEFAULT_GAME)
    ap.add_argument("--interval", type=float, default=2.0,
                    help="seconds between scans (default 2)")
    ap.add_argument("--dry-run", action="store_true",
                    help="print plan only, do not modify the game install")
    ap.add_argument("--once", action="store_true",
                    help="check + apply once, then exit")
    args = ap.parse_args()

    def log(msg: str) -> None:
        ts = time.strftime("%H:%M:%S")
        print(f"[{ts}] {msg}", flush=True)

    roots = [MODS_DIR, DIST_DIR / "winhttp.dll"]
    last = _scan(roots)
    log(f"watching {len(last)} file(s) under mods/ and dist/winhttp.dll")
    log("initial apply...")
    _run_apply(args.game_dir, args.dry_run, log)
    _sync_lua_and_manifest(args.game_dir, log)
    if args.once:
        return 0

    stopped = False
    def _stop(_sig, _frm):
        nonlocal stopped
        stopped = True
        log("interrupted")
    signal.signal(signal.SIGINT, _stop)

    while not stopped:
        time.sleep(args.interval)
        cur = _scan(roots)
        if cur == last:
            continue
        diff_n = (len(set(cur) - set(last))
                  + len(set(last) - set(cur))
                  + sum(1 for k in cur.keys() & last.keys()
                        if cur[k] != last[k]))
        log(f"change detected ({diff_n} file(s) added/removed/touched); reapplying")
        _run_apply(args.game_dir, args.dry_run, log)
        _sync_lua_and_manifest(args.game_dir, log)
        last = cur
    return 0


if __name__ == "__main__":
    sys.exit(main())
