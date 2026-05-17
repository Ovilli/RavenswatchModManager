-- Force the run seed to a fixed value.
--
-- Mechanism (reverse-engineered from FUN_1401c6d60, the global
-- GameOptions constructor):
--
--   DAT_14140dd50 holds a pointer to the GameOptions root struct.
--   The first option in that struct is "Forced seed" (oe::UIntGameOption).
--     - id              0x1949b098 at offset +0x08
--     - VALUE u32                  at offset +0x28
--   The second option is "Forced seed enable" (oe::BoolGameOption).
--     - id              0x1949b099 at offset +0x38
--     - VALUE u8                   at offset +0x58
--
-- Timing: the GameOptions constructor runs AFTER our loader's "ready"
-- event fires, so DAT_14140dd50 will still be null at "ready" time.
-- We listen on "tick" (fired every 500 ms by the loader) and retry
-- until the struct exists, then write once and unsubscribe in spirit
-- (`pinned` flag — we only write once).

local SEED                  = 30758939
local DAT_GAMEOPTIONS_LINK  = 0x14140dd50            -- link-time VA
local FORCED_SEED_VALUE_OFF = 0x28
local FORCED_ENABLE_OFF     = 0x58
local EXPECTED_FORCED_ID    = 0x1949b098
local EXPECTED_ENABLE_ID    = 0x1949b099

local pinned   = false
local attempts = 0

local function link_to_runtime(va)
    -- link-time was image_base 0x140000000; rebase to whatever the OS
    -- mapped the exe at this run.
    return rsmm.module_base() + (va - 0x140000000)
end

local function try_pin()
    if pinned then return end
    attempts = attempts + 1

    local opts_ptr_addr = link_to_runtime(DAT_GAMEOPTIONS_LINK)
    local opts_struct   = rsmm.read_u64(opts_ptr_addr)
    if opts_struct == 0 then
        if attempts == 1 or attempts % 10 == 0 then
            rsmm.log(("[SeedPin] GameOptions not initialized yet (try %d)"):format(attempts))
        end
        return
    end
    -- Sanity: the ids must match what the constructor wrote. Refuses
    -- to write if the game patched and the layout drifted.
    local id_forced = rsmm.read_u32(opts_struct + 0x08)
    local id_enable = rsmm.read_u32(opts_struct + 0x38)
    if id_forced ~= EXPECTED_FORCED_ID or id_enable ~= EXPECTED_ENABLE_ID then
        rsmm.log(("[SeedPin] layout drift — forced=0x%x enable=0x%x; aborting"):format(id_forced, id_enable))
        pinned = true   -- stop retrying
        return
    end
    rsmm.write_u32(opts_struct + FORCED_SEED_VALUE_OFF, SEED)
    rsmm.write_u8 (opts_struct + FORCED_ENABLE_OFF,     1)
    pinned = true
    rsmm.log(("[SeedPin] forced seed = %d (enable=1) after %d ticks"):format(SEED, attempts))
end

rsmm.on_event("ready", try_pin)
rsmm.on_event("tick",  try_pin)
