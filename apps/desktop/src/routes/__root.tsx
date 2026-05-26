import type { QueryClient } from '@tanstack/react-query';
import { Link, Outlet, createRootRouteWithContext, useLocation } from '@tanstack/react-router';
import { exit as processExit } from '@tauri-apps/plugin-process';
import { Command } from '@tauri-apps/plugin-shell';
import { AlertTriangle } from 'lucide-react';
import { Terminal } from 'lucide-react';
import type { CSSProperties, Dispatch, SetStateAction } from 'react';
import { createContext, useContext, useEffect, useMemo, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import PromotedBanner from '../components/PromotedBanner';
import { AccountStrip } from '../components/account-strip';
import { Button, CopyButton, StatPill } from '../components/chrome';
import { CommandPalette } from '../components/command-palette';
import { AboutIcon } from '../components/icons/AboutIcon';
import { BrowseIcon } from '../components/icons/BrowseIcon';
import { ConflictsIcon } from '../components/icons/ConflictsIcon';
import { LaunchIcon } from '../components/icons/LaunchIcon';
import { LibraryIcon } from '../components/icons/LibraryIcon';
import { ProfilesIcon } from '../components/icons/ProfilesIcon';
import { SettingsIcon } from '../components/icons/SettingsIcon';
import { WindowCloseIcon } from '../components/icons/WindowCloseIcon';
import { WindowMaximizeIcon } from '../components/icons/WindowMaximizeIcon';
import { WindowMinimizeIcon } from '../components/icons/WindowMinimizeIcon';
import { ProfilePopover } from '../components/profile-popover';
import { DialogProvider, ToastProvider } from '../components/toast';
import { UpdaterBanner } from '../components/updater';
import { appendLauncherLog, clearLauncherLog } from '../lib/launcher-log';
import { getPlatform, shortcutLabel } from '../lib/platform';
import { restoreAll, runModded, runVanilla } from '../lib/rsmm';
import { activeProfile, detectConflicts, isEnabledIn, outdatedCount, useApp } from '../store';

export const Route = createRootRouteWithContext<{ queryClient: QueryClient }>()({
  component: RootLayout,
});

interface Nav {
  to: '/' | '/browse' | '/profiles' | '/conflicts' | '/settings' | '/commands' | '/about';
  icon: React.ComponentType<{ className?: string }>;
  label: string;
}

const NAV: Nav[] = [
  { to: '/', icon: LibraryIcon, label: 'Library' },
  { to: '/browse', icon: BrowseIcon, label: 'Browse' },
  { to: '/profiles', icon: ProfilesIcon, label: 'Profiles' },
  { to: '/conflicts', icon: ConflictsIcon, label: 'Conflicts' },
  { to: '/settings', icon: SettingsIcon, label: 'Settings' },
  { to: '/commands', icon: Terminal, label: 'Commands' },
  { to: '/about', icon: AboutIcon, label: 'About' },
];

type AppRegionStyle = CSSProperties & { WebkitAppRegion?: 'drag' | 'no-drag' };

const dragStyle: AppRegionStyle = { WebkitAppRegion: 'drag' };
const noDragStyle: AppRegionStyle = { WebkitAppRegion: 'no-drag' };
const GAME_POLL_INTERVAL_MS = 5000;
const GAME_START_TIMEOUT_MS = 5 * 60_000;

type LaunchMode = 'vanilla' | 'modded';

interface LaunchState {
  launching: LaunchMode | null;
  running: LaunchMode | null;
  launchError: string | null;
  setLaunching: Dispatch<SetStateAction<LaunchMode | null>>;
  setRunning: Dispatch<SetStateAction<LaunchMode | null>>;
  setLaunchError: Dispatch<SetStateAction<string | null>>;
}

const LaunchStateContext = createContext<LaunchState | null>(null);

function useLaunchState() {
  const ctx = useContext(LaunchStateContext);
  if (!ctx) throw new Error('useLaunchState must be used inside <LaunchStateContext.Provider>');
  return ctx;
}

function delay(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function createGameProbeCommand() {
  switch (getPlatform()) {
    case 'windows':
      return Command.create('tasklist', ['/FI', 'IMAGENAME eq Ravenswatch.exe', '/NH']);
    case 'macos':
      return Command.create('pgrep', ['-f', 'Ravenswatch']);
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

function NavLink({ to, icon: Icon, label }: Nav) {
  const installed = useApp((s) => s.installed);
  const outdated = useMemo(() => (to === '/' ? outdatedCount(installed) : 0), [to, installed]);
  return (
    <Link
      to={to}
      className="nav-link-grim group"
      activeProps={{ 'data-active': 'true' }}
      inactiveProps={{ 'data-active': 'false' }}
    >
      <Icon className="nav-icon" />
      <span className="font-serif-italic text-base">{label}</span>
      {outdated > 0 ? (
        <span
          className="ml-auto inline-flex h-5 min-w-[1.25rem] items-center justify-center rounded-full bg-gilt/20 px-1.5 font-mono text-[11px] font-semibold text-gilt"
          title={`${outdated} mod${outdated === 1 ? '' : 's'} with available updates`}
        >
          {outdated}
        </span>
      ) : null}
    </Link>
  );
}

function StatusStrip() {
  const { launching, running, launchError, setLaunching, setRunning, setLaunchError } =
    useLaunchState();
  const profile = useApp(activeProfile);
  const installed = useApp((s) => s.installed);
  const profiles = useApp((s) => s.profiles);
  const launchSeq = useRef(0);
  const enabled = profile.loadOrder.filter((id) => isEnabledIn(profile, id)).length;
  const disabled = profile.loadOrder.length - enabled;
  const conflictCount = useMemo(() => detectConflicts(profile).length, [profile]);
  const outdated = useMemo(() => outdatedCount(installed), [installed]);

  const trackGameLifecycle = (mode: 'vanilla' | 'modded', seq: number) => {
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
          const message = `Automatic restore failed: ${String(e)}`;
          setLaunchError(message);
          await appendLauncherLog('error', message);
        }
      } else {
        await appendLauncherLog('info', 'Ravenswatch closed');
      }

      if (launchSeq.current === seq) setRunning(null);
    })();
  };

  const handleLaunch = async (mode: 'vanilla' | 'modded') => {
    if (launching || running) return;
    const seq = ++launchSeq.current;
    setLaunching(mode);
    setLaunchError(null);
    try {
      await clearLauncherLog();
      await appendLauncherLog('info', `Launch requested: ${mode}`);
      const fn = mode === 'vanilla' ? runVanilla : runModded;
      const result = await fn();
      if (!result || !result.ok) {
        const message = `${mode} launch failed (exit ${result?.code ?? 'unknown'})`;
        setLaunchError(message);
        await appendLauncherLog('error', message, {
          code: result?.code ?? null,
          stdout: result?.stdout ?? '',
          stderr: result?.stderr ?? '',
        });
        if (mode === 'modded') {
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
            const rollbackMessage = `Rollback after failed launch failed: ${String(e)}`;
            setLaunchError(rollbackMessage);
            await appendLauncherLog('error', rollbackMessage);
          }
        }
      } else {
        setRunning(mode);
        await appendLauncherLog('info', `Launch handoff complete: ${mode} (running state set)`);
        trackGameLifecycle(mode, seq);
      }
    } catch (e) {
      const message = String(e);
      setLaunchError(message);
      await appendLauncherLog('error', message, { mode });
    } finally {
      setLaunching(null);
    }
  };

  return (
    <div className="surface-grain flex items-center justify-between gap-3 border-b border-border px-3 py-2 backdrop-blur-sm">
      <div className="flex items-center gap-4" style={dragStyle}>
        <span className="font-fraktur text-lg text-parchment">Ravenswatch Mod Manager</span>
      </div>

      <div className="flex items-center gap-2">
        <div className="flex items-center gap-2 pr-2" style={noDragStyle}>
          <Button
            type="button"
            size="sm"
            disabled={launching !== null || running !== null}
            onClick={() => handleLaunch('vanilla')}
          >
            <LaunchIcon className="h-5 w-5 text-parchment" />
            <span>
              {launching === 'vanilla'
                ? 'Restoring…'
                : running === 'vanilla'
                  ? 'Running…'
                  : 'Launch Vanilla'}
            </span>
          </Button>
          <Button
            type="button"
            size="sm"
            variant="primary"
            disabled={launching !== null || running !== null}
            onClick={() => handleLaunch('modded')}
          >
            <LaunchIcon className="h-5 w-5 text-parchment" />
            <span>
              {launching === 'modded'
                ? 'Applying…'
                : running === 'modded'
                  ? 'Running…'
                  : 'Launch Modded'}
            </span>
          </Button>
        </div>

        {launchError ? (
          <span className="flex items-center gap-2 text-xs text-destructive" role="alert">
            <span className="truncate max-w-[300px]">{launchError}</span>
            <CopyButton value={`Launch error: ${launchError}`} />
          </span>
        ) : null}
        <div className="flex items-center gap-2" style={noDragStyle}>
          <StatPill value={enabled} label="enabled" />
          <StatPill value={disabled} label="disabled" />
          {outdated > 0 ? <StatPill value={outdated} label="updates" tone="gilt" /> : null}
          {conflictCount > 0 ? (
            <Link to="/conflicts" className="inline-flex items-center gap-1">
              <AlertTriangle className="h-4 w-4 text-crimson" />
              <StatPill value={conflictCount} label="conflicts" tone="crimson" />
            </Link>
          ) : null}
          <StatPill label="command" value={shortcutLabel('K')} className="tracking-normal" />
        </div>
        <WindowControls />
      </div>
    </div>
  );
}

