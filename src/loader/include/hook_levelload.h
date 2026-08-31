#pragma once
// Level-load failure trace — the decisive measurement for the chapter-2
// failure that `cross_biome` triggers. OPT-IN: off unless
// RSMM_ENABLE_LEVEL_TRACE=1.
//
// WHY THIS AND NOT THE RESOURCE TRACE
// -----------------------------------
// hook_resource.cpp hooks ResourceRef_Resolve, which fires ~90,000 times a
// session across every shader and texture in the game. It answered "is
// state != 1 unusual?" with a flat no (7113 of 90000, ~8%, in a healthy
// session) and could not say anything about the ONE resource that matters,
// because it cannot tell which resolve belongs to a level load.
//
// LevelStream_LoadStep can. It is a 0x68-byte function with exactly one job:
//
//     if (LevelLoad_ProgressTick(...) == 1)        return false;  // abort
//     if (*(u32*)(*slot + 0x38) != 1)              return false;  // state
//     return dispatch(container, *slot, lvlId, links);
//
// and its `false` is what makes LevelObject_LoadOrCreate destroy the
// half-built level, whose teardown (LevelObject_DestroyVectors) walks the
// object vector calling the generic destroy thunk with no null check — the
// observed fault at 0x1401273b6. So a failure here IS the crash's proximate
// cause, one frame above it, holding the resource that caused it.
//
// WHAT IT LOGS
// ------------
// Failures only. On a false return it reports the resource's name (+0x68),
// its state (+0x38) and flags (+0x28), and which of the two branches fired —
// state != 1, or the abort predicate (state == 1 and it still failed). A
// healthy session should print nothing at all, which makes "quiet" the
// finding rather than an ambiguity: hook armed + nothing logged means level
// loads are not failing and the black screen is downstream of this.
//
// ⚠ Read the two branches apart. LevelLoad_AbortPredicate looks INERT on this
// build (no writer of Engine+0x19 was ever found), so an abort-branch hit
// would itself be news and must not be reported as the state branch.
//
// COST
// ----
// One extra call per level-load step — a handful per chapter, not thousands —
// and the guarded reads happen only on the failure path. Unlike the resource
// trace this cannot plausibly perturb what it measures, which matters here:
// the resource trace sat on the shader path and had to be exonerated by a
// separate one-variable rerun before its evidence could be used at all.

namespace rsmm {

// Install the level-load failure trace. Returns true only when armed AND the
// detour is live; a disabled trace logs plainly, because "the user did not arm
// it" is not a fault.
bool install_levelload_hooks();

}  // namespace rsmm
