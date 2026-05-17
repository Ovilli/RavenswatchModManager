#!/usr/bin/env bash
# Run target-function decompiler on existing Ghidra project.
set -e

GHIDRA=~/Documents/Programming/ghidra_11.3_PUBLIC
PROJECT_DIR=~/Documents/Programming/RavenswatchModManager/re/project
PROJECT_NAME=RSMM
SCRIPT_DIR=~/Documents/Programming/RavenswatchModManager/re/scripts
export RSMM_OUT=~/Documents/Programming/RavenswatchModManager/re/out

"$GHIDRA/support/analyzeHeadless" "$PROJECT_DIR" "$PROJECT_NAME" \
    -process "Ravenswatch.exe" \
    -noanalysis \
    -scriptPath "$SCRIPT_DIR" \
    -postScript decompile_targets.py

echo "[RSMM] decompiled output in $RSMM_OUT/decompiled/"
ls -la "$RSMM_OUT/decompiled/"
