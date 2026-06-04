"""Magic-item registry scanner (engine.magic_items).

Distinct from test_magic_item_cook.py (which tests the cook/encode side) —
this covers the read-side scanner that discovers items from decoded dumps.
"""

import pytest

from rsmm.engine import magic_items


def test_strings_in_extracts_only_str_lines():
    txt = "\n".join([
        '  @00bb  str(len=21)  "Armor_Per_Object_Name"',
        'noise line, not a str',
        '@0  str(len=4)  "Foo"',
        '  @ff  int(4)  123',  # not a str() line -> ignored
    ])
    assert magic_items._strings_in(txt) == ["Armor_Per_Object_Name", "Foo"]


def _gen_txt(*strings: str) -> str:
    return "\n".join(f'@{i:04x}  str(len={len(s)})  "{s}"' for i, s in enumerate(strings))


def test_scan_one_extracts_keys_icon_and_debug(tmp_path):
    f = tmp_path / "Foo.entity.ot.EntitySettingsResource.gen.txt"
    f.write_text(_gen_txt(
        "Magical_Objects~GAM.xls", "Foo_Name",
        "Magical_Objects~GAM.xls", "Foo_Description",
        "Magical_Objects~GAM.xls", "Foo_SuperEffect_Desc",
        "Objects\\Icon_Object_Foo.png",
        "Debug Name", "Green_Foo",
    ), encoding="utf-8")

    item = magic_items._scan_one("Foo", "Epic", f)
    assert item.id == "Foo" and item.rarity == "Epic"
    assert item.name_key == "Foo_Name"
    assert item.desc_key == "Foo_Description"
    assert item.super_keys == ["Foo_SuperEffect_Desc"]
    assert item.icon_decoded_path == "Ui/Objects/Icon_Object_Foo.png.Texture.dxt"
    assert item.debug_name == "Green_Foo"
    assert item.entity_decoded_path == (
        "EntitySettings/Objects/Magical_Objects/Epic/"
        "Foo.entity.ot.EntitySettingsResource.gen"
    )


def test_scan_one_missing_optionals_are_none(tmp_path):
    f = tmp_path / "Bare.entity.ot.EntitySettingsResource.gen.txt"
    f.write_text(_gen_txt("unrelated", "strings", "only"), encoding="utf-8")
    item = magic_items._scan_one("Bare", "Common", f)
    assert item.name_key is None and item.desc_key is None
    assert item.super_keys == [] and item.icon_decoded_path is None
    assert item.debug_name is None


@pytest.fixture
def fake_registry(tmp_path, monkeypatch):
    """Build a 2-item fake _MAGIC_DIR and point the scanner at it."""
    root = tmp_path / "Magical_Objects"
    for rarity, item_id in [("Common", "Alpha"), ("Epic", "Beta")]:
        d = root / rarity
        d.mkdir(parents=True)
        (d / f"{item_id}.entity.ot.EntitySettingsResource.gen.txt").write_text(
            _gen_txt("Magical_Objects~GAM.xls", f"{item_id}_Name"), encoding="utf-8"
        )
    monkeypatch.setattr(magic_items, "_MAGIC_DIR", root)
    magic_items.registry.cache_clear()
    yield root
    magic_items.registry.cache_clear()


def test_registry_and_list_ids(fake_registry):
    assert magic_items.list_ids() == ["Alpha", "Beta"]
    assert magic_items.list_ids(rarity="epic") == ["Beta"]  # case-insensitive
    assert magic_items.list_ids(grep="alph") == ["Alpha"]


def test_get_is_case_insensitive_fallback(fake_registry):
    assert magic_items.get("Alpha").name_key == "Alpha_Name"
    assert magic_items.get("beta").id == "Beta"  # fallback path
    assert magic_items.get("nope") is None


def test_registry_empty_without_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(magic_items, "_MAGIC_DIR", tmp_path / "missing")
    magic_items.registry.cache_clear()
    assert magic_items.registry() == {}
    magic_items.registry.cache_clear()
