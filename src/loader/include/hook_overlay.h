#pragma once
namespace rsmm {

// In-game overlay (Dear ImGui drawn on the game's own swapchain).
//
// Hooks DXGI/D3D12 COM vtables, never engine code: IDXGISwapChain::Present /
// Present1 / ResizeBuffers / ResizeBuffers1 and
// ID3D12CommandQueue::ExecuteCommandLists (to learn the game's DIRECT queue).
// Input reaches the panel through a subclass of the game window; while the
// panel is open, the game's GetAsyncKeyState import returns 0 and keyboard /
// mouse messages stop at the subclass, so the game does not act on clicks
// meant for the panel. Insert or F8 toggles it. See docs/_re/IN_GAME_UI.md.
//
// Opt-in via RSMM_ENABLE_INGAME_UI=1 (env or desktop loader-flags file).
bool install_overlay_hooks();
void remove_overlay_hooks();

} // namespace rsmm
