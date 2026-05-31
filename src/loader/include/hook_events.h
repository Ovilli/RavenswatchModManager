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
// OPT-IN: off unless RSMM_ENABLE_GAME_EVENTS=1, because the hook points are
// string-verified but not yet runtime-validated against a live game. Wired
// events: "level_up", "run_end".
bool install_event_hooks();
void remove_event_hooks();

} // namespace rsmm
