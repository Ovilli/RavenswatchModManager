#pragma once
// One guarded path for installing a detour. Use this instead of calling
// fn_resolve / fn_verify / MH_CreateHook / MH_EnableHook by hand.
//
// WHY THIS EXISTS
// ---------------
// Nine hook_*.cpp files each hand-rolled the same four-step sequence, 26 call
// sites in total, and they had drifted apart exactly the way the five copies
// of `readable()` did before mem_safe.h consolidated them:
//
//   * only two of the nine checked that the resolved address is a FUNCTION
//     START. The rest would splice a jump into the middle of a live function
//     if a pattern from an older build happened to match there — which is not
//     hypothetical: the analytics firehose, armed by default on every install,
//     was doing precisely that (0x8d0 bytes inside an unrelated function), and
//     hook_skins.cpp's five targets were all wrong the same way (its symbols
//     were relocated on 2026-08-09 and it now resolves through `Sym::`).
//     `fn_verify` cannot catch it, because the recorded bytes genuinely ARE at
//     that address; only the module's .pdata table knows where functions begin.
//   * several skipped fn_verify entirely, so a patched game got a detour on
//     whatever now lives at the address.
//   * MH_EnableHook failures were silently ignored in some files, leaving a
//     created-but-inactive hook registered against soon-to-be-unmapped code.
//   * every file logged in its own format, so a user's log could not be read
//     uniformly to see which hooks armed.
//
// The failure mode this prevents is the worst one the loader has: a detour on
// a non-entry-point does not intercept a call, it CORRUPTS the function it
// lands in, and the crash surfaces somewhere unrelated much later.
//
// Everything here fails CLOSED: any check that cannot be completed returns
// false and the hook is not installed.

#include <cstdint>
#include <string_view>

namespace rsmm {

// Resolve `pattern_name`, prove it still matches and that it is a real
// function entry, then create AND enable a detour on it.
//
//   tag         short subsystem name for the log, e.g. "gameplay-events"
//   what        human name of the target, e.g. "roster builder"
//   pattern_name  SEMANTIC pattern key — prefer Sym::<Name>_Pattern over a
//                 literal "FUN_<addr>", which is an address from whatever
//                 build the code was written against and survives only as a
//                 legacy alias in the pattern DB.
//   detour      your replacement function
//   trampoline  receives the original; may be null for a pure prepend hook
//   out_va      optionally receives the resolved address
//
// Returns true only when the hook is live.
bool hook_install(std::string_view tag, std::string_view what,
                  std::string_view pattern_name, void* detour,
                  void** trampoline, std::uintptr_t* out_va = nullptr);

// How hard to insist the target is a .pdata entry point.
enum class EntryCheck {
    // Refuse to hook anything .pdata does not list. Correct for every
    // engine-internal hook: those targets are large routines that always
    // carry unwind data, so an absent entry means the address is wrong.
    Require,
    // Log and continue. For addresses a MOD supplies through rsmm.hook: x64
    // may legitimately omit a true leaf function (no stack frame, no calls)
    // from the exception table, so refusing outright would break a valid
    // hook, and the mod author owns that risk. The warning still names the
    // address, which is what turns "the game crashed" into "your hook target
    // is not a function".
    Warn,
};

// Same guarantees as hook_install, but for an address you already hold (a
// vtable slot, a pointer captured at runtime, a mod-supplied VA). There is no
// pattern to verify, so the .pdata check is the only one available — and it is
// the check that matters.
bool hook_install_at(std::string_view tag, std::string_view what,
                     std::uintptr_t va, void* detour, void** trampoline,
                     EntryCheck check = EntryCheck::Require);

// Resolve a function you intend to CALL rather than hook. Same resolve +
// verify + entry-point checks; a mid-function address is just as wrong as a
// call target as it is as a hook target (hook_skins.cpp's "vec_grow" resolved
// to an aligned-array DEALLOCATOR, which would have freed the caller's array).
bool resolve_checked(std::string_view tag, std::string_view what,
                     std::string_view pattern_name, void** out);

// Disable + remove a hook installed above. Safe on 0.
void hook_remove(std::uintptr_t va);

// The entry-point check on its own, for the one caller that cannot use the
// helpers above: hook_lua must set its slot's `installed` flag BETWEEN
// MH_CreateHook and MH_EnableHook (the other order let the game enter a detour
// while the flag was still false, and the dispatcher's answer to that is
// "return 0 without calling the original" — the hooked function silently did
// nothing on its first call). Returns true if the hook may proceed; logs on a
// non-entry-point target but does not refuse, because the address comes from a
// mod. See EntryCheck::Warn.
bool hook_entry_warn(std::string_view tag, std::string_view what,
                     std::uintptr_t va);

} // namespace rsmm
