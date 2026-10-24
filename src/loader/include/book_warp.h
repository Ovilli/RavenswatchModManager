#pragma once
// Where the game's 3D book pages are on screen, so the mod menu can be painted
// onto them. A page is addressed by (u, v) in [0,1]^2, the coordinates of the
// game's own 2048x2048 page art (UI_BookPageBg_Options1/2); page 0 is the left
// page, 1 the right. A measured base shape (book_warp.cpp) is placed on the
// screen by a Calib that book_calib finds in the running game.

namespace rsmm::overlay::warp {

struct Vec2 {
    float x, y;
};

// Base shape -> screen: x = W/2 + dx + s*W*bx, y = H/2 + dy + s*W*by.
// Identity is the screen the base was measured on (book scaled by width).
struct Calib {
    float s = 1.0f;
    float dx = 0.0f;
    float dy = 0.0f;
};

// The base shape of (u, v) on `page`: centre-relative, in screen widths.
Vec2 base(int page, float u, float v);

// Screen position of (u, v) on `page`, for a `width` x `height` display.
Vec2 page_to_screen(int page, float u, float v, float width, float height, const Calib& c);

// The page and (u, v) under a screen position: returns 0 or 1, or -1 when the
// point is on neither page.
int screen_to_page(Vec2 p, float width, float height, const Calib& c, float* u, float* v);

// The flat plane the game's UI (buttons, rows, text) sits on, in front of
// the curved page: content (u, v) on `page` -> screen, and back (-1 = on
// neither page's plane). The page art follows page_to_screen; the content
// drawn on it follows these.
Vec2 content_to_screen(int page, float u, float v, float width, float height, const Calib& c);
int screen_to_content(Vec2 p, float width, float height, const Calib& c, float* u, float* v);

} // namespace rsmm::overlay::warp
