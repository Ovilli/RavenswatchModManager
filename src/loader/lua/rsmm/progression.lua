-- rsmm.progression — R.stat (the keyed entity-value store) and R.xp.
--
-- Split out of rsmm.lua on 2026-08-23, after damage and entity. TWO namespaces
-- in one file on purpose: R.xp reads `_stat_writes_enabled` and
-- `_log_throttled` straight out of the stat section, and they are the only two
-- values either section shares with anything. Split apart they would need an
-- export table and a getter (the write flag is toggled at runtime by
-- R.stat.enable_writes); kept together the module exports NOTHING, which is
-- the same clean contract rsmm/damage.lua has and the opposite of
-- rsmm/entity.lua's ten-value handback.
--
-- Everything the module needs from the parent is a constant or a function —
-- none of it is learned at runtime, so copying is safe here. (See
-- rsmm/damage.lua for the case where it is not: a value the parent assigns
-- later must arrive as a getter.)
--
-- Body below is verbatim from rsmm.lua.

return function(env)

for _, key in ipairs({ "native", "I", "R", "_va_ok", "_ptr_plausible",
                       "_in_image", "_obj_has_vtable", "_vector_valid",
                       "GIVE_IMG_BASE", "ENTITY_IMG_BASE", "ENTITY_VALCTX_OFF",
                       "EV_STORE_OFF", "_hero_plausible", "_ev_ctx" }) do
    if env[key] == nil then
        error("rsmm.progression: parent did not pass env." .. key, 0)
    end
end

local native, I, R      = env.native, env.I, env.R
local _va_ok            = env._va_ok
local _ptr_plausible    = env._ptr_plausible
local _in_image         = env._in_image
local _obj_has_vtable   = env._obj_has_vtable
local _vector_valid     = env._vector_valid
local GIVE_IMG_BASE     = env.GIVE_IMG_BASE
local ENTITY_IMG_BASE   = env.ENTITY_IMG_BASE
local ENTITY_VALCTX_OFF = env.ENTITY_VALCTX_OFF
local EV_STORE_OFF      = env.EV_STORE_OFF
local _hero_plausible   = env._hero_plausible
local _ev_ctx           = env._ev_ctx

-- stats (generic keyed value store — read/grant any per-hero stat) -------
--
-- Beyond HP (R.combat) and XP (R.xp), most hero stats — max health, attack
-- power, crit chance/damage, move speed, cooldown reduction, life steal,
-- dream shards, xp multipliers — live in the engine's generic CRC-keyed
-- entity-value store (the same store R.entity.value / R.modifier read). The
-- keys are decompile-verified from EntityValueRegistry_RegisterAll; full
-- catalog + provenance in docs/_re/kinds/stats.md.
--
--   R.stat.get("attack_power")     -- current value (number) or nil
--   R.stat.names()                 -- known stat names (sorted)
--   R.stat.enable_writes()         -- opt in to the EXPERIMENTAL write path
--   R.stat.set("move_speed", 1.5)  -- set a stat (see caveats)
--   R.stat.add("attack_power", 10) -- current + delta
--
-- READS are always safe. WRITES are EXPERIMENTAL + engine-mutating: run them
-- on the MAIN thread (from a gameplay-event handler or R.schedule.next_main —
-- see [[loader-thread-model]]) and opt in with R.stat.enable_writes() first.
-- DURABILITY: a write lands in the store's override cache, which the engine
-- rebuilds from base+modifiers on the next stat recompute (item pickup, level
-- up, ...), so a set() is not necessarily permanent. HP has its own committed
-- path (R.combat); prefer it for health. Pending in-game verification.
R.stat = {}

-- name -> { key = <crc id>, kind = "f32"|"int" }. Decompile-verified 2026-07-13
-- (agent RE batch; see docs/_re/kinds/stats.md for the full ~40-key table).
R.stat.keys = {
    max_health         = { key = 0x188671a6, kind = "f32" },  -- base "Vitality"
    max_health_pct     = { key = 0x15c9296d, kind = "f32" },  -- default 1.0
    attack_power       = { key = 0x15a486c4, kind = "f32" },
    crit_chance        = { key = 0x15c7d482, kind = "f32" },
    crit_damage        = { key = 0x15c82d13, kind = "f32" },
    move_speed         = { key = 0x044dadde, kind = "f32" },  -- "Move Speed Ratio"
    cooldown_reduction = { key = 0x15b45d80, kind = "f32" },
    life_steal         = { key = 0x15c028c2, kind = "f32" },
    life_on_hit        = { key = 0x1894f1a2, kind = "f32" },
    dream_shards       = { key = 0x171c27b5, kind = "int" },  -- currency count
    xp_multiplier      = { key = 0x187afd1d, kind = "f32" },  -- "Global Xp Modifier"
    difficulty_xp_mult = { key = 0x19bddb2e, kind = "f32" },
}

-- Ability slot order, as registered by EntityValueRegistry_RegisterAll.
R.stat.slots = { primary = 0, secondary = 1, defensive = 2, trait = 3, ultimate = 4 }

-- Per-slot stat families: the key is `base + 2*slot` (adjacent stats differ by
-- 2; see docs/_re/kinds/stats.md). These let a mod touch ONE ability's damage /
-- crit / cooldown instead of the hero-wide stat.
--
-- NOTE for attack_power: the hero-wide key (0x15a486c4) is NOT this family's
-- base -- the per-slot family starts at 0x15a5cf40. For crit_chance and
-- cooldown_reduction the family base IS the hero-wide key, so `*_primary`
-- resolves to the same key as the bare name; that mirrors the registry and is
-- not a bug.
local _slot_families = {
    attack_power       = 0x15a5cf40,
    crit_chance        = 0x15c7d482,
    cooldown_reduction = 0x15b45d80,
}
for family, base in pairs(_slot_families) do
    for slot_name, slot in pairs(R.stat.slots) do
        R.stat.keys[family .. "_" .. slot_name] = { key = base + 2 * slot, kind = "f32" }
    end
end

-- Off-family specials. `basic` sits +0x11 from the attack-power family base
-- (NOT a `+2*slot` member), and the dash keys live in a different range
-- entirely, so they are listed explicitly rather than derived.
R.stat.keys.attack_power_basic      = { key = 0x15a5cf51, kind = "f32" }
R.stat.keys.attack_power_dash       = { key = 0x183a609a, kind = "f32" }
R.stat.keys.crit_chance_dash        = { key = 0x183a60b6, kind = "f32" }
R.stat.keys.cooldown_reduction_dash = { key = 0x183a5fc9, kind = "f32" }

