use serde::Deserialize;
use serde_json::Value;
use std::fs::OpenOptions;
use std::io::Write;
use std::time::{SystemTime, UNIX_EPOCH};
use tauri::{AppHandle, Manager};

const LOG_FILE_NAME: &str = "launcher.log";

#[derive(Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct LauncherLogEntry {
    pub level: String,
    pub message: String,
    pub context: Option<Value>,
}

fn log_path(app: &AppHandle) -> Result<std::path::PathBuf, String> {
    let dir = app
        .path()
        .app_data_dir()
        .map_err(|e| format!("failed to resolve app data dir: {e}"))?;
    Ok(dir.join(LOG_FILE_NAME))
}

fn now_secs() -> u64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|d| d.as_secs())
        .unwrap_or(0)
}

fn write_line(path: &std::path::Path, line: &str) -> Result<(), String> {
    if let Some(parent) = path.parent() {
        std::fs::create_dir_all(parent)
            .map_err(|e| format!("failed to create log dir: {e}"))?;
    }
    let mut file = OpenOptions::new()
        .create(true)
        .append(true)
        .open(path)
        .map_err(|e| format!("failed to open log file: {e}"))?;
    writeln!(file, "{line}").map_err(|e| format!("failed to write log entry: {e}"))
}

fn read_log(path: &std::path::Path) -> Result<String, String> {
    match std::fs::read_to_string(path) {
        Ok(content) => Ok(content),
        Err(err) if err.kind() == std::io::ErrorKind::NotFound => Ok(String::new()),
        Err(err) => Err(format!("failed to read log file: {err}")),
    }
}

#[tauri::command]
pub fn clear_launcher_log(app: AppHandle) -> Result<(), String> {
    let path = log_path(&app)?;
    if let Some(parent) = path.parent() {
        std::fs::create_dir_all(parent)
            .map_err(|e| format!("failed to create log dir: {e}"))?;
    }
    OpenOptions::new()
        .create(true)
        .write(true)
        .truncate(true)
        .open(path)
        .map_err(|e| format!("failed to clear log file: {e}"))?;
    Ok(())
}

/// Replace CR/LF with a visible escape so a single log entry can never split
/// into multiple lines. Without this, any caller (frontend or otherwise) that
/// includes a newline in `message` or `level` can forge fake log records that
/// look indistinguishable from real ones once the file is read back.
fn sanitize(raw: &str) -> String {
    raw.replace('\r', "\\r").replace('\n', "\\n")
}

#[tauri::command]
pub fn append_launcher_log(app: AppHandle, entry: LauncherLogEntry) -> Result<(), String> {
    let path = log_path(&app)?;
    let context = entry
        .context
        .map(|value| format!(" | context={}", sanitize(&value.to_string())))
        .unwrap_or_default();
    write_line(
        &path,
        &format!(
            "{} [{}] {}{}",
            now_secs(),
            sanitize(&entry.level.to_uppercase()),
            sanitize(&entry.message),
            context
        ),
    )
}

#[tauri::command]
pub fn read_launcher_log(app: AppHandle) -> Result<String, String> {
    let path = log_path(&app)?;
    read_log(&path)
}