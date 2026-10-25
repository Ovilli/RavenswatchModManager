"""`rsmm json serve` — answer read-only bridge calls from one warm process.

Every desktop CLI call used to be a cold start (interpreter + imports, plus the
frozen bundle's unpack): ~1 s for `doctor`, paid again on every screen. This
keeps one process alive and runs the bridge in-process, one request at a time.

Protocol, one JSON object per line each way:

    stdin   {"id": 1, "args": ["list"]}
    stdout  {"id": 1, "code": 0, "stdout": "...", "stderr": "..."}

Only READ-ONLY commands are served. The app kills this process after any write
and whenever the environment it was started with (profile, language, game dir)
changes, so in-memory state can never outlive what it describes.
"""

from __future__ import annotations

import contextlib
import io
import json
import os
import sys
import traceback

#: Keep in step with READ_ONLY_COMMANDS in apps/desktop/src/lib/rsmm.ts.
SERVED = frozenset({
    "list", "list-profiles", "overlays", "changelog", "loader-runs", "loader-health",
    "loader-log", "game-status", "conflicts", "active-overrides", "doctor",
})


def servable(args: list[str]) -> bool:
    return bool(args) and args[0] in SERVED and "--fix" not in args


def handle(args: list[str]) -> tuple[int, str, str]:
    from rsmm.cli.json_bridge import main

    if not servable(args):
        return 2, "", f"serve: not a read-only command: {args[:1]}"
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            code = main(args)
        except SystemExit as e:
            code = e.code if isinstance(e.code, int) else (0 if e.code is None else 1)
        except BaseException:  # noqa: BLE001 — one bad request must not kill the server
            traceback.print_exc()
            code = 1
    return code or 0, out.getvalue(), err.getvalue()


def serve() -> int:
    # The protocol owns the real stdout. Point fd 1 at stderr so a stray write
    # (a C extension, a child process inheriting fd 1) cannot corrupt it.
    proto = os.fdopen(os.dup(1), "w", encoding="utf-8")
    os.dup2(2, 1)
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
            rid, args = req["id"], [str(a) for a in req["args"]]
        except (ValueError, KeyError, TypeError):
            continue
        code, out, err = handle(args)
        proto.write(json.dumps({"id": rid, "code": code, "stdout": out, "stderr": err},
                               separators=(",", ":")) + "\n")
        proto.flush()
    return 0
