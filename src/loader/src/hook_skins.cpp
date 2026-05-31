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
#include "loader.h"

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
constexpr std::size_t kOffKey    = 0x3c;  // int matched by hero+0x78 selection
constexpr std::size_t kOffIdx    = 0x48;  // int (engine uses i+1)
constexpr std::size_t kOffAcId   = 0x50;  // std::string-slot (AC asset id)
constexpr std::size_t kOffAlId   = 0x60;  // std::string-slot (AL asset id)
constexpr std::size_t kOffBaseId = 0x70;  // std::string-slot (base asset id)
constexpr std::size_t kOffName   = 0x90;  // std::string-slot (display name)

// Manager list fields.
constexpr std::size_t kMgrCount = 0x08;
constexpr std::size_t kMgrHead  = 0x10;
constexpr std::size_t kMgrTail  = 0x18;

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

RosterBuilder_t g_real_builder = nullptr;
EntryCtor_t     g_entry_ctor   = nullptr;
StringAssign_t  g_string_assign = nullptr;

struct SkinPackDef {
    std::string name;
    std::string ac_id;
    std::string al_id;
    std::string base_id;
    std::int32_t key = 0;
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
const char* dup_cstr(const std::string& s) {
    char* p = static_cast<char*>(malloc(s.size() + 1));
    std::memcpy(p, s.c_str(), s.size() + 1);
    return p;
}

void assign_string(void* entry, std::size_t off, const std::string& s) {
    StringDesc d{};
    d.ptr = dup_cstr(s);
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
    void* mgr_global = reinterpret_cast<void*>(reloc(kMgrPtrGlobalVA));
    void* mgr = *reinterpret_cast<void**>(mgr_global);
    if (!mgr) {
        Loader::get().log("[skin-hook] manager pointer null; skipping append");
        return;
    }
    std::int32_t idx = 10;  // engine used 1..9; ours continue after
    for (const auto& def : g_packs) {
        // Leaked, permanently-stable 0xA0 node (never in the fixed array,
        // never destructed by the engine's shrink path).
        void* e = _aligned_malloc(kEntrySize, 16);
        std::memset(e, 0, kEntrySize);
        link_entry(mgr, e, idx++, def);
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
        d.ac_id   = it.value("ac_id", std::string{});
        d.al_id   = it.value("al_id", std::string{});
        d.base_id = it.value("base_id", std::string{});
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

bool resolve(const char* name, void** out) {
    const auto va = fn_resolve(name);
    if (va == 0 || va == static_cast<std::uintptr_t>(-1)) {
        Loader::get().log(std::string("[skin-hook] resolve ") + name + " failed");
        return false;
    }
    if (!fn_verify(name, va)) {
        Loader::get().log(std::string("[skin-hook] verify ") + name
                          + " @ " + hex_of(va) + " mismatch (game patched?)");
        return false;
    }
    *out = reinterpret_cast<void*>(va);
    Loader::get().log(std::string("[skin-hook] ") + name + " -> " + hex_of(va));
    return true;
}

} // namespace

bool install_skin_hooks() {
    if (!load_pack_defs()) return false;
    if (!fn_resolver_init()) {
        Loader::get().log("[skin-hook] fn_resolver_init failed");
        return false;
    }

    void* builder_va = nullptr;
    if (!resolve("FUN_1401dcae0", &builder_va)) return false;
    if (!resolve("FUN_140214bb0", reinterpret_cast<void**>(&g_entry_ctor))) return false;
    if (!resolve("FUN_1405288b0", reinterpret_cast<void**>(&g_string_assign))) return false;

    const auto rc = MH_CreateHook(builder_va,
                                  reinterpret_cast<LPVOID>(&hook_roster_builder),
                                  reinterpret_cast<LPVOID*>(&g_real_builder));
    if (rc != MH_OK) {
        Loader::get().log("[skin-hook] MH_CreateHook failed rc="
                          + std::to_string(static_cast<int>(rc)));
        return false;
    }
    if (MH_EnableHook(builder_va) != MH_OK) {
        Loader::get().log("[skin-hook] MH_EnableHook failed");
        return false;
    }
    Loader::get().log("[skin-hook] installed on FUN_1401dcae0 (roster builder); "
                      + std::to_string(g_packs.size()) + " pack(s) queued");
    return true;
}

} // namespace rsmm
