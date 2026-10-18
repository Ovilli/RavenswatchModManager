"""The book's item grids widen when mods add items, and go back when they leave."""

from __future__ import annotations

import pytest

from rsmm.engine import compendium_layout as L
from rsmm.engine import corpus
from rsmm.engine import versiondef as VD


@pytest.mark.parametrize("n, cols0, n0, want", [
    (10, 10, 10, 10),   # vanilla one-row tier
    (11, 10, 10, 11),   # the 11th Common item: one row of 11, not a 2nd row
    (20, 10, 10, 20),
    (21, 10, 10, 20),   # two rows of half-height cells fit one vanilla row
    (15, 10, 14, 10),   # Legendary keeps its two rows at 10
    (21, 10, 14, 11),
    (5, 10, 10, 10),    # never fewer columns than vanilla
    (3, 0, 0, 0),       # the frameless slot stays 0
])
def test_columns_fit_the_vanilla_height(n, cols0, n0, want):
    assert L.fit_columns(n, cols0, n0) == want


def _page() -> bytes:
    data = corpus.read(L.PAGE_DECODED)
    if data is None:
        pytest.skip("shipped page not available (no mirror, no install)")
    return data


def test_the_shipped_page_has_ten_columns_per_tier():
    assert L.read_columns(_page()) == [10, 10, 10, 10, 10, 0]


def test_setting_columns_touches_only_those_bytes():
    page = _page()
    out = L.set_columns(page, [11, 10, 10, 10, 20, 0])
    assert len(out) == len(page)
    assert L.read_columns(out) == [11, 10, 10, 10, 20, 0]
    assert sum(a != b for a, b in zip(page, out, strict=True)) == 2
    assert L.set_columns(page, L.read_columns(page)) == page


def test_sync_widens_then_restores(tmp_path, monkeypatch):
    page = _page()
    vd = corpus.read("Definitions/Versions/" + VD.VERSIONDEF_GEN_LEAF)
    if vd is None:
        pytest.skip("shipped versiondef not available")
    gen, page_f = tmp_path / "vd.gen", tmp_path / "page.gen"
    gen.write_bytes(vd)
    page_f.write_bytes(page)
    monkeypatch.setattr(VD, "_locate_cooked_by_leaf", lambda _g, _leaf: gen)
    bak = page_f.with_name(page_f.name + ".rsmm.bak")

    assert L.sync_compendium_columns(tmp_path, False, page_f) == 0   # vanilla pool
    assert not bak.exists()

    # A mod adds one Common item: sync_versiondef backs the manifest up first.
    gen.with_name(gen.name + ".rsmm.bak").write_bytes(vd)
    gen.write_bytes(VD._patch_versiondef_gen(
        vd, ["Objects\\Magical_Objects\\Common\\Mod_Item.entity.ot"]))
    assert L.sync_compendium_columns(tmp_path, False, page_f) == 1
    assert L.read_columns(page_f.read_bytes())[0] == 11
    assert bak.read_bytes() == page
    assert L.sync_compendium_columns(tmp_path, False, page_f) == 0   # idempotent

    # The mod is gone: the manifest is vanilla again, so is the page.
    gen.write_bytes(vd)
    gen.with_name(gen.name + ".rsmm.bak").unlink()
    assert L.sync_compendium_columns(tmp_path, False, page_f) == 1
    assert page_f.read_bytes() == page and not bak.exists()


def test_a_mod_that_owns_the_page_is_left_alone(tmp_path, monkeypatch):
    page_f = tmp_path / "page.gen"
    page_f.write_bytes(b"theirs")
    monkeypatch.setattr(VD, "_locate_cooked_by_leaf", lambda _g, _leaf: page_f)
    assert L.sync_compendium_columns(tmp_path, False, page_f, page_owner="their-mod") == 0
    assert page_f.read_bytes() == b"theirs"
