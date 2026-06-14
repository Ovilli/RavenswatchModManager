#pragma once
namespace rsmm {

// Bridges in-game gameplay events to the Lua event bus (rsmm.on_event).
//
// Each entry post-detours a verified per-event emitter function (located by
// string-xref against the shipped Ravenswatch.exe — see docs/_re/HOOKPOINTS.md
// and docs/_re/kinds/events.md) and, after the original runs, fires the
// matching Lua event via script_emit_event_json. Payloads are intentionally
// minimal/empty for now: emitting an event after the original returns is
// argument-layout-agnostic and crash-safe, whereas reading args at unverified
// offsets is not. Richer payloads land once each emitter's signature is
// confirmed in-game.
//
// In addition to that per-emitter table, install_event_hooks() arms an
// "analytics firehose": one detour on the central telemetry sink
// (Analytics_SubmitNamedEvent / FUN_1401fa470) reads the event-name arg and
// re-publishes EVERY named analytics event to the Lua bus by its raw name
// (game_start, enemy_killed, unlock_hero, ...). One hook, ~37 events, survives
// the game adding new names. Observation-grade — details in hook_events.cpp.
//
// OPT-IN: off unless RSMM_ENABLE_GAME_EVENTS=1, because the hook points are
// string-verified but not yet runtime-validated against a live game. Wired
// typed events: "level_up", "run_end".
bool install_event_hooks();
void remove_event_hooks();

// Installs the hero-capture hooks ONCE (give + gain-health handlers), publishing
// the local hero character pointer to shared slot 0. Independent of the Lua
// event bridge and of any mod's lua_State, so it survives hot-reload and never
// collides. R.entity / R.combat in rsmm.lua read the captured hero from there.
bool install_hero_capture();

} // namespace rsmm
