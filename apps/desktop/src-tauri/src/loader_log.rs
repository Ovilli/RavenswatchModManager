use serde::Serialize;
use std::fs::File;
use std::io::{Read, Seek, SeekFrom};
use std::path::Path;

/// Incremental reader for the in-game loader log.
///
/// The Log screen used to poll by spawning the bundled Python CLI once a
/// second. That is a PyInstaller cold start — hundreds of milliseconds on
/// Windows, plus an antivirus scan of the unpacked bundle — repeated for as
/// long as the tab is open, to re-read a file that had usually grown by one
/// line. Discovery still goes through the CLI (it owns game-directory
/// resolution); only the hot loop moved here, where a tail is a seek and a
/// read.
///
/// The frontend keeps a byte offset and asks for what is past it, so the cost
/// of a poll is proportional to what the game actually wrote rather than to
/// the size of the log.

/// Largest window handed back in one call. A poll returns a line or two; this
/// only bounds the first (offset-less) read and the recovery path after a
/// rotation, where the whole file is in play.
const MAX_WINDOW: u64 = 4 * 1024 * 1024;

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
pub struct LogChunk {
    pub exists: bool,
    /// Size of the file at the moment it was read.
    pub size: u64,
    /// Byte offset to pass to the next call. Always a line boundary.
    pub offset: u64,
    /// Complete lines only — a trailing partial line is left for next time.
    pub content: String,
    /// The file shrank since the caller's offset, so it was rotated or
    /// truncated: whatever the caller has buffered belongs to a dead file and
    /// must be discarded rather than appended to.
    pub reset: bool,
    /// The window skipped bytes before `offset`, so the first line the caller
    /// receives is not the first line of the file.
    pub truncated_head: bool,
}

/// Only the loader's own logs are readable through this command.
///
/// The frontend is our own bundle and remote content cannot reach the IPC, but
/// "read any file the app's user can read, return it to the webview" is a
/// capability worth not having at all. Checked on the CANONICAL path so a
/// `..` segment or a symlink is resolved before the name and parent are
/// judged.
fn allowed(path: &Path) -> bool {
    let name = path.file_name().and_then(|s| s.to_str()).unwrap_or("");
    let parent = path
        .parent()
        .and_then(|p| p.file_name())
        .and_then(|s| s.to_str())
        .unwrap_or("");
    match parent {
        // The live log and the one-run-back alias, written by loader.cpp.
        "mods" => name == "_log.txt" || name == "_log.prev.txt",
        // Archived runs: <game>/rsmm/logs/<stamp>_<session>.log
        "logs" => name.ends_with(".log"),
        _ => false,
    }
}

fn empty(reset: bool) -> LogChunk {
    LogChunk {
        exists: false,
        size: 0,
        offset: 0,
        content: String::new(),
        reset,
        truncated_head: false,
    }
}

