import type { QueryClient } from '@tanstack/react-query';
import { Link, Outlet, createRootRouteWithContext, useLocation } from '@tanstack/react-router';
import { ArrowUp, ChevronDown, PanelLeftClose, PanelLeftOpen, Search, X } from 'lucide-react';
import { Fragment, useEffect, useId, useMemo, useRef, useState } from 'react';
import { AccountStrip } from '../components/account-strip';
import { FirstRunDialogs } from '../components/changelog-dialog';
import { ChannelStatusBanner } from '../components/channel-status-banner';
import { CopyButton } from '../components/chrome';
import { CommandPalette } from '../components/command-palette';
import { BrowseIcon } from '../components/icons/BrowseIcon';
import { ConflictsIcon } from '../components/icons/ConflictsIcon';
import { LaunchIcon } from '../components/icons/LaunchIcon';
import { LibraryIcon } from '../components/icons/LibraryIcon';
import { SettingsIcon } from '../components/icons/SettingsIcon';
import { WindowCloseIcon } from '../components/icons/WindowCloseIcon';
import { WindowMaximizeIcon } from '../components/icons/WindowMaximizeIcon';
import { WindowMinimizeIcon } from '../components/icons/WindowMinimizeIcon';
import { WindowRestoreIcon } from '../components/icons/WindowRestoreIcon';
import { LaunchProvider, useLaunch } from '../components/launch';
import { SidebarTooltip } from '../components/sidebar-tooltip';
import { StartupSelfHeal } from '../components/startup-self-heal';
import { DialogProvider, ToastProvider } from '../components/toast';
import { UpdaterBanner, VersionFooter } from '../components/updater';
import { LIBRARY_PREVIEW } from '../lib/browser-preview';
import { msg } from '../lib/i18n';
import { useT } from '../lib/i18n-react';
import { inTauri, shortcutLabel } from '../lib/platform';
import { quitApp } from '../lib/quit';
import { attachSmoothWheel } from '../lib/smooth-scroll';
import { trackMainWindow } from '../lib/window-state';
import { activeProfile, detectConflicts, isEnabledIn, outdatedCount, useApp } from '../store';

export const Route = createRootRouteWithContext<{ queryClient: QueryClient }>()({
  component: RootLayout,
});

interface Nav {
  to: '/' | '/browse' | '/conflicts' | '/settings';
  icon: React.ComponentType<{ className?: string }>;
  label: string;
}

// Labels are declared in English and translated at render (`NavLink` calls
// `t(label)`): this table is module scope, where there is no active locale and
// nothing to re-render when it changes.
const CONFLICTS_NAV: Nav = { to: '/conflicts', icon: ConflictsIcon, label: msg('Conflicts') };
const SETTINGS_NAV: Nav = { to: '/settings', icon: SettingsIcon, label: msg('Settings') };

const NAV: Nav[] = [
  { to: '/browse', icon: BrowseIcon, label: msg('Browse') },
  { to: '/', icon: LibraryIcon, label: msg('Library') },
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
    return [...NAV, CONFLICTS_NAV];
  }, [conflictCount, location.pathname]);
}

function NavLink({ to, icon: Icon, label: source, collapsed }: Nav & { collapsed: boolean }) {
  const t = useT();
  const installed = useApp((s) => s.installed);
  const profile = useApp(activeProfile);
  const localMods = useApp((s) => s.localMods);
  const activeCount = useMemo(
    () =>
      to === '/'
        ? profile.loadOrder.filter((id) => localMods[id] && isEnabledIn(profile, id)).length
        : 0,
    [to, profile, localMods],
  );
  const activeDescription = t.n(
    activeCount,
    '{n} active mod in {profile}',
    '{n} active mods in {profile}',
    { profile: profile.name },
  );
  const outdated = useMemo(() => (to === '/' ? outdatedCount(installed) : 0), [to, installed]);
  const label = t(source);
  const collapsedLabel = to === '/' ? t('Library · {n} active', { n: activeCount }) : label;
  const updates =
    outdated > 0
      ? t.n(outdated, '{n} mod with an available update', '{n} mods with available updates')
      : null;
  return (
    <Link
      to={to}
      className="nav-link-grim sidebar-nav-item group"
      aria-label={collapsed ? collapsedLabel : undefined}
      data-sidebar-tooltip={collapsed ? collapsedLabel : undefined}
      activeProps={{ 'data-active': 'true' }}
      inactiveProps={{ 'data-active': 'false' }}
    >
      <Icon className="nav-icon shrink-0" aria-hidden />
      <span
        className="sidebar-expanded-content truncate font-serif-italic text-base"
        aria-hidden={collapsed}
      >
        {label}
      </span>
      {to === '/' ? (
        <div
          className="sidebar-expanded-content ml-auto flex shrink-0 items-center gap-1.5 pr-3"
          aria-hidden={collapsed}
        >
          <span
            className={`inline-flex items-center whitespace-nowrap rounded-full px-2 py-0.5 text-xs font-medium tabular-nums text-white ${activeCount > 0 ? 'bg-gilt/15' : 'bg-parchment/5'}`}
            title={activeDescription}
          >
            {t('{n} Active', { n: activeCount })}
          </span>
          {updates ? (
            <span
              className="inline-flex items-center gap-0.5 text-xs tabular-nums text-gilt"
              title={updates}
              aria-label={updates}
            >
              <ArrowUp className="h-3 w-3" aria-hidden />
              {outdated}
            </span>
          ) : null}
        </div>
      ) : null}
    </Link>
  );
}

