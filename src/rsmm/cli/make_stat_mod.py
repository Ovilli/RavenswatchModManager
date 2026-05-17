#!/usr/bin/env python3
"""
Unified stat-patch mod generator.

Covers every Ravenswatch class whose cooked body has a known fixed-layout
numeric schema. One CLI for all of them.

Supported schemas (FINDINGS.md):

    oCGlobalEntityValueSettings (size=23)
        Single float at body+0x0c. 143 game-balance constants.

    GameModifierDefinition (size=29)
        Single float at body+0x15. 19 modifier deltas (damage/speed/...).

    oCDtEnemyCampDifficultyDefinition (size=18)
        Two floats: min (0x0a), max (0x0e). 6 difficulty bands.

Usage:

    # Browse every patchable field across every supported class.
    rsmm stat --list

    # Filter by class or fuzzy name match.
    rsmm stat --list --class oCGlobalEntityValueSettings
    rsmm stat --list --grep Bleed

    # Build a mod. Field syntax: <short_name>[:field]=<value>
    #   short_name is the cooked file stem (case-insensitive).
    #   :field selects a sub-field for multi-field classes (camp difficulty
    #   has :min / :max; single-field classes don't need a suffix).
    rsmm stat --mod-id BigBleed \\
        Bleed_Duration_Value=10 \\
        Hard:min=80 Hard:max=95

The applier (./rsmm apply) installs the resulting mod the usual way.
"""

from __future__ import annotations
import argparse
import struct
import sys
from dataclasses import dataclass
from pathlib import Path

from rsmm.engine.asset_map import encoded_to_decoded
from rsmm.engine.paths import (
    REPO_ROOT,
    MODS_DIR,
    DEFAULT_GAME_DIR as DEFAULT_GAME,
    COOKING_SUBDIR,
)

MARK_BEGIN = bytes.fromhex("1111bbaa")
MARK_END   = bytes.fromhex("2222bbaa")


@dataclass(frozen=True)
class Schema:
    cls: str
    decoded_suffix: str
    expected_body_size: int
    fields: tuple  # ((field_name, offset, struct_fmt), ...)


SCHEMAS: tuple[Schema, ...] = (
    Schema(
        cls="oCGlobalEntityValueSettings",
        decoded_suffix=".globalvalue.ot.GlobalEntityValueSettings.gen",
        expected_body_size=23,
        fields=(("value", 0x0c, "<f"),),
    ),
    Schema(
        cls="GameModifierDefinition",
        decoded_suffix=".gamemodifierdef.ot.meModifierDefinition.gen",
        expected_body_size=29,
        fields=(("value", 0x15, "<f"),),
    ),
    Schema(
        cls="oCDtEnemyCampDifficultyDefinition",
        decoded_suffix=".enemycampdifficultydef.ot.DtEnemyCampDifficultyDefinition.gen",
        expected_body_size=18,
        fields=(
            ("min", 0x0a, "<f"),
            ("max", 0x0e, "<f"),
        ),
    ),
)


@dataclass
class Entry:
    schema: Schema
    cooked_path: Path
    decoded_relpath: str
    short_name: str   # filename stem before first '.'
    values: dict[str, float]   # field_name -> current value


def index_entries(cooking: Path, asset_map: dict[str, str]) -> list[Entry]:
    by_suffix: dict[str, Schema] = {s.decoded_suffix.lower(): s for s in SCHEMAS}
    entries: list[Entry] = []
    for enc_rel, dec_rel in asset_map.items():
        low = dec_rel.lower()
        match: Schema | None = None
        for suf, sch in by_suffix.items():
            if low.endswith(suf):
                match = sch
                break
        if match is None:
            continue
        p = cooking / Path(*enc_rel.split("\\"))
        if not p.exists():
            continue
        try:
            d = p.read_bytes()
        except OSError:
            continue
        lb = d.rfind(MARK_BEGIN)
        le = d.rfind(MARK_END)
        if lb == -1 or le <= lb:
            continue
        body = d[lb + 4:le]
        if len(body) != match.expected_body_size:
            continue
        values: dict[str, float] = {}
        for field_name, off, fmt in match.fields:
            values[field_name] = struct.unpack_from(fmt, body, off)[0]
        short = Path(dec_rel.split("\\")[-1]).name.split(".")[0]
        entries.append(Entry(
            schema=match,
            cooked_path=p,
            decoded_relpath=dec_rel.replace("\\", "/"),
            short_name=short,
            values=values,
        ))
    return entries


