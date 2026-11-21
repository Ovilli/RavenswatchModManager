import { Command } from '@tauri-apps/plugin-shell';
import {
  type ReactNode,
  createContext,
  useCallback,
  useContext,
  useMemo,
  useRef,
  useState,
} from 'react';
import { t } from '../lib/i18n';
import { appendLauncherLog, clearLauncherLog } from '../lib/launcher-log';
import { getPlatform } from '../lib/platform';
import { getLoaderFlags, restoreAll, runModded, runVanilla } from '../lib/rsmm';
import { LaunchOptionsDialog } from './launch-options-dialog';
import { noteModdedLaunch } from './support-nudge';

/**
 * The single owner of "launch the game".
 *
 * Launching modded rewrites files in the game install. `rsmm run` detaches a
 * `watch-restore` process that restores them once the game exits, so this
 * provider only tracks the session for the UI (`running` / `busy`). A failed
 * launch has no watcher, so that path restores here. Route every launch
 * through here.
 */

const GAME_POLL_INTERVAL_MS = 5000;
const GAME_START_TIMEOUT_MS = 5 * 60_000;

export type LaunchMode = 'vanilla' | 'modded';

export interface RunResult {
  ok: boolean;
  code: number;
  stdout: string;
  stderr: string;
}

interface LaunchState {
  launching: LaunchMode | null;
  running: LaunchMode | null;
  launchError: string | null;
  /** True while a launch is being handed off or a launched game is alive. */
  busy: boolean;
  clearError: () => void;
  /** Runs the launch and resolves with the CLI result so callers can render
   * it. A non-zero exit resolves (with `ok: false`) after rolling mods back;
   * only a thrown bridge error rejects. Resolves `null` if a launch is
   * already in flight. */
  launch: (mode: LaunchMode) => Promise<RunResult | null>;
}

const LaunchContext = createContext<LaunchState | null>(null);

export function useLaunch(): LaunchState {
  const ctx = useContext(LaunchContext);
  if (!ctx) throw new Error('useLaunch must be used inside <LaunchProvider>');
  return ctx;
}

