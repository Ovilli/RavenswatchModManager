// Mod key bindings as native Controls rows — see hook_keybinds.h for the why.
//
// Layouts below were read on b9c3 (notes on each symbol in data/symbols.json,
// design notes in the contributor's controls-rows doc):
//   InputKeyGameOption (0x30): +0x0 vftable, +0x8 u32 id (spinlock hash key),
//     +0x10 name oCString (the ini key), +0x21 u8 registered, +0x28 u32 key,
//     +0x2c u32 default key. vftable slot 6 = SetValue(this, const u32*).
//   GameOptionsManager: +0x08 the settings file request (+0x7c requested,
//     +0x80 completed sequence), +0x130 13 category vectors {data, u32 size,
//     u32 cap}; category 4 = Keyboard Inputs, 5 = Gamepad Inputs.
//   Options controller: +0x208 tab entries (0x48 each, count +0x210); entry
//     +0x18 type byte (4 keyboard tab, 5 gamepad tab), +0x20 row vector
//     {data, u32 count}.
//   Key row: +0x98 u32* the key it shows and writes.

#include <windows.h>

#include <atomic>
#include <cctype>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <mutex>
#include <string>

#include "json.hpp"   // single-header nlohmann::json (vendored)

#include "hook_keybinds.h"
#include "hook_input.h"
#include "hook_util.h"
#include "loader.h"
#include "mem_safe.h"
#include "script_lua.h"        // script_try_emit_event_json, script_has_handler
#include "symbols.gen.h"       // GENERATED — Sym::
#include "symbols_api.gen.h"   // GENERATED — engine:: typed accessors

