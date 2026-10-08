-- R.damage, part 3: the NETCODE joins -- sessions, net ids, RakPeer systems and connections, and R.net.*.
--
-- Split out of rsmm/damage.lua (2026-09-26), which loads it; see that file's
-- header for the meter as a whole. Everything here is defined on the shared
-- `F` / `R` tables or on the `_dmg` / `DMG` tables damage.lua owns, so it
-- runs the same as it did inline. The env is checked against an explicit key
-- list: a nil value is no key in Lua, so a pairs() sweep would see nothing.

return function(env)

for _, key in ipairs({ "I", "R", "F", "DMG", "_dmg", "_va_ok", "_ptr_plausible", "LOBBY_HOOK" }) do
    if env[key] == nil then
        error("rsmm.damage_netcode: parent did not pass env." .. key, 0)
    end
end

local I, R, F          = env.I, env.R, env.F
local DMG, _dmg        = env.DMG, env._dmg
local _va_ok, _ptr_plausible = env._va_ok, env._ptr_plausible
local LOBBY_HOOK       = env.LOBBY_HOOK

--- Expose the session matcher for the spec and for diagnosing a build where
--- the representations do not line up.
function R.damage._session_matches(n, text)
    return F._dmg_session_matches(n, text)
end

--- Drive the session join directly. Spec and diagnostics only; in game the
--- gameplay bus feeds it (see the R.on("*") handler below).
function R.damage._session_join(entity, session)
    return F._dmg_note_session(entity, session)
end

--- Drive the cheap identity paths by hand, exactly as the 1 Hz tick does
--- (the spec). Does NOT include the blind sweep, which is opt-in.
function R.damage._identity_tick()
    F._dmg_relabel()
    F._dmg_backfill_ids()
    F._dmg_netid_pass()
    return F._dmg_probe_owner_fast()
end

--- Record a member's peer id (the spec); the lobby hook does this from the
--- parsed attribute blob.
function R.lobby._note_eos(name, id)
    for _, e in ipairs(LOBBY_HOOK.order) do
        if e.name == name then e.eos = id; return true end
    end
    return false
end

--- Drive the label hint by hand (the spec); the meter's tick calls it.
function R.damage._label_hint()
    return F._dmg_label_hint()
end

--- Is a string well-formed UTF-8? (test/diagnostic seam for F._utf8_ok.)
function R.damage._utf8_ok(t) return F._utf8_ok(t) end

--- Drive one net-id pass by hand (diagnostics and the spec); the meter's own
--- tick already calls this once a second.
--- The engine's peer table as the join sees it (test/diagnostic seam).
function R.damage._peer_join() return F._dmg_peer_join() end

--- The connection-record join (test/diagnostic seam).
function R.damage._conn_join() return F._dmg_conn_join() end

--- The RakNet remote-system join (test/diagnostic seam).
function R.damage._rak_join() return F._dmg_rak_join() end

--- The RakNet remote-system table as the join reads it (diagnostic seam).
function R.damage._rak_systems() return F._dmg_rak_systems() end

function R.damage._netid_pass()
    return F._dmg_netid_pass()
end

--- The adopted net-id locator, or a table with `off == nil` while discovery is
--- still running. Read-only: a caller must not be able to adopt one by hand.
function R.damage._netid()
    local path
    if F._netid.path then
        path = {}
        for i, v in ipairs(F._netid.path) do path[i] = v end
    end
    -- A COPY of the path: the adopted locator is the one thing a caller must
    -- not be able to edit from outside.
    return { off = F._netid.off, path = path, kind = F._netid.kind }
end

