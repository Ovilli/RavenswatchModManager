// The game's 3D book pages on screen, as a fitted map from page art (u, v) to
// screen.
//
// Measured 2026-10-24 on a 3440x1440 screenshot of the Settings book (opened
// from a run's escape menu): SIFT matches between the page art
// (UI_BookPageBg_L/R under UI_BookPageBg_Options1/2) and the screen, ~600
// left / ~470 right after RANSAC, plus the four bottom corner diamonds read by
// hand (the lower pages have no other features). Residual ~1 px RMS; the
// warped ornament art lands on the game's within a pixel at the corners.
//
// Refitted 2026-10-24 on a full 3440x1440 frame of the lobby's Settings
// page: the first fit (cubic across the width) matched the outer page to ~1
// px but not the gutter, where the page curls into the spine and the right
// page came out ~25 px too far left, over the spine. The refit keeps the
// outer region of the first fit and adds each page's spine edge on the seam
// line (23 heights, up to the top of the spine) and its inner frame line
// (u 0.9175 left, 0.079 right; below the vines) where the frame was
// measured. Residual 3-4 px RMS.
//
// A page curves across its width but its vertical lines stay nearly
// straight, so the model is high order in u and low order in v:
//   u^0..5, u^0..4 v, v^2, u v^2
// Coordinates are centre-relative and in screen WIDTHS (x' = (x - W/2) / W,
// y' = (y - H/2) / W): the lobby book at 3440x1407 and the run's Settings book
// at 3440x1440 sat at the same horizontal pixels, so the book scales with the
// width. They differed by ~19 px vertically (window chrome or a different
// camera), and other screens are untested, so the shape is placed by a Calib
// that book_calib measures in the running game rather than trusted as is.

#include "book_warp.h"

#include <cmath>