-- Status-effect family (FUN_1401d9070): `0x16ede056 + 2*i`, in registration
-- order. Stacks are ints.
local _status_family = {
    "strength", "regen", "haste", "concealed", "resistant",
    "rooted", "vulnerable", "ignite", "chilled", "poison",
}
for i, name in ipairs(_status_family) do
    R.stat.keys["status_" .. name] = { key = 0x16ede056 + 2 * (i - 1), kind = "int" }
end

-- Status effects registered outside that family.
R.stat.keys.status_shield = { key = 0x173fcd75, kind = "int" }
R.stat.keys.status_bleed  = { key = 0x173fcdac, kind = "int" }
R.stat.keys.status_cursed = { key = 0x1a5d3d69, kind = "int" }
R.stat.keys.status_marked = { key = 0x1a40367d, kind = "int" }

-- Resolve a family + slot to its key spec: R.stat.key("attack_power", "trait")
-- or R.stat.key("attack_power", 3). Returns nil for an unknown pair.
function R.stat.key(name, slot)
    if slot == nil then return R.stat.keys[name] end
    local slot_name = slot
    if type(slot) == "number" then
        slot_name = nil
        for n, i in pairs(R.stat.slots) do
            if i == slot then slot_name = n break end
        end
        if not slot_name then return nil end
    end
    return R.stat.keys[name .. "_" .. slot_name]
end

-- oCEntityValueUnion is a 0x20-byte tagged value. In the caller-provided read
-- buffer it starts at +0; inside a 0x38-byte override entry it starts at +0x08.
local EV_INLINE_OFF = 0x08   -- union: inline sentinel (== 4 => value is inline)
local EV_VALUE_OFF  = 0x10   -- union: inline value (f32 or int32)
local EV_TAG_OFF    = 0x18   -- union: type-tag byte (0 = int/float)
local EV_INLINE     = 4
local ENTRY_UNION_OFF = 0x08 -- override entry: embedded union offset
local ENTRY_KEY_OFF   = 0x00 -- override entry: u32 key
local OVR_DATA_OFF  = 0xc0   -- store -> override vector data ptr (vec base)
local OVR_COUNT_OFF = 0xc8   -- store -> override count (vec+8)
local OVR_STRIDE    = 0x38   -- override entry stride

-- The loader publishes the give handler's param_1 -- the hero's VALUE CONTEXT
-- -- to this slot. See kHeroValueCtxSlot in hook_events.cpp.
local HERO_VALUE_CTX_SLOT = 16

-- A context published by the give handler, IF it answers like a hero's.
--
-- Why a fallback exists at all: every stat write used to be gated on capturing
-- the hero ENTITY, and capture is the part that keeps failing -- sessions 4b4f
-- and a868 each played a full chapter while the spawn-init hook held one
-- candidate that never went live, so R.stat refused every write and steamroller
-- pinned nothing for two playtests running. But the store is
-- *(*(hero+0x2f8) + 0x4c8), and *(hero+0x2f8) is exactly what the give handler
-- receives as param_1. The entity is not on that path; only its context is.
--
-- The loader checks SHAPE (store pointer present and readable). It cannot check
-- MEANING, because the stat key table lives here -- and it must be checked: one
-- a868 run saw three distinct param_1 values, so "a readable store" is not
-- "the local hero's store". Asking the store for a stat every hero has, and
-- requiring a sane answer, is the check that distinguishes them.
-- Why the last attempt failed, so the caller's message can name the actual
-- cause instead of the ambiguous "no hero and no context".
local _ctx_why = "slot empty (the loader has not published one)"

local function _published_ctx()
    if not I.shared_get then
        _ctx_why = "this loader is too old to publish a value context"
        return nil
    end
    local ok, ctx = pcall(I.shared_get, HERO_VALUE_CTX_SLOT)
    if not (ok and type(ctx) == "number" and ctx ~= 0) then
        _ctx_why = "slot empty (the loader published nothing — see [hero-capture] value-ctx lines)"
        return nil
    end
    local s = I.read_u64(ctx + EV_STORE_OFF)
    if not s or s == 0 then
        _ctx_why = string.format("published ctx 0x%x has no store at +0x%x", ctx, EV_STORE_OFF)
        return nil
    end
    -- Semantic gate: a hero's store answers with a positive, finite max health.
    local out = I.scratch(0x20)
    local okc = pcall(R.engine.call, "EntityValue_Get", ctx, out,
                      R.stat.keys.max_health and R.stat.keys.max_health.key
                          or R.stat.keys.attack_power.key)
    if not okc then
        _ctx_why = string.format("ctx 0x%x: EntityValue_Get raised", ctx)
        return nil
    end
    if I.read_u32(out + EV_INLINE_OFF) ~= EV_INLINE then
        _ctx_why = string.format("ctx 0x%x: max_health did not come back inline", ctx)
        return nil
    end
    local v = I.read_f32(out + EV_VALUE_OFF)
    if type(v) ~= "number" or not (v > 0.0 and v < 1.0e6) then
        _ctx_why = string.format("ctx 0x%x: max_health reads %s, not a hero's store",
                                 ctx, tostring(v))
        return nil
    end
    _ctx_why = nil
    return ctx
end

-- Resolve the value-store pointer: *(ctx+0x4c8) where ctx = *(hero+0x2f8).
-- _ev_ctx (entity-values section above) has already validated the whole chain
-- — plausible ctx, plausible store, readable hot fields — so a non-nil ctx with
-- a non-zero store slot is usable as-is. Falls back to the published context
-- when no hero has been captured. Returns the store ptr or nil.
local function _stat_ctx(hero)
    local ctx = hero and _ev_ctx(hero) or nil
    if ctx then return ctx end
    return _published_ctx()
end

local function _stat_store(hero)
    local ctx = _stat_ctx(hero)
    if not ctx then return nil end
    local s = I.read_u64(ctx + EV_STORE_OFF)
    if not s or s == 0 then return nil end
    return s
end

-- Read one stat by its spec ({key,kind}) from the current hero. Always safe:
-- the engine call is made only with an _ev_ctx-validated context pointer.
local function _stat_read(spec)
    local ctx = _stat_ctx(R.entity.hero()); if not ctx then return nil end
    local out = I.scratch(0x20)                               -- zeroed union buffer
    local ok = pcall(R.engine.call, "EntityValue_Get", ctx, out, spec.key)
    if not ok then return nil end
    if I.read_u32(out + EV_INLINE_OFF) ~= EV_INLINE then return nil end
    if spec.kind == "int" then return I.read_u32(out + EV_VALUE_OFF) end
    return I.read_f32(out + EV_VALUE_OFF)
end

-- Current value of a named stat, or nil (unknown name / no hero / non-inline).
function R.stat.get(name)
    local spec = R.stat.keys[name]
    if not spec then R.log("[rsmm.stat] unknown stat: " .. tostring(name)); return nil end
    return _stat_read(spec)
