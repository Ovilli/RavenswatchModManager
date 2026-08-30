"""rsmm log — read the loader log from the game install directory.

Each game launch rotates the log: the fresh run is written to ``_log.txt``, the
prior run is kept as ``_log.prev.txt``, and every finished run is archived
under ``<game>/rsmm/logs/<date>_<time>_<session>.log`` (newest 20 kept). Every
line is stamped with a short per-process session token so concurrent or
successive injections never blur together.

By default only the current (most-recent) session is shown. Use ``--all`` for
the whole file, ``--prev`` for the previous run, ``--sessions`` to list the
session banners, ``--list`` to list archived runs, or ``--run <name>`` to read
one of them (a unique filename prefix is enough).
"""

from __future__ import annotations

import argparse
import re
import sys
import time
from pathlib import Path

from rsmm.cli import _term
from rsmm.engine.paths import DEFAULT_GAME_DIR

_ST = _term.Style()

_SESSION_MARK = "== SESSION "


def logs_dir(game_dir=None) -> Path:
    """Where finished runs are archived by the loader.

    Kept OUT of `mods/` on purpose: `restore` clears that directory wholesale,
    and an archive that a routine restore deletes is not an archive.
    """
    return Path(game_dir or DEFAULT_GAME_DIR) / "rsmm" / "logs"


def archived_runs(game_dir=None) -> list[Path]:
    """Archived run logs, newest first.

    Sorted by NAME, not mtime: the filename leads with the run's own start
    stamp, so lexical order is chronological even though the files are copied
    (which rewrites mtime) at the START of the following run.
    """
    d = logs_dir(game_dir)
    if not d.is_dir():
        return []
    return sorted((p for p in d.glob("*.log") if p.is_file()), reverse=True)


class RunNotFound(LookupError):
    """No archived run matched, or the prefix matched several."""


def resolve_run(name: str, game_dir=None) -> Path:
    """Map a user-supplied run name (or unique prefix) to an archived log.

    The only source of candidates is :func:`archived_runs`, so the result is
    always a real file inside `<game>/rsmm/logs/` no matter what the caller
    passed. That is deliberate: this resolver is reachable from the desktop UI
    (`rsmm json loader-log --run <name>`), where the name arrives from the
    frontend, and matching against a listing rather than joining a path onto a
    directory makes traversal impossible by construction instead of by
    validation.
    """
    runs = archived_runs(game_dir)
    hits = [p for p in runs if p.name == name] or [p for p in runs if p.name.startswith(name)]
    if not hits:
        raise RunNotFound(f"no archived run matching {name!r}")
    if len(hits) > 1:
        raise RunNotFound(
            f"{name!r} matches {len(hits)} runs: " + ", ".join(p.name for p in hits[:6])
        )
    return hits[0]


def log_file(game_dir=None, *, prev: bool = False) -> Path:
    """Where the loader writes its log.

    The single source of this path. The home screen's Log tab used to derive
    it independently and got it wrong (`<game>/rsmm/rsmm_log.txt`, a file that
    has never existed), so the tab was permanently blank while `rsmm log`
    worked fine.
    """
    return Path(game_dir or DEFAULT_GAME_DIR) / "mods" / (
        "_log.prev.txt" if prev else "_log.txt"
    )

# A line is `[<ts> <session> <pid>] <msg>`, where `<msg>` may carry a severity
# token (`[err]` / `[warn]`, from `Loader::log_err` / `log_warn`) and then a
# bracketed subsystem tag (`[va-gate]`, `[skin-hook]`, `[lua]`). Severity comes
# FIRST and is a separate token so `[subsystem]` stays where every existing
# reader looks for it. We dim the machine-generated prefix, colour the severity,
# and accent the subsystem tag so the human-written message stands out.
# Patterns are strict: anything that does not match is printed through untouched.
_TS_RE = re.compile(r"\[\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{3} [0-9a-f]{4} \d+\]")
_TAG_RE = re.compile(r"\[[a-z0-9][a-z0-9_-]{1,20}\]")
_SEV_RE = re.compile(r"\[(err|warn)\]")
_SEP_RE = re.compile(r"=+\Z")


def line_severity(s: str) -> str | None:
    """`'err'`, `'warn'`, or None when the loader did not classify the line.

    None means UNCLASSIFIED, not "fine": severity exists only where the loader
    was taught to emit it, so filters lift what is tagged rather than hiding
    what is not.
    """
    m = _TS_RE.match(s)
    if not m:
        return None
    sev = _SEV_RE.match(s, m.end() + 1)
    return sev.group(1) if sev else None