function delay(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function createGameProbeCommand() {
  switch (getPlatform()) {
    case 'windows':
      return Command.create('tasklist', ['/FI', 'IMAGENAME eq Ravenswatch.exe', '/NH']);
    default:
      return Command.create('pgrep', ['-f', 'Ravenswatch.exe']);
  }
}

async function isRavenswatchRunning(): Promise<boolean> {
  try {
    const result = await createGameProbeCommand().execute();
    if (getPlatform() === 'windows') {
      return /\bRavenswatch\.exe\b/i.test(result.stdout);
    }
    return result.code === 0;
  } catch {
    return false;
  }
}

export function LaunchProvider({ children }: { children: ReactNode }) {
  const [launching, setLaunching] = useState<LaunchMode | null>(null);
  const [running, setRunning] = useState<LaunchMode | null>(null);
  const [launchError, setLaunchError] = useState<string | null>(null);
  // Bumped on every launch so a watcher from a previous session can tell it
  // has been superseded and stop touching state.
  const launchSeq = useRef(0);
  // Linux: a modded launch without the winhttp override in Steam's launch
  // options runs with no loader, so script mods silently do nothing (#148).
  const [optionsPrompt, setOptionsPrompt] = useState(false);
  const skipOptionsCheck = useRef(false);

  const trackGameLifecycle = useCallback((mode: LaunchMode, seq: number) => {
    void (async () => {
      const startedAt = Date.now();
      let sawGameRunning = false;

      while (Date.now() - startedAt < GAME_START_TIMEOUT_MS) {
        if (launchSeq.current !== seq) return;
        if (await isRavenswatchRunning()) {
          sawGameRunning = true;
          break;
        }
        await delay(GAME_POLL_INTERVAL_MS);
      }

      if (!sawGameRunning) {
        if (mode === 'modded') {
          await appendLauncherLog(
            'warn',
            'Could not observe Ravenswatch.exe after launch; the rsmm watcher restores the files regardless',
          );
        }
        if (launchSeq.current === seq) setRunning(null);
        return;
      }

      await appendLauncherLog('info', `Ravenswatch started; waiting for ${mode} session to end`);
      while (launchSeq.current === seq && (await isRavenswatchRunning())) {
        await delay(GAME_POLL_INTERVAL_MS);
      }

      if (launchSeq.current !== seq) return;

      // The rsmm watcher that `rsmm run` detached restores the files; a second
      // restore from here would race it for the install lock.
      await appendLauncherLog(
        'info',
        mode === 'modded'
          ? 'Ravenswatch closed; the rsmm watcher restores the original files'
          : 'Ravenswatch closed',
      );

      if (launchSeq.current === seq) setRunning(null);
    })();
  }, []);

  /** Mods may already be written when a modded launch fails: put the
   *  install back, since no watcher was started to do it. The CLI refuses a
   *  restore while the game runs, so this cannot pull files from under it. */
  const rollbackModded = useCallback(async () => {
    try {
      await appendLauncherLog(
        'info',
        'Launch failed after applying mods; restoring original files',
      );
      const restore = await restoreAll();
      if (!restore || !restore.ok) {
        throw new Error(restore?.stderr?.trim() || restore?.stdout?.trim() || 'restore failed');
      }
      await appendLauncherLog('info', 'Rollback complete');
    } catch (e) {
      const rollbackMessage = t('Rollback after failed launch failed: {error}', {
        error: String(e),
      });
      setLaunchError(rollbackMessage);
      await appendLauncherLog('error', rollbackMessage);
    }
  }, []);

  const launch = useCallback(
    async (mode: LaunchMode): Promise<RunResult | null> => {
      if (launching || running) return null;
      const seq = ++launchSeq.current;
      setLaunching(mode);
      setLaunchError(null);
      try {
        if (mode === 'modded' && getPlatform() !== 'windows' && !skipOptionsCheck.current) {
          const flags = await getLoaderFlags().catch(() => null);
          // `rsmm run` sets the override in the Proton prefix itself; only a
          // prefix that doesn't exist yet (never run under Proton) needs Steam.
          if (flags?.launchOptionsPresent === false && !flags.prefixOverride) {
            setOptionsPrompt(true);
            return null;
          }
        }
        skipOptionsCheck.current = false;
        await clearLauncherLog();
        await appendLauncherLog('info', `Launch requested: ${mode}`);
        const fn = mode === 'vanilla' ? runVanilla : runModded;
        const result = await fn();
        if (!result || !result.ok) {
          const message =
            mode === 'vanilla'
              ? t('Vanilla launch failed (exit {code})', { code: result?.code ?? t('unknown') })
              : t('Modded launch failed (exit {code})', { code: result?.code ?? t('unknown') });
          setLaunchError(message);
          await appendLauncherLog('error', message, {
            code: result?.code ?? null,
            stdout: result?.stdout ?? '',
            stderr: result?.stderr ?? '',
          });
          if (mode === 'modded') await rollbackModded();
          return result;
        }
        setRunning(mode);
        if (mode === 'modded') noteModdedLaunch();
        await appendLauncherLog('info', `Launch handoff complete: ${mode} (running state set)`);
        trackGameLifecycle(mode, seq);
        return result;
      } catch (e) {
        const message = String(e);
        setLaunchError(message);
        await appendLauncherLog('error', message, { mode });
        // A THROWN failure needs the rollback too. `runModded` turns a failed
        // apply into an RsmmExitError, and a timeout throws as well — both used
        // to skip the rollback below the non-zero-exit branch, leaving
        // UsedRscList.ot and whatever apply had written in the install with no
        // game running and no watcher, so a plain Steam launch ran modded.
        if (mode === 'modded') await rollbackModded();
        throw e;
      } finally {
        setLaunching(null);
      }
    },
    [launching, running, trackGameLifecycle, rollbackModded],
  );

  const value = useMemo<LaunchState>(
    () => ({
      launching,
      running,
      launchError,
      busy: launching !== null || running !== null,
      clearError: () => setLaunchError(null),
      launch,
    }),
    [launching, running, launchError, launch],
  );

  return (
    <LaunchContext.Provider value={value}>
      {children}
      {optionsPrompt ? (
        <LaunchOptionsDialog
          onCancel={() => setOptionsPrompt(false)}
          onLaunch={() => {
            setOptionsPrompt(false);
            skipOptionsCheck.current = true;
            // A failure is already in launchError; nothing else to report.
            launch('modded').catch(() => {});
          }}
        />
      ) : null}
    </LaunchContext.Provider>
  );
}
