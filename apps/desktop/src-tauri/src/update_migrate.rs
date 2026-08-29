//! One-time escape from a Linux install the updater can never replace.
//!
//! Tauri's updater rewrites the running binary in place. On Linux that only
//! works for an AppImage the user owns: a `.deb` lands in `/usr/bin`, and an
//! AppImage parked in `/opt` (or an AppImageLauncher store) is root-owned. Both
//! cases dead-end in `update_env::detect()` as `writable: false`, and until now
//! the only way forward was "download the new version yourself" — i.e. a manual
//! reinstall on every single release.
//!
//! This module removes the treadmill. It downloads the update through the
//! updater plugin (so the minisign signature is verified with the very same
//! pubkey and code path as a normal update), writes it as an AppImage into
//! `~/Applications`, carries the system `.desktop` entry over to
//! `~/.local/share/applications` with its `Exec=` repointed, and relaunches
//! from the new copy. `$APPIMAGE` is then set for every later launch, so the
//! ordinary in-place updater takes over and never asks again.
//!
//! What it deliberately does NOT do: touch anything outside `$HOME`. The old
//! system copy stays exactly where the package manager put it — removing it is
//! the package manager's job, so we only report the command for it.

use serde::Serialize;

#[cfg(target_os = "linux")]
use std::io::Write;
#[cfg(target_os = "linux")]
use std::path::{Path, PathBuf};

/// Progress events emitted while the replacement AppImage downloads.
#[cfg_attr(not(target_os = "linux"), allow(dead_code))]
pub const MIGRATE_PROGRESS_EVENT: &str = "updater://migrate-progress";

#[derive(Serialize, Clone)]
// See the note in `update_env`: return payloads are not camel-cased for us.
#[serde(rename_all = "camelCase")]
pub struct MigrationResult {
    /// Where the self-updating AppImage now lives.
    pub path: String,
    /// The desktop entry we wrote, when one could be written.
    pub desktop_entry: Option<String>,
    /// Version that was installed.
    pub version: String,
    /// How to get rid of the copy this one supersedes, when it is a system
    /// package. `None` when nothing is left behind worth mentioning.
    pub leftover: Option<String>,
}

#[cfg(target_os = "linux")]
#[derive(Serialize, Clone)]
struct MigrateProgress {
    downloaded: u64,
    total: Option<u64>,
}

// ---------------------------------------------------------------------------
// Linux implementation
// ---------------------------------------------------------------------------

#[cfg(target_os = "linux")]
fn home() -> Result<PathBuf, String> {
    match std::env::var_os("HOME").map(PathBuf::from) {
        Some(p) if p.is_absolute() => Ok(p),
        _ => Err("HOME is not set to an absolute path, so there is nowhere to install to.".into()),
    }
}

/// The one destination this module ever writes an AppImage to.
///
/// Computed, never accepted from the caller: the relaunch command re-derives it
/// rather than taking a path from the frontend, so there is no way to point
/// either half at an arbitrary file.
#[cfg(target_os = "linux")]
pub(crate) fn appimage_dest() -> Result<PathBuf, String> {
    Ok(home()?
        .join("Applications")
        .join("RavenswatchModManager.AppImage"))
}

/// Is this an AppImage (type 2), rather than a tarball or an HTML error page?
///
/// The updater manifest is ours, but `install()` on Linux accepts several
/// payload shapes and we only know how to plant one. A payload that is not an
/// ELF carrying the AppImage type-2 marker gets rejected before it is written
/// somewhere the user will later double-click.
#[cfg(target_os = "linux")]
fn is_appimage(bytes: &[u8]) -> bool {
    bytes.len() > 16
        && &bytes[0..4] == b"\x7fELF"
        && bytes[8] == 0x41
        && bytes[9] == 0x49
        && bytes[10] == 0x02
}

