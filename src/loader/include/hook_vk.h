#pragma once
namespace rsmm {
// Installs Vulkan swapchain present hook to draw the ImGui mod-manager UI.
void install_vulkan_hooks();
void remove_vulkan_hooks();
} // namespace rsmm
