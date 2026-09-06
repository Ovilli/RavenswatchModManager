-- R.exp — declare a hypothesis in-game, record evidence, close it with a
-- verdict that `rsmm exp` reads back as a table.
--
-- WHY THIS EXISTS. A playtest is the only source of truth for most of this
-- SDK, and it is expensive: a human plays the game, then a fresh session
-- reads a log. Historically one run returned ONE bit, because the answer was
-- prose in `_log.txt` that a person had to interpret. rsmm.lua already says
-- so out loud further up: "probe that cannot say which one wastes a
-- playtest." This module makes a run carry N independent answers instead.
--
--     R.exp.run("tile_registered", "does the pool take a mod tile?", function()
--         local n = count_tiledefs()
--         R.exp.observe("tile_registered", "tiledefs", n)
--         return n > 237, n .. " tiledefs (237 shipped + " .. (n - 237) .. ")"
--     end)
--
--     -- ...or, when the answer only arrives later, from an event:
--     R.exp.case("tile_placed", "is a mod tile ever PLACED?")
--     R.on("gameplay:LEVEL_LOADED", function()
--         R.exp.verdict("tile_placed", saw_it, "3 generations")
--     end)
--
-- STORAGE is R.kv, i.e. <mod_dir>/.rsmm_state, which the loader already
-- writes temp-file + rename. Nothing new is planted and no native binding is
-- needed, so this ships as a Lua-only loader update.
--
-- EVERY WRITE IS FLUSHED IMMEDIATELY. That is the whole crash-safety story:
-- a hard access violation in case 3 kills the process outright and no pcall
-- can catch it, so cases 1-2 have to already be on disk. Evidence is flushed
-- for the same reason -- an observation is at its most valuable when it is
-- the last thing recorded before a crash. Keep observations to a handful per
-- case; a per-frame counter belongs in R.kv directly.

local M = {}

local R          -- injected by rsmm.lua

local PREFIX = "exp."
local SESSION = PREFIX .. "_session"

-- A verdict from the PREVIOUS launch that is still on disk would read as a
-- current PASS and is exactly the failure this module exists to prevent, so
-- the first R.exp call of a process drops every `exp.` key. Cases are always
-- declared after that point, so nothing live is ever cleared.
--
-- The "have I done this yet" flag lives IN THE STORE, not in a module local.
-- `require` caches this module, but `R.kv` is re-created whenever rsmm.lua is
-- re-loaded into the same lua_State (a hot reload of the SDK does exactly
-- that) -- so a plain local outlives the store it is describing, and the
-- reloaded store comes back off disk with the previous launch's verdicts
-- still in it and nothing left to clear them. Comparing our own stamp against
-- what the store currently holds catches that: a store we did not stamp is a
-- store we have not cleared, whichever way it got there.
local _stamp
local _serial = 0
local function _session()
    if _stamp and R.kv.get(SESSION) == _stamp then return end
    for k in pairs(R.kv.all()) do
        if k:sub(1, #PREFIX) == PREFIX then R.kv.set(k, nil) end
    end
    -- os.time() alone is not unique: two clears in the same second would
    -- compare equal and the second store would never be cleared.
    _serial = _serial + 1
    _stamp = os.time() + _serial / 1000
    R.kv.set(SESSION, _stamp)
    R.kv.save(true)
end

-- The key format is `exp.<id>.<field>`, so a dot in an id would split into a
-- field the reader does not know. Fold it rather than refusing: a probe that
-- dies on its own case name has wasted the run it was measuring.
local function _id(id)
    return (tostring(id):gsub("[.\t\n]", "_"))
end

--- Declare a hypothesis. Shows as NO-DATA until a verdict closes it, which is
--- itself a result: it says the code path never ran.
function M.case(id, question)
    _session()
    id = _id(id)
    R.kv.set(PREFIX .. id .. ".q", tostring(question or ""))
    R.kv.set(PREFIX .. id .. ".at", os.time())
    R.kv.save(true)
    return id
end

--- Record one piece of evidence under a case. Non-scalars are stringified —
--- R.kv persists only string/number/boolean.
function M.observe(id, key, value)
    _session()
    local t = type(value)
    if t ~= "string" and t ~= "number" and t ~= "boolean" then
        value = tostring(value)
    end
    R.kv.set(PREFIX .. _id(id) .. ".o." .. _id(key), value)
    R.kv.save(true)
    return value
end

--- Close a case. Safe to call for an id that was never declared — a verdict
--- with no question still reads back fine, which matters when the only place
--- that knows the answer is a handler far from the declaration.
function M.verdict(id, pass, why)
    _session()
    id = _id(id)
    pass = not not pass
    why = tostring(why or "")
    R.kv.set(PREFIX .. id .. ".pass", pass)
    R.kv.set(PREFIX .. id .. ".why", why)
    R.kv.set(PREFIX .. id .. ".at", os.time())
    R.kv.save(true)
    R.log("[rsmm.exp]", id, pass and "PASS" or "FAIL", why)
    return pass
end

--- Declare, run, and close in one go, for a hypothesis answerable on the
--- spot. `fn` returns (pass, why).
---
--- A Lua error inside `fn` closes the case FAIL with the error text instead
--- of propagating. One broken probe must not take the rest of the batch with
--- it — that is the difference between a run that answers 1 of 4 questions
--- and one that answers 4.
function M.run(id, question, fn)
    M.case(id, question)
    local ok, pass, why = pcall(fn)
    if not ok then
        return M.verdict(id, false, "error: " .. tostring(pass))
    end
    return M.verdict(id, pass, why)
end

--- Every case this process has written, as `{ [id] = {question=, pass=,
--- why=, at=, obs={}} }`. Mirrors what `rsmm exp` prints; useful from a mod
--- that wants to react to its own results.
function M.all()
    local out = {}
    for k, v in pairs(R.kv.all()) do
        if k:sub(1, #PREFIX) == PREFIX and k ~= SESSION then
            local id, field = k:sub(#PREFIX + 1):match("^([^.]+)%.(.+)$")
            if id then
                local c = out[id]
                if not c then c = { obs = {} }; out[id] = c end
                if field == "q" then c.question = v
                elseif field == "pass" then c.pass = v
                elseif field == "why" then c.why = v
                elseif field == "at" then c.at = v
                else
                    local o = field:match("^o%.(.+)$")
                    if o then c.obs[o] = v end
                end
            end
        end
    end
    return out
end

return function(env)
    R = env.R
    return M
end
