"""`rsmm values backport`: a snapshot of an older patch as a mod."""

from __future__ import annotations

import pytest

from rsmm.engine import values_backport as VB


def test_a_reference_is_the_path_the_data_spells():
    assert VB._ref_form("Definitions/Tiles/Storm_Island/x.tiledef.ot.DtTileDefinition.gen") \
        == "Tiles\\Storm_Island\\x.tiledef.ot"
    assert VB._ref_form("EntitySettings/Heroes/Hero_Red/Hero_Red.entity.ot"
                        ".EntitySettingsResource.gen") == "Heroes\\Hero_Red\\Hero_Red.entity.ot"


def test_a_rename_pairs_only_the_one_clearly_closest_file():
    d = "Definitions/Tiles/Storm_Island/"
    suf = ".tiledef.ot.DtTileDefinition.gen"
    old = [f"{d}40x40_Storm_Island_Thieves_Gold_Room_01{suf}",
           f"{d}Something_Else_Entirely{suf}"]
    new = [f"{d}40x40_SI_Thieves_Gold_Room_01{suf}",
           f"{d}40x40_SI_Thieves_Gold_Room_01.entity.ot.EntitySettingsResource.gen",
           f"Definitions/Tiles/Avalon/40x40_Storm_Island_Thieves_Gold_Room_01{suf}"]
    assert VB._renames(old, new) == {old[0]: new[0]}


def test_two_equally_close_candidates_are_not_a_rename():
    d, suf = "Definitions/Tiles/A/", ".tiledef.ot.DtTileDefinition.gen"
    assert VB._renames([f"{d}Room_01{suf}"], [f"{d}Room_02{suf}", f"{d}Room_03{suf}"]) == {}


def test_backport_of_a_real_snapshot(tmp_path):
    """Needs a snapshot of an older patch and the install it differs from."""
    from rsmm.engine import cooked
    from rsmm.engine import values_snapshot as VS
    from rsmm.engine import versiondef as V

    rows = [r for r in VS.listing() if r["name"] == "Version_1.05.01.01.27384"]
    if not rows:
        pytest.skip("no Update 5 snapshot on this machine")
    try:
        r = VB.build(rows[0]["name"], tmp_path / "bp", mod_id="bp")
    except VS.SnapshotError as e:
        pytest.skip(str(e))
    vd = (tmp_path / "bp/assets/Definitions/Versions" / V.VERSIONDEF_GEN_LEAF).read_bytes()
    co, _end, cnt = V._find_hero_vector(vd)
    heroes = [e[2] for e in V._mo_vector_entries(vd, co, cnt)]
    assert "Heroes\\Kintaro.herodef.ot" in heroes          # kept, not in Update 5
    assert not any(h.endswith("\\Piper.herodef.ot") for h in heroes)
    assert b"Hero_Red_Update6.entity.ot" not in vd         # the rework is off
    for p in (tmp_path / "bp/assets").rglob("*.gen"):
        raw = p.read_bytes()
        assert cooked.emit(cooked.parse(raw)) == raw, p
    assert not r.readded or all(not x.startswith("Definitions/Tiles/") for x in r.readded)


def test_pack_refuses_a_generated_backport(tmp_path, monkeypatch):
    """Its files are an OLDER patch's originals, which the vanilla-bytes check
    cannot see, so the marker is what keeps it off the mod site."""
    from rsmm.cli import cmd_pack

    mod = tmp_path / "bp"
    (mod / "assets").mkdir(parents=True)
    (mod / "manifest.toml").write_text('[mod]\nid = "bp"\nname = "x"\nversion = "1.0.0"\n')
    (mod / VB.MARKER).write_text("local only\n")
    monkeypatch.setattr(cmd_pack, "MODS_DIR", tmp_path)
    assert cmd_pack.main(["bp"]) == 1
