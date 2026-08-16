import type { QueryClient } from '@tanstack/react-query';
import { Link, Outlet, createRootRouteWithContext, useLocation } from '@tanstack/react-router';
import { AlertTriangle } from 'lucide-react';
import { FlaskConical, ScrollText, Terminal } from 'lucide-react';
import type { CSSProperties } from 'react';
import { useEffect, useMemo, useRef, useState } from 'react';
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
import { LaunchProvider, useLaunch } from '../components/launch';
import { ProfilePopover } from '../components/profile-popover';
import { DialogProvider, ToastProvider } from '../components/toast';
import { UpdaterBanner } from '../components/updater';
import { shortcutLabel } from '../lib/platform';
import { quitApp } from '../lib/quit';
import { restoreAll } from '../lib/rsmm';
import { activeProfile, detectConflicts, isEnabledIn, outdatedCount, useApp } from '../store';

export const Route = createRootRouteWithContext<{ queryClient: QueryClient }>()({
  component: RootLayout,
});

interface Nav {
  to:
    | '/'
    | '/browse'
    | '/profiles'
    | '/conflicts'
    | '/author'
    | '/settings'
    | '/commands'
    | '/log'
    | '/about';
  icon: React.ComponentType<{ className?: string }>;
  label: string;
}

const CONFLICTS_NAV: Nav = { to: '/conflicts', icon: ConflictsIcon, label: 'Conflicts' };

const NAV: Nav[] = [
  { to: '/', icon: LibraryIcon, label: 'Library' },
  { to: '/browse', icon: BrowseIcon, label: 'Browse' },
  { to: '/profiles', icon: ProfilesIcon, label: 'Profiles' },
  // /author is dev-only — cooked-asset inspector, not part of the
  // public client. Visible only in dev builds; route still resolves via
  // direct URL in case a dev pins it for local testing.
  ...(import.meta.env.DEV
    ? ([{ to: '/author' as const, icon: FlaskConical, label: 'Author' }] satisfies Nav[])
    : []),
  { to: '/settings', icon: SettingsIcon, label: 'Settings' },
  { to: '/commands', icon: Terminal, label: 'Commands' },
  { to: '/log', icon: ScrollText, label: 'Log' },
  { to: '/about', icon: AboutIcon, label: 'About' },
];

/**
 * Conflicts is a problem page: it only ever has something to say when two
 * enabled mods collide. Parking it permanently in the sidebar advertised a
 * problem that usually isn't there, so it appears only when the active
 * profile actually has conflicts — or while it is the open route, so the
 * entry cannot vanish out from under the page you are reading.
 */
function useNav(): Nav[] {
  const profile = useApp(activeProfile);
  const location = useLocation();
  const conflictCount = useMemo(() => detectConflicts(profile).length, [profile]);
  return useMemo(() => {
    if (conflictCount === 0 && location.pathname !== '/conflicts') return NAV;
    const items = [...NAV];
    // Slot it back where it used to live: after Profiles.
    const at = items.findIndex((n) => n.to === '/profiles');
    items.splice(at + 1, 0, CONFLICTS_NAV);
    return items;
  }, [conflictCount, location.pathname]);
}

type AppRegionStyle = CSSProperties & { WebkitAppRegion?: 'drag' | 'no-drag' };

const dragStyle: AppRegionStyle = { WebkitAppRegion: 'drag' };
const noDragStyle: AppRegionStyle = { WebkitAppRegion: 'no-drag' };

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
  const { launching, running, launchError, busy, launch } = useLaunch();
  const profile = useApp(activeProfile);
  const installed = useApp((s) => s.installed);
  const localMods = useApp((s) => s.localMods);
  const enabled = profile.loadOrder.filter(
    (id) => localMods[id] && isEnabledIn(profile, id),
  ).length;
  const disabled = profile.loadOrder.length - enabled;
  const conflictCount = useMemo(() => detectConflicts(profile).length, [profile]);
  const outdated = useMemo(() => outdatedCount(installed), [installed]);

  return (
    <div className="surface-grain flex items-center justify-between gap-3 border-b border-border px-3 py-2 backdrop-blur-sm">
      <div className="flex items-center gap-4" style={dragStyle}>
        <span className="font-fraktur text-lg text-parchment">Ravenswatch Mod Manager</span>
      </div>

      <div className="flex items-center gap-2">
        <div className="flex items-center gap-2 pr-2" style={noDragStyle}>
          <Button type="button" size="sm" disabled={busy} onClick={() => void launch('vanilla')}>
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
            disabled={busy}
            onClick={() => void launch('modded')}
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
  const { running } = useLaunch();
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
      await quitApp();
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
      await quitApp();
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
      await quitApp();
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
  const nav = useNav();
  const mainRef = useRef<HTMLElement | null>(null);

  // biome-ignore lint/correctness/useExhaustiveDependencies: re-scroll on navigation
  useEffect(() => {
    mainRef.current?.scrollTo({ top: 0, left: 0 });
  }, [location.pathname]);

  return (
    <ToastProvider>
      <DialogProvider>
        <LaunchProvider>
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
                {nav.map((n) => (
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
              <main
                ref={mainRef}
                className="rsmm-main min-h-0 flex-1 overflow-y-auto px-6 py-6 md:px-8"
              >
                <div className="mx-auto w-full max-w-7xl animate-page-in">
                  <Outlet />
                </div>
              </main>
            </div>

            <CommandPalette />
          </div>
        </LaunchProvider>
      </DialogProvider>
    </ToastProvider>
  );
}
