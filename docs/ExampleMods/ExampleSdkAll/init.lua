-- Exercise every v3 surface so we have a single mod to test against.

local R = require "rsmm"

R.health.checkpoint("per_mod:ExampleSdkAll")

-- Publish an API other mods can consume.
R.api.expose({
    api_name = "exampleall",
    version  = "0.1.0",
    greet = function(name)
        return R.i18n.t("hello", { name = name or "world" })
    end,
})

R.on("ready", function()
    R.log(R.i18n.t("loaded"))
    R.log("mode=" .. tostring(R.config.get("mode", "soft")))
end)

-- Demonstrate schedule + events without depending on the engine being up.
R.schedule.after(1, function()
    R.log("[ExampleSdkAll] 1s tick fired")
end)

R.config.on_change("damage_mult", function(new, old)
    R.log(("[ExampleSdkAll] damage_mult %s -> %s"):format(tostring(old), tostring(new)))
end)