end

-- The known stat names, sorted.
function R.stat.names()
    local t = {}
    for k in pairs(R.stat.keys) do t[#t + 1] = k end
    table.sort(t)
    return t
end

-- EXPERIMENTAL write opt-in (default off — writes mutate live engine state).
local _stat_writes_enabled = false
-- Opt in to the experimental stat write path. Returns TRUE, always: this is a
-- consent flag, not a capability probe, and whether a write lands depends on
-- the hero being captured later. It used to return nothing, which reads as a
-- probe at every call site — the shipped Bloodlust mod did
-- `local ok = R.stat.enable_writes()` at load, got nil, and disabled itself for
-- the whole session. Ask R.entity.ready() if you want to know whether a write
-- can land right now.
-- Throttled logging for messages emitted from PER-EVENT paths.
--
-- R.stat.modify / R.xp.grant are called from gameplay-event handlers, so their
-- refusal messages run at the rate the game fires events. A playtest with
-- Bloodlust installed and hero capture off logged "[rsmm.stat] no hero captured
-- yet" once every three kills, forever — a real condition, reported so often it
-- buried everything else in the file.
--
-- Logs the first occurrence immediately, then at most once per REPEAT_SECONDS,
-- carrying the number suppressed so the reader still sees it is ongoing.
local _log_seen = {}
local REPEAT_SECONDS = 30

local function _log_throttled(key, msg)
    local now = (I.now and I.now()) or os.time()
    local st = _log_seen[key]
    if st == nil then
        _log_seen[key] = { at = now, n = 0 }
        R.log(msg)
        return
    end
    st.n = st.n + 1
    if now - st.at < REPEAT_SECONDS then return end
    R.log(("%s (%d more since last report)"):format(msg, st.n))
    st.at, st.n = now, 0
end

function R.stat.enable_writes()
    _stat_writes_enabled = true
    return true
end

-- Find the override entry for `key` in the store (entry addr, or nil).
local function _stat_find_entry(store, key)
    local data  = I.read_u64(store + OVR_DATA_OFF)
    local count = I.read_u32(store + OVR_COUNT_OFF)
    if not data or data == 0 or not count then return nil end
    for i = 0, count - 1 do
        local entry = data + i * OVR_STRIDE
        if I.read_u32(entry + ENTRY_KEY_OFF) == key then return entry end
    end
    return nil
end

-- Write an inline numeric value into an override entry's embedded union. Uses
-- only page-guarded pokes (a bad address no-ops rather than faults).
local function _stat_write_union(entry, spec, value)
    local u = entry + ENTRY_UNION_OFF
    I.write_u64(u + EV_INLINE_OFF, EV_INLINE)                 -- mark inline
    if spec.kind == "int" then
        I.write_u32(u + EV_VALUE_OFF, math.floor((value or 0) + 0.5))
    else
        I.write_f32(u + EV_VALUE_OFF, (value or 0) + 0.0)
    end
    I.write_u8(u + EV_TAG_OFF, 0)                             -- type tag: int/float
end

-- Set a named stat. EXPERIMENTAL, engine-mutating, MAIN-THREAD ONLY. Finds the
-- hero's override entry for the key (creating one via the engine allocator on a
-- miss) and writes the value into its union. Returns true on write. Fails
-- closed (logs, no-op) if writes aren't enabled, the hero/store is implausible,
-- or a symbol is unresolved.
function R.stat.set(name, value)
    local spec = R.stat.keys[name]
    if not spec then R.log("[rsmm.stat] unknown stat: " .. tostring(name)); return false end
    if not _stat_writes_enabled then
        R.log("[rsmm.stat] writes are experimental and off — call R.stat.enable_writes() first")
        return false
    end
    if not _va_ok("R.stat") then return false end
    -- A captured hero is preferred but not required: the store hangs off the
    -- hero's value CONTEXT, and the give handler publishes that directly. When
    -- the entity never validates (which is the common failure) the context is
    -- still good, and refusing on the entity alone is what left R.stat dead for
    -- two full playtests. A hero that IS captured must still read plausible —
    -- a live-but-wrong entity is a different problem from no entity at all.
    local e = R.entity.hero()
    if e and not _hero_plausible(e) then
        R.log("[rsmm.stat] hero reads implausible — refusing"); return false
    end
    local store = _stat_store(e)
    if not store then
        _log_throttled("stat.nostore",
            "[rsmm.stat] no value store: no hero captured, and the value context "
            .. "is unusable — " .. tostring(_ctx_why))
        return false
    end
    local entry = _stat_find_entry(store, spec.key)
    if not entry then
        -- Miss: grow the override vector via the engine allocator, init the slot.
        local count = I.read_u32(store + OVR_COUNT_OFF) or 0
        local ok, slot = pcall(R.engine.call, "EntityValueOverride_Alloc", store + OVR_DATA_OFF, count, 1)
        if not ok or not slot or slot == 0 then R.log("[rsmm.stat] override alloc failed"); return false end
        I.write_u32(slot + ENTRY_KEY_OFF, spec.key)
        pcall(R.engine.call, "EntityValueUnion_DefaultCtor", slot + ENTRY_UNION_OFF)
        I.write_u32(slot + 0x28, 0); I.write_u16(slot + 0x2c, 0); I.write_u64(slot + 0x30, 0)
        entry = slot
    end
    _stat_write_union(entry, spec, value)
    R.log(string.format("[rsmm.stat] set %s = %s (override cache — TRANSIENT; use R.stat.stick to keep it)",
        name, tostring(value)))
    return true
end

-- current + delta (reads then sets). EXPERIMENTAL (see R.stat.set).
function R.stat.add(name, delta)
    local cur = R.stat.get(name); if not cur then return false end
    return R.stat.set(name, cur + (delta or 0))
end

