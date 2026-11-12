#!/usr/bin/env bash
# Run Ghidra headless analyzer on Ravenswatch.exe, then dump xrefs.
# Output: $RSMM_OUT/xrefs.json
set -e

GHIDRA=${GHIDRA_HOME:?set GHIDRA_HOME to your Ghidra install}
RE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$RE/project"
SCRIPT_DIR="$RE/scripts"
export RSMM_OUT="$RE/out"

PROJECT_NAME=RSMM
EXE=${RAVENSWATCH_EXE:?set RAVENSWATCH_EXE to the path of Ravenswatch.exe}

mkdir -p "$PROJECT_DIR" "$RSMM_OUT"

# -import only first run; subsequent runs use -process to re-run script
if [ -f "$PROJECT_DIR/$PROJECT_NAME.gpr" ]; then
    echo "[RSMM] re-running script on existing project"
    "$GHIDRA/support/analyzeHeadless" "$PROJECT_DIR" "$PROJECT_NAME" \
        -process "Ravenswatch.exe" \
        -noanalysis \
        -scriptPath "$SCRIPT_DIR" \
        -postScript dump_xrefs.py
else
    echo "[RSMM] first run: import + analyze (5-20 min)"
    "$GHIDRA/support/analyzeHeadless" "$PROJECT_DIR" "$PROJECT_NAME" \
        -import "$EXE" \
        -scriptPath "$SCRIPT_DIR" \
        -postScript dump_xrefs.py
fi

echo "[RSMM] done. Output: $RSMM_OUT/xrefs.json"
