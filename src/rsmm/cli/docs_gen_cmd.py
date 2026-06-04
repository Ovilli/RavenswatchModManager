#!/usr/bin/env python3
"""`rsmm docs-gen` — write docs/api/*.md from @sdk_export registrations + the CLI table."""

from __future__ import annotations

import argparse
import filecmp
import sys
import tempfile
from pathlib import Path

from rsmm.engine.paths import REPO_ROOT
from rsmm.sdk.docs_gen import generate


def _check(out: Path) -> int:
    """Regenerate into a temp dir and diff against `out`. Non-zero if stale."""
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        generate(tmp)
        fresh = {p.relative_to(tmp) for p in tmp.rglob("*.md")}
        committed = {p.relative_to(out) for p in out.rglob("*.md")} if out.is_dir() else set()
        missing = sorted(fresh - committed)
        extra = sorted(committed - fresh)
        changed = sorted(
            r for r in (fresh & committed)
            if not filecmp.cmp(tmp / r, out / r, shallow=False)
        )
        if not (missing or extra or changed):
            print(f"docs up to date ({len(fresh)} files in {out})")
            return 0
        print(f"docs out of date in {out}:", file=sys.stderr)
        for r in missing:
            print(f"  missing:   {r}", file=sys.stderr)
        for r in changed:
            print(f"  stale:     {r}", file=sys.stderr)
        for r in extra:
            print(f"  orphaned:  {r}", file=sys.stderr)
        print("Run `rsmm docs-gen` and commit the result.", file=sys.stderr)
        return 1


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="rsmm docs-gen")
    ap.add_argument("--out", type=Path, default=REPO_ROOT / "docs" / "api")
    ap.add_argument(
        "--check",
        action="store_true",
        help="verify docs/api is current without writing (for CI); exit 1 if stale",
    )
    args = ap.parse_args(argv)
    if args.check:
        return _check(args.out)
    written = generate(args.out)
    print(f"wrote {len(written)} files to {args.out}")
    for p in written:
        try:
            print(f"  {p.relative_to(REPO_ROOT)}")
        except ValueError:
            print(f"  {p}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
