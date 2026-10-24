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

#include <atomic>
#include <cstdio>
#include <cstring>
#include <mutex>
#include <string>
#include <vector>

#include "imgui.h"
#include "imgui_impl_dx12.h"
#include "imgui_impl_win32.h"

#include "hook_overlay.h"
#include "hook_util.h"
#include "loader.h"

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

std::atomic<bool> g_visible{false};
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

struct ModRow {
    std::string id;
    std::string name;
    std::string version;
    bool enabled;
};
std::vector<ModRow> g_mods;
int g_click_count = 0;
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
    const float scale = height > 1080 ? float(height) / 1080.0f : 1.0f;
    ImGuiStyle& style = ImGui::GetStyle();
    style.ScaleAllSizes(scale);
    style.FontScaleMain = scale;
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
    info.NumFramesInFlight = static_cast<int>(n);
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

    RECT rc{};
    GetClientRect(desc.OutputWindow, &rc);
    log("renderer ready: " + std::to_string(desc.BufferDesc.Width) + "x"
        + std::to_string(desc.BufferDesc.Height) + " (client "
        + std::to_string(rc.right - rc.left) + "x" + std::to_string(rc.bottom - rc.top)
        + "), format " + std::to_string(int(desc.BufferDesc.Format)) + ", "
        + std::to_string(n) + " buffers");
    return true;
}

void draw_panel() {
    ImGuiIO& io = ImGui::GetIO();
    ImGui::SetNextWindowPos(ImVec2(40, 40), ImGuiCond_FirstUseEver);
    ImGui::SetNextWindowSize(ImVec2(420, 0), ImGuiCond_FirstUseEver);
    if (ImGui::Begin("Ravenswatch Mod Manager")) {
        ImGui::Text("%d mod(s) found", static_cast<int>(g_mods.size()));
        if (ImGui::BeginTable("mods", 3, ImGuiTableFlags_RowBg | ImGuiTableFlags_BordersInnerH)) {
            ImGui::TableSetupColumn("Mod");
            ImGui::TableSetupColumn("Version");
            ImGui::TableSetupColumn("State");
            ImGui::TableHeadersRow();
            for (const auto& m : g_mods) {
                ImGui::TableNextRow();
                ImGui::TableNextColumn();
                ImGui::TextUnformatted(m.name.empty() ? m.id.c_str() : m.name.c_str());
                ImGui::TableNextColumn();
                ImGui::TextUnformatted(m.version.c_str());
                ImGui::TableNextColumn();
                ImGui::TextUnformatted(m.enabled ? "enabled" : "disabled");
            }
            ImGui::EndTable();
        }
        ImGui::Separator();
        if (ImGui::Button("Click test")) {
            ++g_click_count;
            log("click test pressed (" + std::to_string(g_click_count) + ")");
        }
        ImGui::SameLine();
        ImGui::Text("clicked %d time(s)", g_click_count);
        ImGui::TextDisabled("Insert or F8 closes this panel. %.0f FPS", io.Framerate);
    }
    ImGui::End();
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
    bool down = false;
    for (int vk : kToggleKeys) down |= (GetAsyncKeyState(vk) & 0x8000) != 0;
    if (down && !s_toggle_down && GetForegroundWindow() == g_hwnd) {
        const bool now = !g_visible.load();
        g_visible.store(now);
        log(now ? "panel opened" : "panel closed");
    }
    s_toggle_down = down;

    std::vector<Msg> msgs;
    {
        std::lock_guard<std::mutex> in(g_in_mu);
        msgs.swap(g_in);
    }
    if (!g_visible.load()) return;
    for (const Msg& m : msgs) ImGui_ImplWin32_WndProcHandler(g_hwnd, m.msg, m.wp, m.lp);

    const UINT idx = sc->GetCurrentBackBufferIndex();
    if (idx >= g_frames.size()) return;
    Frame& f = g_frames[idx];
    if (f.fence_value && g_fence->GetCompletedValue() < f.fence_value) {
        g_fence->SetEventOnCompletion(f.fence_value, g_fence_event);
        WaitForSingleObject(g_fence_event, 2000);
    }

    ImGui_ImplDX12_NewFrame();
    ImGui_ImplWin32_NewFrame();
    ImGui::GetIO().MouseDrawCursor = true;
    ImGui::NewFrame();
    draw_panel();
    ImGui::Render();

    f.alloc->Reset();
    g_list->Reset(f.alloc, nullptr);
    D3D12_RESOURCE_BARRIER barrier{};
    barrier.Type = D3D12_RESOURCE_BARRIER_TYPE_TRANSITION;
    barrier.Transition.pResource = f.target;
    barrier.Transition.Subresource = D3D12_RESOURCE_BARRIER_ALL_SUBRESOURCES;
    barrier.Transition.StateBefore = D3D12_RESOURCE_STATE_PRESENT;
    barrier.Transition.StateAfter = D3D12_RESOURCE_STATE_RENDER_TARGET;
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
    // Toggling happens in Present; keep the key from the game.
    if ((msg == WM_KEYDOWN || msg == WM_KEYUP) && is_toggle_key(wp)) return 0;
    if (g_visible.load()) {
        if (is_input_msg(msg)) {
            std::lock_guard<std::mutex> in(g_in_mu);
            if (g_in.size() < 1024) g_in.push_back({msg, wp, lp});
        }
        if (swallow_while_open(msg)) return 0;
    }
    return CallWindowProcA(g_prev_wndproc, hwnd, msg, wp, lp);
}

// The game polls every key and mouse button through GetAsyncKeyState
// (input poll, see the recon doc), so blocking its window messages alone
// would still let clicks through to the game.
SHORT WINAPI hk_get_async_key_state(int vk) {
    if (g_visible.load()) return 0;
    return o_get_async_key_state(vk);
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

} // namespace

bool install_overlay_hooks() {
    for (const auto& m : Loader::get().mods()) {
        g_mods.push_back({m.id, m.name, m.version, m.enabled});
    }

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
    if (!g_iat_slot) {
        Loader::get().log_warn(std::string(kTag) + "could not patch GetAsyncKeyState; "
                               "clicks on the panel will also reach the game");
    }
    log("installed; press Insert or F8 in game to open the panel");
    return true;
}

void remove_overlay_hooks() {
    for (auto& va : g_hooked) {
        hook_remove(va);
        va = 0;
    }
    if (g_iat_slot && o_get_async_key_state) {
        write_slot(g_iat_slot, reinterpret_cast<std::uintptr_t>(o_get_async_key_state));
        g_iat_slot = nullptr;
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
