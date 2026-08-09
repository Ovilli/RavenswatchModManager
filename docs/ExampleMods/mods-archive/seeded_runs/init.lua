local R = require "rsmm"

-- Pin the run-generation seed via the engine's own option registry.
-- "Forced seed" is only honoured while the "Dev" build flag is true, so both
-- are set together. All address/offset knowledge lives in R.options (the SDK),
-- so a game patch that moves the registry can't break this mod.

local pinned   = false
local attempts = 0
-- Seed comes from the per-mod config (config.toml / desktop UI), falling
-- back to the schema default. See config_schema.toml.
local DEFAULT_SEED = R.config.get("seed", 30758939)

local function try_pin()
    if pinned then return end
    attempts = attempts + 1
    -- get() is silent while the registry is still nil this early in boot;
    -- probing with it first keeps the retry loop from spamming set()'s
    -- "registry not ready" log line every tick.
    if R.options.get("Forced seed") == nil then
        if attempts == 1 or attempts % 10 == 0 then
            R.log(("[SeedPin] GameOptions not ready yet (try %d)"):format(attempts))
        end
        return
    end
    R.options.set("Forced seed", DEFAULT_SEED)
    R.options.set("Dev", true)
    pinned = true
    R.log(("[SeedPin] forced seed = %d (Dev=1) after %d tick(s)"):format(
        DEFAULT_SEED, attempts))
end

R.on("ready", try_pin)
R.on("tick",  try_pin)
