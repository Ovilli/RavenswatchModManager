#pragma once
// Capture of the GLOBAL entity-value scene context.
//
// WHY THIS EXISTS
// ---------------
// The engine computes ~117 named gameplay values and files each one under a
// 32-bit key. `EntityValueRegistry_RegisterAll` and three sibling routines
// declare them with a display name and a category, and the full harvested
// table is recorded on the `g_GlobalEntityValueSceneContext_Tester_vftable`
// symbol in data/symbols.json.
//
// R.stat already reads the HERO's slice of this system. Everything that is not
// about one hero -- "Is in sandman shop", "Reroll count", "Current chapter",
// "Is in overtime", "Is boss awaken", "Active Enemies Count", "Is Session
// Host", "Revive token" -- lives in a different context entirely, the one whose
// RTTI name is oCGlobalEntityValueSceneContext, and nothing in the loader had
// a pointer to it. Mods therefore inferred all of the above from whatever
// gameplay event came closest, which is how the challenge tracker in
// mods/saga ended up with four separate documented blind spots.
//
// HOW IT IS CAPTURED
// ------------------
// Not by constructing anything. The game reaches that context by
// stack-building an oCTKindOfTypeTester<oCGlobalEntityValueSceneContext,
// oIGameSceneContext> and calling GameScene_FindContextByTester; it does this
// every time it writes one of those values, which is constantly. So the detour
// sits on the lookup itself and keeps the RESULT whenever the tester passed in
// is that one -- identified by its vftable, which is the first qword of a
// stack-constructed tester.
//
// This is deliberately the cheapest possible intervention: no scene pointer to
// find, no tester to build, no call made by us, and nothing written. The
// detour's only side effect is storing a pointer the game just computed.
//
// WHAT IT DOES *NOT* DO
// ---------------------
// It does not read a value. Which reader is correct for this context is an
// open question -- the hero path goes through `EntityValue_Get`, which
// dereferences `ctx + 0x4c8` to find the store, while the game's own writers
// for these keys pass the looked-up pointer straight into a routine that uses
// it with store-shaped offsets (+0x78, +0x98, +0xe0). Those two cannot both be
// right, and picking wrong means handing a garbage store to a hash-map walk
// that has no bound of its own -- the exact shape of crash dump 434d75a5.
//
// So the shape question is answered on the Lua side, at runtime, by probing
// both layouts behind page-guarded reads before any engine call is made. See
// R.game in the SDK. This file's job ends at publishing the pointer.
namespace rsmm {

// Detour GameScene_FindContextByTester and publish the global entity-value
// context as the game looks it up. Returns true only when the hook is live.
bool install_gamevalue_capture();

// Drop the published context when the scene it belongs to is torn down.
// Takes the dispatched event name and filters on it -- see the definition
// for why that filter is not optional.
void drop_global_value_ctx(const char* ev_name);

} // namespace rsmm
