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
import { restoreAll, runModded, runVanilla } from '../lib/rsmm';

/**
 * The single owner of "launch the game".
 *
 * Launching modded rewrites files in the game install, so every launch MUST
 * be followed by a restore once the game exits — and the window-close guard
 * needs to know a modded session is live. That bookkeeping used to sit inside
 * the status strip, which meant launching from anywhere else (the Commands
 * page) applied mods, launched, and then left the install modded forever with
 * no watcher and no close warning. Route every launch through here instead.
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
            'Could not observe Ravenswatch.exe after launch; automatic restore watcher ended',
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

      if (mode === 'modded') {
        try {
          await appendLauncherLog('info', 'Ravenswatch closed; restoring original files');
          const result = await restoreAll();
          if (!result || !result.ok) {
            throw new Error(result?.stderr?.trim() || result?.stdout?.trim() || 'restore failed');
          }
          await appendLauncherLog('info', 'Restore complete');
        } catch (e) {
          // Shown in the status strip, so it is translated; the launcher log
          // line below keeps the same (English) text a support reader expects.
          const message = t('Automatic restore failed: {error}', { error: String(e) });
          setLaunchError(message);
          await appendLauncherLog('error', message);
        }
      } else {
        await appendLauncherLog('info', 'Ravenswatch closed');
      }

      if (launchSeq.current === seq) setRunning(null);
    })();
  }, []);

  const launch = useCallback(
    async (mode: LaunchMode): Promise<RunResult | null> => {
      if (launching || running) return null;
      const seq = ++launchSeq.current;
      setLaunching(mode);
      setLaunchError(null);
      try {
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
          if (mode === 'modded') {
            // Mods were already written before the launch failed. Roll them
            // back now — otherwise the install stays modded with no game
            // running and nothing left to trigger a restore.
            try {
              await appendLauncherLog(
                'info',
                'Launch failed after applying mods; restoring original files',
              );
              const restore = await restoreAll();
              if (!restore || !restore.ok) {
                throw new Error(
                  restore?.stderr?.trim() || restore?.stdout?.trim() || 'restore failed',
                );
              }
              await appendLauncherLog('info', 'Rollback complete');
            } catch (e) {
              const rollbackMessage = t('Rollback after failed launch failed: {error}', {
                error: String(e),
              });
              setLaunchError(rollbackMessage);
              await appendLauncherLog('error', rollbackMessage);
            }
          }
          return result;
        }
        setRunning(mode);
        await appendLauncherLog('info', `Launch handoff complete: ${mode} (running state set)`);
        trackGameLifecycle(mode, seq);
        return result;
      } catch (e) {
        const message = String(e);
        setLaunchError(message);
        await appendLauncherLog('error', message, { mode });
        throw e;
      } finally {
        setLaunching(null);
      }
    },
    [launching, running, trackGameLifecycle],
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

  return <LaunchContext.Provider value={value}>{children}</LaunchContext.Provider>;
}
