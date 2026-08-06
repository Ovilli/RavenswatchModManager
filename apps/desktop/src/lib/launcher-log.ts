import { invoke } from '@tauri-apps/api/core';

type LogContext = Record<string, unknown> | null | undefined;

async function safeInvoke(command: string, payload?: Record<string, unknown>): Promise<void> {
  try {
    await invoke(command, payload ?? {});
  } catch {
    // Logging must never block the launcher.
  }
}

export async function clearLauncherLog(): Promise<void> {
  await safeInvoke('clear_launcher_log');
}

export async function readLauncherLog(): Promise<string> {
  try {
    return await invoke<string>('read_launcher_log');
  } catch {
    return '';
  }
}

export type LogLevel = 'info' | 'warn' | 'error';

export interface LauncherLogEntry {
  /** Epoch milliseconds, or null when the line carried no parseable stamp. */
  at: number | null;
  level: LogLevel | 'other';
  message: string;
  /** The `context={…}` tail, if the writer attached one. */
  context: string | null;
  raw: string;
}

// `<unix_secs> [LEVEL] message[ | context={json}]` — written by
// src-tauri/src/launcher_log.rs, which escapes CR/LF so one entry is
// always exactly one line.
const LINE = /^(\d+)\s+\[([A-Z]+)\]\s*(.*)$/;
const CONTEXT = / \| context=(.*)$/;

/**
 * Parse the raw log file into rows.
 *
 * Beyond presentation this fixes a filtering bug: matching `[ERROR]` as a
 * substring of the whole line also matched entries that merely quote that
 * text in their message (a CLI transcript, say), so the level filter showed
 * lines of the wrong level.
 */
export function parseLauncherLog(raw: string): LauncherLogEntry[] {
  const entries: LauncherLogEntry[] = [];
  for (const line of raw.split('\n')) {
    const trimmed = line.trim();
    if (!trimmed) continue;
    const match = LINE.exec(trimmed);
    if (!match) {
      // Anything the writer didn't produce (hand-edited file, older format)
      // still deserves to be readable, just without structure.
      entries.push({ at: null, level: 'other', message: trimmed, context: null, raw: trimmed });
      continue;
    }
    const secs = match[1] ?? '';
    const level = (match[2] ?? '').toLowerCase();
    const rest = match[3] ?? '';
    const contextMatch = CONTEXT.exec(rest);
    entries.push({
      at: Number(secs) * 1000,
      level: level === 'info' || level === 'warn' || level === 'error' ? level : 'other',
      message: contextMatch ? rest.slice(0, contextMatch.index) : rest,
      context: contextMatch?.[1] ?? null,
      raw: trimmed,
    });
  }
  return entries;
}

export async function appendLauncherLog(
  level: 'info' | 'warn' | 'error',
  message: string,
  context?: LogContext,
): Promise<void> {
  await safeInvoke('append_launcher_log', {
    entry: {
      level,
      message,
      context: context ?? null,
    },
  });
}
