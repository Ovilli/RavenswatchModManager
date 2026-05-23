import { invoke } from '@tauri-apps/api/core';
import { type Child, Command } from '@tauri-apps/plugin-shell';
import { useApp } from '../store';

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
}

/**
 * Invoke the `rsmm` CLI via Tauri sidecar (production) or system PATH
 * (development). Returns parsed JSON output. Throws a typed `RsmmError`
 * subclass on failure.
 */
async function rsmm<T = unknown>(
  args: string[],
  options: RsmmOptions = {},
): Promise<T | null> {
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

function rsmmEnv(): Record<string, string> {
  const modsDir = useApp.getState().settings.modsDir?.trim();
  return modsDir ? { RSMM_MODS_DIR: modsDir } : {};
}

const SIDECAR_PROGS = ['rsmm'] as const;
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
let runtimeEnvPromise: Promise<{ repoRoot: string; path: string }> | null = null;

async function runtimeEnv(): Promise<{ repoRoot: string; path: string }> {
  if (!runtimeEnvPromise) {
    runtimeEnvPromise = invoke<{ repoRoot: string; path: string }>('rsmm_runtime_env');
  }
  return runtimeEnvPromise;
}

async function envForCommand(): Promise<Record<string, string>> {
  const env = rsmmEnv();
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
  const env = await envForCommand();
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
    resolvedProg = undefined;
    throw new RsmmCliMissingError(args);
  }

  if (resolvedProg === null) {
    resolvedProg = undefined;
    return execute(args, options);
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

export const restoreAll = () =>
  rsmm<RunResult>(['restore-all'], { timeoutMs: LONG_TIMEOUT_MS });

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

/**
 * Download a mod from the public index by slug + extract into the
 * local `mods/<slug>/` folder. Server-side this hit also bumps the
 * mod's download counter (see `apps/api/src/routes/mods.ts`).
 */
export const installModFromIndex = (slug: string) =>
  rsmm<InstallResult>(['install-mod', slug], { timeoutMs: LONG_TIMEOUT_MS });
