"""`rsmm values` — back up a game patch's values and see what an update changed.

    rsmm values snapshot [--name N]     save the installed patch's values
    rsmm values list                    the snapshots taken so far
    rsmm values diff <A> [<B>]          what changed from A to B (default:
                                        the install as it is now)
    rsmm values extract <A> <path> -o F one cooked file as snapshot A shipped it

Take a snapshot BEFORE a game update installs: after it, the old values exist
nowhere else. Snapshots live under the per-user data dir, never in the game
directory, so `restore --all` and Steam's verify leave them alone. See
`rsmm.engine.values_snapshot`.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from rsmm.cli import _term
from rsmm.engine import values_snapshot as VS


def _progress(st: _term.Style):
    if not sys.stderr.isatty():
        return None

    def tick(i: int, n: int) -> None:
        if i == n or i % 50 == 0:
            sys.stderr.write(f"\r  reading entities {i}/{n}")
            if i == n:
                sys.stderr.write("\n")
            sys.stderr.flush()
    return tick


def _snapshot(args, st: _term.Style) -> int:
    snap = VS.snapshot(args.name, out_dir=Path(args.out) if args.out else None,
                       progress=_progress(st))
    m = snap.meta
    print(f"{st.ok('saved')} {snap.path}")
    print(f"  {st.dim('build')}     {m.get('build_id') or 'unknown'}")
    print(f"  {st.dim('entities')}  {m['entities']}"
          + (f"  {st.warn(str(m['unreadable']) + ' unreadable (bytes kept)')}"
             if m["unreadable"] else ""))
    print(f"  {st.dim('files')}     {m['files']} cooked files backed up")
    return 0


def _list(_args, st: _term.Style) -> int:
    rows = VS.listing()
    if not rows:
        print(f"no snapshots yet in {VS.snapshots_dir()} (run `rsmm values snapshot`)")
        return 0
    for r in rows:
        print(f"{r['name']:<36} {st.dim('build')} {r.get('build_id') or '?':<10} "
              f"{st.dim(r.get('created', ''))}")
    return 0


def _diff(args, st: _term.Style) -> int:
    a = VS.load(args.a)
    b = VS.load(args.b) if args.b else VS.live(progress=_progress(st))
    changes = [c for c in VS.diff(a.values, b.values)
               if not args.filter or args.filter.lower() in f"{c.rel} {c.where}".lower()]
    if args.json:
        print(json.dumps([c.__dict__ for c in changes], indent=1))
        return 0
    label_b = args.b or "the install now"
    print(_term.rule(f"{args.a} -> {label_b}", st))
    if a.meta.get("build_id") and a.meta.get("build_id") == b.meta.get("build_id"):
        print(st.dim(f"  both are build {a.meta['build_id']}"))
    last = None
    for c in changes[: args.limit or None]:
        if c.rel != last:
            print(st.bold(c.rel.removeprefix("EntitySettings/").removesuffix(VS.ENTITY_SUFFIX)))
            last = c.rel
        if not c.where:
            print(f"  {st.ok('file added') if c.old is None else st.err('file removed')}")
        elif c.old is None:
            print(f"  {st.ok('+')} {c.where}: {c.new}")
        elif c.new is None:
            print(f"  {st.err('-')} {c.where}: {c.old}")
        else:
            old, new = _term.truncate(c.old, 80), _term.truncate(c.new, 80)
            print(f"  {c.where}: {st.dim(old)} -> {new}")
    files = len({c.rel for c in changes})
    more = f" (showing {args.limit})" if args.limit and len(changes) > args.limit else ""
    print(f"\n{len(changes)} change(s) in {files} file(s){more}")
    return 0


def _extract(args, _st: _term.Style) -> int:
    data = VS.restore_file(args.snapshot, args.path.replace("\\", "/"))
    Path(args.output).write_bytes(data)
    print(f"wrote {len(data)} bytes to {args.output}")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="rsmm values", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("snapshot", help="save the installed patch's values")
    p.add_argument("--name", help="snapshot name (default <date>-build<steam build id>)")
    p.add_argument("--out", help=f"parent directory (default {VS.snapshots_dir()})")
    sub.add_parser("list", help="the snapshots taken so far")
    p = sub.add_parser("diff", help="what changed between two snapshots, or since one")
    p.add_argument("a", help="snapshot name or directory")
    p.add_argument("b", nargs="?", help="second snapshot (default: the install now)")
    p.add_argument("--filter", help="only paths/fields containing this text")
    p.add_argument("--limit", type=int, default=0, help="print at most N changes")
    p.add_argument("--json", action="store_true")
    p = sub.add_parser("extract", help="one cooked file as a snapshot shipped it")
    p.add_argument("snapshot")
    p.add_argument("path", help="decoded path, e.g. EntitySettings/Heroes/...gen")
    p.add_argument("-o", "--output", required=True)
    args = ap.parse_args(argv)
    st = _term.Style()
    run = {"snapshot": _snapshot, "list": _list, "diff": _diff, "extract": _extract}[args.cmd]
    try:
        return run(args, st)
    except VS.SnapshotError as e:
        print(f"rsmm values: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
