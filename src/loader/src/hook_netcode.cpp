// Netcode tweaks — see hook_netcode.h and
// apps/docs/src/content/docs/reverse-engineering/multiplayer.md.
//
// Two opt-in patches, both verify-then-write and both located through
// pattern-resolved symbols (never a hardcoded .data/.text address):
//
// 1. Reconnect window. Netcode_PeerStateTick gives a dropped EOS tunnel N
//    seconds (default 60) to come back before Netcode_DropPeer removes it.
//    The four thresholds are contiguous baked uint8 seconds in .data; we find
//    them by decoding the rip-relative operand of the `movzx` that reads the
//    window (Sym::Netcode_ReconnectMaxRead). This used to be a fixed RVA,
//    which went stale in Update 6 (+0x1000) and silently disabled the patch.
//
// 2. RakNet P2P timeout. The co-op mesh runs RakNet over the EOS tunnel and
//    never calls SetTimeoutTime, so it keeps RakPeer's constructor default of
//    10 s. That is SHORTER than the reconnect window above: a peer silent for
//    10 s gets ID_CONNECTION_LOST and, if it was the host, the session is torn
//    down — before the EOS layer's reconnect can finish. We rewrite the
//    constructor's `mov [rsi+0x7ec], 10000` immediate
//    (Sym::RakPeer_DefaultTimeoutStore) at boot, before any session exists,
//    so every RakPeer made afterwards starts with the longer timeout.

#include "hook_netcode.h"
#include "fn_resolver.h"
#include "loader.h"
#include "mem_safe.h"
#include "symbols.gen.h"

#include <windows.h>

#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <string>

