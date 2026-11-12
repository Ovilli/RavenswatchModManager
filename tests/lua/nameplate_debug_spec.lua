local install = assert(loadfile("src/loader/lua/rsmm/nameplate_debug.lua"))()
local function fixture()
    local mem, classes, strings, logs = {}, {}, {}, {}
    local H, E, A, P, S, N, CHILD, CA, LABEL, LS, LN =
        0x100000, 0x200000, 0x300000, 0x400000, 0x500000, 0x600000,
        0x700000, 0x800000, 0x900000, 0xa00000, 0xb00000
    mem[H + 8] = E
    mem[E + 0x190], mem[E + 0x198], mem[A] = A, 1, P
    mem[P + 0x10], mem[S + 0xe8], strings[N] = S, N, "Life Bar Spawner"
    mem[P + 0x100] = CHILD
    mem[CHILD + 0x190], mem[CHILD + 0x198], mem[CA] = CA, 1, LABEL
    mem[LABEL + 0x10], mem[LS + 0xe8], strings[LN] = LS, LN, "Top Bar Text UI"
    classes[E], classes[CHILD] = "oCEntity", "oCEntity"
    classes[P], classes[LABEL] = "oCEntityCpntEntitySpawner", "oCEntityCpntLabelUi"
    local I = setmetatable({
        va_trusted = function() return true end,
        read_u64 = function(p) return mem[p] end,
        read_u32 = function(p) return mem[p] end,
        read_cstr = function(p) return strings[p] end,
    }, { __index = function(_, k) error("Forbidden binding: " .. k) end })
    local R = {
        log = function(s) logs[#logs + 1] = s end,
        rtti = { name = function(p) return classes[p] end },
        entity = { hero = function() return H end },
        net = { session_state = function() return 5 end,
            session_host = function() return 0x76543210abcdef01 end,
            owner = function() return 0x76543210abcdef01 end },
    }
    install({ R = R, I = I })
    return R, I, mem, logs, { H=H, E=E, A=A, P=P, CHILD=CHILD }
end
local passed = 0
local function test(name, fn)
    fn(); passed = passed + 1; print("ok " .. name)
end
test("finds overhead UI through the life bar spawner", function()
    local R, _, _, logs = fixture()
    local r = R.debug.nameplate_snapshot()
    assert(r.status == "captured" and #r.entities == 2)
    assert(r.entities[2].components[1].name == "Top Bar Text UI")
    assert(r.local_is_host and not r.truncated)
    assert(logs[1]:find("76543210abcdef01", 1, true))
end)
test("unknown build refuses all memory reads", function()
    local R, I = fixture()
    I.va_trusted = function() return false end
    I.read_u64 = function() error("must not read") end
    assert(R.debug.nameplate_snapshot().status == "unavailable")
end)
test("no captured hero is retryable", function()
    local R = fixture(); R.entity.hero = function() return nil end
    assert(R.debug.nameplate_snapshot().reason == "hero not captured")
end)
test("corrupt component count is rejected", function()
    local R, _, mem, _, p = fixture(); mem[p.E + 0x198] = 0xffffffff
    assert(R.debug.nameplate_snapshot().status == "unavailable")
end)
test("unknown owner never matches host", function()
    local R = fixture(); R.net.owner = function() return nil end
    assert(not R.debug.nameplate_snapshot().local_is_host)
end)
test("guest never matches host", function()
    local R = fixture(); R.net.owner = function() return 0x76543210abcdef02 end
    assert(not R.debug.nameplate_snapshot().local_is_host)
end)
test("disconnected state never claims host", function()
    local R = fixture(); R.net.session_state = function() return 0 end
    assert(not R.debug.nameplate_snapshot().local_is_host)
end)
test("short vector is followed without retaining old objects", function()
    local R, _, mem, _, p = fixture()
    mem[p.P + 0x100], mem[p.P + 0x108], mem[0xc00000] = 0xc00000, 1, p.CHILD
    assert(#R.debug.nameplate_snapshot().entities == 2)
    mem[0xc00000] = nil
    assert(#R.debug.nameplate_snapshot().entities == 1)
end)
test("cycles are deduplicated", function()
    local R, _, mem, _, p = fixture(); mem[p.P + 0x108] = p.E
    assert(#R.debug.nameplate_snapshot().entities == 2)
end)
test("an oversized live graph exhausts the budget", function()
    local R, _, mem, _, p = fixture()
    mem[p.E + 0x198] = 4096
    for j = 0, 4095 do mem[p.A + j * 8] = p.P end
    local r = R.debug.nameplate_snapshot()
    assert(r.truncated and r.reads <= 24000)
end)
print(passed .. " passed, 0 failed")
