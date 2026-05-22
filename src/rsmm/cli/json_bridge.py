"""
rsmm json — machine-readable bridge for the desktop / web UI.

Subcommands:

    rsmm json list                  list installed mods (mods/ dir)
    rsmm json apply [--dry-run]     run apply, return {ok, code, stdout, stderr}
    rsmm json restore-all           restore every active override
    rsmm json build                 build asset map + loader DLL + merge + apply
    rsmm json doctor                run health check, return structured results
    rsmm json run                   launch the game via steam://rungameid
    rsmm json run --vanilla         restore original files, then launch

All commands emit a single JSON object/array on stdout (UTF-8, no trailing
newline). Stderr is forwarded for diagnostics. Exit code is 0 on success.
"""
from __future__ import annotations

import argparse
import contextlib
import json
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path
from typing import Any

from rsmm.engine.paths import MODS_DIR, REPO_ROOT
from rsmm.cli.apply_mods import clear_runtime_mods, find_game_dir


def _emit(value: Any) -> int:
    sys.stdout.write(json.dumps(value, default=str, separators=(",", ":")))
    sys.stdout.flush()
    return 0


def _read_manifest(path: Path) -> dict[str, Any] | None:
    try:
        with path.open("rb") as f:
            return tomllib.load(f)
    except Exception:
        return None


def cmd_list() -> int:
    items: list[dict[str, Any]] = []
    if not MODS_DIR.is_dir():
        return _emit([])
    for entry in sorted(MODS_DIR.iterdir()):
        if not entry.is_dir() or entry.name.startswith("_"):
            continue
        raw = _read_manifest(entry / "manifest.toml")
        if raw is None:
            continue
        # Manifests use [mod] table for metadata; older ones inline at root.
        manifest = raw.get("mod") if isinstance(raw.get("mod"), dict) else raw
        items.append({
            "id": manifest.get("id", entry.name),
            "slug": entry.name,
            "name": manifest.get("name", entry.name),
            "version": str(manifest.get("version", "0.0.0")),
            "author": manifest.get("author"),
            "summary": manifest.get("summary") or manifest.get("description"),
            "license": manifest.get("license"),
            "tags": manifest.get("tags") or [],
            "enabled": bool(manifest.get("enabled", True)),
            "path": str(entry),
        })
    return _emit(items)


