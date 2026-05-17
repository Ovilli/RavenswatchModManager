#!/usr/bin/env bash
# Dump symbols + strings from the imported Ravenswatch.exe project.
# Fast (~1 min). Output: $RSMM_OUT/symbols.json + strings.json.
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
    -postScript dump_symbols_strings.py
