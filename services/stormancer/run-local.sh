#!/usr/bin/env bash
# Start a local Stormancer grid and deploy the Ravenswatch backend to it.
#
#   ./run-local.sh          start the grid (if needed) and deploy server/
#   ./run-local.sh stop     stop the grid
#
# Needs the .NET SDK. The Stormancer CLI is installed into ./.tools on first run.
set -euo pipefail

here="$(cd "$(dirname "$0")" && pwd)"
tools="$here/.tools"
cli="$tools/stormancer"
# The CLI and grid target .NET 8; roll forward so a newer runtime alone is enough.
export DOTNET_ROLL_FORWARD=Major
# The grid builds the app with `dotnet build`, whose shared compiler server (VBCSCompiler)
# outlives the build and inherits the grid's sockets: after a grid restart it still held
# UDP 30100 and the new grid's RakNet transport failed with SOCKET_PORT_ALREADY_IN_USE.
export UseSharedCompilation=false

if [[ "${1:-}" == "stop" ]]; then
    pkill -f "$cli start" && echo "grid stopped" || echo "grid was not running"
    exit 0
fi

if [[ ! -x "$cli" ]]; then
    dotnet tool install Stormancer.CLI --tool-path "$tools"
fi

# stdin -> grid.log, rolling over to grid.prev.log once grid.log passes GRID_LOG_MAX_MB.
capped_log() {
    local max=$(( ${GRID_LOG_MAX_MB:-50} * 1024 * 1024 )) size line
    size=$(stat -c %s grid.log 2>/dev/null || echo 0)
    exec >>grid.log
    while IFS= read -r line; do
        printf '%s\n' "$line"
        size=$(( size + ${#line} + 1 ))
        if (( size > max )); then
            mv -f grid.log grid.prev.log
            exec >grid.log
            printf '===== log rolled over at %s MB =====\n' "${GRID_LOG_MAX_MB:-50}"
            size=0
        fi
    done
}

cd "$here/grid"
if ! curl -sf -m 2 http://127.0.0.1:8090/_federation >/dev/null; then
    # Bounded on disk: at most grid.log + grid.prev.log, each up to GRID_LOG_MAX_MB (default 50).
    # Appending forever grew without limit on the hosted server, and one bad client can log
    # several errors a second for as long as it stays connected. The previous run is rotated to
    # grid.prev.log rather than thrown away, because a restart is exactly when a log is worth
    # comparing across.
    [[ -f grid.log ]] && mv -f grid.log grid.prev.log
    printf '===== grid start %s =====\n' "$(date '+%Y-%m-%d %H:%M:%S')" >grid.log
    setsid bash -c "$(declare -f capped_log); \"\$0\" start 2>&1 | capped_log" "$cli" &
    for _ in $(seq 1 60); do
        curl -sf -m 2 http://127.0.0.1:8090/_federation >/dev/null && break
        sleep 1
    done
    "$cli" manage clusters add --endpoint http://localhost:8091 >/dev/null
fi

# The live game asks for app "darktales/main" (the EndPointApp "Live" branch), so that is the
# one that must carry our code. local.profile.json (darktales/live-1-05-01) was an earlier wrong
# guess at the app name; deploy both so either endpoint works.
"$cli" manage app deploy --app ../deploy/main.profile.json --create --configure --deploy
"$cli" manage app deploy --app ../deploy/local.profile.json --create --configure --deploy
echo "federation: $(curl -s http://127.0.0.1:8090/_federation)"
echo "grid log:   $here/grid/grid.log"
