"""
rsmm watch — live re-apply on mods/ change.

Polls mods/ + dist/winhttp.dll mtimes every <interval> seconds. On change it
waits for the save to settle, names the mods that changed, lints them, and
runs the applier (which rebuilds mods/_merged/ and syncs each mod's Lua into
the game). A changed mod with lint errors holds the apply back: a manifest
caught half-written would otherwise be skipped by the applier, which pulls
the mod out of the game until the next save. Interrupt with Ctrl-C.

For headless / desktop use; not meant to run as a service.
"""

from __future__ import annotations

import argparse
import contextlib
import io
import json
import re
import signal
import subprocess
import sys
import time
import tomllib
from pathlib import Path

from rsmm.cli import _term
from rsmm.engine import paths as P
from rsmm.engine.paths import BACKUP_SUFFIX, COOKING_REL, DIST_DIR, self_cmd

_SIGINT = getattr(signal, "SIGINT", None)
_SIGTERM = getattr(signal, "SIGTERM", None)

_ST = _term.Style()
_DOT = " · "

#: Files `rsmm apply` itself writes inside a mod folder. Watching them made
#: every save apply twice: once for the edit, once for apply's own bookkeeping.
_APPLY_OWNED = (".rsmm_emitted.json", ".rsmm_emit_cache.json")
#: Editor swap/backup litter (vim, emacs, JetBrains) — a save, not an edit.
_EDITOR_LITTER = re.compile(r"(~|\.sw[a-p]|\.tmp|___jb_(tmp|old)___)$|^\.#|^4913$")
#: Most file names printed per changed mod before "+N more".
_NAMES_SHOWN = 3
#: Lint lines that mean "error"; warnings never hold an apply back.
_ERROR_TAG = re.compile(r"\[(FAIL|ERR|ERROR)\]")
#: lint_one's closing per-mod row, which repeats the error count.
_SUMMARY_ROW = re.compile(r"\(raw=\d+ patches=")
_ANSI = re.compile(r"\033\[[0-9;]*m")


