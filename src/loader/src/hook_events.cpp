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
#include "hook_util.h"
#include "script_lua.h"
#include "loader.h"
#include "mem_safe.h"
#include "symbols.gen.h"        // GENERATED — Sym::NamedEvent_Dispatch_Pattern
#include "event_payload.gen.h"  // GENERATED — rsmm::event_payload()
#include "event_fields.gen.h"   // GENERATED — vftable-keyed payload layouts

#include "MinHook.h"

#include <windows.h>

#include <chrono>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <string>
#include <utility>
#include <vector>

namespace rsmm {
namespace {

// True if [addr, addr+size) is committed and readable (no guard/no-access).
// Shared implementation (mem_safe.cpp): unlike this file's old local copy it
// also checks the readable-protection bits and spans multiple regions instead
// of failing a range that happens to straddle a region boundary.
inline bool committed_readable(std::uintptr_t addr, std::size_t size) {
    return mem_accessible(addr, size, false);
}

// Win x64: first two args in RCX/RDX. Emitters are `(ctx, arg*)`.
using Emitter_t = std::uintptr_t (*)(void*, void*);

struct EventHook {
    const char*  fn_name;     // symbol in function_patterns.json
    const char*  lua_event;   // event published to mods
    Emitter_t    real = nullptr;
    std::uintptr_t va = 0;
    // Per-event fire counter (published in the payload). Emitters can fire
    // from more than one game thread, so the counter is atomic — a torn
    // increment would hand mods a duplicate `seq`, which is exactly the
    // ordering signal they use to de-duplicate.
    std::atomic<unsigned> seq{0};
};

// The event name is interpolated into a JSON string literal and then becomes a
// Lua event key. Accept only the alphabet the game actually uses so a garbled
// read can neither break the JSON (embedded quote/backslash) nor register an
// unprintable event name.
bool json_safe_name(const char* s) {
    if (!s || !s[0]) return false;
    for (const char* p = s; *p; ++p) {
        const unsigned char c = static_cast<unsigned char>(*p);
        if (c < 0x20 || c > 0x7e) return false;
        if (c == '"' || c == '\\') return false;
    }
    return true;
}

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
    if (!script_any_subscribers()) return rv;
    // Build the payload AFTER the original runs (so fields it writes — e.g.
    // ctx+0xCC for level_up — are populated). Events with a verified schema
    // in data/symbols.json emit typed fields; the rest get the safe
    // envelope (seq + raw arg handles). Decode exprs read persistent
    // objects only; see event_payload.gen.h.
    char buf[256];
    event_payload(h.lua_event, buf, sizeof(buf),
                  h.seq.fetch_add(1, std::memory_order_relaxed) + 1, ctx, arg);
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

// Resolve the sink by SEMANTIC name. This was the literal "FUN_1401fa470" —
// the address that function had two builds ago. The name survives in the
// pattern DB as a legacy alias, so it still resolved and fn_verify still
// passed (the recorded bytes DO match) — but it matched at 0x1401fe6d0, which
// is 0x8d0 bytes INSIDE another function, because the routine was merged into
// a larger one. The firehose is armed by default on every install, so that
// detour was splicing a jump into the middle of a live body on every launch.
// The correct address was in data/symbols.json the whole time, as a status=ok
// symbol this file simply never referenced.
constexpr const char* kAnalyticsSink = Sym::Analytics_SubmitNamedEvent_Pattern;

// void(analytics_mgr, payload_kv, StringDesc* name, char has_run_ctx).
// arg4 is a char in R9B; we take/forward the full register width unchanged.
using Submit_t = std::uintptr_t (*)(void*, void*, void*, std::uintptr_t);
Submit_t       g_submit_real = nullptr;
std::uintptr_t g_submit_va   = 0;
std::atomic<unsigned> g_analytics_seq{0};

std::uintptr_t WINAPI analytics_firehose_detour(void* mgr, void* payload,
                                                void* name_desc,
                                                std::uintptr_t flag) {
    // Forward first so the original populates state / sends the event.
    const auto rv = g_submit_real(mgr, payload, name_desc, flag);

    if (name_desc && script_any_subscribers()) {
        // arg3 -> { const char* ptr @+0x0; ... }. Both the descriptor and the
        // string it points at are page-guarded: a moved layout after a game
        // patch would otherwise wild-read on every analytics event.
        std::uintptr_t name = 0;
        if (mem_load(name_desc, &name) && name) {
            char ev[64];
            const size_t n = mem_read_cstr(name, ev, sizeof(ev));
            // "run_end" already fires via the typed Event_RunEnd table hook;
            // skip here to avoid publishing it twice.
            if (n > 0 && json_safe_name(ev) && std::strcmp(ev, "run_end") != 0) {
                char buf[160];
                std::snprintf(buf, sizeof(buf),
                              "{\"event\":\"%s\",\"seq\":%u,\"source\":\"analytics\"}",
                              ev, g_analytics_seq.fetch_add(1) + 1);
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
    // fn_verify only proves the bytes match; .pdata proves it is an ENTRY
    // POINT. Both are needed — a pattern from an older build can match
    // mid-function after the routine is merged into a larger one, and
    // detouring there corrupts that function instead of intercepting a call.
    if (!fn_is_function_start(g_submit_va)) {
        Loader::get().log("[game-events] analytics sink resolves mid-function; "
                          "firehose disabled (refusing to splice a detour into "
                          "the middle of a live function)");
        return false;
    }
    if (!hook_install_at("game-events", "analytics sink", g_submit_va,
                         reinterpret_cast<void*>(&analytics_firehose_detour),
                         reinterpret_cast<void**>(&g_submit_real))) {
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
std::atomic<unsigned> g_gameplay_seq{0};
bool           g_probe_payloads = false;   // RSMM_EVENT_PROBE
// The mined payload layouts are keyed by vftable RVA, which is only valid for
// the build the symbol map was derived from — same gate as any other absolute
// address (Loader::va_globals_trusted).
bool           g_schemas_trusted = false;

std::uintptr_t image_base() {
    HMODULE h = GetModuleHandleA("Ravenswatch.exe");
    if (!h) h = GetModuleHandleA(nullptr);
    return reinterpret_cast<std::uintptr_t>(h);
}

// Copy the event's name (char* at ev+0x20) into `out`, accepting only the
// [A-Z0-9_] alphabet the bus uses. Returns false on a null/garbled name so a
// moved layout degrades to "skip this event", never to a wild read. Both the
// name slot and the string it points at are page-guarded: this runs on the
// game's main thread for EVERY dispatched gameplay event, so an offset the
// next patch invalidates must not be able to fault here.
bool gameplay_event_name(const unsigned char* ev, char* out, size_t cap) {
    std::uintptr_t name = 0;
    if (!mem_load(ev + 0x20, &name) || name == 0) return false;
    const size_t n = mem_read_cstr(name, out, cap);
    if (n == 0 || n >= cap - 1) return false;   // empty or truncated -> reject
    for (size_t i = 0; i < n; ++i) {
        const char c = out[i];
        const bool ok = (c >= 'A' && c <= 'Z') || (c >= '0' && c <= '9') || c == '_';
        if (!ok) return false;
    }
    return true;
}

// Append a formatted field to a JSON payload under construction.
//
// `std::snprintf` returns the length it WOULD have written, so the natural
// `n += snprintf(buf + n, sizeof(buf) - n, ...)` walks `n` PAST the end of the
// buffer on truncation — and then the next call's `sizeof(buf) - n` underflows
// to a huge size_t and writes out of bounds. Every payload decoder here used
// that shape. Formatting into a scratch buffer first also means a field is
// either written whole or not at all, so `buf` is always a valid JSON prefix
// and the closing brace can always be appended.
//
// Returns false when the field did not fit; the caller stops adding.
template <typename... A>
bool json_append(char* buf, int& n, int room, const char* fmt, A... args) {
    char tmp[192];
    const int add = std::snprintf(tmp, sizeof(tmp), fmt, args...);
    if (add <= 0 || add >= static_cast<int>(sizeof(tmp)) || add > room - n) return false;
    std::memcpy(buf + n, tmp, static_cast<std::size_t>(add));
    n += add;
    return true;
}

void WINAPI gameplay_dispatch_detour(void* dispatcher, void* event) {
    // Forward first: subscribers run, the game applies the effect, and the
    // event object (caller-owned; dispatch consumes a clone) is still alive.
    g_dispatch_real(dispatcher, event);

    if (!event) return;
    // This is the game's hottest bus — hundreds of dispatches a second in
    // combat. With nothing subscribed there is no reason to format a payload
    // and parse it back, so bail before doing any work.
    if (!script_any_subscribers()) return;
    const auto* ev = static_cast<const unsigned char*>(event);
    char name[64];
    if (!gameplay_event_name(ev, name, sizeof(name))) return;

    // Everything past the name is a page-guarded read: this detour sees every
    // dispatched gameplay event, so a layout change must degrade to a thinner
    // payload rather than fault the game's main thread.
    std::uint32_t id = 0;
    (void)mem_load(ev + 0x30, &id);
    const auto disp = reinterpret_cast<std::uintptr_t>(dispatcher);

    char buf[768];
    // Largest index a field may end at, leaving room for "}\0". Every append
    // below is bounded against this rather than against sizeof(buf), so the
    // closing brace can always be written and the event always reaches Lua.
    constexpr int kRoom = static_cast<int>(sizeof(buf)) - 2;
    // No `entity` field. It used to be published as `dispatcher - 0x4d8`, an
    // offset that was correct until the 2026-07-09 patch moved the dispatcher
    // sub-object — after which the value pointed into the middle of nothing.
    // The SDK had already measured it as unusable ("_hero_plausible(ev.entity)
    // fails"), so every consumer was reading a number that could not be
    // trusted and had no way to tell. Publishing nothing is strictly better
    // than publishing a knowingly-wrong pointer: a mod now gets nil, which is
    // detectable, instead of garbage, which is not. Mods that want the hero
    // use R.entity.hero(); the SDK derives the dispatcher offset at runtime
    // (see _learn_dispatcher_offset) rather than hardcoding it.
    int n = std::snprintf(buf, sizeof(buf),
                          "{\"event\":\"gameplay:%s\",\"name\":\"%s\",\"seq\":%u,"
                          "\"id\":%u,\"source\":\"gameplay\","
                          "\"dispatcher\":\"0x%llx\"",
                          name, name,
                          g_gameplay_seq.fetch_add(1, std::memory_order_relaxed) + 1, id,
                          static_cast<unsigned long long>(disp));
    if (n < 0 || n >= static_cast<int>(sizeof(buf))) return;

    // Hand-RE'd payload layouts first (their field names carry meaning the
    // mined table cannot). `decoded` stops the generic vftable decode below
    // from emitting the same offsets again under mechanical names.
    bool decoded = false;
    if (std::strcmp(name, "GIVE_MAGICAL_OBJECT") == 0
        && committed_readable(reinterpret_cast<std::uintptr_t>(ev + 0x50), 0x10)) {
        // oe::dt::NamedEventGiveMagicalObject (0x60): MO definition GUID.
        const auto lo = *reinterpret_cast<const std::uint64_t*>(ev + 0x50);
        const auto hi = *reinterpret_cast<const std::uint64_t*>(ev + 0x58);
        json_append(buf, n, kRoom,
                    ",\"mo_guid_lo\":\"0x%llx\",\"mo_guid_hi\":\"0x%llx\"",
                    static_cast<unsigned long long>(lo),
                    static_cast<unsigned long long>(hi));
        decoded = true;
    } else if ((std::strcmp(name, "NETWORK_DAMAGE") == 0
                || std::strcmp(name, "NETWORK_DAMAGE_RESPONSE") == 0)
               && committed_readable(reinterpret_cast<std::uintptr_t>(ev + 0x40), 0xb8)) {
        // oCGameNamedEventNetworkDamage (0x110): f32 value @+0x40, source
        // net-id @+0x48, embedded oCEntityHitData @+0x50 with target entity*
        // @+0x60 and instigator entity* @+0xf0 (see events-bus.md).
        const auto value  = *reinterpret_cast<const float*>(ev + 0x40);
        const auto srcid  = *reinterpret_cast<const std::uint64_t*>(ev + 0x48);
        const auto target = *reinterpret_cast<const std::uint64_t*>(ev + 0x60);
        const auto instig = *reinterpret_cast<const std::uint64_t*>(ev + 0xf0);
        json_append(buf, n, kRoom,
                    ",\"value\":%g,\"source_id\":\"0x%llx\","
                    "\"target_entity\":\"0x%llx\",\"instigator_entity\":\"0x%llx\"",
                    static_cast<double>(value),
                    static_cast<unsigned long long>(srcid),
                    static_cast<unsigned long long>(target),
                    static_cast<unsigned long long>(instig));
        decoded = true;
    } else if (std::strcmp(name, "POWER_UP_COLLECT_REQUEST") == 0
               && committed_readable(reinterpret_cast<std::uintptr_t>(ev + 0x38), 0x28)) {
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
        // adjacent heap — benign garbage filtered by the pin step. The whole
        // +0x38..+0x58 window is page-guarded above, so an event object that
        // really does end early degrades to the envelope instead of faulting.
        // NOTE: this event fires for
        // EVERY power-up collect (level-up cards AND world orbs/globes), so the
        // identity GUID is what distinguishes a specific talent card. Once
        // pinned this collapses to one decoded "card" field. See
        // docs/_re/kinds/talents-pick.md.
        const auto* q = reinterpret_cast<const std::uint64_t*>(ev);
        // `card` = the tentative decoded identity (the +0x50/+0x58 GUID, the
        // GIVE-template payload slot). R.talent.on_pick("<lo>:<hi>", cb) matches
        // on it, so string-id pickable talents work today; the p38..p58 window
        // stays so the offset can be confirmed/corrected in one session.
        json_append(buf, n, kRoom,
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
        decoded = true;
    }
    // Typed payload, keyed by the event object's OWN vftable. This is what
    // turns the ~24 payload-carrying event classes from an opaque envelope
    // into readable fields: read *(ev+0), rebase to an RVA, and look up the
    // layout mined from the binary (event_fields.gen.h). Matching on vftable
    // rather than event name makes the match exact — several names share one
    // class, and one class can be dispatched under names we never listed.
    //
    // Skipped when a decoder above already ran (its hand-RE'd names are the
    // better ones, and duplicate JSON keys would be ambiguous), and when the
    // build fingerprint says the RVAs are for a different game build.
    if (!decoded && g_schemas_trusted && n < static_cast<int>(sizeof(buf) - 2)) {
        std::uintptr_t vft = 0;
        const auto base = image_base();
        if (base && mem_load(ev, &vft) && vft > base) {
            const auto* schema = event_schema_for(
                static_cast<std::uint32_t>(vft - base));
            if (schema) {
                json_append(buf, n, kRoom, ",\"class\":\"%s\"", schema->cls);
                for (std::uint16_t i = 0; i < schema->count; ++i) {
                    const auto& f = schema->fields[i];
                    const auto at = reinterpret_cast<std::uintptr_t>(ev) + f.off;
                    char tmp[64];
                    int add = 0;
                    switch (f.type) {
                        case 'b': { std::uint8_t v;  if (!mem_load(at, &v)) continue;
                            add = std::snprintf(tmp, sizeof(tmp), ",\"%s\":%u", f.name, v); break; }
                        case 'w': { std::uint16_t v; if (!mem_load(at, &v)) continue;
                            add = std::snprintf(tmp, sizeof(tmp), ",\"%s\":%u", f.name, v); break; }
                        case 'u': { std::uint32_t v; if (!mem_load(at, &v)) continue;
                            add = std::snprintf(tmp, sizeof(tmp), ",\"%s\":%u", f.name, v); break; }
                        case 'q': { std::uint64_t v; if (!mem_load(at, &v)) continue;
                            // Pointers/ids as hex strings: a Lua number is a
                            // double and silently loses the low bits of a
                            // 64-bit handle.
                            add = std::snprintf(tmp, sizeof(tmp), ",\"%s\":\"0x%llx\"",
                                                f.name, (unsigned long long)v); break; }
                        case 'f': { float v; if (!mem_load(at, &v)) continue;
                            if (v != v) continue;          // NaN is not valid JSON
                            add = std::snprintf(tmp, sizeof(tmp), ",\"%s\":%g", f.name,
                                                static_cast<double>(v)); break; }
                        case 'd': { double v; if (!mem_load(at, &v)) continue;
                            if (v != v) continue;
                            add = std::snprintf(tmp, sizeof(tmp), ",\"%s\":%g", f.name, v); break; }
                        default: continue;
                    }
                    // Three ways this used to be wrong. `kRoom` keeps the two
                    // bytes the closing "}\0" needs. The subtraction is done in
                    // int, not size_t — `sizeof(buf) - n` is unsigned, so an n
                    // past the end would wrap to a huge value and turn the
                    // bound into a no-op. And `add` is snprintf's WOULD-HAVE
                    // written length, so a long field name truncates into `tmp`
                    // while `add` reports the untruncated size; without the
                    // sizeof(tmp) check the memcpy below reads past `tmp`.
                    if (add <= 0 || add >= static_cast<int>(sizeof(tmp))
                        || add > kRoom - n) break;
                    std::memcpy(buf + n, tmp, static_cast<std::size_t>(add));
                    n += add;
                }
            }
        }
    }

    // Generic probe (RSMM_EVENT_PROBE=1): for every event WITHOUT a decoded
    // layout above, publish a bounded window of the event object as hex
    // qwords. The payload of a new event is otherwise invisible from Lua, so
    // pinning one used to mean a C++ change + rebuild + relaunch per guess;
    // with this a mod reads ev.w38..ev.w70 and finds the field in one session.
    // Off by default (it triples payload size); every read is page-guarded, so
    // an event object that really is smaller degrades to fewer fields.
    if (g_probe_payloads && n < kRoom) {
        for (std::uintptr_t off = 0x38; off <= 0x70; off += 8) {
            std::uint64_t w = 0;
            if (!mem_load(reinterpret_cast<std::uintptr_t>(ev) + off, &w)) break;
            char tmp[48];
            const int add = std::snprintf(tmp, sizeof(tmp), ",\"w%llx\":\"0x%llx\"",
                                          static_cast<unsigned long long>(off),
                                          static_cast<unsigned long long>(w));
            // Same bound as the typed loop above. It used to allow n to reach
            // sizeof(buf)-1, leaving no room for the closing brace — and the
            // check below then DROPPED the whole event. Turning the probe on
            // therefore made big events vanish from Lua entirely, which is the
            // exact opposite of what a diagnostic should do. Writing into a
            // scratch buffer first also stops a truncated snprintf from
            // leaving a half-written field in `buf`.
            if (add <= 0 || add > kRoom - n) break;
            std::memcpy(buf + n, tmp, static_cast<std::size_t>(add));
            n += add;
        }
    }

    // Never drop an event for being long. Every append above is atomic and
    // leaves `buf` a valid JSON prefix, so the worst case is an event that
    // reaches Lua with fewer fields than it has — a mod that reads a missing
    // field gets nil, whereas a dropped event never fires its handler at all
    // and looks like the game not emitting it.
    if (n < 0) return;
    if (n > kRoom) n = kRoom;
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
    if (!fn_verify(Sym::NamedEvent_Dispatch_Pattern, g_dispatch_va)
        || !fn_is_function_start(g_dispatch_va)) {
        Loader::get().log("[gameplay-events] NamedEvent_Dispatch verify mismatch "
                          "or mid-function resolve (game patched?); "
                          "gameplay bus disabled");
        return false;
    }
    if (!hook_install_at("gameplay-events", "NamedEvent_Dispatch", g_dispatch_va,
                         reinterpret_cast<void*>(&gameplay_dispatch_detour),
                         reinterpret_cast<void**>(&g_dispatch_real))) {
        g_dispatch_va = 0;
        return false;
    }
    g_probe_payloads = flag_enabled("RSMM_EVENT_PROBE");
    g_schemas_trusted = Loader::get().va_globals_trusted();
    if (!g_schemas_trusted) {
        Loader::get().log("[gameplay-events] game build != symbol-map build; "
                          "typed payload decode disabled (events still fire "
                          "with the envelope)");
    }
    Loader::get().log(std::string("[gameplay-events] oCGameNamedEvent bus armed "
                      "(every gameplay event -> R.on('gameplay:<NAME>'))")
                      + (g_probe_payloads ? " [payload probe ON: ev.w38..ev.w70]" : ""));
    return true;
}

bool env_truthy(const char* name) {
    // Honour both the env var and the desktop-written flags file.
    return flag_enabled(name);
}

template <int N>
bool arm(EventHook& h) {
    static_assert(N >= 0, "slot index must be non-negative");
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
    if (!fn_is_function_start(h.va)) {
        Loader::get().log(std::string("[game-events] ") + h.fn_name
                          + " resolves mid-function; skipping " + h.lua_event);
        return false;
    }
    if (!hook_install_at("game-events", h.lua_event, h.va,
                         reinterpret_cast<void*>(&detour<N>),
                         reinterpret_cast<void**>(&h.real))) {
        return false;
    }
    return true;
}

// Arm EVERY row of the generated table. This used to read
//   any |= arm<0>(g_hooks[0]); any |= arm<1>(g_hooks[1]);
// which silently capped the table at two entries: `rsmm symbols gen` would
// happily emit a third `kind="event"` row into event_table.gen.h, the code
// would compile, and the hook would never be installed — a generated table
// whose size the consumer did not track. The fold over an index_sequence
// mints the per-slot detour<N> for the ACTUAL table length, so adding a
// symbol to data/symbols.json is now the only step.
template <std::size_t... Is>
bool arm_all(std::index_sequence<Is...>) {
    bool any = false;
    // Left-to-right, and every slot is attempted: `any |= arm(...)` inside a
    // fold keeps a failed resolve from short-circuiting the rest.
    ((any = arm<static_cast<int>(Is)>(g_hooks[Is]) || any), ...);
    return any;
}

constexpr std::size_t kEventHookCount = sizeof(g_hooks) / sizeof(g_hooks[0]);

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
constexpr int kHeroSlot = 0;        // hero character pointer (validated)
constexpr int kHeroAuthSlot = 1;    // 1 once a hero-only routine has captured
constexpr int kHeroPendingSlot = 3; // spawn-init candidate awaiting field init
                                    // (slot 2 = native-capture-active flag)
// Spawn-init fires several times per boot, and a SINGLE pending slot meant
// each call discarded the previous candidate. Measured 2026-08-14: five
// stashes, only the last survived, and that one's HP fields never went live —
// so the pending path was dead for the whole run and capture waited ~94s for a
// gain-health fire instead. The candidates are all hero-identity (the routine
// is hero-only), they just go live at different times, so keep them all and
// let whichever validates first win.
constexpr int kHeroRingFirst = 8;   // slots 8..15 (0..5 are taken)
constexpr int kHeroRingCount = 8;
// Whether hero capture is PERMITTED at all, which is a different question from
// whether the native path armed. Tri-state so an older loader (which never
// writes this slot, leaving 0) is not mistaken for a denial:
//   0 = unknown / loader too old   1 = permitted   2 = explicitly denied
//
// This exists because RSMM_ENABLE_HERO_CAPTURE was not actually a gate. It
// stopped the NATIVE hooks, then rsmm.lua's fallback installed detours on the
// same handlers anyway the first time any mod touched R.entity — visible in a
// playtest log as two `[hook] slot N installed` lines directly under
// "[hero-capture] disabled". The log's claim that R.combat/R.entity/R.stat/R.xp
// were unavailable was simply untrue, and the flag exists precisely because
// these detours have correlated with load-time crashes.
constexpr int kHeroCapturePermitSlot = 4;
constexpr std::uint64_t kPermitUnknown = 0, kPermitYes = 1, kPermitNo = 2;
constexpr std::uintptr_t kHeroHpOff = 0x15c8;
constexpr std::uintptr_t kHeroMaxHpOff = 0x15cc;
constexpr std::uintptr_t kHeroHudMirrorOff = 0x1d80; // ptr to the HUD HP mirror

using SubscribeAll_t    = void (*)(void*);
using GiveHandler_t     = void (*)(void*, void*, void*);
using GainHealthHandler_t = void (*)(void*, void*, void*);
SubscribeAll_t      g_subscribe_real = nullptr;
GiveHandler_t       g_give_real = nullptr;
GainHealthHandler_t g_gain_real = nullptr;
std::uintptr_t g_subscribe_va = 0, g_give_va = 0, g_gain_va = 0;

bool hero_plausible(void* p1) {
    if (!p1) return false;
    auto addr = reinterpret_cast<std::uintptr_t>(p1);
    if (addr & 7) return false;
    // (1) max-HP at +0x15cc AND current HP at +0x15c8 read as sane floats.
    // Both bounds matter: the 2026-07-19 session published 0x277b5360 as hero
    // off a give-handler misfire — its "max HP" was the DENORMAL 1.6e-43
    // (u32 bits ~114), which passes a bare `> 0` check, and its "HP" was
    // 7.6e+28, which this gate never looked at. The garbage slot then kept
    // clobbering the real promoted hero on every later give. `mx >= 0.5` cuts
    // off the entire denormal range; current HP may legitimately exceed max
    // (overheal / shields), so it is only bounded as finite-and-sane.
    if (!committed_readable(addr + kHeroHpOff, 2 * sizeof(float))) return false;
    float hp = *reinterpret_cast<float*>(addr + kHeroHpOff);
    float mx = *reinterpret_cast<float*>(addr + kHeroMaxHpOff);
    if (!(mx >= 0.5f && mx < 1.0e6f)) return false;
    if (!(hp >= 0.0f && hp < 1.0e6f)) return false;
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
    if (!committed_readable(mirror, 0x14)) return false;
    // The mirror's first float is the HUD-rendered HP — bound it like hp so a
    // random committed pointer (the misfire's 0x11ED68 was low but readable)
    // can't pass on readability alone.
    float mv = *reinterpret_cast<float*>(mirror);
    return mv >= 0.0f && mv < 1.0e6f;
}

// The moment hero capture armed, so every capture line can report how long the
// player actually waited. "Ages" is the whole complaint; a log that cannot
// measure it cannot settle it.
std::chrono::steady_clock::time_point g_capture_armed{};
std::atomic<bool> g_capture_reported{false};

double seconds_since_armed() {
    if (g_capture_armed.time_since_epoch().count() == 0) return -1.0;
    return std::chrono::duration<double>(
        std::chrono::steady_clock::now() - g_capture_armed).count();
}

// Log the FIRST successful publish, whatever produced it, exactly once and
// outside the per-detour log caps. Without this the fire that actually
// captured the hero was invisible: `gain fired` is capped at 8 lines and the
// early ones all fail, so a log could show nothing but rejections while
// capture had in fact succeeded seconds later.
void report_capture(const char* via, void* who) {
    if (g_capture_reported.exchange(true)) return;
    char line[192];
    std::snprintf(line, sizeof(line),
                  "[hero-capture] HERO PUBLISHED @%p via %s, %.1fs after arming",
                  who, via, seconds_since_armed());
    Loader::get().log(line);
}

// Record a spawn-init candidate in the ring without displacing the others.
// Duplicates are ignored so one hero re-announcing itself cannot evict the
// four others; the ring wraps only after eight DISTINCT candidates, which is
// more than a boot produces.
std::atomic<int> g_ring_next{0};

void stash_pending_candidate(void* p) {
    const auto v = reinterpret_cast<std::uint64_t>(p);
    if (v == 0) return;
    for (int i = 0; i < kHeroRingCount; ++i) {
        if (shared_get(kHeroRingFirst + i) == v) return;
    }
    const int idx = g_ring_next.fetch_add(1) % kHeroRingCount;
    shared_set(kHeroRingFirst + idx, v);
}

void detour_subscribe_all(void* p1) {
    // Hero spawn/post-load init (FUN_140391860): param_1 is the hero
    // HP-carrier, hero-only and earliest possible. The function itself
    // INITIALIZES the HUD mirror at hero+0x1d80 that hero_plausible checks —
    // so run the ORIGINAL first, then validate + publish. Capturing before the
    // original sees an uninitialized mirror and rejects the real hero.
    //
    // 2026-07-16 playtest: even post-body the HP/mirror fields may still be
    // unpopulated (they fill during the load sequence, seconds later). The
    // identity is authoritative regardless — this init only ever runs for the
    // local hero — so ALWAYS stash it in the pending slot; the Lua side
    // re-validates and promotes it once the fields go live, giving instant
    // capture without a single heuristic-y combat hook needing to fire.
    g_subscribe_real(p1);
    shared_set(kHeroPendingSlot, reinterpret_cast<std::uint64_t>(p1));
    stash_pending_candidate(p1);
    bool ok = hero_plausible(p1);
    // The POINTER matters: this fires several times per boot and the stashes
    // were previously indistinguishable, so a log could not show whether the
    // candidate that kept failing was one object retried or five different
    // ones overwriting each other in the single pending slot.
    char line[192];
    std::snprintf(line, sizeof(line),
                  ok ? "[hero-capture] hero captured at spawn (instant) @%p, %.1fs"
                     : "[hero-capture] spawn-init: stashed pending @%p, %.1fs "
                       "(fields not live yet; promoted on first valid read)",
                  p1, seconds_since_armed());
    Loader::get().log(line);
    if (ok) {
        shared_set(kHeroSlot, reinterpret_cast<std::uint64_t>(p1));
        shared_set(kHeroAuthSlot, 1);
        report_capture("spawn-init", p1);
    }
}

// First-fires diagnostic: the 2026-07-16 playtest saw ZERO captures across
// minutes of combat with both hooks verified-installed — so either the
// handlers never fire on this build, or every candidate fails hero_plausible.
// Log the first few calls of each detour (args + verdict) so a playtest log
// answers which. Cheap: fixed cap, no formatting after the cap.
std::atomic<int> g_give_logged{0}, g_gain_logged{0};
constexpr int kCaptureLogCap = 8;


void detour_give(void* p1, void* p2, void* p3) {
    // Entity_GiveHandler (FUN_1403c7560) is a 3-arg routine — param_3 is the hit
    // context and is dereferenced immediately (*(p3+0x10)/+0x18/+0xa0). The
    // trampoline MUST be called with all three args or the original runs with a
    // garbage R8 and faults reading ~-1 (the 2026-07-14 in-menu crash: the
    // detour + typedef were 2-arg after the handler was re-anchored to a 3-arg
    // function).
    //
    // Param semantics (decompile-verified 2026-07-15): param_1 is the hero's
    // VALUE CONTEXT (*(hero+0x2f8) — it reads its store at param_1+0x4c8), NOT
    // the hero entity; param_2 IS the hero entity (the function dispatches the
    // life-steal/shards-on-hit modifier event at param_2+0x4d8, the entity's
    // NamedEventDispatcher). So capture p2. hero_plausible (max-HP @+0x15cc +
    // HUD mirror @+0x1d80) rejects the ctx and any non-hero target outright, so
    // a mistaken arg can never be published. All three args pass straight
    // through to the trampoline.
    bool ok1 = hero_plausible(p1), ok2 = hero_plausible(p2);
    if (g_give_logged.fetch_add(1) < kCaptureLogCap) {
        char line[160];
        std::snprintf(line, sizeof(line),
                      "[hero-capture] give fired p1=%p(%d) p2=%p(%d)",
                      p1, (int)ok1, p2, (int)ok2);
        Loader::get().log(line);
    }
    if (ok2) {
        shared_set(kHeroSlot, reinterpret_cast<std::uint64_t>(p2));
        shared_set(kHeroAuthSlot, 1);
        report_capture("give-handler", p2);
    }
    g_give_real(p1, p2, p3);
}

void detour_gain_health(void* p1, void* p2, void* p3) {
    // GAIN_HEALTH fires for any entity that heals (incl. enemies), so only take
    // it as a tentative capture until the hero-only give handler confirms.
    bool ok1 = hero_plausible(p1);
    if (g_gain_logged.fetch_add(1) < kCaptureLogCap) {
        char line[160];
        std::snprintf(line, sizeof(line),
                      "[hero-capture] gain fired p1=%p(%d) p2=%p(%d)",
                      p1, (int)ok1, p2, (int)hero_plausible(p2));
        Loader::get().log(line);
    }
    if (shared_get(kHeroAuthSlot) == 0 && ok1) {
        shared_set(kHeroSlot, reinterpret_cast<std::uint64_t>(p1));
        report_capture("gain-health", p1);
    }
    g_gain_real(p1, p2, p3);
}

} // namespace

bool install_hero_capture() {
    // Start the clock here so every capture line reports the wait the player
    // actually experienced, measured from the moment capture became possible.
    g_capture_armed = std::chrono::steady_clock::now();
    // OPT-IN while we stabilize: these are the newest engine detours and have
    // correlated with load-time crashes this dev cycle. Identity / event work
    // doesn't need them; R.combat / R.entity do. Enable with
    // RSMM_ENABLE_HERO_CAPTURE=1 once a run is confirmed stable.
    // flag_enabled, NOT a raw getenv. Every other opt-in in the loader goes
    // through it, which honours both the environment variable AND the
    // rsmm_loader_flags.json the desktop app writes. This one read the
    // environment directly, so the desktop flags panel could not turn hero
    // capture on at all — the toggle appeared to do nothing and the only way
    // in was Steam launch options.
    const bool permitted = flag_enabled("RSMM_ENABLE_HERO_CAPTURE");
    // Publish the DECISION, not just the outcome, so the Lua fallback honours
    // the same answer instead of quietly arming what this refused.
    shared_set(kHeroCapturePermitSlot, permitted ? kPermitYes : kPermitNo);
    if (!permitted) {
        Loader::get().log("[hero-capture] disabled — R.combat/R.entity/R.stat/R.xp "
                          "unavailable. Enable it in the desktop app's flags "
                          "panel, or put RSMM_ENABLE_HERO_CAPTURE=1 BEFORE "
                          "%command% in the Steam launch options (anything "
                          "after %command% is passed to the game as an "
                          "argument, not as an environment variable).");
        return false;
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
    if (hook_install("hero-capture", "subscribe-all (instant capture)",
                     Sym::NamedEvent_HeroSubscribeAll_Pattern,
                     reinterpret_cast<void*>(&detour_subscribe_all),
                     reinterpret_cast<void**>(&g_subscribe_real),
                     &g_subscribe_va)) {
        any = true;
        instant = true;
    } else {
        Loader::get().log("[hero-capture] subscribe-all (instant) hook unavailable; "
                          "falling back to capture-on-action");
    }
    // give/gain were resolved + verified above; hook_install_at adds the
    // .pdata entry-point check the old inline sequence never made.
    any |= hook_install_at("hero-capture", "give handler", g_give_va,
                           reinterpret_cast<void*>(&detour_give),
                           reinterpret_cast<void**>(&g_give_real));
    any |= hook_install_at("hero-capture", "gain-health handler", g_gain_va,
                           reinterpret_cast<void*>(&detour_gain_health),
                           reinterpret_cast<void**>(&g_gain_real));
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
    // ON BY DEFAULT since both buses are in-game proven and they are what
    // makes the SDK worth using: without them R.on() only ever sees the three
    // lifecycle events, so every event-driven mod needed the user to hand-edit
    // Steam launch options first. Publishing is skipped entirely when no mod
    // has subscribed (script_any_subscribers), so an asset-only install pays
    // nothing for them being armed.
    const bool analytics = !env_truthy("RSMM_DISABLE_GAME_EVENTS");
    const bool gameplay  = !env_truthy("RSMM_DISABLE_GAMEPLAY_EVENTS");
    if (!analytics && !gameplay) {
        Loader::get().log("[game-events] both buses disabled by "
                          "RSMM_DISABLE_GAME_EVENTS / RSMM_DISABLE_GAMEPLAY_EVENTS");
        return false;
    }
    if (!fn_resolver_init()) {
        Loader::get().log("[game-events] fn_resolver_init failed");
        return false;
    }
    bool any = false;
    if (analytics) {
        any |= arm_all(std::make_index_sequence<kEventHookCount>{});
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
    // Disable AND remove: on a dynamic unload the detours live in this DLL's
    // .text, so leaving a merely-disabled hook registered keeps MinHook
    // holding a pointer into memory that is about to be unmapped.
    auto drop = [](std::uintptr_t va) { hook_remove(va); };
    for (auto& h : g_hooks) { drop(h.va); h.va = 0; h.real = nullptr; }
    drop(g_submit_va);   g_submit_va = 0;   g_submit_real = nullptr;
    drop(g_dispatch_va); g_dispatch_va = 0; g_dispatch_real = nullptr;
    drop(g_subscribe_va); g_subscribe_va = 0; g_subscribe_real = nullptr;
    drop(g_give_va);      g_give_va = 0;      g_give_real = nullptr;
    drop(g_gain_va);      g_gain_va = 0;      g_gain_real = nullptr;
}

} // namespace rsmm
