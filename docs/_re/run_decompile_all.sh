#!/usr/bin/env bash
# Mass-decompile every function in Ravenswatch.exe to pseudo-C.
# Slow (hours, depending on function count). Output:
#   $RSMM_OUT/decompiled_all/<bucket>/<name>__<addr>.c
#   $RSMM_OUT/functions_index.tsv
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
    -postScript decompile_all.py