def _emitted(mods_root: Path) -> set[Path]:
    """Every file a content emit wrote, per each mod's `.rsmm_emitted.json`.

    Apply rewrites these, so they are its output rather than the author's
    input; a change to one is not a reason to apply again.
    """
    out: set[Path] = set()
    if not mods_root.is_dir():
        return out
    for marker in mods_root.glob("*/.rsmm_emitted.json"):
        try:
            rels = json.loads(marker.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(rels, list):
            assets = marker.parent / "assets"
            out.update(assets / str(r) for r in rels)
    return out


def _ignored(rel: Path) -> bool:
    """True for a path under mods/ whose change is not an author's edit."""
    parts = rel.parts
    if not parts:
        return True
    # discover_mods skips `_`/`.`-prefixed folders (and `_merged` is apply's
    # own output), so nothing under them can change what gets applied.
    if parts[0].startswith(("_", ".")):
        return True
    if any(p in (".git", "__pycache__") for p in parts):
        return True
    name = parts[-1]
    return (name.endswith(BACKUP_SUFFIX) or name in _APPLY_OWNED
            or name.startswith(".rsmm_state") or bool(_EDITOR_LITTER.search(name)))


def _sig(p: Path) -> tuple[int, int]:
    # Size as well as mtime: on a coarse-clock filesystem two saves inside one
    # tick share an mtime, and the second would otherwise go unseen.
    st = p.stat()
    return st.st_mtime_ns, st.st_size


def _scan(roots: list[Path]) -> dict[str, tuple[int, int]]:
    out: dict[str, tuple[int, int]] = {}
    for r in roots:
        if not r.exists():
            continue
        if r.is_file():
            out[str(r)] = _sig(r)
            continue
        emitted = _emitted(r)
        for p in r.rglob("*"):
            if not p.is_file() or _ignored(p.relative_to(r)) or p in emitted:
                continue
            try:
                out[str(p)] = _sig(p)
            except OSError:
                pass
    return out


Snapshot = dict[str, tuple[int, int]]


def _changed(old: Snapshot, new: Snapshot) -> list[str]:
    """Paths added, removed or touched between two scans, sorted."""
    return sorted(k for k in old.keys() | new.keys() if old.get(k) != new.get(k))


def _settle(roots: list[Path], snap: Snapshot, pause: float,
            tries: int = 10) -> Snapshot:
    """Rescan until two scans agree, so one save of several files (or an
    editor that writes, renames and touches) triggers one apply, not three."""
    for _ in range(tries):
        time.sleep(pause)
        nxt = _scan(roots)
        if nxt == snap:
            break
        snap = nxt
    return snap


def _by_mod(paths: list[str], mods_root: Path) -> dict[str, list[str]]:
    """Group changed paths as {mod folder: [path inside it]}; anything outside
    mods/ (the loader DLL) is keyed by its own name."""
    out: dict[str, list[str]] = {}
    for raw in paths:
        p = Path(raw)
        try:
            rel = p.relative_to(mods_root)
        except ValueError:
            out.setdefault(f"{p.parent.name}/{p.name}", [])
            continue
        if len(rel.parts) < 2:
            continue                            # a stray file in mods/ itself
        out.setdefault(rel.parts[0], []).append(Path(*rel.parts[1:]).as_posix())
    return out


def _describe(groups: dict[str, list[str]], mods_root: Path) -> str:
    bits = []
    for name, files in sorted(groups.items()):
        if not files:
            bits.append(_ST.bold(name))
        elif not (mods_root / name).is_dir():
            bits.append(f"{_ST.bold(name)} {_ST.dim('(removed)')}")
        else:
            shown = ", ".join(files[:_NAMES_SHOWN])
            if len(files) > _NAMES_SHOWN:
                shown += f" +{len(files) - _NAMES_SHOWN} more"
            bits.append(f"{_ST.bold(name)} {_ST.dim(f'({shown})')}")
    return ", ".join(bits)


def _wants_lint(mod_dir: Path) -> bool:
    """Lint a changed mod unless its manifest parses and says it is disabled:
    apply leaves a disabled mod out anyway, and an unparseable manifest is
    exactly the half-saved file the gate exists for."""
    manifest = mod_dir / "manifest.toml"
    if not manifest.is_file():
        return False
    try:
        enabled = tomllib.loads(manifest.read_text(encoding="utf-8")) \
            .get("mod", {}).get("enabled", True)
    except (OSError, ValueError, AttributeError):
        return True
    return enabled is True or str(enabled).lower() in ("1", "true", "yes", "on")


def _lint_gate(mod_ids: list[str], mods_root: Path, log) -> list[str]:
    """Lint each changed, enabled mod. Return the ids with errors, after
    printing those errors; warnings are only counted."""
    from rsmm.cli.lint import lint_one

    blocked: list[str] = []
    for mod_id in mod_ids:
        mod_dir = mods_root / mod_id
        if not _wants_lint(mod_dir):
            continue
        buf = io.StringIO()
        try:
            with contextlib.redirect_stdout(buf):
                errs, warns = lint_one(mod_dir)
        except Exception as e:                  # noqa: BLE001 - a lint bug must not end the session
            log(_ST.warn(f"lint: could not check {mod_id} ({e}); applying anyway"))
            continue
        if not errs:
            if warns:
                log(_ST.dim(f"lint: {mod_id} ok, {warns} warning(s) "
                            f"(rsmm lint {mod_id})"))
            continue
        blocked.append(mod_id)
        log(f"{_ST.err('lint:')} {_ST.bold(mod_id)} has {errs} error(s)")
        keep = False
        for line in buf.getvalue().splitlines():
            plain = _ANSI.sub("", line)
            if _ERROR_TAG.search(plain) and not _SUMMARY_ROW.search(plain):
                keep = True
            elif plain.lstrip().startswith("["):
                keep = False                    # a warning or the summary row
            if keep and plain.strip():
                print(f"    {line.strip()}", flush=True)
    return blocked


def _run_apply(game_dir: Path, dry_run: bool, log) -> int:
    cmd = self_cmd(["apply"])
    if dry_run:
        cmd.append("--dry-run")
    cmd += ["--game-dir", str(game_dir)]
    log(_ST.dim(f"+ {' '.join(cmd)}"))
    rc = subprocess.call(cmd)
    if rc:
        log(f"{_ST.err(f'apply failed (exit {rc})')}{_ST.dim(_DOT)}"
            "fix what it reported and save again")
    else:
        log(_ST.ok("applied"))
    return rc


def main() -> int:
    ap = argparse.ArgumentParser(
        prog="rsmm watch",
        description="Watch mods/, lint what changed, and re-apply on every save",
    )
    ap.add_argument("--game-dir", type=Path, default=None,
                    help="Ravenswatch install dir (autodetected if omitted)")
    ap.add_argument("--interval", type=float, default=2.0,
                    help="seconds between scans (default 2)")
    ap.add_argument("--dry-run", action="store_true",
                    help="print plan only, do not modify the game install")
    ap.add_argument("--once", action="store_true",
                    help="check + apply once, then exit")
    ap.add_argument("--no-lint", action="store_true",
                    help="apply a change even when the mod it touches has "
                         "lint errors")
    args = ap.parse_args()

    def log(msg: str) -> None:
        print(f"{_ST.dim(time.strftime('[%H:%M:%S]'))} {msg}", flush=True)

    # Fail once up front rather than on every save for the rest of the session.
    game_dir = args.game_dir or P.default_game_dir()
    if not (game_dir / COOKING_REL).is_dir():
        print(f"no Ravenswatch install at {game_dir} — pass --game-dir "
              "(or set RSMM_GAME_DIR)", file=sys.stderr)
        return 1

    mods_root = P.mods_dir()
    roots = [mods_root, DIST_DIR / "winhttp.dll"]
    last = _scan(roots)
    log(f"watching {len(last)} file(s) under {mods_root} and dist/winhttp.dll")
    log("initial apply...")
    rc = _run_apply(game_dir, args.dry_run, log)
    if args.once:
        return rc

    stopped = False
    def _stop(_sig, _frm):
        nonlocal stopped
        stopped = True
        log("interrupted")
    if _SIGINT is not None:
        signal.signal(_SIGINT, _stop)
    if _SIGTERM is not None:
        signal.signal(_SIGTERM, _stop)

    while not stopped:
        time.sleep(args.interval)
        cur = _scan(roots)
        if cur == last:
            continue
        cur = _settle(roots, cur, min(0.5, args.interval))
        groups = _by_mod(_changed(last, cur), mods_root)
        # The baseline is what the author saved, taken BEFORE apply runs:
        # apply's own writes are filtered out of every scan, so an edit made
        # while a slow apply was cooking still shows up on the next tick.
        last = cur
        if not groups:
            continue
        log(f"changed: {_describe(groups, mods_root)}")
        if not args.no_lint:
            blocked = _lint_gate(
                [g for g in sorted(groups) if (mods_root / g).is_dir()],
                mods_root, log)
            if blocked:
                log(f"{_ST.warn('not applied')}{_ST.dim(_DOT)}the game keeps "
                    "the last good apply until the errors above are fixed")
                continue
        _run_apply(game_dir, args.dry_run, log)
    return 0


if __name__ == "__main__":
    sys.exit(main())
