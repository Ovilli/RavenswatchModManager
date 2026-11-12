// Mouse-wheel notches and the middle-button drag from Input_Poll — see
// hook_input.h for the why.

#include <windows.h>

#include <atomic>
#include <cmath>
#include <cstdint>
#include <cstdio>
#include <initializer_list>

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
constexpr const char* kDragEvent = "input:drag";

// Input manager field the window procedure stores the wheel direction in
// (+1 / -1, a dword) and Input_Poll zeroes once it has set the buttons.
constexpr std::uintptr_t kWheelOff = 0xa0;
// Button record flags (first byte of the 12-byte record).
constexpr std::uint8_t kHeld    = 0x04;
constexpr std::uint8_t kBlocked = 0x01;   // set while the manager's +0x60 countdown runs

// Key table (Sym::g_InputKeyRecords): one 12-byte record per key id. 89 is
// KEY_MouseButtonMiddle; Input_Poll writes it from GetAsyncKeyState(VK_MBUTTON)
// (evidence/mouse-drag-2026-11-11).
constexpr std::uintptr_t kRecStride = 0xc;
constexpr std::uint32_t kKeyMouseMiddle = 89;

// Sym::g_MouseState, the cursor record the game's UI update writes: f32 x, y at
// +0x00/+0x04, f32 width, height at +0x20/+0x24. Read whole, 0x28 bytes.
struct MouseState {
    float x, y, dx, dy, nx, ny, ndx, ndy, w, h;
};
static_assert(sizeof(MouseState) == 0x28, "g_MouseState is 0x28 bytes");
// Past this a coordinate is not a cursor: the record moved or is not set up yet.
constexpr float kPosLimit = 1.0e6f;

using Poll_fn = void (*)(void* mgr, const void* frame_time);
Poll_fn g_real = nullptr;
std::uintptr_t g_poll_va = 0;
std::uintptr_t g_rec_up = 0;
std::uintptr_t g_rec_down = 0;
std::uintptr_t g_rec_middle = 0;
std::uintptr_t g_mouse_state = 0;

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

// --- middle-button drag -------------------------------------------------------
//
// Everything below the atomics is game-thread state: only the poll detour
// touches it.

std::atomic<bool> g_drag_armed{false};
std::atomic<bool> g_drag_held{false};
std::atomic<float> g_drag_x{0.f}, g_drag_y{0.f}, g_drag_w{0.f}, g_drag_h{0.f};
std::atomic<std::uint64_t> g_drag_starts{0};
std::atomic<double> g_drag_sum_dx{0.0}, g_drag_sum_dy{0.0};   // single writer: the poll
std::atomic<bool> g_logged_drag{false};

enum Phase : std::uint8_t { kStart, kMove, kEnd };
constexpr const char* kPhaseName[] = {"start", "move", "end"};

struct DragItem {
    Phase phase;
    bool blocked;
    float dx, dy, x, y, w, h;
};

// Ordered backlog for Lua: start / move / end, consecutive moves merged. 16
// covers several clicks while the Lua lock is busy; overflow resyncs instead.
constexpr int kQueueCap = 16;
DragItem g_queue[kQueueCap];
int g_qlen = 0;

bool g_dragging = false;   // the game reports the middle button held
bool g_have_last = false;  // g_last_* hold a good position for this drag
float g_last_x = 0.f, g_last_y = 0.f;
bool g_queueing = false;   // this drag began with a handler: queue its items
bool g_lua_held = false;   // what Lua was last told: inside a drag or not
MouseState g_pos{};        // newest good read
bool g_pos_ok = false;

bool read_pos() {
    MouseState s{};
    if (!mem_load(g_mouse_state, &s)) return false;
    for (float v : {s.x, s.y, s.w, s.h})
        if (!std::isfinite(v) || std::fabs(v) > kPosLimit) return false;
    g_pos = s;
    g_pos_ok = true;
    g_drag_x.store(s.x, std::memory_order_relaxed);
    g_drag_y.store(s.y, std::memory_order_relaxed);
    g_drag_w.store(s.w, std::memory_order_relaxed);
    g_drag_h.store(s.h, std::memory_order_relaxed);
    return true;
}

DragItem item(Phase p, bool blocked, float dx = 0.f, float dy = 0.f) {
    return DragItem{p, blocked, dx, dy, g_pos.x, g_pos.y, g_pos.w, g_pos.h};
}

void push_raw(const DragItem& it) {
    if (g_qlen < kQueueCap) g_queue[g_qlen++] = it;
}

// Queue full: replace the backlog with the shortest sequence that takes Lua
// from what it was last told to the current state.
void resync(bool blocked) {
    g_qlen = 0;
    if (g_lua_held) push_raw(item(kEnd, blocked));
    if (g_dragging && g_queueing) push_raw(item(kStart, blocked));
}

void push(const DragItem& it) {
    if (!g_queueing) return;
    if (it.phase == kMove && g_qlen > 0 && g_queue[g_qlen - 1].phase == kMove) {
        DragItem& tail = g_queue[g_qlen - 1];
        tail.dx += it.dx;
        tail.dy += it.dy;
        tail.x = it.x; tail.y = it.y; tail.w = it.w; tail.h = it.h;
        tail.blocked = it.blocked;
        return;
    }
    if (g_qlen == kQueueCap) {
        resync(it.blocked);
        return;
    }
    g_queue[g_qlen++] = it;
}

