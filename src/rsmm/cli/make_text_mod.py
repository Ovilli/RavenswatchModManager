#!/usr/bin/env python3
"""
Generate a mod that patches Ravenswatch translation strings.

Format reverse-engineered:

  Each translatable subject (a hero, a level, "Common", etc.) has a *pair*
  of cooked files under `_Cooking/Qqpi/` (decoded `Text/`):

    <Name>~GAM.xls.LocalText.gen                       (keys, ordered)
    <Name>~GAM.xls.LocalText.gen.Lang<XX>              (values, ordered)

  Both are flat arrays of length-prefixed UTF-8 strings with a small
  fixed header. Strings are matched by index — `keys[i]` corresponds to
  `values[i]` in the per-language file.

This tool resolves a (text-bank, key) -> (file, index) lookup, patches
the value in the chosen language file, and emits a mod directory ready
for `./rsmm apply`.

Format (both base and lang files):

  0x00  u32   header_size = 0x10
  0x04  u32   reserved    = 0
  0x08  u32   reserved    = 0
  0x0c  u32   entry_count
  0x10  u32   entry_count (same; maybe capacity)
  0x14  -- entries --
        u32   len_n
        len_n bytes of UTF-8

The footer (everything after the last entry) is verbatim padding/zeros
in the wild; we preserve it exactly.

Usage:

  # browse what's in a text bank
  rsmm text --list Common --lang EN

  # tweak a value
  rsmm text --mod-id LessVulnerableUI \
      Common~EN:Common_Quit="Quit (modded)" \
      Common~EN:Game_You_Died="ouch"
"""

from __future__ import annotations
import argparse
import json
import re
import struct
import sys
from dataclasses import dataclass
from pathlib import Path

from rsmm.engine.paths import (
    REPO_ROOT,
    DATA_DIR,
    MODS_DIR,
    ASSET_MAP_JSON,
    ASSET_MAP_CSV,
    DEFAULT_GAME_DIR as DEFAULT_GAME,
    COOKING_SUBDIR,
)

HEADER_SIZE = 0x14   # 0x10 (4 u32 header) + u32 entry_count + u32 cap?
# Actually file body starts right after the u32 cap at offset 0x14.


@dataclass
class TextFile:
    path: Path
    header: bytes        # bytes 0x00..0x14 (counts + leading u32s)
    entries: list[str]
    footer: bytes        # any trailing padding after last entry


def parse_text_file(path: Path) -> TextFile:
    data = path.read_bytes()
    if len(data) < HEADER_SIZE:
        raise ValueError(f"{path}: too short")
    count = struct.unpack_from("<I", data, 0x0c)[0]
    # data[0x10..0x14] is a sibling count that sometimes equals `count`,
    # sometimes a separate field; we trust `count`. Read kept commented
    # so a future RE pass knows where to look.
    # count2 = struct.unpack_from("<I", data, 0x10)[0]
    pos = HEADER_SIZE
    entries: list[str] = []
    for _ in range(count):
        if pos + 4 > len(data):
            raise ValueError(f"{path}: truncated at entry {len(entries)}")
        n = struct.unpack_from("<I", data, pos)[0]
        pos += 4
        if pos + n > len(data) or n > (1 << 20):
            raise ValueError(f"{path}: bad length {n} at entry {len(entries)}")
        s = data[pos:pos + n].decode("utf-8", errors="replace")
        entries.append(s)
        pos += n
    footer = data[pos:]
    return TextFile(path=path, header=data[:HEADER_SIZE],
                    entries=entries, footer=footer)


def write_text_file(tf: TextFile, count_override: int | None = None) -> bytes:
    count = count_override if count_override is not None else len(tf.entries)
    # rewrite count fields in header
    head = bytearray(tf.header)
    struct.pack_into("<I", head, 0x0c, count)
    struct.pack_into("<I", head, 0x10, count)
    out = bytearray(head)
    for s in tf.entries:
        b = s.encode("utf-8")
        out += struct.pack("<I", len(b))
        out += b
    out += tf.footer
    return bytes(out)


# Language code mapping. The on-disk suffix is the cipher-encoded form of
# the decoded language code (which uses ASCII 2-letter ISO codes).
DECODED_TO_ENCODED_LANG = {
    "EN": "MU",
    "JA": "EW",
    "KO": "IO",
    "RU": "LJ",
    "ES": "MF",
    "DE": "NM",
    "PL": "TG",
    "FR": "VL",
    "IT": "XQ",
    "PT-BR": "TQ-BL",
    # Cipher: Y->Y stays as itself; A->H, F->S, Q->T per find_iyg.py.
    # YA-F decodes to YH-S (Simplified Chinese), YA-Q to YH-T (Traditional).
    "ZH-S": "YA-F",
    "ZH-T": "YA-Q",
    # "RAW" is the in-game debug pseudo-locale: each string prefixed with '*'
    # so testers can spot un-translated keys. Game appears to default to this
    # in vanilla un-localized builds. Note the cipher gives the literal
    # encoded form "LWR".
    "RAW": "LWR",
}
ALL_LANGS = list(DECODED_TO_ENCODED_LANG.keys())


