#!/usr/bin/env python3
"""
Ravenswatch Asset Decrypter — builds a full obfuscated -> plaintext
mapping from UsedRscList.ot using the substitution cipher discovered
during RE. Output goes to `data/asset_map.json` + `data/asset_map.csv`.
"""

from __future__ import annotations
import csv
import json
import os
import sys

from .paths import ASSET_MAP_JSON, ASSET_MAP_CSV

# ── Complete substitution tables (case‑sensitive) ──────────────────
LOWER = {
    'a':'b', 'b':'c', 'c':'j', 'd':'i', 'e':'v', 'f':'q', 'g':'a',
    'h':'f', 'i':'t', 'j':'p', 'k':'v', 'l':'l', 'm':'k', 'n':'h',
    'o':'w', 'p':'x', 'q':'e', 'r':'o', 's':'y', 't':'d', 'u':'r',
    'v':'s', 'w':'u', 'x':'m', 'y':'g', 'z':'n',
}
UPPER = {
    'A':'H', 'B':'B', 'C':'Y', 'D':'V', 'E':'J', 'F':'S', 'G':'L',
    'H':'M', 'I':'K', 'J':'U', 'K':'G', 'L':'R', 'M':'E', 'N':'D',
    'O':'O', 'P':'Q', 'Q':'T', 'R':'W', 'S':'C', 'T':'P', 'U':'N',
    'V':'F', 'W':'A', 'X':'I', 'Y':'Y', 'Z':'I',
}
SYMBOLS = {'!': '\\'}


def decrypt_char(c: str) -> str:
    if c in SYMBOLS: return SYMBOLS[c]
    if c.isupper() and c in UPPER: return UPPER[c]
    if c.islower() and c in LOWER: return LOWER[c]
    return c


def decrypt_string(s: str) -> str:
    return ''.join(decrypt_char(ch) for ch in s)


def main() -> int:
    default = os.path.expanduser(
        "~/.var/app/com.valvesoftware.Steam/.local/share/Steam/"
        "steamapps/common/Ravenswatch/DarkTalesResources/UsedRscList.ot")
    path = os.environ.get(
        "USEDRSCLIST", sys.argv[1] if len(sys.argv) > 1 else default,
    )
    print(f"Reading {path}...")
    with open(path, 'r', encoding='utf-8') as f:
        lines = [line.strip() for line in f if line.strip()]
    if lines and lines[0].isdigit():
        lines = lines[1:]
    mapping = {obf: decrypt_string(obf) for obf in lines}
    print(f"Decrypted {len(mapping)} asset paths.")

    ASSET_MAP_JSON.parent.mkdir(parents=True, exist_ok=True)
    with open(ASSET_MAP_JSON, 'w', encoding='utf-8') as jf:
        json.dump(mapping, jf, indent=2, ensure_ascii=False)
    print(f"Saved {ASSET_MAP_JSON}")

    with open(ASSET_MAP_CSV, 'w', newline='', encoding='utf-8') as cf:
        writer = csv.writer(cf)
        writer.writerow(["Obfuscated Path", "Decrypted Path"])
        for obf, plain in mapping.items():
            writer.writerow([obf, plain])
    print(f"Saved {ASSET_MAP_CSV}")

    print("\nSample entries:")
    for obf in list(mapping.keys())[:10]:
        print(f"  {obf}\n  -> {mapping[obf]}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
