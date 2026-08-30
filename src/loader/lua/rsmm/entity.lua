-- rsmm.entity — the local hero: capture, health, and the entity-value store.
--
-- Split out of rsmm.lua on 2026-08-23, after R.damage. This one is NOT
-- self-contained the way the damage meter was: it sits early in the chunk and
-- the rest of the SDK reads its offsets and predicates as plain locals. So it
-- takes six values IN and hands ten back OUT, and rsmm.lua assigns those to the
-- locals the inline code used to declare. Everything in `exports` is a constant
-- or a function — nothing there is learned at runtime, which is what makes
-- copying them safe (see the getter in rsmm/damage.lua for the case that is
-- not).
--
-- Two of the exports are ASSIGNMENTS BACK into locals rsmm.lua forward-declares
-- above this file's require point (`_hero_capture_is_live`,
-- `_invalidate_hero_capture`): the give path calls them through those upvalues,
-- so they have to land there and not merely exist here.

return function(env)

for _, key in ipairs({ "I", "R", "_va_ok", "_ptr_plausible",
                       "ENTITY_HUDMIRROR_OFF", "ENTITY_ISLOCAL_OFF" }) do
    if env[key] == nil then
        error("rsmm.entity: parent did not pass env." .. key, 0)
    end
end

local I, R                 = env.I, env.R
local _va_ok               = env._va_ok
local _ptr_plausible       = env._ptr_plausible
local ENTITY_HUDMIRROR_OFF = env.ENTITY_HUDMIRROR_OFF
local ENTITY_ISLOCAL_OFF   = env.ENTITY_ISLOCAL_OFF

-- Declared here so the two parent-bound predicates below can be assigned to
-- them exactly as the inline code did; handed back in `exports`.
local _hero_capture_is_live, _invalidate_hero_capture

-- entity / combat -------------------------------------------------------
--
-- Read and modify the local hero's health. The hero CHARACTER object (the one
-- carrying HP) is NOT the bus dispatcher and can't be derived from it — the
-- engine bakes the hero into each event subscription as the handler's first
-- arg. So we capture it by hooking two hero-bound handlers read-only (the
-- GAIN_HEALTH handler and the give-item handler) and grabbing param_1 the
-- first time either fires (i.e. the hero heals/regens or picks something up).
-- Health is then applied through the engine's own modify-health routine
-- (Entity_ModifyHealth), so clamping, the UI bar, on-heal/on-damage triggers
-- and analytics all fire exactly as if the game did it.
--
--   R.entity.hp()        -- current HP (float) or nil (hero not captured yet)
--   R.entity.max_hp()    -- max HP or nil
--   R.entity.hp_frac()   -- hp/max in 0..1 or nil
--   R.entity.ready()     -- true once the hero is captured
--   R.combat.heal(20)    -- heal 20
--   R.combat.damage(15)  -- self-damage 15
--   R.combat.set_hp(50)  -- set HP to an absolute value

R.entity = {}
R.combat = {}

local ENTITY_HP_OFF      = 0x15c8        -- f32 current HP on the hero character
local ENTITY_MAXHP_OFF   = 0x15cc        -- f32 max HP
-- The chain Entity_ModifyHealth dereferences in its first four instructions:
--   r14 = *(entity + 0x8);  rbx = *(r14 + 0x30)
-- Both are unguarded on the engine side, so both are ours to check. See
-- _modify_health_safe below.
local ENTITY_STORE_OFF   = 0x08          -- component/value-store pointer
local ENTITY_STORE_HOP   = 0x30          -- first field ModifyHealth reads off it
-- Function addresses are resolved at runtime through the pattern DB
-- (I.resolve on the semantic symbol name) so a game patch that shifts code
-- can never leave us hooking/calling a stale VA: an unresolved symbol fails
-- closed instead. Only data addresses (vftable) stay link-time constants.
local FLAGLIST_VFT_VA    = 0x140f01650   -- oCCustomFlagList::vftable (re-derived 2026-07-10)
local ENTITY_IMG_BASE    = 0x140000000

local _hero_char = nil
-- Last hero pointer announced in the log. A capture is worth one line; the
-- same capture re-announced on every poll is not. A 4-player session produced
-- ~500 identical "hero CAPTURED" lines in ninety seconds, which buried every
-- other diagnostic in the file.
local _hero_logged = nil
local function _log_capture(fmt, hero, ...)
    if _hero_logged == hero then return end
    _hero_logged = hero
    R.log(string.format(fmt, hero, ...))
end          -- captured hero character object (HP@+0x15c8)
-- Spawn-init candidate whose HP/mirror fields are not populated yet. The Lua
-- mirror of the native pending slot: stashed by the hero's post-load init hook
-- and promoted by the tick pump the first time it reads plausible.
local _hero_pending = nil
local _hero_capture_armed = false
-- Process-global shared slots (see hook_events.cpp install_hero_capture):
--   0 = hero character pointer (published by native capture)
--   1 = native "authoritative seen" flag (give handler fired)
--   2 = native capture active sentinel (loader owns the capture hooks)
local SHARED_HERO_SLOT = 0
local HERO_AUTH_SLOT = 1
local NATIVE_CAPTURE_SLOT = 2
local HERO_PENDING_SLOT = 3   -- spawn-init candidate whose fields weren't live yet
-- Whether capture is PERMITTED (RSMM_ENABLE_HERO_CAPTURE), as opposed to
-- whether the native path armed. 0 = loader too old to say, 1 = yes, 2 = no.
local HERO_PERMIT_SLOT = 4
local PERMIT_NO = 2
-- Set once when the HP-field scan below has run. Every mod gets its own Lua
-- state and they all poll, so without a process-wide latch the scan would be
-- repeated (and re-logged) five times over.
local HERO_SCAN_SLOT = 5
-- Ring of spawn-init candidates published by the native hook; see the
-- promotion loop in R.entity.hero() for why one slot was not enough.
local HERO_RING_FIRST = 8
local HERO_RING_COUNT = 8