def find_banks(cooking: Path, asset_map: dict[str, str]) -> dict[str, Path]:
    """short_name (e.g. 'Common', 'Hero_Beowulf_Common') -> base-file path."""
    out: dict[str, Path] = {}
    for enc, dec in asset_map.items():
        if not dec.endswith(".LocalText.gen"):
            continue
        # strip Text\ prefix and ~GAM.xls.LocalText.gen suffix
        leaf = dec.split("\\")[-1]
        short = leaf.split("~")[0]
        p = cooking / Path(*enc.split("\\"))
        if p.exists():
            out[short] = p
    return out


def parse_assignment(arg: str) -> list[tuple[str, str, str, str]]:
    """`Bank~LANG:Key=Value` -> list of (bank, lang, key, value).

    LANG may be `ALL`, which expands to every known language code.
    Returns a list because of the ALL expansion; a normal assignment
    yields a one-element list.
    """
    m = re.match(r"^([^~]+)~([^:]+):([^=]+)=(.*)$", arg, re.DOTALL)
    if not m:
        raise SystemExit(f"bad assignment {arg!r} (expected Bank~LANG:Key=Value)")
    bank, lang, key, val = m.group(1), m.group(2).upper(), m.group(3), m.group(4)
    if lang == "ALL":
        return [(bank, L, key, val) for L in ALL_LANGS]
    return [(bank, lang, key, val)]


def lang_path_for(base: Path, lang_decoded: str) -> Path:
    enc = DECODED_TO_ENCODED_LANG.get(lang_decoded.upper())
    if not enc:
        raise SystemExit(f"unknown language code {lang_decoded!r}. Known: "
                         f"{', '.join(sorted(DECODED_TO_ENCODED_LANG))}")
    return base.with_name(base.name + f".Ggzy{enc}")


def cmd_list(banks: dict[str, Path], bank_name: str, lang_decoded: str,
             grep: str | None) -> int:
    if bank_name not in banks:
        # try case-insensitive lookup
        for k in banks:
            if k.lower() == bank_name.lower():
                bank_name = k
                break
        else:
            print(f"text bank not found: {bank_name!r}", file=sys.stderr)
            print(f"available (first 30): {', '.join(sorted(banks)[:30])}",
                  file=sys.stderr)
            return 1
    base = banks[bank_name]
    lang_p = lang_path_for(base, lang_decoded)
    base_tf = parse_text_file(base)
    lang_tf = parse_text_file(lang_p) if lang_p.exists() else None
    if not lang_tf:
        print(f"# (no {lang_decoded} file present at {lang_p})")
    n = len(base_tf.entries)
    if lang_tf and len(lang_tf.entries) != n:
        print(f"# WARN: count mismatch base={n} lang={len(lang_tf.entries)}")
    for i, key in enumerate(base_tf.entries):
        val = lang_tf.entries[i] if lang_tf and i < len(lang_tf.entries) else ""
        if grep and grep.lower() not in key.lower() and grep.lower() not in val.lower():
            continue
        # collapse multi-line values for readability
        display_val = val.replace("\n", " \\n ")
        print(f"  [{i:>4d}]  {key}\n          \"{display_val}\"")
    return 0


