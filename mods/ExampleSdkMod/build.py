#!/usr/bin/env python3
"""
Example: author a mod in Python with the RSMM SDK.

Run from the repo root:

    python3 mods/ExampleSdkMod/build.py
    ./rsmm apply          # auto-merges with every other mod's [[patch]] blocks
"""

import sys
from pathlib import Path

# Make `from rsmm import sdk` resolvable without an install step.
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from rsmm import sdk

with sdk.Mod(
    id="ExampleSdkMod",
    name="Example SDK Mod",
    version="1.0.0",
    author="RSMM",
    description="Demonstrates the rsmm.sdk authoring API.",
    load_order=50,
) as m:
    # Balance: double bleed; halve enemy damage.
    m.stat("Bleed_Duration_Value", value=10)
    m.stat("Chapter_Scaling_Enemies_Damage_Factor", value=0.5)

    # Camp difficulty: easier early game.
    m.stat("Easy", min=5, max=10)

    # Translation: rename the Discord menu button to "Mods".
    m.text("Common", lang="EN", key="Menu_Discord", value="Mods")

    # URL redirect (where to send a click on the menu button).
    m.url("DiscordUrl", "https://example.com/mods")

    # Texture swap: friendly aliases auto-registered for hero portraits.
    m.texture("hero.romeo.portrait_active",
              donor="hero.sunwukong.portrait_active")

print(f"Wrote mods/{m.id}/manifest.toml")
print("Next: ./rsmm apply")