def _style_line(s: str) -> str:
    """Colourise a loader log line IN PLACE — never adds/removes characters."""
    if not _ST.enabled:
        return s
    if _SEP_RE.fullmatch(s):
        return _ST.dim(s)
    if s.startswith(_SESSION_MARK):
        return _ST.heading(s)
    m = _TS_RE.match(s)
    if not m:
        return s
    head, rest = _ST.dim(s[:m.end()]), s[m.end():]
    sev = _SEV_RE.match(rest, 1) if rest.startswith(" ") else None
    if sev:
        colour = _ST.err if sev.group(1) == "err" else _ST.warn
        head = f"{head} {colour(sev.group(0))}"
        rest = rest[sev.end():]
    tag = _TAG_RE.match(rest, 1) if rest.startswith(" ") else None
    if tag:
        return f"{head} {_ST.accent(tag.group(0))}{rest[tag.end():]}"
    return head + rest


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
    ap.add_argument("--errors", action="store_true",
                    help="show only lines the loader flagged [err] or [warn] "
                         "(session banners are always kept for context)")
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
    ap.add_argument("--list", action="store_true", dest="list_runs",
                    help="list archived runs under <game>/rsmm/logs and exit")
    ap.add_argument("--run", metavar="NAME",
                    help="read an archived run (filename or unique prefix)")
    ap.add_argument("--game-dir", default=str(DEFAULT_GAME_DIR))
    ap.add_argument("-h", "--help", action="store_true")
    a = ap.parse_args(argv)
    if a.help:
        print(__doc__)
        return 0

    if a.list_runs:
        runs = archived_runs(a.game_dir)
        if not runs:
            print(_ST.dim(f"no archived runs yet in {logs_dir(a.game_dir)}"))
            return 0
        for p in runs:
            kb = p.stat().st_size / 1024
            print(f"  {_ST.bold(p.name):<34} {_ST.dim(f'{kb:>8.0f} KB')}")
        print(f"\n{len(runs)} archived run(s) in {_ST.dim(str(logs_dir(a.game_dir)))}"
              f" — read one with {_ST.accent('rsmm log --run <name>')}")
        return 0

    if a.run:
        try:
            log_path = resolve_run(a.run, a.game_dir)
        except RunNotFound as e:
            print(_ST.err(f"{e} — list them with `rsmm log --list`"), file=sys.stderr)
            return 1
    else:
        log_path = log_file(a.game_dir, prev=a.prev)
    if a.path:
        print(log_path)
        return 0
    if a.clear:
        if log_path.exists():
            log_path.write_text("")
            print(f"cleared {_ST.dim(str(log_path))}")
        else:
            print(f"no log at {_ST.dim(str(log_path))}")
        return 0
    if not log_path.exists():
        print(_ST.err(f"no log yet at {log_path} — launch the game once with the "
                      f"loader installed"), file=sys.stderr)
        return 1

    # `encoding="utf-8"` on every read of this file, always. The loader writes
    # it as UTF-8 (em dashes in its own copy, and player gamertags straight off
    # the lobby blob), but a bare `open()` decodes with the LOCALE preferred
    # encoding — cp936 on a Chinese Windows, cp1251 on a Russian one. A shared
    # diagnostic log came back with every "—" as "鈥" and a Chinese player's
    # name as "鏌樻湀", which reads as a loader bug and is really just the
    # reader guessing. `errors="replace"` stays as the backstop for a torn
    # final line.
    if a.sessions:
        with open(log_path, encoding="utf-8", errors="replace") as f:
            marks = [ln.rstrip("\n") for ln in f if _SESSION_MARK in ln]
        if not marks:
            print(_ST.dim("(no session banners — log predates session-aware loader)"))
            return 0
        for ln in marks:
            print(_style_line(ln))
        return 0

    needle = a.grep.lower() if a.grep else None

    def emit(line: str) -> None:
        s = line.rstrip("\n")
        if needle is not None and needle not in s.lower():
            return
        # Banners survive the severity filter: an error with no run attached to
        # it is not much use.
        if a.errors and line_severity(s) is None and _SESSION_MARK not in s:
            return
        print(_style_line(s), flush=True)

    def current_session(lines: list[str]) -> list[str]:
        """Trim to the last session banner onward (unless --all)."""
        if a.all:
            return lines
        for i in range(len(lines) - 1, -1, -1):
            if _SESSION_MARK in lines[i]:
                return lines[i:]
        return lines

    if not a.follow:
        with open(log_path, encoding="utf-8", errors="replace") as f:
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
        f = open(log_path, encoding="utf-8", errors="replace")
    except FileNotFoundError:
        print(_ST.err(f"Log not found: {log_path}"), file=sys.stderr)
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
                    f = open(log_path, encoding="utf-8", errors="replace")
                    inode = st.st_ino
            except (FileNotFoundError, OSError):
                # Log file was rotated or deleted; wait and retry
                f.close()
                time.sleep(1)
                try:
                    f = open(log_path, encoding="utf-8", errors="replace")
                    try:
                        inode = log_path.stat().st_ino
                    except FileNotFoundError:
                        inode = -1
                except FileNotFoundError:
                    print(_ST.warn("Log file removed; stopping follow."), file=sys.stderr)
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
