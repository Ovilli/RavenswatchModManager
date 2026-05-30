import { invoke } from '@tauri-apps/api/core';
import { type Child, Command } from '@tauri-apps/plugin-shell';
import { useApp } from '../store';
import { getPlatform } from './platform';

interface ExecResult {
  code: number | null;
  stdout: string;
  stderr: string;
}

class RsmmError extends Error {
  constructor(
    message: string,
    public readonly args: string[],
  ) {
    super(message);
    this.name = 'RsmmError';
  }
}

class RsmmCliMissingError extends RsmmError {
  constructor(args: string[]) {
    super(CLI_MISSING_MESSAGE, args);
    this.name = 'RsmmCliMissingError';
  }
}

class RsmmExitError extends RsmmError {
  constructor(
    args: string[],
    public readonly code: number | null,
    public readonly stdout: string,
    public readonly stderr: string,
  ) {
    super(
      `rsmm ${args.join(' ')} failed (exit ${code ?? 'signal'}): ${
        stderr.trim() || stdout.trim() || '<no output>'
      }`,
      args,
    );
    this.name = 'RsmmExitError';
  }
}

class RsmmParseError extends RsmmError {
  constructor(
    args: string[],
    public readonly raw: string,
    cause: unknown,
  ) {
    const preview = raw.length > 200 ? `${raw.slice(0, 200)}…` : raw;
    super(`rsmm ${args.join(' ')} returned invalid JSON: ${preview}`, args);
    this.name = 'RsmmParseError';
    (this as Error).cause = cause;
  }
}

class RsmmTimeoutError extends RsmmError {
  constructor(
    args: string[],
    public readonly timeoutMs: number,
  ) {
    super(`rsmm ${args.join(' ')} timed out after ${timeoutMs}ms`, args);
    this.name = 'RsmmTimeoutError';
  }
}

class RsmmAbortError extends RsmmError {
  constructor(args: string[]) {
    super(`rsmm ${args.join(' ')} aborted`, args);
    // Match the DOMException shape React Query / fetch use to detect
    // abort, so an aborted query is cancelled instead of erroring.
    this.name = 'AbortError';
  }
}

const CLI_MISSING_MESSAGE =
  'RSMM CLI not found.\n\n' +
  'The desktop app needs the rsmm command-line tool.\n\n' +
  'If you installed from source:\n' +
  '  cd RavenswatchModManager\n' +
  '  python3 -m venv .venv && source .venv/bin/activate && pip install -e .\n\n' +
  'If using a pre-built release, reinstall the app.';

const DEFAULT_TIMEOUT_MS = 60_000;
const LONG_TIMEOUT_MS = 10 * 60_000;

interface RsmmOptions {
  signal?: AbortSignal;
  timeoutMs?: number;
  onStdout?: (line: string) => void;
  onStderr?: (line: string) => void;
  profileId?: string;
}

/**
 * Invoke the `rsmm` CLI via Tauri sidecar (production) or system PATH
 * (development). Returns parsed JSON output. Throws a typed `RsmmError`
 * subclass on failure.
 */
async function rsmm<T = unknown>(args: string[], options: RsmmOptions = {}): Promise<T | null> {
  const fullArgs = ['json', ...args];
  const result = await execute(fullArgs, options);
  if (result.code !== 0) {
    throw new RsmmExitError(args, result.code, result.stdout, result.stderr);
  }
  const stdout = result.stdout.trim();
  if (!stdout) return null;
  try {
    return JSON.parse(stdout) as T;
  } catch (cause) {
    throw new RsmmParseError(args, stdout, cause);
  }
}

function defaultModsDir(): string {
  switch (getPlatform()) {
    case 'windows':
      return '%APPDATA%\\rsmm\\mods';
    case 'macos':
      return '~/Library/Application Support/rsmm/mods';
    default:
      return '~/.local/share/rsmm/mods';
  }
}

function rsmmEnv(profileId?: string): Record<string, string> {
  const state = useApp.getState();
  const rootDir = state.settings.modsDir?.trim() || defaultModsDir();
  const id = profileId ?? state.activeProfileId;
  return { RSMM_MODS_DIR: `${rootDir}/profiles/${id}` };
}

const SIDECAR_PROGS = ['binaries/rsmm'] as const;
const CMD_PROGS = ['run-rsmm'] as const;
type ProgName = (typeof SIDECAR_PROGS)[number] | (typeof CMD_PROGS)[number];

function isSidecar(name: string): name is (typeof SIDECAR_PROGS)[number] {
  return (SIDECAR_PROGS as readonly string[]).includes(name);
}

