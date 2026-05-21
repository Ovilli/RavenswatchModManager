import type { QueryClient } from '@tanstack/react-query';
import { createRootRouteWithContext, Link, Outlet } from '@tanstack/react-router';
import { AlertTriangle } from 'lucide-react';
import { WindowMinimizeIcon } from '../components/icons/WindowMinimizeIcon';
import { WindowMaximizeIcon } from '../components/icons/WindowMaximizeIcon';
import { WindowCloseIcon } from '../components/icons/WindowCloseIcon';
import type { CSSProperties } from 'react';
import { useMemo, useState, useEffect } from 'react';
import { AboutIcon } from '../components/icons/AboutIcon';
import { BrowseIcon } from '../components/icons/BrowseIcon';
import { ConflictsIcon } from '../components/icons/ConflictsIcon';
import { LibraryIcon } from '../components/icons/LibraryIcon';
import { ProfilesIcon } from '../components/icons/ProfilesIcon';
import { SettingsIcon } from '../components/icons/SettingsIcon';
import { LaunchIcon } from '../components/icons/LaunchIcon';
import { Button, Crest, StatPill } from '../components/chrome';
import { runVanilla, runModded } from '../lib/rsmm';
import PromotedBanner from '../components/PromotedBanner';
import { CommandPalette } from '../components/command-palette';
import { ProfilePopover } from '../components/profile-popover';
import { activeProfile, detectConflicts, outdatedCount, useApp } from '../store';

export const Route = createRootRouteWithContext<{ queryClient: QueryClient }>()({
  component: RootLayout,
});

interface Nav {
  to: '/' | '/browse' | '/profiles' | '/conflicts' | '/settings' | '/about';
  icon: React.ComponentType<{ className?: string }>;
  label: string;
}

const NAV: Nav[] = [
  { to: '/', icon: LibraryIcon, label: 'Library' },
  { to: '/browse', icon: BrowseIcon, label: 'Browse' },
  { to: '/profiles', icon: ProfilesIcon, label: 'Profiles' },
  { to: '/conflicts', icon: ConflictsIcon, label: 'Conflicts' },
  { to: '/settings', icon: SettingsIcon, label: 'Settings' },
  { to: '/about', icon: AboutIcon, label: 'About' },
];

type AppRegionStyle = CSSProperties & { WebkitAppRegion?: 'drag' | 'no-drag' };

const dragStyle: AppRegionStyle = { WebkitAppRegion: 'drag' };
const noDragStyle: AppRegionStyle = { WebkitAppRegion: 'no-drag' };

function NavLink({ to, icon: Icon, label }: Nav) {
  return (
    <Link
      to={to}
      className="nav-link-grim group"
      activeProps={{
        'data-active': 'true',
      }}
      inactiveProps={{
        'data-active': 'false',
      }}
    >
      <Icon className="nav-icon" />
      <span className="font-serif-italic text-base">{label}</span>
    </Link>
  );
}

function StatusStrip() {
  const profile = useApp(activeProfile);
  const installed = useApp((s) => s.installed);
  const profiles = useApp((s) => s.profiles);
  const enabled = profile.loadOrder.filter((id) => !profile.disabled.has(id)).length;
  const disabled = profile.loadOrder.length - enabled;
  const conflictCount = useMemo(() => detectConflicts(profile).length, [profile]);
  const outdated = useMemo(() => outdatedCount(installed), [installed]);
  const [launching, setLaunching] = useState<'vanilla' | 'modded' | null>(null);
  const [launchError, setLaunchError] = useState<string | null>(null);

  const handleLaunch = async (mode: 'vanilla' | 'modded') => {
    setLaunching(mode);
    setLaunchError(null);
    try {
      const fn = mode === 'vanilla' ? runVanilla : runModded;
      const result = await fn();
      if (!result || !result.ok) {
        setLaunchError(`${mode} launch failed (exit ${result?.code ?? 'unknown'})`);
      }
    } catch (e) {
      setLaunchError(String(e));
    } finally {
      setLaunching(null);
    }
  };

  return (
    <div className="surface-grain flex items-center justify-between gap-3 border-b border-border px-3 py-2 backdrop-blur-sm">
      <div className="flex items-center gap-4" style={dragStyle}>
        <span className="font-fraktur text-lg text-parchment">Ravenswatch Mod Manager</span>
        <span className="font-serif-italic text-ash">
          {profile.name} <span className="text-ash/60">·</span> {profiles.length} profiles
        </span>
      </div>

      <div className="flex items-center gap-2">
        <div className="flex items-center gap-2 pr-2" style={noDragStyle}>
          <Button
            type="button"
            size="sm"
            disabled={launching !== null}
            onClick={() => handleLaunch('vanilla')}
          >
            <LaunchIcon className="h-5 w-5 text-parchment" />
            <span>{launching === 'vanilla' ? 'Restoring…' : 'Launch Vanilla'}</span>
          </Button>
          <Button
            type="button"
            size="sm"
            variant="primary"
            disabled={launching !== null}
            onClick={() => handleLaunch('modded')}
          >
            <LaunchIcon className="h-5 w-5 text-parchment" />
            <span>{launching === 'modded' ? 'Applying…' : 'Launch Modded'}</span>
          </Button>
        </div>

        {launchError ? (
          <span className="text-xs text-destructive">{launchError}</span>
        ) : null}
        <div className="flex items-center gap-2" style={noDragStyle}>
          <StatPill value={enabled} label="enabled" />
          <StatPill value={disabled} label="disabled" />
          {outdated > 0 ? (
            <StatPill value={outdated} label="updates" tone="gilt" />
          ) : null}
          {conflictCount > 0 ? (
            <Link
              to="/conflicts"
              className="inline-flex items-center gap-1"
            >
              <AlertTriangle className="h-4 w-4 text-crimson" />
              <StatPill
                value={conflictCount}
                label="conflicts"
                tone="crimson"
              />
            </Link>
          ) : null}
          <StatPill label="command" value="CMD+K" className="tracking-normal" />
        </div>
        <WindowControls />
      </div>
    </div>
  );
}

