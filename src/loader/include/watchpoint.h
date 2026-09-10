// Hardware WRITE/READ watchpoints — "who wrote this byte".
//
// THE GAP THIS FILLS. Every other instrument here answers "what happened":
// `hook_util` intercepts a function you can already name, `mem_safe` reads a
// field you already found, `R.debug.dump` walks a struct you already have.
// None of them answers the question that actually costs the sessions — a value
// changed and NOTHING in the map says who changed it. The usual answers (rr,
// gdb) do not exist for this target: it is a Windows PE under Proton, rr does
// not support Wine and serialises threads onto one core, and gdb sees Wine's
// frames rather than the game's.
//
// x86-64 already has the mechanism in silicon. DR0-DR3 hold four addresses,
// DR7 arms them with a length and an access type, and the CPU raises
// STATUS_SINGLE_STEP on the instruction AFTER the access, with the faulting
// RIP in the thread context. A vectored exception handler reads it and the
// loader's own symbol map turns that RIP into a function name. No new
// toolchain, no ptrace, no second process.
//
// FOUR SLOTS, TOTAL. Not a budget to spend casually — this is a bisection
// instrument, not a tracer.
//
// PER-THREAD, and that is the sharp edge. Debug registers live in the thread
// context, so arming means walking every thread in the process; a thread
// CREATED after arming has none, which is why `watch_rearm` exists and why the
// count of armed threads is reported rather than assumed.
//
// OFF UNLESS ARMED (`RSMM_ENABLE_WATCH=1`). A process-wide vectored handler
// plus debug registers is exactly the shape an anti-tamper check looks for, and
// this game has anti-tamper logic (see the architecture notes). Debugging tool,
// opt-in, never on in a normal session.
#pragma once

#include <cstdint>
#include <string>
#include <vector>

namespace rsmm {

//: One recorded access. `rip` is the instruction AFTER the access — the CPU
//: reports a trap, not a fault — so the writer is the instruction ending there.
struct WatchHit {
    std::uint64_t seq;
    std::uintptr_t rip;
    std::uintptr_t addr;
    std::uint32_t tid;
    int slot;
};

//: Access kinds, in DR7's own encoding (there is no execute-only kind that is
//: useful here; a code breakpoint is what `hook_install` is for).
enum class WatchKind { Write = 1, ReadWrite = 3 };

//: Arm `addr` across every thread. `len` must be 1, 2, 4 or 8 AND `addr` must
//: be aligned to it — the CPU requires it, and a misaligned watchpoint silently
//: never fires. Returns the slot (0-3), or -1 with `err` set.
int watch_set(std::uintptr_t addr, int len, WatchKind kind, std::string& err);

//: Disarm one slot everywhere, or every slot when `slot < 0`.
bool watch_clear(int slot);

//: Re-apply the current slots to every thread, picking up threads created
//: since. Returns how many threads were armed.
int watch_rearm();

//: Take and clear the recorded hits.
std::vector<WatchHit> watch_drain();

//: `{slot, addr, len, kind, hits}` for each armed slot, for reporting.
struct WatchSlot {
    std::uintptr_t addr;
    int len;
    WatchKind kind;
    std::uint64_t hits;
    bool armed;
};
std::vector<WatchSlot> watch_status();

//: True once the vectored handler is installed. Installed lazily by the first
//: `watch_set`, so an unused capability costs nothing.
bool watch_active();

}  // namespace rsmm
