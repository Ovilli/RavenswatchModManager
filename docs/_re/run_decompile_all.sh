#!/usr/bin/env bash
# Mass-decompile every function in Ravenswatch.exe to pseudo-C.
# Slow (hours, depending on function count). Output:
#   $RSMM_OUT/decompiled_all/<bucket>/<name>__<addr>.c
#   $RSMM_OUT/functions_index.tsv
set -e

GHIDRA=~/Documents/Programming/ghidra_11.3_PUBLIC
RE=~/Documents/Programming/RavenswatchModManager/docs/_re
PROJECT_DIR="$RE/project"
PROJECT_NAME=RSMM
SCRIPT_DIR="$RE/scripts"
export RSMM_OUT="$RE/out"

"$GHIDRA/support/analyzeHeadless" "$PROJECT_DIR" "$PROJECT_NAME" \
    -process "Ravenswatch.exe" \
    -noanalysis \
    -scriptPath "$SCRIPT_DIR" \
    -postScript decompile_all.py
