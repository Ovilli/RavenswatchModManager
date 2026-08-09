// Custom skin-pack roster injection — see hook_skins.h for the rationale.
//
// Detour target FUN_1401dcae0(ctx): the skin-pack roster builder. We run
// the original, then append our own standalone entries to the global
// additional-content manager list. Everything here is derived from the
// verified RE in docs/_re/kinds/skins.md; the three game functions are
// pattern-resolved (function_patterns.json) so they survive minor patches,
// and we guard with fn_verify before calling. The only hard-coded absolute
// is the manager pointer global DAT_141436590, relocated by the live image
// base.

#include "hook_skins.h"
#include "fn_resolver.h"
#include "hook_util.h"
#include "symbols.gen.h"  // GENERATED — Sym::
#include "loader.h"
#include "mem_safe.h"

#include "MinHook.h"
#include "json.hpp"

#include <windows.h>
#include <psapi.h>

#include <atomic>
#include <cstdint>
#include <cstring>
#include <fstream>
#include <mutex>
#include <string>
#include <vector>

namespace rsmm {
namespace {

// --- layout constants (preferred-base 0x140000000) -----------------------
constexpr std::uintptr_t kPreferredBase = 0x140000000ull;
// Global: oCAdditionalContentManager* (pointer-load `MOV RAX,[rip]->...`).
constexpr std::uintptr_t kMgrPtrGlobalVA = 0x141436590ull;

// Entry (oCAdditionalContent) is 0xA0 bytes. Field offsets the builder writes:
constexpr std::size_t kEntrySize = 0xA0;
constexpr std::size_t kOffNext   = 0x08;  // list: next
constexpr std::size_t kOffBack   = 0x10;  // list: written into prev head's slot
constexpr std::size_t kOffOwner  = 0x18;  // list: owner (manager)
constexpr std::size_t kOffKey    = 0x3c;  // int — Steam DLC appid (Steam filter) or match key
constexpr std::size_t kOffIdx    = 0x48;  // int (engine uses i+1)
constexpr std::size_t kOffAcId   = 0x50;  // std::string-slot (AC asset id)
constexpr std::size_t kOffAlId   = 0x60;  // std::string-slot (AL asset id)
constexpr std::size_t kOffBaseId = 0x70;  // std::string-slot (base asset id)
constexpr std::size_t kOffDlcPath= 0x80;  // char* — dlc entitlement path (local filter)
constexpr std::size_t kOffDlcHash= 0x88;  // uint32 — path-hash companion (local filter)
constexpr std::size_t kOffName   = 0x90;  // std::string-slot (display name)

// Manager list fields.
constexpr std::size_t kMgrCount = 0x08;
constexpr std::size_t kMgrHead  = 0x10;
constexpr std::size_t kMgrTail  = 0x18;

// Skin-grid populate (FUN_1401f0f10) writes the visible roster into a
// vector on its screen ctx. Vector layout {ptr; i32 count; u32 cap}
// (see grow helper FUN_140154c20). Per list node the engine calls the
// manager vtable[1] filter and only pushes the node when it returns 3.
constexpr std::size_t kGridVec   = 0x2f8;  // ctx + 0x2f8 -> {ptr, count, cap}
constexpr std::size_t kGridCount = 0x300;
constexpr std::size_t kGridCap   = 0x304;
constexpr std::size_t kVtblFilter = 0x08;  // manager vtable slot returning 3

// The 16-byte string descriptor the game string-assign helper consumes.
// { ptr; lenflags } where high bit of lenflags = "literal / non-owned".
struct StringDesc {
    const char* ptr;
    std::uint32_t lenflags;
    std::uint32_t pad;
};
constexpr std::uint32_t kLiteralBit = 0x80000000u;

// Game functions (Win x64: args in RCX/RDX/...).
using RosterBuilder_t = void (*)(void* ctx);
using EntryCtor_t     = void (*)(void* base, std::uint32_t count);  // FUN_140214bb0
using StringAssign_t  = void (*)(void* dst_slot, const StringDesc* src);  // FUN_1405288b0
using GridPopulate_t  = void (*)(void* ctx, void* arg);  // FUN_1401f0f10
// FUN_140154c20(vec, <unused RDX>, new_cap): the engine passes the new
// capacity in the 3rd integer slot (R8); RDX is left untouched at the call
// sites. Mirror that ABI exactly or new_cap lands in the wrong register.
using VecGrow_t       = void (*)(void* vec, std::uint64_t, std::uint32_t new_cap);
using Filter_t        = int  (*)(void* mgr, void* node);  // manager vtable[1]

RosterBuilder_t g_real_builder = nullptr;
std::uintptr_t  g_builder_va  = 0;
EntryCtor_t     g_entry_ctor   = nullptr;
StringAssign_t  g_string_assign = nullptr;
GridPopulate_t  g_real_populate = nullptr;
VecGrow_t       g_vec_grow      = nullptr;
// Manager vtable[1] grid filter (see docs/_re/kinds/skins.md A2). We detour
// the actual function body so calls through the vtable are intercepted; our
// pack keys return 3 (show as a button), everything else forwards to the
// original (vanilla Steam-DLC / local-file gate, unchanged). The address is
// read from the *live* manager vtable[1] at runtime — NOT pattern-resolved —
// so it's correct on both the Steam and DRM-free builds regardless of which
// manager class the game constructed.
Filter_t        g_real_filter = nullptr;
std::once_flag  g_filter_hooked;
void install_filter_hook(void* mgr);  // defined below; called from append_custom_packs

// Diagnostic: when RSMM_SKIN_FORCE_SHOW=1, after the engine populates the
// skin grid we force-push our appended nodes regardless of the vtable[1]
// filter result (and log that result), to prove the button path in-game
// while the filter predicate is being reverse-engineered (docs A2).
bool g_force_show = false;
std::vector<void*> g_our_nodes;  // nodes we appended, in registration order

struct SkinPackDef {
    std::string name;
    std::string ac_id;
    std::string al_id;
    std::string base_id;
    std::int32_t key = 0;
    std::string dlc_path;  // entitlement file path (local filter, off +0x80)
};
std::vector<SkinPackDef> g_packs;
std::once_flag g_appended;

// --- helpers -------------------------------------------------------------

std::uintptr_t image_base() {
    HMODULE h = GetModuleHandleA("Ravenswatch.exe");
    if (!h) h = GetModuleHandleA(nullptr);
    return reinterpret_cast<std::uintptr_t>(h);
}

// Relocate a preferred-base VA to the live image.
std::uintptr_t reloc(std::uintptr_t static_va) {
    return static_va - kPreferredBase + image_base();
}

std::string hex_of(std::uintptr_t v) {
    char b[32];
    snprintf(b, sizeof(b), "0x%llx", static_cast<unsigned long long>(v));
    return b;
}

// Leak a stable C-string (literal-bit strings are non-owned by the game).
// Returns nullptr on OOM rather than memcpy-ing through it.
const char* dup_cstr(const std::string& s) {
    char* p = static_cast<char*>(malloc(s.size() + 1));
    if (!p) return nullptr;
    std::memcpy(p, s.c_str(), s.size() + 1);
    return p;
}

void assign_string(void* entry, std::size_t off, const std::string& s) {
    StringDesc d{};
    d.ptr = dup_cstr(s);
    if (!d.ptr) return;
    d.lenflags = kLiteralBit | static_cast<std::uint32_t>(s.size());
    g_string_assign(static_cast<std::uint8_t*>(entry) + off, &d);
}

// Push one standalone entry onto the manager list (replicates the exact
// sequence inside FUN_1401dcae0's loop).
void link_entry(void* mgr, void* e, std::int32_t idx, const SkinPackDef& def) {
    g_entry_ctor(e, 1);  // vtable + sentinels + empty strings

    auto i32 = [&](std::size_t off) -> std::int32_t* {
        return reinterpret_cast<std::int32_t*>(static_cast<std::uint8_t*>(e) + off);
    };
    auto pp = [&](void* base, std::size_t off) -> void** {
        return reinterpret_cast<void**>(static_cast<std::uint8_t*>(base) + off);
    };

    *i32(kOffKey) = def.key;
    *i32(kOffIdx) = idx;
    assign_string(e, kOffAcId,   def.ac_id);
    assign_string(e, kOffAlId,   def.al_id);
    assign_string(e, kOffBaseId, def.base_id);
    assign_string(e, kOffName,   def.name);

    // Local filter (oCLocalAdditionalContentManager::vftable[1]) checks
    // node+0x80 for a dlc entitlement path. If provided, set it so the
    // file-existence check passes (see docs/_re/kinds/skins.md A2).
    if (!def.dlc_path.empty()) {
        *pp(e, kOffDlcPath) = const_cast<char*>(dup_cstr(def.dlc_path));
        // Hash at +0x88 is used by the filter for a dead computation;
        // set to path length for consistency.
        *i32(kOffDlcHash) = static_cast<std::int32_t>(def.dlc_path.size());
    }

    // List insert (push-front), matching the builder byte-for-byte.
    *pp(e, kOffOwner) = mgr;
    std::int32_t* mgr_count = reinterpret_cast<std::int32_t*>(
        static_cast<std::uint8_t*>(mgr) + kMgrCount);
    void** mgr_head = pp(mgr, kMgrHead);
    if (*mgr_count == 0) {
        *pp(mgr, kMgrTail) = e;
    } else {
        *pp(*mgr_head, kOffBack) = e;  // old_head+0x10 = e
    }
    *pp(e, kOffNext) = *mgr_head;      // e->next = old head
    *mgr_count += 1;
    *mgr_head = e;                     // head = e
}

void append_custom_packs() {
    // kMgrPtrGlobalVA is an absolute .data address: on a build the symbol map
    // wasn't derived from it points at arbitrary bytes, so gate on the build
    // fingerprint AND page-guard the read before dereferencing what it holds.
    if (!Loader::get().va_globals_trusted()) {
        Loader::get().log("[skin-hook] game build != symbol-map build; "
                          "manager global not trusted, skipping append");
        return;
    }
    const auto mgr_global = reloc(kMgrPtrGlobalVA);
    std::uintptr_t mgr_addr = 0;
    if (!mem_load(mgr_global, &mgr_addr) || mgr_addr == 0) {
        Loader::get().log("[skin-hook] manager pointer null/unreadable; "
                          "skipping append");
        return;
    }
    void* mgr = reinterpret_cast<void*>(mgr_addr);
    // The list splice writes through mgr+0x08..0x18 and reads its vtable.
    if (!mem_writable(mgr, 0x20) || !mem_readable(mgr, sizeof(void*))) {
        Loader::get().log("[skin-hook] manager object not writable; skipping append");
        return;
    }
    // Now that the manager exists, detour its real vtable[1] filter so our
    // packs pass the grid gate as proper buttons (no RSMM_SKIN_FORCE_SHOW).
    install_filter_hook(mgr);
    std::int32_t idx = 10;  // engine used 1..9; ours continue after
    for (const auto& def : g_packs) {
        // Leaked, permanently-stable 0xA0 node (never in the fixed array,
        // never destructed by the engine's shrink path).
        void* e = _aligned_malloc(kEntrySize, 16);
        if (!e) {
            Loader::get().log("[skin-hook] entry alloc failed; stopping append");
            return;
        }
        std::memset(e, 0, kEntrySize);
        link_entry(mgr, e, idx++, def);
        g_our_nodes.push_back(e);
        Loader::get().log("[skin-hook] registered pack '" + def.name
                          + "' key=" + hex_of(static_cast<std::uint32_t>(def.key))
                          + " node=" + hex_of(reinterpret_cast<std::uintptr_t>(e)));
    }
}

void hook_roster_builder(void* ctx) {
    g_real_builder(ctx);  // let the engine build its 9 entries first
    // The builder is expected to run once at bootstrap; guard regardless so
    // a re-run can't double-register our packs.
    std::call_once(g_appended, append_custom_packs);
}

// Push `node` into the screen ctx's skin-grid vector (ctx+0x2f8), growing
// via the engine's own helper, replicating the engine's grow arithmetic.
// Dedups so a menu re-open doesn't insert the same node twice.
void grid_push(void* ctx, void* node) {
    auto u8 = static_cast<std::uint8_t*>(ctx);
    auto* count = reinterpret_cast<std::uint32_t*>(u8 + kGridCount);
    auto* cap   = reinterpret_cast<std::uint32_t*>(u8 + kGridCap);
    auto** bufp = reinterpret_cast<void***>(u8 + kGridVec);
    void** buf = *bufp;
    for (std::uint32_t i = 0; buf && i < *count; i++) {
        if (buf[i] == node) return;  // already shown
    }
    std::uint32_t need = *count + 1;
    if (*cap < need) {
        std::uint32_t ncap = (*cap > 8) ? *cap : 8;
        while (ncap < need) ncap *= 2;
        g_vec_grow(u8 + kGridVec, 0, ncap);  // reallocs *bufp, updates cap
        buf = *bufp;
    }
    buf[*count] = node;
    *count = need;
}

void hook_grid_populate(void* ctx, void* arg) {
    g_real_populate(ctx, arg);  // engine builds the filtered roster first
    std::uintptr_t mgr_addr = 0;
    (void)mem_load(reloc(kMgrPtrGlobalVA), &mgr_addr);
    void* mgr = reinterpret_cast<void*>(mgr_addr);
    for (void* node : g_our_nodes) {
        int filt = -1;
        std::uintptr_t vtbl = 0, fn_addr = 0;
        if (mgr && mem_load(mgr, &vtbl)
            && mem_load(vtbl + kVtblFilter, &fn_addr) && fn_addr) {
            auto fn = reinterpret_cast<Filter_t>(fn_addr);
            filt = fn(mgr, node);  // capture the gate's verdict for A2 RE
        }
        Loader::get().log("[skin-hook] force-show node="
                          + hex_of(reinterpret_cast<std::uintptr_t>(node))
                          + " filter=" + std::to_string(filt)
                          + (filt == 3 ? " (already shown)" : " (forcing)"));
        if (filt != 3) grid_push(ctx, node);
    }
}

// True if `node`'s pack key (+0x3c) belongs to one of our registered packs.
// Guarded: this runs from the vtable-filter detour for EVERY roster node the
// engine tests, including whatever the game hands it.
bool is_our_node_key(void* node) {
    std::int32_t key = 0;
    if (!mem_load(static_cast<std::uint8_t*>(node) + kOffKey, &key)) return false;
    for (const auto& d : g_packs) {
        if (d.key == key) return true;
    }
    return false;
}

// Grid-filter detour. The vanilla body gates a node on Steam-DLC ownership
// (Steam build) or a file-existence check at node+0x80 (DRM-free build); we
// short-circuit our own keys to 3 (= show) and forward every real DLC/skin
// slot to the original so its gate is unchanged. Short-circuiting also keeps
// our null node+0x80 away from the local filter's deref.
int hook_filter(void* mgr, void* node) {
    if (is_our_node_key(node)) return 3;
    return g_real_filter(mgr, node);
}

// Detour the live manager's vtable[1] filter. Called once we hold a valid
// manager pointer (its vtable is set by then). Reads the actual function the
// engine will call, so it's correct for whichever manager class is active.
void install_filter_hook(void* mgr) {
    std::call_once(g_filter_hooked, [mgr]() {
        std::uintptr_t vtbl = 0, filter_va = 0;
        if (!mem_load(mgr, &vtbl) || !mem_load(vtbl + kVtblFilter, &filter_va)
            || filter_va == 0) {
            Loader::get().log("[skin-hook] manager vtable unreadable; grid "
                              "filter not hooked");
            return;
        }
        // Read live from the manager's vtable, so it is correct for whichever
        // manager class the game constructed — but a vtable slot can still
        // hold a thunk or a garbage pointer if the object is not what we
        // think, hence the same entry-point requirement as any other hook.
        if (hook_install_at("skin-hook", "grid filter", filter_va,
                            reinterpret_cast<void*>(&hook_filter),
                            reinterpret_cast<void**>(&g_real_filter))) {
            Loader::get().log("[skin-hook] custom packs will show as buttons");
        } else {
            Loader::get().log("[skin-hook] filter hook unavailable; custom "
                              "packs stay on the roster but render no button "
                              "(set RSMM_SKIN_FORCE_SHOW=1 to force them)");
        }
    });
}

// Boolean opt-ins go through flag_enabled (loader.cpp), which honours BOTH the
// environment variable and the rsmm_loader_flags.json the desktop app writes.
// This file used to carry a private env_truthy() that read only the
// environment, so the desktop flags panel silently could not turn the feature
// on — the same defect that hid hero capture behind Steam launch options.
// --- pack-def loading ----------------------------------------------------

std::int32_t parse_key(const nlohmann::json& v) {
    if (v.is_number_integer()) return v.get<std::int32_t>();
    if (v.is_string()) {
        const std::string s = v.get<std::string>();
        return static_cast<std::int32_t>(std::strtoul(s.c_str(), nullptr, 0));
    }
    return 0;
}

// Read one skinpacks.json (a JSON array of pack objects) into g_packs.
// Keys must be unique across all sources; later duplicates are skipped.
void load_one(const std::filesystem::path& path, const std::string& origin) {
    std::ifstream f(path);
    nlohmann::json j;
    try {
        f >> j;
    } catch (const std::exception& e) {
        Loader::get().log("[skin-hook] " + origin + " parse error: " + e.what());
        return;
    }
    if (!j.is_array()) {
        Loader::get().log("[skin-hook] " + origin + " must be a JSON array");
        return;
    }
    for (const auto& it : j) {
        if (!it.is_object() || !it.contains("name") || !it.contains("key")) {
            Loader::get().log("[skin-hook] " + origin + ": skipping pack (needs name+key)");
            continue;
        }
        SkinPackDef d;
        d.name    = it.value("name", std::string{});
        d.key     = parse_key(it["key"]);
        d.ac_id    = it.value("ac_id", std::string{});
        d.al_id    = it.value("al_id", std::string{});
        d.base_id  = it.value("base_id", std::string{});
        d.dlc_path = it.value("dlc_path", std::string{});
        bool dup = false;
        for (const auto& e : g_packs) {
            if (e.key == d.key) { dup = true; break; }
        }
        if (dup) {
            Loader::get().log("[skin-hook] " + origin + ": duplicate key for '"
                              + d.name + "'; skipping");
            continue;
        }
        g_packs.push_back(std::move(d));
    }
}

// Aggregate pack defs from every enabled mod's `mods/<id>/skinpacks.json`,
// plus a top-level `mods/skinpacks.json` for hand-authored entries.
bool load_pack_defs() {
    std::error_code ec;
    const auto top = Loader::get().mods_dir() / "skinpacks.json";
    if (std::filesystem::exists(top, ec)) {
        load_one(top, "mods/skinpacks.json");
    }
    for (const auto& m : Loader::get().mods()) {
        if (!m.enabled) continue;
        const auto p = m.root / "skinpacks.json";
        if (std::filesystem::exists(p, ec)) {
            load_one(p, m.id + "/skinpacks.json");
        }
    }
    if (g_packs.empty()) {
        Loader::get().log("[skin-hook] no skinpacks.json found; disabled");
        return false;
    }
    Loader::get().log("[skin-hook] loaded " + std::to_string(g_packs.size())
                      + " custom pack def(s)");
    return true;
}

} // namespace

bool install_skin_hooks() {
    if (!load_pack_defs()) return false;
    if (!fn_resolver_init()) {
        Loader::get().log("[skin-hook] fn_resolver_init failed");
        return false;
    }

    // These four were FUN_<addr> literals from two builds ago. Every one of
    // them resolved and passed fn_verify while landing 0x90 to 0xac0 bytes
    // INSIDE an unrelated function — the "roster builder" target sat inside an
    // oCDtEntityCpntMinimapMarker destructor, and the vector-grow helper was
    // an aligned-array DEALLOCATOR that would have freed the caller's array.
    // The feature was disabled by the .pdata gate rather than corrupting the
    // game. All four are now relocated in data/symbols.json and referenced by
    // semantic name, which is stable across game patches.
    if (!resolve_checked("skin-hook", "entry ctor", Sym::Entry_Ctor_Pattern,
                         reinterpret_cast<void**>(&g_entry_ctor))
        || !resolve_checked("skin-hook", "string assign",
                            Sym::String_Assign_Pattern,
                            reinterpret_cast<void**>(&g_string_assign))) {
        Loader::get().log("[skin-hook] disabled: helper routines do not resolve "
                          "to function starts on this build");
        return false;
    }
    if (!hook_install("skin-hook", "roster builder", Sym::SkinRoster_Build_Pattern,
                      reinterpret_cast<void*>(&hook_roster_builder),
                      reinterpret_cast<void**>(&g_real_builder),
                      &g_builder_va)) {
        return false;
    }
    Loader::get().log("[skin-hook] " + std::to_string(g_packs.size())
                      + " pack(s) queued");
    // The grid-filter detour is installed lazily from append_custom_packs once
    // the live manager (and its real vtable[1]) exists — see install_filter_hook.

    // Optional diagnostic: force our nodes to render as grid buttons,
    // bypassing the manager vtable[1] filter (which currently rejects
    // brand-new keys). Off by default; see docs/_re/kinds/skins.md (A1/A2).
    g_force_show = flag_enabled("RSMM_SKIN_FORCE_SHOW");
    if (g_force_show) {
        if (resolve_checked("skin-hook", "vector grow", Sym::Vector_Grow_Pattern,
                            reinterpret_cast<void**>(&g_vec_grow))
            && hook_install("skin-hook", "grid populate",
                            Sym::SkinGrid_Populate_Pattern,
                            reinterpret_cast<void*>(&hook_grid_populate),
                            reinterpret_cast<void**>(&g_real_populate))) {
            Loader::get().log("[skin-hook] force-show enabled "
                              "(RSMM_SKIN_FORCE_SHOW=1)");
        } else {
            Loader::get().log("[skin-hook] force-show unavailable; disabled");
            g_force_show = false;
        }
    }
    return true;
}

} // namespace rsmm
