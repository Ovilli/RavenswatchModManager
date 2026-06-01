"""
Text-bank primitives: parse/write Ravenswatch cooked text files.

Library used by `rsmm.cli.merge` and `rsmm.engine.heroes`. Not user-facing;
mod authors call the SDK (`m.text(bank, lang, key, value)`).

Format (both base `.LocalText.gen` and per-language `.Ggzy<XX>` sibling):

  0x00  u32   header_size = 0x10
  0x04  u32   reserved    = 0
  0x08  u32   reserved    = 0
  0x0c  u32   entry_count
  0x10  u32   entry_count (capacity-ish; same value in practice)
  0x14  -- entries --
        u32   len_n
        len_n bytes of UTF-8

The footer (trailing padding/zeros after the last entry) is preserved
verbatim by `write_text_file`.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass
from pathlib import Path

HEADER_SIZE = 0x14


@dataclass
class TextFile:
    path: Path
    header: bytes
    entries: list[str]
    footer: bytes


def parse_text_file(path: Path) -> TextFile:
    data = path.read_bytes()
    if len(data) < HEADER_SIZE:
        raise ValueError(f"{path}: too short")
    count = struct.unpack_from("<I", data, 0x0c)[0]
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
    return TextFile(path=path, header=data[:HEADER_SIZE],
                    entries=entries, footer=data[pos:])


def write_text_file(tf: TextFile, count_override: int | None = None) -> bytes:
    count = count_override if count_override is not None else len(tf.entries)
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
    "ZH-S": "YA-F",
    "ZH-T": "YA-Q",
    "RAW": "LWR",
}
ALL_LANGS = list(DECODED_TO_ENCODED_LANG.keys())


def find_banks(cooking: Path, asset_map: dict[str, str]) -> dict[str, Path]:
    """short_name (e.g. 'Common', 'Hero_Beowulf_Common') -> base-file Path."""
    out: dict[str, Path] = {}
    for enc, dec in asset_map.items():
        if not dec.endswith(".LocalText.gen"):
            continue
        leaf = dec.split("\\")[-1]
        short = leaf.split("~")[0]
        p = cooking / Path(*enc.split("\\"))
        if p.exists():
            out[short] = p
    return out


def lang_path_for(base: Path, lang_decoded: str) -> Path:
    enc = DECODED_TO_ENCODED_LANG.get(lang_decoded.upper())
    if not enc:
        raise ValueError(f"unknown language code {lang_decoded!r}. Known: "
                         f"{', '.join(sorted(DECODED_TO_ENCODED_LANG))}")
    return base.with_name(base.name + f".Ggzy{enc}")


def _pristine(path: Path) -> Path:
    """Return the vanilla copy of a bank file: its ``.rsmm.bak`` sibling when a
    prior apply backed it up, otherwise the file itself."""
    bak = path.with_name(path.name + ".rsmm.bak")
    return bak if bak.exists() else path


def append_bank_keys(base_gen: Path, new_pairs: dict[str, str]) -> dict[str, bytes]:
    """Append new key/value text entries to a `~GAM.xls.LocalText` bank.

    A text bank is split across files that must stay index-aligned: the base
    `.LocalText.gen` holds the ordered KEYS, each `.Ggzy<XX>` sibling holds the
    ordered VALUES for one language. To add a new entry (e.g. a custom item's
    `<id>_Name`) the key is appended to the base and the display string to
    every existing language sibling at the same index.

    ``new_pairs`` maps key -> English display string (used as the value for all
    languages — a reasonable fallback until per-locale text is provided).
    Returns ``{decoded-or-relative path token: new bytes}`` keyed by the
    apply-layer decoded path: the base bank by its plain name and each sibling
    by the ``...gen.Lang<XX>`` form that ``resolve_special`` understands. Raises
    if a sibling's length doesn't match the base (corrupt/misaligned bank).

    Each file is read from its pristine ``.rsmm.bak`` when one exists, so
    re-running apply (without a restore first) rebuilds from the vanilla bank
    instead of stacking duplicate keys on an already-patched file.
    """
    keys = parse_text_file(_pristine(base_gen))
    base_count = len(keys.entries)
    new_keys = list(new_pairs.keys())
    new_vals = list(new_pairs.values())
    keys.entries.extend(new_keys)

    out: dict[str, bytes] = {"__base__": write_text_file(keys)}
    for lang in ALL_LANGS:
        sib = lang_path_for(base_gen, lang)
        psib = _pristine(sib)
        if not psib.exists():
            continue
        vf = parse_text_file(psib)
        if len(vf.entries) != base_count:
            raise ValueError(
                f"{sib.name}: {len(vf.entries)} values != {base_count} keys; "
                f"bank is misaligned, refusing to append"
            )
        vf.entries.extend(new_vals)
        out[f".Lang{lang}"] = write_text_file(vf)
    return out
