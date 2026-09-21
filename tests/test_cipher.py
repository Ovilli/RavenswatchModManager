"""Cipher contract tests.

The apply pipeline relies on cipher.decode being correct for every
asset_map row — if even one character skews, the mod silently
resolves to the wrong cooked file. We therefore decode-roundtrip
every committed row.

Each case of the cipher is a bijection, so cipher.encode is exact on
every non-collapsed path: the only character the encoder cannot
reproduce is '\\' (directory-collapse to '!', handled by the caller).
We pin known pairs and require every non-collapsed asset_map row to
encode back to its real game name, so an inverse-table regression
cannot silently produce `_Cooking` names the engine will not load.
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


def test_cipher_tables_are_bijections():
    from rsmm.engine import cipher

    for table in (cipher.LOWER_DECODE, cipher.UPPER_DECODE):
        assert len(table) == 26
        assert len(set(table.values())) == 26, "two encoded letters decode alike"
    assert cipher.LOWER_ENCODE == {v: k for k, v in cipher.LOWER_DECODE.items()}
    assert cipher.UPPER_ENCODE == {v: k for k, v in cipher.UPPER_DECODE.items()}


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
    ("Map_Avalon_Common~GAM.xls", "Hgj_Wkglrz_Srxxrz~KWH.plv"),
    # The three letters that once decoded wrong (e->v, Y->Y, Z->I gave
    # "Ibox", "Yone" and "FI" for these). Real asset_map pairs.
    ("Platform\\UI_Social_Icons_Xbox.png", "Tlgihrux\\JX_Frbdgl_Xbrzv_Zarp.jzy"),
    ("BabaYaga_Cauldron_Damaged_FX.fbx", "BgagCgyg_Sgwlturz_Ngxgyqt_VZ.hap"),
    ("Blizzard", "Bldeegut"),
    ("Zone", "Yrzq"),
]


def test_cipher_encode_every_non_collapsed_row():
    """Encoder must reproduce the real game name on every asset_map path
    that is not directory-collapsed ('!' is the caller's job)."""
    from rsmm.engine import cipher

    rows = _read_rows()
    if not rows:
        return  # asset_map.csv not present in this checkout
    fails: list[str] = []
    total = 0
    for enc, dec in rows:
        if len(enc) != len(dec) or "!" in enc:
            continue  # '!' = directory-collapse, owned by the caller
        total += 1
        if cipher.encode(dec) != enc:
            fails.append(f"encode({dec!r}) -> {cipher.encode(dec)!r}, expected {enc!r}")
    assert total > 1000, f"too few non-collapsed rows to trust ({total})"
    assert not fails, f"{len(fails)} of {total} rows. First few: {fails[:5]}"


def test_cipher_encode_pinned_cases():
    from rsmm.engine import cipher

    for dec, enc in ENCODE_PINS:
        assert cipher.encode(dec) == enc, (
            f"encode({dec!r}) -> {cipher.encode(dec)!r}, expected {enc!r}"
        )
        assert cipher.decode(enc) == dec, (
            f"decode({enc!r}) -> {cipher.decode(enc)!r}, expected {dec!r}"
        )
