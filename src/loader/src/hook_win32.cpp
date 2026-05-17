// Win32 input hook removed.
//
// The overlay has been deleted, so this module now keeps the input-hook
// entry points as harmless no-ops to preserve the rest of the loader.

#define WIN32_LEAN_AND_MEAN
#include <windows.h>

#include "loader.h"
#include "hook_win32.h"

namespace rsmm {

namespace {

} // namespace

void install_input_hook() {
    Loader::get().log("input: overlay removed; input hook disabled");
}

void remove_input_hook() {
    // no-op
}

void input_imgui_new_frame() {
    // no-op
}

bool input_should_capture() {
    return false;
}

} // namespace rsmm
