// Generic MinHook -> Lua callback bridge.
//
// See hook_lua.h for the API contract. Implementation strategy:
//
//  * 64 detour slots. Each slot N is a separate WINAPI function
//    `detour_N` with the same fixed prototype (8 uint64_t args).
//    MinHook fills its `trampoline` field per slot at install time.
//
//  * When the game calls a hooked function, control reaches `detour_N`.
//    The detour reads RCX/RDX/R8/R9 + the first 4 stack args (8 total),
//    then calls `dispatch(N, args)`.
//
//  * dispatch acquires the script_lua mutex, looks up the slot, pushes
//    the Lua callback + N args + a `next` C closure (upvalue = slot id),
//    then pcalls. The `next` closure replays the trampoline with the
//    same args.
//
//  * Return value: if the Lua callback returns nil and HASN'T already
//    called `next`, dispatch invokes the trampoline itself (pure read-
//    only hooks become a one-liner). Otherwise the Lua-returned value
//    becomes the function's RAX.
//
// Arity / float caveats: this version reads all 8 slots as uint64_t,
// which is correct for integer / pointer args on the Windows x64 ABI.
// FP args (which actually use XMM0-3) currently fall back to whatever
// happens to land in RCX/RDX/R8/R9 from the previous call -- mostly
// garbage. Hooks on functions with float args are flagged at install
// time and the dispatcher logs a warning; treat the FP arg as opaque.

extern "C" {
#include "lua.h"
#include "lauxlib.h"
}

#include "hook_lua.h"
#include "loader.h"

#include "MinHook.h"

#include <windows.h>

#include <array>
#include <cstdio>
#include <cstring>
#include <mutex>

