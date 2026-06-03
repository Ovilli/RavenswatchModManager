// Netcode tweaks — extend the P2P reconnection window. See hook_netcode.h
// and docs/_re/MULTIPLAYER.md.
//
// The per-peer connection-state tick (FUN_1402afaa0) gives a dropped peer
// `kReconnectMaxRva` seconds (default 60) to come back before FUN_1402b4450
// removes it from the session. These thresholds are baked uint8 seconds in
// .data; we rebase them onto the running module and bump the max-reconnection
// value. We refuse to write unless the four known defaults are all present, so
// a game patch that relocates .data is detected (mismatch -> skip, no blind
// poke at a shifted address).

#include "hook_netcode.h"
#include "loader.h"

#include <windows.h>

#include <cstdint>
#include <string>

namespace rsmm {
namespace {

// Preferred image base the static analysis used; the live module may be ASLR-
// rebased, so we work in RVAs off the real base.
constexpr std::uintptr_t kPreferredBase = 0x140000000ull;

// RVAs of the four contiguous reconnect-timeout bytes (VA - kPreferredBase).
constexpr std::uintptr_t kInterruptDropRva = 0x12e5ed2; // interrupted -> disconnect (s)
constexpr std::uintptr_t kReconnectMaxRva  = 0x12e5ed3; // max reconnection time (s) <-- lever
constexpr std::uintptr_t kReconnectUiRva   = 0x12e5ed4; // show reconnect UI after (s)
constexpr std::uintptr_t kMaxConnectingRva = 0x12e5ed5; // max connecting time (s)

// Known shipped defaults, in RVA order ed2..ed5. All four must match before we
// touch anything (game-update guard).
constexpr std::uint8_t kDefInterruptDrop = 15;
constexpr std::uint8_t kDefReconnectMax  = 60;
constexpr std::uint8_t kDefReconnectUi   = 4;
constexpr std::uint8_t kDefMaxConnecting = 5;

// Default new window when armed by the file marker (env can override).
constexpr int kDefaultWindowSeconds = 250;

std::uintptr_t game_base() {
    HMODULE h = GetModuleHandleA("Ravenswatch.exe");
    if (!h) h = GetModuleHandleA(nullptr);
    return reinterpret_cast<std::uintptr_t>(h);
}

// Desired window from the environment (RSMM_RECONNECT_SECONDS), clamped to the
// byte range. Returns 0 when unset/invalid.
int window_from_env() {
    char buf[8] = {};
    DWORD n = GetEnvironmentVariableA("RSMM_RECONNECT_SECONDS", buf, sizeof(buf));
    if (n == 0 || n >= sizeof(buf)) return 0;
    int v = std::atoi(buf);
    if (v < 1) return 0;
    if (v > 255) v = 255;
    return v;
}

bool file_marker_present() {
    char buf[MAX_PATH];
    if (!GetModuleFileNameA(GetModuleHandleA("winhttp.dll"), buf, sizeof(buf))) return false;
    std::string p(buf);
    auto slash = p.find_last_of("\\/");
    if (slash == std::string::npos) return false;
    std::string marker = p.substr(0, slash) + "\\mods\\.rsmm_extend_reconnect";
    DWORD attr = GetFileAttributesA(marker.c_str());
    return attr != INVALID_FILE_ATTRIBUTES && !(attr & FILE_ATTRIBUTE_DIRECTORY);
}

} // namespace

bool install_netcode_patches() {
    const int env_window = window_from_env();
    const bool by_file = file_marker_present();
    if (env_window == 0 && !by_file) {
        Loader::get().log("[netcode] reconnect-window patch disabled "
                          "(set RSMM_RECONNECT_SECONDS=1..255 or touch "
                          "mods/.rsmm_extend_reconnect)");
        return false;
    }
    const std::uint8_t window =
        static_cast<std::uint8_t>(env_window != 0 ? env_window : kDefaultWindowSeconds);

    const std::uintptr_t base = game_base();
    if (base == 0) {
        Loader::get().log("[netcode] could not resolve game module base; skipping");
        return false;
    }

    auto* ed2 = reinterpret_cast<std::uint8_t*>(base + kInterruptDropRva);
    auto* ed3 = reinterpret_cast<std::uint8_t*>(base + kReconnectMaxRva);
    auto* ed4 = reinterpret_cast<std::uint8_t*>(base + kReconnectUiRva);
    auto* ed5 = reinterpret_cast<std::uint8_t*>(base + kMaxConnectingRva);

    // Game-update guard: all four defaults must be present at the rebased
    // addresses, or .data has moved and we must not write.
    if (*ed2 != kDefInterruptDrop || *ed3 != kDefReconnectMax ||
        *ed4 != kDefReconnectUi  || *ed5 != kDefMaxConnecting) {
        char b[96];
        snprintf(b, sizeof(b),
                 "[netcode] reconnect defaults not found (%u/%u/%u/%u); "
                 "game updated? not patching",
                 *ed2, *ed3, *ed4, *ed5);
        Loader::get().log(b);
        return false;
    }

    DWORD oldprot = 0;
    if (!VirtualProtect(ed3, 1, PAGE_EXECUTE_READWRITE, &oldprot)) {
        Loader::get().log("[netcode] VirtualProtect failed; not patching");
        return false;
    }
    *ed3 = window;
    DWORD tmp = 0;
    VirtualProtect(ed3, 1, oldprot, &tmp);

    char b[96];
    snprintf(b, sizeof(b),
             "[netcode] reconnect window %us -> %us (a dropped peer can rejoin)",
             kDefReconnectMax, window);
    Loader::get().log(b);
    return true;
}

} // namespace rsmm
