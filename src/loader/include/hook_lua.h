#pragma once
// Generic MinHook -> Lua callback bridge.
//
// Backs the Lua-side `rsmm.hook` / `rsmm.unhook` API. Implementation
// pre-bakes N detour slots (template-instantiated trampolines) so we
// can install up to N inline hooks on Ravenswatch.exe without JIT.
//
// Hook signature uses the same single-string format as rsmm.call:
//   first char = return type, remaining = arg types,
//   types: i u l p f d s v   (i32/u32/i64/ptr/float/double/cstr/void)
//
// Arity limit: 8 args. Integer / pointer args supported in this first
// release; floats are accepted by the sig parser but emit a warning
// (the trampoline always reads register slots as integers, which is
// correct for RCX/RDX/R8/R9 but wrong for XMM0-3).

#include <cstdint>
#include <string>
#include <string_view>

extern "C" {
#include "lua.h"
}

namespace rsmm {

// Initialize the global hook table. Idempotent. Returns false if MinHook
// is not initialized (caller is expected to have called MH_Initialize).
bool hook_lua_init();

// Tear down: disable + remove every hook this module installed. Called
// from dllmain DLL_PROCESS_DETACH.
void hook_lua_shutdown();

// Install a hook on `target_va` (already resolved). `L` is the mod's
// lua_State; `cb_ref` is a LUA_REGISTRYINDEX ref to the callback. `sig`
// follows the rsmm.call format (first char = return, rest = args).
// Returns a slot handle >= 0 on success, -1 on failure.
int hook_lua_install(std::uintptr_t target_va,
                     std::string_view sig,
                     lua_State* L,
                     int cb_ref,
                     std::string mod_id);

// Remove a previously installed hook. Idempotent.
bool hook_lua_uninstall(int slot);

// Number of slots currently in use, for diagnostics.
std::size_t hook_lua_active_count();

// Tear down all hooks registered by a specific mod (used on mod
// teardown / reload).
void hook_lua_unregister_mod(const std::string& mod_id);

} // namespace rsmm
