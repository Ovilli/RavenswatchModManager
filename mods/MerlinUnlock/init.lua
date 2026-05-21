-- MerlinUnlock — force unlock conditions to succeed.
--
-- Hooks slot 3 (IsUnlocked) of the three condition subclasses that
-- Merlin's herodef actually uses.  Installed on the first tick
-- (post-init but before hero selection screen builds).

local R = require "rsmm"

local POINTERS_FILE = "pointers.json"
local TOTAL_HOOKS = 3

local HOOK_NAMES = {
    "AdditionalContentGameUnlockConditionSettings_IsUnlocked",
    "NamedEventGameLockConditionSettings_IsUnlocked",
    "HeroProgressionUnlockConditionSettings_IsUnlocked",
}

local SIG = "ipp"

local function always_unlocked(_this, _ctx)
    return 1
end

local ptrs = nil
local done = false

local function file_exists(p)
    local f = io.open(p, "rb")
    if not f then return false end
    f:close()
    return true
end

local function read_pointers(p)
    local f = io.open(p, "rb")
    if not f then return nil, "file not found" end
    local s = f:read("*a")
    f:close()
    local body = s:match('"hooks"%s*:%s*{(.-)}')
    if not body then return nil, "no `hooks` object" end
    local out = {}
    for k, v in body:gmatch('"([%w_]+)"%s*:%s*"([^"]+)"') do
        out[k] = v
    end
    return out
end

local function try_install()
    local ptrs_path = R.mod_dir() .. "/" .. POINTERS_FILE
    if not file_exists(ptrs_path) then
        R.log("[MerlinUnlock] pointers.json not found at " .. ptrs_path)
        return
    end
    ptrs = read_pointers(ptrs_path)
    if not ptrs then
        R.log("[MerlinUnlock] failed to parse pointers.json")
        return
    end

    local n = 0
    for _, name in ipairs(HOOK_NAMES) do
        local va = ptrs[name]
        if not va then
            R.log("[MerlinUnlock] missing pointer: " .. name)
        else
            local ok, slot = pcall(R.hook, va, SIG, always_unlocked)
            if ok and slot then
                n = n + 1
                R.log(string.format("[MerlinUnlock] hooked %s @ %s slot=%d",
                      name, va, slot))
            else
                R.log(string.format("[MerlinUnlock] hook FAILED for %s @ %s: %s",
                      name, va, tostring(slot)))
            end
        end
    end
    R.log(string.format("[MerlinUnlock] installed %d/%d hooks", n, TOTAL_HOOKS))
end

R.on("tick", function()
    if done then return end
    done = true
    R.log("[MerlinUnlock] first tick — installing hooks")
    pcall(try_install)
end)
