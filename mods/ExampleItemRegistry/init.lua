local R = require "rsmm"

R.on("ready", function()
    R.item.register({
        id = "FrostBlade",
        name = "Frost Blade",
        description = "An icy weapon that chills enemies on hit.",
        rarity = "Rare",
        base = "Common/Armor_Per_Object",
    })

    R.item.register({
        id = "EmberShield",
        name = "Ember Shield",
        description = "A fiery shield that burns nearby foes.",
        rarity = "Epic",
        base = "Common/Armor_Per_Object",
    })

    local count = #R.item.list()
    R.log("[ExampleItemRegistry] Registered " .. count .. " items (TODO: not yet wired to game)")
end)
