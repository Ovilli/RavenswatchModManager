use serde::{Deserialize, Serialize};
use std::path::PathBuf;

#[derive(Serialize)]
pub struct RsmmRuntimeEnv {
    pub repo_root: String,
    pub path: String,
}

#[derive(Deserialize, Serialize)]
pub struct RsmmExecResult {
    pub code: Option<i32>,
    pub stdout: String,
    pub stderr: String,
}

/// Detect the monorepo root by walking up from the build-time manifest dir.
/// The sentinel is `<repo_root>/rsmm` (the Python CLI wrapper script).
/// Returns `None` when running a bundled release (sidecar handles it).
pub fn find_repo_root() -> Option<PathBuf> {
    let manifest = PathBuf::from(env!("CARGO_MANIFEST_DIR"));
    // CARGO_MANIFEST_DIR = <repo>/apps/desktop/src-tauri
    let candidate = manifest.parent()?.parent()?.parent()?;
    if candidate.join("rsmm").exists() || candidate.join("rsmm.cmd").exists() {
        Some(candidate.to_path_buf())
    } else {
        None
    }
}

/// Return the full path to `rsmm` (the Python CLI wrapper) or `None` when
/// running in a production bundle.
fn rsmm_path() -> Option<PathBuf> {
    let root = find_repo_root()?;
    let candidate = root.join("rsmm");
    if candidate.exists() {
        Some(candidate)
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
    let Some(root) = find_repo_root() else {
        return;
    };
    let root_str = match root.to_str() {
        Some(s) => s.to_string(),
        None => return,
    };
    let current = std::env::var("PATH").unwrap_or_default();
    // Check by splitting on ':' to avoid false positives from subdirectory
    // paths (e.g. `.venv-build/bin` inside the repo root).
    if current.split(':').any(|p| p == root_str) {
        return;
    }
    let new_path = if current.is_empty() {
        root_str
    } else {
        format!("{root_str}:{current}")
    };
    std::env::set_var("PATH", &new_path);
}

#[tauri::command]
pub fn rsmm_runtime_env() -> RsmmRuntimeEnv {
    let repo_root = find_repo_root()
        .and_then(|p| p.to_str().map(|s| s.to_string()))
        .unwrap_or_default();
    let path = std::env::var("PATH").unwrap_or_default();
    RsmmRuntimeEnv { repo_root, path }
}

/// Run `rsmm` directly from the resolved repo-root path, bypassing the
/// shell plugin's PATH / sidecar resolution entirely. Returns stdout,
/// stderr and exit code. Used by the TypeScript probe in dev mode.
///
/// This is a no-op in production — the sidecar handles everything.
#[tauri::command]
pub fn probe_rsmm(args: Vec<String>) -> Result<RsmmExecResult, String> {
    let rsmm = rsmm_path().ok_or_else(|| "rsmm not found (production bundle)".to_string())?;
    let output = std::process::Command::new(&rsmm)
        .args(&args)
        .output()
        .map_err(|e| format!("failed to spawn {rsmm:?}: {e}"))?;
    Ok(RsmmExecResult {
        code: output.status.code(),
        stdout: String::from_utf8_lossy(&output.stdout).to_string(),
        stderr: String::from_utf8_lossy(&output.stderr).to_string(),
    })
}