def cmd_list(entries: list[Entry], filt_class: str | None, grep: str | None) -> int:
    by_class: dict[str, list[Entry]] = {}
    for e in entries:
        by_class.setdefault(e.schema.cls, []).append(e)
    needle = grep.lower() if grep else None
    for cls, group in by_class.items():
        if filt_class and filt_class != cls:
            continue
        kept = [e for e in group
                if not needle or needle in e.short_name.lower()]
        if not kept:
            continue
        print(f"# {cls}  ({len(kept)} entries)")
        for e in sorted(kept, key=lambda x: x.short_name.lower()):
            if len(e.schema.fields) == 1:
                fn, _, _ = e.schema.fields[0]
                print(f"  {e.values[fn]:>12.4f}   {e.short_name}")
            else:
                vs = "  ".join(
                    f"{fn}={e.values[fn]:.4f}" for fn, _, _ in e.schema.fields
                )
                print(f"  {e.short_name:<48s} {vs}")
        print()
    return 0


def patch_field(cooked: bytes, schema: Schema, field_name: str, value: float) -> bytes:
    lb = cooked.rfind(MARK_BEGIN)
    le = cooked.rfind(MARK_END)
    if lb == -1 or le <= lb:
        raise ValueError("cooked file has no BEGIN/END markers")
    body_start = lb + 4
    body_len = le - body_start
    if body_len != schema.expected_body_size:
        raise ValueError(
            f"unexpected body size {body_len} (want {schema.expected_body_size})"
        )
    for fn, off, fmt in schema.fields:
        if fn == field_name:
            out = bytearray(cooked)
            struct.pack_into(fmt, out, body_start + off, value)
            return bytes(out)
    raise ValueError(f"unknown field {field_name!r} for {schema.cls}")


def parse_overrides(args: list[str]) -> list[tuple[str, str, float]]:
    """returns (short_name, field_name_or_empty, value)."""
    out: list[tuple[str, str, float]] = []
    for raw in args:
        if "=" not in raw:
            raise SystemExit(f"override must be NAME=VALUE, got: {raw!r}")
        lhs, _, rhs = raw.partition("=")
        try:
            v = float(rhs.strip())
        except ValueError:
            raise SystemExit(f"value must be a float: {raw!r}")
        if ":" in lhs:
            short, _, field = lhs.partition(":")
        else:
            short, field = lhs, ""
        out.append((short.strip(), field.strip(), v))
    return out