// Strip a trailing CR from a line so Windows `\r\n` output produces clean
// lines in `onStdout` / `onStderr` callbacks.
function stripCR(s: string): string {
  return s.endsWith('\r') ? s.slice(0, -1) : s;
}

function createCommand(name: string, args: string[], opts: Record<string, unknown> | undefined) {
  return isSidecar(name) ? Command.sidecar(name, args, opts) : Command.create(name, args, opts);
}

let resolvedProg: ProgName | null | undefined = undefined;
let useRustProbe = false;
let runtimeEnvPromise: Promise<{ repoRoot: string; path: string }> | null = null;

async function runtimeEnv(): Promise<{ repoRoot: string; path: string }> {
  if (!runtimeEnvPromise) {
    runtimeEnvPromise = invoke<{ repoRoot: string; path: string }>('rsmm_runtime_env');
  }
  return runtimeEnvPromise;
}

async function envForCommand(profileId?: string): Promise<Record<string, string>> {
  const env = rsmmEnv(profileId);
  try {
    const runtime = await runtimeEnv();
    const pathParts = [runtime.repoRoot, runtime.path].filter(Boolean);
    if (pathParts.length) {
      env.PATH = pathParts.join(':');
    }
  } catch {
    // Best effort; fall back to the inherited PATH.
  }
  return env;
}

async function execute(args: string[], options: RsmmOptions): Promise<ExecResult> {
  const env = await envForCommand(options.profileId);
  const opts = Object.keys(env).length ? { env } : undefined;
  const timeoutMs = options.timeoutMs ?? DEFAULT_TIMEOUT_MS;

  if (options.signal?.aborted) {
    throw new RsmmAbortError(args);
  }

  // First call: probe programs in order. Subsequent calls: use the
  // resolved one. If discovery fails, keep retrying on later calls so
  // a transient startup env issue doesn't permanently poison the app.
  if (resolvedProg === undefined) {
    for (const name of [...SIDECAR_PROGS, ...CMD_PROGS]) {
      try {
        const probe = createCommand(name, args, opts);
        return await runWithLifecycle(name, probe, args, options, timeoutMs);
      } catch (err) {
        if (err instanceof RsmmError) throw err;
        // Try next program.
      }
    }
    // Fall back to the Rust-side probe which works in both dev and
    // production. If it succeeds, use it for all subsequent calls
    // (bypassing the shell plugin entirely).
    try {
      const probeResult = await invoke<{ code: number | null; stdout: string; stderr: string }>(
        'probe_rsmm',
        { args },
      );
      if (probeResult.code === 0) {
        useRustProbe = true;
        return { code: probeResult.code, stdout: probeResult.stdout, stderr: probeResult.stderr };
      }
    } catch {
      // probe_rsmm unavailable or failed.
    }
    resolvedProg = undefined;
    throw new RsmmCliMissingError(args);
  }

  if (resolvedProg === null) {
    resolvedProg = undefined;
    return execute(args, options);
  }

  // Once the Rust probe succeeded, use it for every call.
  if (useRustProbe) {
    const result = await invoke<{ code: number | null; stdout: string; stderr: string }>(
      'probe_rsmm',
      { args },
    ).catch(() => null);
    if (!result || result.code !== 0) {
      useRustProbe = false;
      resolvedProg = undefined;
      throw new RsmmCliMissingError(args);
    }
    return result;
  }

  const cmd = createCommand(resolvedProg, args, opts);
  return runWithLifecycle(resolvedProg, cmd, args, options, timeoutMs);
}

async function runWithLifecycle(
  name: string,
  cmd: ReturnType<typeof Command.create>,
  args: string[],
  options: RsmmOptions,
  timeoutMs: number,
): Promise<ExecResult> {
  // Streaming or explicit cancellation requires spawn() with event
  // listeners. Otherwise stick with the simpler execute() path and
  // wrap a wallclock timeout around it.
  if (options.onStdout || options.onStderr || options.signal) {
    return spawnWithLifecycle(name, cmd, args, options, timeoutMs);
  }
  const exec = cmd.execute();
  const result = timeoutMs > 0 ? await raceTimeout(exec, args, timeoutMs) : await exec;
  resolvedProg = name as ProgName;
  return result;
}

function raceTimeout<T>(p: Promise<T>, args: string[], timeoutMs: number): Promise<T> {
  return new Promise<T>((resolve, reject) => {
    const handle = setTimeout(() => reject(new RsmmTimeoutError(args, timeoutMs)), timeoutMs);
    p.then(
      (v) => {
        clearTimeout(handle);
        resolve(v);
      },
      (err) => {
        clearTimeout(handle);
        reject(err);
      },
    );
  });
}

