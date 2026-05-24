local R = require "rsmm"
local I = R._internal

local DAT_GAMEOPTIONS_LINK  = 0x14140dd50
local FORCED_SEED_VALUE_OFF = 0x28
local FORCED_ENABLE_OFF     = 0x58
local EXPECTED_FORCED_ID    = 0x1949b098
local EXPECTED_ENABLE_ID    = 0x1949b099

local pinned   = false
local attempts = 0
local DEFAULT_SEED = 30758939

local function link_to_runtime(va)
    return I.module_base() + (va - 0x140000000)
end

local function try_pin()
    if pinned then return end
    attempts = attempts + 1

    local opts_ptr_addr = link_to_runtime(DAT_GAMEOPTIONS_LINK)
    local opts_struct   = I.read_u64(opts_ptr_addr)
    if opts_struct == 0 then
        if attempts == 1 or attempts % 10 == 0 then
            R.log(("[SeedPin] GameOptions not initialized yet (try %d)"):format(attempts))
        end
        return
    end
    local id_forced = I.read_u32(opts_struct + 0x08)
    local id_enable = I.read_u32(opts_struct + 0x38)
    if id_forced ~= EXPECTED_FORCED_ID or id_enable ~= EXPECTED_ENABLE_ID then
        R.log(("[SeedPin] layout drift — forced=0x%x enable=0x%x; aborting"):format(id_forced, id_enable))
        pinned = true
        return
    end
    I.write_u32(opts_struct + FORCED_SEED_VALUE_OFF, DEFAULT_SEED)
    I.write_u8 (opts_struct + FORCED_ENABLE_OFF,     1)
    pinned = true
    R.log(("[SeedPin] forced seed = %d (enable=1) after %d ticks"):format(DEFAULT_SEED, attempts))
end

R.on("ready", try_pin)
R.on("tick",  try_pin)
