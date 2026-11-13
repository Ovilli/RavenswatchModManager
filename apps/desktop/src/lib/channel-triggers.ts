/**
 * When the loader and CLI channels are checked.
 *
 * They used to be checked once per launch, when the Library mounted, so a
 * loader published while the app sat open was never noticed and an app that
 * opened on another route never checked at all. Now:
 *
 *  - `start`: once when the app starts, whatever route opens first;
 *  - `focus`: when the window regains focus;
 *  - `prelaunch`: right before a modded launch. Always runs, but waits only on the
 *    loader and is capped, and a timeout or failure never blocks the launch. The
 *    CLI check carries on in the background: a staged CLI only matters after a
 *    restart, so it never holds Play;
 *  - `manual`: an explicit re-check; always runs, no cap.
 *
 * `start` and `focus` are skipped when a check finished within {@link DEBOUNCE_MS}
 * and join one that is still running. Both channels download from release-asset
 * URLs (not the GitHub API), so a check costs no API quota.
 *
 * A launch and a loader write must not overlap: `run --vanilla` removes the
 * loader, and a bundle landing after that would put `winhttp.dll` back before
 * Steam starts the game. So while a launch is in progress `start`/`focus`/`manual`
 * start nothing new, and a vanilla launch first waits for any loader update
 * already running (the banner says so).
 */
import {
  adjustLaunchDepth,
  getChannelPhases,
  getLaunchActive,
  loaderUpdateInFlight,
  setChannelPhase,
  setLaunchHold,
  trackCliUpdate,
  trackLoaderUpdate,
} from './channel-status';
import { t as tr } from './i18n';
import { noteLoaderResult } from './loader-status';
import { type LaunchKind, type UpdateLoaderResult, cliChannel, setLaunchGate } from './rsmm';

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
  /** True while the loader is mid-download. */
  downloading: () => boolean;
  /** Called when a pre-launch check gives up on the loader. */
  timedOut: (seconds: number) => void;
}

const defaultDeps: TriggerDeps = {
  now: () => Date.now(),
  loader: () => trackLoaderUpdate(),
  cli: () => trackCliUpdate(),
  downloading: () => {
    const p = getChannelPhases();
    return p.loader.kind === 'downloading';
  },
  timedOut: (seconds) => {
    const kind = getChannelPhases().loader.kind;
    if (kind === 'checking' || kind === 'downloading') {
      setChannelPhase('loader', {
        kind: 'failed',
        reason: tr('no answer after {seconds} s - launching with the current build', { seconds }),
      });
    }
  },
};

let lastFinished = Number.NEGATIVE_INFINITY;
let lastResult: CheckResult = { loader: null };
/** The loader check in flight. The CLI check is tracked apart: it never gates anything. */
let inflight: Promise<CheckResult> | null = null;
let cliInflight = false;

function startRun(deps: TriggerDeps): Promise<CheckResult> {
  if (!cliInflight) {
    cliInflight = true;
    void (async () => deps.cli())()
      .catch(() => {})
      .finally(() => {
        cliInflight = false;
      });
  }
  const run = (async (): Promise<CheckResult> => {
    let loader: UpdateLoaderResult | null = null;
    try {
      loader = await deps.loader();
    } catch {
      // Published to the banner by the tracked wrapper.
    }
    const result: CheckResult = { loader };
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
 * Check the channels for `reason`. Resolves with the loader's result; the CLI
 * check runs alongside without being waited on. Never rejects; a failure is
 * published to the status banner by the tracked wrappers.
 */
export async function checkChannels(
  reason: CheckReason,
  deps: TriggerDeps = defaultDeps,
): Promise<CheckResult> {
  if (reason !== 'prelaunch') {
    if (inflight) return inflight;
    if (getLaunchActive()) return lastResult;
    if (reason !== 'manual' && deps.now() - lastFinished < DEBOUNCE_MS) return lastResult;
    return startRun(deps);
  }
  // A loader update started elsewhere (the Settings button) counts too: wait on
  // it, with the same cap, instead of starting a second one.
  const external = loaderUpdateInFlight();
  const run = inflight ?? (external ? external.then(() => lastResult) : startRun(deps));
  await capped(run, deps);
  return lastResult;
}

/** Wait until no loader update (from any caller) is running. */
async function waitForLoaderIdle(): Promise<void> {
  for (;;) {
    const pending = [inflight, loaderUpdateInFlight()].filter((p) => p !== null);
    if (pending.length === 0) return;
    await Promise.allSettled(pending);
  }
}

/** Runs before any launch hands off; see the file header. Never throws. */
export async function beforeLaunch(
  kind: LaunchKind,
  deps: TriggerDeps = defaultDeps,
): Promise<void> {
  adjustLaunchDepth(1);
  try {
    if (kind === 'modded') {
      await checkChannels('prelaunch', deps);
      return;
    }
    if (inflight || loaderUpdateInFlight()) {
      setLaunchHold('vanilla');
      try {
        await waitForLoaderIdle();
      } finally {
        setLaunchHold(null);
      }
    }
  } catch {
    // A failed check never blocks the launch.
  }
}

export function afterLaunch(): void {
  adjustLaunchDepth(-1);
}

/** Tests only. */
export function resetChannelTriggers(): void {
  lastFinished = Number.NEGATIVE_INFINITY;
  lastResult = { loader: null };
  inflight = null;
  cliInflight = false;
}

/**
 * Wire the app-level triggers: the start check, window focus and the
 * pre-launch hook. Returns the cleanup. Called once, from the root layout.
 */
export function installChannelTriggers(): () => void {
  setLaunchGate({ before: (kind) => beforeLaunch(kind), after: afterLaunch });
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
    setLaunchGate(null);
  };
}
