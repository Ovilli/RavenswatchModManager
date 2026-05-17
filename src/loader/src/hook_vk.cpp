// Vulkan overlay injection.
//
// Strategy:
//   * MinHook on vkGetInstanceProcAddr (vulkan-1.dll). When the game asks
//     for a proc address we care about (vkCreateDevice,
//     vkCreateSwapchainKHR, vkQueuePresentKHR, vkAcquireNextImageKHR), we
//     return our own trampoline that captures handles on the way through.
//   * vkCreateInstance is hooked the same way at the loader level so we see
//     instance creation.
//   * Once we have a VkDevice + a VkSwapchainKHR we lazy-init ImGui's
//     Vulkan backend. On every present we record an ImGui draw into a
//     transient command buffer with VK_ATTACHMENT_LOAD_OP_LOAD, submit it,
//     then forward to the real vkQueuePresentKHR.
//
// Caveats:
//   * Single-device assumption (the game only opens one logical device).
//   * Swapchain recreation is detected by handle change; the old per-image
//     resources get torn down on the next present after a recreate.
//   * Input is handled in hook_win32.cpp via WndProc subclassing.

#define WIN32_LEAN_AND_MEAN
#include <windows.h>

#include <vulkan/vulkan.h>

#include "MinHook.h"
#include "loader.h"
#include "hook_vk.h"
#include <vector>
#include <mutex>