async function getAppWindow() {
  try {
    const { getCurrentWindow } = await import('@tauri-apps/api/window');
    return getCurrentWindow();
  } catch {
    return null;
  }
}

function WindowControls() {
  const { running } = useLaunchState();
  const [maximized, setMaximized] = useState(false);
  const [available, setAvailable] = useState(false);
  const [quitPromptOpen, setQuitPromptOpen] = useState(false);
  const [quitError, setQuitError] = useState<string | null>(null);
  const [quitBusy, setQuitBusy] = useState(false);

  useEffect(() => {
    let cancelled = false;
    let unlisten: (() => void) | null = null;
    (async () => {
      try {
        const aw = await getAppWindow();
        if (!aw || cancelled) return;
        setAvailable(true);
        try {
          setMaximized(await aw.isMaximized());
        } catch {
          /* ignore */
        }
        try {
          const off = await aw.onResized(async () => {
            try {
              const isMax = await aw.isMaximized();
              if (!cancelled) setMaximized(isMax);
            } catch {
              /* ignore */
            }
          });
          if (cancelled) off();
          else unlisten = off;
        } catch {
          /* ignore */
        }
      } catch (err) {
        console.warn('window controls setup failed', err);
      }
    })();
    return () => {
      cancelled = true;
      unlisten?.();
    };
  }, []);

  useEffect(() => {
    let cancelled = false;
    let unlistenClose: (() => void) | null = null;

    (async () => {
      try {
        const aw = await getAppWindow();
        if (!aw || cancelled) return;
        const off = await aw.onCloseRequested(async (event) => {
          if (running !== 'modded') return;
          event.preventDefault();
          setQuitError(null);
          setQuitPromptOpen(true);
        });
        if (cancelled) off();
        else unlistenClose = off;
      } catch (err) {
        console.warn('window close handler setup failed', err);
      }
    })();

    return () => {
      cancelled = true;
      unlistenClose?.();
    };
  }, [running]);

  const closeAnyway = async () => {
    if (quitBusy) return;
    setQuitBusy(true);
    setQuitError(null);
    try {
      await processExit(0);
      setQuitPromptOpen(false);
    } catch (e) {
      setQuitError(e instanceof Error ? e.message : String(e));
    } finally {
      setQuitBusy(false);
    }
  };

  const restoreAndQuit = async () => {
    if (quitBusy) return;
    setQuitBusy(true);
    setQuitError(null);
    try {
      const result = await restoreAll();
      if (!result || !result.ok) {
        throw new Error(result?.stderr?.trim() || result?.stdout?.trim() || 'restore failed');
      }
      await processExit(0);
      setQuitPromptOpen(false);
    } catch (e) {
      setQuitError(e instanceof Error ? e.message : String(e));
    } finally {
      setQuitBusy(false);
    }
  };

  const withWindow = async (
    action: (aw: NonNullable<Awaited<ReturnType<typeof getAppWindow>>>) => Promise<void>,
    label: string,
  ) => {
    const aw = await getAppWindow();
    if (!aw) {
      console.warn(`Tauri window API not available (${label})`);
      return;
    }
    try {
      await action(aw);
      return true;
    } catch (e) {
      console.warn(`${label} failed`, e);
      return false;
    }
  };

  const doMinimize = () => withWindow((aw) => aw.minimize(), 'minimize');
  const doClose = () => {
    void (async () => {
      if (running === 'modded') {
        setQuitError(null);
        setQuitPromptOpen(true);
        return;
      }
      await processExit(0);
    })();
  };
  const doToggleMax = () =>
    withWindow(async (aw) => {
      const isMax = await aw.isMaximized();
      if (isMax) {
        await aw.unmaximize();
        setMaximized(false);
      } else {
        await aw.maximize();
        setMaximized(true);
      }
    }, 'maximize');

  const RestoreIcon = ({ className }: { className?: string }) => (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.6"
      strokeLinecap="round"
      strokeLinejoin="round"
      className={className}
      aria-hidden="true"
    >
      <rect x="6" y="6" width="12" height="12" rx="1.2" />
      <path d="M9 6V4h8v8h-2" />
    </svg>
  );

  if (!available) return null;

  return (
    <div className="window-controls ml-3 flex items-center gap-2" style={noDragStyle}>
      <button
        type="button"
        title="Minimize"
        onClick={doMinimize}
        aria-label="Minimize"
        className="wc-btn wc-minimize"
      >
        <WindowMinimizeIcon className="h-4 w-4 text-parchment" />
      </button>
      <button
        type="button"
        title={maximized ? 'Restore' : 'Maximize'}
        onClick={doToggleMax}
        aria-label={maximized ? 'Restore' : 'Maximize'}
        className="wc-btn wc-maximize"
      >
        {maximized ? (
          <RestoreIcon className="h-4 w-4 text-parchment" />
        ) : (
          <WindowMaximizeIcon className="h-4 w-4 text-parchment" />
        )}
      </button>
      <button
        type="button"
        title="Close"
        onClick={doClose}
        aria-label="Close"
        className="wc-btn wc-close"
      >
        <WindowCloseIcon className="h-4 w-4 text-crimson" />
      </button>

      {quitPromptOpen
        ? createPortal(
            <div className="fixed inset-0 z-[70] flex items-center justify-center p-4 animate-fade-in">
              <div
                className="absolute inset-0 bg-pitch/80"
                onClick={() => !quitBusy && setQuitPromptOpen(false)}
              />
              <div className="grimoire-card relative w-[min(520px,92vw)] p-5">
                <h3 className="font-fraktur text-xl text-parchment">Quit with active overrides?</h3>
                <p className="font-serif-italic mt-2 text-ash">
                  Ravenswatch is still running with modded files applied. Quitting now leaves those
                  overrides in place until you restore them.
                </p>
                <div className="mt-4 flex flex-nowrap justify-end gap-2">
                  <button
                    type="button"
                    onClick={() => setQuitPromptOpen(false)}
                    disabled={quitBusy}
                    className="whitespace-nowrap border border-border px-3 py-1.5 text-ash hover:text-parchment disabled:opacity-60"
                  >
                    Cancel
                  </button>
                  <button
                    type="button"
                    onClick={() => void restoreAndQuit()}
                    disabled={quitBusy}
                    className="whitespace-nowrap border border-gilt/60 bg-gilt/20 px-3 py-1.5 text-parchment hover:bg-gilt/30 disabled:opacity-60"
                  >
                    Restore & quit
                  </button>
                  <button
                    type="button"
                    onClick={() => void closeAnyway()}
                    disabled={quitBusy}
                    className="whitespace-nowrap border border-crimson bg-crimson/80 px-3 py-1.5 text-parchment hover:bg-oxblood disabled:opacity-60"
                  >
                    Quit anyway
                  </button>
                </div>
                {quitError ? <p className="mt-3 text-sm text-crimson">{quitError}</p> : null}
              </div>
            </div>,
            document.body,
          )
        : null}
    </div>
  );
}

