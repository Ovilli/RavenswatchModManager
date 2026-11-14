/**
 * What the CLI and loader channel updates are doing right now, and what the
 * app is running.
 *
 * Both channels download in the background (setup-banner on the Library, the
 * Settings button) and used to say nothing until they were done, so a tester could
 * not tell "still fetching" from "never checked". Every real update now goes
 * through {@link trackLoaderUpdate} / {@link trackCliUpdate}, which publish a
 * phase here for the banner to render. Read-only checks (`--check`) are not
 * tracked: they run on screen mounts and would flash the banner.
 */
import { t as tr } from './i18n';
import {
  type CliChannel,
  type LoaderDownloadProgress,
  type UpdateCliResult,
  type UpdateLoaderResult,
  cliChannel,
  formatBytes,
  updateCli,
  updateLoader,
} from './rsmm';

export type ChannelName = 'cli' | 'loader';

export type ChannelPhase =
  | { kind: 'idle' }
  | { kind: 'checking' }
  | { kind: 'downloading'; received: number; total: number }
  | { kind: 'installed'; version: number | null }
  | { kind: 'failed'; reason: string };

/** How long an "installed" confirmation stays up. */
export const INSTALLED_VISIBLE_MS = 8000;

const IDLE: ChannelPhase = { kind: 'idle' };
let phases: Record<ChannelName, ChannelPhase> = { cli: IDLE, loader: IDLE };
const timers: Partial<Record<ChannelName, ReturnType<typeof setTimeout>>> = {};
const listeners = new Set<() => void>();

export function getChannelPhases(): Record<ChannelName, ChannelPhase> {
  return phases;
}

export function subscribeChannelPhases(fn: () => void): () => void {
  listeners.add(fn);
  return () => {
    listeners.delete(fn);
  };
}

export function setChannelPhase(name: ChannelName, phase: ChannelPhase): void {
  clearTimeout(timers[name]);
  phases = { ...phases, [name]: phase };
  // A staged CLI waits for a restart, so its row stays until dismissed or acted on.
  if (phase.kind === 'installed' && name === 'loader') {
    timers[name] = setTimeout(() => setChannelPhase(name, IDLE), INSTALLED_VISIBLE_MS);
  }
  for (const fn of listeners) fn();
}

let launchHold: 'vanilla' | 'modded' | null = null;

/** Which launch is waiting on an in-flight loader update, or null. */
export function getLaunchHold(): 'vanilla' | 'modded' | null {
  return launchHold;
}

export function setLaunchHold(hold: 'vanilla' | 'modded' | null): void {
  if (hold === launchHold) return;
  launchHold = hold;
  for (const fn of listeners) fn();
}

let launchDepth = 0;

/** True while a launch is being handed off (see channel-triggers.ts). */
export function getLaunchActive(): boolean {
  return launchDepth > 0;
}

export function adjustLaunchDepth(delta: 1 | -1): void {
  const was = launchDepth > 0;
  launchDepth = Math.max(0, launchDepth + delta);
  if (was !== launchDepth > 0) for (const fn of listeners) fn();
}

/** Tests only. */
export function resetChannelPhases(): void {
  launchDepth = 0;
  clearTimeout(timers.cli);
  clearTimeout(timers.loader);
  phases = { cli: IDLE, loader: IDLE };
  launchHold = null;
}

/** The one-line banner text for a phase, or null when there is nothing to say. */
export function describePhase(name: ChannelName, phase: ChannelPhase): string | null {
  const what = name === 'cli' ? tr('CLI') : tr('Game loader');
  switch (phase.kind) {
    case 'idle':
      return null;
    case 'checking':
      return tr('Checking for a new {what}…', { what });
    case 'downloading': {
      const size = phase.total
        ? `${formatBytes(phase.received)} / ${formatBytes(phase.total)} (${Math.min(
            100,
            Math.floor((phase.received / phase.total) * 100),
          )}%)`
        : formatBytes(phase.received);
      return tr('Downloading {what} - {size}', { what, size });
    }
    case 'installed': {
      const version = phase.version == null ? '' : ` v${phase.version}`;
      return name === 'cli'
        ? tr('CLI{version} downloaded - restart the app to use it.', { version })
        : tr('Game loader{version} installed - restart Ravenswatch to pick it up.', { version });
    }
    case 'failed':
      return tr('{what} update failed: {reason}', { what, reason: phase.reason });
  }
}

