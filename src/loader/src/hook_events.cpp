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
#include "symbols.gen.h"        // GENERATED — Sym::NamedEvent_Dispatch_Pattern
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

// ---------------------------------------------------------------------------
// oCGameNamedEvent gameplay bus: one detour on NamedEvent_Dispatch
// (FUN_14066a700) exposes EVERY entity-context gameplay event — the bus the
// game itself uses for NETWORK_DAMAGE, GIVE_MAGICAL_OBJECT, GAIN_REROLL,
// REMOVE_*_OBJECT, CINE_START/STOP, ... (full map: docs/_re/kinds/events-bus.md).
//
// Unlike the analytics firehose these carry LIVE payloads: the dispatcher is
// the receiving entity's NamedEventDispatcher sub-object (entity + 0x4d8 for
// entity-scoped events; the world dispatcher sits at world + 0x340, so the
// derived `entity` field is only meaningful for entity-scoped events) and the
// event object itself carries its plaintext name at +0x20 and the interned id
// at +0x30, so the hook needs no per-event table and survives the game adding
// names. Payload fields are decoded for the events whose layout is verified
// (NETWORK_DAMAGE / NETWORK_DAMAGE_RESPONSE / GIVE_MAGICAL_OBJECT); raw
// pointers are published as hex strings (Lua doubles can't hold 64-bit ints).

// void NamedEvent_Dispatch(void* dispatcher, oCGameNamedEvent* ev)
using Dispatch_t = void (*)(void*, void*);
Dispatch_t     g_dispatch_real = nullptr;
std::uintptr_t g_dispatch_va   = 0;
unsigned       g_gameplay_seq  = 0;

// Copy the event's name (char* at ev+0x20) into `out`, accepting only the
// [A-Z0-9_] alphabet the bus uses. Returns false on a null/garbled name so a
// moved layout degrades to "skip this event", never to a wild read.
bool gameplay_event_name(const unsigned char* ev, char* out, size_t cap) {
    const char* name = *reinterpret_cast<const char* const*>(ev + 0x20);
    if (!name) return false;
    size_t i = 0;
    for (; i < cap - 1 && name[i]; ++i) {
        const char c = name[i];
        const bool ok = (c >= 'A' && c <= 'Z') || (c >= '0' && c <= '9') || c == '_';
        if (!ok) return false;
        out[i] = c;
    }
    out[i] = '\0';
    return i > 0 && name[i] == '\0';
}

void WINAPI gameplay_dispatch_detour(void* dispatcher, void* event) {
    // Forward first: subscribers run, the game applies the effect, and the
    // event object (caller-owned; dispatch consumes a clone) is still alive.
    g_dispatch_real(dispatcher, event);

    if (!event) return;
    const auto* ev = static_cast<const unsigned char*>(event);
    char name[64];
    if (!gameplay_event_name(ev, name, sizeof(name))) return;

    const auto id   = *reinterpret_cast<const std::uint32_t*>(ev + 0x30);
    const auto disp = reinterpret_cast<std::uintptr_t>(dispatcher);

    char buf[512];
    int n = std::snprintf(buf, sizeof(buf),
                          "{\"event\":\"gameplay:%s\",\"name\":\"%s\",\"seq\":%u,"
                          "\"id\":%u,\"source\":\"gameplay\","
                          "\"dispatcher\":\"0x%llx\",\"entity\":\"0x%llx\"",
                          name, name, ++g_gameplay_seq, id,
                          static_cast<unsigned long long>(disp),
                          static_cast<unsigned long long>(disp - 0x4d8));
    if (n < 0 || n >= static_cast<int>(sizeof(buf))) return;

    // Verified payload layouts only; everything else gets the envelope.
    if (std::strcmp(name, "GIVE_MAGICAL_OBJECT") == 0) {
        // oe::dt::NamedEventGiveMagicalObject (0x60): MO definition GUID.
        const auto lo = *reinterpret_cast<const std::uint64_t*>(ev + 0x50);
        const auto hi = *reinterpret_cast<const std::uint64_t*>(ev + 0x58);
        n += std::snprintf(buf + n, sizeof(buf) - n,
                           ",\"mo_guid_lo\":\"0x%llx\",\"mo_guid_hi\":\"0x%llx\"",
                           static_cast<unsigned long long>(lo),
                           static_cast<unsigned long long>(hi));
    } else if (std::strcmp(name, "NETWORK_DAMAGE") == 0
               || std::strcmp(name, "NETWORK_DAMAGE_RESPONSE") == 0) {
        // oCGameNamedEventNetworkDamage (0x110): f32 value @+0x40, source
        // net-id @+0x48, embedded oCEntityHitData @+0x50 with target entity*
        // @+0x60 and instigator entity* @+0xf0 (see events-bus.md).
        const auto value  = *reinterpret_cast<const float*>(ev + 0x40);
        const auto srcid  = *reinterpret_cast<const std::uint64_t*>(ev + 0x48);
        const auto target = *reinterpret_cast<const std::uint64_t*>(ev + 0x60);
        const auto instig = *reinterpret_cast<const std::uint64_t*>(ev + 0xf0);
        n += std::snprintf(buf + n, sizeof(buf) - n,
                           ",\"value\":%g,\"source_id\":\"0x%llx\","
                           "\"target_entity\":\"0x%llx\",\"instigator_entity\":\"0x%llx\"",
                           static_cast<double>(value),
                           static_cast<unsigned long long>(srcid),
                           static_cast<unsigned long long>(target),
                           static_cast<unsigned long long>(instig));
    }
    if (n < 0 || n >= static_cast<int>(sizeof(buf) - 2)) return;
    buf[n] = '}'; buf[n + 1] = '\0';

    const std::string lua_event = std::string("gameplay:") + name;
    script_emit_event_json(lua_event, buf);
}

