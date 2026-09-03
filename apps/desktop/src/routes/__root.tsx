import type { QueryClient } from '@tanstack/react-query';
import { Link, Outlet, createRootRouteWithContext, useLocation } from '@tanstack/react-router';
import { AlertTriangle } from 'lucide-react';
import { PanelLeftClose, PanelLeftOpen, ScrollText, Terminal, X } from 'lucide-react';
import type { CSSProperties } from 'react';
import { useEffect, useMemo, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import PromotedBanner from '../components/PromotedBanner';
import { AccountStrip } from '../components/account-strip';
import { FirstRunDialogs } from '../components/changelog-dialog';
import { Button, CopyButton, StatPill, useModalChrome } from '../components/chrome';
import { CommandPalette } from '../components/command-palette';
import { BrowseIcon } from '../components/icons/BrowseIcon';
import { ConflictsIcon } from '../components/icons/ConflictsIcon';
import { LaunchIcon } from '../components/icons/LaunchIcon';
import { LibraryIcon } from '../components/icons/LibraryIcon';
import { ProfilesIcon } from '../components/icons/ProfilesIcon';
import { SettingsIcon } from '../components/icons/SettingsIcon';
import { WindowCloseIcon } from '../components/icons/WindowCloseIcon';
import { WindowMaximizeIcon } from '../components/icons/WindowMaximizeIcon';
import { WindowMinimizeIcon } from '../components/icons/WindowMinimizeIcon';
import { WindowRestoreIcon } from '../components/icons/WindowRestoreIcon';
import { LaunchProvider, useLaunch } from '../components/launch';
import { ProfilePopover } from '../components/profile-popover';
import { DialogProvider, ToastProvider } from '../components/toast';
import { UpdaterBanner, VersionFooter } from '../components/updater';
import { msg } from '../lib/i18n';
import { useT } from '../lib/i18n-react';
import { shortcutLabel } from '../lib/platform';
import { quitApp } from '../lib/quit';
import { restoreAll } from '../lib/rsmm';
import { attachSmoothWheel } from '../lib/smooth-scroll';
import { activeProfile, detectConflicts, isEnabledIn, outdatedCount, useApp } from '../store';

export const Route = createRootRouteWithContext<{ queryClient: QueryClient }>()({
  component: RootLayout,
});

interface Nav {
  to: '/' | '/browse' | '/profiles' | '/conflicts' | '/settings' | '/commands' | '/log';
  icon: React.ComponentType<{ className?: string }>;
  label: string;
}

// Labels are declared in English and translated at render (`NavLink` calls
// `t(label)`): this table is module scope, where there is no active locale and
// nothing to re-render when it changes.
const CONFLICTS_NAV: Nav = { to: '/conflicts', icon: ConflictsIcon, label: msg('Conflicts') };

const NAV: Nav[] = [
  { to: '/', icon: LibraryIcon, label: msg('Library') },
  { to: '/browse', icon: BrowseIcon, label: msg('Browse') },
  { to: '/profiles', icon: ProfilesIcon, label: msg('Profiles') },
  // /author (the cooked-asset inspector) has no sidebar entry — it is a dev
  // tool, not a destination. The route still resolves by direct URL.
  { to: '/commands', icon: Terminal, label: msg('Commands') },
  { to: '/log', icon: ScrollText, label: msg('Log') },
];

/**
 * Pinned to the foot of the sidebar rather than sitting in the list.
 *
 * Settings is not a destination you browse between — it is where you go to
 * change how the rest behaves, and About now lives inside it as a tab. Keeping
 * it out of the run of content pages, down by the collapse control, says that.
 */
const SETTINGS_NAV: Nav = { to: '/settings', icon: SettingsIcon, label: msg('Settings') };

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

function NavLink({ to, icon: Icon, label: source, collapsed }: Nav & { collapsed: boolean }) {
  const t = useT();
  const installed = useApp((s) => s.installed);
  const outdated = useMemo(() => (to === '/' ? outdatedCount(installed) : 0), [to, installed]);
  const label = t(source);
  const updates =
    outdated > 0
      ? t.n(outdated, '{n} mod with an available update', '{n} mods with available updates')
      : null;
  return (
    <Link
      to={to}
      className={collapsed ? 'nav-link-grim group justify-center' : 'nav-link-grim group'}
      // With the label hidden the icon is the only thing left, and an icon is
      // not a name: `aria-label` keeps the link readable to a screen reader and
      // `title` gives everyone else a tooltip for the same text.
      aria-label={collapsed ? label : undefined}
      title={collapsed ? label : undefined}
      activeProps={{ 'data-active': 'true' }}
      inactiveProps={{ 'data-active': 'false' }}
    >
      <Icon className="nav-icon" />
      {collapsed ? null : <span className="font-serif-italic text-base">{label}</span>}
      {updates && !collapsed ? (
        <span
          className="ml-auto inline-flex h-5 min-w-[1.25rem] items-center justify-center rounded-full bg-gilt/20 px-1.5 font-mono text-[11px] font-semibold text-gilt"
          title={updates}
        >
          {outdated}
        </span>
      ) : null}
    </Link>
  );
}

function StatusStrip() {
  const t = useT();
  const { launching, running, launchError, busy, launch, clearError } = useLaunch();
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
    // `relative z-30`: `.surface-grain` sets `backdrop-filter`, which makes this
    // strip a stacking context with `z-index: auto` — so its profile menu, no
    // matter how high its own z-index, is confined here and painted before the
    // `.grimoire-card`s below (they are `backdrop-filter` stacking contexts too,
    // and later in the DOM). An explicit z-index lifts the whole strip instead.
    <div className="surface-grain relative z-30 flex items-center justify-between gap-3 border-b border-border px-3 py-2 backdrop-blur-sm">
      {/* The left half yields space, the right half does not: the launch
          buttons must never be squeezed, so the profile name truncates first.
          It keeps `dragStyle` even though it holds no text of its own — the
          empty run to the left of the picker is the window's drag handle. */}
      <div className="flex min-w-0 items-center gap-3" style={dragStyle}>
        {/* `no-drag`, or the frameless window swallows the click. */}
        <div className="min-w-0" style={noDragStyle}>
          <ProfilePopover compact />
        </div>
      </div>

      <div className="flex shrink-0 items-center gap-2">
        <div className="flex items-center gap-2 pr-2" style={noDragStyle}>
          <Button
            type="button"
            size="sm"
            disabled={busy}
            /* A floor, because the label is not fixed: it swaps to "Restoring…"
               and "Running…" as a launch proceeds, and a button that resizes
               mid-launch shoves the one beside it. The floor clears the longest
               label in every typeface preset, so all three states render at the
               same width; a preset wide enough to exceed it grows rather than
               clipping. Shared by both buttons so the pair reads as a pair. */
            className="min-w-[11rem]"
            onClick={() => void launch('vanilla')}
          >
            <LaunchIcon className="h-5 w-5 text-parchment" />
            <span>
              {launching === 'vanilla'
                ? t('Restoring…')
                : running === 'vanilla'
                  ? t('Running…')
                  : t('Launch Vanilla')}
            </span>
          </Button>
          <Button
            type="button"
            size="sm"
            variant="primary"
            disabled={busy}
            className="min-w-[11rem]"
            onClick={() => void launch('modded')}
          >
            <LaunchIcon className="h-5 w-5 text-parchment" />
            <span>
              {launching === 'modded'
                ? t('Applying…')
                : running === 'modded'
                  ? t('Running…')
                  : t('Launch Modded')}
            </span>
          </Button>
        </div>

        {launchError ? (
          <span className="flex items-center gap-2 text-xs text-destructive" role="alert">
            <span className="truncate max-w-[300px]">{launchError}</span>
            <CopyButton value={t('Launch error: {error}', { error: launchError })} />
            {/* A failed launch used to pin its message into the status strip
                until the next launch attempt: `clearError` existed with no
                caller anywhere. */}
            <button
              type="button"
              onClick={clearError}
              title={t('Dismiss')}
              aria-label={t('Dismiss the launch error')}
              className="shrink-0 text-ash transition-colors duration-150 hover:text-parchment"
            >
              <X className="h-3.5 w-3.5" aria-hidden="true" />
            </button>
          </span>
        ) : null}
        {/* Hidden rather than squashed below `lg`. The cluster is `shrink-0`
            so the launch buttons keep their size, which means something has to
            give when the window is narrow — and a mod count is the most
            expendable thing in this row. */}
        <div className="hidden items-center gap-2 lg:flex" style={noDragStyle}>
          <StatPill value={enabled} label={t('enabled')} />
          <StatPill value={disabled} label={t('disabled')} />
          {outdated > 0 ? <StatPill value={outdated} label={t('updates')} tone="gilt" /> : null}
          {conflictCount > 0 ? (
            <Link to="/conflicts" className="inline-flex items-center gap-1">
              <AlertTriangle className="h-4 w-4 text-crimson" />
              <StatPill value={conflictCount} label={t('conflicts')} tone="crimson" />
            </Link>
          ) : null}
          <StatPill label={t('command')} value={shortcutLabel('K')} className="tracking-normal" />
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
  const t = useT();
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
        // CLI output is passed through untranslated — it is the sidecar's own
        // text, and mistranslating a diagnostic is worse than showing it as-is.
        throw new Error(result?.stderr?.trim() || result?.stdout?.trim() || t('restore failed'));
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

  if (!available) return null;

  return (
    <div className="window-controls ml-3 flex items-center gap-2" style={noDragStyle}>
      <button
        type="button"
        title={t('Minimize')}
        onClick={doMinimize}
        aria-label={t('Minimize')}
        className="wc-btn wc-minimize"
      >
        <WindowMinimizeIcon className="h-4 w-4 text-parchment" />
      </button>
      <button
        type="button"
        title={maximized ? t('Restore') : t('Maximize')}
        onClick={doToggleMax}
        aria-label={maximized ? t('Restore') : t('Maximize')}
        className="wc-btn wc-maximize"
      >
        {maximized ? (
          <WindowRestoreIcon className="h-4 w-4 text-parchment" />
        ) : (
          <WindowMaximizeIcon className="h-4 w-4 text-parchment" />
        )}
      </button>
      <button
        type="button"
        title={t('Close')}
        onClick={doClose}
        aria-label={t('Close')}
        className="wc-btn wc-close"
      >
        <WindowCloseIcon className="h-4 w-4 text-crimson" />
      </button>

      {quitPromptOpen ? (
        <QuitPrompt
          busy={quitBusy}
          error={quitError}
          onCancel={() => setQuitPromptOpen(false)}
          onRestoreAndQuit={() => void restoreAndQuit()}
          onQuitAnyway={() => void closeAnyway()}
        />
      ) : null}
    </div>
  );
}

function RootLayout() {
  const t = useT();
  const location = useLocation();
  const nav = useNav();
  const collapsed = useApp((s) => s.settings.sidebarCollapsed);
  const update = useApp((s) => s.updateSettings);
  const mainRef = useRef<HTMLElement | null>(null);

  // biome-ignore lint/correctness/useExhaustiveDependencies: re-scroll on navigation
  useEffect(() => {
    mainRef.current?.scrollTo({ top: 0, left: 0 });
  }, [location.pathname]);

  // The webview scrolls a mouse notch as one teleport, which is what makes the
  // app feel harder than the same page in a browser. Delegated from the
  // document so dialogs, the log view and every list get the same feel as the
  // main area — including ones added later. Trackpads are untouched.
  useEffect(() => attachSmoothWheel(document), []);

  return (
    <ToastProvider>
      <DialogProvider>
        <LaunchProvider>
          <div className="flex h-screen w-screen overflow-hidden">
            <aside
              className={`surface-grain flex shrink-0 flex-col border-r border-border ${
                collapsed ? 'w-20' : 'w-72'
              }`}
            >
              <div className={collapsed ? 'px-3 pt-5 pb-4' : 'px-5 pt-5 pb-4'}>
                <div className="flex items-center justify-center">
                  <img
                    src="/logo.png"
                    alt="Ravenswatch Mod Manager"
                    className={`shrink-0 rounded-md object-cover ${
                      collapsed ? 'h-10 w-10' : 'h-14 w-14'
                    }`}
                  />
                </div>
              </div>

              <nav className="flex flex-1 flex-col gap-1 px-2 py-2">
                {nav.map((n) => (
                  <NavLink key={n.to} {...n} collapsed={collapsed} />
                ))}
              </nav>

              <div className="border-t border-border/60 px-2 pt-2 pb-1">
                <NavLink {...SETTINGS_NAV} collapsed={collapsed} />
              </div>

              <div className={collapsed ? 'px-2 pb-2' : 'px-4 pb-2'}>
                <button
                  type="button"
                  onClick={() => update({ sidebarCollapsed: !collapsed })}
                  aria-label={
                    collapsed ? t('Expand the sidebar') : t('Collapse the sidebar to icons')
                  }
                  title={collapsed ? t('Expand the sidebar') : t('Collapse the sidebar to icons')}
                  aria-pressed={collapsed}
                  className={`flex w-full items-center gap-2 rounded border border-transparent px-2 py-1.5 text-ash hover:border-border hover:text-parchment ${
                    collapsed ? 'justify-center' : ''
                  }`}
                >
                  {collapsed ? (
                    <PanelLeftOpen className="h-4 w-4" aria-hidden />
                  ) : (
                    <PanelLeftClose className="h-4 w-4" aria-hidden />
                  )}
                  {collapsed ? null : (
                    <span className="font-mono text-xs">{t('Collapse sidebar')}</span>
                  )}
                </button>
              </div>

              {/* Wide controls with nothing meaningful to show at 5rem, so
                  they step aside rather than being squeezed into an unreadable
                  version of themselves. */}
              {collapsed ? null : (
                <>
                  <AccountStrip />
                  <div className="px-4 pb-4">
                    <PromotedBanner vertical />
                  </div>
                </>
              )}
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
            <FirstRunDialogs />
            <VersionFooter />
          </div>
        </LaunchProvider>
      </DialogProvider>
    </ToastProvider>
  );
}

/**
 * Quit while modded files are still applied.
 *
 * Its own component so `useModalChrome`'s focus move runs when the PROMPT
 * mounts, not when the window-controls strip does. Portalled to the body,
 * which is why the focus move matters: the overlay comes after the whole app
 * in DOM order, so without it the first tab stop is the sidebar.
 */
function QuitPrompt({
  busy,
  error,
  onCancel,
  onRestoreAndQuit,
  onQuitAnyway,
}: {
  busy: boolean;
  error: string | null;
  onCancel: () => void;
  onRestoreAndQuit: () => void;
  onQuitAnyway: () => void;
}) {
  const t = useT();
  const cancelRef = useRef<HTMLButtonElement>(null);
  // Escape means "do not quit" — the safe answer, and the one the backdrop
  // click already gave. It is ignored mid-restore, where cancelling would
  // leave the install half-restored.
  const onKeyDown = useModalChrome(cancelRef, busy ? undefined : onCancel);

  return createPortal(
    <dialog
      open
      aria-labelledby="quit-prompt-title"
      className="fixed inset-0 z-[70] flex items-center justify-center p-4 animate-fade-in"
      onKeyDown={onKeyDown}
    >
      <div className="absolute inset-0 bg-pitch/80" onClick={() => !busy && onCancel()} />
      <div className="grimoire-card relative w-[min(520px,92vw)] p-5">
        <h3 id="quit-prompt-title" className="font-fraktur text-xl text-parchment">
          {t('Quit with active overrides?')}
        </h3>
        <p className="font-serif-italic mt-2 text-ash">
          {t(
            'Ravenswatch is still running with modded files applied. Quitting now leaves those overrides in place until you restore them.',
          )}
        </p>
        <div className="mt-4 flex flex-nowrap justify-end gap-2">
          <button
            type="button"
            ref={cancelRef}
            onClick={onCancel}
            disabled={busy}
            className="whitespace-nowrap border border-border px-3 py-1.5 text-ash hover:text-parchment disabled:opacity-60"
          >
            {t('Cancel')}
          </button>
          <button
            type="button"
            onClick={onRestoreAndQuit}
            disabled={busy}
            className="whitespace-nowrap border border-gilt/60 bg-gilt/20 px-3 py-1.5 text-parchment hover:bg-gilt/30 disabled:opacity-60"
          >
            {t('Restore & quit')}
          </button>
          <button
            type="button"
            onClick={onQuitAnyway}
            disabled={busy}
            className="whitespace-nowrap border border-crimson bg-crimson/80 px-3 py-1.5 text-parchment hover:bg-oxblood disabled:opacity-60"
          >
            {t('Quit anyway')}
          </button>
        </div>
        {error ? (
          <p className="mt-3 text-sm text-crimson" role="alert">
            {error}
          </p>
        ) : null}
      </div>
    </dialog>,
    document.body,
  );
}
