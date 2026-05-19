-- ExampleMagicItem — content is declared in manifest.toml via [[content]].
-- This init.lua just logs at ready so the mod has a runtime presence.
--
-- For runtime behavior (e.g. per-tick effect on the owning hero),
-- subscribe to R.events here once R.hero is exposed.

local R = require "rsmm"
R.health.checkpoint("per_mod:ExampleMagicItem")

R.on("ready", function()
    R.log("[ExampleMagicItem] loaded; item registration is declarative.")
end)
