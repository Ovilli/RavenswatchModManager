// In-game overlay: Dear ImGui on the game's DX12 swapchain.
//
// Why DXGI and not the engine: Ravenswatch imports only dxgi/d3d12 (the old
// overlay hooked vulkan-1.dll, which the game never loads, and so never drew),
// and every piece needed here is a COM or Win32 interface. No engine symbol is
// touched, so a game patch cannot move anything this file depends on.
//
// Threads: Present runs on the game's render thread; the window procedure on
// its window thread. ImGui is only ever touched from Present (under g_mu). The
// window procedure only queues messages (under g_in_mu) and flips g_visible.
// Lua is never called from here (docs: loader-thread-model).
//
// Recon behind every choice: docs/_re/IN_GAME_UI.md.

// imgui_impl_dx12 calls CreateDXGIFactory1 and D3DCompile directly. Rename
// them (here and, via CMake, in the backend) to shims that look the real ones
// up at runtime, so winhttp.dll gains no import on dxgi/d3dcompiler: it is
// also loaded by crashpad_handler.exe, and a missing d3dcompiler_47 would
// otherwise stop the game from starting at all.
#define CreateDXGIFactory1 rsmm_CreateDXGIFactory1
#define D3DCompile rsmm_D3DCompile

#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <d3d12.h>
#include <dxgi1_4.h>
#include <d3dcompiler.h>

#include <algorithm>
#include <cfloat>
#include <cmath>
#include <atomic>
#include <cstdio>
#include <cstring>
#include <mutex>
#include <string>
#include <thread>
#include <vector>

#include "imgui.h"
#include "imgui_impl_dx12.h"
#include "imgui_impl_win32.h"

#include "hook_overlay.h"
#include "hook_util.h"
#include "loader.h"
#include "book_calib.h"
#include "book_warp.h"
#include "overlay_menu.h"
#include "symbols.gen.h"

extern IMGUI_IMPL_API LRESULT ImGui_ImplWin32_WndProcHandler(HWND, UINT, WPARAM, LPARAM);

namespace {

FARPROC proc_of(const char* const* dlls, const char* fn) {
    for (; *dlls; ++dlls) {
        HMODULE h = GetModuleHandleA(*dlls);
        if (!h) h = LoadLibraryA(*dlls);
        if (!h) continue;
        if (FARPROC p = GetProcAddress(h, fn)) return p;
    }
    return nullptr;
}

} // namespace

extern "C" HRESULT WINAPI rsmm_CreateDXGIFactory1(REFIID riid, void** factory) {
    using Fn = HRESULT(WINAPI*)(REFIID, void**);
    static const char* const dlls[] = {"dxgi.dll", nullptr};
    static auto fn = reinterpret_cast<Fn>(proc_of(dlls, "CreateDXGIFactory1"));
    return fn ? fn(riid, factory) : E_NOINTERFACE;
}

extern "C" HRESULT WINAPI rsmm_D3DCompile(const void* data, SIZE_T data_size,
        const char* filename, const D3D_SHADER_MACRO* defines, ID3DInclude* include,
        const char* entrypoint, const char* target, UINT sflags, UINT eflags,
        ID3DBlob** shader, ID3DBlob** error_messages) {
    static const char* const dlls[] = {"d3dcompiler_47.dll", "d3dcompiler_46.dll",
                                       "d3dcompiler_43.dll", nullptr};
    static auto fn = reinterpret_cast<pD3DCompile>(proc_of(dlls, "D3DCompile"));
    if (!fn) return E_NOINTERFACE;
    return fn(data, data_size, filename, defines, include, entrypoint, target,
              sflags, eflags, shader, error_messages);
}

