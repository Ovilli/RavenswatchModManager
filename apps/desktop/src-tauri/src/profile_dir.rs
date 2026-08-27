use std::path::{Path, PathBuf};
use tauri_plugin_opener::OpenerExt;

/// A profile id is a single path segment under `<mods_root>/profiles/`.
/// Anything else — `..`, a separator, a NUL, a drive letter — would let the
/// caller walk out of the mods tree, so it is rejected here as well as in the
/// frontend store (see `lib/untrusted-state.ts`).
fn is_safe_profile_id(id: &str) -> bool {
    !id.is_empty()
        && id.len() <= 64
        && id
            .chars()
            .all(|c| c.is_ascii_alphanumeric() || c == '_' || c == '-')
}

/// Expand a directory setting the way a user expects when they type it.
///
/// The old frontend path handled a leading `~` only and passed the result
/// straight to `mkdir`. `Command` does not run a shell, so the Windows default
/// (`%APPDATA%\rsmm\mods`) was never expanded and "open folder" created a
/// literal directory named `%APPDATA%` next to the app. Both forms are handled
/// here, on the side that owns the filesystem.
fn expand(raw: &str) -> PathBuf {
    let mut out = raw.trim().to_string();

    if out == "~" || out.starts_with("~/") || out.starts_with("~\\") {
        if let Some(home) = dirs_home() {
            out = format!("{}{}", home.to_string_lossy(), &out[1..]);
        }
    }

    // %VAR% (Windows) — resolved against the real process environment; an
    // unset variable is left as written rather than collapsing to an empty
    // segment, which would silently retarget the path at the filesystem root.
    while let Some(start) = out.find('%') {
        let Some(rel_end) = out[start + 1..].find('%') else {
            break;
        };
        let end = start + 1 + rel_end;
        let name = &out[start + 1..end];
        let Ok(value) = std::env::var(name) else {
            break;
        };
        out = format!("{}{}{}", &out[..start], value, &out[end + 1..]);
    }

    PathBuf::from(out)
}

fn dirs_home() -> Option<PathBuf> {
    std::env::var_os("HOME")
        .or_else(|| std::env::var_os("USERPROFILE"))
        .map(PathBuf::from)
}

/// Create a profile's mods directory if needed and reveal it in the file
/// manager.
///
/// This replaces two over-broad shell grants that used to sit in the default
/// capability: `mkdir` with `args: true` (arbitrary directory creation) and
/// `shell:allow-open` scoped to `file:///**` (asking the OS to open ANY path,
/// which on Windows means handing an arbitrary file to its registered handler).
/// Neither is needed once the one operation that wanted them lives here, where
/// the profile id is validated and the path is built rather than accepted.
#[tauri::command]
pub fn open_profile_dir(
    app: tauri::AppHandle,
    mods_root: String,
    profile_id: String,
) -> Result<(), String> {
    if !is_safe_profile_id(&profile_id) {
        return Err("invalid profile id".to_string());
    }
    let root = expand(&mods_root);
    if root.as_os_str().is_empty() {
        return Err("mods directory is not set".to_string());
    }

    let dir: PathBuf = root.join("profiles").join(&profile_id);

    // The id is already known to be a single safe segment, so `join` cannot
    // have escaped `root`; assert it anyway, because this is the last point
    // before a real mkdir.
    if !dir.starts_with(&root) {
        return Err("resolved path escaped the mods directory".to_string());
    }

    std::fs::create_dir_all(&dir).map_err(|e| format!("could not create {}: {e}", dir.display()))?;

    app.opener()
        .open_path(path_str(&dir)?, None::<&str>)
        .map_err(|e| format!("could not open {}: {e}", dir.display()))
}

fn path_str(p: &Path) -> Result<String, String> {
    p.to_str()
        .map(|s| s.to_string())
        .ok_or_else(|| "path is not valid UTF-8".to_string())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn accepts_ordinary_ids() {
        for id in ["default", "chaos", "a-b_C9", &"x".repeat(64)] {
            assert!(is_safe_profile_id(id), "{id} should be accepted");
        }
    }

    #[test]
    fn rejects_traversal_and_separators() {
        for id in [
            "",
            "..",
            "../..",
            "a/b",
            "a\\b",
            "a\0b",
            "C:",
            ".",
            "with space",
            &"x".repeat(65),
        ] {
            assert!(!is_safe_profile_id(id), "{id:?} should be rejected");
        }
    }

    #[test]
    fn expands_a_leading_tilde() {
        std::env::set_var("HOME", "/home/tester");
        assert_eq!(expand("~/mods"), PathBuf::from("/home/tester/mods"));
        // A tilde anywhere else is a legal filename character, not a home ref.
        assert_eq!(expand("/srv/a~b"), PathBuf::from("/srv/a~b"));
    }

    #[test]
    fn expands_percent_variables() {
        std::env::set_var("RSMM_TEST_APPDATA", "/tmp/appdata");
        assert_eq!(
            expand("%RSMM_TEST_APPDATA%/rsmm/mods"),
            PathBuf::from("/tmp/appdata/rsmm/mods")
        );
    }

    #[test]
    fn leaves_an_unset_variable_alone_rather_than_emptying_it() {
        let raw = "%RSMM_DEFINITELY_UNSET_VAR%/rsmm/mods";
        assert_eq!(expand(raw), PathBuf::from(raw));
    }
}
