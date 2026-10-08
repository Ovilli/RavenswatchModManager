-- R.damage, part 2: WHO a row is -- naming the ally rows (hero-id probe, name sweep and claims, lobby refresh).
--
-- Split out of rsmm/damage.lua (2026-09-26), which loads it; see that file's
-- header for the meter as a whole. Everything here is defined on the shared
-- `F` / `R` tables or on the `_dmg` / `DMG` tables damage.lua owns, so it
-- runs the same as it did inline. The env is checked against an explicit key
-- list: a nil value is no key in Lua, so a pairs() sweep would see nothing.

return function(env)

for _, key in ipairs({ "I", "R", "F", "_dmg", "_ptr_plausible", "LOBBY_REFRESH_SLOT", "LOBBY_HOOK" }) do
    if env[key] == nil then
        error("rsmm.damage_identity: parent did not pass env." .. key, 0)
    end
end

local I, R, F          = env.I, env.R, env.F
local _dmg             = env._dmg
local _ptr_plausible   = env._ptr_plausible
local LOBBY_REFRESH_SLOT = env.LOBBY_REFRESH_SLOT
local LOBBY_HOOK       = env.LOBBY_HOOK

--- Re-label ally rows once the lobby roster is known.
---
--- Rows are created the instant an ally deals damage, which is usually before
--- the background scan has found the lobby. Without this they would keep the
--- "Player N" placeholder for the whole run even though the name is available
--- seconds later.
--- Find the row-side field that carries the lobby's `RequestedHero` id.
---
--- Names are matched to rows BY POSITION today: `allies[rank]`, i.e. the order
--- allies happened to first deal damage in, which is not the lobby's order and
--- is wrong as often as it is right (rows carry `label_guess` for exactly this
--- reason). The join that would be exact is the hero: every lobby member record
--- carries `RequestedHero` (+0x10), so if the row's own object holds the same
--- id at some offset, name and row line up with no guessing at all.
---
--- Rather than hand-RE that offset over several launches, let one session find
--- it: sweep each row's controller for a dword that equals one of the known
--- hero ids, and keep only the offsets where EVERY row reads a DIFFERENT known
--- id. A field that is constant across players, or that only matches for one of
--- them, is not the hero id — the discriminator is the same "must differ across
--- siblings" trick that finds abstract vtable slots.
---
--- Pure page-guarded reads, once per session, and only when a co-op lobby has
--- actually produced two identified members and two rows.
local HERO_ID_PROBE = { done = false, LO = 0, HI = 0x2000,
                        HOP_HI = 0x800,   -- how far into a hero definition
                        BUDGET = 20000,   -- probes per background tick; the deep scan is ~900k,
                                          -- so this finishes it inside a minute
                        cursor = nil, hits = nil, rows_n = 0, hop = nil,
                        off = nil, w = 4, attempts = 0, MAX_ATTEMPTS = 6,
                        -- Seconds a restart-worthy change has to wait when one
                        -- just happened. The scan restarts whenever the row
                        -- COUNT changes, which is right (a new row is a bigger
                        -- sample and may veto an offset) but was unbounded: a
                        -- board that forks rows -- a transform, a respawn, an
                        -- ally the build cannot identify -- threw the ~900k
                        -- probe scan back to phase 1 as often as rows appeared,
                        -- so it burned its per-tick budget forever and never
                        -- finished. Coalescing costs nothing: `rows_n` is left
                        -- stale while cooling, so the restart still happens,
                        -- just once for a burst instead of once per row.
                        RESTART_EVERY = 30, restarted_at = nil }

