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

from .cipher import decode as decrypt_char
from .paths import ASSET_MAP_CSV, ASSET_MAP_JSON, DEFAULT_GAME_DIR


def decrypt_string(s: str) -> str:
    return ''.join(decrypt_char(ch) for ch in s)


def main() -> int:
    default = str(DEFAULT_GAME_DIR / "DarkTalesResources" / "UsedRscList.ot")
    path = os.environ.get(
        "USEDRSCLIST", sys.argv[1] if len(sys.argv) > 1 else default,
    )
    print(f"Reading {path}...")
    with open(path, encoding='utf-8') as f:
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
