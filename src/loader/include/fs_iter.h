#pragma once
// Non-throwing directory iteration.
//
// `for (auto& e : fs::directory_iterator(dir, ec))` LOOKS guarded and is not.
// The error_code overload only covers CONSTRUCTION; the range-for then calls
// `operator++`, which has no error_code and throws `filesystem_error` when the
// underlying read fails mid-walk — a mod folder deleted while the hot-reload
// poll is walking it, a network/Proton share that blinks, a permission change.
//
// That matters because one of these loops (the hot-reload mtime scan) runs on
// the detached ticker thread, which has no catch at all: an escaping exception
// there is `std::terminate`, i.e. the game disappears with no dialog and a log
// whose last line is unrelated. The others sit inside the loader thread's
// try/catch, where a throw is survivable but still aborts the whole init —
// one unreadable directory entry and NO mod loads.
//
// So: construct with an error_code AND increment with one. `fn` returns false
// to stop early.

#include <filesystem>
#include <system_error>
#include <utility>

namespace rsmm {

namespace detail {
template <class It, class Fn>
void fs_walk(It it, Fn&& fn) {
    std::error_code ec;
    const It end;
    while (it != end) {
        if (!fn(*it)) return;
        // The throwing `++it` is exactly what this header exists to avoid.
        it.increment(ec);
        // A failed increment leaves the iterator unspecified — stop rather
        // than risk reading it again.
        if (ec) return;
    }
}
}  // namespace detail

// Immediate children of `dir`. A missing or unreadable directory is not an
// error here: the callback simply never fires.
template <class Fn>
void for_each_in_dir(const std::filesystem::path& dir, Fn&& fn) {
    std::error_code ec;
    std::filesystem::directory_iterator it(
        dir, std::filesystem::directory_options::skip_permission_denied, ec);
    if (ec) return;
    detail::fs_walk(std::move(it), std::forward<Fn>(fn));
}

// Whole subtree, same contract.
template <class Fn>
void for_each_in_tree(const std::filesystem::path& dir, Fn&& fn) {
    std::error_code ec;
    std::filesystem::recursive_directory_iterator it(
        dir, std::filesystem::directory_options::skip_permission_denied, ec);
    if (ec) return;
    detail::fs_walk(std::move(it), std::forward<Fn>(fn));
}

}  // namespace rsmm
