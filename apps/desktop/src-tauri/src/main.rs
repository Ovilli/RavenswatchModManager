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

        // The AppImage's own launcher (linuxdeploy's GTK hook) exports
        // `GDK_BACKEND=x11` before we ever run, so a packaged build renders
        // through XWayland on a Wayland desktop while `pnpm dev` renders
        // natively — which is a real difference in scroll smoothness between
        // two builds of identical code, and one nothing outside the process
        // can override, since the hook's `export` wins over an inherited
        // value. GTK reads the variable at init, which happens inside `run()`
        // below, so this is the last point where it can still be changed.
        //
        // Deliberately opt-in: x11 is there because the Wayland backend
        // crashes on some systems (tauri-apps/tauri#8541). This exists so the
        // two can be compared on a machine that is not crashing —
        // `RSMM_GDK_BACKEND=wayland ./RavenswatchModManager.AppImage`.
        if let Some(backend) = std::env::var_os("RSMM_GDK_BACKEND") {
            std::env::set_var("GDK_BACKEND", backend);
        }
    }

    rsmm_desktop_lib::run();
}
