#!/usr/bin/env python3
"""Driver for Ghidra headless analysis + full decompile export.

Imports Ravenswatch.exe into a Ghidra project, runs auto-analysis, then
dumps every function's decompiled C to a JSON-Lines stream that downstream
tooling (string search, pattern miner, mod-target locator) can consume.

Usage:
    scripts/ghidra_export.py \\
        --ghidra  /path/to/ghidra_11.3_PUBLIC \\
        --exe     /path/to/Ravenswatch.exe \\
        --project /path/to/ghidra_project \\
        --out     data/decompiled.jsonl

Long-running. ~30-90 min for a 22MB binary on a desktop CPU. Re-runs reuse
the existing Ghidra project (-import skipped if already imported) so only
the export pass repeats.
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

DEFAULT_GHIDRA  = "/home/ovilli/Documents/Programming/ghidra_11.3_PUBLIC"
DEFAULT_EXE     = (
    "/home/ovilli/.var/app/com.valvesoftware.Steam/.local/share/Steam"
    "/steamapps/common/Ravenswatch/Ravenswatch.exe"
)
DEFAULT_PROJECT = str(Path(__file__).resolve().parent.parent / "ghidra_project")
DEFAULT_OUT     = str(Path(__file__).resolve().parent.parent / "data" / "decompiled.jsonl")
PROJECT_NAME    = "Ravenswatch"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--ghidra", default=DEFAULT_GHIDRA)
    ap.add_argument("--exe", default=DEFAULT_EXE)
    ap.add_argument("--project", default=DEFAULT_PROJECT)
    ap.add_argument("--out", default=DEFAULT_OUT)
    ap.add_argument("--script-dir", default=str(Path(__file__).resolve().parent / "ghidra_scripts"))
    ap.add_argument("--no-analysis", action="store_true",
                    help="skip auto-analysis (only useful for re-export passes)")
    args = ap.parse_args()

    ghidra = Path(args.ghidra)
    exe    = Path(args.exe)
    proj   = Path(args.project)
    out    = Path(args.out)
    headless = ghidra / "support" / "analyzeHeadless"
    if not headless.exists():
        print(f"analyzeHeadless not found: {headless}", file=sys.stderr)
        return 1
    if not exe.is_file():
        print(f"exe not found: {exe}", file=sys.stderr)
        return 1

    proj.mkdir(parents=True, exist_ok=True)
    out.parent.mkdir(parents=True, exist_ok=True)

    script_dir = Path(args.script_dir)
    script_dir.mkdir(parents=True, exist_ok=True)

    # Re-use existing import if the .gpr metadata already exists, otherwise import.
    gpr_files = list(proj.glob("*.gpr"))
    is_imported = any(p.stem == PROJECT_NAME for p in gpr_files)

    cmd = [
        str(headless),
        str(proj),
        PROJECT_NAME,
        "-scriptPath", str(script_dir),
        "-postScript", "ExportDecompiled.java", str(out),
    ]
    if is_imported:
        cmd += ["-process", exe.name, "-noanalysis"] if args.no_analysis else [
            "-process", exe.name,
        ]
    else:
        cmd += ["-import", str(exe)]
        if args.no_analysis:
            cmd.append("-noanalysis")
    cmd += ["-readOnly"] if args.no_analysis else []
    # Keep Java heap large enough for a 22 MB PE + analysis.
    env = dict(os.environ)
    env.setdefault("_JAVA_OPTIONS", "-Xmx8G")
    print("$", " ".join(cmd), file=sys.stderr)
    return subprocess.call(cmd, env=env)


if __name__ == "__main__":
    sys.exit(main())
