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

/// Prepend the monorepo root to the process PATH so Tauri's shell plugin can
/// resolve the `rsmm` command without frontend env workarounds.
///
/// This is a no-op in production (no repo root found) and safe to call
/// multiple times (idempotent — only prepends once).
pub fn prepend_repo_root_to_path() {
    let Some(root) = find_repo_root() else { return };
    let root_str = match root.to_str() {
        Some(s) => s.to_string(),
        None => return,
    };
    let current = std::env::var("PATH").unwrap_or_default();
    if current.contains(&root_str) {
        return;
    }
    let new_path = if current.is_empty() {
        root_str.clone()
    } else {
        format!("{root_str}:{current}")
    };
    std::env::set_var("PATH", &new_path);
    eprintln!("[rsmm_env] prepended repo root to PATH: {new_path}");
}

#[tauri::command]
pub fn rsmm_runtime_env() -> RsmmRuntimeEnv {
    let repo_root = find_repo_root()
        .and_then(|p| p.to_str().map(|s| s.to_string()))
        .unwrap_or_default();
    let path = std::env::var("PATH").unwrap_or_default();
    RsmmRuntimeEnv { repo_root, path }
}
