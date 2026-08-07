//! Pre-flight for the in-place updater.
//!
//! The Tauri updater replaces the running binary on disk. On Linux that means
//! it rewrites the `.AppImage` file pointed at by `$APPIMAGE` (and, to do that,
//! it first creates a scratch directory next to it and renames the old file
//! into it — so the *parent directory* must be writable too, not just the
//! file). When either check fails the plugin surfaces the raw
//! `Permission denied (os error 13)` with no hint about what to do, which is
//! what users hit when the AppImage lives in a root-owned directory
//! (`/opt`, `/usr/local/bin`, an AppImageLauncher/Gearlever store) — or when
//! the app was installed from the `.deb`, in which case `$APPIMAGE` is unset,
//! the "AppImage" the updater tries to rewrite is `/usr/bin/<app>`, and no
//! amount of retrying will ever succeed.
//!
//! This module reports that state up-front so the UI can point at the
//! downloads page instead of failing with an errno.

use serde::Serialize;
use std::path::{Path, PathBuf};

#[derive(Serialize)]
pub struct UpdateTarget {
    /// `appimage` | `system-package` | `portable` | `unsupported-check`.
    pub kind: String,
    /// The file the updater would overwrite, when known.
    pub path: Option<String>,
    /// False when an in-place update is guaranteed to fail with EACCES.
    pub writable: bool,
    /// Human-readable explanation, empty when `writable` is true.
    pub reason: String,
}

impl UpdateTarget {
    fn ok(kind: &str, path: Option<PathBuf>) -> Self {
        Self {
            kind: kind.to_string(),
            path: path.map(|p| p.display().to_string()),
            writable: true,
            reason: String::new(),
        }
    }

    fn blocked(kind: &str, path: Option<PathBuf>, reason: impl Into<String>) -> Self {
        Self {
            kind: kind.to_string(),
            path: path.map(|p| p.display().to_string()),
            writable: false,
            reason: reason.into(),
        }
    }
}

/// Can we create (and remove) a file in `dir`?
///
/// `metadata().permissions().readonly()` is not enough here: it reports the
/// mode bits, which say nothing about the *effective* rights of this uid once
/// ownership, ACLs or a read-only mount are involved. Probing is the only
/// honest answer.
#[cfg(target_os = "linux")]
fn dir_writable(dir: &Path) -> bool {
    let probe = dir.join(format!(".rsmm-update-probe-{}", std::process::id()));
    match std::fs::File::create(&probe) {
        Ok(_) => {
            let _ = std::fs::remove_file(&probe);
            true
        }
        Err(_) => false,
    }
}

#[cfg(target_os = "linux")]
fn file_writable(path: &Path) -> bool {
    std::fs::OpenOptions::new().write(true).open(path).is_ok()
}

/// Directories whose contents are owned by the package manager. An app running
/// from here was installed system-wide (`.deb`/`.rpm`/distro package) and can
/// never be updated in place by a user-owned process.
#[cfg(target_os = "linux")]
const SYSTEM_PREFIXES: &[&str] = &["/usr/", "/opt/", "/snap/", "/nix/store/", "/var/lib/flatpak/"];

#[cfg(target_os = "linux")]
fn detect() -> UpdateTarget {
    // The updater uses `$APPIMAGE` (via `app.env().appimage`) as the path to
    // overwrite. When it is set we are running from an AppImage and that file
    // is the real target; `current_exe()` would point inside the read-only
    // squashfs mount instead.
    let appimage = std::env::var_os("APPIMAGE").map(PathBuf::from);
    let exe = std::env::current_exe().ok();

    if let Some(path) = appimage {
        if !path.exists() {
            return UpdateTarget::blocked(
                "appimage",
                Some(path.clone()),
                format!(
                    "The AppImage this app was launched from ({}) no longer exists, so it can't be replaced.",
                    path.display()
                ),
            );
        }
        let parent = path.parent().unwrap_or(Path::new("/")).to_path_buf();
        if !dir_writable(&parent) || !file_writable(&path) {
            return UpdateTarget::blocked(
                "appimage",
                Some(path.clone()),
                format!(
                    "No write access to {} — the updater has to replace the AppImage in place. \
                     Move it somewhere you own (for example ~/Applications) and relaunch, or \
                     download the new version manually.",
                    parent.display()
                ),
            );
        }
        return UpdateTarget::ok("appimage", Some(path));
    }

    // No $APPIMAGE: either a system package or a loose binary.
    let Some(exe) = exe else {
        return UpdateTarget::ok("unsupported-check", None);
    };
    let exe_str = exe.display().to_string();
    let system = SYSTEM_PREFIXES.iter().any(|p| exe_str.starts_with(p));
    if system {
        return UpdateTarget::blocked(
            "system-package",
            Some(exe),
            "This copy was installed system-wide (.deb or distro package), so the in-app \
             updater can't replace it. Install the new version from the downloads page, \
             or use your package manager.",
        );
    }

    let parent = exe.parent().unwrap_or(Path::new("/")).to_path_buf();
    if !dir_writable(&parent) || !file_writable(&exe) {
        return UpdateTarget::blocked(
            "portable",
            Some(exe),
            format!(
                "No write access to {} — the updater has to replace the app binary in place. \
                 Download the new version manually instead.",
                parent.display()
            ),
        );
    }
    UpdateTarget::ok("portable", Some(exe))
}

#[cfg(not(target_os = "linux"))]
fn detect() -> UpdateTarget {
    // Windows runs the NSIS installer, which elevates on its own; macOS isn't
    // shipped. Nothing to pre-flight.
    UpdateTarget::ok("unsupported-check", std::env::current_exe().ok())
}

/// Report whether the in-place updater can write over this install.
#[tauri::command]
pub fn update_install_target() -> UpdateTarget {
    detect()
}

#[cfg(all(test, target_os = "linux"))]
mod tests {
    use super::*;

    #[test]
    fn probes_real_write_access_not_mode_bits() {
        assert!(dir_writable(&std::env::temp_dir()));
        // /proc is a kernel filesystem: no uid can create entries in its root.
        assert!(!dir_writable(Path::new("/proc")));
    }

    #[test]
    fn system_install_is_reported_unwritable() {
        for prefix in SYSTEM_PREFIXES {
            assert!(prefix.starts_with('/') && prefix.ends_with('/'), "{prefix}");
        }
        // A binary under /usr/bin must never be treated as updatable in place.
        assert!(SYSTEM_PREFIXES
            .iter()
            .any(|p| "/usr/bin/rsmm-desktop".starts_with(p)));
    }

    #[test]
    fn detect_never_panics() {
        let t = detect();
        assert!(!t.kind.is_empty());
        assert_eq!(t.writable, t.reason.is_empty());
    }
}
