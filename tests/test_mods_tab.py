"""Unit tests for the RSMM page-button builder (engine/mods_tab.py)."""

from __future__ import annotations

import struct
from pathlib import Path

import pytest

from rsmm.engine import mods_tab

_COOKING_CANDIDATES = [
    Path.home() / ".var/app/com.valvesoftware.Steam/.local/share/Steam"
    "/steamapps/common/Ravenswatch/DarkTalesResources/_Cooking",
    Path.home() / ".local/share/Steam/steamapps/common/Ravenswatch"
    "/DarkTalesResources/_Cooking",
]


def test_button_constants_consistent():
    # The Lua template binds the desc names — the BUTTONS table must ship
    # exactly those, and x positions must stay inside the page.
    names = {desc for _, desc, _ in mods_tab.BUTTONS}
    assert names == {mods_tab.BUTTON_NEXT, mods_tab.BUTTON_PREV,
                     mods_tab.BUTTON_TOGGLE}
    for win, desc, x in mods_tab.BUTTONS:
        assert desc.startswith("RSMM_")
        assert win.startswith("RSMM ")
        assert 0.0 < x < 1.0


def test_build_tab_assets_missing_map_entry():
    with pytest.raises(mods_tab.ModsTabError, match="asset map is missing"):
        mods_tab.build_tab_assets(Path("/nonexistent"), {})


def test_replace_blob_strings_and_remint():
    from rsmm.engine import cooked
    from rsmm.engine import entity_append as EA
    blob = (b"\x05\x00\x00\x00" + cooked.MARK_BEGIN + b"\x00" * 4 +
            cooked.MARK_END + bytes(range(16)) +
            b"\x04\x00\x00\x00Tuto" + b"\x00" * 8)
    out = EA.replace_blob_strings(blob, {"Tuto": "RSMM_X"})
    assert b"\x06\x00\x00\x00RSMM_X" in out and b"Tuto" not in out
    with pytest.raises(EA.EntityAppendError, match="not present"):
        EA.replace_blob_strings(blob, {"Nope": "x"})
    reminted = EA.remint_guid(blob)
    assert reminted[:0x10] == blob[:0x10]
    assert reminted[0x10:0x20] != blob[0x10:0x20]  # GUID after inner END
    assert reminted[0x20:] == blob[0x20:]


def test_build_tab_assets_against_install():
    root = next((c for c in _COOKING_CANDIDATES if c.is_dir()), None)
    if root is None:
        pytest.skip("no Ravenswatch install found")
    from rsmm.cli.apply_mods import load_asset_map
    from rsmm.engine import cooked
    from rsmm.engine import entity_append as EA
    assets = mods_tab.build_tab_assets(root, load_asset_map())

    frame_dec = mods_tab.FRAME_PAGE_DECODED.replace("\\", "/")
    assert set(assets) == {frame_dec}
    cf = cooked.parse(assets[frame_dec])
    n = EA.validate_layout(cf)          # directory still consistent

    added = [cf.sections[i].payload
             for i in range(n - 2 * len(mods_tab.BUTTONS) + 1, n + 1)]
    wins, descs = added[0::2], added[1::2]
    for (win_name, desc_name, x), win, desc in zip(mods_tab.BUTTONS,
                                                   wins, descs,
                                                   strict=True):
        assert win_name.encode() in win
        assert desc_name.encode() in win      # window links desc by name
        assert desc_name.encode() in desc
        assert struct.pack("<f", x) in desc   # repositioned
        assert b"Next Button" not in win and b"Next_Button" not in win
        assert b"Next_Button" not in desc
    # window GUIDs reminted -> all distinct
    guids = {w[w.find(cooked.MARK_END) + 4:][:16] for w in wins}
    assert len(guids) == len(wins)
    # donor pair untouched
    win_cls = next(i for i, c in enumerate(cf.classes)
                   if c.name == "oCEntityCpntWindowUiSettings")
    EA.find_component(cf, b"Next Button", win_cls)  # still unique


def test_build_bookmark_assets_against_install():
    root = next((c for c in _COOKING_CANDIDATES if c.is_dir()), None)
    if root is None:
        pytest.skip("no Ravenswatch install found")
    from rsmm.cli.apply_mods import load_asset_map
    from rsmm.engine import cooked
    from rsmm.engine import entity_append as EA
    assets = mods_tab.build_bookmark_assets(root, load_asset_map())

    scene = assets[mods_tab.BOOK_SCENE_DECODED.replace("\\", "/")]
    cf = cooked.parse(scene)
    n = EA.validate_layout(cf)          # directory still consistent
    node = cf.sections[n - 1].payload
    spawner = cf.sections[n].payload
    assert b"RSMM Tab 3d Node" in node
    assert b"RSMM Tab Spawner" in spawner
    assert b"Book_Menu\\RSMM_Tab_Mesh_Controller.entity.ot" in spawner
    assert b"Tuto" not in node and b"Tuto" not in spawner
    # class indexes match the directory tail
    dir_pl = cf.sections[0].payload
    tail = struct.unpack_from("<2I", dir_pl, 4 + 4 * (n - 2))
    assert tail == (struct.unpack_from("<I", node, 0)[0],
                    struct.unpack_from("<I", spawner, 0)[0])

    bookmark = assets[mods_tab.RSMM_TAB_DECODED.replace("\\", "/")]
    assert b"M_Book_Input_Tab" in bookmark
    assert b"M_Book_Compendium_Tab" not in bookmark
