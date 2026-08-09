// Custom magical-object pool injection — see hook_items.h.
//
// Post-detours FUN_140258760 (SpawnAllObjects) after the engine spawns
// its items from the master linked list, then injects Lua-registered
// custom items into the pool's runtime array at DAT_1414365d0 + 0x10 so
// they appear in hero-item selection.
//
// Entity resource pointers are resolved at spawn time via the game's own
// resource-by-path lookup (FUN_140487040), which is pattern-resolved
// and thus survives minor game patches.

#include "hook_items.h"
#include "fn_resolver.h"
#include "loader.h"
#include "mem_safe.h"
#include "symbols.gen.h"      // GENERATED — addresses (Sym::)
#include "symbols_api.gen.h"  // GENERATED — typed accessors (engine::)

#include "MinHook.h"

#include <windows.h>

#include <chrono>
#include <cstdint>
#include <cstdio>
#include <mutex>
#include <string>
#include <thread>
#include <vector>

namespace rsmm {
namespace {

// --- layout constants (preferred-base 0x140000000) -----------------------
// Addresses come from the canonical symbol map (data/symbols.json) via the
// generated Sym:: namespace; edit names there, not magic numbers here.
constexpr std::uintptr_t kPreferredBase = Sym::kPreferredBase;

// Pool global pointer address (Sym::g_MagicalObjectPool / DAT_1414365d0).
constexpr std::uintptr_t kPoolPtrGlobalVA = Sym::g_MagicalObjectPool;

// Pool offsets (relative to the pointer at DAT_1414365d0).
// +0x00 void* master_linked_list  — linked list of nodes the engine spawns
// +0x10 void** runtime_array      — array of EntityResource* (hero selection)
// +0x18 uint32_t runtime_count
// +0x1c uint32_t runtime_cap
constexpr std::size_t kOffRuntimeArray = 0x10;
constexpr std::size_t kOffRuntimeCount = 0x18;
constexpr std::size_t kOffRuntimeCap   = 0x1c;

// SpawnAllObjects used to be recorded as an INTERNAL entry point at +0x70
// inside a larger merged function, and this file asserted that arithmetic.
// That model is gone: in the shipped build the routine is its own function,
// called from the boot orchestrator as SpawnAllObjects(g_MagicalObjectPool,
// scene) — which is exactly the declared void(void*, void*). The anchor was
// also the bug: when the parent was remapped without re-deriving the offset,
// parent+0x70 landed 2 bytes inside a 5-byte call, so a detour there would
// have spliced mid-instruction. Resolve Sym::MagicalObject_SpawnAllObjects
// directly (see install_item_hooks); no offset math, nothing to drift.

// --- game function type aliases -----------------------------------------
// Sourced from the generated typed accessors (engine::), themselves derived
// from data/symbols.json cabi entries — single source of truth for the ABI.

using ResourceLookup_t  = engine::Resource_LookupByPath_fn;          // FUN_140487040
using VecGrow_t         = engine::Vector_Grow_fn;                    // FUN_140154c20
using SpawnAllObjects_t = engine::MagicalObject_SpawnAllObjects_fn;  // FUN_140258760

// --- resolved function pointers -----------------------------------------

SpawnAllObjects_t g_real_spawn_all = nullptr;
ResourceLookup_t  g_resource_lookup = nullptr;
VecGrow_t         g_vec_grow = nullptr;

// --- registered custom items (populated via Lua FFI) ---------------------

struct ItemReg {
    std::string id;
    std::string name;
    std::string description;
    std::string base_id;       // vanilla item id to clone
    std::string entity_path;   // decoded path for FUN_140487040 lookup
    int         rarity = 0;    // 0=Common, 1=Rare, etc.
};

std::vector<ItemReg> g_items;
std::mutex g_items_mu;

// --- helpers -------------------------------------------------------------

std::uintptr_t image_base() {
    HMODULE h = GetModuleHandleA("Ravenswatch.exe");
    if (!h) h = GetModuleHandleA(nullptr);
    return reinterpret_cast<std::uintptr_t>(h);
}

std::uintptr_t reloc(std::uintptr_t static_va) {
    return static_va - kPreferredBase + image_base();
}

std::string hex_of(std::uintptr_t v) {
    char b[32];
    snprintf(b, sizeof(b), "0x%llx", static_cast<unsigned long long>(v));
    return b;
}

std::string hex_ptr(const void* p) {
    return hex_of(reinterpret_cast<std::uintptr_t>(p));
}
// --- item registration (called from script_lua.cpp) ---------------------

bool register_item_locked(const ItemReg& item) {
    std::lock_guard<std::mutex> g(g_items_mu);
    for (const auto& existing : g_items) {
        if (existing.id == item.id) return false;
    }
    g_items.push_back(item);
    return true;
}

// Tries to find an entity resource by decoded path using the game's
// resource lookup. Returns the EntityResource* or nullptr.
void* find_entity_resource(const std::string& decoded_path) {
    if (!g_resource_lookup) {
        Loader::get().log("[item-hook] resource lookup unavailable");
        return nullptr;
    }

    // Try forward-slash path first (SDK convention).
    void* rsc = g_resource_lookup(decoded_path.c_str(), nullptr, nullptr, nullptr);

    // Try backslash variant (game convention on Windows).
    if (!rsc) {
        std::string bs = decoded_path;
        for (auto& ch : bs) { if (ch == '/') ch = '\\'; }
        rsc = g_resource_lookup(bs.c_str(), nullptr, nullptr, nullptr);
    }

    return rsc;
}

void inject_custom_items(void* pool) {
    if (!pool) {
        Loader::get().log("[item-hook] inject: null pool");
        return;
    }
    std::lock_guard<std::mutex> g(g_items_mu);
    if (g_items.empty()) {
        Loader::get().log("[item-hook] inject: no items to inject");
        return;
    }

    if (!g_resource_lookup || !g_vec_grow) {
        Loader::get().log("[item-hook] inject: resource_lookup or vec_grow unavailable");
        return;
    }

    const auto u8 = static_cast<std::uint8_t*>(pool);
    auto* array_ptr = reinterpret_cast<void***>(u8 + kOffRuntimeArray);
    auto* count_ptr = reinterpret_cast<std::uint32_t*>(u8 + kOffRuntimeCount);
    auto* cap_ptr   = reinterpret_cast<std::uint32_t*>(u8 + kOffRuntimeCap);

    Loader::get().log("[item-hook] inject: pool count=" + std::to_string(*count_ptr)
                      + " cap=" + std::to_string(*cap_ptr)
                      + " items=" + std::to_string(g_items.size()));

    for (const auto& item : g_items) {
        void* rsc = find_entity_resource(item.entity_path);
        if (!rsc) {
            Loader::get().log("[item-hook] resource not loaded: "
                              + item.id + " @ " + item.entity_path);
            continue;
        }

        // Dedup against current runtime array contents.
        bool already = false;
        for (std::uint32_t i = 0; i < *count_ptr; i++) {
            if ((*array_ptr)[i] == rsc) {
                already = true;
                break;
            }
        }
        if (already) {
            Loader::get().log("[item-hook] already in pool: " + item.id);
            continue;
        }

        const std::uint32_t need = *count_ptr + 1;
        Loader::get().log("[item-hook] growing pool from " + std::to_string(*cap_ptr)
                          + " to at least " + std::to_string(need));
        if (*cap_ptr < need) {
            std::uint32_t ncap = (*cap_ptr > 8) ? *cap_ptr : 8;
            while (ncap < need) ncap *= 2;
            g_vec_grow(u8 + kOffRuntimeArray, 0, ncap);
            // vec_grow may have reallocated; refresh pointers.
            array_ptr = reinterpret_cast<void***>(u8 + kOffRuntimeArray);
            cap_ptr   = reinterpret_cast<std::uint32_t*>(u8 + kOffRuntimeCap);
        }

        (*array_ptr)[*count_ptr] = rsc;
        *count_ptr = need;

        Loader::get().log("[item-hook] injected: " + item.id
                          + " rsc=" + hex_ptr(rsc)
                          + " pool_count=" + std::to_string(*count_ptr));
    }
}

// --- read-only pool diagnostic -------------------------------------------

// Dumps the SOURCE/master list the engine spawns from (pool+0x0, count at
// pool+0x8) plus the spawned runtime array (pool+0x10, count +0x18). Each
// source entry: +0x00 is the entry id/uid qword the spawner dedups on,
// +0x48 is the EntitySettingsResource* it spawns from. This tells us whether
// our custom magical-object DEFINITION actually loaded into the source list
// (if so, the boot SpawnAllObjects already spawns it for free and no loader
// injection is needed — the bug would be elsewhere). Read-only: never writes,
// never calls game code, so it can't crash the spawn pipeline.
void dump_pool(void* pool) {
    const auto u8 = static_cast<std::uint8_t*>(pool);
    void**  src_arr   = *reinterpret_cast<void***>(u8 + 0x0);
    auto    src_count = *reinterpret_cast<std::uint32_t*>(u8 + 0x8);
    auto    run_count = *reinterpret_cast<std::uint32_t*>(u8 + kOffRuntimeCount);
    Loader::get().log("[pool-dump] source_count=" + std::to_string(src_count)
                      + " runtime_count=" + std::to_string(run_count)
                      + " src_arr=" + hex_ptr(src_arr));
    if (!src_arr) return;
    for (std::uint32_t i = 0; i < src_count && i < 512; ++i) {
        auto* entry = static_cast<std::uint8_t*>(src_arr[i]);
        if (!entry) continue;
        const auto id  = *reinterpret_cast<std::uint64_t*>(entry + 0x0);
        const auto rsc = *reinterpret_cast<void**>(entry + 0x48);
        // Identity GUID at def+0x88/+0x90 — the value MagicalObjectPool_SourceLookup
        // matches AND the owned-set dedups on (MagicalObject_RegisterInstance).
        // Logged so a custom clone's identity can be mapped to its base and
        // surgically re-minted (clones that share a base's identity get deduped
        // out at grant time — see magic_item_cook.py). Read-only.
        const auto guid_lo = *reinterpret_cast<std::uint64_t*>(entry + 0x88);
        const auto guid_hi = *reinterpret_cast<std::uint64_t*>(entry + 0x90);
        Loader::get().log("[pool-dump]   [" + std::to_string(i) + "] entry="
                          + hex_ptr(entry) + " id=" + hex_of(id)
                          + " rsc=" + hex_ptr(rsc)
                          + " guid=" + hex_of(guid_lo) + ":" + hex_of(guid_hi));
    }
}

// --- deferred inject (covers the missed boot-time spawn) ------------------

// SpawnAllObjects(DAT_1414365d0, ...) runs ONCE during InitialLoading
// (confirmed: FUN_140260280 "InitialLoading - MagicalObject SpawnAllObjects").
// Our loader runs in a background thread that usually arms the detour just
// after that single call, so the detour never fires. This poller reads the
// pool global directly and injects once the engine has populated it
// (count>0 ⇒ the boot spawn finished AND the resource system is up — so the
// resource lookup won't crash, unlike an inject-at-install on an empty pool).
//
// Reads are gated: the pool global is a zero-init static, so it's null until
// the manager exists; we never dereference the pool until it reports a
// non-zero element count. (MinGW has no __try/__except, hence the gating.)
//
// Non-null is NOT proof of a live pool: if kPoolPtrGlobalVA is stale (a game
// patch moved .data — exactly what the 2026-07-09 update did) the slot holds
// unrelated bytes, and dereferencing them access-violates on a background
// thread, killing the whole game seconds-to-minutes after boot (CrashDB dumps
// 2026-07-10). Only dereference pointers that VirtualQuery says are readable.
static bool readable(const void* p, std::size_t len) { return mem_readable(p, len); }

// The MO-pool inject calls the resource-by-path lookup FUN_140487040, which
// mis-resolves on the shipped build and crashes the game (CrashDB 2026-07-10).
// Custom items already load via UsedRscList, so inject is a redundant fallback
// and MUST NOT be armable by the ordinary loader-flag path. Require BOTH the
// enable var AND an explicit "I accept it's broken" acknowledgement, so a
// user who flips the normal flag can never trip the crash. Development-only.
static bool item_inject_armed() {
    char e[8], a[8];
    const bool enabled = GetEnvironmentVariableA(
        "RSMM_ENABLE_ITEM_INJECT", e, sizeof(e)) && e[0] == '1';
    if (!enabled) {
        Loader::get().log("[item-hook] inject gated off "
                          "(items load via UsedRscList; inject is a broken fallback)");
        return false;
    }
    const bool acknowledged = GetEnvironmentVariableA(
        "RSMM_I_ACCEPT_ITEM_INJECT_IS_BROKEN", a, sizeof(a)) && a[0] == '1';
    if (!acknowledged) {
        Loader::get().log("[item-hook] RSMM_ENABLE_ITEM_INJECT set but refused: "
                          "inject mis-resolves and crashes on this build. Also set "
                          "RSMM_I_ACCEPT_ITEM_INJECT_IS_BROKEN=1 (dev only) to force.");
        return false;
    }
    Loader::get().log("[item-hook] WARNING: forcing known-broken item inject "
                      "(RSMM_I_ACCEPT_ITEM_INJECT_IS_BROKEN=1)");
    return true;
}

void deferred_inject_poll() {
    bool warned_unreadable = false;
    for (int i = 0; i < 600; ++i) {  // ~150 s @ 250 ms, then give up
        // Even the pool GLOBAL is read through the guard: on a mismatched
        // build the rebased RVA can land outside the image's committed pages.
        std::uintptr_t pool_addr = 0;
        (void)mem_load(reloc(kPoolPtrGlobalVA), &pool_addr);
        void* pool = reinterpret_cast<void*>(pool_addr);
        if (pool && !readable(pool, kOffRuntimeCount + sizeof(std::uint32_t))) {
            if (!warned_unreadable) {
                warned_unreadable = true;
                Loader::get().log("[item-hook] pool global holds an unreadable "
                                  "pointer — g_MagicalObjectPool VA is likely "
                                  "stale for this game build; inject disabled");
            }
            pool = nullptr;
        }
        if (pool) {
            const auto count = *reinterpret_cast<std::uint32_t*>(
                static_cast<std::uint8_t*>(pool) + kOffRuntimeCount);
            // Sane pool sizes are a few hundred; an absurd count means we are
            // reading through a stale global into garbage — don't touch it.
            if (count > 0 && count < 100000) {
                Loader::get().log("[item-hook] deferred inject: pool populated (count="
                                  + std::to_string(count) + ")");
                // Read-only source-list dump (opt-in) to learn whether our
                // custom definition loaded into the spawn source list.
                {
                    char dbuf[8];
                    if (GetEnvironmentVariableA("RSMM_DUMP_POOL", dbuf, sizeof(dbuf))
                            && dbuf[0] == '1') {
                        dump_pool(pool);
                    }
                }
                // Inject only when double-opted in (known-broken; see
                // item_inject_armed). Custom items already load via UsedRscList.
                if (item_inject_armed()) {
                    inject_custom_items(pool);
                }
                return;
            }
        }
        std::this_thread::sleep_for(std::chrono::milliseconds(250));
    }
    Loader::get().log("[item-hook] deferred inject: timed out waiting for pool");
}

// --- detour ---------------------------------------------------------------

void WINAPI hook_spawn_all_objects(void* pool, void* spawn_ctx) {
    Loader::get().log(std::string("[item-hook] SpawnAllObjects fired pool=")
                      + hex_ptr(pool) + " spawn_ctx=" + hex_ptr(spawn_ctx));
    g_real_spawn_all(pool, spawn_ctx);
    Loader::get().log("[item-hook] SpawnAllObjects returned OK");
    // Inject is opt-in (same gate as deferred_inject_poll): it calls the
    // resource-by-path lookup FUN_140487040, which mis-resolves on this build and
    // crashes. Custom items already load via UsedRscList, so the inject is a
    // redundant fallback — never run it ungated. (Was an ungated crash here when
    // the detour fired on the primary thread with g_resource_lookup resolved.)
    if (item_inject_armed()) {
        inject_custom_items(pool);
    }
}

// --- resolution helpers ---------------------------------------------------

bool resolve(const char* name, void** out) {
    const auto va = fn_resolve(name);
    if (va == 0 || va == static_cast<std::uintptr_t>(-1)) {
        Loader::get().log(std::string("[item-hook] resolve ") + name + " failed");
        return false;
    }
    if (!fn_verify(name, va)) {
        Loader::get().log(std::string("[item-hook] verify ") + name
                          + " @ " + hex_of(va) + " mismatch (game patched?)");
        return false;
    }
    *out = reinterpret_cast<void*>(va);
    Loader::get().log(std::string("[item-hook] ") + name + " -> " + hex_of(va));
    return true;
}

} // anonymous namespace

// --- public API ----------------------------------------------------------

bool register_native_item(const char* id_str,
                          const char* name_str,
                          const char* desc_str,
                          const char* base_str,
                          const char* entity_str,
                          int rarity) {
    ItemReg item;
    if (id_str)       item.id          = id_str;
    if (name_str)     item.name        = name_str;
    if (desc_str)     item.description = desc_str;
    if (base_str)     item.base_id     = base_str;
    if (entity_str)   item.entity_path = entity_str;
    item.rarity  = rarity;
    return register_item_locked(item);
}

bool resolve_item_guid(const char* id_str, unsigned long long* lo,
                       unsigned long long* hi) {
    if (!id_str) return false;
    // Copy out the registered item's path under the lock; don't hold it while
    // touching game memory.
    std::string entity_path;
    {
        std::lock_guard<std::mutex> g(g_items_mu);
        for (const auto& it : g_items) {
            if (it.id == id_str) { entity_path = it.entity_path; break; }
        }
    }
    if (entity_path.empty()) return false;       // unknown id

    // Absolute .data global: only meaningful on the build the symbol map came
    // from, and every hop below is page-guarded regardless. R.item.guid()
    // POLLS this from Lua, so an unguarded walk here would fault repeatedly.
    if (!Loader::get().va_globals_trusted()) return false;

    void* rsc = find_entity_resource(entity_path);
    if (!rsc) return false;                       // definition not loaded yet

    std::uintptr_t pool = 0;
    if (!mem_load(reloc(kPoolPtrGlobalVA), &pool) || pool == 0) return false;
    std::uintptr_t src_arr = 0;
    std::uint32_t src_count = 0;
    if (!mem_load(pool + 0x0, &src_arr) || !mem_load(pool + 0x8, &src_count)) return false;
    if (!src_arr || src_count > 4096) return false;

    // Find the source entry spawned from our resource (+0x48) and read its
    // identity GUID (+0x88/+0x90) — the same fields dump_pool reports.
    for (std::uint32_t i = 0; i < src_count; ++i) {
        std::uintptr_t entry = 0;
        if (!mem_load(src_arr + i * sizeof(void*), &entry) || entry == 0) continue;
        std::uintptr_t from = 0;
        if (!mem_load(entry + 0x48, &from)
            || from != reinterpret_cast<std::uintptr_t>(rsc)) continue;
        std::uint64_t glo = 0, ghi = 0;
        if (!mem_load(entry + 0x88, &glo) || !mem_load(entry + 0x90, &ghi)) return false;
        if (lo) *lo = glo;
        if (hi) *hi = ghi;
        return true;
    }
    return false;                                 // not in source list (yet)
}

bool install_item_hooks() {
    {
        std::lock_guard<std::mutex> g(g_items_mu);
        if (g_items.empty()) {
            Loader::get().log("[item-hook] no items registered; disabled");
            return false;
        }
    }

    if (!fn_resolver_init()) {
        Loader::get().log("[item-hook] fn_resolver_init failed");
        return false;
    }

    // Resolve helper functions by SEMANTIC pattern name. These three used to
    // be resolved by the address-derived names FUN_140487040 / FUN_140154c20 /
    // FUN_1402586f0, which are the addresses those functions had two game
    // builds ago — they survive only as legacy aliases in the pattern DB, so
    // the resolve was one DB regeneration away from silently returning
    // nothing. Sym::*_Pattern is stable across patches by construction.
    if (!resolve(Sym::Resource_LookupByPath_Pattern,
                 reinterpret_cast<void**>(&g_resource_lookup))) {
        Loader::get().log("[item-hook] resource lookup unavailable; "
                          "items will be registered but not injected until "
                          "function_patterns.json is regenerated");
        // Non-fatal — the hook still installs (injection will log a skip).
    }
    if (!resolve(Sym::Vector_Grow_Pattern, reinterpret_cast<void**>(&g_vec_grow))) {
        Loader::get().log("[item-hook] vec_grow unavailable; "
                          "same fallback as above");
    }

    // SpawnAllObjects resolves directly now (see the note at the top) —
    // no containing-function + offset arithmetic to drift. If the pattern no
    // longer resolves the game was likely patched; do NOT fall back to the
    // baked VA, which may now point at unrelated code.
    std::uintptr_t spawn_va = fn_resolve(Sym::MagicalObject_SpawnAllObjects_Pattern);
    if (spawn_va == 0 || spawn_va == static_cast<std::uintptr_t>(-1)) {
        Loader::get().log("[item-hook] SpawnAllObjects pattern not found; "
                          "disabled until function_patterns.json is regenerated");
        return false;
    }
    if (!fn_verify(Sym::MagicalObject_SpawnAllObjects_Pattern, spawn_va)) {
        Loader::get().log("[item-hook] SpawnAllObjects verify failed; "
                          "pattern mismatch (game patched?)");
        return false;
    }
    Loader::get().log(std::string("[item-hook] SpawnAllObjects @ ")
                      + hex_of(spawn_va));

    const auto target = reinterpret_cast<LPVOID>(spawn_va);
    const auto rc = MH_CreateHook(target,
                                  reinterpret_cast<LPVOID>(&hook_spawn_all_objects),
                                  reinterpret_cast<LPVOID*>(&g_real_spawn_all));
    if (rc != MH_OK) {
        Loader::get().log("[item-hook] MH_CreateHook failed rc="
                          + std::to_string(static_cast<int>(rc)));
        return false;
    }
    if (MH_EnableHook(target) != MH_OK) {
        Loader::get().log("[item-hook] MH_EnableHook failed");
        return false;
    }

    {
        std::lock_guard<std::mutex> g(g_items_mu);
        Loader::get().log("[item-hook] installed on FUN_140258760 (SpawnAllObjects); "
                          + std::to_string(g_items.size()) + " item(s) queued");
    }

    // The detour above only fires if SpawnAllObjects runs AFTER we arm it.
    // It runs once during InitialLoading and usually races ahead of us, so
    // also start a deferred poller that injects into the already-built pool
    // once it's populated. inject_custom_items dedups, so if the detour did
    // fire, the poller's inject is a harmless no-op.
    if (!Loader::get().va_globals_trusted()) {
        Loader::get().log("[item-hook] va-globals untrusted for this game "
                          "build; deferred inject poll not started");
        return true;
    }
    std::thread(deferred_inject_poll).detach();
    return true;
}

} // namespace rsmm
