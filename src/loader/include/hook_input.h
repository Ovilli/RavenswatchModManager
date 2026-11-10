#pragma once
// Mouse-wheel notches from the game's own input poll.
//
// WHY THIS EXISTS
// ---------------
// The game reads the wheel, but only for UI: the window procedure stores +1 or
// -1 on the input manager (+0xa0), and the per-frame poll (Input_Poll) turns it
// into two virtual buttons (g_InputMouseWheelUp / g_InputMouseWheelDown) that
// read "pressed" for exactly one frame. Nothing in a run listens to them unless
// the player rebinds an action to the wheel. A Lua tick (500 ms) samples far
// too rarely to see a one-frame press, so a notch has to be counted on the
// frame it happens.
//
// HOW
// ---
// A detour on Input_Poll reads +0xa0 before the original consumes it, and
// counts a notch when the original zeroed it AND the matching record reads
// held. Nothing is written and nothing is swallowed: the game's UI keeps
// getting every notch. Counted notches are delivered as the Lua event
// "input:wheel" {steps, up, down, blocked}; steps is net notches since the last
// delivery, positive for wheel up. Delivery never blocks the game thread: when
// the Lua lock is busy the notches wait for the next frame.
#include <cstdint>

namespace rsmm {

// Detour Input_Poll. Gated on va_globals_trusted() (the wheel records are VA
// globals). Returns true only when the hook is live.
bool install_input_hooks();

// True once the poll detour is live.
bool input_armed();

// Running totals of counted notches since launch.
void input_wheel_totals(std::uint64_t* up, std::uint64_t* down);

} // namespace rsmm
