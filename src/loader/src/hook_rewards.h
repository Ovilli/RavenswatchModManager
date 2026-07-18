#pragma once
namespace rsmm {

// Reward-roll diagnostic dump.
//
// A `reward` SDK mod that empties a reward_types row (min=max=0) did NOT stop
// the banned reward objects in-game, even though the edit is byte-correct and
// installed. Static RE of the roll fn FUN_1401e9800 found TWO placement paths:
// a count-gated reward_types path (edit honoured) reading a GLOBAL reward-def
// registry, and a separate guaranteed/forced path on the scene-context def
// (ctx+0xa8) that bypasses reward_types counts. So a type-count ban misses if
// the chests come from the guaranteed path or from a registry def that isn't
// our override. See docs/_re/kinds/rewards.md.
//
// This hook is READ-ONLY. It detours the roll, and on the first fire dumps the
// reward-def registry ([begin,end) at the two baked globals) + the scene-context
// def, logging each def's reward_types shape (per type: min/max/item-count) so
// the chest-bearing def can be identified by shape (our override shows the
// emptied type as min=max=0,items=0; stock shows 3/4,items=3). Every read is
// VirtualQuery-guarded, so a wrong offset logs/skips instead of faulting.
//
// Off by default (RSMM_ENABLE_REWARD_DUMP=1 to arm); one-shot then muted.
bool install_reward_hooks();

} // namespace rsmm
