"""Field-level edits to plaintext `.ot` files, and the `kind="ot"` patch.

The alternative this replaces is a mod shipping a whole copy of
`ApplicationSettings.ot`: a redistributed game file that also reverts whatever
the next game patch changes in the parts the mod never cared about.
"""

from __future__ import annotations

import pytest

from rsmm.engine.ot_patch import OtPatchError, apply_edits, set_field

# Shaped like the real file: a descriptor block with a NESTED value block whose
# fields must never be mistaken for the descriptor's own.
SAMPLE = "\n".join([
    "//OPROJECT oCTextSaver",
    "SingleObject0=C30",
    "{",
    "m_oDefaultValue=C6",
    "{",
    "u|u16Type=0",
    "f|_GrabFloatValue()=0",
    "}",
    "u|m_uMaxStackSize=0",
    "s|m_sLabel=Merlin DMG Zone",
    "i|m_eStackMode=0",
    "i|m_eComputerType=3",
    "}",
    "SingleObject1=C30",
    "{",
    "m_oDefaultValue=C6",
    "{",
    "u|u16Type=2",
    "}",
    "u|m_uMaxStackSize=0",
    "s|m_sLabel=Fury",
    "i|m_eComputerType=0",
    "}",
    "",
])


def test_sets_only_the_named_field_of_the_named_block():
    out, edit = set_field(SAMPLE, selector="Merlin DMG Zone",
                          field="m_eComputerType", value=0)
    assert edit.old == "3" and edit.new == "0"
    assert "i|m_eComputerType=0" in out
    # Exactly one line differs, and the other block is untouched.
    diff = [(a, b) for a, b in zip(SAMPLE.split("\n"), out.split("\n"), strict=True) if a != b]
    assert diff == [("i|m_eComputerType=3", "i|m_eComputerType=0")]
    assert len(out) == len(SAMPLE)


def test_a_nested_blocks_fields_are_not_the_blocks_own():
    """`u16Type` lives in the nested value block, so the descriptor has no such
    field — and inventing one the engine ignores is the failure mode this
    refuses."""
    with pytest.raises(OtPatchError, match="no field"):
        set_field(SAMPLE, selector="Merlin DMG Zone", field="u16Type", value=1)


def test_unknown_selector_is_an_error_not_a_silent_noop():
    with pytest.raises(OtPatchError, match="no block"):
        set_field(SAMPLE, selector="Nope", field="m_eComputerType", value=0)


def test_missing_field_is_an_error():
    with pytest.raises(OtPatchError, match="no field"):
        set_field(SAMPLE, selector="Fury", field="m_eStackMode", value=1)


def test_ambiguous_selector_is_refused():
    doubled = SAMPLE.replace("s|m_sLabel=Fury", "s|m_sLabel=Merlin DMG Zone")
    with pytest.raises(OtPatchError, match="matches 2 blocks"):
        set_field(doubled, selector="Merlin DMG Zone",
                  field="m_eComputerType", value=0)


def test_selector_field_can_be_something_other_than_the_label():
    out, edit = set_field(SAMPLE, selector="0", selector_field="m_eStackMode",
                          field="m_eComputerType", value=5)
    assert edit.new == "5"
    assert "i|m_eComputerType=5" in out


def test_the_files_type_prefix_decides_how_a_value_is_written():
    # The float lives in the NESTED value block, so it is reached by selecting
    # that block (`u16Type`), not the descriptor that contains it.
    inner, edit = set_field(SAMPLE, selector="0", selector_field="u16Type",
                            field="_GrabFloatValue()", value=0.25)
    assert edit.new == "0.25"
    assert "f|_GrabFloatValue()=0.25" in inner
    # `%.9g`, which is what the shipped file uses: enough to round-trip a
    # float32, with no trailing zeros.
    whole, edit = set_field(SAMPLE, selector="0", selector_field="u16Type",
                            field="_GrabFloatValue()", value=1)
    assert edit.new == "1"


def test_a_string_into_an_int_field_is_refused():
    with pytest.raises(OtPatchError, match="needs an integer"):
        set_field(SAMPLE, selector="Merlin DMG Zone",
                  field="m_eComputerType", value="zero")


def test_apply_edits_composes_in_order():
    out, done = apply_edits(SAMPLE, [
        {"selector": "Merlin DMG Zone", "field": "m_eComputerType", "value": 4},
        {"selector": "Fury", "field": "m_eComputerType", "value": 2},
    ])
    assert [e.new for e in done] == ["4", "2"]
    assert out.count("i|m_eComputerType=4") == 1
    assert out.count("i|m_eComputerType=2") == 1


def _mod(mods, mid, *, order=100, patches=""):
    d = mods / mid
    d.mkdir(parents=True)
    d.joinpath("manifest.toml").write_text(
        f'[mod]\nid = "{mid}"\nenabled = true\nload_order = {order}\n{patches}',
        encoding="utf-8")
    return d


