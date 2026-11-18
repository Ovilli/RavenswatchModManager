#!/bin/sh
# Serve the repo's Ghidra project over MCP with pyghidra-mcp (headless).
#
# Leave it running; Claude Code and opencode connect to the URL in .mcp.json /
# opencode.json. No Ghidra window is needed. Ctrl+C saves and closes the
# project. Extra arguments go to pyghidra-mcp (e.g. --gui to drive a live
# CodeBrowser in the same JVM).
#
# Needs Ghidra >= 12.0 (pyghidra refuses 11.x) and uv. Opening the project in
# Ghidra 12 upgrades it; 11.x cannot open it afterwards.
#
# GHIDRA_INSTALL_DIR (required) is a Ghidra 12 install. RSMM_GHIDRA_PROJECT is
# the folder holding the project's .gpr, and defaults to the gitignored
# ghidra_project/ in the repo.
set -eu
cd "$(dirname "$0")/../.."

PORT="${RSMM_GHIDRA_MCP_PORT:-8765}"
export GHIDRA_INSTALL_DIR="${GHIDRA_INSTALL_DIR:-}"
PATH="$HOME/.local/bin:$PATH"

if [ -z "$GHIDRA_INSTALL_DIR" ]; then
  echo "GHIDRA_INSTALL_DIR is not set — set it to a Ghidra 12 install" >&2
  exit 1
fi
if [ ! -x "$GHIDRA_INSTALL_DIR/support/analyzeHeadless" ] \
   && [ ! -f "$GHIDRA_INSTALL_DIR/support/analyzeHeadless.bat" ]; then
  echo "no Ghidra at '$GHIDRA_INSTALL_DIR' — set GHIDRA_INSTALL_DIR to a Ghidra 12 install" >&2
  exit 1
fi

PROJECT_DIR="${RSMM_GHIDRA_PROJECT:-$PWD/ghidra_project}"
GPR=""
for f in "$PROJECT_DIR"/*.gpr; do
  [ -f "$f" ] || continue
  if [ -n "$GPR" ]; then
    echo "more than one .gpr in '$PROJECT_DIR'" >&2
    exit 1
  fi
  GPR="$f"
done
if [ -z "$GPR" ]; then
  echo "no .gpr in '$PROJECT_DIR' — set RSMM_GHIDRA_PROJECT to the project folder" >&2
  exit 1
fi

# pyghidra-mcp is pinned: its CLI client breaks on newer `mcp` releases, so an
# unpinned upgrade can change what works. Bump deliberately.
exec uvx --python 3.12 pyghidra-mcp@0.2.7 \
  --transport streamable-http --host 127.0.0.1 --port "$PORT" \
  --project-path "$GPR" "$@"