#[tauri::command]
pub fn read_loader_log_chunk(
    path: String,
    offset: Option<u64>,
    max_bytes: Option<u64>,
) -> Result<LogChunk, String> {
    // A log that does not exist yet is the normal state on a fresh install —
    // the loader writes one only after the game has run once. Not an error.
    let canonical = match std::fs::canonicalize(&path) {
        Ok(p) => p,
        Err(err) if err.kind() == std::io::ErrorKind::NotFound => return Ok(empty(false)),
        Err(err) => return Err(format!("failed to resolve log path: {err}")),
    };
    if !allowed(&canonical) {
        return Err("refusing to read a path that is not a loader log".into());
    }

    let mut file = match File::open(&canonical) {
        Ok(f) => f,
        Err(err) if err.kind() == std::io::ErrorKind::NotFound => return Ok(empty(false)),
        Err(err) => return Err(format!("failed to open log: {err}")),
    };
    let size = file
        .metadata()
        .map_err(|e| format!("failed to stat log: {e}"))?
        .len();
    let window = max_bytes.unwrap_or(MAX_WINDOW).min(MAX_WINDOW).max(1);

    // Where the caller left off, and whether that offset still means anything.
    // The loader rotates the log at 8 MB mid-session and again on every
    // launch, so "my offset is past the end" is routine, not a bug.
    let requested = offset.unwrap_or(u64::MAX);
    let reset = offset.is_some() && requested > size;
    let mut start = if offset.is_none() || reset {
        size.saturating_sub(window)
    } else {
        requested
    };
    // Repositioned to the tail, or asked for more than one window's worth.
    let mut truncated_head = start > 0 && (offset.is_none() || reset);
    if size - start > window {
        start = size - window;
        truncated_head = true;
    }
    if start >= size {
        return Ok(LogChunk {
            exists: true,
            size,
            offset: size,
            content: String::new(),
            reset,
            truncated_head: false,
        });
    }

    file.seek(SeekFrom::Start(start))
        .map_err(|e| format!("failed to seek log: {e}"))?;
    let mut buf = vec![0u8; (size - start) as usize];
    let read = file
        .read(&mut buf)
        .map_err(|e| format!("failed to read log: {e}"))?;
    buf.truncate(read);

    // Cut at the last newline. This is what makes the offset resumable: it is
    // always a line boundary, so the next call never receives half a line, and
    // (because a newline is also a UTF-8 boundary) lossy decoding can never
    // mangle a character that merely straddles two polls.
    let end = match buf.iter().rposition(|b| *b == b'\n') {
        Some(i) => i + 1,
        // No complete line yet. Hold the offset and wait rather than emitting
        // a fragment the caller would render as a line of its own.
        None => return Ok(LogChunk { exists: true, size, offset: start, content: String::new(), reset, truncated_head }),
    };
    let mut begin = 0usize;
    if truncated_head {
        // We landed mid-line; drop the fragment before the first newline.
        if let Some(i) = buf[..end].iter().position(|b| *b == b'\n') {
            begin = i + 1;
        }
    }

    Ok(LogChunk {
        exists: true,
        size,
        offset: start + end as u64,
        content: String::from_utf8_lossy(&buf[begin..end]).into_owned(),
        reset,
        truncated_head,
    })
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::io::Write;

    /// A scratch `<tmp>/<unique>/mods/_log.txt`, because `allowed()` judges the
    /// parent directory name and a bare temp file would be refused.
    fn scratch(name: &str) -> std::path::PathBuf {
        let dir = std::env::temp_dir()
            .join(format!("rsmm-loader-log-{}-{:?}", name, std::time::SystemTime::now()))
            .join("mods");
        std::fs::create_dir_all(&dir).unwrap();
        dir.join("_log.txt")
    }

    fn write(path: &Path, body: &str) {
        let mut f = std::fs::File::create(path).unwrap();
        f.write_all(body.as_bytes()).unwrap();
    }

    fn append(path: &Path, body: &str) {
        let mut f = std::fs::OpenOptions::new().append(true).open(path).unwrap();
        f.write_all(body.as_bytes()).unwrap();
    }

    #[test]
    fn refuses_paths_that_are_not_loader_logs() {
        assert!(allowed(Path::new("/game/mods/_log.txt")));
        assert!(allowed(Path::new("/game/mods/_log.prev.txt")));
        assert!(allowed(Path::new("/game/rsmm/logs/2026-08-27_ab12.log")));
        assert!(!allowed(Path::new("/etc/passwd")));
        assert!(!allowed(Path::new("/game/mods/manifest.toml")));
        // A save file next to the logs is still not a log.
        assert!(!allowed(Path::new("/game/logs/Profile_1.ob")));
    }

    #[test]
    fn missing_file_reads_as_absent_not_as_an_error() {
        let chunk = read_loader_log_chunk("/nope/mods/_log.txt".into(), None, None).unwrap();
        assert!(!chunk.exists);
        assert_eq!(chunk.content, "");
    }

    #[test]
    fn resumes_from_the_offset_and_returns_only_new_lines() {
        let p = scratch("resume");
        write(&p, "one\ntwo\n");
        let first =
            read_loader_log_chunk(p.to_string_lossy().into(), None, None).unwrap();
        assert_eq!(first.content, "one\ntwo\n");
        assert_eq!(first.offset, 8);

        append(&p, "three\n");
        let second =
            read_loader_log_chunk(p.to_string_lossy().into(), Some(first.offset), None).unwrap();
        assert_eq!(second.content, "three\n");
        assert!(!second.reset);
    }

    #[test]
    fn holds_a_partial_line_until_the_writer_finishes_it() {
        let p = scratch("partial");
        write(&p, "done\n");
        let first = read_loader_log_chunk(p.to_string_lossy().into(), None, None).unwrap();
        append(&p, "half");
        let second =
            read_loader_log_chunk(p.to_string_lossy().into(), Some(first.offset), None).unwrap();
        // The fragment is not emitted, and the offset does not advance past it.
        assert_eq!(second.content, "");
        assert_eq!(second.offset, first.offset);
        append(&p, "-rest\n");
        let third =
            read_loader_log_chunk(p.to_string_lossy().into(), Some(second.offset), None).unwrap();
        assert_eq!(third.content, "half-rest\n");
    }

    #[test]
    fn flags_a_rotation_so_the_caller_drops_its_stale_buffer() {
        let p = scratch("rotate");
        write(&p, "old line one\nold line two\n");
        let first = read_loader_log_chunk(p.to_string_lossy().into(), None, None).unwrap();
        // The loader rotates by replacing the file; the new one is shorter.
        write(&p, "new\n");
        let second =
            read_loader_log_chunk(p.to_string_lossy().into(), Some(first.offset), None).unwrap();
        assert!(second.reset);
        assert_eq!(second.content, "new\n");
    }

    #[test]
    fn a_windowed_read_starts_at_a_line_boundary() {
        let p = scratch("window");
        write(&p, "aaaa\nbbbb\ncccc\n");
        // Small enough that the window lands inside the first line.
        let chunk = read_loader_log_chunk(p.to_string_lossy().into(), None, Some(12)).unwrap();
        assert!(chunk.truncated_head);
        // Never a half line: the leading fragment is dropped.
        assert!(chunk.content.starts_with("bbbb\n") || chunk.content.starts_with("cccc\n"));
        assert_eq!(chunk.offset, chunk.size);
    }
}
