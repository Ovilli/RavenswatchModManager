// Lua scripting for mods.
//
// A mod's optional init.lua is executed in its own lua_State after the
// loader has scanned mods/ and applied static (file-based) overrides. The
// script can register additional overrides, react to events, or call any
// rsmm.* API we expose.
//
// API surface is intentionally small. Today: logging, dynamic overrides,
// event callbacks. Future additions (combat hooks, UI extensions) attach
// here.

extern "C" {
#include "lua.h"
#include "lualib.h"
#include "lauxlib.h"
}

#include "script_lua.h"
#include "loader.h"
#include "fn_resolver.h"
#include "fn_call.h"
#include "hook_lua.h"
#include "hook_items.h"

#include "json.hpp"   // single-header nlohmann::json (vendored)

#include <windows.h>

#include <cstdint>
#include <cstring>
#include <filesystem>
#include <fstream>
#include <iterator>
#include <mutex>
#include <type_traits>
#include <unordered_map>
#include <vector>

namespace rsmm {

namespace {

// Recursively materialize a parsed JSON value as a Lua value on the stack.
// Objects -> string-keyed tables, arrays -> 1-based tables, null -> nil.
void json_to_lua(lua_State* L, const nlohmann::json& j) {
    switch (j.type()) {
        case nlohmann::json::value_t::object: {
            lua_createtable(L, 0, (int)j.size());
            for (auto it = j.begin(); it != j.end(); ++it) {
                json_to_lua(L, it.value());
                lua_setfield(L, -2, it.key().c_str());
            }
            break;
        }
        case nlohmann::json::value_t::array: {
            lua_createtable(L, (int)j.size(), 0);
            int i = 1;
            for (const auto& el : j) {
                json_to_lua(L, el);
                lua_rawseti(L, -2, i++);
            }
            break;
        }
        case nlohmann::json::value_t::string:
            lua_pushstring(L, j.get_ref<const std::string&>().c_str());
            break;
        case nlohmann::json::value_t::boolean:
            lua_pushboolean(L, j.get<bool>() ? 1 : 0);
            break;
        case nlohmann::json::value_t::number_integer:
        case nlohmann::json::value_t::number_unsigned:
            lua_pushinteger(L, (lua_Integer)j.get<long long>());
            break;
        case nlohmann::json::value_t::number_float:
            lua_pushnumber(L, j.get<double>());
            break;
        default:
            lua_pushnil(L);
            break;
    }
}

struct ModScript {
    lua_State* L = nullptr;
    std::string id;
    std::filesystem::path root;
    std::filesystem::file_time_type init_mtime{};
};

std::recursive_mutex g_mu;
std::unordered_map<std::string, ModScript> g_scripts;

} // namespace

// Exported so hook_lua.cpp can serialize Lua VM access across
// hook-callback threads. Same mutex protects g_scripts + every
// per-mod lua_State. Recursive: a Lua handler may call back into the
// engine (R.engine.call of a hooked function, e.g. NamedEvent_Dispatch)
// whose detour re-enters script_emit_event_json on the same thread.
std::recursive_mutex& script_lua_mutex() { return g_mu; }

namespace {

ModScript* current_from_state(lua_State* L) {
    lua_getfield(L, LUA_REGISTRYINDEX, "__rsmm_mod_id");
    const char* id = lua_tostring(L, -1);
    lua_pop(L, 1);
    if (!id) return nullptr;
    auto it = g_scripts.find(id);
    return (it == g_scripts.end()) ? nullptr : &it->second;
}

// -- Lua bindings ---------------------------------------------------------

int lua_log(lua_State* L) {
    const char* msg = luaL_checkstring(L, 1);
    auto* m = current_from_state(L);
    std::string tag = m ? ("[" + m->id + "] ") : std::string();
    Loader::get().log(tag + msg);
    return 0;
}

int lua_mod_dir(lua_State* L) {
    auto* m = current_from_state(L);
    lua_pushstring(L, m ? m->root.string().c_str() : "");
    return 1;
}

// rsmm._internal.state_read() -> string | nil
//   Reads <mod_dir>/.rsmm_state (opaque bytes) for the calling mod. Backs
//   the persistent R.kv store. Returns nil when no state file exists.
int lua_state_read(lua_State* L) {
    auto* m = current_from_state(L);
    if (!m) { lua_pushnil(L); return 1; }
    std::ifstream f(m->root / ".rsmm_state", std::ios::binary);
    if (!f) { lua_pushnil(L); return 1; }
    std::string data((std::istreambuf_iterator<char>(f)),
                     std::istreambuf_iterator<char>());
    lua_pushlstring(L, data.data(), data.size());
    return 1;
}

// rsmm._internal.state_write(str) -> bool
//   Persists `str` to <mod_dir>/.rsmm_state via a temp-file + rename so a
//   crash mid-write can't truncate the existing state.
int lua_state_write(lua_State* L) {
    size_t n = 0;
    const char* s = luaL_checklstring(L, 1, &n);
    auto* m = current_from_state(L);
    if (!m) { lua_pushboolean(L, 0); return 1; }
    const auto tmp = m->root / ".rsmm_state.tmp";
    const auto dst = m->root / ".rsmm_state";
    {
        std::ofstream f(tmp, std::ios::binary | std::ios::trunc);
        if (!f) { lua_pushboolean(L, 0); return 1; }
        f.write(s, static_cast<std::streamsize>(n));
        if (!f.good()) { lua_pushboolean(L, 0); return 1; }
    }
    std::error_code ec;
    std::filesystem::rename(tmp, dst, ec);
    if (ec) { std::filesystem::remove(tmp, ec); lua_pushboolean(L, 0); return 1; }
    lua_pushboolean(L, 1);
    return 1;
}

// rsmm.tags([mod_id]) -> table
//   Parsed tags.json for the given mod (default: the calling mod). Returns
//   { tag_id = { "member", ... }, ... }, or an empty table if none.
int lua_mod_tags(lua_State* L) {
    const char* want = lua_tostring(L, 1);  // optional
    const ModScript* m = want ? nullptr : current_from_state(L);
    std::string raw;
    if (want) {
        auto it = g_scripts.find(want);
        if (it != g_scripts.end()) {
            for (const auto& mod : Loader::get().mods())
                if (mod.id == want) { raw = mod.tags_json; break; }
        }
    } else if (m) {
        for (const auto& mod : Loader::get().mods())
            if (mod.id == m->id) { raw = mod.tags_json; break; }
    }
    if (raw.empty()) { lua_newtable(L); return 1; }
    try {
        json_to_lua(L, nlohmann::json::parse(raw));
    } catch (const std::exception&) {
        lua_newtable(L);
    }
    return 1;
}

int lua_register_asset_override(lua_State* L) {
    const char* decoded = luaL_checkstring(L, 1);
    const char* src     = luaL_checkstring(L, 2);
    auto& Ld = Loader::get();
    auto* m = current_from_state(L);
    if (!m) return 0;

    // Stash into a synthetic mod entry-like override. We piggy-back on the
    // loader's existing override table by translating decoded -> encoded
    // and recording the on-disk source path.
    if (const auto* enc = Ld.decoded_to_encoded(decoded)) {
        // Re-enter loader internals via a tiny helper: append the override
        // by mutating the first matching mod's files. For simplicity we
        // log and rely on apply_overrides to be called by the caller (the
        // typical pattern: register everything in init.lua, then call
        // rsmm.commit()).
        for (auto& mod : Ld.mods_mut()) {
            if (mod.id == m->id) {
                ModFile mf;
                mf.decoded_path = decoded;
                mf.src = src;
                mod.files.push_back(std::move(mf));
                break;
            }
        }
        lua_pushboolean(L, 1);
    } else {
        Ld.log(std::string("[lua] no encoded match for ") + decoded);
        lua_pushboolean(L, 0);
    }
    return 1;
}

int lua_commit(lua_State* /*L*/) {
    Loader::get().apply_overrides();
    return 0;
}

int lua_game_dir(lua_State* L) {
    lua_pushstring(L, Loader::get().game_dir().string().c_str());
    return 1;
}

int lua_is_in_main_menu(lua_State* L) {
    lua_pushboolean(L, Loader::get().is_in_main_menu() ? 1 : 0);
    return 1;
}

int lua_list_mods(lua_State* L) {
    const auto& mods = Loader::get().mods();
    lua_createtable(L, (int)mods.size(), 0);
    int idx = 1;
    for (const auto& m : mods) {
        lua_createtable(L, 0, 5);
        lua_pushstring(L, m.id.c_str());      lua_setfield(L, -2, "id");
        lua_pushstring(L, m.name.c_str());    lua_setfield(L, -2, "name");
        lua_pushstring(L, m.version.c_str()); lua_setfield(L, -2, "version");
        lua_pushstring(L, m.author.c_str());  lua_setfield(L, -2, "author");
        lua_pushboolean(L, m.enabled ? 1 : 0); lua_setfield(L, -2, "enabled");
        lua_rawseti(L, -2, idx++);
    }
    return 1;
}

int lua_encoded_path(lua_State* L) {
    const char* decoded = luaL_checkstring(L, 1);
    const auto* enc = Loader::get().decoded_to_encoded(decoded);
    if (enc) { lua_pushstring(L, enc->c_str()); return 1; }
    lua_pushnil(L);
    return 1;
}

int lua_decoded_path(lua_State* L) {
    const char* encoded = luaL_checkstring(L, 1);
    const auto* dec = Loader::get().encoded_to_decoded(encoded);
    if (dec) { lua_pushstring(L, dec->c_str()); return 1; }
    lua_pushnil(L);
    return 1;
}

// Event callbacks live in the registry under key "__rsmm_events"; each
// event name maps to a list of refs.
int lua_on_event(lua_State* L) {
    const char* name = luaL_checkstring(L, 1);
    luaL_checktype(L, 2, LUA_TFUNCTION);
    lua_getfield(L, LUA_REGISTRYINDEX, "__rsmm_events");
    if (lua_isnil(L, -1)) {
        lua_pop(L, 1);
        lua_newtable(L);
        lua_pushvalue(L, -1);
        lua_setfield(L, LUA_REGISTRYINDEX, "__rsmm_events");
    }
    lua_getfield(L, -1, name);
    if (lua_isnil(L, -1)) {
        lua_pop(L, 1);
        lua_newtable(L);
        lua_pushvalue(L, -1);
        lua_setfield(L, -3, name);
    }
    // append fn at end
    lua_pushvalue(L, 2);
    lua_rawseti(L, -2, (lua_Integer)lua_rawlen(L, -2) + 1);
    lua_pop(L, 2);
    return 0;
}

// -- Game function calling --------------------------------------------------
//
// rsmm.resolve(name) -> integer | nil
//   Pattern-resolves a game function by symbolic name (FUN_xxx or a
//   user-given alias). Returns the runtime VA, or nil if not found.
//
// rsmm.call(target, argtypes, ...) -> integer | number | string | nil
//   target: integer VA (from resolve) or a name string.
//   argtypes: string like "iif" — see fn_call.h for codes. The first
//             char is the RETURN type; remaining are arg types.
//   Remaining lua args supply argument values. String args ('s')
//   accept Lua strings (passed as const char*).
//
// rsmm.read_u32(va) / read_u64 / read_f32 / read_f64 / read_cstr(va, max)
// rsmm.write_u32(va, v) / write_u64 / write_f32 / write_f64
//   Raw memory access. Used to read/write game globals once resolved
//   via patterns or pulled from a known offset.
//
// rsmm.module_base() -> integer
//   Image base of Ravenswatch.exe at runtime. Useful for converting
//   recorded link-time VAs to runtime VAs as a fallback, though
//   rsmm.resolve is preferred.

int lua_resolve(lua_State* L) {
    const char* name = luaL_checkstring(L, 1);
    auto va = fn_resolve(name);
    if (va == 0) { lua_pushnil(L); return 1; }
    lua_pushinteger(L, static_cast<lua_Integer>(va));
    return 1;
}

int lua_module_base(lua_State* L) {
    auto h = GetModuleHandleA("Ravenswatch.exe");
    if (!h) h = GetModuleHandleA(nullptr);
    lua_pushinteger(L, reinterpret_cast<lua_Integer>(h));
    return 1;
}

int lua_call_native(lua_State* L) {
    // Arg 1: VA (integer) or name (string).
    std::uintptr_t va = 0;
    if (lua_isinteger(L, 1)) {
        va = static_cast<std::uintptr_t>(lua_tointeger(L, 1));
    } else if (lua_isstring(L, 1)) {
        va = fn_resolve(lua_tostring(L, 1));
        if (va == 0) {
            return luaL_error(L, "rsmm.call: unknown function '%s'", lua_tostring(L, 1));
        }
    } else {
        return luaL_error(L, "rsmm.call: arg 1 must be address or name");
    }
    const char* sig = luaL_checkstring(L, 2);
    if (!sig[0]) return luaL_error(L, "rsmm.call: empty signature");
    char ret_t = sig[0];
    std::string_view arg_t(sig + 1);
    if (arg_t.size() > 8) return luaL_error(L, "rsmm.call: max 8 args");

    std::uint64_t args[8] = {};
    int li = 3;
    for (std::size_t i = 0; i < arg_t.size(); i++, li++) {
        char t = arg_t[i];
        switch (t) {
            case 'i': args[i] = static_cast<std::uint64_t>(static_cast<std::int32_t>(luaL_checkinteger(L, li))); break;
            case 'u': args[i] = static_cast<std::uint64_t>(static_cast<std::uint32_t>(luaL_checkinteger(L, li))); break;
            case 'l':
            case 'p': args[i] = static_cast<std::uint64_t>(luaL_checkinteger(L, li)); break;
            case 'f': { float f = static_cast<float>(luaL_checknumber(L, li)); double d = f; std::memcpy(&args[i], &d, sizeof(d)); break; }
            case 'd': { double d = luaL_checknumber(L, li);                                  std::memcpy(&args[i], &d, sizeof(d)); break; }
            case 's': args[i] = reinterpret_cast<std::uint64_t>(luaL_checkstring(L, li)); break;
            default:  return luaL_error(L, "rsmm.call: bad arg type '%c'", t);
        }
    }

    std::uint64_t raw = fn_call_raw(va, arg_t, args);

    switch (ret_t) {
        case 'v': return 0;
        case 'i': lua_pushinteger(L, static_cast<lua_Integer>(static_cast<std::int32_t>(raw))); return 1;
        case 'u': lua_pushinteger(L, static_cast<lua_Integer>(static_cast<std::uint32_t>(raw))); return 1;
        case 'l':
        case 'p': lua_pushinteger(L, static_cast<lua_Integer>(raw)); return 1;
        case 'f': { float f; std::memcpy(&f, &raw, sizeof(f)); lua_pushnumber(L, f); return 1; }
        case 'd': { double d; std::memcpy(&d, &raw, sizeof(d)); lua_pushnumber(L, d); return 1; }
        case 's': {
            auto p = reinterpret_cast<const char*>(raw);
            if (!p) lua_pushnil(L); else lua_pushstring(L, p);
            return 1;
        }
        default: return luaL_error(L, "rsmm.call: bad ret type '%c'", ret_t);
    }
}

template <typename T>
int read_value(lua_State* L) {
    auto va = static_cast<std::uintptr_t>(luaL_checkinteger(L, 1));
    T v{};
    std::memcpy(&v, reinterpret_cast<const void*>(va), sizeof(T));
    if constexpr (std::is_floating_point_v<T>) lua_pushnumber(L, v);
    else lua_pushinteger(L, static_cast<lua_Integer>(v));
    return 1;
}
template <typename T>
int write_value(lua_State* L) {
    auto va = static_cast<std::uintptr_t>(luaL_checkinteger(L, 1));
    T v;
    if constexpr (std::is_floating_point_v<T>) v = static_cast<T>(luaL_checknumber(L, 2));
    else v = static_cast<T>(luaL_checkinteger(L, 2));
    std::memcpy(reinterpret_cast<void*>(va), &v, sizeof(T));
    return 0;
}

int lua_read_u8 (lua_State* L) { return read_value<std::uint8_t >(L); }
int lua_read_u16(lua_State* L) { return read_value<std::uint16_t>(L); }
int lua_read_u32(lua_State* L) { return read_value<std::uint32_t>(L); }
int lua_read_u64(lua_State* L) { return read_value<std::uint64_t>(L); }
int lua_read_f32(lua_State* L) { return read_value<float        >(L); }
int lua_read_f64(lua_State* L) { return read_value<double       >(L); }
int lua_write_u8 (lua_State* L) { return write_value<std::uint8_t >(L); }
int lua_write_u16(lua_State* L) { return write_value<std::uint16_t>(L); }
int lua_write_u32(lua_State* L) { return write_value<std::uint32_t>(L); }
int lua_write_u64(lua_State* L) { return write_value<std::uint64_t>(L); }
int lua_write_f32(lua_State* L) { return write_value<float        >(L); }
int lua_write_f64(lua_State* L) { return write_value<double       >(L); }

// rsmm.hook(name_or_va, sig, callback) -> slot_handle
//   name_or_va: string (resolved via fn_resolve) or integer (runtime VA).
//   sig:        rsmm.call-style "rXXXX" (first char = ret type, rest = args).
//   callback:   function(arg1, arg2, ..., next).
//     - Receives unpacked args + a `next` closure that replays the
//       original game function with arbitrary args.
//     - Return nil -> auto-call original with received args and return
//       its result (read-only hook pattern).
//     - Return value -> overrides the original return; original is NOT
//       called unless the callback already invoked `next` explicitly.
int lua_hook(lua_State* L) {
    std::uintptr_t va = 0;
    if (lua_isinteger(L, 1)) {
        va = static_cast<std::uintptr_t>(lua_tointeger(L, 1));
    } else if (lua_isstring(L, 1)) {
        va = fn_resolve(lua_tostring(L, 1));
        if (va == 0) return luaL_error(L, "rsmm.hook: unknown function '%s'",
                                       lua_tostring(L, 1));
    } else {
        return luaL_error(L, "rsmm.hook: arg 1 must be address or name");
    }
    const char* sig = luaL_checkstring(L, 2);
    if (!sig[0]) return luaL_error(L, "rsmm.hook: empty sig");
    luaL_checktype(L, 3, LUA_TFUNCTION);

    // Ref the callback into the current state's registry.
    lua_pushvalue(L, 3);
    int cb_ref = luaL_ref(L, LUA_REGISTRYINDEX);

    auto* m = current_from_state(L);
    std::string mod_id = m ? m->id : std::string{"(unknown)"};

    int slot = hook_lua_install(va, sig, L, cb_ref, mod_id);
    if (slot < 0) {
        luaL_unref(L, LUA_REGISTRYINDEX, cb_ref);
        return luaL_error(L, "rsmm.hook: install failed (see _log.txt)");
    }
    lua_pushinteger(L, slot);
    return 1;
}

int lua_unhook(lua_State* L) {
    int slot = (int)luaL_checkinteger(L, 1);
    bool ok = hook_lua_uninstall(slot);
    lua_pushboolean(L, ok ? 1 : 0);
    return 1;
}

int lua_hook_count(lua_State* L) {
    lua_pushinteger(L, static_cast<lua_Integer>(hook_lua_active_count()));
    return 1;
}

// rsmm._internal.register_item(id, name, description, base, entity_path, rarity)
//   Called by R.item.register() in rsmm.lua. Stores the registration into
//   the C++ hook_items registry so the hook can inject the entity resource
//   into the magical-object pool at spawn time.
//   Returns true on success, false on duplicate id.
int lua_register_item(lua_State* L) {
    const char* id          = luaL_checkstring(L, 1);
    const char* name        = luaL_optstring(L, 2, "");
    const char* description = luaL_optstring(L, 3, "");
    const char* base        = luaL_optstring(L, 4, "");
    const char* entity_path = luaL_optstring(L, 5, "");
    int          rarity     = (int)luaL_optinteger(L, 6, 0);
    bool ok = register_native_item(id, name, description, base, entity_path, rarity);
    lua_pushboolean(L, ok ? 1 : 0);
    return 1;
}

int lua_read_cstr(lua_State* L) {
    auto va = static_cast<std::uintptr_t>(luaL_checkinteger(L, 1));
    auto max = static_cast<std::size_t>(luaL_optinteger(L, 2, 1024));
    auto p = reinterpret_cast<const char*>(va);
    std::size_t n = 0;
    while (n < max && p[n]) n++;
    lua_pushlstring(L, p, n);
    return 1;
}

// Page-state guard so a bad pointer (the norm while chasing struct offsets)
// returns nil/false instead of access-violating the game. Confirms the whole
// [addr, addr+size) range is committed + readable (and writable for poke).
static bool mem_accessible(std::uintptr_t addr, std::size_t size, bool need_write) {
    if (addr == 0) return false;
    const DWORD readable = PAGE_READONLY | PAGE_READWRITE | PAGE_WRITECOPY |
                           PAGE_EXECUTE_READ | PAGE_EXECUTE_READWRITE |
                           PAGE_EXECUTE_WRITECOPY;
    const DWORD writable = PAGE_READWRITE | PAGE_WRITECOPY |
                           PAGE_EXECUTE_READWRITE | PAGE_EXECUTE_WRITECOPY;
    for (std::uintptr_t a = addr; a < addr + size; ) {
        MEMORY_BASIC_INFORMATION mbi{};
        if (VirtualQuery(reinterpret_cast<void*>(a), &mbi, sizeof(mbi)) == 0) return false;
        if (mbi.State != MEM_COMMIT) return false;
        if (mbi.Protect & (PAGE_NOACCESS | PAGE_GUARD)) return false;
        if (!(mbi.Protect & readable)) return false;
        if (need_write && !(mbi.Protect & writable) &&
            !(mbi.Protect & (PAGE_READONLY | PAGE_EXECUTE_READ))) {
            // read-only page is fine for poke (we VirtualProtect it RW); only
            // truly inaccessible protections fail above.
        }
        auto region_end = reinterpret_cast<std::uintptr_t>(mbi.BaseAddress) + mbi.RegionSize;
        a = region_end;
    }
    return true;
}

// rsmm.peek(addr [, size=8]) -> integer | nil   (size in {1,2,4,8})
// Guarded raw read; nil on an unreadable address. Use to walk struct offsets
// and pointer chains (e.g. the netcode role field) — see docs/_re/MULTIPLAYER.md.
int lua_peek(lua_State* L) {
    auto addr = static_cast<std::uintptr_t>(luaL_checkinteger(L, 1));
    auto size = static_cast<int>(luaL_optinteger(L, 2, 8));
    if (size != 1 && size != 2 && size != 4 && size != 8)
        return luaL_error(L, "rsmm.peek: size must be 1, 2, 4 or 8");
    if (!mem_accessible(addr, static_cast<std::size_t>(size), false)) {
        lua_pushnil(L);
        return 1;
    }
    std::uint64_t v = 0;
    switch (size) {
        case 1: v = *reinterpret_cast<std::uint8_t*>(addr); break;
        case 2: v = *reinterpret_cast<std::uint16_t*>(addr); break;
        case 4: v = *reinterpret_cast<std::uint32_t*>(addr); break;
        case 8: v = *reinterpret_cast<std::uint64_t*>(addr); break;
    }
    lua_pushinteger(L, static_cast<lua_Integer>(v));
    return 1;
}

// rsmm.poke(addr, value [, size=8]) -> bool   (size in {1,2,4,8})
// Guarded raw write (VirtualProtects the page RW around the store). Returns
// false on an inaccessible address. DANGEROUS — only behind an explicit,
// opt-in experiment mod.
int lua_poke(lua_State* L) {
    auto addr = static_cast<std::uintptr_t>(luaL_checkinteger(L, 1));
    auto val = static_cast<std::uint64_t>(luaL_checkinteger(L, 2));
    auto size = static_cast<int>(luaL_optinteger(L, 3, 8));
    if (size != 1 && size != 2 && size != 4 && size != 8)
        return luaL_error(L, "rsmm.poke: size must be 1, 2, 4 or 8");
    if (!mem_accessible(addr, static_cast<std::size_t>(size), true)) {
        lua_pushboolean(L, 0);
        return 1;
    }
    DWORD oldp = 0;
    if (!VirtualProtect(reinterpret_cast<void*>(addr), size, PAGE_EXECUTE_READWRITE, &oldp)) {
        lua_pushboolean(L, 0);
        return 1;
    }
    switch (size) {
        case 1: *reinterpret_cast<std::uint8_t*>(addr) = static_cast<std::uint8_t>(val); break;
        case 2: *reinterpret_cast<std::uint16_t*>(addr) = static_cast<std::uint16_t>(val); break;
        case 4: *reinterpret_cast<std::uint32_t*>(addr) = static_cast<std::uint32_t>(val); break;
        case 8: *reinterpret_cast<std::uint64_t*>(addr) = val; break;
    }
    DWORD tmp = 0;
    VirtualProtect(reinterpret_cast<void*>(addr), size, oldp, &tmp);
    lua_pushboolean(L, 1);
    return 1;
}

// rsmm._internal.scratch([size=0x100]) -> addr
// Loader-owned scratch region for building native structs from Lua (e.g. an
// oCGameNamedEvent before NamedEvent_Dispatch). One static buffer, zeroed on
// every call — callers must finish using it before the next scratch() call.
// Serialized by the script mutex like every other Lua entry point.
int lua_scratch(lua_State* L) {
    constexpr std::size_t kScratchCap = 0x1000;
    alignas(16) static std::uint8_t buf[kScratchCap];
    auto size = static_cast<std::size_t>(luaL_optinteger(L, 1, 0x100));
    if (size == 0 || size > kScratchCap)
        return luaL_error(L, "rsmm.scratch: size must be 1..%d", (int)kScratchCap);
    std::memset(buf, 0, size);
    lua_pushinteger(L, static_cast<lua_Integer>(reinterpret_cast<std::uintptr_t>(buf)));
    return 1;
}

void register_api(lua_State* L) {
    // Public, documented surface. This is what a mod author writes against.
    // High-level behaviors (R.item.register / R.scaling / R.talent / ...)
    // live in the Lua-side `rsmm` module installed alongside the loader
    // and are loaded by `require "rsmm"`.
    static const luaL_Reg public_lib[] = {
        { "log",                     lua_log },
        { "mod_dir",                 lua_mod_dir },
        { "tags",                    lua_mod_tags },
        { "register_asset_override", lua_register_asset_override },
        { "on_event",                lua_on_event },
        { "commit",                  lua_commit },
        { "hook",                    lua_hook },
        { "unhook",                  lua_unhook },
        { "hook_count",              lua_hook_count },
        { nullptr, nullptr }
    };
    // Power-user / SDK-internal surface. Not documented in the modding
    // guide. The high-level `rsmm` Lua module uses these under the hood;
    // mod authors should reach for the documented `R.*` API first and
    // only drop down here when nothing covers their case.
    static const luaL_Reg internal_lib[] = {
        { "resolve",                 lua_resolve },
        { "call",                    lua_call_native },
        { "module_base",             lua_module_base },
        { "game_dir",                lua_game_dir },
        { "is_in_main_menu",         lua_is_in_main_menu },
        { "list_mods",               lua_list_mods },
        { "encoded_path",            lua_encoded_path },
        { "decoded_path",            lua_decoded_path },
        { "read_u8",                 lua_read_u8 },
        { "read_u16",                lua_read_u16 },
        { "read_u32",                lua_read_u32 },
        { "read_u64",                lua_read_u64 },
        { "read_f32",                lua_read_f32 },
        { "read_f64",                lua_read_f64 },
        { "read_cstr",               lua_read_cstr },
        { "peek",                    lua_peek },
        { "poke",                    lua_poke },
        { "scratch",                 lua_scratch },
        { "register_item",           lua_register_item },
        { "write_u8",                lua_write_u8 },
        { "write_u16",               lua_write_u16 },
        { "write_u32",               lua_write_u32 },
        { "write_u64",               lua_write_u64 },
        { "write_f32",               lua_write_f32 },
        { "write_f64",               lua_write_f64 },
        { "state_read",              lua_state_read },
        { "state_write",             lua_state_write },
        { nullptr, nullptr }
    };
    luaL_newlib(L, public_lib);          // -1 = rsmm
    luaL_newlib(L, internal_lib);        // -2 = rsmm, -1 = _internal
    lua_setfield(L, -2, "_internal");
    lua_setglobal(L, "rsmm");
}

} // namespace

bool script_run_mod_init(const std::string& mod_id,
                         const std::filesystem::path& mod_root) {
    const auto init_path = mod_root / "init.lua";
    if (!std::filesystem::exists(init_path)) return false;

    std::lock_guard<std::recursive_mutex> g(g_mu);
    lua_State* L = luaL_newstate();
    if (!L) return false;
    luaL_openlibs(L);

    // Sandbox: remove dangerous functions so mod init.lua can't escape
    // the asset-override sandbox via os.execute / io.open / debug / load.
    lua_pushnil(L); lua_setglobal(L, "dofile");
    lua_pushnil(L); lua_setglobal(L, "loadfile");
    lua_pushnil(L); lua_setglobal(L, "load");
    lua_pushnil(L); lua_setglobal(L, "collectgarbage");
    lua_pushnil(L); lua_setglobal(L, "debug");
    lua_pushnil(L); lua_setglobal(L, "io");
    lua_getglobal(L, "os");
    if (lua_istable(L, -1)) {
      lua_pushnil(L); lua_setfield(L, -2, "execute");
      lua_pushnil(L); lua_setfield(L, -2, "rename");
      lua_pushnil(L); lua_setfield(L, -2, "remove");
      lua_pushnil(L); lua_setfield(L, -2, "exit");
      lua_pushnil(L); lua_setfield(L, -2, "tmpname");
    }
    lua_pop(L, 1);

    lua_pushstring(L, mod_id.c_str());
    lua_setfield(L, LUA_REGISTRYINDEX, "__rsmm_mod_id");
    register_api(L);

    // Prepend `<game>/rsmm/lib/?.lua` to package.path so `require "rsmm"`
    // (and friends) resolve to the SDK module that ships next to the
    // loader. Without this Lua's default search path would only find
    // mods/<id>/init.lua. The native `rsmm` global stays available as a
    // fallback for low-level scripts that don't want the wrapper.
    {
        const auto sdk_lib_dir =
            Loader::get().game_dir() / "rsmm" / "lib";
        const std::string entry =
            sdk_lib_dir.string() + "/?.lua;" +
            sdk_lib_dir.string() + "/?/init.lua;";
        lua_getglobal(L, "package");
        if (lua_istable(L, -1)) {
            lua_getfield(L, -1, "path");
            const std::string cur = lua_isstring(L, -1) ? lua_tostring(L, -1) : "";
            lua_pop(L, 1);
            lua_pushstring(L, (entry + cur).c_str());
            lua_setfield(L, -2, "path");
        }
        lua_pop(L, 1);
    }

    ModScript& s = g_scripts[mod_id];
    s.L    = L;
    s.id   = mod_id;
    s.root = mod_root;
    std::error_code ec;
    s.init_mtime = std::filesystem::last_write_time(init_path, ec);

    if (luaL_dofile(L, init_path.string().c_str()) != LUA_OK) {
        Loader::get().log(std::string("[lua] ") + mod_id + " init failed: "
                          + lua_tostring(L, -1));
        lua_close(L);
        g_scripts.erase(mod_id);
        return false;
    }
    Loader::get().log("[lua] " + mod_id + " init OK");
    return true;
}

namespace {

// Shared dispatch: call every handler of `name` with one argument — the
// payload table (built per-state by `push_payload`). Handlers registered
// under "*" receive every event as (payload, name); exact-name handlers
// keep the one-argument form.
template <class PushPayload>
void emit_locked(const std::string& name, PushPayload push_payload) {
    std::lock_guard<std::recursive_mutex> g(g_mu);
    for (auto& [id, s] : g_scripts) {
        if (!s.L) continue;
        lua_State* L = s.L;
        lua_getfield(L, LUA_REGISTRYINDEX, "__rsmm_events");
        if (!lua_istable(L, -1)) { lua_pop(L, 1); continue; }
        for (const char* key : {name.c_str(), "*"}) {
            const bool wildcard = (key[0] == '*' && key[1] == '\0');
            if (wildcard && name == "*") break;  // don't double-fire literal "*"
            lua_getfield(L, -1, key);
            if (!lua_istable(L, -1)) { lua_pop(L, 1); continue; }
            const int n = (int)lua_rawlen(L, -1);
            for (int i = 1; i <= n; ++i) {
                lua_rawgeti(L, -1, i);     // handler fn
                push_payload(L);           // arg 1: payload table
                if (wildcard) lua_pushlstring(L, name.data(), name.size());  // arg 2
                if (lua_pcall(L, wildcard ? 2 : 1, 0, 0) != LUA_OK) {
                    Loader::get().log(std::string("[lua] ") + id + " event " + name + ": "
                                      + lua_tostring(L, -1));
                    lua_pop(L, 1);
                }
            }
            lua_pop(L, 1);
        }
        lua_pop(L, 1);
    }
}

} // namespace

void script_emit_event(const std::string& name) {
    emit_locked(name, [](lua_State* L) { lua_newtable(L); });
}

void script_emit_event_json(const std::string& name, const std::string& payload_json) {
    nlohmann::json parsed;
    bool ok = false;
    try {
        parsed = nlohmann::json::parse(payload_json);
        ok = parsed.is_object() || parsed.is_array();
    } catch (const std::exception&) {
        ok = false;
    }
    emit_locked(name, [&](lua_State* L) {
        if (ok) json_to_lua(L, parsed); else lua_newtable(L);
    });
}

void script_reload_changed() {
    // Poll every loaded mod's init.lua; if mtime has advanced, tear
    // down the lua_State and re-run init. The mod's own subscribers
    // (rsmm.on_event) live inside the registry table, so closing
    // lua_close drops them automatically — no stale callbacks remain.
    std::vector<std::pair<std::string, std::filesystem::path>> to_reload;
    {
        std::lock_guard<std::recursive_mutex> g(g_mu);
        for (auto& [id, s] : g_scripts) {
            const auto init_path = s.root / "init.lua";
            std::error_code ec;
            auto mt = std::filesystem::last_write_time(init_path, ec);
            if (ec) continue;
            if (mt != s.init_mtime) {
                to_reload.emplace_back(id, s.root);
            }
        }
    }
    for (auto& [id, root] : to_reload) {
        Loader::get().log("[lua] " + id + " reload (init.lua changed)");
        // Drop the mod's hooks first; the slots hold cb_refs that
        // become dangling the moment we close the lua_State.
        hook_lua_unregister_mod(id);
        // Tear down old state, build new one.
        {
            std::lock_guard<std::recursive_mutex> g(g_mu);
            auto it = g_scripts.find(id);
            if (it != g_scripts.end() && it->second.L) {
                lua_close(it->second.L);
                g_scripts.erase(it);
            }
        }
        script_run_mod_init(id, root);
        // Replay "ready" so handlers re-register and fire once.
        script_emit_event("ready");
    }
}

void script_shutdown_all() {
    // Drop all hooks before any lua_State goes away so the trampoline
    // dispatcher can't be entered with a destroyed VM.
    hook_lua_shutdown();
    std::lock_guard<std::recursive_mutex> g(g_mu);
    for (auto& [_, s] : g_scripts) {
        if (s.L) lua_close(s.L);
    }
    g_scripts.clear();
}

} // namespace rsmm
