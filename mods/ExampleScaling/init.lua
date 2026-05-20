local R = require "rsmm"

R.on("ready", function()
    R.scaling.set("enemy_damage", function(act)
        local mult = ({1, 1.5, 2.5, 4})[act] or 1
        return mult
    end)

    R.scaling.set("enemy_health", function(act)
        local mult = ({1, 1.4, 2.0, 3.0})[act] or 1
        return mult
    end)

    R.log("[ExampleScaling] Enemy damage/health scaling overrides installed (TODO: not yet wired to game)")
end)
