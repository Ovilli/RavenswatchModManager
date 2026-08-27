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
#include "mem_safe.h"

#include <windows.h>
#include <psapi.h>

#include <atomic>
#include <cstdio>
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

// "40 53 ?? 8d" -> bytes + mask. Returns false on a malformed token so a
// corrupt DB entry is dropped instead of throwing out of the whole load
// (std::stoi throws, and this runs inside the one-shot init).
bool parse_pattern(const std::string& pat, std::vector<std::uint8_t>& bytes,
                   std::vector<std::uint8_t>& mask) {
    bytes.clear(); mask.clear();
    std::istringstream iss(pat);
    std::string tok;
    while (iss >> tok) {
        if (tok == "??" || tok == "?") { bytes.push_back(0); mask.push_back(0); continue; }
        if (tok.size() != 2 || !std::isxdigit(static_cast<unsigned char>(tok[0]))
                            || !std::isxdigit(static_cast<unsigned char>(tok[1]))) {
            return false;
        }
        bytes.push_back(static_cast<std::uint8_t>(std::stoi(tok, nullptr, 16)));
        mask.push_back(0xFF);
    }
    if (bytes.empty()) return false;
    // At least one FIXED byte, or the scan is meaningless: scan_all anchors on
    // the first masked byte, and with none it anchors on bytes[0] — a zero it
    // never actually wrote — then finds the first 0x00 in .text and passes the
    // mask check vacuously, resolving the symbol to a garbage address that
    // every later check (fn_verify, .pdata) would then be asked about. Reject
    // it here so the entry is DROPPED and the capability disables itself.
    for (const auto m : mask) {
        if (m) return true;
    }
    return false;
}

