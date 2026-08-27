import { invoke } from '@tauri-apps/api/core';
import { type Child, Command } from '@tauri-apps/plugin-shell';
import { useApp } from '../store';
import { getPlatform, joinPathEntries } from './platform';
import { isSafeProfileId } from './untrusted-state';

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
    default:
      return '~/.local/share/rsmm/mods';
  }
}

/**
 * Environment handed to every CLI invocation. Exported for tests: the profile
 * id it interpolates decides which directory the CLI creates, overwrites and
 * deletes in, so the fail-closed behaviour below is worth asserting directly
 * rather than through a mocked process spawn.
 */
export function rsmmEnv(profileId?: string): Record<string, string> {
  const state = useApp.getState();
  const rootDir = state.settings.modsDir?.trim() || defaultModsDir();
  const requested = profileId ?? state.activeProfileId;
  // Defence in depth. The store sanitizes every profile id at the boundary
  // (see lib/untrusted-state.ts), but this is the SINK: the id lands inside
  // RSMM_MODS_DIR, which is where the CLI creates, overwrites and deletes
  // files. An id that ever slipped through unvalidated — a future code path,
  // a caller passing one straight from an API response — would traverse out of
  // the mods tree from here. Fail closed onto the default profile instead.
  const id = isSafeProfileId(requested) ? requested : 'default';
  return { RSMM_MODS_DIR: `${rootDir}/profiles/${id}` };
}

/**
 * Programs the shell plugin may run, in probe order.
 *
 * `run-rsmm` (a bare `rsmm` resolved from PATH) used to sit here as a second
 * entry and shipped in the production capability with it. In a release build
 * the sidecar wins the probe, so the only way that entry was ever reached was
 * a build whose sidecar is missing — the documented CI failure mode — and it
 * then ran whatever `rsmm` the user's PATH happened to point at. On Windows,
 * where PATH routinely contains user-writable directories, that is a binary
 * planting surface for no benefit: the Rust `probe_rsmm` fallback below
 * already covers development by locating `<repo_root>/rsmm` directly, without
 * involving PATH at all.
 */
const SIDECAR_PROGS = ['binaries/rsmm'] as const;
type ProgName = (typeof SIDECAR_PROGS)[number];

// Strip a trailing CR from a line so Windows `\r\n` output produces clean
// lines in `onStdout` / `onStderr` callbacks.
function stripCR(s: string): string {
  return s.endsWith('\r') ? s.slice(0, -1) : s;
}

function createCommand(name: string, args: string[], opts: Record<string, unknown> | undefined) {
  return Command.sidecar(name, args, opts);
}

/** `undefined` = not resolved yet (next call re-probes). */
let resolvedProg: ProgName | undefined = undefined;
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
    const path = joinPathEntries([runtime.repoRoot, runtime.path], getPlatform());
    if (path) {
      env.PATH = path;
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
    for (const name of SIDECAR_PROGS) {
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
      // Resolving at all means the Rust side FOUND and ran rsmm, so adopt it
      // for later calls. The exit code says what the command did, not whether
      // the CLI exists — keying adoption on `code === 0` meant one legitimately
      // failing command (a failed apply) made the app declare the CLI missing.
      const probeResult = await withTimeout(
        invoke<ExecResult>('probe_rsmm', { args }),
        args,
        timeoutMs,
      );
      useRustProbe = true;
      return probeResult;
    } catch (err) {
      if (err instanceof RsmmError) throw err; // timeout — not a missing CLI
      // probe_rsmm unavailable, or rsmm genuinely not found.
    }
    resolvedProg = undefined;
    throw new RsmmCliMissingError(args);
  }

  // Once the Rust probe succeeded, use it for every call.
  if (useRustProbe) {
    try {
      // A non-zero exit is the command's answer and belongs to the caller —
      // `rsmm()` turns it into an RsmmExitError carrying the real stderr.
      // Reporting it as "CLI not found" hid every genuine failure behind a
      // reinstall prompt and threw away the resolution on the way out.
      return await withTimeout(invoke<ExecResult>('probe_rsmm', { args }), args, timeoutMs);
    } catch (err) {
      if (err instanceof RsmmError) throw err; // timeout
      useRustProbe = false;
      resolvedProg = undefined;
      throw new RsmmCliMissingError(args);
    }
  }

  const cmd = createCommand(resolvedProg, args, opts);
  return runWithLifecycle(resolvedProg, cmd, args, options, timeoutMs);
}

