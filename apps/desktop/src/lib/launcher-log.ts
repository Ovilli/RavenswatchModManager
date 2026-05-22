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