def _game(tmp_path):
    g = tmp_path / "game"
    (g / "DarkTalesResources").mkdir(parents=True)
    (g / "DarkTalesResources" / "ApplicationSettings.ot").write_text(
        SAMPLE, encoding="utf-8")
    (g / "DarkTalesResources" / "_Cooking").mkdir()
    return g


def test_merge_edits_the_games_own_file(tmp_path, monkeypatch):
    """End to end: a manifest with three strings in it produces the same bytes
    a hand-edited copy of the game file would have."""
    from rsmm.cli import merge

    mods = tmp_path / "mods"
    _mod(mods, "Test", patches='\n[[patch]]\nkind = "ot"\n'
         'selector = "Merlin DMG Zone"\nfield = "m_eComputerType"\nvalue = 0\n')
    monkeypatch.setattr("rsmm.cli.merge.MODS_DIR", mods)

    out, conflicts = merge.build_merged_mod(_game(tmp_path))

    assert conflicts == []
    produced = (out / "assets" / "_root" / "DarkTalesResources"
                / "ApplicationSettings.ot").read_text(encoding="utf-8")
    assert produced == SAMPLE.replace("i|m_eComputerType=3", "i|m_eComputerType=0")


def test_merge_prefers_the_pristine_backup_over_a_previous_result(
        tmp_path, monkeypatch):
    """Composing on top of an already-installed result would make the outcome
    depend on how many times apply has run."""
    from rsmm.cli import merge

    g = _game(tmp_path)
    live = g / "DarkTalesResources" / "ApplicationSettings.ot"
    live.with_name(live.name + ".rsmm.bak").write_text(SAMPLE, encoding="utf-8")
    live.write_text(SAMPLE.replace("i|m_eComputerType=3", "i|m_eComputerType=9"),
                    encoding="utf-8")

    mods = tmp_path / "mods"
    _mod(mods, "Test", patches='\n[[patch]]\nkind = "ot"\n'
         'selector = "Fury"\nfield = "m_eComputerType"\nvalue = 1\n')
    monkeypatch.setattr("rsmm.cli.merge.MODS_DIR", mods)

    out, _ = merge.build_merged_mod(g)
    produced = (out / "assets" / "_root" / "DarkTalesResources"
                / "ApplicationSettings.ot").read_text(encoding="utf-8")
    # Built from the BACKUP, so the 9 that a previous apply wrote is gone.
    assert "i|m_eComputerType=9" not in produced
    assert "i|m_eComputerType=3" in produced


def test_merge_reports_two_mods_fighting_over_one_field(tmp_path, monkeypatch):
    from rsmm.cli import merge

    mods = tmp_path / "mods"
    _mod(mods, "A", order=1, patches='\n[[patch]]\nkind = "ot"\n'
         'selector = "Fury"\nfield = "m_eComputerType"\nvalue = 1\n')
    _mod(mods, "B", order=2, patches='\n[[patch]]\nkind = "ot"\n'
         'selector = "Fury"\nfield = "m_eComputerType"\nvalue = 5\n')
    monkeypatch.setattr("rsmm.cli.merge.MODS_DIR", mods)

    out, conflicts = merge.build_merged_mod(_game(tmp_path))

    assert [c[0] for c in conflicts] == ["ot"]
    produced = (out / "assets" / "_root" / "DarkTalesResources"
                / "ApplicationSettings.ot").read_text(encoding="utf-8")
    assert "i|m_eComputerType=5" in produced      # later load_order wins


def test_a_bad_edit_refuses_the_whole_file(tmp_path, monkeypatch, capsys):
    """Half-applied edits are a configuration nobody wrote."""
    from rsmm.cli import merge

    mods = tmp_path / "mods"
    _mod(mods, "Test", patches='\n[[patch]]\nkind = "ot"\n'
         'selector = "Fury"\nfield = "m_eComputerType"\nvalue = 1\n'
         '\n[[patch]]\nkind = "ot"\n'
         'selector = "Ghost"\nfield = "m_eComputerType"\nvalue = 1\n')
    monkeypatch.setattr("rsmm.cli.merge.MODS_DIR", mods)

    out, _ = merge.build_merged_mod(_game(tmp_path))

    assert out is None
    assert "no block" in capsys.readouterr().err


def test_merge_refuses_a_traversing_file_path(tmp_path, monkeypatch, capsys):
    from rsmm.cli import merge

    mods = tmp_path / "mods"
    _mod(mods, "Test", patches='\n[[patch]]\nkind = "ot"\n'
         'file = "../../etc/passwd"\n'
         'selector = "Fury"\nfield = "m_eComputerType"\nvalue = 1\n')
    monkeypatch.setattr("rsmm.cli.merge.MODS_DIR", mods)

    out, _ = merge.build_merged_mod(_game(tmp_path))

    assert out is None
    assert "traversal" in capsys.readouterr().err
