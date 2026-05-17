#!/usr/bin/env bash
# Run Ghidra headless analyzer on Ravenswatch.exe, then dump xrefs.
# Output: re/out/xrefs.json
set -e

GHIDRA=~/Documents/Programming/ghidra_11.3_PUBLIC
PROJECT_DIR=~/Documents/Programming/RavenswatchModManager/re/project
PROJECT_NAME=RSMM
EXE=/home/ovilli/.var/app/com.valvesoftware.Steam/.local/share/Steam/steamapps/common/Ravenswatch/Ravenswatch.exe
SCRIPT_DIR=~/Documents/Programming/RavenswatchModManager/re/scripts
export RSMM_OUT=~/Documents/Programming/RavenswatchModManager/re/out

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
