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
// Floating-point args and returns ARE supported. On the Windows x64 ABI the
// first four arguments go in RCX/RDX/R8/R9 *or* XMM0-3 depending on each
// slot's TYPE, and an FP return comes back in XMM0 rather than RAX — so a
// detour declared with all-integer parameters reads garbage for any float
// argument (and returns garbage for a float-returning function). Since a
// detour's prototype is fixed at compile time, the slot table is indexed by
// SHAPE as well as slot: `kShapes` = 16 combinations of "is arg N (of the
// first four) floating-point" x 2 for "is the return floating-point".
//
// FP params are declared `double` even for a 'f' (float) slot: a double
// parameter is just the 64 raw bits of XMM, and the caller of a float-arg
// function puts the float in the low 32 of that register, so copying the
// bits out and reinterpreting the low half recovers the value exactly. The
// same trick works in reverse for the return. Arguments 5..8 arrive on the
// stack in 8-byte slots regardless of type, so they need no shaping.

extern "C" {
#include "lua.h"
#include "lauxlib.h"
}

#include "hook_lua.h"
#include "loader.h"
#include "hook_util.h"

#include "MinHook.h"

#include <windows.h>

#include <array>
#include <cstdio>
#include <cstring>
#include <mutex>
#include <type_traits>
#include <utility>
#include <vector>

namespace rsmm {

extern std::recursive_mutex& script_lua_mutex();   // exported from script_lua.cpp


namespace {

constexpr int MAX_SLOTS = 64;

// Shape = which of the first four arguments are floating-point (bits 0..3)
// plus whether the return is floating-point (bit 4). See the file header.
constexpr unsigned kShapeRetBit = 4;
constexpr unsigned kShapes      = 32;

inline bool is_fp_code(char c) { return c == 'f' || c == 'd'; }

// Shape of a validated signature ("<ret><args...>").
unsigned sig_shape(std::string_view sig) {
    unsigned m = 0;
    if (!sig.empty() && is_fp_code(sig[0])) m |= 1u << kShapeRetBit;
    const auto args = sig.substr(sig.empty() ? 0 : 1);
    for (std::size_t i = 0; i < args.size() && i < 4; ++i) {
        if (is_fp_code(args[i])) m |= 1u << i;
    }
    return m;
}

struct Slot {
    std::uintptr_t target_va = 0;
    void*          trampoline = nullptr;   // called through a shaped thunk
    lua_State*     L = nullptr;
    int            cb_ref = LUA_NOREF;
    std::string    sig;          // "rXXXX": ret + args
    std::string    mod_id;
    unsigned       shape = 0;
    bool           installed = false;
};

std::array<Slot, MAX_SLOTS> g_slots{};
std::mutex g_slots_mu;

// --- ABI shaping ----------------------------------------------------------

// Parameter type for argument I under shape M. FP slots are declared `double`
// so the compiler routes them through XMM; the 64 raw bits are what we keep,
// which for a 'f' (float) slot leaves the value in the low half exactly where
// the ABI puts it.
template <unsigned M, int I>
using ArgT = std::conditional_t<((M >> I) & 1u) != 0, double, std::uint64_t>;

template <unsigned M>
using RetT = std::conditional_t<((M >> kShapeRetBit) & 1u) != 0,
                                double, std::uintptr_t>;

inline std::uint64_t raw_bits(double d) {
    std::uint64_t r; std::memcpy(&r, &d, sizeof(r)); return r;
}
inline std::uint64_t raw_bits(std::uint64_t v) { return v; }

template <unsigned M, int I>
inline ArgT<M, I> as_arg(std::uint64_t v) {
    if constexpr (((M >> I) & 1u) != 0) {
        double d; std::memcpy(&d, &v, sizeof(d)); return d;
    } else {
        return v;
    }
}

std::uint64_t dispatch(int slot, std::uint64_t* a);

// Call a MinHook trampoline with the prototype its target actually has.
// Without this the original would receive integer registers for its float
// parameters — i.e. a `next()` from a Lua hook on a float-taking function
// would corrupt the very call it is replaying.
template <unsigned M>
std::uint64_t tramp_call_t(void* t, const std::uint64_t* a) {
    using Fn = RetT<M> (WINAPI*)(ArgT<M, 0>, ArgT<M, 1>, ArgT<M, 2>, ArgT<M, 3>,
                                 std::uint64_t, std::uint64_t,
                                 std::uint64_t, std::uint64_t);
    const auto r = reinterpret_cast<Fn>(t)(
        as_arg<M, 0>(a[0]), as_arg<M, 1>(a[1]), as_arg<M, 2>(a[2]), as_arg<M, 3>(a[3]),
        a[4], a[5], a[6], a[7]);
    return raw_bits(static_cast<
        std::conditional_t<((M >> kShapeRetBit) & 1u) != 0, double, std::uint64_t>>(r));
}

using TrampThunk = std::uint64_t (*)(void*, const std::uint64_t*);

template <unsigned... S>
inline std::array<TrampThunk, sizeof...(S)>
make_tramp_table(std::integer_sequence<unsigned, S...>) {
    return { &tramp_call_t<S>... };
}
const std::array<TrampThunk, kShapes> g_tramp_table =
    make_tramp_table(std::make_integer_sequence<unsigned, kShapes>{});

// Replay the original. Returns 0 when there is no trampoline (a hook whose
// install half-failed), which is the same "act as if it returned nothing"
// fallback the dispatcher used before.
inline std::uint64_t call_trampoline(unsigned shape, void* tramp,
                                     const std::uint64_t* a) {
    if (!tramp || shape >= kShapes) return 0;
    return g_tramp_table[shape](tramp, a);
}

// --- argument marshalling -------------------------------------------------
//
// Slot values carry the RAW register bits. For 'd' that is the double; for
// 'f' it is the float's 32-bit pattern in the low half (which is exactly what
// the ABI puts in XMM). fn_call.cpp uses the identical convention, so a value
// can move between a hook callback and rsmm.call without re-encoding.

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
            // Float bits in the LOW half — the mirror of push_arg('f'). This
            // used to store the *double* encoding, so a float replayed through
            // next() (or returned from a callback) reached the game as noise.
            const float f = static_cast<float>(luaL_checknumber(L, idx));
            std::uint32_t bits; std::memcpy(&bits, &f, sizeof(bits));
            return static_cast<std::uint64_t>(bits);
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
    // COPY the slot under the lock. The old code kept a `Slot*` and read
    // `s->sig` / `s->trampoline` after unlocking, so a concurrent uninstall
    // (which assigns `s = Slot{}` and frees the trampoline) could pull the
    // signature string out from under this call.
    Slot snap;
    {
        std::lock_guard<std::mutex> g(g_slots_mu);
        if (slot < 0 || slot >= MAX_SLOTS) return luaL_error(L, "rsmm.hook.next: bad slot");
        snap = g_slots[slot];
    }
    if (!snap.installed || !snap.trampoline) {
        return luaL_error(L, "rsmm.hook.next: slot not installed");
    }
    const char  ret_t = snap.sig[0];
    const auto  args_sv = std::string_view(snap.sig).substr(1);
    const int   n_args = static_cast<int>(args_sv.size());