/// Write `bytes` as an executable AppImage at [`appimage_dest`].
///
/// Staged under a PID-qualified name and renamed into place, so an interrupted
/// write can never leave a half-file where the desktop entry points.
#[cfg(target_os = "linux")]
fn install_appimage(bytes: &[u8]) -> Result<PathBuf, String> {
    use std::os::unix::fs::PermissionsExt;

    let dest = appimage_dest()?;
    let dir = dest
        .parent()
        .ok_or_else(|| "install destination has no parent directory".to_string())?;
    std::fs::create_dir_all(dir)
        .map_err(|e| format!("Could not create {}: {e}", dir.display()))?;

    let staging = dir.join(format!(".RavenswatchModManager.new-{}", std::process::id()));
    let write = (|| -> std::io::Result<()> {
        let mut f = std::fs::File::create(&staging)?;
        f.write_all(bytes)?;
        f.sync_all()
    })();
    if let Err(e) = write {
        let _ = std::fs::remove_file(&staging);
        return Err(format!("Could not write {}: {e}", staging.display()));
    }
    if let Err(e) = std::fs::set_permissions(&staging, std::fs::Permissions::from_mode(0o755)) {
        let _ = std::fs::remove_file(&staging);
        return Err(format!("Could not make {} executable: {e}", staging.display()));
    }
    if let Err(e) = std::fs::rename(&staging, &dest) {
        let _ = std::fs::remove_file(&staging);
        return Err(format!("Could not install to {}: {e}", dest.display()));
    }
    Ok(dest)
}

/// Escape a path for a `.desktop` `Exec=` value.
#[cfg(target_os = "linux")]
fn desktop_quote(path: &Path) -> String {
    let s = path.display().to_string();
    let mut out = String::with_capacity(s.len() + 2);
    out.push('"');
    for c in s.chars() {
        if c == '"' || c == '\\' || c == '$' || c == '`' {
            out.push('\\');
        }
        out.push(c);
    }
    out.push('"');
    out
}

/// The system `.desktop` entry for the copy we are replacing, as
/// `(file name, contents)`.
///
/// Matched by `Exec=` rather than by a guessed name: the bundler derives the
/// file name from the product name, which we would have to keep in sync by
/// hand. Reusing the SAME file name is what makes the migration invisible —
/// `~/.local/share/applications` shadows `/usr/share/applications`, so the
/// launcher icon the user already has starts opening the AppImage.
#[cfg(target_os = "linux")]
fn system_desktop_entry() -> Option<(String, String)> {
    let exe = std::env::current_exe().ok()?;
    let exe_name = exe.file_name()?.to_string_lossy().to_string();
    let exe_str = exe.display().to_string();

    for dir in ["/usr/share/applications", "/usr/local/share/applications"] {
        let Ok(entries) = std::fs::read_dir(dir) else {
            continue;
        };
        for entry in entries.flatten() {
            let path = entry.path();
            if path.extension().and_then(|e| e.to_str()) != Some("desktop") {
                continue;
            }
            let Ok(text) = std::fs::read_to_string(&path) else {
                continue;
            };
            let matches = text.lines().any(|line| {
                let Some(value) = line.strip_prefix("Exec=") else {
                    return false;
                };
                let target = value.trim().trim_matches('"');
                let first = target.split_whitespace().next().unwrap_or(target);
                first == exe_str || first.ends_with(&format!("/{exe_name}")) || first == exe_name
            });
            if matches {
                let name = path.file_name()?.to_string_lossy().to_string();
                return Some((name, text));
            }
        }
    }
    None
}

