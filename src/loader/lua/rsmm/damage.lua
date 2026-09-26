-- rsmm.damage — per-player damage attribution (the run's damage meter).
--
-- Split out of rsmm.lua on 2026-08-23. It was ~5000 lines, 45% of the
-- entrypoint, and the most self-contained namespace in it: 86 private helpers
-- that nothing else reads, and only the handful of parent values below.
--
-- CONTRACT: this module returns a FUNCTION, not a table. The plain-table
-- submodules merged by _submodule are standalone; this one needs
-- the parent's private helper table and pointer guards, and it installs its own
-- hooks, so rsmm.lua calls it with an env and it populates R/F in place.
--
-- Everything below the header is verbatim from rsmm.lua, with two deliberate
-- changes, both marked at their site: F is no longer rebound, and the
-- dispatcher offset arrives as a getter.

return function(env)

-- Validate the env before reading it. A key the parent forgets to pass is nil
-- here, and nil is a legal value for most of what this module does with them:
-- MEM_SCAN_MB silently becomes a nil scan budget, LOBBY_REFRESH_SLOT a nil
-- shared slot. Nothing raises and nothing looks wrong, which is precisely the
-- failure mode the split had to be defended against. Raising instead means
-- _submodule_fn logs "failed to install" and R.damage is absent — loud, and
-- caught by the surface checks in rsmm_spec.
for _, key in ipairs({ "I", "R", "F", "_va_ok", "_ptr_plausible",
                       "ENTITY_IMG_BASE", "LOBBY_REFRESH_SLOT", "MEM_SCAN_MB",
                       "LOBBY_HOOK", "dispatcher_entity_off" }) do
    if env[key] == nil then
        error("rsmm.damage: parent did not pass env." .. key, 0)
    end
end

local I, R, F                = env.I, env.R, env.F
local _va_ok, _ptr_plausible = env._va_ok, env._ptr_plausible
local ENTITY_IMG_BASE        = env.ENTITY_IMG_BASE
local LOBBY_REFRESH_SLOT     = env.LOBBY_REFRESH_SLOT
local MEM_SCAN_MB            = env.MEM_SCAN_MB
local LOBBY_HOOK             = env.LOBBY_HOOK
-- A GETTER. See its use site: the parent learns this at runtime.
local _dispatcher_entity_off = env.dispatcher_entity_off

-- damage meter --------------------------------------------------------------
--
-- Per-player damage attribution: who is carrying the run. Three sources feed
-- one board, in priority order, and each one is disjoint from the others by
-- construction so a hit is never counted twice (all three re-confirmed against
-- the live decompile 2026-08-15).
--
-- 1. HeroStats_OnDamageDealt — PRIMARY. The engine's own per-hero damage
--    bookkeeping, called once per damage application with the DEALING HERO's
--    controller as its first argument. It is hero-scoped (enemies never reach
--    it), it sees every path that lands damage rather than one producer, and
--    it fires for ALLIES too: the engine only skips its own totalling for a
--    non-local hero (the `+0x1d88` gate), it still runs the function. That is
--    what makes an ally's damage countable at all — the game itself never
--    totals it.
-- 2. Entity_ResolveAttackHits — the local attack resolver. Used for damage
--    TAKEN (an enemy swinging at a hero reaches it, and it is the only "I got
--    hit" signal that works in single player), and as the dealt-damage
--    fallback if the primary symbol is unavailable on a future build.
-- 3. gameplay:NETWORK_DAMAGE — replicated damage, keyed by the attacker's NET
--    id (every pointer in that event belongs to the sending machine). Only
--    credited when the same player's hit did not already arrive through source
--    1 on this machine; rows are merged by net id, and a matching amount
--    inside a short window is dropped as the same hit seen twice.
--
-- MULTIPLAYER SCOPE. A peer counts what its own machine applies plus what
-- other machines replicate to it. The host applies enemy damage, so a host's
-- board is complete; a client is complete for its own damage and as complete
-- as replication allows for allies. Nothing here is networked by the mod and
-- no game state is touched — every hook replays the original untouched.
--
--     R.damage.enable{ window = 10 }
--     for rank, row in ipairs(R.damage.board()) do
--         R.log(rank, row.label, row.dealt, row.share, row.dps)
--     end

R.damage = {}

-- Constants and helpers are grouped into two tables ON PURPOSE. Lua caps a
-- function at 200 live locals and the module chunk is one function; as flat
-- locals this section pushed rsmm.lua over the limit and it stopped compiling
-- altogether — every mod dead, for a damage meter. Two tables cost two locals.
local DMG = {
    -- Engine literals that sit inside the serialized lobby member list, found
    -- next to the local display name in session 6c4f. Anchoring the name hunt
    -- on these rather than on a player's name needs no config and cannot
    -- collide with an asset path.
    -- Bytes `mem_find` may examine per needle. Was 512 MB, and EVERY hit in
    -- sessions 5736/274f sat below ~0x1b000000 — the scan was exhausting its
    -- budget inside the low heap (where Lua's own strings live) and returning
    -- before it ever reached the game's allocations. The searches were finding
    -- the probe and the config because those are the only things in the part
    -- of the address space the probe could afford to look at.
    NAME_SCAN_MB    = MEM_SCAN_MB,
    -- Strings that exist ONLY in this SDK. Lua interns every literal in the
    -- module, so the scan finds rsmm.lua's own string table and reports it as
    -- a record — most of session 5736's output was the probe finding itself,
    -- including the marker literals above. A window containing any of these is
    -- our Lua heap, never a game structure.
    STATS_SYMBOL    = "HeroStats_OnDamageDealt",
    TAKEN_SYMBOL    = "HeroStats_OnDamageTaken",
    ATTACK_SYMBOL   = "Entity_ResolveAttackHits",
    -- oCDtEntityCpntHeroController
    HERO_ENTITY_OFF  = 0x08,     -- owning oCEntity
    HERO_ISLOCAL_OFF = 0x1d88,   -- 1 = this machine's player
    HERO_MIRROR_OFF  = 0x1d80,   -- HUD HP mirror; LOCAL player only
    HERO_STATS_OFF   = 0x1db0,   -- per-run stats record (end-screen source)
    STATS_TOTAL_OFF  = 0xa8,     -- u32 total damage — LOCAL hero only
    STATS_BEST_OFF   = 0xcc,     -- f32 biggest single hit
    -- oCDtProcessedDamage
    PD_VALUE_OFF     = 0x10,     -- -> hit-value object
    VALUE_AMOUNT_OFF = 0x08,     -- f32 damage inside it
    -- Two flag bytes on the SAME value object, both read straight off the
    -- engine (Ghidra 2026-08-24).
    --
    -- +0x1b is the gate the engine puts its OWN accounting behind. In
    -- HeroStats_OnDamageDealt the entire body — the HUD mirror at hero+0x1d80,
    -- the end-screen total at stats+0xa8, the best-hit at +0xcc, the per-ability
    -- split, the analytics submit — sits inside
    --     if (*(char *)(value + 0x1b) != '\0') { ... }
    -- and Entity_GiveHandler skips the whole on-hit chain (life steal, "life on
    -- hit", the modifier events) on the same byte. So a hit with this clear is
    -- one the game itself does not count, and the meter counting it is the
    -- likeliest explanation for session a34f reading 898436 against the game's
    -- own 898071 for the same player: close, but consistently OVER.
    --
    -- +0x11 is the kill flag: it is what selects the killed-target analytics
    -- branch (the one that stamps KilledByPet / KilledBySummon).
    VALUE_APPLIED_OFF = 0x1b,
    VALUE_KILLED_OFF  = 0x11,
    -- Fail-open guard for the gate above. If the flag reads clear on nearly
    -- everything, the offset does not mean here what it means in the decompile
    -- (a game patch moved the field), and filtering on it would silently zero
    -- the board — the worst failure this meter has. Past this many observed
    -- hits, if that few passed, the gate turns itself off and says so.
    GATE_MIN_SAMPLE  = 40,
    GATE_MIN_PASS    = 0.10,
    PD_SOURCE_OFF    = 0xa0,     -- -> hit-def / source info
    SOURCE_TYPE_OFF  = 0xc8,     -- u16 attack-type enum
    -- Entity_ResolveAttackHits arguments
    CTX_ENTITY_OFF   = 0x08,     -- attacker context -> attacking entity
    TGT_COUNT_OFF    = 0x00,
    TGT_DATA_OFF     = 0x08,
    MAX_TARGETS      = 32,
    NET_AUTHORITY_OFF = 0x130,   -- net component: 0 = locally owned
    SAMPLE_CAP       = 4096,     -- rolling-window entries per actor
    DEDUPE_WINDOW    = 0.4,      -- seconds a replicated echo can lag by
    -- REBIND SAFETY. A row is only re-adopted by a new controller when the old
    -- controller can no longer be alive. Primary evidence is the CHAPTER EPOCH
    -- (bumped by the engine's own chapter/map events); this is the fallback for
    -- a build where those events never arrive -- a row nobody has credited for
    -- this long has plausibly lost its controller. Only the EXACT hero-id join
    -- may use it; the is-local guess never may.
    REBIND_IDLE      = 45,       -- seconds a row must be silent to be adopted
    -- VICTIM CLASSIFICATION (the enemy-vs-scenery test).
    --
    -- The bookkeeping hook's 2nd argument is the VICTIM ENTITY -- not a stats
    -- block, which is what symbols.json claimed until 2026-08-17. Its sole
    -- caller hands the same pointer to Entity_GetNetComponent, and this
    -- function reads the victim's definition at +0x28 to stamp the analytics
    -- record with the target's resource path. So the victim is already in our
    -- hands on the primary source; classifying it needs no extra hook.
    --
    -- An entity is a gameplay ENEMY when it carries an
    -- oCDtEntityCpntEnemyController component. Fences, jars, vegetation and
    -- mission props are Hittable + HitPoint with no controller at all
    -- (EntitySettings/Destructible_Common/* vs Enemies/NPC_Common/Enemy_Model).
    -- The test is a pure page-guarded READ of the component array -- never an
    -- engine call, so a stale offset yields a wrong answer, never a crash.
    -- Components on an oCEntity live in an F14/SwissTable map keyed by CLASS
    -- ID, not in the +0x190 pointer array — that array belongs to an
    -- oCEntitySpawnerGo (Entity_GetComponentByTester's parameter), which is
    -- why session c536 read `n/a` for every enemy it probed and found the
    -- controller on nobody. Layout from Entity_GetNetComponent
    -- (FUN_140312db0), which does this exact lookup for oCEntityCpntNetwork.
    CPNT_CTRL_OFF    = 0x5e8,    -- entity -> F14 control bytes
    CPNT_SLOTS_OFF   = 0x5f0,    -- entity -> slot array
    CPNT_MASK_OFF    = 0x600,    -- entity -> bucket mask (capacity - 1)
    CPNT_SLOT_STRIDE = 0x10,     -- slot = { u32 class id @+0, cpnt* @+8 }
    CPNT_SLOT_PTR    = 0x08,
    -- Refuse an implausible capacity outright. This is a LINEAR walk of the
    -- component map with one page-guarded read per slot, and it runs on the
    -- GAME thread inside the damage detour, so the cap is the worst-case cost
    -- of one hit on an unclassifiable victim. 0x4000 allowed 16,384 guarded
    -- reads for a victim whose mask read as garbage — three times over
    -- (VICTIM_RETRIES) before the entity was given up on. A real entity's map
    -- holds a handful of components and its capacity is a small power of two;
    -- rsmm.lua's own copy of this walk (R.net.component) has always capped at
    -- 1024. 512 is still an order of magnitude above anything real and makes
    -- the bad case 32x cheaper.
    MAX_SLOTS        = 512,
    -- Engine class ids, stamped by each class registrar as
    -- `mov [desc+0x28], <id>`. A content hash of the class NAME, so it is far
    -- more patch-stable than a vftable VA — and the same key the engine's own
    -- component map is indexed by. Mined by tools/mine_class_ids.py; the
    -- miner is confirmed by 0x154fce5c resolving to oCEntityCpntNetwork,
    -- the literal Entity_GetNetComponent hardcodes.
    ENEMY_CTRL_CLASS_ID = 0x1561073c,   -- oCDtEntityCpntEnemyController
    HERO_CTRL_CLASS_ID  = 0x155aac59,   -- oCDtEntityCpntHeroController
    ENEMY_CTRL_VFT_VA = 0x140f30b78,    -- symbols.json EnemyController_vftable
    CPNT_OWNER_OFF   = 0x08,     -- component -> owner entity (back-ptr)
    VICTIM_DEF_OFF   = 0x28,     -- entity -> oCEntitySettings (confirmed live)
    SETTINGS_RSRC_OFF = 0x70,    -- settings -> resource the engine stringifies
    VICTIM_CACHE_CAP = 512,      -- entity -> class cache entries before reset
    -- How many times ONE entity may be re-scanned after an inconclusive read.
    -- A victim whose component map cannot be read answers `unknown` on every
    -- hit, and `unknown` is fail-open — so a DoT ticking on it re-ran the full
    -- linear slot walk on the MAIN THREAD, per tick, for the whole run. Three
    -- attempts is enough to catch an entity that was merely mid-construction.
    VICTIM_RETRIES   = 3,
    -- Reason string for the stale-ally rebind. A GUESS, not an identity: it
    -- must never unlock the idle-adoption path in F._dmg_may_rebind.
    STALE_ALLY = "the only ally row whose controller died with the last chapter",
    PROBE_VICTIMS    = 12,       -- distinct victims the probe reports, then off
    PROBE_VFTS       = 6,        -- component vftables logged per victim
    -- The engine's own attack-type names, read out of the table at
    -- 0x1412ed7d0 that the bookkeeping routine indexes with the enum.
    TYPES = { [0] = "attack", "power", "special", "defense",
              "trait", "ultimate", "dash" },
}

-- NB: F is the parent chunk's shared helper table, passed in. Do NOT
-- rebind it here — code above the damage section (the lobby name hunt)
-- reads F._netid through the PARENT's upvalue, and a fresh table here
-- would leave that one empty forever.
local _dmg = {
    on       = false,
    window   = 10,        -- seconds behind `dps`
    min      = 0,         -- ignore hits at or below this
    names    = {},        -- slot -> player-supplied label
    actors   = {},        -- key -> row
    by_netid = {},        -- net id -> row (merges the replicated view in)
    by_hero  = {},        -- lobby hero id -> row (survives a chapter change)
    order    = {},        -- slot -> row, stable join order
    seen     = {},        -- entity -> true: known NOT a hero, stop asking
    subs     = {},        -- per-hit callbacks
    stats_hooked = false,
    taken_hooked = false,
    hooked   = false,     -- resolver
    local_id = nil,       -- local hero net id (false = unavailable)
    started  = nil,
    -- CHAPTER EPOCH. Incremented by the engine's chapter/map-generation events.
    -- Rows record the epoch they were last bound in, and a row may only be
    -- re-adopted by a NEW controller in a LATER epoch -- inside one chapter,
    -- an unseen hero controller is a different player, never a rebuild.
    epoch    = 0,
    refusals = 0,         -- merges declined (logged, bounded)
    -- The engine's applied-damage gate (see F._dmg_applied). Starts armed and
    -- SAMPLING: it counts everything until it has seen enough hits to prove
    -- the flag means what the decompile says on this build.
    gate_on   = true,
    gate_seen = 0,
    gate_pass = 0,
    -- Victim classification. `ignore_scenery` is OPT-IN: the engine's own
    -- end-screen total counts prop damage, so counting it is what MATCHES the
    -- game, and dropping it is a deliberate divergence a mod asks for.
    ignore_scenery = false,
    -- The identity hunt (whole-address-space scan + the 24k-probe blind sweep).
    -- OPT-IN, and off by default since 2026-08-20.
    --
    -- Not because it is slow -- because it is a COINCIDENCE GENERATOR. Every
    -- ally name it has ever produced, across every shipped log, came through a
    -- DIFFERENT offset chain:
    --
    --     entity+0x610 -> +0x140    "Gennadiy Tiger`s лапки"
    --     entity+0x678 -> +0x2d0    "Ovili"        (the LOCAL row)
    --     entity+0xad8 -> +0x1c0    "yjukih"
    --     entity+0x440 -> +0x2f0    "Shingaro Miamada"
    --     entity+0xff0 -> +0x8      "Yume"
    --     member+0x360 -> +0xd0     "Ovili"        (the LOCAL row)
    --     member+0x920 -> +0x2a8    "Timattttttt"  (the LOCAL row -- and WRONG)
    --     member+0x1138 -> +0x248   "gaetemp91"
    --     member+0x210              "exs1stenz"
    --
    -- Nine successes, nine offsets, no repeat. A real field answers at the SAME
    -- offset every time; this is finding whatever copy of a roster string
    -- happens to be reachable from the object, and which row it lands on is
    -- arbitrary. Session 6136 is the proof it can be wrong rather than merely
    -- unlucky: it named the LOCAL row "Timattttttt" with Ovili at the keyboard,
    -- which then consumed that name and left its real owner on a placeholder.
    -- Ghidra (2026-08-20) closed the question for two of those chains: the exe
    -- contains ZERO sites that walk entity+0x678 -> +0x2d0 or +0xad8 -> +0x1c0.
    --
    -- It also costs: 89s of blind sweeping across 12 row-passes in session 174f
    -- (~3.2M guarded reads) for zero names. But the cost is the lesser reason.
    --
    -- Turn it on with `R.damage.enable{ identity_hunt = true }` when RE'ing the
    -- identity itself. `R.damage.sweep_identity()` still works either way --
    -- that is the explicit call, and gating it would break the one entry point
    -- a person uses deliberately. To LABEL a run reliably, use player_1..4.
    identity_hunt = false,
    -- The TARGETED address scan (`_dmg_probe_owner_fast`), which is what
    -- actually names an ally. Bounded per roster (F._own.SWEEP_TRIES), but it
    -- still reads F._own.SLICE_MB of address space per second while it runs,
    -- and on a machine where that is felt the honest answer is a switch: the
    -- board keeps its lobby names, they are just marked as guesses. Set
    -- player_1..4 in the mod config for names that are never guesses.
    identity_scan = true,
    -- Show every lobby member on the board, even before they have dealt any
    -- damage (see F._dmg_roster_rows). OFF here and ON in the meter, which is
    -- the right layer for it: `board()` without this is a list of MEASUREMENTS,
    -- and every caller that reasons about attribution wants exactly that. A
    -- scoreboard is a presentation, and a presentation is the mod's call.
    roster_rows = false,
    probe    = false,     -- log the class of the first few distinct victims
    probes   = 0,
    vprobed  = {},        -- victim entity -> already reported
    -- entity -> session id of the machine driving it (see
    -- F._dmg_note_session). Empty until an event proves the join.
    sess_by_entity = {},
    vclass   = {},        -- victim entity -> true (enemy) / false (scenery)
    vclass_n = 0,
    -- Victim SETTINGS pointer -> enemy/scenery, learned from the entities whose
    -- component map DID read. Victims of the same type share one settings
    -- object (see F._dmg_probe_victim), so one conclusive scan of a jar
    -- classifies every other jar — including the instances whose own component
    -- map cannot be read, which is the leak this table closes.
    sclass   = {},
    sclass_n = 0,
    scenery  = 0,         -- damage dropped by the filter, session-wide
}

function F._dmg_now()
    if I.now then
        local ok, t = pcall(I.now)
        if ok and type(t) == "number" then return t end
    end
    return os.time()
end

-- An entity we are willing to hand to an engine lookup: plausible, and its
-- component store at +0x8 is a plausible pointer too. Both engine helpers used
-- below dereference that store unconditionally, so this gate is what keeps a
-- stale pointer from faulting the game instead of returning false.
function F._dmg_entity_ok(e)
    if not _ptr_plausible(e) then return false end
    return _ptr_plausible(I.read_u64(e + 8))
end

-- Heroes (including remote ones) own a magical-object component; summons, pets
-- and enemies do not. Same discriminator R.give uses on a dispatcher.
function F._dmg_is_hero(e)
    if type(I.is_grant_target) ~= "function" then return false end
    -- Plausibility only. The native discriminator page-guards every read it
    -- makes (entity header, the component store at +0x8, the F14 tables) and
    -- answers false on a bad pointer, so gating it on OUR idea of a valid
    -- store is redundant — and it was wrong: a live 4-player log showed the
    -- hero's +0x8 reading as the -1 sentinel, so this gate refused every
    -- victim and `taken` stayed 0 for the whole run.
    if not _ptr_plausible(e) then return false end
    local ok, v = pcall(I.is_grant_target, e)
    return ok and v == true
end

-- Victim classification: enemy vs scenery ---------------------------------
--
-- Everything here is READS. The component array is the same one
-- Entity_GetComponentByTester (FUN_1406e3210) walks, so the offsets are the
-- engine's own; the vftable comparison is the same shape R.xp uses to find the
-- XP component. Nothing is handed to the engine, so the worst a stale offset
-- can do is answer "unknown" -- and unknown NEVER filters (fail-open, so a
-- wrong offset under-filters instead of hiding a player's real damage).

-- Rebased EnemyController vftable, or nil when the module base is unavailable.
function F._dmg_enemy_vft()
    local base = I.module_base()
    if not base or base == 0 then return nil end
    return base + (DMG.ENEMY_CTRL_VFT_VA - ENTITY_IMG_BASE)
end

--- Scan an entity's components for the enemy controller.
--- Returns nil when the entity could not be inspected at all, else a table
--- { enemy, count, slot, owner_ok } — `owner_ok` records whether the matched
--- component's back-pointer at +0x8 points at the entity, which the probe
--- reports so the back-ptr assumption is confirmed in-game rather than
--- assumed (it is NOT required for the match; see _dmg_is_enemy).
function F._dmg_scan_components(entity)
    if not _ptr_plausible(entity) then return nil, "entity implausible" end
    local slots = I.read_u64(entity + DMG.CPNT_SLOTS_OFF)
    local mask  = I.read_u64(entity + DMG.CPNT_MASK_OFF)
    -- A NULL map is an answer, not a failure: the entity owns no components at
    -- all, so it certainly owns no EnemyController. Session ec1d hit this on
    -- two of twelve victims (both 1.0-damage props) and calling them "unknown"
    -- would have let exactly the damage this filter exists for through.
    -- A non-null but implausible pointer is a genuine failed read.
    if (slots == 0 or slots == nil) and (mask == 0 or mask == nil) then
        return { enemy = false, count = 0, empty = true }
    end
    -- The decline REASON matters: session c536 reported "no components" for
    -- every enemy and there was no way to tell an empty map from a bad read.
    if not _ptr_plausible(slots) then
        return nil, ("slots=0x%x implausible"):format(slots or 0)
    end
    if type(mask) ~= "number" or mask < 0 or mask + 1 > DMG.MAX_SLOTS then
        return nil, ("mask=%s over cap"):format(tostring(mask))
    end
    -- The map is walked LINEARLY rather than hashed: the engine's own probe
    -- computes an F14 hash to find one key fast, but we are reading a handful
    -- of slots on a bounded table, and a linear pass needs no hash function to
    -- stay correct across a game patch.
    local want = F._dmg_enemy_vft()
    for i = 0, mask do
        local slot = slots + i * DMG.CPNT_SLOT_STRIDE
        local id   = I.read_u32(slot)
        if id == DMG.ENEMY_CTRL_CLASS_ID then
            local comp = I.read_u64(slot + DMG.CPNT_SLOT_PTR)
            if _ptr_plausible(comp) then
                return { enemy = true, count = mask + 1, slot = i,
                         -- Reported, never required: both are corroboration
                         -- for the class id, which is the actual test.
                         vft_ok   = want ~= nil and I.read_u64(comp) == want,
                         owner_ok = I.read_u64(comp + DMG.CPNT_OWNER_OFF) == entity }
            end
        end
    end
    return { enemy = false, count = mask + 1 }
end

--- The victim's oCEntitySettings pointer, which is its TYPE identity.
---
--- Every jar shares one settings object, every gnoll hunter shares another (the
--- victim probe logs it for exactly this reason). That makes it the key the
--- classification should be remembered under: a per-ENTITY answer has to be
--- re-derived for each instance, and an instance whose component map does not
--- read is unclassifiable forever, while the TYPE was already answered by a
--- sibling that read fine.
function F._dmg_settings(entity)
    local set = I.read_u64(entity + DMG.VICTIM_DEF_OFF)
    return _ptr_plausible(set) and set or nil
end

--- true = gameplay enemy, false = scenery/prop/mission object, nil = unknown.
---
--- Cached per victim pointer because a multi-hit ability re-classifies the
--- same target several times a frame. The cache is validated against the
--- entity's own vftable: pointers ARE recycled inside a run (an enemy dies, a
--- prop lands on its memory), and two reads to re-check beat believing a
--- stale answer.
---
--- THREE tiers, because `unknown` is fail-open and therefore expensive: a
--- victim that answers unknown has its damage counted, so a family of props
--- whose component map cannot be read lands on the board as carry damage. The
--- 2026-08-18 co-op log is that failure — one player at 11,612 hits for 613k
--- damage (59 per hit, against 353 for the top row), long runs of exactly 1.0
--- (the flat per-hit prop value), and a `scenery` column frozen for the last
--- four minutes of the run while their hit count kept climbing.
---
---   1. the per-ENTITY cache (vftable-validated), for the multi-hit case;
---   2. the per-TYPE map, keyed by the settings pointer — filled only from
---      CONCLUSIVE scans, and consulted when this entity's own scan declines;
---   3. give up and answer unknown, but stop re-scanning after
---      DMG.VICTIM_RETRIES attempts. The walk runs on the main thread inside a
---      damage detour, so re-running it per DoT tick for a whole run is not
---      free.
function F._dmg_is_enemy(entity)
    if not _ptr_plausible(entity) then return nil end
    local vft = I.read_u64(entity)
    local hit = _dmg.vclass[entity]
    if hit and hit.vft == vft then
        -- A cached `unknown` still gets a bounded number of retries: the first
        -- read may simply have caught the entity mid-construction.
        if hit.enemy ~= nil or (hit.tries or 0) >= DMG.VICTIM_RETRIES then
            -- The type map may have learned the answer from a sibling since.
            if hit.enemy == nil then
                -- `set and _dmg.sclass[set] or nil` would turn a learned
                -- SCENERY answer (false) back into nil, which is the fail-open
                -- branch this whole table exists to close.
                local set = F._dmg_settings(entity)
                if set ~= nil and _dmg.sclass[set] ~= nil then
                    return _dmg.sclass[set]
                end
            end
            return hit.enemy
        end
    end
    local scan = F._dmg_scan_components(entity)
    if _dmg.vclass_n >= DMG.VICTIM_CACHE_CAP then
        _dmg.vclass, _dmg.vclass_n = {}, 0
        hit = nil
    end
    local set = F._dmg_settings(entity)
    if scan then
        -- Conclusive. Teach the TYPE, so every sibling instance is answered
        -- even when its own component map is unreadable.
        if set and _dmg.sclass[set] == nil then
            if _dmg.sclass_n >= DMG.VICTIM_CACHE_CAP then
                _dmg.sclass, _dmg.sclass_n = {}, 0
            end
            _dmg.sclass[set] = scan.enemy
            _dmg.sclass_n = _dmg.sclass_n + 1
        end
        _dmg.vclass[entity] = { vft = vft, enemy = scan.enemy }
        _dmg.vclass_n = _dmg.vclass_n + 1
        return scan.enemy
    end
    -- Inconclusive: remember the attempt so the walk is not repeated forever,
    -- then fall back to what this victim's TYPE already answered elsewhere.
    local tries = ((hit and hit.vft == vft) and (hit.tries or 0) or 0) + 1
    _dmg.vclass[entity] = { vft = vft, enemy = nil, tries = tries }
    _dmg.vclass_n = _dmg.vclass_n + 1
    if set ~= nil and _dmg.sclass[set] ~= nil then return _dmg.sclass[set] end
    return nil
end

function F._dmg_img_rel(p)
    local base = I.module_base()
    if not p or p == 0 or not base or base == 0 or p < base then return nil end
    return p - base + ENTITY_IMG_BASE
end

--- One-shot diagnostic: what IS this victim?
---
--- Round 1 (2026-08-17, session c536) proved the plumbing and killed the
--- theory: every victim read back as oCEntity (vft 0x140f743b0) with
--- oCEntitySettings at +0x28 and real components at +0x190 — but NOT ONE of
--- twelve carried the EnemyController, and most reported no component array at
--- all. So this round reports (a) WHY the array read declined, (b) EVERY
--- component vftable, not the first six, and (c) the settings' resource path,
--- read as inline strings — that names the victim ("Gnoll_Hunter" vs
--- "Destructible_Jar") instead of leaving it an address, which is the only
--- way to tell a wrong offset from a wrong theory.
---
--- Bounded (DMG.PROBE_VICTIMS victims per process) because it runs on the MAIN
--- THREAD inside the damage detour. Reads only — no engine calls, so nothing
--- here can fault the game.
function F._dmg_probe_victim(entity, amount)
    if not _dmg.probe or _dmg.probes >= DMG.PROBE_VICTIMS then return end
    if not _ptr_plausible(entity) or _dmg.vprobed[entity] then return end
    _dmg.vprobed[entity] = true
    _dmg.probes = _dmg.probes + 1
    local n = _dmg.probes
    local scan, why = F._dmg_scan_components(entity)
    -- Image-relative, so the numbers in the log line up with the addresses in
    -- data/symbols.json across launches (ASLR moves the module, not the RVAs).
    local function hex(p)
        local v = F._dmg_img_rel(p)
        return v and string.format("0x%x", v) or "?"
    end
    local slots = I.read_u64(entity + DMG.CPNT_SLOTS_OFF)
    local mask  = I.read_u64(entity + DMG.CPNT_MASK_OFF)
    local set   = I.read_u64(entity + DMG.VICTIM_DEF_OFF)
    R.log(string.format(
        "[rsmm.damage] victim probe #%d: ent=0x%x vft=%s slots=0x%x mask=%s "
        .. "enemy=%s slot=%s vft_ok=%s owner_ok=%s settings=0x%x dmg=%.1f%s",
        n, entity, hex(I.read_u64(entity)), slots or 0, tostring(mask),
        scan and tostring(scan.enemy) or "unknown",
        scan and scan.slot and tostring(scan.slot) or "-",
        scan and scan.slot and tostring(scan.vft_ok) or "-",
        scan and scan.slot and tostring(scan.owner_ok) or "-",
        set or 0, amount or 0, why and (" declined: " .. why) or ""))
    -- Every OCCUPIED slot's class id. These decode offline against
    -- data/class_ids.json, so one log says exactly which components a fence
    -- and a gnoll each carry — the thing round 1 could not answer.
    if scan then
        local line = {}
        for i = 0, scan.count - 1 do
            local slot = slots + i * DMG.CPNT_SLOT_STRIDE
            local id   = I.read_u32(slot)
            if id and id ~= 0 and _ptr_plausible(I.read_u64(slot + DMG.CPNT_SLOT_PTR)) then
                line[#line + 1] = string.format("0x%x", id)
            end
            if #line == 8 then
                R.log(("[rsmm.damage] probe #%d class ids: %s")
                      :format(n, table.concat(line, " ")))
                line = {}
            end
        end
        if #line > 0 then
            R.log(("[rsmm.damage] probe #%d class ids: %s")
                  :format(n, table.concat(line, " ")))
        end
    end
    -- No string dump here. Reading the victim's asset path out of the settings
    -- object was tried in session ec1d and returned noise ("JAT_I", "0cbuJ^"):
    -- the path is not inline at settings+0x70, the engine reaches it through a
    -- resource handle it resolves with a call. The class ids answer the
    -- question anyway — an enemy's map holds EnemyController +
    -- CharacterController + RemoteDamageOwner + ModifierHolder, a prop's holds
    -- oCEntityCpntNetwork and nothing else — so the string hunt has no
    -- remaining job. `settings` is still logged as an identity: victims of the
    -- same TYPE share one settings pointer, which is what makes it usable as a
    -- classification cache key.
end

-- The engine's local/remote test: net component +0x130 is 0 when this machine
-- controls the entity; no net component at all means it is not replicated.
function F._dmg_entity_is_local(e)
    -- The engine's is-local byte — see _dispatcher_is_local for why it is
    -- neither the net component (crashes) nor the HUD mirror (allies have one).
    if not _ptr_plausible(e) then return false end
    return I.read_u8(e + DMG.HERO_ISLOCAL_OFF) == 1
end

-- NO net-id lookup here, deliberately.
--
-- This used to call Entity_GetNetId to key rows by a replication-stable id.
-- It crashed the game (2026-08-15, dump a97c76fe): that function calls
-- Entity_GetNetComponent, which walks the entity's component map with no
-- guard, and a hero object whose store slot holds the -1 sentinel takes the
-- process down. `is_grant_target` accepting an object proves it is a grantable
-- hero — NOT that a different subsystem can traverse it.
--
-- Nothing needed it badly enough to risk that. The replicated path already
-- carries a net id in its own payload (a plain number off the wire, no engine
-- call), the local player is identified by its HUD mirror, and cross-source
-- double counting is caught by the amount+time echo filter.

-- Net id: the identity that survives replication. nil when unavailable.
function F._dmg_net_id(_e)
    -- Intentionally always nil: see the note above. Kept as a seam so the
    -- callers read the same whether or not a SAFE net-id source ever appears.
    return nil
end

function F._dmg_label_for(slot, is_local)
    if _dmg.names[slot] then return _dmg.names[slot] end
    if is_local then
        -- The local player's real name, when Steam can tell us. "You" is the
        -- fallback, not the goal: a scoreboard full of "Player 2" is what this
        -- avoids for at least one row.
        local ok, name = pcall(R.player.name)
        if ok and type(name) == "string" then return name end
        return "You"
    end
    -- A real name from the LOBBY beats "Player 2". Cache-only (R.lobby.members
    -- never scans) because this runs on the MAIN THREAD inside a damage hook.
    -- If the roster is not resolved yet the row gets a placeholder and
    -- F._dmg_relabel fixes it as soon as the background scan lands.
    --
    -- ⚠ A name is only taken here when there is exactly ONE ally it could
    -- belong to and this is the first ally row — that case is exact by
    -- elimination. The old code matched allies in JOIN ORDER (`allies[rank]`),
    -- which is the order they first dealt damage in and has nothing to do with
    -- the lobby's order, so with 3+ players it attached real names to the wrong
    -- damage totals (reported 2026-08-19, 4p co-op: the local row was right and
    -- every ally row was shuffled). A wrong name on a real number is worse than
    -- no name, so everything else waits for the hero-id join in F._dmg_relabel.
    local ok, allies = pcall(R.lobby.allies)
    if ok and type(allies) == "table" and #allies == 1 then
        local others = 0
        for _, row in ipairs(_dmg.order) do
            if not row.is_local then others = others + 1 end
        end
        if others == 0 then return allies[1] end
    end
    return "Player " .. tostring(slot)
end

-- The rest of R.damage is in two parts that this file loads: WHO a row is
-- (rsmm/damage_identity.lua) and the netcode joins (rsmm/damage_netcode.lua).
-- They define functions on F and R and read the tables above by reference, so
-- only the order matters: DMG and _dmg exist before they load. A part that
-- fails raises, so R.damage is absent (loud) rather than half-installed.
local _part_env = { I = I, R = R, F = F, DMG = DMG, _dmg = _dmg, _va_ok = _va_ok,
                    _ptr_plausible = _ptr_plausible, LOBBY_HOOK = LOBBY_HOOK,
                    LOBBY_REFRESH_SLOT = LOBBY_REFRESH_SLOT }
require("rsmm.damage_identity")(_part_env)
require("rsmm.damage_netcode")(_part_env)

--- True when a scan could actually change something: some ally row is still
--- wearing a "Player N" placeholder. Solo runs never qualify, so they never
--- pay for a scan.
function F._dmg_wants_lobby()
    for _, row in ipairs(_dmg.order) do
        if not row.is_local and not _dmg.names[row.slot]
            and row.label:find("^Player %d") then
            return true
        end
    end
    return false
end

function F._dmg_new_row(key, is_local)
    local slot = #_dmg.order + 1
    local row = {
        key = key, slot = slot, is_local = is_local or false,
        label = F._dmg_label_for(slot, is_local),
        dealt = 0, taken = 0, hits = 0, best = 0, by_type = {},
        -- Damage the scenery filter dropped. Kept per row so a UI can show
        -- "and 4.2k into the furniture" instead of silently losing it.
        scenery = 0, scenery_hits = 0,
        -- Kills this player landed, and hits the engine's own gate discarded
        -- (see F._dmg_applied). Initialised here rather than lazily so every
        -- consumer sees a number from the first frame.
        kills = 0, discarded = 0, discarded_amount = 0,
        -- Damage credited even though the victim could NOT be classified. The
        -- filter is fail-open on purpose (never hide a player's damage on a bad
        -- read), which means an unreadable prop family is counted as carry
        -- damage — so the amount that rests on that assumption is counted too,
        -- and a board that looks wrong can be checked against it instead of
        -- argued about.
        unknown = 0, unknown_hits = 0,
        -- Has ANY source ever reported damage taken for this row? `taken` is 0
        -- both for a player who was never hit and for a player this machine
        -- cannot observe, and those are not the same claim (see R.damage.board).
        taken_seen = false,
        first = F._dmg_now(), last = 0, samples = {}, recent = {},
        -- The chapter this row's controller was bound in. See F._dmg_rebind.
        epoch = _dmg.epoch,
    }
    _dmg.actors[key] = row
    _dmg.order[slot] = row
    return row
end

-- A player is reachable under several keys — its hero CONTROLLER (the engine's
-- bookkeeping hands us that), its ENTITY (the attack resolver hands us that),
-- and its NET id (replication hands us that). They must all land on ONE row, or
-- the same player shows up two or three times on the board and every share is
-- wrong. Alias keys point at the row; the net id gets its own index.
function F._dmg_alias(row, key)
    if key and _dmg.actors[key] == nil then _dmg.actors[key] = row end
end

function F._dmg_bind_netid(row, entity)
    if row.netid ~= nil or not entity then return end
    local id = F._dmg_net_id(entity)
    row.netid = id or false
    if id then _dmg.by_netid[id] = row end
end

--- May `prev` be handed to a controller it has never been bound to?
---
--- Only when its own controller cannot still be alive. See F._dmg_rebind for
--- why this is the whole safety of that function.
function F._dmg_may_rebind(prev, why)
    local newer = (prev.epoch or 0) < _dmg.epoch
    -- The exact join may also adopt a row that has gone quiet for longer than a
    -- chapter load; a GUESS may not, because a wrong match would then merge
    -- live allies the moment one of them stops attacking for 45 seconds.
    --
    -- Two reasons are guesses: the is-local byte, and the stale-ally rule
    -- below (which infers "same player" from "exactly one ally row's
    -- controller died over this chapter change"). The stale rule is safe
    -- BECAUSE it needs a chapter boundary -- a player who simply leaves
    -- mid-run also leaves a dead controller, and letting the idle path adopt
    -- that row would hand the next player to join their name and their total.
    local exact = why ~= "local flag" and why ~= DMG.STALE_ALLY
    local idle = exact and prev.last and prev.last > 0
                 and (F._dmg_now() - prev.last) >= DMG.REBIND_IDLE
    if newer or idle then return true end
    -- Say it, but not once per hit: this is the branch that keeps a player on
    -- the board, and a silent refusal looks exactly like the bug it prevents.
    _dmg.refusals = _dmg.refusals + 1
    if _dmg.refusals <= 4 then
        R.log(("[rsmm.damage] refused to merge a new controller into %s (%s) — "
               .. "same chapter (epoch %d) and that row is still active, so this "
               .. "is a DIFFERENT player, not a rebuilt controller")
              :format(prev.label or "?", why or "?", _dmg.epoch))
    end
    return false
end

--- Adopt an existing row for a hero controller we have not seen before.
---
--- The meter used to key rows by the controller pointer alone, which is stable
--- only WITHIN a chapter. Crossing into the next chapter rebuilds every hero
--- controller, so every player forked a second row: the 2026-08-17 evening log
--- shows seven rows for a four-player lobby, "Juice" listed twice (both flagged
--- as the local player), placeholder labels running to "Player 7", and the
--- abandoned rows frozen at 0.0 dps while the run continued. Nothing was lost
--- exactly — it was double-counted into two halves, which is worse, because
--- every `share` on the board is then wrong.
---
--- Two joins, strongest first:
---   1. the HERO ID, when the sweep has confirmed where it lives. Each player
---      in a run has a distinct hero, so this is exact.
---   2. the engine's is-local byte. There is exactly ONE local player, so a
---      second local controller is always the same person. This needs no RE at
---      all and fixes the duplicate that matters most (your own row).
---
--- BOTH joins are gated on the row's controller being GONE, which is the part
--- the first version left out — and a merge is far worse than the fork it
--- replaced. A four-player run (2026-08-18, session 29a8) boarded TWO rows: an
--- unseen controller inside the SAME chapter is another player standing next to
--- you, and this function adopted it as "the same person, new object". A
--- rebuild only happens at a chapter boundary, so that is what is required:
---
---   * hero-id join (exact): a later EPOCH, or a row nothing has credited for
---     REBIND_IDLE seconds (the fallback for a build whose chapter events never
---     arrive — a live player is never silent across a whole chapter load).
---   * is-local join (a guess — one misread byte at +0x1d88 folds every ally
---     onto your row): a later EPOCH, and nothing else.
---
--- Refusing costs a duplicate row, which is visible, self-explanatory and
--- keeps every player's damage. Merging silently deletes a player.
--- Returns the adopted row, or nil to let the caller board a new player.
function F._dmg_rebind(hero, is_local, entity)
    local id = F._dmg_hero_id(hero)
    local prev = id and _dmg.by_hero[id] or nil
    local why = prev and "hero " .. tostring(id) or nil
    -- No fallback scan over the rows here: every path that sets `hero_id` also
    -- writes `by_hero` (see F._dmg_backfill_ids), so a scan could only find what
    -- the index already has. It was written, could not be made to fail in the
    -- spec, and was deleted rather than shipped unexercised.
    if not prev and is_local then
        for _, r in ipairs(_dmg.order) do
            if r.is_local then prev, why = r, "local flag"; break end
        end
    end
    -- STALE-ROW ADOPTION, for the case that has neither key: an ALLY after a
    -- chapter change.
    --
    -- Session a34f, measured against the game's own end-of-run scoreboard:
    -- Ovilli 898436 vs 898071 (exact -- the local row rebinds on the is-local
    -- flag), but the two allies came out as FIVE rows, one player's damage
    -- split across three of them, because an ally has no hero id on this build
    -- and is not local, so every chapter handed them a fresh controller and
    -- `prev` stayed nil.
    --
    -- The rule is deliberately narrow, and refuses rather than guesses:
    -- the new controller must belong to a LATER epoch than the row, the row's
    -- own controller must no longer read as a live hero, and there must be
    -- EXACTLY ONE such row. Two stale rows means two allies respawned and
    -- nothing here can say which is which -- that forks, as before. In a34f
    -- only one ally's controller moved per chapter (the others kept their
    -- address), which is precisely the unambiguous case.
    if not prev and not is_local then
        local stale, n = nil, 0
        for _, r in ipairs(_dmg.order) do
            if not r.is_local and (r.epoch or 0) < _dmg.epoch
               and not (_ptr_plausible(r.key) and F._dmg_is_hero(r.key)) then
                stale, n = r, n + 1
            end
        end
        if n == 1 then
            prev, why = stale, DMG.STALE_ALLY
        elseif n > 1 then
            if not _dmg.stale_said then
                _dmg.stale_said = true
                R.log(("[rsmm.damage] %d ally row(s) went stale over this "
                       .. "chapter change — cannot say which is which, so the "
                       .. "new controller starts its own row"):format(n))
            end
        end
    end
    if not prev then return nil end
    if not F._dmg_may_rebind(prev, why) then return nil end
    _dmg.actors[hero] = prev
    prev.key = hero
    prev.epoch = _dmg.epoch          -- bound HERE now; see F._dmg_may_rebind
    prev.hero_id = id or prev.hero_id
    if prev.hero_id then _dmg.by_hero[prev.hero_id] = prev end
    -- New controller, so a sweep that came up empty on the old one deserves
    -- another go: the name may live on this object even though it did not live
    -- on the last. (A row that already knows who it is keeps that answer.)
    prev.own_done = nil
    F._dmg_alias(prev, entity)
    F._dmg_bind_netid(prev, entity)
    R.log(("[rsmm.damage] rebound %s to controller 0x%x (%s) — chapter change, "
           .. "not a new player"):format(prev.label, hero,
              id and ("hero " .. id) or "local flag"))
    return prev
end

-- Row for a hero CONTROLLER (source 1). The controller is what the SDK already
-- captures for the local player, and its +0x1d88 byte is the engine's own
-- "this is my player" flag — cheaper and more direct than a net lookup.
function F._dmg_row_for_hero(hero)
    if not _ptr_plausible(hero) then return nil end
    local row = _dmg.actors[hero]
    if row then return row end
    local is_local = I.read_u8(hero + DMG.HERO_ISLOCAL_OFF) == 1
    local entity = I.read_u64(hero + DMG.HERO_ENTITY_OFF)
    -- ONE line, once per session. The 2026-08-15 co-op run showed the net-id
    -- lookup refusing this entity, which also explains an empty `taken` column:
    -- if controller+0x8 is not the entity the rest of the SDK recognises, rows
    -- cannot be merged with the resolver's view of the same player. Dump the
    -- raw chain so the next session says which link is wrong instead of
    -- guessing.
    if not _dmg.probed then
        _dmg.probed = true
        R.log(string.format(
            "[rsmm.damage] identity probe: controller=0x%x hero?=%s inner=%s "
            .. "inner_hero?=%s mirror=%s local_byte=%s",
            hero, tostring(F._dmg_is_hero(hero)), tostring(entity),
            tostring(_ptr_plausible(entity) and F._dmg_is_hero(entity) or false),
            tostring(I.read_u64(hero + DMG.HERO_MIRROR_OFF)),
            tostring(I.read_u8(hero + DMG.HERO_ISLOCAL_OFF))))
    end
    -- The resolver may have boarded this player by entity already (it sees
    -- damage TAKEN before the hero deals any). Reuse that row.
    local existing = _ptr_plausible(entity) and _dmg.actors[entity] or nil
    if existing then
        _dmg.actors[hero] = existing
        return existing
    end
    -- A CHAPTER TRANSITION rebuilds every hero controller, so an unknown
    -- pointer usually means "same player, new object" — not a new player.
    -- Adopt the existing row instead of forking a second one for them.
    existing = F._dmg_rebind(hero, is_local, entity)
    if existing then return existing end
    row = F._dmg_new_row(hero, is_local)
    -- The owner id lives on the ENTITY (the component map is the entity's),
    -- not on the controller — so stamp it from the entity this controller
    -- owns, or the two sources key the same player differently.
    if _ptr_plausible(entity) and R.net and R.net.owner then
        row.owner = R.net.owner(entity)
    end
    F._dmg_alias(row, entity)
    -- One line per player BOARDED, bounded. Session 29a8 was a four-player run
    -- that produced two rows, and the log could not say which join collapsed
    -- them: whether the is-local byte reads 1 for an ally (it must not — there
    -- is one local player) is a two-byte question that otherwise costs a whole
    -- playtest, in a timezone eight hours away.
    _dmg.boarded = (_dmg.boarded or 0) + 1
    if _dmg.boarded <= 8 then
        R.log(("[rsmm.damage] boarded row %d (%s): controller=0x%x local_byte=%s "
               .. "hero_id=%s epoch=%d"):format(
                  row.slot, row.label or "?", hero,
                  tostring(I.read_u8(hero + DMG.HERO_ISLOCAL_OFF)),
                  tostring(F._dmg_hero_id(hero)), _dmg.epoch))
    end
    -- Sweep for the hero-id field as soon as a SECOND row exists, rather than
    -- waiting for the next tick: the identity is needed by the time the next
    -- chapter loads, and a row boarded in the meantime would be un-rebindable.
    -- Self-gating (needs two rows and two identified lobby members) and
    -- bounded, so this is a no-op on all but a couple of calls per session.
    F._dmg_probe_hero_field()
    row.hero_id = F._dmg_hero_id(hero)
    if row.hero_id then _dmg.by_hero[row.hero_id] = row end
    F._dmg_bind_netid(row, entity)
    if is_local and _dmg.local_id == nil then
        _dmg.local_id = (row.netid ~= false and row.netid) or false
    end
    return row
end

-- Row for an ENTITY seen through the attack resolver (source 2). The negative
-- answer is cached: an enemy attacks hundreds of times a run and each miss
-- would otherwise be an engine lookup.
function F._dmg_row_for_entity(e)
    if not _ptr_plausible(e) then return nil end
    local row = _dmg.actors[e]
    if row then return row end
    if _dmg.seen[e] then return nil end
    if not F._dmg_is_hero(e) then _dmg.seen[e] = true; return nil end
    local id = F._dmg_net_id(e)
    if id and _dmg.by_netid[id] then
        row = _dmg.by_netid[id]
        F._dmg_alias(row, e)
        return row
    end
    local is_local = F._dmg_entity_is_local(e)
    -- THE LOCAL PLAYER IS ONE ROW, whatever object the engine hands us.
    --
    -- F._dmg_row_for_hero adopts an existing local row on the is-local flag
    -- ("same player, new object"); this path never did, so any swap of the
    -- hero OBJECT mid-chapter forked a second row for the same person. Sun
    -- Wukong's transform is the reported case (2026-08-24), and it is not the
    -- only one -- a respawn rebuilds the object too. The fork is not just a
    -- duplicate row: it is a row that can never be named (F._dmg_claim refuses
    -- a name another row already holds), so `wanted` in
    -- F._dmg_probe_owner_fast stays true for the rest of the run and the
    -- address-space sweep keeps running behind it. That is the stutter.
    --
    -- Sound by construction: there is exactly one local player per process,
    -- and the is-local byte is the engine's own answer (see
    -- F._dmg_entity_is_local). Allies get no such rule -- nothing on this
    -- build identifies them (the hero-id join is dead here), so an ally swap
    -- still forks rather than guessing which row it belongs to.
    -- OWNER JOIN — the identity the engine itself uses. R.net.owner reads the
    -- exact field Entity_ResolveAttackHits stamps into every hit it builds
    -- (netcomp -> +0xb8 -> +0x100 -> +0x28, confirmed in Ghidra 2026-08-24),
    -- so two entities answering with the same id have the same owner. That is
    -- what makes an ALLY's transformed or cloned hero attributable: no roster,
    -- no name, no guess. Tried before the is-local rule because it is exact
    -- where that one is a fallback.
    --
    -- Deliberately narrow, because the failure it must never have is merging
    -- two live players (one machine can own two heroes in local co-op, and
    -- the host owns every enemy):
    --   * both ids must be present and equal;
    --   * the row's OWN key must no longer read as a live hero. A swap
    --     replaces the object, so the old one is dead — whereas two heroes
    --     that are both alive are two players, whatever they share.
    local owner = R.net and R.net.owner and R.net.owner(e) or nil
    if owner then
        for _, r in ipairs(_dmg.order) do
            if r.owner == owner and r.key ~= e
               and not (_ptr_plausible(r.key) and F._dmg_is_hero(r.key)) then
                F._dmg_alias(r, e)
                r.key = e
                _dmg.owner_joins = (_dmg.owner_joins or 0) + 1
                if _dmg.owner_joins <= 8 then
                    R.log(("[rsmm.damage] owner join: entity 0x%x has the same "
                           .. "owner as row %d (%s) whose object is gone — "
                           .. "transform or respawn, not a new player")
                          :format(e, r.slot, r.label or "?"))
                end
                return r
            end
        end
    end
    if is_local then
        for _, r in ipairs(_dmg.order) do
            if r.is_local then
                F._dmg_alias(r, e)
                -- Bounded like the boarding log above. One line per swap is
                -- useful; a hero whose ability spawns a fresh object per cast
                -- would otherwise write one per cast for a whole run, into the
                -- log a player is asked to attach to a bug report.
                _dmg.swaps = (_dmg.swaps or 0) + 1
                if _dmg.swaps <= 8 then
                    R.log(("[rsmm.damage] local hero object changed to 0x%x "
                           .. "(transform or respawn) — reusing row %d, not a "
                           .. "new player%s"):format(e, r.slot,
                              _dmg.swaps == 8 and " (further swaps silent)" or ""))
                end
                return r
            end
        end
    end
    row = F._dmg_new_row(e, is_local)
    row.owner = owner
    row.netid = id or false
    if id then _dmg.by_netid[id] = row end
    if is_local and _dmg.local_id == nil then
        _dmg.local_id = (row.netid ~= false and row.netid) or false
    end
    return row
end

function F._dmg_publish(row, amount, target, source, kind)
    if #_dmg.subs == 0 then return end
    local hit = { label = row.label, slot = row.slot, is_local = row.is_local,
                  amount = amount, target = target, source = source,
                  kind = kind or "dealt" }
    for _, cb in ipairs(_dmg.subs) do pcall(cb, hit) end
end

-- Has this row just been credited the same amount BY THE LOCAL APPLY PATH?
-- Sources 1 and 3 are disjoint in theory (the machine that applies a hit is not
-- the machine that receives its replication), but "in theory" is not a good
-- enough reason to risk double-counting a player's damage, which is the one
-- number this whole feature exists to get right.
--
-- Only cross-source echoes are dropped, never repeats within one source: a
-- multi-hit ability lands several IDENTICAL amounts inside a few frames, and an
-- amount-based filter that ignored the source would silently eat most of a
-- flurry's damage — the exact opposite of the bug it is there to prevent.
function F._dmg_is_echo(row, amount, now)
    local r = row.recent
    for i = #r, 1, -1 do
        if now - r[i].t > DMG.DEDUPE_WINDOW then
            table.remove(r, i)
        elseif math.abs(r[i].a - amount) < 0.01 then
            return true
        end
    end
    return false
end

-- Did ANY player's locally-applied hit just land for this amount?
--
-- Without a net id we cannot ask "is this replicated event about me", so the
-- test widens from one row to all of them: if this machine applied a hit of
-- the same size a moment ago, the event is that hit coming back, and crediting
-- it would invent a phantom player. Four rows and a 0.4s window — cheaper than
-- the engine call it replaces, and it cannot crash the game.
function F._dmg_echo_of_local(amount, now)
    for _, row in ipairs(_dmg.order) do
        if F._dmg_is_echo(row, amount, now) then return true end
    end
    return false
end

function F._dmg_credit(row, amount, target, source, kind)
    local now = F._dmg_now()
    row.dealt = row.dealt + amount
    row.hits  = row.hits + 1
    row.last  = now
    if amount > row.best then row.best = amount end
    if kind then row.by_type[kind] = (row.by_type[kind] or 0) + amount end
    local s = row.samples
    s[#s + 1] = { t = now, a = amount }
    -- Bound the window buffer: a long run at high APM would grow it without
    -- limit. Dropping the oldest half keeps the recent window (all `dps` reads)
    -- honest.
    if #s > DMG.SAMPLE_CAP then
        local keep = {}
        for i = #s // 2, #s do keep[#keep + 1] = s[i] end
        row.samples = keep
    end
    -- Only the local apply path seeds the echo filter; see F._dmg_is_echo.
    if source == "hero-stats" then
        local r = row.recent
        r[#r + 1] = { t = now, a = amount }
        if #r > 32 then table.remove(r, 1) end
    end
    F._dmg_publish(row, amount, target, source, "dealt")
end

-- One resolved hit from the attack resolver. `attacker` may be nil (an enemy
-- swinging), `target` may be nil. Damage landing on a HERO is never carry
-- damage — it is that hero's `taken`, and its attacker does not join the board.
function F._dmg_record(attacker, target, amount, source)
    if type(amount) ~= "number" or amount ~= amount then return end   -- NaN
    if amount <= _dmg.min then return end
    local victim = target and F._dmg_row_for_entity(target) or nil
    if victim then
        victim.taken = victim.taken + amount
        victim.taken_seen = true
        victim.last_hurt = F._dmg_now()
        F._dmg_publish(victim, amount, target, source, "taken")
        return
    end
    if not attacker then return end
    F._dmg_probe_victim(target, amount)
    -- With the hero-stat hook armed, dealt damage is counted there for EVERY
    -- hero (allies included); crediting it here as well would double it.
    if _dmg.stats_hooked then return end
    -- Same scenery filter as the bookkeeping path — this branch is the SOLO
    -- fallback on a build where the stat hook is unresolved, and it would
    -- otherwise keep counting fences on exactly the builds that need it most.
    local cls
    if _dmg.ignore_scenery and target then cls = F._dmg_is_enemy(target) end
    if cls == false then
        attacker.scenery = attacker.scenery + amount
        attacker.scenery_hits = attacker.scenery_hits + 1
        _dmg.scenery = _dmg.scenery + amount
        return
    end
    if _dmg.ignore_scenery and target and cls == nil then
        attacker.unknown = attacker.unknown + amount
        attacker.unknown_hits = attacker.unknown_hits + 1
    end
    F._dmg_credit(attacker, amount, target, source)
end

-- Source 1: the engine's per-hero bookkeeping. Observation only.
--- Did the engine count this hit? true / false / nil when the flag is
--- unreadable (which is fail-OPEN: never drop a player's damage on a bad read).
---
--- Self-disarming. The flag is a single byte at an RE-derived offset, and the
--- failure mode of getting it wrong is catastrophic and silent: every hit
--- filtered, a board of zeroes, and nothing in the log saying why. So the
--- first GATE_MIN_SAMPLE hits are only MEASURED; if fewer than GATE_MIN_PASS
--- of them passed, the offset cannot mean what the decompile says it means on
--- this build and the gate retires itself for the session.
function F._dmg_applied(valobj)
    if not _dmg.gate_on then return nil end
    if not I.read_u8 then return nil end
    local b = I.read_u8(valobj + DMG.VALUE_APPLIED_OFF)
    if type(b) ~= "number" then return nil end
    local pass = b ~= 0
    _dmg.gate_seen = (_dmg.gate_seen or 0) + 1
    if pass then _dmg.gate_pass = (_dmg.gate_pass or 0) + 1 end
    if _dmg.gate_seen == DMG.GATE_MIN_SAMPLE then
        local ratio = (_dmg.gate_pass or 0) / _dmg.gate_seen
        if ratio < DMG.GATE_MIN_PASS then
            _dmg.gate_on = false
            R.log(("[rsmm.damage] the engine's applied-damage flag (+0x%x) read "
                   .. "set on only %d of %d hits — that offset does not mean "
                   .. "what it means in the decompile on this build, so the "
                   .. "filter is OFF for this session and every hit counts "
                   .. "(report this: it means a game patch moved the field)")
                  :format(DMG.VALUE_APPLIED_OFF, _dmg.gate_pass or 0, _dmg.gate_seen))
            return nil
        end
        R.log(("[rsmm.damage] engine applied-flag gate live: %d of %d hits "
               .. "counted by the game"):format(_dmg.gate_pass or 0, _dmg.gate_seen))
    end
    -- While still sampling, count everything: a gate that has not proven
    -- itself must not be allowed to drop damage.
    if _dmg.gate_seen < DMG.GATE_MIN_SAMPLE then return nil end
    return pass
end

--- Did this hit kill the target? The flag the engine uses to pick its
--- killed-target analytics branch.
function F._dmg_killed(valobj)
    if not I.read_u8 then return false end
    return I.read_u8(valobj + DMG.VALUE_KILLED_OFF) == 1
end

function F._dmg_observe_stats(hero, target, pd)
    if not _ptr_plausible(hero) or not _ptr_plausible(pd) then return end
    local valobj = I.read_u64(pd + DMG.PD_VALUE_OFF)
    if not _ptr_plausible(valobj) then return end
    local amount = I.read_f32(valobj + DMG.VALUE_AMOUNT_OFF)
    if type(amount) ~= "number" or amount ~= amount or amount <= _dmg.min then return end
    -- THE ENGINE'S OWN GATE. See DMG.VALUE_APPLIED_OFF: everything the game
    -- counts for this hit sits behind this byte, so a hit with it clear is one
    -- the end screen will not show and the meter should not either.
    local applied = F._dmg_applied(valobj)
    local row = F._dmg_row_for_hero(hero)
    if not row then return end
    if applied == false then
        row.discarded = (row.discarded or 0) + 1
        row.discarded_amount = (row.discarded_amount or 0) + amount
        return
    end
    if F._dmg_killed(valobj) then row.kills = (row.kills or 0) + 1 end
    -- What did they hit? The probe reports the first few distinct victims so
    -- the classification can be confirmed from a log rather than trusted.
    F._dmg_probe_victim(target, amount)
    -- Fences, jars, vegetation and mission props inflate a damage board
    -- without meaning anything. `unknown` (nil) counts: never drop a player's
    -- damage on a failed read.
    -- NOT `_dmg.ignore_scenery and F._dmg_is_enemy(target) or nil`: in Lua that
    -- idiom turns a classified `false` (the scenery answer this filter exists
    -- for) into `nil`, which is the fail-open branch.
    local cls
    if _dmg.ignore_scenery then cls = F._dmg_is_enemy(target) end
    if cls == false then
        row.scenery = row.scenery + amount
        row.scenery_hits = row.scenery_hits + 1
        _dmg.scenery = _dmg.scenery + amount
        return
    end
    if _dmg.ignore_scenery and cls == nil then
        -- Counted (fail-open), but counted SEPARATELY as well: this is the only
        -- number that says how much of a row rests on a victim the filter could
        -- not read.
        row.unknown = row.unknown + amount
        row.unknown_hits = row.unknown_hits + 1
    end
    -- Which ability landed it, for the per-ability breakdown. A source object
    -- that does not read back cleanly just means "other" — never a reason to
    -- drop the damage.
    local kind = "other"
    local src = I.read_u64(pd + DMG.PD_SOURCE_OFF)
    if _ptr_plausible(src) then
        local t = I.read_u16(src + DMG.SOURCE_TYPE_OFF)
        if type(t) == "number" and DMG.TYPES[t] then kind = DMG.TYPES[t] end
    end
    F._dmg_credit(row, amount, target, "hero-stats", kind)
end

-- Source 1b: the engine's per-hero damage-RECEIVED bookkeeping.
--
-- The resolver's victim path cannot name a hero on this build (is_grant_target
-- answers false for the controller AND for controller+0x8 — probed live on
-- 2026-08-15), so `taken` was empty for every player. This hook hands the
-- victim over as the same hero object the rows are already keyed by, so it
-- merges with no translation and covers allies too.
function F._dmg_observe_taken(victim, pd)
    if not _ptr_plausible(victim) or not _ptr_plausible(pd) then return end
    -- Same processed-damage record as the dealt side: hit-value object at
    -- +0x10, its f32 at +0x8. The one-shot probe reports the alternative
    -- (+0xa0) too, so a layout difference shows up as data in the log rather
    -- than as another silently empty column.
    local valobj = I.read_u64(pd + DMG.PD_VALUE_OFF)
    local amount = _ptr_plausible(valobj)
        and I.read_f32(valobj + DMG.VALUE_AMOUNT_OFF) or nil
    if not _dmg.probed_taken then
        _dmg.probed_taken = true
        local alt = I.read_u64(pd + DMG.PD_SOURCE_OFF)
        R.log(string.format(
            "[rsmm.damage] taken probe: victim=0x%x local=%s value@+0x10=%s "
            .. "alt@+0xa0=%s",
            victim, tostring(I.read_u8(victim + DMG.HERO_ISLOCAL_OFF)),
            tostring(amount),
            tostring(_ptr_plausible(alt) and I.read_f32(alt + 8) or nil)))
    end
    if type(amount) ~= "number" or amount ~= amount or amount <= 0 then return end
    local row = F._dmg_row_for_hero(victim)
    if not row then return end
    row.taken = row.taken + amount
    row.taken_seen = true
    row.last_hurt = F._dmg_now()
    F._dmg_publish(row, amount, victim, "hero-stats", "taken")
end

function F._dmg_arm_taken()
    if _dmg.taken_hooked then return true end
    if not (R.hook and I.resolve) then return false end
    local va = I.resolve(DMG.TAKEN_SYMBOL)
    if not va or va == 0 then return false end
    -- void(victim, processedDamage). Observation only: return nil without
    -- calling next, and the loader replays the original with the raw arguments.
    local ok, slot, why = pcall(R.hook, va, "vpp", function(victim, pd)
        if _dmg.on then pcall(F._dmg_observe_taken, victim, pd) end
        return nil
    end)
    if not ok then return false end
    if slot == nil and why ~= "already-hooked" then return false end
    _dmg.taken_hooked = true
    return true
end

function F._dmg_arm_stats()
    if _dmg.stats_hooked then return true end
    if not (R.hook and I.resolve) then return false end
    local va = I.resolve(DMG.STATS_SYMBOL)
    if not va or va == 0 then return false end
    -- void(hero, target, processedDamage, char). Read-only: return nil without
    -- calling next, and the loader replays the original with the raw arguments
    -- it received, so the engine's own bookkeeping is bit-for-bit unchanged.
    local ok, slot, why = pcall(R.hook, va, "vpppi", function(hero, target, pd)
        if _dmg.on then pcall(F._dmg_observe_stats, hero, target, pd) end
        return nil
    end)
    if not ok then return false end
    if slot == nil and why ~= "already-hooked" then return false end
    _dmg.stats_hooked = true
    return true
end

-- Source 2: the local attack resolver.
--
-- The signature must carry ALL FIVE arguments ("fpupff", matching the symbol's
-- cabi). The 5th is base damage, which the Windows x64 ABI passes on the
-- STACK; a 4-argument signature would still install, but `next()` would replay
-- the original with whatever happened to be in that stack slot — i.e. a random
-- base damage on every attack in the game.
function F._dmg_observe_attack(ctx, targets, amount)
    if type(amount) ~= "number" or amount <= 0 then return end
    if not _ptr_plausible(ctx) or not _ptr_plausible(targets) then return end
    local attacker = I.read_u64(ctx + DMG.CTX_ENTITY_OFF)
    -- `row` is nil when the attacker is not a hero — an enemy swinging. That is
    -- NOT a reason to stop: the swing may be landing on a hero, and that hero's
    -- `taken` is the other half of the board (and the "I just got hit" signal
    -- other mods subscribe to). F._dmg_record handles a nil attacker.
    local row = F._dmg_row_for_entity(attacker)
    local n = I.read_u32(targets + DMG.TGT_COUNT_OFF)
    local data = I.read_u64(targets + DMG.TGT_DATA_OFF)
    if type(n) ~= "number" or n <= 0 or not _ptr_plausible(data) then
        if row then F._dmg_record(row, nil, amount, "local") end
        return
    end
    if n > DMG.MAX_TARGETS then n = DMG.MAX_TARGETS end
    -- ONE line, once per session, for the other half of the board: `taken`
    -- was 0 for everyone in the 2026-08-15 co-op run, and the two candidate
    -- explanations (enemy attacks never reach this hook / the victim is not
    -- recognised as a hero) look identical from outside. Report the first
    -- swing that is NOT from a boarded hero, with what we make of its target.
    if not _dmg.probed_victim and not row then
        _dmg.probed_victim = true
        local first = I.read_u64(data)
        R.log(string.format(
            "[rsmm.damage] victim probe: attacker=%s target=%s hero?=%s boarded=%s",
            tostring(attacker), tostring(first),
            tostring(F._dmg_is_hero(first)),
            tostring(_dmg.actors[first] ~= nil)))
    end
    for i = 0, n - 1 do
        F._dmg_record(row, I.read_u64(data + i * 8), amount, "local")
    end
end

function F._dmg_arm_resolver()
    if _dmg.hooked then return true end
    if not (R.hook and I.resolve) then return false end
    local va = I.resolve(DMG.ATTACK_SYMBOL)
    if not va or va == 0 then return false end
    local ok, slot, why = pcall(R.hook, va, "fpupff",
        function(ctx, hitdef, targets, mul, base, nxt)
            local dmg = nxt(ctx, hitdef, targets, mul, base)
            if _dmg.on then pcall(F._dmg_observe_attack, ctx, targets, dmg) end
            return dmg
        end)
    if not ok then return false end
    if slot == nil and why ~= "already-hooked" then return false end
    _dmg.hooked = true
    return true
end

-- CHAPTER EPOCH. The engine rebuilds every hero controller when a chapter
-- loads, which is the ONLY moment a row may legitimately change controller (see
-- F._dmg_rebind). Both events are subscribed because neither is guaranteed:
-- GAME_END_NEXT_CHAPTER fires as the old chapter tears down, MAP_GENERATION_DONE
-- as the new one is built, and a build that emits only one of them still gets a
-- bump. Extra bumps are harmless — the epoch only ever UNLOCKS a rebind that a
-- pointer change already asked for.
function F._dmg_next_epoch(name)
    _dmg.epoch = _dmg.epoch + 1
    -- The identity scan's ADDRESSES die with the chapter. Every object it
    -- recorded is torn down here, so holding them is both useless (a rebuilt
    -- controller reaches none of them) and unsafe (freed memory is handed back
    -- out, so a stale address can come to sit next to an unrelated row and name
    -- it wrongly). Nothing else would ever have dropped them: `addrs_key` is
    -- the ROSTER, and a chapter change does not touch the roster, so an ally
    -- still unnamed at the boundary was served a dead cache for the rest of
    -- the run.
    --
    -- The CHAINS are deliberately KEPT. An offset into a rebuilt object is the
    -- one thing about a player that a chapter change does not move, so they are
    -- exactly what names the new controllers — in two reads, with no scan.
    F._own.addrs, F._own.addrs_key, F._own.queue = nil, nil, nil
    -- The net-id DISCOVERY cache dies with them, for the same reason and one
    -- worse: it is keyed by controller ADDRESS, and the allocator hands those
    -- addresses back out. A rebuilt controller landing where a previous row
    -- sat would read as already probed and inherit the OTHER player's hits,
    -- which is precisely how a locator gets adopted against the wrong person.
    -- The ADOPTED locator is kept on purpose -- an offset is what survives a
    -- chapter change; only the per-controller findings are stale.
    F._netid.probed, F._netid.hits = {}, {}
    -- The GUID report is per RUN, and a refusal must not outlive the rows it
    -- was about: new chapter, new controllers, new chance to resolve.
    F._netid.guid_said, F._netid.guid_done = false, false
    F._netid.peer_said, F._netid.peer_done = false, false
    -- A chapter rebuilds every hero controller, so every row's owner GUID is
    -- new — the one moment the raknet join has something it has not already
    -- answered. Without this it stays stood down for the rest of the run.
    F._netid.rak_done, F._netid.rak_idle, F._netid.rak_said = false, 0, false
    F._netid.peer_gen, F._netid.peer_scanned, F._netid.peer_hit = nil, {}, {}
    -- Sticky guesses belong to the board that made them: a chapter change
    -- re-adopts every controller, so slot N is not the same player it was.
    _dmg.guessed = {}
    -- Per RUN, not per process: a later run that also never receives the other
    -- players' attributes deserves to be told so too.
    _dmg.roster_warned = false
    if _dmg.on then
        R.log(("[rsmm.damage] chapter epoch %d (%s) — hero controllers may now "
               .. "be re-adopted"):format(_dmg.epoch, name))
    end
end
R.on("gameplay:GAME_END_NEXT_CHAPTER",
     function() F._dmg_next_epoch("GAME_END_NEXT_CHAPTER") end)
R.on("gameplay:MAP_GENERATION_DONE",
     function() F._dmg_next_epoch("MAP_GENERATION_DONE") end)

-- Source 3: replicated damage. Identity is the net id; the victim is the
-- entity the event was dispatched INTO, which the SDK can reach once it has
-- learned where a dispatcher sits inside its entity (R.give's
-- _learn_dispatcher_offset). Until then the victim is unknown and the hit is
-- credited to the attacker — the right default, since the overwhelming
-- majority of replicated damage is a player hitting an enemy.
--- Is the replicated `value` field actually DAMAGE on this build?
---
--- ⚠ Ghidra 2026-08-24, reading the emitter (NamedEvent_NetSend's producer,
--- FUN_1407276a0) field by field as it builds oCGameNamedEventNetworkDamage:
---
---     ev+0x38 = -1                              (sender id, stamped later)
---     ev+0x40 = *(float*)(*(attacker+0x30)+0x24) * DAT_140fcbee8
---     ev+0x48 = FUN_1407273c0(attacker)         (netcomp -> vft[0x20] id)
---     ev+0x50 = embedded oCEntityHitData, copied field-for-field from the pd
---
--- `*(entity+0x30)` is the SCENE CONTEXT — HeroStats_OnDamageDealt applies
--- oCTKindOfTypeTester<oCGameEventSceneContext> to that exact pointer, and
--- feeds `+0x24` into its recent-hits window, comparing it against a seconds
--- threshold. So on the SENDER, ev+0x40 is a clock, not a damage number, and
--- the payload schema calling it `value` is asking this meter to credit a
--- timestamp as damage — a phantom row climbing by hundreds per hit.
---
--- What a RECEIVER sees is a different question: the netcode reconstructs the
--- event from the wire and the serializer may well land damage there. Nobody
--- has measured it, and this client has never received one (no `net victim
--- probe` line in any shipped log), so neither reading can be assumed.
---
--- Rather than guess, let the data decide. A clock only ever goes UP; damage
--- does not. After enough strictly-increasing values in a row the field is a
--- clock, crediting stops, and the log says so — on any build, without a
--- playtest to arrange.
function F._dmg_net_value_is_clock(amount)
    if _dmg.net_credit == false then return true end
    local prev = _dmg.net_last
    _dmg.net_last = amount
    if prev and amount > prev then
        _dmg.net_rising = (_dmg.net_rising or 0) + 1
    else
        _dmg.net_rising = 0
    end
    if (_dmg.net_rising or 0) < 8 then return false end
    _dmg.net_credit = false
    R.log(("[rsmm.damage] the replicated damage field has risen on %d "
           .. "consecutive events (now %.1f) — that is a CLOCK, not damage "
           .. "(the emitter writes scene-time*k at ev+0x40), so replicated "
           .. "hits stop being credited. Local and hero-stat sources are "
           .. "unaffected."):format(_dmg.net_rising, amount))
    return true
end

R.on("gameplay:NETWORK_DAMAGE", function(ev)
    if not _dmg.on then return end
    local amount = tonumber(ev.value)
    local id = tonumber(ev.source_id or "")
    if not amount or amount <= _dmg.min or not id or id == -1 then return end
    -- One line per event, three times, whatever happens next: this client has
    -- never received one of these, so the first session that does is the one
    -- that settles what the field means.
    _dmg.net_logged = (_dmg.net_logged or 0) + 1
    if _dmg.net_logged <= 3 then
        R.log(("[rsmm.damage] replicated hit #%d: value=%.3f source_id=0x%x "
               .. "(is that damage, or scene time? see F._dmg_net_value_is_clock)")
              :format(_dmg.net_logged, amount, id))
    end
    if F._dmg_net_value_is_clock(amount) then return end
    -- Already counted here? Then it is this machine's own hit echoing back via
    -- another peer, not a new player's damage. (There is no net id to compare
    -- against any more — asking the engine for one crashed the game.)
    if F._dmg_echo_of_local(amount, F._dmg_now()) then return end
    -- VICTIM: prefer the payload's own `target_entity` (+0x60 of the embedded
    -- oCEntityHitData, decoded by event_fields.gen.h) over deriving it from the
    -- dispatcher. The derived guess was the only source here, which is part of
    -- why `taken` stayed 0 for every ally: the engine hands us the target
    -- outright and we were reconstructing it.
    local victim
    local target = tonumber(ev.target_entity or "")
    if target and target ~= 0 and _ptr_plausible(target) then victim = target end
    -- Read through the getter, never a captured value: the parent learns this
    -- offset at RUNTIME (it is nil until corroborated), so a load-time copy
    -- would be nil forever and silently drop every derived victim.
    local disp_off = _dispatcher_entity_off()
    if not victim and disp_off and type(ev.dispatcher) == "string" then
        local disp = tonumber(ev.dispatcher)
        if disp then victim = disp - disp_off end
    end
    -- One line, once: does the target we now decode actually correspond to a
    -- player row? If it never does, ally `taken` is not reachable from this
    -- event either and the answer is netcode, not attribution — but that has
    -- been ASSERTED in the symbol note without ever being measured.
    _dmg.net_victim_probes = (_dmg.net_victim_probes or 0) + 1
    if _dmg.net_victim_probes <= 4 then
        -- Lookup and classify ONLY, never create. _dmg_row_for_hero and
        -- _dmg_row_for_entity both CREATE a row for a plausible pointer, and
        -- most NETWORK_DAMAGE targets are enemies — probing with either would
        -- have put enemies on the scoreboard.
        --
        -- `hero?` is the question that decides the whole feature: if a hit on
        -- an ALLY never reaches this machine as NETWORK_DAMAGE, then ally
        -- `taken` is genuinely unavailable here (owner-side only, as the symbol
        -- note claims) and the column should say so rather than read 0. If it
        -- does arrive, the row just needs joining — the ally's row is keyed by
        -- net id, and entity->net-id is dead (see F._dmg_net_id), so that join
        -- has to be built deliberately rather than by creating a second row.
        local known = victim ~= nil and _dmg.actors[victim] or nil
        R.log(string.format(
            "[rsmm.damage] net victim probe #%d: target=%s row=%s hero?=%s",
            _dmg.net_victim_probes,
            target and string.format("0x%x", target) or "nil",
            known and (known.label or "?") or "none",
            tostring(victim ~= nil and F._dmg_is_hero(victim) or false)))
    end
    if victim and _dmg.actors[victim] then
        local row = _dmg.actors[victim]
        row.taken = row.taken + amount
        row.taken_seen = true
        row.last_hurt = F._dmg_now()
        F._dmg_publish(row, amount, victim, "net", "taken")
        return
    end
    local row = _dmg.by_netid[id]
    if not row then
        row = F._dmg_new_row("net:" .. string.format("%x", id), false)
        row.netid = id
        _dmg.by_netid[id] = row
    end
    F._dmg_credit(row, amount, victim, "net")
end)

--- Start metering. Idempotent; safe to call from `ready` or from run:start.
---   opts.window          seconds behind the rolling `dps` figure (default 10)
---   opts.min             ignore hits at or below this value (default 0)
---   opts.names           { [slot] = "Alice", ... } fixed labels by join order
---   opts.ignore_scenery  drop damage dealt to destructible props and mission
---                        objects (fences, jars, dream-shard nodes), counting
---                        only hits on gameplay enemies. Default FALSE, which
---                        is what matches the game's own end-screen total.
---                        Dropped damage is still totalled per row (`scenery`).
---   opts.probe           log the class of the first few distinct victims, so
---                        the enemy test can be confirmed from a log
---   opts.roster_rows     board every lobby member, including those who have
---                        not dealt damage yet, as a zeroed row (default false;
---                        the shipped meter turns it on)
---   opts.identity_scan   run the targeted address scan that puts real names
---                        on ally rows (default TRUE). It is bounded per
---                        roster, but it does read memory in the background
---                        while it runs; turn it off if that is felt. The
---                        board keeps its lobby names, marked as guesses.
function R.damage.enable(opts)
    opts = opts or {}
    if type(opts.window) == "number" and opts.window > 0 then _dmg.window = opts.window end
    if type(opts.min) == "number" then _dmg.min = opts.min end
    if opts.ignore_scenery ~= nil then _dmg.ignore_scenery = opts.ignore_scenery and true or false end
    -- Let unidentified rows borrow the leftover lobby names by join order. OFF
    -- by default: the mapping is a guess, and a wrong name on a real damage
    -- total cannot be spotted from inside the game.
    if opts.guess_names ~= nil then _dmg.guess_names = opts.guess_names and true or false end
    if opts.probe ~= nil then _dmg.probe = opts.probe and true or false end
    if opts.identity_hunt ~= nil then
        _dmg.identity_hunt = opts.identity_hunt and true or false
    end
    if opts.identity_scan ~= nil then
        _dmg.identity_scan = opts.identity_scan and true or false
    end
    if opts.roster_rows ~= nil then
        _dmg.roster_rows = opts.roster_rows and true or false
    end
    -- Seconds before a row whose sweep found nothing is swept again. A row is
    -- swept the moment it first deals damage and the object that identifies it
    -- may not be populated yet, so one pass is not an answer. 0 retries on the
    -- next tick, which is what the spec uses.
    if type(opts.retry_after) == "number" and opts.retry_after >= 0 then
        F._own.RETRY_AFTER = opts.retry_after
    end
    if type(opts.names) == "table" then
        for k, v in pairs(opts.names) do
            if type(k) == "number" and type(v) == "string" then _dmg.names[k] = v end
        end
    end
    if _dmg.on then return true end
    _dmg.on = true
    _dmg.started = F._dmg_now()
    local stats = F._dmg_arm_stats()
    local taken = F._dmg_arm_taken()
    local resolver = F._dmg_arm_resolver()
    R.log(("[rsmm.damage] metering on (window %ds, sources: %s, victims: %s%s)")
          :format(_dmg.window, R.damage.mode(),
                  _dmg.ignore_scenery and "enemies only" or "everything the game counts",
                  _dmg.probe and ", probe on" or ""))
    if _dmg.ignore_scenery and not F._dmg_enemy_vft() then
        R.log("[rsmm.damage] module base unavailable — the enemy test cannot "
              .. "run, so nothing is filtered (damage is never dropped on a "
              .. "failed read)")
    end
    F._dmg_lobby_refresh()
    if not stats then
        R.log("[rsmm.damage] " .. DMG.STATS_SYMBOL .. " unresolved on this game "
              .. "build — ALLY damage will only be counted where the engine "
              .. "replicates it to this machine")
    end
    if not taken then
        R.log("[rsmm.damage] " .. DMG.TAKEN_SYMBOL .. " unresolved on this game "
              .. "build — the `taken` column will stay empty")
    end
    if not resolver then
        R.log("[rsmm.damage] " .. DMG.ATTACK_SYMBOL .. " unresolved — solo "
              .. "damage has no fallback source on this build")
    end
    return true
end

--- Which sources are live, e.g. "hero-stats+resolver+net".
function R.damage.mode()
    local parts = {}
    if _dmg.stats_hooked then parts[#parts + 1] = "hero-stats" end
    if _dmg.taken_hooked then parts[#parts + 1] = "hero-taken" end
    if _dmg.hooked then parts[#parts + 1] = "resolver" end
    parts[#parts + 1] = "net"
    return table.concat(parts, "+")
end

--- Stop counting. The detours stay installed (uninstalling a hook another mod
--- may be using is worse than an early return in a callback) but nothing is
--- recorded while metering is off.
function R.damage.disable() _dmg.on = false end

function R.damage.enabled() return _dmg.on end

--- True when the engine's per-hero bookkeeping is hooked — the source that
--- makes ALLY damage countable. False means ally numbers depend on replication.
function R.damage.tracks_allies() return _dmg.stats_hooked end

--- True when the local attack resolver is hooked (damage taken, solo damage).
function R.damage.resolver_armed() return _dmg.hooked end

--- Is the scenery filter on? Pass a boolean to turn it on or off mid-run
--- (rows keep both totals, so toggling never loses a number).
function R.damage.ignore_scenery(on)
    if on ~= nil then _dmg.ignore_scenery = on and true or false end
    return _dmg.ignore_scenery
end

--- Damage the scenery filter dropped this run, across every player. 0 when
--- the filter is off — nothing is classified unless it is asked for.
function R.damage.scenery_total() return _dmg.scenery end


--- Classify a victim entity: true = gameplay enemy, false = scenery / prop /
--- mission object, nil = could not tell (and therefore never filtered).
function R.damage.is_enemy(entity) return F._dmg_is_enemy(entity) end

--- Per-hit callback: cb{ label, slot, is_local, amount, target, source, kind }.
--- `kind` is "dealt" (they damaged something that is not a hero) or "taken"
--- (they were damaged) — the reliable "I just got hit" signal, since the local
--- resolver sees enemy attacks on heroes too.
function R.damage.on(cb)
    assert(type(cb) == "function", "R.damage.on: cb must be function")
    _dmg.subs[#_dmg.subs + 1] = cb
    return #_dmg.subs
end

--- Name a player by join order (1 = first actor seen). Applies retroactively.
function R.damage.name(slot, label)
    assert(type(slot) == "number", "R.damage.name: slot must be number")
    assert(type(label) == "string", "R.damage.name: label must be string")
    _dmg.names[slot] = label
    local row = _dmg.order[slot]
    if row then row.label = label end
end

--- The page-cached reader and its flush, exposed for the spec and for a mod
--- doing its own struct walking. Same answer as a guarded read, one syscall
--- per 4 KiB page instead of one per value (see F._dmg_pread).
function R.damage._pread(va, w) return F._dmg_pread(va, w) end
function R.damage._pflush() return F._dmg_pflush() end

--- Clear every counter. Called on run boundaries by the meter mod; call it
--- yourself for per-chapter or per-fight scores.
function R.damage.reset()
    _dmg.actors, _dmg.order, _dmg.seen, _dmg.by_netid = {}, {}, {}, {}
    _dmg.by_hero = {}
    -- Per RUN, like _dmg.roster_warned: a fresh board deserves to be told its
    -- own forking story rather than inheriting the last run's silence.
    _dmg.fork_said = false
    _dmg.swaps = 0
    _dmg.owner_joins = 0
    -- Re-arm the gate's SAMPLE, not the gate's verdict: a run that proved the
    -- offset wrong keeps it off (gate_on is deliberately not touched here).
    _dmg.gate_seen, _dmg.gate_pass = 0, 0
    -- Per run, like the gate's sample: a fresh board re-measures the field.
    -- `net_credit` is NOT reset -- a build that proved it a clock keeps that.
    _dmg.net_last, _dmg.net_rising, _dmg.net_logged = nil, 0, 0
    -- The sweep's CURSOR points at a row that no longer exists; the CHAIN is a
    -- fact about the engine's layout and stays.
    F._own.cursor = nil
    -- Same split for the member link: the cursor and the per-member "already
    -- swept" set point at dead rows, the learned OFFSET is layout and stays.
    -- The candidate table goes too — a hit is only evidence while the row it
    -- named still exists.
    _dmg.local_id, _dmg.started = nil, F._dmg_now()
    -- Victim pointers do not survive a run boundary: the next run reuses the
    -- addresses for different objects, so a kept cache would answer for the
    -- wrong entity. (The per-entry vftable check would catch most of that;
    -- dropping the table is cheaper and exact.)
    _dmg.vclass, _dmg.vclass_n, _dmg.scenery = {}, 0, 0
    -- The TYPE map is dropped with the entity cache: settings objects are
    -- reloaded per run, so a kept answer could be about a different asset.
    _dmg.sclass, _dmg.sclass_n = {}, 0
end

--- Total damage dealt to non-hero targets by everyone on the board.
function R.damage.total()
    local sum = 0
    for _, row in ipairs(_dmg.order) do sum = sum + row.dealt end
    return sum
end

--- The scoreboard, highest damage first — the ranking, recomputed on every
--- call so a caller polling it always shows the current order. Each row:
---   rank, label, slot, is_local, dealt, taken, hits, best, dps, share, by_type
---   scenery, scenery_hits, unknown, unknown_hits, taken_known, dps_window
--- `dps` is over the configured window (`dps_window`) and `share` is the
--- fraction of all damage dealt — the "who is carrying" number.
---
--- Three keys exist so a UI can say what it does NOT know, instead of printing
--- a confident zero: `unknown`/`unknown_hits` (damage counted against a victim
--- the scenery filter could not classify) and `taken_known` (false when nothing
--- has ever reported damage taken for this player, which is the normal state
--- for an ally).
--- Lobby members with no row yet, as zeroed placeholder rows.
---
--- A row is only ever created when damage is first attributed to a player, so
--- until someone lands a counted hit they simply are not on the board. For a
--- support that can be most of a chapter, or all of it: session 104f's "Artur"
--- carried 57% of the team's healing and did not appear until 110s into a 165s
--- chapter, which reads as "the meter lost a player", not as "he had not hit
--- anything yet".
---
--- Derived on every call and never stored in `_dmg.order`. That is the whole
--- safety argument: a placeholder owns no entity key, so it can never absorb a
--- hit, never forks at a chapter change, and vanishes the instant the real row
--- exists — the alternative (seeding a real row per member) would have to guess
--- which controller belongs to whom, which is the join that does not exist.
---
--- @param taken  set of names already on the board, by `player` AND by `label`
---               (a guessed label is still that player's row on screen, and
---               showing them twice is worse than showing them late).
function F._dmg_roster_rows(taken, next_slot)
    local ok, members = pcall(R.lobby.members)
    if not ok or type(members) ~= "table" then return {} end
    -- AN UNIDENTIFIED ROW BLOCKS THIS ENTIRELY. `taken` is a set of names, so a
    -- row still reading "Player 2" matches no member — and every member would
    -- then be added underneath it, including whoever that row already is. The
    -- board would show more rows than there are players and list somebody
    -- twice, which is a worse lie than listing them late. Once the lobby names
    -- land (guess_names, or the raknet join) this clears by itself.
    for _, row in ipairs(_dmg.order) do
        if not row.is_local and type(row.label) == "string"
           and row.label:match("^Player %d+$") then
            return {}
        end
    end
    local me, out = F._dmg_me(), {}
    for _, m in ipairs(members) do
        local nm = m.name
        if type(nm) == "string" and nm ~= "" and not taken[nm] then
            taken[nm] = true
            next_slot = next_slot + 1
            out[#out + 1] = {
                label = nm, slot = next_slot, is_local = (nm == me),
                hero_id = m.hero_id, label_guess = false, player = nil,
                -- Not a measurement of zero: this player has no row at all yet.
                -- A UI that wants to say "waiting" rather than "0" reads this.
                pending = true,
                dealt = 0, taken = 0, hits = 0, best = 0, last = 0,
                by_type = {}, scenery = 0, scenery_hits = 0,
                unknown = 0, unknown_hits = 0,
                taken_known = false,
                dps = 0, dps_window = _dmg.window, share = 0, idle = nil,
            }
        end
    end
    return out
end

function R.damage.board()
    local now = F._dmg_now()
    local cutoff = now - _dmg.window
    local total = R.damage.total()
    local out = {}
    for _, row in ipairs(_dmg.order) do
        local recent, keep = 0, {}
        for _, s in ipairs(row.samples) do
            if s.t >= cutoff then recent = recent + s.a; keep[#keep + 1] = s end
        end
        row.samples = keep
        local by_type = {}
        for k, v in pairs(row.by_type) do by_type[k] = v end
        out[#out + 1] = {
            label = row.label, slot = row.slot, is_local = row.is_local,
            -- The player's hero, when the identity sweep has found it. A UI can
            -- show the character, and it is what makes a row survive a chapter
            -- change, so it is worth surfacing rather than keeping internal.
            hero_id = row.hero_id, label_guess = row.label_guess,
            -- The lobby name this row was PROVEN to be (owner-name sweep), as
            -- opposed to `label`, which may still be a placeholder.
            player = row.player,
            dealt = row.dealt, taken = row.taken, hits = row.hits,
            best = row.best, last = row.last, by_type = by_type,
            scenery = row.scenery, scenery_hits = row.scenery_hits,
            -- Kills, and what the engine's own gate threw away. `discarded`
            -- being large next to `dealt` is the signal that this build
            -- discards more than expected — worth seeing rather than hiding.
            kills = row.kills or 0,
            discarded = row.discarded or 0,
            discarded_amount = row.discarded_amount or 0,
            -- Damage credited to a victim the filter could not classify. A UI
            -- that shows `hits` should show this too: it is the part of the row
            -- that may be prop chip damage counted as carry (see F._dmg_is_enemy).
            unknown = row.unknown, unknown_hits = row.unknown_hits,
            -- Is `taken = 0` a MEASUREMENT or an absence of one? On this build
            -- the per-hero damage-RECEIVED bookkeeping only fires for heroes
            -- this machine owns, so an ally reads 0 all run whether or not they
            -- were ever hit — and a scoreboard column that cannot tell the two
            -- apart is a wrong number, not a missing one. False until some
            -- source has actually reported a hit on this player.
            taken_known = row.taken_seen == true,
            dps = recent / _dmg.window,
            -- The window `dps` covers, so a caller can LABEL it. A report
            -- printed every 15s off a 10s window has a 5s blind spot, and a
            -- player who stopped attacking 11s ago reads 0.0 dps in a report
            -- that also shows their damage rising — which reads as a bug.
            dps_window = _dmg.window,
            share = total > 0 and (row.dealt / total) or 0,
            idle = row.last > 0 and (now - row.last) or nil,
        }
    end
    -- Everyone in the lobby appears, whether or not they have hit anything yet.
    -- Zero damage sorts last, so this never displaces a real row.
    if _dmg.roster_rows then
        local taken = {}
        for _, row in ipairs(out) do
            if row.player then taken[row.player] = true end
            if row.label then taken[row.label] = true end
        end
        for _, row in ipairs(F._dmg_roster_rows(taken, #_dmg.order)) do
            out[#out + 1] = row
        end
    end
    table.sort(out, function(a, b)
        if a.dealt ~= b.dealt then return a.dealt > b.dealt end
        return a.slot < b.slot
    end)
    for i, row in ipairs(out) do row.rank = i end
    return out
end

--- The player currently on top (or nil when nothing has been recorded).
function R.damage.leader()
    local board = R.damage.board()
    return board[1]
end

--- The engine's OWN run totals for the local player, straight off the hero's
--- stats record (+0x1db0) — the numbers the end-of-run summary shows. Useful
--- as a cross-check that the meter is counting the same fight the game is.
--- Returns nil when there is no captured hero yet; ally records exist but the
--- engine never fills them, which is the whole reason this module accumulates.
function R.damage.engine_totals()
    local hero = R.entity and R.entity.hero and R.entity.hero()
    if not _ptr_plausible(hero) then return nil end
    local rec = I.read_u64(hero + DMG.HERO_STATS_OFF)
    if not _ptr_plausible(rec) then return nil end
    return {
        dealt = I.read_u32(rec + DMG.STATS_TOTAL_OFF),
        best  = I.read_f32(rec + DMG.STATS_BEST_OFF),
    }
end

end
