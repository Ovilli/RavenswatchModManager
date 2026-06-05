"""Cipher contract tests.

The apply pipeline relies on cipher.decode being correct for every
asset_map row — if even one character skews, the mod silently
resolves to the wrong cooked file. We therefore decode-roundtrip
every committed row.

cipher.encode is ~98% exact on non-collapsed paths. Four decoded
characters are genuinely ambiguous: 'v' (-> 'k' 98.6% / 'e' 1.4%),
'I' (-> 'X' / 'Z' via the clean 'FI' digraph rule), 'Y' (-> 'C' 84% /
'Y' 16%, unresolvable) and '\\' (directory-collapse, handled by the
caller). We pin known pairs and enforce an accuracy floor against the
whole asset_map so the table can't silently regress (e.g. the old
'v' -> 'e' bug that produced unloadable `_Cooking` names).
"""

import csv
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
ASSET_MAP_CSV = REPO / "data" / "asset_map.csv"


def _read_rows():
    if not ASSET_MAP_CSV.is_file():
        return []
    rows = []
    with ASSET_MAP_CSV.open(encoding="utf-8") as f:
        rdr = csv.reader(f)
        next(rdr, None)  # header: Obfuscated Path, Decrypted Path
        for row in rdr:
            if len(row) >= 2 and row[0] and row[1]:
                rows.append((row[0], row[1]))
    return rows


def test_cipher_roundtrip_every_asset_map_row():
    from rsmm.engine import cipher

    rows = _read_rows()
    assert rows, f"asset_map.csv missing or empty at {ASSET_MAP_CSV}"

    decode_fails: list[str] = []
    for enc, dec in rows:
        if cipher.decode(enc) != dec:
            decode_fails.append(
                f"decode({enc!r}) -> {cipher.decode(enc)!r}, expected {dec!r}"
            )

    assert not decode_fails, (
        f"{len(decode_fails)} decode failures out of {len(rows)} rows. "
        f"First few: {decode_fails[:5]}"
    )


# Known-good (decoded, encoded) pairs — mirrors cipher._selftest plus
# a couple of extras spread across the asset tree. If a regression
# breaks the encoder for these, mods that author these specific paths
# will silently no-op at apply time.
ENCODE_PINS = [
    ("EntitySettings", "MzidisFqiidzyv"),
    ("Book_Menu", "Brrm_Hqzw"),
    ("Social", "Frbdgl"),
    (
        "Book_Social_Tab_Mesh_Controller.entity.ot.EntitySettingsResource.gen",
        "Brrm_Frbdgl_Qga_Hqvn_Srziurllqu.qzidis.ri.MzidisFqiidzyvLqvrwubq.yqz",
    ),
    # Regression: decoded 'v' must encode to 'k' (was wrongly 'e'), and
    # the 'FI' digraph must encode to 'VZ'. Both are real asset_map pairs.
    ("Map_Avalon_Common~GAM.xls", "Hgj_Wkglrz_Srxxrz~KWH.plv"),
    ("FI", "VZ"),
]


def test_cipher_encode_accuracy_floor():
    """Encoder must match the real game name on >=97% of non-collapsed
    asset_map paths. Guards against an inverse-table regression silently
    producing `_Cooking` names the engine can't load for new assets."""
    from rsmm.engine import cipher

    rows = _read_rows()
    if not rows:
        return  # asset_map.csv not present in this checkout
    ok = total = 0
    for enc, dec in rows:
        if len(enc) != len(dec) or "!" in enc:
            continue  # '!' = directory-collapse, owned by the caller
        total += 1
        ok += cipher.encode(dec) == enc
    assert total > 1000, f"too few non-collapsed rows to trust ({total})"
    acc = ok / total
    assert acc >= 0.97, f"encode accuracy {acc:.3%} below 97% floor ({ok}/{total})"


def test_cipher_encode_pinned_cases():
    from rsmm.engine import cipher

    for dec, enc in ENCODE_PINS:
        assert cipher.encode(dec) == enc, (
            f"encode({dec!r}) -> {cipher.encode(dec)!r}, expected {enc!r}"
        )
        assert cipher.decode(enc) == dec, (
            f"decode({enc!r}) -> {cipher.decode(enc)!r}, expected {dec!r}"
        )