/// Copy a themed icon out of the system theme into the user's, so the launcher
/// entry keeps its icon after the system package is removed. Best effort.
#[cfg(target_os = "linux")]
fn copy_icon(icon: &str) {
    if icon.is_empty() || icon.starts_with('/') {
        return; // absolute path: nothing to re-theme, and not ours to copy.
    }
    let Ok(home) = home() else { return };

    let mut sources: Vec<(PathBuf, PathBuf)> = Vec::new();
    if let Ok(sizes) = std::fs::read_dir("/usr/share/icons/hicolor") {
        for size in sizes.flatten() {
            let apps = size.path().join("apps");
            let Ok(files) = std::fs::read_dir(&apps) else {
                continue;
            };
            for f in files.flatten() {
                let p = f.path();
                if p.file_stem().and_then(|s| s.to_str()) == Some(icon) {
                    let rel = size.file_name();
                    sources.push((
                        p.clone(),
                        home.join(".local/share/icons/hicolor")
                            .join(&rel)
                            .join("apps"),
                    ));
                }
            }
        }
    }
    for ext in ["png", "svg", "xpm"] {
        let p = PathBuf::from(format!("/usr/share/pixmaps/{icon}.{ext}"));
        if p.exists() {
            sources.push((p, home.join(".local/share/pixmaps")));
        }
    }

    for (src, dir) in sources {
        if std::fs::create_dir_all(&dir).is_err() {
            continue;
        }
        if let Some(name) = src.file_name() {
            let _ = std::fs::copy(&src, dir.join(name));
        }
    }
}

/// Repoint every `Exec=` in a desktop entry, drop `TryExec=`, and report the
/// `Icon=` name so it can be copied into the user's icon theme.
///
/// Split out from the I/O around it because this is the fiddly half: keeping
/// `Name`, `Categories`, `StartupWMClass` and the `x-scheme-handler/rsmm`
/// registration is the whole reason the system entry is reused rather than
/// synthesised, and `TryExec=` must go — it names the binary that is about to
/// be removed, and a stale one makes the launcher hide the entry entirely.
#[cfg(target_os = "linux")]
fn rewrite_exec(text: &str, exec_line: &str) -> (String, Option<String>) {
    let mut icon = None;
    let mut out = String::with_capacity(text.len());
    for line in text.lines() {
        if line.starts_with("TryExec=") {
            continue;
        }
        if let Some(v) = line.strip_prefix("Icon=") {
            if icon.is_none() {
                icon = Some(v.trim().to_string());
            }
        }
        if line.starts_with("Exec=") {
            out.push_str(exec_line);
        } else {
            out.push_str(line);
        }
        out.push('\n');
    }
    (out, icon)
}

/// Point a user-level desktop entry at the freshly installed AppImage.
///
/// When a system entry exists it is reused verbatim with only `Exec=` rewritten
/// (and `TryExec=` dropped, since it names the binary that is going away), so
/// the name, categories, `StartupWMClass` and the `x-scheme-handler/rsmm`
/// registration the OAuth deep link depends on all survive.
#[cfg(target_os = "linux")]
fn write_desktop_entry(appimage: &Path) -> Option<String> {
    let home = home().ok()?;
    let dir = home.join(".local/share/applications");
    std::fs::create_dir_all(&dir).ok()?;

    let exec = format!("Exec={} %U", desktop_quote(appimage));
    let (name, contents) = match system_desktop_entry() {
        Some((name, text)) => {
            let (out, icon) = rewrite_exec(&text, &exec);
            if let Some(icon) = icon {
                copy_icon(&icon);
            }
            (name, out)
        }
        None => (
            "ravenswatch-mod-manager.desktop".to_string(),
            format!(
                "[Desktop Entry]\n\
                 Type=Application\n\
                 Name=Ravenswatch Mod Manager\n\
                 Comment=Mod manager for Ravenswatch\n\
                 {exec}\n\
                 Terminal=false\n\
                 Categories=Utility;\n\
                 MimeType=x-scheme-handler/rsmm;\n"
            ),
        ),
    };

    let path = dir.join(&name);
    std::fs::write(&path, contents).ok()?;

    // Refreshes the scheme-handler cache so `rsmm://` OAuth callbacks route to
    // the AppImage instead of the binary that is about to disappear. Absent on
    // minimal systems; the entry itself is what matters.
    let _ = std::process::Command::new("update-desktop-database")
        .arg(&dir)
        .stdout(std::process::Stdio::null())
        .stderr(std::process::Stdio::null())
        .status();

    Some(path.display().to_string())
}

