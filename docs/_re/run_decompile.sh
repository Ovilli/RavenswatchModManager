#!/usr/bin/env bash
# Run target-function decompiler on existing Ghidra project.
set -e

GHIDRA=${GHIDRA_HOME:?set GHIDRA_HOME to your Ghidra install}
RE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$RE/project"
SCRIPT_DIR="$RE/scripts"
export RSMM_OUT="$RE/out"

PROJECT_NAME=RSMM

"$GHIDRA/support/analyzeHeadless" "$PROJECT_DIR" "$PROJECT_NAME" \
    -process "Ravenswatch.exe" \
    -noanalysis \
    -scriptPath "$SCRIPT_DIR" \
    -postScript decompile_targets.py

echo "[RSMM] decompiled output in $RSMM_OUT/decompiled/"
ls -la "$RSMM_OUT/decompiled/"
