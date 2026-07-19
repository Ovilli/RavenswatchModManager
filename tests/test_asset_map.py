"""Cached asset-map loader + decoded<->encoded inversion."""

import json

import pytest

from rsmm.engine import asset_map


@pytest.fixture(autouse=True)
def _clear_caches():
    # The loaders are lru_cache(maxsize=1); reset around every test so a
    # monkeypatched ASSET_MAP_JSON is actually re-read.
    asset_map.encoded_to_decoded.cache_clear()
    asset_map.decoded_to_encoded.cache_clear()
    yield
    asset_map.encoded_to_decoded.cache_clear()
    asset_map.decoded_to_encoded.cache_clear()


def _write_map(tmp_path, monkeypatch, mapping: dict[str, str]):
    p = tmp_path / "asset_map.json"
    p.write_text(json.dumps(mapping), encoding="utf-8")
    monkeypatch.setattr(asset_map, "ASSET_MAP_JSON", p)
    return p


def test_encoded_to_decoded_loads_and_caches(tmp_path, monkeypatch):
    p = _write_map(tmp_path, monkeypatch, {"ENC\\a.bin": "foo\\bar.bin"})
    assert asset_map.encoded_to_decoded() == {"ENC\\a.bin": "foo\\bar.bin"}
    # Second call is cached: deleting the file must not change the result.
    p.unlink()
    assert asset_map.encoded_to_decoded() == {"ENC\\a.bin": "foo\\bar.bin"}


def test_decoded_to_encoded_inverts_and_normalises_slashes(tmp_path, monkeypatch):
    _write_map(tmp_path, monkeypatch, {"ENC\\a.bin": "foo\\bar.bin"})
    # Decoded keys are normalised to forward slashes.
    assert asset_map.decoded_to_encoded() == {"foo/bar.bin": "ENC\\a.bin"}


def test_decoded_to_encoded_warns_on_collision(tmp_path, monkeypatch, caplog):
    # Two encoded paths decoding to the same forward-slash key: last wins + warn.
    _write_map(tmp_path, monkeypatch, {
        "ENC1": "same\\path",
        "ENC2": "same/path",
    })
    with caplog.at_level("WARNING"):
        out = asset_map.decoded_to_encoded()
    assert out == {"same/path": "ENC2"}  # last one survives
    assert any("duplicate decoded path" in r.message for r in caplog.records)


# --- FMOD sound banks ------------------------------------------------------
#
# Banks are the one asset family the engine loads by path instead of through
# `UsedRscList.ot`, so they are absent from asset_map and must resolve by
# ciphering the plaintext path directly.

def test_audio_banks_are_absent_from_the_asset_map():
    """The premise of resolve_audio_bank: a dec2enc lookup can never hit."""
    dec2enc = asset_map.decoded_to_encoded()
    assert not [d for d in dec2enc if d.endswith(".bank")]


def test_resolve_audio_bank_ciphers_the_plaintext_path():
    from rsmm.cli.apply_mods import resolve_audio_bank

    # Verified against the shipped tree: _Cooking/Wwtdr/Hwvdb.agzm exists.
    assert resolve_audio_bank("Audio/Music.bank") == "Wwtdr\\Hwvdb.agzm"
    assert resolve_audio_bank("Audio/Master.strings.bank") == "Wwtdr\\Hgviqu.viudzyv.agzm"
    # Backslash input is accepted too (manifests may use either separator).
    assert resolve_audio_bank("Audio\\Music.bank") == "Wwtdr\\Hwvdb.agzm"


def test_resolve_audio_bank_declines_non_banks():
    from rsmm.cli.apply_mods import resolve_audio_bank

    for decoded in (
        "Audio/DarkTales.bankset.FModEventProject.gen",  # in asset_map already
        "Characters/Character_Grey.mat.ot",
        "Audio/nested/dir/Music.bank",                   # banks are flat
        "Music.bank",                                    # not under Audio/
    ):
        assert resolve_audio_bank(decoded) is None, decoded


def test_resolve_special_routes_banks_without_an_asset_map():
    from rsmm.cli.apply_mods import resolve_audio_bank, resolve_special

    assert resolve_special("Audio/Maps.bank", {}) == resolve_audio_bank("Audio/Maps.bank")