function RootLayout() {
  const location = useLocation();
  const mainRef = useRef<HTMLElement | null>(null);
  const [launching, setLaunching] = useState<LaunchMode | null>(null);
  const [running, setRunning] = useState<LaunchMode | null>(null);
  const [launchError, setLaunchError] = useState<string | null>(null);
  const launchState = useMemo(
    () => ({
      launching,
      running,
      launchError,
      setLaunching,
      setRunning,
      setLaunchError,
    }),
    [launchError, launching, running],
  );

  // biome-ignore lint/correctness/useExhaustiveDependencies: re-scroll on navigation
  useEffect(() => {
    mainRef.current?.scrollTo({ top: 0, left: 0 });
  }, [location.pathname]);

  return (
    <ToastProvider>
      <DialogProvider>
        <LaunchStateContext.Provider value={launchState}>
          <div className="flex h-screen w-screen overflow-hidden">
            <aside className="surface-grain flex w-72 flex-col border-r border-border">
              <div className="px-5 pt-5 pb-4">
                <div className="flex items-center gap-3">
                  <div>
                    <img
                      src="/logo.png"
                      alt="Ravenswatch Mod Manager"
                      className="h-14 w-14 rounded-md object-cover"
                    />
                  </div>
                  <div>
                    <h1 className="font-fraktur text-3xl leading-none text-parchment">RSMM</h1>
                    <p className="font-serif-italic mt-1 text-sm text-ash">
                      Ravenswatch Mod Manager
                    </p>
                  </div>
                </div>
              </div>

              <div className="px-4 pb-3">
                <ProfilePopover />
              </div>

              <nav className="flex flex-1 flex-col gap-1 px-2 py-2">
                {NAV.map((n) => (
                  <NavLink key={n.to} {...n} />
                ))}
              </nav>
              <AccountStrip />
              <div className="px-4 pb-4">
                <PromotedBanner vertical />
              </div>
            </aside>

            <div className="flex min-h-0 flex-1 flex-col overflow-hidden">
              <StatusStrip />
              <UpdaterBanner />
              <main ref={mainRef} className="min-h-0 flex-1 overflow-y-auto px-6 py-6 md:px-8">
                <div className="mx-auto w-full max-w-7xl animate-page-in">
                  <Outlet />
                </div>
              </main>
            </div>

            <CommandPalette />
          </div>
        </LaunchStateContext.Provider>
      </DialogProvider>
    </ToastProvider>
  );
}