-- ⚠ THE SHARED SLOT MAP IS FULL — there are 16 slots and 15 are spoken for.
--
--   0..4   native: hero ptr / auth / capture-active / pending / permit
--   5      Lua: HP-field scan latch
--   6      Lua: hero rejection-diagnostic budget
--   7      Lua: name-probe latch (the only free slot left)
--   8..15  native: hero candidate RING — POINTERS, written by the loader
--
-- Slots 8..15 hold live hero pointers. Taking one for a Lua latch does not
-- merely collide, it EVICTS a spawn candidate: on 2026-08-16 the name probe
-- claimed slot 9, wrote 1 into it, and `hero CAPTURED` stopped appearing in
-- every subsequent session. Lua reads the ring (below) and must never write
-- it; `lua_shared_set` now refuses that range outright. Adding another latch
-- means growing g_shared, not borrowing a slot.
-- Slot 7 is the last free shared slot (8..15 are the native hero ring).
local LOBBY_REFRESH_SLOT = 7

-- When this state first saw ANY hero candidate, so a capture can report the
-- wait the player actually experienced. The native side reports its own
-- captures, but promotion usually happens HERE (the fields go live long after
-- the stash), and that path printed no timing at all — so the one number the
-- "capture takes ages" question needs was missing from the log.
local _hero_first_seen = nil

local function _note_hero_candidate()
    if not _hero_first_seen and I.now then
        local ok, t = pcall(I.now)
        if ok and type(t) == "number" then _hero_first_seen = t end
    end
end

--- "N.Ns after the first candidate appeared", or "" when unmeasurable.
local function _capture_latency()
    if not I.now then return "" end
    local ok, t = pcall(I.now)
    if not ok or type(t) ~= "number" then return "" end
    -- Prefer the RUN start. Measuring from the first candidate answered the
    -- wrong question: candidates are stashed in the menu, so a player who sat
    -- in the menu for ten minutes and then captured within seconds of pressing
    -- start was reported as a 443.9s capture, which reads as a loader bug and
    -- is not one.
    local started = R.run and R.run.started_at and R.run.started_at()
    if type(started) == "number" then
        return string.format(" (%.1fs after the run started)", t - started)
    end
    if not _hero_first_seen then return "" end
    return string.format(" (%.1fs after the first candidate appeared)",
                         t - _hero_first_seen)
end

-- True when the loader's native hero-capture is installed. When it is, the Lua
-- side must not arm its own per-state capture hooks (they'd collide with the
-- native ones, MH_ERROR_ALREADY_CREATED) — it just reads the shared slot.
-- The flag was never actually a gate. It stopped the NATIVE hooks, and then
-- this fallback installed detours on the SAME handlers the first time any mod
-- touched R.entity — a playtest log showed two `[hook] slot N installed` lines
-- directly beneath "[hero-capture] disabled", while the loader claimed
-- R.combat/R.entity/R.stat/R.xp were unavailable. The flag exists because
-- these detours have correlated with load-time crashes, so "off" has to mean
-- off everywhere, not just in C++.
--
-- Only an EXPLICIT denial refuses. A loader too old to publish the slot leaves
-- it 0, and those builds keep the previous behaviour rather than silently
-- losing capture (rsmm.lua is disk-loaded, so it can be newer than the DLL).
local function _capture_denied()
    if not I.shared_get then return false end
    local ok, v = pcall(I.shared_get, HERO_PERMIT_SLOT)
    return ok and v == PERMIT_NO
end

local function _native_capture_active()
    if not I.shared_get then return false end
    local ok, v = pcall(I.shared_get, NATIVE_CAPTURE_SLOT)
    return ok and v == 1
end

-- A captured pointer is "hero-like" if its max-HP field reads as a sane float
-- AND it carries a valid HUD HP-mirror pointer at +0x1d80. The mirror is the
-- hero discriminator: Entity_ModifyHealth dereferences **(hero+0x1d80) on every
-- heal/damage. Non-player entities (GAIN_HEALTH fires for enemies too) have no
-- HUD mirror, so requiring it rejects false captures. Verified in Ghidra
-- (FUN_140391d30 / FUN_140399a10). All reads are fault-safe (return nil on a
-- bad address).
--
-- ⚠ THIS DOES NOT MAKE A POINTER ModifyHealth-SAFE, though it claimed to until
-- session 8c4f. That run adopted 0x3cb111a0 through the give-handler; it had a
-- sane HP pair and a live mirror, passed here, and still took the process down
-- at Entity_ModifyHealth+0x45 — because the function reads a DIFFERENT chain
-- first (*(entity+0x8) then +0x30), and that slot held the -1 sentinel. The
-- mirror says "this is a hero"; it says nothing about the value store. Callers
-- that hand the pointer to the engine must use _modify_health_safe.
local function _hero_plausible(e)
    if not e or e == 0 then return false end
    local mx = I.read_f32(e + ENTITY_MAXHP_OFF)
    local cur = I.read_f32(e + ENTITY_HP_OFF)
    -- cur may legitimately EXCEED mx (overheal / shields / HP-boost items), so
    -- only bound it as finite+non-negative, not cur <= mx. mx must be a sane
    -- positive bar size — that's the real garbage-pointer discriminator, and
    -- the floor is 0.5 rather than >0 because the 2026-07-19 misfire's "max"
    -- was the DENORMAL 1.6e-43, which a bare >0 accepts.
    if not (type(mx) == "number" and mx >= 0.5 and mx < 1e6
        and type(cur) == "number" and cur >= 0 and cur < 1e6) then
        return false
    end
    local mirror = I.read_u64(e + ENTITY_HUDMIRROR_OFF)
    if type(mirror) ~= "number" or mirror == 0 then return false end
    -- mirror is dereferenced as *(mirror) (the HUD-rendered HP) by the engine;
    -- bound the value like cur so a random-but-readable pointer can't pass.
    local mv = I.read_f32(mirror)
    return type(mv) == "number" and mv >= 0 and mv < 1e6
end

