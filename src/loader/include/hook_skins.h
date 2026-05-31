#pragma once
namespace rsmm {

// Custom skin-pack roster injection.
//
// The selectable skin roster is NOT data-driven: it is a fixed table of
// 9 `oCAdditionalContent` ("SkinPack") entries built once at startup by
// FUN_1401dcae0, which writes the count as the immediate constant 9 and
// populates each 0xA0-byte entry from parallel `.rdata` arrays. The
// entries are threaded into the global additional-content manager linked
// list (head pointer DAT_141436590); UI/selection consumers walk that
// list, not the fixed array. See docs/_re/kinds/skins.md and the
// `skin-roster-hardcoded` memory.
//
// To ADD a selectable pack we POST-detour FUN_1401dcae0: after the engine
// builds its 9 entries we allocate our own standalone 0xA0 nodes (NOT in
// the fixed-capacity array, so the engine's realloc/shrink on a re-run
// can't clobber them), placement-construct each via the game's own entry
// ctor (FUN_140214bb0), fill the string members via the game's string
// assign (FUN_1405288b0), and push them onto the manager list with the
// exact insert sequence the builder uses.
//
// Opt-in: aggregates pack definitions from every enabled mod's
// `mods/<id>/skinpacks.json` (written by SDK `Mod().skinpack(...)`) plus an
// optional top-level `mods/skinpacks.json`. No defs => no-op. Each entry:
// { "name", "key" (int or "0x.."), "ac_id", "al_id", "base_id" }. Keys must
// be unique across sources. Returns true if at least one pack registered.
bool install_skin_hooks();

} // namespace rsmm
