#pragma once
namespace rsmm {

// Spawn-system dynamic trace.
//
// A generic R.spawn(template, transform) is blocked on locating the runtime
// entity instantiator: it is a vtable-dispatched method on the runtime spawner
// component (oCEntityCpntEntitySpawner / oCSpawnerGoEntityCollector) whose
// vtable registration sits in code regions Ghidra leaves undefined — static RE
// is exhausted (see docs/_re/kinds/spawn-system.md). The documented next step is
// a DYNAMIC trace: detour the selector prepare virtual (FUN_140330c30, a clean
// unique pattern like hook_skills) and capture a LIVE spawner component plus its
// vtable, candidate-template vector and owning sub-object at runtime, so the
// instantiator's vtable can be mapped against the live module base in a play
// session.
//
// This hook is READ-ONLY by design. There is no mutating lever: appending a
// template entry to the SELECTOR's candidate vector (+0x68) and letting it tick
// FREES the entries — it does not spawn (the instantiating component is a
// distinct one). So the tool only logs; it never edits the spawner. Off by
// default (RSMM_ENABLE_SPAWN_HOOK=1 to arm); per-entry dump is gated again
// behind RSMM_SPAWN_TRACE_VERBOSE because prepare fires on every spawner tick.
bool install_spawn_hooks();

} // namespace rsmm
