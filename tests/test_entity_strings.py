"""lstr surgery on cooked entity settings (`engine.entity_strings`).

Runs against the shipped Main_Book_Menu entity (skipped without a game
install) — the file whose path-string wiring the mod-menu work retargets.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from rsmm.engine import entity_strings as ES

_COOKING_CANDIDATES = [
    Path(os.path.expanduser(
        "~/.var/app/com.valvesoftware.Steam/.local/share/Steam/steamapps/"
        "common/Ravenswatch/DarkTalesResources/_Cooking"
    )),
    Path(os.path.expanduser("~/.steam/steam/steamapps/common/Ravenswatch/"
                            "DarkTalesResources/_Cooking")),
]
_TARGET = "Main_Book_Menu.entity.ot.EntitySettingsResource.gen"
_PAGE_REF = r"GameUis\All_Book_Pages\Tuto_Compendim_Page.entity.ot"


@pytest.fixture(scope="module")
def menu_bytes() -> bytes:
    root = next((c for c in _COOKING_CANDIDATES if c.is_dir()), None)
    if root is None:
        pytest.skip("no Ravenswatch install found")
    amap = Path("data/asset_map.json")
    if not amap.is_file():
        pytest.skip("no asset map")
    rev = {v: k for k, v in json.loads(amap.read_text()).items()}
    dec = next((d for d in rev if d.endswith(_TARGET)), None)
    if dec is None:
        pytest.skip("Main_Book_Menu not in asset map")
    p = root / Path(*rev[dec].replace("\\", "/").split("/"))
    if not p.is_file():
        pytest.skip("Main_Book_Menu cooked file missing")
    return p.read_bytes()


def test_scan_finds_page_wiring(menu_bytes):
    strs = {s for _, _, s in ES.list_strings(menu_bytes)}
    assert _PAGE_REF in strs
    assert r"GameUis\All_Book_Pages\Play_Book_Page.entity.ot" in strs


def test_identity_replace_is_byte_stable(menu_bytes):
    assert ES.replace_strings(menu_bytes, {_PAGE_REF: _PAGE_REF}) == menu_bytes


def test_variable_length_replace_roundtrips(menu_bytes):
    new = r"GameUis\All_Book_Pages\RSMM_Mods_Page_With_A_Longer_Name.entity.ot"
    out = ES.replace_strings(menu_bytes, {_PAGE_REF: new})
    strs = {s for _, _, s in ES.list_strings(out)}
    assert new in strs and _PAGE_REF not in strs
    assert ES.replace_strings(out, {new: _PAGE_REF}) == menu_bytes


def test_missing_source_raises(menu_bytes):
    with pytest.raises(ES.EntityStringError, match="not present"):
        ES.replace_strings(menu_bytes, {"No_Such_String_Here": "x"})


def test_non_ascii_replacement_rejected(menu_bytes):
    with pytest.raises(ES.EntityStringError, match="ASCII"):
        ES.replace_strings(menu_bytes, {_PAGE_REF: "Modsé"})
