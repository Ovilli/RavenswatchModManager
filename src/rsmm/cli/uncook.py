"""rsmm uncook — extract a cooked asset to an editable source-format file.

The cooked container is parsed by `rsmm.engine.cooked` (always works). The
per-class payload schema dispatches via `rsmm.engine.cooked_schemas`. When the
schema isn't reversed yet, `--raw` is still available and dumps the section
payload bytes directly so byte-level mods are unblocked.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from rsmm.engine import cooked, cooked_schemas


def _resolve_output(input_path: Path, out: Path | None, source_ext: str) -> Path:
    if out is not None:
        return out
    return input_path.with_suffix(f".{source_ext}")


def main() -> int:
    ap = argparse.ArgumentParser(
        prog="rsmm uncook",
        description="Extract a cooked Ravenswatch asset to a source-format file.",
    )
    ap.add_argument("input", type=Path, help="cooked file (.yqz / .tpi / .zux / .gen)")
    ap.add_argument(
        "-o", "--output", type=Path, default=None,
        help="output path (default: <input>.<source-ext>)",
    )
    ap.add_argument(
        "--raw", action="store_true",
        help="bypass schema, write the concatenated section payloads as raw bytes",
    )
    ap.add_argument(
        "--section", type=int, default=None,
        help="with --raw, write only this section (0-indexed)",
    )
    ap.add_argument(
        "--info", action="store_true",
        help="print container header + class table, do not write any file",
    )
    ap.add_argument(
        "--json", action="store_true",
        help="with --info, emit structured JSON on stdout (for tools / UI)",
    )
    args = ap.parse_args()

    if not args.input.exists():
        print(f"input not found: {args.input}", file=sys.stderr)
        return 1

    data = args.input.read_bytes()
    cf = cooked.parse(data)
    root_class = cf.classes[0].name if cf.classes else "<unknown>"

    if args.info:
        if args.json:
            import json as _json
            handler = cooked_schemas.get(root_class)
            print(_json.dumps({
                "path": str(args.input),
                "size": len(data),
                "variant": cf.variant,
                "flags": cf.flags,
                "extra": cf.extra,
                "type_tag": cf.type_tag,
                "root_class": root_class,
                "schema_status": "stub" if isinstance(
                    handler, cooked_schemas.SchemaHandler
                ) and not handler.decoded else "raw",
                "source_ext": handler.source_ext,
                "classes": [
                    {
                        "name": cls.name,
                        "uid": f"{cls.class_id:#010x}",
                        "version": [cls.version_major, cls.version_minor],
                        "parent": f"{cls.parent_id:#010x}",
                    }
                    for cls in cf.classes
                ],
                "sections": [
                    {"index": i, "size": len(sec.payload)}
                    for i, sec in enumerate(cf.sections)
                ],
            }))
            return 0
        print(f"variant={cf.variant} flags={cf.flags:#x} extra={cf.extra} "
              f"type_tag={cf.type_tag:#x}")
        print(f"classes ({len(cf.classes)}):")
        for cls in cf.classes:
            print(f"  {cls.name}  uid={cls.class_id:#010x}  "
                  f"v={cls.version_major}.{cls.version_minor}  "
                  f"parent={cls.parent_id:#010x}")
        print(f"sections ({len(cf.sections)}):")
        for i, sec in enumerate(cf.sections):
            print(f"  [{i}] payload={len(sec.payload)} bytes")
        return 0

    if args.raw:
        if args.section is not None:
            if args.section < 0 or args.section >= len(cf.sections):
                print(f"--section {args.section} out of range (0..{len(cf.sections)-1})",
                      file=sys.stderr)
                return 1
            out_bytes = cf.sections[args.section].payload
        else:
            out_bytes = b"".join(sec.payload for sec in cf.sections)
        out_path = _resolve_output(args.input, args.output, "raw")
        out_path.write_bytes(out_bytes)
        print(f"wrote {out_path} ({len(out_bytes)} bytes from {root_class})")
        return 0

    handler = cooked_schemas.get(root_class)
    try:
        # Default mapping: concatenate non-prelude section payloads. Once
        # per-class schemas land, handler.decode will accept the structured
        # CookedFile / per-class section split instead of a flat blob.
        payload = b"".join(sec.payload for sec in cf.sections)
        decoded = handler.decode(payload)
    except cooked_schemas.NotReversedError as e:
        print(f"{e}", file=sys.stderr)
        print("Pass --raw to extract section bytes directly, or "
              "--info to inspect the container.", file=sys.stderr)
        return 2

    out_path = _resolve_output(args.input, args.output, handler.source_ext)
    out_path.write_bytes(decoded)
    print(f"wrote {out_path} ({len(decoded)} bytes from {root_class})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
