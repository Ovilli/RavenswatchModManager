"""rsmm install-loader — copy winhttp.dll + SDK lib into the game install."""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

from rsmm.engine.paths import COOKING_SUBDIR, DEFAULT_GAME_DIR, REPO_ROOT

# Characters that have meaning in cmd.exe / powershell / bash. None of
# them are legal in real filesystem paths on any platform we ship to,
# so rejecting them prevents an attacker who can influence the
# `game-dir` argument from injecting shell metacharacters that the
# downstream .bat / .ps1 / .sh scripts would later expand.
_SHELL_METAS = ('"', "'", "`", "$", ";", "|", "&", "\n", "\r", "\0")


def _validate_game_dir(raw: str) -> Path:
    if any(m in raw for m in _SHELL_METAS):
        raise ValueError(f"game-dir contains shell metacharacters: {raw!r}")
    p = Path(raw)
    if not p.is_dir():
        raise ValueError(f"game-dir is not a directory: {raw!r}")
    return p


def _symbol_resolve_gate(game_dir: Path) -> bool:
    """Dev-only fail-closed check before planting: run scripts/verify_symbol_resolve.py
    against the game's OWN exe so a DLL carrying mis-resolved (mid-instruction)
    symbols is never deployed — the July-2026 false-ok class that shipped ~63
    broken symbols and crashed the gameplay bus. Returns True (proceed) when the
    check passes OR cannot run (frozen sidecar, no capstone, no scripts/, no exe)
    — end users hit those and are unaffected; only a dev checkout gates.
    """
    if getattr(sys, "frozen", False):
        return True
    script = REPO_ROOT / "scripts" / "verify_symbol_resolve.py"
    exe = game_dir / "Ravenswatch.exe"
    if not script.exists() or not exe.exists():
        return True
    # The verifier reports "could not run" (missing capstone / pattern DB /
    # importable rsmm) separately from "symbols are bad". Conflating them told a
    # user to go recover addresses when the actual fault was an ImportError.
    cannot_run = 3
    try:
        rc = subprocess.call([sys.executable, str(script), "--exe", str(exe)])
    except OSError:
        return True
    if rc == cannot_run:
        print(
            "install-loader: symbol-resolve gate SKIPPED (see reason above) — "
            "planting anyway. Symbols were not verified against this exe.",
            file=sys.stderr,
        )
        return True
    if rc != 0:
        print(
            "\ninstall-loader: symbol-resolve gate FAILED — refusing to plant a DLL "
            "with mid-instruction symbols. Recover the addresses or downgrade+strip "
            "them (see the symbols-pipeline memory), or pass --force to override.",
            file=sys.stderr,
        )
        return False
    return True


def _lua_syntax_gate() -> bool:
    """Refuse to plant an SDK that does not compile.

    The Lua SDK is disk-loaded, so `install-loader` is the moment a broken
    rsmm.lua reaches the game — and a syntax error there is not a degraded
    feature, it is `require "rsmm"` raising for EVERY mod. It happened on
    2026-08-16: one `local` too many ("too many local variables (limit is 200)"
    — the main chunk sits at that ceiling) was planted and would have bricked
    the next launch, caught only because the same command was run twice by hand.

    Compile-only (`luac -p`) against the files about to be copied. Skips
    silently when no Lua binary is on PATH or in a frozen bundle, so end users
    are never blocked by a check they cannot run; CI and dev checkouts have it.
    """
    if getattr(sys, "frozen", False):
        return True
    lib = REPO_ROOT / "src" / "loader" / "lib"
    if not lib.is_dir():
        return True
    luac = next((c for c in ("luac5.4", "luac5.3", "luac")
                 if shutil.which(c)), None)
    if luac is None:
        return True
    bad = []
    for f in sorted(lib.rglob("*.lua")):
        r = subprocess.run([luac, "-p", str(f)], capture_output=True, text=True)
        if r.returncode != 0:
            bad.append(r.stderr.strip() or f"{f}: compile failed")
    if bad:
        print("\ninstall-loader: SDK Lua does not compile — refusing to plant it "
              "(every mod's `require \"rsmm\"` would raise):", file=sys.stderr)
        for b in bad:
            print(f"  {b}", file=sys.stderr)
        print("Fix the syntax error, or pass --force to plant anyway.",
              file=sys.stderr)
        return False
    return True


def _replant_newer_loader(game_dir: Path) -> None:
    """Restore a newer loader that `rsmm update-loader` had already pulled.

    The platform script always plants the loader bundled inside THIS rsmm
    build. That is correct for a fresh install and wrong for a user who is
    running ahead of it via the update channel — and `restore --all` wipes
    the loader, so the restore/install-loader cycle is routine, not rare.
    Without this, every restore would silently roll such a user back and
    undo the out-of-band channel.

    Advisory: a failure here leaves a working (older) loader planted, so it
    warns instead of failing the install.
    """
    try:
        from rsmm.engine.loader_update import LoaderUpdateError, replant_cached
    except ImportError:
        return
    try:
        result = replant_cached(game_dir)
    except LoaderUpdateError as exc:
        print(f"install-loader: cached loader update not replanted: {exc}",
              file=sys.stderr)
        return
    if result:
        print(f"install-loader: replanted loader v{result['loader_version']} "
              f"from the update channel ({len(result['planted'])} files)")


def main(argv: list[str] | None = None) -> int:
    if argv is None:
        argv = sys.argv[1:]
    force = False
    if "--force" in argv:
        force = True
        argv = [a for a in argv if a != "--force"]
    if not argv:
        if (DEFAULT_GAME_DIR / COOKING_SUBDIR).is_dir():
            argv = [str(DEFAULT_GAME_DIR)]
        else:
            print(
                "Could not autodetect Ravenswatch install. "
                "Pass the path: rsmm install-loader <game-dir>",
                file=sys.stderr,
            )
            return 1

    # Defense in depth: the argv is forwarded to a .bat / .ps1 / .sh
    # helper. Validate up front so a hostile path never reaches the
    # shell, no matter how the helper script quotes its inputs.
    try:
        argv[0] = str(_validate_game_dir(argv[0]))
    except ValueError as exc:
        print(f"install-loader: {exc}", file=sys.stderr)
        return 1

    if not force and not _lua_syntax_gate():
        return 1

    if not force and not _symbol_resolve_gate(Path(argv[0])):
        return 1

    # Use REPO_ROOT so this works under both a source checkout and a
    # PyInstaller-frozen bundle (where REPO_ROOT resolves to _MEIPASS
    # and the install_loader scripts must be bundled alongside it).
    root = REPO_ROOT
    script_sh = root / "src/rsmm/cli/install_loader.sh"
    script_ps1 = root / "src/rsmm/cli/install_loader.ps1"

    if sys.platform == "win32":
        if not script_ps1.exists():
            print(f"install script not found: {script_ps1}", file=sys.stderr)
            return 1
        cmd = ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
               "-File", str(script_ps1), *argv]
        rc = subprocess.call(cmd)
    else:
        if not script_sh.exists():
            print(f"install script not found: {script_sh}", file=sys.stderr)
            return 1
        rc = subprocess.call([str(script_sh), *argv])

    if rc == 0:
        _replant_newer_loader(Path(argv[0]))
    return rc


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
