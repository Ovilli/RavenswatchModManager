use serde::Serialize;
use std::path::Path;

/// Reader for a mod's live overlay rows.
///
/// An overlay HUD polls once a second while the game is being played. It used
/// to do that by spawning the bundled Python CLI — a PyInstaller cold start
/// plus an antivirus scan of the unpacked bundle on Windows, and the command
/// re-parsed EVERY installed mod's `manifest.toml` on every tick to read one
/// small state file. With two HUDs open that was two of those per second,
/// during play. The same mistake the Log screen already fixed for its tail
/// (see `loader_log.rs`), so the same shape of fix: the CLI still owns
/// discovery — game-directory resolution, the manifest declaration, and the
/// `statePath` it hands back — and only the hot loop lives here.
///
/// The file is small (rows are capped at 64 by the CLI that writes the
/// contract) and rewritten wholesale by the mod, so this returns all of it
/// rather than tailing by offset.

/// Refuse anything larger than this. A HUD's state file is a few KB; a
/// megabyte means something else is writing there and it is not ours to load
/// into the webview.
const MAX_BYTES: u64 = 2 * 1024 * 1024;

/// The one file name the loader's `R.kv` writes per mod.
const STATE_FILE: &str = ".rsmm_state";

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
pub struct OverlayState {
    /// False when the mod has not published anything yet — the normal state
    /// for an installed mod before the game has run, not an error.
    pub exists: bool,
    pub size: u64,
    /// Raw `<type>\t<key>\t<value>` lines. Parsed on the frontend, which
    /// already owns the matching decode for the CLI's own output.
    pub content: String,
}

/// Only a mod's own state file is readable through this command.
///
/// Same reasoning as the loader-log reader: the frontend is our own bundle and
/// remote content cannot reach the IPC, but "read any file the user can read,
/// hand it to the webview" is a capability worth not having. Judged on the
/// CANONICAL path, so a `..` segment or a symlink is resolved before the name
/// and its parents are inspected.
///
/// `<game>/mods/<mod folder>/.rsmm_state` — the file name must match exactly
/// and its grandparent must be a `mods` directory.
fn allowed(path: &Path) -> bool {
    if path.file_name().and_then(|s| s.to_str()) != Some(STATE_FILE) {
        return false;
    }
    path.parent()
        .and_then(|mod_dir| mod_dir.parent())
        .and_then(|p| p.file_name())
        .and_then(|s| s.to_str())
        == Some("mods")
}

fn empty() -> OverlayState {
    OverlayState {
        exists: false,
        size: 0,
        content: String::new(),
    }
}

#[tauri::command]
pub fn read_overlay_state(path: String) -> Result<OverlayState, String> {
    let canonical = match std::fs::canonicalize(&path) {
        Ok(p) => p,
        // Nothing published yet, or the mod was uninstalled while its HUD was
        // open. Both are ordinary.
        Err(err) if err.kind() == std::io::ErrorKind::NotFound => return Ok(empty()),
        Err(err) => return Err(format!("failed to resolve overlay state path: {err}")),
    };
    if !allowed(&canonical) {
        return Err("refusing to read a path that is not a mod overlay state file".into());
    }

    let size = match std::fs::metadata(&canonical) {
        Ok(meta) => meta.len(),
        Err(err) if err.kind() == std::io::ErrorKind::NotFound => return Ok(empty()),
        Err(err) => return Err(format!("failed to stat overlay state: {err}")),
    };
    if size > MAX_BYTES {
        return Err(format!(
            "overlay state file is {size} bytes (max {MAX_BYTES})"
        ));
    }

    match std::fs::read(&canonical) {
        // The loader writes UTF-8, but a torn read mid-write can land on a
        // partial sequence. Lossy rather than an error: the frontend drops any
        // line it cannot parse and the next tick is a fraction of a second away.
        Ok(bytes) => Ok(OverlayState {
            exists: true,
            size,
            content: String::from_utf8_lossy(&bytes).to_string(),
        }),
        Err(err) if err.kind() == std::io::ErrorKind::NotFound => Ok(empty()),
        Err(err) => Err(format!("failed to read overlay state: {err}")),
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::path::PathBuf;

    #[test]
    fn accepts_a_mod_state_file() {
        assert!(allowed(&PathBuf::from("/games/rw/mods/damage-meter/.rsmm_state")));
    }

    #[test]
    fn rejects_another_name_in_the_right_place() {
        assert!(!allowed(&PathBuf::from("/games/rw/mods/dm/manifest.toml")));
        assert!(!allowed(&PathBuf::from("/games/rw/mods/dm/.rsmm_state.bak")));
    }

    #[test]
    fn rejects_the_right_name_in_another_place() {
        assert!(!allowed(&PathBuf::from("/home/user/.ssh/.rsmm_state")));
        // Directly under mods/ is one level too shallow: that is the loader's
        // own tree, not a mod's.
        assert!(!allowed(&PathBuf::from("/games/rw/mods/.rsmm_state")));
    }
}
