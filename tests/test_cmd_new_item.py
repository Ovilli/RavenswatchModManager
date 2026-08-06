"""`rsmm new --kind item` scaffolds a manifest that parses and lints clean.

The item block is mined from the chosen base rather than templated, so the
regressions this guards are: a manifest that no longer parses (cooked icon
refs are Windows paths, and `\\U` is a unicode escape in a TOML basic string),
and seeded `value_patches` whose defaults the applier can't re-find.
"""

import importlib
import tomllib

import pytest

from rsmm.engine import magic_item_cook as cook


@pytest.fixture
def scaffold(tmp_path, monkeypatch):
    """Run `rsmm new` against a throwaway mods dir, return the parsed manifest."""
    monkeypatch.setenv("RSMM_MODS_DIR", str(tmp_path))
    import rsmm.engine.paths as paths

    importlib.reload(paths)
    cmd_new = importlib.reload(importlib.import_module("rsmm.cli.cmd_new"))
    # Never prompt: a test has no terminal, and the picker would block.
    monkeypatch.setattr(cmd_new, "_interactive", lambda: False)

    def run(*argv: str) -> dict:
        assert cmd_new.main(list(argv)) == 0
        text = (tmp_path / argv[0] / "manifest.toml").read_text(encoding="utf-8")
        return tomllib.loads(text)

    return run


def _base_available(base: str) -> bool:
    from rsmm.cli import cmd_items

    return cmd_items._find_item(base) is not None


def test_item_scaffold_parses_and_mines_the_base(scaffold):
    if not _base_available("Armor_Per_Object"):
        pytest.skip("vanilla item corpus not present")
    doc = scaffold("demo", "--kind", "item", "--base", "Common/Armor_Per_Object")
    block = doc["content"][0]
    assert block["kind"] == "item"
    assert block["base"] == "Common/Armor_Per_Object"
    assert block["rarity"] == "Common"
    # Mined from the base, not templated — and the backslash survived quoting.
    assert block["icon"].endswith(".png")
    assert "\\" in block["icon"]


def test_seeded_value_patches_round_trip(scaffold):
    """Every seeded patch must satisfy the applier, or the scaffold fails lint."""
    if not _base_available("Armor_Per_Object"):
        pytest.skip("vanilla item corpus not present")
    from rsmm.cli import cmd_items

    doc = scaffold("demo", "--kind", "item", "--base", "Armor_Per_Object")
    found = cmd_items._find_item("Armor_Per_Object")
    assert found is not None
    data = found[2].read_bytes()
    patches = doc["content"][0].get("value_patches", [])
    assert patches, "expected at least one editable field on this base"
    for label, old, _new in patches:
        # Raises if the label or the expected old value isn't where we said.
        cook.set_value_after_label(data, label, old, old)


def test_metadata_flags_land_in_the_manifest(scaffold):
    doc = scaffold(
        "demo", "--kind", "item", "--base", "Armor_Per_Object",
        "--name", "Iron Carapace", "--desc", "Armor per rare object.",
        "--rarity", "Rare", "--icon", "GreenArmor",
    )
    assert doc["mod"]["name"] == "Iron Carapace"
    block = doc["content"][0]
    assert block["name"] == "Iron Carapace"
    assert block["description"] == "Armor per rare object."
    assert block["rarity"] == "Rare"
    assert block["icon"] == "GreenArmor"


def test_unknown_base_still_scaffolds_a_parseable_placeholder(scaffold):
    doc = scaffold("demo", "--kind", "item", "--base", "No_Such_Item")
    assert doc["content"][0]["base"] == "No_Such_Item"
    # Left unseeded: we cannot know the labels of an item we can't read.
    assert "value_patches" not in doc["content"][0]


def test_non_item_kinds_keep_their_template(scaffold):
    doc = scaffold("demo", "--kind", "enemy", "--base", "Gnoll_Shielded")
    assert doc["content"][0]["base"] == "Gnoll_Shielded"
    # Non-confirmed kinds ship opted-in and disabled.
    assert doc["mod"]["experimental"] is True
    assert doc["mod"]["enabled"] is False


def test_apostrophe_in_text_stays_parseable(scaffold):
    """A literal TOML string can't hold a quote — the emitter must switch forms."""
    doc = scaffold("demo", "--kind", "item", "--base", "Armor_Per_Object",
                   "--name", "Crab's Hide", "--desc", 'The "best" armor.')
    assert doc["content"][0]["name"] == "Crab's Hide"
    assert doc["content"][0]["description"] == 'The "best" armor.'
