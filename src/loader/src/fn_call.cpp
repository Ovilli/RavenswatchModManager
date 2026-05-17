// Generic function caller for Windows x64. We dispatch on argtypes via
// a switch instead of pulling in libffi — the supported shapes (up to 8
// args, primitive types) cover every game function a mod is going to
// touch, and a switch keeps the build dep-free.

#include "fn_call.h"

#include <cstring>

namespace rsmm {
namespace {

constexpr int MAX_ARGS = 8;

using GP1 = std::uint64_t (*)(std::uint64_t);
using GP2 = std::uint64_t (*)(std::uint64_t, std::uint64_t);
using GP3 = std::uint64_t (*)(std::uint64_t, std::uint64_t, std::uint64_t);
using GP4 = std::uint64_t (*)(std::uint64_t, std::uint64_t, std::uint64_t, std::uint64_t);
using GP5 = std::uint64_t (*)(std::uint64_t, std::uint64_t, std::uint64_t, std::uint64_t,
                              std::uint64_t);
using GP6 = std::uint64_t (*)(std::uint64_t, std::uint64_t, std::uint64_t, std::uint64_t,
                              std::uint64_t, std::uint64_t);
using GP7 = std::uint64_t (*)(std::uint64_t, std::uint64_t, std::uint64_t, std::uint64_t,
                              std::uint64_t, std::uint64_t, std::uint64_t);
using GP8 = std::uint64_t (*)(std::uint64_t, std::uint64_t, std::uint64_t, std::uint64_t,
                              std::uint64_t, std::uint64_t, std::uint64_t, std::uint64_t);

// Float-arg-position-aware variants. The x64 ABI puts FP args in xmm0..3
// when the corresponding slot is FP; integer slots stay in rcx/rdx/r8/r9.
// We need fixed C++ signatures so the compiler emits the right shuffle.
// Pre-canned cases for the common 1- and 2-arg float prototypes:
using GP_F = double (*)(double);
using GP_FF = double (*)(double, double);
using GP_IF = double (*)(std::uint64_t, double);
using GP_FI = double (*)(double, std::uint64_t);

} // namespace

std::uint64_t fn_call_raw(std::uintptr_t target_va,
                          std::string_view argtypes,
                          const std::uint64_t* args) {
    auto t = reinterpret_cast<void*>(target_va);
    int n = static_cast<int>(argtypes.size());
    if (n > MAX_ARGS) n = MAX_ARGS;

    // Detect any FP slots — if present, route through the FP-aware
    // helpers. Otherwise the all-integer fast path covers everything.
    bool any_fp = false;
    for (int i = 0; i < n; i++) {
        if (argtypes[i] == 'f' || argtypes[i] == 'd') { any_fp = true; break; }
    }

    if (!any_fp) {
        switch (n) {
            case 0: return reinterpret_cast<std::uint64_t(*)()>(t)();
            case 1: return reinterpret_cast<GP1>(t)(args[0]);
            case 2: return reinterpret_cast<GP2>(t)(args[0], args[1]);
            case 3: return reinterpret_cast<GP3>(t)(args[0], args[1], args[2]);
            case 4: return reinterpret_cast<GP4>(t)(args[0], args[1], args[2], args[3]);
            case 5: return reinterpret_cast<GP5>(t)(args[0], args[1], args[2], args[3], args[4]);
            case 6: return reinterpret_cast<GP6>(t)(args[0], args[1], args[2], args[3], args[4], args[5]);
            case 7: return reinterpret_cast<GP7>(t)(args[0], args[1], args[2], args[3], args[4], args[5], args[6]);
            case 8: return reinterpret_cast<GP8>(t)(args[0], args[1], args[2], args[3], args[4], args[5], args[6], args[7]);
        }
    }

    // Mixed integer/float — handle the two-arg combinations that cover
    // 95% of game math helpers. Anything broader needs libffi.
    auto as_d = [](std::uint64_t v) { double r; std::memcpy(&r, &v, sizeof(r)); return r; };
    auto from_d = [](double v) { std::uint64_t r; std::memcpy(&r, &v, sizeof(r)); return r; };
    if (n == 1) {
        return from_d(reinterpret_cast<GP_F>(t)(as_d(args[0])));
    }
    if (n == 2) {
        bool a0 = argtypes[0] == 'f' || argtypes[0] == 'd';
        bool a1 = argtypes[1] == 'f' || argtypes[1] == 'd';
        if (a0 && a1)  return from_d(reinterpret_cast<GP_FF>(t)(as_d(args[0]), as_d(args[1])));
        if (!a0 && a1) return from_d(reinterpret_cast<GP_IF>(t)(args[0], as_d(args[1])));
        if (a0 && !a1) return from_d(reinterpret_cast<GP_FI>(t)(as_d(args[0]), args[1]));
    }
    // Beyond this, surface a clear nil-return rather than crash. The
    // Lua binding rewrites this to a proper error.
    return 0;
}

} // namespace rsmm