namespace rsmm {

extern std::mutex& script_lua_mutex();   // exported from script_lua.cpp


namespace {

constexpr int MAX_SLOTS = 64;

// Trampoline prototype: 8 64-bit slots (covers Win x64 ABI for up to
// 8 integer/pointer args; first 4 in registers, next 4 on stack).
using Trampoline = std::uintptr_t (WINAPI *)(std::uint64_t, std::uint64_t,
                                             std::uint64_t, std::uint64_t,
                                             std::uint64_t, std::uint64_t,
                                             std::uint64_t, std::uint64_t);

struct Slot {
    std::uintptr_t target_va = 0;
    Trampoline     trampoline = nullptr;
    lua_State*     L = nullptr;
    int            cb_ref = LUA_NOREF;
    std::string    sig;          // "rXXXX": ret + args
    std::string    mod_id;
    bool           installed = false;
    bool           has_fp = false;
};

std::array<Slot, MAX_SLOTS> g_slots{};
std::mutex g_slots_mu;

// --- argument marshalling -------------------------------------------------

// Push one positional arg onto the Lua stack per sig type code.
void push_arg(lua_State* L, char t, std::uint64_t v) {
    switch (t) {
        case 'i': lua_pushinteger(L, static_cast<lua_Integer>(
                                       static_cast<std::int32_t>(v))); break;
        case 'u': lua_pushinteger(L, static_cast<lua_Integer>(
                                       static_cast<std::uint32_t>(v))); break;
        case 'l':
        case 'p': lua_pushinteger(L, static_cast<lua_Integer>(v)); break;
        case 'f': {
            float f; std::memcpy(&f, &v, sizeof(f));
            lua_pushnumber(L, f); break;
        }
        case 'd': {
            double d; std::memcpy(&d, &v, sizeof(d));
            lua_pushnumber(L, d); break;
        }
        case 's': {
            auto p = reinterpret_cast<const char*>(v);
            if (p) lua_pushstring(L, p); else lua_pushnil(L);
            break;
        }
        default: lua_pushnil(L); break;
    }
}

// Pull one Lua arg back as the 64-bit slot value (for next() / return).
std::uint64_t pull_arg(lua_State* L, int idx, char t) {
    switch (t) {
        case 'i': return static_cast<std::uint64_t>(
                          static_cast<std::int32_t>(luaL_checkinteger(L, idx)));
        case 'u': return static_cast<std::uint64_t>(
                          static_cast<std::uint32_t>(luaL_checkinteger(L, idx)));
        case 'l':
        case 'p': return static_cast<std::uint64_t>(luaL_checkinteger(L, idx));
        case 'f': {
            float f = static_cast<float>(luaL_checknumber(L, idx));
            double d = f; std::uint64_t r; std::memcpy(&r, &d, sizeof(r)); return r;
        }
        case 'd': {
            double d = luaL_checknumber(L, idx);
            std::uint64_t r; std::memcpy(&r, &d, sizeof(r)); return r;
        }
        case 's': return reinterpret_cast<std::uint64_t>(luaL_optstring(L, idx, ""));
        default:  return 0;
    }
}

// Push a return value from Lua onto the stack so the dispatcher can
// pack it into RAX.
std::uint64_t pull_ret(lua_State* L, int idx, char t) {
    if (lua_isnoneornil(L, idx)) return 0;
    return pull_arg(L, idx, t);
}

// --- the `next` closure ---------------------------------------------------

int lua_hook_next(lua_State* L) {
    const int slot = static_cast<int>(lua_tointeger(L, lua_upvalueindex(1)));
    Slot* s = nullptr;
    {
        std::lock_guard<std::mutex> g(g_slots_mu);
        if (slot < 0 || slot >= MAX_SLOTS) return luaL_error(L, "rsmm.hook.next: bad slot");
        s = &g_slots[slot];
        if (!s->installed || !s->trampoline) {
            return luaL_error(L, "rsmm.hook.next: slot not installed");
        }
    }
    const char  ret_t = s->sig[0];
    const auto  args_sv = std::string_view(s->sig).substr(1);
    const int   n_args = static_cast<int>(args_sv.size());

    std::uint64_t a[8] = {};
    for (int i = 0; i < n_args && i < 8; i++) {
        a[i] = pull_arg(L, 1 + i, args_sv[i]);
    }
    std::uint64_t raw = s->trampoline(a[0], a[1], a[2], a[3], a[4], a[5], a[6], a[7]);
    push_arg(L, ret_t, raw);
    return ret_t == 'v' ? 0 : 1;
}

// --- dispatcher -----------------------------------------------------------

std::uint64_t dispatch(int slot, std::uint64_t* a) {
    Slot snap{};
    {
        std::lock_guard<std::mutex> g(g_slots_mu);
        if (slot < 0 || slot >= MAX_SLOTS) return 0;
        snap = g_slots[slot];   // copy under lock so we can drop it before pcall
    }
    if (!snap.installed) return 0;

    std::lock_guard<std::mutex> g(script_lua_mutex());
    lua_State* L = snap.L;
    if (!L) {
        if (snap.trampoline) return snap.trampoline(a[0], a[1], a[2], a[3], a[4], a[5], a[6], a[7]);
        return 0;
    }
    const int base = lua_gettop(L);
    lua_rawgeti(L, LUA_REGISTRYINDEX, snap.cb_ref);
    if (!lua_isfunction(L, -1)) {
        lua_pop(L, 1);
        if (snap.trampoline) return snap.trampoline(a[0], a[1], a[2], a[3], a[4], a[5], a[6], a[7]);
        return 0;
    }

    const char ret_t = snap.sig[0];
    const auto args_sv = std::string_view(snap.sig).substr(1);
    const int n_args = static_cast<int>(args_sv.size());
    for (int i = 0; i < n_args && i < 8; i++) {
        push_arg(L, args_sv[i], a[i]);
    }
    // `next` upvalue = slot id; closure replays the trampoline.
    lua_pushinteger(L, slot);
    lua_pushcclosure(L, &lua_hook_next, 1);

    const int total = n_args + 1;
    if (lua_pcall(L, total, 1, 0) != LUA_OK) {
        Loader::get().log(std::string("[hook] cb error in ") + snap.mod_id + ": "
                          + lua_tostring(L, -1));
        lua_settop(L, base);
        if (snap.trampoline) return snap.trampoline(a[0], a[1], a[2], a[3], a[4], a[5], a[6], a[7]);
        return 0;
    }

    std::uint64_t r;
    if (lua_isnoneornil(L, -1)) {
        // Convenience: nil return = "act like a no-op, pass through".
        lua_pop(L, 1);
        r = snap.trampoline ? snap.trampoline(a[0], a[1], a[2], a[3], a[4], a[5], a[6], a[7]) : 0;
    } else {
        r = pull_ret(L, -1, ret_t);
        lua_pop(L, 1);
    }
    lua_settop(L, base);
    return r;
}

// --- detour slots: template-instantiated -----------------------------------

template <int Slot>
std::uintptr_t WINAPI detour_t(std::uint64_t a0, std::uint64_t a1,
                               std::uint64_t a2, std::uint64_t a3,
                               std::uint64_t a4, std::uint64_t a5,
                               std::uint64_t a6, std::uint64_t a7)
{
    std::uint64_t a[8] = { a0, a1, a2, a3, a4, a5, a6, a7 };
    return dispatch(Slot, a);
}

template <int... I>
constexpr std::array<void*, sizeof...(I)>
make_detour_table(std::integer_sequence<int, I...>) {
    return { reinterpret_cast<void*>(&detour_t<I>)... };
}

const std::array<void*, MAX_SLOTS> g_detour_table =
    make_detour_table(std::make_integer_sequence<int, MAX_SLOTS>{});

bool sig_has_float(std::string_view sig) {
    for (char c : sig) if (c == 'f' || c == 'd') return true;
    return false;
}

bool sig_validate(std::string_view sig) {
    if (sig.empty() || sig.size() > 9) return false;
    auto ok = [](char c) {
        return c == 'i' || c == 'u' || c == 'l' || c == 'p'
            || c == 'f' || c == 'd' || c == 's' || c == 'v';
    };
    for (char c : sig) if (!ok(c)) return false;
    return true;
}

} // namespace

bool hook_lua_init() {
    return true;   // nothing to do; slots are zero-initialized.
}

int hook_lua_install(std::uintptr_t target_va,
                     std::string_view sig,
                     lua_State* L,
                     int cb_ref,
                     std::string mod_id)
{
    if (!sig_validate(sig)) {
        Loader::get().log("[hook] bad sig '" + std::string(sig) + "'");
        return -1;
    }
    std::lock_guard<std::mutex> g(g_slots_mu);

    int slot = -1;
    for (int i = 0; i < MAX_SLOTS; i++) {
        if (!g_slots[i].installed) { slot = i; break; }
    }
    if (slot < 0) {
        Loader::get().log("[hook] no free slots (MAX_SLOTS=" + std::to_string(MAX_SLOTS) + ")");
        return -1;
    }
    Slot& s = g_slots[slot];
    s.target_va = target_va;
    s.L         = L;
    s.cb_ref    = cb_ref;
    s.sig.assign(sig);
    s.mod_id    = std::move(mod_id);
    s.has_fp    = sig_has_float(std::string_view(s.sig).substr(1));

    if (s.has_fp) {
        Loader::get().log("[hook] WARN sig '" + s.sig + "' has float args; "
                          "FP shimming not implemented — args may be garbage");
    }

    auto rc = MH_CreateHook(reinterpret_cast<LPVOID>(target_va),
                            g_detour_table[slot],
                            reinterpret_cast<LPVOID*>(&s.trampoline));
    if (rc != MH_OK) {
        Loader::get().log("[hook] MH_CreateHook va=0x"
                          + [&]{char b[32]; snprintf(b,sizeof(b),"%llx",(unsigned long long)target_va); return std::string(b);}()
                          + " rc=" + std::to_string(static_cast<int>(rc)));
        s = Slot{};
        return -1;
    }
    auto er = MH_EnableHook(reinterpret_cast<LPVOID>(target_va));
    if (er != MH_OK) {
        Loader::get().log("[hook] MH_EnableHook rc=" + std::to_string(static_cast<int>(er)));
        MH_RemoveHook(reinterpret_cast<LPVOID>(target_va));
        s = Slot{};
        return -1;
    }
    s.installed = true;
    Loader::get().log("[hook] slot " + std::to_string(slot) + " installed va=0x"
                      + [&]{char b[32]; snprintf(b,sizeof(b),"%llx",(unsigned long long)target_va); return std::string(b);}()
                      + " sig=" + s.sig + " mod=" + s.mod_id);
    return slot;
}

bool hook_lua_uninstall(int slot) {
    std::lock_guard<std::mutex> g(g_slots_mu);
    if (slot < 0 || slot >= MAX_SLOTS) return false;
    Slot& s = g_slots[slot];
    if (!s.installed) return false;
    MH_DisableHook(reinterpret_cast<LPVOID>(s.target_va));
    MH_RemoveHook(reinterpret_cast<LPVOID>(s.target_va));
    // Free the Lua registry ref if we still have a live state.
    if (s.L && s.cb_ref != LUA_NOREF) {
        luaL_unref(s.L, LUA_REGISTRYINDEX, s.cb_ref);
    }
    Loader::get().log("[hook] slot " + std::to_string(slot) + " uninstalled");
    s = Slot{};
    return true;
}

std::size_t hook_lua_active_count() {
    std::lock_guard<std::mutex> g(g_slots_mu);
    std::size_t n = 0;
    for (auto& s : g_slots) if (s.installed) n++;
    return n;
}

void hook_lua_unregister_mod(const std::string& mod_id) {
    // Collect slots to uninstall first (uninstall takes the same lock).
    std::vector<int> victims;
    {
        std::lock_guard<std::mutex> g(g_slots_mu);
        for (int i = 0; i < MAX_SLOTS; i++) {
            if (g_slots[i].installed && g_slots[i].mod_id == mod_id) {
                victims.push_back(i);
            }
        }
    }
    for (int i : victims) hook_lua_uninstall(i);
}

void hook_lua_shutdown() {
    for (int i = 0; i < MAX_SLOTS; i++) hook_lua_uninstall(i);
}

} // namespace rsmm