--- Read a hero id of width `w` at `va`.
---
--- WIDTH MATTERS. The first version read dwords only, and a hero id is a small
--- number (session ea68's lobby: 2, 4, 5, 6) — exactly the kind of value an
--- engine stores in a BYTE. A dword read over a byte field picks up whatever
--- the next three bytes hold, so the id is invisible unless those happen to be
--- zero. That sweep reported "no offset distinguishes the rows" on a real
--- 4-player run; it was never in a position to see a u8 or u16 field.
--- PAGE CACHE for the probe sweeps.
---
--- Every I.read_* is a page check — one VirtualQuery — before it copies its
--- 1..8 bytes. That is the right shape for a mod poking at a struct, and the
--- wrong one entirely for these sweeps: they budget 20,000 (hero-id) and
--- 24,000 (owner) probes PER TICK, so between them they were asking the OS
--- ~44,000 times a second whether a page was readable. Under Proton each of
--- those goes through Wine's memory manager and takes the process VM lock —
--- the same lock the game's own thread needs to touch memory. Nothing runs on
--- the main thread, and the player still feels a stutter. That is the report
--- this exists to answer ("only this mod left, still stutters").
---
--- One read_block per 4 KiB page instead, unpacked from the snapshot: a
--- sequential sweep of a 0x2000 window drops from 8,192 syscalls to 2.
---
--- Cache lifetime is ONE TICK (F._dmg_pflush), so a value is at most a tick
--- stale — irrelevant to these probes, which are looking for a field that
--- holds the same id all run. Bounded to PAGES blocks so a scattered sweep
--- cannot turn into megabytes of Lua strings; past that it just reads the old
--- way.
F._pg = { SIZE = 0x1000, PAGES = 256, blocks = {}, n = 0 }

function F._dmg_pflush()
    if F._pg.n > 0 then F._pg.blocks, F._pg.n = {}, 0 end
end

--- Guarded single read, the fallback for anything the cache cannot serve.
function F._dmg_read_raw(va, w)
    if w == 1 then return I.read_u8(va) end
    if w == 2 then return I.read_u16 and I.read_u16(va) end
    if w == 8 then return I.read_u64(va) end
    return I.read_u32(va)
end

local _PG_FMT = { [1] = "<I1", [2] = "<I2", [4] = "<I4", [8] = "<I8" }

--- Read `w` bytes at `va` through the page cache.
function F._dmg_pread(va, w)
    if type(va) ~= "number" or va <= 0 then return nil end
    if not I.read_block then return F._dmg_read_raw(va, w) end
    local base = va - (va % F._pg.SIZE)
    local blk = F._pg.blocks[base]
    if blk == nil then
        if F._pg.n >= F._pg.PAGES then return F._dmg_read_raw(va, w) end
        blk = I.read_block(base, F._pg.SIZE) or false
        F._pg.blocks[base], F._pg.n = blk, F._pg.n + 1
    end
    if not blk then return nil end
    local off = va - base + 1
    -- A field straddling the page boundary is not in this snapshot; the
    -- guarded read handles it (and costs one syscall, rarely).
    if off + w - 1 > #blk then return F._dmg_read_raw(va, w) end
    local ok, v = pcall(string.unpack, _PG_FMT[w] or "<I4", blk, off)
    if not ok then return nil end
    return v
end

function F._dmg_read_id(va, w)
    return F._dmg_pread(va, w)
end

--- @param wide  also sweep BYTE and WORD fields. ~3x the reads, so only the
---              background tick asks for it; the boarding path stays dword-only.
function F._dmg_probe_hero_field(wide)
    if HERO_ID_PROBE.done then return end
    local okm, members = pcall(R.lobby.members)
    if not okm or type(members) ~= "table" then return end
    local ids, n = {}, 0
    for _, m in ipairs(members) do
        if m.hero_id and not ids[m.hero_id] then
            ids[m.hero_id] = m.name
            n = n + 1
        end
    end
    if n < 2 then return end
    local rows = {}
    for _, row in ipairs(_dmg.order) do
        -- Rows are keyed by controller, entity OR net id; only the pointer
        -- keys are objects we can read fields out of.
        if _ptr_plausible(row.key) then rows[#rows + 1] = row end
    end
    -- SAMPLE SIZE. Two rows is the minimum that can discriminate anything, but
    -- in a four-player lobby it is also the sample most likely to leave an
    -- unrelated field looking unique — and adopting a wrong offset MERGES two
    -- players (2026-08-18, session 29a8: four players, two rows). So wait for a
    -- third row whenever the lobby says a third player exists; a two-player
    -- lobby still adopts on two, since that is every row there will ever be.
    local need = n >= 3 and 3 or 2
    if #rows < need then return end
    -- A NEW row is new evidence: restart the scan so every offset is judged
    -- against the biggest sample available. Otherwise an offset that looked
    -- unique against three rows is adopted while a fourth would have vetoed it.
    local c = HERO_ID_PROBE.cursor
    -- A WIDER call is new evidence too. The damage path probes u32 only; the
    -- background tick probes u8/u16/u32. Resuming the narrow scan's cursor
    -- would skip the byte and word passes entirely — and a byte-sized hero id
    -- is the case this sweep exists for.
    local churn = (HERO_ID_PROBE.rows_n ~= #rows)
    local now = F._dmg_now()
    local cooling = churn and HERO_ID_PROBE.restarted_at ~= nil
                    and (now - HERO_ID_PROBE.restarted_at) < HERO_ID_PROBE.RESTART_EVERY
    if not c or (churn and not cooling)
       or ((wide and true or false) and not c.wide) then
        c = { phase = 1, wi = 1, off = HERO_ID_PROBE.LO, hop = 0, ptrs = nil,
              wide = wide and true or false }
        HERO_ID_PROBE.cursor, HERO_ID_PROBE.hits = c, {}
        HERO_ID_PROBE.rows_n = #rows
        HERO_ID_PROBE.restarted_at = now
    end

    local hits = HERO_ID_PROBE.hits
    -- Widths, each with its own stride: a byte field can start anywhere, a word
    -- field on any even address.
    local widths = wide and { 1, 2, 4 } or { 4 }

    -- Two phases. DIRECT looks for the id as a field on the controller —
    -- which three live four-player sessions have now reported as "no offset
    -- distinguishes the rows", at every width. HOP looks one pointer deep,
    -- because that is where an engine of this shape actually keeps it: the
    -- controller holds a pointer to the hero DEFINITION, and the id is a field
    -- of the definition. Same evidence test either way, and it is a strong one
    -- — three or more rows reading DISTINCT ids that are all on the roster, at
    -- one offset. Resumable and budgeted: the hop space is ~900k probes, which
    -- is a few minutes of background ticks, not a frame.
    -- One FIELD, not one width. A byte holding 4 reads as 4 through u8, u16 and
    -- u32 whenever the bytes after it happen to be zero, so the same location
    -- was landing in `hits` three times and every deep scan ended "ambiguous"
    -- — the one outcome that adopts nothing. Widths are tried narrowest first
    -- and the narrowest wins: a byte field read as a dword only works while the
    -- neighbours stay zero, which is exactly the trap the wide sweep was added
    -- to escape.
    local function record(off, hop, w, text)
        for _, h in ipairs(hits) do
            if h.off == off and h.hop == hop then return end
        end
        hits[#hits + 1] = { off = off, hop = hop, w = w, text = text }
    end

    -- GROUND TRUTH, free. Row 1 is the local player, Steam already told us who
    -- that is, and their lobby blob carries their RequestedHero — so any offset
    -- claiming to be the hero id MUST read exactly that id on the local row.
    --
    -- Without this the test only asks that the rows read DISTINCT ids that are
    -- on the roster, and a 0x2000-byte controller scanned at strides 1/2/4 is
    -- thousands of small-int fields, plenty of which satisfy that by accident.
    -- Session 174f did exactly that: it adopted `+0x1b60/u32`, and a sweep of
    -- the shipped exe (2026-08-20) finds ZERO reads or writes at +0x1b60 on any
    -- object base — while every offset this meter uses that IS proven in-game
    -- (+0x15c8 HP, +0x1d80 mirror, +0x1d88 is-local, +0x1db0 stats) shows 11 to
    -- 58. The engine never touches +0x1b60; it was uninitialised memory that
    -- happened to hold three roster hero ids, and every ally name on that board
    -- came from it.
    --
    -- The anchor is exactly as sound as the join it guards: `ids` maps
    -- RequestedHero -> name, so if the local row does not read the local
    -- member's RequestedHero, the join is meaningless for every other row too.
    local anchor_row, anchor_id
    do
        local okme, me = pcall(R.player.name)
        if okme and type(me) == "string" and me ~= "" then
            for _, m in ipairs(members) do
                if m.name == me and m.hero_id then anchor_id = m.hero_id break end
            end
            if anchor_id then
                for _, row in ipairs(rows) do
                    if row.is_local then anchor_row = row break end
                end
            end
        end
    end
    HERO_ID_PROBE.anchored = anchor_row ~= nil

    local function judge(read, strict)
        local seen, matched = {}, 0
        for i, row in ipairs(rows) do
            local v = read(i, row)
            -- The anchor is a veto, not a vote: a wrong value here disqualifies
            -- the offset outright, however well every other row reads.
            if anchor_row and row == anchor_row and v ~= anchor_id then
                return false
            end
            if type(v) == "number" and ids[v] then
                if seen[v] then return false end   -- two rows, one player
                seen[v] = true
                matched = matched + 1
            end
        end
        -- `strict` demands EVERY row, not just `need` of them. The deep scan
        -- searches ~900k offsets instead of 24k, so the coincidence rate is
        -- ~40x higher and "three rows agreed" stops being rare — a scan that
        -- ends ambiguous adopts nothing and the run stays on placeholders.
        -- Requiring the whole board to read a distinct roster id is a test
        -- almost nothing passes by accident.
        --
        -- ⚠ UNTESTED BRANCH. It only differs from the quorum once there are
        -- MORE rows than `need` (four players, quorum three), and a four-row
        -- fixture would not board cleanly in the spec harness. The three-row
        -- deep-scan test exercises this path with strict == need.
        return matched >= (strict and #rows or need)
    end

    -- PHASE 1, the field on the controller itself. Runs to completion in this
    -- call: it is ~24k probes, and the rest of the meter depends on the answer
    -- being ready the moment the second row boards.
    if c.phase == 1 then
        for _, w in ipairs(widths) do
            for off = HERO_ID_PROBE.LO, HERO_ID_PROBE.HI, w do
                if judge(function(_, row)
                        return F._dmg_read_id(row.key + off, w)
                    end) then
                    record(off, nil, w, string.format("+0x%x/u%d", off, w * 8))
                    if #hits >= 8 then break end
                end
            end
            if #hits >= 8 then break end
        end
        -- Anything at all here settles it, one way or the other. The deep scan
        -- below is for the case three live four-player sessions actually
        -- produced: nothing on the controller, at any width.
        c.phase = (#hits == 0) and 2 or 3
    end

    -- PHASE 2, one pointer deep. The controller holds a pointer to the hero
    -- DEFINITION and the id is a field of that — which is why every direct
    -- sweep so far reported "no offset distinguishes the rows". ~900k probes,
    -- so it is budgeted and resumable across background ticks; the evidence
    -- test is the same strong one (three or more rows reading DISTINCT roster
    -- ids at one offset).
    -- ⛔ PHASE 2 IS RE-ONLY, gated on `identity_hunt`.
    --
    -- ~900k page-guarded reads, budgeted at 20k per BACKGROUND TICK, i.e. ~45
    -- ticks of solid probing on every single run. It was ungated, and it is the
    -- heaviest thing the SDK does -- the "lags sometimes hard" the board was
    -- blamed for. What makes it waste rather than cost is that the answer is
    -- already known: three live four-player sessions found no hero id on the
    -- controller at any width, and Ghidra (2026-08-20) showed why -- there are
    -- no fixed component slots on oCEntity, so session 7068's chains were heap
    -- coincidence. The peer table now supplies names by a different route.
    --
    -- Phase 1 stays on for everyone: it is a bounded direct sweep and it is
    -- what would notice if a patch ever DID put the id back on the controller.
    if c.phase == 2 and not _dmg.identity_hunt then
        c.phase = 3
        if not HERO_ID_PROBE.deep_said then
            HERO_ID_PROBE.deep_said = true
            R.log("[rsmm.damage] hero-id deep scan skipped (no id on the "
                .. "controller on this build; enable identity_hunt to re-run it)")
        end
    end
    local budget = HERO_ID_PROBE.BUDGET
    while budget > 0 and c.phase == 2 do
        budget = budget - 1
        local w = widths[c.wi]
        -- One pointer read per OFFSET, reused across every hop and width;
        -- per-probe would triple the cost of the phase.
        if not c.ptrs then
            c.ptrs = {}
            local live = 0
            for i, row in ipairs(rows) do
                local ptr = F._dmg_pread(row.key + c.off, 8)
                c.ptrs[i] = _ptr_plausible(ptr) and ptr or false
                if c.ptrs[i] then live = live + 1 end
            end
            c.live = live
        end
        if c.live >= need
           and c.live == #rows
           and judge(function(i)
                   local ptr = c.ptrs[i]
                   return ptr and F._dmg_read_id(ptr + c.hop, w) or nil
               end, true) then
            record(c.off, c.hop, w, string.format("+0x%x -> +0x%x/u%d",
                                                  c.off, c.hop, w * 8))
        end
        c.hop = c.hop + w
        if c.hop > HERO_ID_PROBE.HOP_HI then
            c.hop, c.wi = 0, c.wi + 1
            if c.wi > #widths then
                c.wi, c.ptrs = 1, nil
                c.off = c.off + 8                  -- pointer slots are aligned
                if c.off > HERO_ID_PROBE.HI then c.phase = 3 end
            end
        end
        if #hits >= 8 then c.phase = 3 end
    end
    -- Still scanning: say nothing. The version that re-ran the whole sweep
    -- every tick logged the same "no offset distinguishes the rows" line each
    -- time, which buried the log without adding one fact.
    if c.phase <= 2 then return end
    HERO_ID_PROBE.cursor = nil

    local known = {}
    for id, nm in pairs(ids) do known[#known + 1] = string.format("%s=%d", nm, id) end
    table.sort(known)
    -- ADOPT the offset, do not just report it. A confirmed hero id is the only
    -- identity a player keeps across a CHAPTER TRANSITION: the engine builds a
    -- fresh hero controller for the next chapter, so rows keyed by the
    -- controller pointer fork — the same player appears twice, the slot counter
    -- runs past the player count ("Player 6", "Player 7"), and the abandoned
    -- rows sit at 0.0 dps for the rest of the run. That is exactly what the
    -- 2026-08-17 evening log shows: seven rows for a four-player lobby, "Juice"
    -- twice, both marked as the local player.
    --
    -- Only an UNAMBIGUOUS sweep is adopted. With two rows several offsets can
    -- coincidentally hold two distinct known ids; keying identity on the wrong
    -- one would merge two different players into one row, which is worse than
    -- the duplicate it fixes. Ambiguity re-arms the probe instead: a later
    -- sweep with more rows narrows it.
    if #hits == 1 then
        HERO_ID_PROBE.off, HERO_ID_PROBE.w = hits[1].off, hits[1].w
        HERO_ID_PROBE.hop = hits[1].hop
        HERO_ID_PROBE.done = true
        HERO_ID_PROBE.text = hits[1].text   -- so a withdrawal can name it
        -- BACKFILL every row that was boarded before the identity existed.
        -- The sweep cannot run until two rows and two named lobby members are
        -- in hand, so the FIRST row — often an ally, since the sweep fires when
        -- the second player deals damage — would otherwise carry no hero id and
        -- fork at the next chapter anyway. That is the residual duplicate the
        -- first version of this fix would still have produced.
        F._dmg_backfill_ids()
    else
        HERO_ID_PROBE.done = false
        HERO_ID_PROBE.attempts = (HERO_ID_PROBE.attempts or 0) + 1
        if HERO_ID_PROBE.attempts >= HERO_ID_PROBE.MAX_ATTEMPTS then
            HERO_ID_PROBE.done = true          -- give up; pointer keys only
        end
    end
    R.log(("[rsmm.damage] hero-id field probe: %d row(s), lobby ids {%s} -> %s")
          :format(#rows, table.concat(known, ", "),
                  #hits == 1 and (hits[1].text .. " ADOPTED as the row identity")
                  or (#hits > 1
                      and ("ambiguous (" .. (function()
                              local ts = {}
                              for _, h in ipairs(hits) do ts[#ts + 1] = h.text end
                              return table.concat(ts, " ")
                          end)() .. "), retrying")
                      or ("no offset distinguishes the rows (widths tried: %s)")
                         :format(wide and "u8 u16 u32" or "u32"))))
end

--- Re-check the adopted hero-id offset against the CURRENT board.
---
--- The probe adopts on the first sample big enough to discriminate (three rows
--- when the lobby seats four) and then sets `done`, whose first act is to make
--- the probe return immediately. So a FOURTH row — the one piece of evidence
--- that could still veto the offset — arrives after the decision and is never
--- consulted. Session 174f: `+0x1b60/u32` adopted at 17:39:54 on three rows,
--- row 4 boarded at 17:40:11, and the offset was never questioned again.
---
--- Withdrawing matters more than mislabelling suggests: `by_hero` is also the
--- chapter-change rebind key, so a wrong identity MERGES two players' rows at
--- the next boundary, which deletes a player's damage rather than misnaming it.
---
--- Cheap: one guarded read per row, on the background tick.
function F._dmg_recheck_hero_field()
    if not HERO_ID_PROBE.off then return end
    local okm, members = pcall(R.lobby.members)
    if not okm or type(members) ~= "table" or #members == 0 then return end
    local ids, anchor_id = {}, nil
    for _, m in ipairs(members) do
        if m.hero_id and m.name then ids[m.hero_id] = m.name end
    end
    local okme, me = pcall(R.player.name)
    if okme and type(me) == "string" and me ~= "" then
        for _, m in ipairs(members) do
            if m.name == me and m.hero_id then anchor_id = m.hero_id break end
        end
    end
    -- Only POSITIVE contradictions count. A row whose fields are not live yet
    -- reads nil, and nil is not evidence against the offset.
    local seen, why = {}, nil
    for _, row in ipairs(_dmg.order) do
        if _ptr_plausible(row.key) then
            local v = F._dmg_hero_id(row.key)
            if type(v) == "number" then
                if row.is_local and anchor_id and v ~= anchor_id then
                    why = ("the local row reads hero %d but this machine's "
                           .. "player is hero %d"):format(v, anchor_id)
                elseif seen[v] then
                    why = ("rows %d and %d both read hero %d"):format(
                        seen[v], row.slot, v)
                elseif not ids[v] then
                    why = ("row %d reads hero %d, which is nobody on the "
                           .. "roster"):format(row.slot, v)
                end
                seen[v] = row.slot
            end
        end
        if why then break end
    end
    if not why then return end

    R.log(("[rsmm.damage] WITHDRAWING the hero-id offset %s: %s. Every name it "
           .. "handed out is unproven, so those rows go back to placeholders.")
          :format(HERO_ID_PROBE.text or "?", why))
    HERO_ID_PROBE.off, HERO_ID_PROBE.hop, HERO_ID_PROBE.w = nil, nil, nil
    HERO_ID_PROBE.text, HERO_ID_PROBE.done = nil, false
    HERO_ID_PROBE.cursor, HERO_ID_PROBE.hits, HERO_ID_PROBE.rows_n = nil, {}, nil
    -- A withdrawal is not row churn; it must not be throttled by the restart
    -- cooldown, or the re-scan it exists to trigger waits up to RESTART_EVERY.
    HERO_ID_PROBE.restarted_at = nil
    _dmg.by_hero = {}
    for _, row in ipairs(_dmg.order) do
        row.hero_id = nil
        -- A name the SWEEP proved (`row.player`) or one the player configured
        -- stands; only the hero-join's guesses are taken back.
        if not row.player and not _dmg.names[row.slot] then
            row.label = F._dmg_label_for(row.slot, row.is_local)
            row.label_guess = false
        end
    end
end

--- Give every row an identity it is missing. Rows boarded before the sweep
--- adopted an offset have none, and a row without one forks at the next
--- chapter — so this runs when the offset lands AND on the tick, because a
--- controller's fields are not always live the first time it is seen.
function F._dmg_backfill_ids()
    if not HERO_ID_PROBE.off then return end
    for _, r in ipairs(_dmg.order) do
        if not r.hero_id and _ptr_plausible(r.key) then
            r.hero_id = F._dmg_hero_id(r.key)
            if r.hero_id then _dmg.by_hero[r.hero_id] = r end
        end
    end
end

--- The player's identity, stable across chapter transitions. nil until the
--- sweep above has confirmed an offset, or when the value read there is not a
--- hero id the lobby knows about (a re-created controller can be read before
--- its fields are live — the same "not live yet" window hero-capture handles).
function F._dmg_hero_id(hero)
    local off = HERO_ID_PROBE.off
    if not off or not _ptr_plausible(hero) then return nil end
    local base = hero
    -- An adopted HOP offset means the id lives in the object the controller
    -- points at (the hero definition), not on the controller itself.
    if HERO_ID_PROBE.hop then
        base = I.read_u64(hero + off)
        if not _ptr_plausible(base) then return nil end
        off = HERO_ID_PROBE.hop
    end
    local id = F._dmg_read_id(base + off, HERO_ID_PROBE.w)
    if type(id) ~= "number" or id <= 0 or id >= 0x1000 then return nil end
    -- Cross-check against the roster when there is one: the offset was chosen
    -- from a two-row sample, so a value that is not a known hero id means the
    -- field has been re-used and the identity must not be trusted.
    local ok, members = pcall(R.lobby.members)
    if ok and type(members) == "table" and #members > 0 then
        for _, m in ipairs(members) do
            if m.hero_id == id then return id end
        end
        return nil
    end
    return id
end

-- Identity by the player's OWN NAME, found in their controller's memory graph.
--
-- The hero-id join needs the lobby's `RequestedHero` to sit as a dword on the
-- hero controller, and a four-player playtest (2026-08-19, session 5a1d) proved
-- it does not: `4 row(s), lobby ids {...} -> no offset distinguishes the rows`,
-- repeated all run, every ally on a "Player N" placeholder. A placeholder is
-- honest but it is not the point of a damage meter — "who did 3252" has to have
-- an answer.
--
-- So stop hunting the id and hunt the thing already in hand: the gamertag. A
-- player's display name appearing inside their own controller — inline, behind
-- a pointer, or as the heap data of an MSVC std::string — is SELF-EVIDENT
-- identity. It needs no cross-row corroboration the way a bare integer does,
-- because no unrelated field coincidentally spells "Keif_Buddings". One row
-- identified also yields the offset chain, which names every later row in two
-- reads.
--
-- Bounded, resumable, background-thread only: a fixed read budget per tick, a
-- cursor that survives across ticks, and page-guarded reads throughout (a bad
-- address returns nil, it does not fault).
-- (a field on `F`, not a local: rsmm.lua sits at Lua's 200-live-locals cap
-- for the module chunk — one more `local` here fails to COMPILE the whole SDK.)
F._own = {
    WIN = 0x2000,        -- how far into an object a name may sit
    HOP = 0x400,         -- and how far into an object one pointer away. 0x100
                         -- was too shallow to reach a name held deep inside the
                         -- HUD mirror (+0x1d80) or the stats block (+0x1db0),
                         -- which are the two objects on a controller most
                         -- likely to carry one.
    STRIDE = 8,
    BUDGET = 24000,      -- probes per tick. A full row is ~264k over both
                         -- bases, so at 6000 a four-player board took ~3
                         -- minutes to even finish its FIRST pass — longer than
                         -- session fb4f's whole run, which is why nothing was
                         -- named. The reads are page-guarded and cheap.
    -- Every { base = 1|2, off = n, hop = n|nil } that has named a row, learned
    -- on THIS board. Deliberately EMPTY at startup.
    --
    -- It was briefly seeded with the two chains session 7068 recorded
    -- (`entity+0x678 -> +0x2d0`, `entity+0xad8 -> +0x1c0`) on the theory that an
    -- offset chain is a property of the build. Ghidra says otherwise, and the
    -- theory was wrong because those are not offsets into anything:
    --
    --   * Across all 65,347 .pdata functions of the shipped exe there is not a
    --     single site that loads [X+0x678] and then reads [+0x2d0], nor one for
    --     [X+0xad8] -> [+0x1c0]. (The same sweep does find real chains, e.g.
    --     [X+0xb8] -> [+0x20], so it is not blind.)
    --   * +0xad8 is never touched on any register that also walks an entity.
    --   * The one qword-pointer write at +0x678 near entity-shaped code belongs
    --     to `oe::dt::EntityCpntRecapBookPageSettings::~dtor` (FUN_140419aa0),
    --     an unrelated UI settings class; the other site stores a FLOAT there.
    --   * There are no fixed component slots on oCEntity to be found anyway:
    --     Entity_GetNetComponent reaches components through a hash map at
    --     entity+0x5e8/+0x5f0/+0x600 keyed by class id. See its symbol note.
    --
    -- So session 7068's two chains were heap COINCIDENCE — a pointer that
    -- happened to sit at that offset in that run's hero entity, landing that
    -- far before a string that happened to hold the id. Seeding a coincidence
    -- makes it a prior that runs BEFORE every corroborating check, on every
    -- board, forever. A chain is only trustworthy once it has been observed on
    -- THIS board and survived the one-owner rule below.
    chains = {},
    addrs = nil,         -- where each roster name lives in memory
    addrs_key = nil,     -- the roster those addresses were scanned for
    MAX_HITS = 20000,    -- copies of one needle worth collecting. Both 24 and
                         -- 512 were CEILINGS, not limits: sessions 314f and
                         -- a84f truncated every needle, and a truncated scan
                         -- keeps whichever copies sit LOWEST in the address
                         -- space — never the game-heap object that owns the
                         -- player. A peer id turns up in hundreds of network
                         -- buffers, so the cap has to be far above that or it
                         -- silently decides the answer.
    -- Bytes of address space one tick may examine. `mem_find`'s own default
    -- is 512 MB, which is a debug-probe figure: it is seconds of wall time and
    -- the player feels it as a stall. The lobby sweep has run at 48 MB a tick
    -- all along without a single report, so this sits beside it. The sweep
    -- takes MINUTES to cross the address space at this rate, and that is the
    -- intended trade — it runs on the background thread against a board the
    -- guessed names have already labelled, so finishing sooner buys nothing a
    -- player can see, while finishing louder costs a frame.
    SLICE_MB = 48,
    cursor_va = 0,       -- resume address for the needle at the head of `queue`
    hits_n = 0,          -- hits collected for THAT needle, across its slices
    PAGE = 12,           -- address index granularity (4 KiB), see _dmg_index
    -- There is no time-based rescan, and the `SCAN_EVERY`/`scan_at` pair that
    -- claimed to be one was set and never read by anything. What actually
    -- bounds the scan is `addrs_key` (the roster) plus the chapter epoch, which
    -- drops the cache in F._dmg_next_epoch — a timer would only reintroduce
    -- the periodic address-space walk this all exists to avoid.
    queue = nil,         -- needles still to scan, one per tick
    -- Full address-space sweeps allowed PER ROSTER before the scan gives up.
    --
    -- Without a bound this never stops, and that is what a player feels as a
    -- constant stutter for a whole co-op run. Two things conspire:
    -- `_dmg_probe_owner_fast` gates on `row.player`, which only a VERIFIED
    -- claim sets — a guessed label (`guess_names`, on by default) leaves it
    -- nil forever — so the board can display four correct names and still be
    -- asking to be scanned. And `_dmg_next_epoch` drops `addrs_key` on every
    -- chapter, which re-arms the whole sweep from cursor 0. A run has several
    -- chapters, so the sweep restarts before it finishes and the address space
    -- is walked at SLICE_MB per second, without pause, for the entire run.
    --
    -- A sweep that crossed the address space and claimed nobody will not claim
    -- anybody on a re-run against the same roster, so retrying it forever buys
    -- nothing at all. Two attempts covers the one case a retry can help: a
    -- sweep aborted mid-way by a chapter boundary. Any successful claim clears
    -- the counter, because then the scan is demonstrably working and the rows
    -- still unnamed deserve the next pass.
    SWEEP_TRIES = 2,
    tries = {},          -- roster key -> sweeps started for it
    gave_up = {},        -- roster key -> true once it is not worth retrying
    TRIES = 4,           -- full sweeps per row before it is given up on
    RETRY_AFTER = 20,    -- seconds between them. A chapter is shorter than
                         -- the old 45s, so a row could miss its whole run.
    cursor = nil,        -- { row = <row>, base = 1, off = 0, hop = nil }
    found = 0, swept = 0,
}

--- Where in the process does each player's identity string actually live?
---
--- The blind sweep asks the wrong question. It walks ~264k offsets PER ROW
--- reading a string at every one, which is ~44s of background ticks per row —
--- session fb4f's whole run finished before the first pass did, and nothing
--- was named. The engine can answer the question directly: `mem_find` is a
--- native scan for a byte pattern, so ONE scan per player yields every address
--- that player's peer id is stored at.
---
--- That turns identification into arithmetic. A row owns a name when one of
--- its pointers lands just before one of that name's addresses — the chain
--- session 7068 found by brute force (`entity+0x678 -> +0x2d0`) is exactly the
--- statement "a pointer at entity+0x678 points 0x2d0 bytes before the string".
--- Testing that costs 2048 pointer reads and some subtraction, not 264k string
--- reads, and it is the same evidence.
---
--- Cached against the roster: re-scanning the address space every tick would
--- be far worse than the sweep it replaces.
function F._dmg_find_needles(names)
    if type(I.mem_find) ~= "function" then return nil end
    -- PEER IDS ONLY. A gamertag turns up in chat, the friends list and every
    -- piece of UI text that mentions the player, so scanning for it doubles
    -- the work to produce the noisiest half of the results. The id is not
    -- human-facing, so its copies are the objects that actually own the
    -- player — and it is what named a row in session 314f.
    local keys = {}
    for needle, m in pairs(names) do
        if needle ~= m.name then keys[#keys + 1] = needle end
    end
    table.sort(keys)
    local key = table.concat(keys, "\1")
    if F._own.addrs_key == key and not F._own.queue then return F._own.addrs end
    if #keys == 0 then return nil end

    -- ONE needle per tick, and ONE SLICE of that needle per tick. Each scan is
    -- a native walk of the whole user address space; eight back to back on a
    -- single tick is the stutter session a84f reported, and even ONE unsliced
    -- call is gigabytes of ReadProcessMemory holding the process VM lock —
    -- session a14f's two hard hitches were this call, at the 512 MB default,
    -- three needles at 11:37:03 and two more at 11:40:01.
    --
    -- Dropping `mem_find`'s second return was also a CORRECTNESS bug, and the
    -- quieter one. That value is the resume address, and the whole reason the
    -- native side has one. Without it the sweep stopped dead at the default
    -- budget and never continued, so it searched the low heap — where Lua's
    -- own strings live — and never reached the game's allocations at all.
    -- `capped` counts hits, not bytes, so the log called that a clean scan.
    -- It is the exact failure NAME_SCAN_MB documents for sessions 5736/274f,
    -- reintroduced one layer up, and it is why this scan has never once
    -- claimed a row.
    -- Already swept this roster to no effect. Answer from the cache (which is
    -- nil after a chapter epoch, and a nil answer costs the caller one loop
    -- over the rows) rather than walking the address space again.
    if F._own.gave_up[key] then
        F._own.addrs_key, F._own.queue = key, nil
        return F._own.addrs
    end
    if F._own.addrs_key ~= key then
        local n = (F._own.tries[key] or 0) + 1
        if n > F._own.SWEEP_TRIES then
            F._own.gave_up[key] = true
            F._own.addrs_key, F._own.addrs, F._own.queue = key, nil, nil
            R.log(("[rsmm.damage] identity scan: %d sweep(s) of this roster "
                   .. "named nobody — standing down for the rest of the "
                   .. "session (the board keeps its lobby names; set "
                   .. "player_1..4 in the mod config for names that are never "
                   .. "guesses)"):format(F._own.SWEEP_TRIES))
            return nil
        end
        F._own.tries[key] = n
        F._own.addrs_key, F._own.addrs = key, {}
        F._own.queue, F._own.capped = {}, 0
        -- The slice cursor belongs to the needle at the head of the queue
        -- being dropped here. Left behind, the first needle of the NEXT
        -- roster resumes from a stranger's address and never scans anything
        -- below it. This is also the chapter-epoch path: `_dmg_next_epoch`
        -- clears `addrs_key`, so the very next call lands in this branch.
        F._own.cursor_va, F._own.hits_n = 0, 0
        for i = #keys, 1, -1 do F._own.queue[#F._own.queue + 1] = keys[i] end
    end
    local q = F._own.queue
    if q and #q > 0 then
        -- PEEK, don't pop: the needle stays at the head until its sweep
        -- reaches the end of the address space. Popping here is what made the
        -- unsliced call look complete.
        local needle = q[#q]
        local left = F._own.MAX_HITS - (F._own.hits_n or 0)
        local nxt = 0
        if left <= 0 then
            F._own.capped = (F._own.capped or 0) + 1
        else
            local ok, hits, resume = pcall(I.mem_find, needle, left,
                                           F._own.SLICE_MB,
                                           F._own.cursor_va or 0)
            if ok and type(hits) == "table" then
                local m = names[needle]
                for _, va in ipairs(hits) do
                    if va and va > 0x10000 then
                        F._own.addrs[#F._own.addrs + 1] = { va = va,
                                                            name = m.name }
                        F._own.hits_n = (F._own.hits_n or 0) + 1
                    end
                end
                nxt = (type(resume) == "number") and resume or 0
                if F._own.hits_n >= F._own.MAX_HITS then
                    F._own.capped, nxt = (F._own.capped or 0) + 1, 0
                end
            end
            -- A raise leaves nxt at 0, which retires the needle. Carrying the
            -- cursor forward instead would re-raise on the same slice every
            -- tick for the rest of the run.
        end
        F._own.cursor_va = nxt
        if nxt == 0 then
            table.remove(q)
            F._own.hits_n = 0
        end
        if #q == 0 then
            F._own.queue = nil
            -- Say when a needle hit the ceiling. A truncated scan looks
            -- exactly like a healthy one in the totals, which is how two
            -- sessions were spent chasing the wrong thing.
            R.log(("[rsmm.damage] identity scan: %d needle(s) -> %d "
                   .. "address(es) in memory%s"):format(
                #keys, #F._own.addrs,
                (F._own.capped or 0) > 0
                    and (", %d TRUNCATED at the %d cap"):format(
                        F._own.capped, F._own.MAX_HITS) or ""))
        end
    end
    return F._own.addrs
end

--- Index the found addresses by page.
---
--- With the cap raised, a four-player lobby can have a couple of thousand
--- addresses, and the naive test (every pointer against every address) is
--- 2048 x 2000 comparisons per row. Bucketing by page makes each test a
--- constant handful: a string within +0x400 of a pointer is on that pointer's
--- page or the next one.
function F._dmg_index(addrs)
    -- MEMOISED on the address list's identity and length. `addrs` is
    -- F._own.addrs, which is append-only while the needle queue drains and
    -- frozen for the rest of the run -- but the caller runs on every
    -- background tick, and with `guess_names` on a row keeps `row.player ==
    -- nil` even once it has a label, so "every tick" means "for the whole
    -- session". Rebuilding a couple of thousand buckets each time is pure
    -- waste, and it is waste that scales with the number of players.
    if F._own.page_src == addrs and F._own.page_n == #addrs then
        return F._own.page_idx
    end
    local by_page = {}
    for _, a in ipairs(addrs) do
        local k = a.va >> F._own.PAGE
        local b = by_page[k]
        if not b then b = {}; by_page[k] = b end
        b[#b + 1] = a
    end
    F._own.page_src, F._own.page_n, F._own.page_idx = addrs, #addrs, by_page
    return by_page
end

--- Every roster name this row's own memory reaches, as a set.
---
--- Direct (the string is inside the row's object) or one hop (a pointer in the
--- row's object lands within +0x%x of it). Both are the same test against a
--- known address, so neither costs a string read.
function F._dmg_row_names(row, by_page)
    local found, n = {}, 0
    -- STRUCTURED, not a log string. `_dmg_chain_name` replays a
    -- {base, off, hop} in two reads and names every later row for free, but it
    -- can only do that if this pass hands the chain back as numbers. Recording
    -- the formatted text alone left that replay unreachable — `if chain.base`
    -- was false for every chain this path found — so a board with one unnamed
    -- row paid for a full address-space scan every tick for the rest of the
    -- session. The names came out right; the game hitched for the whole run.
    local function note(name, how, base, off, hop)
        if not found[name] then
            found[name] = { how = how, base = base, off = off, hop = hop }
            n = n + 1
        end
    end
    -- Every address within `span` bytes after `from`, via the page index.
    -- `mk(d)` returns the human text AND the chain that produced it.
    local function near(from, span, mk)
        local first, last = from >> F._own.PAGE, (from + span) >> F._own.PAGE
        for k = first, last do
            local b = by_page[k]
            if b then
                for _, a in ipairs(b) do
                    if a.va >= from and a.va - from <= span then
                        note(a.name, mk(a.va - from))
                    end
                end
            end
        end
    end
    local bases = { { row.key, "ctrl" } }
    local ent = I.read_u64(row.key + 0x08)
    if _ptr_plausible(ent) then bases[#bases + 1] = { ent, "entity" } end
    -- `bi` IS `chain.base`: 1 = the controller (row.key), 2 = the entity at
    -- row.key+0x08 — the same two bases `_dmg_chain_name` re-derives.
    for bi, b in ipairs(bases) do
        local base, tag = b[1], b[2]
        near(base, F._own.WIN, function(d)
            return ("%s+0x%x"):format(tag, d), bi, d, nil
        end)
        for off = 0, F._own.WIN, 8 do
            local p = I.read_u64(base + off)
            if _ptr_plausible(p) then
                near(p, F._own.HOP, function(d)
                    return ("%s+0x%x -> +0x%x"):format(tag, off, d), bi, off, d
                end)
            end
        end
    end
    return found, n
end

--- Name every row that can be named, in one pass. Background thread only.
---
--- The correctness rule is the same one the whole meter is built on: a name is
--- only used when it can belong to exactly ONE row. A string that several rows
--- reach is a shared table (the lobby roster, a UI list), not an owner — and
--- claiming from it would put a real player's damage under someone else's
--- name, which is the bug this all started with.
function F._dmg_probe_owner_fast()
    -- The user's opt-out. Checked before anything else so turning it off costs
    -- exactly one comparison per tick.
    if not _dmg.identity_scan then return false end
    local names, _ = F._dmg_name_set()
    if not names or not I.read_u64 then return false end

    -- CLAIM THE LOCAL ROW FIRST. Steam already told us who this player is, so
    -- their identity is the one thing on the board that never needs a scan.
    --
    -- This claim used to live ONLY inside `F._dmg_probe_owner`, the blind
    -- sweep — which is opt-in and off by default, so in a normal session it
    -- never ran and `row.player` stayed nil on the local row forever. The
    -- `wanted` gate below reads exactly that field, so every session had at
    -- least one row permanently asking to be identified, and the address scan
    -- ran for the whole run hunting for a name already in hand. Solo escaped
    -- only by accident (no lobby means no needles, so `names` is nil above).
    --
    -- It hid from the spec for the same reason it hid in game, from the other
    -- side: `R.damage.sweep_identity()` — what every test drives — routes
    -- through `_dmg_probe_owner`, so the claim always ran under test and never
    -- ran in play. See spec 2f2c, which drives the default path instead.
    local me = F._dmg_me()
    if me then
        for _, row in ipairs(_dmg.order) do
            if row.is_local and not row.player then
                F._dmg_claim(row, names, me, "steam")
            end
        end
    end

    -- Nothing to identify, nothing to scan for. Without this the address
    -- space is walked again on every roster change of a lobby whose rows are
    -- all already named.
    local wanted = false
    for _, row in ipairs(_dmg.order) do
        if not row.player and _ptr_plausible(row.key) then wanted = true break end
    end
    if not wanted then return false end

    -- MORE ROWS THAN PLAYERS means the board has forked, and a forked board is
    -- one the scan cannot answer: two rows belong to the same person, so every
    -- name they both reach is "shared" under the one-owner rule below and
    -- identifies nobody. Scanning on is pure cost, and cost the player feels --
    -- an ally who keeps swapping hero objects (a transform, a respawn) adds a
    -- row each time and each new row re-opens `wanted` above forever. The local
    -- player cannot fork any more (F._dmg_row_for_entity), but nothing on this
    -- build identifies an ALLY, so their forks are not mergeable and this is
    -- the bound instead. Names already claimed are kept; the rest stay lobby
    -- guesses, which is what they would have been anyway.
    -- ⚠ `#members >= 2`, not `> 0`. A roster this client was never fully sent
    -- is the NORMAL case on this build, not a fork: session c236 saw four rows
    -- against one lobby member all run, and today's 2-player log named its ally
    -- through the raknet join with ZERO members parsed. Comparing rows against
    -- a roster that only ever held this player would call every co-op run
    -- forked and stand the name scan down on all of them -- turning a fix for
    -- a stutter into a regression in ally names. Two members is the same
    -- threshold the rest of this file uses before it believes the roster.
    local members = R.lobby.members()
    if #members >= 2 and #_dmg.order > #members then
        if not _dmg.fork_said then
            _dmg.fork_said = true
            R.log(("[rsmm.damage] %d rows for a %d-player lobby — a hero object "
                   .. "swap forked the board, so the identity scan cannot "
                   .. "answer and stands down (rows keep their lobby names)")
                  :format(#_dmg.order, #members))
        end
        return false
    end

    local addrs = F._dmg_find_needles(names)
    if not addrs or #addrs == 0 then return false end

    local by_page = F._dmg_index(addrs)
    local rows, cand = {}, {}
    for _, row in ipairs(_dmg.order) do
        if not row.player and _ptr_plausible(row.key) then
            local found, n = F._dmg_row_names(row, by_page)
            if n > 0 then
                rows[#rows + 1] = row
                cand[row] = found
            end
        end
    end
    if #rows == 0 then return false end

    -- How many rows reach each name. More than one = shared, so it identifies
    -- nobody.
    local owners = {}
    for _, row in ipairs(rows) do
        for name in pairs(cand[row]) do owners[name] = (owners[name] or 0) + 1 end
    end
    local named = false
    for _, row in ipairs(rows) do
        local only, hit, count = nil, nil, 0
        for name, h in pairs(cand[row]) do
            if owners[name] == 1 then only, hit, count = name, h, count + 1 end
        end
        if count == 1 then
            if F._dmg_claim(row, names, only, hit.how) then
                -- The chain, not just its text. This is the whole point of the
                -- scan: one row identified yields the offsets that name every
                -- later row — and every later RUN — in two reads.
                F._dmg_note_chain(hit.base, hit.off, hit.hop, hit.how)
                named = true
            end
        elseif count > 1 then
            R.log(("[rsmm.damage] row %d reaches %d different players' "
                   .. "identities — shared memory, so it names nobody")
                  :format(row.slot, count))
        end
    end
    return named
end

--- Remember a chain that produced a hit, once.
function F._dmg_note_chain(base, off, hop, text)
    for _, ch in ipairs(F._own.chains) do
        if ch.base == base and ch.off == off and ch.hop == hop
           and ch.text == text then return end
    end
    F._own.chains[#F._own.chains + 1] = { base = base, off = off, hop = hop,
                                          text = text }
end

--- The roster as a printable list of NAMES. (Distinct from
--- _dmg_roster_text, which formats a members table the caller already has.)
---
--- Deliberately not the needle set: the sweep searches for peer ids as well as
--- gamertags, and session 7068's dead-end line printed four raw EOS GUIDs
--- alongside the four players, which reads as a corrupt roster.
function F._dmg_roster_names()
    local ok, members = pcall(R.lobby.members)
    if not ok or type(members) ~= "table" then return "?" end
    local t, ids = {}, 0
    for _, m in ipairs(members) do
        t[#t + 1] = tostring(m.name)
        if type(m.eos) == "string" and #m.eos > 0 then ids = ids + 1 end
    end
    table.sort(t)
    -- The COUNT of peer ids, because a sweep with no needle to look for and a
    -- sweep that looked and found nothing are the same log line otherwise —
    -- which is exactly why session fb4f could not be explained. Printing the
    -- ids themselves (the first version) made the roster read as corrupt.
    return ("%s — %d of %d carry a peer id"):format(
        table.concat(t, ", "), ids, #members)
end

--- The lobby names as a lookup set, plus the longest one. nil when the roster
--- is still empty (solo, or names have not arrived yet).
function F._dmg_name_set()
    local ok, members = pcall(R.lobby.members)
    if not ok or type(members) ~= "table" then return nil end
    local set, longest = {}, 0
    local function needle(text, m)
        if type(text) ~= "string" or #text == 0 or #text > 64 then return end
        -- Every needle resolves to the member, and every hit is reported under
        -- the member's NAME — a row must never end up labelled with a peer id.
        set[text] = m
        if #text > longest then longest = #text end
    end
    for _, m in ipairs(members) do
        if type(m.name) == "string" and #m.name > 0 then
            needle(m.name, m)
            needle(m.eos, m)
        end
    end
    if longest == 0 then return nil end
    return set, longest
end

--- Does a known player name start at `va`? Returns the name, or nil.
---
--- One `read_cstr` per address, not one per candidate name: the read stops at
--- the first NUL, so a stored name comes back whole and the set does the rest.
--- That keeps a 70k-probe sweep to 70k reads rather than 70k x roster size.
--- NUL-terminated string at `va`, through the page cache (see F._dmg_pread).
--- Falls back to the guarded reader when the string would run past the cached
--- page, which is the only case the snapshot cannot answer.
function F._dmg_pstr(va, max)
    if type(va) ~= "number" or va <= 0 then return nil end
    if not I.read_block then return I.read_cstr and I.read_cstr(va, max) or nil end
    local base = va - (va % F._pg.SIZE)
    local blk = F._pg.blocks[base]
    if blk == nil then
        if F._pg.n >= F._pg.PAGES then
            return I.read_cstr and I.read_cstr(va, max) or nil
        end
        blk = I.read_block(base, F._pg.SIZE) or false
        F._pg.blocks[base], F._pg.n = blk, F._pg.n + 1
    end
    if not blk then return nil end
    local from = va - base + 1
    if from > #blk then return nil end
    local stop = blk:find("\0", from, true)
    -- No terminator inside the page: the string may continue past it, so let
    -- the guarded reader answer rather than truncating at a page boundary.
    if not stop then return I.read_cstr and I.read_cstr(va, max) or nil end
    if stop - from > max then return nil end
    return blk:sub(from, stop - 1)
end

function F._dmg_name_at(va, names, longest)
    if not _ptr_plausible(va) then return nil end
    local s = F._dmg_pstr(va, longest + 1)
    -- Return the member's NAME, not the string that matched: the needle may
    -- have been their peer id.
    if type(s) == "string" and names[s] then return names[s].name end
    return nil
end

--- Read the adopted chain on `row`. Two reads once the chain is known.
function F._dmg_chain_name(row, chain, names, longest)
    local base = chain.base == 2 and I.read_u64(row.key + 0x08) or row.key
    if not _ptr_plausible(base) then return nil end
    if not chain.hop then return F._dmg_name_at(base + chain.off, names, longest) end
    local p = I.read_u64(base + chain.off)
    if not _ptr_plausible(p) then return nil end
    return F._dmg_name_at(p + chain.hop, names, longest)
end

--- Would some OTHER unnamed row resolve this same chain to this same name?
---
--- The blind sweep walks ONE row at a time, so on its own it has no way to
--- tell an owner from a shared table — it claimed whatever it reached first,
--- and `_dmg_claim`'s duplicate refusal then only stopped the SECOND row, long
--- after the first had taken a name that may not be its own. That is the same
--- failure `_dmg_probe_owner_fast`'s one-owner rule and the chain replay's both
--- refuse, and the sweep undercut both of them by running after them.
---
--- Costs two pointer reads per other row, and only at the instant of a claim.
function F._dmg_chain_shared(row, chain, name, names, longest, me)
    for _, other in ipairs(_dmg.order) do
        if other ~= row and not other.player and _ptr_plausible(other.key) then
            -- The local row is never a rival claimant for somebody else's name:
            -- Steam already said who is at this keyboard, so a gamertag inside
            -- YOUR object (session 6136) must not make the real owner's name
            -- look shared and strand that player on a placeholder.
            local rival = not (other.is_local and type(me) == "string"
                               and me ~= "" and name ~= me)
            if rival
               and F._dmg_chain_name(other, chain, names, longest) == name then
                return true
            end
        end
    end
    return false
end

--- Bind `row` to the lobby member called `name`.
---
--- Refuses a name another row already holds. Two rows resolving to one player
--- means the chain is reading something shared (a lobby array, the local
--- player's own copy), and merging two players is the one failure that DELETES
--- damage from the board — always fail toward the placeholder.
--- Who is at this keyboard, remembered.
---
--- `R.player.name` is a Steam call and it can come back empty on a background
--- tick even when it answered a moment earlier on the main thread. Session
--- d536 is that window: the local row's LABEL was resolved at boarding (Steam
--- fine), then every sweep tick asked again, got nothing, and so skipped the
--- steam claim -- which left row 1 unclaimed and the duplicate guard with
--- nothing to compare against. An ally then claimed "Ovilli" off a global the
--- engine hangs on every entity, and the board showed two of them.
---
--- So the answer is cached the first time anyone gets it, and the LOCAL ROW's
--- own label is the fallback: it was resolved from Steam already, and it is
--- the one name on the board that was never inferred.
function F._dmg_me()
    if _dmg.me then return _dmg.me end
    local ok, nm = pcall(R.player.name)
    if ok and type(nm) == "string" and nm ~= "" and nm ~= "You" then
        _dmg.me = nm
        return nm
    end
    for _, row in ipairs(_dmg.order) do
        if row.is_local then
            local lbl = row.player or row.label
            if type(lbl) == "string" and lbl ~= "" and lbl ~= "You"
               and not lbl:match("^Player %d+$") then
                _dmg.me = lbl
                return lbl
            end
        end
    end
    return nil
end

function F._dmg_claim(row, names, name, how)
    local m = names[name]
    -- Steam is authoritative for the LOCAL row, and does not depend on the
    -- roster sweep having seen that player. Session d536 is the roster WITHOUT
    -- the local member in it, so `names[me]` was nil, the steam claim never
    -- ran, `row.player` stayed unset on row 1 -- and the duplicate guard below,
    -- which is what stops a second row taking a name, had nothing to compare
    -- against. Two rows finished the run labelled "Ovilli".
    if not m and not (row.is_local and how == "steam") then return false end
    -- The local row is the ONE row whose name is not an inference: Steam told
    -- us. Session 6136 renamed it anyway, off a stack frame masquerading as a
    -- member object. The visible label survived (the local row keeps its Steam
    -- name below), but `row.player` did not — and that CONSUMED a real
    -- player's name: row 3 was refused "Timattttttt" twice as a duplicate and
    -- finished the run as "Player 3". A wrong claim here costs two rows.
    if row.is_local then
        local me = F._dmg_me()
        if me and me ~= name then
            R.log(("[rsmm.damage] refusing row %d -> %q (%s): that row is this "
                   .. "machine's player, and Steam calls them %q")
                  :format(row.slot, name, how, me))
            return false
        end
    end
    -- AND THE MIRROR: an ally may never be named after this machine's player.
    -- There is exactly one local player and Steam names them before any sweep
    -- runs, so a NON-local row resolving to that name is proof the chain is
    -- shared -- the local player's name is reachable from a global the engine
    -- hangs off every entity -- not proof of ownership. Session d536 claimed
    -- `entity+0xcc8 -> +0x39b` for an ally that way and the board showed two
    -- "Ovilli" rows while the ally's real name, InsertCoin2Start, vanished.
    --
    -- This does not depend on the local row having been claimed first, which
    -- is the whole point: the ordering is what failed.
    if not row.is_local then
        local me = F._dmg_me()
        if me and me == name then
            if not _dmg.self_claim_said then
                _dmg.self_claim_said = true
                R.log(("[rsmm.damage] refusing row %d -> %q (%s): that is this "
                       .. "machine's player and this row is not them, so the "
                       .. "chain is shared memory, not ownership")
                      :format(row.slot, name, how))
            end
            return false
        end
    end
    for _, other in ipairs(_dmg.order) do
        if other ~= row and other.player == name then
            R.log(("[rsmm.damage] refusing row %d -> %q (%s): row %d already "
                   .. "holds that name"):format(row.slot, name, how, other.slot))
            return false
        end
    end
    row.player = name
    if m and m.hero_id and not row.hero_id then
        row.hero_id = m.hero_id
        _dmg.by_hero[m.hero_id] = row
    end
    -- The local row keeps the name Steam gave it; they are the same person and
    -- the Steam persona is the one the player recognises as themselves.
    if not row.is_local then
        row.label = name
        row.label_guess = false
    end
    F._own.found = F._own.found + 1
    -- The sweep budget is there to stop a scan that never answers. This one
    -- just answered, so clear it: the rows still unnamed have earned the next
    -- pass, and a roster previously stood down on is worth re-arming.
    F._own.tries, F._own.gave_up = {}, {}
    R.log(("[rsmm.damage] row %d IS %q (%s)%s"):format(
        row.slot, name, how, row.is_local and " [local]" or ""))
    return true
end

--- Advance the owner-name sweep by one budget's worth. Background thread only.
function F._dmg_probe_owner()
    local names, longest = F._dmg_name_set()
    if not names or not I.read_cstr or not I.read_u64 then return end

    -- The local row is not a mystery: Steam named it before the run started.
    -- Leaving it unclaimed made every sweep spend a quarter of its budget, and
    -- four retries, re-deriving a fact already in hand — session 314f swept
    -- row 1 three times for nothing.
    -- No `names[me]` gate. The roster is a SWEEP result and it drops members
    -- that stop being re-parsed, so the local player is routinely absent from
    -- it (session d536, and the two "not in this lobby - dropped" lines in
    -- a14f). Gating the local claim on the roster meant the one name the meter
    -- knows for certain went unclaimed, which in turn disarmed the duplicate
    -- guard in `_dmg_claim`. Steam is the source here, not the roster.
    local me = F._dmg_me()
    if me then
        for _, row in ipairs(_dmg.order) do
            if row.is_local and not row.player then
                F._dmg_claim(row, names, me, "steam")
            end
        end
    end

    -- CHAINS FIRST. A chain is two pointer reads and a string compare; the
    -- scan below is a native walk of the WHOLE address space, and the lobby
    -- sweep above already documents why that is felt even from the background
    -- thread — ReadProcessMemory at that volume saturates memory bandwidth
    -- and the process VM lock, which stalls the game's threads too. Scanning
    -- first meant the cheap answer was only ever consulted after the expensive
    -- one had already been paid for, on every tick with an unnamed row.
    --
    -- ALL of them are tried, not just the last — session 7068 named two rows
    -- through two DIFFERENT chains (`entity+0x678 -> +0x2d0` and
    -- `entity+0xad8 -> +0x1c0`), so a single remembered chain would have been
    -- the wrong one for half the board.
    -- Resolve every chain against every unnamed row FIRST, claim second, under
    -- the same one-owner rule the scan uses. A chain is a GUESS about where a
    -- name lives, and two of them are now SEEDED from an older session rather
    -- than learned on this board — so if two rows resolve a chain to the SAME
    -- name, that chain is reading something shared (the lobby roster, a UI
    -- list) and it identifies nobody. Claiming row-by-row in slot order, which
    -- is what this loop used to do, would hand that name to whichever row came
    -- first: a real player's damage under another player's name, the one
    -- failure the whole meter is built to refuse.
    local cand, hits = {}, 0
    for _, chain in ipairs(F._own.chains) do
        if chain.base then
            for _, row in ipairs(_dmg.order) do
                if not row.player and _ptr_plausible(row.key) then
                    local nm = F._dmg_chain_name(row, chain, names, longest)
                    if nm then
                        local c = cand[row]
                        if not c then c = {}; cand[row] = c end
                        if not c[nm] then c[nm] = chain; hits = hits + 1 end
                    end
                end
            end
        end
    end
    -- The local row is not a claimant for anybody else's name, so it must not
    -- count as an OWNER of one either. Session 6136's gamertag sat inside the
    -- local player's own object; `_dmg_claim` already refuses to rename row 1
    -- off it, but leaving it in the tally makes the real owner's name look
    -- shared, and the player who actually owns it is then stranded on a
    -- placeholder — which is the second half of that same bug.
    if hits > 0 and me then
        for row, c in pairs(cand) do
            if row.is_local then
                for nm in pairs(c) do
                    if nm ~= me then c[nm] = nil; hits = hits - 1 end
                end
            end
        end
    end
    if hits > 0 then
        local owners = {}
        for _, c in pairs(cand) do
            for nm in pairs(c) do owners[nm] = (owners[nm] or 0) + 1 end
        end
        -- Over `_dmg.order`, not `pairs(cand)`: claim order must not depend on
        -- table iteration order, or which row wins an ambiguity changes between
        -- runs and the board stops being reproducible.
        for _, row in ipairs(_dmg.order) do
            local c = cand[row]
            if c then
                local only, chain, n = nil, nil, 0
                for nm, ch in pairs(c) do
                    if owners[nm] == 1 then only, chain, n = nm, ch, n + 1 end
                end
                if n == 1 then
                    -- Name the chain that claimed the row, so the log tells a
                    -- seeded offset that still works apart from one a scan had
                    -- to rediscover.
                    F._dmg_claim(row, names, only,
                                 "chain " .. (chain.text or "?"))
                elseif n > 1 then
                    R.log(("[rsmm.damage] row %d resolves %d different players "
                           .. "through its chains — ambiguous, so it names "
                           .. "nobody"):format(row.slot, n))
                end
            end
        end
    end

    -- Only now ask the process where the names ARE, and check which row owns
    -- each. Costs one native scan per player and 2048 pointer reads per row.
    -- `_dmg_probe_owner_fast` gates itself on there still being an unnamed
    -- row, so a board the chains finished never reaches this at all. The blind
    -- sweep below stays as the fallback for a loader without `mem_find`.
    if F._dmg_probe_owner_fast() then return end

    local c = F._own.cursor
    if not c or c.row.player or c.row.own_done or c.row.dropped then
        -- Pick the next row that has neither an identity nor a completed sweep.
        c = nil
        for _, row in ipairs(_dmg.order) do
            if not row.player and _ptr_plausible(row.key)
               and (not row.own_done
                    or (row.own_retry_at and F._dmg_now() >= row.own_retry_at)) then
                row.own_done, row.own_retry_at = false, nil
                c = { row = row, base = 1, off = 0, hop = nil }
                break
            end
        end
        F._own.cursor = c
        if not c then return end
    end

    local row = c.row
    local budget = F._own.BUDGET
    while budget > 0 do
        local base = c.base == 2 and F._dmg_pread(row.key + 0x08, 8) or row.key
        if _ptr_plausible(base) then
            if c.hop == nil then
                -- Direct: the name lives in the object itself (an inline
                -- std::string, a fixed char buffer).
                local nm = F._dmg_name_at(base + c.off, names, longest)
                budget = budget - 1
                if nm then
                    local ch = { base = c.base, off = c.off, hop = nil }
                    -- Record it either way: a shared chain is still a fact
                    -- about this build, and the cross-row rule above is where
                    -- it gets judged.
                    F._dmg_note_chain(c.base, c.off, nil)
                    if F._dmg_chain_shared(row, ch, nm, names, longest, me) then
                        R.log(("[rsmm.damage] row %d reaches %q at %s, but so "
                               .. "does another unnamed row — shared memory, "
                               .. "so it names nobody"):format(row.slot, nm,
                            ("%s+0x%x"):format(
                                c.base == 2 and "entity" or "ctrl", c.off)))
                    else
                        F._dmg_claim(row, names, nm,
                            ("%s+0x%x"):format(c.base == 2 and "entity" or "ctrl", c.off))
                    end
                    F._own.cursor = nil
                    return
                end
            else
                -- One hop: the field is a pointer and the name is behind it —
                -- a `char*`, a `std::string*`, or the heap buffer of an MSVC
                -- std::string (whose data pointer sits at +0x8, which this
                -- reaches as hop 0 of that offset).
                local p = F._dmg_pread(base + c.off, 8)
                if _ptr_plausible(p) then
                    local nm = F._dmg_name_at(p + c.hop, names, longest)
                    budget = budget - 1
                    if nm then
                        local ch = { base = c.base, off = c.off, hop = c.hop }
                        F._dmg_note_chain(c.base, c.off, c.hop)
                        local how = ("%s+0x%x -> +0x%x"):format(
                            c.base == 2 and "entity" or "ctrl", c.off, c.hop)
                        if F._dmg_chain_shared(row, ch, nm, names, longest, me) then
                            R.log(("[rsmm.damage] row %d reaches %q at %s, but "
                                   .. "so does another unnamed row — shared "
                                   .. "memory, so it names nobody")
                                  :format(row.slot, nm, how))
                        else
                            F._dmg_claim(row, names, nm, how)
                        end
                        F._own.cursor = nil
                        return
                    end
                else
                    c.hop = F._own.HOP        -- nothing to walk; skip the hops
                    budget = budget - 1
                end
            end
        else
            budget = budget - 1
            c.off = F._own.WIN                    -- unreadable base: end this pass
        end

        -- Cursor advance: hops, then offsets, then base, then the hop stage.
        if c.hop ~= nil then
            c.hop = c.hop + F._own.STRIDE
            if c.hop > F._own.HOP then c.hop = 0; c.off = c.off + F._own.STRIDE end
        else
            c.off = c.off + F._own.STRIDE
        end
        if c.off > F._own.WIN then
            c.off = 0
            if c.base == 1 then
                c.base = 2
            elseif c.hop == nil then
                c.base, c.hop = 1, 0       -- direct pass done; walk pointers
            else
                -- Both passes done on both bases: this controller does not
                -- reach any lobby name. Say so ONCE, with everything needed to
                -- take it further (the next step is RE, not a wider sweep).
                row.own_done = true
                row.own_tries = (row.own_tries or 0) + 1
                F._own.swept = F._own.swept + 1
                F._own.cursor = nil
                -- RETRY, do not retire. A row is swept the moment it deals its
                -- first damage, and the fields that identify it are not
                -- necessarily populated yet — session 7068 named rows 1 and 2
                -- and dead-ended rows 3 and 4, which had boarded seconds
                -- earlier. Retiring a row after one pass makes that permanent
                -- for the whole run.
                -- ⚠ UNTESTED BRANCH. Reaching it in the spec needs a full
                -- ~264k-probe pass to COMPLETE before the fixture populates
                -- the row, and a shorter pass simply continues instead. The
                -- behaviour it guards (a row is not retired after one dead
                -- end) is covered; the countdown itself is not.
                if row.own_tries < F._own.TRIES then
                    row.own_retry_at = F._dmg_now() + F._own.RETRY_AFTER
                end
                R.log(("[rsmm.damage] owner-name sweep: row %d (%s, ctrl=0x%x) "
                       .. "holds no lobby id within +0x%x, direct or one hop "
                       .. "(attempt %d of %d) — roster was {%s}"):format(
                    row.slot, row.label, row.key, F._own.WIN,
                    row.own_tries, F._own.TRIES, F._dmg_roster_names()))
                return
            end
        end
    end
end

--- Advance the identity sweep by ONE slice.
---
--- The meter already drives this from its background tick; this exists so a
--- diagnostic ("who is row 3?") or a test can push it along without waiting.
--- BACKGROUND THREAD ONLY — it walks thousands of addresses.
function R.damage.sweep_identity()
    -- Re-check FIRST: a withdrawal clears `done`, so the probe below can start
    -- looking again in the same call, with whatever rows have since boarded.
    F._dmg_recheck_hero_field()
    F._dmg_probe_hero_field(true)     -- byte and word widths too
    F._dmg_backfill_ids()
    return F._dmg_probe_owner()
end

--- What the identity sweep has found. For diagnostics and the spec.
--- Mark every row as identified. Spec-only: it makes "there is nothing left
--- to look for" reachable without faking a memory layout for each row.
function R.damage._name_all()
    for _, row in ipairs(_dmg.order) do row.player = row.player or row.label end
end

function R.damage.identity()
    -- `chain` is the FIRST chain this board learned. Nothing is pre-seeded (see
    -- F._own.chains), so a non-nil value here means the scan actually ran and
    -- found something on this build — which is the number worth reading.
    return { chain = F._own.chains[1], chains = F._own.chains,
             found = F._own.found, swept = F._own.swept,
             hero_id_offset = HERO_ID_PROBE.off }
end

function F._dmg_relabel()
    -- Connected allies only: a name from someone who has left is exactly what
    -- the leftover-row guess below would hand to a forked row.
    local allies = F._dmg_live_allies()
    if type(allies) ~= "table" or #allies == 0 then return end
    -- Name by HERO when the row's identity is known: each lobby member record
    -- carries its RequestedHero, so this is an exact join.
    --
    -- There is NO positional fallback. `allies[rank]` — the old fallback — ranks
    -- rows by the order allies first dealt damage, which is unrelated to the
    -- lobby's order, so from three players up it printed a real name against
    -- another player's damage. What remains is ELIMINATION: once every row that
    -- has a hero id is named, a single unnamed ally row facing a single unclaimed
    -- ally name can only be that player. Everything else keeps its "Player N"
    -- placeholder until the hero-id probe lands.
    -- HERO IDS ARE NOT UNIQUE. Session 8f36 (2026-08-20) is a four-player
    -- lobby with TWO players on hero 10: "PigGoesQuack(hero 10)" and
    -- "Ovilli(hero 10)". Ravenswatch does not force distinct heroes, so the
    -- whole hero-id join is only ever valid for the ids that happen to be
    -- unique in THIS lobby -- and a duplicate id silently kept the last writer,
    -- which is a real player's damage under another real player's name.
    --
    -- Any id that more than one member claims is dropped outright. The rows
    -- that would have been named from it keep their placeholders, which is the
    -- correct answer: the roster genuinely cannot tell those two apart.
    local by_hero, okm, members = {}, pcall(R.lobby.members)
    if okm then
        local list, dup = members, {}
        if type(list) == "table" then
            for _, m in ipairs(list) do
                if m.hero_id and m.name then
                    if by_hero[m.hero_id] and by_hero[m.hero_id] ~= m.name then
                        dup[m.hero_id] = true
                    end
                    by_hero[m.hero_id] = m.name
                end
            end
            for id in pairs(dup) do
                by_hero[id] = nil
                if not _dmg.dup_hero_said then
                    _dmg.dup_hero_said = true
                    R.log(("[rsmm.damage] hero %d is claimed by more than one "
                           .. "player this run %s the hero id cannot identify "
                           .. "either of them, so it names neither")
                          :format(id, "\u{2014}"))
                end
            end
        end
    end
    -- Pass 1: the exact joins, plus the names they account for. `row.player` is
    -- the owner-name sweep's answer and outranks the hero id — it read the
    -- player's own gamertag out of the player's own object.
    local claimed, ally_rows, pending = {}, {}, {}
    for _, row in ipairs(_dmg.order) do
        if not row.is_local then
            local exact = row.player or (row.hero_id and by_hero[row.hero_id]) or nil
            local entry = { row = row, name = exact, guess = false }
            if exact then claimed[exact] = true else pending[#pending + 1] = entry end
            ally_rows[#ally_rows + 1] = entry
        end
    end
    -- Pass 2: elimination. Guarded on `#ally_rows <= #allies` because a row that
    -- forked at a chapter change is a duplicate player, not a new one, and would
    -- otherwise swallow the name of someone who has not dealt damage yet.
    local unclaimed = {}
    for _, nm in ipairs(allies) do
        if not claimed[nm] then unclaimed[#unclaimed + 1] = nm end
    end
    -- STABLE ORDER. `allies` follows R.lobby.members(), which is sorted by
    -- PARSE RECENCY -- and the engine re-parses every member several times a
    -- second, so that order flips constantly. Session a34f logged 192 renames
    -- in one run, `EvilMurray, fruktik_kiwi` and `fruktik_kiwi, EvilMurray`
    -- alternating once a second, which swapped the two players' names across
    -- their damage totals for the whole match. A guess may be wrong; it must
    -- not be wrong DIFFERENTLY every second.
    table.sort(unclaimed)
    if #pending == 1 and #ally_rows <= #allies and #unclaimed == 1 then
        pending[1].name = unclaimed[1]
        pending[1].guess = true              -- exact by count, not by hero id
    elseif _dmg.guess_names and not F._dmg_board_forked(members) then
        -- Hands the leftover names to the leftover rows in JOIN ORDER, which is
        -- a guess: every row it touches is flagged `label_guess` and a UI that
        -- shows the name must show the flag (the board prints a trailing "?").
        --
        -- ⚠ This branch was made opt-in on 2026-08-20 because the silent
        -- version put a real name on another player's damage. Turning it OFF BY
        -- DEFAULT was the wrong half of that fix: the lobby hook reliably learns
        -- all four names (sessions 6136/5636/0a36/7068/fb4f/314f/a84f/174f/304f/
        -- 8f36/c536/014f/e736/2c36/9e4f all logged a full four-name roster), but
        -- no join on this build can say which row is which -- the hero id is
        -- dead here because players pick duplicate heroes, and the owner-GUID
        -- key has no member bridge yet. So the default produced a board that
        -- KNEW every name and printed "Player 1..4" anyway. A marked guess
        -- beats that; an unmarked one does not. `player_1..player_4` in the
        -- config remain the way to get names that are never guesses.
        -- STICKY. A row keeps the guess it was first given for as long as
        -- that name is still in the lobby, so the board settles instead of
        -- re-dealing the same names on every tick. Cleared per epoch with the
        -- rest of the board.
        _dmg.guessed = _dmg.guessed or {}
        local live, taken = {}, {}
        for _, nm in ipairs(allies) do live[nm] = true end
        for _, entry in ipairs(pending) do
            local prev = _dmg.guessed[entry.row.slot]
            if prev and live[prev] and not claimed[prev] and not taken[prev] then
                entry.name, entry.guess, taken[prev] = prev, true, true
            end
        end
        for _, entry in ipairs(pending) do
            if not entry.name then
                for _, nm in ipairs(unclaimed) do
                    if not taken[nm] then
                        entry.name, entry.guess, taken[nm] = nm, true, true
                        _dmg.guessed[entry.row.slot] = nm
                        break
                    end
                end
            end
        end
    end
    local changed = 0
    for _, entry in ipairs(ally_rows) do
        local row = entry.row
        local nm = _dmg.names[row.slot] or entry.name
        if nm and row.label ~= nm then
            row.label = nm
            row.label_guess = _dmg.names[row.slot] == nil and entry.guess
            changed = changed + 1
        end
    end
    if changed > 0 then
        R.log(("[rsmm.damage] lobby roster: %s (%d row(s) renamed)")
              :format(table.concat(allies, ", "), changed))
    end
end

--- More rows than the lobby has players. The same signal the identity scan
--- stands down on, asked separately because it disqualifies GUESSING too.
---
--- A player log from a 4-player run (2026-08-24) came back with FIVE rows, one
--- of them labelled `X ?` against 57,699 damage. Join-order guessing cannot be
--- right on a board with more rows than players — one row is a duplicate of
--- another, so at least one name is on the wrong damage by construction, and
--- the trailing "?" reads as "roughly right" when it is "certainly wrong for
--- somebody". A placeholder is the honest answer there.
function F._dmg_board_forked(members)
    if type(members) ~= "table" or #members < 2 then return false end
    local rows = 0
    for _ in ipairs(_dmg.order) do rows = rows + 1 end
    return rows > #members
end

--- Apply the lobby roster to the board's ally rows.
---
--- Public because the roster resolves asynchronously: a UI that wants names
--- the moment they land can call this instead of waiting for the next tick.
--- Cheap — no scan (see R.lobby.members).
function R.damage.relabel() return F._dmg_relabel() end

--- Resolve the lobby roster on the BACKGROUND thread, then re-label.
---
--- Never call the scan from a gameplay path: it walks the address space and
--- costs seconds. This is the only place allowed to trigger it.
function F._dmg_lobby_refresh()
    if not (R.schedule and R.schedule.every) then return end
    -- One resolver for the whole process, not one per mod state.
    if I.shared_get and I.shared_set then
        local ok, n = pcall(I.shared_get, LOBBY_REFRESH_SLOT)
        if ok and type(n) == "number" and n > 0 then return end
        pcall(I.shared_set, LOBBY_REFRESH_SLOT, 1)
    end
    -- DEMAND-DRIVEN. The scan is only worth its ~4 s when there is actually a
    -- row it could name, which makes the common cases free: a solo run never
    -- scans at all, and a co-op run stops scanning the moment every ally has a
    -- real name.
    --
    -- The previous shape — scan on a 30 s timer, then refuse to rescan for
    -- 120 s — managed to be both wasteful and too slow: its one scan landed
    -- during loading, before anyone had joined, found nothing, and the retry
    -- was still 6 s away when session 1e36 ended. Ticking often but scanning
    -- rarely is the right way round.
    -- One SLICE per tick. `refresh` walks a bounded number of bytes and
    -- returns; the sweep spans many ticks, so nothing ever blocks long enough
    -- to be felt. The demand gate still applies, so a solo run does no work at
    -- all beyond the (free) relabel.
    R.schedule.every(1, function()
        -- METERING OFF MEANS OFF. The detours stay installed (see
        -- R.damage.disable) and cost an early return, but this tick is the
        -- expensive half of the meter -- address-space sweeps, the hero-field
        -- probe, the per-row netid pass -- and it used to keep running for the
        -- rest of the process after `disable()`, because nothing here ever
        -- read `_dmg.on` and the timer is never cancelled. A player who turned
        -- the meter off still paid for it, which is exactly what a user
        -- reported on 2026-08-24 ("background processes still running with the
        -- mod off"). Cancelling the timer instead would be wrong: `enable()`
        -- is idempotent and would not re-arm it.
        --
        -- One consequence, deliberate: the tick is claimed by ONE lua_State
        -- per process (LOBBY_REFRESH_SLOT), so if that state stops metering,
        -- no other state's board gets relabelled either. Releasing the slot
        -- here would let a second state arm its own timer, and then a
        -- re-enable would leave TWO running -- doubling the very scans this
        -- gate exists to stop. One mod owns R.damage in practice, so the
        -- cheaper failure is the right one.
        if not _dmg.on then return end
        local ok, err = pcall(function()
            -- The page cache is per TICK: drop last tick's snapshot before
            -- anything reads, so a probe never sees a second-old value.
            F._dmg_pflush()
            -- Cheap every time: re-read the known blocks and apply names.
            F._dmg_relabel()
            -- Before the probe, not after: a withdrawal has to clear `done` so
            -- the same tick can start looking again with the bigger sample.
            F._dmg_label_hint()
            F._dmg_recheck_hero_field()
            F._dmg_probe_hero_field(true)     -- background: byte and word too
            F._dmg_backfill_ids()
            -- Bounded and one-shot per row: 0x400 bytes of the row's net
            -- component plus 0x120 at each pointer it holds, looking for a
            -- 32-hex-character session id. Once a locator is adopted this is
            -- two reads per unnamed row. Not gated behind `identity_hunt`,
            -- because unlike the name sweep it cannot answer by coincidence.
            F._dmg_netid_pass()
            -- REAL NAMES, and NOT part of `identity_hunt`.
            --
            -- This asks the process where each player's peer id physically is
            -- (one native `mem_find` per player, ONE needle per tick) and then
            -- checks which row reaches a copy of it, under the one-owner rule.
            -- It is the path that actually produced names, and it is already
            -- rate-limited -- the back-to-back scans that caused session a84f's
            -- stutter were fixed inside it, by spreading the needles.
            --
            -- ⚠ It used to sit INSIDE `F._dmg_probe_owner`, so switching
            -- `identity_hunt` off to stop the blind sweep's stutter switched
            -- this off too and the board went back to "Player 2". That was a
            -- regression, not a decision: the expensive part is the sweep
            -- below, not this.
            --
            -- Self-gating: with no unnamed row it returns immediately, so a
            -- named board and a solo run both cost nothing.
            F._dmg_probe_owner_fast()
            -- The BLIND cursor sweep: hundreds of thousands of probes at every
            -- offset of every row. That is the stutter, and it answered at a
            -- different offset every time it "worked", so it stays opt-in.
            if _dmg.identity_hunt then F._dmg_probe_owner() end
            if F._dmg_wants_lobby() then
                local before = #R.lobby.members()
                local members = R.lobby.refresh()
                if #members ~= before then
                    R.log(("[rsmm.damage] lobby scan: %d member(s)%s")
                          :format(#members, #members > 0
                              and (" — " .. F._dmg_roster_text(members)) or ""))
                end
                F._dmg_relabel()
            end
        end)
        if not ok then
            R.log("[rsmm.damage] lobby refresh failed: " .. tostring(err))
        end
    end)
end

--- "Alice (Aladdin), Bob (Scarlet)" — the roster as one log line.
function F._dmg_roster_text(members)
    local parts = {}
    for _, m in ipairs(members) do
        -- Prefer the hero NAME over the raw id: "Yume (Juliet)" is something a
        -- player can match against what they saw on screen; "Yume (hero 4)" is
        -- not. Display only -- see R.lobby.HERO_NAMES.
        local hero = m.hero or R.lobby.hero_name(m.hero_id)
        parts[#parts + 1] = hero and (m.name .. " (" .. hero .. ")") or m.name
    end
    return table.concat(parts, ", ")
end

--- Record a member's session id without a live lobby. Spec and diagnostics
--- only: in game this comes from the attribute-parser detour, which recovers
--- the member as `blob - 0x28`.
function R.lobby._note_session(name, sid)
    for _, e in ipairs(LOBBY_HOOK.order) do
        if e.name == name then e.session = sid; return true end
    end
    return false
end

--- Record the member OBJECT the hook saw for `name`, and snapshot the pointers
--- it holds (diagnostics and the spec). The hook does both on every parse --
--- and the SNAPSHOT is the part that matters: the member is destroyed after
--- the call, so nothing may read it later.
function R.lobby._note_member(name, addr)
    for _, e in ipairs(LOBBY_HOOK.order) do
        if e.name == name then
            e.member = addr
            if _ptr_plausible(addr) and I.read_u64 then
                local ptrs, n, words = {}, 0, {}
                for off = 0, F._netid.MEMWIN - 8, 8 do
                    local v = I.read_u64(addr + off)
                    if type(v) == "number" and v ~= 0 and v ~= -1 then words[v] = true end
                    if _ptr_plausible(v) and not ptrs[v] then
                        ptrs[v] = true; n = n + 1
                    end
                end
                if n > 0 then e.ptrs, e.nptrs = ptrs, n end
                if next(words) then e.words = words end
            end
            return true
        end
    end
    return false
end

--- Offset of the controller field that carries the player's hero id, once the
--- sweep has confirmed ONE candidate — the identity that lets a row survive a
--- chapter change. nil while unknown or ambiguous, in which case rows fall back
--- to pointer identity (and the local player to the engine's is-local byte).
--- Worth putting in a bug report: it is the field a game patch is most likely
--- to move.
function R.damage.hero_id_offset() return HERO_ID_PROBE.off end

end
