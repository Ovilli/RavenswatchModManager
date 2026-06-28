#pragma once
namespace rsmm {

// Runtime skill (talent) injection.
//
// Editing the cooked herodef to add a skill row crashes the hero: the herodef
// deserialiser (FUN_14031e630) is a strict versioned, ordered field reader, and
// a spliced node desyncs every field read after it (see
// docs/_re/kinds/skills-system.md). Instead we detour the deserialiser and grow
// the hero's runtime skill vector (herodef+0x7d0) AFTER load — the same approach
// hook_items uses for the magical-object pool. The Skill/talent menu enumerates
// that runtime vector, so an appended skill shows without touching the file.
//
// Default behaviour is READ-ONLY: it logs the skill vector (offset/count/cap)
// for each loaded herodef so the +0x7d0 offset + element layout can be confirmed
// in a play session. The mutating append is gated behind RSMM_ENABLE_SKILL_INJECT
// and only fires when the vector looks sane (plausible count + spare capacity),
// so a wrong offset can never corrupt memory.
bool install_skill_hooks();

} // namespace rsmm
