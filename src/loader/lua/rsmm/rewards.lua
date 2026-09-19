-- R.rewards — read the LIVE reward definitions.
--
-- WHY. A `reward` mod rewrites a retail *.rewarddef.ot, and "the file is on
-- disk" has never been the question: the 2026-07-12 playtest had a
-- byte-correct override installed and chests still spawned. What decides it
-- is which def objects the engine actually holds. The definition registry
-- (R.defs) already enumerates them by class, so this reads each one's
-- reward_types vector and hands back its SHAPE — the same (min, max, items)
-- triple per type that the cooked codec reports — which is a fingerprint an
-- override can be recognised by without knowing a def's name.
--
-- Layout (RE 2026-07-12, docs/_re/kinds/rewards.md — the roll handler's own
-- Block-1 reads):
--   def+0x288   reward_types vector data (array of type-entry pointers)
--   def+0x290   u32 count
--   type+0x10   u32 item count
--   type+0x18   u32 min count
--   type+0x1c   u32 max count
--
-- Read-only and page-guarded. A def whose vector does not read plausibly is
-- reported with `types = nil`, never skipped silently, so a moved offset shows
-- up as a result.

local M = {}

local R, I

local TYPES_PTR, TYPES_N = 0x288, 0x290
local T_ITEMS, T_MIN, T_MAX = 0x10, 0x18, 0x1c
local MAX_TYPES = 64

--- The reward_types shape of one live def: `{ {min=, max=, items=}, ... }`,
--- or nil when the vector does not read plausibly.
function M.shape(def)
    if not (I.read_u64 and I.read_u32 and R.ptr) then return nil end
    if not R.ptr.plausible(def) then return nil end
    local arr = I.read_u64(def + TYPES_PTR)
    local n = I.read_u32(def + TYPES_N)
    if not arr or not n or n == 0 or n > MAX_TYPES then return nil end
    if not R.ptr.plausible(arr) then return nil end
    local out = {}
    for i = 0, n - 1 do
        local t = I.read_u64(arr + i * 8)
        if not t or not R.ptr.plausible(t) then return nil end
        out[#out + 1] = { items = I.read_u32(t + T_ITEMS),
                          min = I.read_u32(t + T_MIN),
                          max = I.read_u32(t + T_MAX) }
    end
    return out
end

--- `"(min,max,items)(...)"` — the form the cooked codec and a manifest's
--- expected shape are written in, so a log line compares by eye.
function M.format(shape)
    if not shape then return "<unreadable>" end
    local parts = {}
    for _, t in ipairs(shape) do
        parts[#parts + 1] = ("(%s,%s,%s)"):format(
            tostring(t.min), tostring(t.max), tostring(t.items))
    end
    return table.concat(parts)
end

--- Every live oCDtRewardDefinition: `{ {def=, shape=}, ... }`, plus a reason
--- string when the registry itself cannot be read.
function M.defs()
    if not (R.defs and R.defs.instances) then return {}, "R.defs missing" end
    if R.defs.ready and not R.defs.ready() then
        return {}, (R.defs.why_not and R.defs.why_not()) or "registry unreadable"
    end
    local out = {}
    for _, d in ipairs(R.defs.instances("RewardDefinition") or {}) do
        out[#out + 1] = { def = d, shape = M.shape(d) }
    end
    return out
end

--- Log every live reward def's shape, marking any that equals `expect`
--- (a formatted shape string). Returns how many matched.
function M.report(expect, tag)
    tag = tag or "[rsmm.rewards]"
    local defs, why = M.defs()
    if why then
        R.log(tag .. " cannot read reward defs: " .. why)
        return 0
    end
    local hits = 0
    for _, e in ipairs(defs) do
        local s = M.format(e.shape)
        local mark = ""
        if expect and s == expect then
            hits = hits + 1
            mark = "   <<< MATCHES"
        end
        R.log(("%s def 0x%x types %s%s"):format(tag, e.def, s, mark))
    end
    R.log(("%s %d live reward def(s)%s"):format(tag, #defs,
        expect and ((", %d match %s"):format(hits, expect)) or ""))
    return hits
end

return function(env)
    R, I = env.R, env.I
    return M
end
