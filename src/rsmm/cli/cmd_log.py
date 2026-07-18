"""rsmm log — read the loader log from the game install directory.

Each game launch rotates the log: the fresh run is written to ``_log.txt`` and
the prior run is kept as ``_log.prev.txt``. Every line is stamped with a short
per-process session token so concurrent/successive injections never blur.

By default only the current (most-recent) session is shown. Use ``--all`` for
the whole file, ``--prev`` for the previous run, or ``--sessions`` to list the
session banners.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

from rsmm.engine.paths import DEFAULT_GAME_DIR


def main(argv: list[str] | None = None) -> int:
    if argv is None:
        argv = sys.argv[1:]

    ap = argparse.ArgumentParser(prog="rsmm log", add_help=False)
    ap.add_argument("-n", "--lines", type=int, default=0,
                    help="show only the last N lines")
    ap.add_argument("-f", "--follow", action="store_true",
                    help="stream new lines as the game writes them")
    ap.add_argument("--clear", action="store_true",
                    help="truncate the log file")
    ap.add_argument("--grep", help="filter to lines matching this substring (case-insensitive)")
    ap.add_argument("--path", action="store_true",
                    help="print the log path and exit")
    ap.add_argument("--all", action="store_true",
                    help="show every session in the file (default: only the "
                         "current/most-recent session)")
    ap.add_argument("--prev", action="store_true",
                    help="read the previous run's log (_log.prev.txt), rotated "
                         "out when the game last launched")
    ap.add_argument("--sessions", action="store_true",
                    help="list the session banners in the log and exit")
    ap.add_argument("--game-dir", default=str(DEFAULT_GAME_DIR))
    ap.add_argument("-h", "--help", action="store_true")
    a = ap.parse_args(argv)
    if a.help:
        print(__doc__)
        return 0

    mods = Path(a.game_dir) / "mods"
    log_path = mods / ("_log.prev.txt" if a.prev else "_log.txt")
    if a.path:
        print(log_path)
        return 0
    if a.clear:
        if log_path.exists():
            log_path.write_text("")
            print(f"cleared {log_path}")
        else:
            print(f"no log at {log_path}")
        return 0
    if not log_path.exists():
        print(f"no log yet at {log_path} — launch the game once with the "
              f"loader installed", file=sys.stderr)
        return 1

    _SESSION_MARK = "== SESSION "

    if a.sessions:
        with open(log_path, errors="replace") as f:
            marks = [ln.rstrip("\n") for ln in f if _SESSION_MARK in ln]
        if not marks:
            print("(no session banners — log predates session-aware loader)")
            return 0
        for ln in marks:
            print(ln)
        return 0

    needle = a.grep.lower() if a.grep else None

    def emit(line: str) -> None:
        s = line.rstrip("\n")
        if needle is None or needle in s.lower():
            print(s, flush=True)

    def current_session(lines: list[str]) -> list[str]:
        """Trim to the last session banner onward (unless --all)."""
        if a.all:
            return lines
        for i in range(len(lines) - 1, -1, -1):
            if _SESSION_MARK in lines[i]:
                return lines[i:]
        return lines

    if not a.follow:
        with open(log_path, errors="replace") as f:
            lines = f.readlines()
        lines = current_session(lines)
        if a.lines and a.lines > 0:
            lines = lines[-a.lines:]
        for ln in lines:
            emit(ln)
        return 0

    try:
        inode = log_path.stat().st_ino
    except FileNotFoundError:
        inode = -1

    try:
        f = open(log_path, errors="replace")
    except FileNotFoundError:
        print(f"Log not found: {log_path}", file=sys.stderr)
        return 1

    try:
        if a.lines and a.lines > 0:
            tail = f.readlines()[-a.lines:]
            for ln in tail:
                emit(ln)
        else:
            f.seek(0, 2)
        while True:
            line = f.readline()
            if line:
                emit(line)
                continue
            time.sleep(0.25)
            try:
                st = log_path.stat()
                if st.st_ino != inode or st.st_size < f.tell():
                    f.close()
                    f = open(log_path, errors="replace")
                    inode = st.st_ino
            except (FileNotFoundError, OSError):
                # Log file was rotated or deleted; wait and retry
                f.close()
                time.sleep(1)
                try:
                    f = open(log_path, errors="replace")
                    try:
                        inode = log_path.stat().st_ino
                    except FileNotFoundError:
                        inode = -1
                except FileNotFoundError:
                    print("Log file removed; stopping follow.", file=sys.stderr)
                    return 0
    except KeyboardInterrupt:
        return 0
    finally:
        try:
            f.close()
        except Exception:
            pass


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