function spawnWithLifecycle(
  name: string,
  cmd: ReturnType<typeof Command.create>,
  args: string[],
  options: RsmmOptions,
  timeoutMs: number,
): Promise<ExecResult> {
  return new Promise<ExecResult>((resolve, reject) => {
    let stdout = '';
    let stderr = '';
    let stdoutBuf = '';
    let stderrBuf = '';
    let settled = false;
    let child: Child | null = null;

    const cleanup = (timeoutHandle: ReturnType<typeof setTimeout> | null) => {
      if (timeoutHandle) clearTimeout(timeoutHandle);
      options.signal?.removeEventListener('abort', onAbort);
    };

    const finish = (action: () => void, timeoutHandle: ReturnType<typeof setTimeout> | null) => {
      if (settled) return;
      settled = true;
      cleanup(timeoutHandle);
      action();
    };

    const timeoutHandle =
      timeoutMs > 0
        ? setTimeout(() => {
            child?.kill().catch(() => {});
            finish(() => reject(new RsmmTimeoutError(args, timeoutMs)), null);
          }, timeoutMs)
        : null;

    const onAbort = () => {
      child?.kill().catch(() => {});
      finish(() => reject(new RsmmAbortError(args)), timeoutHandle);
    };

    if (options.signal) {
      if (options.signal.aborted) {
        finish(() => reject(new RsmmAbortError(args)), timeoutHandle);
        return;
      }
      options.signal.addEventListener('abort', onAbort, { once: true });
    }

    cmd.stdout.on('data', (chunk: string) => {
      stdout += chunk;
      if (options.onStdout) {
        stdoutBuf += chunk;
        const lines = stdoutBuf.split('\n');
        stdoutBuf = lines.pop() ?? '';
        for (const line of lines) options.onStdout(stripCR(line));
      }
    });
    cmd.stderr.on('data', (chunk: string) => {
      stderr += chunk;
      if (options.onStderr) {
        stderrBuf += chunk;
        const lines = stderrBuf.split('\n');
        stderrBuf = lines.pop() ?? '';
        for (const line of lines) options.onStderr(stripCR(line));
      }
    });

    cmd.on('close', ({ code }: { code: number | null }) => {
      if (stdoutBuf && options.onStdout) options.onStdout(stripCR(stdoutBuf));
      if (stderrBuf && options.onStderr) options.onStderr(stripCR(stderrBuf));
      resolvedProg = name as ProgName;
      finish(() => resolve({ code, stdout, stderr }), timeoutHandle);
    });

    cmd.on('error', (err: string) => {
      finish(() => reject(new Error(err)), timeoutHandle);
    });

    cmd.spawn().then(
      (c) => {
        child = c;
      },
      (err) => {
        finish(() => reject(err), timeoutHandle);
      },
    );
  });
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
  dependencies: Record<string, string>;
  writes: string[];
}

export interface ModConfigField {
  type: 'bool' | 'int' | 'float' | 'string' | 'enum';
  default: boolean | number | string | null;
  min: number | null;
  max: number | null;
  choices: string[];
  label: string;
}

export interface ModConfigSchema {
  fields: Record<string, ModConfigField>;
}

export interface ModConfigResponse {
  ok: boolean;
  error?: string;
  modId?: string;
  path?: string;
  schema?: ModConfigSchema;
  values?: Record<string, boolean | number | string>;
}

interface RunResult {
  ok: boolean;
  code: number;
  stdout: string;
  stderr: string;
}

export interface DoctorCheck {
  status: 'OK' | 'WARN' | 'FAIL';
  ok: boolean;
  label: string;
}

export interface DoctorResult extends RunResult {
  checks: DoctorCheck[];
}

interface ApplyOptions extends RsmmOptions {
  dryRun?: boolean;
  force?: boolean;
  noMerge?: boolean;
}

// Bare wrappers take no arguments so React Query's QueryFunctionContext
// (passed as the first arg of `queryFn`) is not silently captured as
// `RsmmOptions`. Pass options explicitly via `rsmm(args, options)` if
// you need cancellation, timeout overrides, or streaming.

export const listLocalMods = () => rsmm<LocalMod[]>(['list']);