-- Is this candidate THIS machine's player?
--
-- The HUD-mirror gate in _hero_plausible is a local-only test by RE (only the
-- local player owns a HUD HP mirror), and that is the whole defence against
-- publishing an ALLY as the hero. It is not much of a defence to rest on alone:
-- the spawn-init hook that feeds the candidate ring fires once per HERO, not
-- once per machine — the 2026-08-18 four-player session stashed three candidates
-- inside 5 ms and four more at the next chapter — so the ring is full of remote
-- allies and the mirror is the only thing between them and R.combat writing to
-- somebody else's HP.
--
-- The engine's own answer is the byte at +0x1d88. It is used to PREFER a
-- candidate, never to refuse one: a hero object mid-load reads 0 there, and
-- refusing on that would trade an ally-capture risk for never capturing at all.
--
-- ⚠ THESE LIVE ON R.entity, NOT IN LOCALS. rsmm.lua's module chunk is one Lua
-- function and Lua caps a function at 200 locals; this section is already at the
-- limit, so four more `local`s here stopped the whole SDK from compiling (every
-- mod dead — the same wall the DMG table exists to work around). Table fields
-- cost nothing, and none of this is on a per-hit path.
function R.entity._is_local(p)
    if not p or p == 0 then return false end
    return I.read_u8(p + ENTITY_ISLOCAL_OFF) == 1
end

-- CHAPTER INVALIDATION -----------------------------------------------------
--
-- The engine rebuilds every hero controller when a chapter loads (R.damage's
-- epoch/rebind machinery exists for the same reason). Nothing retired the
-- published capture, so after a chapter change slot 0 still held the PREVIOUS
-- chapter's hero — freed memory, which keeps reading plausible for a long time
-- (see the hero-switch note in R.entity.hero) — and every R.combat/R.stat/R.xp
-- write went into a dead object with nothing in the log to say so. The
-- 2026-08-18 session is exactly that: captured @71611030 at 17:24:48, two
-- chapter epochs later that pointer was still the published hero and no second
-- capture line ever appeared.
--
-- The native candidate RING (slots 8..15) has the same staleness and cannot be
-- cleared the same way: `lua_shared_set` refuses that range outright (a mod that
-- wrote a latch into slot 9 broke capture in every later session), and the
-- native stash DEDUPES, so a retired pointer is never overwritten either. So the
-- ring is retired on the Lua side: each entry is remembered with a FINGERPRINT
-- of the fields capture reads, and a retired entry is skipped only while that
-- fingerprint still matches. If the allocator hands the same address to the next
-- chapter's hero the fingerprint moves and the candidate is adopted normally, so
-- this cannot make a live hero permanently invisible.
R.entity._stale = {}

function R.entity._fingerprint(p)
    if not p or p == 0 then return "" end
    return table.concat({
        tostring(I.read_u64(p + ENTITY_HUDMIRROR_OFF)),
        tostring(I.read_f32(p + ENTITY_MAXHP_OFF)),
        tostring(I.read_f32(p + ENTITY_HP_OFF)),
        tostring(I.read_u8(p + ENTITY_ISLOCAL_OFF)),
    }, "/")
end

--- Was `p` retired at a chapter boundary, and is it still the same object?
function R.entity._retired(p)
    local fp = R.entity._stale[p]
    if fp == nil then return false end
    if R.entity._fingerprint(p) ~= fp then
        R.entity._stale[p] = nil        -- a new object at a recycled address
        return false
    end
    return true
end

--- Retire the captured hero and every pending candidate.
---
--- Called on the chapter teardown event, where the controller the capture points
--- at is about to be freed. Deliberately NOT called on MAP_GENERATION_DONE: the
--- next chapter's hero can be stashed and published before that event lands, and
--- retiring then would throw away the capture it just made.
---
--- Public because a mod that knows the hero is gone (a hero switch it drove
--- itself) can say so rather than waiting for a rejection to be noticed.
function R.entity.invalidate_capture(why)
    if not (I.shared_get and I.shared_set) then return false end
    local retired = 0
    local function retire(slot)
        local ok, v = pcall(I.shared_get, slot)
        if ok and type(v) == "number" and v ~= 0 then
            R.entity._stale[v] = R.entity._fingerprint(v)
            retired = retired + 1
        end
    end
    retire(SHARED_HERO_SLOT)
    retire(HERO_PENDING_SLOT)
    -- The ring is read-only from Lua (see above), so its entries are retired by
    -- fingerprint instead of by being zeroed.
    for i = 0, HERO_RING_COUNT - 1 do retire(HERO_RING_FIRST + i) end
    pcall(I.shared_set, SHARED_HERO_SLOT, 0)
    pcall(I.shared_set, HERO_AUTH_SLOT, 0)
    pcall(I.shared_set, HERO_PENDING_SLOT, 0)
    _hero_char = nil
    _hero_pending = nil
    if retired > 0 then
        R.log(("[rsmm.entity] hero capture retired (%s) — %d candidate(s) belong "
               .. "to the chapter being torn down; the next spawn re-captures")
              :format(tostring(why or "chapter change"), retired))
    end
    return true
end

-- Chapter teardown only; see R.entity.invalidate_capture for why
-- MAP_GENERATION_DONE is not subscribed.
R.on("gameplay:GAME_END_NEXT_CHAPTER",
     function() R.entity.invalidate_capture("GAME_END_NEXT_CHAPTER") end)
R.on("run:end", function() R.entity.invalidate_capture("run:end") end)

-- NOTE: ev.entity (= dispatcher - 0x4d8 from the gameplay bus) is NOT the hero
-- HP-carrier. Empirically _hero_plausible(ev.entity) fails: the dispatch entity
-- (dispatcher owner) and the HP-carrier are separate sub-objects — the hero is
-- bound into each subscription as functor context, not reachable from the event
-- by a fixed offset. So capture stays hook-based (param_1 of the hero handlers),
-- which needs one hero action (heal/lifesteal/pickup) but reads the right object.

