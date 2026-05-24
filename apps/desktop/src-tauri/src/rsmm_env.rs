use serde::Serialize;
use std::path::PathBuf;

#[derive(Serialize)]
pub struct RsmmRuntimeEnv {
    pub repo_root: String,
    pub path: String,
}

/// Detect the monorepo root by walking up from the build-time manifest dir.
/// The sentinel is `<repo_root>/rsmm` (the Python CLI wrapper script).
/// Returns `None` when running a bundled release (sidecar handles it).
fn find_repo_root() -> Option<PathBuf> {
    let manifest = PathBuf::from(env!("CARGO_MANIFEST_DIR"));
    // CARGO_MANIFEST_DIR = <repo>/apps/desktop/src-tauri
    let candidate = manifest.parent()?.parent()?.parent()?;
    if candidate.join("rsmm").exists() || candidate.join("rsmm.cmd").exists() {
        Some(candidate.to_path_buf())
    } else {
        None
    }
}

#[tauri::command]
pub fn rsmm_runtime_env() -> RsmmRuntimeEnv {
    let repo_root = find_repo_root()
        .and_then(|p| p.to_str().map(|s| s.to_string()))
        .unwrap_or_default();
    let path = std::env::var("PATH").unwrap_or_default();
    RsmmRuntimeEnv { repo_root, path }
}
