#pragma once
// Finds where the game's book pages are on THIS screen: matches the Settings
// page ornaments (the game's own art, known exactly) against one captured
// frame of the game's Settings page, searching the scale and offset that
// place book_warp's measured base shape on them.

#include <cstdint>
#include <vector>

#include "book_warp.h"

namespace rsmm::overlay::calib {

// One captured frame: 8-bit luminance and RGB, row-major.
struct Frame {
    int w = 0;
    int h = 0;
    std::vector<std::uint8_t> lum;
    std::vector<std::uint8_t> rgb;   // 3 bytes per pixel
};

// A frame straight off a mapped readback buffer (RGBA8 or BGRA8 rows), for
// tracking without converting the whole frame.
struct View {
    const std::uint8_t* px = nullptr;
    int w = 0;
    int h = 0;
    std::size_t pitch = 0;
    bool bgra = false;
};

struct Result {
    bool ok = false;
    warp::Calib calib;
    float score = 0;            // mean local contrast at ornament edges, best fit
    float identity_score = 0;   // the same at the uncalibrated base, for the log
};

// `ornament[p]` is page p's overlay art, RGBA8 straight alpha, tex_w x tex_h.
// `hint` (the last good placement) is tried first.
Result find(const Frame& frame, const std::uint8_t* const ornament[2], int tex_w, int tex_h,
            const warp::Calib& hint = warp::Calib{});

// Follow the book from `from` to where it is on `view`: a small, fast search
// for every frame of the book's open/close animations. `ok` false = lost.
Result track(const View& view, const std::uint8_t* const ornament[2], int tex_w, int tex_h,
             const warp::Calib& from);

// How the game lights its pages, relative to the plain page art: for each
// page, `grid` x `grid` cells of RGB multipliers (row-major, 3 floats each).
// The book is lit in the scene (a warm glow, shade toward the spine, a darker
// book in a run), and the painted pages look pasted on without it.
struct Lighting {
    int grid = 0;
    std::vector<float> gain[2];

    // Bilinear multiplier at (u, v) on `page`, or {1,1,1} when unmeasured.
    void at(int page, float u, float v, float out[3]) const;
};

// Measure it on `frame` with the book placed by `c`. `page[p]` is page p's
// plain parchment art (page_w x page_h), `ornament[p]` its overlay art: only
// pixels the ornaments leave clear are compared, and in each cell only the
// brightest samples, since the game's own buttons and rows sit on the page.
Lighting measure_lighting(const Frame& frame, const warp::Calib& c,
                          const std::uint8_t* const page[2], int page_w, int page_h,
                          const std::uint8_t* const ornament[2], int orn_w, int orn_h, int grid);

} // namespace rsmm::overlay::calib
