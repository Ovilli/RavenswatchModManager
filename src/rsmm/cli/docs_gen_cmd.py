#!/usr/bin/env python3
"""`rsmm docs-gen` — write the SDK/CLI reference from @sdk_export registrations.

Writes plain Markdown to `docs/api/` (CI `--check`s it) and the same pages with
Starlight frontmatter to `apps/docs/src/content/docs/reference/sdk-api/` so they
render on the docs site. Also writes the `manifest.toml` JSON Schema
(`rsmm.sdk.manifest_spec`) to the docs site's public root, so editors can load
it from https://docs.rsmm.me/manifest.schema.json.
"""

from __future__ import annotations

import argparse
import filecmp
import json
import sys
import tempfile
from pathlib import Path

from rsmm.engine.paths import REPO_ROOT
from rsmm.sdk.docs_gen import generate

SITE_OUT = REPO_ROOT / "apps" / "docs" / "src" / "content" / "docs" / "reference" / "sdk-api"
SCHEMA_OUT = REPO_ROOT / "apps" / "docs" / "public" / "manifest.schema.json"


def _schema_text() -> str:
    from rsmm.sdk.manifest_spec import json_schema
    return json.dumps(json_schema(), indent=2, ensure_ascii=False) + "\n"


def _check_dir(out: Path, site: bool) -> list[str]:
    """Regenerate into a temp dir and diff against `out`. Returns problem lines."""
    problems: list[str] = []
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        if site:
            generate(None, site_out=tmp)
        else:
            generate(tmp)
        fresh = {p.relative_to(tmp) for p in tmp.rglob("*.md")}
        committed = {p.relative_to(out) for p in out.rglob("*.md")} if out.is_dir() else set()
        for r in sorted(fresh - committed):
            problems.append(f"  missing:   {out}/{r}")
        for r in sorted(committed - fresh):
            problems.append(f"  orphaned:  {out}/{r}")
        for r in sorted(r for r in (fresh & committed)
                        if not filecmp.cmp(tmp / r, out / r, shallow=False)):
            problems.append(f"  stale:     {out}/{r}")
    return problems


def _check(out: Path) -> int:
    problems = _check_dir(out, site=False) + _check_dir(SITE_OUT, site=True)
    if not SCHEMA_OUT.is_file():
        problems.append(f"  missing:   {SCHEMA_OUT}")
    elif SCHEMA_OUT.read_text(encoding="utf-8") != _schema_text():
        problems.append(f"  stale:     {SCHEMA_OUT}")
    if not problems:
        print(f"docs up to date ({out} + {SITE_OUT})")
        return 0
    print("docs out of date:", file=sys.stderr)
    for p in problems:
        print(p, file=sys.stderr)
    print("Run `rsmm docs-gen` and commit the result.", file=sys.stderr)
    return 1


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="rsmm docs-gen")
    ap.add_argument("--out", type=Path, default=REPO_ROOT / "docs" / "api")
    ap.add_argument(
        "--check",
        action="store_true",
        help="verify generated docs are current without writing (for CI); exit 1 if stale",
    )
    args = ap.parse_args(argv)
    if args.check:
        return _check(args.out)
    written = generate(args.out, site_out=SITE_OUT)
    SCHEMA_OUT.write_text(_schema_text(), encoding="utf-8")
    written.append(SCHEMA_OUT)
    # Both output dirs are wholly generated, so a page this run did not write
    # belongs to a module that no longer exists. `--check` already calls those
    # "orphaned"; delete them here so a plain regen leaves nothing to clean up.
    keep = {p.resolve() for p in written}
    for d in (args.out, SITE_OUT):
        for stale in sorted(d.rglob("*.md")) if d.is_dir() else []:
            if stale.resolve() not in keep:
                stale.unlink()
                shown = stale.relative_to(REPO_ROOT) if stale.is_relative_to(REPO_ROOT) else stale
                print(f"removed {shown}")
    print(f"wrote {len(written)} files ({args.out} + {SITE_OUT})")
    for p in written:
        try:
            print(f"  {p.relative_to(REPO_ROOT)}")
        except ValueError:
            print(f"  {p}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
