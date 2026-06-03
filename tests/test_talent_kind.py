"""The `[[content]] kind="talent"` builder patches a hero entity value and
writes it as a plain asset override into the mod's assets/ tree.

Runs against the real vanilla Hero_Juliet entity (skipped if the corpus is
absent).
"""

from pathlib import Path

import pytest

from rsmm.engine import talent_values as TV
from rsmm.sdk.content import ContentError, ContentRegistry

_JULIET = (Path(__file__).resolve().parents[1] / "data" / "uncooked"
           / "EntitySettings" / "Heroes" / "Hero_Juliet"
           / "Hero_Juliet.entity.ot.EntitySettingsResource.gen")
_LABEL = "Skill Attack Burst Projectile Height Value"  # 1.75 in vanilla


def _require_juliet():
    if not _JULIET.is_file():
        pytest.skip("vanilla Hero_Juliet corpus file not present")


def test_talent_kind_emits_patched_override(tmp_path):
    _require_juliet()
    cr = ContentRegistry(mod_id="TestTalentMod")
    cr.register("talent", id="JulietTest", hero="Juliet",
                file="Hero_Juliet.entity",
                value_patches=[[_LABEL, 1.75, 3.0]])
    written = cr.emit(tmp_path)

    assert len(written) == 1
    out = written[0]
    assert out.name == "Hero_Juliet.entity.ot.EntitySettingsResource.gen"
    assert "EntitySettings/Heroes/Hero_Juliet" in out.as_posix()
    vals = {v.label: v.value for v in TV.list_talent_values(out.read_bytes())}
    assert vals[_LABEL] == 3.0


def test_talent_kind_unknown_label_errors(tmp_path):
    _require_juliet()
    cr = ContentRegistry(mod_id="TestTalentMod")
    cr.register("talent", id="JulietBad", hero="Juliet",
                value_patches=[["No Such Skill Value", 1.0, 2.0]])
    with pytest.raises(ContentError, match="not found"):
        cr.emit(tmp_path)


def test_talent_kind_unknown_hero_errors(tmp_path):
    cr = ContentRegistry(mod_id="TestTalentMod")
    cr.register("talent", id="GhostHero", hero="NotARealHero",
                value_patches=[["X Value", 1.0, 2.0]])
    with pytest.raises(ContentError, match="hero dir"):
        cr.emit(tmp_path)
