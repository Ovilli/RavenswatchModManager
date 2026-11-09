#!/usr/bin/env bash
# Dump the raw .text bytes + image base of the imported project.
# Run this on the OLD build's project BEFORE re-importing a patched exe —
# scripts/remap_symbols.py + rewire_va_globals.py rebuild byte patterns
# from these bytes to re-locate symbols in the new build.
# Fast (~1 min). Output: $RSMM_OUT/text_section.{bin,json}.
set -e

GHIDRA=${GHIDRA_HOME:?set GHIDRA_HOME to your Ghidra install}
RE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$RE/project"
SCRIPT_DIR="$RE/scripts"
export RSMM_OUT="$RE/out"

PROJECT_NAME=${1:-RSMM}   # pass a project name to target a specific build

"$GHIDRA/support/analyzeHeadless" "$PROJECT_DIR" "$PROJECT_NAME" \
    -process "Ravenswatch.exe" \
    -noanalysis \
    -scriptPath "$SCRIPT_DIR" \
    -postScript dump_text_section.py