void drag_move(bool blocked) {
    if (!read_pos()) return;   // no movement this frame; the next good read catches up
    if (!g_have_last) {
        g_last_x = g_pos.x; g_last_y = g_pos.y; g_have_last = true;
        return;
    }
    const float dx = g_pos.x - g_last_x, dy = g_pos.y - g_last_y;
    if (dx == 0.f && dy == 0.f) return;
    g_last_x = g_pos.x; g_last_y = g_pos.y;
    g_drag_sum_dx.store(g_drag_sum_dx.load(std::memory_order_relaxed) + dx, std::memory_order_relaxed);
    g_drag_sum_dy.store(g_drag_sum_dy.load(std::memory_order_relaxed) + dy, std::memory_order_relaxed);
    push(item(kMove, blocked, dx, dy));
}

void drag_begin(bool blocked) {
    g_dragging = true;
    g_drag_held.store(true, std::memory_order_relaxed);
    g_drag_starts.fetch_add(1, std::memory_order_relaxed);
    g_have_last = read_pos();
    if (g_have_last) { g_last_x = g_pos.x; g_last_y = g_pos.y; }
    // A drag that starts with nobody listening is not queued at all, so a mod
    // that subscribes mid-drag never gets a move without its start.
    g_queueing = script_has_handler(kDragEvent);
    push(item(kStart, blocked));
    hook_note_fire(g_poll_va);
    if (!g_logged_drag.exchange(true)) {
        char line[128];
        std::snprintf(line, sizeof(line), "[input] first middle drag seen on thread %lu",
                      static_cast<unsigned long>(GetCurrentThreadId()));
        Loader::get().log(line);
    }
}

void drag_end(bool blocked) {
    // Cleared before the push, so an overflow resync sees the drag as over.
    g_dragging = false;
    g_have_last = false;
    g_drag_held.store(false, std::memory_order_relaxed);
    push(item(kEnd, blocked));
}

void try_deliver_drag() {
    if (!script_has_handler(kDragEvent)) {
        g_qlen = 0;
        g_queueing = false;
        g_lua_held = false;
        return;
    }
    int sent = 0;
    for (; sent < g_qlen; ++sent) {
        const DragItem& it = g_queue[sent];
        char json[320];
        std::snprintf(json, sizeof(json),
                      "{\"phase\":\"%s\",\"button\":\"middle\",\"dx\":%.3f,\"dy\":%.3f,"
                      "\"x\":%.3f,\"y\":%.3f,\"w\":%.3f,\"h\":%.3f,\"blocked\":%s}",
                      kPhaseName[it.phase], it.dx, it.dy, it.x, it.y, it.w, it.h,
                      it.blocked ? "true" : "false");
        // Lua lock busy: the rest waits, in order, for a later poll.
        if (!script_try_emit_event_json(kDragEvent, json)) break;
        if (it.phase == kStart) g_lua_held = true;
        else if (it.phase == kEnd) g_lua_held = false;
    }
    if (sent == 0) return;
    for (int i = sent; i < g_qlen; ++i) g_queue[i - sent] = g_queue[i];
    g_qlen -= sent;
}

void drag_on_poll() {
    std::uint8_t flags = 0;
    // An unreadable record counts as released: an open drag ends.
    const bool held = mem_load(g_rec_middle, &flags) && (flags & kHeld);
    const bool blocked = (flags & kBlocked) != 0;
    if (held && !g_dragging) {
        drag_begin(blocked);
    } else if (held) {
        drag_move(blocked);
    } else if (g_dragging) {
        drag_move(blocked);   // the movement up to the release frame
        drag_end(blocked);
    }
    if (g_qlen > 0) try_deliver_drag();
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
        // poll's skip branch) leaves the record as it was, and the notch is lost
        // for the game's readers too.
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

    if (g_drag_armed.load(std::memory_order_relaxed)) drag_on_poll();
}

} // namespace

bool input_armed() { return g_armed.load(std::memory_order_acquire); }

void input_wheel_totals(std::uint64_t* up, std::uint64_t* down) {
    if (up) *up = g_up.load(std::memory_order_relaxed);
    if (down) *down = g_down.load(std::memory_order_relaxed);
}

bool input_drag_armed() { return g_drag_armed.load(std::memory_order_acquire); }

bool input_drag_state(InputDragState* out) {
    if (!out || !input_drag_armed()) return false;
    out->held = g_drag_held.load(std::memory_order_relaxed);
    out->x = g_drag_x.load(std::memory_order_relaxed);
    out->y = g_drag_y.load(std::memory_order_relaxed);
    out->w = g_drag_w.load(std::memory_order_relaxed);
    out->h = g_drag_h.load(std::memory_order_relaxed);
    out->drags = g_drag_starts.load(std::memory_order_relaxed);
    out->dx = g_drag_sum_dx.load(std::memory_order_relaxed);
    out->dy = g_drag_sum_dy.load(std::memory_order_relaxed);
    return true;
}

bool install_input_hooks() {
    // Fail closed on an unfingerprinted build: the button records and the
    // cursor record are raw VAs, and on another build they name other bytes.
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
    if (!ok) return false;

    // The middle drag rides on the same detour. Its records failing to read
    // leaves the wheel working and only the drag off.
    g_rec_middle = rebase(Sym::g_InputKeyRecords) + kKeyMouseMiddle * kRecStride;
    g_mouse_state = rebase(Sym::g_MouseState);
    MouseState ms{};
    if (mem_load(g_rec_middle, &probe) && mem_load(g_mouse_state, &ms)) {
        g_drag_armed.store(true, std::memory_order_release);
    } else {
        Loader::get().log("[input] middle drag not armed: the middle-button or cursor "
                          "record is not readable");
    }
    return true;
}

} // namespace rsmm
