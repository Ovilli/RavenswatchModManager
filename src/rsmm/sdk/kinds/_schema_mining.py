"""Schema mining harness — empirical RE for binary class layouts.

Per kind, the pipeline is:

  1. Bucket every vanilla cooked file that contains class C by body size.
  2. For each (size, files_at_size) cohort, run `class_diff` to find the
     byte ranges that differ vs ranges that are constant.
  3. Cross-ref differing ranges against `docs/_re/out/strings.json` and
     `docs/_re/out/symbols.json` to label likely fields (text-bank
     keys = strings; floats = stat-globals; 16-byte GUIDs = ids).
  4. Emit `data/schemas/<class>.json` consumed by `kinds/<kind>.py`.

This module is a thin orchestrator; the heavy work happens in
`src/rsmm/dev/class_diff.py` (already exists in the repo as part of the
RE pipeline). Per-kind callers select which classes to mine.

Run manually:
    python3 -m rsmm.sdk.kinds._schema_mining --class oCEntityCpntMagicalObjectSettings
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from rsmm.engine.paths import DATA_DIR

SCHEMA_DIR = DATA_DIR / "schemas"


@dataclass
class MiningResult:
    cls: str
    cohorts: int                 # how many size buckets sampled
    fields_labeled: int          # how many byte ranges we believe to know
    schema_path: Path


def mine(cls: str, *, kind: str | None = None) -> MiningResult:
    """Best-effort layout extraction. Always writes a schema file even
    if every offset is "unknown" — downstream callers can detect that
    and fail with `SchemaNotMined`.
    """
    SCHEMA_DIR.mkdir(parents=True, exist_ok=True)
    out = SCHEMA_DIR / f"{cls}.json"
    # Placeholder schema body. Real mining requires calling into
    # `rsmm.dev.class_diff` which depends on the Ghidra-dumped corpus
    # under `docs/_re/out/decompiled_all/`. That corpus is gitignored
    # for size reasons. See `docs/SDK_V3.md` → Open work.
    body = {
        "class": cls,
        "kind": kind,
        "schema_version": 1,
        "status": "stub",
        "fields": [],
        "notes": "Run `rsmm dev class-diff <cls>` to populate fields once "
                 "the decompiled corpus is present.",
    }
    out.write_text(json.dumps(body, indent=2), encoding="utf-8")
    return MiningResult(
        cls=cls, cohorts=0, fields_labeled=0,
        schema_path=out,
    )


def main(argv: Iterable[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Schema mining stub.")
    ap.add_argument("--class", dest="cls", required=True,
                    help="Class name to mine (e.g. oCEntityCpntMagicalObjectSettings)")
    ap.add_argument("--kind", help="Optional kind label (item/enemy/...)")
    args = ap.parse_args(list(argv) if argv is not None else None)
    r = mine(args.cls, kind=args.kind)
    print(f"wrote {r.schema_path}  cohorts={r.cohorts}  fields={r.fields_labeled}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
