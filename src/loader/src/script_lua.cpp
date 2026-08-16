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
#include "hook_util.h"
#include "loader.h"
#include "health.h"
#include "mem_safe.h"
#include "fn_resolver.h"
#include "symbols_api.gen.h"   // engine:: typed, pattern-resolved accessors
#include "fn_call.h"
#include "hook_lua.h"
#include "hook_items.h"

#include "json.hpp"   // single-header nlohmann::json (vendored)
#include "toml.hpp"   // single-header toml++ (vendored)

#include <windows.h>

#include <algorithm>
#include <atomic>
#include <cstdint>
#include <cstring>
#include <filesystem>
#include <fstream>
#include <iterator>
#include <limits>
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
    // How many rsmm.on_event handlers this state registered, so closing it
    // can take them back out of the process-wide count.
    int handlers = 0;
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

// Newest mtime across every *.lua under a mod directory, or a default-
// constructed time when the tree can't be walked. Hot-reload keys off this
// rather than init.lua alone: a mod that splits its code into modules
// (`require "mymod.thing"`) never reloaded when the module changed, because
// only the entry point was watched — and the modules are re-required from
// scratch anyway, since the reload rebuilds the whole lua_State.
std::filesystem::file_time_type newest_lua_mtime(const std::filesystem::path& root) {
    std::filesystem::file_time_type newest{};
    std::error_code ec;
    std::filesystem::recursive_directory_iterator it(
        root, std::filesystem::directory_options::skip_permission_denied, ec);
    if (ec) return newest;
    int budget = 512;   // don't stat a mod that ships an enormous asset tree
    for (const auto& entry : it) {
        if (--budget < 0) break;
        if (!entry.is_regular_file(ec) || ec) continue;
        if (entry.path().extension() != ".lua") continue;
        auto mt = std::filesystem::last_write_time(entry.path(), ec);
        if (ec) continue;
        if (mt > newest) newest = mt;
    }
    return newest;
}

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

// rsmm._internal.self_id() -> string
//   The calling mod's id. R.api uses it to namespace exposed APIs; without
//   this binding every mod's api_name defaulted to "?" and the SECOND mod to
//   call R.api.expose() errored with "name already taken: ?".
int lua_self_id(lua_State* L) {
    auto* m = current_from_state(L);
    lua_pushstring(L, m ? m->id.c_str() : "");
    return 1;
}

// rsmm._internal.now() -> number
//   Monotonic seconds (fractional) since process start. R.schedule's timers
//   fall back to os.time() when this is missing, which has ONE-SECOND
//   resolution — so `R.schedule.after(0.25, ...)` was really "somewhere in the
//   next second or two", and repeated sub-second polls all fired at once.
int lua_now(lua_State* L) {
    static const LARGE_INTEGER freq = []{
        LARGE_INTEGER f{}; QueryPerformanceFrequency(&f); return f;
    }();
    static const LARGE_INTEGER start = []{
        LARGE_INTEGER c{}; QueryPerformanceCounter(&c); return c;
    }();
    LARGE_INTEGER now{};
    if (freq.QuadPart == 0 || !QueryPerformanceCounter(&now)) {
        lua_pushnumber(L, static_cast<lua_Number>(GetTickCount64()) / 1000.0);
        return 1;
    }
    lua_pushnumber(L, static_cast<lua_Number>(now.QuadPart - start.QuadPart)
                        / static_cast<lua_Number>(freq.QuadPart));
    return 1;
}

// -- crash history / boot canary (backs rsmm/health.lua) --------------------

int lua_health_count(lua_State* L) {
    const char* id = luaL_optstring(L, 1, nullptr);
    auto* m = current_from_state(L);
    const std::string want = id ? id : (m ? m->id : std::string{});
    lua_pushinteger(L, health::crash_count(want));
    return 1;
}

int lua_health_last_error(lua_State* L) {
    const char* id = luaL_optstring(L, 1, nullptr);
    auto* m = current_from_state(L);
    const std::string want = id ? id : (m ? m->id : std::string{});
    const std::string err = health::last_error(want);
    if (err.empty()) lua_pushnil(L); else lua_pushstring(L, err.c_str());
    return 1;
}

int lua_health_disable(lua_State* L) {
    const char* id = luaL_optstring(L, 1, nullptr);
    const char* reason = luaL_optstring(L, 2, "");
    auto* m = current_from_state(L);
    const std::string want = id ? id : (m ? m->id : std::string{});
    if (want.empty()) { lua_pushboolean(L, 0); return 1; }
    health::set_disabled(want, reason);
    lua_pushboolean(L, 1);
    return 1;
}

int lua_health_checkpoint(lua_State* L) {
    const char* step = luaL_checkstring(L, 1);
    auto* m = current_from_state(L);
    health::checkpoint(m ? ("per_mod:" + m->id + ":" + step) : std::string(step));
    return 0;
}

// -- localisation (backs rsmm/i18n.lua) ------------------------------------
//
// A mod ships <mod>/lang/<LOCALE>.toml (a `[strings]` table, per the SDK
// guide) or <mod>/lang/<LOCALE>.json (a flat {key: "text"} object). The
// active locale comes from RSMM_LOCALE, else <game>/rsmm/locale.txt, else EN;
// a missing locale falls back to EN, which is what the guide promises.
// Parsed once per lua_State and cached in the registry.

const char* active_locale() {
    static const std::string locale = []{
        char buf[16] = {0};
        DWORD n = GetEnvironmentVariableA("RSMM_LOCALE", buf, sizeof(buf));
        if (n > 0 && n < sizeof(buf)) return std::string(buf);
        std::error_code ec;
        const auto p = Loader::get().game_dir() / "rsmm" / "locale.txt";
        if (std::filesystem::exists(p, ec)) {
            std::ifstream f(p);
            std::string s;
            if (std::getline(f, s)) {
                while (!s.empty() && (s.back() == '\r' || s.back() == '\n' ||
                                      s.back() == ' ')) s.pop_back();
                if (!s.empty() && s.size() < 16) return s;
            }
        }
        return std::string("EN");
    }();
    return locale.c_str();
}

int lua_i18n_locale(lua_State* L) {
    lua_pushstring(L, active_locale());
    return 1;
}

// Merge one lang file into the table at the top of the stack. Missing file =
// no-op; a parse error logs and leaves what's already there.
void load_locale_file(lua_State* L, const std::filesystem::path& path) {
    std::error_code ec;
    if (!std::filesystem::exists(path, ec)) return;
    try {
        if (path.extension() == ".toml") {
            toml::table doc = toml::parse_file(path.string());
            const toml::table* section = doc["strings"].as_table();
            if (!section) section = &doc;   // tolerate a flat file
            for (auto&& [key, node] : *section) {
                if (auto s = node.as_string()) {
                    lua_pushstring(L, (**s).c_str());
                    lua_setfield(L, -2, std::string(key.str()).c_str());
                }
            }
        } else {
            std::ifstream f(path);
            nlohmann::json j;
            f >> j;
            if (j.is_object()) {
                for (auto it = j.begin(); it != j.end(); ++it) {
                    if (!it.value().is_string()) continue;
                    lua_pushstring(L, it.value().get_ref<const std::string&>().c_str());
                    lua_setfield(L, -2, it.key().c_str());
                }
            }
        }
    } catch (const std::exception& e) {
        Loader::get().log(std::string("[i18n] ") + path.string()
                          + " parse error: " + e.what());
    }
}