// Masked scan over .text. Anchors on the first non-wildcard byte and finds
// candidate positions with memchr — the C library's vectorised search — rather
// than a byte-at-a-time loop. .text is ~20 MB and `symbols audit` forces ~140
// full scans, so the difference is seconds per launch, not microseconds.
std::vector<std::uintptr_t> scan_all(const PatEntry& e) {
    std::vector<std::uintptr_t> out;
    if (g_text_base == 0 || e.bytes.empty()) return out;
    const std::size_t plen = e.bytes.size();
    if (plen > g_text_size) return out;
    std::size_t anchor = 0;
    for (std::size_t i = 0; i < e.mask.size(); i++) {
        if (e.mask[i]) { anchor = i; break; }
    }
    const auto needle = e.bytes[anchor];
    const auto* base = reinterpret_cast<const std::uint8_t*>(g_text_base);
    // Last valid match START is g_text_size - plen; the anchor byte for it
    // sits `anchor` further along, which is the inclusive end of the search.
    const std::size_t last_anchor = g_text_size - plen + anchor;
    std::size_t i = anchor;
    while (i <= last_anchor) {
        const auto* hit = static_cast<const std::uint8_t*>(
            std::memchr(base + i, needle, last_anchor - i + 1));
        if (!hit) break;
        const std::size_t pos = static_cast<std::size_t>(hit - base);
        const std::size_t b = pos - anchor;
        bool ok = true;
        for (std::size_t k = 0; k < plen; k++) {
            if (e.mask[k] && base[b + k] != e.bytes[k]) { ok = false; break; }
        }
        if (ok) out.push_back(g_text_base + b);
        i = pos + 1;
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
        Loader::get().log_err("[fn] function_patterns.json not found "
                          "(set RSMM_DATA=/path/to/data)");
        return false;
    }
    std::ifstream in(pf);
    if (!in) {
        Loader::get().log_err("[fn] failed to open " + pf.string());
        return false;
    }
    // Minimal hand-rolled JSON parse: the file is a flat array of
    // objects with known keys. We avoid a JSON-lib dep in the loader.
    // Each object: { "name": "...", "addr": "0x...", "size": N,
    //                "pattern": "...", "used_bytes": N, "match_index": N }
    std::string body((std::istreambuf_iterator<char>(in)),
                     std::istreambuf_iterator<char>());
    std::size_t pos = 0;
    // Locate `"key":` strictly INSIDE the current object. Both helpers used to
    // do `body.find(':', p) + 1` without checking for npos (which wraps to 0
    // and then parses from the top of the file) and find_int never bounded its
    // hit by obj_end, so a record missing "match_index" silently picked up the
    // NEXT record's index — resolving that symbol to the wrong function.
    auto value_start = [&](const std::string& key, std::size_t obj_end)
            -> std::size_t {
        const std::string needle = "\"" + key + "\"";
        auto p = body.find(needle, pos);
        if (p == std::string::npos || p >= obj_end) return std::string::npos;
        auto colon = body.find(':', p + needle.size());
        if (colon == std::string::npos || colon >= obj_end) return std::string::npos;
        auto v = colon + 1;
        while (v < obj_end && std::isspace((unsigned char)body[v])) v++;
        return v < obj_end ? v : std::string::npos;
    };
    auto find_str = [&](const std::string& key, std::size_t obj_end) -> std::string {
        auto p = value_start(key, obj_end);
        if (p == std::string::npos || body[p] != '"') return {};
        p++;
        auto end = body.find('"', p);
        if (end == std::string::npos || end > obj_end) return {};
        return body.substr(p, end - p);
    };
    auto find_int = [&](const std::string& key, std::size_t obj_end,
                        long long fallback) -> long long {
        auto p = value_start(key, obj_end);
        if (p == std::string::npos) return fallback;
        return std::strtoll(body.c_str() + p, nullptr, 10);
    };
    std::size_t malformed = 0;
    while (pos < body.size()) {
        auto open = body.find('{', pos);
        if (open == std::string::npos) break;
        auto close = body.find('}', open);
        if (close == std::string::npos) break;
        pos = open;
        auto name = find_str("name", close);
        auto pat = find_str("pattern", close);
        // A record with no match_index means "the pattern is unique" (index 0).
        // Defaulting to 0 explicitly beats inheriting a neighbour's value.
        auto idx = static_cast<int>(find_int("match_index", close, 0));
        if (!name.empty() && !pat.empty()) {
            PatEntry& e = g_patterns[name];
            if (!parse_pattern(pat, e.bytes, e.mask)) {
                g_patterns.erase(name);
                ++malformed;
            } else {
                e.match_index = idx;
            }
        }
        pos = close + 1;
    }
    if (malformed) {
        Loader::get().log("[fn] dropped " + std::to_string(malformed)
                          + " malformed pattern(s)");
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
    // Callers pass an address they computed themselves (a resolve result plus
    // an anchor offset, or a baked VA), so the range is not guaranteed mapped.
    // This is the LAST gate before a MinHook install — reading past the end of
    // .text here would fault during boot.
    if (!mem_accessible(va, e.bytes.size(), false)) return false;
    auto base = reinterpret_cast<const std::uint8_t*>(va);
    for (std::size_t k = 0; k < e.bytes.size(); k++) {
        if (e.mask[k] && base[k] != e.bytes[k]) return false;
    }
    return true;
}

bool fn_is_function_start(std::uintptr_t va) {
    // The module's own .pdata (exception directory) lists one RUNTIME_FUNCTION
    // per function, sorted by BeginAddress. A binary search over it answers
    // "is this an entry point" exactly, with no prologue guesswork.
    HMODULE h = GetModuleHandleA("Ravenswatch.exe");
    if (!h) h = GetModuleHandleA(nullptr);
    if (!h) return false;
    const auto base = reinterpret_cast<std::uintptr_t>(h);
    auto* dos = reinterpret_cast<IMAGE_DOS_HEADER*>(h);
    if (!mem_accessible(base, sizeof(IMAGE_DOS_HEADER), false)) return false;
    auto* nt = reinterpret_cast<IMAGE_NT_HEADERS64*>(base + dos->e_lfanew);
    if (!mem_accessible(reinterpret_cast<std::uintptr_t>(nt),
                        sizeof(IMAGE_NT_HEADERS64), false)) return false;

    const auto& dir =
        nt->OptionalHeader.DataDirectory[IMAGE_DIRECTORY_ENTRY_EXCEPTION];
    if (dir.VirtualAddress == 0 || dir.Size < sizeof(RUNTIME_FUNCTION)) return false;
    const auto table_addr = base + dir.VirtualAddress;
    if (!mem_accessible(table_addr, dir.Size, false)) return false;

    const auto* fns = reinterpret_cast<const RUNTIME_FUNCTION*>(table_addr);
    const std::size_t n = dir.Size / sizeof(RUNTIME_FUNCTION);
    if (va < base) return false;
    const auto rva = static_cast<std::uint32_t>(va - base);

    std::size_t lo = 0, hi = n;
    while (lo < hi) {
        const std::size_t mid = lo + (hi - lo) / 2;
        const auto begin = fns[mid].BeginAddress;
        if (begin == rva) return true;
        if (begin < rva) lo = mid + 1;
        else hi = mid;
    }
    return false;
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

size_t fn_resolver_dump_resolved(const std::string& path) {
    if (!g_inited && !fn_resolver_init()) return 0;
    // Snapshot the semantic pattern names first (force_resolve mutates the
    // cache but not the map, so iterating names is stable).
    std::vector<std::string> names;
    names.reserve(g_patterns.size());
    for (auto& [name, _] : g_patterns) {
        // Skip the FUN_<addr> aliases — only the human-named symbols matter for
        // an audit against symbols.json.
        if (name.rfind("FUN_", 0) != 0) names.push_back(name);
    }
    std::ofstream out(path, std::ios::trunc);
    if (!out) {
        Loader::get().log_warn("[fn] dump: cannot write " + path);
        return 0;
    }
    out << "[\n";
    size_t written = 0;
    bool first = true;
    for (auto& name : names) {
        auto va = fn_resolve(name);          // force-resolves + caches
        if (!out) break;
        if (!first) out << ",\n";
        first = false;
        out << "  {\"name\":\"" << name << "\",\"va\":";
        if (va && mem_accessible(va, 16, false)) {
            char hexva[24];
            std::snprintf(hexva, sizeof(hexva), "\"0x%llx\"",
                          static_cast<unsigned long long>(va));
            out << hexva << ",\"bytes\":\"";
            // First 16 bytes at the resolved VA — the prologue an auditor can
            // re-disassemble to confirm it's a real function start.
            auto* p = reinterpret_cast<const unsigned char*>(va);
            char hb[3];
            for (int i = 0; i < 16; i++) {
                std::snprintf(hb, sizeof(hb), "%02x", p[i]);
                out << hb;
            }
            out << "\"}";
            written++;
        } else {
            out << "null,\"bytes\":null}";
        }
    }
    out << "\n]\n";
    Loader::get().log("[fn] dumped " + std::to_string(written) + " resolved symbols -> " + path);
    return written;
}

} // namespace rsmm
