local R = require "rsmm"

R.on("ready", function()
    local ok, addr = pcall(R._internal.resolve, "FUN_140487040")
    if not ok or addr == 0 then
        R.log("[ExampleHookMod] Could not resolve target function; hooks not supported on this build")
        return
    end

    local hooked = false
    R.hook(addr, "p", function(...)
        if not hooked then
            hooked = true
            R.log("[ExampleHookMod] Hook installed — resource lookup intercepted (first call only)")
        end
    end)
end)
