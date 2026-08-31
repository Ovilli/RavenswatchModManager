#pragma once
// Resource-resolve trace — the dynamic half of the chapter-transition crash
// investigation. OPT-IN: off unless RSMM_ENABLE_RESOURCE_TRACE=1.
//
// WHY
// ---
// LevelStream_LoadStep bails when `*(*(resourceSlot) + 0x38) != 1`, and its
// caller LevelObject_LoadOrCreate treats that as a failed load and destroys the
// half-built level — whose teardown walks the object vector calling the generic
// destroy thunk with no null check. That is the observed fault at 0x1401273b6.
//
// The static hunt for who WRITES +0x38 dead-ended twice (see the notes on
// LevelStream_LoadStep and Engine_Singleton in data/symbols.json): the object
// is produced by a service registered at runtime from static initializers, so
// its concrete class is not statically reachable, and the field shape
// (0x30/0x38/0x3c/0x68/0x80/0x90) is far too generic to fingerprint — one
// promising "state pair" turned out to be a vector's size/capacity.
//
// So read it from the running game instead. ResourceRef_Resolve is status=ok
// with a version-resilient pattern, and it is the function that fills the very
// slot LevelStream_LoadStep then tests, so hooking it puts us on exactly the
// object in question with no pointer guessing.
//
// WHAT IT ANSWERS
//   * what the state values actually are (the enum is NOT established — "1 =
//     usable" was inferred from a single comparison);
//   * whether a value seen at a FAILING chapter transition differs from the
//     ones seen during a healthy one.
//
// ⚠ FIRST RESULT (2026-08-31, 90k resolves in one session): `state != 1` is
// ROUTINE — 7113 of 90000 (~8%), throughout a session whose chapter 1 was
// perfectly healthy, overwhelmingly state 0. So the hypothesis this hook was
// built to test — that LevelStream_LoadStep refusing on `state != 1` is the
// chapter-transition fault — is REFUTED. That refusal is ordinary control
// flow. The trace stays because the per-value histogram can still show a value
// appearing only at a failing transition, but nothing here should treat
// `state != 1` as an error.
//
// It only ever READS, through the mem_safe guards, and logs. It changes no
// engine state.

namespace rsmm {

// Install the ResourceRef_Resolve trace. Returns true only when armed AND the
// detour is live; a disabled trace is a plain log line, not a warning, because
// "the user did not arm it" is not a fault.
bool install_resource_hooks();

}  // namespace rsmm
