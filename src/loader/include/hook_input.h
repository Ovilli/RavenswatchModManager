#pragma once
// Mouse-wheel notches and the middle-button drag from the game's own input poll.
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
// The middle button is the same story: the poll writes key record 89
// (g_InputKeyRecords) from GetAsyncKeyState(VK_MBUTTON) every frame, and only
// the UI reads it. The cursor lives in g_MouseState, which the game's UI update
// refreshes from WM_MOUSEMOVE. A drag is "record 89 held" plus "the cursor
// moved", both game state.
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
//
// After the original, the same detour reads record 89's held bit and
// g_MouseState's x/y. While held, the difference between two polls' positions
// is the drag's movement (the record's own dx/dy is rewritten only when the UI
// update runs, so reading it every poll could count a frame twice). Delivered
// in order as "input:drag" {phase = start|move|end, dx, dy, x, y, w, h,
// blocked, button = "middle"}, consecutive moves merged, same non-blocking rule.
#include <cstdint>

namespace rsmm {

// Detour Input_Poll. Gated on va_globals_trusted() (the wheel records are VA
// globals). Returns true only when the hook is live. The drag arms with it when
// the middle record and g_MouseState read; if they do not, the wheel still works.
bool install_input_hooks();

// True once the poll detour is live.
bool input_armed();

// Running totals of counted notches since launch.
void input_wheel_totals(std::uint64_t* up, std::uint64_t* down);

// True once the middle drag is armed (the poll detour is live and both records read).
bool input_drag_armed();

struct InputDragState {
    bool held;              // the game reports the middle button held
    float x, y, w, h;       // the game's cursor and client size, newest good read
    std::uint64_t drags;    // drags started since launch
    double dx, dy;          // total movement while held since launch, pixels
};

// Fills `out` and returns true when the drag is armed.
bool input_drag_state(InputDragState* out);

} // namespace rsmm
