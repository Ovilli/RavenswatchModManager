//! The CLI downloaded from the rolling `cli` release (see
//! src/rsmm/engine/cli_update.py), in `<app local data>/cli/`:
//!
//! * `staged/`  — written by `rsmm json update-cli`, never run from;
//! * `current/` — what the app runs, when it beats the bundled sidecar.
//!
//! `staged` becomes `current` here, at startup, before the frontend can spawn a
//! CLI: Windows cannot replace a directory a running process holds files in.

use serde::{Deserialize, Serialize};
use std::path::{Path, PathBuf};
use tauri::Manager;

#[derive(Deserialize)]
struct Stamp {
    cli_version: u64,
    abi: u64,
}

/// The stamp of the CLI bundled into this app build.
fn bundled() -> Stamp {
    serde_json::from_str(include_str!("../../../../data/cli_version.json"))
        .expect("data/cli_version.json is malformed")
}

fn read_stamp(dir: &Path) -> Option<Stamp> {
    serde_json::from_str(&std::fs::read_to_string(dir.join("channel.json")).ok()?).ok()
}

fn exe_name() -> &'static str {
    if cfg!(windows) {
        "rsmm.exe"
    } else {
        "rsmm"
    }
}

pub fn channel_dir(app: &tauri::AppHandle) -> Option<PathBuf> {
    Some(app.path().app_local_data_dir().ok()?.join("cli"))
}

/// Swap a fully staged build into `current`. Best effort: on any failure the
/// app keeps running whatever it ran before.
pub fn promote_staged(app: &tauri::AppHandle) {
    let Some(root) = channel_dir(app) else { return };
    if let Ok(entries) = std::fs::read_dir(&root) {
        for e in entries.flatten() {
            if e.file_name().to_string_lossy().starts_with("old-") {
                let _ = std::fs::remove_dir_all(e.path());
            }
        }
    }
    let staged = root.join("staged");
    if read_stamp(&staged).is_none() || !staged.join(exe_name()).is_file() {
        return;
    }
    let current = root.join("current");
    let old = root.join(format!("old-{}", std::process::id()));
    if current.exists() && std::fs::rename(&current, &old).is_err() {
        return;
    }
    if std::fs::rename(&staged, &current).is_err() {
        let _ = std::fs::rename(&old, &current);
        return;
    }
    let _ = std::fs::remove_dir_all(&old);
}

/// The channel CLI, when it is the one to run: same abi as this app and a
/// HIGHER version than the bundled copy. Equal means the bundled sidecar,
/// which may carry newer commits under the same stamp.
pub fn active_exe(app: &tauri::AppHandle) -> Option<PathBuf> {
    let current = channel_dir(app)?.join("current");
    let stamp = read_stamp(&current)?;
    let own = bundled();
    let exe = current.join(exe_name());
    (stamp.abi == own.abi && stamp.cli_version > own.cli_version && exe.is_file()).then_some(exe)
}

#[derive(Serialize)]
pub struct CliChannel {
    /// Where `update-cli --dest` stages builds.
    pub dir: Option<String>,
    /// `current` should be run instead of the bundled sidecar.
    pub active: bool,
    /// `cli_version` of the CLI the app runs (channel or bundled).
    pub version: u64,
}

#[tauri::command]
pub fn cli_channel(app: tauri::AppHandle) -> CliChannel {
    let dir = channel_dir(&app);
    let active = active_exe(&app).is_some();
    let version = dir
        .as_deref()
        .filter(|_| active)
        .and_then(|d| read_stamp(&d.join("current")))
        .map_or(bundled().cli_version, |s| s.cli_version);
    CliChannel {
        dir: dir.map(|d| d.to_string_lossy().into_owned()),
        active,
        version,
    }
}
