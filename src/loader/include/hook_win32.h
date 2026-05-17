#pragma once
namespace rsmm {

// Subclasses the game window's WndProc so ImGui receives mouse/keyboard
// input. Idempotent: subsequent calls find the window if it didn't exist
// at first install time and complete the subclass.
void install_input_hook();
void remove_input_hook();

// Called once per frame from the Vulkan present hook.
void input_imgui_new_frame();

// Lets other hooks know whether input should be eaten before the game sees it.
bool input_should_capture();

} // namespace rsmm
