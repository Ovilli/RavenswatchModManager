// Hardware watchpoints via DR0-DR3 + a vectored exception handler.
// See watchpoint.h for why this exists and what it costs.

#include <windows.h>
#include <tlhelp32.h>

#include <atomic>
#include <cstdio>
#include <mutex>
#include <vector>

#include "loader.h"
#include "watchpoint.h"

namespace rsmm {
namespace {

constexpr int kSlots = 4;
// A ring, not a log. A watchpoint on a hot field fires thousands of times a
// second; keeping the FIRST N and a count is what makes the report readable,
// and the first hit is the one that names the writer anyway.
constexpr std::size_t kMaxHits = 256;

struct Slot {
    std::uintptr_t addr = 0;
    int len = 0;
    WatchKind kind = WatchKind::Write;
    std::atomic<std::uint64_t> hits{0};
    bool armed = false;
};

Slot g_slots[kSlots];
std::mutex g_mu;                       // guards g_slots' non-atomic fields
std::mutex g_hits_mu;
std::vector<WatchHit> g_hits;
std::atomic<std::uint64_t> g_seq{0};
PVOID g_veh = nullptr;

// DR7 encoding, per Intel SDM Vol 3B 17.2.4:
//   bit 2n       local enable for slot n
//   bits 16+4n   R/W  (01 = data write, 11 = data read-or-write)
//   bits 18+4n   LEN  (00 = 1 byte, 01 = 2, 11 = 4, 10 = 8)
// LEN 10 (8 bytes) is the encoding that reads as "2 bytes" if you assume the
// field is just (len-1); it is not, and getting it wrong arms a watchpoint on
// the wrong span rather than failing.
int len_bits(int len) {
    switch (len) {
        case 1: return 0b00;
        case 2: return 0b01;
        case 4: return 0b11;
        case 8: return 0b10;
        default: return -1;
    }
}

std::uint64_t build_dr7() {
    std::uint64_t dr7 = 0;
    for (int i = 0; i < kSlots; ++i) {
        if (!g_slots[i].armed) continue;
        dr7 |= (1ull << (2 * i));                                    // L<i>
        dr7 |= (static_cast<std::uint64_t>(g_slots[i].kind) << (16 + 4 * i));
        dr7 |= (static_cast<std::uint64_t>(len_bits(g_slots[i].len)) << (18 + 4 * i));
    }
    return dr7;
}

void apply_to_context(CONTEXT& c) {
    c.Dr0 = g_slots[0].armed ? g_slots[0].addr : 0;
    c.Dr1 = g_slots[1].armed ? g_slots[1].addr : 0;
    c.Dr2 = g_slots[2].armed ? g_slots[2].addr : 0;
    c.Dr3 = g_slots[3].armed ? g_slots[3].addr : 0;
    c.Dr6 = 0;
    c.Dr7 = build_dr7();
}

// Arm one thread. The CALLING thread is handled without suspending it:
// SuspendThread on self deadlocks, while Get/SetThreadContext for debug
// registers is serviced against the kernel's saved context and works. Every
// other thread is suspended around the update, or the context written back can
// be one the scheduler has already moved past.
bool arm_thread(DWORD tid) {
    const bool self = (tid == GetCurrentThreadId());
    HANDLE h = OpenThread(
        THREAD_GET_CONTEXT | THREAD_SET_CONTEXT | THREAD_SUSPEND_RESUME, FALSE, tid);
    if (!h) return false;

    if (!self && SuspendThread(h) == static_cast<DWORD>(-1)) {
        CloseHandle(h);
        return false;
    }

    CONTEXT c{};
    c.ContextFlags = CONTEXT_DEBUG_REGISTERS;
    bool ok = GetThreadContext(h, &c) != 0;
    if (ok) {
        apply_to_context(c);
        c.ContextFlags = CONTEXT_DEBUG_REGISTERS;
        ok = SetThreadContext(h, &c) != 0;
    }

    if (!self) ResumeThread(h);
    CloseHandle(h);
    return ok;
}

int arm_all_threads() {
    HANDLE snap = CreateToolhelp32Snapshot(TH32CS_SNAPTHREAD, 0);
    if (snap == INVALID_HANDLE_VALUE) return 0;

    const DWORD pid = GetCurrentProcessId();
    THREADENTRY32 te{};
    te.dwSize = sizeof(te);
    int armed = 0;
    if (Thread32First(snap, &te)) {
        do {
            // dwSize is the documented way to know th32OwnerProcessID was
            // actually filled in; older kernels short-fill the struct.
            if (te.dwSize >= FIELD_OFFSET(THREADENTRY32, th32OwnerProcessID)
                                 + sizeof(te.th32OwnerProcessID)
                && te.th32OwnerProcessID == pid
                && arm_thread(te.th32ThreadID)) {
                ++armed;
            }
            te.dwSize = sizeof(te);
        } while (Thread32Next(snap, &te));
    }
    CloseHandle(snap);
    return armed;
}

LONG CALLBACK veh(EXCEPTION_POINTERS* ep) {
    if (ep->ExceptionRecord->ExceptionCode != EXCEPTION_SINGLE_STEP) {
        return EXCEPTION_CONTINUE_SEARCH;
    }
    // DR6 low four bits say which slot fired. A single-step that is NOT ours
    // (a debugger, an engine anti-tamper probe) must pass straight through, or
    // this handler silently eats someone else's exception.
    const std::uint64_t dr6 = ep->ContextRecord->Dr6;
    const int slot = (dr6 & 1) ? 0 : (dr6 & 2) ? 1 : (dr6 & 4) ? 2 : (dr6 & 8) ? 3 : -1;
    if (slot < 0) return EXCEPTION_CONTINUE_SEARCH;

    g_slots[slot].hits.fetch_add(1, std::memory_order_relaxed);
    {
        std::lock_guard<std::mutex> lk(g_hits_mu);
        if (g_hits.size() < kMaxHits) {
            g_hits.push_back(WatchHit{
                g_seq.fetch_add(1, std::memory_order_relaxed),
                static_cast<std::uintptr_t>(ep->ContextRecord->Rip),
                g_slots[slot].addr,
                GetCurrentThreadId(),
                slot,
            });
        }
    }

    // Consume the status bits, or the next trap reports this slot as well.
    ep->ContextRecord->Dr6 = 0;
    return EXCEPTION_CONTINUE_EXECUTION;
}

}  // namespace

bool watch_active() { return g_veh != nullptr; }

int watch_set(std::uintptr_t addr, int len, WatchKind kind, std::string& err) {
    if (!flag_enabled("RSMM_ENABLE_WATCH")) {
        err = "watchpoints are off (set RSMM_ENABLE_WATCH=1). They install a "
              "process-wide exception handler and use the CPU debug registers, "
              "which is what an anti-tamper check looks for — opt-in only.";
        return -1;
    }
    if (len_bits(len) < 0) {
        err = "length must be 1, 2, 4 or 8";
        return -1;
    }
    if (addr == 0 || (addr % static_cast<std::uintptr_t>(len)) != 0) {
        // The CPU requires natural alignment and gives no diagnostic for a
        // misaligned one: it simply never fires, which reads as "nothing wrote
        // it" — the single most misleading answer this tool could give.
        err = "address must be non-zero and aligned to its length";
        return -1;
    }

    std::lock_guard<std::mutex> lk(g_mu);
    int slot = -1;
    for (int i = 0; i < kSlots; ++i) {
        if (!g_slots[i].armed) { slot = i; break; }
    }
    if (slot < 0) {
        err = "all 4 hardware watchpoints are in use; clear one first";
        return -1;
    }

    if (!g_veh) {
        // FIRST in the chain: this handler must see the trap before anything
        // that might swallow it, and it declines everything that is not ours.
        g_veh = AddVectoredExceptionHandler(1, &veh);
        if (!g_veh) {
            err = "AddVectoredExceptionHandler failed";
            return -1;
        }
    }

    g_slots[slot].addr = addr;
    g_slots[slot].len = len;
    g_slots[slot].kind = kind;
    g_slots[slot].hits.store(0, std::memory_order_relaxed);
    g_slots[slot].armed = true;

    const int n = arm_all_threads();
    char line[256];
    std::snprintf(line, sizeof(line),
                  "[watch] slot %d armed on %#llx len %d (%s) across %d thread(s)",
                  slot, static_cast<unsigned long long>(addr), len,
                  kind == WatchKind::Write ? "write" : "read/write", n);
    Loader::get().log(line);
    if (n == 0) {
        // Armed in the table and on nothing real. Say so: a watchpoint that
        // reports no hits because it reached no thread is indistinguishable
        // from one that reports no hits because nothing wrote.
        Loader::get().log_warn("[watch] armed ZERO threads — no hit can be "
                               "reported; the slot is set but inert");
    }
    return slot;
}

bool watch_clear(int slot) {
    std::lock_guard<std::mutex> lk(g_mu);
    if (slot >= kSlots) return false;
    for (int i = 0; i < kSlots; ++i) {
        if (slot < 0 || i == slot) g_slots[i].armed = false;
    }
    arm_all_threads();
    // The VEH stays installed on purpose: removing and re-adding it on every
    // clear/set cycle is a window in which another handler can take priority 1.
    return true;
}

int watch_rearm() {
    std::lock_guard<std::mutex> lk(g_mu);
    return arm_all_threads();
}

std::vector<WatchHit> watch_drain() {
    std::lock_guard<std::mutex> lk(g_hits_mu);
    std::vector<WatchHit> out;
    out.swap(g_hits);
    return out;
}

std::vector<WatchSlot> watch_status() {
    std::lock_guard<std::mutex> lk(g_mu);
    std::vector<WatchSlot> out;
    for (int i = 0; i < kSlots; ++i) {
        out.push_back(WatchSlot{g_slots[i].addr, g_slots[i].len, g_slots[i].kind,
                                g_slots[i].hits.load(std::memory_order_relaxed),
                                g_slots[i].armed});
    }
    return out;
}

}  // namespace rsmm
