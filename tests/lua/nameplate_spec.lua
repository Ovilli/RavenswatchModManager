local install = assert(loadfile("src/loader/lua/rsmm/nameplate.lua"))()
local function fixture()
    local H,E,A,P,S,U,UA,W,WS,F,C,N =
        0x100000,0x200000,0x300000,0x400000,0x500000,0x600000,
        0x700000,0x800000,0x900000,0xa00000,0xb00000,0xc00000
    local mem, strings, classes = {}, {}, {}
    mem[H+8]=E
    mem[E+0x190],mem[E+0x198],mem[A]=A,1,P
    mem[P+8],mem[P+0x10],mem[S+0xe8]=E,S,N
    strings[N]="Life Bar Spawner"
    mem[P+0x88]=U
    mem[U+0x190],mem[U+0x198],mem[UA]=UA,1,W
    mem[W+8],mem[W+0x10],mem[WS+0xe8]=U,WS,N+0x100
    strings[N+0x100]="Life Bar Game Ui"
    mem[W+0x88]=F
    mem[F],mem[C]=0x140010000,0x140020000
    mem[F+0x280],mem[F+0x288]=N+0x200,18
    strings[N+0x200]="Game_UI_Main_Frame"
    mem[C+0x280],mem[C+0x288]=N+0x300,15
    strings[N+0x300]="RSMM_Host_Crown"
    mem[F+0x2a8],mem[C+8],mem[C+0x2a8],mem[C+0x298]=C,-1,-1,F
    mem[C+0x234],mem[C+0x2dc]=0x30,1
    classes[E],classes[U]="oCEntity","oCEntity"
    classes[P],classes[W]="oCEntityCpntEntitySpawner","oCEntityCpntGameUi"
    local R={entity={hero=function() return H end, _scene=function() return true end,
        _retired=function() return false end, _is_live=function(p) return p==H end,
        _is_hero_object=function(p) return p==H end},
        rtti={name=function(p) return classes[p] end},
        engine={va=function(s) return ({UiLayoutWindow_vftable=0x140010000,
            UiPicture_vftable=0x140020000})[s] end},
        net={owner=function(e) assert(e==E); return 0x76543210abcdef01 end,
            session_host=function() return 0x76543210abcdef01 end,
            session_state=function() return 5 end}}
    local I={va_trusted=function() return true end,module_base=function() return 0x140000000 end,
        shared_get=function() return H end,read_u64=function(p) return mem[p] end,
        read_u32=function(p) return mem[p] end,read_u8=function(p) return mem[p] end,
        read_f32=function(p) return mem[p] end,read_cstr=function(p) return strings[p] end}
    install({R=R,I=I})
    return R,I,mem,{H=H,E=E,P=P,C=C,F=F,W=W},strings,classes
end
local passed=0
local function test(name,fn) fn(); passed=passed+1; print("ok "..name) end
test("native crown identity and exact 64-bit host join",function()
    local R=fixture(); local r=R.nameplate.inspect()
    assert(r.status=="captured" and #r.players==1)
    assert(r.host=="76543210abcdef01" and r.players[1].is_host)
    assert(r.players[1].visible and r.players[1].alpha==1)
    assert(r.players[1].widget==nil and r.players[1].entity==nil)
end)
test("guest is not host",function()
    local R=fixture(); R.net.session_host=function() return 2 end
    local p=R.nameplate.inspect().players[1]; assert(p.host_known and not p.is_host)
end)
test("unknown identity stays unknown",function()
    local R=fixture(); R.net.session_host=function() return nil end
    local p=R.nameplate.inspect().players[1]; assert(not p.host_known and not p.is_host)
end)
test("disconnected session never claims host",function()
    local R=fixture(); R.net.session_state=function() return 0 end
    assert(not R.nameplate.inspect().players[1].is_host)
end)
test("changed build performs no object reads",function()
    local R,I=fixture(); I.va_trusted=function() return false end
    I.read_u64=function() error("unexpected read") end
    assert(R.nameplate.inspect().status=="unavailable")
end)
test("retired hero is not inspected",function()
    local R=fixture(); R.entity._retired=function() return true end
    assert(#R.nameplate.inspect().players==0)
end)
test("child cannot belong to another frame",function()
    local R,I,m,a=fixture(); m[a.C+0x298]=0x123400
    assert(R.nameplate.inspect().status=="unavailable")
end)
test("sibling cycle refuses a partial result",function()
    local R,I,m,a=fixture(); m[a.C+8]=a.C
    assert(R.nameplate.inspect().status=="unavailable")
end)
test("crown must be a picture leaf",function()
    local R,I,m,a=fixture(); m[a.C+0x2a8]=a.F
    assert(R.nameplate.inspect().status=="unavailable")
end)
test("component must belong to the hero",function()
    local R,I,m,a=fixture(); m[a.P+8]=0x123400
    assert(R.nameplate.inspect().status=="unavailable")
end)
test("peer frame is found from the game UI root",function()
    local R,_,mem,a=fixture()
    local root=0xd00000
    mem[a.W+0x88]=root
    mem[root]=mem[a.F]
    mem[root+0x2a8],mem[a.F+8],mem[a.F+0x298]=a.F,-1,root
    assert(R.nameplate.inspect().players[1].is_host)
    mem[a.F+8]=a.F
    assert(R.nameplate.inspect().status=="unavailable")
end)
test("runtime hides unknown owners and shows only the matching host", function()
    local R,_,mem,a=fixture()
    R.engine.resolve=function() return 1 end
    local calls=0
    R.engine.call_safe=function(name, guards, widget, visible, immediate)
        assert(name=="UiElement_SetVisible" and guards[1][2](widget))
        assert(widget==a.C and immediate==1)
        mem[widget+0x234]=visible==1 and 0x30 or 0x20
        calls=calls+1
    end
    local host=R.net.session_host()
    R.net.session_host=function() return nil end
    local hidden=R.nameplate.update_host_crowns()
    assert(hidden.changed==1 and hidden.players[1].visible==false)
    assert(R.nameplate.update_host_crowns().changed==0)
    R.net.session_host=function() return host end
    local shown=R.nameplate.update_host_crowns()
    assert(shown.changed==1 and shown.players[1].visible==true and calls==2)
end)
print(passed.." passed, 0 failed")
