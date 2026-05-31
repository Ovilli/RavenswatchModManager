// Gameplay-event -> Lua event bridge. See hook_events.h for rationale.
//
// We detour each verified per-event emitter, forward the call unchanged
// (preserving the first two register args; MinHook keeps the original
// prologue so forwarding RCX/RDX is sufficient and we never touch the
// stack), then publish the corresponding Lua event. Targets are
// pattern-resolved + fn_verify'd so a future game patch degrades to a
// no-op instead of jumping into moved code.

#include "hook_events.h"
#include "fn_resolver.h"
#include "script_lua.h"
#include "loader.h"

#include "MinHook.h"

#include <windows.h>

#include <cstdint>
#include <string>
#include <vector>

namespace rsmm {
namespace {

// Win x64: first two args in RCX/RDX. Emitters are `(ctx, arg*)`.
using Emitter_t = std::uintptr_t (*)(void*, void*);

struct EventHook {
    const char*  fn_name;     // symbol in function_patterns.json
    const char*  lua_event;   // event published to mods
    Emitter_t    real = nullptr;
    std::uintptr_t va = 0;
};

// Verified by string-xref against the shipped exe (docs/_re/kinds/events.md):
// the function bodies reference the "level_up_reach" / "run_end" name strings.
EventHook g_hooks[] = {
    { "FUN_1401f6410", "level_up", nullptr, 0 },
    { "FUN_1401f51e0", "run_end",  nullptr, 0 },
};

// One detour per slot — MinHook needs a distinct target function pointer, so
// we template on the slot index to mint a unique trampoline per entry.
template <int N>
std::uintptr_t WINAPI detour(void* ctx, void* arg) {
    EventHook& h = g_hooks[N];
    const auto rv = h.real(ctx, arg);
    // Empty payload: safe regardless of the emitter's true signature.
    script_emit_event_json(h.lua_event, "{}");
    return rv;
}

bool env_truthy(const char* name) {
    char buf[8] = {};
    DWORD n = GetEnvironmentVariableA(name, buf, sizeof(buf));
    return n > 0 && n < sizeof(buf) && (buf[0] == '1' || buf[0] == 't' || buf[0] == 'T');
}

template <int N>
bool arm(EventHook& h) {
    h.va = fn_resolve(h.fn_name);
    if (h.va == 0 || h.va == static_cast<std::uintptr_t>(-1)) {
        Loader::get().log(std::string("[game-events] resolve ") + h.fn_name + " failed");
        return false;
    }
    if (!fn_verify(h.fn_name, h.va)) {
        Loader::get().log(std::string("[game-events] verify ") + h.fn_name
                          + " mismatch (game patched?); skipping " + h.lua_event);
        return false;
    }
    if (MH_CreateHook(reinterpret_cast<LPVOID>(h.va),
                      reinterpret_cast<LPVOID>(&detour<N>),
                      reinterpret_cast<LPVOID*>(&h.real)) != MH_OK) {
        Loader::get().log(std::string("[game-events] MH_CreateHook ") + h.fn_name + " failed");
        return false;
    }
    if (MH_EnableHook(reinterpret_cast<LPVOID>(h.va)) != MH_OK) {
        Loader::get().log(std::string("[game-events] MH_EnableHook ") + h.fn_name + " failed");
        return false;
    }
    Loader::get().log(std::string("[game-events] '") + h.lua_event + "' -> "
                      + h.fn_name + " hooked");
    return true;
}

} // namespace

bool install_event_hooks() {
    if (!env_truthy("RSMM_ENABLE_GAME_EVENTS")) {
        Loader::get().log("[game-events] disabled (set RSMM_ENABLE_GAME_EVENTS=1 to "
                          "bridge level_up/run_end to rsmm.on_event)");
        return false;
    }
    if (!fn_resolver_init()) {
        Loader::get().log("[game-events] fn_resolver_init failed");
        return false;
    }
    bool any = false;
    any |= arm<0>(g_hooks[0]);
    any |= arm<1>(g_hooks[1]);
    return any;
}

void remove_event_hooks() {
    for (auto& h : g_hooks) {
        if (h.va) MH_DisableHook(reinterpret_cast<LPVOID>(h.va));
    }
}

} // namespace rsmm
