// Online-backend redirect: point the game's Stormancer client at another
// backend (services/stormancer/), and log the Steam web-ticket identities the
// game requests (the server needs Stormancer's `steam.backendIdentity`).
//
// WHY AT THE WINHTTP LAYER
// ------------------------
// The game picks its backend from hardcoded URLs (https://dt-live*.
// passtechgames.com, chosen by the EndPointApp setting). Stormancer's HTTP
// client (cpprest) reaches them through WinHTTP, and this DLL IS the game's
// winhttp.dll: WinHttpConnect / WinHttpOpenRequest are exported from here
// instead of being forwarded (exports/winhttp.def). Rewriting the host there
// touches no game code and no engine address, so it survives game patches.
// Only the HTTP leg is redirected; the RakNet UDP endpoint the client connects
// to afterwards comes from the backend's own federation/scene-token responses.
//
// Armed by env RSMM_BACKEND_URL or the first line of mods/.rsmm_backend, e.g.
// `http://127.0.0.1:8090`. Only plain http:// targets are supported: the TLS
// flag is cleared on redirected requests, since the replacement backend has no
// certificate for passtechgames.com.
//
// THE IDENTITY PROBE
// ------------------
// Stormancer calls ISteamUser::GetAuthTicketForWebApi(identity) with an
// identity the game fills in at runtime (it is not a literal anywhere in the
// exe or the game data). The probe swaps that one vtable slot in Steam's
// ISteamUser023 interface for a wrapper that logs the identity string and calls
// through. It never reads or logs the ticket. The slot offset is read from
// steam_api64's own flat-API thunk rather than assumed.

#include "hook_backend.h"
#include "loader.h"
#include "mem_safe.h"

#include <windows.h>
#include <winhttp.h>

#include <array>
#include <cstdint>
#include <cstdlib>
#include <cstring>
#include <fstream>
#include <mutex>
#include <string>
#include <unordered_set>

