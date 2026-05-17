// Pattern-based function resolver. Loads data/function_patterns.json
// once, scans Ravenswatch.exe's .text on demand.
//
// Pattern format (from `scripts/gen_function_patterns.py`):
//   "40 53 ?? ?? 8d ..."  — IDA-style hex with ?? wildcards
//   match_index           — for non-unique patterns, this is the rank
//                           among full-.text matches (sorted by VA) to
//                           pick. Pre-computed by the generator so the
//                           loader doesn't need ANY symbol knowledge.

#include "fn_resolver.h"
#include "loader.h"

#include <windows.h>
#include <psapi.h>

#include <atomic>
#include <cstring>
#include <fstream>
#include <mutex>
#include <sstream>
#include <unordered_map>
#include <vector>

namespace rsmm {
namespace {

struct PatEntry {
    std::vector<std::uint8_t> bytes;
    std::vector<std::uint8_t> mask;
    int match_index;
    // Cached resolve result. 0 = unresolved, ~0 = resolution failed.
    std::atomic<std::uintptr_t> resolved{0};
};

std::unordered_map<std::string, PatEntry> g_patterns;
std::mutex g_mu;
std::uintptr_t g_text_base = 0;
std::size_t g_text_size = 0;
std::atomic<bool> g_inited{false};

bool locate_text_section() {
    auto h = GetModuleHandleA("Ravenswatch.exe");
    if (!h) h = GetModuleHandleA(nullptr);
    if (!h) return false;
    MODULEINFO mi{};
    if (!GetModuleInformation(GetCurrentProcess(), h, &mi, sizeof(mi))) return false;
    auto base = reinterpret_cast<std::uintptr_t>(h);
    auto dos = reinterpret_cast<IMAGE_DOS_HEADER*>(h);
    auto nt = reinterpret_cast<IMAGE_NT_HEADERS64*>(base + dos->e_lfanew);
    auto sec = IMAGE_FIRST_SECTION(nt);
    for (int i = 0; i < nt->FileHeader.NumberOfSections; i++) {
        if (std::memcmp(sec[i].Name, ".text", 5) == 0) {
            g_text_base = base + sec[i].VirtualAddress;
            g_text_size = sec[i].Misc.VirtualSize;
            return true;
        }
    }
    return false;
}

void parse_pattern(const std::string& pat, std::vector<std::uint8_t>& bytes,
                   std::vector<std::uint8_t>& mask) {
    bytes.clear(); mask.clear();
    std::istringstream iss(pat);
    std::string tok;
    while (iss >> tok) {
        if (tok == "??") { bytes.push_back(0); mask.push_back(0); }
        else { bytes.push_back(static_cast<std::uint8_t>(std::stoi(tok, nullptr, 16))); mask.push_back(0xFF); }
    }
}

// Naive masked scan over .text. Anchors on the first non-wildcard byte
// for cheap rejection. Hot path is short — runs once per cold call
// per pattern, then we cache. SSE'd version is a TODO; not the
// bottleneck while we have only a few hundred mods worth of calls.
std::vector<std::uintptr_t> scan_all(const PatEntry& e) {
    std::vector<std::uintptr_t> out;
    if (g_text_base == 0 || e.bytes.empty()) return out;
    std::size_t plen = e.bytes.size();
    if (plen > g_text_size) return out;
    int anchor = 0;
    for (std::size_t i = 0; i < e.mask.size(); i++) {
        if (e.mask[i]) { anchor = static_cast<int>(i); break; }
    }
    auto needle = e.bytes[anchor];
    auto base = reinterpret_cast<const std::uint8_t*>(g_text_base);
    std::size_t end = g_text_size - plen + 1 + static_cast<std::size_t>(anchor);
    for (std::size_t i = static_cast<std::size_t>(anchor); i < end; i++) {
        if (base[i] != needle) continue;
        std::size_t b = i - anchor;
        bool ok = true;
        for (std::size_t k = 0; k < plen; k++) {
            if (e.mask[k] && base[b + k] != e.bytes[k]) { ok = false; break; }
        }
        if (ok) out.push_back(g_text_base + b);
    }
    return out;
}

std::filesystem::path locate_patterns_file() {
    if (auto env = std::getenv("RSMM_DATA")) {
        std::filesystem::path p(env);
        p /= "function_patterns.json";
        if (std::filesystem::exists(p)) return p;
    }
    // Fall back to <game>/rsmm/data/function_patterns.json, planted by
    // install-loader / a future packaging step.
    char buf[MAX_PATH];
    if (GetModuleFileNameA(GetModuleHandleA("winhttp.dll"), buf, sizeof(buf))) {
        std::filesystem::path p(buf);
        p = p.parent_path() / "rsmm" / "data" / "function_patterns.json";
        if (std::filesystem::exists(p)) return p;
    }
    return {};
}

} // namespace

bool fn_resolver_init() {
    if (g_inited) return true;
    std::lock_guard<std::mutex> g(g_mu);
    if (g_inited) return true;
    if (!locate_text_section()) {
        Loader::get().log("[fn] .text section not located");
        return false;
    }
    auto pf = locate_patterns_file();
    if (pf.empty()) {
        Loader::get().log("[fn] function_patterns.json not found "
                          "(set RSMM_DATA=/path/to/data)");
        return false;
    }
    std::ifstream in(pf);
    if (!in) {
        Loader::get().log("[fn] failed to open " + pf.string());
        return false;
    }
    // Minimal hand-rolled JSON parse: the file is a flat array of
    // objects with known keys. We avoid a JSON-lib dep in the loader.
    // Each object: { "name": "...", "addr": "0x...", "size": N,
    //                "pattern": "...", "used_bytes": N, "match_index": N }
    std::string body((std::istreambuf_iterator<char>(in)),
                     std::istreambuf_iterator<char>());
    std::size_t pos = 0;
    auto skip_ws = [&]{ while (pos < body.size() && std::isspace((unsigned char)body[pos])) pos++; };
    auto find_str = [&](const std::string& key, std::size_t obj_end) -> std::string {
        std::string needle = "\"" + key + "\"";
        auto p = body.find(needle, pos);
        if (p == std::string::npos || p > obj_end) return {};
        p = body.find(':', p) + 1;
        skip_ws();
        if (body[p] != '"') return {};
        p++;
        auto end = body.find('"', p);
        return body.substr(p, end - p);
    };
    auto find_int = [&](const std::string& key, std::size_t obj_end) -> long long {
        std::string needle = "\"" + key + "\"";
        auto p = body.find(needle, pos);
        if (p == std::string::npos || p > obj_end) return 0;
        p = body.find(':', p) + 1;
        return std::strtoll(body.c_str() + p, nullptr, 10);
    };
    while (pos < body.size()) {
        auto open = body.find('{', pos);
        if (open == std::string::npos) break;
        auto close = body.find('}', open);
        if (close == std::string::npos) break;
        pos = open;
        auto name = find_str("name", close);
        auto pat = find_str("pattern", close);
        auto idx = static_cast<int>(find_int("match_index", close));
        if (!name.empty() && !pat.empty()) {
            PatEntry& e = g_patterns[name];
            parse_pattern(pat, e.bytes, e.mask);
            e.match_index = idx;
        }
        pos = close + 1;
    }
    Loader::get().log("[fn] loaded " + std::to_string(g_patterns.size()) + " patterns");
    g_inited = true;
    return true;
}

std::uintptr_t fn_resolve(std::string_view name) {
    if (!g_inited && !fn_resolver_init()) return 0;
    std::string key(name);
    auto it = g_patterns.find(key);
    if (it == g_patterns.end()) return 0;
    PatEntry& e = it->second;
    auto cached = e.resolved.load(std::memory_order_relaxed);
    if (cached != 0) return (cached == static_cast<std::uintptr_t>(-1)) ? 0 : cached;
    auto hits = scan_all(e);
    if (e.match_index < 0 || static_cast<size_t>(e.match_index) >= hits.size()) {
        e.resolved.store(static_cast<std::uintptr_t>(-1), std::memory_order_relaxed);
        return 0;
    }
    auto va = hits[e.match_index];
    e.resolved.store(va, std::memory_order_relaxed);
    return va;
}

bool fn_verify(std::string_view name, std::uintptr_t va) {
    if (!g_inited && !fn_resolver_init()) return false;
    auto it = g_patterns.find(std::string(name));
    if (it == g_patterns.end()) return false;
    auto& e = it->second;
    auto base = reinterpret_cast<const std::uint8_t*>(va);
    for (std::size_t k = 0; k < e.bytes.size(); k++) {
        if (e.mask[k] && base[k] != e.bytes[k]) return false;
    }
    return true;
}

size_t fn_resolver_pattern_count() { return g_patterns.size(); }

size_t fn_resolver_resolved_count() {
    size_t n = 0;
    for (auto& [_, e] : g_patterns) {
        auto v = e.resolved.load(std::memory_order_relaxed);
        if (v != 0 && v != static_cast<std::uintptr_t>(-1)) n++;
    }
    return n;
}

} // namespace rsmm
