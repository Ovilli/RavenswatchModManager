use serde::{Deserialize, Serialize};
use std::path::PathBuf;
use tauri::Manager;

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

fn target_triple() -> &'static str {
    match option_env!("TARGET") {
        Some(t) => t,
        None => "x86_64-unknown-linux-gnu",
    }
}

/// Return the full path to the rsmm sidecar binary in a production bundle.
/// Tries multiple possible locations since the path depends on the Tauri 2
/// bundler version and target format.
fn sidecar_path(app: &tauri::AppHandle) -> Option<PathBuf> {
    let resource_dir = app.path().resource_dir().ok()?;
    let triple = target_triple();
    let candidates = [
        resource_dir.join("binaries").join(format!("rsmm-{triple}")),
        resource_dir.join(format!("rsmm-{triple}")),
    ];
    candidates.iter().find(|p| p.exists()).cloned()
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

/// Run `rsmm` directly, bypassing the shell plugin's PATH / sidecar
/// resolution entirely. In dev mode finds the Python wrapper at the repo
/// root; in production runs the bundled sidecar via `std::process::Command`.
/// Used by the TypeScript probe as a fallback when the shell plugin fails.
#[tauri::command]
pub fn probe_rsmm(app: tauri::AppHandle, args: Vec<String>) -> Result<RsmmExecResult, String> {
    let rsmm = rsmm_path()
        .or_else(|| sidecar_path(&app))
        .ok_or_else(|| "rsmm not found".to_string())?;

    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        let _ = std::fs::set_permissions(&rsmm, std::fs::Permissions::from_mode(0o755));
    }

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
