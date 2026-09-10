-- R.watch — hardware watchpoints. "WHO WROTE THIS BYTE?"
--
-- WHY THIS EXISTS. Everything else in this SDK answers "what happened". This
-- answers "who did it", which is the question that has actually cost the
-- sessions: a field changes and nothing in the symbol map says which code
-- changed it, so the answer gets guessed from call sites and the guess is
-- wrong (see the entity-identity offsets that turned out to be heap
-- coincidence). The usual tools do not exist here — the target is a Windows PE
-- under Proton, so rr does not apply and gdb sees Wine's frames, not the
-- game's. x86-64 has the mechanism in silicon and the loader can just use it.
--
--     R.watch.on(hero + 0x15c8, { len = 4, label = "hp" })
--     -- play until the thing happens, then:
--     R.watch.report()
--     -- [watch] hp 0x140... x3   <- feed that to scripts/disasm.py --whatis
--
-- THE OUTPUT IS A STATIC VA, on purpose. Symbolising in-process would mean
-- shipping a second copy of the pattern DB into the game; the repo already has
-- a disassembler that resolves a VA to a semantic name
-- (`python scripts/disasm.py --whatis <va>`), so this rebases the runtime RIP
-- onto the image base the symbol map uses and prints that. One copy of the
-- knowledge, on the side that already has it.
--
-- FOUR SLOTS IN THE WHOLE CPU. A bisection instrument, not a tracer.
--
-- ⚠ OFF UNLESS ARMED. Needs `RSMM_ENABLE_WATCH=1` in the loader flags. A
-- process-wide exception handler plus the debug registers is the shape an
-- anti-tamper check looks for, and this game has anti-tamper logic. Never
-- leave it on in a normal session.
--
-- ⚠ PER-THREAD. Debug registers live in the thread context, so a thread the
-- game creates AFTER arming carries none. That is what "it stopped reporting"
-- means; `R.watch.rearm()` is the fix, and `R.watch.on` reports how many
-- threads it reached so zero is visible rather than silent.
--
-- ⚠ THE RIP IS THE INSTRUCTION AFTER THE ACCESS. The CPU raises a trap, not a
-- fault. `--whatis` lands inside the right function either way, but do not
-- read the address as the writing instruction's own start.

local M = {}

local R, I

--: The base `data/symbols.json` records addresses against. Runtime RIP is
--: rebased onto it so the printed value is the one every offline tool expects.
local IMG_BASE = 0x140000000

--: `label` per slot, so a report says "hp" rather than an address the reader
--: has to remember the meaning of.
local _labels = {}

local function _static(rip)
    local base = I.module_base()
    if not base or base == 0 then return rip end
    return rip - base + IMG_BASE
end

--- Watch `va`. Returns slot, or nil + reason.
---
--- `opts.len` is 1/2/4/8 (default 4) and `va` MUST be aligned to it — the CPU
--- requires it and a misaligned watchpoint never fires, which reads as "nothing
--- wrote it". `opts.kind` is "w" (default) or "rw". `opts.label` names it.
function M.on(va, opts)
    opts = opts or {}
    local len = opts.len or 4
    local slot, err = I.watch_set(va, len, opts.kind or "w")
    if not slot then
        R.log("[watch] " .. tostring(err))
        return nil, err
    end
    _labels[slot] = opts.label or string.format("%#x", va)
    return slot
end

--- Watch a FIELD of a live object — the common case, and the one where the
--- alignment rule bites, so it is checked here with a message that says what
--- to do instead of failing in silicon.
function M.field(ptr, off, opts)
    opts = opts or {}
    local len = opts.len or 4
    local va = ptr + off
    if va % len ~= 0 then
        local err = string.format(
            "%#x+%#x = %#x is not %d-byte aligned; a misaligned watchpoint "
            .. "never fires. Use len = %d, or watch the aligned neighbour.",
            ptr, off, va, len, 1)
        R.log("[watch] " .. err)
        return nil, err
    end
    return M.on(va, opts)
end

--- Disarm one slot, or every slot when `slot` is nil.
function M.off(slot)
    if slot == nil then _labels = {} else _labels[slot] = nil end
    return I.watch_clear(slot)
end

--- Re-apply every armed slot to every thread, including ones created since.
--- Returns how many threads were armed.
function M.rearm()
    local n = I.watch_rearm()
    R.log("[watch] re-armed " .. tostring(n) .. " thread(s)")
    return n
end

--- Drain the recorded hits and log them, grouped by writer.
---
--- Grouped because a watchpoint on a per-frame field produces hundreds of
--- identical lines and one distinct writer; the count is the interesting part
--- and the address is the answer.
function M.report()
    local hits = I.watch_drain()
    if #hits == 0 then
        -- Say WHICH of the two "no hits" this is. A slot that reached no
        -- thread and a field nothing wrote look identical in a log, and they
        -- call for opposite next steps.
        local armed = 0
        for _, s in ipairs(I.watch_status()) do
            if s.armed then armed = armed + 1 end
        end
        R.log("[watch] no hits (" .. armed .. " slot(s) armed) — if this is "
              .. "unexpected, try R.watch.rearm(): a thread created after "
              .. "arming carries no debug registers")
        return {}
    end

    local by = {}
    local order = {}
    for _, h in ipairs(hits) do
        local va = _static(h.rip)
        local key = h.slot .. ":" .. va
        if not by[key] then
            by[key] = { slot = h.slot, va = va, tid = h.tid, count = 0,
                        label = _labels[h.slot] or ("slot " .. h.slot) }
            order[#order + 1] = key
        end
        by[key].count = by[key].count + 1
    end

    local out = {}
    for _, key in ipairs(order) do
        local g = by[key]
        out[#out + 1] = g
        R.log(string.format(
            "[watch] %s wrote from %#x x%d (tid %d) — "
            .. "python scripts/disasm.py --whatis %#x",
            g.label, g.va, g.count, g.tid, g.va))
    end
    return out
end

--- `{ {slot, addr, len, kind, hits, armed, label}, ... }`.
function M.status()
    local st = I.watch_status()
    for _, s in ipairs(st) do s.label = _labels[s.slot] end
    return st
end

return function(env)
    R, I = env.R, env.I
    return M
end
