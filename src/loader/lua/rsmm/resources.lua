-- R.shards.gain / R.ingredient — run resources through the game's own pickup
-- events. PROVEN IN GAME 2026-10-10: shards.gain(50) took the counter 0 -> 50
-- and ingredient.add("Key", 2) showed two more keys. remove() has not been
-- exercised in game.
--
--     R.shards.gain(20)               -- as if picked up: shard-gain bonuses apply
--     R.ingredient.add("Key", 2)      -- Bean, Key, Note, Stone, Straw, Wood
--     R.ingredient.remove("Key", 1)
--     R.ingredient.names()            -- the ingredients loaded this session
--
-- R.shards.add writes the shard count through Hero_ModifyDreamShards with no
-- context. GAIN_DREAM_SHARDS is what a pickup sends: its hero handler
-- (0x1403a72b0) multiplies a positive amount by the hero's two shard-gain
-- values (keys 0x173900d6, 0x1d788952), tags it `PickedUpByMyself` (+0x5c) or
-- `Purchase` (+0x5d), then calls Hero_ModifyDreamShards with those tags — so
-- item bonuses and anything that reacts to a pickup see it.
--   oCDtNamedEventGainDreamShards, 0x60 bytes (ctor 0x1402e6ce0):
--     +0x50 u64 source net id (-1), +0x58 i32 amount, +0x5c u8 picked up (1),
--     +0x5d u8 purchase (0)
--
-- GAIN_INGREDIENT's handler (0x14039acc0) passes (+0x50 id, +0x54 count) to
-- the hero's ingredient routine (0x14039a970), which looks the id up among the
-- loaded IngredientDefinitions (def + 0x290) and adds or, for a negative
-- count, removes.
--   oCGameEventGainIngredient, 0x58 bytes (ctor 0x1402da4f0):
--     +0x50 u32 ingredient id, +0x54 i16 count
--
-- MAIN THREAD only (R.schedule.next_main), like every engine-mutating call.
return function(env)
    local R, I = env.R, env.I
    local NE = env.named_event                   -- rsmm/named_event.lua

    local SHARDS_VFT_VA = 0x140f224c0            -- oCDtNamedEventGainDreamShards_vftable
    local INGREDIENT_VFT_VA = 0x140f26460        -- oCGameEventGainIngredient_vftable
    local INGREDIENT_ID_OFF, INGREDIENT_NAME_OFF = 0x290, 0x298

    local shards = {}
    function shards.gain(n)
        if type(n) ~= "number" or n ~= math.floor(n) or n < 1 or n > 0x7fffffff then
            R.log("[rsmm.shards] gain(n): n must be a whole number >= 1")
            return false
        end
        local ev, disp = NE.begin("R.shards", SHARDS_VFT_VA, "GAIN_DREAM_SHARDS", 0x60)
        if not ev then return false end
        I.write_u64(ev + 0x50, 0xffffffffffffffff)   -- source, as the ctor leaves it
        I.write_u32(ev + 0x58, n)
        I.write_u8(ev + 0x5c, 1)                     -- picked up (ctor default)
        I.write_u8(ev + 0x5d, 0)                     -- not a purchase
        return NE.send("R.shards", ev, disp, "+" .. n)
    end

    local ingredient = {}

    -- { [lower name] = { id = u32, name = string } } from the live defs.
    local function catalog()
        local out = {}
        if not (R.defs and R.defs.instances) then return out end
        for _, def in ipairs(R.defs.instances("IngredientDefinition")) do
            local id = I.read_u32(def + INGREDIENT_ID_OFF)
            local sp = I.read_u64(def + INGREDIENT_NAME_OFF)
            local name = sp and R.ptr.plausible(sp) and I.read_cstr(sp, 64) or nil
            if id and name and name ~= "" then
                out[name:lower()] = { id = id, name = name }
            end
        end
        return out
    end

    function ingredient.names()
        local out = {}
        for _, e in pairs(catalog()) do out[#out + 1] = e.name end
        table.sort(out)
        return out
    end

    local function send_ingredient(which, count, fn)
        if type(which) ~= "string" then
            R.log("[rsmm.ingredient] " .. fn .. ": name an ingredient (R.ingredient.names())")
            return false
        end
        local e = catalog()[which:lower()]
        if not e then
            local known = ingredient.names()
            R.log("[rsmm.ingredient] " .. fn .. ": no ingredient named " .. which
                .. (#known > 0 and (" (loaded: " .. table.concat(known, ", ") .. ")")
                    or " (no ingredient definitions are loaded yet)"))
            return false
        end
        local ev, disp = NE.begin("R.ingredient", INGREDIENT_VFT_VA, "GAIN_INGREDIENT", 0x58)
        if not ev then return false end
        I.write_u32(ev + 0x50, e.id)
        I.write_u16(ev + 0x54, count & 0xffff)
        I.write_u16(ev + 0x56, 0)
        return NE.send("R.ingredient", ev, disp,
            string.format("%s %+d (id=0x%x)", e.name, count, e.id))
    end

    local function valid_count(n, fn)
        n = n == nil and 1 or n
        if type(n) ~= "number" or n ~= math.floor(n) or n < 1 or n > 0x7fff then
            R.log("[rsmm.ingredient] " .. fn .. ": n must be a whole number from 1 to 32767")
            return nil
        end
        return n
    end

    function ingredient.add(which, n)
        n = valid_count(n, "add")
        return n ~= nil and send_ingredient(which, n, "add")
    end

    function ingredient.remove(which, n)
        n = valid_count(n, "remove")
        return n ~= nil and send_ingredient(which, -n, "remove")
    end

    return { shards = shards, ingredient = ingredient }
end
