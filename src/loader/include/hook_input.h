#pragma once
// Mouse-wheel notches, the middle-button drag and mouse-look from the game's own input poll.
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
// While the cursor lock is on the cursor is recentred every frame, so the
// position difference means nothing: no drag starts and one in progress ends.
//
// MOUSE-LOOK
// ----------
// The game's UI update (FUN_14045ab40) has a cursor-lock mode nothing turns on:
// with the lock byte set it reads the cursor, takes dx/dy against a centre
// point, and SetCursorPos()es back to the centre. The centre is two floats in
// SCREEN coordinates that nothing writes. After the original poll the detour
// writes the game window's client-area centre there and sets the lock byte while
// a mod has requested it (R.input.mouse_look), and posts the game's own dx/dy
// from g_MouseState as "input:mouse_move" {dx, dy, x, y, w, h, locked, blocked}
// (merged when the Lua lock is busy). The lock is released (byte 0, cursor
// shown) whenever the request is off, a menu is open (Lua reports it), or the
// game window is not the foreground window.
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

// True once mouse-look can run: the poll detour is live and the lock byte, the
// centre floats and the cursor record are all readable and writable.
bool input_look_armed();

// Request mouse-look on or off (any thread). `hide` also hides the OS cursor
// while the lock is engaged. Returns false when it is not armed. The game
// thread applies it on its next poll. A request lapses after a few seconds
// unless input_look_refresh() or another request keeps it alive, so a mod whose
// Lua state is gone cannot leave the lock on. Returns the request's id (never 0),
// or 0 when not armed; a later request supersedes it.
std::uint64_t input_look_request(bool on, bool hide);

// Keep the request alive and tell the loader whether a game menu is open. Only
// the request `request_id` names can do this: once another request has
// superseded it the call does nothing. 0 means "no id" (an older SDK) and
// always applies.
void input_look_refresh(bool menu_open, std::uint64_t request_id);

struct InputLookState {
    bool requested;   // a mod asked for it
    bool active;      // the lock is engaged right now
    bool paused;      // requested but released (menu open, or the game is not foreground)
    bool hidden;      // the OS cursor is hidden by us
};

// Fills `out` and returns true when armed.
bool input_look_state(InputLookState* out);

// Unload: asks the game thread (next poll) to release - lock byte 0, cursor shown -
// and waits up to 250 ms; falls back to clearing the byte from the caller.
void input_look_shutdown();

} // namespace rsmm
