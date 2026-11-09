-- ExampleGameModifier — a custom "negative mode" (GameModifier).
--
-- The new selectable modifier is declared in manifest.toml via [[content]]
-- (kind="modifier"); the SDK clones a vanilla def, relabels it and repoints its
-- behaviour. This init.lua shows the RUNTIME side: reading modifier state with
-- R.modifier, so a mod can layer custom behaviour gated on which modifiers are
-- active this run (Heredos wishlist #5/#6/#17). See docs/_re/kinds/game-modifiers.md.

local R = require "rsmm"

-- Report the run's modifier state once the hero is live. R.modifier reads the
-- engine's CRC-keyed entity-value store by name; values are 0/nil until a run
-- with modifiers is actually loaded (read-only, never faults).
R.on("ready", function()
    R.log("[ExampleGameModifier] loaded; custom modifier 'Double Trouble' is declarative.")
end)

-- Example custom behaviour: when the player picks up an item AND the run has the
-- "Game Difficulty" lever raised, log a heads-up. Swap the body for a real
-- effect (e.g. R.combat / R.give) to build a true combo-modifier.
R.on("gameplay:GIVE_MAGICAL_OBJECT", function(_)
    local diff = R.modifier.value("Game Difficulty")
    if type(diff) == "number" and diff > 0 then
        R.log(string.format("[ExampleGameModifier] item gained at difficulty %.0f", diff))
    end
end)