def cmd_make(args, asset_map: dict[str, str], banks: dict[str, Path]) -> int:
    if not args.assignments:
        print("no assignments given", file=sys.stderr)
        return 2
    # group assignments by (bank, lang); LANG=ALL expands to every code
    grouped: dict[tuple[str, str], list[tuple[str, str]]] = {}
    for raw in args.assignments:
        for bank, lang, key, val in parse_assignment(raw):
            grouped.setdefault((bank, lang), []).append((key, val))

    mod_dir = MODS_DIR / args.mod_id
    if mod_dir.exists() and not args.force:
        print(f"mod dir exists: {mod_dir}; use --force", file=sys.stderr)
        return 1
    mod_dir.mkdir(parents=True, exist_ok=True)
    assets = mod_dir / "assets"
    assets.mkdir(parents=True, exist_ok=True)

    applied: list[tuple[str, str, str, str, str]] = []   # (bank,lang,key,old,new)
    for (bank, lang), pairs in grouped.items():
        if bank not in banks:
            # case-insensitive
            for k in banks:
                if k.lower() == bank.lower():
                    bank = k
                    break
            else:
                print(f"  [skip] no text bank {bank!r}", file=sys.stderr)
                continue
        base = banks[bank]
        lang_p = lang_path_for(base, lang)
        if not lang_p.exists():
            print(f"  [skip] no {lang} file for {bank}: {lang_p}", file=sys.stderr)
            continue
        base_tf = parse_text_file(base)
        lang_tf = parse_text_file(lang_p)
        key_to_idx = {k: i for i, k in enumerate(base_tf.entries)}
        for key, new_val in pairs:
            idx = key_to_idx.get(key)
            if idx is None:
                print(f"  [skip] {bank}~{lang}: no key {key!r}", file=sys.stderr)
                continue
            old = lang_tf.entries[idx] if idx < len(lang_tf.entries) else ""
            if idx >= len(lang_tf.entries):
                lang_tf.entries.append(new_val)
            else:
                lang_tf.entries[idx] = new_val
            applied.append((bank, lang, key, old, new_val))
        # write modified lang file under assets/
        decoded_lang_rel = asset_map.get(
            str(lang_p.relative_to(args.game_dir / COOKING_SUBDIR)
                ).replace("/", "\\"))
        if not decoded_lang_rel:
            # asset_map only indexes base .LocalText.gen, not the .Lang* siblings.
            # Recover the decoded sibling path from base's decoded path + suffix.
            enc_rel = str(lang_p.relative_to(
                args.game_dir / COOKING_SUBDIR
            )).replace("/", "\\")
            base_enc_rel = str(base.relative_to(
                args.game_dir / COOKING_SUBDIR
            )).replace("/", "\\")
            base_dec = asset_map.get(base_enc_rel, base_enc_rel)
            suffix = enc_rel[len(base_enc_rel):]   # e.g. ".GgzyMU"
            # decode suffix: ".Ggzy<XX>" -> ".Lang<dec>"
            m = re.match(r"\.Ggzy(.+)$", suffix)
            if m:
                enc_lang = m.group(1)
                # invert DECODED_TO_ENCODED_LANG
                for dec_lang, enc_l in DECODED_TO_ENCODED_LANG.items():
                    if enc_l == enc_lang:
                        decoded_lang_rel = base_dec + f".Lang{dec_lang}"
                        break
                else:
                    decoded_lang_rel = base_dec + f".Lang_{enc_lang}"
            else:
                decoded_lang_rel = base_dec + suffix
        dest = assets / Path(*decoded_lang_rel.replace("\\", "/").split("/"))
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(write_text_file(lang_tf))
        print(f"  wrote {decoded_lang_rel}  ({len(lang_tf.entries)} entries)")

    if not applied:
        print("nothing applied", file=sys.stderr)
        return 1

    manifest = mod_dir / "manifest.toml"
    manifest.write_text(
        f"# Generated by rsmm text\n"
        f"[mod]\n"
        f'id          = "{args.mod_id}"\n'
        f'name        = "{args.name or args.mod_id}"\n'
        f'version     = "1.0.0"\n'
        f'author      = "{args.author}"\n'
        f'description = "Patches translation strings."\n'
        f"enabled     = true\n",
        encoding="utf-8",
    )
    readme = mod_dir / "README.md"
    lines = [f"# {args.mod_id}", "", "Patched translations:", ""]
    for bank, lang, key, old, new in applied:
        lines.append(f"- `{bank}~{lang}:{key}`")
        lines.append(f"    was: {old!r}")
        lines.append(f"    now: {new!r}")
    lines += ["", "Install with `./rsmm apply`.", ""]
    readme.write_text("\n".join(lines), encoding="utf-8")

    print(f"\nWrote mod {args.mod_id} with {len(applied)} string change(s).")
    print("Next: ./rsmm apply")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--game-dir", type=Path, default=DEFAULT_GAME)
    ap.add_argument("--list", metavar="BANK",
                    help="dump (key, value) pairs from a text bank")
    ap.add_argument("--lang", default="EN",
                    help="language code to read/write (default EN)")
    ap.add_argument("--grep", default=None,
                    help="filter --list output by substring")
    ap.add_argument("--mod-id", default="TextMod")
    ap.add_argument("--name", default=None)
    ap.add_argument("--author", default="RSMM")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("assignments", nargs="*",
                    help="Bank~LANG:Key=Value pairs")
    args = ap.parse_args()

    cooking = args.game_dir / COOKING_SUBDIR
    if not cooking.is_dir():
        print(f"_Cooking not found: {cooking}", file=sys.stderr)
        return 1
    asset_map = json.loads((ASSET_MAP_JSON).read_text(encoding="utf-8"))
    banks = find_banks(cooking, asset_map)

    if args.list:
        return cmd_list(banks, args.list, args.lang, args.grep)
    return cmd_make(args, asset_map, banks)


if __name__ == "__main__":
    sys.exit(main())