/// How the user gets rid of the copy we just superseded.
#[cfg(target_os = "linux")]
fn leftover_hint() -> Option<String> {
    let exe = std::env::current_exe().ok()?;
    let exe_str = exe.display().to_string();
    let system = ["/usr/", "/opt/", "/snap/", "/nix/store/", "/var/lib/flatpak/"]
        .iter()
        .any(|p| exe_str.starts_with(p));
    if !system {
        return None;
    }
    // `dpkg -S` names the package that owns the binary. Absent on non-Debian
    // systems, so the generic sentence is the fallback, never an error.
    let pkg = std::process::Command::new("dpkg")
        .arg("-S")
        .arg(&exe)
        .output()
        .ok()
        .filter(|o| o.status.success())
        .and_then(|o| {
            String::from_utf8_lossy(&o.stdout)
                .split(':')
                .next()
                .map(|s| s.trim().to_string())
                .filter(|s| !s.is_empty())
        });
    Some(match pkg {
        Some(pkg) => format!(
            "The old system-wide copy is still installed. Remove it with: sudo apt remove {pkg}"
        ),
        None => format!(
            "The old system-wide copy at {exe_str} is still installed — remove it with your package manager."
        ),
    })
}

#[cfg(target_os = "linux")]
async fn migrate(app: tauri::AppHandle) -> Result<MigrationResult, String> {
    use tauri::Emitter;
    use tauri_plugin_updater::UpdaterExt;

    let updater = app
        .updater_builder()
        // Migration is about WHERE the app is installed, not which version it
        // is: a user already on the latest build still wants off a `.deb` that
        // can never update itself. Without this, `check()` returns `None` for
        // them and the escape hatch is only reachable in the narrow window
        // where a newer release happens to exist.
        .version_comparator(|_current, _remote| true)
        .build()
        .map_err(|e| format!("Updater unavailable: {e}"))?;
    let update = updater
        .check()
        .await
        .map_err(|e| format!("Update check failed: {e}"))?
        .ok_or_else(|| {
            "The update feed doesn't list a Linux build to install.".to_string()
        })?;

    let version = update.version.clone();
    let emitter = app.clone();
    let mut downloaded: u64 = 0;
    // `download()` verifies the minisign signature against the configured
    // pubkey before it returns — the bytes below are as trusted as anything the
    // normal in-place updater installs.
    let bytes = update
        .download(
            move |chunk, total| {
                downloaded += chunk as u64;
                let _ = emitter.emit(
                    MIGRATE_PROGRESS_EVENT,
                    MigrateProgress { downloaded, total },
                );
            },
            || {},
        )
        .await
        .map_err(|e| format!("Download failed: {e}"))?;

    if !is_appimage(&bytes) {
        return Err(
            "The published Linux update is not an AppImage, so it can't be installed this way. \
             Download it from the releases page instead."
                .into(),
        );
    }

    let path = install_appimage(&bytes)?;
    let desktop_entry = write_desktop_entry(&path);

    Ok(MigrationResult {
        path: path.display().to_string(),
        desktop_entry,
        version,
        leftover: leftover_hint(),
    })
}

/// Start the migrated AppImage, shortly after we are gone.
///
/// The delay is load-bearing: `tauri-plugin-single-instance` is registered, so
/// a new process started while this one is still alive would hand its argv to
/// the dying instance and immediately exit. The caller quits right after this
/// returns, and the shell picks the AppImage up once we are out of the way.
///
/// `sh -c '… exec "$0"' <path>` passes the path as an argv element, so it is
/// never parsed by the shell — no quoting or injection to get wrong.
#[cfg(target_os = "linux")]
fn relaunch() -> Result<(), String> {
    let dest = appimage_dest()?;
    if !dest.is_file() {
        return Err(format!("{} is missing — nothing to relaunch.", dest.display()));
    }
    std::process::Command::new("sh")
        .arg("-c")
        .arg("sleep 2; exec \"$0\"")
        .arg(&dest)
        .stdin(std::process::Stdio::null())
        .stdout(std::process::Stdio::null())
        .stderr(std::process::Stdio::null())
        .spawn()
        .map_err(|e| format!("Could not start {}: {e}", dest.display()))?;
    Ok(())
}

// ---------------------------------------------------------------------------
// Non-Linux: nothing to migrate. Windows updates through the NSIS installer.
// ---------------------------------------------------------------------------

