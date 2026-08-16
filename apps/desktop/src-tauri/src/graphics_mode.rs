//! Software-rendering escape hatch for a broken display driver.
//!
//! A user's machine blue-screened with `VIDEO_SCHEDULER_INTERNAL_ERROR`
//! (bug check 0x119) while a mod page was open — a kernel fault raised by
//! dxgkrnl when the display driver violates the GPU scheduling contract. An
//! app cannot cause that directly; it can only submit GPU work the driver
//! then mishandles (WebView2 compositing, a video player iframe). Fixing the
//! driver is the user's job, but shipping no way to stop touching the GPU
//! leaves them with "the app BSODs my PC" and nothing to try.
//!
//! So: an opt-in flag that makes the webview render in software. It must be
//! applied BEFORE the webview is created — WebView2 reads
//! `WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS` from the environment at startup —
//! which is why this runs in `main()` and is backed by a FILE rather than the
//! frontend's settings store: nothing in the webview exists yet to ask.
//!
//! Linux already forces software rendering unconditionally in `main.rs`
//! (webkitgtk + DMABUF is its own minefield), so this only changes Windows.

use std::path::PathBuf;

/// Marker file: present = render in software.
const FLAG_FILE: &str = "disable-gpu";
/// Must match `identifier` in tauri.conf.json — the same directory Tauri's
/// own `app_data_dir()` resolves to, so the file sits with the app's data
/// rather than in a second, surprising location.
const APP_IDENTIFIER: &str = "dev.rsmm.desktop";

/// Where the marker lives. Resolved without an `AppHandle`, because the flag
/// is read before Tauri exists.
pub fn flag_path() -> Option<PathBuf> {
    #[cfg(target_os = "windows")]
    let base = std::env::var_os("APPDATA").map(PathBuf::from);
    #[cfg(not(target_os = "windows"))]
    let base = std::env::var_os("XDG_CONFIG_HOME")
        .map(PathBuf::from)
        .or_else(|| std::env::var_os("HOME").map(|h| PathBuf::from(h).join(".config")));
    Some(base?.join(APP_IDENTIFIER).join(FLAG_FILE))
}

/// True when the user asked for software rendering (or set the env override).
pub fn is_disabled() -> bool {
    if matches!(std::env::var("RSMM_DISABLE_GPU").as_deref(), Ok("1") | Ok("true")) {
        return true;
    }
    flag_path().map(|p| p.exists()).unwrap_or(false)
}

/// Apply the flag to the environment. Call from `main()` BEFORE the Tauri
/// builder runs; after the webview is created it has no effect.
pub fn apply() {
    if !is_disabled() {
        return;
    }
    #[cfg(target_os = "windows")]
    {
        // Append rather than replace: a user may already be passing their own
        // WebView2 arguments, and silently dropping them would be its own bug.
        let mut args = std::env::var("WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS").unwrap_or_default();
        for flag in ["--disable-gpu", "--disable-gpu-compositing", "--disable-features=UseSkiaRenderer"] {
            if !args.contains(flag) {
                if !args.is_empty() {
                    args.push(' ');
                }
                args.push_str(flag);
            }
        }
        std::env::set_var("WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS", args);
    }
    #[cfg(not(target_os = "windows"))]
    {
        // main.rs already sets these on Linux; keep the behaviour identical
        // when the flag is set on any other platform.
        std::env::set_var("WEBKIT_DISABLE_COMPOSITING_MODE", "1");
        std::env::set_var("LIBGL_ALWAYS_SOFTWARE", "1");
    }
}

/// Read the current setting for the Settings screen.
#[tauri::command]
pub fn gpu_acceleration_disabled() -> bool {
    is_disabled()
}

/// Persist the setting. Takes effect on the next launch — the webview's
/// renderer is chosen at process start and cannot be swapped underneath a
/// live window, so the UI must say "restart required" rather than pretend.
#[tauri::command]
pub fn set_gpu_acceleration_disabled(disabled: bool) -> Result<bool, String> {
    let path = flag_path().ok_or_else(|| "could not resolve the app data directory".to_string())?;
    if disabled {
        if let Some(parent) = path.parent() {
            std::fs::create_dir_all(parent)
                .map_err(|e| format!("failed to create {}: {e}", parent.display()))?;
        }
        std::fs::write(&path, b"1")
            .map_err(|e| format!("failed to write {}: {e}", path.display()))?;
    } else if path.exists() {
        std::fs::remove_file(&path)
            .map_err(|e| format!("failed to remove {}: {e}", path.display()))?;
    }
    Ok(disabled)
}
