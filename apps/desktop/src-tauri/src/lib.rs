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
    builder = builder.plugin(tauri_plugin_shell::init());

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
