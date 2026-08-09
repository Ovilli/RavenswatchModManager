// Generic function caller for Windows x64.
//
// The ABI decides, PER ARGUMENT POSITION, whether the value travels in an
// integer register (RCX/RDX/R8/R9) or an SSE register (XMM0-3), based on the
// argument's TYPE. A C++ caller therefore needs the exact prototype: casting
// the target to an all-integer signature and passing a float in RCX means the
// callee reads XMM0, which holds whatever the last FP operation left there.
//
// So instead of libffi (a build dep we don't want) we template a small thunk
// over the SHAPE of the first four arguments — each is integer, float, or
// double, giving 3^4 = 81 shapes — times the three return classes (integer /
// float / double). 243 leaf functions, all trivial, generated at compile time.
// Arguments 5..8 always occupy an 8-byte stack slot regardless of type, so
// they need no shaping, and the Windows x64 caller-cleanup rule means passing
// eight arguments to a function that takes fewer is harmless — which is why
// there is no per-arity dimension.
//
// Value convention (shared with hook_lua.cpp): a slot holds the RAW register
// bits. 'd' is the double's 64 bits; 'f' is the float's 32 bits in the low
// half, exactly where the ABI puts it.

#include "fn_call.h"

#include <array>
#include <cstring>
#include <type_traits>
#include <utility>

namespace rsmm {
namespace {

constexpr int MAX_ARGS = 8;

// Per-position type kind, base-3 digits of the shape index.
enum Kind : unsigned { KInt = 0, KFloat = 1, KDouble = 2 };
constexpr unsigned kArgShapes = 81;    // 3^4
constexpr unsigned kRetKinds  = 3;     // integer-ish / float / double

constexpr unsigned kPow3[5] = { 1, 3, 9, 27, 81 };

template <unsigned Shape, int I>
constexpr Kind kind_at() { return static_cast<Kind>((Shape / kPow3[I]) % 3); }

template <unsigned Shape, int I>
using ArgT = std::conditional_t<kind_at<Shape, I>() == KFloat, float,
             std::conditional_t<kind_at<Shape, I>() == KDouble, double,
                                std::uint64_t>>;

template <unsigned R>
using RetT = std::conditional_t<R == KFloat, float,
             std::conditional_t<R == KDouble, double, std::uint64_t>>;

// Raw slot bits -> the typed argument the callee expects.
template <unsigned Shape, int I>
inline ArgT<Shape, I> arg_of(std::uint64_t v) {
    if constexpr (kind_at<Shape, I>() == KFloat) {
        float f; auto lo = static_cast<std::uint32_t>(v);
        std::memcpy(&f, &lo, sizeof(f)); return f;
    } else if constexpr (kind_at<Shape, I>() == KDouble) {
        double d; std::memcpy(&d, &v, sizeof(d)); return d;
    } else {
        return v;
    }
}

template <unsigned R>
inline std::uint64_t ret_bits(RetT<R> r) {
    if constexpr (R == KFloat) {
        std::uint32_t bits; std::memcpy(&bits, &r, sizeof(bits));
        return bits;
    } else if constexpr (R == KDouble) {
        std::uint64_t bits; std::memcpy(&bits, &r, sizeof(bits));
        return bits;
    } else {
        return r;
    }
}

template <unsigned Shape, unsigned R>
std::uint64_t call_t(void* t, const std::uint64_t* a) {
    using Fn = RetT<R> (*)(ArgT<Shape, 0>, ArgT<Shape, 1>, ArgT<Shape, 2>,
                           ArgT<Shape, 3>, std::uint64_t, std::uint64_t,
                           std::uint64_t, std::uint64_t);
    return ret_bits<R>(reinterpret_cast<Fn>(t)(
        arg_of<Shape, 0>(a[0]), arg_of<Shape, 1>(a[1]),
        arg_of<Shape, 2>(a[2]), arg_of<Shape, 3>(a[3]),
        a[4], a[5], a[6], a[7]));
}

using Thunk = std::uint64_t (*)(void*, const std::uint64_t*);

template <unsigned R, unsigned... S>
inline std::array<Thunk, sizeof...(S)> make_row(std::integer_sequence<unsigned, S...>) {
    return { &call_t<S, R>... };
}
template <unsigned... R>
inline std::array<std::array<Thunk, kArgShapes>, sizeof...(R)>
make_table(std::integer_sequence<unsigned, R...>) {
    return { make_row<R>(std::make_integer_sequence<unsigned, kArgShapes>{})... };
}
const std::array<std::array<Thunk, kArgShapes>, kRetKinds> g_thunks =
    make_table(std::make_integer_sequence<unsigned, kRetKinds>{});

Kind kind_of(char code) {
    if (code == 'f') return KFloat;
    if (code == 'd') return KDouble;
    return KInt;
}

} // namespace

std::uint64_t fn_call_raw(std::uintptr_t target_va,
                          std::string_view argtypes,
                          const std::uint64_t* args) {
    if (target_va == 0) return 0;
    auto t = reinterpret_cast<void*>(target_va);
    const int n = static_cast<int>(argtypes.size()) > MAX_ARGS
                      ? MAX_ARGS
                      : static_cast<int>(argtypes.size());

    unsigned shape = 0;
    for (int i = 0; i < n && i < 4; i++) {
        shape += static_cast<unsigned>(kind_of(argtypes[i])) * kPow3[i];
    }

    // Copy into a fixed 8-slot frame: the thunks always pass eight arguments,
    // and the unused tail must be defined rather than read off the end of a
    // shorter caller array.
    std::uint64_t frame[MAX_ARGS] = {};
    for (int i = 0; i < n; i++) frame[i] = args[i];

    // The return class is chosen by the caller (fn_call_ret), defaulting to
    // the integer thunk — the right one for void/int/pointer/string returns.
    return g_thunks[KInt][shape](t, frame);
}

std::uint64_t fn_call_raw_ret(std::uintptr_t target_va,
                              char ret_code,
                              std::string_view argtypes,
                              const std::uint64_t* args) {
    if (target_va == 0) return 0;
    auto t = reinterpret_cast<void*>(target_va);
    const int n = static_cast<int>(argtypes.size()) > MAX_ARGS
                      ? MAX_ARGS
                      : static_cast<int>(argtypes.size());

    unsigned shape = 0;
    for (int i = 0; i < n && i < 4; i++) {
        shape += static_cast<unsigned>(kind_of(argtypes[i])) * kPow3[i];
    }
    std::uint64_t frame[MAX_ARGS] = {};
    for (int i = 0; i < n; i++) frame[i] = args[i];

    return g_thunks[kind_of(ret_code)][shape](t, frame);
}

} // namespace rsmm
