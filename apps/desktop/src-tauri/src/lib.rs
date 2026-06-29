mod launcher_log;
mod rsmm_env;

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
        .invoke_handler(tauri::generate_handler![
            launcher_log::append_launcher_log,
            launcher_log::clear_launcher_log,
            launcher_log::read_launcher_log,
            rsmm_env::rsmm_runtime_env,
            rsmm_env::probe_rsmm,
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
    }

    if let Err(e) = builder.run(tauri::generate_context!()) {
        eprintln!("fatal: tauri runtime exited with error: {e}");
        std::process::exit(1);
    }
}
