#pragma once
// Pattern-based function resolver: maps symbolic names like
// "FUN_1401c6d60" to runtime VAs by scanning Ravenswatch.exe's .text
// section for the byte signature recorded in data/function_patterns.json.
//
// Why pattern-resolve instead of absolute addresses: the link-time VAs
// in symbols.json hold only for the exact build that produced them.
// Every game patch shifts code around; pattern signatures survive
// minor rebuilds because they capture instruction shape, not absolute
// positions.

#include <cstdint>
#include <string>
#include <string_view>

namespace rsmm {

// Load patterns from data/function_patterns.json (relative to the mod
// manager root, located via env var RSMM_DATA or alongside the loader
// DLL). Idempotent.
bool fn_resolver_init();

// Resolve a function by symbolic name. Returns 0 on failure. Cached.
std::uintptr_t fn_resolve(std::string_view name);

// Direct address sanity-check: confirm the bytes at `va` still match
// the recorded pattern for `name`. Used by guards before calling.
bool fn_verify(std::string_view name, std::uintptr_t va);

// Is `va` the ENTRY POINT of a function, per the module's own .pdata
// exception table? This is ground truth from the binary, not a heuristic.
//
// fn_verify answers "do the recorded bytes still live here", which is a
// different question and cannot catch the failure that matters: a pattern
// recorded from an older build can match perfectly at an address that is now
// the MIDDLE of a function, because the routine was merged or inlined into a
// larger one. Detouring there does not intercept a call — it splices a jump
// into the middle of somebody else's body. Measured on the shipped build:
// four of the five names hook_skins.cpp resolves land 0x90 to 0xac0 bytes
// past a real function start.
//
// Returns false when the table cannot be read, so callers fail CLOSED.
bool fn_is_function_start(std::uintptr_t va);

// Diagnostics for `rsmm doctor` & logs.
size_t fn_resolver_pattern_count();
size_t fn_resolver_resolved_count();

// Ground-truth dump: force-resolve every SEMANTIC pattern (names not of the
// form FUN_<addr>) against the live exe and write {name, va, first-16-bytes}
// to `path` as JSON. This is the authoritative "what did the loader actually
// resolve" record — `rsmm symbols audit` diffs it against data/symbols.json so
// a mis-resolved address is caught from the RUNNING game, not a Python
// reimplementation of the scan. Returns the number of symbols written.
size_t fn_resolver_dump_resolved(const std::string& path);

} // namespace rsmm