    std::uint64_t a[8] = {};
    for (int i = 0; i < n_args && i < 8; i++) {
        a[i] = pull_arg(L, 1 + i, args_sv[i]);
    }
    const std::uint64_t raw = call_trampoline(snap.shape, snap.trampoline, a);
    push_arg(L, ret_t, raw);
    return ret_t == 'v' ? 0 : 1;
}

// --- dispatcher -----------------------------------------------------------

std::uint64_t dispatch(int slot, std::uint64_t* a) {
    if (slot < 0 || slot >= MAX_SLOTS) return 0;
    // Take the Lua lock BEFORE snapshotting the slot. hook_lua_uninstall takes
    // the same lock, so a slot that is still `installed` here cannot be torn
    // down (trampoline freed, callback unref'd) while we run below. Lock order
    // is script -> slots everywhere, so this cannot deadlock against install /
    // uninstall / next, all of which are entered from Lua.
    std::lock_guard<std::recursive_mutex> g(script_lua_mutex());
    Slot snap;
    {
        std::lock_guard<std::mutex> gs(g_slots_mu);
        snap = g_slots[slot];
    }
    if (!snap.installed) return 0;

    lua_State* L = snap.L;
    if (!L) return call_trampoline(snap.shape, snap.trampoline, a);
    const int base = lua_gettop(L);
    lua_rawgeti(L, LUA_REGISTRYINDEX, snap.cb_ref);
    if (!lua_isfunction(L, -1)) {
        lua_pop(L, 1);
        return call_trampoline(snap.shape, snap.trampoline, a);
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
        return call_trampoline(snap.shape, snap.trampoline, a);
    }

    std::uint64_t r;
    if (lua_isnoneornil(L, -1)) {
        // Convenience: nil return = "act like a no-op, pass through".
        lua_pop(L, 1);
        r = call_trampoline(snap.shape, snap.trampoline, a);
    } else {
        r = pull_ret(L, -1, ret_t);
        lua_pop(L, 1);
    }
    lua_settop(L, base);
    return r;
}

// --- detour slots: template-instantiated -----------------------------------

// One detour per (shape, slot): MinHook needs a distinct function POINTER per
// hook, and the Windows x64 ABI needs a distinct PROTOTYPE per argument shape.
template <unsigned M, int Slot>
RetT<M> WINAPI detour_t(ArgT<M, 0> a0, ArgT<M, 1> a1, ArgT<M, 2> a2, ArgT<M, 3> a3,
                        std::uint64_t a4, std::uint64_t a5,
                        std::uint64_t a6, std::uint64_t a7)
{
    std::uint64_t a[8] = { raw_bits(a0), raw_bits(a1), raw_bits(a2), raw_bits(a3),
                           a4, a5, a6, a7 };
    const std::uint64_t r = dispatch(Slot, a);
    if constexpr (((M >> kShapeRetBit) & 1u) != 0) {
        double d; std::memcpy(&d, &r, sizeof(d)); return d;
    } else {
        return static_cast<std::uintptr_t>(r);
    }
}

template <unsigned M, int... I>
inline std::array<void*, sizeof...(I)>
make_slot_row(std::integer_sequence<int, I...>) {
    return { reinterpret_cast<void*>(&detour_t<M, I>)... };
}

template <unsigned... S>
inline std::array<std::array<void*, MAX_SLOTS>, sizeof...(S)>
make_detour_table(std::integer_sequence<unsigned, S...>) {
    return { make_slot_row<S>(std::make_integer_sequence<int, MAX_SLOTS>{})... };
}

const std::array<std::array<void*, MAX_SLOTS>, kShapes> g_detour_table =
    make_detour_table(std::make_integer_sequence<unsigned, kShapes>{});

// "<ret><args...>": 'v' is a return-only code, every arg code must be a value
// type, and the arity cap is 8 (the ABI shaping only covers 8 slots).
bool sig_validate(std::string_view sig) {
    if (sig.empty() || sig.size() > 9) return false;
    auto value_code = [](char c) {
        return c == 'i' || c == 'u' || c == 'l' || c == 'p'
            || c == 'f' || c == 'd' || c == 's';
    };
    if (!value_code(sig[0]) && sig[0] != 'v') return false;
    for (char c : sig.substr(1)) if (!value_code(c)) return false;
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
    s.shape     = sig_shape(s.sig);

    // Mods hand us a raw address, so this is where a bad one becomes a jump
    // spliced into the middle of a live function. Warn rather than refuse: x64
    // may legitimately omit a true leaf from .pdata, and the mod author owns
    // the risk — but the log now names the address, which turns "the game
    // crashed" into "your hook target is not a function".
    hook_entry_warn("hook", "mod hook target", target_va);
    auto rc = MH_CreateHook(reinterpret_cast<LPVOID>(target_va),
                            g_detour_table[s.shape][slot],
                            &s.trampoline);
    if (rc != MH_OK) {
        const auto hex = [&]{
            char b[32];
            snprintf(b, sizeof(b), "%llx", (unsigned long long)target_va);
            return std::string(b);
        }();
        s = Slot{};
        // ALREADY_CREATED is not a failure, it is the NORMAL outcome when more
        // than one mod wants the same engine hook: every mod runs in its own
        // lua_State and each arms the SDK's shared capture hooks, so the first
        // one wins and the rest land here. Reported as a plain error it looked
        // like three broken mods — and the SDK, unable to tell the two apart,
        // went on to blame the game build ("handlers unresolved"), which sent
        // debugging in entirely the wrong direction. Distinct return code so
        // the caller can say what actually happened.
        if (rc == MH_ERROR_ALREADY_CREATED) {
            Loader::get().log("[hook] va=0x" + hex + " already hooked by another "
                              "mod; sharing it (not an error)");
            return kHookAlreadyOwned;
        }
        Loader::get().log("[hook] MH_CreateHook va=0x" + hex
                          + " rc=" + std::to_string(static_cast<int>(rc)));
        return -1;
    }
    // Mark installed BEFORE enabling. The other order left a window in which
    // the game could enter the detour while `installed` was still false — and
    // the dispatcher's answer to that is "return 0 without calling the
    // original", i.e. the hooked function silently did nothing on its first
    // call. (We still hold g_slots_mu, so nothing observes the flag early.)
    s.installed = true;
    auto er = MH_EnableHook(reinterpret_cast<LPVOID>(target_va));
    if (er != MH_OK) {
        Loader::get().log("[hook] MH_EnableHook rc=" + std::to_string(static_cast<int>(er)));
        MH_RemoveHook(reinterpret_cast<LPVOID>(target_va));
        s = Slot{};
        return -1;
    }
    Loader::get().log("[hook] slot " + std::to_string(slot) + " installed va=0x"
                      + [&]{char b[32]; snprintf(b,sizeof(b),"%llx",(unsigned long long)target_va); return std::string(b);}()
                      + " sig=" + s.sig + " mod=" + s.mod_id);
    return slot;
}

bool hook_lua_uninstall(int slot) {
    // Script lock first (see dispatch): it is what guarantees no detour is
    // mid-callback on this slot when we free its trampoline and drop the
    // callback ref. Lock order everywhere is script -> slots.
    std::lock_guard<std::recursive_mutex> gl(script_lua_mutex());
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
