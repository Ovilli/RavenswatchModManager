#!/usr/bin/env bash
# Dump symbols + strings from the imported Ravenswatch.exe project.
# Fast (~1 min). Output: $RSMM_OUT/symbols.json + strings.json.
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
    -postScript dump_symbols_strings.py