/**
 * Tauri refuses any command the capability does not list. A build that ships
 * `shell:allow-execute` without `shell:allow-spawn` fails every streaming
 * call outright — the whole command dies, not merely its progress reporting.
 */
function isSpawnForbidden(err: unknown): boolean {
  const msg = err instanceof Error ? err.message : String(err);
  return msg.includes('plugin:shell|spawn') && msg.includes('not allowed');
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
    try {
      return await spawnWithLifecycle(name, cmd, args, options, timeoutMs);
    } catch (err) {
      // Cancellation has no execute() equivalent, so only the callers that
      // merely wanted output lines can degrade to the plain path. Losing a
      // progress meter beats losing the command.
      if (options.signal || !isSpawnForbidden(err)) throw err;
    }
  }
  const result = await withTimeout(cmd.execute(), args, timeoutMs);
  resolvedProg = name as ProgName;
  return result;
}

/** `timeoutMs <= 0` means "no wallclock limit" — racing a zero-delay timer
 * against it would reject instantly instead. */
function withTimeout<T>(p: Promise<T>, args: string[], timeoutMs: number): Promise<T> {
  return timeoutMs > 0 ? raceTimeout(p, args, timeoutMs) : p;
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

/**
 * Every sidecar child currently running.
 *
 * Quitting used to hard-exit the process while these were still alive, which
 * on Windows leaves orphaned `rsmm.exe` processes holding the mods directory.
 * Tracking them is what makes an orderly shutdown possible (see `quitApp`).
 */
const liveChildren = new Set<Child>();

/**
 * Kill every running sidecar. Best-effort by design: a child that has already
 * exited, or refuses to die, must not be able to block the quit path.
 */
export async function killLiveChildren(): Promise<void> {
  const children = [...liveChildren];
  liveChildren.clear();
  await Promise.allSettled(children.map((c) => c.kill()));
}

export function liveChildCount(): number {
  return liveChildren.size;
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
      if (child) liveChildren.delete(child);
      if (stdoutBuf && options.onStdout) options.onStdout(stripCR(stdoutBuf));
      if (stderrBuf && options.onStderr) options.onStderr(stripCR(stderrBuf));
      resolvedProg = name as ProgName;
      finish(() => resolve({ code, stdout, stderr }), timeoutHandle);
    });

    cmd.on('error', (err: string) => {
      if (child) liveChildren.delete(child);
      finish(() => reject(new Error(err)), timeoutHandle);
    });

    cmd.spawn().then(
      (c) => {
        child = c;
        liveChildren.add(c);
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
  /**
   * The mod ships a `config_schema.toml`. Carried on the list payload so the
   * library can offer a Configure control per row without one `config get`
   * spawn per installed mod. Optional: an older sidecar omits it.
   */
  hasConfig?: boolean;
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

/** A repair doctor knows how to run for a finding. `manual` ones need a
 * human (close Steam, rebuild the DLL); `automatic` ones `--fix` can run. */
export interface DoctorFix {
  label: string;
  argv: string[];
  risk: 'safe' | 'destructive';
  manual: boolean;
  automatic: boolean;
}

export interface DoctorCheck {
  status: 'OK' | 'WARN' | 'FAIL';
  ok: boolean;
  label: string;
  /** Longer explanation of the finding. Empty when there is nothing to add. */
  detail?: string;
  /** Stable identifier — safe to match on, unlike the label. */
  code?: string;
  /** Which doctor section produced it ("loader", "mods", …). */
  section?: string;
  fix?: DoctorFix | null;
  fixable?: boolean;
}

/** What `--fix` actually did, one entry per attempted repair. */
export interface DoctorRepair {
  code: string;
  fix: string;
  outcome: 'fixed' | 'failed' | 'skipped' | string;
  detail: string;
}

export interface DoctorResult extends RunResult {
  checks: DoctorCheck[];
  repairs?: DoctorRepair[];
  // True when the game install changed since the last apply (Steam patch
  // or file verify) — mods are stale until the next apply, which
  // auto-recovers. null/undefined = could not determine.
  gameUpdated?: boolean | null;
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

export interface LoaderLogResult {
  path: string;
  /** False until the game has run once with the loader installed — not an
   * error, and the UI says so rather than showing a failure. */
  exists: boolean;
  gameDir: string;
  lines: string[];
  /** True when `lines` was capped; the oldest lines were dropped, not the newest. */
  truncated: boolean;
  sessions: number;
  /** Byte length at read time. The follow loop seeds its incremental tail from
   *  this so the first poll does not re-read what this call already returned.
   *  Optional: an older sidecar omits it. */
  bytes?: number;
}

/** Read the in-game loader log (`<game>/mods/_log.txt`). Defaults to the
 * latest session only — the file keeps every run since the last rotation. */
export const readLoaderLog = (
  opts: { lines?: number; prev?: boolean; allSessions?: boolean; run?: string } = {},
) =>
  rsmm<LoaderLogResult>([
    'loader-log',
    '--lines',
    String(opts.lines ?? 400),
    // `--run` names an archived run and is mutually exclusive with `--prev`;
    // the sidecar resolves the name against its own listing, so nothing
    // outside <game>/rsmm/logs is reachable through it.
    ...(opts.run ? ['--run', opts.run] : opts.prev ? ['--prev'] : []),
    ...(opts.allSessions ? ['--all'] : []),
  ]);

export interface ArchivedRun {
  /** Opaque handle to pass back as `readLoaderLog({ run })`. */
  name: string;
  bytes: number;
  /** Unix seconds. */
  mtime: number;
}

/** Archived runs under `<game>/rsmm/logs`, newest first. The loader keeps the
 *  last 20, and until this existed a crash three launches ago was CLI-only. */
export const listLoaderRuns = () => rsmm<{ dir: string; runs: ArchivedRun[] }>(['loader-runs']);

export interface ModHealthRow {
  id: string;
  crashes: number;
  lastError: string;
  disabled: boolean;
  disabledReason: string;
  /** Unix seconds, 0 when never recorded. */
  lastSeen: number;
}

export interface LoaderHealth {
  path?: string;
  exists: boolean;
  /** Consecutive failed boots before the loader quarantines a mod. */
  threshold: number;
  /** Present only while a canary is OPEN — the loader closes it once a launch
   *  has survived boot, so an open one means the previous run died. */
  canary: {
    open: true;
    step: string;
    session: string;
    /** Null when the run died before any mod code ran: not a mod's fault. */
    blamedMod: string | null;
  } | null;
  /** Only mods with a crash record; a clean mod would bury the rest. */
  mods: ModHealthRow[];
}

/** The loader's boot canary + crash history (`<game>/mods/_health.json`).
 *  The loader is the only process that can see a crashy boot, and it disables
 *  a mod after three in a row — this is how the app can say so. */
export const loaderHealth = () => rsmm<LoaderHealth>(['loader-health']);

/** Clear a mod's crash record so the loader stops skipping it at load. */
export const resetModHealth = (modId: string) =>
  rsmm<{ ok: boolean; modId: string }>(['loader-health-reset', modId]);

/** Health check. `fix` runs each finding's automated repair and re-checks;
 * `force` additionally allows the destructive ones (they roll the install
 * back or delete installed files), so it is never implied by `fix`. */
export const doctor = (opts: { fix?: boolean; force?: boolean } = {}) =>
  rsmm<DoctorResult>(
    ['doctor', ...(opts.fix ? ['--fix'] : []), ...(opts.force ? ['--force'] : [])],
    // A repair run shells out to apply / install-loader / update-data, which
    // are minutes-long jobs — the default 60s budget would time out mid-repair.
    opts.fix ? { timeoutMs: LONG_TIMEOUT_MS } : {},
  );

export interface UpdateDataResult {
  ok: boolean;
  status: 'up_to_date' | 'updated' | 'update_available' | 'not_planted' | 'error';
  // Whether the remote DB was generated against the user's exact game build.
  exeMatch?: boolean | null;
  generated?: string | null;
  patternCount?: number | null;
  plantedPath?: string;
  error?: string;
}

// Pulls the latest function-pattern DB (rolling `pattern-db` GitHub release)
// into <game>/rsmm/data/ so the loader resolves engine functions after a
// game patch without waiting for an app release. Safe to call every launch:
// no-ops when already up to date, and any failure is reported, not thrown.
export const updatePatternDb = (opts: { checkOnly?: boolean } = {}) =>
  rsmm<UpdateDataResult>(opts.checkOnly ? ['update-data', '--check'] : ['update-data']);

export interface UpdateLoaderResult {
  ok: boolean;
  status:
    | 'up_to_date'
    | 'updated'
    | 'update_available'
    // The published bundle needs a newer rsmm to plant it — the app itself
    // must be updated. Distinct from 'error' so the UI can say so.
    | 'needs_app_update'
    // Local build is newer than the channel (a dev checkout, or mid-publish).
    | 'ahead'
    // Nothing published on the channel yet — normal, not a failure.
    | 'not_published'
    | 'error';
  installedVersion?: number | null;
  remoteVersion?: number | null;
  rsmmVersion?: string | null;
  generated?: string | null;
  notes?: string | null;
  planted?: string[] | null;
  error?: string;
}

// Pulls the signed loader DLL + Lua SDK bundle (rolling `loader` GitHub
// release) into the game directory. This is the channel that lets a loader
// or Lua-SDK fix reach users without a desktop release + reinstall; the app
// binary itself still updates through the Tauri updater. Safe to call every
// launch: no-ops when up to date, and any failure is reported, not thrown.
/** Bytes so far and, when the server said, the total. `total: 0` means the
 *  size is unknown — render that as indeterminate, never as 0%. */
export interface LoaderDownloadProgress {
  phase: string;
  received: number;
  total: number;
}

/**
 * Fetch + plant the loader bundle, reporting download progress.
 *
 * The CLI writes progress as NDJSON on STDERR: stdout is contractually one
 * JSON object, so it cannot carry a stream. Lines that are not progress (real
 * diagnostics) are ignored here and still reach the error path on failure.
 */
export const updateLoader = (
  opts: { checkOnly?: boolean; onProgress?: (p: LoaderDownloadProgress) => void } = {},
) =>
  rsmm<UpdateLoaderResult>(
    opts.checkOnly ? ['update-loader', '--check'] : ['update-loader'],
    // Downloads a multi-MB DLL + SDK bundle over the network.
    {
      timeoutMs: LONG_TIMEOUT_MS,
      onStderr: opts.onProgress
        ? (line) => {
            const p = parseProgressLine(line);
            if (p) opts.onProgress?.(p);
          }
        : undefined,
    },
  );

/** One stderr line -> progress, or null when it is anything else. */
export function parseProgressLine(line: string): LoaderDownloadProgress | null {
  const trimmed = line.trim();
  if (!trimmed.startsWith('{') || !trimmed.includes('"progress"')) return null;
  try {
    const parsed = JSON.parse(trimmed) as { progress?: Partial<LoaderDownloadProgress> };
    const p = parsed.progress;
    if (!p || typeof p.received !== 'number' || typeof p.total !== 'number') return null;
    return { phase: String(p.phase ?? ''), received: p.received, total: p.total };
  } catch {
    return null;
  }
}

/** "5.4 MB" — for a download meter, where 1 KB = 1024 B and one decimal is
 *  as much precision as a progress line can use. */
export function formatBytes(n: number): string {
  if (!Number.isFinite(n) || n <= 0) return '0 B';
  const units = ['B', 'KB', 'MB', 'GB'];
  let v = n;
  let i = 0;
  while (v >= 1024 && i < units.length - 1) {
    v /= 1024;
    i += 1;
  }
  return `${i === 0 ? Math.round(v) : v.toFixed(1)} ${units[i]}`;
}

export interface GameStatus {
  ok: boolean;
  running: boolean;
}

/** Is the game up? A planted loader does not reach a session already running —
 *  the DLL is loaded at process start — so this decides "restart" vs "launch". */
export const gameStatus = () => rsmm<GameStatus>(['game-status']);

export interface RestartGameResult {
  ok: boolean;
  wasRunning?: boolean;
  error?: string | null;
}

/** Close Ravenswatch (politely, then firmly) and launch it again. Loses a run
 *  in progress, so callers must confirm first. */
export const restartGame = () =>
  rsmm<RestartGameResult>(['restart-game'], { timeoutMs: LONG_TIMEOUT_MS });

export interface ChangelogFeedResult {
  ok: boolean;
  // 'fetched' = live from the channel, 'cached' = a previous fetch (possibly
  // stale, `error` says why it could not be refreshed), 'bundled' = this
  // build's own copy, 'unavailable' = nothing to show at all.
  status: 'fetched' | 'cached' | 'bundled' | 'unavailable' | 'error';
  generated?: string;
  entries: {
    version: string;
    // Present on a loader-channel note, which belongs to no app release.
    loader_version?: number;
    date: string;
    summary?: string;
    highlights: string[];
  }[];
  error?: string | null;
}

// Reads the rolling `changelog` GitHub release. Notes are published on their
// own so a loader-channel fix — which reaches users with no app release — can
// still announce itself. The CLI caches the feed and falls back to its bundled
// copy, so this is cheap to call on launch and works offline.
export const fetchChangelog = (opts: { refresh?: boolean } = {}) =>
  rsmm<ChangelogFeedResult>(opts.refresh ? ['changelog', '--refresh'] : ['changelog']);

export interface LoaderFlag {
  name: string;
  label: string;
  description: string;
  safe: boolean;
}

export interface LoaderFlagsState {
  ok: boolean;
  gameDir?: string | null;
  flagsPath?: string | null;
  available: LoaderFlag[];
  enabled: string[];
  // Whether winhttp.dll is in place. Only present on `get`.
  loaderInstalled?: boolean;
  // Linux/Proton: whether Steam launch options carry the winhttp override.
  // null on native Windows (override not needed there). Only present on `get`.
  launchOptionsPresent?: boolean | null;
  error?: string;
}

export const getLoaderFlags = () => rsmm<LoaderFlagsState>(['loader-flags', 'get']);

// Writes the full enabled-flag set (the bridge ignores anything not marked
// safe, so a stale UI can never arm a crashing flag).
export const setLoaderFlags = (names: string[]) =>
  rsmm<LoaderFlagsState>(['loader-flags', 'set', JSON.stringify(names)]);

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
  /**
   * What happened to the mod's `on_disable.py` — its one chance to undo
   * state it wrote at runtime, since after the folder is deleted there is
   * nothing left to run. `ok` | `absent` | `not-enabled` are all fine;
   * anything else means the mod is gone but its cleanup never happened.
   */
  disableHook?: string;
  disableHookDetail?: string;
}

/** Statuses where no cleanup was owed, or it completed. */
const DISABLE_HOOK_OK = new Set(['ok', 'absent', 'not-enabled']);

/**
 * A user-facing warning when a mod was removed but its cleanup did not run,
 * or null when there is nothing to say.
 *
 * Reported symptom this exists for: a seed-pinning mod wrote `Forced seed`
 * into the game's own settings, and uninstalling it deleted the only code
 * that knew how to unpin it — so the run seed stayed frozen with no mod left
 * to blame. A silent "Mod uninstalled." is the wrong thing to show then.
 */
export const disableHookWarning = (result: UninstallResult | null): string | null => {
  const status = result?.disableHook;
  if (!status || DISABLE_HOOK_OK.has(status)) return null;
  const detail = result?.disableHookDetail?.trim();
  const who = result?.modId ? `${result.modId}'s` : "The mod's";
  const because = detail ? `: ${detail}` : '';
  return `${who} cleanup step did not run (${status})${because}. It may have left settings behind in the game.`;
};

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

/** A column in a mod-declared overlay (its manifest `[overlay]` block). */
export interface OverlayColumn {
  key: string;
  label: string;
  type: 'text' | 'number' | 'percent' | 'bar';
  format: 'plain' | 'compact';
  suffix: string;
}

/** One mod's overlay: what it declared, plus the rows it has published. */
export interface OverlayRecord {
  modId: string;
  modName: string;
  enabled: boolean;
  /**
   * Which tree the declaration came from. "library" = the mod has not been
   * applied yet (dev loop), so it will have no rows until it is.
   */
  source?: 'game' | 'library';
  title?: string;
  icon?: string;
  columns?: OverlayColumn[];
  sort?: { key: string; dir: 'asc' | 'desc' } | null;
  highlight?: string | null;
  empty?: string;
  /** Set when the manifest declaration is malformed; nothing else is usable. */
  error?: string;
  rows: Record<string, string | number | boolean>[];
  meta: Record<string, string | number | boolean>;
  /** Unix seconds of the mod's last publish; 0 = never. */
  updated: number;
  /** false = the mod has not published anything yet this session. */
  exists: boolean;
}

export interface OverlayList {
  gameDir: string;
  overlays: OverlayRecord[];
}

/**
 * Every mod-declared overlay with its live rows. Polled by overlay windows,
 * so it uses a short timeout: a hung read must not stack up behind the next
 * tick.
 */
export const listOverlays = () => rsmm<OverlayList>(['overlays'], { timeoutMs: 10_000 });
