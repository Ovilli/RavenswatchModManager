"""A mod item's own icon must be preloaded by the versiondef cache.

Of the 599 shipped resource caches, only ``LiveOps5.versiondef.UsedRscCache.ot``
lists item icons (all 94 ``Objects\\UI_Object_*`` textures), so an icon the mod
adds under its own name has no other preloader.
"""

from __future__ import annotations

from rsmm.engine import cipher
from rsmm.engine import versiondef as V
from rsmm.engine.paths import BACKUP_SUFFIX, COOKING_REL

ICON = "Ui/Objects/UI_Object_Zz_Test_Item.png.Texture.dxt"
ENTITY = ("EntitySettings/Objects/Magical_Objects/Common/"
          "Zz_Test_Item.entity.ot.EntitySettingsResource.gen")
PRISTINE = (b"1\nUi|Objects\\UI_Object_GreenArmor.png|oCTexture\n"
            b"EntitySettings|Objects\\Magical_Objects\\Common\\Armor_Per_Object"
            b".entity.ot|oCEntitySettingsResource\n")


def test_item_icon_maps_to_its_cache_ref():
    assert V._mo_icon_cache_ref(ICON) == "Objects\\UI_Object_Zz_Test_Item.png"
    assert V._mo_icon_cache_ref(ICON.replace("/", "\\")) == \
        "Objects\\UI_Object_Zz_Test_Item.png"
    # Other UI families have their own preloaders (herodef, tile caches).
    assert V._mo_icon_cache_ref("Ui/MiniMap/Icons/X.png.Texture.dxt") is None
    assert V._mo_icon_cache_ref("Ui/Objects/Sub/X.png.Texture.dxt") is None
    assert V._mo_icon_cache_ref(ENTITY) is None


def _game(tmp_path):
    cooking = tmp_path / COOKING_REL
    cooking.mkdir(parents=True)
    cache = cooking / cipher.encode(V.VERSIONDEF_CACHE_LEAF)
    assert cipher.decode(cache.name) == V.VERSIONDEF_CACHE_LEAF
    cache.write_bytes(PRISTINE)
    return cache


def test_sync_lists_the_new_icon_and_drops_it_again(tmp_path):
    cache = _game(tmp_path)
    V.sync_versiondef(tmp_path, {"a": ENTITY, "b": ICON}, dry_run=False)
    body = cache.read_bytes().decode("latin1").splitlines()
    assert "Ui|Objects\\UI_Object_Zz_Test_Item.png|oCTexture" in body
    assert body[:3] == PRISTINE.decode("latin1").splitlines()
    assert (cache.parent / (cache.name + BACKUP_SUFFIX)).is_file()

    once = cache.read_bytes()
    V.sync_versiondef(tmp_path, {"a": ENTITY, "b": ICON}, dry_run=False)
    assert cache.read_bytes() == once                          # idempotent

    V.sync_versiondef(tmp_path, {}, dry_run=False)             # mod disabled
    assert cache.read_bytes() == PRISTINE


def test_a_shipped_icon_repoint_adds_no_duplicate(tmp_path):
    cache = _game(tmp_path)
    V.sync_versiondef(tmp_path, {"a": ENTITY,
                                 "b": "Ui/Objects/UI_Object_GreenArmor.png.Texture.dxt"},
                      dry_run=False)
    body = cache.read_bytes().decode("latin1").splitlines()
    assert body.count("Ui|Objects\\UI_Object_GreenArmor.png|oCTexture") == 1
