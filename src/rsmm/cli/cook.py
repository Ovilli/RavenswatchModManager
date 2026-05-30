"""rsmm cook — pack an editable source-format file into a cooked asset.

Mirror of `rsmm uncook`. Source extension (or --class) selects the schema
handler. Class table + version come from a template file: either a sibling
`.tpl.json` describing the registry, or by referencing an existing cooked
file to copy its header from. The latter is the practical path for mod
authors — replicate a shipped file's structure, swap in new payload bytes.

When the schema is not yet reversed (most classes today), this command
errors with a NotReversedError. Use the source's matching reference cooked
file via `--from <reference.yqz>` + `--raw` to bypass schema and substitute
the section payload verbatim — useful for byte-replace mods authored as
edits to a hex-dumped raw payload.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from rsmm.engine import cooked, cooked_schemas


def main() -> int:
    ap = argparse.ArgumentParser(
        prog="rsmm cook",
        description="Pack a source asset into a cooked Ravenswatch file.",
    )
    ap.add_argument("input", type=Path,
                    help="source file (.gltf / .dds / .png / .raw / ...)")
    ap.add_argument("-o", "--output", type=Path, default=None,
                    help="output path (default: <input>.yqz)")
    ap.add_argument(
        "--class", dest="class_name", default=None,
        help="override class name (default: inferred from --from reference)",
    )
    ap.add_argument(
        "--from", dest="reference", type=Path, default=None,
        help="reference cooked file to copy header/class-table/version from. "
             "Required until schema-only cooking is supported.",
    )
    ap.add_argument(
        "--raw", action="store_true",
        help="treat input as already-cooked section payload bytes; "
             "skip schema encoding. Requires --from for container framing.",
    )
    ap.add_argument(
        "--section", type=int, default=None,
        help="with --raw, replace only this section's payload "
             "(0-indexed). Other sections copied from --from verbatim.",
    )
    args = ap.parse_args()

    if not args.input.exists():
        print(f"input not found: {args.input}", file=sys.stderr)
        return 1
    if args.reference is None:
        print(
            "cook currently requires --from <reference.yqz> to derive the "
            "container header + class table. Schema-only cooking lands once "
            "per-class encoders are implemented (see docs/RE_NOTES.md).",
            file=sys.stderr,
        )
        return 2

    ref_data = args.reference.read_bytes()
    cf = cooked.parse(ref_data)
    root_class = args.class_name or (cf.classes[0].name if cf.classes else "")
    if not root_class:
        print("could not determine class — pass --class explicitly", file=sys.stderr)
        return 1

    src_bytes = args.input.read_bytes()

    if args.raw:
        if args.section is None:
            # Whole payload replacement: pack as one section.
            cf.sections = [cooked.Section(payload=src_bytes)]
        else:
            if args.section < 0 or args.section >= len(cf.sections):
                print(f"--section {args.section} out of range "
                      f"(0..{len(cf.sections)-1})", file=sys.stderr)
                return 1
            cf.sections[args.section] = cooked.Section(payload=src_bytes)
    else:
        handler = cooked_schemas.get(root_class)
        try:
            payload = handler.encode(src_bytes)
        except cooked_schemas.NotReversedError as e:
            print(f"{e}", file=sys.stderr)
            print("Use --raw + --from + --section to substitute section bytes "
                  "directly without going through the schema.", file=sys.stderr)
            return 2
        # Single-section replacement: assumes the leaf class owns the last
        # section. Prelude sections (e.g. oIResource) copied from --from
        # unchanged. Once oIResource schema lands the encoder can rebuild
        # the prelude too.
        cf.sections[-1] = cooked.Section(payload=payload)

    out_path = args.output or args.input.with_suffix(".yqz")
    out_path.write_bytes(cooked.emit(cf))
    print(f"wrote {out_path} ({len(out_path.read_bytes())} bytes, class={root_class})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