namespace rsmm {
namespace {

constexpr const char* kEvent = "input:keybind";

struct OcStr {           // oCString: {char*, u32 len | 0x80000000 literal, u32 cap}
    const char* p;
    std::uint32_t len;
    std::uint32_t cap;
};
constexpr std::uint32_t kLiteral = 0x80000000u;
OcStr lit(const std::string& s) { return {s.c_str(), std::uint32_t(s.size()) | kLiteral, 0}; }

// InputKeyGameOption
constexpr std::size_t    kOptSize      = 0x30;
constexpr std::uintptr_t kOptId        = 0x08;
constexpr std::uintptr_t kOptName      = 0x10;
constexpr std::uintptr_t kOptValue     = 0x28;
constexpr std::uintptr_t kOptDefault   = 0x2c;
constexpr std::size_t    kSlotSetValue = 6;
// GameOptionsManager
constexpr std::uintptr_t kMgrRequest   = 0x08;
constexpr std::uintptr_t kReqRequested = 0x7c;
constexpr std::uintptr_t kReqCompleted = 0x80;
constexpr std::uintptr_t kMgrCats      = 0x130;
constexpr std::uintptr_t kCatStride    = 0x10;
constexpr std::uintptr_t kVecSize      = 0x08;
constexpr std::uint32_t  kCatKeyboard  = 4;
constexpr std::uint32_t  kCatPad       = 5;
// Options controller and tab entries
constexpr std::uintptr_t kCtrlTabs     = 0x208;
constexpr std::uintptr_t kCtrlTabCount = 0x210;
constexpr std::uintptr_t kTabStride    = 0x48;
constexpr std::uintptr_t kTabType      = 0x18;
constexpr std::uintptr_t kTabRows      = 0x20;
constexpr std::uintptr_t kTabRowCount  = 0x28;
constexpr std::uint8_t   kTabKeyboard  = 4;
constexpr std::uint8_t   kTabPad       = 5;
constexpr std::uintptr_t kRowValue     = 0x98;
// The vanilla row each mod row is spawned from: Explo::DashAbility, an
// action the capture accepts any key for (rebound to keys 76 and 91 in the
// 2026-11-11 probe). The row is then pointed at the mod's option and retitled.
constexpr std::uint32_t  kTemplateExplo = 6;
// Key table
constexpr std::uintptr_t kRecStride    = 12;
constexpr std::uint8_t   kRecPressed   = 0x08;
constexpr std::uint8_t   kRecBlocked   = 0x01;
constexpr std::uint32_t  kKeyMax       = 0xff;   // above this a key id is not a key
// Key id ranges by device: keyboard 1-84, mouse buttons 85-91, wheel 92-93
// (the Keyboard tab), gamepad 94 and up (the Gamepad tab). 0 = unbound.
constexpr std::uint32_t  kKeyboardMax  = 93;
constexpr std::uint32_t  kPadMin       = 94;

constexpr int         kMaxBindings = 16;
constexpr std::size_t kMaxId       = 32;
constexpr std::size_t kMaxLabel    = 32;   // longer runs into the row's key box

struct Binding {
    std::string mod, id, label, name;   // name = "<mod>::<id>", the ini key
    std::uint32_t def_kb = 0, def_pad = 0;
    alignas(16) std::uint8_t opt_kb[kOptSize] = {};
    alignas(16) std::uint8_t opt_pad[kOptSize] = {};
    // Poll thread only.
    std::uint32_t pending = 0;
    bool pending_blocked = false;
    std::uint32_t seen_kb = 0, seen_pad = 0;
    // What Lua reads (keybind_keys, from any thread). The options themselves
    // are written by the game thread, the Controls menu and the settings
    // worker, so readers get this copy, published by the poll every frame.
    std::atomic<std::uint32_t> snap_kb{0}, snap_pad{0};
};

// Fixed storage: the game holds pointers into opt_kb / opt_pad for the whole
// session, so bindings never move and are never freed.
Binding g_binds[kMaxBindings];
std::atomic<int> g_count{0};
std::mutex g_decl_mu;

std::atomic<bool> g_armed{false};          // menu + resolver hooks live
std::atomic<bool> g_decls_closed{false};   // install ran: every init.lua is done
std::atomic<bool> g_registered{false};
std::atomic<bool> g_register_failed{false};  // terminal: the poll stops retrying
bool g_told_late_tab = false;              // main thread only

engine::GameOptionsManager_Register_fn    g_register     = nullptr;
engine::GameOptionsManager_RequestLoad_fn g_request_load = nullptr;
engine::OptionsMenu_SpawnExploKeyRow_fn   g_spawn_row    = nullptr;
engine::OptionsMenuElement_SetTitle_fn    g_set_title    = nullptr;

using build_fn = void (*)(void*, void*, void*);
build_fn g_real_build_kb = nullptr;
build_fn g_real_build_pad = nullptr;
using clear_fn = void (*)(void*, void*, std::uint32_t);
clear_fn g_real_clear = nullptr;

std::uintptr_t image_base() {
    HMODULE h = GetModuleHandleA("Ravenswatch.exe");
    if (!h) h = GetModuleHandleA(nullptr);
    return reinterpret_cast<std::uintptr_t>(h);
}

std::uintptr_t rebase(std::uintptr_t va) {
    return va - Sym::kPreferredBase + image_base();
}

std::uint32_t fnv1a32(const std::string& s) {
    std::uint32_t h = 0x811c9dc5u;
    for (unsigned char c : s) { h ^= c; h *= 0x01000193u; }
    return h;
}

bool valid_id(const std::string& s) {
    if (s.empty() || s.size() > kMaxId) return false;
    for (unsigned char c : s) {
        if (!(std::isalnum(c) || c == '_')) return false;
    }
    return true;
}

std::uint32_t& value_of(std::uint8_t* opt) {
    return *reinterpret_cast<std::uint32_t*>(opt + kOptValue);
}

void build_option(std::uint8_t* opt, const Binding& b, std::uint32_t def, std::uintptr_t vtbl) {
    std::memset(opt, 0, kOptSize);
    *reinterpret_cast<std::uintptr_t*>(opt) = vtbl;
    *reinterpret_cast<std::uint32_t*>(opt + kOptId) = fnv1a32(b.name);
    const OcStr name = lit(b.name);   // aliases b.name, which lives for the session
    std::memcpy(opt + kOptName, &name, sizeof(name));
    *reinterpret_cast<std::uint32_t*>(opt + kOptValue) = def;
    *reinterpret_cast<std::uint32_t*>(opt + kOptDefault) = def;
}

// The game's own SetValue (vftable slot 6): takes the option's spinlock, which
// the menu and the settings walk also take.
void set_value(std::uint8_t* opt, std::uint32_t key) {
    using set_fn = void (*)(void*, const std::uint32_t*);
    auto** vt = *reinterpret_cast<set_fn**>(opt);
    vt[kSlotSetValue](opt, &key);
}

// --- registration (input poll, game main thread) ----------------------------

void try_register() {
    auto& L = Loader::get();
    const int n = g_count.load(std::memory_order_acquire);
    if (n == 0) {   // nothing declared: nothing to register, nothing to re-read
        g_registered.store(true, std::memory_order_release);
        return;
    }
    if (!g_register || !g_request_load) {
        L.log_err("[keybinds] engine calls not resolved; " + std::to_string(n)
                  + " binding(s) not registered");
        g_register_failed.store(true, std::memory_order_release);
        return;
    }
    std::uintptr_t mgr = 0, opts = 0;
    if (!mem_load(rebase(Sym::g_GameOptionsManager), &mgr) || !mgr
        || !mem_load(rebase(Sym::g_GameOptions), &opts) || !opts) {
        return;   // the options are not built yet: try again next frame
    }
    // The vanilla key slots must already be registered (GameOptions_InitKeySlots
    // ran), the game must have read the file once, and no settings request may
    // be in flight.
    std::uint32_t kb_count = 0, requested = 0, completed = 0;
    const std::uintptr_t req = mgr + kMgrRequest;
    if (!mem_load(mgr + kMgrCats + kCatKeyboard * kCatStride + kVecSize, &kb_count)
        || !mem_load(req + kReqRequested, &requested)
        || !mem_load(req + kReqCompleted, &completed)) {
        L.log_err("[keybinds] options manager not readable; bindings not registered");
        g_register_failed.store(true, std::memory_order_release);
        return;
    }
    // completed == 0: the boot's own read has not run, so the request may not
    // be bound to GameSettings yet. Wait for it; registering after it is the
    // whole point of the re-read.
    if (kb_count == 0 || completed == 0 || requested != completed) return;

    const std::uintptr_t vtbl = rebase(Sym::InputKeyGameOption_vftable);
    for (int i = 0; i < n; ++i) {
        Binding& b = g_binds[i];
        build_option(b.opt_kb, b, b.def_kb, vtbl);
        build_option(b.opt_pad, b, b.def_pad, vtbl);
        g_register(reinterpret_cast<void*>(mgr), kCatKeyboard, b.opt_kb);
        g_register(reinterpret_cast<void*>(mgr), kCatPad, b.opt_pad);
    }
    // Saved keys: the game's own read of GameSettings.ini, synchronous.
    g_request_load(nullptr, reinterpret_cast<void*>(req));
    for (int i = 0; i < n; ++i) {
        Binding& b = g_binds[i];
        b.seen_kb = value_of(b.opt_kb);
        b.seen_pad = value_of(b.opt_pad);
        b.snap_kb.store(b.seen_kb, std::memory_order_relaxed);
        b.snap_pad.store(b.seen_pad, std::memory_order_relaxed);
    }
    g_registered.store(true, std::memory_order_release);
    char line[160];
    std::snprintf(line, sizeof(line),
                  "[keybinds] registered %d binding(s) and re-read GameSettings on thread %lu",
                  n, static_cast<unsigned long>(GetCurrentThreadId()));
    L.log(line);
}

// --- presses (input poll) -----------------------------------------------------

void check_key(Binding& b, std::uint8_t* opt, std::uint32_t& seen, std::uintptr_t table) {
    const std::uint32_t key = value_of(opt);
    if (key != seen) {   // rebound since last frame: the capture's own press is not ours
        seen = key;
        return;
    }
    if (key == 0 || key > kKeyMax) return;
    std::uint8_t flags = 0;
    if (!mem_load(table + key * kRecStride, &flags) || !(flags & kRecPressed)) return;
    ++b.pending;
    b.pending_blocked = (flags & kRecBlocked) != 0;
}

void deliver(int n) {
    // Nobody listening: drop the backlog so a late subscriber does not get it.
    if (!script_has_handler(kEvent)) {
        for (int i = 0; i < n; ++i) g_binds[i].pending = 0;
        return;
    }
    for (int i = 0; i < n; ++i) {
        Binding& b = g_binds[i];
        if (b.pending == 0) continue;
        const nlohmann::json ev = {
            {"mod", b.mod}, {"id", b.id}, {"presses", b.pending},
            {"key", value_of(b.opt_kb)}, {"pad", value_of(b.opt_pad)},
            {"blocked", b.pending_blocked},
        };
        // Lua lock busy: keep the presses for the next frame.
        if (!script_try_emit_event_json(kEvent, ev.dump())) return;
        b.pending = 0;
    }
}

// --- menu rows (Settings build, game main thread) ---------------------------

void add_rows(void* ctrl, std::uint32_t tab_index, std::uint8_t want_type) {
    auto& L = Loader::get();
    const int n = g_count.load(std::memory_order_acquire);
    if (n == 0 || !g_armed.load(std::memory_order_acquire)) return;
    if (!g_registered.load(std::memory_order_acquire)) {
        if (!g_told_late_tab) {
            g_told_late_tab = true;
            L.log_warn("[keybinds] Controls tab built before the bindings were registered; "
                       "their rows are missing until Settings is built again");
        }
        return;
    }
    const auto c = reinterpret_cast<std::uintptr_t>(ctrl);
    std::uintptr_t tabs = 0;
    std::uint32_t count = 0;
    std::uint8_t type = 0;
    if (!mem_load(c + kCtrlTabs, &tabs) || !mem_load(c + kCtrlTabCount, &count)
        || tab_index >= count || !tabs
        || !mem_load(tabs + tab_index * kTabStride + kTabType, &type) || type != want_type) {
        L.log_err("[keybinds] controls tab not found where expected; no binding rows");
        return;
    }
    const std::uintptr_t entry = tabs + tab_index * kTabStride;
    int added = 0;
    for (int i = 0; i < n; ++i) {
        Binding& b = g_binds[i];
        std::uint32_t before = 0, after = 0;
        if (!mem_load(entry + kTabRowCount, &before)) break;
        g_spawn_row(ctrl, kTemplateExplo, reinterpret_cast<void*>(entry));
        std::uintptr_t rows = 0, row = 0;
        if (!mem_load(entry + kTabRowCount, &after) || after != before + 1
            || !mem_load(entry + kTabRows, &rows) || !rows
            || !mem_load(rows + before * sizeof(void*), &row) || !row
            || !mem_writable(reinterpret_cast<void*>(row + kRowValue), sizeof(void*))) {
            L.log_err("[keybinds] row spawn failed at '" + b.name + "'");
            break;
        }
        std::uint8_t* opt = want_type == kTabKeyboard ? b.opt_kb : b.opt_pad;
        *reinterpret_cast<std::uint32_t**>(row + kRowValue) = &value_of(opt);
        OcStr title = lit(b.label);   // aliases b.label, which lives for the session
        g_set_title(reinterpret_cast<void*>(row), &title);   // also re-reads row+0x98
        ++added;
    }
    char line[160];
    std::snprintf(line, sizeof(line), "[keybinds] %d row(s) added to the %s tab on thread %lu",
                  added, want_type == kTabKeyboard ? "Keyboard" : "Gamepad",
                  static_cast<unsigned long>(GetCurrentThreadId()));
    L.log(line);
}

std::uint32_t tab_count(void* ctrl) {
    std::uint32_t count = UINT32_MAX;
    if (!mem_load(reinterpret_cast<std::uintptr_t>(ctrl) + kCtrlTabCount, &count)) {
        return UINT32_MAX;
    }
    return count;
}

void hook_build_kb(void* ctrl, void* page, void* parent) {
    const std::uint32_t index = tab_count(ctrl);   // the tab the builder is about to add
    g_real_build_kb(ctrl, page, parent);
    if (index != UINT32_MAX) add_rows(ctrl, index, kTabKeyboard);
}

void hook_build_pad(void* ctrl, void* page, void* parent) {
    const std::uint32_t index = tab_count(ctrl);
    g_real_build_pad(ctrl, page, parent);
    if (index != UINT32_MAX) add_rows(ctrl, index, kTabPad);
}

// The vanilla resolver clears only the 31 vanilla actions. It runs before the
// row that took `key` writes it, so clearing every binding on `key` here
// leaves exactly that row's option holding it afterwards.
void hook_clear(void* ctrl, void* unused, std::uint32_t key) {
    g_real_clear(ctrl, unused, key);
    if (key == 0 || !g_registered.load(std::memory_order_acquire)) return;
    const int n = g_count.load(std::memory_order_acquire);
    for (int i = 0; i < n; ++i) {
        Binding& b = g_binds[i];
        if (value_of(b.opt_kb) == key) set_value(b.opt_kb, 0);
        if (value_of(b.opt_pad) == key) set_value(b.opt_pad, 0);
    }
}

template <typename F>
bool need(const char* what, const char* pattern, F* out) {
    return resolve_checked("keybinds", what, pattern, reinterpret_cast<void**>(out));
}

} // anonymous namespace

bool keybinds_armed() { return g_armed.load(std::memory_order_acquire); }

bool keybinds_registered() { return g_registered.load(std::memory_order_acquire); }

bool keybinds_failed() { return g_register_failed.load(std::memory_order_acquire); }

int keybind_add(const std::string& mod, const std::string& id, const std::string& label,
                std::uint32_t kb, std::uint32_t pad, std::string* err) {
    auto fail = [&](const std::string& why) {
        if (err) *err = why;
        return -1;
    };
    std::lock_guard<std::mutex> g(g_decl_mu);
    const int n = g_count.load(std::memory_order_relaxed);
    for (int i = 0; i < n; ++i) {
        if (g_binds[i].mod == mod && g_binds[i].id == id) return i;   // hot reload
    }
    if (g_decls_closed.load(std::memory_order_acquire)) {
        return fail("keybinds can only be added from init.lua (the bindings are already "
                    "registered with the game)");
    }
    if (mod.empty()) return fail("no mod id");
    if (!valid_id(id)) return fail("id must be 1-32 letters, digits or _");
    if (label.empty() || label.size() > kMaxLabel) return fail("label must be 1-32 characters");
    if (kb != 0 && kb > kKeyboardMax) {
        return fail("key must be a keyboard or mouse key id (1-93), or 0");
    }
    if (pad != 0 && (pad < kPadMin || pad > kKeyMax)) {
        return fail("pad must be a gamepad key id (94-255), or 0");
    }
    if (n >= kMaxBindings) {
        return fail("no room: " + std::to_string(kMaxBindings) + " keybinds across all mods");
    }
    Binding& b = g_binds[n];
    b.mod = mod;
    b.id = id;
    b.label = label;
    b.name = mod + "::" + id;
    b.def_kb = kb;
    b.def_pad = pad;
    // Until registration Lua reads the defaults.
    b.snap_kb.store(kb, std::memory_order_relaxed);
    b.snap_pad.store(pad, std::memory_order_relaxed);
    g_count.store(n + 1, std::memory_order_release);
    return n;
}

bool keybind_keys(int index, std::uint32_t* kb, std::uint32_t* pad) {
    if (index < 0 || index >= g_count.load(std::memory_order_acquire)) return false;
    Binding& b = g_binds[index];
    if (kb) *kb = b.snap_kb.load(std::memory_order_relaxed);
    if (pad) *pad = b.snap_pad.load(std::memory_order_relaxed);
    return true;
}

void keybinds_on_poll() {
    if (!g_armed.load(std::memory_order_acquire)) return;
    if (!g_registered.load(std::memory_order_acquire)) {
        if (g_register_failed.load(std::memory_order_acquire)) return;
        try_register();
        return;
    }
    const int n = g_count.load(std::memory_order_acquire);
    if (n == 0) return;
    const std::uintptr_t table = rebase(Sym::g_InputKeyRecords);
    bool any = false;
    for (int i = 0; i < n; ++i) {
        Binding& b = g_binds[i];
        check_key(b, b.opt_kb, b.seen_kb, table);
        check_key(b, b.opt_pad, b.seen_pad, table);
        b.snap_kb.store(b.seen_kb, std::memory_order_relaxed);
        b.snap_pad.store(b.seen_pad, std::memory_order_relaxed);
        any = any || b.pending != 0;
    }
    if (any) deliver(n);
}

bool install_keybind_hooks() {
    auto& L = Loader::get();
    // Every init.lua has run by the time the installers do: from here on a new
    // declaration would miss the one re-read of GameSettings.
    g_decls_closed.store(true, std::memory_order_release);
    const int n = g_count.load(std::memory_order_acquire);
    // Fail closed on an unfingerprinted build: the option vftable, the manager
    // and the key table are raw VAs.
    if (!L.va_globals_trusted()) {
        L.log("[keybinds] not arming: VA globals are not trusted on this game build");
        return false;
    }
    if (!input_armed()) {
        L.log("[keybinds] not arming: the input poll hook is not live");
        return false;
    }
    if (!need("register option", Sym::GameOptionsManager_Register_Pattern, &g_register)
        || !need("request load", Sym::GameOptionsManager_RequestLoad_Pattern, &g_request_load)
        || !need("spawn key row", Sym::OptionsMenu_SpawnExploKeyRow_Pattern, &g_spawn_row)
        || !need("set title", Sym::OptionsMenuElement_SetTitle_Pattern, &g_set_title)) {
        g_register = nullptr;
        g_request_load = nullptr;
        return false;
    }
    if (!hook_install("keybinds", "keyboard controls tab", Sym::OptionsMenu_BuildKeyboardControls_Pattern,
                      reinterpret_cast<void*>(&hook_build_kb),
                      reinterpret_cast<void**>(&g_real_build_kb))
        || !hook_install("keybinds", "gamepad controls tab", Sym::OptionsMenu_BuildGamepadControls_Pattern,
                         reinterpret_cast<void*>(&hook_build_pad),
                         reinterpret_cast<void**>(&g_real_build_pad))
        || !hook_install("keybinds", "duplicate key resolver", Sym::OptionsMenu_ClearDuplicateKey_Pattern,
                         reinterpret_cast<void*>(&hook_clear),
                         reinterpret_cast<void**>(&g_real_clear))) {
        // Without the rows nobody can see or change a binding: register nothing.
        g_register = nullptr;
        g_request_load = nullptr;
        return false;
    }
    g_armed.store(true, std::memory_order_release);
    L.log("[keybinds] armed: " + std::to_string(n) + " binding(s) declared");
    return true;
}

} // namespace rsmm
