#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

fn main() {
    // Opt-in software rendering, for a machine whose display driver cannot
    // survive the GPU work a webview does (see graphics_mode.rs). Must run
    // before the Tauri builder: WebView2 reads its arguments from the
    // environment when the webview process starts.
    rsmm_desktop_lib::graphics_mode::apply();

    #[cfg(target_os = "linux")]
    {
        std::env::set_var("WEBKIT_DISABLE_DMABUF_RENDERER", "1");
        std::env::set_var("WEBKIT_DISABLE_COMPOSITING_MODE", "1");
        std::env::set_var("LIBGL_ALWAYS_SOFTWARE", "1");
    }

    rsmm_desktop_lib::run();
}