namespace rsmm {
namespace {

// ---- configuration --------------------------------------------------------

struct BackendTarget {
    bool armed = false;
    std::wstring host;
    INTERNET_PORT port = 80;
    std::string url;  // as configured, for the log
};

std::string dll_dir() {
    char buf[MAX_PATH];
    if (!GetModuleFileNameA(GetModuleHandleA("winhttp.dll"), buf, sizeof(buf))) return {};
    std::string p(buf);
    auto slash = p.find_last_of("\\/");
    return slash == std::string::npos ? std::string() : p.substr(0, slash);
}

std::string configured_url() {
    char buf[512] = {};
    DWORD n = GetEnvironmentVariableA("RSMM_BACKEND_URL", buf, sizeof(buf));
    if (n > 0 && n < sizeof(buf)) return buf;

    const std::string dir = dll_dir();
    if (dir.empty()) return {};
    std::ifstream f(dir + "\\mods\\.rsmm_backend");
    std::string line;
    if (f && std::getline(f, line)) {
        while (!line.empty() && (line.back() == '\r' || line.back() == ' ')) line.pop_back();
        return line;
    }
    return {};
}

// Parses http://host[:port][/]. Anything else leaves the target unarmed.
BackendTarget parse_target(const std::string& url) {
    BackendTarget t;
    t.url = url;
    const std::string scheme = "http://";
    if (url.compare(0, scheme.size(), scheme) != 0) return t;
    std::string rest = url.substr(scheme.size());
    if (auto slash = rest.find('/'); slash != std::string::npos) rest.resize(slash);
    std::string host = rest;
    if (auto colon = rest.rfind(':'); colon != std::string::npos) {
        host = rest.substr(0, colon);
        const int port = std::atoi(rest.c_str() + colon + 1);
        if (port < 1 || port > 65535) return t;
        t.port = static_cast<INTERNET_PORT>(port);
    }
    if (host.empty()) return t;
    t.host.assign(host.begin(), host.end());
    t.armed = true;
    return t;
}

const BackendTarget& target() {
    static const BackendTarget t = parse_target(configured_url());
    return t;
}

// The game's built-in backends (all EndPointApp values except LocalDev).
bool is_passtech_backend(LPCWSTR server) {
    if (!server) return false;
    static const wchar_t* kHosts[] = {
        L"dt-live.passtechgames.com",
        L"dt-live-2.passtechgames.com",
        L"dt-live-3.passtechgames.com",
        L"dt-dev.passtechgames.com",
    };
    for (const wchar_t* h : kHosts)
        if (_wcsicmp(server, h) == 0) return true;
    return false;
}

// ---- WinHTTP passthrough --------------------------------------------------

HMODULE real_winhttp() {
    static HMODULE h = [] {
        HMODULE m = GetModuleHandleA("winhttp_real.dll");
        return m ? m : LoadLibraryA("winhttp_real.dll");
    }();
    return h;
}

template <typename Fn>
Fn real_fn(const char* name) {
    HMODULE h = real_winhttp();
    return h ? reinterpret_cast<Fn>(GetProcAddress(h, name)) : nullptr;
}

std::mutex g_redirected_mu;
std::unordered_set<HINTERNET> g_redirected;  // connect handles we pointed elsewhere

// ---- Steam identity probe -------------------------------------------------

using GetAuthTicketForWebApiFn = std::uint32_t (*)(void* self, const char* identity);
GetAuthTicketForWebApiFn g_real_get_ticket = nullptr;

std::uint32_t probe_get_auth_ticket_for_web_api(void* self, const char* identity) {
    char buf[128] = {};
    if (identity && mem_read_cstr(reinterpret_cast<std::uintptr_t>(identity), buf, sizeof(buf)))
        Loader::get().log(std::string("[backend] Steam web-ticket identity: \"") + buf + "\"");
    else
        Loader::get().log("[backend] Steam web-ticket identity: <unreadable>");
    return g_real_get_ticket(self, identity);
}

// steam_api64's flat thunk is `mov rax,[rcx]; jmp [rax+disp8]` (optionally
// behind a REX prefix). Returns the vtable byte offset it jumps through, or -1.
int slot_offset_from_flat_thunk(const std::uint8_t* p) {
    std::array<std::uint8_t, 16> code{};
    if (!mem_load(reinterpret_cast<std::uintptr_t>(p), &code)) return -1;
    for (int i = 0; i + 3 <= static_cast<int>(sizeof(code)); ++i) {
        // FF 60 xx  = jmp qword ptr [rax + disp8]
        if (code[i] == 0xFF && code[i + 1] == 0x60) return code[i + 2];
        // 48 FF 60 xx = same with REX.W
        if (i + 4 <= static_cast<int>(sizeof(code)) && code[i] == 0x48 && code[i + 1] == 0xFF &&
            code[i + 2] == 0x60)
            return code[i + 3];
    }
    return -1;
}

void install_identity_probe_once() {
    static std::once_flag once;
    std::call_once(once, [] {
        HMODULE api = GetModuleHandleA("steam_api64.dll");
        if (!api) {
            Loader::get().log_warn("[backend] steam_api64.dll not loaded; identity probe skipped");
            return;
        }
        using SteamUserFn = void* (*)();
        auto steam_user = reinterpret_cast<SteamUserFn>(GetProcAddress(api, "SteamAPI_SteamUser_v023"));
        auto flat = reinterpret_cast<const std::uint8_t*>(
            GetProcAddress(api, "SteamAPI_ISteamUser_GetAuthTicketForWebApi"));
        if (!steam_user || !flat) {
            Loader::get().log_warn("[backend] Steam exports missing; identity probe skipped");
            return;
        }
        const int offset = slot_offset_from_flat_thunk(flat);
        if (offset < 0 || offset % 8 != 0) {
            Loader::get().log_warn("[backend] unrecognised Steam thunk; identity probe skipped");
            return;
        }
        void* iface = steam_user();
        std::uintptr_t vtable = 0;
        if (!iface || !mem_load(reinterpret_cast<std::uintptr_t>(iface), &vtable) ||
            !mem_readable(reinterpret_cast<const void*>(vtable + offset), sizeof(void*))) {
            Loader::get().log_warn("[backend] ISteamUser not available yet; identity probe skipped");
            return;
        }
        auto* slot = reinterpret_cast<void**>(vtable + offset);
        DWORD old = 0;
        if (!VirtualProtect(slot, sizeof(void*), PAGE_READWRITE, &old)) {
            Loader::get().log_err("[backend] VirtualProtect on ISteamUser vtable failed");
            return;
        }
        g_real_get_ticket = reinterpret_cast<GetAuthTicketForWebApiFn>(*slot);
        *slot = reinterpret_cast<void*>(&probe_get_auth_ticket_for_web_api);
        DWORD tmp = 0;
        VirtualProtect(slot, sizeof(void*), old, &tmp);
        Loader::get().log("[backend] Steam web-ticket identity probe armed (vtable +" +
                          std::to_string(offset) + ")");
    });
}

bool identity_probe_wanted() {
    return target().armed || flag_enabled("RSMM_LOG_STEAM_IDENTITY");
}

} // namespace

bool install_backend_redirect() {
    const BackendTarget& t = target();
    if (!t.url.empty() && !t.armed) {
        Loader::get().log_warn("[backend] ignoring backend URL \"" + t.url +
                               "\": only http://host[:port] is supported");
    }
    if (!t.armed) {
        Loader::get().log("[backend] redirect disabled (set RSMM_BACKEND_URL or "
                          "write a URL to mods/.rsmm_backend)");
        return false;
    }
    Loader::get().log("[backend] Passtech backend requests go to " + t.url);
    return true;
}

} // namespace rsmm

