#!/usr/bin/env python3
"""`rsmm rebuild-fn-patterns` — regenerate the byte-pattern DB for the installed game.

After a Steam update every address moves, so ``data/function_patterns.json`` has to be
rebuilt against the new ``Ravenswatch.exe``. The steps already exist as scripts; this
runs them in order, checks each, and reports the result:

  1. (``--ghidra``) re-dump ``symbols.json`` from the analysed Ghidra project
  2. ``scripts/gen_function_patterns.py``   the ~50k generic signatures
  3. ``scripts/sync_symbol_patterns.py``    the stable semantic entries + meta stamp
  4. ``scripts/verify_symbol_resolve.py``   every status=ok symbol must resolve to a real
     function boundary in the live exe (the repo's gate after any regeneration)
  5. ``scripts/test_pattern_resolve.py --all``   every entry must resolve, by the loader's
     own scan, to the address it was recorded for

The old DB is kept as ``*.prev`` and put back if a step fails or is interrupted. It stops
there: it does not remap ``data/symbols.json`` (see the patch-day steps in the pipeline
docs), rebuild the loader, or publish. About 2-3 minutes on a desktop CPU.

  rsmm rebuild-fn-patterns               # skip when the DB already matches this exe
  rsmm rebuild-fn-patterns --force
  rsmm rebuild-fn-patterns --ghidra      # also re-run the symbol dump first
  rsmm rebuild-fn-patterns --dry-run     # print the plan only
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

from rsmm.engine.paths import REPO_ROOT, default_game_dir

_DB = "data/function_patterns.json"
_META = "data/function_patterns.meta.json"
_DUMP = "docs/_re/run_dump_symbols.sh"
#: verify_symbol_resolve's "the gate could not run" code, as opposed to 1 = bad symbols.
EXIT_CANNOT_RUN = 3


def _exe(game_dir: Path) -> Path | None:
    for rel in ("Ravenswatch.exe", "Ravenswatch-Win64-Shipping.exe",
                "Ravenswatch/Binaries/Win64/Ravenswatch-Win64-Shipping.exe"):
        if (game_dir / rel).is_file():
            return game_dir / rel
    return None


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _has_capstone(python: str) -> bool:
    if python == sys.executable:
        try:
            import capstone  # scripts/gen_function_patterns.py disassembles with it
            return True
        except ImportError:
            return False
    try:
        return subprocess.run([python, "-c", "import capstone"], capture_output=True,
                              timeout=30).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def _python() -> str | None:
    """An interpreter that can run the scripts: this one, else the repo's own venv.

    ``./rsmm`` runs under whatever ``python3`` is first on PATH, which is not always the
    environment that has the RE dependencies installed."""
    for cand in (sys.executable, REPO_ROOT / ".venv" / "bin" / "python",
                 REPO_ROOT / ".venv" / "Scripts" / "python.exe"):
        if Path(cand).is_file() and _has_capstone(str(cand)):
            return str(cand)
    return None


def _plan(py: str, exe: Path, ghidra: bool, validate: bool) -> list[tuple[str, list[str]]]:
    steps: list[tuple[str, list[str]]] = []
    if ghidra:
        steps.append(("dump symbols from Ghidra", ["bash", _DUMP]))
    steps += [
        ("generate patterns", [py, "scripts/gen_function_patterns.py", "--exe", str(exe)]),
        ("sync semantic entries", [py, "scripts/sync_symbol_patterns.py", "--exe", str(exe)]),
    ]
    if validate:
        steps += [
            ("verify symbols resolve",
             [py, "scripts/verify_symbol_resolve.py", "--exe", str(exe)]),
            ("resolve every entry",
             [py, "scripts/test_pattern_resolve.py", "--all", "--exe", str(exe)]),
        ]
    return steps


def _run(label: str, argv: list[str]) -> tuple[int, str]:
    """Run one step in the repo, echoing its output; return (exit code, its text)."""
    print(f"==> {label}: {' '.join(argv)}", flush=True)
    t0 = time.monotonic()
    proc = subprocess.Popen(argv, cwd=REPO_ROOT, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, text=True, errors="replace")
    lines: list[str] = []
    assert proc.stdout is not None
    for line in proc.stdout:
        lines.append(line)
        print("    " + line.rstrip(), flush=True)
    code = proc.wait()
    print(f"    ({time.monotonic() - t0:.0f}s, exit {code})", flush=True)
    return code, "".join(lines)


def _tally(text: str) -> tuple[int, int] | None:
    """``(ok, fail)`` from test_pattern_resolve's ``ALL DONE ok=N fail=M (..%)`` line."""
    for line in reversed(text.splitlines()):
        if line.startswith("ALL DONE"):
            try:
                f = dict(kv.split("=", 1) for kv in line.split() if "=" in kv)
                return int(f["ok"]), int(f["fail"])
            except (KeyError, ValueError):
                return None
    return None


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="rsmm rebuild-fn-patterns",
                                 description=__doc__.split("\n\n")[0])
    add = ap.add_argument
    add("--game-dir", type=Path, help="the Ravenswatch install (default: autodetected)")
    add("--force", action="store_true",
        help="rebuild even if the DB already matches this exe")
    add("--ghidra", action="store_true",
        help="re-dump symbols.json from Ghidra first (slow)")
    add("--skip-validate", action="store_true",
        help="skip the two resolve checks (not recommended)")
    add("--dry-run", action="store_true", help="print the plan and stop")
    args = ap.parse_args(argv)

    if not (REPO_ROOT / "scripts" / "gen_function_patterns.py").is_file():
        print("error: this needs a source checkout (no scripts/ in an installed build)",
              file=sys.stderr)
        return 2
    game_dir = args.game_dir or default_game_dir()
    exe = _exe(Path(game_dir))
    if exe is None:
        print(f"error: no Ravenswatch.exe under {game_dir} (use --game-dir)", file=sys.stderr)
        return 2
    if args.ghidra and not (REPO_ROOT / _DUMP).is_file():
        print(f"error: {_DUMP} not found", file=sys.stderr)
        return 2

    py = _python()
    if py is None:
        print(f"error: the pattern generator needs capstone, and neither {sys.executable} nor "
              f"the repo's .venv has it.\n       pip install capstone", file=sys.stderr)
        return 2

    sha = _sha256(exe)
    meta_path, db_path = REPO_ROOT / _META, REPO_ROOT / _DB
    old: dict = {}
    if meta_path.is_file():
        try:
            old = json.loads(meta_path.read_text(encoding="utf-8"))
        except ValueError:
            old = {}
    print(f"game exe   {exe}\n           sha256 {sha[:16]}…  ({exe.stat().st_size:,} bytes)")
    if old.get("game_exe_sha256"):
        same = old["game_exe_sha256"] == sha
        print(f"current DB {old.get('pattern_count', '?')} entries, built for "
              f"{'THIS exe' if same else 'a different exe'} ({old['game_exe_sha256'][:16]}…)")
        if same and db_path.is_file() and not args.force and not args.ghidra:
            print("Already built for this exe. Nothing to do (--force to rebuild anyway).")
            return 0
    else:
        print("current DB none, or it has no exe stamp")

    steps = _plan(py, exe, args.ghidra, not args.skip_validate)
    if args.dry_run:
        print("\nplan:")
        for label, cmd in steps:
            print(f"  {label}: {' '.join(cmd)}")
        return 0

    saved: list[tuple[Path, Path]] = []
    for p in (db_path, meta_path):
        if p.is_file():
            prev = p.with_name(p.name + ".prev")
            shutil.copy2(p, prev)
            saved.append((p, prev))

    def restore(why: str) -> int:
        for p, prev in saved:
            shutil.copy2(prev, p)
            prev.unlink()
        for p in (db_path, meta_path):              # nothing to go back to: no half-made DB
            if p not in {q for q, _prev in saved}:
                p.unlink(missing_ok=True)
        print(f"\nFAILED: {why}. The previous DB is back in place.", file=sys.stderr)
        return 1

    tally: tuple[int, int] | None = None
    try:
        for label, cmd in steps:
            code, text = _run(label, cmd)
            if code == EXIT_CANNOT_RUN and label.startswith("verify"):
                print("    (the symbol gate could not run here; the DB is NOT verified)")
                continue
            if code != 0:
                return restore(f"{label} exited {code}")
            if label.startswith("resolve every"):
                tally = _tally(text)
                if tally is None:
                    return restore("could not read the resolve check's result")
                if tally[1]:
                    return restore(f"{tally[1]} of {sum(tally)} entries resolve to the wrong "
                                   f"address or none")
    except KeyboardInterrupt:
        return restore("interrupted")

    meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.is_file() else {}
    print("\nPattern DB rebuilt.")
    print(f"  entries   {meta.get('pattern_count', '?')}")
    print(f"  exe       {str(meta.get('game_exe_sha256', ''))[:16]}…")
    if tally is not None:
        print(f"  resolve   all {tally[0]} entries, to their recorded address")
    print("Not done by this command: remapping data/symbols.json after a patch, "
          "`rsmm symbols gen`, rebuilding the loader, and publishing "
          "(scripts/publish_pattern_db.sh). The previous DB is kept as *.prev (gitignored).")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
