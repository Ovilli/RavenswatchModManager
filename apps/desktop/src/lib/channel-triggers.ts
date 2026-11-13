/**
 * When the loader and CLI channels are checked.
 *
 * They used to be checked once per launch, when the Library mounted, so a
 * loader published while the app sat open was never noticed and an app that
 * opened on another route never checked at all. Now:
 *
 *  - `start`: once when the app starts, whatever route opens first;
 *  - `focus`: when the window regains focus;
 *  - `prelaunch`: right before the game is launched. Always runs, but is capped,
 *    and a timeout or failure never blocks the launch;
 *  - `manual`: an explicit re-check; always runs, no cap.
 *
 * `start` and `focus` are skipped when a check finished within {@link DEBOUNCE_MS}
 * and join one that is still running. Both channels download from release-asset
 * URLs (not the GitHub API), so a check costs no API quota.
 */
import {
  type ChannelName,
  getChannelPhases,
  setChannelPhase,
  trackCliUpdate,
  trackLoaderUpdate,
} from './channel-status';
import { t as tr } from './i18n';
import { noteLoaderResult } from './loader-status';
import { type UpdateLoaderResult, cliChannel, setPreLaunchHook } from './rsmm';

export type CheckReason = 'start' | 'focus' | 'prelaunch' | 'manual';

export const DEBOUNCE_MS = 60_000;
/** How long a pre-launch check may take before the game launches regardless. */
export const PRELAUNCH_CHECK_MS = 3000;
/** Once a bundle is actually downloading, a pre-launch check may take this long. */
export const PRELAUNCH_DOWNLOAD_MS = 120_000;

export interface CheckResult {
  loader: UpdateLoaderResult | null;
}

export interface TriggerDeps {
  now: () => number;
  loader: () => Promise<UpdateLoaderResult | null>;
  cli: () => Promise<unknown>;
  /** True while either channel is mid-download. */
  downloading: () => boolean;
  /** Called for a channel still running when a pre-launch check gives up. */
  timedOut: (seconds: number) => void;
}

const defaultDeps: TriggerDeps = {
  now: () => Date.now(),
  loader: () => trackLoaderUpdate(),
  cli: () => trackCliUpdate(),
  downloading: () => {
    const p = getChannelPhases();
    return p.loader.kind === 'downloading' || p.cli.kind === 'downloading';
  },
  timedOut: (seconds) => {
    const p = getChannelPhases();
    for (const name of ['loader', 'cli'] as ChannelName[]) {
      if (p[name].kind === 'checking' || p[name].kind === 'downloading') {
        setChannelPhase(name, {
          kind: 'failed',
          reason: tr('no answer after {seconds} s - launching with the current build', { seconds }),
        });
      }
    }
  },
};

let lastFinished = Number.NEGATIVE_INFINITY;
let lastResult: CheckResult = { loader: null };
let inflight: Promise<CheckResult> | null = null;

function startRun(deps: TriggerDeps): Promise<CheckResult> {
  const run = (async (): Promise<CheckResult> => {
    // A CLI download must not hold up the loader's, and neither may throw out.
    const [loader] = await Promise.allSettled([deps.loader(), deps.cli()]);
    const result: CheckResult = { loader: loader.status === 'fulfilled' ? loader.value : null };
    noteLoaderResult(result.loader);
    lastResult = result;
    lastFinished = deps.now();
    return result;
  })().finally(() => {
    inflight = null;
  });
  inflight = run;
  return run;
}

/** Resolve with `run`, or give up after the cap (longer once a download is under way). */
async function capped(run: Promise<CheckResult>, deps: TriggerDeps): Promise<void> {
  const after = (ms: number) =>
    new Promise<'timeout'>((resolve) => setTimeout(() => resolve('timeout'), ms));
  const first = await Promise.race([run, after(PRELAUNCH_CHECK_MS)]);
  if (first !== 'timeout') return;
  if (deps.downloading()) {
    const second = await Promise.race([run, after(PRELAUNCH_DOWNLOAD_MS)]);
    if (second !== 'timeout') return;
    deps.timedOut(Math.round((PRELAUNCH_CHECK_MS + PRELAUNCH_DOWNLOAD_MS) / 1000));
    return;
  }
  deps.timedOut(Math.round(PRELAUNCH_CHECK_MS / 1000));
}

/**
 * Check both channels for `reason`. Never rejects; a failure is published to
 * the status banner by the tracked wrappers.
 */
export async function checkChannels(
  reason: CheckReason,
  deps: TriggerDeps = defaultDeps,
): Promise<CheckResult> {
  if (reason === 'start' || reason === 'focus') {
    if (inflight) return inflight;
    if (deps.now() - lastFinished < DEBOUNCE_MS) return lastResult;
    return startRun(deps);
  }
  const run = inflight ?? startRun(deps);
  if (reason === 'manual') return run;
  await capped(run, deps);
  return lastResult;
}

/** Tests only. */
export function resetChannelTriggers(): void {
  lastFinished = Number.NEGATIVE_INFINITY;
  lastResult = { loader: null };
  inflight = null;
}

/**
 * Wire the app-level triggers: the start check, window focus and the
 * pre-launch hook. Returns the cleanup. Called once, from the root layout.
 */
export function installChannelTriggers(): () => void {
  setPreLaunchHook(async () => {
    await checkChannels('prelaunch');
  });
  const onFocus = () => {
    void checkChannels('focus');
  };
  window.addEventListener('focus', onFocus);
  // A CLI build staged by an earlier launch is waiting for a restart: say so
  // now rather than after the next check.
  void cliChannel().then((c) => {
    if (c.staged != null && c.staged > c.version) {
      setChannelPhase('cli', { kind: 'installed', version: c.staged });
    }
  });
  void checkChannels('start');
  return () => {
    window.removeEventListener('focus', onFocus);
    setPreLaunchHook(null);
  };
}
