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

    char buf[768];
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
    } else if (std::strcmp(name, "POWER_UP_COLLECT_REQUEST") == 0) {
        // oCDtNamedEventPowerUpCollectRequest — fired when the player picks a
        // level-up / reward card; the payload carries the picked card's
        // identity. The exact offset is not yet *confirmed* (the class
        // registrar region is unanalysed in the corpus — the RTTI string xref
        // at 0x1402fdb6c is outside any defined function), but the GIVE sibling
        // (FUN_14030f430) fixes the shared oCGameNamedEvent template: the
        // object is 0x60 bytes and the def GUID payload sits at +0x50/+0x58.
        // The pick event's reward-def GUID is the prime suspect at the same
        // +0x50/+0x58. We still publish a small window to pin it in one in-game
        // session: +0x38 (covers a no-Network direct subclass whose payload
        // starts earlier) through +0x58. The read is bounded to +0x58 = the
        // GIVE template's last field; if the pick event omits the Network layer
        // it may be smaller, so the high window fields can read a few bytes of
        // adjacent (still-mapped) heap — benign garbage filtered by the pin
        // step, never an unmapped fault in practice. NOTE: this event fires for
        // EVERY power-up collect (level-up cards AND world orbs/globes), so the
        // identity GUID is what distinguishes a specific talent card. Once
        // pinned this collapses to one decoded "card" field. See
        // docs/_re/kinds/talents-pick.md.
        const auto* q = reinterpret_cast<const std::uint64_t*>(ev);
        // `card` = the tentative decoded identity (the +0x50/+0x58 GUID, the
        // GIVE-template payload slot). R.talent.on_pick("<lo>:<hi>", cb) matches
        // on it, so string-id pickable talents work today; the p38..p58 window
        // stays so the offset can be confirmed/corrected in one session.
        n += std::snprintf(buf + n, sizeof(buf) - n,
                           ",\"card\":\"0x%llx:0x%llx\","
                           "\"p38\":\"0x%llx\",\"p40\":\"0x%llx\","
                           "\"p48\":\"0x%llx\",\"p50\":\"0x%llx\",\"p58\":\"0x%llx\"",
                           static_cast<unsigned long long>(q[10]),
                           static_cast<unsigned long long>(q[11]),
                           static_cast<unsigned long long>(q[7]),
                           static_cast<unsigned long long>(q[8]),
                           static_cast<unsigned long long>(q[9]),
                           static_cast<unsigned long long>(q[10]),
                           static_cast<unsigned long long>(q[11]));
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
// The hero CHARACTER object (HP @ +0x15c8, max @ +0x15cc) is param_1 of three
// hero-bound routines. Capturing it lets R.entity / R.combat read & modify the
// local hero's health. Previously rsmm.lua armed these hooks per mod Lua state,
// which broke two ways: (1) a second mod hooking the same address got
// MH_ERROR_ALREADY_CREATED, (2) a Lua hot-reload re-armed over its own live
// hook (also ALREADY_CREATED) and the old state's callback died. Installing
// once here — at loader-thread time, never on reload — fixes both. The captured
// pointer is published to shared slot 0 (slot 1 = "authoritative seen"), which
// every Lua state reads via R.entity.hero().
//
// THREE capture sources, fastest-first:
//   1. HeroSubscribeAll (FUN_140391d30) — the hero's spawn/post-load init.
//      Verified in Ghidra: single-arg void(hero), writes the hero's own HP
//      fields ([hero+0x15c8]/[hero+0x15cc]) from the HUD mirror (hero+0x1d80)
//      then subscribes the hero to every named event. Runs ONCE at spawn,
//      BEFORE the hero ever acts — so it captures with ZERO latency and is
//      hero-only (enemies have no HUD mirror), i.e. authoritative. This is the
//      fix for the old "hero only captured after first heal/pickup" wart.
//   2. GiveHandler (FUN_1403a7ba0) — hero-only item grant; authoritative,
//      re-confirms across a hero switch when slot 1 was invalidated.
//   3. GainHealthHandler (FUN_1403993f0) — fires for ANY healing entity, so
//      tentative only (kept as a fallback for an older corpus where source 1
//      might not resolve).
constexpr int kHeroSlot = 0;     // hero character pointer
constexpr int kHeroAuthSlot = 1; // 1 once a hero-only routine has captured
constexpr std::uintptr_t kHeroMaxHpOff = 0x15cc;
constexpr std::uintptr_t kHeroHudMirrorOff = 0x1d80; // ptr to the HUD HP mirror

// True if [addr, addr+size) is committed and readable (no guard/no-access).
bool committed_readable(std::uintptr_t addr, std::size_t size) {
    MEMORY_BASIC_INFORMATION mbi{};
    if (VirtualQuery(reinterpret_cast<void*>(addr), &mbi, sizeof(mbi)) == 0) return false;
    if (mbi.State != MEM_COMMIT) return false;
    if (mbi.Protect & (PAGE_NOACCESS | PAGE_GUARD)) return false;
    auto region_end = reinterpret_cast<std::uintptr_t>(mbi.BaseAddress) + mbi.RegionSize;
    return addr + size <= region_end;
}

using SubscribeAll_t    = void (*)(void*);
using GiveHandler_t     = void (*)(void*, void*);
using GainHealthHandler_t = void (*)(void*, void*, void*);
SubscribeAll_t      g_subscribe_real = nullptr;
GiveHandler_t       g_give_real = nullptr;
GainHealthHandler_t g_gain_real = nullptr;
std::uintptr_t g_subscribe_va = 0, g_give_va = 0, g_gain_va = 0;

bool hero_plausible(void* p1) {
    if (!p1) return false;
    auto addr = reinterpret_cast<std::uintptr_t>(p1);
    if (addr & 7) return false;
    // (1) max-HP at +0x15cc reads as a sane float.
    if (!committed_readable(addr + kHeroMaxHpOff, sizeof(float))) return false;
    float mx = *reinterpret_cast<float*>(addr + kHeroMaxHpOff);
    if (!(mx > 0.0f && mx < 1.0e6f)) return false;
    // (2) the HUD HP-mirror pointer at +0x1d80 is a valid, readable pointer.
    // This is the hero discriminator: Entity_ModifyHealth dereferences
    // **(hero+0x1d80) unconditionally on any heal/damage, so a captured pointer
    // that lacks a live mirror here would crash R.combat. Non-player entities
    // (which Entity_GainHealthHandler also fires for) have no HUD mirror, so
    // requiring it both rejects false captures AND guarantees the captured
    // pointer is ModifyHealth-safe. Verified: FUN_140391d30 / FUN_140399a10.
    // CO-OP: only the LOCAL player owns the HUD HP mirror — remote allies render
    // but have no local HUD — so this requirement also pins capture to the local
    // hero, the one R.combat should target. (The engine's own local/remote test
    // is the authority flag on Entity_GetNetComponent(entity)+0x130; we don't
    // need it here because the mirror is a cheaper, read-only proxy.)
    if (!committed_readable(addr + kHeroHudMirrorOff, sizeof(void*))) return false;
    auto mirror = *reinterpret_cast<std::uintptr_t*>(addr + kHeroHudMirrorOff);
    if (mirror == 0 || (mirror & 7)) return false;
    // mirror is dereferenced as **(hero+0x1d80) and *(*(hero+0x1d80)+0x10).
    return committed_readable(mirror, 0x14);
}

void detour_subscribe_all(void* p1) {
    // Hero spawn/post-load init: param_1 is the hero HP-carrier, hero-only and
    // earliest possible. Authoritative capture with no wait for a hero action.
    if (hero_plausible(p1)) {
        shared_set(kHeroSlot, reinterpret_cast<std::uint64_t>(p1));
        shared_set(kHeroAuthSlot, 1);
    }
    g_subscribe_real(p1);
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
    // Pattern-resolve both handlers (same path as the gameplay bus) so the
    // hooks survive game patches instead of trusting a baked, soon-stale VA: a
    // stale address would land the detour mid-instruction and crash on load.
    if (!fn_resolver_init()) {
        Loader::get().log("[hero-capture] fn_resolver_init failed; disabled");
        return false;
    }
    g_give_va = fn_resolve(Sym::Entity_GiveHandler_Pattern);
    g_gain_va = fn_resolve(Sym::Entity_GainHealthHandler_Pattern);
    if (g_give_va == 0 || g_give_va == static_cast<std::uintptr_t>(-1)
        || g_gain_va == 0 || g_gain_va == static_cast<std::uintptr_t>(-1)) {
        Loader::get().log("[hero-capture] handler resolve failed; disabled");
        return false;
    }
    if (!fn_verify(Sym::Entity_GiveHandler_Pattern, g_give_va)
        || !fn_verify(Sym::Entity_GainHealthHandler_Pattern, g_gain_va)) {
        Loader::get().log("[hero-capture] handler verify mismatch (game patched?); "
                          "disabled to avoid a mid-instruction hook");
        return false;
    }
    bool any = false;
    bool instant = false;
    // Source 1 (best-effort, instant): the hero spawn/post-load init. Captures
    // the hero the moment it spawns, before it ever acts. If it can't resolve
    // (older corpus), the give/gain hooks below still provide capture-on-action.
    g_subscribe_va = fn_resolve(Sym::NamedEvent_HeroSubscribeAll_Pattern);
    if (g_subscribe_va != 0 && g_subscribe_va != static_cast<std::uintptr_t>(-1)
        && fn_verify(Sym::NamedEvent_HeroSubscribeAll_Pattern, g_subscribe_va)
        && MH_CreateHook(reinterpret_cast<LPVOID>(g_subscribe_va),
                         reinterpret_cast<LPVOID>(&detour_subscribe_all),
                         reinterpret_cast<LPVOID*>(&g_subscribe_real)) == MH_OK
        && MH_EnableHook(reinterpret_cast<LPVOID>(g_subscribe_va)) == MH_OK) {
        any = true;
        instant = true;
    } else {
        Loader::get().log("[hero-capture] subscribe-all (instant) hook unavailable; "
                          "falling back to capture-on-action");
    }
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
        Loader::get().log(instant
            ? "[hero-capture] armed (instant: hero published to shared slot 0 at "
              "spawn; R.entity/R.combat available to all mods)"
            : "[hero-capture] armed (hero published to shared slot 0 on first "
              "heal/pickup; R.entity/R.combat available to all mods)");
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