/** The failure text when a result is an error, else null. */
export function failureReason(
  r: Pick<UpdateLoaderResult | UpdateCliResult, 'ok' | 'status' | 'error'> | null,
): string | null {
  if (r === null) return tr('no answer from the CLI');
  if (r.status === 'error' || r.ok === false) return r.error ?? tr('unknown error');
  return null;
}

/**
 * The staged CLI version waiting for a restart, or null. `update-cli` counts a
 * staged build as installed, so installed > running means a download is
 * waiting, whether it arrived just now or on an earlier check.
 */
export function cliPendingVersion(
  r: Pick<UpdateCliResult, 'status' | 'installedVersion'>,
  running: number,
): number | null {
  const have = r.installedVersion ?? 0;
  return r.status !== 'error' && have > running ? have : null;
}

function messageOf(e: unknown): string {
  return e instanceof Error ? e.message : String(e);
}

let loaderFlight: Promise<unknown> | null = null;

/** The loader update running right now (whoever started it), or null. A launch
 *  must not hand off while this can still write `winhttp.dll`. */
export function loaderUpdateInFlight(): Promise<unknown> | null {
  return loaderFlight;
}

/** Loader update, with the phase published. Same result as `updateLoader`. */
export function trackLoaderUpdate(
  opts: { onProgress?: (p: LoaderDownloadProgress) => void } = {},
): Promise<UpdateLoaderResult | null> {
  const run = runTrackedLoaderUpdate(opts);
  const settled = run.then(
    () => undefined,
    () => undefined,
  );
  loaderFlight = settled;
  void settled.then(() => {
    if (loaderFlight === settled) loaderFlight = null;
  });
  return run;
}

async function runTrackedLoaderUpdate(opts: {
  onProgress?: (p: LoaderDownloadProgress) => void;
}): Promise<UpdateLoaderResult | null> {
  setChannelPhase('loader', { kind: 'checking' });
  try {
    const r = await updateLoader({
      onProgress: (p) => {
        setChannelPhase('loader', { kind: 'downloading', received: p.received, total: p.total });
        opts.onProgress?.(p);
      },
    });
    const failed = failureReason(r);
    if (failed) setChannelPhase('loader', { kind: 'failed', reason: failed });
    else if (r?.status === 'updated') {
      setChannelPhase('loader', { kind: 'installed', version: r.installedVersion ?? null });
    } else setChannelPhase('loader', IDLE);
    return r;
  } catch (e) {
    setChannelPhase('loader', { kind: 'failed', reason: messageOf(e) });
    throw e;
  }
}

/** CLI update, with the phase published. Same result as `updateCli`. */
export async function trackCliUpdate(): Promise<UpdateCliResult | null> {
  setChannelPhase('cli', { kind: 'checking' });
  try {
    const r = await updateCli({
      onProgress: (p) =>
        setChannelPhase('cli', { kind: 'downloading', received: p.received, total: p.total }),
    });
    // null = no channel directory on this install (dev build): nothing to say.
    const failed = r === null ? null : failureReason(r);
    const pending = r === null ? null : cliPendingVersion(r, (await cliChannel()).version);
    if (failed) setChannelPhase('cli', { kind: 'failed', reason: failed });
    else if (pending != null) setChannelPhase('cli', { kind: 'installed', version: pending });
    else setChannelPhase('cli', IDLE);
    return r;
  } catch (e) {
    setChannelPhase('cli', { kind: 'failed', reason: messageOf(e) });
    throw e;
  }
}

/** Where the loader in the game dir came from: `release`, a hand-built `dev`, or `none`. */
export type LoaderState = 'release' | 'dev' | 'none';

/** "v9", "dev", "none", or null when it cannot be told. */
export function describeLoaderInstall(
  state: LoaderState | undefined,
  version: number | null | undefined,
): string | null {
  if (state === 'none') return tr('none');
  if (state === 'dev') return tr('dev');
  if (version == null) return null;
  return `v${version}`;
}

/** "v12 - update channel" or "v12 - embedded". */
export function describeCliSource(cli: Pick<CliChannel, 'active' | 'version'>): string {
  return cli.active
    ? tr('v{version} - update channel', { version: cli.version })
    : tr('v{version} - embedded', { version: cli.version });
}
