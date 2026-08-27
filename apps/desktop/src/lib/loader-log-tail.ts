import { invoke } from '@tauri-apps/api/core';

/**
 * Incremental follow for the loader log.
 *
 * Following used to mean spawning the bundled Python CLI once a second and
 * having it re-read and re-parse the whole file. That is a PyInstaller cold
 * start per poll — on Windows, hundreds of milliseconds plus an antivirus scan
 * of the unpacked bundle — to learn that the game had written one more line.
 *
 * The CLI still does discovery: it owns game-directory resolution and the
 * session slicing for the first page. After that the frontend holds a byte
 * offset and asks the Rust side (`read_loader_log_chunk`) for what is past it,
 * so a poll costs a seek and a read of exactly what the game appended.
 */

export interface LogChunk {
  exists: boolean;
  size: number;
  offset: number;
  content: string;
  /** The file shrank: it was rotated or truncated, and anything buffered
   *  belongs to a dead file. */
  reset: boolean;
  truncatedHead: boolean;
}

export function readLoaderLogChunk(
  path: string,
  offset: number | null,
  maxBytes?: number,
): Promise<LogChunk> {
  return invoke<LogChunk>('read_loader_log_chunk', {
    path,
    offset: offset ?? undefined,
    maxBytes,
  });
}

export interface TailState {
  /** Byte offset to resume from, or null before the first successful read. */
  offset: number | null;
  lines: string[];
  /** Set once the buffer has dropped lines off the front. */
  truncated: boolean;
}

export const emptyTail: TailState = { offset: null, lines: [], truncated: false };

/**
 * Fold one chunk into the buffered lines.
 *
 * A `reset` chunk REPLACES the buffer rather than extending it: the loader
 * rotates the log on every launch and again at its size cap, so appending
 * across a rotation would splice two unrelated runs into one apparently
 * continuous session — the exact confusion the per-run session tokens exist to
 * prevent.
 */
export function appendChunk(state: TailState, chunk: LogChunk, cap: number): TailState {
  if (!chunk.exists) return { ...emptyTail };
  const incoming = chunk.content ? chunk.content.replace(/\n$/, '').split('\n') : [];
  const base = chunk.reset ? [] : state.lines;
  const merged = incoming.length ? [...base, ...incoming] : base;
  const overflow = merged.length > cap;
  return {
    offset: chunk.offset,
    lines: overflow ? merged.slice(merged.length - cap) : merged,
    truncated: (chunk.reset ? false : state.truncated) || overflow || chunk.truncatedHead,
  };
}

const SESSION_MARK = '== SESSION ';

/**
 * Trim to the newest session unless every session was asked for.
 *
 * Applied at render over the whole buffer rather than once at load: the game
 * can start a new session while the screen is following, and a view still
 * showing the previous run's lines below the new banner reads as one long
 * confusing run.
 */
export function sessionSlice(lines: string[], allSessions: boolean): string[] {
  if (allSessions) return lines;
  for (let i = lines.length - 1; i >= 0; i--) {
    if (lines[i]?.includes(SESSION_MARK)) return lines.slice(i);
  }
  return lines;
}
