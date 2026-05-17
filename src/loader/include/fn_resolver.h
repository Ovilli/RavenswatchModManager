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

// Diagnostics for `rsmm doctor` & logs.
size_t fn_resolver_pattern_count();
size_t fn_resolver_resolved_count();

} // namespace rsmm
