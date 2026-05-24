local R = require "rsmm"

R.on("ready", function()
    R.log("[TheForgotten] v1.0.0 loaded")

    local hero_count = 0
    local enemy_count = 0
    local boss_count = 0
    local item_count = 0

    local mods = R.list_mods()
    for _, m in ipairs(mods or {}) do
        if m.id == "TheForgotten" and m.enabled then
            R.log("[TheForgotten] Content registered: Vindicator (hero), CursedKnight (enemy), ForgottenKing (boss), 3 items")
            hero_count = 1
            enemy_count = 1
            boss_count = 1
            item_count = 3
            break
        end
    end

    R.log(("[TheForgotten] %d hero, %d enemy, %d boss, %d items ready"):format(
        hero_count, enemy_count, boss_count, item_count
    ))
end)

R.on("level_load", function(payload)
    R.log(("[TheForgotten] Level loaded: %s"):format(payload.name or "unknown"))
end)
