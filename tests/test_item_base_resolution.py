"""An item `base` resolves under both spellings the docs and mods use.

`Common/Armor_Per_Object` (rarity-qualified, the form `guides/examples.mdx` and
mods/iron-crab-hide ship) used to miss in both resolvers: lint reported "not a
known vanilla item" and the cooker quietly emitted a legacy manifest instead of
a real cooked clone. A wrong rarity prefix must still miss, so a typo surfaces
rather than resolving to the wrong file.
"""

import pytest

from rsmm.cli.cmd_items import _find_item
from rsmm.sdk.kinds.items import _find_base

_ID = "Armor_Per_Object"


def _require_corpus():
    if _find_item(_ID) is None:
        pytest.skip("vanilla Armor_Per_Object corpus file not present")


@pytest.mark.parametrize("spelling", [_ID, f"Common/{_ID}", f"Common\\{_ID}"])
def test_find_item_accepts_both_spellings(spelling):
    _require_corpus()
    found = _find_item(spelling)
    assert found is not None
    assert (found[0], found[1]) == (_ID, "Common")


@pytest.mark.parametrize("spelling", [_ID, f"Common/{_ID}", f"Common\\{_ID}"])
def test_find_base_cooks_from_both_spellings(spelling):
    _require_corpus()
    found = _find_base(spelling)
    assert found is not None
    cooked, rarity = found
    assert rarity == "Common"
    assert cooked == _find_base(_ID)[0]


@pytest.mark.parametrize("spelling", [f"Rare/{_ID}", f"Legendary/{_ID}"])
def test_wrong_rarity_prefix_does_not_resolve(spelling):
    _require_corpus()
    assert _find_item(spelling) is None
    assert _find_base(spelling) is None