int lua_i18n_table(lua_State* L) {
    lua_getfield(L, LUA_REGISTRYINDEX, "__rsmm_i18n");
    if (lua_istable(L, -1)) return 1;
    lua_pop(L, 1);

    lua_newtable(L);
    if (auto* m = current_from_state(L)) {
        // EN last so it acts as the fallback: strings the active locale is
        // missing keep the English text instead of vanishing.
        std::vector<std::string> locales;
        if (std::strcmp(active_locale(), "EN") != 0) locales.emplace_back("EN");
        locales.emplace_back(active_locale());
        for (const auto& loc : locales) {
            load_locale_file(L, m->root / "lang" / (loc + ".toml"));
            load_locale_file(L, m->root / "lang" / (loc + ".json"));
        }
    }
    lua_pushvalue(L, -1);
    lua_setfield(L, LUA_REGISTRYINDEX, "__rsmm_i18n");
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

// -- Per-mod config (<mod_dir>/config.toml) --------------------------------
//
// The host-side ConfigStore (rsmm.sdk.config) persists user-edited values
// as a flat `[config]` table of primitives; `rsmm apply` / install-loader
// sync the file into the game-side mod dir. The sandbox nils `io`, so the
// file is read here and exposed as rsmm._internal.config_get/_set/_all
// (consumed by the R.config Lua module). Loaded once per lua_State at
// script_run_mod_init; a hot-reload of init.lua re-reads it.

void load_mod_config(lua_State* L, const std::filesystem::path& root) {
    lua_newtable(L);
    const auto cfg_path = root / "config.toml";
    std::error_code ec;
    if (std::filesystem::exists(cfg_path, ec)) {
        try {
            toml::table doc = toml::parse_file(cfg_path.string());
            const toml::table* section = doc["config"].as_table();
            if (!section) section = &doc;  // tolerate flat files without [config]
            for (auto&& [key, node] : *section) {
                if (auto b = node.as_boolean())             lua_pushboolean(L, **b ? 1 : 0);
                else if (auto i = node.as_integer())        lua_pushinteger(L, (lua_Integer)**i);
                else if (auto f = node.as_floating_point()) lua_pushnumber(L, **f);
                else if (auto s = node.as_string())         lua_pushstring(L, (**s).c_str());
                else continue;
                lua_setfield(L, -2, std::string(key.str()).c_str());
            }
        } catch (const std::exception& e) {
            Loader::get().log(std::string("[config] parse fail ")
                              + cfg_path.string() + ": " + e.what());
        }
    }
    lua_setfield(L, LUA_REGISTRYINDEX, "__rsmm_config");
}

bool config_write_file(lua_State* L, const std::filesystem::path& root) {
    lua_getfield(L, LUA_REGISTRYINDEX, "__rsmm_config");
    if (!lua_istable(L, -1)) { lua_pop(L, 1); return false; }
    toml::table section;
    lua_pushnil(L);
    while (lua_next(L, -2)) {
        if (lua_type(L, -2) == LUA_TSTRING) {
            const std::string k = lua_tostring(L, -2);
            switch (lua_type(L, -1)) {
                case LUA_TBOOLEAN:
                    section.insert(k, (bool)lua_toboolean(L, -1));
                    break;
                case LUA_TNUMBER:
                    if (lua_isinteger(L, -1))
                        section.insert(k, (std::int64_t)lua_tointeger(L, -1));
                    else
                        section.insert(k, (double)lua_tonumber(L, -1));
                    break;
                case LUA_TSTRING:
                    section.insert(k, std::string(lua_tostring(L, -1)));
                    break;
                default: break;  // tables/functions never persist
            }
        }
        lua_pop(L, 1);
    }
    lua_pop(L, 1);
    toml::table doc;
    doc.insert("config", std::move(section));
    // Temp-file + rename, same crash-safety contract as state_write.
    const auto tmp = root / "config.toml.tmp";
    const auto dst = root / "config.toml";
    {
        std::ofstream f(tmp, std::ios::trunc);
        if (!f) return false;
        f << doc << "\n";
        if (!f.good()) return false;
    }
    std::error_code ec;
    std::filesystem::rename(tmp, dst, ec);
    if (ec) { std::filesystem::remove(tmp, ec); return false; }
    return true;
}

// rsmm._internal.config_get(key) -> bool|integer|number|string | nil
int lua_config_get(lua_State* L) {
    luaL_checkstring(L, 1);
    lua_getfield(L, LUA_REGISTRYINDEX, "__rsmm_config");
    if (!lua_istable(L, -1)) { lua_pushnil(L); return 1; }
    lua_pushvalue(L, 1);
    lua_gettable(L, -2);
    return 1;
}

// rsmm._internal.config_set(key, value) -> bool
//   Updates the in-memory table and persists <mod_dir>/config.toml. Value
//   must be nil (= delete key), boolean, number, or string — the primitive
//   set the host-side schema can validate.
int lua_config_set(lua_State* L) {
    luaL_checkstring(L, 1);
    const int t = lua_type(L, 2);
    if (t != LUA_TNIL && t != LUA_TBOOLEAN && t != LUA_TNUMBER && t != LUA_TSTRING)
        return luaL_error(L, "config value must be nil, boolean, number or string");
    auto* m = current_from_state(L);
    if (!m) { lua_pushboolean(L, 0); return 1; }
    lua_getfield(L, LUA_REGISTRYINDEX, "__rsmm_config");
    if (!lua_istable(L, -1)) {
        lua_pop(L, 1);
        lua_newtable(L);
        lua_pushvalue(L, -1);
        lua_setfield(L, LUA_REGISTRYINDEX, "__rsmm_config");
    }
    lua_pushvalue(L, 1);
    lua_pushvalue(L, 2);
    lua_settable(L, -3);
    lua_pop(L, 1);
    lua_pushboolean(L, config_write_file(L, m->root) ? 1 : 0);
    return 1;
}

// rsmm._internal.config_all() -> table (shallow copy)
int lua_config_all(lua_State* L) {
    lua_newtable(L);
    lua_getfield(L, LUA_REGISTRYINDEX, "__rsmm_config");
    if (lua_istable(L, -1)) {
        lua_pushnil(L);
        while (lua_next(L, -2)) {
            lua_pushvalue(L, -2);   // key
            lua_pushvalue(L, -2);   // value
            lua_settable(L, -6);    // result[key] = value
            lua_pop(L, 1);
        }
    }
    lua_pop(L, 1);
    return 1;
}

// rsmm._internal.intent_write(op, mod_id) -> bool
//   Append a mod-lifecycle intent for the HOST-side CLI to consume (the game
//   runs under Proton; the loader cannot shell out to rsmm in-process). One
//   JSON object per line in <cooking>/.rsmm_intents.jsonl, next to
//   .rsmm_state.json; `rsmm intents apply` executes + clears it. The op
//   allowlist and the mod-id shape are validated HERE so a misbehaving mod
//   cannot turn the intent file into an arbitrary-write primitive.
int lua_intent_write(lua_State* L) {
    static const char* kOps[] = { "enable", "disable", "uninstall" };
    const char* op = luaL_checkstring(L, 1);
    const char* mod = luaL_checkstring(L, 2);
    bool op_ok = false;
    for (const char* k : kOps) op_ok = op_ok || std::strcmp(op, k) == 0;
    size_t mlen = std::strlen(mod);
    bool mod_ok = mlen > 0 && mlen < 64;
    for (size_t i = 0; mod_ok && i < mlen; ++i) {
        char c = mod[i];
        mod_ok = (c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z') ||
                 (c >= '0' && c <= '9') || c == '-' || c == '_' || c == '.';
    }
    if (mod_ok && (mod[0] == '.' || std::strstr(mod, "..") != nullptr)) mod_ok = false;
    if (!op_ok || !mod_ok) {
        Loader::get().log(std::string("[intents] rejected op='") + op + "' mod='" + mod + "'");
        lua_pushboolean(L, 0);
        return 1;
    }
    const auto path = Loader::get().game_dir() / "DarkTalesResources" / "_Cooking"
                    / ".rsmm_intents.jsonl";
    nlohmann::json line = {
        {"op", op},
        {"mod", mod},
        {"ts", static_cast<std::uint64_t>(GetTickCount64())},
    };
    std::ofstream f(path, std::ios::binary | std::ios::app);
    if (!f) { lua_pushboolean(L, 0); return 1; }
    f << line.dump() << "\n";
    lua_pushboolean(L, f.good() ? 1 : 0);
    Loader::get().log(std::string("[intents] queued ") + op + " " + mod);
    return 1;
}

// rsmm.tags([mod_id]) -> table
//   Parsed tags.json for the given mod (default: the calling mod). Returns
//   { tag_id = { "member", ... }, ... }, or an empty table if none.
int lua_mod_tags(lua_State* L) {
    const char* want = lua_tostring(L, 1);  // optional
    const ModScript* m = want ? nullptr : current_from_state(L);
    std::string id = want ? std::string(want) : (m ? m->id : std::string{});
    std::string raw;
    if (!id.empty()) {
        // Look the mod up in the LOADER's list, not in g_scripts. Keying off
        // g_scripts meant a mod without an init.lua (data-only mods are the
        // common case) had no script entry, so its tags.json read back empty
        // even though the loader had it parsed and in memory.
        for (const auto& mod : Loader::get().mods())
            if (mod.id == id) { raw = mod.tags_json; break; }
    }
    if (raw.empty()) { lua_newtable(L); return 1; }
    try {
        json_to_lua(L, nlohmann::json::parse(raw));
    } catch (const std::exception&) {
        lua_newtable(L);
    }
    return 1;
}

// -- cross-mod API bridge (backs rsmm/api.lua) -----------------------------
//
// Every mod runs in its OWN lua_State, so a table exposed by mod A is simply
// not reachable from mod B's state — R.api's registry was a plain Lua table
// and therefore only ever visible to the mod that filled it. The registry
// lives natively instead, and calls are marshalled across states as JSON.
//
// That means the contract is DATA, not closures: arguments and the return
// value must be nil / boolean / number / string / table-of-those. A function
// argument cannot cross a state boundary and is rejected rather than silently
// arriving as nil.

struct ApiEntry {
    std::string mod_id;
    std::string version;
};
// Guarded by g_mu. Every path that runs Lua takes it first — mod init,
// emit_locked, and the hook dispatcher — so a binding body is always already
// under the lock and may touch g_apis / g_scripts directly.
std::unordered_map<std::string, ApiEntry> g_apis;

// Serialize the Lua value at `idx` into `out`. Returns false when the value
// contains something that cannot cross a state boundary.
bool lua_to_json(lua_State* L, int idx, nlohmann::json& out, int depth = 0) {
    if (depth > 16) return false;
    idx = lua_absindex(L, idx);
    switch (lua_type(L, idx)) {
        case LUA_TNIL: case LUA_TNONE: out = nullptr; return true;
        case LUA_TBOOLEAN: out = (lua_toboolean(L, idx) != 0); return true;
        case LUA_TNUMBER:
            if (lua_isinteger(L, idx)) out = (long long)lua_tointeger(L, idx);
            else                       out = (double)lua_tonumber(L, idx);
            return true;
        case LUA_TSTRING: {
            size_t n = 0;
            const char* s = lua_tolstring(L, idx, &n);
            out = std::string(s, n);
            return true;
        }
        case LUA_TTABLE: break;
        default: return false;      // function / userdata / thread
    }
    // Array iff keys are exactly 1..n.
    const auto len = (lua_Integer)lua_rawlen(L, idx);
    bool is_array = len > 0;
    if (is_array) {
        lua_pushnil(L);
        while (lua_next(L, idx)) {
            if (!lua_isinteger(L, -2) || lua_tointeger(L, -2) < 1
                || lua_tointeger(L, -2) > len) {
                is_array = false;
                lua_pop(L, 2);
                break;
            }
            lua_pop(L, 1);
        }
    }
    if (is_array) {
        out = nlohmann::json::array();
        for (lua_Integer i = 1; i <= len; ++i) {
            lua_rawgeti(L, idx, i);
            nlohmann::json v;
            const bool ok = lua_to_json(L, -1, v, depth + 1);
            lua_pop(L, 1);
            if (!ok) return false;
            out.push_back(std::move(v));
        }
        return true;
    }
    out = nlohmann::json::object();
    lua_pushnil(L);
    while (lua_next(L, idx)) {
        const int kt = lua_type(L, -2);
        if (kt != LUA_TSTRING && kt != LUA_TNUMBER) { lua_pop(L, 2); return false; }
        lua_pushvalue(L, -2);                 // stringify a copy, not the key
        const std::string key = lua_tostring(L, -1);
        lua_pop(L, 1);
        nlohmann::json v;
        const bool ok = lua_to_json(L, -1, v, depth + 1);
        lua_pop(L, 1);
        if (!ok) return false;
        out[key] = std::move(v);
    }
    return true;
}

// rsmm._internal.api_expose(name, version, table) -> bool
//   Stashes `table` in this state's registry under `__rsmm_api[name]` and
//   records name -> (mod, version) in the process-wide map.
int lua_api_expose(lua_State* L) {
    const char* name = luaL_checkstring(L, 1);
    const char* version = luaL_optstring(L, 2, "0.0.0");
    luaL_checktype(L, 3, LUA_TTABLE);
    auto* m = current_from_state(L);
    if (!m) { lua_pushboolean(L, 0); return 1; }
    auto it = g_apis.find(name);
    if (it != g_apis.end() && it->second.mod_id != m->id) {
        return luaL_error(L, "rsmm.api: '%s' is already exposed by mod '%s'",
                          name, it->second.mod_id.c_str());
    }
    lua_getfield(L, LUA_REGISTRYINDEX, "__rsmm_api");
    if (!lua_istable(L, -1)) {
        lua_pop(L, 1);
        lua_newtable(L);
        lua_pushvalue(L, -1);
        lua_setfield(L, LUA_REGISTRYINDEX, "__rsmm_api");
    }
    lua_pushvalue(L, 3);
    lua_setfield(L, -2, name);
    lua_pop(L, 1);

    g_apis[name] = ApiEntry{ m->id, version };
    Loader::get().log("[api] " + m->id + " exposes '" + std::string(name)
                      + "' v" + version);
    lua_pushboolean(L, 1);
    return 1;
}

// rsmm._internal.api_info(name) -> mod_id, version | nil
int lua_api_info(lua_State* L) {
    const char* name = luaL_checkstring(L, 1);
    auto it = g_apis.find(name);
    if (it == g_apis.end()) { lua_pushnil(L); return 1; }
    lua_pushstring(L, it->second.mod_id.c_str());
    lua_pushstring(L, it->second.version.c_str());
    return 2;
}

// rsmm._internal.api_list() -> { name = { mod_id, version }, ... }
int lua_api_list(lua_State* L) {
    lua_createtable(L, 0, (int)g_apis.size());
    for (const auto& [name, e] : g_apis) {
        lua_createtable(L, 0, 2);
        lua_pushstring(L, e.mod_id.c_str());  lua_setfield(L, -2, "mod_id");
        lua_pushstring(L, e.version.c_str()); lua_setfield(L, -2, "version");
        lua_setfield(L, -2, name.c_str());
    }
    return 1;
}

// rsmm._internal.api_call(name, key, ...) -> ok, result_or_error
//   Invokes `__rsmm_api[name][key](...)` in the PROVIDING mod's lua_State.
//   Arguments and the result cross as JSON (see the note above). Errors from
//   the provider are returned as (false, message) rather than propagated, so
//   a broken provider can't take down its consumer.
int lua_api_call(lua_State* L) {
    const char* name = luaL_checkstring(L, 1);
    const char* key  = luaL_checkstring(L, 2);
    const int nargs = lua_gettop(L) - 2;

    auto it = g_apis.find(name);
    if (it == g_apis.end()) {
        lua_pushboolean(L, 0);
        lua_pushfstring(L, "rsmm.api: '%s' is not exposed", name);
        return 2;
    }
    auto sit = g_scripts.find(it->second.mod_id);
    if (sit == g_scripts.end() || !sit->second.L) {
        lua_pushboolean(L, 0);
        lua_pushfstring(L, "rsmm.api: provider '%s' has no live state",
                        it->second.mod_id.c_str());
        return 2;
    }

    nlohmann::json args = nlohmann::json::array();
    for (int i = 0; i < nargs; ++i) {
        nlohmann::json v;
        if (!lua_to_json(L, 3 + i, v)) {
            lua_pushboolean(L, 0);
            lua_pushfstring(L, "rsmm.api: argument %d is not data "
                               "(functions/userdata cannot cross mods)", i + 1);
            return 2;
        }
        args.push_back(std::move(v));
    }

    lua_State* T = sit->second.L;
    const int base = lua_gettop(T);
    lua_getfield(T, LUA_REGISTRYINDEX, "__rsmm_api");
    if (!lua_istable(T, -1)) {
        lua_settop(T, base);
        lua_pushboolean(L, 0);
        lua_pushstring(L, "rsmm.api: provider exposed no table");
        return 2;
    }
    lua_getfield(T, -1, name);
    if (!lua_istable(T, -1)) {
        lua_settop(T, base);
        lua_pushboolean(L, 0);
        lua_pushfstring(L, "rsmm.api: provider has no '%s' table", name);
        return 2;
    }
    lua_getfield(T, -1, key);
    if (!lua_isfunction(T, -1)) {
        // Not callable: expose the VALUE instead (fields are legal too).
        nlohmann::json v;
        const bool ok = lua_to_json(T, -1, v);
        lua_settop(T, base);
        lua_pushboolean(L, ok ? 1 : 0);
        if (ok) json_to_lua(L, v);
        else lua_pushfstring(L, "rsmm.api: '%s.%s' is not callable or data", name, key);
        return 2;
    }
    for (const auto& a : args) json_to_lua(T, a);
    if (lua_pcall(T, static_cast<int>(args.size()), 1, 0) != LUA_OK) {
        const char* err = lua_tostring(T, -1);
        std::string msg = err ? err : "unknown error";
        lua_settop(T, base);
        lua_pushboolean(L, 0);
        lua_pushlstring(L, msg.data(), msg.size());
        return 2;
    }
    nlohmann::json result;
    const bool ok = lua_to_json(T, -1, result);
    lua_settop(T, base);
    lua_pushboolean(L, ok ? 1 : 0);
    if (ok) json_to_lua(L, result);
    else lua_pushstring(L, "rsmm.api: provider returned a non-data value");
    return 2;
}

// rsmm._internal.emit(name, payload) -> bool
//   Publish an event to EVERY mod's state (including the caller's). This is
//   the signalling half of cross-mod communication: R.api carries data CALLS,
//   but a callback cannot cross a lua_State boundary, so a producer tells
//   consumers "something happened" by emitting.
//
//   Two rules make a forged event impossible to mistake for an engine one:
//
//   * Reserved names are refused. The loader owns "gameplay:" / "ui:" and the
//     lifecycle events, and a mod that could emit under those names could
//     drive another mod's engine-mutating handlers whenever it liked.
//   * `source` and `from` are stamped by the loader, overwriting whatever the
//     mod supplied. This one matters for thread safety: R.schedule's MAIN
//     thread pump and R.stat's re-assert both gate on `ev.source ==
//     "gameplay"`, i.e. "we are inside the NamedEvent_Dispatch detour on the
//     game's own thread". A mod emitting that from the ticker thread would
//     run engine-mutating callbacks off-thread — the exact race those gates
//     exist to prevent (see [[loader-thread-model]]).
int lua_emit_event(lua_State* L) {
    const char* name = luaL_checkstring(L, 1);
    if (!lua_isnoneornil(L, 2)) luaL_checktype(L, 2, LUA_TTABLE);

    // Prefixes the loader publishes under. A mod emitting one of these could
    // make other mods act on a state change that never happened.
    static const char* const kReservedPrefix[] = {
        "gameplay:", "ui:", "rsmm:", "hero:", "menu:", "run:", "mods:",
    };
    static const char* const kReservedExact[]  = { "setup", "ready", "tick", "exit", "*" };
    for (const char* p : kReservedPrefix) {
        if (std::strncmp(name, p, std::strlen(p)) == 0) {
            return luaL_error(L, "rsmm.emit: '%s' is reserved by the loader "
                                 "(prefix your own events with '<modid>:')", name);
        }
    }
    for (const char* e : kReservedExact) {
        if (std::strcmp(name, e) == 0) {
            return luaL_error(L, "rsmm.emit: '%s' is a lifecycle event and "
                                 "cannot be emitted by a mod", name);
        }
    }

    nlohmann::json payload = nlohmann::json::object();
    if (lua_istable(L, 2) && !lua_to_json(L, 2, payload)) {
        return luaL_error(L, "rsmm.emit: payload must be data "
                             "(nil/boolean/number/string/table)");
    }
    if (!payload.is_object()) payload = nlohmann::json::object();
    auto* m = current_from_state(L);
    payload["event"]  = name;
    payload["source"] = "mod";
    payload["from"]   = m ? m->id : std::string("(unknown)");

    // Recursive mutex: emitting from inside a handler re-enters on the same
    // thread, and emit_locked dispatches over a snapshot, so that is safe.
    script_emit_event_json(name, payload.dump());
    lua_pushboolean(L, 1);
    return 1;
}

int lua_register_asset_override(lua_State* L) {
    const char* decoded = luaL_checkstring(L, 1);
    const char* src     = luaL_checkstring(L, 2);
    auto& Ld = Loader::get();
    auto* m = current_from_state(L);
    if (!m) return 0;

    // The source must live inside the calling mod's own directory. Without
    // this a mod's init.lua could point an override at ANY file on the user's
    // disk, and the IO hook would then serve that file's bytes to the game.
    {
        std::error_code ec;
        auto abs_src = std::filesystem::weakly_canonical(
            std::filesystem::absolute(src, ec), ec);
        auto abs_root = std::filesystem::weakly_canonical(m->root, ec);
        const auto rel = abs_src.lexically_relative(abs_root);
        if (ec || rel.empty() || *rel.begin() == "..") {
            Ld.log("[lua] " + m->id + " override source rejected (outside the "
                   "mod directory): " + std::string(src));
            lua_pushboolean(L, 0);
            return 1;
        }
    }

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

// Total handlers registered across every state. The gameplay bus fires
// hundreds of times a second in combat, and formatting + parsing a payload
// nobody reads is pure overhead — the detours check this first and bail.
std::atomic<int> g_handler_count{0};

// Event callbacks live in the registry under key "__rsmm_events"; each
// event name maps to a list of refs.
int lua_on_event(lua_State* L) {
    const char* name = luaL_checkstring(L, 1);
    luaL_checktype(L, 2, LUA_TFUNCTION);
    g_handler_count.fetch_add(1, std::memory_order_relaxed);
    if (auto* m = current_from_state(L)) m->handlers++;
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

// rsmm.va_trusted() -> bool
//   False when the installed game build differs from the build the symbol
//   map's absolute data addresses were derived for (see Loader::init's
//   va-gate). Lua features built on such addresses (R.options, R.give's
//   pool scan) must degrade gracefully instead of reading garbage.
int lua_va_trusted(lua_State* L) {
    lua_pushboolean(L, Loader::get().va_globals_trusted() ? 1 : 0);
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
            // 'f' carries the FLOAT's 32 bits in the low half (the ABI's XMM
            // layout), not a widened double — see fn_call.h.
            case 'f': { float f = static_cast<float>(luaL_checknumber(L, li));
                        std::uint32_t b; std::memcpy(&b, &f, sizeof(b)); args[i] = b; break; }
            case 'd': { double d = luaL_checknumber(L, li); std::memcpy(&args[i], &d, sizeof(d)); break; }
            case 's': args[i] = reinterpret_cast<std::uint64_t>(luaL_checkstring(L, li)); break;
            default:  return luaL_error(L, "rsmm.call: bad arg type '%c'", t);
        }
    }
    // Validate the return code BEFORE calling: a bad code used to make the
    // call anyway and only then raise, so a typo'd signature still ran an
    // engine function with a wrong prototype.
    switch (ret_t) {
        case 'v': case 'i': case 'u': case 'l': case 'p': case 'f': case 'd': case 's': break;
        default: return luaL_error(L, "rsmm.call: bad ret type '%c'", ret_t);
    }

    std::uint64_t raw = fn_call_raw_ret(va, ret_t, arg_t, args);

    switch (ret_t) {
        case 'v': return 0;
        case 'i': lua_pushinteger(L, static_cast<lua_Integer>(static_cast<std::int32_t>(raw))); return 1;
        case 'u': lua_pushinteger(L, static_cast<lua_Integer>(static_cast<std::uint32_t>(raw))); return 1;
        case 'l':
        case 'p': lua_pushinteger(L, static_cast<lua_Integer>(raw)); return 1;
        case 'f': { float f; auto lo = static_cast<std::uint32_t>(raw);
                    std::memcpy(&f, &lo, sizeof(f)); lua_pushnumber(L, f); return 1; }
        case 'd': { double d; std::memcpy(&d, &raw, sizeof(d)); lua_pushnumber(L, d); return 1; }
        case 's': {
            // The game returned a char*; copy it out through the page guard so
            // a stale/garbage pointer yields nil instead of faulting.
            if (!raw) { lua_pushnil(L); return 1; }
            char buf[1024];
            const std::size_t n = mem_read_cstr(static_cast<std::uintptr_t>(raw),
                                                buf, sizeof(buf));
            if (n == 0 && !mem_accessible(static_cast<std::uintptr_t>(raw), 1, false)) {
                lua_pushnil(L);
            } else {
                lua_pushlstring(L, buf, n);
            }
            return 1;
        }
    }
    return 0;
}

// The page-state guard (rsmm::mem_accessible, mem_safe.h) keeps every raw
// read/write primitive from access-violating the game on a bad pointer — the
// norm while chasing struct offsets.

template <typename T>
int read_value(lua_State* L) {
    auto va = static_cast<std::uintptr_t>(luaL_checkinteger(L, 1));
    if (!mem_accessible(va, sizeof(T), false)) { lua_pushnil(L); return 1; }
    T v{};
    std::memcpy(&v, reinterpret_cast<const void*>(va), sizeof(T));
    if constexpr (std::is_floating_point_v<T>) lua_pushnumber(L, v);
    else lua_pushinteger(L, static_cast<lua_Integer>(v));
    return 1;
}
template <typename T>
int write_value(lua_State* L) {
    auto va = static_cast<std::uintptr_t>(luaL_checkinteger(L, 1));
    if (!mem_accessible(va, sizeof(T), true)) { lua_pushboolean(L, 0); return 1; }
    T v;
    if constexpr (std::is_floating_point_v<T>) v = static_cast<T>(luaL_checknumber(L, 2));
    else v = static_cast<T>(luaL_checkinteger(L, 2));
    std::memcpy(reinterpret_cast<void*>(va), &v, sizeof(T));
    lua_pushboolean(L, 1);
    return 1;
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
    if (slot == kHookAlreadyOwned) {
        // Another mod's state already owns this hook. That is the expected
        // outcome for the SDK's shared capture hooks whenever more than one
        // mod is installed, and the hook is live — so this is a soft result,
        // not an error. Second return value lets rsmm.lua tell "someone else
        // has it" (fine) from "this build cannot be hooked" (fail closed).
        luaL_unref(L, LUA_REGISTRYINDEX, cb_ref);
        lua_pushnil(L);
        lua_pushstring(L, "already-hooked");
        return 2;
    }
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

// rsmm._internal.item_guid(id) -> lo, hi  (or nil if not resolvable yet)
//   Returns a registered custom item's runtime identity GUID once its
//   definition has loaded into the magical-object pool. nil until then, so the
//   caller polls. Backs R.item.guid() — the bridge that lets a mod bind
//   R.item.behavior to its OWN registered item without precomputing the GUID.
int lua_item_guid(lua_State* L) {
    const char* id = luaL_checkstring(L, 1);
    unsigned long long lo = 0, hi = 0;
    if (!resolve_item_guid(id, &lo, &hi)) { lua_pushnil(L); return 1; }
    lua_pushinteger(L, (lua_Integer)lo);
    lua_pushinteger(L, (lua_Integer)hi);
    return 2;
}

// _internal.is_grant_target(entity_va) -> bool
//   True iff `entity` owns a magical-object component, i.e. it is a grantable
//   hero and NOT a summon / pet / enemy. Mirrors the discriminator at the top
//   of Hero_GrantMagicalObject (FUN_140397030): store = *(entity+8), then a
//   read-only F14 lookup keyed by the entity pointer; heroes are registered in
//   the store, transient entities are not. R.give's dispatcher capture uses
//   this to reject a non-hero dispatcher (a summon that fired an anchor event)
//   from clobbering _give_hero. Every dereference is page-guarded so a bogus
//   pointer returns false instead of faulting the game.
int lua_is_grant_target(lua_State* L) {
    auto entity = static_cast<std::uintptr_t>(luaL_checkinteger(L, 1));
    // Need the object header + the component-store pointer at entity+0x8.
    if (!mem_accessible(entity, 0x10, false)) { lua_pushboolean(L, 0); return 1; }
    std::uintptr_t store = 0;
    std::memcpy(&store, reinterpret_cast<const void*>(entity + 8), sizeof(store));
    // The lookup dereferences the store's F14 control/slot arrays at +0x1d0.. —
    // require the whole header committed before handing it to the engine fn.
    if (!mem_accessible(store, 0x1f0, false)) { lua_pushboolean(L, 0); return 1; }
    auto fn = engine::Entity_LookupMagicalObjectComponent();
    if (!fn) { lua_pushboolean(L, 0); return 1; }
    void* out = nullptr;
    fn(reinterpret_cast<void*>(store), &out, reinterpret_cast<void*>(entity));
    lua_pushboolean(L, out != nullptr ? 1 : 0);
    return 1;
}

// _internal.steam_name([steamid64]) -> string | nil
//   The Steam display name: the local player's with no argument, another
//   account's with a SteamID64.
//
//   Read straight out of steam_api64.dll's FLAT api, which the shipped DLL
//   exports (SteamAPI_SteamFriends_v017 -> ISteamFriends*, then
//   SteamAPI_ISteamFriends_GetPersonaName / _GetFriendPersonaName). Going
//   through the DLL rather than the game's own party structures means this
//   keeps working across game patches, and it is why "You" can become a real
//   name today: no netcode RE required for the LOCAL player.
//
//   Steam only knows a remote name once it has seen that account (a lobby
//   member, a friend); for an unknown id it returns the empty string, which
//   surfaces here as nil rather than a blank row.
//
//   Everything is resolved lazily and cached: a miss (game launched without
//   Steam, DLL absent) must cost one GetProcAddress, not one per call.
int lua_steam_name(lua_State* L) {
    using GetFriendsFn = void* (*)();
    using PersonaFn    = const char* (*)(void*);
    using FriendFn     = const char* (*)(void*, std::uint64_t);

    static bool          tried   = false;
    static void*         friends = nullptr;
    static PersonaFn     persona = nullptr;
    static FriendFn      friend_name = nullptr;

    if (!tried) {
        tried = true;
        if (HMODULE m = GetModuleHandleA("steam_api64.dll")) {
            auto get_friends = reinterpret_cast<GetFriendsFn>(
                reinterpret_cast<void*>(GetProcAddress(m, "SteamAPI_SteamFriends_v017")));
            persona = reinterpret_cast<PersonaFn>(
                reinterpret_cast<void*>(GetProcAddress(m, "SteamAPI_ISteamFriends_GetPersonaName")));
            friend_name = reinterpret_cast<FriendFn>(
                reinterpret_cast<void*>(
                    GetProcAddress(m, "SteamAPI_ISteamFriends_GetFriendPersonaName")));
            if (get_friends) friends = get_friends();
            Loader::get().log(std::string("[steam] persona lookup ")
                              + (friends && persona ? "available" : "unavailable"));
        }
    }
    if (!friends) { lua_pushnil(L); return 1; }

    const char* name = nullptr;
    if (lua_isnoneornil(L, 1)) {
        if (persona) name = persona(friends);
    } else {
        const auto id = static_cast<std::uint64_t>(luaL_checkinteger(L, 1));
        if (friend_name) name = friend_name(friends, id);
    }
    // Steam returns "" for an account it has never seen. A blank label is
    // worse than no label: the caller can fall back to something meaningful.
    if (!name || !*name) { lua_pushnil(L); return 1; }
    lua_pushstring(L, name);
    return 1;
}

// _internal.mem_find(needle [, max_hits=16] [, budget_mb=512]) -> { va, ... }
//
// Every address in the process whose bytes equal `needle`. An RE probe, not a
// gameplay API: it exists because "where does the engine keep the player
// names" is a question static analysis kept answering with a maybe. Give it a
// string you can already see on screen and it reports every copy — and the
// copies that sit at a regular stride ARE the player table.
//
// Two deliberate choices:
//
//  1. ReadProcessMemory, not a direct read. A committed page can be decommitted
//     by another thread between VirtualQuery and the compare, and MinGW has no
//     __try to catch the fault. RPM validates in the kernel and returns FALSE,
//     so the worst case is a skipped region rather than a dead game.
//  2. A hard byte budget. This walks the whole user address space; without a
//     cap a fragmented heap turns a debug probe into a multi-second freeze.
//     Private, committed, readable, non-guard pages only — mapped images and
//     file views cannot hold a runtime-received name.
int lua_mem_find(lua_State* L) {
    std::size_t needle_len = 0;
    const char* needle = luaL_checklstring(L, 1, &needle_len);
    const auto max_hits = static_cast<std::size_t>(luaL_optinteger(L, 2, 16));
    auto budget = static_cast<std::size_t>(luaL_optinteger(L, 3, 512)) << 20;
    if (needle_len == 0 || needle_len > 512 || max_hits == 0) {
        lua_createtable(L, 0, 0);
        lua_pushinteger(L, 0);
        return 2;
    }

    constexpr std::size_t CHUNK = 1u << 20;
    // Overlap so a match straddling two chunks is still found.
    const std::size_t overlap = needle_len - 1;
    std::vector<char> buf(CHUNK + overlap);
    std::vector<std::uintptr_t> hits;

    SYSTEM_INFO si{};
    GetSystemInfo(&si);
    auto addr = reinterpret_cast<std::uintptr_t>(si.lpMinimumApplicationAddress);
    const auto limit = reinterpret_cast<std::uintptr_t>(si.lpMaximumApplicationAddress);
    // RESUME POINT. A full sweep copies gigabytes and takes seconds; even on a
    // background thread that saturates memory bandwidth and the process VM
    // lock, which the player feels as a hitch. The caller therefore walks the
    // address space in small slices across many ticks, passing back the
    // address this call stopped at. Second return value is that address, or 0
    // when the sweep is complete.
    if (auto from = static_cast<std::uintptr_t>(luaL_optinteger(L, 4, 0)); from > addr)
        addr = from;

    std::uintptr_t resume = 0;
    MEMORY_BASIC_INFORMATION mbi{};
    while (addr < limit && hits.size() < max_hits && budget > 0) {
        if (VirtualQuery(reinterpret_cast<LPCVOID>(addr), &mbi, sizeof(mbi)) != sizeof(mbi))
            break;
        const auto region = reinterpret_cast<std::uintptr_t>(mbi.BaseAddress);
        const std::size_t size = mbi.RegionSize;
        const DWORD prot = mbi.Protect & 0xFF;
        const bool usable =
            mbi.State == MEM_COMMIT && mbi.Type == MEM_PRIVATE
            && !(mbi.Protect & (PAGE_GUARD | PAGE_NOACCESS))
            && (prot == PAGE_READWRITE || prot == PAGE_WRITECOPY
                || prot == PAGE_EXECUTE_READWRITE);
        if (usable) {
            std::size_t off = 0;
            for (; off < size && hits.size() < max_hits && budget > 0; off += CHUNK) {
                const std::size_t want = (std::min)(CHUNK + overlap, size - off);
                SIZE_T got = 0;
                if (!ReadProcessMemory(GetCurrentProcess(),
                                       reinterpret_cast<LPCVOID>(region + off),
                                       buf.data(), want, &got) || got < needle_len)
                    continue;
                budget = got >= budget ? 0 : budget - got;
                for (std::size_t i = 0; i + needle_len <= got; ++i) {
                    if (std::memcmp(buf.data() + i, needle, needle_len) == 0) {
                        hits.push_back(region + off + i);
                        if (hits.size() >= max_hits) break;
                    }
                }
            }
            // Out of budget PART-WAY through a region: resume at the chunk we
            // did not reach, not at the next region. Advancing past `region +
            // size` here would silently skip the remainder — and the lobby
            // block lives in exactly the kind of large region where that
            // matters.
            if (budget == 0 && off < size) {
                resume = region + off;
                break;
            }
        }
        if (size == 0) break;
        addr = region + size;
        if (budget == 0) { resume = addr; break; }
    }

    lua_createtable(L, static_cast<int>(hits.size()), 0);
    for (std::size_t i = 0; i < hits.size(); ++i) {
        lua_pushinteger(L, static_cast<lua_Integer>(hits[i]));
        lua_rawseti(L, -2, static_cast<int>(i) + 1);
    }
    // 0 means "swept to the end of the address space" — the caller uses that
    // to know a slice sequence is finished rather than merely paused.
    lua_pushinteger(L, static_cast<lua_Integer>(resume));
    return 2;
}

// rsmm._internal.hook_report() -> { {tag=, what=, va=, fires=}, ... }
//
// The armed-hook registry, so a mod (or `R.hooks.status()`) can answer "is this
// capability live, and has it ever run". Installed-but-never-fired is the case
// worth surfacing: it means the target moved to a different caller, which
// resolve + fn_verify + .pdata all pass happily.
int lua_hook_report(lua_State* L) {
    HookInfo info[64];
    const std::size_t n = hook_snapshot(info, 64);
    lua_createtable(L, static_cast<int>(n), 0);
    for (std::size_t i = 0; i < n; ++i) {
        lua_createtable(L, 0, 4);
        lua_pushstring(L, info[i].tag ? info[i].tag : "?");
        lua_setfield(L, -2, "tag");
        lua_pushstring(L, info[i].what ? info[i].what : "?");
        lua_setfield(L, -2, "what");
        lua_pushinteger(L, static_cast<lua_Integer>(info[i].va));
        lua_setfield(L, -2, "va");
        lua_pushinteger(L, static_cast<lua_Integer>(info[i].fires));
        lua_setfield(L, -2, "fires");
        lua_rawseti(L, -2, static_cast<int>(i) + 1);
    }
    return 1;
}

int lua_read_cstr(lua_State* L) {
    auto va = static_cast<std::uintptr_t>(luaL_checkinteger(L, 1));
    auto max = static_cast<std::size_t>(luaL_optinteger(L, 2, 1024));
    if (max == 0 || !mem_accessible(va, 1, false)) { lua_pushnil(L); return 1; }
    if (max > 0x10000) max = 0x10000;
    // mem_read_cstr stops at the first byte outside the readable range, so a
    // non-terminated string near a page boundary can't fault.
    std::vector<char> buf(max + 1);
    const std::size_t n = mem_read_cstr(va, buf.data(), buf.size());
    lua_pushlstring(L, buf.data(), n);
    return 1;
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
    // Read-only check on purpose: poke upgrades the protection itself just
    // below, so demanding a writable page here would refuse the read-only
    // pages it exists to patch.
    if (!mem_accessible(addr, static_cast<std::size_t>(size), false)) {
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
    // Ring arena, NOT a single static buffer. Callers legitimately need two
    // live scratch blocks at once (e.g. a forged event struct plus the empty
    // string it points at). The old single static buffer made every call
    // return the SAME address and memset its front — which nulled a live
    // event's vftable and crashed the engine's virtual fill with a zero
    // vtable (2026-07-16 R.stat.modify, READ @0x20 at ModifierEvent_Ctor).
    // Successive allocations now come from distinct arena regions; a block is
    // only reused after the ring wraps (32 KiB of newer allocations), which a
    // build-then-call scratch user never survives long enough to see.
    constexpr std::size_t kArenaCap = 0x8000;
    constexpr std::size_t kMaxAlloc = 0x1000;   // per-call cap (unchanged API)
    alignas(16) static std::uint8_t arena[kArenaCap];
    static std::size_t cursor = 0;
    static std::mutex m;   // two Lua threads may scratch concurrently
    auto size = static_cast<std::size_t>(luaL_optinteger(L, 1, 0x100));
    if (size == 0 || size > kMaxAlloc)
        return luaL_error(L, "rsmm.scratch: size must be 1..%d", (int)kMaxAlloc);
    std::uint8_t* p = nullptr;
    {
        std::lock_guard<std::mutex> lk(m);
        std::size_t aligned = (size + 15) & ~static_cast<std::size_t>(15);
        if (cursor + aligned > kArenaCap) cursor = 0;   // wrap
        p = arena + cursor;
        cursor += aligned;
    }
    std::memset(p, 0, size);
    lua_pushinteger(L, static_cast<lua_Integer>(reinterpret_cast<std::uintptr_t>(p)));
    return 1;
}

// rsmm._internal.shared_get(slot) -> int ; rsmm._internal.shared_set(slot, val)
// Tiny process-global key/value store (slots 0..15), shared across EVERY mod's
// Lua state. MinHook installs are process-global: only one Lua state wins the
// hook on a given engine address (a second mod hooking the same addr gets
// MH_ERROR_ALREADY_CREATED). So a handle captured by one mod's capture hook
// (e.g. the hero entity) must be published somewhere all states can read it.
// This is that somewhere. Atomic so the (main-thread) capture write is visible
// to any state's read without a lock.
// Storage lives here (file-local); the rsmm:: accessors are defined just past
// the anonymous namespace so they have external linkage for native callers.
std::atomic<std::uint64_t> g_shared[16];
int lua_shared_get(lua_State* L) {
    auto slot = static_cast<int>(luaL_checkinteger(L, 1));
    if (slot < 0 || slot >= 16) return luaL_error(L, "rsmm.shared_get: slot must be 0..15");
    lua_pushinteger(L, static_cast<lua_Integer>(shared_get(slot)));
    return 1;
}
// Slots 8..15 are the native hero-candidate RING (hook_events.cpp
// kHeroRingFirst): they hold live hero POINTERS published by the spawn-init
// hook, and Lua's promotion loop reads them. A Lua write there does not just
// collide with another latch, it EVICTS a spawn candidate — on 2026-08-16 a
// probe latch took slot 9 and `hero CAPTURED` stopped happening for the rest
// of the session, with nothing in the log connecting the two. Read-only from
// Lua, enforced here rather than by convention.
constexpr int kSharedRingFirst = 8;

int lua_shared_set(lua_State* L) {
    auto slot = static_cast<int>(luaL_checkinteger(L, 1));
    if (slot < 0 || slot >= 16) return luaL_error(L, "rsmm.shared_set: slot must be 0..15");
    if (slot >= kSharedRingFirst)
        return luaL_error(L, "rsmm.shared_set: slots %d..15 are the native hero "
                             "candidate ring and are read-only from Lua",
                          kSharedRingFirst);
    shared_set(slot, static_cast<std::uint64_t>(luaL_checkinteger(L, 2)));
    return 0;
}

// Remove the parts of the standard library a mod has no business reaching.
//
// Nil-ing the GLOBAL is not enough: luaL_openlibs also records every standard
// library in `package.loaded`, so `local io = require "io"` handed the mod
// back the very table we had just hidden — and `package.loadlib` / a
// `package.cpath` search could load an arbitrary DLL into the game process.
// Both holes are closed here, and the loaders list is trimmed to the Lua-file
// searcher so `require` can still find SDK modules but can never load native
// code.
void apply_sandbox(lua_State* L) {
    static const char* const kDropGlobals[] = {
        "dofile", "loadfile", "load", "collectgarbage", "debug", "io",
    };
    for (const char* g : kDropGlobals) { lua_pushnil(L); lua_setglobal(L, g); }

    // package.loaded.<lib> = nil, so require can't resurrect them.
    lua_getfield(L, LUA_REGISTRYINDEX, LUA_LOADED_TABLE);
    if (lua_istable(L, -1)) {
        for (const char* g : kDropGlobals) {
            lua_pushnil(L); lua_setfield(L, -2, g);
        }
    }
    lua_pop(L, 1);

    lua_getglobal(L, "os");
    if (lua_istable(L, -1)) {
        static const char* const kDropOs[] = {
            "execute", "rename", "remove", "exit", "tmpname", "setlocale",
        };
        for (const char* f : kDropOs) { lua_pushnil(L); lua_setfield(L, -2, f); }
    }
    lua_pop(L, 1);

    lua_getglobal(L, "package");
    if (lua_istable(L, -1)) {
        lua_pushnil(L); lua_setfield(L, -2, "loadlib");
        lua_pushstring(L, ""); lua_setfield(L, -2, "cpath");
        // searchers = { preload, lua-file }. Dropping searchers 3 and 4 (the
        // C-library loaders) is what makes an empty cpath un-bypassable.
        lua_getfield(L, -1, "searchers");
        if (lua_istable(L, -1)) {
            for (int i = static_cast<int>(lua_rawlen(L, -1)); i >= 3; --i) {
                lua_pushnil(L);
                lua_rawseti(L, -2, i);
            }
        }
        lua_pop(L, 1);
    }
    lua_pop(L, 1);
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
        { "emit",                    lua_emit_event },
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
        { "va_trusted",              lua_va_trusted },
        { "module_base",             lua_module_base },
        { "self_id",                 lua_self_id },
        { "now",                     lua_now },
        { "health_count",            lua_health_count },
        { "health_last_error",       lua_health_last_error },
        { "health_disable",          lua_health_disable },
        { "health_checkpoint",       lua_health_checkpoint },
        { "i18n_table",              lua_i18n_table },
        { "i18n_locale",             lua_i18n_locale },
        { "api_expose",              lua_api_expose },
        { "api_info",                lua_api_info },
        { "api_list",                lua_api_list },
        { "api_call",                lua_api_call },
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
        { "hook_report",             lua_hook_report },
        { "peek",                    lua_peek },
        { "poke",                    lua_poke },
        { "scratch",                 lua_scratch },
        { "shared_get",              lua_shared_get },
        { "shared_set",              lua_shared_set },
        { "register_item",           lua_register_item },
        { "item_guid",               lua_item_guid },
        { "is_grant_target",         lua_is_grant_target },
        { "mem_find",                lua_mem_find },
        { "steam_name",              lua_steam_name },
        { "write_u8",                lua_write_u8 },
        { "write_u16",               lua_write_u16 },
        { "write_u32",               lua_write_u32 },
        { "write_u64",               lua_write_u64 },
        { "write_f32",               lua_write_f32 },
        { "write_f64",               lua_write_f64 },
        { "state_read",              lua_state_read },
        { "state_write",             lua_state_write },
        { "intent_write",            lua_intent_write },
        { "config_get",              lua_config_get },
        { "config_set",              lua_config_set },
        { "config_all",              lua_config_all },
        { nullptr, nullptr }
    };
    luaL_newlib(L, public_lib);          // -1 = rsmm
    luaL_newlib(L, internal_lib);        // -2 = rsmm, -1 = _internal
    lua_setfield(L, -2, "_internal");
    lua_setglobal(L, "rsmm");
}

} // namespace

bool script_any_subscribers() {
    return g_handler_count.load(std::memory_order_relaxed) > 0;
}

// External-linkage accessors for the process-global shared slots (declared in
// script_lua.h). g_shared lives in the anonymous namespace above; these reach
// it within the same translation unit, giving native code (e.g. hero-capture)
// and the Lua bridge one store.
void shared_set(int slot, std::uint64_t value) {
    if (slot >= 0 && slot < 16) g_shared[slot].store(value);
}
std::uint64_t shared_get(int slot) {
    return (slot >= 0 && slot < 16) ? g_shared[slot].load() : 0;
}

bool script_run_mod_init(const std::string& mod_id,
                         const std::filesystem::path& mod_root) {
    const auto init_path = mod_root / "init.lua";
    if (!std::filesystem::exists(init_path)) return false;
    if (health::is_disabled(mod_id)) {
        Loader::get().log("[lua] " + mod_id + " skipped (disabled in "
                          "mods/_health.json)");
        return false;
    }
    // Stamp the canary before running mod code. If the game dies inside this
    // init.lua the next launch reads the step back and blames this mod by name
    // — the whole reason the canary exists.
    health::checkpoint("per_mod:" + mod_id);

    std::lock_guard<std::recursive_mutex> g(g_mu);
    lua_State* L = luaL_newstate();
    if (!L) return false;
    luaL_openlibs(L);

    apply_sandbox(L);

    lua_pushstring(L, mod_id.c_str());
    lua_setfield(L, LUA_REGISTRYINDEX, "__rsmm_mod_id");
    load_mod_config(L, mod_root);
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
    s.init_mtime = newest_lua_mtime(mod_root);

    if (luaL_dofile(L, init_path.string().c_str()) != LUA_OK) {
        Loader::get().log(std::string("[lua] ") + mod_id + " init failed: "
                          + lua_tostring(L, -1));
        lua_close(L);
        g_scripts.erase(mod_id);
        health::checkpoint("post_init:" + mod_id);
        return false;
    }
    Loader::get().log("[lua] " + mod_id + " init OK");
    health::checkpoint("post_init:" + mod_id);
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
    // Iterate over a SNAPSHOT of (id, state). The mutex is recursive, so a
    // handler that re-enters the loader (an engine call whose detour publishes
    // another event, a hot-reload) runs on this same thread while we hold the
    // lock — and anything that inserts into or erases from g_scripts would
    // invalidate the iterator mid-loop.
    std::vector<std::pair<std::string, lua_State*>> targets;
    targets.reserve(g_scripts.size());
    for (auto& [id, s] : g_scripts) {
        if (s.L) targets.emplace_back(id, s.L);
    }
    for (auto& [id, L] : targets) {
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
    // Poll every loaded mod's Lua sources; if any mtime has advanced, tear
    // down the lua_State and re-run init. The mod's own subscribers
    // (rsmm.on_event) live inside the registry table, so closing
    // lua_close drops them automatically — no stale callbacks remain.
    std::vector<std::pair<std::string, std::filesystem::path>> to_reload;
    {
        std::lock_guard<std::recursive_mutex> g(g_mu);
        for (auto& [id, s] : g_scripts) {
            const auto mt = newest_lua_mtime(s.root);
            if (mt == std::filesystem::file_time_type{}) continue;
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
        {
            // Retract its exposed APIs too: they point into the state we are
            // about to close, and init.lua re-exposes them on the way back up.
            std::lock_guard<std::recursive_mutex> g(g_mu);
            for (auto it = g_apis.begin(); it != g_apis.end(); ) {
                it = (it->second.mod_id == id) ? g_apis.erase(it) : std::next(it);
            }
        }
        // Tear down old state, build new one.
        {
            std::lock_guard<std::recursive_mutex> g(g_mu);
            auto it = g_scripts.find(id);
            if (it != g_scripts.end() && it->second.L) {
                g_handler_count.fetch_sub(it->second.handlers,
                                          std::memory_order_relaxed);
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
    g_handler_count.store(0, std::memory_order_relaxed);
    g_scripts.clear();
    g_apis.clear();   // the tables they name lived in the states just closed
}

} // namespace rsmm
