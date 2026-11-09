-- R.camera — read and change the in-run TOP-DOWN camera while the game runs.
--
-- WHAT THE CAMERA IS. The gameplay view is not code: Hero_Common.entity carries
-- three `oCEntityCpntTopDownCameraSettings` components — "Default Camera" (the
-- in-run view), "Zoom Camera" and "Ultimate Trigger Zoom Camera" — and every
-- hero instantiates an `oCEntityCpntTopDownCamera` per settings object.
--
-- WHY A LIVE WRITE WORKS. The component binds each settings field once
-- (vftable slot 5, 0x1407e8230 on the 2026-10 build): a LINKED field gets a
-- binding object, but a LITERAL field's slot keeps only a pointer to the
-- settings record and copies nothing (binder 0x140274ba0 returns early when
-- record+0x58 == -1). Every read of a literal therefore goes back to the
-- settings record, so writing the record's number changes the camera on its
-- next update. A linked field (Default Camera's FOV follows "Camera FOV
-- Operation") is refused: its inline number is never read.
--
-- LAYOUT (settings object, from its ctor 0x1407e7770 + deserializer
-- 0x1407e7d50). Value records sit at +0xf8 + 0x80*i; the union is at record
-- +0x60: inline sentinel +0x68 (== 4), value +0x70, type byte +0x78 (0 = f32).
-- The manifest's value_N fields map to records in file order, so value_7 is
-- +0x3f8. ★ yaw (value_7) is PROVEN IN GAME (2026-10-02, data edit 45°→135°
-- rotated the view). The other names are read off comparing the three shipped
-- cameras and are NOT yet proven — `R.camera.FIELDS` marks which is which.
--
-- Components are found by RTTI class name through R.entity.components, never
-- by a vftable address, so a game patch that moves the vtable does not matter.
-- Every read is page-guarded and every write is preceded by the full record
-- check, so a moved layout means `nil, reason`, never a bad write.

local M = {}

local R, I

local CAMERA_CLASS   = "oCEntityCpntTopDownCamera"
local SETTINGS_CLASS = "oCEntityCpntTopDownCameraSettings"
local CPNT_SETTINGS  = 0x10      -- component -> its settings object
local UNION          = 0x60      -- record -> oCEntityValueUnion
local U_SENTINEL     = 0x08      -- == 4 when the value is stored inline
local U_VALUE        = 0x10
local U_TYPE         = 0x18      -- 0 = f32, 2 = bool
local REC_LINK       = 0x58      -- u32 picker index; 0xffffffff = literal

-- name -> { record offset, unit, proven, spread }. `deg` fields are radians in
-- the file.
--
-- `spread` is how a change to the default camera carries to the hero's other
-- cameras. The game swaps the default camera out for whole stretches of play,
-- not just for an ultimate: Kintaro on foot uses his own "Shared Camera"
-- (Hero_Kintaro, Base\Child State Alt Form), Melusine's Sing Stance her "Wisp
-- Camera", and the Baba Yaga house a boss "Camera TopDown" (1.06 cooked data).
-- A field set on the default camera only snapped back to the shipped value for
-- as long as any of those was active (camera-control on Kintaro, 2026-10-29).
-- Kintaro's and Melusine's are components of the hero entity, so cameras()
-- finds them (the Kintaro clip kept its yaw across the switch). The boss camera
-- belongs to a map object, which this module does not reach yet.
-- Copying one number to every camera would erase what makes them differ (the
-- ultimate camera's look height is 0.5, the boss camera's distance 36), so:
--   "abs"  every camera gets the same value;
--   "add"  every camera moves by the default camera's change from its original;
--   "mul"  every camera scales by the default camera's ratio to its original.
-- nil leaves the other cameras alone: the ultimate cameras zoom by FOV (27.5
-- against the default's 31), so a shared FOV would cancel the zoom.
M.FIELDS = {
    yaw      = { off = 0x3f8, unit = "deg", proven = true,  spread = "abs" },
    pitch    = { off = 0x278, unit = "deg", proven = false, spread = "add" },
    distance = { off = 0x2f8, unit = "raw", proven = false, spread = "mul" },
    fov      = { off = 0x378, unit = "raw", proven = false },
    height   = { off = 0x478, unit = "raw", proven = false, spread = "add" },
}
local DEFAULT_FLAG = 0xf8        -- value_16: true on "Default Camera" only

-- settings ptr .. ":" .. off -> { at, v = original, w = what we last wrote }.
-- `w` tells a record we changed from one the game rebuilt: when the number
-- there is no longer ours, it is the new original.
local _orig = {}

local function _original(settings, off, at)
    local now = I.read_f32(at)
    if now == nil then return nil end
    local key = ("%x:%x"):format(settings, off)
    local o = _orig[key]
    if o == nil or o.at ~= at or (o.w ~= nil and now ~= o.w) then
        o = { at = at, v = now }
        _orig[key] = o
    end
    return o.v, o
end

local function _plausible(p)
    return type(p) == "number" and p ~= 0 and R.ptr and R.ptr.plausible(p)
end

local function _is(obj, cls)
    local n = R.rtti and R.rtti.name and R.rtti.name(obj)
    if type(n) ~= "string" then return false end
    -- "oe::oCEntityCpntTopDownCamera" ends with the class; the settings class
    -- shares the prefix, so require the name to END there.
    return n:sub(-#cls) == cls
end

-- Class name for a SEARCH: only objects whose first word is a vftable inside
-- the game image, and looked up once per vftable. R.rtti.name is a dozen
-- guarded reads plus a string; called on every pointer a search met, it made
-- one search take ~13 s (2026-11-08). _is() stays uncached for the checks
-- that guard a write.
local _vt_cls = {}
local function _cls(p)
    local vt = I.read_u64(p)
    if not (vt and R.ptr and R.ptr.in_image and R.ptr.in_image(vt)) then return nil end
    local c = _vt_cls[vt]
    if c == nil then
        c = R.rtti and R.rtti.name and R.rtti.name(p) or false
        _vt_cls[vt] = c
    end
    return c or nil
end

-- A class name without its namespace, for log paths.
local function _short(c) return (c:gsub("^.*::", "")) end

-- The record's inline f32, or nil + reason. `write` is checked the same way.
local function _record(settings, off)
    local rec = settings + off
    local link = I.read_u32(rec + REC_LINK)
    if link == nil then return nil, "settings unreadable" end
    if link ~= 0xffffffff then return nil, "linked to another value (not a plain number)" end
    if I.read_u64(rec + UNION + U_SENTINEL) ~= 4 then return nil, "value not stored inline" end
    if I.read_u8(rec + UNION + U_TYPE) ~= 0 then return nil, "not a float" end
    return rec + UNION + U_VALUE
end

-- Entities that may own the cameras. The captured hero, its value context and
-- its owner are the obvious ones, but the first launch (2026-10-02) found no
-- camera on any of them, the same wall the XP lookup hit: the component-owning
-- oCEntity hangs off another field. So every pointer field of the hero and the
-- context is probed too, and a probed object counts only when EVERY entry of
-- its component array points back at it (comp+0x08 == entity) — a loose
-- "plausible array" is how a heap coincidence gets accepted.
local function _owns_its_components(e)
    local list = R.entity.components(e)
    if not list or #list == 0 then return nil end
    for _, c in ipairs(list) do
        if I.read_u64(c.ptr + 0x08) ~= e then return nil end
    end
    return list
end

-- The oCEntity's REAL component store: an open-addressed class-id map, slots
-- of { u32 class_id; u64 component } at entity+0x5f0, bucket mask at +0x600
-- (R.net._k; Entity_GetNetComponent). The +0x190 array R.entity.components
-- walks is not it — the second launch (2026-10-02) read 238 components there
-- across three entities and no camera. Walked whole rather than looked up by
-- id, since the hero has three cameras of the one class.
local function _map_components(e)
    local k = R.net and R.net._k
    if not k then return {} end
    local slots, mask = I.read_u64(e + k.SLOTS), I.read_u64(e + k.MASK)
    if not _plausible(slots) or type(mask) ~= "number" or mask < 0 or mask >= k.MAX then
        return {}
    end
    local out = {}
    for i = 0, mask do
        local v = I.read_u64(slots + i * 0x10 + 8)
        if _plausible(v) and I.read_u32(slots + i * 0x10) ~= 0 then out[#out + 1] = { ptr = v } end
    end
    return out
end

local _owners_for, _owners = nil, nil

local function _entities(hero)
    if hero == _owners_for and _owners then return _owners end
    local out, seen = {}, {}
    local function consider(e, direct)
        if not _plausible(e) or seen[e] then return end
        seen[e] = true
        local list = (direct and R.entity.components(e) or _owns_its_components(e)) or {}
        -- The class-id map only on a real oCEntity: a probed pointer field is
        -- anything, and its +0x5f0 is someone else's memory.
        local n = _cls(e)
        if type(n) == "string" and n:sub(-8) == "oCEntity" then
            for _, c in ipairs(_map_components(e)) do list[#list + 1] = c end
        end
        if #list > 0 then out[#out + 1] = { entity = e, components = list } end
    end
    local ctx = I.read_u64(hero + 0x2f8)
    for _, e in ipairs({ hero, ctx, I.read_u64(hero + 0x08) }) do consider(e, true) end
    for _, base in ipairs({ hero, ctx }) do
        if _plausible(base) then
            for off = 0, 0x7f8, 8 do consider(I.read_u64(base + off), false) end
        end
    end
    _owners_for, _owners = hero, out
    return out
end

-- Bounded pointer search from the hero objects, for the cameras' real home.
-- Three launches found no camera in the hero entities' +0x190 arrays or
-- class-id maps (238 + 7 components), so the controller keeps them somewhere
-- else. This follows plausible pointers breadth-first, up to `depth` hops and
-- `budget` objects, and records the field path to every object whose RTTI
-- names a TopDown camera or its settings. Page-guarded reads only.
--
-- It is a JOB advanced a few milliseconds per call, never run whole. Run whole
-- it took long enough (2500 objects x 256 reads, each with an RTTI lookup) to
-- hold the Lua state for seconds, and the game thread's Lua hooks (the damage
-- meter's) waited on it: the game froze on every hero change, worst while dead
-- and spectating, when it ran four times a tick (2026-11-08).
local function _now() return (I.now and I.now()) or os.clock() end

local function _search_new(roots, depth, budget)
    local job = { hits = {}, seen = {}, queue = {}, qi = 1, n = 0, depth = depth, budget = budget }
    for _, r in ipairs(roots) do
        if _plausible(r.ptr) and not job.seen[r.ptr] then
            job.seen[r.ptr] = true
            job.queue[#job.queue + 1] = { ptr = r.ptr, path = r.name, d = 0 }
        end
    end
    return job
end

-- Advance `job` for about `slice` seconds; true once it is finished.
local function _search_step(job, slice)
    local stop = _now() + slice
    local unpack = string.unpack
    while job.qi <= #job.queue and job.n < job.budget do
        local node = job.queue[job.qi]; job.qi = job.qi + 1; job.n = job.n + 1
        -- One guarded read for the object's first 0x800 bytes (it may come
        -- back shorter near the end of a mapping), not 256 single reads.
        local blk = I.read_block and I.read_block(node.ptr, 0x800)
        local n = blk and (#blk // 8) or 256
        for i = 0, n - 1 do
            local off = i * 8
            local p
            if blk then p = unpack("<i8", blk, off + 1) else p = I.read_u64(node.ptr + off) end
            if _plausible(p) and not job.seen[p] then
                job.seen[p] = true
                local cls = _cls(p)
                local path = cls and ("%s+0x%x[%s]"):format(node.path, off, _short(cls))
                    or ("%s+0x%x"):format(node.path, off)
                if cls and cls:find("TopDownCamera", 1, true) then
                    job.hits[#job.hits + 1] = { ptr = p, cls = cls, path = path, d = node.d + 1 }
                elseif node.d + 1 < job.depth then
                    job.queue[#job.queue + 1] = { ptr = p, path = path, d = node.d + 1 }
                end
            end
        end
        if _now() >= stop then break end
    end
    return job.qi > #job.queue or job.n >= job.budget
end

-- Where the search starts: the controller, its owner and value context, every
-- entity found, and each entity's template (+0x28).
local function _roots(hero, owners)
    local roots = {
        { ptr = hero, name = "hero" },
        { ptr = I.read_u64(hero + 0x08), name = "hero.owner" },
        { ptr = I.read_u64(hero + 0x2f8), name = "hero.ctx" },
    }
    for i, o in ipairs(owners) do
        roots[#roots + 1] = { ptr = o.entity, name = ("entity%d"):format(i) }
        roots[#roots + 1] = { ptr = I.read_u64(o.entity + 0x28), name = ("entity%d.template"):format(i) }
    end
    return roots
end

local _miss_logged = false

-- Once per session: what was searched, so a miss is one launch, not five.
local function _log_miss(hero, owners, hits, visited)
    if _miss_logged then return end
    _miss_logged = true
    R.log(("[rsmm.camera] no camera: hero=0x%x (%s), %d entity(ies) with components")
        :format(hero, tostring(R.rtti.name(hero)), #owners))
    for _, o in ipairs(owners) do
        local cams = {}
        for _, c in ipairs(o.components) do
            local n = R.rtti.name(c.ptr)
            if type(n) == "string" and n:find("Camera", 1, true) then cams[#cams + 1] = n end
        end
        local sample = {}
        for i = 1, math.min(6, #o.components) do
            sample[i] = tostring(R.rtti.name(o.components[i].ptr))
        end
        R.log(("[rsmm.camera]   0x%x %s: %d components, camera-like: %s; e.g. %s"):format(
            o.entity, tostring(R.rtti.name(o.entity)), #o.components,
            #cams > 0 and table.concat(cams, ", ") or "none", table.concat(sample, ", ")))
    end
    R.log(("[rsmm.camera] pointer search: %d object(s) visited, %d camera hit(s)")
        :format(visited or 0, #hits))
    for i = 1, math.min(#hits, 24) do
        R.log("[rsmm.camera]   " .. hits[i].path .. " = " .. hits[i].cls)
    end
end

local _cams_for, _cams = nil, nil

local function _default_flag(s)
    local flag = s + DEFAULT_FLAG + UNION
    return I.read_u64(flag + U_SENTINEL) == 4
        and I.read_u8(flag + U_TYPE) == 2 and I.read_u8(flag + U_VALUE) == 1
end

-- A cached list stays good while every entry still has its classes.
local function _still_valid(list)
    for _, c in ipairs(list) do
        if not _is(c.settings, SETTINGS_CLASS) then return false end
        if c.component and not _is(c.component, CAMERA_CLASS) then return false end
    end
    return #list > 0
end

--- Every live top-down camera of the local hero:
--- `{ { component=, settings=, default=<bool> }, ... }`, or nil + reason.
--- `component` is nil for a settings object found without its component.
---
--- The cameras are NOT hero components: three launches (2026-10-02) read every
--- component of the hero's four entities (+0x190 arrays and class-id maps)
--- without one. The fourth found them by pointer search, three hops out —
--- `hero+0x1e0+0x2b0+0x548` and `hero+0x300+0x568+0x160` (components) and
--- `hero.owner+0x640+0x70` (settings). Those hops cross heap objects with no
--- known meaning, so they are not hard-coded: the search (see _search_step)
--- runs a slice per call until done, and only RTTI-confirmed objects are kept.
--- Each camera component's own entity (+0x08) is then read for its siblings.
---
--- A hero's own cameras come and go: Kintaro's "Shared Camera" belongs to his
--- on-foot state (Child State Alt Form) and is found only while he is on foot,
--- and the one found at run start is not the one in use after a remount
--- (2026-11-08: one launch found only it, the next only the default camera).
--- So the cheap pass over the hero's entities is redone every RESCAN seconds.
--- What the search finds is kept for the session, across hero changes, while
--- its classes hold: the default camera is one object for every form Kintaro
--- takes, and every transform, death and respawn is a new captured hero. A
--- search runs only while no default camera is known, at most once per hero
--- per RESEARCH seconds. Compare the list's settings pointers to notice a
--- camera that appeared (camera-control re-applies then).
local RESCAN, RESEARCH = 1.0, 15
-- Seconds of search per slice. Timers fire on the loader's 500 ms "tick", so
-- this is the search's share of each half second, not of 25 ms.
M.SEARCH_SLICE = 0.025
-- Where the search found the cameras on the 2026-10 build (see above), as
-- field offsets from the hero: two to a camera component, one to a settings
-- object (through hero.owner).
local PATHS = {
    { 0x1e0, 0x2b0, 0x548 },
    { 0x300, 0x568, 0x160 },
    { 0x08, 0x640, 0x70 },
}
local _scan_at, _none = nil, nil -- _none: the reason, while the hero has no camera
local _known = {}                -- settings ptr -> entry, from searches
local _job, _job_for = nil, nil
local _searched = {}             -- hero -> when its last search ended

local function _alive(c)
    return _is(c.settings, SETTINGS_CLASS) and (not c.component or _is(c.component, CAMERA_CLASS))
end

-- The search after its first slice runs on its own timer, one slice every
-- STEP_EVERY seconds, so its share of the loader thread stays small however
-- often cameras() is called. cameras() only picks up the finished result.
local STEP_EVERY = 0.025
local _hit_logged = false
local _job_done, _pumping = nil, false

--- One slice of a running search; false when there is nothing left to do.
function M._search_pump()
    local job = _job
    if not job then _pumping = false; return false end
    if _search_step(job, M.SEARCH_SLICE) then
        _job, _job_done, _pumping = nil, job, false
        return false
    end
    return true
end

local function _start_pump()
    if _pumping or not (R.schedule and R.schedule.after) then return end
    _pumping = true
    local function tick()
        if M._search_pump() then R.schedule.after(STEP_EVERY, tick) end
    end
    R.schedule.after(STEP_EVERY, tick)
end

-- WHERE THE CAMERAS ACTUALLY ARE (read live from outside the game, 2026-11-08,
-- Kintaro + Beowulf co-op): plain components in the HERO ENTITY's +0x190
-- component array, owner (+0x08) == that entity. Kintaro's entity held Shared
-- Camera and both Ultimate Ability 1 cameras at [1043..1045] and Default /
-- Ultimate Trigger Zoom / Zoom at [3004..3006] of 3880 components; Beowulf's
-- held the three shared ones at [2662..2664] of 3538. R.entity.components
-- refuses any array over 256 ("a real entity has tens"), so every pass above
-- saw nothing and the slow search was the only way in: the 8-minute wait.
--
-- Every hero in the match is read, not only the captured one: in that session
-- capture had taken the ally's controller, and Kintaro's own cameras were on
-- the other entity. The candidate ring (shared slots 8..15) holds one
-- controller per hero. A camera's settings object is shared by every hero that
-- uses it ("Default Camera" was one object behind both heroes' components),
-- and a camera only drives the screen of the machine it runs on, so writing an
-- ally's is harmless.
local ENT_CPNTS, ENT_COUNT, ENT_MAX = 0x190, 0x198, 16384
local HERO_RING_FIRST, HERO_RING_COUNT = 8, 8
local _ent_cache = {}            -- entity -> { arr, n, idx = { camera slots } }

local function _is_camera_cpnt(cp)
    local c = _plausible(cp) and _cls(cp)
    return c and c:sub(-#CAMERA_CLASS) == CAMERA_CLASS or false
end

-- Hero controllers worth reading: the captured one and every live ring entry.
local function _hero_controllers(hero)
    local out, seen = {}, {}
    local function add(h)
        if _plausible(h) and not seen[h] then seen[h] = true; out[#out + 1] = h end
    end
    add(hero)
    if I.shared_get then
        for i = 0, HERO_RING_COUNT - 1 do
            local ok, h = pcall(I.shared_get, HERO_RING_FIRST + i)
            if ok and type(h) == "number" and h ~= 0
                    and not (R.entity._retired and R.entity._retired(h))
                    and (not R.entity._is_hero_object or R.entity._is_hero_object(h)) then
                add(h)
            end
        end
    end
    return out
end

-- The camera components in entity `e`'s full component array. The array is
-- read in blocks; the slots that held cameras are remembered, so while the
-- array itself is unchanged only those few slots are re-read.
local function _entity_cameras(e)
    if not _plausible(e) then return {} end
    local arr, n = I.read_u64(e + ENT_CPNTS), I.read_u32(e + ENT_COUNT)
    if not (_plausible(arr) and n and n > 0 and n <= ENT_MAX) then return {} end
    local c = _ent_cache[e]
    if c and c.arr == arr and c.n == n then
        local out = {}
        for _, i in ipairs(c.idx) do
            local cp = I.read_u64(arr + i * 8)
            if _is_camera_cpnt(cp) then out[#out + 1] = cp end
        end
        if #out == #c.idx then return out end
    end
    local idx, out, unpack = {}, {}, string.unpack
    local i = 0
    while i < n do
        local take = math.min(n - i, 0x2000)          -- read_block caps at 64 KB
        local blk = I.read_block and I.read_block(arr + i * 8, take * 8)
        for j = 0, take - 1 do
            local cp
            if blk and #blk >= (j + 1) * 8 then
                cp = unpack("<i8", blk, j * 8 + 1)
            else
                cp = I.read_u64(arr + (i + j) * 8)
            end
            if _is_camera_cpnt(cp) then idx[#idx + 1] = i + j; out[#out + 1] = cp end
        end
        i = i + take
    end
    _ent_cache[e] = { arr = arr, n = n, idx = idx }
    return out
end

function M.cameras()
    if not (I and I.read_u64 and I.read_u32 and I.read_u8) then return nil, "loader too old" end
    local hero = R.entity and R.entity.hero and R.entity.hero()
    if not hero then return nil, "hero not captured (start a run)" end
    local now = _now()
    if hero == _cams_for and not _job_done and _scan_at and now - _scan_at < RESCAN then
        if _none then return nil, _none end
        if _cams and _still_valid(_cams) then return _cams end
    end

    local out, seen = {}, {}
    local function add_settings(s, c)
        if not _plausible(s) or seen[s] or not _is(s, SETTINGS_CLASS) then return end
        seen[s] = true
        out[#out + 1] = { component = c, settings = s, default = _default_flag(s) }
    end
    local function add_component(c)
        if _plausible(c) and _is(c, CAMERA_CLASS) then
            add_settings(I.read_u64(c + CPNT_SETTINGS), c)
        end
    end
    local function add_entity(e)
        if not _plausible(e) then return end
        for _, c in ipairs(R.entity.components(e) or {}) do add_component(c.ptr) end
        local n = R.rtti.name(e)
        if type(n) == "string" and n:sub(-8) == "oCEntity" then
            for _, c in ipairs(_map_components(e)) do add_component(c.ptr) end
        end
    end

    local function has_default()
        for _, c in ipairs(out) do if c.default then return true end end
        return false
    end

    -- First and normally only pass: every hero entity's full component array
    -- (see _entity_cameras). The controller itself is read too, since a test
    -- double or a future build may hand back the entity directly.
    for _, h in ipairs(_hero_controllers(hero)) do
        for _, e in ipairs({ I.read_u64(h + 0x08), h }) do
            for _, cp in ipairs(_entity_cameras(e)) do add_component(cp) end
        end
    end

    -- Fallbacks, only while no default camera turned up there.
    local owners = {}
    if not has_default() then
        _owners_for, _owners = nil, nil
        owners = _entities(hero)
        for _, o in ipairs(owners) do
            for _, c in ipairs(o.components) do add_component(c.ptr) end
        end
    end
    -- What earlier searches found, for any hero, while it is still there.
    for s, c in pairs(_known) do
        if _alive(c) then add_settings(c.settings, c.component) else _known[s] = nil end
    end
    -- The paths the search found before, tried first: a handful of reads, and
    -- the class check at the end makes a stale path a miss, never a wrong
    -- camera. The sliced search alone took over 30 s to reach the camera (Kintaro,
    -- 2026-11-08), and nothing applied until it did.
    if not has_default() then
        local first = #out + 1
        for _, path in ipairs(PATHS) do
            local p = hero
            for _, off in ipairs(path) do
                p = _plausible(p) and I.read_u64(p + off) or nil
            end
            if _plausible(p) then
                if _is(p, CAMERA_CLASS) then
                    add_component(p)
                    add_entity(I.read_u64(p + 0x08))
                else
                    add_settings(p, nil)
                end
            end
        end
        for i = first, #out do _known[out[i].settings] = out[i] end
    end
    -- A search for another hero, or for a default camera now known, is moot.
    if has_default() or _job_for ~= hero then _job = nil end
    if _job_done and (has_default() or _job_done.hero ~= hero) then _job_done = nil end
    if not has_default() and not _job and not _job_done
            and (_searched[hero] == nil or now - _searched[hero] >= RESEARCH) then
        _job, _job_for = _search_new(_roots(hero, owners), 3, 2500), hero
        _job.hero = hero
        -- First slice now (a small or mocked search ends here), the rest timed.
        if _search_step(_job, M.SEARCH_SLICE) then
            _job_done, _job = _job, nil
        else
            _start_pump()
        end
    end
    if _job_done then
        local job = _job_done
        _job_done, _job_for, _searched[hero] = nil, nil, now
        local first = #out + 1
        for _, h in ipairs(job.hits) do
            if h.cls:sub(-#CAMERA_CLASS) == CAMERA_CLASS then
                add_component(h.ptr)
                add_entity(I.read_u64(h.ptr + 0x08))
            else
                add_settings(h.ptr, nil)
            end
        end
        for i = first, #out do _known[out[i].settings] = out[i] end
        -- Say what the search saw (once per session); a list without the
        -- default camera is kept anyway, since yaw still reaches it.
        if not has_default() then
            _log_miss(hero, owners, job.hits, job.n)
        elseif not _hit_logged then
            -- Where it was, so PATHS can be corrected from one log.
            _hit_logged = true
            R.log(("[rsmm.camera] search found the camera after %d object(s); paths:"):format(job.n))
            for i = 1, math.min(#job.hits, 12) do
                R.log("[rsmm.camera]   " .. job.hits[i].path .. " = " .. job.hits[i].cls)
            end
        end
    end

    _cams_for, _scan_at = hero, now
    if #out == 0 then
        _cams = nil
        _none = _job and "looking for the camera (search under way)" or "no top-down camera on the hero"
        return nil, _none
    end
    _cams, _none = out, nil
    return out
end

local function _field(name)
    local f = M.FIELDS[name]
    if not f then error("R.camera: unknown field '" .. tostring(name) .. "'", 3) end
    return f
end

local function _to_file(f, v) return f.unit == "deg" and math.rad(v) or v end
-- `v` is a guarded read, so nil when the page went away under us (a chapter
-- teardown); nil passes through rather than raising in math.deg.
local function _from_file(f, v)
    if v == nil then return nil end
    return f.unit == "deg" and math.deg(v) or v
end

--- The default camera's `name` (degrees for yaw/pitch), or nil + reason.
function M.get(name)
    local f = _field(name)
    local cams, why = M.cameras()
    if not cams then return nil, why end
    for _, c in ipairs(cams) do
        if c.default then
            local at, err = _record(c.settings, f.off)
            if not at then return nil, err end
            local v = _from_file(f, I.read_f32(at))
            if v == nil then return nil, "the camera record is no longer readable" end
            return v
        end
    end
    return nil, "no default camera found"
end

local function _write(c, f, at, v)
    local _, o = _original(c.settings, f.off, at)
    if not o then return false end
    I.write_f32(at, v)
    o.w = I.read_f32(at)         -- as stored (f32), so the next compare is exact
    return true
end

--- Set `name` live: the default camera takes `value`, and the hero's other
--- cameras follow by the field's `spread` (see FIELDS), so the view keeps the
--- setting when the game switches cameras. `opts.all = true` writes `value` to
--- every camera as is; `opts.all = false` writes the default camera only.
--- Returns the number of cameras written, or nil + reason.
function M.set(name, value, opts)
    local f = _field(name)
    if type(value) ~= "number" or value ~= value then return nil, "value must be a number" end
    if not I.write_f32 then return nil, "loader too old" end
    local spread = f.spread
    if opts and opts.all == true then spread = "abs" end
    if opts and opts.all == false then spread = nil end
    local cams, why = M.cameras()
    if not cams then return nil, why end
    local want = _to_file(f, value)

    -- The default camera's original is what "add" and "mul" are measured from.
    local base
    if spread == "add" or spread == "mul" then
        for _, c in ipairs(cams) do
            if c.default then
                local at = _record(c.settings, f.off)
                if at then base = _original(c.settings, f.off, at) end
                if base then break end
            end
        end
        if spread == "mul" and base == 0 then base = nil end
        -- No readable default original: change only what was asked for.
        if base == nil then spread = nil end
    end

    local n, last = 0, nil
    for _, c in ipairs(cams) do
        if c.default or spread then
            local at, err = _record(c.settings, f.off)
            if at then
                local v = want
                if not c.default and spread ~= "abs" then
                    local orig = _original(c.settings, f.off, at)
                    if orig == nil then
                        v = nil
                    elseif spread == "add" then
                        v = orig + (want - base)
                    else
                        v = orig * (want / base)
                    end
                end
                if v ~= nil and _write(c, f, at, v) then
                    n = n + 1
                else
                    last = "the camera record is no longer readable"
                end
            else
                last = err
            end
        end
    end
    if n == 0 then
        return nil, last or ("no default camera among the %d found"):format(#cams)
    end
    return n
end

--- Put back every value R.camera changed this session.
function M.reset()
    local n = 0
    for key, o in pairs(_orig) do
        -- Only a number that is still ours: a record the game rebuilt since
        -- already holds its own value, and one we only read was never changed.
        if o.w ~= nil and I.read_f32(o.at) == o.w then I.write_f32(o.at, o.v); n = n + 1 end
        _orig[key] = nil
    end
    return n
end

--- One log line per camera: which is default, and every field's value or why
--- it cannot be read. For the first launch on a new build.
function M.describe()
    local cams, why = M.cameras()
    if not cams then R.log("[rsmm.camera] " .. why); return end
    for i, c in ipairs(cams) do
        local parts = {}
        for name, f in pairs(M.FIELDS) do
            local at, err = _record(c.settings, f.off)
            local v = at and _from_file(f, I.read_f32(at))
            parts[#parts + 1] = name .. "=" .. (v and ("%.3f"):format(v) or err or "unreadable")
        end
        table.sort(parts)
        R.log(("[rsmm.camera] #%d %s settings=0x%x %s"):format(
            i, c.default and "default" or "other", c.settings, table.concat(parts, " ")))
    end
end

--- DIAGNOSTIC. Search from the hero (and the scene, when R.run has seen the
--- world) for EVERY top-down camera and log where each one sits: the pointer
--- path with the class of each hop, the owning entity, whether it is the
--- default camera, and its values. Runs whole, capped at `opts.limit` seconds
--- (default 3), so the game can stall that long: for a run meant to map where
--- the cameras live, never for a mod's normal poll.
function M.explore(tag, opts)
    opts = opts or {}
    tag = tostring(tag or "manual")
    if not (I and I.read_u64 and R.entity and R.entity.hero) then return end
    local hero = R.entity.hero()
    if not hero then R.log("[rsmm.camera] explore " .. tag .. ": no hero captured"); return end
    local t0 = _now()
    _owners_for, _owners = nil, nil
    local owners = _entities(hero)
    local roots = _roots(hero, owners)
    local scene = R.run and R.run.world_owner and R.run.world_owner()
    if scene then roots[#roots + 1] = { ptr = scene, name = "scene" } end
    local job = _search_new(roots, opts.depth or 4, opts.budget or 6000)
    local done = _search_step(job, opts.limit or 3.0)
    R.log(("[rsmm.camera] explore %s: hero=0x%x %s, scene=%s; %d object(s) in %.2f s%s; %d camera object(s)")
        :format(tag, hero, tostring(R.rtti.name(hero)),
                scene and ("0x%x"):format(scene) or "not seen yet",
                job.n, _now() - t0, done and "" or " (STOPPED at the time cap)", #job.hits))
    for _, o in ipairs(owners) do
        for _, c in ipairs(o.components) do
            local n = R.rtti.name(c.ptr)
            if type(n) == "string" and n:find("TopDownCamera", 1, true) then
                R.log(("[rsmm.camera]   on hero entity 0x%x %s: 0x%x %s"):format(
                    o.entity, tostring(R.rtti.name(o.entity)), c.ptr, n))
            end
        end
    end
    for i, h in ipairs(job.hits) do
        local s, comp = h.ptr, nil
        if h.cls:sub(-#CAMERA_CLASS) == CAMERA_CLASS then
            comp, s = h.ptr, I.read_u64(h.ptr + CPNT_SETTINGS)
        end
        local vals = {}
        if _plausible(s) and _is(s, SETTINGS_CLASS) then
            for _, name in ipairs({ "distance", "pitch", "yaw", "height", "fov" }) do
                local f = M.FIELDS[name]
                local at, err = _record(s, f.off)
                local v = at and _from_file(f, I.read_f32(at))
                vals[#vals + 1] = name .. "=" .. (v and ("%.2f"):format(v) or (err and "linked" or "?"))
            end
        end
        local owner = comp and I.read_u64(comp + 0x08)
        R.log(("[rsmm.camera]   #%d %s %s, depth %d: %s"):format(i,
            comp and "component" or "settings",
            (_plausible(s) and _default_flag(s)) and "DEFAULT" or "other", h.d or 0, h.path))
        R.log(("[rsmm.camera]      settings=0x%x owner=%s %s"):format(s or 0,
            _plausible(owner) and ("0x%x %s"):format(owner, tostring(R.rtti.name(owner))) or "-",
            table.concat(vals, " ")))
    end
    return job.hits
end

return function(env)
    R, I = env.R, env.I
    return M
end
