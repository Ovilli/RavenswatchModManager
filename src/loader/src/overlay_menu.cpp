// The in-game mod menu, drawn as the game's Settings book in its own UI art.
//
// Generic by construction: nothing here knows any mod. The left page lists
// what manifests say; the right page draws whatever fields a mod declares
// in config_schema.toml and writes the values to its config.toml in the same
// `[config]` form the loader's R.config reads, so a running mod picks a change
// up through config_reload and fires on_change, exactly as it does for the
// desktop overlay's controls.
//
// Art and fonts come from the UI pack (rsmm.engine.ui_pack). Every draw helper
// falls back to a plain shape when its texture is absent.

#include "overlay_menu.h"

#include <algorithm>
#include <cfloat>
#include <cmath>
#include <cstdio>
#include <cstring>
#include <fstream>
#include <map>
#include <string>
#include <unordered_map>
#include <vector>

#include "imgui.h"
#include "imgui_internal.h"   // ImFontLoader / atlas packing for the game fonts
#include "json.hpp"   // single-header nlohmann::json (vendored)
#include "toml.hpp"   // single-header toml++ (vendored)

#include "loader.h"

namespace fs = std::filesystem;

namespace rsmm::overlay {
namespace {

void log(const std::string& s) { Loader::get().log("[ingame-ui] " + s); }
void log_warn(const std::string& s) { Loader::get().log_warn("[ingame-ui] " + s); }

// --- UI pack -----------------------------------------------------------------

struct Tex {
    int w = 0, h = 0;
    std::vector<std::uint8_t> rgba;
    ImTextureID id = 0;
};

struct Glyph {
    float x, y, w, h, xoff, yoff, adv;
};

// One page of an AngelCode-style bitmap font (rsmm.engine.game_font).
struct BmFont {
    int page_w = 0, page_h = 0;
    float size = 0, line_height = 0, base = 0;
    std::vector<std::uint8_t> alpha;
    std::unordered_map<std::uint32_t, Glyph> glyphs;
};

std::map<std::string, Tex> g_tex;
BmFont g_bm_title, g_bm_body;
bool g_have_title = false, g_have_body = false;
ImFont* g_font_title = nullptr;
ImFont* g_font_body = nullptr;

// Two ImGui contexts draw the menu (the screen, and the offscreen pages that
// are painted onto the game's book), each with its own font atlas and scale.
// Every entry point binds the current context's set into the globals above.
struct ContextState {
    ImGuiContext* ctx;
    ImFont* title;
    ImFont* body;
    float scale;
};
std::vector<ContextState> g_contexts;
float g_scale = 1.0f;
// The book page's height in pixels, set each frame by menu_draw. Every size
// in the book is a fraction of it, read off the game's own Settings book, so
// the menu keeps the vanilla proportions at any resolution.
float g_ph = 1000.0f;

bool read_file(const fs::path& p, std::vector<std::uint8_t>& out, std::size_t want) {
    std::ifstream f(p, std::ios::binary);
    if (!f) return false;
    out.resize(want);
    f.read(reinterpret_cast<char*>(out.data()), static_cast<std::streamsize>(want));
    return static_cast<std::size_t>(f.gcount()) == want;
}

void load_pack(const fs::path& game_dir) {
    const fs::path dir = game_dir / "rsmm" / "ui";
    nlohmann::json meta;
    try {
        std::ifstream f(dir / "pack.json");
        if (!f) {
            log("no UI pack (run `rsmm install-loader`); using the plain look");
            return;
        }
        meta = nlohmann::json::parse(f);
    } catch (const std::exception& e) {
        log_warn(std::string("UI pack unreadable: ") + e.what());
        return;
    }
    // Named, not iterated straight off value(): a range-for over a member of
    // a temporary keeps only the member alive, not the json it belongs to.
    const nlohmann::json textures = meta.value("textures", nlohmann::json::object());
    for (auto& [key, t] : textures.items()) {
        Tex tex;
        tex.w = t.value("w", 0);
        tex.h = t.value("h", 0);
        if (tex.w <= 0 || tex.h <= 0 || tex.w > 8192 || tex.h > 8192) continue;
        if (!read_file(dir / t.value("file", ""), tex.rgba, std::size_t(tex.w) * tex.h * 4)) continue;
        g_tex[key] = std::move(tex);
    }
    auto load_font = [&](const char* key, BmFont& out) {
        auto fonts = meta.value("fonts", nlohmann::json::object());
        if (!fonts.contains(key)) return false;
        const auto& j = fonts[key];
        out.page_w = j.value("w", 0);
        out.page_h = j.value("h", 0);
        out.size = j.value("size", 0.0f);
        out.line_height = j.value("line_height", 0.0f);
        out.base = j.value("base", 0.0f);
        if (out.page_w <= 0 || out.page_h <= 0 || out.line_height <= 0) return false;
        std::vector<std::uint8_t> rgba;
        if (!read_file(dir / j.value("file", ""), rgba, std::size_t(out.page_w) * out.page_h * 4))
            return false;
        out.alpha.resize(std::size_t(out.page_w) * out.page_h);
        for (std::size_t i = 0; i < out.alpha.size(); ++i) out.alpha[i] = rgba[i * 4 + 3];
        const nlohmann::json glyphs = j.value("glyphs", nlohmann::json::object());
        for (auto& [cp, g] : glyphs.items()) {
            if (!g.is_array() || g.size() < 7) continue;
            auto at = [&](int i) { return g[i].get<float>(); };
            out.glyphs[static_cast<std::uint32_t>(std::stoul(cp))] =
                Glyph{at(0), at(1), at(2), at(3), at(4), at(5), at(6)};
        }
        return !out.glyphs.empty();
    };
    g_have_title = load_font("title", g_bm_title);
    g_have_body = load_font("body", g_bm_body);
    log("UI pack: " + std::to_string(g_tex.size()) + " textures, fonts "
        + (g_have_title ? "title " : "") + (g_have_body ? "body" : ""));
}

// --- game bitmap fonts as an ImGui font loader -------------------------------
//
// ImGui 1.92 asks for glyphs at whatever size is drawn. The game ships one
// bitmap per font, so each glyph is resampled from the page: 4x4 bilinear
// samples per output pixel, clamped to the glyph's own rectangle so
// neighbours on the page never bleed in. A line is scaled to fill the
// requested size (line_height -> Size), matching ImGui's line height.

float sample(const BmFont& f, const Glyph& g, float sx, float sy) {
    const float x0 = g.x, y0 = g.y, x1 = g.x + g.w - 1, y1 = g.y + g.h - 1;
    sx = std::clamp(sx - 0.5f, x0, std::max(x0, x1));
    sy = std::clamp(sy - 0.5f, y0, std::max(y0, y1));
    const int ix = static_cast<int>(sx), iy = static_cast<int>(sy);
    const int jx = std::min(ix + 1, static_cast<int>(std::max(x0, x1)));
    const int jy = std::min(iy + 1, static_cast<int>(std::max(y0, y1)));
    const float fx = sx - ix, fy = sy - iy;
    auto at = [&](int x, int y) -> float {
        if (x < 0 || y < 0 || x >= f.page_w || y >= f.page_h) return 0.0f;
        return f.alpha[std::size_t(y) * f.page_w + x];
    };
    const float top = at(ix, iy) * (1 - fx) + at(jx, iy) * fx;
    const float bot = at(ix, jy) * (1 - fx) + at(jx, jy) * fx;
    return top * (1 - fy) + bot * fy;
}

bool bm_src_init(ImFontAtlas*, ImFontConfig* src) {
    src->FontLoaderData = src->FontData;
    return true;
}

void bm_src_destroy(ImFontAtlas*, ImFontConfig* src) { src->FontLoaderData = nullptr; }

bool bm_contains(ImFontAtlas*, ImFontConfig* src, ImWchar cp) {
    const auto* f = static_cast<const BmFont*>(src->FontLoaderData);
    return f && f->glyphs.count(cp) != 0;
}

bool bm_baked_init(ImFontAtlas*, ImFontConfig* src, ImFontBaked* baked, void*) {
    const auto* f = static_cast<const BmFont*>(src->FontLoaderData);
    if (!f || src->MergeMode) return true;
    const float k = baked->Size / f->line_height;
    baked->Ascent = std::ceil(f->base * k);
    baked->Descent = std::floor(-(f->line_height - f->base) * k);
    return true;
}

bool bm_load_glyph(ImFontAtlas* atlas, ImFontConfig* src, ImFontBaked* baked, void*,
                   ImWchar cp, ImFontGlyph* out, float* out_advance_x) {
    const auto* f = static_cast<const BmFont*>(src->FontLoaderData);
    if (!f) return false;
    const auto it = f->glyphs.find(cp);
    if (it == f->glyphs.end()) return false;
    const Glyph& g = it->second;
    const float k = baked->Size / f->line_height;
    if (out_advance_x) {
        *out_advance_x = g.adv * k;
        return true;
    }
    out->Codepoint = cp;
    out->AdvanceX = g.adv * k;
    if (g.w < 1 || g.h < 1) return true;   // space and friends: advance only

    const float density = src->RasterizerDensity * baked->RasterizerDensity;
    const float px = k * density;
    const int w = std::max(1, static_cast<int>(std::ceil(g.w * px)));
    const int h = std::max(1, static_cast<int>(std::ceil(g.h * px)));
    const ImFontAtlasRectId id = ImFontAtlasPackAddRect(atlas, w, h);
    if (id == ImFontAtlasRectId_Invalid) return false;
    ImTextureRect* r = ImFontAtlasPackGetRect(atlas, id);

    std::vector<std::uint8_t> bitmap(std::size_t(w) * h);
    constexpr int kSub = 4;
    for (int y = 0; y < h; ++y) {
        for (int x = 0; x < w; ++x) {
            float sum = 0;
            for (int sy = 0; sy < kSub; ++sy) {
                for (int sx = 0; sx < kSub; ++sx) {
                    sum += sample(*f, g, g.x + (x + (sx + 0.5f) / kSub) / px,
                                  g.y + (y + (sy + 0.5f) / kSub) / px);
                }
            }
            bitmap[std::size_t(y) * w + x] =
                static_cast<std::uint8_t>(std::clamp(sum / (kSub * kSub), 0.0f, 255.0f));
        }
    }
    out->X0 = g.xoff * k;
    out->Y0 = g.yoff * k;
    out->X1 = out->X0 + w / density;
    out->Y1 = out->Y0 + h / density;
    out->Visible = true;
    out->PackId = id;
    ImFontAtlasBakedSetFontGlyphBitmap(atlas, baked, src, out, r, bitmap.data(),
                                       ImTextureFormat_Alpha8, w);
    return true;
}

const ImFontLoader* bm_loader() {
    static ImFontLoader loader;
    loader.Name = "rsmm-bitmap";
    loader.FontSrcInit = bm_src_init;
    loader.FontSrcDestroy = bm_src_destroy;
    loader.FontSrcContainsGlyph = bm_contains;
    loader.FontBakedInit = bm_baked_init;
    loader.FontBakedLoadGlyph = bm_load_glyph;
    return &loader;
}

ImFont* add_bm_font(BmFont& f, const char* name, float size) {
    ImFontConfig cfg;
    cfg.FontData = &f;            // read by bm_src_init; the atlas never frees it
    cfg.FontDataSize = 1;
    cfg.FontDataOwnedByAtlas = false;
    cfg.FontLoader = bm_loader();
    cfg.SizePixels = size;
    std::snprintf(cfg.Name, sizeof(cfg.Name), "%s", name);
    return ImGui::GetIO().Fonts->AddFont(&cfg);
}

// --- mods, schemas, values ---------------------------------------------------

struct Value {
    enum Kind { None, Bool, Int, Float, Str } kind = None;
    bool b = false;
    std::int64_t i = 0;
    double f = 0;
    std::string s;
    double num() const { return kind == Int ? double(i) : kind == Float ? f : 0.0; }
};

struct Field {
    std::string key, type, label;
    bool has_min = false, has_max = false;
    double min = 0, max = 0;
    std::vector<std::string> choices;
    Value def;
    char text[256] = {};   // InputText buffer for string fields
};

struct ModEntry {
    std::string id, name, version, author, description;
    bool enabled = false;
    fs::path root;
    std::vector<Field> fields;
    std::string schema_error;
    std::map<std::string, Value> values;
};

std::vector<ModEntry> g_mods;

Value from_node(const toml::node& n) {
    Value v;
    if (auto b = n.as_boolean()) { v.kind = Value::Bool; v.b = **b; }
    else if (auto i = n.as_integer()) { v.kind = Value::Int; v.i = **i; }
    else if (auto f = n.as_floating_point()) { v.kind = Value::Float; v.f = **f; }
    else if (auto s = n.as_string()) { v.kind = Value::Str; v.s = **s; }
    return v;
}

void load_schema(ModEntry& m) {
    const fs::path p = m.root / "config_schema.toml";
    std::error_code ec;
    if (!fs::exists(p, ec)) return;
    toml::table doc;
    try {
        doc = toml::parse_file(p.string());
    } catch (const std::exception& e) {
        m.schema_error = e.what();
        return;
    }
    const toml::table* fields = doc["fields"].as_table();
    if (!fields) return;
    // toml++ tables are key-sorted; the author's order is the file's order.
    std::vector<std::pair<std::uint32_t, Field>> ordered;
    for (auto&& [key, node] : *fields) {
        const toml::table* t = node.as_table();
        if (!t) continue;
        Field f;
        f.key = std::string(key.str());
        f.type = (*t)["type"].value_or(std::string("string"));
        f.label = (*t)["label"].value_or(f.key);
        if (auto v = (*t)["min"].value<double>()) { f.has_min = true; f.min = *v; }
        if (auto v = (*t)["max"].value<double>()) { f.has_max = true; f.max = *v; }
        if (const toml::array* c = (*t)["choices"].as_array()) {
            for (auto&& e : *c) {
                if (auto s = e.value<std::string>()) f.choices.push_back(*s);
            }
        }
        if (const toml::node* d = t->get("default")) f.def = from_node(*d);
        ordered.emplace_back(node.source().begin.line, std::move(f));
    }
    std::stable_sort(ordered.begin(), ordered.end(),
                     [](const auto& a, const auto& b) { return a.first < b.first; });
    for (auto& [line, f] : ordered) m.fields.push_back(std::move(f));
}

void load_values(ModEntry& m) {
    const fs::path p = m.root / "config.toml";
    std::error_code ec;
    if (!fs::exists(p, ec)) return;
    try {
        toml::table doc = toml::parse_file(p.string());
        const toml::table* section = doc["config"].as_table();
        if (!section) section = &doc;
        for (auto&& [key, node] : *section) {
            const Value v = from_node(node);
            if (v.kind != Value::None) m.values[std::string(key.str())] = v;
        }
    } catch (const std::exception& e) {
        log_warn(m.id + ": config.toml unreadable: " + e.what());
    }
}

void load_mods() {
    for (const auto& src : Loader::get().mods()) {
        ModEntry m;
        m.id = src.id;
        m.name = src.name.empty() ? src.id : src.name;
        m.version = src.version;
        m.author = src.author;
        m.enabled = src.enabled;
        m.root = src.root;
        try {
            toml::table man = toml::parse_file((src.root / "manifest.toml").string());
            m.description = man["mod"]["description"].value_or(std::string());
        } catch (const std::exception&) {
        }
        load_schema(m);
        load_values(m);
        for (Field& f : m.fields) {
            if (f.type != "string") continue;
            const auto it = m.values.find(f.key);
            const std::string& s = it != m.values.end() ? it->second.s : f.def.s;
            std::snprintf(f.text, sizeof(f.text), "%s", s.c_str());
        }
        g_mods.push_back(std::move(m));
    }
    std::sort(g_mods.begin(), g_mods.end(), [](const ModEntry& a, const ModEntry& b) {
        return a.name < b.name;
    });
}

Value value_of(const ModEntry& m, const Field& f) {
    const auto it = m.values.find(f.key);
    return it != m.values.end() ? it->second : f.def;
}

// Same shape the loader's config_write_file produces: a `[config]` table,
// temp file + rename. Keys the menu does not know are kept.
bool write_values(ModEntry& m) {
    const fs::path dst = m.root / "config.toml";
    const fs::path tmp = m.root / "config.toml.tmp";
    toml::table doc;
    std::error_code ec;
    if (fs::exists(dst, ec)) {
        try {
            doc = toml::parse_file(dst.string());
        } catch (const std::exception&) {
            doc = toml::table{};
        }
    }
    toml::table section;
    if (const toml::table* c = doc["config"].as_table()) {
        section = *c;
    } else {
        for (auto&& [k, n] : doc) {   // a flat file: keep its values
            if (!n.is_table()) section.insert(k, n);
        }
    }
    for (const auto& [key, v] : m.values) {
        switch (v.kind) {
            case Value::Bool: section.insert_or_assign(key, v.b); break;
            case Value::Int: section.insert_or_assign(key, v.i); break;
            case Value::Float: section.insert_or_assign(key, v.f); break;
            case Value::Str: section.insert_or_assign(key, v.s); break;
            case Value::None: break;
        }
    }
    toml::table out;
    out.insert("config", std::move(section));
    {
        std::ofstream f(tmp, std::ios::trunc);
        if (!f) return false;
        f << out << "\n";
        if (!f.good()) return false;
    }
    fs::rename(tmp, dst, ec);
    if (ec) {
        fs::remove(tmp, ec);
        log_warn(m.id + ": could not write config.toml");
        return false;
    }
    return true;
}

void set_value(ModEntry& m, const Field& f, Value v, bool write_now) {
    if (f.type == "int") { v.i = std::int64_t(std::llround(v.num())); v.kind = Value::Int; }
    if (f.type == "float") { v.f = v.num(); v.kind = Value::Float; }
    m.values[f.key] = v;
    if (write_now) write_values(m);
}

// --- drawing -----------------------------------------------------------------
//
// Laid out after the game's own Settings screen (an open book): categories as
// buttons on the left page, parameter rows on the right page.

// Colours read off the game's Settings screen.
const ImU32 kInk = IM_COL32(59, 48, 38, 255);        // labels and values on parchment
const ImU32 kInkSoft = IM_COL32(110, 98, 82, 255);   // secondary text on parchment
const ImU32 kLight = IM_COL32(236, 226, 204, 255);   // text on the dark buttons
const ImU32 kOff = IM_COL32(150, 140, 125, 255);     // disabled
const ImU32 kOrnament = IM_COL32(92, 80, 66, 200);   // white ornaments, tinted
const ImU32 kKnot = IM_COL32(150, 142, 128, 210);    // the row's knot decoration
const ImU32 kTrack = IM_COL32(86, 72, 58, 255);      // slider track
const ImU32 kCover = IM_COL32(46, 36, 30, 255);      // book cover around the pages

const Tex* tex(const char* key) {
    const auto it = g_tex.find(key);
    return it != g_tex.end() && it->second.id ? &it->second : nullptr;
}

void image(ImDrawList* dl, const char* key, ImVec2 a, ImVec2 b, ImU32 tint = IM_COL32_WHITE,
           ImVec2 uv0 = ImVec2(0, 0), ImVec2 uv1 = ImVec2(1, 1)) {
    if (const Tex* t = tex(key)) dl->AddImage(t->id, a, b, uv0, uv1, tint);
}

// Stretch the middle, keep the ends: buttons and rows have shaped end caps.
void image3(ImDrawList* dl, const char* key, ImVec2 a, ImVec2 b, float cap_l, float cap_r,
            ImU32 tint = IM_COL32_WHITE, ImU32 fallback = IM_COL32(70, 58, 44, 230)) {
    const Tex* t = tex(key);
    if (!t) {
        dl->AddRectFilled(a, b, fallback, 6 * g_scale);
        return;
    }
    const float k = (b.y - a.y) / t->h;
    float l = cap_l * k, r = cap_r * k;
    const float room = b.x - a.x;
    if (l + r > room) {
        const float shrink = room / (l + r);
        l *= shrink;
        r *= shrink;
    }
    const float u1 = cap_l / t->w, u2 = 1.0f - cap_r / t->w;
    dl->AddImage(t->id, a, ImVec2(a.x + l, b.y), ImVec2(0, 0), ImVec2(u1, 1), tint);
    dl->AddImage(t->id, ImVec2(a.x + l, a.y), ImVec2(b.x - r, b.y), ImVec2(u1, 0), ImVec2(u2, 1), tint);
    dl->AddImage(t->id, ImVec2(b.x - r, a.y), b, ImVec2(u2, 0), ImVec2(1, 1), tint);
}

void bind_context() {
    for (const ContextState& c : g_contexts) {
        if (c.ctx == ImGui::GetCurrentContext()) {
            g_font_title = c.title;
            g_font_body = c.body;
            g_scale = c.scale;
            return;
        }
    }
}

ImFont* font_title() { return g_font_title ? g_font_title : ImGui::GetFont(); }
ImFont* font_body() { return g_font_body ? g_font_body : ImGui::GetFont(); }

ImVec2 measure(ImFont* f, float size, const char* s) {
    return f->CalcTextSizeA(size, FLT_MAX, 0.0f, s);
}

std::string fit(ImFont* f, float size, const std::string& s, float width) {
    if (measure(f, size, s.c_str()).x <= width) return s;
    std::string cut = s;
    while (!cut.empty() && measure(f, size, (cut + "...").c_str()).x > width) cut.pop_back();
    return cut + "...";
}

void text_at(ImDrawList* dl, ImFont* f, float size, ImVec2 p, ImU32 col, const std::string& s) {
    dl->AddText(f, size, p, col, s.c_str());
}

void text_centered(ImDrawList* dl, ImFont* f, float size, ImVec2 a, ImVec2 b, ImU32 col,
                   const std::string& s) {
    const std::string t = fit(f, size, s, b.x - a.x);
    const ImVec2 sz = measure(f, size, t.c_str());
    dl->AddText(f, size, ImVec2((a.x + b.x - sz.x) * 0.5f, (a.y + b.y - sz.y) * 0.5f), col, t.c_str());
}

// A category button of the Settings book: dark, gold when selected.
bool menu_button(const char* id, const std::string& label, ImVec2 size, bool selected,
                 bool enabled = true) {
    const ImVec2 a = ImGui::GetCursorScreenPos();
    const bool clicked = ImGui::InvisibleButton(id, size);
    const bool hovered = ImGui::IsItemHovered();
    const ImVec2 b(a.x + size.x, a.y + size.y);
    ImDrawList* dl = ImGui::GetWindowDrawList();
    const char* key = selected ? "button_selected" : !enabled ? "button_disabled"
                    : hovered ? "button_hover" : "button";
    image3(dl, key, a, b, 100, 100, IM_COL32_WHITE,
           selected ? IM_COL32(200, 168, 110, 240) : IM_COL32(80, 66, 50, 230));
    const float pad = size.y * 0.6f;
    text_centered(dl, font_title(), size.y * 0.36f, ImVec2(a.x + pad, a.y), ImVec2(b.x - pad, b.y),
                  selected ? kInk : enabled ? kLight : kOff, label);
    return clicked;
}

// The dark "Reset to default" button.
bool confirm_button(const char* id, const std::string& label, ImVec2 size) {
    const ImVec2 a = ImGui::GetCursorScreenPos();
    const bool clicked = ImGui::InvisibleButton(id, size);
    const bool hovered = ImGui::IsItemHovered();
    const ImVec2 b(a.x + size.x, a.y + size.y);
    ImDrawList* dl = ImGui::GetWindowDrawList();
    image3(dl, hovered ? "confirm_hover" : "confirm", a, b, 40, 40, IM_COL32_WHITE,
           IM_COL32(30, 26, 20, 240));
    text_centered(dl, font_body(), size.y * 0.44f, a, b, kLight, label);
    return clicked;
}

// < value > as on the game's options rows. Returns -1, 0 or +1.
int arrows(const char* id, ImVec2 a, ImVec2 b, const std::string& value) {
    ImDrawList* dl = ImGui::GetWindowDrawList();
    const float h = (b.y - a.y) * 0.72f;
    const float aw = h * 64.0f / 78.0f;
    const float cy = (a.y + b.y) * 0.5f;
    int step = 0;
    for (int side = 0; side < 2; ++side) {
        const ImVec2 p0(side == 0 ? a.x : b.x - aw, cy - h * 0.5f);
        const ImVec2 p1(p0.x + aw, cy + h * 0.5f);
        ImGui::SetCursorScreenPos(p0);
        ImGui::PushID(side);
        if (ImGui::InvisibleButton(id, ImVec2(aw, h))) step = side == 0 ? -1 : 1;
        const ImU32 tint = ImGui::IsItemHovered() ? IM_COL32(255, 244, 214, 255) : IM_COL32_WHITE;
        ImGui::PopID();
        if (tex("arrow")) {
            // The art points right; the left arrow is the same image mirrored.
            image(dl, "arrow", p0, p1, tint, ImVec2(side == 0 ? 1.0f : 0.0f, 0),
                  ImVec2(side == 0 ? 0.0f : 1.0f, 1));
        } else {
            text_centered(dl, font_body(), h, p0, p1, kInk, side == 0 ? "<" : ">");
        }
    }
    text_centered(dl, font_body(), (b.y - a.y) * 0.45f, ImVec2(a.x + aw, a.y),
                  ImVec2(b.x - aw, b.y), kInk, value);
    return step;
}

// The game's slider: dark track with diamond ends + gold diamond handle.
// `released` is set on the frame a drag ends.
bool slider(const char* id, ImVec2 a, ImVec2 b, double& v, double lo, double hi, bool* released) {
    ImDrawList* dl = ImGui::GetWindowDrawList();
    const float h = b.y - a.y;
    const float handle = h * 0.62f;
    const float x0 = a.x + handle * 0.5f, x1 = b.x - handle * 0.5f;
    ImGui::SetCursorScreenPos(a);
    ImGui::InvisibleButton(id, ImVec2(b.x - a.x, h));
    const bool active = ImGui::IsItemActive();
    const bool hovered = ImGui::IsItemHovered();
    *released = ImGui::IsItemDeactivated();
    bool changed = false;
    if (active && hi > lo) {
        const float t = std::clamp((ImGui::GetIO().MousePos.x - x0) / std::max(1.0f, x1 - x0), 0.0f, 1.0f);
        const double nv = lo + (hi - lo) * t;
        changed = nv != v;
        v = nv;
    }
    const float cy = (a.y + b.y) * 0.5f;
    const float track_h = h * 0.30f;
    if (tex("slider")) {
        image(dl, "slider", ImVec2(a.x, cy - track_h * 0.5f), ImVec2(b.x, cy + track_h * 0.5f), kTrack);
    } else {
        dl->AddLine(ImVec2(a.x, cy), ImVec2(b.x, cy), kTrack, 2 * g_scale);
    }
    const float t = hi > lo ? float((v - lo) / (hi - lo)) : 0.0f;
    const float hx = x0 + (x1 - x0) * std::clamp(t, 0.0f, 1.0f);
    const ImVec2 h0(hx - handle * 0.5f, cy - handle * 0.5f), h1(hx + handle * 0.5f, cy + handle * 0.5f);
    if (tex("slider_handle")) {
        image(dl, "slider_handle", h0, h1,
              active || hovered ? IM_COL32(255, 246, 222, 255) : IM_COL32_WHITE);
    } else {
        dl->AddCircleFilled(ImVec2(hx, cy), handle * 0.4f, IM_COL32(232, 194, 122, 255));
    }
    return changed;
}

std::string format_value(const Field& f, const Value& v) {
    char buf[64];
    if (f.type == "int") {
        std::snprintf(buf, sizeof(buf), "%lld", static_cast<long long>(std::llround(v.num())));
        return buf;
    }
    std::snprintf(buf, sizeof(buf), "%.2f", v.num());
    std::string s = buf;   // 1.50 -> 1.5, 2.00 -> 2
    while (!s.empty() && s.back() == '0') s.pop_back();
    if (!s.empty() && s.back() == '.') s.pop_back();
    return s;
}

// One page of the book: the parchment under the Settings screen's own
// ornament overlay (frame, vines and, on the left, the title cartouche), with
// the fold darkening toward the spine.
void page(ImDrawList* dl, const char* parchment, const char* ornament, ImVec2 a, ImVec2 b,
          bool right) {
    if (tex(parchment)) image(dl, parchment, a, b);
    else dl->AddRectFilled(a, b, IM_COL32(214, 205, 184, 255));
    if (tex(ornament)) {
        image(dl, ornament, a, b);
    } else {
        const float in = 26 * g_scale;
        dl->AddRect(ImVec2(a.x + in, a.y + in), ImVec2(b.x - in, b.y - in), kOrnament, 0, 0,
                    1.6f * g_scale);
    }
    const float shade = (b.x - a.x) * 0.05f;
    if (right) {
        dl->AddRectFilledMultiColor(a, ImVec2(a.x + shade, b.y), IM_COL32(0, 0, 0, 80),
                                    IM_COL32(0, 0, 0, 0), IM_COL32(0, 0, 0, 0), IM_COL32(0, 0, 0, 80));
    } else {
        dl->AddRectFilledMultiColor(ImVec2(b.x - shade, a.y), b, IM_COL32(0, 0, 0, 0),
                                    IM_COL32(0, 0, 0, 80), IM_COL32(0, 0, 0, 80), IM_COL32(0, 0, 0, 0));
    }
}

// --- pages -------------------------------------------------------------------

int g_sel = 0;           // index into g_mods
int g_dirty = -1;        // a slider changed this mod's values; write on release


void mod_list(float row_h) {
    const float w = ImGui::GetContentRegionAvail().x;
    for (int i = 0; i < int(g_mods.size()); ++i) {
        const ModEntry& m = g_mods[i];
        ImGui::PushID(i);
        if (menu_button("mod", m.name, ImVec2(w, row_h), i == g_sel, m.enabled)) g_sel = i;
        ImGui::PopID();
        ImGui::Dummy(ImVec2(0, row_h * 0.21f));   // vanilla: 0.066 tall every 0.080
    }
    if (g_mods.empty()) {
        ImDrawList* dl = ImGui::GetWindowDrawList();
        text_at(dl, font_body(), g_ph * 0.021f, ImGui::GetCursorScreenPos(), kInkSoft,
                "No mods are installed.");
    }
}

// The selected mod's name, version/author and description, drawn above the
// scrolling rows so it never scrolls away. Returns the height it used. A long
// description is cut at whole words to `max_h`.
float details_header(ImDrawList* dl, const ModEntry& m, ImVec2 p, float w, float max_h) {
    const float ts = g_ph * 0.036f, bs = g_ph * 0.0205f;
    text_at(dl, font_title(), ts, p, kInk, fit(font_title(), ts, m.name, w));
    std::string sub = m.version.empty() ? std::string() : "v" + m.version;
    if (!m.author.empty()) sub += (sub.empty() ? "by " : "  -  by ") + m.author;
    if (!m.enabled) sub += sub.empty() ? "Disabled" : "  -  Disabled";
    float y = p.y + ts * 1.05f;
    text_at(dl, font_body(), bs, ImVec2(p.x, y), kInkSoft, sub);
    y += bs * 1.45f;
    if (!m.description.empty()) {
        std::string d = m.description;
        const float room = max_h - (y - p.y) - g_ph * 0.04f;
        while (d.size() > 1 && font_body()->CalcTextSizeA(bs, FLT_MAX, w, d.c_str()).y > room) {
            const auto cut = d.find_last_of(' ', d.size() - 2);
            d = (cut == std::string::npos ? d.substr(0, d.size() / 2) : d.substr(0, cut)) + "...";
        }
        dl->AddText(font_body(), bs, ImVec2(p.x, y), kInk, d.c_str(), nullptr, w);
        y += font_body()->CalcTextSizeA(bs, FLT_MAX, w, d.c_str()).y + bs * 0.5f;
    }
    if (const Tex* r = tex("rule")) {
        const float rw = std::min(w * 0.6f, g_ph * 0.30f);
        const float rh = rw * r->h / r->w;
        image(dl, "rule", ImVec2(p.x + (w - rw) * 0.5f, y), ImVec2(p.x + (w + rw) * 0.5f, y + rh), kOrnament);
        y += rh;
    }
    return y - p.y + bs * 0.6f;
}

void field_row(ModEntry& m, Field& f, int index, float row_h) {
    ImDrawList* dl = ImGui::GetWindowDrawList();
    const float w = ImGui::GetContentRegionAvail().x;
    const ImVec2 a = ImGui::GetCursorScreenPos();
    const ImVec2 b(a.x + w, a.y + row_h);
    const bool hover = ImGui::IsMouseHoveringRect(a, b) && ImGui::IsWindowHovered();
    // The row art's pointed end sits behind the knot, as in the game.
    const float knot = row_h * 1.05f;
    image3(dl, hover ? "row_hover" : "row", ImVec2(a.x + knot * 0.45f, a.y), b, 110, 24,
           IM_COL32_WHITE, IM_COL32(0, 0, 0, 30));
    if (const Tex* d = tex("deco")) {
        const float dh = row_h * 0.86f, dw = dh * d->w / d->h;
        image(dl, "deco", ImVec2(a.x, a.y + (row_h - dh) * 0.5f), ImVec2(a.x + dw, a.y + (row_h + dh) * 0.5f), kKnot);
    }

    const float label_x = a.x + knot + row_h * 0.15f;
    const float ctrl_w = w * 0.40f;
    const ImVec2 c0(b.x - ctrl_w - row_h * 0.25f, a.y + row_h * 0.12f);
    const ImVec2 c1(b.x - row_h * 0.25f, b.y - row_h * 0.12f);
    const float ls = row_h * 0.34f;   // the game's labels are a third of the row
    const float label_w = c0.x - label_x - row_h * 0.3f;
    const std::string shown = fit(font_body(), ls, f.label, label_w);
    const ImVec2 lp(label_x, a.y + (row_h - ls) * 0.5f - row_h * 0.04f);
    text_at(dl, font_body(), ls, lp, kInk, shown);
    if (shown != f.label && ImGui::IsWindowHovered()
        && ImGui::IsMouseHoveringRect(lp, ImVec2(lp.x + label_w, lp.y + ls))) {
        ImGui::PushStyleColor(ImGuiCol_Text, ImColor(kLight).Value);
        ImGui::PushFont(font_body(), g_ph * 0.019f);
        ImGui::BeginTooltip();
        ImGui::PushTextWrapPos(520 * g_scale);
        ImGui::TextUnformatted(f.label.c_str());
        ImGui::PopTextWrapPos();
        ImGui::EndTooltip();
        ImGui::PopFont();
        ImGui::PopStyleColor();
    }

    ImGui::PushID(index);
    Value v = value_of(m, f);
    if (f.type == "bool") {
        const bool on = v.kind == Value::Bool ? v.b : false;
        if (arrows("b", c0, c1, on ? "On" : "Off")) {
            Value nv;
            nv.kind = Value::Bool;
            nv.b = !on;
            set_value(m, f, nv, true);
        }
    } else if (f.type == "enum" && !f.choices.empty()) {
        int cur = 0;
        for (int i = 0; i < int(f.choices.size()); ++i) {
            if (f.choices[i] == v.s) cur = i;
        }
        if (const int step = arrows("e", c0, c1, f.choices[cur])) {
            const int n = int(f.choices.size());
            Value nv;
            nv.kind = Value::Str;
            nv.s = f.choices[((cur + step) % n + n) % n];
            set_value(m, f, nv, true);
        }
    } else if ((f.type == "int" || f.type == "float") && f.has_min && f.has_max) {
        const float vw = (c1.y - c0.y) * 2.2f;
        double d = v.num();
        bool released = false;
        if (slider("s", c0, ImVec2(c1.x - vw - 10 * g_scale, c1.y), d, f.min, f.max, &released)) {
            Value nv;
            nv.kind = Value::Float;
            nv.f = d;
            set_value(m, f, nv, false);
            g_dirty = int(&m - g_mods.data());
        }
        if (released && g_dirty >= 0) {
            write_values(g_mods[g_dirty]);
            g_dirty = -1;
        }
        const std::string s = format_value(f, value_of(m, f));
        const float vs = (c1.y - c0.y) * 0.45f;
        const ImVec2 sz = measure(font_body(), vs, s.c_str());
        text_at(dl, font_body(), vs, ImVec2(c1.x - sz.x, (c0.y + c1.y - sz.y) * 0.5f), kInk, s);
    } else if (f.type == "int" || f.type == "float") {
        const double step = f.type == "int" ? 1.0 : (std::fabs(v.num()) >= 10 ? 1.0 : 0.1);
        if (const int dir = arrows("n", c0, c1, format_value(f, v))) {
            double nvn = v.num() + dir * step;
            if (f.has_min) nvn = std::max(nvn, f.min);
            if (f.has_max) nvn = std::min(nvn, f.max);
            Value nv;
            nv.kind = Value::Float;
            nv.f = nvn;
            set_value(m, f, nv, true);
        }
    } else if (f.type == "string") {
        ImGui::SetCursorScreenPos(ImVec2(c0.x, (a.y + b.y) * 0.5f - ImGui::GetFrameHeight() * 0.5f));
        ImGui::SetNextItemWidth(c1.x - c0.x);
        ImGui::PushFont(font_body(), ls);
        if (ImGui::InputText("##t", f.text, sizeof(f.text), ImGuiInputTextFlags_EnterReturnsTrue)
            || ImGui::IsItemDeactivatedAfterEdit()) {
            Value nv;
            nv.kind = Value::Str;
            nv.s = f.text;
            set_value(m, f, nv, true);
        }
        ImGui::PopFont();
    } else {
        // multiselect / item-grid: a picker of game art, which is the desktop
        // app's job.
        text_centered(dl, font_body(), ls * 0.85f, c0, c1, kInkSoft, "Edit in the desktop app");
    }
    ImGui::PopID();
    ImGui::SetCursorScreenPos(ImVec2(a.x, b.y + row_h * 0.15f));   // vanilla: 0.060 every 0.069
    ImGui::Dummy(ImVec2(w, 0));
}

void details_rows(float row_h) {
    if (g_sel < 0 || g_sel >= int(g_mods.size())) return;
    ModEntry& m = g_mods[g_sel];
    ImDrawList* dl = ImGui::GetWindowDrawList();
    const float bs = g_ph * 0.021f;
    const float w = ImGui::GetContentRegionAvail().x;
    if (!m.schema_error.empty()) {
        const std::string msg = "config_schema.toml did not parse: " + m.schema_error;
        dl->AddText(font_body(), bs, ImGui::GetCursorScreenPos(), kInk, msg.c_str(), nullptr, w);
        return;
    }
    if (m.fields.empty()) {
        text_at(dl, font_body(), bs, ImGui::GetCursorScreenPos(), kInkSoft, "This mod has no settings.");
        return;
    }
    for (int i = 0; i < int(m.fields.size()); ++i) field_row(m, m.fields[i], i, row_h);
}

void reset_defaults(ModEntry& m) {
    for (Field& f : m.fields) {
        if (f.def.kind == Value::None) continue;
        m.values[f.key] = f.def;
        if (f.type == "string") std::snprintf(f.text, sizeof(f.text), "%s", f.def.s.c_str());
    }
    write_values(m);
}

} // namespace

// --- entry points ------------------------------------------------------------

void menu_init(const fs::path& game_dir) {
    load_pack(game_dir);
    load_mods();
    std::size_t with = 0;
    for (const auto& m : g_mods) with += m.fields.empty() ? 0 : 1;
    log(std::to_string(g_mods.size()) + " mod(s), " + std::to_string(with) + " with settings");
}

void menu_setup_imgui(float scale) {
    g_scale = scale;
    ImGuiIO& io = ImGui::GetIO();
    g_font_body = g_have_body ? add_bm_font(g_bm_body, "Fontin Sans (game)", 22.0f) : nullptr;
    g_font_title = g_have_title ? add_bm_font(g_bm_title, "Germania One (game)", 40.0f) : nullptr;
    if (g_font_body) io.FontDefault = g_font_body;
    g_contexts.push_back({ImGui::GetCurrentContext(), g_font_title, g_font_body, scale});

    ImGuiStyle& st = ImGui::GetStyle();
    st.WindowBorderSize = 0;
    st.FrameRounding = 4 * scale;
    st.ScrollbarSize = 14 * scale;
    st.ScrollbarRounding = 6 * scale;
    ImVec4* c = st.Colors;
    c[ImGuiCol_Text] = ImColor(kInk);
    c[ImGuiCol_TextDisabled] = ImColor(kInkSoft);
    c[ImGuiCol_WindowBg] = ImVec4(0, 0, 0, 0);
    c[ImGuiCol_ChildBg] = ImVec4(0, 0, 0, 0);
    c[ImGuiCol_FrameBg] = ImVec4(0.93f, 0.90f, 0.82f, 0.85f);
    c[ImGuiCol_FrameBgHovered] = ImVec4(0.96f, 0.93f, 0.86f, 0.95f);
    c[ImGuiCol_FrameBgActive] = ImVec4(1.0f, 0.97f, 0.90f, 1.0f);
    c[ImGuiCol_ScrollbarBg] = ImVec4(0, 0, 0, 0.06f);
    c[ImGuiCol_ScrollbarGrab] = ImColor(kTrack);
    c[ImGuiCol_ScrollbarGrabHovered] = ImColor(kInk);
    c[ImGuiCol_ScrollbarGrabActive] = ImColor(kInk);
    c[ImGuiCol_TextSelectedBg] = ImVec4(0.91f, 0.76f, 0.48f, 0.35f);
}

void menu_upload(UploadFn upload) {
    int ok = 0;
    for (auto& [key, t] : g_tex) {
        t.id = upload(t.w, t.h, t.rgba.data());
        ok += t.id ? 1 : 0;
    }
    if (ok != int(g_tex.size())) {
        log_warn("uploaded " + std::to_string(ok) + " of " + std::to_string(g_tex.size())
                 + " UI textures");
    }
}

const std::uint8_t* menu_texture_pixels(const char* key, int* w, int* h) {
    const auto it = g_tex.find(key);
    if (it == g_tex.end() || it->second.rgba.empty()) return nullptr;
    *w = it->second.w;
    *h = it->second.h;
    return it->second.rgba.data();
}

void menu_forget_textures() {
    for (auto& [key, t] : g_tex) t.id = 0;
}

// The book's contents on two pages of `pw` x `ph`, the left one at `l0` and
// the right one `gap` to its right. Positions and sizes are fractions of a
// page (measured on the game's own Settings book and its page art), so the
// same code draws the flat book and the pages painted onto the game's book.
// Returns false when the menu asked to close.
// The book's page art: parchment, ornaments, and the title in the art's own
// cartouche. On the game's book this layer follows the curved page; the
// content (draw_book) follows the flat UI plane in front of it.
static void draw_book_art(ImDrawList* dl, ImVec2 l0, float pw, float ph, float gap) {
    const ImVec2 l1(l0.x + pw, l0.y + ph);
    const ImVec2 r0(l1.x + gap, l0.y), r1(r0.x + pw, l1.y);
    page(dl, "page_l", "ornament_l", l0, l1, false);
    page(dl, "page_r", "ornament_r", r0, r1, true);
    const ImVec2 c(l0.x + pw * 0.473f, l0.y + ph * 0.073f);
    const float ts = ph * 0.030f;
    const ImVec2 sz = measure(font_title(), ts, "MODS");
    text_at(dl, font_title(), ts, ImVec2(c.x - sz.x * 0.5f, c.y - sz.y * 0.5f), kInk, "MODS");
}

static bool draw_book(ImDrawList* dl, ImVec2 l0, float pw, float ph, float gap) {
    g_ph = ph;
    const ImVec2 l1(l0.x + pw, l0.y + ph);
    const ImVec2 r0(l1.x + gap, l0.y);
    auto L = [&](float fx, float fy) { return ImVec2(l0.x + pw * fx, l0.y + ph * fy); };
    auto R = [&](float fx, float fy) { return ImVec2(r0.x + pw * fx, r0.y + ph * fy); };

    // Measured on the game's own Settings page, mapped back through the book
    // warp into page fractions: category buttons u 0.093-0.86 from v 0.199,
    // 0.066 tall every 0.080; parameter rows from the knot at u 0.133 to
    // 0.903 from v 0.208, 0.060 tall every 0.069; "Reset to default" u
    // 0.629-0.908, v 0.913-0.956.

    // Left page: the mods.
    const ImVec2 list0 = L(0.093f, 0.199f), list1 = L(0.875f, 0.885f);
    ImGui::SetCursorScreenPos(list0);
    ImGui::BeginChild("list", ImVec2(list1.x - list0.x, list1.y - list0.y),
                      ImGuiChildFlags_None, ImGuiWindowFlags_NoBackground);
    mod_list(ph * 0.066f);
    ImGui::EndChild();

    bool keep_open = true;
    const ImVec2 bsz(pw * 0.279f, ph * 0.043f);
    ImGui::SetCursorScreenPos(L(0.093f, 0.913f));
    if (confirm_button("back", "Back", bsz)) keep_open = false;
    {
        const char* hint = "Esc closes this menu";
        const float hs = ph * 0.017f;
        const ImVec2 at = L(0.093f, 0.913f);
        text_at(dl, font_body(), hs, ImVec2(at.x + bsz.x + pw * 0.03f, at.y + (bsz.y - hs) * 0.5f),
                kInkSoft, hint);
    }

    // Right page: the selected mod's header (pinned), its settings below.
    static int s_last_sel = -1;
    const ImVec2 det0 = R(0.133f, 0.16f), det1 = R(0.93f, 0.885f);
    float header_h = 0;
    if (g_sel >= 0 && g_sel < int(g_mods.size())) {
        header_h = details_header(dl, g_mods[g_sel], det0, det1.x - det0.x, (det1.y - det0.y) * 0.4f);
    }
    ImGui::SetCursorScreenPos(ImVec2(det0.x, det0.y + header_h));
    if (s_last_sel != g_sel) {
        ImGui::SetNextWindowScroll(ImVec2(0, 0));
        s_last_sel = g_sel;
    }
    ImGui::BeginChild("details", ImVec2(det1.x - det0.x, det1.y - det0.y - header_h),
                      ImGuiChildFlags_None, ImGuiWindowFlags_NoBackground);
    details_rows(ph * 0.060f);
    ImGui::EndChild();

    if (g_sel >= 0 && g_sel < int(g_mods.size()) && !g_mods[g_sel].fields.empty()) {
        ImGui::SetCursorScreenPos(R(0.629f, 0.913f));
        if (confirm_button("reset", "Reset to default", bsz)) reset_defaults(g_mods[g_sel]);
    }
    return keep_open;
}

bool menu_draw() {
    bind_context();
    ImGuiIO& io = ImGui::GetIO();
    const ImVec2 disp = io.DisplaySize;
    ImGui::GetBackgroundDrawList()->AddRectFilled(ImVec2(0, 0), disp, IM_COL32(0, 0, 0, 140));

    // The game's Settings book: pages about 0.69 of the screen height and
    // 0.88 as wide as tall.
    const float s = g_scale;
    const float cover = 16 * s, spine = 8 * s;
    float ph = disp.y * 0.69f;
    float pw = ph * 0.88f;
    if (2 * pw + 2 * cover + 2 * spine > disp.x * 0.96f) {
        pw = (disp.x * 0.96f - 2 * cover - 2 * spine) * 0.5f;
        ph = pw / 0.88f;
    }
    const float W = 2 * pw + 2 * cover + 2 * spine, H = ph + 2 * cover;
    const ImVec2 pos((disp.x - W) * 0.5f, (disp.y - H) * 0.5f);
    ImGui::SetNextWindowPos(pos);
    ImGui::SetNextWindowSize(ImVec2(W, H));
    ImGui::Begin("##rsmm_menu", nullptr,
                 ImGuiWindowFlags_NoDecoration | ImGuiWindowFlags_NoBackground
                 | ImGuiWindowFlags_NoMove | ImGuiWindowFlags_NoSavedSettings);
    ImDrawList* dl = ImGui::GetWindowDrawList();
    dl->AddRectFilled(pos, ImVec2(pos.x + W, pos.y + H), kCover, 14 * s);
    draw_book_art(dl, ImVec2(pos.x + cover, pos.y + cover), pw, ph, 2 * spine);
    const bool keep_open = draw_book(dl, ImVec2(pos.x + cover, pos.y + cover), pw, ph, 2 * spine);
    ImGui::End();
    return keep_open;
}

bool menu_draw_pages(float page) {
    bind_context();
    // Square pages: the game's page art is square and the book stretches it,
    // so drawing in its space keeps every proportion the game's. Two windows,
    // so hook_overlay can route their draw lists apart: the art (no input)
    // into the page texture, the content onto the screen through the UI plane.
    constexpr ImGuiWindowFlags kFlags = ImGuiWindowFlags_NoDecoration | ImGuiWindowFlags_NoBackground
                                        | ImGuiWindowFlags_NoMove | ImGuiWindowFlags_NoSavedSettings;
    ImGui::SetNextWindowPos(ImVec2(0, 0));
    ImGui::SetNextWindowSize(ImVec2(2 * page, page));
    ImGui::Begin("##rsmm_art", nullptr, kFlags | ImGuiWindowFlags_NoInputs
                 | ImGuiWindowFlags_NoBringToFrontOnFocus | ImGuiWindowFlags_NoFocusOnAppearing);
    ImDrawList* art = ImGui::GetWindowDrawList();
    draw_book_art(art, ImVec2(0, 0), page, page, 0);
    // 20% darker: hook_overlay lights the art like the game's book with
    // vertex colours, which can only darken, and the game lights parts of
    // its page above the plain art (kPageHeadroom there).
    art->AddRectFilled(ImVec2(0, 0), ImVec2(2 * page, page), IM_COL32(0, 0, 0, 51));
    ImGui::End();

    ImGui::SetNextWindowPos(ImVec2(0, 0));
    ImGui::SetNextWindowSize(ImVec2(2 * page, page));
    ImGui::Begin("##rsmm_pages", nullptr, kFlags);
    const bool keep_open = draw_book(ImGui::GetWindowDrawList(), ImVec2(0, 0), page, page, 0);
    ImGui::End();
    return keep_open;
}

bool menu_escape_button(int vanilla_buttons) {
    bind_context();
    const ImVec2 disp = ImGui::GetIO().DisplaySize;
    const float H = disp.y;
    // The escape menu's column, measured on the game at 3440x1407 against
    // things the overlay drew at known positions: centred, top at 0.370 of
    // the screen height, buttons 0.294 x 0.0524 H every 0.0624 H, the same in
    // the lobby (2 buttons) and in a run (3). Mods is the next entry.
    const ImVec2 size(H * 0.294f, H * 0.0524f);
    const ImVec2 at((disp.x - size.x) * 0.5f, H * 0.370f + vanilla_buttons * H * 0.0624f);
    ImGui::SetNextWindowPos(at);
    ImGui::SetNextWindowSize(size);
    ImGui::Begin("##rsmm_escape", nullptr,
                 ImGuiWindowFlags_NoDecoration | ImGuiWindowFlags_NoBackground
                 | ImGuiWindowFlags_NoMove | ImGuiWindowFlags_NoSavedSettings
                 | ImGuiWindowFlags_NoFocusOnAppearing);
    ImGui::SetCursorScreenPos(at);
    const bool clicked = ImGui::InvisibleButton("mods", size);
    const bool hovered = ImGui::IsItemHovered();
    const ImVec2 b(at.x + size.x, at.y + size.y);
    ImDrawList* dl = ImGui::GetWindowDrawList();
    // Normal / Selected art of the vanilla buttons (the game shows the
    // hovered one as Selected).
    image3(dl, hovered ? "menu_button_hover" : "menu_button", at, b, 22, 22, IM_COL32_WHITE,
           IM_COL32(28, 26, 20, 240));
    // Labels are gold on the normal art and cream on the selected one.
    text_centered(dl, font_body(), size.y * 0.44f, at, b,
                  hovered ? IM_COL32(246, 236, 212, 255) : IM_COL32(222, 186, 122, 255), "Mods");
    ImGui::End();
    return clicked;
}

} // namespace rsmm::overlay
