import { Command } from '@tauri-apps/plugin-shell';

/**
 * Invoke `rsmm json <args>` Python CLI via Tauri shell sidecar.
 * `json_bridge.py` always writes a single JSON value to stdout.
 */
export async function rsmm<T = unknown>(args: string[]): Promise<T> {
  const cmd = Command.create('rsmm', ['json', ...args]);
  const out = await cmd.execute();
  if (out.code !== 0) {
    throw new Error(`rsmm json ${args.join(' ')} exited ${out.code}: ${out.stderr || out.stdout}`);
  }
  const stdout = out.stdout.trim();
  if (!stdout) return null as T;
  return JSON.parse(stdout) as T;
}

export interface LocalMod {
  id: string;
  slug: string;
  name: string;
  version: string;
  author: string | null;
  summary: string | null;
  license: string | null;
  tags: string[];
  enabled: boolean;
  path: string;
}

export interface RunResult {
  ok: boolean;
  code: number;
  stdout: string;
  stderr: string;
}

export interface DoctorResult extends RunResult {
  checks: { status: 'OK' | 'WARN' | 'FAIL'; ok: boolean; label: string }[];
}

export const listLocalMods = () => rsmm<LocalMod[]>(['list']);
export const applyMods = (opts: { dryRun?: boolean; force?: boolean; noMerge?: boolean } = {}) => {
  const args = ['apply'];
  if (opts.dryRun) args.push('--dry-run');
  if (opts.force) args.push('--force');
  if (opts.noMerge) args.push('--no-merge');
  return rsmm<RunResult>(args);
};
export const restoreAll = () => rsmm<RunResult>(['restore-all']);
export const buildAll = () => rsmm<RunResult>(['build']);
export const doctor = () => rsmm<DoctorResult>(['doctor']);
