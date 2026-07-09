"""In-game mod-menu page generator (`engine.mod_menu` + `rsmm menu`)."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from rsmm.engine import entity_strings as ES
from rsmm.engine import mod_menu

_COOKING_CANDIDATES = [
    Path(os.path.expanduser(
        "~/.var/app/com.valvesoftware.Steam/.local/share/Steam/steamapps/"
        "common/Ravenswatch/DarkTalesResources/_Cooking"
    )),
    Path(os.path.expanduser("~/.steam/steam/steamapps/common/Ravenswatch/"
                            "DarkTalesResources/_Cooking")),
]

_MODS = [
    {"id": "b_mod", "name": "Bravo", "version": "1.1", "enabled": True},
    {"id": "a_mod", "name": "Alpha", "version": "0.2", "enabled": False},
]


def test_menu_texts_lists_mods_sorted_with_status():
    t = mod_menu.menu_texts(_MODS)
    assert t["RSMM_Menu_Title"] == "RSMM Mods"
    assert "2 mod(s) installed, 1 enabled" in t["RSMM_Menu_Body"]
    rows = "\n".join(t[k] for k in ("RSMM_Menu_Row_1", "RSMM_Menu_Row_2",
                                    "RSMM_Menu_Row_3"))
    assert rows.index("Alpha 0.2  [disabled]") < rows.index("Bravo 1.1")


def test_menu_texts_empty():
    t = mod_menu.menu_texts([])
    assert "(no mods installed)" in t["RSMM_Menu_Row_1"]


def test_build_menu_assets_against_install():
    root = next((c for c in _COOKING_CANDIDATES if c.is_dir()), None)
    if root is None:
        pytest.skip("no Ravenswatch install found")
    from rsmm.cli.apply_mods import load_asset_map
    assets = mod_menu.build_menu_assets(root, load_asset_map(), _MODS)

    page_dec = mod_menu.PAGE_DECODED.replace("\\", "/")
    assert page_dec in assets
    strs = {s for _, _, s in ES.list_strings(assets[page_dec])}
    assert set(mod_menu.SLOT_KEYS.values()) <= strs
    assert not any(s.startswith("Quick_Guide_") for s in strs)

    bank_dec = mod_menu.BANK_DECODED.replace("\\", "/")
    assert bank_dec in assets                      # keys file
    assert any(k.startswith(f"{bank_dec}.Lang") for k in assets)  # siblings
    assert b"RSMM_Menu_Row_3" in assets[bank_dec]


def test_build_menu_assets_missing_map_entry():
    with pytest.raises(mod_menu.ModMenuError, match="asset map is missing"):
        mod_menu.build_menu_assets(Path("/nonexistent"), {}, [])


def test_init_lua_shape():
    lua = mod_menu.init_lua()
    # The interactive layer must go through the sanctioned R.* surface only —
    # no raw addresses, no peek/poke (mods-no-raw-addresses rule).
    assert 'require "rsmm"' in lua
    assert "R.mods.list()" in lua
    assert "R.mods.request(" in lua
    assert 'R.on("ui:press"' in lua
    assert 'R.on("gameplay:BOOK_MENU_OPEN"' in lua
    assert "0x14" not in lua
    for banned in ("peek", "poke", "call_raw", "read_u"):
        assert banned not in lua
    # Excludes itself from the toggle list.
    assert 'MENU_MOD_ID = "RSMMMenu"' in lua
    # MODS-tab button labels are injected from mods_tab (no drift) and no
    # placeholder tokens survive rendering.
    from rsmm.engine import mods_tab
    assert "@BTN_" not in lua
    for name in (mods_tab.BUTTON_NEXT, mods_tab.BUTTON_PREV,
                 mods_tab.BUTTON_TOGGLE):
        assert f'"{name}"' in lua