-- Install the read-only capture hooks once. Both handlers take pointer args
-- only (no float), so hooking them is safe; the callback returns nil to replay
-- the original unchanged. Called lazily so R.hook is defined by first use.
local function _arm_hero_capture()
    if _hero_capture_armed then return end
    if _capture_denied() then
        _hero_capture_armed = true   -- refuse once, quietly thereafter
        R.log("[rsmm.entity] hero capture is disabled "
              .. "(RSMM_ENABLE_HERO_CAPTURE off) — not installing the capture "
              .. "hooks. R.combat/R.entity/R.stat/R.xp stay unavailable.")
        return
    end
    local base = I.module_base()
    if not base or base == 0 or not R.hook then return end
    _hero_capture_armed = true
    -- The GAIN_HEALTH handler fires for ANY entity that heals (incl. enemies),
    -- so its capture is only tentative (taken if nothing better seen yet). The
    -- give-item handler is hero-only (only the local player picks up MOs), so it
    -- is authoritative and overwrites any tentative capture.
    local function capture(p1, authoritative)
        if not _hero_plausible(p1) then return end
        if _hero_char == p1 then return end
        if _hero_char ~= nil and not authoritative then return end
        _hero_char = p1
        -- Publish to the process-global slot so other mods' Lua states (which
        -- lose the MinHook install with ALREADY_CREATED) still see this hero.
        if I.shared_set then pcall(I.shared_set, SHARED_HERO_SLOT, p1) end
        R.log(string.format("[rsmm.entity] hero captured @0x%x (hp %.0f/%.0f)%s",
            p1, I.read_f32(p1 + ENTITY_HP_OFF), I.read_f32(p1 + ENTITY_MAXHP_OFF),
            authoritative and " [authoritative]" or " [tentative]"))
    end
    -- Best-effort: a failed capture hook must NEVER abort the mod that
    -- required rsmm. Handler addresses come from the pattern DB (nil when the
    -- symbol is unverified for this game build — fail closed, never hook a
    -- stale VA), and R.hook can still raise on install failure, so guard each
    -- with pcall — capture just stays unavailable; everything else still runs.
    local gain_va = I.resolve and I.resolve("Entity_GainHealthHandler")
    local give_va = I.resolve and I.resolve("Entity_GiveHandler")
    -- Both handlers take pointer-only args (ptr,ptr,ptr). Either one captures
    -- the hero (the mirror plausibility check inside capture() rejects any
    -- non-hero entity that also fires them), so capture survives as long as ONE
    -- resolves; only warn when BOTH are unresolved for this build.
    -- ARG SEMANTICS differ: the gain-health handler's param_1 is the hero
    -- entity, but the give handler's param_1 is the hero's VALUE CONTEXT
    -- (*(hero+0x2f8)) and its param_2 is the hero entity (decompile-verified
    -- 2026-07-15; the ctx never passes _hero_plausible, which is why the
    -- authoritative capture silently never fired).
    -- R.hook returns (nil, "already-hooked") when another mod's lua_State got
    -- there first. That is the NORMAL case with more than one mod installed and
    -- the hook is live — the hero still arrives through the shared slot — so it
    -- must not be counted as a failure. Reporting it as one is what produced
    -- "both handlers unresolved for this game build" in a log where the
    -- handlers had resolved perfectly well and another mod owned the hook.
    local function arm(va, sig, fn)
        if not va then return false end
        local ok, slot, why = pcall(R.hook, va, sig, fn)
        if not ok then return false end
        if slot == nil and why == "already-hooked" then return true end
        return slot ~= nil
    end
    -- SPAWN-INIT source. This is what makes capture instant instead of
    -- "whenever you next heal or pick something up".
    --
    -- The other two handlers only fire on a hero ACTION, so with the native
    -- capture off a run could go a minute or more before anything was
    -- captured — measured at 73 seconds in one playtest, and the result was
    -- only [tentative] because it came from the heal path. This routine is the
    -- hero's own post-load init: it runs once, at spawn, before the hero acts,
    -- and it is hero-only (enemies have no HUD mirror), so its capture is
    -- authoritative.
    --
    -- Its param_1 is the HP-carrier, but the fields are NOT live yet — this
    -- function is what populates the HUD mirror the plausibility gate checks.
    -- So stash the identity and let the tick pump promote it the moment it
    -- reads plausible, exactly as the native path does with its pending slot.
    local sub_va = I.resolve and I.resolve("NamedEvent_HeroSubscribeAll")
    local ok0 = arm(sub_va, "vp", function(p1)
        if p1 and p1 ~= 0 then _hero_pending = p1 end
        return nil
    end)
    local ok1 = arm(gain_va, "vppp", function(p1) capture(p1, false); return nil end)
    local ok2 = arm(give_va, "vppp", function(_, p2) capture(p2, true); return nil end)
    ok1 = ok1 or ok0
    if not (ok1 or ok2) then
        local why = (gain_va or give_va)
            and "could not be hooked (another mod may own them, or the install failed)"
            or "unresolved for this game build"
        R.log("[rsmm.entity] hero-capture handlers " .. why
            .. "; R.combat/R.entity/R.stat/R.xp disabled this run, "
            .. "other mods unaffected")
    end
end

--- One-shot: find where the HP pair really lives on a rejected hero.
--
-- The 2026-08-13 playtest narrowed the failure precisely. The pending pointer
-- IS the hero (the spawn-init routine is hero-only), the HUD-mirror pointer at
-- +0x1d80 reads as a valid heap address — so the object and its size are what
-- we expect — and yet `hp`/`max` at +0x15c8/+0x15cc read 0.0 for 18+ seconds
-- of live play. Readable, plausible object, zero fields: that is a MOVED
-- FIELD, not a bad pointer, and no amount of waiting fixes it.
--
-- So sweep the object for the pair instead of hardcoding a guess: adjacent
-- f32s where the second is a sane bar size and the first sits inside it. The
-- hero's real HP pair must appear; anything else that matches is noise the
-- offsets and values let us reject by eye. All reads are page-guarded (bad
-- address -> nil, never a fault), and the whole thing runs once per PROCESS
-- via a shared latch, not once per mod.
-- Scan a given pointer at these rejection counts, not on the first one. The
-- fields fill DURING the load sequence, and the 19:56 log shows two different
-- pending heroes six seconds apart — the menu character, then the run's. A
-- true one-shot would have measured the wrong object while it was still blank
-- and latched. Ticks are ~500ms, so these are roughly 5s and 20s in.
-- One table, not four locals: the main chunk is at Lua's 200-local ceiling, so
-- every new top-level `local` here costs a "too many local variables" compile
-- failure of the whole SDK.
local HERO_SCAN = {
    -- Rejection counts that trigger a scan. Ticks are ~500ms, so 10/40 are
    -- roughly 5s and 20s after the candidate was stashed -- and session 914f
    -- (2026-08-18) showed that is entirely inside the LOAD: both scans fired
    -- before the hero existed in the map (the second one 5s after
    -- MAP_GENERATION_DONE), found nothing, and no scan ever ran while the hero
    -- was alive and taking damage. 200 and 800 are ~100s and ~400s in, which is
    -- mid-fight, and the process-wide budget of MAX still caps the total.
    AT   = { [10] = true, [40] = true, [200] = true, [800] = true },
    MAX  = 6,                        -- total scans per process, all mods
    LO   = 0x1000, HI = 0x2400,
    seen = {},                       -- pointer -> rejections observed here
}

