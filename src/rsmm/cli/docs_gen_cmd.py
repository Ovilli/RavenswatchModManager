#!/usr/bin/env python3
"""`rsmm docs-gen` — write docs/api/*.md from @sdk_export registrations."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from rsmm.engine.paths import REPO_ROOT
from rsmm.sdk.docs_gen import generate


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="rsmm docs-gen")
    ap.add_argument("--out", type=Path, default=REPO_ROOT / "docs" / "api")
    args = ap.parse_args(argv)
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