namespace rsmm {
namespace {

namespace warp = overlay::warp;
namespace calib = overlay::calib;

constexpr const char* kTag = "[ingame-ui] ";
// Either key toggles: many laptop keyboards have no Insert.
constexpr int kToggleKeys[] = {VK_INSERT, VK_F8};
constexpr UINT kSrvHeapSize = 64;

// COM vtable slots. ABI-fixed by the interface definitions in dxgi*.h/d3d12.h:
// IUnknown(3) + IDXGIObject(4) + IDXGIDeviceSubObject(1) puts Present at 8;
// IDXGISwapChain1 starts at 18, IDXGISwapChain3 at 36.
constexpr int kSlotPresent = 8;
constexpr int kSlotResizeBuffers = 13;
constexpr int kSlotPresent1 = 22;
constexpr int kSlotResizeBuffers1 = 39;
constexpr int kSlotExecuteCommandLists = 10;

using PresentFn = HRESULT(STDMETHODCALLTYPE*)(IDXGISwapChain*, UINT, UINT);
using Present1Fn = HRESULT(STDMETHODCALLTYPE*)(IDXGISwapChain1*, UINT, UINT,
                                               const DXGI_PRESENT_PARAMETERS*);
using ResizeBuffersFn = HRESULT(STDMETHODCALLTYPE*)(IDXGISwapChain*, UINT, UINT,
                                                    UINT, DXGI_FORMAT, UINT);
using ResizeBuffers1Fn = HRESULT(STDMETHODCALLTYPE*)(IDXGISwapChain3*, UINT, UINT,
        UINT, DXGI_FORMAT, UINT, const UINT*, IUnknown* const*);
using ExecuteFn = void(STDMETHODCALLTYPE*)(ID3D12CommandQueue*, UINT,
                                           ID3D12CommandList* const*);
using GetAsyncKeyStateFn = SHORT(WINAPI*)(int);

PresentFn o_present = nullptr;
Present1Fn o_present1 = nullptr;
ResizeBuffersFn o_resize = nullptr;
ResizeBuffers1Fn o_resize1 = nullptr;
ExecuteFn o_execute = nullptr;
GetAsyncKeyStateFn o_get_async_key_state = nullptr;

std::uintptr_t g_hooked[5] = {};

// The escape menu's UI controller show/hide (oCDtEntityCpntEscapeGameMenuUiController
// vtable slots 28/29, data/symbols.json UiController_OnShow/OnHide). They set
// and clear the game's own "Is game menu open" flag, and fire wherever the
// menu opens. InGameMenuGs alone did not fire for the lobby's Esc menu.
// While the menu is open the overlay offers a Mods button.
using UiControllerFn = void (*)(void* controller);
UiControllerFn o_menu_enter = nullptr;
UiControllerFn o_menu_leave = nullptr;
std::uintptr_t g_menu_enter_va = 0;
std::uintptr_t g_menu_leave_va = 0;
std::atomic<bool> g_escape_menu{false};

// The run's menu state (oe::dt::InGameMenuGs). It did not enter for the
// lobby's Esc menu, so while it is active the escape menu is the run's
// (Resume / Settings / Abandon) rather than the lobby's (Resume / Quit to
// desktop), which decides where the Mods button goes.
using GameStateFn = void (*)(void* self, void* ctx);
GameStateFn o_run_menu_enter = nullptr;
GameStateFn o_run_menu_leave = nullptr;
std::uintptr_t g_run_menu_enter_va = 0;
std::uintptr_t g_run_menu_leave_va = 0;
std::atomic<bool> g_run_menu{false};

// UIs that open ON TOP of the escape menu (its Settings book, the Abandon
// confirmation, a loading screen). The escape menu stays "shown" under them,
// so its Mods button must hide while one of them is up. Only a show that
// happens while the escape menu is open counts: in the lobby the book is up
// before Esc is pressed and must not hide the button.
struct Cover {
    const char* what;
    const char* show_pattern;
    const char* hide_pattern;
    UiControllerFn o_show = nullptr;
    UiControllerFn o_hide = nullptr;
    std::uintptr_t show_va = 0;
    std::uintptr_t hide_va = 0;
    std::atomic<bool> up{false};
};
Cover g_covers[] = {
    {"book menu", Sym::BookMenuUiController_OnShow_Pattern, Sym::BookMenuUiController_OnHide_Pattern},
    {"modal popup", Sym::ModalUiController_OnShow_Pattern, Sym::ModalUiController_OnHide_Pattern},
    {"loading screen", Sym::LoadingScreenUiController_OnShow_Pattern,
     Sym::LoadingScreenUiController_OnHide_Pattern},
};

bool escape_menu_covered() {
    for (const Cover& c : g_covers) {
        if (c.up.load()) return true;
    }
    return false;
}

std::atomic<bool> g_visible{false};
// Set when the menu closes and cleared once every key that could have closed
// it is up again: the key or click that closed the menu is still held on that
// frame, and the game must not read it as its own (Esc would open its pause
// menu, a click on Back would land in the world).
std::atomic<bool> g_mask_until_release{false};
std::atomic<ID3D12CommandQueue*> g_queue{nullptr};

// --- input: window thread -> render thread --------------------------------
struct Msg {
    UINT msg;
    WPARAM wp;
    LPARAM lp;
};
std::mutex g_in_mu;
std::vector<Msg> g_in;
HWND g_hwnd = nullptr;
WNDPROC g_prev_wndproc = nullptr;
std::uintptr_t* g_iat_slot = nullptr;

// --- renderer: render thread only, under g_mu -------------------------------
struct Frame {
    ID3D12CommandAllocator* alloc = nullptr;
    ID3D12Resource* target = nullptr;
    D3D12_CPU_DESCRIPTOR_HANDLE rtv{};
    UINT64 fence_value = 0;
};

std::mutex g_mu;
bool g_imgui_ready = false;      // ImGui context + win32 backend
bool g_renderer_ready = false;   // dx12 backend + per-frame resources
IDXGISwapChain3* g_sc = nullptr; // not owned; identity only
ID3D12Device* g_device = nullptr;
ID3D12DescriptorHeap* g_rtv_heap = nullptr;
ID3D12DescriptorHeap* g_srv_heap = nullptr;
ID3D12GraphicsCommandList* g_list = nullptr;
ID3D12Fence* g_fence = nullptr;
HANDLE g_fence_event = nullptr;
UINT64 g_fence_last = 0;
std::vector<Frame> g_frames;
std::vector<UINT> g_srv_free;
UINT g_srv_step = 0;

// Textures the menu uploaded; they live in g_srv_heap, so they go with it.
struct OwnedTexture {
    ID3D12Resource* res = nullptr;
};
std::vector<OwnedTexture> g_textures;

// The menu painted onto the game's own book. Both pages are drawn by the one
// ImGui context as a window at (0, 0); its draw lists are split off after
// Render() and rendered into an offscreen texture, which the rest of the
// frame draws through book_warp onto the book. (A second ImGui context with
// its own atlas was tried first: its text came out as fragments.)
constexpr int kBookPageMax = 1536;   // pixels per page side; the book shows ~1300
int g_book_page = 0;                 // this renderer's page size, 0 = no page texture
ID3D12Resource* g_book_rt = nullptr;
ID3D12DescriptorHeap* g_book_rtv_heap = nullptr;
ImTextureID g_book_tex = 0;
constexpr const char* kPagesWindow = "##rsmm_pages";   // overlay_menu's content window
constexpr const char* kArtWindow = "##rsmm_art";       // overlay_menu's page-art window

// Opening: get the game's own Settings page on screen. Calibrating: match its
// ornaments on one captured frame (book_calib). Shown: paint over it.
// Closing: the game is animating its book away (or turning its page); the
// pages are painted, and tracked, until the book is no longer recognised.
enum class BookMode { Off, Opening, Calibrating, Shown, Closing };
BookMode g_book_mode = BookMode::Off;
unsigned long long g_book_since = 0;       // ms, when the mode last changed
bool g_book_from_run = false;               // opened from a run's escape menu
unsigned g_book_escape_epoch = 0;           // escape-menu opens seen when Shown began
// Opening runs in steps: the lobby's escape menu has no Settings button, so
// it is closed first and the book's own Settings (gear) tab clicked instead.
enum class OpenStep { CloseEscape, WaitForPage };
OpenStep g_open_step = OpenStep::WaitForPage;
unsigned long long g_clicked_at = 0;
POINT g_cursor_restore{};
unsigned long long g_cursor_restore_at = 0;
// A fake click shows the game a cursor at the clicked point (its
// GetCursorPos, plus a WM_MOUSEMOVE for its hover) without moving the real
// one. Only when that import can't be patched does the real cursor jump.
std::uintptr_t* g_cursor_iat_slot = nullptr;
using GetCursorPosFn = BOOL(WINAPI*)(LPPOINT);
GetCursorPosFn o_get_cursor_pos = nullptr;
std::atomic<LONG> g_fake_cursor_x{0}, g_fake_cursor_y{0};
std::atomic<unsigned long long> g_fake_cursor_until{0};
std::atomic<LPARAM> g_fake_cursor_lp{0};   // the WM_MOUSEMOVE we posted
warp::Calib g_calib;                        // where the book is on this screen
calib::Lighting g_light;                    // how the game lights it (measured with g_calib)
// The pages are drawn this much darker into their texture, so the measured
// lighting, applied as vertex colours (which can only darken), can also
// brighten where the game lights the page above its plain art (the warm glow
// on the left page measured up to 1.25x).
constexpr float kPageHeadroom = 0.8f;
// Calibration runs on a worker thread; the render thread polls the state. It
// is retried on fresh frames until the page matches: the game's book opens
// with a camera move, and a frame from mid-move does not match yet.
std::atomic<int> g_calib_state{0};          // 0 idle, 1 running, 2 done
calib::Result g_calib_result;               // written before state becomes 2
calib::Lighting g_calib_light;              // with it, when the result is ok
unsigned long long g_next_capture = 0;      // ms, earliest next calibration frame
int g_calib_tries = 0;
// Frames are searched from right after the click: a lock happens as soon as
// the page is recognisable, and tracking follows the rest of its motion.
constexpr unsigned long long kCalibrateAfterClickMs = 150;
constexpr unsigned long long kCalibrateGiveUpMs = 6000;

// The game's book (BookMenuUiController shown/hidden) and how often the
// escape menu has opened, both updated from game-thread hooks. The book's
// show does NOT fire again each time Settings opens (the controller stays
// shown), so opening never waits on it: the screen itself (calibration)
// says when the Settings page is there. Its hide still marks the book gone.
std::atomic<bool> g_book_ui{false};
std::atomic<unsigned> g_book_hides{0};
std::atomic<unsigned> g_escape_epoch{0};
unsigned g_book_hides_seen = 0;             // hides seen when Shown began

// Input the overlay sends to the game itself: a click (on the escape menu's
// Settings button or the book's gear tab), or Esc to close a menu. Windows of
// GetTickCount64 ms during which the game's GetAsyncKeyState reads the key as
// held.
std::atomic<unsigned long long> g_fake_click_from{0}, g_fake_click_to{0};
std::atomic<unsigned long long> g_fake_escape_from{0}, g_fake_escape_to{0};
// While the pages are painted the game gets no input, except Esc, which
// closes its book the game's own way.
std::atomic<bool> g_book_masking{false};

// Tracking: while the pages are painted the book is re-found every frame (or
// every kTrackIdleEvery frames once it is still), from a readback buffer that
// stays mapped, so the pages ride along with the game's open/close animations.
// Two readback slots: a frame's copy is read on a later frame, once the GPU
// has finished it, so tracking never stalls the game (a wait every frame
// made the pages stutter, 2026-10-24).
struct Readback {
    ID3D12Resource* buf = nullptr;
    ID3D12CommandAllocator* alloc = nullptr;
    ID3D12GraphicsCommandList* list = nullptr;
    void* mapped = nullptr;
    UINT64 fence = 0;      // signalled when its copy is done; 0 = empty
    bool bgra = false;
};
Readback g_rbs[2];
int g_rb_next = 0;
UINT64 g_rb_valid_after = 0;   // copies queued up to here show an older scene
D3D12_PLACED_SUBRESOURCE_FOOTPRINT g_rb_fp{};
UINT64 g_rb_w = 0;
UINT g_rb_h = 0;
unsigned long long g_track_hot_until = 0;   // ms; track every frame until then
unsigned g_frame_no = 0;
int g_track_lost = 0;
bool g_have_lock = false;                   // g_calib came from a real lock
constexpr int kTrackIdleEvery = 10;
constexpr unsigned long long kTrackHotMs = 800;
constexpr unsigned long long kClosingMaxMs = 1500;
// The game's own Settings book over the escape menu: its book-shown event
// fires only on the first open of a session, so the Mods button watches the
// screen instead. A click in the escape menu's column hides the button and
// starts looking for the Settings page; the button comes back when the page
// is not (or no longer) there.
unsigned long long g_vanilla_watch_until = 0;
bool g_vanilla_book = false;
int g_vanilla_lost = 0;
constexpr unsigned long long kVanillaWatchMs = 1500;

unsigned long long now_ms() { return GetTickCount64(); }

bool g_logged_no_queue = false;
bool g_logged_first_frame = false;

template <class T>
void release(T*& p) {
    if (p) {
        p->Release();
        p = nullptr;
    }
}

void log(const std::string& s) { Loader::get().log(kTag + s); }
void log_err(const std::string& s) { Loader::get().log_err(kTag + s); }

void srv_alloc(ImGui_ImplDX12_InitInfo*, D3D12_CPU_DESCRIPTOR_HANDLE* cpu,
               D3D12_GPU_DESCRIPTOR_HANDLE* gpu) {
    if (g_srv_free.empty()) {   // IM_ASSERT is compiled out in Release
        cpu->ptr = 0;
        gpu->ptr = 0;
        log_err("SRV heap exhausted");
        return;
    }
    const UINT i = g_srv_free.back();
    g_srv_free.pop_back();
    cpu->ptr = g_srv_heap->GetCPUDescriptorHandleForHeapStart().ptr + i * g_srv_step;
    gpu->ptr = g_srv_heap->GetGPUDescriptorHandleForHeapStart().ptr + UINT64(i) * g_srv_step;
}

void srv_free(ImGui_ImplDX12_InitInfo*, D3D12_CPU_DESCRIPTOR_HANDLE cpu,
              D3D12_GPU_DESCRIPTOR_HANDLE) {
    const auto start = g_srv_heap->GetCPUDescriptorHandleForHeapStart().ptr;
    g_srv_free.push_back(static_cast<UINT>((cpu.ptr - start) / g_srv_step));
}

void gpu_wait_idle();
void release_readbacks();

// The full mip chain of straight-alpha RGBA8, each level a 2x2 box filter of
// the one above. The game's art is drawn far smaller than it is stored (a
// 1300x128 button at ~80 px tall), and minified without mips it aliases into
// jagged, shimmering edges. Averaged on premultiplied colour: a straight
// average pulls the colour of transparent pixels into the edges and fringes
// them dark.
std::vector<std::vector<std::uint8_t>> mip_chain(int w, int h, const std::uint8_t* rgba) {
    std::vector<std::vector<std::uint8_t>> levels;
    levels.emplace_back(rgba, rgba + std::size_t(w) * h * 4);
    while (w > 1 || h > 1) {
        const int nw = std::max(1, w / 2), nh = std::max(1, h / 2);
        const std::vector<std::uint8_t>& src = levels.back();
        std::vector<std::uint8_t> dst(std::size_t(nw) * nh * 4);
        for (int y = 0; y < nh; ++y) {
            for (int x = 0; x < nw; ++x) {
                float r = 0, g = 0, b = 0, a = 0;
                for (int dy = 0; dy < 2; ++dy) {
                    for (int dx = 0; dx < 2; ++dx) {
                        const int sx = std::min(w - 1, x * 2 + dx), sy = std::min(h - 1, y * 2 + dy);
                        const std::uint8_t* p = &src[(std::size_t(sy) * w + sx) * 4];
                        const float pa = p[3] / 255.0f;
                        r += p[0] * pa;
                        g += p[1] * pa;
                        b += p[2] * pa;
                        a += pa;
                    }
                }
                std::uint8_t* q = &dst[(std::size_t(y) * nw + x) * 4];
                q[0] = a > 0 ? std::uint8_t(std::min(255.0f, r / a + 0.5f)) : 0;
                q[1] = a > 0 ? std::uint8_t(std::min(255.0f, g / a + 0.5f)) : 0;
                q[2] = a > 0 ? std::uint8_t(std::min(255.0f, b / a + 0.5f)) : 0;
                q[3] = std::uint8_t(std::min(255.0f, a / 4 * 255.0f + 0.5f));
            }
        }
        levels.push_back(std::move(dst));
        w = nw;
        h = nh;
    }
    return levels;
}

// Straight RGBA8 rows -> a mipmapped, shader-visible texture in our SRV heap,
// uploaded on the game's queue and waited for. Only called from renderer_init
// (render thread, under g_mu), a few dozen times per renderer, so the
// blocking wait is cheaper than a staging scheme.
ImTextureID upload_texture(int w, int h, const std::uint8_t* rgba) {
    ID3D12CommandQueue* queue = g_queue.load();
    if (!g_device || !queue || w <= 0 || h <= 0) return 0;
    D3D12_HEAP_PROPERTIES heap{};
    heap.Type = D3D12_HEAP_TYPE_DEFAULT;
    D3D12_RESOURCE_DESC desc{};
    desc.Dimension = D3D12_RESOURCE_DIMENSION_TEXTURE2D;
    desc.Width = UINT64(w);
    desc.Height = UINT(h);
    desc.DepthOrArraySize = 1;
    const auto levels = mip_chain(w, h, rgba);
    const UINT n_mips = UINT(levels.size());
    desc.MipLevels = UINT16(n_mips);
    desc.Format = DXGI_FORMAT_R8G8B8A8_UNORM;
    desc.SampleDesc.Count = 1;
    ID3D12Resource* tex = nullptr;
    if (FAILED(g_device->CreateCommittedResource(&heap, D3D12_HEAP_FLAG_NONE, &desc,
            D3D12_RESOURCE_STATE_COPY_DEST, nullptr, __uuidof(ID3D12Resource),
            reinterpret_cast<void**>(&tex)))) {
        return 0;
    }
    std::vector<D3D12_PLACED_SUBRESOURCE_FOOTPRINT> fps(n_mips);
    std::vector<UINT> rows(n_mips);
    std::vector<UINT64> row_bytes(n_mips);
    UINT64 total = 0;
    g_device->GetCopyableFootprints(&desc, 0, n_mips, 0, fps.data(), rows.data(),
                                    row_bytes.data(), &total);

    D3D12_HEAP_PROPERTIES up_heap{};
    up_heap.Type = D3D12_HEAP_TYPE_UPLOAD;
    D3D12_RESOURCE_DESC up_desc{};
    up_desc.Dimension = D3D12_RESOURCE_DIMENSION_BUFFER;
    up_desc.Width = total;
    up_desc.Height = 1;
    up_desc.DepthOrArraySize = 1;
    up_desc.MipLevels = 1;
    up_desc.SampleDesc.Count = 1;
    up_desc.Layout = D3D12_TEXTURE_LAYOUT_ROW_MAJOR;
    ID3D12Resource* upload = nullptr;
    ID3D12CommandAllocator* alloc = nullptr;
    ID3D12GraphicsCommandList* list = nullptr;
    void* mapped = nullptr;
    bool ok = SUCCEEDED(g_device->CreateCommittedResource(&up_heap, D3D12_HEAP_FLAG_NONE,
                  &up_desc, D3D12_RESOURCE_STATE_GENERIC_READ, nullptr,
                  __uuidof(ID3D12Resource), reinterpret_cast<void**>(&upload)))
        && SUCCEEDED(upload->Map(0, nullptr, &mapped))
        && SUCCEEDED(g_device->CreateCommandAllocator(D3D12_COMMAND_LIST_TYPE_DIRECT,
                  __uuidof(ID3D12CommandAllocator), reinterpret_cast<void**>(&alloc)))
        && SUCCEEDED(g_device->CreateCommandList(0, D3D12_COMMAND_LIST_TYPE_DIRECT, alloc,
                  nullptr, __uuidof(ID3D12GraphicsCommandList), reinterpret_cast<void**>(&list)));
    if (ok) {
        for (UINT m = 0; m < n_mips; ++m) {
            auto* dst = static_cast<std::uint8_t*>(mapped) + fps[m].Offset;
            const std::size_t row = std::size_t(fps[m].Footprint.Width) * 4;
            for (UINT y = 0; y < rows[m]; ++y) {
                std::memcpy(dst + std::size_t(y) * fps[m].Footprint.RowPitch,
                            levels[m].data() + y * row, row);
            }
        }
        upload->Unmap(0, nullptr);
        for (UINT m = 0; m < n_mips; ++m) {
            D3D12_TEXTURE_COPY_LOCATION to{};
            to.pResource = tex;
            to.Type = D3D12_TEXTURE_COPY_TYPE_SUBRESOURCE_INDEX;
            to.SubresourceIndex = m;
            D3D12_TEXTURE_COPY_LOCATION from{};
            from.pResource = upload;
            from.Type = D3D12_TEXTURE_COPY_TYPE_PLACED_FOOTPRINT;
            from.PlacedFootprint = fps[m];
            list->CopyTextureRegion(&to, 0, 0, 0, &from, nullptr);
        }
        D3D12_RESOURCE_BARRIER barrier{};
        barrier.Type = D3D12_RESOURCE_BARRIER_TYPE_TRANSITION;
        barrier.Transition.pResource = tex;
        barrier.Transition.Subresource = D3D12_RESOURCE_BARRIER_ALL_SUBRESOURCES;
        barrier.Transition.StateBefore = D3D12_RESOURCE_STATE_COPY_DEST;
        barrier.Transition.StateAfter = D3D12_RESOURCE_STATE_PIXEL_SHADER_RESOURCE;
        list->ResourceBarrier(1, &barrier);
        list->Close();
        ID3D12CommandList* lists[] = {list};
        o_execute(queue, 1, lists);
        queue->Signal(g_fence, ++g_fence_last);
        gpu_wait_idle();
    }
    release(list);
    release(alloc);
    release(upload);
    D3D12_CPU_DESCRIPTOR_HANDLE cpu{};
    D3D12_GPU_DESCRIPTOR_HANDLE gpu{};
    if (ok) srv_alloc(nullptr, &cpu, &gpu);
    if (!ok || !cpu.ptr) {
        release(tex);
        return 0;
    }
    D3D12_SHADER_RESOURCE_VIEW_DESC srv{};
    srv.Format = desc.Format;
    srv.ViewDimension = D3D12_SRV_DIMENSION_TEXTURE2D;
    srv.Shader4ComponentMapping = D3D12_DEFAULT_SHADER_4_COMPONENT_MAPPING;
    srv.Texture2D.MipLevels = n_mips;
    g_device->CreateShaderResourceView(tex, &srv, cpu);
    g_textures.push_back({tex});
    return static_cast<ImTextureID>(gpu.ptr);
}

void gpu_wait_idle() {
    if (!g_fence || !g_fence_last) return;
    if (g_fence->GetCompletedValue() < g_fence_last) {
        g_fence->SetEventOnCompletion(g_fence_last, g_fence_event);
        WaitForSingleObject(g_fence_event, 2000);
    }
}

// Drop everything tied to the swapchain's buffers or the device. The ImGui
// context survives so window positions and state outlive a resize.
void renderer_teardown() {
    gpu_wait_idle();
    overlay::menu_forget_textures();
    for (auto& t : g_textures) release(t.res);
    g_textures.clear();
    release(g_book_rt);
    release(g_book_rtv_heap);
    release_readbacks();
    g_book_tex = 0;
    g_book_page = 0;
    if (g_renderer_ready) ImGui_ImplDX12_Shutdown();
    for (auto& f : g_frames) {
        release(f.alloc);
        release(f.target);
    }
    g_frames.clear();
    release(g_list);
    release(g_rtv_heap);
    release(g_srv_heap);
    release(g_fence);
    if (g_fence_event) {
        CloseHandle(g_fence_event);
        g_fence_event = nullptr;
    }
    g_fence_last = 0;
    release(g_device);
    g_sc = nullptr;
    g_renderer_ready = false;
}

LRESULT CALLBACK wndproc(HWND hwnd, UINT msg, WPARAM wp, LPARAM lp);

void imgui_init(HWND hwnd, UINT height) {
    IMGUI_CHECKVERSION();
    ImGui::CreateContext();
    ImGuiIO& io = ImGui::GetIO();
    io.IniFilename = nullptr;   // never write imgui.ini into the game folder
    io.LogFilename = nullptr;
    // The game owns the system cursor (it hides or swaps it during play), so
    // ImGui draws its own while the panel is open instead of fighting it.
    io.ConfigFlags |= ImGuiConfigFlags_NoMouseCursorChange;
    ImGui::StyleColorsDark();
    // The menu sizes its own art and text by this; ImGui's widgets (text
    // fields, scrollbars) get the same factor through their paddings.
    const float scale = std::max(0.6f, float(height) / 1080.0f);
    ImGui::GetStyle().ScaleAllSizes(scale);
    overlay::menu_setup_imgui(scale);
    ImGui_ImplWin32_Init(hwnd);

    g_hwnd = hwnd;
    g_prev_wndproc = reinterpret_cast<WNDPROC>(SetWindowLongPtrA(
        hwnd, GWLP_WNDPROC, reinterpret_cast<LONG_PTR>(&wndproc)));
    log(g_prev_wndproc ? "subclassed game window" : "SetWindowLongPtrA failed; no input");
    g_imgui_ready = true;
}

bool renderer_init(IDXGISwapChain3* sc) {
    DXGI_SWAP_CHAIN_DESC desc{};
    if (FAILED(sc->GetDesc(&desc))) return false;
    if (FAILED(sc->GetDevice(__uuidof(ID3D12Device),
                             reinterpret_cast<void**>(&g_device)))) {
        log_err("swapchain has no D3D12 device");
        return false;
    }
    const UINT n = desc.BufferCount;

    D3D12_DESCRIPTOR_HEAP_DESC rtv_desc{};
    rtv_desc.Type = D3D12_DESCRIPTOR_HEAP_TYPE_RTV;
    rtv_desc.NumDescriptors = n;
    D3D12_DESCRIPTOR_HEAP_DESC srv_desc{};
    srv_desc.Type = D3D12_DESCRIPTOR_HEAP_TYPE_CBV_SRV_UAV;
    srv_desc.NumDescriptors = kSrvHeapSize;
    srv_desc.Flags = D3D12_DESCRIPTOR_HEAP_FLAG_SHADER_VISIBLE;
    if (FAILED(g_device->CreateDescriptorHeap(&rtv_desc, __uuidof(ID3D12DescriptorHeap),
                                              reinterpret_cast<void**>(&g_rtv_heap)))
        || FAILED(g_device->CreateDescriptorHeap(&srv_desc, __uuidof(ID3D12DescriptorHeap),
                                                 reinterpret_cast<void**>(&g_srv_heap)))
        || FAILED(g_device->CreateFence(0, D3D12_FENCE_FLAG_NONE, __uuidof(ID3D12Fence),
                                        reinterpret_cast<void**>(&g_fence)))) {
        log_err("descriptor heap / fence creation failed");
        return false;
    }
    g_fence_event = CreateEventW(nullptr, FALSE, FALSE, nullptr);
    g_srv_step = g_device->GetDescriptorHandleIncrementSize(
        D3D12_DESCRIPTOR_HEAP_TYPE_CBV_SRV_UAV);
    g_srv_free.clear();
    for (UINT i = kSrvHeapSize; i-- > 0;) g_srv_free.push_back(i);

    const UINT rtv_step = g_device->GetDescriptorHandleIncrementSize(
        D3D12_DESCRIPTOR_HEAP_TYPE_RTV);
    D3D12_CPU_DESCRIPTOR_HANDLE rtv = g_rtv_heap->GetCPUDescriptorHandleForHeapStart();
    g_frames.resize(n);
    for (UINT i = 0; i < n; ++i) {
        Frame& f = g_frames[i];
        if (FAILED(sc->GetBuffer(i, __uuidof(ID3D12Resource),
                                 reinterpret_cast<void**>(&f.target)))
            || FAILED(g_device->CreateCommandAllocator(
                   D3D12_COMMAND_LIST_TYPE_DIRECT, __uuidof(ID3D12CommandAllocator),
                   reinterpret_cast<void**>(&f.alloc)))) {
            log_err("back buffer / allocator " + std::to_string(i) + " failed");
            return false;
        }
        f.rtv = rtv;
        g_device->CreateRenderTargetView(f.target, nullptr, rtv);
        rtv.ptr += rtv_step;
    }
    if (FAILED(g_device->CreateCommandList(0, D3D12_COMMAND_LIST_TYPE_DIRECT,
                                           g_frames[0].alloc, nullptr,
                                           __uuidof(ID3D12GraphicsCommandList),
                                           reinterpret_cast<void**>(&g_list)))) {
        log_err("command list creation failed");
        return false;
    }
    g_list->Close();

    if (!g_imgui_ready) imgui_init(desc.OutputWindow, desc.BufferDesc.Height);

    ImGui_ImplDX12_InitInfo info;
    info.Device = g_device;
    info.CommandQueue = g_queue.load();
    // Two renders per frame when the pages are painted (the page texture, then
    // the screen), and the backend cycles its vertex buffers per render.
    info.NumFramesInFlight = static_cast<int>(2 * n);
    info.RTVFormat = desc.BufferDesc.Format;
    info.DSVFormat = DXGI_FORMAT_UNKNOWN;
    info.SrvDescriptorHeap = g_srv_heap;
    info.SrvDescriptorAllocFn = &srv_alloc;
    info.SrvDescriptorFreeFn = &srv_free;
    if (!ImGui_ImplDX12_Init(&info)) {
        log_err("ImGui_ImplDX12_Init failed");
        return false;
    }
    g_sc = sc;
    g_renderer_ready = true;
    overlay::menu_upload(&upload_texture);

    // The pages' render target. Optional: without it the menu opens flat.
    // The pages window must fit the screen (ImGui clips top-level windows to
    // it), so a page is at most the screen's height and half its width.
    {
        const int page = std::min<int>({kBookPageMax, int(desc.BufferDesc.Height),
                                        int(desc.BufferDesc.Width / 2)});
        D3D12_HEAP_PROPERTIES heap{};
        heap.Type = D3D12_HEAP_TYPE_DEFAULT;
        D3D12_RESOURCE_DESC rd{};
        rd.Dimension = D3D12_RESOURCE_DIMENSION_TEXTURE2D;
        rd.Width = UINT64(page) * 2;
        rd.Height = UINT(page);
        rd.DepthOrArraySize = 1;
        rd.MipLevels = 1;
        rd.Format = DXGI_FORMAT_R8G8B8A8_UNORM;
        rd.SampleDesc.Count = 1;
        rd.Flags = D3D12_RESOURCE_FLAG_ALLOW_RENDER_TARGET;
        D3D12_CLEAR_VALUE clear{};
        clear.Format = rd.Format;
        D3D12_DESCRIPTOR_HEAP_DESC hd{};
        hd.Type = D3D12_DESCRIPTOR_HEAP_TYPE_RTV;
        hd.NumDescriptors = 1;
        D3D12_CPU_DESCRIPTOR_HANDLE cpu{};
        D3D12_GPU_DESCRIPTOR_HANDLE gpu{};
        if (page > 0
            && SUCCEEDED(g_device->CreateCommittedResource(&heap, D3D12_HEAP_FLAG_NONE, &rd,
                D3D12_RESOURCE_STATE_PIXEL_SHADER_RESOURCE, &clear, __uuidof(ID3D12Resource),
                reinterpret_cast<void**>(&g_book_rt)))
            && SUCCEEDED(g_device->CreateDescriptorHeap(&hd, __uuidof(ID3D12DescriptorHeap),
                reinterpret_cast<void**>(&g_book_rtv_heap)))) {
            g_device->CreateRenderTargetView(g_book_rt, nullptr,
                                             g_book_rtv_heap->GetCPUDescriptorHandleForHeapStart());
            srv_alloc(nullptr, &cpu, &gpu);
        }
        if (cpu.ptr) {
            D3D12_SHADER_RESOURCE_VIEW_DESC sd{};
            sd.Format = rd.Format;
            sd.ViewDimension = D3D12_SRV_DIMENSION_TEXTURE2D;
            sd.Shader4ComponentMapping = D3D12_DEFAULT_SHADER_4_COMPONENT_MAPPING;
            sd.Texture2D.MipLevels = 1;
            g_device->CreateShaderResourceView(g_book_rt, &sd, cpu);
            g_book_tex = static_cast<ImTextureID>(gpu.ptr);
            g_book_page = page;
        } else {
            log_err("book page texture unavailable; the menu opens flat");
        }
    }

    RECT rc{};
    GetClientRect(desc.OutputWindow, &rc);
    log("renderer ready: " + std::to_string(desc.BufferDesc.Width) + "x"
        + std::to_string(desc.BufferDesc.Height) + " (client "
        + std::to_string(rc.right - rc.left) + "x" + std::to_string(rc.bottom - rc.top)
        + "), format " + std::to_string(int(desc.BufferDesc.Format)) + ", "
        + std::to_string(n) + " buffers");
    return true;
}

void open_menu() {
    g_visible.store(true);
    log("menu opened");
}

void set_book_mode(BookMode m, const char* why) {
    if (m == g_book_mode) return;
    g_book_mode = m;
    g_book_since = now_ms();
    g_rb_valid_after = g_fence_last;   // a copy from before this change is not this book
    g_book_masking.store(m == BookMode::Shown || m == BookMode::Closing);
    if (m == BookMode::Shown) {
        g_book_escape_epoch = g_escape_epoch.load();
        g_book_hides_seen = g_book_hides.load();
    }
    if (m == BookMode::Calibrating) {
        g_next_capture = g_book_since;
        g_calib_tries = 0;
    }
    if (m == BookMode::Off) g_mask_until_release.store(true);
    static const char* const kNames[] = {"closed", "opening", "calibrating", "shown", "closing"};
    log(std::string("book menu ") + kNames[int(m)] + " (" + why + ")");
}

// Press a point of the game's own UI: move the cursor there (the game reads
// hover from window messages, so they must reach it), report the left button
// held for a moment through the game's GetAsyncKeyState, put the cursor back.
void click_game_at(POINT client) {
    const unsigned long long t = now_ms();
    const LPARAM at = MAKELPARAM(client.x, client.y);
    ClientToScreen(g_hwnd, &client);
    if (g_cursor_iat_slot) {
        g_fake_cursor_x.store(client.x);
        g_fake_cursor_y.store(client.y);
        g_fake_cursor_until.store(t + 320);
        g_fake_cursor_lp.store(at);
        PostMessageA(g_hwnd, WM_MOUSEMOVE, 0, at);
    } else {
        if (!g_cursor_restore_at) GetCursorPos(&g_cursor_restore);
        SetCursorPos(client.x, client.y);
    }
    g_fake_click_from.store(t + 80);
    g_fake_click_to.store(t + 220);
    g_cursor_restore_at = t + 320;
    g_clicked_at = t;
}

void press_escape() {
    const unsigned long long t = now_ms();
    g_fake_escape_from.store(t + 30);
    g_fake_escape_to.store(t + 160);
}

// The book's Settings (gear) tab, measured on the lobby book at 3440x1407:
// centre-relative, in screen widths, like book_warp (the book scales with the
// width). The tab is ~160 x 85 px there, so the uncalibrated position is
// close enough to hit it.
POINT gear_tab(float width, float height) {
    return POINT{LONG(width * 0.5f - 0.17733f * width), LONG(height * 0.5f - 0.18125f * width)};
}

// Mods in the escape menu. In a run: press the escape menu's own Settings
// button (the 2nd of its column, measured in overlay_menu.cpp's
// menu_escape_button). In the lobby: close the escape menu, then the gear tab.
void open_book_from_escape(float width, float height) {
    g_book_from_run = g_run_menu.load();
    if (g_book_from_run) {
        click_game_at(POINT{LONG(width * 0.5f), LONG(height * (0.370f + 0.0624f + 0.0262f))});
        g_open_step = OpenStep::WaitForPage;
    } else {
        press_escape();
        g_open_step = OpenStep::CloseEscape;
    }
    set_book_mode(BookMode::Opening, g_book_from_run ? "Settings via the escape menu" : "lobby book");
}

// The book's first tab (Play), measured with the gear tab: the lobby's book
// returns there on Back.
POINT play_tab(float width, float height) {
    return POINT{LONG(width * 0.5f - 0.27442f * width), LONG(height * 0.5f - 0.18125f * width)};
}

// Leave the way the game does, with its animation: in a run, Esc (the game
// closes its Settings book and returns to the escape menu); in the lobby,
// turn the book back to its Play page. The pages stay painted and tracked
// while the book moves (Closing) until it is no longer recognised.
void close_book(const char* why) {
    if (g_book_mode == BookMode::Shown) {
        if (g_book_from_run) {
            press_escape();
        } else {
            RECT r{};
            GetClientRect(g_hwnd, &r);
            click_game_at(play_tab(float(r.right - r.left), float(r.bottom - r.top)));
        }
        g_track_hot_until = now_ms() + kClosingMaxMs;
        set_book_mode(BookMode::Closing, why);
        return;
    }
    set_book_mode(BookMode::Off, why);
}

void release_readbacks() {
    for (Readback& r : g_rbs) {
        if (r.buf && r.mapped) r.buf->Unmap(0, nullptr);
        r.mapped = nullptr;
        r.fence = 0;
        release(r.list);
        release(r.alloc);
        release(r.buf);
    }
    g_rb_w = 0;
    g_rb_h = 0;
}

// Queue a copy of the back buffer as the game left it (nothing of ours is
// drawn yet this frame) into the next free readback slot. Returns the slot,
// or -1 (unsupported format, or both slots still in flight).
int capture_async(ID3D12Resource* target, ID3D12CommandQueue* queue) {
    const D3D12_RESOURCE_DESC desc = target->GetDesc();
    const bool bgra = desc.Format == DXGI_FORMAT_B8G8R8A8_UNORM || desc.Format == DXGI_FORMAT_B8G8R8A8_UNORM_SRGB;
    const bool rgba = desc.Format == DXGI_FORMAT_R8G8B8A8_UNORM || desc.Format == DXGI_FORMAT_R8G8B8A8_UNORM_SRGB;
    if (!bgra && !rgba) {
        static bool s_logged = false;
        if (!s_logged) log("cannot read back format " + std::to_string(int(desc.Format)) + "; book not calibrated");
        s_logged = true;
        return -1;
    }
    if (g_rb_w != desc.Width || g_rb_h != desc.Height) {
        gpu_wait_idle();
        release_readbacks();
        UINT rows = 0;
        UINT64 row_bytes = 0, total = 0;
        g_device->GetCopyableFootprints(&desc, 0, 1, 0, &g_rb_fp, &rows, &row_bytes, &total);
        D3D12_HEAP_PROPERTIES heap{};
        heap.Type = D3D12_HEAP_TYPE_READBACK;
        D3D12_RESOURCE_DESC bd{};
        bd.Dimension = D3D12_RESOURCE_DIMENSION_BUFFER;
        bd.Width = total;
        bd.Height = 1;
        bd.DepthOrArraySize = 1;
        bd.MipLevels = 1;
        bd.SampleDesc.Count = 1;
        bd.Layout = D3D12_TEXTURE_LAYOUT_ROW_MAJOR;
        for (Readback& r : g_rbs) {
            const bool made = SUCCEEDED(g_device->CreateCommittedResource(&heap, D3D12_HEAP_FLAG_NONE, &bd,
                                  D3D12_RESOURCE_STATE_COPY_DEST, nullptr, __uuidof(ID3D12Resource),
                                  reinterpret_cast<void**>(&r.buf)))
                && SUCCEEDED(g_device->CreateCommandAllocator(D3D12_COMMAND_LIST_TYPE_DIRECT,
                                  __uuidof(ID3D12CommandAllocator), reinterpret_cast<void**>(&r.alloc)))
                && SUCCEEDED(g_device->CreateCommandList(0, D3D12_COMMAND_LIST_TYPE_DIRECT, r.alloc, nullptr,
                                  __uuidof(ID3D12GraphicsCommandList), reinterpret_cast<void**>(&r.list)))
                && SUCCEEDED(r.buf->Map(0, nullptr, &r.mapped));
            if (!made) {
                release_readbacks();
                return -1;
            }
            r.list->Close();
        }
        g_rb_w = desc.Width;
        g_rb_h = desc.Height;
    }
    const int slot = g_rb_next;
    Readback& r = g_rbs[slot];
    if (r.fence && g_fence->GetCompletedValue() < r.fence) return -1;   // still copying
    r.alloc->Reset();
    r.list->Reset(r.alloc, nullptr);
    D3D12_RESOURCE_BARRIER b{};
    b.Type = D3D12_RESOURCE_BARRIER_TYPE_TRANSITION;
    b.Transition.pResource = target;
    b.Transition.Subresource = D3D12_RESOURCE_BARRIER_ALL_SUBRESOURCES;
    b.Transition.StateBefore = D3D12_RESOURCE_STATE_PRESENT;
    b.Transition.StateAfter = D3D12_RESOURCE_STATE_COPY_SOURCE;
    r.list->ResourceBarrier(1, &b);
    D3D12_TEXTURE_COPY_LOCATION from{};
    from.pResource = target;
    from.Type = D3D12_TEXTURE_COPY_TYPE_SUBRESOURCE_INDEX;
    D3D12_TEXTURE_COPY_LOCATION to{};
    to.pResource = r.buf;
    to.Type = D3D12_TEXTURE_COPY_TYPE_PLACED_FOOTPRINT;
    to.PlacedFootprint = g_rb_fp;
    r.list->CopyTextureRegion(&to, 0, 0, 0, &from, nullptr);
    b.Transition.StateBefore = D3D12_RESOURCE_STATE_COPY_SOURCE;
    b.Transition.StateAfter = D3D12_RESOURCE_STATE_PRESENT;
    r.list->ResourceBarrier(1, &b);
    r.list->Close();
    ID3D12CommandList* lists[] = {r.list};
    o_execute(queue, 1, lists);
    queue->Signal(g_fence, ++g_fence_last);
    r.fence = g_fence_last;
    r.bgra = bgra;
    g_rb_next ^= 1;
    return slot;
}

calib::View slot_view(int slot) {
    calib::View v;
    v.px = static_cast<const std::uint8_t*>(g_rbs[slot].mapped) + g_rb_fp.Offset;
    v.w = int(g_rb_w);
    v.h = int(g_rb_h);
    v.pitch = g_rb_fp.Footprint.RowPitch;
    v.bgra = g_rbs[slot].bgra;
    return v;
}

// The newest finished copy not read yet, without waiting. Marks it read.
bool take_finished(calib::View* out) {
    const UINT64 done = g_fence ? g_fence->GetCompletedValue() : 0;
    int best = -1;
    for (int i = 0; i < 2; ++i) {
        const UINT64 f = g_rbs[i].fence;
        if (f && f <= done && f > g_rb_valid_after && (best < 0 || f > g_rbs[best].fence)) best = i;
    }
    if (best < 0) return false;
    *out = slot_view(best);
    for (Readback& r : g_rbs) {
        if (r.fence && r.fence <= g_rbs[best].fence) r.fence = 0;
    }
    return true;
}

// The current frame, waiting for the copy: only for the occasional full
// search, never per frame.
bool capture_view(ID3D12Resource* target, ID3D12CommandQueue* queue, calib::View* out) {
    const int slot = capture_async(target, queue);
    if (slot < 0) return false;
    gpu_wait_idle();
    *out = slot_view(slot);
    g_rbs[slot].fence = 0;
    return true;
}

// One frame of the game as luminance + RGB, for the full search and the
// lighting measurement on the worker thread (which needs its own copy).
bool capture_frame(ID3D12Resource* target, ID3D12CommandQueue* queue, calib::Frame* out) {
    calib::View v;
    if (!capture_view(target, queue, &v)) return false;
    out->w = v.w;
    out->h = v.h;
    out->lum.resize(std::size_t(v.w) * v.h);
    out->rgb.resize(std::size_t(v.w) * v.h * 3);
    const int r = v.bgra ? 2 : 0, bl = v.bgra ? 0 : 2;
    for (int y = 0; y < v.h; ++y) {
        const std::uint8_t* row = v.px + std::size_t(y) * v.pitch;
        std::uint8_t* dst = &out->lum[std::size_t(y) * v.w];
        std::uint8_t* rgb = &out->rgb[std::size_t(y) * v.w * 3];
        for (int x = 0; x < v.w; ++x) {
            const std::uint8_t* p = row + std::size_t(x) * 4;
            dst[x] = std::uint8_t((p[r] * 54 + p[1] * 183 + p[bl] * 19) >> 8);
            rgb[x * 3] = p[r];
            rgb[x * 3 + 1] = p[1];
            rgb[x * 3 + 2] = p[bl];
        }
    }
    return true;
}

// Re-find the book near where it was, on the newest finished copy (a frame
// or two old), and queue a copy of this frame for next time. 1 = found,
// 0 = not recognisable (moved too far, turned its page, left the screen),
// -1 = no finished copy yet.
int track_book(ID3D12Resource* target, ID3D12CommandQueue* queue) {
    int w = 0, h = 0, w2 = 0, h2 = 0;
    const std::uint8_t* left = overlay::menu_texture_pixels("ornament_l", &w, &h);
    const std::uint8_t* right = overlay::menu_texture_pixels("ornament_r", &w2, &h2);
    if (!left || !right || w != w2 || h != h2) return 0;
    calib::View v;
    const bool have = take_finished(&v);
    int found = -1;
    if (have) {
        const std::uint8_t* const art[2] = {left, right};
        const calib::Result r = calib::track(v, art, w, h, g_calib);
        found = r.ok ? 1 : 0;
        if (r.ok) {
            // Frame-to-frame noise (fire, particles) moves the best fit by a
            // pixel or so: a still book keeps its placement, or the pages
            // shimmer. Only a real move is taken, and keeps tracking hot.
            const float ds = std::fabs(r.calib.s - g_calib.s) * float(g_rb_w);
            const float dd = std::max(std::fabs(r.calib.dx - g_calib.dx), std::fabs(r.calib.dy - g_calib.dy));
            const bool hot = now_ms() < g_track_hot_until;
            if (std::max(ds, dd) > 1.5f) g_track_hot_until = std::max(g_track_hot_until, now_ms() + kTrackHotMs);
            if (hot || std::max(ds, dd) > 1.5f) g_calib = r.calib;
        }
    }
    capture_async(target, queue);
    return found;
}

// Opening -> Calibrating -> Shown, and back to Off when the game closes its
// book or opens its escape menu over it.
void step_book_mode(float width, float height) {
    const unsigned long long t = now_ms();
    if (g_cursor_restore_at && t >= g_cursor_restore_at) {
        if (g_cursor_iat_slot) {
            // Hand the game back the real cursor for its hover.
            POINT p{};
            GetCursorPos(&p);
            ScreenToClient(g_hwnd, &p);
            PostMessageA(g_hwnd, WM_MOUSEMOVE, 0, MAKELPARAM(p.x, p.y));
        } else {
            SetCursorPos(g_cursor_restore.x, g_cursor_restore.y);
        }
        g_cursor_restore_at = 0;
    }
    switch (g_book_mode) {
        case BookMode::Opening: {
            if (g_open_step == OpenStep::CloseEscape) {
                if (t >= g_fake_escape_to.load() && !g_escape_menu.load()) {
                    click_game_at(gear_tab(width, height));
                    g_open_step = OpenStep::WaitForPage;
                }
            } else if (t >= g_fake_click_to.load() + kCalibrateAfterClickMs) {
                set_book_mode(BookMode::Calibrating, "looking for the Settings page");
            }
            if (g_book_mode == BookMode::Opening && t - g_book_since > 5000) {
                set_book_mode(BookMode::Off, "the escape menu did not close");
            }
            break;
        }
        case BookMode::Calibrating:
            if (g_book_from_run && !g_escape_menu.load()) {
                // The Settings click did not open the book (the game closed
                // its escape menu instead): nothing to paint on.
                set_book_mode(BookMode::Off, "the escape menu closed before the book opened");
                break;
            }
            if (g_calib_state.load() == 2) {
                g_calib_state.store(0);
                ++g_calib_tries;
                const calib::Result& r = g_calib_result;
                if (r.ok || t - g_book_since > kCalibrateGiveUpMs) {
                    char buf[200];
                    std::snprintf(buf, sizeof(buf), "calibration after %d frame(s): score %.1f "
                                  "(uncalibrated %.1f), scale %.3f, offset %.1f, %.1f px", g_calib_tries,
                                  r.score, r.identity_score, r.calib.s, r.calib.dx, r.calib.dy);
                    log(buf);
                }
                if (r.ok) {
                    g_calib = r.calib;
                    g_light = std::move(g_calib_light);
                    g_have_lock = true;
                    // The search ran on a frame from a moment ago: track hard
                    // while the book may still be settling.
                    g_track_hot_until = t + 1500;
                    set_book_mode(BookMode::Shown, "calibrated");
                } else if (t - g_book_since > kCalibrateGiveUpMs) {
                    // Leave the game's book as it is: it works on its own.
                    set_book_mode(BookMode::Off, "the Settings page was not found on screen");
                } else {
                    g_next_capture = t + 120;   // the book is still moving: try a newer frame
                }
            }
            break;
        case BookMode::Shown:
            // A full search that was still running when a quick lock showed
            // the pages: keep its lighting (measured on this book).
            if (g_calib_state.load() == 2) {
                g_calib_state.store(0);
                if (g_calib_result.ok) g_light = std::move(g_calib_light);
            }
            if (g_book_hides.load() != g_book_hides_seen) set_book_mode(BookMode::Off, "the game closed its book");
            else if (g_escape_epoch.load() != g_book_escape_epoch) set_book_mode(BookMode::Off, "escape menu opened");
            break;
        case BookMode::Closing:
            if (t - g_book_since > kClosingMaxMs) set_book_mode(BookMode::Off, "closing took too long");
            break;
        case BookMode::Off:
            break;
    }
}

// Start calibrating on this frame: capture it, search on a worker thread.
void start_calibration(ID3D12Resource* target, ID3D12CommandQueue* queue) {
    if (g_calib_state.load() != 0) return;
    calib::Frame frame;
    int w = 0, h = 0, w2 = 0, h2 = 0;
    const std::uint8_t* left = overlay::menu_texture_pixels("ornament_l", &w, &h);
    const std::uint8_t* right = overlay::menu_texture_pixels("ornament_r", &w2, &h2);
    if (!left || !right || w != w2 || h != h2 || !capture_frame(target, queue, &frame)) {
        // No art to match or no frame: paint with the measured shape as is.
        g_calib_result = calib::Result{};
        g_calib_result.ok = left && right;
        g_calib_state.store(2);
        return;
    }
    g_calib_state.store(1);
    const warp::Calib hint = g_calib;
    int pw = 0, ph = 0, pw2 = 0, ph2 = 0;
    const std::uint8_t* page_l = overlay::menu_texture_pixels("page_l", &pw, &ph);
    const std::uint8_t* page_r = overlay::menu_texture_pixels("page_r", &pw2, &ph2);
    if (pw != pw2 || ph != ph2) page_l = page_r = nullptr;
    std::thread([frame = std::move(frame), left, right, w, h, hint, page_l, page_r, pw, ph]() {
        const std::uint8_t* const art[2] = {left, right};
        calib::Result r = calib::find(frame, art, w, h, hint);
        calib::Lighting light;
        if (r.ok && page_l && page_r) {
            const std::uint8_t* const pages[2] = {page_l, page_r};
            light = calib::measure_lighting(frame, r.calib, pages, pw, ph, art, w, h, 24);
        }
        g_calib_light = std::move(light);
        g_calib_result = r;
        g_calib_state.store(2);
    }).detach();
}

// Draw the pages' texture onto the game's book through the calibrated warp,
// lit like the game lights its book: each vertex carries the measured
// lighting (relative to the texture's kPageHeadroom darkening).
void draw_pages_on_book(ImDrawList* dl, float width, float height) {
    constexpr int kGrid = 40;
    constexpr int kVerts = (kGrid + 1) * (kGrid + 1);
    dl->PushTexture(g_book_tex);
    for (int page = 0; page < 2; ++page) {
        dl->PrimReserve(kGrid * kGrid * 6, kVerts);
        const ImDrawIdx base = ImDrawIdx(dl->_VtxCurrentIdx);
        const float u0 = page * 0.5f;
        for (int j = 0; j <= kGrid; ++j) {
            for (int i = 0; i <= kGrid; ++i) {
                const float u = float(i) / kGrid, v = float(j) / kGrid;
                const overlay::warp::Vec2 p = overlay::warp::page_to_screen(page, u, v, width, height, g_calib);
                float g[3];
                g_light.at(page, u, v, g);
                if (g_light.grid == 0) g[0] = g[1] = g[2] = kPageHeadroom;   // unmeasured: as drawn
                auto ch = [](float x) { return int(std::clamp(x / kPageHeadroom, 0.0f, 1.0f) * 255.0f + 0.5f); };
                dl->PrimWriteVtx(ImVec2(p.x, p.y), ImVec2(u0 + 0.5f * u, v), IM_COL32(ch(g[0]), ch(g[1]), ch(g[2]), 255));
            }
        }
        for (int j = 0; j < kGrid; ++j) {
            for (int i = 0; i < kGrid; ++i) {
                const ImDrawIdx a = ImDrawIdx(base + j * (kGrid + 1) + i);
                const ImDrawIdx b = ImDrawIdx(a + 1), d = ImDrawIdx(a + kGrid + 1), c = ImDrawIdx(d + 1);
                dl->PrimWriteIdx(a);
                dl->PrimWriteIdx(b);
                dl->PrimWriteIdx(c);
                dl->PrimWriteIdx(a);
                dl->PrimWriteIdx(c);
                dl->PrimWriteIdx(d);
            }
        }
    }
    dl->PopTexture();
}

// Input for the painted pages: the mouse goes through the inverse warp into
// the pages window's own coordinates; keys and characters come from the
// queued window messages. Queued after the platform backend's own events so
// these are the ones ImGui ends the frame with.
void feed_page_input(const std::vector<Msg>& msgs, float width, float height) {
    ImGuiIO& io = ImGui::GetIO();
    POINT c{};
    GetCursorPos(&c);
    ScreenToClient(g_hwnd, &c);
    float u = 0, v = 0;
    // The content sits on the UI plane, not the curved page (book_warp).
    const int page = overlay::warp::screen_to_content({float(c.x), float(c.y)}, width, height, g_calib, &u, &v);
    if (page >= 0) io.AddMousePosEvent((page + u) * g_book_page, v * g_book_page);
    else io.AddMousePosEvent(-FLT_MAX, -FLT_MAX);
    io.AddMouseButtonEvent(0, (GetAsyncKeyState(VK_LBUTTON) & 0x8000) != 0);
    for (const Msg& m : msgs) {
        if (m.msg == WM_MOUSEWHEEL) {
            io.AddMouseWheelEvent(0, float(GET_WHEEL_DELTA_WPARAM(m.wp)) / WHEEL_DELTA);
        } else if (m.msg == WM_CHAR && m.wp >= 32) {
            io.AddInputCharacter(unsigned(m.wp));
        } else if (m.msg == WM_KEYDOWN || m.msg == WM_KEYUP) {
            ImGuiKey k = ImGuiKey_None;
            switch (m.wp) {
                case VK_BACK: k = ImGuiKey_Backspace; break;
                case VK_DELETE: k = ImGuiKey_Delete; break;
                case VK_RETURN: k = ImGuiKey_Enter; break;
                case VK_LEFT: k = ImGuiKey_LeftArrow; break;
                case VK_RIGHT: k = ImGuiKey_RightArrow; break;
                case VK_HOME: k = ImGuiKey_Home; break;
                case VK_END: k = ImGuiKey_End; break;
                default: break;
            }
            if (k != ImGuiKey_None) io.AddKeyEvent(k, m.msg == WM_KEYDOWN);
        }
    }
}

// Route the painted pages' draw lists. The art window's go into the page
// texture (drawn onto the curved page by draw_pages_on_book). The content
// window's (and its tooltips, opened at page coordinates) stay on the screen
// but are moved there vertex by vertex through the flat UI plane the game's
// own buttons sit on, lit like the page, so text stays sharp and straight.
bool starts_with(const char* s, const char* prefix) { return std::strncmp(s, prefix, std::strlen(prefix)) == 0; }

void place_content_vertex(ImDrawVert& vtx, float width, float height) {
    const float P = float(g_book_page);
    const int page = vtx.pos.x >= P ? 1 : 0;
    const float u = (vtx.pos.x - page * P) / P, v = vtx.pos.y / P;
    const overlay::warp::Vec2 p = overlay::warp::content_to_screen(page, u, v, width, height, g_calib);
    vtx.pos = ImVec2(p.x, p.y);
    float g[3];
    g_light.at(page, std::clamp(u, 0.0f, 1.0f), std::clamp(v, 0.0f, 1.0f), g);
    const ImU32 c = vtx.col;
    auto ch = [&](int shift, float gain) {
        return ImU32(std::clamp(float((c >> shift) & 0xFF) * gain, 0.0f, 255.0f) + 0.5f) << shift;
    };
    vtx.col = ch(IM_COL32_R_SHIFT, g[0]) | ch(IM_COL32_G_SHIFT, g[1]) | ch(IM_COL32_B_SHIFT, g[2])
              | (c & (ImU32(0xFF) << IM_COL32_A_SHIFT));
}

ImVec4 place_content_clip(const ImVec4& r, float width, float height) {
    const float P = float(g_book_page);
    const ImVec2 corners[4] = {{r.x, r.y}, {r.z, r.y}, {r.x, r.w}, {r.z, r.w}};
    ImVec4 out(FLT_MAX, FLT_MAX, -FLT_MAX, -FLT_MAX);
    for (const ImVec2& k : corners) {
        const int page = k.x >= P ? 1 : 0;
        const overlay::warp::Vec2 p = overlay::warp::content_to_screen(
            page, std::clamp((k.x - page * P) / P, 0.0f, 1.0f), std::clamp(k.y / P, 0.0f, 1.0f), width, height, g_calib);
        out = ImVec4(std::min(out.x, p.x), std::min(out.y, p.y), std::max(out.z, p.x), std::max(out.w, p.y));
    }
    return out;
}

void split_page_draw_data(ImDrawData* screen, ImDrawData* pages, float width, float height) {
    pages->Clear();
    pages->Valid = true;
    pages->DisplayPos = ImVec2(0, 0);
    pages->DisplaySize = ImVec2(2.0f * g_book_page, float(g_book_page));
    pages->FramebufferScale = ImVec2(1, 1);
    pages->OwnerViewport = screen->OwnerViewport;
    pages->Textures = screen->Textures;
    ImVector<ImDrawList*> keep;
    for (ImDrawList* dl : screen->CmdLists) {
        const char* owner = dl->_OwnerName ? dl->_OwnerName : "";
        if (starts_with(owner, kArtWindow)) {
            pages->CmdLists.push_back(dl);
            pages->TotalVtxCount += dl->VtxBuffer.Size;
            pages->TotalIdxCount += dl->IdxBuffer.Size;
            continue;
        }
        if (starts_with(owner, kPagesWindow) || starts_with(owner, "##Tooltip")) {
            for (ImDrawVert& v : dl->VtxBuffer) place_content_vertex(v, width, height);
            for (ImDrawCmd& cmd : dl->CmdBuffer) cmd.ClipRect = place_content_clip(cmd.ClipRect, width, height);
        }
        keep.push_back(dl);
    }
    pages->CmdListsCount = pages->CmdLists.Size;
    screen->CmdLists.swap(keep);
    screen->CmdListsCount = screen->CmdLists.Size;
    screen->TotalVtxCount = screen->TotalIdxCount = 0;
    for (ImDrawList* dl : screen->CmdLists) {
        screen->TotalVtxCount += dl->VtxBuffer.Size;
        screen->TotalIdxCount += dl->IdxBuffer.Size;
    }
}

void close_menu(const char* how) {
    g_visible.store(false);
    g_mask_until_release.store(true);
    log(std::string("menu closed (") + how + ")");
}

void on_present(IDXGISwapChain* raw) {
    std::lock_guard<std::mutex> lock(g_mu);

    ID3D12CommandQueue* queue = g_queue.load();
    if (!queue) {
        if (!g_logged_no_queue) {
            g_logged_no_queue = true;
            log("Present seen before any DIRECT queue; waiting for one");
        }
        return;
    }

    IDXGISwapChain3* sc = nullptr;
    if (FAILED(raw->QueryInterface(__uuidof(IDXGISwapChain3),
                                   reinterpret_cast<void**>(&sc)))) {
        return;
    }
    sc->Release();   // the game holds it; we only need the typed pointer this call

    if (g_renderer_ready && sc != g_sc) renderer_teardown();
    if (!g_renderer_ready && !renderer_init(sc)) {
        renderer_teardown();
        return;
    }

    // The toggle is polled here, not taken from WM_KEYDOWN: the first launch
    // showed the panel ready but no key message ever reached the subclass.
    // This module's GetAsyncKeyState import is the real one (only the game's
    // import is masked), and only the focused game window counts.
    static bool s_toggle_down = false;
    static bool s_escape_down = false;
    auto held = [](int vk) { return (GetAsyncKeyState(vk) & 0x8000) != 0; };
    bool down = false;
    for (int vk : kToggleKeys) down |= held(vk);
    const bool escape = held(VK_ESCAPE);
    const bool focused = GetForegroundWindow() == g_hwnd;
    if (focused && down && !s_toggle_down) {
        if (g_book_mode != BookMode::Off) close_book("toggle key");
        else if (g_visible.load()) close_menu("toggle key");
        // Always the flat book: painting onto the game's book needs a known
        // context (the escape menu's Mods button). From here the game could
        // be mid-run, where a click sent to the game's tab position would
        // land in the world, and "the book is up" is not reliable (above).
        else open_menu();
    } else if (focused && escape && !s_escape_down && g_visible.load()) {
        close_menu("Esc");
    } else if (focused && escape && !s_escape_down && g_book_mode == BookMode::Shown) {
        // Handled here rather than passed to the game: the game did not
        // react to a real Esc over the painted pages (2026-10-24 launch),
        // while the Esc close_book sends it always worked.
        close_book("Esc");
    }
    RECT rc{};
    GetClientRect(g_hwnd, &rc);
    const float width = float(rc.right - rc.left), height = float(rc.bottom - rc.top);
    step_book_mode(width, height);
    s_toggle_down = down;
    s_escape_down = escape;
    if (g_mask_until_release.load() && !down && !escape && !held(VK_LBUTTON) && !held(VK_RBUTTON)) {
        g_mask_until_release.store(false);
    }

    std::vector<Msg> msgs;
    {
        std::lock_guard<std::mutex> in(g_in_mu);
        msgs.swap(g_in);
    }
    // A real click on the escape menu's column (not ours: fake clicks only
    // exist for the game, at its GetAsyncKeyState).
    static bool s_click_down = false;
    const bool click = held(VK_LBUTTON);
    if (click && !s_click_down && g_book_mode == BookMode::Off && g_escape_menu.load() && !g_visible.load()) {
        POINT p{};
        GetCursorPos(&p);
        ScreenToClient(g_hwnd, &p);
        const float col_half = height * 0.294f * 0.5f;
        if (std::fabs(float(p.x) - width * 0.5f) <= col_half && p.y >= height * 0.370f
            && p.y <= height * (0.370f + (g_run_menu.load() ? 3 : 2) * 0.0624f)) {   // vanilla rows, not Mods
            g_vanilla_watch_until = now_ms() + kVanillaWatchMs;
            g_rb_valid_after = g_fence_last;
        }
    }
    s_click_down = click;
    if (!g_escape_menu.load() || g_book_mode != BookMode::Off) {
        g_vanilla_watch_until = 0;
        if (g_vanilla_book) log("the game's Settings book is gone");
        g_vanilla_book = false;
    }

    const UINT idx = sc->GetCurrentBackBufferIndex();
    ++g_frame_no;
    if (idx < g_frames.size() && g_book_mode == BookMode::Off && (g_vanilla_book || now_ms() < g_vanilla_watch_until)) {
        ID3D12Resource* target = g_frames[idx].target;
        if (!g_vanilla_book) {
            if (track_book(target, queue) == 1) {
                g_vanilla_book = true;
                g_vanilla_lost = 0;
                g_vanilla_watch_until = 0;
                log("the game's Settings book is open; Mods button hidden");
            }
        } else if (g_frame_no % 5 == 0) {
            const int found = track_book(target, queue);
            if (found == 1) {
                g_vanilla_lost = 0;
            } else if (found == 0 && ++g_vanilla_lost >= 2) {
                g_vanilla_book = false;
                log("the game's Settings book is gone");
            }
        }
    }
    if (idx < g_frames.size()) {
        ID3D12Resource* target = g_frames[idx].target;
        if (g_book_mode == BookMode::Calibrating) {
            // The quick way in: the book usually comes to rest where it was
            // last time, so try tracking from there on every frame; the full
            // search (worker) covers the first open and a moved camera.
            if (g_have_lock && track_book(target, queue) == 1) {
                log("book found by tracking from the last position");
                g_track_hot_until = now_ms() + kTrackHotMs;
                set_book_mode(BookMode::Shown, "tracked");
            } else if (now_ms() >= g_next_capture) {
                start_calibration(target, queue);
            }
        } else if (g_book_mode == BookMode::Shown || g_book_mode == BookMode::Closing) {
            const bool due = now_ms() < g_track_hot_until || g_frame_no % kTrackIdleEvery == 0;
            if (due) {
                const int found = track_book(target, queue);
                if (found == 1) {
                    g_track_lost = 0;
                } else if (found == 0 && ++g_track_lost >= 2) {
                    g_track_lost = 0;
                    if (g_book_mode == BookMode::Closing) {
                        set_book_mode(BookMode::Off, "the book has gone");
                    } else if (now_ms() - g_book_since < 3000) {
                        // Locked while the book was still moving in (a page
                        // turn): look again rather than leave the vanilla page.
                        set_book_mode(BookMode::Calibrating, "lost the book right after opening; looking again");
                    } else {
                        set_book_mode(BookMode::Off, "lost the book on screen");
                    }
                }
            }
        }
    }

    const bool book = (g_book_mode == BookMode::Shown || g_book_mode == BookMode::Closing) && g_book_page > 0;
    const bool menu = g_visible.load() && !book;
    // While our book is on its way (Opening/Calibrating) the Mods button
    // stays, like a vanilla button stays until its page covers it; it goes
    // when our pages are painted.
    const bool opening = g_book_mode == BookMode::Opening || g_book_mode == BookMode::Calibrating;
    const bool button_only = !menu && !book && (g_book_mode == BookMode::Off || opening) && g_escape_menu.load()
                             && !escape_menu_covered() && !g_vanilla_book && now_ms() >= g_vanilla_watch_until;
    if (!menu && !button_only && !book) return;
    if (!book) {
        for (const Msg& m : msgs) ImGui_ImplWin32_WndProcHandler(g_hwnd, m.msg, m.wp, m.lp);
    }

    if (idx >= g_frames.size()) return;
    Frame& f = g_frames[idx];
    if (f.fence_value && g_fence->GetCompletedValue() < f.fence_value) {
        g_fence->SetEventOnCompletion(f.fence_value, g_fence_event);
        WaitForSingleObject(g_fence_event, 2000);
    }

    ImGui_ImplDX12_NewFrame();
    ImGui_ImplWin32_NewFrame();
    if (book) feed_page_input(msgs, width, height);
    // The game shows its own cursor in its escape menu and on its book; ours
    // only for the flat book, where the game may have hidden it.
    ImGui::GetIO().MouseDrawCursor = menu;
    ImGui::NewFrame();
    if (book) {
        if (!overlay::menu_draw_pages(float(g_book_page)) && g_book_mode == BookMode::Shown) close_book("Back");
        draw_pages_on_book(ImGui::GetBackgroundDrawList(), width, height);
    } else if (menu) {
        if (!overlay::menu_draw()) close_menu("Back");
    } else if (overlay::menu_escape_button(g_run_menu.load() ? 3 : 2) && !opening) {
        if (g_book_page) open_book_from_escape(width, height);
        else open_menu();
    }
    ImGui::Render();
    ImDrawData pages_dd;
    const bool paint_pages = book;
    if (paint_pages) split_page_draw_data(ImGui::GetDrawData(), &pages_dd, width, height);

    f.alloc->Reset();
    g_list->Reset(f.alloc, nullptr);
    D3D12_RESOURCE_BARRIER barrier{};
    barrier.Type = D3D12_RESOURCE_BARRIER_TYPE_TRANSITION;
    barrier.Transition.pResource = f.target;
    barrier.Transition.Subresource = D3D12_RESOURCE_BARRIER_ALL_SUBRESOURCES;
    barrier.Transition.StateBefore = D3D12_RESOURCE_STATE_PRESENT;
    barrier.Transition.StateAfter = D3D12_RESOURCE_STATE_RENDER_TARGET;
    if (paint_pages) {
        D3D12_RESOURCE_BARRIER rt{};
        rt.Type = D3D12_RESOURCE_BARRIER_TYPE_TRANSITION;
        rt.Transition.pResource = g_book_rt;
        rt.Transition.Subresource = D3D12_RESOURCE_BARRIER_ALL_SUBRESOURCES;
        rt.Transition.StateBefore = D3D12_RESOURCE_STATE_PIXEL_SHADER_RESOURCE;
        rt.Transition.StateAfter = D3D12_RESOURCE_STATE_RENDER_TARGET;
        g_list->ResourceBarrier(1, &rt);
        const D3D12_CPU_DESCRIPTOR_HANDLE brtv = g_book_rtv_heap->GetCPUDescriptorHandleForHeapStart();
        const float clear[4] = {0, 0, 0, 0};
        g_list->ClearRenderTargetView(brtv, clear, 0, nullptr);
        g_list->OMSetRenderTargets(1, &brtv, FALSE, nullptr);
        g_list->SetDescriptorHeaps(1, &g_srv_heap);
        ImGui_ImplDX12_RenderDrawData(&pages_dd, g_list);
        rt.Transition.StateBefore = D3D12_RESOURCE_STATE_RENDER_TARGET;
        rt.Transition.StateAfter = D3D12_RESOURCE_STATE_PIXEL_SHADER_RESOURCE;
        g_list->ResourceBarrier(1, &rt);
    }
    g_list->ResourceBarrier(1, &barrier);
    g_list->OMSetRenderTargets(1, &f.rtv, FALSE, nullptr);
    g_list->SetDescriptorHeaps(1, &g_srv_heap);
    ImGui_ImplDX12_RenderDrawData(ImGui::GetDrawData(), g_list);
    barrier.Transition.StateBefore = D3D12_RESOURCE_STATE_RENDER_TARGET;
    barrier.Transition.StateAfter = D3D12_RESOURCE_STATE_PRESENT;
    g_list->ResourceBarrier(1, &barrier);
    g_list->Close();

    ID3D12CommandList* lists[] = {g_list};
    o_execute(queue, 1, lists);
    queue->Signal(g_fence, ++g_fence_last);
    f.fence_value = g_fence_last;

    if (!g_logged_first_frame) {
        g_logged_first_frame = true;
        log("first panel frame submitted");
    }
}

// A swapchain call that reached us through another hooked swapchain method
// (some implementations route Present through Present1) must not draw twice.
thread_local int t_depth = 0;

HRESULT STDMETHODCALLTYPE hk_present(IDXGISwapChain* sc, UINT sync, UINT flags) {
    if (t_depth++ == 0 && !(flags & DXGI_PRESENT_TEST)) on_present(sc);
    const HRESULT hr = o_present(sc, sync, flags);
    --t_depth;
    return hr;
}

HRESULT STDMETHODCALLTYPE hk_present1(IDXGISwapChain1* sc, UINT sync, UINT flags,
                                      const DXGI_PRESENT_PARAMETERS* params) {
    if (t_depth++ == 0 && !(flags & DXGI_PRESENT_TEST)) on_present(sc);
    const HRESULT hr = o_present1(sc, sync, flags, params);
    --t_depth;
    return hr;
}

// ResizeBuffers fails while anyone still holds a back buffer, so ours go first.
HRESULT STDMETHODCALLTYPE hk_resize(IDXGISwapChain* sc, UINT n, UINT w, UINT h,
                                    DXGI_FORMAT fmt, UINT flags) {
    log("ResizeBuffers " + std::to_string(w) + "x" + std::to_string(h));
    {
        std::lock_guard<std::mutex> lock(g_mu);
        if (g_renderer_ready) renderer_teardown();
    }
    ++t_depth;
    const HRESULT hr = o_resize(sc, n, w, h, fmt, flags);
    --t_depth;
    return hr;
}

HRESULT STDMETHODCALLTYPE hk_resize1(IDXGISwapChain3* sc, UINT n, UINT w, UINT h,
                                     DXGI_FORMAT fmt, UINT flags, const UINT* mask,
                                     IUnknown* const* queues) {
    log("ResizeBuffers1 " + std::to_string(w) + "x" + std::to_string(h));
    {
        std::lock_guard<std::mutex> lock(g_mu);
        if (g_renderer_ready) renderer_teardown();
    }
    ++t_depth;
    const HRESULT hr = o_resize1(sc, n, w, h, fmt, flags, mask, queues);
    --t_depth;
    return hr;
}

// The swapchain does not expose its queue, so learn it from the first DIRECT
// queue the game submits on. Distinct DIRECT queues are logged: more than one
// would mean the panel may be submitting on the wrong one.
void STDMETHODCALLTYPE hk_execute(ID3D12CommandQueue* q, UINT n,
                                  ID3D12CommandList* const* lists) {
    static std::atomic<bool> s_warned_second{false};
    if (q->GetDesc().Type == D3D12_COMMAND_LIST_TYPE_DIRECT) {
        ID3D12CommandQueue* expected = nullptr;
        if (g_queue.load() == nullptr) {
            q->AddRef();   // keeps the pointer valid however long we hold it
            if (g_queue.compare_exchange_strong(expected, q)) {
                log("captured the game's DIRECT command queue");
            } else {
                q->Release();
            }
        }
        if (q != g_queue.load() && !s_warned_second.exchange(true)) {
            Loader::get().log_warn(std::string(kTag)
                + "a second DIRECT queue is in use; the panel stays on the first");
        }
    }
    o_execute(q, n, lists);
}

bool is_input_msg(UINT m) {
    return (m >= WM_MOUSEFIRST && m <= WM_MOUSELAST) || (m >= WM_KEYFIRST && m <= WM_KEYLAST)
           || m == WM_SETFOCUS || m == WM_KILLFOCUS || m == WM_MOUSELEAVE;
}

// Stops at us while the panel is open: WM_SYS* still reach the game so
// Alt+Tab / Alt+F4 keep working.
bool swallow_while_open(UINT m) {
    if (m >= WM_MOUSEFIRST && m <= WM_MOUSELAST) return true;
    return m == WM_KEYDOWN || m == WM_KEYUP || m == WM_CHAR || m == WM_DEADCHAR
           || m == WM_UNICHAR;
}

bool is_toggle_key(WPARAM wp) {
    for (int vk : kToggleKeys) {
        if (wp == static_cast<WPARAM>(vk)) return true;
    }
    return false;
}

LRESULT CALLBACK wndproc(HWND hwnd, UINT msg, WPARAM wp, LPARAM lp) {
    // Diagnostic: the panel's mouse input arrives only through here, so say
    // once whether the game's window messages reach the subclass at all.
    static std::atomic<bool> s_seen_input{false};
    if (is_input_msg(msg) && !s_seen_input.exchange(true)) {
        char buf[64];
        std::snprintf(buf, sizeof(buf), "window input is arriving (first msg 0x%x)", msg);
        log(buf);
    }
    // During a fake click the game must keep seeing the clicked point: a real
    // move would pull its hover off the button before the press lands.
    if (msg == WM_MOUSEMOVE && now_ms() < g_fake_cursor_until.load() && lp != g_fake_cursor_lp.load()) return 0;
    // Toggling happens in Present; keep the key from the game.
    if ((msg == WM_KEYDOWN || msg == WM_KEYUP) && is_toggle_key(wp)) return 0;
    // In the game's escape menu the Mods button needs the mouse too, but the
    // game keeps it: only an open book swallows input.
    const bool book_open = g_book_masking.load();
    if (g_visible.load() || book_open || (g_escape_menu.load() && !escape_menu_covered())) {
        if (is_input_msg(msg)) {
            std::lock_guard<std::mutex> in(g_in_mu);
            if (g_in.size() < 1024) g_in.push_back({msg, wp, lp});
        }
        // The painted pages keep the game's own cursor, which follows mouse
        // moves; clicks still stop here (and at GetAsyncKeyState).
        const bool keep_move = book_open && msg == WM_MOUSEMOVE;
        if ((g_visible.load() || book_open) && !keep_move && swallow_while_open(msg)) return 0;
    }
    return CallWindowProcA(g_prev_wndproc, hwnd, msg, wp, lp);
}

template <int I>
void hk_cover_show(void* controller) {
    Cover& c = g_covers[I];
    hook_note_fire(c.show_va);
    c.o_show(controller);
    if (I == 0) g_book_ui.store(true);
    if (g_escape_menu.load() && !c.up.exchange(true)) log(std::string(c.what) + " opened over the escape menu");
}

template <int I>
void hk_cover_hide(void* controller) {
    Cover& c = g_covers[I];
    hook_note_fire(c.hide_va);
    c.o_hide(controller);
    c.up.store(false);
    if (I == 0) {
        g_book_ui.store(false);
        g_book_hides.fetch_add(1);
    }
}

template <int I>
void install_cover() {
    Cover& c = g_covers[I];
    if (!hook_install("ingame-ui", c.what, c.show_pattern, reinterpret_cast<void*>(&hk_cover_show<I>),
                      reinterpret_cast<void**>(&c.o_show), &c.show_va)) {
        return;
    }
    if (!hook_install("ingame-ui", c.what, c.hide_pattern, reinterpret_cast<void*>(&hk_cover_hide<I>),
                      reinterpret_cast<void**>(&c.o_hide), &c.hide_va)) {
        // A show with no hide would hide the button for good.
        hook_remove(c.show_va);
        c.show_va = 0;
    }
}

void hk_menu_enter(void* controller) {
    hook_note_fire(g_menu_enter_va);
    for (Cover& c : g_covers) c.up.store(false);   // a fresh escape menu starts uncovered
    g_escape_epoch.fetch_add(1);
    o_menu_enter(controller);
    if (!g_escape_menu.exchange(true)) log("escape menu opened");
}

void hk_run_menu_enter(void* self, void* ctx) {
    hook_note_fire(g_run_menu_enter_va);
    o_run_menu_enter(self, ctx);
    if (!g_run_menu.exchange(true)) log("run menu state entered");
}

void hk_run_menu_leave(void* self, void* ctx) {
    hook_note_fire(g_run_menu_leave_va);
    o_run_menu_leave(self, ctx);
    if (g_run_menu.exchange(false)) log("run menu state left");
}

void hk_menu_leave(void* controller) {
    hook_note_fire(g_menu_leave_va);
    o_menu_leave(controller);
    if (g_escape_menu.exchange(false)) log("escape menu closed");
}

// The game polls every key and mouse button through GetAsyncKeyState
// (input poll, see the recon doc), so blocking its window messages alone
// would still let clicks through to the game.
SHORT WINAPI hk_get_async_key_state(int vk) {
    const unsigned long long t = now_ms();
    if (vk == VK_LBUTTON && t >= g_fake_click_from.load() && t < g_fake_click_to.load()) {
        return SHORT(0x8000);
    }
    if (vk == VK_ESCAPE && t >= g_fake_escape_from.load() && t < g_fake_escape_to.load()) {
        return SHORT(0x8000);
    }
    if (g_book_masking.load()) return 0;   // Esc included: the overlay closes the book itself
    if (g_visible.load() || g_mask_until_release.load()) return 0;
    return o_get_async_key_state(vk);
}

BOOL WINAPI hk_get_cursor_pos(LPPOINT p) {
    if (p && now_ms() < g_fake_cursor_until.load()) {
        p->x = g_fake_cursor_x.load();
        p->y = g_fake_cursor_y.load();
        return TRUE;
    }
    return o_get_cursor_pos(p);
}

std::uintptr_t* find_iat_slot(HMODULE mod, const char* dll, const char* fn) {
    auto* base = reinterpret_cast<BYTE*>(mod);
    auto* dos = reinterpret_cast<IMAGE_DOS_HEADER*>(base);
    if (dos->e_magic != IMAGE_DOS_SIGNATURE) return nullptr;
    auto* nt = reinterpret_cast<IMAGE_NT_HEADERS*>(base + dos->e_lfanew);
    const auto& dir = nt->OptionalHeader.DataDirectory[IMAGE_DIRECTORY_ENTRY_IMPORT];
    if (!dir.VirtualAddress) return nullptr;
    for (auto* imp = reinterpret_cast<IMAGE_IMPORT_DESCRIPTOR*>(base + dir.VirtualAddress);
         imp->Name; ++imp) {
        if (_stricmp(reinterpret_cast<const char*>(base + imp->Name), dll) != 0) continue;
        auto* thunk = reinterpret_cast<IMAGE_THUNK_DATA*>(base + imp->FirstThunk);
        auto* names = reinterpret_cast<IMAGE_THUNK_DATA*>(
            base + (imp->OriginalFirstThunk ? imp->OriginalFirstThunk : imp->FirstThunk));
        for (; thunk->u1.Function; ++thunk, ++names) {
            if (names->u1.Ordinal & IMAGE_ORDINAL_FLAG) continue;
            auto* by_name = reinterpret_cast<IMAGE_IMPORT_BY_NAME*>(
                base + names->u1.AddressOfData);
            if (strcmp(reinterpret_cast<const char*>(by_name->Name), fn) == 0) {
                return reinterpret_cast<std::uintptr_t*>(&thunk->u1.Function);
            }
        }
    }
    return nullptr;
}

bool write_slot(std::uintptr_t* slot, std::uintptr_t value) {
    DWORD old = 0;
    if (!VirtualProtect(slot, sizeof(*slot), PAGE_READWRITE, &old)) return false;
    *slot = value;
    VirtualProtect(slot, sizeof(*slot), old, &old);
    return true;
}

LRESULT CALLBACK dummy_wndproc(HWND h, UINT m, WPARAM w, LPARAM l) {
    return DefWindowProcA(h, m, w, l);
}

// Build a throwaway device + queue + swapchain to read the vtables the game's
// own objects share (one vtable per implementing class).
bool read_vtables(void** vt_sc, bool* has_sc3, void** vt_queue) {
    static const char* const d3d12[] = {"d3d12.dll", nullptr};
    auto create_device = reinterpret_cast<PFN_D3D12_CREATE_DEVICE>(
        proc_of(d3d12, "D3D12CreateDevice"));
    if (!create_device) {
        log_err("d3d12.dll has no D3D12CreateDevice");
        return false;
    }

    WNDCLASSEXA wc{};
    wc.cbSize = sizeof(wc);
    wc.lpfnWndProc = &dummy_wndproc;
    wc.hInstance = GetModuleHandleA(nullptr);
    wc.lpszClassName = "rsmm_overlay_probe";
    RegisterClassExA(&wc);
    HWND hwnd = CreateWindowExA(0, wc.lpszClassName, "", WS_OVERLAPPEDWINDOW, 0, 0,
                                64, 64, nullptr, nullptr, wc.hInstance, nullptr);

    ID3D12Device* dev = nullptr;
    ID3D12CommandQueue* queue = nullptr;
    IDXGIFactory1* factory = nullptr;
    IDXGISwapChain* sc = nullptr;
    bool ok = false;
    do {
        if (!hwnd) { log_err("probe window creation failed"); break; }
        if (FAILED(create_device(nullptr, D3D_FEATURE_LEVEL_11_0, __uuidof(ID3D12Device),
                                 reinterpret_cast<void**>(&dev)))) {
            log_err("probe D3D12 device creation failed");
            break;
        }
        D3D12_COMMAND_QUEUE_DESC qd{};
        qd.Type = D3D12_COMMAND_LIST_TYPE_DIRECT;
        if (FAILED(dev->CreateCommandQueue(&qd, __uuidof(ID3D12CommandQueue),
                                           reinterpret_cast<void**>(&queue)))) {
            log_err("probe command queue creation failed");
            break;
        }
        if (FAILED(CreateDXGIFactory1(__uuidof(IDXGIFactory1),
                                      reinterpret_cast<void**>(&factory)))) {
            log_err("probe DXGI factory creation failed");
            break;
        }
        DXGI_SWAP_CHAIN_DESC sd{};
        sd.BufferCount = 2;
        sd.BufferDesc.Width = 64;
        sd.BufferDesc.Height = 64;
        sd.BufferDesc.Format = DXGI_FORMAT_R8G8B8A8_UNORM;
        sd.BufferUsage = DXGI_USAGE_RENDER_TARGET_OUTPUT;
        sd.OutputWindow = hwnd;
        sd.SampleDesc.Count = 1;
        sd.Windowed = TRUE;
        sd.SwapEffect = DXGI_SWAP_EFFECT_FLIP_DISCARD;
        if (FAILED(factory->CreateSwapChain(queue, &sd, &sc))) {
            log_err("probe swapchain creation failed");
            break;
        }
        IDXGISwapChain3* sc3 = nullptr;
        *has_sc3 = SUCCEEDED(sc->QueryInterface(__uuidof(IDXGISwapChain3),
                                                reinterpret_cast<void**>(&sc3)));
        release(sc3);
        *vt_sc = *reinterpret_cast<void**>(sc);
        *vt_queue = *reinterpret_cast<void**>(queue);
        ok = true;
    } while (false);

    release(sc);
    release(factory);
    release(queue);
    release(dev);
    if (hwnd) DestroyWindow(hwnd);
    UnregisterClassA(wc.lpszClassName, wc.hInstance);
    return ok;
}

// --- diagnostics -------------------------------------------------------------
// The game started exiting ~2 s into boot with this build and left neither a
// crash dump nor an error. These say how: any serious exception (with the
// module and offset it happened in) and any ExitProcess / TerminateProcess the
// game itself calls (with the game function that called it).

std::atomic<int> g_exceptions_logged{0};
PVOID g_veh = nullptr;
using ExitProcessFn = void(WINAPI*)(UINT);
using TerminateProcessFn = BOOL(WINAPI*)(HANDLE, UINT);
ExitProcessFn o_exit_process = nullptr;
TerminateProcessFn o_terminate_process = nullptr;
std::uintptr_t* g_exit_slot = nullptr;
std::uintptr_t* g_terminate_slot = nullptr;

std::string where(const void* addr) {
    HMODULE mod = nullptr;
    char name[MAX_PATH] = "?";
    if (GetModuleHandleExA(GET_MODULE_HANDLE_EX_FLAG_FROM_ADDRESS
                           | GET_MODULE_HANDLE_EX_FLAG_UNCHANGED_REFCOUNT,
                           static_cast<LPCSTR>(addr), &mod) && mod) {
        GetModuleFileNameA(mod, name, sizeof(name));
    }
    const char* base = name;
    for (const char* q = name; *q; ++q) {
        if (*q == '\\' || *q == '/') base = q + 1;
    }
    char buf[MAX_PATH + 64];
    std::snprintf(buf, sizeof(buf), "%p (%s+0x%llx)", addr, base,
                  mod ? static_cast<unsigned long long>(reinterpret_cast<std::uintptr_t>(addr)
                                                        - reinterpret_cast<std::uintptr_t>(mod))
                      : 0ULL);
    return buf;
}

LONG CALLBACK diag_veh(EXCEPTION_POINTERS* ep) {
    const DWORD code = ep->ExceptionRecord->ExceptionCode;
    // Serious ones only: access violations, illegal instructions, stack
    // overflow, heap corruption, fail-fast. Not C++ throws or debug output.
    const bool serious = code == EXCEPTION_ACCESS_VIOLATION || code == EXCEPTION_ILLEGAL_INSTRUCTION
                         || code == EXCEPTION_STACK_OVERFLOW || code == 0xC0000374 || code == 0xC0000409
                         || code == EXCEPTION_PRIV_INSTRUCTION || code == EXCEPTION_INT_DIVIDE_BY_ZERO;
    if (serious && g_exceptions_logged.fetch_add(1) < 8) {
        char buf[96];
        std::snprintf(buf, sizeof(buf), "exception 0x%08lx on thread %lu at ", code, GetCurrentThreadId());
        std::string line = std::string(buf) + where(ep->ExceptionRecord->ExceptionAddress);
        if (code == EXCEPTION_ACCESS_VIOLATION && ep->ExceptionRecord->NumberParameters >= 2) {
            std::snprintf(buf, sizeof(buf), ", %s 0x%llx",
                          ep->ExceptionRecord->ExceptionInformation[0] ? "writing" : "reading",
                          static_cast<unsigned long long>(ep->ExceptionRecord->ExceptionInformation[1]));
            line += buf;
        }
        Loader::get().log_err(std::string(kTag) + line);
    }
    return EXCEPTION_CONTINUE_SEARCH;
}

void WINAPI hk_exit_process(UINT code) {
    char buf[64];
    std::snprintf(buf, sizeof(buf), "the game called ExitProcess(%u) from ", code);
    Loader::get().log_warn(std::string(kTag) + buf + where(__builtin_return_address(0)));
    o_exit_process(code);
}

BOOL WINAPI hk_terminate_process(HANDLE process, UINT code) {
    if (process == GetCurrentProcess() || GetProcessId(process) == GetCurrentProcessId()) {
        char buf[64];
        std::snprintf(buf, sizeof(buf), "the game called TerminateProcess(self, %u) from ", code);
        Loader::get().log_warn(std::string(kTag) + buf + where(__builtin_return_address(0)));
    }
    return o_terminate_process(process, code);
}

void install_diagnostics() {
    g_veh = AddVectoredExceptionHandler(0, &diag_veh);   // last in line: observe, never handle
    if (HMODULE game = GetModuleHandleA(nullptr)) {
        g_exit_slot = find_iat_slot(game, "KERNEL32.dll", "ExitProcess");
        g_terminate_slot = find_iat_slot(game, "KERNEL32.dll", "TerminateProcess");
    }
    if (g_exit_slot) {
        o_exit_process = reinterpret_cast<ExitProcessFn>(*g_exit_slot);
        if (!write_slot(g_exit_slot, reinterpret_cast<std::uintptr_t>(&hk_exit_process))) g_exit_slot = nullptr;
    }
    if (g_terminate_slot) {
        o_terminate_process = reinterpret_cast<TerminateProcessFn>(*g_terminate_slot);
        if (!write_slot(g_terminate_slot, reinterpret_cast<std::uintptr_t>(&hk_terminate_process))) {
            g_terminate_slot = nullptr;
        }
    }
}

void remove_diagnostics() {
    if (g_veh) RemoveVectoredExceptionHandler(g_veh);
    g_veh = nullptr;
    if (g_exit_slot) write_slot(g_exit_slot, reinterpret_cast<std::uintptr_t>(o_exit_process));
    if (g_terminate_slot) write_slot(g_terminate_slot, reinterpret_cast<std::uintptr_t>(o_terminate_process));
    g_exit_slot = g_terminate_slot = nullptr;
}

} // namespace

bool install_overlay_hooks() {
    install_diagnostics();
    overlay::menu_init(Loader::get().game_dir());

    void* vt_sc = nullptr;
    void* vt_queue = nullptr;
    bool has_sc3 = false;
    if (!read_vtables(&vt_sc, &has_sc3, &vt_queue)) return false;
    auto slot = [](void* vt, int i) {
        return reinterpret_cast<std::uintptr_t>(static_cast<void**>(vt)[i]);
    };

    // Queue first: Present does nothing until it knows the queue.
    if (!hook_install_at("ingame-ui", "ExecuteCommandLists",
                         slot(vt_queue, kSlotExecuteCommandLists),
                         reinterpret_cast<void*>(&hk_execute),
                         reinterpret_cast<void**>(&o_execute), EntryCheck::AnyModule)) {
        return false;
    }
    g_hooked[0] = slot(vt_queue, kSlotExecuteCommandLists);
    if (!hook_install_at("ingame-ui", "ResizeBuffers", slot(vt_sc, kSlotResizeBuffers),
                         reinterpret_cast<void*>(&hk_resize),
                         reinterpret_cast<void**>(&o_resize), EntryCheck::AnyModule)) {
        remove_overlay_hooks();
        return false;
    }
    g_hooked[1] = slot(vt_sc, kSlotResizeBuffers);
    if (has_sc3) {
        if (hook_install_at("ingame-ui", "ResizeBuffers1", slot(vt_sc, kSlotResizeBuffers1),
                            reinterpret_cast<void*>(&hk_resize1),
                            reinterpret_cast<void**>(&o_resize1), EntryCheck::AnyModule)) {
            g_hooked[2] = slot(vt_sc, kSlotResizeBuffers1);
        }
        if (hook_install_at("ingame-ui", "Present1", slot(vt_sc, kSlotPresent1),
                            reinterpret_cast<void*>(&hk_present1),
                            reinterpret_cast<void**>(&o_present1), EntryCheck::AnyModule)) {
            g_hooked[3] = slot(vt_sc, kSlotPresent1);
        }
    }
    if (!hook_install_at("ingame-ui", "Present", slot(vt_sc, kSlotPresent),
                         reinterpret_cast<void*>(&hk_present),
                         reinterpret_cast<void**>(&o_present), EntryCheck::AnyModule)) {
        remove_overlay_hooks();
        return false;
    }
    g_hooked[4] = slot(vt_sc, kSlotPresent);

    if (HMODULE game = GetModuleHandleA(nullptr)) {
        g_iat_slot = find_iat_slot(game, "USER32.dll", "GetAsyncKeyState");
    }
    if (g_iat_slot) {
        o_get_async_key_state = reinterpret_cast<GetAsyncKeyStateFn>(*g_iat_slot);
        if (!write_slot(g_iat_slot,
                        reinterpret_cast<std::uintptr_t>(&hk_get_async_key_state))) {
            g_iat_slot = nullptr;
        }
    }
    if (HMODULE game = GetModuleHandleA(nullptr)) {
        g_cursor_iat_slot = find_iat_slot(game, "USER32.dll", "GetCursorPos");
    }
    if (g_cursor_iat_slot) {
        o_get_cursor_pos = reinterpret_cast<GetCursorPosFn>(*g_cursor_iat_slot);
        if (!write_slot(g_cursor_iat_slot, reinterpret_cast<std::uintptr_t>(&hk_get_cursor_pos))) {
            g_cursor_iat_slot = nullptr;
        }
    }
    if (!g_cursor_iat_slot) log("could not patch GetCursorPos; clicks for the game will move the cursor");
    if (!g_iat_slot) {
        Loader::get().log_warn(std::string(kTag) + "could not patch GetAsyncKeyState; "
                               "clicks on the panel will also reach the game");
    }
    // Optional: without them the menu still opens on F8 / Insert.
    const bool enter = hook_install("ingame-ui", "escape menu show", Sym::UiController_OnShow_Pattern,
                                    reinterpret_cast<void*>(&hk_menu_enter),
                                    reinterpret_cast<void**>(&o_menu_enter), &g_menu_enter_va);
    const bool leave = enter && hook_install("ingame-ui", "escape menu hide",
                                    Sym::UiController_OnHide_Pattern,
                                    reinterpret_cast<void*>(&hk_menu_leave),
                                    reinterpret_cast<void**>(&o_menu_leave), &g_menu_leave_va);
    if (enter && !leave) {
        // An enter with no leave would leave the button up forever.
        hook_remove(g_menu_enter_va);
        g_menu_enter_va = 0;
    }
    if (leave) {
        // Each only hides the button under its UI; a missing one costs that.
        install_cover<0>();
        install_cover<1>();
        install_cover<2>();
        static_assert(sizeof(g_covers) / sizeof(g_covers[0]) == 3, "install every cover");
        // Only places the button; without it the lobby layout is assumed.
        const bool run_in = hook_install("ingame-ui", "run menu enter", Sym::InGameMenuGs_OnEnter_Pattern,
                                         reinterpret_cast<void*>(&hk_run_menu_enter),
                                         reinterpret_cast<void**>(&o_run_menu_enter), &g_run_menu_enter_va);
        const bool run_out = run_in && hook_install("ingame-ui", "run menu leave",
                                         Sym::InGameMenuGs_OnLeave_Pattern,
                                         reinterpret_cast<void*>(&hk_run_menu_leave),
                                         reinterpret_cast<void**>(&o_run_menu_leave), &g_run_menu_leave_va);
        if (run_in && !run_out) {
            hook_remove(g_run_menu_enter_va);
            g_run_menu_enter_va = 0;
        }
    }
    log(leave ? "installed; F8 / Insert or Mods in the escape menu opens the menu"
              : "installed; F8 / Insert opens the menu (no escape-menu button this build)");
    return true;
}

void remove_overlay_hooks() {
    remove_diagnostics();
    hook_remove(g_menu_enter_va);
    hook_remove(g_menu_leave_va);
    hook_remove(g_run_menu_enter_va);
    hook_remove(g_run_menu_leave_va);
    for (Cover& c : g_covers) {
        hook_remove(c.show_va);
        hook_remove(c.hide_va);
        c.show_va = c.hide_va = 0;
    }
    g_menu_enter_va = g_menu_leave_va = g_run_menu_enter_va = g_run_menu_leave_va = 0;
    for (auto& va : g_hooked) {
        hook_remove(va);
        va = 0;
    }
    if (g_iat_slot && o_get_async_key_state) {
        write_slot(g_iat_slot, reinterpret_cast<std::uintptr_t>(o_get_async_key_state));
        g_iat_slot = nullptr;
    }
    if (g_cursor_iat_slot && o_get_cursor_pos) {
        write_slot(g_cursor_iat_slot, reinterpret_cast<std::uintptr_t>(o_get_cursor_pos));
        g_cursor_iat_slot = nullptr;
    }
    std::lock_guard<std::mutex> lock(g_mu);
    if (g_hwnd && g_prev_wndproc
        && GetWindowLongPtrA(g_hwnd, GWLP_WNDPROC) == reinterpret_cast<LONG_PTR>(&wndproc)) {
        SetWindowLongPtrA(g_hwnd, GWLP_WNDPROC, reinterpret_cast<LONG_PTR>(g_prev_wndproc));
    }
    if (g_renderer_ready) renderer_teardown();
    if (g_imgui_ready) {
        ImGui_ImplWin32_Shutdown();
        ImGui::DestroyContext();
        g_imgui_ready = false;
    }
    if (ID3D12CommandQueue* q = g_queue.exchange(nullptr)) q->Release();
}

} // namespace rsmm