--- True while the main menu is up (best-effort; false when unknowable).
--
-- There is no run hero on the menu, so a candidate the spawn-init hook stashed
-- there is the menu's preview character and its HP fields are blank BY DESIGN.
-- Polling it is harmless, but LOGGING it is not: the 2026-08-16 session spent
-- its entire process-wide budget -- all six field scans and 40+ rejection lines
-- -- sitting in menus, so the one measurement worth having ("still zero during
-- LIVE play => the offsets moved") could never be taken, and every scan
-- correctly reported "no candidate pair found" about an object that had none
-- yet. Rejections are only counted, and only printed, outside the menu.
--
-- The binding is IO-hook derived and answers false whenever it cannot tell
-- (loader still booting, IO hook off), so this degrades to the previous
-- always-log behaviour instead of going silent.
local function _in_main_menu()
    if not I.is_in_main_menu then return false end
    local ok, v = pcall(I.is_in_main_menu)
    return (ok and v) or false
end

--- Is it worth spending diagnostics on a hero candidate right now?
---
--- There is no hero to find in the main menu, so every rejection line and
--- field scan emitted there is noise that also burns a process-wide budget:
--- session 6c4f sat in the menu for eleven minutes, spent all six scans on a
--- blank object, and then reported the capture as taking 443.9s — a number
--- measured from a candidate that appeared while nobody was playing.
---
--- The run boundary is the right signal. `is_in_main_menu` is NOT: it is
--- derived from MainMenu asset READS, so it goes false about five seconds
--- after the menu finishes loading and stays false while you sit in it, which
--- is exactly the window this is meant to suppress.
---
--- Which is what session ba4f (2026-08-18) hit: the whole process sat in the
--- menu and the lobby looking for a team, no run boundary had EVER fired, so
--- the fallback ran — and the fallback answered "in play" five seconds in. The
--- entire process-wide budget (all six field scans, 40+ rejection lines) was
--- spent on the character-select preview hero, whose HP fields are blank by
--- design, before a run ever started. Same outcome as session 6c4f, re-entered
--- through the fallback the 6c4f fix installed.
---
--- Three sources now, strongest first:
---   1. the analytics run boundary (run_start / run_end) — exact, but it rides
---      the firehose and a session can legitimately not have it;
---   2. the gameplay bus (GAME_START / MAP_GENERATION_DONE vs GAME_END_*) —
---      the same question asked of a different hook, so a build missing one
---      usually still has the other. NOT routed into run:start/run:end, which
---      mods reset counters on: MAP_GENERATION_DONE fires per CHAPTER;
---   3. nothing at all — then SUPPRESS. Diagnostics whose budget is spent
---      before the measurement can be taken are worse than no diagnostics, and
---      the suppression says so once, in the log, with the reason.
function HERO_SCAN.in_play()
    local rr = R.run
    if rr and rr.signalled and rr.signalled() then
        return (rr.active and rr.active()) and true or false
    end
    if rr and rr._play_signalled then return rr._play_active == true end
    if not HERO_SCAN.quiet_logged then
        HERO_SCAN.quiet_logged = true
        R.log("[rsmm.entity] hero diagnostics suppressed: no run signal on this "
              .. "build (neither the analytics run boundary nor the gameplay "
              .. "bus has fired). They arm themselves the moment a run starts.")
    end
    return false
end

-- Internals, for the spec: `in_play` decides whether a whole class of
-- diagnostics runs, so its three states are worth testing directly.
R.entity._scan = HERO_SCAN

local function _scan_hp_fields(p)
    if not (I.shared_get and I.shared_set) then return end
    local n = (HERO_SCAN.seen[p] or 0) + 1
    HERO_SCAN.seen[p] = n
    if not HERO_SCAN.AT[n] then return end
    -- Process-wide budget: every mod has its own Lua state and all of them
    -- poll, so the cap has to live in the shared slot, not in this state.
    local oks, used = pcall(I.shared_get, HERO_SCAN_SLOT)
    used = (oks and type(used) == "number") and used or 0
    if used >= HERO_SCAN.MAX then return end
    pcall(I.shared_set, HERO_SCAN_SLOT, used + 1)

    local hits = {}
    for off = HERO_SCAN.LO, HERO_SCAN.HI, 4 do
        local cur = I.read_f32(p + off)
        local mx = I.read_f32(p + off + 4)
        if type(cur) == "number" and type(mx) == "number"
            and mx >= 20.0 and mx < 5000.0 and cur > 0.0 and cur <= mx then
            hits[#hits + 1] = string.format("+0x%x %.1f/%.1f", off, cur, mx)
            if #hits >= 12 then break end
        end
    end
    R.log(string.format(
        "[rsmm.entity] HP-FIELD SCAN #%d on 0x%x after %d rejections "
        .. "(expected +0x%x): %s",
        used + 1, p, n, ENTITY_HP_OFF,
        #hits > 0 and table.concat(hits, "  ") or "no candidate pair found"))
end

-- The captured local hero character pointer, or nil if not seen yet. The
-- loader's native capture publishes it to the shared slot at hero spawn (it
-- hooks the hero's spawn/post-load init, NamedEvent_HeroSubscribeAll, whose
-- param_1 is the HP-carrier) — so it's available almost immediately, no longer
-- gated on the hero's first heal/pickup. Read fresh every call so a hero-switch
-- (which clears the slot) is picked up automatically.
-- Rejection diagnostics are capped PER MOD STATE, and every installed mod has
-- its own state — so a 6-line cap became 6 x N identical lines (37 in one
-- measured session, all the same pointer and the same zero fields). The reason
-- to print them at all is "a rejection that persists into live play means the
-- offsets moved", which one state answers as well as seven. `HERO_DIAG_SLOT`
-- is a cross-state claim: the first state to log takes it, the rest stay quiet.
local _hero_diag_n = 0
local HERO_DIAG_SLOT = 6

--- True at most `limit` times across ALL mod states, not per state.
local function _diag_budget(limit)
    if _hero_diag_n >= limit then return false end   -- this state has had its say
    local ok, n = pcall(I.shared_get, HERO_DIAG_SLOT)
    n = (ok and type(n) == "number") and n or 0
    if n >= limit then return false end
    if I.shared_set then pcall(I.shared_set, HERO_DIAG_SLOT, n + 1) end
    _hero_diag_n = _hero_diag_n + 1
    return true
end
function R.entity.hero()
    if I.shared_get then
        local ok, h = pcall(I.shared_get, SHARED_HERO_SLOT)
        h = (ok and type(h) == "number") and h or 0

        -- HERO SWITCH: a spawn-init candidate that is BOTH different from the
        -- published hero and already plausible means the hero changed, and it
        -- has to win over the published one.
        --
        -- Without this the published slot shadows it completely: the check
        -- below returns early while `h` still reads plausible, so the pending
        -- branch is never reached and the new hero is invisible until the give
        -- path happens to notice its dispatcher changed. Measured 2026-08-13
        -- switching characters mid-run — the new hero sat pending for 95
        -- seconds with not one rejection logged, because the code never looked
        -- at it. (Freed memory keeps reading plausible for a long time, so
        -- "the old pointer still validates" is not evidence it is still the
        -- hero.) The first capture of a run is NOT this case: there the slot
        -- is empty and the wait is the hero's own fields going live.
        local okp, pend = pcall(I.shared_get, HERO_PENDING_SLOT)
        if okp and type(pend) == "number" and pend ~= 0 and pend ~= h
            and not R.entity._retired(pend) and _hero_plausible(pend) then
            if I.shared_set then
                pcall(I.shared_set, SHARED_HERO_SLOT, pend)
                pcall(I.shared_set, HERO_AUTH_SLOT, 1)
                pcall(I.shared_set, HERO_PENDING_SLOT, 0)
            end
            _log_capture("[rsmm.entity] hero CAPTURED 0x%x (was 0x%x)%s", pend, h,
                         _capture_latency())
            return pend
        end

        if h ~= 0 then
            if _hero_plausible(h) then return h end
            -- DIAG (first few only): the native capture published a pointer the
            -- Lua plausibility gate now rejects — log the raw reads so a
            -- playtest log shows WHY (stale/freed entity? moved offsets?).
            if HERO_SCAN.in_play() and _diag_budget(6) then
                R.log(string.format(
                    "[rsmm.entity] slot hero 0x%x REJECTED: hp=%s max=%s mirror=%s",
                    h, tostring(I.read_f32(h + ENTITY_HP_OFF)),
                    tostring(I.read_f32(h + ENTITY_MAXHP_OFF)),
                    tostring(I.read_u64(h + ENTITY_HUDMIRROR_OFF))))
            end
        end
        -- Pending spawn candidate: the native spawn-init hook stashes the hero
        -- identity BEFORE its HP/mirror fields are populated (they fill during
        -- the load sequence). Promote it to the real slot the first time it
        -- reads plausible — instant capture with no combat prerequisite.
        -- Every spawn-init candidate, not just the latest. The native side
        -- keeps them in a ring (slots 8..15) because a single slot meant each
        -- spawn-init discarded the previous candidate: measured 2026-08-14,
        -- five stashes collapsed to one whose HP fields never went live, so
        -- the pending path was dead for the entire run and capture fell back
        -- to waiting ~94s for a gain-health fire. They are all hero-identity
        -- (the routine is hero-only); they simply go live at different times,
        -- so promote whichever validates first.
        --
        -- TWO passes, local players first. The ring holds one candidate per HERO
        -- in a co-op run, not one per machine, so "first plausible entry wins"
        -- means "whichever ally the allocator happened to place in a lower ring
        -- slot wins" — and R.combat would then heal, damage and buff somebody
        -- else's character. The engine's is-local byte decides it when it is
        -- readable; when nothing claims to be local the old behaviour stands,
        -- so a build where that byte moved still captures.
        local fallback, fallback_slot = nil, nil
        for i = 0, HERO_RING_COUNT - 1 do
            local okr, cand = pcall(I.shared_get, HERO_RING_FIRST + i)
            if okr and type(cand) == "number" and cand ~= 0 then
                _note_hero_candidate()
            end
            if okr and type(cand) == "number" and cand ~= 0 and cand ~= h
                and not R.entity._retired(cand) and _hero_plausible(cand) then
                if R.entity._is_local(cand) then
                    fallback, fallback_slot = cand, i
                    break
                elseif not fallback then
                    fallback, fallback_slot = cand, i
                end
            end
        end
        if fallback then
            if I.shared_set then
                pcall(I.shared_set, SHARED_HERO_SLOT, fallback)
                pcall(I.shared_set, HERO_AUTH_SLOT, 1)
                pcall(I.shared_set, HERO_PENDING_SLOT, 0)
            end
            _log_capture("[rsmm.entity] hero CAPTURED 0x%x from ring slot %d "
                         .. "(local_byte=%s)%s",
                         fallback, fallback_slot,
                         tostring(I.read_u8(fallback + ENTITY_ISLOCAL_OFF)),
                         _capture_latency())
            return fallback
        end

        local okp, p = pcall(I.shared_get, HERO_PENDING_SLOT)
        if okp and type(p) == "number" and p ~= 0 and not R.entity._retired(p) then
            if _hero_plausible(p) then
                if I.shared_set then
                    pcall(I.shared_set, SHARED_HERO_SLOT, p)
                    pcall(I.shared_set, HERO_AUTH_SLOT, 1)
                    pcall(I.shared_set, HERO_PENDING_SLOT, 0)
                end
                _log_capture("[rsmm.entity] hero CAPTURED 0x%x from the pending slot%s",
                             p, _capture_latency())
                return p
            end
            -- DIAG (first few only). A rejection here is NORMAL for a while:
            -- the candidate is authoritative by construction (the spawn-init
            -- routine is hero-only) but its HP fields do not populate until
            -- the run actually starts, so every tick spent in character select
            -- logs one. Measured 2026-08-13: ~58s from first stash to
            -- promotion on a fresh run, with the field sweep below finding no
            -- HP pair anywhere on the object in the meantime — the fields are
            -- genuinely blank, not moved.
            --
            -- What it is still worth printing for: a rejection that persists
            -- INTO live play means the offsets really did move, and rejecting
            -- silently is how that failed invisibly before (every downstream
            -- API no-ops with nothing in the log to say why).
            --
            -- Both the line and the field sweep are MENU-GATED: a rejection in
            -- the menu carries no information (see `_in_main_menu`), and
            -- spending the shared scan budget there is what made the 2026-08-16
            -- log six scans of a blank preview character.
            if HERO_SCAN.in_play() then
                if _diag_budget(6) then
                    local mirror = I.read_u64(p + ENTITY_HUDMIRROR_OFF)
                    R.log(string.format(
                        "[rsmm.entity] pending hero 0x%x REJECTED: hp=%s max=%s "
                        .. "mirror=%s mirror[0]=%s",
                        p, tostring(I.read_f32(p + ENTITY_HP_OFF)),
                        tostring(I.read_f32(p + ENTITY_MAXHP_OFF)),
                        tostring(mirror),
                        tostring(mirror and mirror ~= 0 and I.read_f32(mirror) or nil)))
                end
                _scan_hp_fields(p)
            end
        end
    end
    -- Legacy fallback: an older loader without native capture, or the native
    -- capture switched off. Arm the per-state Lua hooks (safe only when native
    -- capture is NOT present — otherwise it would collide on the same
    -- addresses).
    if not _native_capture_active() then
        if not _hero_char then _arm_hero_capture() end
        -- Promote the spawn-init candidate as soon as its fields go live. The
        -- tick pump calls through here every 500ms, so this lands within one
        -- tick of the hero becoming readable rather than waiting for the first
        -- heal or pickup.
        if not _hero_char and _hero_pending and _hero_plausible(_hero_pending) then
            _hero_char = _hero_pending
            _hero_pending = nil
            if I.shared_set then pcall(I.shared_set, SHARED_HERO_SLOT, _hero_char) end
            R.log(string.format(
                "[rsmm.entity] hero captured @0x%x (hp %.0f/%.0f) [spawn-init]",
                _hero_char, I.read_f32(_hero_char + ENTITY_HP_OFF),
                I.read_f32(_hero_char + ENTITY_MAXHP_OFF)))
        end
        return _hero_char
    end
    return nil
end

-- True once the hero has been captured (hp/max/heal/damage will work).
function R.entity.ready() return R.entity.hero() ~= nil end

--- Is hero capture PERMITTED this session (RSMM_ENABLE_HERO_CAPTURE)?
--
-- Distinct from R.entity.ready(), which asks whether the hero has been
-- captured YET. A mod needs both to give useful advice: "not captured" during
-- loading or a menu is normal and resolves itself, while "not permitted" needs
-- the player to change a setting. A playtest with the flag correctly ON still
-- told the user to go and enable it, because the mods had no way to tell the
-- two apart — capture legitimately took ~3 minutes there, since the hero's HUD
-- mirror is not populated until the run is actually under way.
--
-- False ONLY on an explicit refusal; a loader too old to publish the answer
-- reports true, matching what it will actually do.
function R.entity.capture_enabled() return not _capture_denied() end

function R.entity.hp()
    local e = R.entity.hero(); if not e then return nil end
    return I.read_f32(e + ENTITY_HP_OFF)
end

function R.entity.max_hp()
    local e = R.entity.hero(); if not e then return nil end
    return I.read_f32(e + ENTITY_MAXHP_OFF)
end

function R.entity.hp_frac()
    local cur, mx = R.entity.hp(), R.entity.max_hp()
    if not cur or not mx or mx <= 0 then return nil end
    return cur / mx
end

-- Apply a raw health delta (delta>0 heals, delta<0 damages). Returns true on
-- dispatch, false if the hero isn't captured yet, the module base is
-- unavailable, or health reads implausible (guards against a bad pointer).
-- Can the engine safely traverse what Entity_ModifyHealth traverses?
--
-- Its first four instructions are
--   0x14039a361  mov r14, [rcx + 0x8]
--   0x14039a365  mov rbx, [r14 + 0x30]     <- +0x45, the faulting one
-- with no null or sentinel check of its own. A store slot holding the -1
-- sentinel therefore reads address 0x2f and takes the whole process down —
-- which is exactly what happened in session 8c4f, on a pointer that had
-- already satisfied _hero_plausible.
--
-- Both reads here are page-guarded, so probing costs nothing; the moment the
-- pointer becomes a call ARGUMENT the engine owns the deref, so this is the
-- last place it can be checked. Same reason Entity_GetNetId is banned from the
-- SDK (it walks the component map unguarded and dies on the same sentinel).
local function _modify_health_safe(e)
    local store = I.read_u64(e + ENTITY_STORE_OFF)
    if type(store) ~= "number" or store == 0
        or store == 0xffffffffffffffff or store == -1 then
        return false, "value store slot holds the -1 sentinel or null"
    end
    if not _ptr_plausible(store) then
        return false, "value store pointer is not a plausible address"
    end
    -- The engine reads this one next, unguarded. If it is not readable here it
    -- will not be readable a microsecond later inside the detour.
    if I.read_u64(store + ENTITY_STORE_HOP) == nil then
        return false, "value store is not readable at +0x30"
    end
    return true
end

local function _modify_health(delta)
    local e = R.entity.hero()
    if not e then
        R.log("[rsmm.combat] no hero yet — wait until the hero heals/regens or "
            .. "picks something up once (R.entity.ready())")
        return false
    end
    if not _hero_plausible(e) then
        R.log("[rsmm.combat] hero health reads implausible — refusing modify")
        return false
    end
    local ok_store, why = _modify_health_safe(e)
    if not ok_store then
        R.log(("[rsmm.combat] refusing modify on 0x%x: %s — Entity_ModifyHealth "
               .. "would fault reading it"):format(e, why))
        return false
    end
    if not _va_ok("R.combat") then return false end
    local base = I.module_base()
    if not base or base == 0 then return false end
    -- empty oCCustomFlagList ctx { vftable, list=0, count=0 } in scratch
    local ctx = I.scratch(0x20)
    I.poke(ctx + 0x00, base + (FLAGLIST_VFT_VA - ENTITY_IMG_BASE), 8)
    I.poke(ctx + 0x08, 0, 8)
    I.poke(ctx + 0x10, 0, 8)
    local fn = I.resolve and I.resolve("Entity_ModifyHealth")
    if not fn then
        R.log("[rsmm.combat] Entity_ModifyHealth unresolved for this game build "
            .. "— refusing modify (regenerate function_patterns.json)")
        return false
    end
    R.engine.call_raw(fn, "vpfp", e, delta + 0.0, ctx)
    return true
end

function R.combat.heal(amount)   return _modify_health(math.abs(amount or 0)) end
function R.combat.damage(amount) return _modify_health(-math.abs(amount or 0)) end

-- Set HP to an absolute value by applying the difference from current.
function R.combat.set_hp(value)
    local cur = R.entity.hp()
    if not cur then return false end
    return _modify_health((value or 0) - cur)
end

-- Wire the forward-declared invalidator now that _hero_char + the shared slot
-- exist. On hero switch / new run the captured HP-carrier is stale; drop it and
-- clear the process-global slot so the next heal/pickup re-captures cleanly.
_hero_capture_is_live = function()
    if not I.shared_get then return false end
    local ok, h = pcall(I.shared_get, SHARED_HERO_SLOT)
    return ok and type(h) == "number" and h ~= 0 and _hero_plausible(h)
end

_invalidate_hero_capture = function()
    _hero_char = nil
    if I.shared_set then
        pcall(I.shared_set, SHARED_HERO_SLOT, 0)  -- drop stale hero pointer
        pcall(I.shared_set, HERO_AUTH_SLOT, 0)    -- let native re-capture new hero
    end
end

-- entity values (generic CRC-keyed run/stat store) ----------------------
--
-- Each hero carries a generic keyed value store on its value context. The
-- context is a POINTER field: ctx = *(hero+0x2f8), and the store hangs off it
-- at *(ctx+0x4c8). The engine's own reader (FUN_140399d00, the damage-taken
-- handler) loads the pointer first — `ctx = *(hero+0x2f8)` — then calls
-- EntityValue_Get(ctx, out, crcKey). Passing hero+0x2f8 (the field's ADDRESS)
-- instead makes EntityValue_Get read *(hero+0x7c0) as the store — a float
-- field, not a pointer — and EntityValue_Lookup then faults dereferencing it
-- (the 2026-07-15 in-run crash: store=0xbf800000, i.e. -1.0f, read at +0xc8).
-- EntityValue_Get reads one key into a ~0x20-byte oCEntityValueUnion: type tag
-- @+0x8 (4 = inline f32), value @+0x10. A missing key yields value 0 (safe —
-- never faults). We only read INLINE numeric values (every modifier/difficulty
-- key is numeric); a non-inline (string/vector) key returns nil rather than
-- deref an unknown-typed pointer, so no union destructor is needed.
-- See docs/_re/kinds/entity-values.md and docs/_re/kinds/stats.md.
local ENTITY_VALCTX_OFF = 0x2f8   -- hero -> POINTER to entity value context
local EV_STORE_OFF      = 0x4c8   -- ctx -> POINTER to value store
local EV_TAG_OFF        = 0x08    -- oCEntityValueUnion type tag
local EV_VAL_OFF        = 0x10    -- inline f32 when tag == EV_TAG_INLINE
local EV_TAG_INLINE     = 4

-- Resolve the hero's value CONTEXT pointer, fail-closed. Validates the whole
-- chain the engine will dereference unguarded inside EntityValue_Get /
-- EntityValue_Lookup before we hand it a pointer:
--   ctx   = *(hero+0x2f8)  must be a plausible, readable pointer
--   store = *(ctx+0x4c8)   may be 0 (engine handles it) — but if non-zero it
--                          must be plausible AND its hot fields readable:
--                          count u32 @store+0xc8 (read unconditionally), the
--                          override array ptr @store+0xc0 (read when count>0)
--                          and the base hashmap ptr @store+0x80 (deref'd
--                          unconditionally on a cache miss).
-- Every probe is page-guarded (nil on unmapped), so validation cannot fault.
-- Returns ctx, or nil if any link is implausible.
local function _ev_ctx(hero)
    local ctx = I.read_u64(hero + ENTITY_VALCTX_OFF)
    if not ctx or not _ptr_plausible(ctx) then return nil end
    local store = I.read_u64(ctx + EV_STORE_OFF)
    if store == nil then return nil end                     -- ctx page unreadable
    if store ~= 0 then
        if not _ptr_plausible(store) then return nil end
        local count = I.read_u32(store + 0xc8)
        if count == nil or count > 0x10000 then return nil end
        if count > 0 then
            local data = I.read_u64(store + 0xc0)
            if not data or not _ptr_plausible(data) then return nil end
        end
        local hmap = I.read_u64(store + 0x80)
        if not hmap or not _ptr_plausible(hmap) then return nil end
    end
    return ctx
end

-- Read one entity-value by raw CRC key from the current hero's store.
-- Returns a Lua number (inline f32) or nil (no hero / missing / non-inline).
function R.entity.value(key)
    assert(type(key) == "number", "R.entity.value: key must be a number (CRC id)")
    local e = R.entity.hero(); if not e then return nil end
    local ctx = _ev_ctx(e); if not ctx then return nil end
    local out = I.scratch(0x20)               -- zeroed; tag starts at 0
    local ok = pcall(R.engine.call, "EntityValue_Get", ctx, out, key)
    if not ok then return nil end
    if I.read_u32(out + EV_TAG_OFF) ~= EV_TAG_INLINE then return nil end
    return I.read_f32(out + EV_VAL_OFF)
end

-- Values the rest of rsmm.lua still reads as plain locals. Adding one here
-- means adding it to the assignment block at the require site too — a name
-- that is exported and never picked up is silently nil at every use.
return {
    ENTITY_IMG_BASE          = ENTITY_IMG_BASE,
    SHARED_HERO_SLOT         = SHARED_HERO_SLOT,
    LOBBY_REFRESH_SLOT       = LOBBY_REFRESH_SLOT,
    ENTITY_VALCTX_OFF        = ENTITY_VALCTX_OFF,
    EV_STORE_OFF             = EV_STORE_OFF,
    _native_capture_active   = _native_capture_active,
    _hero_plausible          = _hero_plausible,
    _ev_ctx                  = _ev_ctx,
    _hero_capture_is_live    = _hero_capture_is_live,
    _invalidate_hero_capture = _invalidate_hero_capture,
}

end
