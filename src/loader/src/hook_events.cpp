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
#include "event_payload.gen.h"  // GENERATED — rsmm::event_payload()

#include "MinHook.h"

#include <windows.h>

#include <cstdint>
#include <cstdio>
#include <cstring>
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
    unsigned     seq = 0;     // per-event fire counter (published in payload)
};

// Verified by string-xref against the shipped exe (docs/_re/kinds/events.md):
// the function bodies reference the event name strings. The catalog is
// sourced from data/symbols.json (kind="event") — edit it there and run
// `rsmm symbols gen`, never hand-edit the generated table below.
EventHook g_hooks[] = {
#include "event_table.gen.h"
};

// One detour per slot — MinHook needs a distinct target function pointer, so
// we template on the slot index to mint a unique trampoline per entry.
template <int N>
std::uintptr_t WINAPI detour(void* ctx, void* arg) {
    EventHook& h = g_hooks[N];
    const auto rv = h.real(ctx, arg);
    // Build the payload AFTER the original runs (so fields it writes — e.g.
    // ctx+0xCC for level_up — are populated). Events with a verified schema
    // in data/symbols.json emit typed fields; the rest get the safe
    // envelope (seq + raw arg handles). Decode exprs read persistent
    // objects only; see event_payload.gen.h.
    char buf[256];
    event_payload(h.lua_event, buf, sizeof(buf), ++h.seq, ctx, arg);
    script_emit_event_json(h.lua_event, buf);
    return rv;
}

// ---------------------------------------------------------------------------
// Analytics "firehose": one detour on the central telemetry sink
// (Analytics_SubmitNamedEvent / FUN_1401fa470) re-publishes EVERY named
// analytics event to the Lua bus by its raw name. ~37 gameplay callers funnel
// through this sink (run_end, enemy_killed, matchmaking_start, level_up_reach,
// ...), so a single hook gives mods R.on("<name>", cb) for all of them and
// survives the game adding new event names — no per-event table entry needed.
//
// These are observation-grade: they fire after the gameplay action and carry
// analytics KV, not live entity handles. Good for triggers, not for mutating
// the actor (see the oCGameNamedEvent bus for that). The event name lives in
// arg3, a StringDesc { const char* ptr; uint32 len|0x80000000; ... }.

constexpr const char* kAnalyticsSink = "FUN_1401fa470";

// void(analytics_mgr, payload_kv, StringDesc* name, char has_run_ctx).
// arg4 is a char in R9B; we take/forward the full register width unchanged.
using Submit_t = std::uintptr_t (*)(void*, void*, void*, std::uintptr_t);
Submit_t       g_submit_real = nullptr;
std::uintptr_t g_submit_va   = 0;
unsigned       g_analytics_seq = 0;

std::uintptr_t WINAPI analytics_firehose_detour(void* mgr, void* payload,
                                                void* name_desc,
                                                std::uintptr_t flag) {
    // Forward first so the original populates state / sends the event.
    const auto rv = g_submit_real(mgr, payload, name_desc, flag);

    if (name_desc) {
        // arg3 -> { const char* ptr @+0x0; ... }. The name is a .rdata
        // literal; bound the copy defensively in case of a moved layout.
        const char* name = *reinterpret_cast<const char* const*>(name_desc);
        if (name) {
            char ev[64];
            size_t i = 0;
            for (; i < sizeof(ev) - 1 && name[i]; ++i) ev[i] = name[i];
            ev[i] = '\0';
            // "run_end" already fires via the typed Event_RunEnd table hook;
            // skip here to avoid publishing it twice.
            if (ev[0] && std::strcmp(ev, "run_end") != 0) {
                char buf[160];
                std::snprintf(buf, sizeof(buf),
                              "{\"event\":\"%s\",\"seq\":%u,\"source\":\"analytics\"}",
                              ev, ++g_analytics_seq);
                script_emit_event_json(ev, buf);
            }
        }
    }
    return rv;
}

bool install_analytics_firehose() {
    g_submit_va = fn_resolve(kAnalyticsSink);
    if (g_submit_va == 0 || g_submit_va == static_cast<std::uintptr_t>(-1)) {
        Loader::get().log("[game-events] resolve analytics sink failed");
        return false;
    }
    if (!fn_verify(kAnalyticsSink, g_submit_va)) {
        Loader::get().log("[game-events] analytics sink verify mismatch "
                          "(game patched?); firehose disabled");
        return false;
    }
    if (MH_CreateHook(reinterpret_cast<LPVOID>(g_submit_va),
                      reinterpret_cast<LPVOID>(&analytics_firehose_detour),
                      reinterpret_cast<LPVOID*>(&g_submit_real)) != MH_OK
        || MH_EnableHook(reinterpret_cast<LPVOID>(g_submit_va)) != MH_OK) {
        Loader::get().log("[game-events] analytics firehose hook failed");
        g_submit_va = 0;
        return false;
    }
    Loader::get().log("[game-events] analytics firehose armed "
                      "(every named event -> rsmm.on_event by raw name)");
    return true;
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
    // One detour on the central telemetry sink republishes every named
    // analytics event to the Lua bus (see install_analytics_firehose).
    any |= install_analytics_firehose();
    return any;
}

void remove_event_hooks() {
    for (auto& h : g_hooks) {
        if (h.va) MH_DisableHook(reinterpret_cast<LPVOID>(h.va));
    }
    if (g_submit_va) MH_DisableHook(reinterpret_cast<LPVOID>(g_submit_va));
}

} // namespace rsmm
