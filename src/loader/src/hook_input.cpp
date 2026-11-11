// Mouse-wheel notches from Input_Poll — see hook_input.h for the why.

#include <windows.h>

#include <atomic>
#include <cstdint>
#include <cstdio>

#include "hook_input.h"
#include "hook_keybinds.h"   // keybinds_on_poll
#include "hook_util.h"
#include "loader.h"
#include "mem_safe.h"
#include "script_lua.h"    // script_try_emit_event_json, script_has_handler
#include "symbols.gen.h"   // GENERATED — Sym::

namespace rsmm {
namespace {

constexpr const char* kEvent = "input:wheel";

// Input manager field the window procedure stores the wheel direction in
// (+1 / -1, a dword) and Input_Poll zeroes once it has set the buttons.
constexpr std::uintptr_t kWheelOff = 0xa0;
// Button record flags (first byte of the 12-byte record).
constexpr std::uint8_t kHeld    = 0x04;
constexpr std::uint8_t kBlocked = 0x01;   // set while the manager's +0x60 countdown runs

using Poll_fn = void (*)(void* mgr, const void* frame_time);
Poll_fn g_real = nullptr;
std::uintptr_t g_poll_va = 0;
std::uintptr_t g_rec_up = 0;
std::uintptr_t g_rec_down = 0;

std::atomic<bool> g_armed{false};
std::atomic<std::uint64_t> g_up{0};
std::atomic<std::uint64_t> g_down{0};
std::atomic<std::int64_t> g_pending{0};     // net notches not yet delivered
std::atomic<bool> g_pending_blocked{false};  // the newest notch arrived while blocked
std::atomic<bool> g_logged_thread{false};

std::uintptr_t image_base() {
    HMODULE h = GetModuleHandleA("Ravenswatch.exe");
    if (!h) h = GetModuleHandleA(nullptr);
    return reinterpret_cast<std::uintptr_t>(h);
}

std::uintptr_t rebase(std::uintptr_t va) {
    return va - Sym::kPreferredBase + image_base();
}

void try_deliver() {
    // Nobody listening: drop the backlog so a mod that subscribes later does
    // not receive every notch of the session at once.
    if (!script_has_handler(kEvent)) {
        g_pending.store(0, std::memory_order_relaxed);
        return;
    }
    const std::int64_t n = g_pending.exchange(0, std::memory_order_acq_rel);
    if (n == 0) return;
    char json[192];
    std::snprintf(json, sizeof(json),
                  "{\"steps\":%lld,\"up\":%llu,\"down\":%llu,\"blocked\":%s}",
                  static_cast<long long>(n),
                  static_cast<unsigned long long>(g_up.load(std::memory_order_relaxed)),
                  static_cast<unsigned long long>(g_down.load(std::memory_order_relaxed)),
                  g_pending_blocked.load(std::memory_order_relaxed) ? "true" : "false");
    // Lua lock busy (the ticker or another thread is running a handler): put
    // the notches back and retry on the next frame rather than stall the game.
    if (!script_try_emit_event_json(kEvent, json))
        g_pending.fetch_add(n, std::memory_order_acq_rel);
}

void detour_poll(void* mgr, const void* frame_time) {
    // Guarded even though `mgr` is the poll's own `this`: the offset is RE-derived
    // and goes stale on a patch. One VirtualQuery per frame.
    const auto field = reinterpret_cast<std::uintptr_t>(mgr) + kWheelOff;
    std::int32_t pre = 0;
    if (mgr == nullptr || !mem_load(field, &pre)) pre = 0;

    g_real(mgr, frame_time);
    // Mod keybinds: registration on the first polls, then presses (hook_keybinds.cpp).
    keybinds_on_poll();

    if (pre != 0) {
        hook_note_fire(g_poll_va);
        if (!g_logged_thread.exchange(true)) {
            char line[128];
            std::snprintf(line, sizeof(line),
                          "[input] first wheel notch seen on thread %lu",
                          static_cast<unsigned long>(GetCurrentThreadId()));
            Loader::get().log(line);
        }
        // Count it only when the poll really consumed it (+0xa0 back to 0) and
        // the matching virtual button reads held. A skipped mouse block (the
        // poll's skip branch) leaves +0xa0 set, and the next poll counts it.
        std::int32_t post = 1;
        std::uint8_t flags = 0;
        const std::uintptr_t rec = pre > 0 ? g_rec_up : g_rec_down;
        if (mem_load(field, &post) && post == 0 && mem_load(rec, &flags) && (flags & kHeld)) {
            (pre > 0 ? g_up : g_down).fetch_add(1, std::memory_order_relaxed);
            g_pending.fetch_add(pre > 0 ? 1 : -1, std::memory_order_acq_rel);
            g_pending_blocked.store((flags & kBlocked) != 0, std::memory_order_relaxed);
        }
    }
    if (g_pending.load(std::memory_order_relaxed) != 0) try_deliver();
}

} // namespace

bool input_armed() { return g_armed.load(std::memory_order_acquire); }

void input_wheel_totals(std::uint64_t* up, std::uint64_t* down) {
    if (up) *up = g_up.load(std::memory_order_relaxed);
    if (down) *down = g_down.load(std::memory_order_relaxed);
}

bool install_input_hooks() {
    // Fail closed on an unfingerprinted build: the two button records are raw
    // VAs, and on another build they name some other bytes.
    if (!Loader::get().va_globals_trusted()) {
        Loader::get().log("[input] not arming: VA globals are not trusted on this game "
                          "build, so the wheel button records cannot be located");
        return false;
    }
    g_rec_up = rebase(Sym::g_InputMouseWheelUp);
    g_rec_down = rebase(Sym::g_InputMouseWheelDown);
    std::uint8_t probe = 0;
    if (!mem_load(g_rec_up, &probe) || !mem_load(g_rec_down, &probe)) {
        Loader::get().log("[input] not arming: wheel button records are not readable");
        return false;
    }
    const bool ok = hook_install("input", "input poll", Sym::Input_Poll_Pattern,
                                 reinterpret_cast<void*>(&detour_poll),
                                 reinterpret_cast<void**>(&g_real), &g_poll_va);
    g_armed.store(ok, std::memory_order_release);
    return ok;
}

} // namespace rsmm