// ---- exported WinHTTP wrappers (see exports/winhttp.def) ---------------------

extern "C" {

HINTERNET WINAPI rsmm_WinHttpConnect(HINTERNET session, LPCWSTR server, INTERNET_PORT port,
                                     DWORD reserved) {
    using namespace rsmm;
    using Fn = HINTERNET(WINAPI*)(HINTERNET, LPCWSTR, INTERNET_PORT, DWORD);
    static Fn real = real_fn<Fn>("WinHttpConnect");
    if (!real) {
        SetLastError(ERROR_PROC_NOT_FOUND);
        return nullptr;
    }

    // Stormancer's first HTTP request comes after SteamAPI_Init and before its
    // Steam login, so the first connect is the moment to arm the probe.
    if (identity_probe_wanted()) install_identity_probe_once();

    const BackendTarget& t = target();
    if (!t.armed || !is_passtech_backend(server)) return real(session, server, port, reserved);

    HINTERNET h = real(session, t.host.c_str(), t.port, reserved);
    if (h) {
        std::lock_guard<std::mutex> lk(g_redirected_mu);
        g_redirected.insert(h);
    }
    std::string from;
    for (const wchar_t* p = server; *p; ++p) from.push_back(static_cast<char>(*p));
    Loader::get().log("[backend] redirected " + from + " -> " + t.url);
    return h;
}

HINTERNET WINAPI rsmm_WinHttpOpenRequest(HINTERNET connect, LPCWSTR verb, LPCWSTR object,
                                         LPCWSTR version, LPCWSTR referrer, LPCWSTR* accept_types,
                                         DWORD flags) {
    using namespace rsmm;
    using Fn = HINTERNET(WINAPI*)(HINTERNET, LPCWSTR, LPCWSTR, LPCWSTR, LPCWSTR, LPCWSTR*, DWORD);
    static Fn real = real_fn<Fn>("WinHttpOpenRequest");
    if (!real) {
        SetLastError(ERROR_PROC_NOT_FOUND);
        return nullptr;
    }
    bool redirected;
    {
        std::lock_guard<std::mutex> lk(g_redirected_mu);
        redirected = g_redirected.count(connect) != 0;
    }
    if (redirected) flags &= ~static_cast<DWORD>(WINHTTP_FLAG_SECURE);
    return real(connect, verb, object, version, referrer, accept_types, flags);
}

BOOL WINAPI rsmm_WinHttpCloseHandle(HINTERNET handle) {
    using namespace rsmm;
    using Fn = BOOL(WINAPI*)(HINTERNET);
    static Fn real = real_fn<Fn>("WinHttpCloseHandle");
    {
        std::lock_guard<std::mutex> lk(g_redirected_mu);
        g_redirected.erase(handle);
    }
    if (!real) {
        SetLastError(ERROR_PROC_NOT_FOUND);
        return FALSE;
    }
    return real(handle);
}

} // extern "C"
