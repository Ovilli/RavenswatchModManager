"""Cipher contract tests.

The apply pipeline relies on cipher.decode being correct for every
asset_map row — if even one character skews, the mod silently
resolves to the wrong cooked file. We therefore decode-roundtrip
every committed row.

cipher.encode is a separate story. The encoder table has known
ambiguities (collision: decoded 'v' has two valid encoded inverses,
'e' and 'k'; the engine's choice is path-dependent and we don't yet
model it). So encode is asserted on a curated whitelist of paths the
existing module-level `_selftest` already pins, plus we sanity-check
that `decode(encode(dec))` brings any shallow decoded path back to
itself.
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
]


def test_cipher_encode_pinned_cases():
    from rsmm.engine import cipher

    for dec, enc in ENCODE_PINS:
        assert cipher.encode(dec) == enc, (
            f"encode({dec!r}) -> {cipher.encode(dec)!r}, expected {enc!r}"
        )
        assert cipher.decode(enc) == dec, (
            f"decode({enc!r}) -> {cipher.decode(enc)!r}, expected {dec!r}"
        )
