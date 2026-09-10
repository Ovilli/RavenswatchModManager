#pragma once
// Level-build trace — which of the three silent paths leaves a level EMPTY.
// OPT-IN: off unless RSMM_ENABLE_LEVEL_BUILD_TRACE=1.
//
// THE QUESTION
// ------------
// A mod-owned tile level is PLACED, its resource RESOLVES, and none of its
// objects are instantiated — not even the shipped ones it inherited from its
// donor. Measured 2026-09-10: 5 mod tiles in one map, and the donor's
// `Health_Fountain` (which that level places exactly once, and which only that
// one shipped tile places in the whole chapter) resolved ZERO extra times.
//
// WHERE IT IS DECIDED
// -------------------
// `FUN_1407466b0` builds one level in four calls. After LevelStream_LoadStep
// succeeds it calls the gate this file hooks:
//
//     gate(db, level, 0)   false -> the level is DESTROYED and the slot nulled
//                          true  -> the level is kept at [owner+0x68]
//
// and inside the gate, after appending the level to the database vector:
//
//     accept = FUN_14047c930(...)          ; refuse -> jump PAST the loop
//     n      = *(u32*)(level + 0xc8)       ; object count
//     for i in 0..n:  elem = *(void**)(level + 0xc0) + i*0x38
//         if ((*(u32*)(db + 0xa0) & *(u32*)(elem + 0x30)) == 0) continue;  // SKIP
//         LevelObject_LoadOrCreate(...)
//
// Three ways out, all silent, none logged by the engine and none faulting:
//   (1) the accept check refuses and the loop never runs;
//   (2) the count is 0, so there is nothing to walk;
//   (3) every element fails the mask test and is skipped one by one.
//
// WHAT IT LOGS
// ------------
// Per call: the object count BEFORE the real gate runs, the database's mask,
// and the gate's verdict after. That separates all three in a single run:
//
//   count 0                      -> (2) the level deserialized no objects
//   count > 0 and verdict false  -> (1) refused, and the level was destroyed
//   count > 0 and verdict true   -> (3) kept, so the objects were SKIPPED
//                                   one by one and the mask is the next read
//
// ⚠ `test` always clears CF, so the engine's `jbe` is really `je`: an object is
// skipped when the AND is ZERO. Stride 0x38 is the size of a resource REF BLOCK
// (see hook_resource.cpp), which puts +0x30 exactly where `resolvedPtr` lives —
// so (3) may be "this object's resource never resolved", i.e. the documented
// null-preload failure seen from the skip side rather than the crash side.
// This detour does not assume either reading; it reports the numbers.
//
// COST
// ----
// One extra call per LEVEL BUILD — a few hundred per chapter at most, not the
// ~90,000 of the resource trace — and every read is page-guarded, so a
// half-built level degrades to `<unread>` rather than faulting the game.

namespace rsmm {

// Install the level-build trace. Returns true only when armed AND the detour
// is live; a disabled trace logs plainly, because "the user did not arm it" is
// not a fault.
bool install_levelbuild_hooks();

}  // namespace rsmm
