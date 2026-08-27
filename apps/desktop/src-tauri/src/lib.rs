pub mod graphics_mode;
mod launcher_log;
mod loader_log;
mod profile_dir;
mod rsmm_env;
mod update_env;

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    // Before anything else, attempt to prepend the monorepo root to PATH
    // so the `rsmm` CLI is discoverable during development. In production
    // the sidecar binary handles this — if the repo root isn't found this
    // is a no-op.
    rsmm_env::prepend_repo_root_to_path();

    let mut builder = tauri::Builder::default()
        .setup(|_app| {
            // On Linux (and Windows dev builds) the `rsmm://` scheme isn't
            // claimed by an installer, so register it at runtime. Best-effort:
            // a failure here just means OAuth deep links won't route — the
            // rest of the app still works.
            #[cfg(any(target_os = "linux", all(debug_assertions, target_os = "windows")))]
            {
                use tauri_plugin_deep_link::DeepLinkExt;
                if let Err(e) = _app.deep_link().register_all() {
                    eprintln!("warning: failed to register rsmm:// deep link: {e}");
                }
            }
            Ok(())
        })
        // When the main window goes away, so does the app — even if an
        // auxiliary window (the damage overlay, which is skipTaskbar and
        // therefore invisible in alt-tab) is still open. Without this the
        // process survives its own UI: nothing on screen, nothing in the
        // taskbar, and a second launch is refused by the single-instance
        // plugin. Hooked on DESTROYED rather than CloseRequested so a
        // cancelled quit ("you are still running the game") does not take the
        // overlay down with it.
        .on_window_event(|window, event| {
            if window.label() != "main" {
                return;
            }
            if matches!(event, tauri::WindowEvent::Destroyed) {
                use tauri::Manager;
                let app = window.app_handle().clone();
                for (label, other) in app.webview_windows() {
                    if label != "main" {
                        let _ = other.close();
                    }
                }
            }
        })
        .invoke_handler(tauri::generate_handler![
            launcher_log::append_launcher_log,
            launcher_log::clear_launcher_log,
            launcher_log::read_launcher_log,
            loader_log::read_loader_log_chunk,
            rsmm_env::rsmm_runtime_env,
            rsmm_env::probe_rsmm,
            update_env::update_install_target,
            graphics_mode::gpu_acceleration_disabled,
            graphics_mode::set_gpu_acceleration_disabled,
            profile_dir::open_profile_dir,
        ]);

    // Plugins are best-effort. If one fails to initialize (e.g. an
    // unsupported platform, missing system dependency, or a build that
    // doesn't ship the corresponding crate), log it and keep going —
    // the app should still open without `tauri_plugin_shell` rather
    // than panic on startup.
    // Single instance MUST be registered before the deep-link plugin. With
    // the `deep-link` feature it forwards the `rsmm://` OAuth callback URL to
    // the already-running instance (whose webview holds the in-flight sign-in)
    // instead of letting the OS spawn a second window. The callback just
    // raises the existing window.
    #[cfg(desktop)]
    {
        use tauri::Manager;
        builder = builder.plugin(tauri_plugin_single_instance::init(|app, _argv, _cwd| {
            if let Some(w) = app.get_webview_window("main") {
                let _ = w.set_focus();
            }
        }));
    }

    builder = builder.plugin(tauri_plugin_shell::init());
    // OS plugin: the sign-in flow (@daveyplate/better-auth-tauri) probes
    // `platform()` from `@tauri-apps/plugin-os`. Registering it defines the
    // `__TAURI_OS_PLUGIN_INTERNALS__` global the JS bridge reads — without it
    // login crashes with "undefined is not an object".
    builder = builder.plugin(tauri_plugin_os::init());
    // Opener: lets the frontend launch the system browser for the OAuth flow.
    builder = builder.plugin(tauri_plugin_opener::init());
    // Deep link: receives the `rsmm://` OAuth callback the API redirects to
    // after a social sign-in. `register_all()` claims the scheme at runtime
    // on Linux/Windows (handy for dev — production installers register it via
    // the bundle config). The JS handler lives in src/main.tsx.
    builder = builder.plugin(tauri_plugin_deep_link::init());

    #[cfg(desktop)]
    {
        builder = builder.plugin(tauri_plugin_updater::Builder::new().build());
        builder = builder.plugin(tauri_plugin_process::init());
        // Global shortcut: the escape hatch for a click-through overlay. Once
        // an overlay ignores the mouse it cannot receive the click that would
        // un-ignore it, and alt-tabbing to Settings mid-fight is not an
        // answer — so the toggle has to be reachable while the game has focus.
        builder = builder.plugin(tauri_plugin_global_shortcut::Builder::new().build());
    }

    if let Err(e) = builder.run(tauri::generate_context!()) {
        eprintln!("fatal: tauri runtime exited with error: {e}");
        std::process::exit(1);
    }
}
