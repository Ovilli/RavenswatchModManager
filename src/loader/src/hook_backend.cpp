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
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <fstream>
#include <functional>
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

bool under_wine() {
    HMODULE ntdll = GetModuleHandleA("ntdll.dll");
    return ntdll && GetProcAddress(ntdll, "wine_get_version");
}

HMODULE renamed_copy() {
    HMODULE m = GetModuleHandleA("winhttp_real.dll");
    return m ? m : LoadLibraryA("winhttp_real.dll");
}

// The WinHTTP every call is passed on to, chosen once. Every export (the
// thunks in winhttp_thunks.S and the wrappers below) goes to this ONE module,
// so a handle is never used with a WinHTTP other than the one that made it.
//
// Native Windows: the genuine System32\winhttp.dll, by full path. It used to
// be winhttp_real.dll, a copy of that file in the game folder, and running it
// under that name broke WinHTTP outright: a player's every Stormancer and
// MyNacon request failed at once with cpprest's "Open failed" (no party code,
// no online), while the same bytes worked after restore moved them back to
// winhttp.dll (2026-10-09).
//
// Wine/Proton keeps the renamed copy -- Wine's own builtin, and the only
// combination proven there. It is also the fallback when the System32 load
// fails or hands back this proxy instead of a second module.
HMODULE real_winhttp() {
    static HMODULE h = [] {
        if (!under_wine()) {
            wchar_t dir[MAX_PATH];
            const UINT n = GetSystemDirectoryW(dir, MAX_PATH);
            HMODULE self = nullptr;
            GetModuleHandleExW(GET_MODULE_HANDLE_EX_FLAG_FROM_ADDRESS |
                                   GET_MODULE_HANDLE_EX_FLAG_UNCHANGED_REFCOUNT,
                               reinterpret_cast<LPCWSTR>(&real_winhttp), &self);
            if (n > 0 && n < MAX_PATH - 16) {
                HMODULE m = LoadLibraryW((std::wstring(dir, n) + L"\\winhttp.dll").c_str());
                if (m && m != self) return m;
            }
        }
        return renamed_copy();
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

std::string narrow(LPCWSTR w) {
    std::string out;
    for (const wchar_t* p = w; p && *p; ++p) out.push_back(static_cast<char>(*p));
    return out;
}

// A failed call into the real WinHTTP, said once per (function, error). On a
// Windows tester's machine every WinHttpConnect came back NULL - Stormancer and
// MyNacon both logged only "Open failed", the cpprest text for "the connection
// could not be opened" - and nothing here said why, because the wrapper logged
// "redirected" without looking at the result. The module path is part of the
// answer: winhttp_real.dll is a COPY of the system DLL on Windows, Wine's own
// on Proton, and the two have only ever been proven on one of those.
// Restores the caller's last error, so the game sees exactly what it saw before.
void note_winhttp_failure(const char* fn, LPCWSTR server) {
    const DWORD err = GetLastError();
    static std::mutex mu;
    static std::unordered_set<std::uint64_t> seen;
    bool first_ever = false;
    {
        std::lock_guard<std::mutex> lk(mu);
        first_ever = seen.empty();
        const std::uint64_t key = (static_cast<std::uint64_t>(std::hash<std::string>{}(fn)) << 32) ^ err;
        if (!seen.insert(key).second) {
            SetLastError(err);
            return;
        }
    }
    if (first_ever) {
        char path[MAX_PATH] = {};
        HMODULE real = real_winhttp();
        if (real) GetModuleFileNameA(real, path, sizeof(path));
        Loader::get().log_warn(std::string("[backend] real WinHTTP is ") +
                               (path[0] ? path : "<not loaded>"));
    }
    Loader::get().log_warn(std::string("[backend] ") + fn + "(" + narrow(server) +
                           ") failed, error " + std::to_string(err) +
                           " (12xxx = ERROR_WINHTTP_*; 12018 = handle from another WinHTTP)");
    SetLastError(err);
}

// Said once per function: that the game got this far in WinHTTP. cpprest
// reports every failure while setting up a session as the same "Open failed",
// so the first-call lines show which step it reached.
void note_first_call(const char* fn, const std::string& detail) {
    static std::mutex mu;
    static std::unordered_set<std::string> seen;
    {
        std::lock_guard<std::mutex> lk(mu);
        if (!seen.insert(fn).second) return;
    }
    const DWORD err = GetLastError();
    Loader::get().log(std::string("[backend] ") + fn + " reached" +
                      (detail.empty() ? "" : " (" + detail + ")"));
    SetLastError(err);
}

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
    {
        // Which WinHTTP the game's online traffic goes through: the first
        // thing to read when a player reports no party code.
        char path[MAX_PATH] = {};
        HMODULE real = real_winhttp();
        if (real) GetModuleFileNameA(real, path, sizeof(path));
        if (real)
            Loader::get().log(std::string("[backend] real WinHTTP: ") + path);
        else
            Loader::get().log_warn("[backend] no real WinHTTP could be loaded -- online will fail");
    }
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

// ---- pass-through table for winhttp_thunks.S ---------------------------------

namespace {
const char* const kFwdNames[] = {
#include "winhttp_fwd_names.inc"
};
constexpr std::size_t kFwdCount = sizeof(kFwdNames) / sizeof(kFwdNames[0]);

// What an export the real module lacks resolves to. Every pass-through export
// returns BOOL, a handle or a DWORD status, so 0 plus a last error is a plain
// failure the caller already handles -- unlike a jump to null.
std::uintptr_t WINAPI missing_export() {
    SetLastError(ERROR_PROC_NOT_FOUND);
    return 0;
}
} // namespace

void* rsmm_winhttp_fwd[kFwdCount] = {};

// Called by a thunk's first use; returns (and caches) the real address.
// Concurrent first calls resolve the same address, so the race is benign.
void* rsmm_winhttp_resolve(unsigned idx) {
    if (idx >= kFwdCount) return reinterpret_cast<void*>(&missing_export);
    void* fn = nullptr;
    if (HMODULE real = rsmm::real_winhttp())
        fn = reinterpret_cast<void*>(GetProcAddress(real, kFwdNames[idx]));
    if (!fn) fn = reinterpret_cast<void*>(&missing_export);
    rsmm_winhttp_fwd[idx] = fn;
    return fn;
}

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
    if (!t.armed || !is_passtech_backend(server)) {
        HINTERNET h = real(session, server, port, reserved);
        if (!h) note_winhttp_failure("WinHttpConnect", server);
        else note_first_call("WinHttpConnect", narrow(server));
        return h;
    }

    HINTERNET h = real(session, t.host.c_str(), t.port, reserved);
    if (!h) {
        note_winhttp_failure("WinHttpConnect", t.host.c_str());
        return h;
    }
    {
        std::lock_guard<std::mutex> lk(g_redirected_mu);
        g_redirected.insert(h);
    }
    Loader::get().log("[backend] redirected " + narrow(server) + " -> " + t.url);
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
    HINTERNET h = real(connect, verb, object, version, referrer, accept_types, flags);
    if (!h) note_winhttp_failure("WinHttpOpenRequest", object);
    return h;
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

// ---- diagnostic pass-throughs -------------------------------------------------
//
// Every step cpprest takes to open a session, so a failure says which call and
// which error instead of the one "Open failed" the game logs for all of them.
// A Windows player stayed offline with nothing but this proxy active (no game
// hooks: no pattern DB) and with the real WinHTTP loaded from System32, and
// the loader logged no failure at all, because only Connect / OpenRequest were
// watched (2026-10-09). Each wrapper calls straight through and changes nothing.

#define RSMM_REAL(name, Fn)                                         \
    static Fn real = rsmm::real_fn<Fn>(name);                       \
    if (!real) {                                                    \
        SetLastError(ERROR_PROC_NOT_FOUND);                         \
        rsmm::note_winhttp_failure(name, nullptr);                  \
    }

HINTERNET WINAPI rsmm_WinHttpOpen(LPCWSTR agent, DWORD access, LPCWSTR proxy, LPCWSTR bypass,
                                  DWORD flags) {
    using Fn = HINTERNET(WINAPI*)(LPCWSTR, DWORD, LPCWSTR, LPCWSTR, DWORD);
    RSMM_REAL("WinHttpOpen", Fn)
    if (!real) return nullptr;
    // The proxy mode, not the proxy itself: whether one is configured is the
    // useful part, and its address is the player's own network detail.
    rsmm::note_first_call("WinHttpOpen", "access type " + std::to_string(access) +
                          (proxy && *proxy ? ", named proxy set" : "") +
                          ", flags 0x" + [&] { char b[16]; snprintf(b, sizeof b, "%lx",
                              static_cast<unsigned long>(flags)); return std::string(b); }());
    HINTERNET h = real(agent, access, proxy, bypass, flags);
    if (!h) rsmm::note_winhttp_failure("WinHttpOpen", nullptr);
    return h;
}

BOOL WINAPI rsmm_WinHttpSetTimeouts(HINTERNET h, int resolve, int connect, int send, int receive) {
    using Fn = BOOL(WINAPI*)(HINTERNET, int, int, int, int);
    RSMM_REAL("WinHttpSetTimeouts", Fn)
    if (!real) return FALSE;
    BOOL ok = real(h, resolve, connect, send, receive);
    if (!ok) rsmm::note_winhttp_failure("WinHttpSetTimeouts", nullptr);
    return ok;
}

BOOL WINAPI rsmm_WinHttpSetOption(HINTERNET h, DWORD option, LPVOID buffer, DWORD length) {
    using Fn = BOOL(WINAPI*)(HINTERNET, DWORD, LPVOID, DWORD);
    RSMM_REAL("WinHttpSetOption", Fn)
    if (!real) return FALSE;
    BOOL ok = real(h, option, buffer, length);
    if (!ok) {
        const DWORD err = GetLastError();
        std::wstring which = L"option " + std::to_wstring(option);
        SetLastError(err);
        rsmm::note_winhttp_failure("WinHttpSetOption", which.c_str());
    }
    return ok;
}

WINHTTP_STATUS_CALLBACK WINAPI rsmm_WinHttpSetStatusCallback(HINTERNET h,
                                                             WINHTTP_STATUS_CALLBACK cb,
                                                             DWORD flags, DWORD_PTR reserved) {
    using Fn = WINHTTP_STATUS_CALLBACK(WINAPI*)(HINTERNET, WINHTTP_STATUS_CALLBACK, DWORD, DWORD_PTR);
    RSMM_REAL("WinHttpSetStatusCallback", Fn)
    if (!real) return WINHTTP_INVALID_STATUS_CALLBACK;
    WINHTTP_STATUS_CALLBACK prev = real(h, cb, flags, reserved);
    if (prev == WINHTTP_INVALID_STATUS_CALLBACK)
        rsmm::note_winhttp_failure("WinHttpSetStatusCallback", nullptr);
    return prev;
}

BOOL WINAPI rsmm_WinHttpGetDefaultProxyConfiguration(WINHTTP_PROXY_INFO* info) {
    using Fn = BOOL(WINAPI*)(WINHTTP_PROXY_INFO*);
    RSMM_REAL("WinHttpGetDefaultProxyConfiguration", Fn)
    if (!real) return FALSE;
    BOOL ok = real(info);
    if (!ok) rsmm::note_winhttp_failure("WinHttpGetDefaultProxyConfiguration", nullptr);
    return ok;
}

BOOL WINAPI rsmm_WinHttpGetIEProxyConfigForCurrentUser(WINHTTP_CURRENT_USER_IE_PROXY_CONFIG* cfg) {
    using Fn = BOOL(WINAPI*)(WINHTTP_CURRENT_USER_IE_PROXY_CONFIG*);
    RSMM_REAL("WinHttpGetIEProxyConfigForCurrentUser", Fn)
    if (!real) return FALSE;
    BOOL ok = real(cfg);
    // Failing here is normal when no IE proxy is set; cpprest moves on.
    if (!ok) rsmm::note_winhttp_failure("WinHttpGetIEProxyConfigForCurrentUser", nullptr);
    else if (cfg)
        rsmm::note_first_call("WinHttpGetIEProxyConfigForCurrentUser",
                              std::string(cfg->fAutoDetect ? "auto-detect on" : "auto-detect off") +
                              (cfg->lpszAutoConfigUrl ? ", PAC url set" : "") +
                              (cfg->lpszProxy ? ", proxy set" : ""));
    return ok;
}

BOOL WINAPI rsmm_WinHttpSendRequest(HINTERNET h, LPCWSTR headers, DWORD headers_len, LPVOID optional,
                                    DWORD optional_len, DWORD total_len, DWORD_PTR context) {
    using Fn = BOOL(WINAPI*)(HINTERNET, LPCWSTR, DWORD, LPVOID, DWORD, DWORD, DWORD_PTR);
    RSMM_REAL("WinHttpSendRequest", Fn)
    if (!real) return FALSE;
    BOOL ok = real(h, headers, headers_len, optional, optional_len, total_len, context);
    if (!ok) rsmm::note_winhttp_failure("WinHttpSendRequest", nullptr);
    return ok;
}

BOOL WINAPI rsmm_WinHttpReceiveResponse(HINTERNET h, LPVOID reserved) {
    using Fn = BOOL(WINAPI*)(HINTERNET, LPVOID);
    RSMM_REAL("WinHttpReceiveResponse", Fn)
    if (!real) return FALSE;
    BOOL ok = real(h, reserved);
    if (!ok) rsmm::note_winhttp_failure("WinHttpReceiveResponse", nullptr);
    return ok;
}

#undef RSMM_REAL

} // extern "C"