bool install_gameplay_bus() {
    g_dispatch_va = fn_resolve(Sym::NamedEvent_Dispatch_Pattern);
    if (g_dispatch_va == 0 || g_dispatch_va == static_cast<std::uintptr_t>(-1)) {
        Loader::get().log("[gameplay-events] resolve NamedEvent_Dispatch failed");
        return false;
    }
    if (!fn_verify(Sym::NamedEvent_Dispatch_Pattern, g_dispatch_va)) {
        Loader::get().log("[gameplay-events] NamedEvent_Dispatch verify mismatch "
                          "(game patched?); gameplay bus disabled");
        return false;
    }
    if (MH_CreateHook(reinterpret_cast<LPVOID>(g_dispatch_va),
                      reinterpret_cast<LPVOID>(&gameplay_dispatch_detour),
                      reinterpret_cast<LPVOID*>(&g_dispatch_real)) != MH_OK
        || MH_EnableHook(reinterpret_cast<LPVOID>(g_dispatch_va)) != MH_OK) {
        Loader::get().log("[gameplay-events] NamedEvent_Dispatch hook failed");
        g_dispatch_va = 0;
        return false;
    }
    Loader::get().log("[gameplay-events] oCGameNamedEvent bus armed "
                      "(every gameplay event -> R.on('gameplay:<NAME>'))");
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

// --- hero capture (once, native) --------------------------------------------
//
// The hero CHARACTER object (HP @ +0x15c8, max @ +0x15cc) is param_1 of two
// hero-bound handlers. Capturing it lets R.entity / R.combat read & modify the
// local hero's health. Previously rsmm.lua armed these hooks per mod Lua state,
// which broke two ways: (1) a second mod hooking the same address got
// MH_ERROR_ALREADY_CREATED, (2) a Lua hot-reload re-armed over its own live
// hook (also ALREADY_CREATED) and the old state's callback died. Installing
// once here — at loader-thread time, never on reload — fixes both. The captured
// pointer is published to shared slot 0 (slot 1 = "authoritative seen"), which
// every Lua state reads via R.entity.hero().
constexpr int kHeroSlot = 0;     // hero character pointer
constexpr int kHeroAuthSlot = 1; // 1 once the hero-only give handler has fired
constexpr std::uintptr_t kHeroMaxHpOff = 0x15cc;

using GiveHandler_t     = void (*)(void*, void*);
using GainHealthHandler_t = void (*)(void*, void*, void*);
GiveHandler_t       g_give_real = nullptr;
GainHealthHandler_t g_gain_real = nullptr;
std::uintptr_t g_give_va = 0, g_gain_va = 0;

bool hero_plausible(void* p1) {
    if (!p1) return false;
    auto addr = reinterpret_cast<std::uintptr_t>(p1);
    if (addr & 7) return false;
    MEMORY_BASIC_INFORMATION mbi{};
    auto q = addr + kHeroMaxHpOff;
    if (VirtualQuery(reinterpret_cast<void*>(q), &mbi, sizeof(mbi)) == 0) return false;
    if (mbi.State != MEM_COMMIT) return false;
    if (mbi.Protect & (PAGE_NOACCESS | PAGE_GUARD)) return false;
    float mx = *reinterpret_cast<float*>(q);
    return mx > 0.0f && mx < 1.0e6f;
}

void detour_give(void* p1, void* p2) {
    if (hero_plausible(p1)) {
        shared_set(kHeroSlot, reinterpret_cast<std::uint64_t>(p1));
        shared_set(kHeroAuthSlot, 1);
    }
    g_give_real(p1, p2);
}

void detour_gain_health(void* p1, void* p2, void* p3) {
    // GAIN_HEALTH fires for any entity that heals (incl. enemies), so only take
    // it as a tentative capture until the hero-only give handler confirms.
    if (shared_get(kHeroAuthSlot) == 0 && hero_plausible(p1))
        shared_set(kHeroSlot, reinterpret_cast<std::uint64_t>(p1));
    g_gain_real(p1, p2, p3);
}

// va symbols (no byte pattern) — rebase the preferred-base address by the live
// image delta, same as the Lua side does via module_base.
std::uintptr_t rebase(std::uintptr_t preferred) {
    auto h = GetModuleHandleA("Ravenswatch.exe");
    if (!h) h = GetModuleHandleA(nullptr);
    if (!h) return 0;
    return reinterpret_cast<std::uintptr_t>(h) + (preferred - Sym::kPreferredBase);
}

} // namespace