namespace rsmm {

namespace {

// --- captured state ------------------------------------------------------
struct VkState {
    VkInstance       instance       = VK_NULL_HANDLE;
    VkPhysicalDevice phys           = VK_NULL_HANDLE;
    VkDevice         device         = VK_NULL_HANDLE;
    VkQueue          queue          = VK_NULL_HANDLE;
    uint32_t         queue_family   = ~0u;
    VkSwapchainKHR   swapchain      = VK_NULL_HANDLE;
} g_vk;

std::mutex g_mu;

// --- function pointers (real) -------------------------------------------
PFN_vkGetInstanceProcAddr   real_vkGetInstanceProcAddr   = nullptr;
PFN_vkCreateInstance        real_vkCreateInstance        = nullptr;
PFN_vkCreateDevice          real_vkCreateDevice          = nullptr;
PFN_vkGetDeviceQueue        real_vkGetDeviceQueue        = nullptr;
PFN_vkCreateSwapchainKHR    real_vkCreateSwapchainKHR    = nullptr;
PFN_vkDestroySwapchainKHR   real_vkDestroySwapchainKHR   = nullptr;
PFN_vkQueuePresentKHR       real_vkQueuePresentKHR       = nullptr;
PFN_vkGetSwapchainImagesKHR real_vkGetSwapchainImagesKHR = nullptr;

template <typename T>
void resolve_device(VkDevice dev, const char* name, T& out) {
    out = reinterpret_cast<T>(
        real_vkGetInstanceProcAddr(reinterpret_cast<VkInstance>(dev), name));
    // Fallback via instance-level lookup (Loader trampolines accept any handle).
    if (!out && g_vk.instance) {
        out = reinterpret_cast<T>(real_vkGetInstanceProcAddr(g_vk.instance, name));
    }
}

template <typename T>
void resolve_instance(VkInstance inst, const char* name, T& out) {
    out = reinterpret_cast<T>(real_vkGetInstanceProcAddr(inst, name));
}

// Overlay removed: the Vulkan hook now only captures device/swapchain state.

// --- wrapped vulkan entry points -----------------------------------------

VKAPI_ATTR VkResult VKAPI_CALL hook_vkCreateInstance(
        const VkInstanceCreateInfo* ci, const VkAllocationCallbacks* alloc, VkInstance* out) {
    VkResult r = real_vkCreateInstance(ci, alloc, out);
    if (r == VK_SUCCESS && out && *out) {
        std::lock_guard<std::mutex> g(g_mu);
        g_vk.instance = *out;
        resolve_instance(*out, "vkCreateDevice",       real_vkCreateDevice);
        Loader::get().log("captured VkInstance");
    }
    return r;
}

VKAPI_ATTR VkResult VKAPI_CALL hook_vkCreateDevice(
        VkPhysicalDevice phys, const VkDeviceCreateInfo* ci,
        const VkAllocationCallbacks* alloc, VkDevice* out) {
    VkResult r = real_vkCreateDevice(phys, ci, alloc, out);
    if (r != VK_SUCCESS || !out || !*out) return r;

    std::lock_guard<std::mutex> g(g_mu);
    g_vk.phys   = phys;
    g_vk.device = *out;

    if (ci->queueCreateInfoCount > 0) {
        g_vk.queue_family = ci->pQueueCreateInfos[0].queueFamilyIndex;
    }

    // Resolve every device function we need.
    resolve_device(*out, "vkGetDeviceQueue",           real_vkGetDeviceQueue);
    resolve_device(*out, "vkCreateSwapchainKHR",       real_vkCreateSwapchainKHR);
    resolve_device(*out, "vkDestroySwapchainKHR",      real_vkDestroySwapchainKHR);
    resolve_device(*out, "vkQueuePresentKHR",          real_vkQueuePresentKHR);
    resolve_device(*out, "vkGetSwapchainImagesKHR",    real_vkGetSwapchainImagesKHR);

    // Grab queue 0 of the family the game used.
    if (real_vkGetDeviceQueue) {
        real_vkGetDeviceQueue(*out, g_vk.queue_family, 0, &g_vk.queue);
    }
    Loader::get().log("captured VkDevice");
    return r;
}

VKAPI_ATTR VkResult VKAPI_CALL hook_vkCreateSwapchainKHR(
        VkDevice device, const VkSwapchainCreateInfoKHR* ci,
        const VkAllocationCallbacks* alloc, VkSwapchainKHR* out) {
    VkResult r = real_vkCreateSwapchainKHR(device, ci, alloc, out);
    if (r != VK_SUCCESS || !out) return r;

    std::lock_guard<std::mutex> g(g_mu);
    g_vk.swapchain = *out;
    return r;
}

VKAPI_ATTR VkResult VKAPI_CALL hook_vkQueuePresentKHR(
        VkQueue queue, const VkPresentInfoKHR* pInfo) {
    Loader::get().note_present();
    return real_vkQueuePresentKHR(queue, pInfo);
}

// --- proc-address interception ------------------------------------------

VKAPI_ATTR PFN_vkVoidFunction VKAPI_CALL hook_vkGetInstanceProcAddr(
        VkInstance instance, const char* pName) {
    if (!pName) return real_vkGetInstanceProcAddr(instance, pName);
    #define WRAP(name) if (!strcmp(pName, #name)) { \
        if (!real_##name) real_##name = (PFN_##name)real_vkGetInstanceProcAddr(instance, pName); \
        return (PFN_vkVoidFunction)hook_##name; \
    }
    WRAP(vkCreateInstance)
    WRAP(vkCreateDevice)
    WRAP(vkCreateSwapchainKHR)
    WRAP(vkQueuePresentKHR)
    #undef WRAP
    return real_vkGetInstanceProcAddr(instance, pName);
}

} // namespace

void install_vulkan_hooks() {
    HMODULE vk = GetModuleHandleW(L"vulkan-1.dll");
    if (!vk) vk = LoadLibraryW(L"vulkan-1.dll");
    if (!vk) {
        Loader::get().log("vulkan-1.dll not present; overlay disabled");
        return;
    }

    auto gipa = reinterpret_cast<PFN_vkGetInstanceProcAddr>(
        GetProcAddress(vk, "vkGetInstanceProcAddr"));
    if (!gipa) {
        Loader::get().log("vkGetInstanceProcAddr missing");
        return;
    }

    if (MH_CreateHook(reinterpret_cast<LPVOID>(gipa),
                      reinterpret_cast<LPVOID>(&hook_vkGetInstanceProcAddr),
                      reinterpret_cast<LPVOID*>(&real_vkGetInstanceProcAddr)) != MH_OK) {
        Loader::get().log("MH_CreateHook vkGetInstanceProcAddr failed");
        return;
    }

    auto ci = reinterpret_cast<PFN_vkCreateInstance>(
        GetProcAddress(vk, "vkCreateInstance"));
    if (ci) {
        MH_CreateHook(reinterpret_cast<LPVOID>(ci),
                      reinterpret_cast<LPVOID>(&hook_vkCreateInstance),
                      reinterpret_cast<LPVOID*>(&real_vkCreateInstance));
    }

    MH_EnableHook(MH_ALL_HOOKS);
    Loader::get().log("vulkan hooks installed");
}

void remove_vulkan_hooks() {
    std::lock_guard<std::mutex> g(g_mu);
}

} // namespace rsmm