function WindowControls() {
  const [maximized, setMaximized] = useState(false);

  useEffect(() => {
    let mounted = true;
    (async () => {
      try {
        const { getCurrentWindow } = await import('@tauri-apps/api/window');
        const isMax = await getCurrentWindow().isMaximized();
        if (mounted) setMaximized(isMax);
      } catch (e) {
        // not running in Tauri - ignore
      }
      // diagnostic imports removed
    })();
    return () => {
      mounted = false;
    };
  }, []);

  async function getAppWindow() {
    try {
      const { getCurrentWindow } = await import('@tauri-apps/api/window');
      const { WebviewWindow } = await import('@tauri-apps/api/webviewWindow');
      // debug
      // diagnostic logs removed
      const appWindow = getCurrentWindow();
      if (appWindow) return appWindow;
      return WebviewWindow.getCurrent();
    } catch (err) {
      // import failure logged elsewhere; swallow here
      return null;
    }
  }

  const doMinimize = async () => {
    const aw = await getAppWindow();
    if (!aw) {
      console.warn('Tauri window API not available (minimize)');
      alert('Window controls are only available in the desktop app.');
      return;
    }
    try {
      await aw.minimize();
    } catch (e) {
      console.warn('minimize failed', e);
    }
  };

  const doToggleMax = async () => {
    const aw = await getAppWindow();
    if (!aw) {
      console.warn('Tauri window API not available (maximize)');
      alert('Window controls are only available in the desktop app.');
      return;
    }
    try {
      const isMax = await aw.isMaximized();
      if (isMax) {
        await aw.unmaximize();
        setMaximized(false);
      } else {
        await aw.maximize();
        setMaximized(true);
      }
    } catch (e) {
      console.warn('toggleMax failed', e);
    }
  };

  const doClose = async () => {
    const aw = await getAppWindow();
    if (!aw) {
      console.warn('Tauri window API not available (close)');
      alert('Window controls are only available in the desktop app.');
      return;
    }
    try {
      await aw.close();
    } catch (e) {
      console.warn('close failed', e);
    }
  };

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

  return (
    <div className="window-controls ml-3 flex items-center gap-2" style={noDragStyle}>
      <button type="button" title="Minimize" onClick={doMinimize} aria-label="Minimize" className="wc-btn wc-minimize">
        <WindowMinimizeIcon className="h-4 w-4 text-parchment" />
      </button>
      <button
        type="button"
        title={maximized ? 'Restore' : 'Maximize'}
        onClick={doToggleMax}
        aria-label={maximized ? 'Restore' : 'Maximize'}
        className="wc-btn wc-maximize"
      >
        {maximized ? <RestoreIcon className="h-4 w-4 text-parchment" /> : <WindowMaximizeIcon className="h-4 w-4 text-parchment" />}
      </button>
      <button type="button" title="Close" onClick={doClose} aria-label="Close" className="wc-btn wc-close">
        <WindowCloseIcon className="h-4 w-4 text-crimson" />
      </button>
    </div>
  );
}

function RootLayout() {
  return (
    <div className="flex h-screen w-screen overflow-hidden">
      <aside className="surface-grain flex w-72 flex-col border-r border-border">
        <div className="px-5 pt-5 pb-4">
          <div className="flex items-center gap-3">
            <div className="animate-float">
              <Crest monogram="R" size="sm" />
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
        <div className="px-4 pb-4">
          <PromotedBanner vertical />
        </div>
      </aside>

      <div className="flex flex-1 flex-col overflow-hidden">
        <StatusStrip />
        <main className="flex-1 overflow-y-auto px-6 py-6 md:px-8">
          <div className="mx-auto w-full max-w-7xl animate-page-in">
            <Outlet />
          </div>
        </main>
      </div>

      <CommandPalette />
    </div>
  );
}