--- Does the int64 session id `n` and the member's session STRING refer to the
--- same session? Exact match against every plausible text form, never a
--- "close enough". The point of this whole path is that it cannot invent an
--- answer; a fuzzy compare would hand that property straight back.
function F._dmg_session_forms(n)
    local hex = ("%016x"):format(n)
    -- Byte-reversed, for a little-endian half of a GUID printed big-endian.
    local swapped = hex:gsub("(%x%x)", function(b) return b end)
    local rev = {}
    for i = 15, 1, -2 do rev[#rev + 1] = hex:sub(i, i + 1) end
    swapped = table.concat(rev)
    return { ("%d"):format(n), ("%x"):format(n), ("%X"):format(n),
             ("0x%x"):format(n), ("0x%X"):format(n),
             hex, hex:upper(), swapped, swapped:upper() }
end

--- Does the member's session id `text` contain this int64 as one of its halves?
---
--- The lobby's session id is a 128-bit GUID STRING, not an int64: session 8f36
--- logged "Ovilli" as "31b1a3aef8ce46e9a4d76be3c7526757", 32 hex characters.
--- The netcode path deals in 8 bytes (NamedEvent_NetSend stores a single
--- qword at ev+0x38), so if the two are the same identity at all, the qword
--- can only be one HALF of that GUID. Both halves and both byte orders are
--- tried; anything else would be a guess, and a guess is what this design
--- exists to refuse.
function F._dmg_session_halves(n, text)
    if type(text) ~= "string" or #text ~= 32 or text:find("[^0-9a-fA-F]") then
        return false
    end
    local lo, hi = text:sub(1, 16):lower(), text:sub(17, 32):lower()
    for _, form in ipairs(F._dmg_session_forms(n)) do
        local f = form:lower()
        if #f == 16 and (f == lo or f == hi) then return true end
    end
    return false
end

function F._dmg_session_matches(n, text)
    if type(n) ~= "number" or type(text) ~= "string" then return false end
    for _, form in ipairs(F._dmg_session_forms(n)) do
        if form == text then return true end
    end
    return F._dmg_session_halves(n, text)
end

--- The lobby member whose session id is `n`, or nil.
---
--- Requires EXACTLY ONE match. Two members answering to one session id means
--- the representation guess is wrong (e.g. a truncated form colliding), and a
--- collision must name nobody -- same rule the rest of the meter runs on.
function F._dmg_session_member(n)
    local ok, members = pcall(R.lobby.members)
    if not ok or type(members) ~= "table" then return nil end
    local hit, count = nil, 0
    for _, m in ipairs(members) do
        if type(m.session) == "string" and F._dmg_session_matches(n, m.session) then
            hit, count = m, count + 1
        end
    end
    if count == 1 then return hit end
    return nil
end

-- net-component peer id ----------------------------------------------------
--
-- The join the gameplay bus could not give us.
--
-- Sessions c536 and e736 settled ev+0x38: every event the bus dispatched in
-- either run carried the SAME vftable (0xf05aa8), i.e. the base
-- oCGameNamedEvent, and on the base class +0x38 is not a peer. The values it
-- held are handles (0x8146_00xx_00000004, 0x8075_00xx_000y_0004) and in one
-- case a raw code address (0x1463b00a2). So no gameplay event on this build
-- carries a sender, and F._dmg_note_session can never fire from it.
--
-- What DOES have to know the owner is the entity's NET COMPONENT: replication
-- routes by peer, so whatever replicates a remote hero must name the machine
-- driving it. The component is a separate allocation reached through the
-- component map, so the entity+0x2000 sweep never looked at it.
--
-- The needle is the lobby member's session id -- 32 hex characters, the same
-- string LobbyMembers_Local compares to find "everyone but me". A 128-bit
-- value matching by accident is not a risk worth modelling, and that is what
-- makes this different in kind from sweeping memory for a display name.
F._netid = {
    WIN    = 0x800,    -- bytes of the net component to inspect
    HOPWIN = 0x180,    -- bytes at each pointer the component holds
    off    = nil,      -- adopted offset, once a row's own session proves one
    path   = nil,      -- pointer path from the component, or nil for a direct read
    kind   = nil,      -- "string" | "qword-lo" | "qword-hi"
    hits   = {},       -- row.key -> hit list, from the one-shot discovery
    probed = {},       -- row.key -> true
    said   = false,
    counted = false,
    vft_said = false,
    guid_said = false,
    guid_proven = false,
    guid_done = false,   -- a refusal is final for the run: the gates said no
    -- The net component fields NamedEvent_NetSend dereferences by name.
    DEEP    = { 0xb8, 0xc0, 0xc8 },
    -- oCSLNetworkObject::vft[0x18]: *(*(*(C+0xb8)+0x100)+0x28) is the session
    -- this entity replicates to. Read straight off the decompile.
    OWNER_PATH = { 0xb8, 0x100, 0x28 },
    owner_said = 0,
    owner_vft_said = false,
    DEEPWIN = 0x200,   -- bytes of each of those objects to inspect
    MEMWIN = 0x100,    -- bytes of the lobby member object to harvest
    -- Netcode_PeerSlots / Netcode_PeerCount, the engine's own list of the
    -- other machines in the run. Baked VAs, so every read is gated on
    -- _va_ok(): a stale global is a plausible-looking pointer, not a nil.
    --
    -- ⚠ The base is 0x14143f600, NOT 0x14143f650. The tick's `lea rax,
    -- [rip+...]` lands on 0x14143f650 because it indexes slot+0x50 (the
    -- tunnel pointer) directly, so reading the array from there is off by
    -- 0x50 and every string comes back from the NEXT slot. The true base is
    -- what the slot ctor FUN_1402aedf0 zeroes, field by field.
    PEER_SLOTS  = 0x14143f600,
    PEER_COUNT  = 0x14143f780,
    PEER_STRIDE = 0x60,        -- `lea rax,[rax+rax*2]; shl rax,5` in the tick
    PEER_MAX    = 32,          -- refuse an implausible count outright
    -- Slot fields, all decompile-confirmed (FUN_1402aedf0 fills them,
    -- FUN_1402b5db0 frees them, FUN_1402b0170/FUN_1402b0230 look up by them).
    PEER_NAME    = 0x00,       -- PlayerName, straight off the parsed record
    PEER_SESSION = 0x10,       -- the lobby member's +0x00 session id
    PEER_EOS     = 0x20,       -- m_sEosUserId — the engine's "P2P User"
    PEER_HASH    = 0x30,       -- u64 hash of the EOS id (FUN_1402aed50)
    PEER_TUNNEL  = 0x50,       -- the P2P connection: +0xc0 port, +0xcc state
    PEER_STR    = { 0x00, 0x10, 0x20 },
    -- The two fields NamedEvent_NetSendToPeer (0x1407216c0) dereferences to
    -- unicast an event at ONE session, read straight off its disassembly:
    --
    --     rsi = [netcomp + 0xc8]              ; the scene
    --     rcx = [rsi + 0x28]                  ; the session manager
    --     call [[rcx] + 0x88](rcx, &out)      ; out = the LOCAL session id
    --     cmp  out, [target]                  ; skip a send to ourselves
    --     call [[rsi] + 0xc0](rsi, target, m) ; send to that session
    --
    -- So the engine routes by the SAME qword the replica calls
    -- creatingSystemGUID, and scene+0x28 is the object that owns the
    -- session->connection mapping. That is where a guid can become a peer.
    SCENE     = 0xc8,
    SCENE_MGR = 0x28,
    -- Stormancer::RakNetConnection + 0xf8 is the owning RakNetGUID, written
    -- by the ctor as `param_1[0x1f] = *param_2`. The map node the transport
    -- keeps it in is { _Next, _Prev, GUID @+0x10, connection* @+0x18 }.
    -- THE RAKNET REMOTE-SYSTEM TABLE, read exactly where the engine reads it.
    --
    -- oCDtP2PSessionSceneContext::vft[0x88] (0x1408b7550) is one line --
    -- `[this+0x210]->vft[0x190](&out)` -- and that callee (0x140ae3280) is
    -- also one line: `out = {u64 @this+0x7f0, u16 @this+0x7f8}`, i.e. the
    -- LOCAL RakNetGUID. So ctx+0x210 is an oCSLNetPeer, the RakPeer wrapper.
    --
    -- Its vft[0x100] (0x140ae1700) is the enumerator, and it walks members:
    --
    --     for i in 0 .. *(u32*)(peer+0x258):
    --         rs = *(void**)(peer+0x250 + i*8)
    --         if *(char*)rs != 0 and *(int*)(rs+0x2cec) == 7:      -- connected
    --             emit SystemAddress at rs+0x08  (sockaddr: port at +2, ntohs)
    --             emit {u64 @rs+0x2cc8, u16 @rs+0x2cd0}            -- RakNetGUID
    --
    -- which is RakNet::RakPeer::RemoteSystemStruct. That GUID is the same
    -- qword Replica3::creatingSystemGUID puts on a hero's replica, and the
    -- SystemAddress is the UDP endpoint whose PORT Netcode_PeerSlots already
    -- exposes per peer (slot+0x50 -> +0xc0, ntohs'd by FUN_1402aa470). One
    -- table therefore carries both halves of the join, and reading it is
    -- pure loads -- no engine call, no allocation, nothing to free.
    --
    -- [2026-09-20] That enumerator is now NAMED: `vft[0x100]` is slot 32 of
    -- RakNet::RakPeer, i.e. RakPeer::GetSystemList (symbol
    -- RakPeer_GetSystemList; RakPeer's shipped vtable matches the public
    -- header at 87/87 slots, so the slot IS the identity). `ConnectMode::
    -- CONNECTED == 7` in RakPeer.h, confirming RS_STATE's filter. Every
    -- constant below was re-read out of the CURRENT exe's disassembly on that
    -- date, not carried over from the August decompile.
    --
    -- Calling it is NOT an option and never will be: it takes two
    -- `DataStructures::List<T>&` out-params it push_back()s into, which Lua
    -- cannot construct. The member walk below is the only safe consumer, and
    -- that is why this stays a read even though the function now has a name.
    -- The P2P SESSION state machine, read off P2PSession_SetState (0x14085ca70)
    -- and its state-name table (P2PSession_StateNames, 0x140eece10). The names
    -- are transcribed here rather than read from that table because the table
    -- is a `va` global: reading it would need the va gate for no gain, since
    -- the enum is what we actually want and it is fixed for this build.
    --
    -- ⚠ Indices 7..13 of that table are a SECOND, unrelated connection enum
    -- (Pending, Connecting, Connected, Disconnecting, ...). A session state is
    -- 0..6 ONLY -- anything outside that is not a session state and must not be
    -- named, or "Disconnecting" gets reported for a value that never meant it.
    CTX_STATE = 0x70,
    SESSION_STATES = {
        [0] = "ConnectingToServer", [1] = "ConnectingToHost",
        [2] = "ConnectingToPeers",  [3] = "Pending",
        [4] = "ConnectingAsHost",   [5] = "Connected",
        [6] = "Disconnected",
    },
    -- ctx+0x218 -> the holder whose +0x48 is the session HOST's RakNetGUID,
    -- gated on its +0x20 being non-null. Straight out of the only non-logging
    -- branch of P2PSession_OnFcm2NewHost (0x1408b8530), which reads exactly
    -- this chain and compares it against UNASSIGNED_RAKNET_GUID.
    CTX_HOST     = 0x218,
    CTX_HOST_OK  = 0x20,
    CTX_HOST_GUID = 0x48,
    CTX_PEER  = 0x210,    -- proven a RakPeer: Netcode_SessionCtx_LocalGuid
                          -- calls [ctx+0x210]->vft[0x190], and 0x190/8 = slot
                          -- 50 = RakPeer::GetMyGUID.
    RS_LIST   = 0x250,
    RS_COUNT  = 0x258,
    RS_ADDR   = 0x08,
    RS_GUID   = 0x2cc8,
    RS_STATE  = 0x2cec,
    RS_CONNECTED = 7,
    RS_MAX    = 64,
    rak_said  = false,
    rak_done  = false,
    rak_idle  = 0,        -- consecutive passes that named nothing new
    -- Three is enough to cover a row boarding a tick or two after its peer
    -- slot appears, without spinning for the rest of the match.
    RAK_IDLE_MAX = 3,
    CONN_GUID = 0xf8,
    NODE_KEY  = 0x10,
    NODE_VAL  = 0x18,
    NODE_NEXT = 0x00,
    MAP_MAX   = 64,      -- refuse to walk a list longer than any real lobby
    MGRWIN    = 0x400,   -- bytes of the session manager to walk for pointers
    NODEWIN   = 0x200,   -- bytes of each object it points at
    conn_said = false,
    conn_done = false,
    conn_hit  = {},      -- row.key -> peer slot, kept once the hunt answers
    peer_said   = false,
    peer_done   = false,
    peer_gen    = nil,   -- #peers the memo below was built for
    peer_scanned = {},   -- row.key -> true: its window has been walked once
    peer_hit    = {},    -- row.key -> peer slot, kept after the one-shot scan
}

--- The lobby MEMBER OBJECTS as pointer needles: every plausible pointer the
--- member holds, plus the member's own address, mapped back to the member.
---
--- Session 2c36 settled the value search: all four rows resolved a real net
--- component and NONE of them held a session id within +0x400, direct or one
--- hop. So the peer is not identified there by its GUID -- which is what you
--- would expect if the engine keys peers by a connection OBJECT rather than by
--- the id string the lobby exposes.
---
--- A pointer both structures hold is a much stronger claim than a matching
--- integer: it says the member and the net component reference the SAME
--- allocation. Combined with the anchor and distinctness gates, a coincidence
--- would have to be a pointer that (a) one member alone holds, (b) one row
--- alone holds, (c) pairs the local row with the local player, and (d) pairs
--- every other row with a different member. Nothing shared satisfies that.
---
--- A value two members share is poisoned, exactly like a session needle.
function F._dmg_member_ptrs()
    local ok, members = pcall(R.lobby.members)
    if not ok or type(members) ~= "table" or not I.read_u64 then return nil end
    local by, n, total = {}, 0, 0
    for _, m in ipairs(members) do
        if type(m.ptrs) == "table" then
            for v in pairs(m.ptrs) do
                if by[v] == nil then by[v] = m
                elseif by[v] and by[v] ~= m then by[v] = false end
                total = total + 1
            end
            n = n + 1
        end
    end
    -- HOW MANY members contributed, once. Session 9e4f reported 30 hits that
    -- all named one player, and "every row holds a shared pointer" and "only
    -- one member had any needles at all, so nothing could poison one" look
    -- identical in the log without this. They are a different bug each.
    -- Latch on the first NON-EMPTY answer. Session c236 latched on "0 of 0"
    -- five seconds into the process, before a single member had been parsed,
    -- and then never spoke again for the rest of the run -- so the one number
    -- this line exists to report was the one number it could not report.
    if not F._netid.counted and n > 0 then
        F._netid.counted = true
        R.log(("[rsmm.damage] net id: %d of %d lobby member(s) contributed "
               .. "%d pointer needle(s)"):format(n, #members, total))
    end
    if n == 0 then return nil end
    return by
end

--- Both needle sets in one table, so a scan reads each qword once.
function F._dmg_netid_targets()
    local hex = F._dmg_session_needles()
    local ptr = F._dmg_member_ptrs()
    if not hex and not ptr then return nil end
    return { hex = hex or {}, ptr = ptr or {} }
end

--- The lobby's session ids as needles, keyed by the hex text a read would
--- produce. Text, not integers: a GUID half can exceed the signed 64-bit range
--- Lua 5.4 parses, and a float compare would match its neighbours too.
---
--- Both halves and both byte orders, because the netcode deals in qwords and a
--- half stored little-endian prints reversed. A needle two members share is
--- poisoned rather than dropped -- it must never name the first one found.
function F._dmg_session_needles()
    local ok, members = pcall(R.lobby.members)
    if not ok or type(members) ~= "table" then return nil end
    local function rev(h)
        local t = {}
        for i = 15, 1, -2 do t[#t + 1] = h:sub(i, i + 1) end
        return table.concat(t)
    end
    local by, n = {}, 0
    for _, m in ipairs(members) do
        local s = m.session
        if type(s) == "string" and #s == 32 and not s:find("[^0-9a-fA-F]") then
            s = s:lower()
            local lo, hi = s:sub(1, 16), s:sub(17, 32)
            local add = function(key, kind)
                if by[key] == nil then
                    by[key] = { m = m, kind = kind }
                elseif by[key] and by[key].m ~= m then
                    by[key] = false           -- shared by two members: useless
                end
            end
            add(s, "string")
            add(lo, "qword-lo")
            add(hi, "qword-hi")
            add(rev(lo), "qword-lo")
            add(rev(hi), "qword-hi")
            n = n + 1
        end
    end
    if n == 0 then return nil end
    return by
end

--- Every match for a member needle in `base[0 .. win)`: a session id as a
--- qword or a std::string, or a pointer the member itself holds. Guarded
--- reads only, so an unmapped page costs a nil.
--- `path` is how `base` was reached from the net component: nil for the
--- component itself, {a} for `*(nc+a)`, {a,b} for `*(*(nc+a)+b)`. Recorded on
--- every hit so an adopted locator can be RE-READ on another row -- a hit
--- nobody can reproduce is not a locator.
function F._dmg_scan_session(base, win, targets, path)
    local out = {}
    if not _ptr_plausible(base) or not I.read_u64 then return out end
    for off = 0, win - 8, 8 do
        local q = F._dmg_pread(base + off, 8)
        if type(q) == "number" then
            local h = targets.hex[("%016x"):format(q)]
            if h then
                out[#out + 1] = { off = off, path = path, kind = h.kind, m = h.m }
            else
                local m = targets.ptr[q]
                if m then out[#out + 1] = { off = off, path = path, kind = "ptr", m = m } end
            end
        end
        -- A std::string read is up to three more guarded reads, and this
        -- loop runs tens of thousands of times per row. Only bother where one
        -- could actually start: the heap form begins with a pointer, and the
        -- inline form begins with hex characters.
        local looks = _ptr_plausible(q)
        if not looks and type(q) == "number" then
            local c = q & 0xff
            looks = (c >= 0x30 and c <= 0x39) or (c >= 0x61 and c <= 0x66)
                    or (c >= 0x41 and c <= 0x46)
        end
        local s = looks and R.debug.stdstring_at and R.debug.stdstring_at(base + off)
        if type(s) == "string" and #s == 32 then
            local h = targets.hex[s:lower()]
            if h then out[#out + 1] = { off = off, path = path, kind = "string", m = h.m } end
        end
    end
    return out
end

--- The owning peer's RakNetGUID for a row, or nil.
---
--- `oCSLNetworkObject::vft[0x18]` (0x1408c0d40) is one line:
---
---     *out = *(*(netobj + 0x100) + 0x28);
---
--- netobj+0x100 is the oCSLNetReplica (set in its ctor, FUN_1408c0890's
--- param_2), and the replica is a RakNet::Replica3 whose +0x28 is
--- `creatingSystemGUID` -- the peer that created it, i.e. the machine whose
--- player owns this hero. Read, never called: three guarded loads.
function F._dmg_owner_guid(row)
    -- STICKY. Session 0e36 read a GUID for rows 1 and 2 at 18:43 and then
    -- reported `row 2 guid=nil, row 3 guid=nil, row 4 guid=nil` five minutes
    -- later: the chain is only walkable while the row's controller still
    -- points at a live entity with a net component, and a death or a chapter
    -- boundary breaks it. The GUID itself is a property of the OWNING MACHINE
    -- and cannot change under a row, so the first answer is the answer -- and
    -- a join that runs later must not lose the key it already had.
    if row.owner_guid then return row.owner_guid end
    local g = F._dmg_controller_guid(row.key)
    if g then row.owner_guid = g end
    return g
end

--- The owner GUID of a hero CONTROLLER that has no row yet, or nil. Guarded
--- reads only, so it is safe on the main thread inside a damage hook -- which
--- is where F._dmg_rebind needs it, to tell two stale ally rows apart.
function F._dmg_controller_guid(key)
    if not I.read_u64 or not _ptr_plausible(key) then return nil end
    local ent = I.read_u64(key + DMG.HERO_ENTITY_OFF)
    if not _ptr_plausible(ent) then return nil end
    local nc = R.net.component(ent)
    if not nc then return nil end
    local inner = F._dmg_netid_walk(nc, { 0xb8, 0x100 })
    if not inner then return nil end
    local g = I.read_u64(inner + 0x28)
    if type(g) ~= "number" or g == 0 or g == -1 then return nil end
    return g
end

--- Lobby names of the players actually CONNECTED to this session, as a set,
--- or nil when the peer table cannot say (unreadable, empty, or a slot with no
--- readable name -- filtering on a partial table would drop a real player).
---
--- The lobby roster only ever grows within a session: 2026-10-07 (Sky's log)
--- kept "MaxS394" for a three-player run he had already left. The board showed
--- him as a zeroed placeholder, and after a chapter change the name guess
--- handed his name to Jivil's forked row. The peer table is the engine's own
--- list of who is in the session, so it is what decides who is still here.
---
--- And only when every peer is a lobby member: a peer table that names someone
--- the lobby never saw is not describing this session, and filtering on it
--- would drop the real players.
function F._dmg_connected_names()
    local ok, peers = pcall(R.net.peers)
    if not ok or type(peers) ~= "table" or #peers == 0 then return nil end
    local okl, members = pcall(R.lobby.members, true)
    if not okl or type(members) ~= "table" then return nil end
    local known = {}
    for _, m in ipairs(members) do
        if type(m.name) == "string" then known[m.name] = true end
    end
    local set = {}
    for _, e in ipairs(peers) do
        if type(e.name) ~= "string" or not known[e.name] then return nil end
        set[e.name] = true
    end
    local okm, me = pcall(R.player.name)
    if okm and type(me) == "string" then set[me] = true end
    return set
end

--- R.lobby.allies() minus anyone the peer table says has left. Unfiltered
--- when the peer table cannot answer (see F._dmg_connected_names).
function F._dmg_live_allies()
    local ok, allies = pcall(R.lobby.allies)
    if not ok or type(allies) ~= "table" then return nil end
    local live = F._dmg_connected_names()
    if not live then return allies end
    local out = {}
    for _, nm in ipairs(allies) do
        if live[nm] then out[#out + 1] = nm end
    end
    return out
end

--- Is `t` well-formed UTF-8?
---
--- Hand-rolled rather than `utf8.len`: the loader's Lua is 5.4 and does have
--- the library, but this runs on every peer-slot read against bytes that may be
--- a stale pointer's contents, and `utf8.len` accepts the over-long and
--- surrogate encodings that a garbage read produces as readily as a real name.
--- Rejecting those is the entire point of the check.
---
--- On `F` rather than a `local`: the main chunk sits at Lua's 200-local
--- ceiling, and one more `local function` here costs the whole SDK its compile.
function F._utf8_ok(t)
    local i, n = 1, #t
    while i <= n do
        local c = t:byte(i)
        local extra, lo, hi
        if c < 0x80 then extra = 0
        elseif c >= 0xc2 and c <= 0xdf then extra, lo, hi = 1, 0x80, 0xbf
        elseif c == 0xe0 then extra, lo, hi = 2, 0xa0, 0xbf   -- no over-long
        elseif c >= 0xe1 and c <= 0xec then extra, lo, hi = 2, 0x80, 0xbf
        elseif c == 0xed then extra, lo, hi = 2, 0x80, 0x9f   -- no surrogates
        elseif c >= 0xee and c <= 0xef then extra, lo, hi = 2, 0x80, 0xbf
        elseif c == 0xf0 then extra, lo, hi = 3, 0x90, 0xbf   -- no over-long
        elseif c >= 0xf1 and c <= 0xf3 then extra, lo, hi = 3, 0x80, 0xbf
        elseif c == 0xf4 then extra, lo, hi = 3, 0x80, 0x8f   -- <= U+10FFFF
        else return false
        end
        for k = 1, extra do
            local b = t:byte(i + k)
            if not b then return false end
            local min = (k == 1) and lo or 0x80
            local max = (k == 1) and hi or 0xbf
            if b < min or b > max then return false end
        end
        i = i + 1 + extra
    end
    return true
end

--- One engine string/buffer descriptor: {void* ptr @+0x0; int32 len @+0x8;
--- uint32 cap @+0xc}. Same shape as LobbyAttributes_Parse's StringDesc, and
--- the shape the peer-slot destructor frees three of.
function F._peer_str(va)
    if not (I.read_u64 and I.read_u32 and I.read_cstr) then return nil end
    local ptr = I.read_u64(va)
    if not _ptr_plausible(ptr) then return nil end
    local len = I.read_u32(va + 8)
    if type(len) ~= "number" then return nil end
    len = len & 0x7fffffff                 -- bit 31 is the "not owned" flag
    if len < 1 or len > 128 then return nil end
    local t = I.read_cstr(ptr, len + 1)
    if type(t) ~= "string" or #t ~= len then return nil end
    -- PRINTABLE, not ASCII. This guard used to be `[^\32-\126]`, which threw
    -- away every player whose name is not plain ASCII -- session 104f's "7♣"
    -- (U+2663, bytes E2 99 A3) came back nil from the peer slot while its
    -- session and EOS ids, being hex, came back fine.
    --
    -- That is not a cosmetic loss. A nameless peer slot is a row that can never
    -- be PROVEN, and "is any row still unnamed?" is the gate on both the raknet
    -- join and the address scan -- so one non-ASCII name in the lobby left both
    -- running for the entire match, re-announcing the same result once a second
    -- (70 identical lines in that log). A run with an accented, CJK or emoji
    -- name in it is the common case, not the exotic one.
    --
    -- The guard's real job is rejecting a garbage read, and what garbage looks
    -- like is CONTROL bytes and malformed sequences, not high bytes. So: no
    -- C0/DEL, and the high bytes must form valid UTF-8.
    if t:find("[%z\1-\31\127]") then return nil end
    if not F._utf8_ok(t) then return nil end
    return t
end

--- The engine's own peer table — one entry per OTHER machine in the run.
---
--- Read-only, no engine call, ~`count` * a handful of guarded loads. This is
--- the only structure that holds one record per remote player, which is what a
--- row->player join has been missing: the board knows every NAME (lobby
--- attributes) and a distinct per-row owner RakNetGUID, and nothing joined them.
---
--- Layout in `Netcode_PeerSlots`'s note. Returns `{}` rather than guessing when
--- the va gate is closed or the count is implausible.
function R.net.peers()
    if not _va_ok("the netcode peer table") then return {} end
    if not (I.module_base and I.read_u32 and I.read_u64) then return {} end
    local base = I.module_base()
    if not base or base == 0 then return {} end
    local slots = base + (F._netid.PEER_SLOTS - 0x140000000)
    local n = I.read_u32(base + (F._netid.PEER_COUNT - 0x140000000))
    if type(n) ~= "number" or n < 1 or n > F._netid.PEER_MAX then return {} end
    local out = {}
    for i = 0, n - 1 do
        local slot = slots + i * F._netid.PEER_STRIDE
        local e = { index = i, slot = slot, text = {} }
        e.name    = F._peer_str(slot + F._netid.PEER_NAME)
        e.session = F._peer_str(slot + F._netid.PEER_SESSION)
        e.eos     = F._peer_str(slot + F._netid.PEER_EOS)
        e.hash    = I.read_u64(slot + F._netid.PEER_HASH)
        if e.hash == 0 or e.hash == -1 then e.hash = nil end
        local ptr = I.read_u64(slot + F._netid.PEER_TUNNEL)
        if _ptr_plausible(ptr) then
            e.peer  = ptr
            -- ntohs'd in FUN_1402aa470 (Ordinal_15 = ntohs), so this is a
            -- UDP PORT in network order, NOT a RakNet system index.
            e.port  = I.read_u16 and I.read_u16(ptr + 0xc0)
            e.state = I.read_u32(ptr + 0xcc)
        end
        for _, off in ipairs(F._netid.PEER_STR) do
            local t = F._peer_str(slot + off)
            if t then e.text[#e.text + 1] = t end
        end
        out[#out + 1] = e
    end
    return out
end

--- The RakNet remote-system table: `{ guid, port, state }` per connected peer.
---
--- This is `RakPeer::GetSystemList`'s answer, obtained by WALKING RakPeer's
--- members rather than calling it. The function itself takes two
--- `DataStructures::List<T>&` out-params it push_back()s into, which Lua cannot
--- construct — so the call is permanently off the table and the read is the
--- API. Every offset was re-read from the shipped exe (see F._netid).
---
--- Why a mod wants it: `guid` is the same value R.net.owner(entity) returns for
--- that player's hero, and `port` is what R.net.peers() exposes per peer beside
--- the display NAME. One table therefore bridges "who owns this entity" to
--- "what is their name". Returns nil, never a partial guess.
function R.net.systems() return F._dmg_rak_systems() end

--- The P2P session's current state, as `code, name` — or nil when unknown.
---
--- `name` is nil for any code outside 0..6 while `code` is still returned, so
--- an unexpected value is reported as itself instead of being mislabelled with
--- a name borrowed from the second enum that shares the engine's table.
---
--- Pure reads: the context is the one F._dmg_conn_mgr already walks to
--- (netcomp -> scene -> scene+0x28), and the state is a single u32 at +0x70.
--- No engine call, so this is safe to poll.
function R.net.session_state()
    local mgr = F._dmg_conn_mgr()
    if not mgr or not I.read_u32 then return nil end
    local v = I.read_u32(mgr + F._netid.CTX_STATE)
    if type(v) ~= "number" or v < 0 or v > 0xffff then return nil end
    return v, F._netid.SESSION_STATES[v]
end

--- The RakNetGUID of the session HOST, or nil when there is no host yet.
---
--- The engine's own test, lifted verbatim from the only branch of
--- P2PSession_OnFcm2NewHost that does anything: take ctx+0x218, and only if
--- its +0x20 is non-null read the GUID at +0x48; the UNASSIGNED sentinel
--- (all-ones) means "no host elected", which this reports as nil rather than
--- as a peer nobody can match.
---
--- Compare it against R.net.owner(entity) to answer "is the host the machine
--- that owns this hero", and against R.damage._rak_systems() to turn it into
--- a port and therefore a NAME.
function R.net.session_host()
    local mgr = F._dmg_conn_mgr()
    if not mgr or not I.read_u64 then return nil end
    local h = I.read_u64(mgr + F._netid.CTX_HOST)
    if not _ptr_plausible(h) then return nil end
    if I.read_u64(h + F._netid.CTX_HOST_OK) == 0 then return nil end
    local g = I.read_u64(h + F._netid.CTX_HOST_GUID)
    if type(g) ~= "number" or g == 0 or g == -1
       or g == 0xffffffffffffffff then return nil end
    return g
end

--- The owner GUID's SYSTEM INDEX, the other half of the RakNetGUID.
---
--- `RakNetGUID` is `{uint64 g; uint16 systemIndex}` — the replica ctor
--- initialises 16 bytes at +0x28 — so the index sits at replica+0x30. It is
--- the candidate bridge to the peer table, whose peer objects carry a u16 at
--- +0xc0 that Netcode_DropPeer's finder matches on.
function F._dmg_owner_index(row)
    if not I.read_u16 or not _ptr_plausible(row.key) then return nil end
    local ent = I.read_u64(row.key + DMG.HERO_ENTITY_OFF)
    if not _ptr_plausible(ent) then return nil end
    local nc = R.net.component(ent)
    if not nc then return nil end
    local inner = F._dmg_netid_walk(nc, { 0xb8, 0x100 })
    if not inner then return nil end
    local ix = I.read_u16(inner + 0x30)
    if type(ix) ~= "number" or ix == 0xffff then return nil end
    return ix
end

--- Join rows to players through the ENGINE'S OWN PEER TABLE.
---
--- `Netcode_PeerSlots` is one 0x60-byte slot per other machine in the run, and
--- the slot already carries the player's display NAME (+0x00), their lobby
--- session id (+0x10), their EOS ProductUserId (+0x20) and a 64-bit hash of
--- that id (+0x30). It is a better name source than the lobby roster: the
--- roster is append-only history, this is current membership.
---
--- The unsolved half is which SLOT owns which row. The engine's own join is by
--- the +0x30 hash -- FUN_140272700 walks the slots and matches each against
--- `hash(member.m_sEosUserId)`, logging "No party member found for P2P User"
--- when it cannot -- so that hash is the shape an ownership record would take
--- on the hero side too. This scans each row's controller and entity for it.
---
--- A hit is an EQUALITY on a 64-bit engine-computed id, which is what separates
--- it from `guess_names`. No hit names nobody, and the report below still says
--- what both halves held.
function F._dmg_peer_join()
    if F._netid.peer_done then return false end
    -- Nothing unnamed, nothing to look for. Without this the window walk below
    -- runs on a board that is already fully named, forever.
    local wanted = false
    for _, row in ipairs(_dmg.order) do
        if not row.is_local and not row.player and _ptr_plausible(row.key) then
            wanted = true
            break
        end
    end
    if not wanted then return false end
    local peers = R.net.peers()
    if #peers == 0 then return false end
    -- ONE-SHOT PER ROW, re-armed only when the peer set changes.
    --
    -- The scan below is 0x800 bytes of the controller plus 0x800 of the entity,
    -- read a qword at a time through the page guard: ~512 native calls per row.
    -- The first version ran it on EVERY background tick for every unnamed row
    -- and never stopped, because a miss returns false rather than latching --
    -- four rows is ~2000 guarded reads a tick, forever. That is the "lags
    -- sometimes hard" shape: invisible while it happens to match, brutal while
    -- it does not. A row's controller does not sprout the key later, so once is
    -- the right number of times; a NEW peer is the only thing that can change
    -- the answer, so that is what re-arms it.
    local gen = #peers
    if F._netid.peer_gen ~= gen then
        F._netid.peer_gen, F._netid.peer_scanned = gen, {}
    end

    -- The engine's own key. FUN_1402aed50 hashes the EOS id into slot+0x30 and
    -- FUN_140272700 joins a lobby member to a peer by comparing that hash --
    -- so if anything on the hero side records which player owns it, this
    -- 64-bit value is the shape it would take. A value two peers share
    -- identifies neither.
    local by_hash = {}
    for _, e in ipairs(peers) do
        if e.hash then
            by_hash[e.hash] = (by_hash[e.hash] == nil) and e or false
        end
    end

    local hit, found = {}, {}
    for _, row in ipairs(_dmg.order) do
        if _ptr_plausible(row.key) and not F._netid.peer_scanned[row.key] then
            F._netid.peer_scanned[row.key] = true
            row._peer_ix = F._dmg_owner_index(row)
            local ent = I.read_u64(row.key + DMG.HERO_ENTITY_OFF)
            for _, obj in ipairs({ row.key, _ptr_plausible(ent) and ent or nil }) do
                for off = 0, F._netid.WIN - 8, 8 do
                    local v = I.read_u64(obj + off)
                    local e = type(v) == "number" and by_hash[v]
                    if e then
                        F._netid.peer_hit = F._netid.peer_hit or {}
                        F._netid.peer_hit[row.key] = e
                        found[#found + 1] = ("row %d +0x%x -> %s"):format(
                            row.slot, off, tostring(e.name))
                    end
                end
            end
        end
        -- Carried across ticks: the scan happened once, its answer has to
        -- outlive it or the join can never act on a row it already solved.
        local e = F._netid.peer_hit and F._netid.peer_hit[row.key]
        if e then hit[row] = e end
    end

    if not F._netid.peer_said then
        F._netid.peer_said = true
        local pp = {}
        for _, e in ipairs(peers) do
            pp[#pp + 1] = ("#%d %s session=%s eos=%s port=%s state=%s hash=%s"):format(
                e.index, tostring(e.name), tostring(e.session), tostring(e.eos),
                tostring(e.port), tostring(e.state),
                e.hash and ("0x%x"):format(e.hash) or "nil")
        end
        local rr = {}
        for _, row in ipairs(_dmg.order) do
            local g = F._dmg_owner_guid(row)
            rr[#rr + 1] = ("row %d guid=%s ix=%s"):format(
                row.slot, g and ("0x%x"):format(g) or "nil",
                tostring(row._peer_ix))
        end
        -- Both halves, always. A silent failure costs a playtest to work out
        -- which side was empty; this line says so outright.
        R.log(("[rsmm.damage] peer table: %d peer(s) [%s]; rows [%s]; hash hits [%s]")
              :format(#peers, table.concat(pp, ", "), table.concat(rr, ", "),
                      #found > 0 and table.concat(found, ", ") or "none"))
    end
    if not next(hit) then return false end

    -- Same two gates as every other join. The anchor is the one that catches a
    -- plausible-but-wrong bridge: if this machine's own row comes back as
    -- somebody else, the mapping is not an identity.
    local me
    local okn, nm = pcall(R.player.name)
    if okn and type(nm) == "string" and nm ~= "" then me = nm end
    for row, e in pairs(hit) do
        if row.is_local and me and e.name and e.name ~= me then
            R.log(("[rsmm.damage] peer join REFUSED: this machine's row resolves "
                   .. "to %q but Steam calls this player %q"):format(e.name, me))
            F._netid.peer_done = true
            return false
        end
    end
    local by = {}
    for row, e in pairs(hit) do
        if e.name then
            if by[e.name] then
                R.log(("[rsmm.damage] peer join REFUSED: rows %d and %d both "
                       .. "resolve to %q"):format(by[e.name].slot, row.slot, e.name))
                F._netid.peer_done = true
                return false
            end
            by[e.name] = row
        end
    end

    local named = 0
    for row, e in pairs(hit) do
        if e.name and not row.is_local and _dmg.names[row.slot] == nil
           and row.label ~= e.name then
            row.label, row.label_guess, row.player = e.name, false, e.name
            named = named + 1
        end
    end
    if named > 0 then
        F._netid.peer_done = true
        R.log(("[rsmm.damage] PEER JOIN PROVEN: %d row(s) named from the engine's "
               .. "own peer table — exact, not a guess"):format(named))
    end
    return named > 0
end

--- Name rows by matching the owner GUID against the lobby members' own words.
---
--- The engine has to know which peer each lobby member is, and a RakNetGUID is
--- a plain 64-bit number, so if it records that anywhere on the member this
--- finds it. Same two gates as everything else: the local row must resolve to
--- the Steam persona, and no two rows may resolve to the same member.
---
--- Costs one table lookup per (row, member) pair. Nothing is searched.
function F._dmg_guid_join()
    if F._netid.guid_done then return false end
    local ok, members = pcall(R.lobby.members)
    if not ok or type(members) ~= "table" then return false end
    -- NOT gated on the roster size. The GUID report below is about the ROWS --
    -- distinct values prove the field is the per-player key whether or not any
    -- member carries one -- and gating the whole function on `#members >= 2`
    -- suppressed it in exactly the sessions where it was worth having.
    if #members < 1 then return false end
    local guid, hit, rows = {}, {}, 0
    for _, row in ipairs(_dmg.order) do
        local g = F._dmg_owner_guid(row)
        if g then
            guid[row] = g
            rows = rows + 1
            local found, count = nil, 0
            for _, m in ipairs(members) do
                if type(m.words) == "table" and m.words[g] then
                    found, count = m, count + 1
                end
            end
            -- A GUID two members claim identifies neither.
            if count == 1 then hit[row] = found end
        end
    end
    if rows == 0 then return false end
    -- Report the GUIDs once, whatever happens. Four different values is the
    -- proof that the field is the owner key even when no member carries it.
    if not F._netid.guid_said and rows > 1 then
        F._netid.guid_said = true
        local seen, n = {}, 0
        local parts = {}
        for _, row in ipairs(_dmg.order) do
            if guid[row] then
                if not seen[guid[row]] then seen[guid[row]] = true; n = n + 1 end
                parts[#parts + 1] = ("row %d = 0x%x%s"):format(
                    row.slot, guid[row], hit[row] and (" -> " .. hit[row].name) or "")
            end
        end
        R.log(("[rsmm.damage] owner GUIDs: %s (%d distinct across %d row(s))")
              :format(table.concat(parts, ", "), n, rows))
    end
    if not next(hit) then return false end
    -- ANCHOR: the local row must resolve to this machine's player.
    local me
    local okn, nm = pcall(R.player.name)
    if okn and type(nm) == "string" and nm ~= "" then me = nm end
    for row, m in pairs(hit) do
        if row.is_local and me and m.name ~= me then
            R.log(("[rsmm.damage] owner GUID join REFUSED: this machine's row "
                   .. "resolves to %q but Steam calls this player %q")
                  :format(m.name, me))
            F._netid.guid_done = true
            return false
        end
    end
    -- DISTINCTNESS: two rows resolving to one member means the match is not an
    -- identity, so it names nobody.
    local by = {}
    for row, m in pairs(hit) do
        if by[m.name] then
            R.log(("[rsmm.damage] owner GUID join REFUSED: rows %d and %d both "
                   .. "resolve to %q"):format(by[m.name].slot, row.slot, m.name))
            F._netid.guid_done = true
            return false
        end
        by[m.name] = row
    end
    local names, named = F._dmg_name_set(), false
    if not names then return false end
    for row, m in pairs(hit) do
        if not row.player and names[m.name] then
            if F._dmg_claim(row, names, m.name, "owner GUID") then named = true end
        end
    end
    if named and not F._netid.guid_proven then
        F._netid.guid_proven = true
        R.log("[rsmm.damage] OWNER GUID JOIN PROVEN: rows are named from "
              .. "RakNet::Replica3::creatingSystemGUID -- the peer the engine "
              .. "itself says created the hero, matched against the lobby "
              .. "member that carries the same GUID.")
    end
    return named
end

--- The object the engine routes sessions through, reached from a live row.
---
--- `netcomp+0xc8` is the scene and `scene+0x28` is the session manager --
--- both read straight out of NamedEvent_NetSendToPeer, which asks that object
--- for the LOCAL session id (vft slot 0x88) before unicasting through the
--- scene's own slot 0xc0. Whatever maps a session qword to a connection lives
--- there, and a row's owner GUID *is* that qword.
---
--- Any row will do: every replicated entity in the run shares one scene.
--- entity -> net component -> scene -> P2P session context. nil, never a guess.
function F._dmg_ctx_from_entity(ent)
    if not I.read_u64 or not _ptr_plausible(ent) then return nil end
    local nc = R.net.component(ent)
    if not nc then return nil end
    local scene = I.read_u64(nc + F._netid.SCENE)
    if not _ptr_plausible(scene) then return nil end
    local mgr = I.read_u64(scene + F._netid.SCENE_MGR)
    if not _ptr_plausible(mgr) then return nil end
    return mgr, scene
end

function F._dmg_conn_mgr()
    if not I.read_u64 then return nil end
    for _, row in ipairs(_dmg.order) do
        if _ptr_plausible(row.key) then
            local mgr, scene = F._dmg_ctx_from_entity(
                I.read_u64(row.key + DMG.HERO_ENTITY_OFF))
            if mgr then return mgr, scene end
        end
    end
    -- FALLBACK: the captured local hero.
    --
    -- The board walk above finds the session context only once a row EXISTS,
    -- i.e. only after somebody has dealt damage with the meter running. That
    -- is fine for the damage join, which by definition has rows -- but it made
    -- R.net.session_state / session_host / systems return nil for the entire
    -- length of a live four-player match when the meter was off (observed
    -- 2026-09-20, session 8b36: peers read perfectly, all three of those
    -- returned nil, every poll). The session context has nothing to do with
    -- damage; any replicated entity reaches it, and R.entity.hero() is one we
    -- already hold. R.entity.hero() hands out the hero oCEntity, so it goes
    -- straight into the walk with no controller hop.
    if R.entity and R.entity.hero then
        local ok, hero = pcall(R.entity.hero)
        if ok then
            local mgr, scene = F._dmg_ctx_from_entity(hero)
            if mgr then return mgr, scene end
        end
    end
    return nil
end

--- Every 64-bit value that identifies exactly ONE peer slot.
---
--- A value two peers share identifies neither, so it is dropped rather than
--- resolved to whichever was seen last -- the same rule the EOS-hash join
--- uses, for the same reason.
function F._dmg_peer_needles(peers)
    local n = {}
    local function add(v, e)
        if type(v) ~= "number" or v == 0 or v == -1 then return end
        if not _ptr_plausible(v) and v ~= e.hash then return end
        if n[v] ~= nil and n[v] ~= e then n[v] = false else n[v] = e end
    end
    for _, e in ipairs(peers) do
        add(e.hash, e)                                   -- FUN_1402aed50's EOS hash
        for _, off in ipairs(F._netid.PEER_STR) do       -- the three string buffers
            add(I.read_u64(e.slot + off), e)
        end
        add(e.peer, e)                                   -- the P2P tunnel object
        add(e.slot, e)                                   -- the slot itself
    end
    return n
end

--- The RakNet remote-system table for this run: GUID -> UDP port.
---
--- Pure reads off the chain in F._netid's notes, all of it decompiled rather
--- than guessed. Returns a list of `{ guid, port, state }`, or nil when the
--- chain does not resolve -- never a partial guess.
function F._dmg_rak_systems()
    if not (I.read_u64 and I.read_u32 and I.read_u16) then return nil end
    local mgr = F._dmg_conn_mgr()
    if not mgr then return nil end
    local peer = I.read_u64(mgr + F._netid.CTX_PEER)
    if not _ptr_plausible(peer) then return nil end
    local list = I.read_u64(peer + F._netid.RS_LIST)
    local n    = I.read_u32(peer + F._netid.RS_COUNT)
    if not _ptr_plausible(list) then return nil end
    if type(n) ~= "number" or n < 1 or n > F._netid.RS_MAX then return nil end
    local out = {}
    for i = 0, n - 1 do
        local rs = I.read_u64(list + i * 8)
        if _ptr_plausible(rs) then
            local g  = I.read_u64(rs + F._netid.RS_GUID)
            -- sockaddr_in: sin_family @+0, sin_port @+2, network order. The
            -- engine passes it through ntohs (Ordinal_15) and so must we.
            local np = I.read_u16(rs + F._netid.RS_ADDR + 2)
            local st = I.read_u32(rs + F._netid.RS_STATE)
            if type(g) == "number" and g ~= 0 and g ~= -1 and type(np) == "number" then
                out[#out + 1] = {
                    guid  = g,
                    port  = ((np & 0xff) << 8) | ((np >> 8) & 0xff),
                    state = st,
                    rs    = rs,
                }
            end
        end
    end
    if #out == 0 then return nil end
    return out
end

--- The display name for a peer slot, recovering one the slot itself lacks.
---
--- Session 104f, match 2: peer #0 read `nil` for its name while carrying a
--- perfectly good session id AND EOS id — and the lobby roster knew that
--- player as "7♣". One nameless slot is not a cosmetic loss: the row it
--- belongs to can never be proven, so `_dmg_rak_join`'s "is anyone still
--- unnamed?" gate stays open for the rest of the match, re-pairing and
--- re-announcing every OTHER row once a second forever (70 identical PROVEN
--- lines in that log), and the address scan next door reads the same shape and
--- keeps sweeping too.
---
--- The recovery is still READ, not searched: `m_sEosUserId` and the session id
--- are named fields on the lobby member and named fields on the peer slot, so
--- this is the same kind of join as the port match, on a different column.
--- EOS first — it is the account, where a session id is per-connection.
function F._dmg_peer_name(e)
    if type(e) ~= "table" then return nil end
    if type(e.name) == "string" and e.name ~= "" then return e.name end
    local ok, members = pcall(R.lobby.members)
    if not ok or type(members) ~= "table" then return nil end
    for _, key in ipairs({ "eos", "session" }) do
        local want = e[key]
        if type(want) == "string" and #want > 0 then
            for _, m in ipairs(members) do
                if m[key] == want and type(m.name) == "string" and m.name ~= "" then
                    return m.name
                end
            end
        end
    end
    return nil
end

--- Name rows from the RakNet remote-system table, joined on the UDP PORT.
---
--- THE ONLY JOIN HERE THAT IS READ RATHER THAN SEARCHED. Both halves are
--- fields the disassembly names outright:
---
---   * a row's owner GUID is Replica3::creatingSystemGUID (Entity_GetNetId),
---   * RemoteSystemStruct carries that same GUID beside the peer's
---     SystemAddress (oCSLNetPeer::vft[0x100]),
---   * and Netcode_PeerSlots carries the display NAME beside the same UDP
---     port (slot+0x50 -> +0xc0).
---
--- So GUID -> port -> name, with no offset ever adopted by agreement and
--- nothing searched for. The gates below are still here, because a layout can
--- be right and a build can still have moved: this machine must not appear as
--- one of its own remote systems, and two rows may not land on one peer.
function F._dmg_rak_join()
    if F._netid.rak_done then return false end
    local wanted = false
    for _, row in ipairs(_dmg.order) do
        if not row.is_local and not row.player and _ptr_plausible(row.key) then
            wanted = true
            break
        end
    end
    if not wanted then return false end

    local peers = R.net.peers()
    if #peers == 0 then return false end
    local systems = F._dmg_rak_systems()
    if not systems then return false end

    -- port -> peer slot. A port two peers share names neither.
    local by_port = {}
    for _, e in ipairs(peers) do
        if type(e.port) == "number" and e.port ~= 0 then
            if by_port[e.port] ~= nil and by_port[e.port] ~= e then by_port[e.port] = false
            else by_port[e.port] = e end
        end
    end
    -- guid -> peer slot, through the remote-system table.
    local by_guid_peer = {}
    for _, sys in ipairs(systems) do
        local e = by_port[sys.port]
        if e then
            if by_guid_peer[sys.guid] ~= nil and by_guid_peer[sys.guid] ~= e then
                by_guid_peer[sys.guid] = false
            else
                by_guid_peer[sys.guid] = e
            end
        end
    end

    local pair, notes = {}, {}
    for _, row in ipairs(_dmg.order) do
        local g = F._dmg_owner_guid(row)
        local e = g and by_guid_peer[g]
        if e then
            pair[row] = e
            notes[#notes + 1] = ("row %d 0x%x:%d <-> %s")
                                :format(row.slot, g, e.port, tostring(e.name))
        end
    end

    if not F._netid.rak_said and #systems > 0 then
        F._netid.rak_said = true
        local ss = {}
        for _, sys in ipairs(systems) do
            ss[#ss + 1] = ("0x%x:%d%s"):format(sys.guid, sys.port,
                sys.state == F._netid.RS_CONNECTED and "" or (" state=" .. tostring(sys.state)))
        end
        -- The whole table, once. If a build moves RemoteSystemStruct this line
        -- is what says so -- implausible ports and zero GUIDs read as garbage
        -- at a glance, where a silent `return false` reads as "no co-op".
        R.log(("[rsmm.damage] raknet systems: %d [%s]; peer ports [%s]; pairs [%s]")
              :format(#systems, table.concat(ss, " "),
                      (function()
                          local t = {}
                          for _, e in ipairs(peers) do
                              t[#t + 1] = ("%s:%s"):format(tostring(e.name), tostring(e.port))
                          end
                          return table.concat(t, " ")
                      end)(),
                      #notes > 0 and table.concat(notes, ", ") or "none"))
    end
    if not next(pair) then return false end

    -- ANCHOR. The remote-system table is the OTHER machines; this one being in
    -- it means the chain is not what the decompile says it is.
    for row, e in pairs(pair) do
        if e and row.is_local then
            R.log(("[rsmm.damage] raknet join REFUSED: this machine's row pairs "
                   .. "with remote system %q"):format(tostring(e.name)))
            F._netid.rak_done = true
            return false
        end
    end
    -- DISTINCTNESS.
    local by = {}
    for row, e in pairs(pair) do
        if e and e.name then
            if by[e.name] then
                R.log(("[rsmm.damage] raknet join REFUSED: rows %d and %d both "
                       .. "pair with %q"):format(by[e.name].slot, row.slot, e.name))
                F._netid.rak_done = true
                return false
            end
            by[e.name] = row
        end
    end

    -- NEWLY named, not pairable. `named` used to count every row the join
    -- COULD pair, which is a constant for the rest of the match — so a single
    -- row it could never pair (a nameless peer slot) meant this block rewrote
    -- the same two labels and logged the same "PROVEN" line every tick for the
    -- whole run. Counting the rows whose name actually CHANGED makes the log
    -- an event again and makes the return value mean "I made progress".
    local named, total = 0, 0
    for row, e in pairs(pair) do
        local nm = F._dmg_peer_name(e)
        if nm and not row.is_local and _dmg.names[row.slot] == nil then
            total = total + 1
            if row.player ~= nm then
                row.label, row.label_guess, row.player = nm, false, nm
                named = named + 1
            end
        end
    end
    if named > 0 then
        R.log(("[rsmm.damage] RAKNET JOIN PROVEN: %d of %d row(s) named by "
               .. "matching Replica3::creatingSystemGUID to RakPeer's "
               .. "remote-system table and its UDP port to the peer slot's "
               .. "tunnel — read, not searched"):format(named, total))
        F._netid.rak_idle = 0
        return true
    end

    -- Nothing new, and the pairing is a pure read of tables that only change
    -- when the lobby does. Stand down rather than re-deriving the same answer
    -- once a second until the run ends; the chapter epoch re-arms it, which is
    -- the only moment a row's controller (and so its owner GUID) can change.
    F._netid.rak_idle = (F._netid.rak_idle or 0) + 1
    if F._netid.rak_idle >= F._netid.RAK_IDLE_MAX then
        F._netid.rak_done = true
        if total < #_dmg.order - 1 then
            R.log(("[rsmm.damage] raknet join: named every row it can (%d); "
                   .. "the rest have no peer slot carrying a name, so they "
                   .. "keep their lobby guess — set player_1..4 in the "
                   .. "damage-meter config for exact labels"):format(total))
        end
    end
    return false
end

--- Is `obj` the Stormancer RakNetConnection whose owner GUID is `g`?
---
--- SELF-VALIDATING, and that is why this join is not another coincidence
--- search. RakNetConnection's constructor (FUN_140b9cd50, reached from the
--- factory FUN_140b287f0) copies the RakNetGUID's 64-bit half into
--- `param_1[0x1f]` -- connection + 0xf8 -- from the `{uint64 g; uint16
--- systemIndex}` the transport was handed. The same qword is what
--- Replica3::creatingSystemGUID holds on the hero's replica. So a candidate
--- pointer either answers with the row's own GUID at that one offset or it is
--- not a connection, and no window size or scan order can fake it.
function F._dmg_is_conn(obj, g)
    if not _ptr_plausible(obj) then return false end
    return I.read_u64(obj + F._netid.CONN_GUID) == g
end

--- Join rows to peers through the ENGINE'S OWN CONNECTION REGISTRY.
---
--- Every earlier join searched the HERO side for something the peer side
--- holds, and the hero side never had it: session 2c36 proved no row's net
--- component reaches a lobby session id, and session 0e36's peer scan found
--- no EOS hash anywhere in a controller or entity. The registry is where the
--- engine itself keeps the two halves together.
---
--- WHAT THE REGISTRY IS (Ghidra, this build, 2026-08-21). The netcode is
--- Stormancer over RakNet -- the RTTI carries `Stormancer::RakNetTransport`,
--- `Stormancer::RakNetConnection`, `Stormancer::ConnectionsRepository`,
--- `RakNet::Replica3`. FUN_140b287f0 builds a RakNetConnection from an
--- incoming `{uint64 g; uint16 systemIndex}` and inserts it into a
--- `std::unordered_map<uint64, ...>` at transport+0x80 via FUN_140b2fd80,
--- which is textbook MSVC `try_emplace`: FNV-1a over the key's 8 bytes
--- (`^0xcbf29ce484222325`, `*0x100000001b3`), compare `*(int64*)key ==
--- node[2]`, 0x38-byte node. So a live node is
---
---     { _Next @+0x00, _Prev @+0x08, GUID @+0x10, RakNetConnection* @+0x18 }
---
--- and the connection it points at repeats that same GUID at +0xf8. Three
--- values that must agree, so one hit is proof rather than evidence.
---
--- WHAT IS STILL A SEARCH: which peer slot a connection belongs to. That is
--- the one unproven half, so it is gated the same way every other locator
--- here is -- a candidate offset must resolve a DIFFERENT peer on every
--- connection, and the run must not name the local machine.
---
--- Bounded and one-shot: 0x400 bytes of each object the net component routes
--- through, then 0x200 at each pointer they hold. Finding ONE node is enough
--- to enumerate every connection in the run, because the map is a linked
--- list -- so the cost does not scale with the lobby.
function F._dmg_conn_join()
    if F._netid.conn_done then return false end
    if not (I.read_u64 and _dmg.order) then return false end
    local wanted = false
    for _, row in ipairs(_dmg.order) do
        if not row.is_local and not row.player and _ptr_plausible(row.key) then
            wanted = true
            break
        end
    end
    if not wanted then return false end

    local peers = R.net.peers()
    if #peers == 0 then return false end

    -- Rows keyed by owner GUID. A GUID two rows share names neither -- and two
    -- rows sharing one is itself worth saying, because it would mean the field
    -- is not per-player after all.
    local by_guid, guids, dup = {}, 0, false
    for _, row in ipairs(_dmg.order) do
        local g = F._dmg_owner_guid(row)
        if g then
            guids = guids + 1
            if by_guid[g] and by_guid[g] ~= row then by_guid[g], dup = false, true
            else by_guid[g] = row end
        end
    end
    if guids == 0 then return false end

    local mgr, scene = F._dmg_conn_mgr()
    if not mgr then return false end
    local needles = F._dmg_peer_needles(peers)

    -- The registry, once found, is a linked list: one node reaches all of it.
    local conns, node_at, walked = {}, nil, 0
    local guid_at, peer_at, seen, kids = {}, {}, {}, {}
    local function examine(obj, win, collect)
        if not _ptr_plausible(obj) or seen[obj] then return end
        seen[obj] = true
        for off = 0, win - 8, 8 do
            local q = I.read_u64(obj + off)
            if type(q) == "number" and q ~= 0 then
                local r = by_guid[q]
                if r then
                    guid_at[obj + off] = r
                    -- MAP NODE? The qword after the key is the connection, and
                    -- the connection repeats the key at +0xf8. Three agreeing
                    -- values is proof, not evidence.
                    local val = I.read_u64(obj + off + (F._netid.NODE_VAL - F._netid.NODE_KEY))
                    if F._dmg_is_conn(val, q) then
                        conns[q] = val
                        node_at = node_at or (obj + off - F._netid.NODE_KEY)
                    end
                end
                -- Or the connection itself, held directly.
                if _ptr_plausible(q) then
                    local g = I.read_u64(q + F._netid.CONN_GUID)
                    if type(g) == "number" and by_guid[g] then conns[g] = q end
                end
                local e = needles[q]
                if e then peer_at[obj + off] = e end
                if collect and _ptr_plausible(q) and off < 0x80 then
                    kids[#kids + 1] = q
                end
            end
        end
    end

    -- Every object the net component routes through, not just one: NetSend
    -- reads C+0xc0 for the local session and NetSendToPeer reads
    -- [C+0xc8]+0x28 for the same value, so both are entry points into the
    -- same netcode layer and either may be the one that holds the registry.
    local objs = { mgr }
    if scene then objs[#objs + 1] = scene end
    for off = 0, F._netid.MGRWIN - 8, 8 do
        local p = I.read_u64(mgr + off)
        if _ptr_plausible(p) then objs[#objs + 1] = p end
    end
    if scene then
        for off = 0, F._netid.MGRWIN - 8, 8 do
            local p = I.read_u64(scene + off)
            if _ptr_plausible(p) then objs[#objs + 1] = p end
        end
    end
    for _, o in ipairs(objs) do examine(o, F._netid.NODEWIN, true) end

    if not next(conns) and not next(guid_at) then
        -- Second hop, tighter window, capped.
        local n = 0
        for _, k in ipairs(kids) do
            n = n + 1
            if n > 512 then break end
            examine(k, 0x100, false)
        end
    end

    -- ONE NODE IS THE WHOLE MAP. `_Next` at +0x00 walks the bucket list the
    -- transport keeps every connection in, so the lobby's size costs nothing:
    -- the rows this machine has never scanned near are reached anyway.
    if node_at then
        local n, cur = 0, I.read_u64(node_at + F._netid.NODE_NEXT)
        while _ptr_plausible(cur) and cur ~= node_at and n < F._netid.MAP_MAX do
            local key = I.read_u64(cur + F._netid.NODE_KEY)
            local val = I.read_u64(cur + F._netid.NODE_VAL)
            if type(key) == "number" and F._dmg_is_conn(val, key) then
                conns[key] = val
                walked = walked + 1
            end
            cur = I.read_u64(cur + F._netid.NODE_NEXT)
            n = n + 1
        end
    end

    -- WHICH PEER IS THIS CONNECTION? The only unproven half, so it gets the
    -- locator discipline: a candidate offset must answer with a DIFFERENT
    -- peer on every connection it reads, or it is a shared field and names
    -- nobody. Offsets are relative to the connection object, which makes them
    -- reportable and re-checkable next session instead of being a one-run
    -- coincidence.
    local tally = {}
    local function offer(off, row, e)
        local t = tally[off]
        if t == nil then t = { rows = {}, used = {}, n = 0 }; tally[off] = t end
        if t.rows[row] and t.rows[row] ~= e then t.bad = true
        elseif t.used[e] and t.used[e] ~= row then t.bad = true
        elseif not t.rows[row] then
            t.rows[row], t.used[e], t.n = e, row, t.n + 1
        end
    end
    for g, obj in pairs(conns) do
        local row = by_guid[g]
        if row then
            for off = 0, F._netid.NODEWIN - 8, 8 do
                local q = I.read_u64(obj + off)
                local e = type(q) == "number" and needles[q]
                if e then offer(off, row, e) end
            end
        end
    end
    -- FALLBACK, for the case where no connection was reached at all: the same
    -- rule applied to raw distance between a GUID and a peer value in the
    -- same region. Weaker (it proves a layout, not an identity), so it only
    -- runs when the strong path found nothing.
    if not next(conns) then
        for ga, row in pairs(guid_at) do
            if row then
                for na, e in pairs(peer_at) do
                    local dd = na - ga
                    if dd >= -F._netid.NODEWIN and dd <= F._netid.NODEWIN then
                        offer(dd, row, e)
                    end
                end
            end
        end
    end
    local best, bestd
    for off, t in pairs(tally) do
        if not t.bad and t.n >= 2 and (best == nil or t.n > best.n) then
            best, bestd = t, off
        end
    end

    local pair, notes = {}, {}
    if best then
        for row, e in pairs(best.rows) do
            pair[row] = e
            notes[#notes + 1] = ("row %d <-> %s"):format(row.slot, tostring(e.name))
        end
    end

    -- RE-REPORTED WHEN THE INPUT GROWS. Session 7636 logged this line at
    -- 19:20:44 with ONE row's GUID known, and never again -- by 19:21:28 all
    -- four were known and the run's real answer went unlogged. A one-shot
    -- report on a board that fills in over the first minute reports the
    -- emptiest moment it will ever have.
    if F._netid.conn_said ~= guids then
        F._netid.conn_said = guids
        local gg = {}
        for _, row in ipairs(_dmg.order) do
            gg[#gg + 1] = ("row %d=%s"):format(row.slot,
                row.owner_guid and ("0x%x"):format(row.owner_guid) or "nil")
        end
        local ng, np = 0, 0
        for _ in pairs(guid_at) do ng = ng + 1 end
        for _ in pairs(peer_at) do np = np + 1 end
        -- Every half of the search, always. Which one came back empty is the
        -- whole diagnosis: no GUID hit means the records are not reachable
        -- from the manager, no peer hit means they are reachable but hold
        -- nothing that identifies a slot, and both non-zero with no delta
        -- means they are not one record.
        local nc = 0
        for _ in pairs(conns) do nc = nc + 1 end
        R.log(("[rsmm.damage] connection join: mgr=0x%x%s, %d object(s) walked, "
               .. "rows [%s]%s, %d guid hit(s), %d peer hit(s), %d connection(s) "
               .. "(%d off the map list, node %s), locator %s, pairs [%s]")
              :format(mgr, F._dmg_vft_text(mgr), #objs,
                      table.concat(gg, " "), dup and " (SHARED — not per-player)" or "",
                      ng, np, nc, walked,
                      node_at and ("0x%x"):format(node_at) or "none",
                      bestd and ("%s0x%x"):format(bestd < 0 and "-" or "+",
                                                  bestd < 0 and -bestd or bestd)
                             or "none",
                      #notes > 0 and table.concat(notes, ", ") or "none"))
    end

    -- ANCHOR. This machine is not one of its own peers, so the local row
    -- pairing with a peer slot means the record is shared, not owned.
    for row, e in pairs(pair) do
        if e and row.is_local then
            R.log(("[rsmm.damage] connection join REFUSED: this machine's row "
                   .. "pairs with peer %q, and a peer is by definition another "
                   .. "machine"):format(tostring(e.name)))
            F._netid.conn_done = true
            return false
        end
    end
    -- DISTINCTNESS.
    local by = {}
    for row, e in pairs(pair) do
        if e and e.name then
            if by[e.name] then
                R.log(("[rsmm.damage] connection join REFUSED: rows %d and %d both "
                       .. "pair with %q"):format(by[e.name].slot, row.slot, e.name))
                F._netid.conn_done = true
                return false
            end
            by[e.name] = row
        end
    end

    local named = 0
    for row, e in pairs(pair) do
        if e and e.name and not row.is_local and _dmg.names[row.slot] == nil then
            row.label, row.label_guess, row.player = e.name, false, e.name
            F._netid.conn_hit[row.key] = e
            named = named + 1
        end
    end
    if named > 0 then
        F._netid.conn_done = true
        R.log(("[rsmm.damage] CONNECTION JOIN PROVEN: %d row(s) named from the "
               .. "connection record the engine routes by — the object that "
               .. "holds the hero's creatingSystemGUID also holds the peer "
               .. "slot, so the pairing is an equality, not a guess"):format(named))
    end
    return named > 0
end

--- A heap object's vftable as an RVA, for the log. "" when it has none.
function F._dmg_vft_text(obj)
    local mb = I.module_base and I.module_base()
    local vft = I.read_u64 and I.read_u64(obj)
    if mb and mb ~= 0 and _ptr_plausible(vft) and vft > mb then
        return (" (vftable rva 0x%x)"):format(vft - mb)
    end
    return ""
end

--- One-shot: what session ids does this row's net component reach?
---
--- Logs every hit AND the empty result. "The component holds no session id"
--- and "the probe never ran" are the same silence otherwise, and that
--- ambiguity is what cost session 8f36 a whole playtest.
function F._dmg_probe_netid(row, targets)
    if F._netid.probed[row.key] then return F._netid.hits[row.key] end
    if not targets or not I.read_u64 then return nil end
    local ent = I.read_u64(row.key + DMG.HERO_ENTITY_OFF)
    if not _ptr_plausible(ent) then return nil end
    local nc = R.net.component(ent)
    if not nc then
        if not F._netid.said then
            F._netid.said = true
            R.log(("[rsmm.damage] net id: row %d has no net component — the "
                   .. "peer-id join cannot be probed"):format(row.slot))
        end
        return nil
    end
    F._netid.probed[row.key] = true
    local hits = F._dmg_scan_session(nc, F._netid.WIN, targets, nil)
    for off = 0, F._netid.WIN - 8, 8 do
        local p = F._dmg_pread(nc + off, 8)
        if _ptr_plausible(p) then
            for _, h in ipairs(F._dmg_scan_session(p, F._netid.HOPWIN, targets, { off })) do
                hits[#hits + 1] = h
            end
        end
    end
    -- TWO hops, but only down the three pointers the disassembly names.
    --
    -- NamedEvent_NetSend (0x140721630) and NamedEvent_NetSendToPeer say where
    -- identity actually lives on this component:
    --
    --     [C+0xc0]->vft[0x88](&out)  -> ptr whose [0] is the LOCAL session
    --     [C+0xb8]->vft[0x18](&out)  -> ptr to the session this entity talks to
    --     [C+0xc8]                   -> the scene that sends to a session
    --
    -- Two things follow. Sessions are compared as a single QWORD
    -- (`local_res20 != *param_3`), so the netcode's session is 8 bytes and the
    -- lobby's is a 32-character string -- they are not the same value, which
    -- is why no scan for the GUID could ever hit. And the value is reached
    -- through a VCALL, so it sits deeper than the one hop above. If that qword
    -- is a pointer to a peer object, the object is where a name or a GUID
    -- would be, and that is exactly two hops down these three fields.
    --
    -- Bounded to the named fields on purpose: this is a read of a known
    -- structure, not a wider sweep.
    for _, field in ipairs(F._netid.DEEP) do
        local obj = I.read_u64(nc + field)
        if _ptr_plausible(obj) then
            for _, h in ipairs(F._dmg_scan_session(obj, F._netid.DEEPWIN, targets, { field })) do
                hits[#hits + 1] = h
            end
            for off = 0, F._netid.DEEPWIN - 8, 8 do
                local p = F._dmg_pread(obj + off, 8)
                if _ptr_plausible(p) then
                    for _, h in ipairs(F._dmg_scan_session(p, F._netid.HOPWIN,
                                                           targets, { field, off })) do
                        hits[#hits + 1] = h
                    end
                end
            end
        end
    end
-- THE OWNER FIELD, read exactly where the engine reads it.
    --
    -- oCSLNetworkObject::vft[0x18] (0x1408c0d40) is one line:
    --
    --     *out = *(*(netobj + 0x100) + 0x28);
    --
    -- so the session an entity replicates to is `*(*(*(C+0xb8)+0x100)+0x28)`,
    -- a plain three-hop field path. No vcall needed, and nothing here is a
    -- guess about WHICH offsets -- the disassembly names all three.
    --
    -- The qword itself is logged per row whatever it is. If the four rows hold
    -- four different values it is the owner key, and the only open question is
    -- what maps it to a name; if they are all equal it is not.
    do
        local owner = F._dmg_netid_walk(nc, F._netid.OWNER_PATH)
        local raw
        local o = F._dmg_netid_walk(nc, { 0xb8, 0x100 })
        if o then raw = I.read_u64(o + 0x28) end
        if raw and F._netid.owner_said < 4 then
            F._netid.owner_said = F._netid.owner_said + 1
            R.log(("[rsmm.damage] net id: row %d owner session = 0x%x%s")
                  :format(row.slot, raw,
                          _ptr_plausible(raw) and " (a pointer)" or ""))
        end
        -- If it is a pointer, the object behind it is where a session STRING
        -- would live -- one hop past what any earlier pass reached.
        if owner then
            for _, h in ipairs(F._dmg_scan_session(owner, F._netid.DEEPWIN,
                                                   targets, F._netid.OWNER_PATH)) do
                hits[#hits + 1] = h
            end
            if not F._netid.owner_vft_said then
                local mb = I.module_base and I.module_base()
                local vft = I.read_u64(owner)
                if mb and mb ~= 0 and _ptr_plausible(vft) and vft > mb then
                    F._netid.owner_vft_said = true
                    R.log(("[rsmm.damage] net id: owner object vftable rva 0x%x")
                          :format(vft - mb))
                end
            end
        end
    end
    -- The net object's VFTABLE, once. Its slot 0x18 returns the session this
    -- entity replicates to; decompiling that one function statically answers
    -- the whole question, and the RVA is the only thing the exe cannot tell me
    -- without a live instance.
    if not F._netid.vft_said then
        local obj = I.read_u64(nc + 0xb8)
        local mb = I.module_base and I.module_base()
        if _ptr_plausible(obj) and mb and mb ~= 0 then
            local vft = I.read_u64(obj)
            if _ptr_plausible(vft) and vft > mb then
                F._netid.vft_said = true
                R.log(("[rsmm.damage] net id: net object vftable rva 0x%x "
                       .. "(slot 0x18 = the session this entity replicates to)")
                      :format(vft - mb))
            end
        end
    end
    F._netid.hits[row.key] = hits
    -- Cap the per-row detail. Session 9e4f printed thirty of these, which is
    -- a lot of log for one fact ("this row reaches N locators naming M
    -- players"); the counts are what a reader acts on, the first few lines are
    -- enough to see the shape.
    local who, nwho = {}, 0
    for _, h in ipairs(hits) do
        if h.m and not who[h.m.name] then who[h.m.name] = true; nwho = nwho + 1 end
    end
    -- Once per row per RUN. The probe re-runs every chapter (its cache is
    -- per controller, and a chapter rebuilds them), and Sky's 2026-10-07 log
    -- repeated this block after each of 11 chapters -- ~40 lines a chapter
    -- of the same shape, burying the lines a reader needed.
    F._netid.said_rows = F._netid.said_rows or {}
    if F._netid.said_rows[row.slot] then return hits end
    F._netid.said_rows[row.slot] = true
    for i, h in ipairs(hits) do
        if i > 4 then break end
        R.log(("[rsmm.damage] net id: row %d (%s) netcomp%s +0x%x is %q (%s)")
              :format(row.slot, tostring(row.label),
                      F._dmg_netid_path_text(h.path),
                      h.off, tostring(h.m.name), h.kind))
    end
    if #hits > 4 then
        R.log(("[rsmm.damage] net id: row %d has %d locator(s) naming %d "
               .. "player(s) (showing 4)"):format(row.slot, #hits, nwho))
    end
    if #hits == 0 then
        R.log(("[rsmm.damage] net id: row %d (%s) netcomp 0x%x carries no lobby "
               .. "session id and no member pointer within +0x%x, direct or one hop")
              :format(row.slot, tostring(row.label), nc, F._netid.WIN))
    end
    return hits
end

--- Read the ADOPTED locator on one row and claim the member it names.
function F._dmg_apply_netid(row, targets)
    local L = F._netid
    if not L.off or not targets or not I.read_u64 then return false end
    local ent = I.read_u64(row.key + DMG.HERO_ENTITY_OFF)
    if not _ptr_plausible(ent) then return false end
    local nc = R.net.component(ent)
    if not nc then return false end
    local base = F._dmg_netid_walk(nc, L.path)
    if not base then return false end
    local m
    if L.kind == "string" then
        local s = R.debug.stdstring_at and R.debug.stdstring_at(base + L.off)
        local hit = (type(s) == "string") and targets.hex[s:lower()] or nil
        m = hit and hit.m or nil
    elseif L.kind == "ptr" then
        local q = I.read_u64(base + L.off)
        -- The member table is rebuilt every pass, so a pointer that has since
        -- become shared stops naming anyone rather than keeping a stale answer.
        m = (type(q) == "number") and targets.ptr[q] or nil
    else
        local q = I.read_u64(base + L.off)
        local hit = (type(q) == "number") and targets.hex[("%016x"):format(q)] or nil
        m = hit and hit.m or nil
    end
    if not m then return false end
    local names = F._dmg_name_set()
    if not names or not names[m.name] then return false end
    return F._dmg_claim(row, names, m.name, ("net id +0x%x (%s)"):format(L.off, L.kind))
end

--- "netcomp +0xb8 -> +0x40 ->" -- the pointer path, for the log.
function F._dmg_netid_path_text(path)
    if not path then return "" end
    local t = {}
    for _, v in ipairs(path) do t[#t + 1] = ("+0x%x ->"):format(v) end
    return " " .. table.concat(t, " ")
end

--- A locator key, so hits from different rows can be compared. The PATH is
--- part of the identity: the same offset reached two different ways is two
--- different locators.
function F._dmg_netid_key(h)
    local p = h.path and table.concat(h.path, ",") or "-"
    return ("%s|%s|%x"):format(p, tostring(h.kind), h.off)
end

--- Walk an adopted locator's pointer path from the net component. Guarded, so
--- a path that no longer resolves returns nil instead of faulting.
function F._dmg_netid_walk(nc, path)
    local base = nc
    if not path then return base end
    for _, v in ipairs(path) do
        base = I.read_u64(base + v)
        if not _ptr_plausible(base) then return nil end
    end
    return base
end

--- Discovery, adoption and use, one pass. Background thread only.
---
--- Adoption needs BOTH gates, and both exist because a single-row agreement is
--- exactly what the hero-id probe had when it adopted +0x1b60, an offset the
--- engine never touches:
---
---   1. ANCHOR. The locator must name the LOCAL player on the local row.
---      Steam already told us who that is, so this is a fact to check against,
---      not another inference.
---   2. DISTINCTNESS. Read on every probed row, the locator must name a
---      DIFFERENT member each time. A field that answers the same on two rows
---      is a lobby-wide pointer, not an owner.
function F._dmg_netid_pass()
    -- The GUID join FIRST: it is the only one of these built on a field the
    -- disassembly names outright, and it costs a table lookup per (row,
    -- member) pair. Everything below is a search.
    if F._dmg_guid_join() then return true end
    -- FIRST, because it is the only one that is read rather than searched.
    if F._dmg_rak_join() then return true end
    -- Then the registry walk, then the hero-side scans.
    if F._dmg_conn_join() then return true end
    if F._dmg_peer_join() then return true end
    local targets = F._dmg_netid_targets()
    if not targets then return false end

    -- Adopted: two reads per unnamed row and nothing else.
    if F._netid.off then
        local named = false
        for _, row in ipairs(_dmg.order) do
            if not row.player and _ptr_plausible(row.key) then
                if F._dmg_apply_netid(row, targets) then named = true end
            end
        end
        return named
    end

    -- Discovery. Every row, once each; rows board over the first minute of a
    -- run, so this keeps running until a candidate survives both gates.
    for _, row in ipairs(_dmg.order) do
        if _ptr_plausible(row.key) then F._dmg_probe_netid(row, targets) end
    end

    local me
    local ok, nm = pcall(R.player.name)
    if ok and type(nm) == "string" and nm ~= "" then me = nm end
    if not me then return false end

    -- The anchor row's candidate locators: those that read the local player.
    local anchor
    for _, row in ipairs(_dmg.order) do
        if row.is_local then anchor = row break end
    end
    if not anchor or not F._netid.hits[anchor.key] then return false end
    local cand = {}
    for _, h in ipairs(F._netid.hits[anchor.key]) do
        if h.m and h.m.name == me then cand[F._dmg_netid_key(h)] = h end
    end
    if next(cand) == nil then return false end

    -- Distinctness across every other probed row.
    local seen = { [me] = true }
    local rows = 0
    for _, row in ipairs(_dmg.order) do
        if row ~= anchor and F._netid.hits[row.key] then
            rows = rows + 1
            local got = {}
            for _, h in ipairs(F._netid.hits[row.key]) do
                got[F._dmg_netid_key(h)] = h
            end
            for key, _ in pairs(cand) do
                local h = got[key]
                if not h or not h.m or seen[h.m.name] then
                    cand[key] = nil
                else
                    seen[h.m.name] = true
                end
            end
        end
    end
    -- One ally row is the minimum: agreeing with itself proves nothing.
    if rows == 0 then return false end

    local key, hit = next(cand)
    if not key then return false end
    if next(cand, key) ~= nil then
        -- Several locators survived. Any of them would work, but picking one
        -- at random makes the log unreproducible; take the lowest offset.
        for k, h in pairs(cand) do
            if h.off < hit.off then key, hit = k, h end
        end
    end
    F._netid.off, F._netid.path, F._netid.kind = hit.off, hit.path, hit.kind
    R.log(("[rsmm.damage] NET ID JOIN PROVEN: netcomp%s +0x%x (%s) holds the "
           .. "owning player's session id — it reads %q on this machine's own "
           .. "row and a different lobby member on every other row. Rows are "
           .. "named from the engine's replication data, not from a search.")
          :format(F._dmg_netid_path_text(hit.path), hit.off, hit.kind, me))
    return F._dmg_netid_pass()
end

--- Learn "this entity is driven by this session" from a networked event.
---
--- SELF-VERIFYING, and that is the entire design. The engine stamps ev+0x38
--- with the session id of the machine that raised the event
--- (NamedEvent_NetSend), and the lobby hands us each member's session id as a
--- string. Whether those two are the same value in different clothes is NOT
--- assumed: this only ever fires when a member's string matches the int64
--- EXACTLY. If the representations never line up, nothing matches, nobody is
--- named, and the board stays on placeholders -- which is the correct failure.
---
--- Contrast with every earlier mechanism: the memory sweep answered at a
--- different offset every time it "worked", and the hero-id probe adopted an
--- offset the engine never touches. Neither could tell you it was wrong. This
--- one is wrong only if it stays silent.
function F._dmg_note_session(entity, session)
    if not _ptr_plausible(entity) or type(session) ~= "number" then return end
    local prev = _dmg.sess_by_entity[entity]
    if prev == session then return end
    _dmg.sess_by_entity[entity] = session
    local m = F._dmg_session_member(session)
    if not m then
        -- Say it ONCE. "The join never matched" and "no events carried a
        -- session" are the same silence otherwise, and telling them apart is
        -- what a playtest is for.
        if not _dmg.sess_warned then
            _dmg.sess_warned = true
            R.log(("[rsmm.damage] event session 0x%x matches no lobby member "
                   .. "session id -- the join is not proven on this build, so "
                   .. "no row will be named from it"):format(session))
        end
        return
    end
    if not _dmg.sess_proven then
        _dmg.sess_proven = true
        R.log(("[rsmm.damage] SESSION JOIN PROVEN: event session 0x%x == lobby "
               .. "member %q. Rows are now named from the engine's own peer "
               .. "id, not from anything found by searching memory.")
              :format(session, m.name))
    end
    -- Bind every row whose controller owns this entity.
    for _, row in ipairs(_dmg.order) do
        if not row.player and _ptr_plausible(row.key) then
            local ent = I.read_u64(row.key + DMG.HERO_ENTITY_OFF)
            if ent == entity then
                local names = F._dmg_name_set()
                if names and names[m.name] then
                    F._dmg_claim(row, names, m.name, "session")
                end
            end
        end
    end
end

--- The ev+0x38 feeder, RETIRED.
---
--- Sessions c536, e736 and 014f all agree: every event the gameplay bus
--- dispatches is the base oCGameNamedEvent (one vftable, 0xf05aa8), and on the
--- base class +0x38 is not a peer -- the values are handles
--- (0x8146_00xx_00000004) and in one case a raw code address. It is the sender
--- only on oCGameNamedEventNetwork subclasses, which this bus never sees.
---
--- So this callback ran on EVERY gameplay event, for a field that could never
--- answer. On the analytics firehose that is the one place per-event Lua work
--- is actually felt, and the meter is the mod that gets blamed for it. The
--- owner lives at *(*(*(netcomp+0xb8)+0x100)+0x28) instead -- read once per
--- row, on the background tick, by F._dmg_probe_netid.
---
--- `R.net.event_session(ev)` is kept: a mod hooking a genuine network event
--- subclass can still read it, and that is where the field IS the sender.


--- Say ONCE how to put real names on this run's board.
---
--- The board cannot work it out on its own. The engine hands us a set of
--- players and a set of hero objects and nothing linking the two: the hero
--- entity carries no hero id, no player id and no name, so every row->player
--- answer the meter ever produced by searching memory was a coincidence (nine
--- "successes", nine different offsets, one of them provably the wrong person).
--- player_1..player_4 IS the mechanism, not a workaround for a missing one.
function F._dmg_label_hint()
    if _dmg.hinted then return end
    local ok, members = pcall(R.lobby.members)
    if not ok or type(members) ~= "table" then return end
    -- MORE ROWS THAN PLAYERS ON THE ROSTER. Session c236: four rows fighting,
    -- one lobby member all run -- this client parsed its OWN attributes three
    -- times and was never sent anybody else's. No join can help there, because
    -- there is no name to assign; the meter is missing the input, not the
    -- link. That case used to fall out of the `#members < 2` guard below and
    -- say nothing at all, which reads exactly like a broken join.
    if #members < 2 then
        local allies = 0
        for _, row in ipairs(_dmg.order) do
            if not row.is_local then allies = allies + 1 end
        end
        if allies > 0 and not _dmg.roster_warned then
            _dmg.roster_warned = true
            R.log(("[rsmm.damage] %d ally row(s) on the board but %d lobby "
                   .. "member(s) known — this client was never sent the other "
                   .. "players' lobby attributes, so no ally NAME exists to "
                   .. "assign this run (set player_1..player_4 in the config "
                   .. "to label them)"):format(allies, #members))
        end
        return
    end
    local unnamed = 0
    for _, row in ipairs(_dmg.order) do
        if not row.is_local and not _dmg.names[row.slot] then unnamed = unnamed + 1 end
    end
    if unnamed == 0 then return end
    _dmg.hinted = true
    R.log(("[rsmm.damage] %d row(s) have no proven name. This run's lobby: %s")
          :format(unnamed, F._dmg_roster_text(members)))
    R.log("[rsmm.damage] to label the board, set player_1..player_4 in the "
          .. "damage-meter config, in JOIN ORDER (row N = player_N). Those "
          .. "always win, and they are the only EXACT method: the engine gives "
          .. "the meter nothing that links a hero object to a player.")
end

end
