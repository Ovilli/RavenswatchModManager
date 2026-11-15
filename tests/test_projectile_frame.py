"""A projectile written from data (engine/projectile_frame.py): built on the
shared hero projectile, it carries the same parts a shipped projectile does,
and nothing of any hero's projectile file."""

from __future__ import annotations

import re

import pytest

from rsmm.engine import corpus
from rsmm.engine import entity_fields as EF
from rsmm.engine import projectile_frame as PF
from rsmm.engine.entity_graph_edit import EntityFile

RED = ("EntitySettings/Heroes/Hero_Red/"
       "Hero_Red_Projectile_Spike.entity.ot.EntitySettingsResource.gen")


def _read(ref: str):
    return corpus.read(f"EntitySettings/{ref.replace(chr(92), '/')}.EntitySettingsResource.gen")


def _have() -> bool:
    try:
        return corpus.read(RED) is not None and _read(PF.MODEL) is not None
    except Exception:  # noqa: BLE001 — no corpus
        return False


needs_corpus = pytest.mark.skipif(not _have(), reason="no corpus")
_RED_MESH = "Characters\\Heroes\\RED\\Red_Dagger.fbx"
_RED_MAT = "Characters\\Heroes\\RED\\Textures\\M_Red_Dagger_Projectile.mat.ot"
_RED_TRAIL = "Settings\\Heroes\\Hero_Red_FX\\RED_Skill_Dash_Projectile_Trail_01.vfx.ot"
_RED_IMPACT = "Settings\\Heroes\\Hero_Red_FX\\RED_Impact_01.vfx.ot"


def _plain(o) -> bytes:
    """An object's bytes with its class indices (file-specific) blanked."""
    return re.sub(rb"\x11\x11\xbb\xaa....", b"\x11\x11\xbb\xaa", bytes(o), flags=re.S)[4:]


@needs_corpus
def test_written_from_data_it_is_reds_spike_part_for_part():
    """Given Red's mesh, material, lifetime and effects, the projectile written
    on the shared base has Red's spike's five parts field for field, its
    trail setup byte for byte; it is a new file (its own identity, no sounds
    or parts of Red's)."""
    me = EntityFile(PF.build(_read, stem="Hero_T_Spike", mesh=_RED_MESH, material=_RED_MAT,
                             lifetime=0.5, trail=_RED_TRAIL, impact=_RED_IMPACT), "Hero_T_Spike")
    red = EntityFile(corpus.read(RED), "Hero_Red_Projectile_Spike")
    assert sorted(c.name for c in me.graph().components) == [
        "Alive Fx Default", "Impact Fx Default", "Lifetime Duration", "Mesh",
        "Projectile Attack Selector"]
    for part in ("Mesh", "Projectile Attack Selector", "Lifetime Duration"):
        mine = {f.name: f.text for f in EF.fields(me.component(part))}
        theirs = {f.name: f.text for f in EF.fields(red.component(part))}
        assert mine == theirs, part
    assert _plain(me.objects[PF._fx_ids(me, "Alive Fx Default")[0]]) == \
        _plain(red.objects[PF._fx_ids(red, "Alive Fx Default")[0]])
    impact = bytes(me.objects[PF._fx_ids(me, "Impact Fx Default")[0]])
    assert _RED_IMPACT.encode() in impact
    raw = PF.build(_read, stem="Hero_T_Spike", mesh=_RED_MESH, material=_RED_MAT)
    assert b"Hero_Red_Projectile_Spike" not in raw and b"FMod" not in raw


@needs_corpus
def test_options_pierce_bare_and_base_impact():
    """`pierce = false` keeps the base's plain attack (stops at the first hit);
    no trail flies bare; no impact keeps the base's own burst."""
    me = EntityFile(PF.build(_read, stem="Hero_T_Bean", mesh="a.fbx", material="",
                             pierce=False), "Hero_T_Bean")
    sel = next(f.text for f in EF.fields(me.component("Projectile Attack Selector"))
               if f.name == "obj_2")
    assert "Projectile_Model\\Projectile Attack" in sel and "Piercing" not in sel
    assert PF._fx_ids(me, "Alive Fx Default") == []
    assert PF.BASE_IMPACT.encode() in bytes(me.objects[PF._fx_ids(me, "Impact Fx Default")[0]])
