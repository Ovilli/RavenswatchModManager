// Calibrating the book warp against the running game.
//
// The Settings page ornaments are thin dark ink on light parchment, and their
// art is known pixel for pixel. Under a correct placement every point on the
// edge of an ornament stroke lands on a dark screen pixel with light parchment
// a few pixels away; under a wrong one, or on a frame without the page, it
// does not. The score is that LOCAL contrast, averaged over the edge points:
// a global ink-vs-paper average was tried first and is gamed by any dark area
// next to a light one (a frame without the book outscored the real page).
// Only placement (scale, dx, dy) is searched, not the shape: the shape was
// fitted on the game to ~1 px (book_warp.cpp) and the screens seen so far
// differed by placement alone.

#include "book_calib.h"

#include <algorithm>
#include <mutex>
#include <cmath>

namespace rsmm::overlay::calib {
namespace {

struct Point {
    float bx, by;   // book_warp base shape coordinates
};

float lum_of(const std::uint8_t* p) { return (p[0] * 54 + p[1] * 183 + p[2] * 19) / 256.0f; }

// Dark, opaque ornament pixels with clear art within 3 texels: stroke edges,
// where the local contrast lives. Sampled on a grid, thinned to a bounded count.
std::vector<Point> edge_points(const std::uint8_t* const ornament[2], int w, int h) {
    std::vector<Point> pts;
    auto alpha = [&](int p, int x, int y) {
        x = std::clamp(x, 0, w - 1);
        y = std::clamp(y, 0, h - 1);
        return ornament[p][(std::size_t(y) * w + x) * 4 + 3];
    };
    for (int p = 0; p < 2; ++p) {
        if (!ornament[p]) continue;
        for (int y = 0; y < h; y += 3) {
            for (int x = 0; x < w; x += 3) {
                const std::uint8_t* px = &ornament[p][(std::size_t(y) * w + x) * 4];
                if (px[3] <= 200 || lum_of(px) >= 100) continue;
                if (alpha(p, x - 3, y) >= 5 && alpha(p, x + 3, y) >= 5 && alpha(p, x, y - 3) >= 5
                    && alpha(p, x, y + 3) >= 5) {
                    continue;   // inside a stroke, not at its edge
                }
                const warp::Vec2 b = warp::base(p, float(x) / (w - 1), float(y) / (h - 1));
                pts.push_back({b.x, b.y});
            }
        }
    }
    if (pts.size() > 6000) {
        std::vector<Point> out;
        const double step = double(pts.size()) / 6000;
        for (std::size_t i = 0; i < 6000; ++i) out.push_back(pts[std::size_t(i * step)]);
        pts.swap(out);
    }
    return pts;
}

// The edge points of a pair of ornament textures, built once: tracking asks
// for them every frame, and they only depend on the (fixed) UI pack art.
const std::vector<Point>& edge_points_cached(const std::uint8_t* const ornament[2], int w, int h) {
    static std::mutex mu;
    static const std::uint8_t* key[2] = {nullptr, nullptr};
    static std::vector<Point> pts;
    std::lock_guard<std::mutex> lock(mu);
    if (key[0] != ornament[0] || key[1] != ornament[1] || pts.empty()) {
        pts = edge_points(ornament, w, h);
        key[0] = ornament[0];
        key[1] = ornament[1];
    }
    return pts;
}

// Luminance of a captured frame, or straight off a mapped readback (View).
struct FrameLum {
    const Frame& f;
    int w() const { return f.w; }
    int h() const { return f.h; }
    int at(int x, int y) const { return f.lum[std::size_t(y) * f.w + x]; }
};
struct ViewLum {
    const View& v;
    int w() const { return v.w; }
    int h() const { return v.h; }
    int at(int x, int y) const {
        const std::uint8_t* p = v.px + std::size_t(y) * v.pitch + std::size_t(x) * 4;
        return v.bgra ? (p[2] * 54 + p[1] * 183 + p[0] * 19) >> 8 : (p[0] * 54 + p[1] * 183 + p[2] * 19) >> 8;
    }
};

// Mean local contrast (brightest of 8 pixels at radius 5 minus the pixel
// itself, floored at 0) over every `stride`-th point; off-screen points
// count as no contrast.
template <class Lum>
float score(const Lum& f, const std::vector<Point>& pts, const warp::Calib& c, int stride, int ring_size = 8) {
    // The first 4 are the cheap ring tracking uses; all 8 for a full search.
    static const int kRing[8][2] = {{5, 0}, {-5, 0}, {0, 5}, {0, -5}, {4, 4}, {-4, 4}, {4, -4}, {-4, -4}};
    const float W = float(f.w()), H = float(f.h());
    double sum = 0;
    std::size_t n = 0;
    for (std::size_t i = 0; i < pts.size(); i += stride) {
        ++n;
        const int x = int(std::lround(W * 0.5f + c.dx + c.s * W * pts[i].bx));
        const int y = int(std::lround(H * 0.5f + c.dy + c.s * W * pts[i].by));
        if (x < 5 || y < 5 || x >= f.w() - 5 || y >= f.h() - 5) continue;
        const int centre = f.at(x, y);
        int ring = 0;
        for (int k = 0; k < ring_size; ++k) ring = std::max(ring, f.at(x + kRing[k][0], y + kRing[k][1]));
        sum += std::max(0, ring - centre);
    }
    return n ? float(sum / n) : 0.0f;
}

// Best placement on a (c0 +- span) grid, every `stride`-th point.
template <class Lum>
void search(const Lum& f, const std::vector<Point>& pts, warp::Calib c0, float s_span, float s_step,
            float d_span, float d_step, int stride, warp::Calib* best, float* best_score,
            int ring_size = 8) {
    for (float s = c0.s - s_span; s <= c0.s + s_span + 1e-6f; s += s_step) {
        for (float dy = c0.dy - d_span; dy <= c0.dy + d_span + 1e-6f; dy += d_step) {
            for (float dx = c0.dx - d_span; dx <= c0.dx + d_span + 1e-6f; dx += d_step) {
                const warp::Calib c{s, dx, dy};
                const float sc = score(f, pts, c, stride, ring_size);
                if (sc > *best_score) {
                    *best_score = sc;
                    *best = c;
                }
            }
        }
    }
}

// Measured offline on reconstructed 3440-wide frames: the run's and the
// lobby's Settings pages scored ~30-33 (found at identity, and at dy -19.5
// for the lobby), the run's escape menu without a book 7.
constexpr float kAccept = 18.0f;
// Tracking searches a small window and scores with a cheaper ring, and a
// 17 px miss still scored 18.8 offline, so a tracked placement must score
// close to a true lock (~29-30) to be kept.
constexpr float kTrackAccept = 24.0f;

} // namespace

Result find(const Frame& frame, const std::uint8_t* const ornament[2], int tex_w, int tex_h,
            const warp::Calib& hint) {
    Result r;
    if (frame.w <= 0 || frame.h <= 0 || tex_w <= 0 || tex_h <= 0) return r;
    const std::vector<Point>& pts = edge_points_cached(ornament, tex_w, tex_h);
    if (pts.size() < 200) return r;
    const FrameLum f{frame};

    r.identity_score = score(f, pts, warp::Calib{}, 1);
    warp::Calib best;
    float best_score = -1;
    // The last good placement first (repeat attempts are usually there),
    // then scale +-6% and offsets +-64 px around the base, then two
    // refinements around the best. The coarse steps stay under the ring
    // radius so a true match is never stepped over. Every placement measured
    // so far was within 20 px of the base, so the coarse range is generous
    // and keeps a search fast enough to retry every few frames (~0.2 s).
    search(f, pts, hint, 0.0f, 1.0f, 0.0f, 1.0f, 1, &best, &best_score);
    search(f, pts, warp::Calib{}, 0.06f, 0.01f, 64.0f, 4.0f, 8, &best, &best_score);
    search(f, pts, best, 0.01f, 0.002f, 4.0f, 1.0f, 2, &best, &best_score);
    search(f, pts, best, 0.002f, 0.0005f, 1.0f, 0.5f, 1, &best, &best_score);

    r.calib = best;
    r.score = best_score;
    r.ok = best_score >= kAccept;
    return r;
}

Result track(const View& view, const std::uint8_t* const ornament[2], int tex_w, int tex_h,
             const warp::Calib& from) {
    Result r;
    if (!view.px || view.w <= 0 || view.h <= 0) return r;
    const std::vector<Point>& pts = edge_points_cached(ornament, tex_w, tex_h);
    if (pts.size() < 200) return r;
    const ViewLum f{view};
    // Cheap enough for every frame of an animation (~0.6 M samples): a joint
    // scale x offset grid around `from`, then a finer joint grid, then the
    // offset alone. Scale and offset must be searched together: a 2% scale
    // error moves the page edges ~23 px, far beyond the 5 px contrast ring,
    // and a one-at-a-time search settles on the wrong scale. The range
    // covers one frame of the book's animations (a few px, well under 1%);
    // a bigger jump is reported lost and the caller searches from scratch.
    warp::Calib best = from;
    float best_score = score(f, pts, from, 16, 4);
    search(f, pts, from, 0.010f, 0.005f, 10.0f, 2.5f, 16, &best, &best_score, 4);
    search(f, pts, best, 0.003f, 0.0015f, 2.0f, 1.0f, 16, &best, &best_score, 4);
    best_score = -1;
    search(f, pts, best, 0.0f, 1.0f, 0.5f, 0.5f, 4, &best, &best_score, 8);
    r.calib = best;
    r.score = best_score;
    r.ok = best_score >= kTrackAccept;
    return r;
}

void Lighting::at(int page, float u, float v, float out[3]) const {
    out[0] = out[1] = out[2] = 1.0f;
    if (grid <= 0 || gain[page].size() != std::size_t(grid) * grid * 3) return;
    // Cell centres sit at (i + 0.5) / grid.
    const float fx = std::clamp(u * grid - 0.5f, 0.0f, float(grid - 1));
    const float fy = std::clamp(v * grid - 0.5f, 0.0f, float(grid - 1));
    const int x0 = int(fx), y0 = int(fy);
    const int x1 = std::min(x0 + 1, grid - 1), y1 = std::min(y0 + 1, grid - 1);
    const float tx = fx - x0, ty = fy - y0;
    const std::vector<float>& g = gain[page];
    for (int c = 0; c < 3; ++c) {
        auto G = [&](int x, int y) { return g[(std::size_t(y) * grid + x) * 3 + c]; };
        out[c] = (G(x0, y0) * (1 - tx) + G(x1, y0) * tx) * (1 - ty) + (G(x0, y1) * (1 - tx) + G(x1, y1) * tx) * ty;
    }
}

Lighting measure_lighting(const Frame& frame, const warp::Calib& c,
                          const std::uint8_t* const page[2], int page_w, int page_h,
                          const std::uint8_t* const ornament[2], int orn_w, int orn_h, int grid) {
    Lighting L;
    if (frame.rgb.size() != std::size_t(frame.w) * frame.h * 3 || grid <= 0) return L;
    constexpr int kSamples = 10;   // per cell side
    const float W = float(frame.w), H = float(frame.h);
    for (int p = 0; p < 2; ++p) {
        if (!page[p] || !ornament[p]) return Lighting{};
        std::vector<float> g(std::size_t(grid) * grid * 3, 0.0f);
        std::vector<char> valid(std::size_t(grid) * grid, 0);
        struct Sample { float lum, f[3], r[3]; };
        std::vector<Sample> cell;
        for (int cj = 0; cj < grid; ++cj) {
            for (int ci = 0; ci < grid; ++ci) {
                cell.clear();
                for (int sj = 0; sj < kSamples; ++sj) {
                    for (int si = 0; si < kSamples; ++si) {
                        const float u = (ci + (si + 0.5f) / kSamples) / grid;
                        const float v = (cj + (sj + 0.5f) / kSamples) / grid;
                        const int ox = std::min(orn_w - 1, int(u * orn_w)), oy = std::min(orn_h - 1, int(v * orn_h));
                        if (ornament[p][(std::size_t(oy) * orn_w + ox) * 4 + 3] > 10) continue;
                        const warp::Vec2 b = warp::base(p, u, v);
                        const int x = int(W * 0.5f + c.dx + c.s * W * b.x);
                        const int y = int(H * 0.5f + c.dy + c.s * W * b.y);
                        if (x < 0 || y < 0 || x >= frame.w || y >= frame.h) continue;
                        const std::uint8_t* fp = &frame.rgb[(std::size_t(y) * frame.w + x) * 3];
                        const int px = std::min(page_w - 1, int(u * page_w)), py = std::min(page_h - 1, int(v * page_h));
                        const std::uint8_t* rp = &page[p][(std::size_t(py) * page_w + px) * 4];
                        cell.push_back({float(frame.lum[std::size_t(y) * frame.w + x]),
                                        {float(fp[0]), float(fp[1]), float(fp[2])},
                                        {float(rp[0]), float(rp[1]), float(rp[2])}});
                    }
                }
                if (cell.size() < 8) continue;
                // Parchment is the brightest thing on the page: keep the top 30%.
                std::sort(cell.begin(), cell.end(), [](const Sample& a, const Sample& b) { return a.lum > b.lum; });
                cell.resize(std::max<std::size_t>(3, cell.size() * 3 / 10));
                for (int ch = 0; ch < 3; ++ch) {
                    std::vector<float> fv, rv;
                    for (const Sample& s : cell) {
                        fv.push_back(s.f[ch]);
                        rv.push_back(s.r[ch]);
                    }
                    std::nth_element(fv.begin(), fv.begin() + fv.size() / 2, fv.end());
                    std::nth_element(rv.begin(), rv.begin() + rv.size() / 2, rv.end());
                    const float ratio = fv[fv.size() / 2] / std::max(1.0f, rv[rv.size() / 2]);
                    g[(std::size_t(cj) * grid + ci) * 3 + ch] = std::clamp(ratio, 0.1f, 2.0f);
                }
                valid[std::size_t(cj) * grid + ci] = 1;
            }
        }
        // Unmeasured cells (all ornament, or off screen) take their measured
        // neighbours' average, spreading inward until every cell has a value.
        for (int pass = 0; pass < grid; ++pass) {
            bool missing = false;
            std::vector<char> next = valid;
            for (int cj = 0; cj < grid; ++cj) {
                for (int ci = 0; ci < grid; ++ci) {
                    const std::size_t k = std::size_t(cj) * grid + ci;
                    if (valid[k]) continue;
                    float sum[3] = {0, 0, 0};
                    int n = 0;
                    for (int dj = -1; dj <= 1; ++dj) {
                        for (int di = -1; di <= 1; ++di) {
                            const int x = ci + di, y = cj + dj;
                            if (x < 0 || y < 0 || x >= grid || y >= grid || !valid[std::size_t(y) * grid + x]) continue;
                            for (int ch = 0; ch < 3; ++ch) sum[ch] += g[(std::size_t(y) * grid + x) * 3 + ch];
                            ++n;
                        }
                    }
                    if (!n) {
                        missing = true;
                        continue;
                    }
                    for (int ch = 0; ch < 3; ++ch) g[k * 3 + ch] = sum[ch] / n;
                    next[k] = 1;
                }
            }
            valid.swap(next);
            if (!missing) break;
        }
        // One 3x3 box blur: the grid is coarse and the game's light is smooth.
        std::vector<float> blurred(g.size());
        for (int cj = 0; cj < grid; ++cj) {
            for (int ci = 0; ci < grid; ++ci) {
                for (int ch = 0; ch < 3; ++ch) {
                    float sum = 0;
                    int n = 0;
                    for (int dj = -1; dj <= 1; ++dj) {
                        for (int di = -1; di <= 1; ++di) {
                            const int x = std::clamp(ci + di, 0, grid - 1), y = std::clamp(cj + dj, 0, grid - 1);
                            sum += g[(std::size_t(y) * grid + x) * 3 + ch];
                            ++n;
                        }
                    }
                    blurred[(std::size_t(cj) * grid + ci) * 3 + ch] = sum / n;
                }
            }
        }
        L.gain[p].swap(blurred);
    }
    L.grid = grid;
    return L;
}

} // namespace rsmm::overlay::calib