namespace rsmm::overlay::warp {
namespace {

struct Term {
    int i, j;   // u^i v^j
};
constexpr Term kTerms[] = {{0, 0}, {1, 0}, {2, 0}, {3, 0}, {4, 0}, {5, 0}, {0, 1},
                           {1, 1}, {2, 1}, {3, 1}, {4, 1}, {0, 2}, {1, 2}};
constexpr int kN = sizeof(kTerms) / sizeof(kTerms[0]);

struct Fit {
    float x[kN];
    float y[kN];
};

const Fit kPages[2] = {
    {{-0.335381f, 0.329191f, 0.278722f, -0.959408f, 1.285104f, -0.601662f, -0.026581f, 0.000104f,
      -0.156147f, 0.387000f, -0.198497f, -0.027127f, 0.021570f},
     {-0.170663f, 0.016694f, 0.024107f, -0.469112f, 0.823979f, -0.391553f, 0.311656f, 0.040045f,
      0.059739f, -0.218290f, 0.120184f, 0.070426f, -0.002374f}},
    {{-0.002248f, 0.128677f, 1.020591f, -2.132513f, 2.047232f, -0.730417f, 0.001601f, 0.048133f,
      0.134009f, -0.346786f, 0.190958f, -0.003185f, 0.030894f},
     {-0.166628f, -0.030020f, -0.110037f, 0.500089f, -0.553890f, 0.191371f, 0.314647f, 0.063597f,
      -0.010894f, -0.143209f, 0.092478f, 0.066079f, -0.001883f}},
};

// The game's buttons and rows are NOT on the curved page: their edges are
// straight lines and they widen toward the camera, i.e. flat UI in front of
// it. One homography per page, content (u, v) -> base coordinates, fitted
// 2026-10-24 on the same frame to every vanilla Settings button and row: the
// top/bottom edges at two screen columns per page and each element's left and
// right ends (residual ~3 px). Content (u, v) is the same page fraction the
// layout in overlay_menu.cpp is written in.
const float kPlanes[2][9] = {
    {0.34456472f, -0.00104761f, -0.33025995f, -0.00614977f, 0.33072874f, -0.16271659f,
     -0.01737539f, -0.15248880f, 1.00000000f},
    {0.35520474f, -0.00563274f, -0.01451423f, 0.01041923f, 0.33475368f, -0.17735581f,
     0.01141775f, -0.14648929f, 1.00000000f},
};

float ipow(float b, int e) {
    float r = 1.0f;
    for (int k = 0; k < e; ++k) r *= b;
    return r;
}

// Value and partial derivatives of one fitted coordinate at (u, v).
void eval(const float c[kN], float u, float v, float* f, float* fu, float* fv) {
    *f = *fu = *fv = 0.0f;
    for (int k = 0; k < kN; ++k) {
        const int i = kTerms[k].i, j = kTerms[k].j;
        *f += c[k] * ipow(u, i) * ipow(v, j);
        if (i) *fu += c[k] * i * ipow(u, i - 1) * ipow(v, j);
        if (j) *fv += c[k] * j * ipow(u, i) * ipow(v, j - 1);
    }
}

} // namespace

Vec2 base(int page, float u, float v) {
    const Fit& k = kPages[page ? 1 : 0];
    float x, y, d1, d2;
    eval(k.x, u, v, &x, &d1, &d2);
    eval(k.y, u, v, &y, &d1, &d2);
    return {x, y};
}

Vec2 page_to_screen(int page, float u, float v, float width, float height, const Calib& c) {
    const Vec2 b = base(page, u, v);
    return {width * 0.5f + c.dx + c.s * width * b.x, height * 0.5f + c.dy + c.s * width * b.y};
}

int screen_to_page(Vec2 p, float width, float height, const Calib& c, float* u_out, float* v_out) {
    if (width <= 0 || c.s <= 0) return -1;
    // Back to the base shape's space, where the fit is solved.
    const float tx = (p.x - width * 0.5f - c.dx) / (c.s * width);
    const float ty = (p.y - height * 0.5f - c.dy) / (c.s * width);
    // Float rounding lands an exact edge a hair outside [0, 1].
    constexpr float kEdge = 2e-3f;
    // The two fits overlap by a few percent at the spine, where the pages
    // have no features and both extrapolate. That strip is margin on both,
    // so a point on both pages goes to the one it is further inside of.
    int best = -1;
    float best_depth = -1, best_u = 0, best_v = 0;
    for (int page = 0; page < 2; ++page) {
        const Fit& k = kPages[page];
        float u = 0.5f, v = 0.5f;
        bool converged = false;
        for (int it = 0; it < 20; ++it) {
            float x, xu, xv, y, yu, yv;
            eval(k.x, u, v, &x, &xu, &xv);
            eval(k.y, u, v, &y, &yu, &yv);
            const float ex = x - tx, ey = y - ty;
            if (std::fabs(ex) < 4e-6f && std::fabs(ey) < 4e-6f) {   // ~0.01 px
                converged = true;
                break;
            }
            const float det = xu * yv - xv * yu;
            if (std::fabs(det) < 1e-9f) break;
            u -= (ex * yv - ey * xv) / det;
            v -= (ey * xu - ex * yu) / det;
            if (u < -1 || u > 2 || v < -1 || v > 2) break;   // diverging: not this page
        }
        if (!converged || u < -kEdge || u > 1 + kEdge || v < -kEdge || v > 1 + kEdge) continue;
        u = std::fmin(1.0f, std::fmax(0.0f, u));
        v = std::fmin(1.0f, std::fmax(0.0f, v));
        const float depth = page == 0 ? 1 - u : u;   // distance from the spine
        if (depth > best_depth) {
            best = page;
            best_depth = depth;
            best_u = u;
            best_v = v;
        }
    }
    if (best >= 0) {
        *u_out = best_u;
        *v_out = best_v;
    }
    return best;
}

Vec2 content_to_screen(int page, float u, float v, float width, float height, const Calib& c) {
    const float* h = kPlanes[page ? 1 : 0];
    const float w = h[6] * u + h[7] * v + h[8];
    const float bx = (h[0] * u + h[1] * v + h[2]) / w;
    const float by = (h[3] * u + h[4] * v + h[5]) / w;
    return {width * 0.5f + c.dx + c.s * width * bx, height * 0.5f + c.dy + c.s * width * by};
}

int screen_to_content(Vec2 p, float width, float height, const Calib& c, float* u_out, float* v_out) {
    if (width <= 0 || c.s <= 0) return -1;
    const double bx = (p.x - width * 0.5 - c.dx) / (c.s * width);
    const double by = (p.y - height * 0.5 - c.dy) / (c.s * width);
    // The planes overlap a little at the spine, where neither page has
    // content: a point on both goes to the page it is further inside of.
    int best = -1;
    double best_depth = -1, best_u = 0, best_v = 0;
    for (int page = 0; page < 2; ++page) {
        const float* h = kPlanes[page];
        // Solve h * (u, v, 1) ~ (bx, by, 1): two linear equations in u, v.
        const double a11 = h[0] - bx * h[6], a12 = h[1] - bx * h[7], b1 = bx * h[8] - h[2];
        const double a21 = h[3] - by * h[6], a22 = h[4] - by * h[7], b2 = by * h[8] - h[5];
        const double det = a11 * a22 - a12 * a21;
        if (std::fabs(det) < 1e-12) continue;
        double u = (b1 * a22 - a12 * b2) / det, v = (a11 * b2 - a21 * b1) / det;
        constexpr double kEdge = 1e-4;   // float rounding at an exact edge
        if (u < -kEdge || u > 1 + kEdge || v < -kEdge || v > 1 + kEdge) continue;
        u = std::fmin(1.0, std::fmax(0.0, u));
        v = std::fmin(1.0, std::fmax(0.0, v));
        const double depth = page == 0 ? 1 - u : u;
        if (depth > best_depth) {
            best = page;
            best_depth = depth;
            best_u = u;
            best_v = v;
        }
    }
    if (best >= 0) {
        *u_out = float(best_u);
        *v_out = float(best_v);
    }
    return best;
}

} // namespace rsmm::overlay::warp