#[cfg(not(target_os = "linux"))]
async fn migrate(_app: tauri::AppHandle) -> Result<MigrationResult, String> {
    Err("AppImage migration only applies to Linux.".into())
}

#[cfg(not(target_os = "linux"))]
fn relaunch() -> Result<(), String> {
    Err("AppImage migration only applies to Linux.".into())
}

/// Install the pending update as a self-updating AppImage under `$HOME`.
#[tauri::command]
pub async fn migrate_to_appimage(app: tauri::AppHandle) -> Result<MigrationResult, String> {
    migrate(app).await
}

/// Queue a launch of the migrated AppImage; the caller quits immediately after.
#[tauri::command]
pub fn relaunch_migrated_appimage() -> Result<(), String> {
    relaunch()
}

#[cfg(all(test, target_os = "linux"))]
mod tests {
    use super::*;

    #[test]
    fn only_type2_appimages_are_installable() {
        let mut img = vec![0u8; 32];
        img[0..4].copy_from_slice(b"\x7fELF");
        img[8] = 0x41;
        img[9] = 0x49;
        img[10] = 0x02;
        assert!(is_appimage(&img));

        // A plain ELF (the .deb's own binary) must not be planted as an AppImage.
        let mut elf = img.clone();
        elf[8] = 0;
        elf[9] = 0;
        elf[10] = 0;
        assert!(!is_appimage(&elf));

        assert!(!is_appimage(b"<html>404</html>"));
        assert!(!is_appimage(b""));
    }

    #[test]
    fn exec_paths_are_quoted_and_escaped() {
        assert_eq!(
            desktop_quote(Path::new("/home/a b/App.AppImage")),
            "\"/home/a b/App.AppImage\""
        );
        assert_eq!(
            desktop_quote(Path::new("/home/we\"ird/$HOME/App")),
            "\"/home/we\\\"ird/\\$HOME/App\""
        );
    }

    #[test]
    fn desktop_entry_keeps_everything_but_the_exec_path() {
        let system = "[Desktop Entry]\n\
                      Type=Application\n\
                      Name=Ravenswatch Mod Manager\n\
                      Exec=/usr/bin/rsmm-desktop %U\n\
                      TryExec=/usr/bin/rsmm-desktop\n\
                      Icon=ravenswatch-mod-manager\n\
                      Categories=Utility;\n\
                      MimeType=x-scheme-handler/rsmm;\n\
                      StartupWMClass=rsmm-desktop\n";
        let (out, icon) = rewrite_exec(system, "Exec=\"/home/u/Applications/x.AppImage\" %U");

        assert!(out.contains("Exec=\"/home/u/Applications/x.AppImage\" %U\n"));
        // The binary is about to be removed: a surviving TryExec makes the
        // launcher hide the entry outright.
        assert!(!out.contains("TryExec"));
        assert!(!out.contains("/usr/bin/rsmm-desktop"));
        // Everything the app depends on has to survive — losing the scheme
        // handler silently breaks the OAuth deep link.
        assert!(out.contains("MimeType=x-scheme-handler/rsmm;"));
        assert!(out.contains("StartupWMClass=rsmm-desktop"));
        assert!(out.contains("Name=Ravenswatch Mod Manager"));
        assert_eq!(icon.as_deref(), Some("ravenswatch-mod-manager"));
    }

    #[test]
    fn destination_is_always_under_home() {
        // One test, not two: these mutate the process environment and cargo
        // runs tests on threads, so splitting them makes them race.
        let restore = std::env::var_os("HOME");
        std::env::set_var("HOME", "/home/tester");
        assert_eq!(
            appimage_dest().unwrap(),
            PathBuf::from("/home/tester/Applications/RavenswatchModManager.AppImage")
        );
        // A relative HOME is refused rather than resolved against the cwd.
        std::env::set_var("HOME", "relative/path");
        assert!(appimage_dest().is_err());
        match restore {
            Some(v) => std::env::set_var("HOME", v),
            None => std::env::remove_var("HOME"),
        }
    }
}