def cmd_make(args, entries: list[Entry]) -> int:
    overrides = parse_overrides(args.assignments)
    by_short: dict[str, list[Entry]] = {}
    for e in entries:
        by_short.setdefault(e.short_name.lower(), []).append(e)

    mod_dir = MODS_DIR / args.mod_id
    assets = mod_dir / "assets"
    if mod_dir.exists() and not args.force:
        print(f"mod dir exists: {mod_dir}. Use --force to overwrite.", file=sys.stderr)
        return 1
    mod_dir.mkdir(parents=True, exist_ok=True)
    assets.mkdir(parents=True, exist_ok=True)

    # group writes by destination so multi-field patches collapse into one file
    pending: dict[str, tuple[Entry, dict[str, float]]] = {}

    for short, field, value in overrides:
        candidates = by_short.get(short.lower(), [])
        if not candidates:
            print(f"  [skip] no entry named {short!r}", file=sys.stderr)
            continue
        if len(candidates) > 1:
            wanted = [c for c in candidates if any(
                fn == (field or c.schema.fields[0][0]) for fn, _, _ in c.schema.fields
            )]
            if len(wanted) != 1:
                names = [c.schema.cls for c in candidates]
                print(f"  [skip] {short!r} ambiguous across classes: {names}",
                      file=sys.stderr)
                continue
            entry = wanted[0]
        else:
            entry = candidates[0]
        fname = field or entry.schema.fields[0][0]
        if fname not in {fn for fn, _, _ in entry.schema.fields}:
            valid = [fn for fn, _, _ in entry.schema.fields]
            print(f"  [skip] {short!r} has no field {fname!r}; valid: {valid}",
                  file=sys.stderr)
            continue
        slot = pending.setdefault(entry.decoded_relpath, (entry, {}))
        slot[1][fname] = value

    if not pending:
        print("Nothing applied.", file=sys.stderr)
        return 1

    applied_rows: list[tuple[str, str, str, str]] = []
    for decoded, (entry, fields) in pending.items():
        data = entry.cooked_path.read_bytes()
        for fname, value in fields.items():
            data = patch_field(data, entry.schema, fname, value)
        dest = assets / decoded
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)
        for fname, value in fields.items():
            old = entry.values[fname]
            applied_rows.append((entry.short_name, fname, f"{old:g}", f"{value:g}"))

    desc = args.name or f"Patches {len(applied_rows)} stat field(s)"
    (mod_dir / "manifest.toml").write_text(
        "# Generated by rsmm stat\n"
        "[mod]\n"
        f'id          = "{args.mod_id}"\n'
        f'name        = "{desc}"\n'
        f'version     = "1.0.0"\n'
        f'author      = "{args.author}"\n'
        f'description = "Patches numeric fields in known cooked schemas."\n'
        "enabled     = true\n",
        encoding="utf-8",
    )
    lines = [f"# {args.mod_id}", "", "Patched fields:", ""]
    for short, fname, old, new in applied_rows:
        lines.append(f"- `{short}:{fname}`: {old} -> {new}")
    lines += ["", "Install with `./rsmm apply` from the repo root.", ""]
    (mod_dir / "README.md").write_text("\n".join(lines), encoding="utf-8")

    print(f"Wrote mod {args.mod_id} with {len(applied_rows)} patched field(s).")
    for short, fname, old, new in applied_rows:
        print(f"  {short}:{fname}  {old} -> {new}")
    print("\nNext: ./rsmm apply")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--game-dir", type=Path, default=DEFAULT_GAME)
    ap.add_argument("--list", action="store_true",
                    help="print all patchable fields and exit")
    ap.add_argument("--class", dest="cls", default=None,
                    help="restrict --list to one class")
    ap.add_argument("--grep", default=None,
                    help="filter --list by substring of the field short name")
    ap.add_argument("--mod-id", default="StatMod",
                    help="output mod folder name under mods/")
    ap.add_argument("--name", default=None,
                    help="display name of the generated mod")
    ap.add_argument("--author", default="RSMM",
                    help="author field for manifest")
    ap.add_argument("--force", action="store_true",
                    help="overwrite an existing mod dir")
    ap.add_argument("assignments", nargs="*",
                    help="NAME[:FIELD]=VALUE assignments")
    args = ap.parse_args()

    cooking = args.game_dir / COOKING_SUBDIR
    if not cooking.is_dir():
        print(f"_Cooking not found: {cooking}", file=sys.stderr)
        return 1
    entries = index_entries(cooking, encoded_to_decoded())
    if not entries:
        print("No patchable entries found across known schemas.", file=sys.stderr)
        return 1

    if args.list:
        return cmd_list(entries, args.cls, args.grep)
    if not args.assignments:
        ap.print_help()
        return 2
    return cmd_make(args, entries)


if __name__ == "__main__":
    sys.exit(main())
