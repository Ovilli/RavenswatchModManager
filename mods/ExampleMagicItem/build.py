"""Example mod: edit one magical object and clone another.

Run with: python3 mods/ExampleMagicItem/build.py

Re-emits this mod's `manifest.toml` from the SDK. Then `./rsmm apply`
installs it the usual way (auto-merges with other mods' [[patch]]
blocks).
"""

from rsmm import sdk


with sdk.Mod(
    "ExampleMagicItem",
    name="Example: Magic Item Edits",
    author="rsmm",
    version="1.0.0",
    description="Rename a vanilla magic item and clone a new one.",
    load_order=50,
) as m:
    # --- Edit an existing item ----------------------------------------
    #
    # Replace name/description/super-effect text for the Common-rarity
    # Armor_Per_Object. Every language can be patched at once by
    # passing lang="ALL".
    m.magic_item(
        "Armor_Per_Object",
        name="Iron Hide",
        description="Gain armor per equipped object.",
        super_effect="Bonus armor per rare object.",
    )

    # --- Clone an item under a new id ---------------------------------
    #
    # `new_id` MUST be the same byte length as `from_id` (16 chars
    # here). The clone copies the donor's cooked entity bytes, renames
    # internal references in-place, and ships fresh text-bank entries
    # for the new id under the chosen language.
    #
    # Caveat: numeric values inside the donor entity body (armor
    # amount, modifier scalars) are NOT yet patchable — the clone is
    # mechanically identical to the donor until the oCEntityCpntValue
    # schema RE catches up (see docs/ROADMAP.md).
    m.magic_item_clone(
        "Iron_Crabs_Yikes",
        from_id="Armor_Per_Object",
        name="Iron Crab Hide",
        description="A second armor-per-object item, just for fun.",
        super_effect="Bonus armor per rare object.",
    )