function SidebarSearch({ collapsed }: { collapsed: boolean }) {
  const t = useT();
  return (
    <button
      type="button"
      onClick={() =>
        window.dispatchEvent(
          new KeyboardEvent('keydown', { key: 'k', ctrlKey: true, bubbles: true }),
        )
      }
      aria-label={t('Search mods and commands')}
      aria-keyshortcuts="Control+K Meta+K"
      data-sidebar-tooltip={t('Search mods and commands')}
      data-sidebar-tooltip-shortcut={shortcutLabel('K')}
      data-sidebar-tooltip-side={collapsed ? 'right' : 'bottom'}
      className={
        collapsed
          ? 'nav-link-grim sidebar-nav-item'
          : 'sidebar-header-search flex items-center justify-center text-ash transition-colors duration-150 hover:bg-char/40 hover:text-parchment'
      }
    >
      <Search className="nav-icon shrink-0" aria-hidden />
    </button>
  );
}

function SidebarLaunch({ collapsed }: { collapsed: boolean }) {
  const t = useT();
  const { launching, running, launchError, busy, launch, clearError } = useLaunch();
  const [menuOpen, setMenuOpen] = useState(false);
  const menuId = useId();
  const wrapRef = useRef<HTMLDivElement>(null);
  const disclosureRef = useRef<HTMLButtonElement>(null);
  const vanillaRef = useRef<HTMLButtonElement>(null);
  const label =
    launching === 'vanilla'
      ? t('Restoring…')
      : launching === 'modded'
        ? t('Applying…')
        : running
          ? t('Running…')
          : t('Launch Modded');

  useEffect(() => {
    if (!menuOpen || collapsed) return;
    vanillaRef.current?.focus();
    const dismiss = (event: MouseEvent) => {
      if (event.target instanceof Node && !wrapRef.current?.contains(event.target))
        setMenuOpen(false);
    };
    const keydown = (event: KeyboardEvent) => {
      if (event.key !== 'Escape') return;
      setMenuOpen(false);
      disclosureRef.current?.focus();
    };
    document.addEventListener('mousedown', dismiss);
    document.addEventListener('keydown', keydown);
    return () => {
      document.removeEventListener('mousedown', dismiss);
      document.removeEventListener('keydown', keydown);
    };
  }, [menuOpen, collapsed]);

  useEffect(() => {
    if (busy || collapsed) setMenuOpen(false);
  }, [busy, collapsed]);

  return (
    <div
      ref={wrapRef}
      className="sidebar-section relative flex shrink-0 flex-col gap-2 pb-app-sm"
      onBlur={(event) => {
        if (!event.currentTarget.contains(event.relatedTarget)) setMenuOpen(false);
      }}
    >
      {launchError ? (
        <div
          role="alert"
          className={`flex items-start gap-2 text-xs text-crimson ${collapsed ? 'grimoire-card grimoire-card--raised absolute bottom-full left-3 z-50 mb-2 w-64 p-3' : 'pb-1'}`}
        >
          <span className="min-w-0 flex-1 break-words">{launchError}</span>
          <CopyButton value={t('Launch error: {error}', { error: launchError })} />
          <button
            type="button"
            onClick={clearError}
            title={t('Dismiss')}
            aria-label={t('Dismiss the launch error')}
            className="shrink-0 text-ash transition-colors duration-150 hover:text-parchment"
          >
            <X className="h-3.5 w-3.5" aria-hidden="true" />
          </button>
        </div>
      ) : null}
      <div className="sidebar-launch-control flex bg-crimson">
        <button
          type="button"
          disabled={busy}
          className="sidebar-launch-action grid min-w-0 flex-1 items-center text-base font-semibold text-parchment transition-colors duration-150 hover:bg-parchment/10 disabled:pointer-events-none disabled:opacity-50"
          aria-label={label}
          data-sidebar-tooltip={collapsed ? label : undefined}
          onClick={() => {
            setMenuOpen(false);
            void launch('modded');
          }}
        >
          <LaunchIcon className="h-5 w-5 shrink-0" aria-hidden />
          <span
            className="sidebar-expanded-content truncate pr-2 text-left"
            aria-hidden={collapsed}
          >
            {label}
          </span>
        </button>
        {collapsed ? null : (
          <button
            ref={disclosureRef}
            type="button"
            disabled={busy}
            className="sidebar-launch-disclosure flex shrink-0 items-center justify-center border-l border-parchment/20 text-parchment transition-colors duration-150 hover:bg-parchment/10 disabled:pointer-events-none disabled:opacity-50"
            aria-label={t('Launch options')}
            aria-haspopup="menu"
            aria-expanded={menuOpen}
            aria-controls={menuId}
            onClick={() => setMenuOpen((open) => !open)}
            onKeyDown={(event) => {
              if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
                event.preventDefault();
                setMenuOpen(true);
              }
            }}
          >
            <ChevronDown className="h-4 w-4" aria-hidden />
          </button>
        )}
      </div>
      {menuOpen && !collapsed ? (
        <div
          id={menuId}
          role="menu"
          aria-label={t('Launch options')}
          className="grimoire-card grimoire-card--raised absolute inset-x-3 bottom-full z-50 mb-2 p-1.5"
        >
          <button
            ref={vanillaRef}
            type="button"
            role="menuitem"
            disabled={busy}
            className="flex min-h-11 w-full items-center gap-3 rounded px-3 py-2 text-left text-base font-semibold text-parchment transition-colors duration-150 hover:bg-char/60 focus-visible:bg-char/60"
            onClick={() => {
              setMenuOpen(false);
              disclosureRef.current?.focus();
              void launch('vanilla');
            }}
          >
            <LaunchIcon className="h-5 w-5 shrink-0 text-ash" />
            {t('Launch Vanilla')}
          </button>
        </div>
      ) : null}
    </div>
  );
}

