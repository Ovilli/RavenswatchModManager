local R = require "rsmm"

-- ADDITIVE PICKABLE TALENT — replaces nothing.
--
-- The hero's 28 Skill Controller rows are a fixed schema (a 29th bricks the
-- hero — see docs/_re/kinds/skills-system.md), so a net-new *skill* card is not
-- possible as a data mod. The magical-object / reward pool is the opposite:
-- variable-length and UsedRscList-additive. So a NEW magical object is the
-- engine-supported "new card", and the mod's own Lua gives it talent behaviour.
--
-- Two layers compose:
--   1. manifest [[content]] kind="item"  -> emits + registers the NEW asset
--      (the visible, pickable card; loads into the pool via UsedRscList).
--   2. this init.lua                      -> the mod's OWN effect, bound to the
--      item's runtime identity GUID via R.item.on_guid + R.item.behavior.

local ITEM_ID    = "RSMM_Talent_LightningReflexes"
local ENTITY_PATH =
    "EntitySettings/Objects/Magical_Objects/Common/"
    .. ITEM_ID .. ".entity.ot.EntitySettingsResource"
local HEAL_PER_USE = 5

-- Tell the loader the item's path so it can resolve the runtime GUID. (The
-- asset itself is registered by the manifest's item kind; this just records the
-- path in the native item registry that R.item.guid reads.)
R.item.register{ id = ITEM_ID, entity_path = ENTITY_PATH }

-- Once the definition has loaded into the pool, resolve its identity GUID and
-- arm the talent: heal on each ability use, but only while the item is owned.
R.item.on_guid(ITEM_ID, function(lo, hi)
    R.log(string.format("[additive-talent] %s identity %08x:%08x — armed",
        ITEM_ID, hi, lo))
    R.on("gameplay:ABILITY_EXIT", function()
        if not (R.give.owns and R.give.owns(lo, hi)) then return end
        if not R.entity.ready() then return end
        local before = R.entity.hp() or -1
        R.combat.heal(HEAL_PER_USE)
        R.log(string.format("[additive-talent] heal %d (HP %.0f -> %.0f)",
            HEAL_PER_USE, before, R.entity.hp() or -1))
    end)
end)

R.on("ready", function()
    R.log("[additive-talent] waiting for " .. ITEM_ID .. " to load into the pool")
end)
