"""The pause menu's Mods button (rsmm.engine.escape_menu)."""

from __future__ import annotations

import json
import struct

import pytest

from rsmm.engine import corpus
from rsmm.engine import escape_menu as M
from rsmm.engine.entity_graph_edit import EntityFile
from rsmm.engine.paths import BACKUP_SUFFIX


@pytest.fixture()
def menu():
    data = corpus.read(M.MENU_DECODED)
    if data is None:
        pytest.skip("Escape_Menu_Model not available")
    return data


def _labels(gen):
    _c, _n, items = M._items(EntityFile(gen, "x"))
    return [f.text.split("text ")[1].split("'")[1] for f in items]


def test_the_mods_button_sits_right_after_settings(menu):
    out = M.add_mods_button(menu)
    assert _labels(out) == ["Continue", "Settings", "Mods", "Bug report", "Abandon",
                            "Quit to main menu", "Quit to desktop"]
    assert out.count(struct.pack("<I", M.MODS_ACTION)) == 1
    assert M.add_mods_button(out) == out            # applying twice adds one button


def test_the_button_needs_the_loader_and_follows_its_off_switch(menu, tmp_path):
    page = tmp_path / "menu.gen"
    page.write_bytes(menu)
    flags = tmp_path / "rsmm_loader_flags.json"
    assert M.sync_escape_menu(tmp_path, False, page) == 0      # no loader: no button
    (tmp_path / "winhttp.dll").write_bytes(b"MZ..." + M.LOADER_MARKER)
    assert M.sync_escape_menu(tmp_path, False, page) == 1
    assert M.has_mods_button(page.read_bytes())
    assert page.with_name(page.name + BACKUP_SUFFIX).read_bytes() == menu
    assert M.sync_escape_menu(tmp_path, False, page) == 0
    flags.write_text(json.dumps([M.FLAG]))
    assert M.sync_escape_menu(tmp_path, False, page) == 1
    assert page.read_bytes() == menu
    assert not page.with_name(page.name + BACKUP_SUFFIX).exists()
