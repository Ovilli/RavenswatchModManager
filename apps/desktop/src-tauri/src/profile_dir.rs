use std::path::{Path, PathBuf};
#[cfg(not(target_os = "linux"))]
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

    reveal(&app, &dir)
}

/// Hand a directory to the desktop's file manager.
///
/// On Linux this deliberately does NOT go through `tauri_plugin_opener`. Its
/// `open_path` spawns `xdg-open` DETACHED, inheriting our environment — and in
/// an AppImage that environment is rewritten by linuxdeploy's GTK hook
/// (`GTK_PATH`, `GIO_EXTRA_MODULES`, `GSETTINGS_SCHEMA_DIR`,
/// `GDK_PIXBUF_MODULE_FILE`, `LD_LIBRARY_PATH`, … all pointing inside the
/// AppDir). The file manager it launches then loads the AppDir's GTK modules
/// against the system's own libraries and dies on startup. Detached means no
/// exit status is ever read, so the button did nothing at all and reported
/// nothing — the exact symptom.
///
/// So: strip the AppDir variables, spawn, and WAIT for the launcher, whose
/// non-zero status becomes a real error message.
#[cfg(target_os = "linux")]
fn reveal(_app: &tauri::AppHandle, dir: &Path) -> Result<(), String> {
    // linuxdeploy's GTK hook plus the AppImage runtime's own two. Removing a
    // variable that was never set is a no-op, so this is safe outside an
    // AppImage — where it is also unnecessary, and where nothing is lost by
    // running the same code path.
    const APPDIR_VARS: [&str; 10] = [
        "LD_LIBRARY_PATH",
        "LD_PRELOAD",
        "GTK_DATA_PREFIX",
        "GTK_EXE_PREFIX",
        "GTK_PATH",
        "GTK_IM_MODULE_FILE",
        "GDK_PIXBUF_MODULE_FILE",
        "GSETTINGS_SCHEMA_DIR",
        "GIO_EXTRA_MODULES",
        "GDK_BACKEND",
    ];

    let mut last = String::new();
    for launcher in ["xdg-open", "gio", "nautilus", "dolphin", "thunar", "nemo"] {
        let mut cmd = std::process::Command::new(launcher);
        if launcher == "gio" {
            cmd.arg("open");
        }
        cmd.arg(dir);
        for var in APPDIR_VARS {
            cmd.env_remove(var);
        }
        // `XDG_DATA_DIRS` is prefixed rather than replaced by the hook, so the
        // system entries are still in there — leaving it alone keeps the
        // user's real .desktop database reachable.
        match cmd.status() {
            Ok(st) if st.success() => return Ok(()),
            Ok(st) => last = format!("{launcher} exited with {st}"),
            // Not installed — try the next one.
            Err(e) => last = format!("{launcher}: {e}"),
        }
    }
    Err(format!("could not open {}: {last}", dir.display()))
}

#[cfg(not(target_os = "linux"))]
fn reveal(app: &tauri::AppHandle, dir: &Path) -> Result<(), String> {
    app.opener()
        .open_path(path_str(dir)?, None::<&str>)
        .map_err(|e| format!("could not open {}: {e}", dir.display()))
}

/// Copy one profile's mods directory to another profile's.
///
/// A profile is not only a row in the frontend store: its mods live on disk
/// under `<mods_root>/profiles/<id>`, and every CLI call runs with
/// `RSMM_MODS_DIR` pointed at the ACTIVE profile's directory. So duplicating a
/// profile in the store alone produced a profile whose folder did not exist —
/// `rsmm json list` then returned nothing, and because that empty list is what
/// the library renders, BOTH the copy and the original looked empty until the
/// original was activated again and the list came back.
///
/// Copies, rather than hard-links: enabling or disabling a mod rewrites
/// `manifest.toml` inside the mod folder, and a link would push that edit into
/// the profile it was copied from.
#[tauri::command]
pub fn copy_profile_dir(
    mods_root: String,
    from_profile_id: String,
    to_profile_id: String,
) -> Result<(), String> {
    if !is_safe_profile_id(&from_profile_id) || !is_safe_profile_id(&to_profile_id) {
        return Err("invalid profile id".to_string());
    }
    if from_profile_id == to_profile_id {
        return Err("source and destination are the same profile".to_string());
    }
    let root = expand(&mods_root);
    if root.as_os_str().is_empty() {
        return Err("mods directory is not set".to_string());
    }
    let src = root.join("profiles").join(&from_profile_id);
    let dst = root.join("profiles").join(&to_profile_id);
    if !src.starts_with(&root) || !dst.starts_with(&root) {
        return Err("resolved path escaped the mods directory".to_string());
    }
    // Nothing to copy is not a failure: a profile that never had a mod
    // installed has no directory yet.
    if !src.is_dir() {
        return std::fs::create_dir_all(&dst)
            .map_err(|e| format!("could not create {}: {e}", dst.display()));
    }
    copy_tree(&src, &dst)
}

/// Recursive directory copy. Symlinks are followed as whatever they point at
/// (`fs::copy` reads through them) and never recreated, so a copied profile
/// cannot carry a link out of the mods tree.
fn copy_tree(src: &Path, dst: &Path) -> Result<(), String> {
    std::fs::create_dir_all(dst).map_err(|e| format!("could not create {}: {e}", dst.display()))?;
    let entries =
        std::fs::read_dir(src).map_err(|e| format!("could not read {}: {e}", src.display()))?;
    for entry in entries {
        let entry = entry.map_err(|e| format!("could not read {}: {e}", src.display()))?;
        let from = entry.path();
        let to = dst.join(entry.file_name());
        let meta = std::fs::metadata(&from)
            .map_err(|e| format!("could not stat {}: {e}", from.display()))?;
        if meta.is_dir() {
            copy_tree(&from, &to)?;
        } else {
            std::fs::copy(&from, &to)
                .map_err(|e| format!("could not copy {}: {e}", from.display()))?;
        }
    }
    Ok(())
}

#[cfg(not(target_os = "linux"))]
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

    #[test]
    fn copies_a_profile_tree_including_nested_files() {
        let base = std::env::temp_dir().join(format!("rsmm-copy-{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&base);
        let src = base.join("profiles").join("a");
        std::fs::create_dir_all(src.join("mod-one")).unwrap();
        std::fs::write(src.join("mod-one").join("manifest.toml"), b"enabled = true").unwrap();
        std::fs::write(src.join("top.txt"), b"x").unwrap();

        copy_profile_dir(
            base.to_string_lossy().to_string(),
            "a".to_string(),
            "b".to_string(),
        )
        .unwrap();

        let dst = base.join("profiles").join("b");
        assert_eq!(
            std::fs::read(dst.join("mod-one").join("manifest.toml")).unwrap(),
            b"enabled = true"
        );
        assert!(dst.join("top.txt").is_file());
        let _ = std::fs::remove_dir_all(&base);
    }

    #[test]
    fn refuses_an_unsafe_or_identical_profile_id() {
        let base = std::env::temp_dir().join("rsmm-copy-guard");
        assert!(copy_profile_dir(base.to_string_lossy().to_string(), "..".into(), "b".into()).is_err());
        assert!(copy_profile_dir(base.to_string_lossy().to_string(), "a".into(), "a".into()).is_err());
    }
}