-- native engine modifier (composes with the game's own math) -------------
--
-- R.stat.modify(name, amount [, duration]) inserts a REAL engine modifier for
-- the stat's key: it builds an oCGameEventNetworkModifier (layout decompile-
-- verified from FUN_1403c7560's inline construction + ModifierEvent_Ctor
-- FUN_140389fb0) and calls EntityValueStore_ApplyModifierEvent(store, ev, 0, 0)
-- directly. Unlike R.stat.set (cache poke, wiped by recompute) and R.stat.stick
-- (re-assertion, pins the FINAL value), a modifier lives in the store's
-- modifier registry (store+0x88) and is folded together with the game's own
-- item/talent modifiers on every recompute — it COMPOSES and SURVIVES.
--
-- Event layout (0x98 bytes):
--   +0x00 vftable (oCGameEventNetworkModifier)  +0x08 state u32 (0 = ready)
--   +0x20 name oCString {ptr,cap|0x80000000,len} +0x30 name hash (bus only —
--   unused on the direct call)                   +0x38 modifier id (-1 = fresh)
--   +0x50 serial u32   +0x54 stat CRC key u32    +0x58 counter u32
--   +0x60 oCEntityValueUnion (0x20B) carrying the AMOUNT (engine-ctor'd)
--   +0x80 duration f32 (<0 = permanent; give-handler uses 5.0 for its 5s buff)
--   +0x84/+0x88 multipliers f32 (1.0)            +0x8c flag u8 (1)
--   +0x90 source entity (0 = no lifetime binding)
--
-- How the amount folds (add/mul/replace) is DATA-DRIVEN per key: the value
-- def in the store's base map picks the typed modifier (def+0x74) and the
-- merge op (def+0x70: 1=add-stack 2=set 3=match-replace 4=min-remaining) and
-- caps the count (def+0x68). We can't choose the op — the engine applies its
-- native semantics for that stat, which is exactly what "compose correctly"
-- means. In co-op non-authority the engine relays the event to the host
-- instead of applying locally (its own code path, not ours).
--
-- EXPERIMENTAL + engine-mutating: MAIN THREAD only, R.stat.enable_writes()
-- required, fail-closed on any unresolved symbol / implausible pointer.
-- Pending in-game verification. Don't combine with R.stat.stick on the same
-- stat (stick pins the final value and would fight the modifier).
local MODIFIER_EVENT_VFT_VA = 0x140f322d0  -- oCGameEventNetworkModifier_vftable (symbol map)
local _mod_serial = 0

function R.stat.modify(name, amount, duration)
    local spec = R.stat.keys[name]
    if not spec then R.log("[rsmm.stat] unknown stat: " .. tostring(name)); return false end
    if type(amount) ~= "number" then
        R.log("[rsmm.stat] modify: amount must be a number"); return false
    end
    if not _stat_writes_enabled then
        R.log("[rsmm.stat] writes are experimental and off — call R.stat.enable_writes() first")
        return false
    end
    if not _va_ok("R.stat.modify") then return false end
    local e = R.entity.hero()
    if e and not _hero_plausible(e) then
        R.log("[rsmm.stat] hero reads implausible — refusing"); return false
    end
    local store = _stat_store(e)
    if not store then
        _log_throttled("stat.nostore",
            "[rsmm.stat] no value store: no hero captured, and the value context "
            .. "is unusable — " .. tostring(_ctx_why))
        return false
    end

    -- Rebase the vftable va and sanity-probe it: slot 0 must hold a pointer
    -- into the game module (a wrong build / stale va reads as garbage and we
    -- refuse rather than hand the engine a fake object with a bad vtable).
    local base = I.module_base()
    if not base or base == 0 then return false end
    local vft = base + (MODIFIER_EVENT_VFT_VA - GIVE_IMG_BASE)
    local slot0 = I.read_u64(vft)
    if not slot0 or slot0 < base or slot0 >= base + 0x1600000 then
        R.log("[rsmm.stat] modifier-event vftable implausible on this build — refusing")
        return false
    end

    -- ONE scratch alloc for event + trailing ""-buffer. NEVER take a second
    -- scratch while the first is live: the native arena may hand back an
    -- overlapping block and zero its front — a second call here wiped the
    -- event's vftable and crashed the engine's virtual fill with a null
    -- vtable (2026-07-16, minidumps 25815b01/0425b5d9: READ @0x20 at
    -- ModifierEvent_Ctor+0xb9).
    local ev = I.scratch(0xb0)                     -- 0x98 event + 0x10 name tail
    local empty = ev + 0xa0                        -- zeroed tail doubles as ""
    I.write_u64(ev + 0x00, vft)
    I.write_u32(ev + 0x08, 0)                      -- state: ready
    I.write_u64(ev + 0x20, empty)                  -- name: empty, UNOWNED
    I.write_u32(ev + 0x28, 0x80000000)             -- (cap flag = engine won't free)
    I.write_u32(ev + 0x2c, 0)
    I.write_u32(ev + 0x30, 0)                      -- name hash: direct call, unused
    I.write_u64(ev + 0x38, 0xffffffffffffffff)     -- modifier id: fresh
    I.write_u32(ev + 0x40, 0)
    I.write_u64(ev + 0x48, 0xffffffffffffffff)
    _mod_serial = _mod_serial + 1
    I.write_u32(ev + 0x50, _mod_serial)
    I.write_u32(ev + 0x54, spec.key)
    I.write_u32(ev + 0x58, 0)
    -- The amount rides in the embedded union at +0x60. Construct it through
    -- the engine's own ctors (exactly the sequence the give-handler and
    -- ApplyModifierEvent use for their locals: default-ctor, destruct,
    -- re-init as numeric type 0) — then write the inline value.
    local u = ev + 0x60
    local okc, uret = pcall(R.engine.call, "EntityValueUnion_DefaultCtor", u)
    if not okc or not uret then
        R.log("[rsmm.stat] union ctor unresolved — refusing"); return false
    end
    pcall(R.engine.call, "EntityValueUnion_Destruct", u)
    pcall(R.engine.call, "EntityValueUnion_InitAsType", u, 0)
    if spec.kind == "int" then
        I.write_u32(u + 0x10, math.floor(amount + 0.5))
    else
        I.write_f32(u + 0x10, amount + 0.0)
    end
    I.write_f32(ev + 0x80, duration or -1.0)       -- default: permanent
    I.write_f32(ev + 0x84, 1.0)
    I.write_f32(ev + 0x88, 1.0)
    I.write_u8(ev + 0x8c, 1)
    I.write_u64(ev + 0x90, 0)                      -- no entity-lifetime binding
    -- Resolve BEFORE calling: ApplyModifierEvent returns void, so a nil from
    -- R.engine.call can't distinguish success from an unresolved symbol.
    if not R.engine.resolve("EntityValueStore_ApplyModifierEvent") then
        R.log("[rsmm.stat] ApplyModifierEvent unresolved on this build — refusing"); return false
    end
    local ok = pcall(R.engine.call, "EntityValueStore_ApplyModifierEvent", store, ev, 0, 0)
    if not ok then
        R.log("[rsmm.stat] ApplyModifierEvent raised — modifier NOT applied"); return false
    end
    R.log(string.format("[rsmm.stat] modify %s %+g (native modifier, %s)", name, amount,
        (duration and duration >= 0) and (tostring(duration) .. "s") or "permanent"))
    return true
end

-- durable stats (sticky re-assertion) -----------------------------------
--
-- R.stat.set writes the override CACHE, which EntityValueStore_Recompute
-- (FUN_140749a90) rebuilds from base + engine modifiers whenever the key goes
-- dirty (item pickup, level-up, ...). So a bare set is TRANSIENT. R.stat.stick
-- makes a value DURABLE by re-asserting it on the main-thread gameplay pump:
-- once a recompute clobbers the key, the next gameplay event re-applies it. The
-- re-assert is DRIFT-GATED — it only re-pokes when the live value has actually
-- moved off the target — so steady-state cost is one page-guarded read per
-- pinned stat per gameplay event and zero writes.
--
-- This is re-assertion over the existing (gated) poke, NOT a native engine
-- modifier: it pins the FINAL value and does not compose with the game's own
-- modifier math. For "set attack to X and keep it" that is exactly right. A true
-- additive modifier that composes with item/talent modifiers needs the
-- oCGameEventNetworkModifier dispatch path (symbols EntityValueStore_ApplyModifierEvent
-- / ModifierEvent_Ctor) whose event payload is not yet decoded — see
-- docs/_re/kinds/stats.md.
--
--   R.stat.stick("attack_power", 500)   -- set + keep it there
--   R.stat.unstick("attack_power")      -- stop pinning (engine restores base)
--   R.stat.sticky()                     -- table of currently-pinned {name=value}
local _stat_sticky = {}
local _stat_reassert_installed = false
local _STAT_DRIFT = 1e-4

-- Re-apply every pinned stat whose live value has drifted. Runs on the main
-- thread (called only from the gameplay-bus handler installed below).
local function _stat_reassert()
    if not _stat_writes_enabled then return end
    -- Re-assert whenever a store is reachable, by hero or by published context.
    if not _stat_store(R.entity.hero()) then return end
    for name, value in pairs(_stat_sticky) do
        local cur = R.stat.get(name)
        if cur == nil or math.abs(cur - value) > _STAT_DRIFT then
            R.stat.set(name, value)
        end
    end
end

-- Subscribe the re-assert to the gameplay bus once. The gameplay-bus wildcard
-- runs on the game's MAIN thread (same pump as the schedule main tick below);
-- gating on ev.source == "gameplay" keeps engine-mutating writes off the loader
-- background thread ("tick"/"ready"), per [[loader-thread-model]].
local function _stat_install_reassert()
    if _stat_reassert_installed then return end
    _stat_reassert_installed = true
    R.on("*", function(ev)
        if ev and ev.source == "gameplay" then _stat_reassert() end
    end)
end

-- Pin a stat to `value` durably. Applies immediately through R.stat.set (so all
-- its gates apply: enable_writes, main-thread, hero/store plausibility) and
-- re-asserts after every recompute. Returns the immediate-apply result.
function R.stat.stick(name, value)
    local spec = R.stat.keys[name]
    if not spec then R.log("[rsmm.stat] unknown stat: " .. tostring(name)); return false end
    _stat_sticky[name] = value
    _stat_install_reassert()
    return R.stat.set(name, value)
end

-- Stop pinning a stat. The engine's next recompute restores its computed value.
-- Returns true if it was pinned.
function R.stat.unstick(name)
    local had = _stat_sticky[name] ~= nil
    _stat_sticky[name] = nil
    return had
end

-- Shallow copy of the currently-pinned {name = value} table.
function R.stat.sticky()
    local t = {}
    for k, v in pairs(_stat_sticky) do t[k] = v end
    return t
end

-- experience (level / xp grant) -----------------------------------------
--
-- XP lives on its own hero component (the XpComponent), not the value store.
-- R.xp reads level/xp and (EXPERIMENTAL) grants XP through the engine's own
-- gain-experience routine, which runs the level-up loop and fires _XP_LEVEL_UP.
-- Grant is engine-mutating: MAIN THREAD + R.stat.enable_writes() opt-in.
--
--   R.xp.level() / R.xp.xp()   -- current level / xp-within-level, or nil
--   R.xp.grant(100)            -- add XP (levels up as needed)
R.xp = {}

-- CORRECTED 2026-07-18: was 0x140f23200, which is not a vtable at all -- it
-- lands 0x50 inside this one (slot 10 of 30), so `*(comp) == VA` could never
-- match and R.xp returned nil on every build. Real class is
-- oCDtEntityCpntGroupLevel. Keep in sync with symbols.json XpComponent_vftable
-- -- this literal mirrors the symbol map by hand.
local XP_VFTABLE_VA      = 0x140f231b0  -- oCDtEntityCpntGroupLevel::vftable
local XP_TESTER_VA       = 0x141476e00  -- XpComponent_TypeTester (data global)
local XP_ARR_OFF         = 0x190        -- entity -> component ptr array
local XP_ARR_COUNT_OFF   = 0x198        -- entity -> component count
local XP_OWNER_OFF       = 0x08         -- component -> owner entity (back-ptr)
local XP_PROGRESS_OFF    = 0x108        -- xpComp -> {level u32 @+0, xp u32 @+4}
local XP_GAIN_AMOUNT_OFF = 0x50         -- xpGain struct -> amount (int)

local _xp_cache_hero, _xp_cache_comp = nil, nil
local _xp_diag_done = false

-- Candidate component-array owners. The two direct candidates —
-- *(hero+0x2f8) and the captured object itself — both had EMPTY component
-- arrays in the 2026-07-17 playtest (diag: arr=0 count=0), so the
-- component-owning oCEntity hangs off some OTHER field of the captured
-- controller. Probe every pointer-sized field of the hero and of the value
-- ctx for an object with a plausible component array @+0x190/+0x198
-- (Entity_GetComponentByTester's walk, decompile-reconfirmed 2026-07-17).
-- Pure page-guarded reads, cached per hero — tick-thread safe.
-- An owner is accepted ONLY if its ENTIRE component array validates: every
-- entry is a plausible pointer whose vftable lies inside the game image and
-- whose owner back-ptr points back at the entity. This is the gate that
-- makes it safe to hand the entity to engine code later — the 2026-07-17
-- crash (null deref at Entity_GetComponentByTester+0x36) was the engine
-- walking a false-positive "array" the loose probe had accepted.
local function _xp_owner_valid(entity, _mbase)
    return _vector_valid(entity, XP_ARR_OFF, XP_ARR_COUNT_OFF, {
        min = 1, max = 0x100,
        check_entry = function(comp, owner)
            -- component: vtable in image AND owner back-ptr matches the entity.
            return _obj_has_vtable(comp) and I.read_u64(comp + XP_OWNER_OFF) == owner
        end,
    })
end

local _xp_owners_hero, _xp_owners = nil, nil
local function _xp_entities(hero)
    if hero == _xp_owners_hero and _xp_owners then return _xp_owners end
    local mbase = I.module_base(); if not mbase or mbase == 0 then return {} end
    local owners, seen = {}, {}
    local function consider(P)
        if not P or P == 0 or seen[P] or not _ptr_plausible(P) then return end
        seen[P] = true
        if _xp_owner_valid(P, mbase) then owners[#owners + 1] = P end
    end
    local ctx = I.read_u64(hero + ENTITY_VALCTX_OFF)
    consider(ctx); consider(hero)
    for _, base in ipairs({ hero, ctx }) do
        if base and base ~= 0 and _ptr_plausible(base) then
            for off = 0, 0x7f8, 8 do
                consider(I.read_u64(base + off))
            end
        end
    end
    _xp_owners_hero, _xp_owners = hero, owners
    return owners
end

-- Engine-call-free XP detection: the XpComponent is recognizable by shape —
-- +0x108 points at a {level u32, xp u32} block with sane values and +0x10
-- holds the curve object pointer. Accepted only when exactly ONE component
-- across all validated owners matches (ambiguity falls through to the
-- engine-tester path rather than risking a grant on the wrong component).
local function _xp_heuristic(hero, mbase)
    local hit, hits = nil, 0
    for _, entity in ipairs(_xp_entities(hero)) do
        local arr = I.read_u64(entity + XP_ARR_OFF)
        local n   = I.read_u32(entity + XP_ARR_COUNT_OFF)
        for i = 0, n - 1 do
            local comp = I.read_u64(arr + i * 8)
            local prog = I.read_u64(comp + XP_PROGRESS_OFF)
            if prog and prog ~= 0 and _ptr_plausible(prog)
               and _ptr_plausible(I.read_u64(comp + 0x10)) then
                local lvl = I.read_u32(prog)
                local xpv = I.read_u32(prog + 4)
                if lvl and xpv and lvl >= 1 and lvl <= 200 and xpv < 10000000 then
                    hits = hits + 1
                    hit = comp
                end
            end
        end
    end
    if hits == 1 then
        local vft = I.read_u64(hit)
        R.log(string.format(
            "[rsmm.xp] heuristic found XpComponent 0x%x (vft 0x%x; map expects 0x%x)",
            hit, vft and (vft - mbase + ENTITY_IMG_BASE) or 0, XP_VFTABLE_VA))
        return hit
    end
    if hits > 1 then
        R.log(string.format("[rsmm.xp] heuristic ambiguous (%d progress-shaped components) — deferring to engine tester", hits))
    end
    return nil
end

-- Pure-memory fallback: scan the component array for the exact XpComponent
-- vftable. Misses if the live component is a SUBCLASS (different vftable) —
-- the suspected cause of the 2026-07-16 "XP component not found". Kept as the
-- thread-safe read path; each hit validated by the owner back-ptr.
local function _xp_scan(hero)
    local base = I.module_base(); if not base or base == 0 then return nil end
    local want = base + (XP_VFTABLE_VA - ENTITY_IMG_BASE)
    for _, entity in ipairs(_xp_entities(hero)) do
        if entity and entity ~= 0 then
            local arr   = I.read_u64(entity + XP_ARR_OFF)
            local count = I.read_u32(entity + XP_ARR_COUNT_OFF)
            if arr and arr ~= 0 and count and count <= 0x400 then
                for i = 0, count - 1 do
                    local comp = I.read_u64(arr + i * 8)
                    if comp and comp ~= 0 and I.read_u64(comp) == want
                       and I.read_u64(comp + XP_OWNER_OFF) == entity then
                        return comp
                    end
                end
            end
        end
    end
    return nil
end

-- One-shot diagnostic when everything misses: log each candidate's component
-- count and the rebased vftables of its first few components, so the real
-- XpComponent vftable can be identified from the log without a debugger.
local function _xp_diag(hero)
    if _xp_diag_done then return end
    _xp_diag_done = true
    local base = I.module_base(); if not base or base == 0 then return end
    local owners = _xp_entities(hero)
    R.log(string.format("[rsmm.xp] diag: %d component-array owner(s) probed from hero 0x%x",
        #owners, hero))
    for ci = 1, math.min(#owners, 8) do
        local entity = owners[ci]
        local arr   = I.read_u64(entity + XP_ARR_OFF)
        local count = I.read_u32(entity + XP_ARR_COUNT_OFF)
        -- The candidate's OWN class matters as much as its components: the
        -- 2026-07-18 runs showed the probed owners are plain oCEntity, and the
        -- target is absent from all of them.
        local ovft = I.read_u64(entity)
        R.log(string.format("[rsmm.xp] diag cand%d entity=0x%x arr=0x%x count=%s entity_vft=%s",
            ci, entity, arr or 0, tostring(count),
            (ovft and ovft > base) and string.format("0x%x", ovft - base + ENTITY_IMG_BASE)
                or "?"))
        -- Scan EVERY component and report a verdict rather than dumping a
        -- prefix: a 12-entry cap hid the answer for five playtests.
        if arr and arr ~= 0 and count and count <= 0x400 then
            local found = nil
            for i = 0, count - 1 do
                local comp = I.read_u64(arr + i * 8)
                local vft  = comp and comp ~= 0 and I.read_u64(comp) or nil
                if vft and vft - base + ENTITY_IMG_BASE == XP_VFTABLE_VA then
                    found = i; break
                end
            end
            R.log(string.format("[rsmm.xp] diag cand%d target 0x%x: %s",
                ci, XP_VFTABLE_VA,
                found and ("FOUND at index " .. found) or "absent from all " ..
                    tostring(count) .. " components"))
            for i = 0, math.min(count, 64) - 1 do
                local comp = I.read_u64(arr + i * 8)
                local vft  = comp and comp ~= 0 and I.read_u64(comp) or nil
                if vft and vft > base then
                    R.log(string.format("[rsmm.xp] diag cand%d comp[%d]=0x%x vft=0x%x",
                        ci, i, comp, vft - base + ENTITY_IMG_BASE))
                end
            end
        end
    end
end

-- ---------------------------------------------------------------------------
-- Constructor capture — the component is NOT on the hero.
--
-- Five playtests scanned the hero's component array and found nothing; the
-- 2026-07-19 run settled it with a full scan (absent from all 227 components
-- of all 3 probed owners, every owner a genuine oCEntity). The reason is
-- structural: exactly one oCDtEntityCpntGroupLevel is authored in the whole
-- corpus, on EntitySettings/Common_Settings/Group_Scaling.entity.ot — the
-- party-wide scaling entity. No amount of walking the hero can reach it.
--
-- So stop searching and let the engine hand it over: detour its constructor
-- and keep `this`.
--
-- The ctor can run MORE THAN ONCE, and not every instance is the live one:
-- session 5f36 captured an instance whose curve config was empty (max_level
-- clamps to 1, xp_for_level=0xffffffff) and whose level/xp never moved while
-- the party demonstrably gained XP — a template/menu construction, not the
-- run's tracker. So keep the last few constructed pointers and, at read
-- time, prefer the one with a USABLE curve; an instance may also gain its
-- config after construction (settings deserialize post-ctor), so the choice
-- is re-evaluated whenever the current pick has no curve.
local _gl_seen, _gl_comp = {}, nil
local _gl_armed = false
local GL_SEEN_MAX = 8

--- Pure-memory (tick-thread-safe) probe: does this component have a level
-- curve the engine would actually honor? Mirrors what XpForLevel/GetMaxLevel
-- read: curve table at *(comp+0x10)+0x1d8 (enable flag +0x1d0, count +0x1e0)
-- or the "Max Hero Level" signal object at comp+0x70.
local function _gl_curve_usable(p)
    local cfg = I.read_u64(p + 0x10)
    if cfg and cfg ~= 0 and _ptr_plausible(cfg) then
        local flag  = I.read_u8(cfg + 0x1d0)
        local count = I.read_u32(cfg + 0x1e0)
        if flag and flag ~= 0 and count and count > 0 and count < 0x1000 then
            return true
        end
    end
    local sig = I.read_u64(p + 0x70)
    return sig ~= nil and sig ~= 0 and _ptr_plausible(sig)
end

--- True if `p` looks like a fully-constructed GroupLevel component.
-- Checked lazily rather than at hook time: the hook callback runs BEFORE the
-- original, so at capture the object is raw memory with no vftable yet (the
-- same reason hero capture stashes "pending" and promotes on first valid
-- read). Every read here is page-guarded, so a bad pointer yields nil.
local function _gl_valid(p)
    if not p or p == 0 or not _ptr_plausible(p) then return false end
    local base = I.module_base()
    if not base or base == 0 then return false end
    if I.read_u64(p) ~= base + (XP_VFTABLE_VA - ENTITY_IMG_BASE) then return false end
    -- +0x108 is the {level u32, xp u32} progress pointer (the destructor just
    -- below the ctor releases exactly this field, which is how it was pinned).
    local prog = I.read_u64(p + XP_PROGRESS_OFF)
    if not prog or prog == 0 or not _ptr_plausible(prog) then return false end
    local lvl = I.read_u32(prog)
    return lvl ~= nil and lvl >= 1 and lvl <= 200
end

-- MUST be armed before the run starts, unlike every other hook here.
--
-- First playtest (session 974f) proved it: the hook resolved and installed
-- correctly on the right function, but lazily — on the first R.xp read, which
-- the demo does about a minute into a run:
--
--   11:43:03  StatGrantDemo init OK
--   11:43:17  hero spawn-init            <- Group_Scaling built around here
--   11:44:18  [hook] slot 0 installed    <- 61s too late; ctor already ran
--
-- The component is constructed once, at run start. A hook installed after
-- that never fires, so capture is not "flaky", it is guaranteed to miss.
-- `setup` (all mods' init.lua ran) is the earliest lifecycle point that is
-- still safely after module load — arming at module load would let a failure
-- abort require"rsmm" for every mod, which is why the other hooks are lazy.
local function _arm_group_level_capture()
    if _gl_armed then return end
    if not R.hook or not I.resolve then return end
    _gl_armed = true
    -- nil when the symbol is unverified for this build — fail closed rather
    -- than hooking a stale VA (a mid-function detour corrupts the stream).
    local va = I.resolve("GroupLevelComponent_Ctor")
    if not va or va == 0 then
        R.log("[rsmm.xp] GroupLevelComponent_Ctor unresolved for this build; "
            .. "level/xp unavailable this run")
        return
    end
    -- Signature is `void*(void* self)`: return + one pointer arg, no floats.
    --
    -- The callback could instead call the supplied `next(self)` to run the
    -- ctor and validate immediately. Deliberately NOT done: if anything in
    -- this callback then raised, the loader's error path replays the
    -- trampoline itself, so the CONSTRUCTOR would run twice on the same
    -- object — double-initialising it and leaking whatever the first pass
    -- allocated. Stashing and returning nil keeps the original running
    -- exactly once, at the cost of validating on the next read instead.
    local ok, slot, why = pcall(R.hook, va, "pp", function(self)
        -- Stash only. Returning nil replays the original, which is what
        -- actually writes the vftable and allocates the progress block.
        -- Newest first; dedupe; bounded (the ctor may run per menu/run).
        if self and self ~= 0 then
            for i = #_gl_seen, 1, -1 do
                if _gl_seen[i] == self then table.remove(_gl_seen, i) end
            end
            table.insert(_gl_seen, 1, self)
            for i = #_gl_seen, GL_SEEN_MAX + 1, -1 do table.remove(_gl_seen, i) end
        end
        return nil
    end)
    -- (nil, "already-hooked") means another mod's state armed the same ctor
    -- hook first. The hook is live and its captures land in this state too, so
    -- that is a success — reporting it as "level/xp unavailable" once per extra
    -- mod is how a working four-mod install came to look like three broken ones.
    if ok and slot == nil and why == "already-hooked" then return end
    if not ok or slot == nil then
        R.log("[rsmm.xp] could not install GroupLevelComponent_Ctor hook; "
            .. "level/xp unavailable this run")
    end
end

--- The live party-wide level/XP component, or nil.
-- Selection order: (1) a valid captured instance WITH a usable curve — the
-- one the engine's grant path would honor; (2) the newest valid instance
-- otherwise (reads still work; grant's gate pre-flight refuses honestly).
-- The pick is re-evaluated while it has no curve, because settings
-- deserialize after the ctor and a better instance (or this one's config)
-- can appear on a later read.
local function _group_level()
    if _gl_comp and _gl_valid(_gl_comp) and _gl_curve_usable(_gl_comp) then
        return _gl_comp
    end
    _arm_group_level_capture()
    local fallback = nil
    for _, p in ipairs(_gl_seen) do
        if _gl_valid(p) then
            if _gl_curve_usable(p) then
                if _gl_comp ~= p then
                    _gl_comp = p
                    R.log(string.format("[rsmm.xp] group-level component "
                        .. "captured @0x%x (level %d, curve present)", p,
                        I.read_u32(I.read_u64(p + XP_PROGRESS_OFF)) or 0))
                end
                return p
            end
            fallback = fallback or p
        end
    end
    if fallback then
        if _gl_comp ~= fallback then
            _gl_comp = fallback
            R.log(string.format("[rsmm.xp] group-level component captured "
                .. "@0x%x (level %d, NO curve config yet — grant will refuse "
                .. "until it appears)", fallback,
                I.read_u32(I.read_u64(fallback + XP_PROGRESS_OFF)) or 0))
        end
        return fallback
    end
    _gl_comp = nil                      -- entity torn down between runs
    return nil
end

-- Arm at `setup` so the hook is live before the run builds the component.
-- Subscribing cannot fail the way hooking can, and the arm itself is
-- pcall-guarded internally, so this cannot abort require"rsmm".
native.on_event("setup", function() pcall(_arm_group_level_capture) end)

-- Locate the hero's XpComponent. `allow_engine` (MAIN THREAD ONLY — the
-- engine walk calls each component's virtual IsKindOf) uses the engine's own
-- Entity_GetComponentByTester with the XpComponent type-tester, which
-- resolves subclasses the exact-vftable scan can't. The result is cached per
-- hero so the tick-thread readers (level/xp) never touch engine code.
local function _xp_component(hero, allow_engine)
    -- Constructor capture first: it returns the authored instance directly,
    -- so it is both cheaper and correct where the hero scan is structurally
    -- incapable of succeeding. The scans below remain as a fallback in case a
    -- future build does put a level component on the hero.
    local captured = _group_level()
    if captured then return captured end
    if not hero then return nil end
    if hero == _xp_cache_hero and _xp_cache_comp then return _xp_cache_comp end
    local comp = _xp_scan(hero)
    if not comp then
        local mb = I.module_base()
        if mb and mb ~= 0 then comp = _xp_heuristic(hero, mb) end
    end
    if not comp and allow_engine then
        local base = I.module_base()
        local tester = base and base ~= 0 and (base + (XP_TESTER_VA - ENTITY_IMG_BASE)) or nil
        if tester and _ptr_plausible(I.read_u64(tester)) then
            for _, entity in ipairs(_xp_entities(hero)) do
                -- entity already passed _xp_owner_valid (full component-array
                -- validation) inside _xp_entities — safe to hand to the engine
                -- walk. call_safe re-guards both pointer args as belt-and-braces.
                if entity and entity ~= 0 and _ptr_plausible(entity) then
                    local ok, got = pcall(R.engine.call_safe, "Entity_GetComponentByTester",
                                          { 1, { 2, _in_image } }, entity, tester)
                    local prog = ok and type(got) == "number" and got ~= 0
                                 and I.read_u64(got + XP_PROGRESS_OFF) or 0
                    if prog and prog ~= 0 then
                        local vft = I.read_u64(got)
                        R.log(string.format(
                            "[rsmm.xp] engine lookup found XpComponent 0x%x (vft 0x%x; map scan expects 0x%x)",
                            got, vft and (vft - base + ENTITY_IMG_BASE) or 0, XP_VFTABLE_VA))
                        comp = got
                        break
                    end
                end
            end
        end
        if not comp then _xp_diag(hero) end
    end
    if comp then _xp_cache_hero, _xp_cache_comp = hero, comp end
    return comp
end

local function _xp_progress(field)
    local comp = _xp_component(R.entity.hero()); if not comp then return nil end
    local prog = I.read_u64(comp + XP_PROGRESS_OFF)
    if not prog or prog == 0 then return nil end
    return I.read_u32(prog + field)
end

function R.xp.level() return _xp_progress(0) end
function R.xp.xp()    return _xp_progress(4) end

-- Grant XP through the engine's gain-experience routine. EXPERIMENTAL,
-- MAIN-THREAD ONLY, gated by R.stat.enable_writes(). Fails closed on any guard.
function R.xp.grant(amount)
    if not _stat_writes_enabled then
        R.log("[rsmm.xp] grant is experimental and off — call R.stat.enable_writes() first")
        return false
    end
    if not _va_ok("R.xp") then return false end
    amount = math.floor(amount or 0)
    if amount <= 0 then return false end
    local hero = R.entity.hero()
    if not hero then _log_throttled("xp.nohero", "[rsmm.xp] no hero captured yet"); return false end
    -- grant runs on the MAIN thread (schedule.next_main contract) — the only
    -- place the engine-walk lookup is safe.
    local comp = _xp_component(hero, true)
    if not comp then R.log("[rsmm.xp] XP component not found for this build — refusing"); return false end
    -- Snapshot progress so a silent engine no-op is detectable afterwards.
    local prog = I.read_u64(comp + XP_PROGRESS_OFF)
    local lvl0 = prog and prog ~= 0 and I.read_u32(prog) or nil
    local xp0  = prog and prog ~= 0 and I.read_u32(prog + 4) or nil
    -- Pre-flight the engine's own gate. Hero_GainExperience starts with an
    -- is-max-level check and returns WITHOUT touching anything when the
    -- (chain-last) level >= max level — and a component with no max-level
    -- config clamps max to 1, so a level-1 hero is "at max" and every grant
    -- silently no-ops (the 2026-07-19 playtest: "granted 200 xp", xp stayed
    -- 0). Surface that instead of reporting success. The gate returns via
    -- `setae al`, so only the low byte of the return is defined.
    local okg, gate = pcall(R.engine.call, "XpComponent_IsMaxLevel", comp)
    if okg and type(gate) == "number" and (gate & 0xff) ~= 0 then
        local _, maxl = pcall(R.engine.call, "XpComponent_GetMaxLevel", comp)
        local _, need = pcall(R.engine.call, "XpComponent_XpForLevel", comp, lvl0 or 1)
        R.log(string.format(
            "[rsmm.xp] grant refused by engine max-level gate: level=%s xp=%s "
            .. "max_level=%s xp_for_level=%s next_link=0x%x — the captured "
            .. "component has no usable level curve, so the engine would "
            .. "silently drop the grant",
            tostring(lvl0), tostring(xp0), tostring(maxl), tostring(need),
            I.read_u64(comp + 0x110) or 0))
        return false
    end
    -- The routine reads only *(int*)(xpGain+0x50); a zeroed scratch is enough.
    local gain = I.scratch(0x60)
    I.write_u32(gain + XP_GAIN_AMOUNT_OFF, amount)
    local ok = pcall(R.engine.call, "Hero_GainExperience", comp, gain)
    if not ok then R.log("[rsmm.xp] Hero_GainExperience unresolved/failed"); return false end
    -- Read back: the call returning is not proof anything landed.
    local lvl1 = prog and prog ~= 0 and I.read_u32(prog) or nil
    local xp1  = prog and prog ~= 0 and I.read_u32(prog + 4) or nil
    if lvl1 == lvl0 and xp1 == xp0 then
        R.log(string.format(
            "[rsmm.xp] grant NO-OP: level/xp unchanged (level=%s xp=%s) after "
            .. "Hero_GainExperience — engine dropped it past the max-level gate",
            tostring(lvl1), tostring(xp1)))
        return false
    end
    R.log(string.format("[rsmm.xp] granted %d xp (level %s->%s, xp %s->%s)",
        amount, tostring(lvl0), tostring(lvl1), tostring(xp0), tostring(xp1)))
    return true
end

end
