local R = require "rsmm"

-- Pin the run-generation seed via the engine's own option registry so every
-- participant generates the identical world. "Forced seed" is only honoured
-- while the "Dev" build flag is true, so both are set together. All
-- address/offset knowledge lives in R.options (the SDK), so a game patch
-- that moves the registry can't break this mod.
--
-- The chapter-3 start itself is data-side: the [[content]] block in
-- manifest.toml overrides the All_Chapters gamemode def with a re-sequenced
-- chapter list. Nothing to do here at runtime for that part.

local pinned   = false
local attempts = 0
-- Seed comes from the per-mod config (config.toml / desktop UI), falling
-- back to the schema default. See config_schema.toml. Change the seed per
-- race event; all participants must use the same value.
local RACE_SEED = R.config.get("seed", 30758939)

local function try_pin()
    if pinned then return end
    attempts = attempts + 1
    -- get() is silent while the registry is still nil this early in boot;
    -- probing with it first keeps the retry loop from spamming set()'s
    -- "registry not ready" log line every tick.
    if R.options.get("Forced seed") == nil then
        if attempts == 1 or attempts % 10 == 0 then
            R.log(("[SeedRuns] GameOptions not ready yet (try %d)"):format(attempts))
        end
        return
    end
    R.options.set("Forced seed", RACE_SEED)
    R.options.set("Dev", true)
    pinned = true
    R.log(("[SeedRuns] forced seed = %d (Dev=1) after %d tick(s)"):format(
        RACE_SEED, attempts))
end

R.on("ready", try_pin)
R.on("tick",  try_pin)
