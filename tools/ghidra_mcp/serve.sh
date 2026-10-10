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
set -eu
cd "$(dirname "$0")/../.."

GHIDRA_INSTALL_DIR="${GHIDRA_INSTALL_DIR:-$HOME/Documents/Programming/ghidra_12.1.4_PUBLIC}"
PORT="${RSMM_GHIDRA_MCP_PORT:-8765}"
export GHIDRA_INSTALL_DIR
PATH="$HOME/.local/bin:$PATH"

if [ ! -x "$GHIDRA_INSTALL_DIR/support/analyzeHeadless" ]; then
  echo "no Ghidra at $GHIDRA_INSTALL_DIR — set GHIDRA_INSTALL_DIR to a Ghidra 12 install" >&2
  exit 1
fi

# pyghidra-mcp is pinned: its CLI client breaks on newer `mcp` releases, so an
# unpinned upgrade can change what works. Bump deliberately.
exec uvx --python 3.12 pyghidra-mcp@0.2.7 \
  --transport streamable-http --host 127.0.0.1 --port "$PORT" \
  --project-path "$PWD/ghidra_project/Ravenswatch-New.gpr" "$@"