namespace rsmm {
namespace {

// ---- shared helpers ---------------------------------------------------------

// Integer value of a valued env var, clamped to [lo, hi]. 0 when unset/invalid.
int env_seconds(const char* name, int lo, int hi) {
    char buf[8] = {};
    DWORD n = GetEnvironmentVariableA(name, buf, sizeof(buf));
    if (n == 0 || n >= sizeof(buf)) return 0;
    int v = std::atoi(buf);
    if (v < 1) return 0;
    if (v < lo) v = lo;
    if (v > hi) v = hi;
    return v;
}

// <game>/mods/<file> exists (the game dir is where our winhttp.dll lives).
bool mods_marker_present(const char* file) {
    char buf[MAX_PATH];
    if (!GetModuleFileNameA(GetModuleHandleA("winhttp.dll"), buf, sizeof(buf))) return false;
    std::string p(buf);
    auto slash = p.find_last_of("\\/");
    if (slash == std::string::npos) return false;
    std::string marker = p.substr(0, slash) + "\\mods\\" + file;
    DWORD attr = GetFileAttributesA(marker.c_str());
    return attr != INVALID_FILE_ATTRIBUTES && !(attr & FILE_ATTRIBUTE_DIRECTORY);
}

// Resolve an anchor symbol: its pattern names the PARENT function; the site is
// parent + (Sym::Site - Sym::Parent). Proves the parent bytes still match and
// that the parent is a real function entry. 0 on any failure.
std::uintptr_t resolve_anchor(const char* tag, const char* pattern,
                              std::uintptr_t offset) {
    std::uintptr_t parent = fn_resolve(pattern);
    if (parent == 0 || parent == static_cast<std::uintptr_t>(-1)) {
        char b[160];
        std::snprintf(b, sizeof(b), "[netcode] %s: pattern %s not found "
                      "(run `rsmm update-data`); not patching", tag, pattern);
        Loader::get().log_err(b);
        return 0;
    }
    if (!fn_verify(pattern, parent) || !fn_is_function_start(parent)) {
        char b[160];
        std::snprintf(b, sizeof(b), "[netcode] %s: %s verify failed "
                      "(game patched?); not patching", tag, pattern);
        Loader::get().log_err(b);
        return 0;
    }
    return parent + offset;
}

bool write_protected(void* dst, const void* src, size_t n) {
    DWORD oldprot = 0;
    if (!VirtualProtect(dst, n, PAGE_EXECUTE_READWRITE, &oldprot)) return false;
    std::memcpy(dst, src, n);
    DWORD tmp = 0;
    VirtualProtect(dst, n, oldprot, &tmp);
    FlushInstructionCache(GetCurrentProcess(), dst, n);
    return true;
}

// ---- 1. reconnect window ----------------------------------------------------

constexpr std::uintptr_t kWindowReadOff =
    Sym::Netcode_ReconnectMaxRead - Sym::Netcode_PeerStateTick;
static_assert(kWindowReadOff == 0x3a7,
              "symbol map moved the reconnect-window read inside PeerStateTick");

// Shipped defaults, in byte order: interrupt-drop / MAX RECONNECT / show-UI /
// max-connecting (seconds). All four must match before we write.
constexpr std::uint8_t kDefaults[4] = {15, 60, 4, 5};
constexpr int kDefaultWindowSeconds = 250;

// Returns the window written, or 0 when not armed / not patched.
int patch_reconnect_window() {
    const int env_window = env_seconds("RSMM_RECONNECT_SECONDS", 1, 255);
    const bool by_file = mods_marker_present(".rsmm_extend_reconnect");
    if (env_window == 0 && !by_file) {
        Loader::get().log("[netcode] reconnect-window patch disabled "
                          "(set RSMM_RECONNECT_SECONDS=1..255 or touch "
                          "mods/.rsmm_extend_reconnect)");
        return 0;
    }
    const int window = env_window != 0 ? env_window : kDefaultWindowSeconds;

    const std::uintptr_t site = resolve_anchor(
        "reconnect", Sym::Netcode_ReconnectMaxRead_Pattern, kWindowReadOff);
    if (site == 0) return 0;

    // movzx ecx, byte ptr [rip+disp32]  =  0f b6 0d <disp32>, 7 bytes.
    const auto* insn = reinterpret_cast<const std::uint8_t*>(site);
    if (!mem_readable(insn, 7) || insn[0] != 0x0F || insn[1] != 0xB6 || insn[2] != 0x0D) {
        Loader::get().log("[netcode] reconnect: window read is not `movzx ecx, "
                          "byte [rip+x]` (game patched?); not patching");
        return 0;
    }
    std::int32_t disp = 0;
    std::memcpy(&disp, insn + 3, sizeof(disp));
    auto* window_byte = reinterpret_cast<std::uint8_t*>(site + 7 + disp);
    std::uint8_t* bytes = window_byte - 1;  // interrupt-drop sits just before

    if (!mem_readable(bytes, 4)) {
        Loader::get().log("[netcode] reconnect: timeout bytes not mapped; not patching");
        return 0;
    }
    if (std::memcmp(bytes, kDefaults, 4) != 0) {
        char b[112];
        std::snprintf(b, sizeof(b),
                      "[netcode] reconnect defaults not found (%u/%u/%u/%u); "
                      "game updated? not patching",
                      bytes[0], bytes[1], bytes[2], bytes[3]);
        Loader::get().log(b);
        return 0;
    }
    const std::uint8_t v = static_cast<std::uint8_t>(window);
    if (!write_protected(window_byte, &v, 1)) {
        Loader::get().log_err("[netcode] reconnect: VirtualProtect failed; not patching");
        return 0;
    }
    char b[112];
    std::snprintf(b, sizeof(b),
                  "[netcode] reconnect window %us -> %ds (a dropped peer can rejoin)",
                  kDefaults[1], window);
    Loader::get().log(b);
    return window;
}

// ---- 2. RakNet P2P timeout --------------------------------------------------

constexpr std::uintptr_t kTimeoutStoreOff =
    Sym::RakPeer_DefaultTimeoutStore - Sym::RakPeer_Ctor;
static_assert(kTimeoutStoreOff == 0xeb0,
              "symbol map moved the defaultTimeoutTime store inside RakPeer_Ctor");

// mov dword ptr [rsi+0x7ec], 0x2710  (defaultTimeoutTime = 10000 ms)
constexpr std::uint8_t kTimeoutStore[10] = {0xC7, 0x86, 0xEC, 0x07, 0x00, 0x00,
                                            0x10, 0x27, 0x00, 0x00};
constexpr int kStockTimeoutSeconds = 10;
constexpr int kDefaultP2PTimeoutSeconds = 60;

// Returns the timeout written (seconds), or 0 when not armed / not patched.
int patch_p2p_timeout() {
    const int env_secs = env_seconds("RSMM_P2P_TIMEOUT_SECONDS",
                                     kStockTimeoutSeconds, 300);
    const bool by_file = mods_marker_present(".rsmm_p2p_timeout");
    if (env_secs == 0 && !by_file) {
        Loader::get().log("[netcode] P2P timeout patch disabled (stock 10 s; "
                          "set RSMM_P2P_TIMEOUT_SECONDS=10..300 or touch "
                          "mods/.rsmm_p2p_timeout)");
        return 0;
    }
    const int secs = env_secs != 0 ? env_secs : kDefaultP2PTimeoutSeconds;

    const std::uintptr_t site = resolve_anchor(
        "p2p-timeout", Sym::RakPeer_DefaultTimeoutStore_Pattern, kTimeoutStoreOff);
    if (site == 0) return 0;

    auto* insn = reinterpret_cast<std::uint8_t*>(site);
    if (!mem_readable(insn, sizeof(kTimeoutStore)) ||
        std::memcmp(insn, kTimeoutStore, sizeof(kTimeoutStore)) != 0) {
        Loader::get().log("[netcode] p2p-timeout: RakPeer ctor store is not "
                          "`mov [rsi+0x7ec], 10000` (game patched?); not patching");
        return 0;
    }
    const std::uint32_t ms = static_cast<std::uint32_t>(secs) * 1000u;
    if (!write_protected(insn + 6, &ms, sizeof(ms))) {
        Loader::get().log_err("[netcode] p2p-timeout: VirtualProtect failed; not patching");
        return 0;
    }
    char b[128];
    std::snprintf(b, sizeof(b),
                  "[netcode] RakNet P2P timeout %ds -> %ds (a stalled peer or "
                  "host is no longer cut at 10 s)",
                  kStockTimeoutSeconds, secs);
    Loader::get().log(b);
    return secs;
}

} // namespace

bool install_netcode_patches() {
    const int window = patch_reconnect_window();
    const int timeout = patch_p2p_timeout();
    // The RakNet layer sits ABOVE the EOS tunnel: once it times out, the
    // session is gone no matter how long the tunnel is allowed to reconnect.
    if (window > 0 && window > (timeout > 0 ? timeout : kStockTimeoutSeconds)) {
        char b[176];
        std::snprintf(b, sizeof(b),
                      "[netcode] reconnect window %ds exceeds the RakNet "
                      "P2P timeout %ds; drops longer than the timeout still end "
                      "the session (raise RSMM_P2P_TIMEOUT_SECONDS)",
                      window, timeout > 0 ? timeout : kStockTimeoutSeconds);
        Loader::get().log_warn(b);
    }
    return window > 0 || timeout > 0;
}

} // namespace rsmm
