#pragma once
// Safe Lua error stringification + traceback-carrying pcall.
//
// Two problems this exists to end, both of which shipped:
//
// 1. `std::string(...) + lua_tostring(L, -1)` is UB when the error object is
//    not a string or number — `lua_tostring` returns nullptr, and appending a
//    null `const char*` to a std::string is undefined. A mod raising
//    `error({code = 1})` (perfectly legal Lua, and the idiomatic way to throw
//    structured errors) therefore took the whole GAME down from inside the
//    loader's own error handler. Every raise site must go through
//    `lua_err_str`, which cannot return null.
//
// 2. Every `lua_pcall` in the loader ran with msgh = 0, so an error was one
//    line with no stack: "init.lua:12: attempt to index a nil value" and
//    nothing about who called it. `lua_pcall_traced` installs a message
//    handler that runs BEFORE the stack unwinds, so the log carries the whole
//    call chain — which is the difference between a mod author fixing their
//    bug and filing an issue.
//
// Both are deliberately raise-free: they run inside detours on the game's own
// thread, where a longjmp out of a C++ frame is a crash, not an exception.

#include <cstdio>
#include <string>

// The vendored Lua headers carry no `__cplusplus` / `extern "C"` guards of
// their own, so every includer has to supply the linkage. This header links
// today only because both current includers happened to pull Lua in inside
// their own `extern "C" { }` first, making these no-ops; the next TU that
// reaches lua_err.h FIRST would give every Lua symbol C++ linkage and fail at
// link. Guard here so the include order stops mattering.
extern "C" {
#include "lauxlib.h"
#include "lua.h"
}

namespace rsmm {

// Render the value at `idx` for a log line. NEVER returns an empty/garbage
// string and never raises.
//
// A table with a __tostring metamethod is rendered through it — but via a
// PROTECTED call, because a metamethod that itself raises would otherwise
// unwind straight out of the error path that was trying to report the first
// error. If it misbehaves we fall back to the type name.
inline std::string lua_err_str(lua_State* L, int idx = -1) {
    if (!L) return "<no lua state>";
    idx = lua_absindex(L, idx);
    const int t = lua_type(L, idx);
    if (t == LUA_TSTRING || t == LUA_TNUMBER) {
        // Safe to convert in place: `idx` is an error object on the stack, not
        // a table key mid-`lua_next`.
        std::size_t n = 0;
        if (const char* s = lua_tolstring(L, idx, &n)) return std::string(s, n);
        return "<unprintable error>";
    }
    if (t == LUA_TNIL || t == LUA_TNONE) return "<nil error object>";

    if (luaL_getmetafield(L, idx, "__tostring") != LUA_TNIL) {
        if (lua_isfunction(L, -1)) {
            lua_pushvalue(L, idx);
            if (lua_pcall(L, 1, 1, 0) == LUA_OK && lua_type(L, -1) == LUA_TSTRING) {
                std::size_t n = 0;
                const char* s = lua_tolstring(L, -1, &n);
                std::string out = s ? std::string(s, n) : std::string();
                lua_pop(L, 1);
                if (!out.empty()) return out;
                return "<empty __tostring>";
            }
        }
        lua_pop(L, 1);   // the metafield, or whatever the failed call left
    }

    char buf[96] = {0};
    std::snprintf(buf, sizeof(buf), "<non-string error object: %s at %p>",
                  lua_typename(L, t), lua_topointer(L, idx));
    return buf;
}

// Message handler for `lua_pcall_traced`. Runs on the still-live erroring
// stack, so the traceback names the frames that raised rather than the frame
// that caught.
inline int lua_err_traceback(lua_State* L) {
    const std::string msg = lua_err_str(L, 1);
    luaL_traceback(L, L, msg.c_str(), 1);
    return 1;
}

// `lua_pcall` with the traceback handler installed. Same stack contract as
// lua_pcall (function + nargs pushed, results or one error object left).
inline int lua_pcall_traced(lua_State* L, int nargs, int nresults) {
    const int fn_idx = lua_gettop(L) - nargs;      // the function being called
    lua_pushcfunction(L, &lua_err_traceback);
    lua_insert(L, fn_idx);                          // msgh must sit BELOW it
    const int rc = lua_pcall(L, nargs, nresults, fn_idx);
    lua_remove(L, fn_idx);
    return rc;
}

// Load and run a file with the same traceback handler. Replaces luaL_dofile,
// which pcalls with msgh = 0.
inline int lua_dofile_traced(lua_State* L, const char* path) {
    const int rc = luaL_loadfile(L, path);
    if (rc != LUA_OK) return rc;                    // syntax error: no stack yet
    return lua_pcall_traced(L, 0, LUA_MULTRET);
}

}  // namespace rsmm