def _collect_rsmm(args: list[str]) -> dict[str, Any]:
    cmd = [str(REPO_ROOT / "rsmm"), *args]
    try:
        proc = subprocess.run(
            cmd,
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError as e:
        return {"ok": False, "code": 127, "stdout": "", "stderr": str(e)}
    return {
        "ok": proc.returncode == 0,
        "code": proc.returncode,
        "stdout": proc.stdout,
        "stderr": proc.stderr,
    }


def _run_rsmm(args: list[str]) -> int:
    """Spawn `./rsmm <args>` and emit {ok, code, stdout, stderr}."""
    return _emit(_collect_rsmm(args))


def cmd_apply(rest: list[str]) -> int:
    return _run_rsmm(["apply", *rest])


def cmd_restore_all() -> int:
    return _run_rsmm(["apply", "--restore-all"])


def cmd_build(rest: list[str]) -> int:
    return _run_rsmm(["build", *rest])


def _uninstall_loader_runtime(game_dir: Path) -> tuple[bool, str]:
    """Best-effort cleanup of loader artifacts for a pure vanilla launch."""
    notes: list[str] = []
    loader_dll = game_dir / "winhttp.dll"
    real_dll = game_dir / "winhttp_real.dll"
    asset_map = game_dir / "asset_map.json"
    rsmm_dir = game_dir / "rsmm"

    try:
        if real_dll.exists():
            if loader_dll.exists():
                loader_dll.unlink()
            shutil.move(str(real_dll), str(loader_dll))
            notes.append("restored stock winhttp.dll")
        elif loader_dll.exists():
            loader_dll.unlink()
            notes.append("removed rsmm winhttp.dll")

        if asset_map.exists():
            asset_map.unlink()
            notes.append("removed asset_map.json")

        if rsmm_dir.exists():
            shutil.rmtree(rsmm_dir)
            notes.append("removed rsmm runtime dir")
    except OSError as e:
        return False, str(e)

    if not notes:
        notes.append("loader artifacts already absent")
    return True, ", ".join(notes)


def cmd_run(rest: list[str]) -> int:
    """Launch the game. --vanilla restores originals first."""
    args = ["run", "--force"]
    filtered = [a for a in rest if a != "--vanilla"]
    if len(filtered) < len(rest):
        restore = _collect_rsmm(["apply", "--restore-all"])
        if not restore["ok"]:
                        return _emit(restore)
        game_dir = find_game_dir()
        if game_dir is None:
            return _emit({
                "ok": False,
                "code": 1,
                "stdout": "",
                "stderr": "Could not autodetect Ravenswatch install to clear runtime mods.",
            })
        with contextlib.redirect_stdout(sys.stderr):
            cleared = clear_runtime_mods(game_dir)
        if not cleared:
            return _emit({
                "ok": False,
                "code": 1,
                "stdout": "",
                "stderr": f"Failed to clear runtime mods dir: {game_dir / 'mods'}",
            })
        ok, detail = _uninstall_loader_runtime(game_dir)
        if not ok:
            return _emit({
                "ok": False,
                "code": 1,
                "stdout": "",
                "stderr": f"Failed to uninstall loader artifacts: {detail}",
            })
        print(f"Vanilla cleanup: {detail}", file=sys.stderr)
        args.extend(["--force", "--clear-launch-options"])
    return _run_rsmm([*args, *filtered])


def cmd_doctor() -> int:
    """
    Run doctor as a subprocess so the UI can display the raw, coloured
    output verbatim, but also parse a coarse OK/WARN/FAIL line tally
    from the printed summary for at-a-glance status.
    """
    cmd = [str(REPO_ROOT / "rsmm"), "doctor"]
    try:
        proc = subprocess.run(
            cmd, cwd=REPO_ROOT, capture_output=True, text=True, check=False,
        )
    except FileNotFoundError as e:
        return _emit({"ok": False, "code": 127, "stdout": "", "stderr": str(e),
                      "checks": []})

    checks: list[dict[str, Any]] = []
    for raw in proc.stdout.splitlines():
        line = raw.strip()
        if not line:
            continue
        for tag in ("OK", "WARN", "FAIL"):
            prefix = f"[{tag}]"
            if line.startswith(prefix):
                checks.append({
                    "status": tag,
                    "ok": tag == "OK",
                    "label": line[len(prefix):].strip(),
                })
                break

    return _emit({
        "ok": proc.returncode == 0,
        "code": proc.returncode,
        "stdout": proc.stdout,
        "stderr": proc.stderr,
        "checks": checks,
    })


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="rsmm json",
        description="Machine-readable JSON bridge for the desktop / web UI.",
    )
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list", help="list installed mods")
    p_apply = sub.add_parser("apply", help="run apply")
    p_apply.add_argument("--dry-run", action="store_true")
    p_apply.add_argument("--force", action="store_true")
    p_apply.add_argument("--no-merge", action="store_true")
    sub.add_parser("restore-all", help="restore every active override")
    sub.add_parser("build", help="build asset map + loader + merge + apply")
    sub.add_parser("doctor", help="system health check")
    p_run = sub.add_parser("run", help="launch the game")
    p_run.add_argument("--vanilla", action="store_true", help="restore originals before launching")

    args = ap.parse_args(argv)
    if args.cmd == "list":
        return cmd_list()
    if args.cmd == "apply":
        rest = []
        if args.dry_run:
            rest.append("--dry-run")
        if args.force:
            rest.append("--force")
        if args.no_merge:
            rest.append("--no-merge")
        return cmd_apply(rest)
    if args.cmd == "restore-all":
        return cmd_restore_all()
    if args.cmd == "build":
        return cmd_build([])
    if args.cmd == "doctor":
        return cmd_doctor()
    if args.cmd == "run":
        rest = []
        if args.vanilla:
            rest.append("--vanilla")
        return cmd_run(rest)
    ap.error(f"unknown subcommand: {args.cmd}")
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