// Author / cooked-asset inspection. These bypass the `json` CLI bridge
// because `uncook` and `cook` are text/binary commands with their own
// --json flag for structured output (not the legacy json bridge).
export interface CookedClassEntry {
  name: string;
  uid: string;
  version: [number, number];
  parent: string;
}
export interface CookedSectionEntry {
  index: number;
  size: number;
}
export interface CookedInfo {
  path: string;
  size: number;
  variant: 'A' | 'B';
  flags: number;
  extra: number;
  type_tag: number;
  root_class: string;
  schema_status: 'stub' | 'raw';
  source_ext: string;
  classes: CookedClassEntry[];
  sections: CookedSectionEntry[];
}
export async function uncookInfo(path: string): Promise<CookedInfo> {
  const args = ['uncook', '--info', '--json', path];
  const result = await execute(args, {});
  if (result.code !== 0) {
    throw new RsmmExitError(args, result.code, result.stdout, result.stderr);
  }
  try {
    return JSON.parse(result.stdout.trim()) as CookedInfo;
  } catch (cause) {
    throw new RsmmParseError(args, result.stdout, cause);
  }
}

export const listLocalModsForProfile = (profileId: string) =>
  rsmm<LocalMod[]>(['list'], { profileId });

export async function getModConfig(modId: string): Promise<ModConfigResponse> {
  const result = await rsmm<ModConfigResponse>(['config', 'get', modId]);
  if (!result) {
    throw new Error(`empty config response for ${modId}`);
  }
  return result;
}

export async function setModConfig(
  modId: string,
  values: Record<string, boolean | number | string>,
): Promise<ModConfigResponse> {
  const result = await rsmm<ModConfigResponse>(['config', 'set', modId, JSON.stringify(values)], {
    timeoutMs: LONG_TIMEOUT_MS,
  });
  if (!result) {
    throw new Error(`empty config response for ${modId}`);
  }
  return result;
}

export interface ConflictEntry {
  type: 'file' | 'patch' | 'manifest';
  modIds: string[];
  path?: string;
  patchKind?: string;
  field?: string;
  target?: string;
  values?: Record<string, string>;
}

export const getConflicts = () => rsmm<ConflictEntry[]>(['conflicts']);

export const doctor = () => rsmm<DoctorResult>(['doctor']);

export const applyMods = (opts: ApplyOptions = {}) => {
  const { dryRun, force, noMerge, ...rsmmOpts } = opts;
  const args = ['apply'];
  if (dryRun) args.push('--dry-run');
  if (force) args.push('--force');
  if (noMerge) args.push('--no-merge');
  return rsmm<RunResult>(args, { timeoutMs: LONG_TIMEOUT_MS, ...rsmmOpts });
};

export const build = () => rsmm<RunResult>(['build'], { timeoutMs: LONG_TIMEOUT_MS });

const runGame = () => rsmm<RunResult>(['run'], { timeoutMs: DEFAULT_TIMEOUT_MS });

export const runVanilla = () =>
  rsmm<RunResult>(['run', '--vanilla'], { timeoutMs: DEFAULT_TIMEOUT_MS });

export const restoreAll = () => rsmm<RunResult>(['restore-all'], { timeoutMs: LONG_TIMEOUT_MS });

export interface ActiveOverridesStatus {
  ok: boolean;
  gameDir?: string | null;
  cookingDir?: string | null;
  hasActiveOverrides: boolean;
  activeOverrideCount: number;
  error?: string;
}

export const getActiveOverridesStatus = () =>
  rsmm<ActiveOverridesStatus>(['active-overrides'], { timeoutMs: LONG_TIMEOUT_MS });

export async function runModded(): Promise<RunResult | null> {
  const applyResult = await applyMods();
  if (applyResult && applyResult.ok === false) {
    throw new RsmmExitError(['apply'], applyResult.code, applyResult.stdout, applyResult.stderr);
  }
  return runGame();
}

// publish-to-index lives on the website now (see apps/www /publish and
// /my-mods). The desktop client only consumes the registry — install,
// browse, and run. Pack/upload helpers used to live here.

export interface InstallResult {
  ok: boolean;
  slug?: string;
  version?: string;
  sha256?: string;
  sizeBytes?: number;
  installedTo?: string;
  error?: string;
}

export interface UninstallResult {
  ok: boolean;
  modId?: string;
  removed?: boolean;
  removedPath?: string;
  error?: string;
}

/**
 * Download a mod from the public index by slug + extract into the
 * local `mods/<slug>/` folder. Server-side this hit also bumps the
 * mod's download counter (see `apps/api/src/routes/mods.ts`).
 */
export const installModFromIndex = (slug: string, profileId?: string) =>
  rsmm<InstallResult>(['install-mod', slug], { timeoutMs: LONG_TIMEOUT_MS, profileId });

export const installModVersion = (slug: string, version: string, profileId?: string) =>
  rsmm<InstallResult>(['install-mod-version', slug, version], {
    timeoutMs: LONG_TIMEOUT_MS,
    profileId,
  });

export const uninstallLocalMod = (modId: string) =>
  rsmm<UninstallResult>(['uninstall-mod', modId], { timeoutMs: LONG_TIMEOUT_MS });