async function getAppWindow() {
  if (!inTauri()) return null;
  try {
    const { getCurrentWindow } = await import('@tauri-apps/api/window');
    return getCurrentWindow();
  } catch {
    return null;
  }
}

function WindowControls() {
  const t = useT();
  const [maximized, setMaximized] = useState(false);
  const [available, setAvailable] = useState(false);

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
    void quitApp();
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
    <div
      className="window-controls absolute right-3 top-3 z-40 flex items-center gap-2"
      data-tauri-drag-region
    >
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
  const sidebarRef = useRef<HTMLElement | null>(null);

  // biome-ignore lint/correctness/useExhaustiveDependencies: re-scroll on navigation
  useEffect(() => {
    mainRef.current?.scrollTo({ top: 0, left: 0 });
  }, [location.pathname]);

  // The webview scrolls a mouse notch as one teleport, which is what makes the
  // app feel harder than the same page in a browser. Delegated from the
  // document so dialogs, the log view and every list get the same feel as the
  // main area — including ones added later. Trackpads are untouched.
  useEffect(() => attachSmoothWheel(document), []);

  // Remember where the user put the window. Mounted from the root route, which
  // the overlay windows never render — they draw `OverlayHud` directly and
  // keep their own per-mod geometry.
  useEffect(() => trackMainWindow(), []);

  return (
    <ToastProvider>
      <DialogProvider>
        <LaunchProvider>
          <StartupSelfHeal />
          <div className="flex h-screen w-screen overflow-hidden">
            <aside
              ref={sidebarRef}
              data-collapsed={collapsed}
              onClick={(event) => {
                // The empty rail expands; its links, menus and actions keep their own behavior.
                if (
                  collapsed &&
                  event.target instanceof Element &&
                  event.currentTarget.contains(event.target) &&
                  !event.target.closest('button, a, [role="menu"]')
                ) {
                  update({ sidebarCollapsed: false });
                }
              }}
              className={`app-sidebar relative z-40 flex shrink-0 flex-col border-r border-border transition-[width] duration-150 ease-grimoire ${
                collapsed ? 'w-[var(--sidebar-collapsed-width)]' : 'w-72'
              }`}
            >
              <div
                className="sidebar-section shrink-0 py-app"
                data-tauri-drag-region={collapsed ? undefined : true}
              >
                <div
                  className="sidebar-header"
                  data-tauri-drag-region={collapsed ? undefined : true}
                >
                  <div className="sidebar-brand">
                    <img src="/logo.png" alt="Ravenswatch Mod Manager" className="sidebar-logo" />
                  </div>
                  <div
                    className="sidebar-expanded-content min-w-0 overflow-hidden font-serif-italic text-lg leading-none text-parchment"
                    aria-hidden={collapsed}
                    data-tauri-drag-region
                  >
                    <span className="block truncate">Ravenswatch</span>
                    <span className="block truncate text-sm leading-none text-ash">
                      Mod Manager
                    </span>
                  </div>
                  {collapsed ? null : <SidebarSearch collapsed={false} />}
                  <button
                    type="button"
                    onClick={() => update({ sidebarCollapsed: !collapsed })}
                    aria-label={
                      collapsed ? t('Expand the sidebar') : t('Collapse the sidebar to icons')
                    }
                    aria-expanded={!collapsed}
                    data-sidebar-tooltip={
                      collapsed ? t('Expand the sidebar') : t('Collapse the sidebar to icons')
                    }
                    className="sidebar-toggle flex items-center justify-center text-ash transition-colors duration-150 hover:bg-char/40 hover:text-parchment"
                  >
                    {collapsed ? <PanelLeftOpen aria-hidden /> : <PanelLeftClose aria-hidden />}
                  </button>
                </div>
              </div>

              <nav
                className="min-h-0 flex-1 overflow-x-hidden overflow-y-auto pb-1"
                data-tauri-drag-region={collapsed ? undefined : true}
              >
                <div className="sidebar-section sidebar-nav-content flex flex-col gap-app-sm">
                  {nav.map((n) => (
                    <Fragment key={n.to}>
                      <NavLink {...n} collapsed={collapsed} />
                      {collapsed && n.to === '/' ? <SidebarSearch collapsed /> : null}
                    </Fragment>
                  ))}
                </div>
              </nav>

              <SidebarLaunch collapsed={collapsed} />
              <div className="sidebar-section shrink-0 pb-app">
                <NavLink {...SETTINGS_NAV} collapsed={collapsed} />
              </div>
              <AccountStrip collapsed={collapsed} />
              <SidebarTooltip sidebarRef={sidebarRef} />
            </aside>

            <div className="relative flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden">
              {/* Reserve native dragging space independently of the sidebar.
                  Keeping it in flow also leaves update banners clickable. */}
              {inTauri() ? (
                <div
                  aria-hidden="true"
                  data-tauri-drag-region
                  className="relative z-30 h-12 shrink-0"
                />
              ) : null}
              <WindowControls />
              <UpdaterBanner />
              <ChannelStatusBanner />
              {LIBRARY_PREVIEW ? (
                <div className="flex flex-wrap items-center gap-x-4 gap-y-1 px-app py-2 text-sm text-ash">
                  <span>Library preview · sample mods · reload to reset</span>
                  <a
                    href="/?preview=off"
                    className="underline underline-offset-4 hover:text-parchment"
                  >
                    Exit preview
                  </a>
                </div>
              ) : null}
              <main
                ref={mainRef}
                // Clear the 7rem footer fade, with another 1rem below the last item.
                className="rsmm-main min-h-0 flex-1 overflow-y-auto px-app pt-app pb-32"
              >
                <div className="w-full animate-page-in">
                  <Outlet />
                </div>
              </main>
              {/* Fades and blurs what scrolls under the version footer. */}
              <div
                aria-hidden="true"
                className="pointer-events-none absolute inset-x-0 bottom-0 z-10 h-28 bg-gradient-to-t from-[hsl(var(--pitch))] via-[hsl(var(--pitch)/0.7)] to-transparent backdrop-blur-sm [mask-image:linear-gradient(to_top,black_35%,transparent)]"
              />
            </div>

            <CommandPalette />
            {LIBRARY_PREVIEW ? null : <FirstRunDialogs />}
            <VersionFooter />
          </div>
        </LaunchProvider>
      </DialogProvider>
    </ToastProvider>
  );
}