bool install_hero_capture() {
    // OPT-IN while we stabilize: these are the newest engine detours and have
    // correlated with load-time crashes this dev cycle. Identity / event work
    // doesn't need them; R.combat / R.entity do. Enable with
    // RSMM_ENABLE_HERO_CAPTURE=1 once a run is confirmed stable.
    {
        char buf[8] = {};
        DWORD n = GetEnvironmentVariableA("RSMM_ENABLE_HERO_CAPTURE", buf, sizeof(buf));
        if (!(n > 0 && n < sizeof(buf) && (buf[0] == '1' || buf[0] == 't' || buf[0] == 'T'))) {
            Loader::get().log("[hero-capture] disabled (set RSMM_ENABLE_HERO_CAPTURE=1 "
                              "to enable R.combat/R.entity)");
            return false;
        }
    }
    g_give_va = rebase(Sym::Entity_GiveHandler);
    g_gain_va = rebase(Sym::Entity_GainHealthHandler);
    if (g_give_va == 0 || g_gain_va == 0) {
        Loader::get().log("[hero-capture] module base unavailable; disabled");
        return false;
    }
    bool any = false;
    if (MH_CreateHook(reinterpret_cast<LPVOID>(g_give_va),
                      reinterpret_cast<LPVOID>(&detour_give),
                      reinterpret_cast<LPVOID*>(&g_give_real)) == MH_OK
        && MH_EnableHook(reinterpret_cast<LPVOID>(g_give_va)) == MH_OK) {
        any = true;
    } else {
        Loader::get().log("[hero-capture] give-handler hook failed");
    }
    if (MH_CreateHook(reinterpret_cast<LPVOID>(g_gain_va),
                      reinterpret_cast<LPVOID>(&detour_gain_health),
                      reinterpret_cast<LPVOID*>(&g_gain_real)) == MH_OK
        && MH_EnableHook(reinterpret_cast<LPVOID>(g_gain_va)) == MH_OK) {
        any = true;
    } else {
        Loader::get().log("[hero-capture] gain-health-handler hook failed");
    }
    if (any) {
        // Sentinel: tells rsmm.lua native capture owns these handlers, so it
        // must NOT re-arm the per-state Lua capture hooks (which would collide
        // with these as MH_ERROR_ALREADY_CREATED).
        shared_set(2, 1);
        Loader::get().log("[hero-capture] armed (hero published to shared slot 0 on "
                          "first heal/pickup; R.entity/R.combat available to all mods)");
    }
    return any;
}

bool install_event_hooks() {
    const bool analytics = env_truthy("RSMM_ENABLE_GAME_EVENTS");
    const bool gameplay  = env_truthy("RSMM_ENABLE_GAMEPLAY_EVENTS");
    if (!analytics && !gameplay) {
        Loader::get().log("[game-events] disabled (RSMM_ENABLE_GAME_EVENTS=1 bridges "
                          "analytics events, RSMM_ENABLE_GAMEPLAY_EVENTS=1 bridges the "
                          "oCGameNamedEvent bus to rsmm.on_event)");
        return false;
    }
    if (!fn_resolver_init()) {
        Loader::get().log("[game-events] fn_resolver_init failed");
        return false;
    }
    bool any = false;
    if (analytics) {
        any |= arm<0>(g_hooks[0]);
        any |= arm<1>(g_hooks[1]);
        // One detour on the central telemetry sink republishes every named
        // analytics event to the Lua bus (see install_analytics_firehose).
        any |= install_analytics_firehose();
    }
    // One detour on the named-event dispatch republishes every entity-context
    // gameplay event (see install_gameplay_bus).
    if (gameplay) any |= install_gameplay_bus();
    return any;
}

void remove_event_hooks() {
    for (auto& h : g_hooks) {
        if (h.va) MH_DisableHook(reinterpret_cast<LPVOID>(h.va));
    }
    if (g_submit_va) MH_DisableHook(reinterpret_cast<LPVOID>(g_submit_va));
    if (g_dispatch_va) MH_DisableHook(reinterpret_cast<LPVOID>(g_dispatch_va));
}

} // namespace rsmm
