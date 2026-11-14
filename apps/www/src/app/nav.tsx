'use client';

import { buttonVariants } from '@rsmm/ui';
import { useQuery } from '@tanstack/react-query';
import {
  Bell,
  BookOpen,
  Heart,
  Library,
  LogOut,
  Menu,
  Settings,
  ShieldCheck,
  Upload,
  X,
} from 'lucide-react';
import type { Route } from 'next';
import Link from 'next/link';
import { usePathname, useRouter } from 'next/navigation';
import { useEffect, useId, useRef, useState } from 'react';
import { api } from '../lib/api';
import { signOut, useSession } from '../lib/auth-client';
import './nav.css';

/** Bell in the header linking to /notifications, with an unread-count badge.
 *  Polls every five minutes (and on window focus) so a new notification
 *  surfaces without a reload; each poll is a paid function invocation. */
function NotificationBell() {
  const { data: session } = useSession();
  const q = useQuery({
    queryKey: ['me', 'notifications'],
    queryFn: () => api.me.notifications(),
    enabled: !!session,
    refetchInterval: 5 * 60_000,
  });
  if (!session) return null;
  const unread = q.data?.unread ?? 0;
  return (
    <Link
      href="/notifications"
      aria-label={`Notifications${unread > 0 ? ` (${unread} unread)` : ''}`}
      className="relative flex h-10 w-10 shrink-0 items-center justify-center rounded-full text-zinc-200 transition-colors hover:bg-white/10 hover:text-white"
    >
      <Bell className="h-5 w-5" aria-hidden="true" />
      {unread > 0 && (
        <span className="absolute -right-1 -top-1 flex h-4 min-w-4 items-center justify-center rounded-full bg-crimson px-1 text-[10px] font-semibold text-white">
          {unread > 9 ? '9+' : unread}
        </span>
      )}
    </Link>
  );
}

// Guides and the Modding Guide are deliberately absent. The bar is for what
// someone arrives wanting — the catalogue and the app — and reading material
// was crowding it. Both are reached from the block at the foot of the home
// page and from the footer; the Modding Guide additionally sits at the top of
// /guides, which is where a reader looking for how-to material already is.
const navLinks = [
  { href: '/' as const, label: 'Home' },
  { href: '/registry' as const, label: 'Registry' },
  { href: '/c' as const, label: 'Collections' },
];

const userMenuLinks = [
  { href: '/publish' as const, label: 'Publish', icon: Upload },
  { href: '/my-mods' as const, label: 'My Mods', icon: Library },
  { href: '/my-guides' as const, label: 'My Guides', icon: BookOpen },
  { href: '/account/follows' as const, label: 'Followed Mods', icon: Heart },
  { href: '/account' as const, label: 'Account', icon: Settings },
];

function initialFor(name: string | null | undefined, email: string | null | undefined): string {
  const src = name?.trim() || email?.trim() || '?';
  return Array.from(src)[0] ?? '?';
}

function UserMenu() {
  const router = useRouter();
  const { data: session } = useSession();
  const [open, setOpen] = useState(false);
  const wrapRef = useRef<HTMLDivElement | null>(null);
  // Admin capability drives the moderation link only; routes stay server-gated.
  const whoami = useQuery({
    queryKey: ['me', 'whoami'],
    queryFn: () => api.me.whoami(),
    enabled: !!session,
    staleTime: 5 * 60_000,
    retry: false,
  });

  useEffect(() => {
    if (!open) return;
    function onDocClick(e: MouseEvent) {
      if (!wrapRef.current) return;
      if (!wrapRef.current.contains(e.target as Node)) setOpen(false);
    }
    function onKey(e: KeyboardEvent) {
      if (e.key === 'Escape') setOpen(false);
    }
    document.addEventListener('mousedown', onDocClick);
    document.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('mousedown', onDocClick);
      document.removeEventListener('keydown', onKey);
    };
  }, [open]);

  const user = session?.user;
  if (!user) return null;

  const initial = initialFor(user.name, user.email);
  const displayName = user.name?.trim() || user.email || 'Account';

  async function handleSignOut() {
    setOpen(false);
    await signOut();
    router.push('/');
    router.refresh();
  }

  return (
    <div ref={wrapRef} className="relative min-w-0">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-haspopup="menu"
        aria-expanded={open}
        aria-label={`Open user menu for ${displayName}`}
        className="group flex h-10 max-w-full items-center gap-2.5 rounded-full text-zinc-200 transition-colors hover:text-white"
      >
        <span className="flex h-10 w-10 shrink-0 items-center justify-center overflow-hidden rounded-full bg-zinc-700 text-lg transition-colors group-hover:bg-zinc-600">
          {user.image ? (
            <img src={user.image} alt="" className="h-full w-full object-cover" />
          ) : (
            <span>{initial}</span>
          )}
        </span>
        <span className="hidden max-w-32 truncate text-base sm:block xl:max-w-40">
          {displayName}
        </span>
      </button>

      {open ? (
        <div
          role="menu"
          className="absolute right-0 top-full z-50 mt-2 w-60 overflow-hidden rounded-lg border border-border/60 bg-background/95 shadow-xl backdrop-blur-xl"
        >
          <div className="flex items-center gap-3 border-b border-border/40 p-3">
            <div className="flex h-10 w-10 items-center justify-center overflow-hidden rounded-full border border-border/60 bg-muted text-xs font-semibold">
              {user.image ? (
                <img src={user.image} alt={displayName} className="h-full w-full object-cover" />
              ) : (
                <span>{initial}</span>
              )}
            </div>
            <div className="min-w-0">
              <p className="truncate text-sm font-medium">{displayName}</p>
              {user.email ? (
                <p className="truncate text-xs text-muted-foreground">{user.email}</p>
              ) : null}
            </div>
          </div>
          <nav className="py-1">
            {userMenuLinks.map((link) => {
              const Icon = link.icon;
              return (
                <Link
                  key={link.href}
                  href={link.href}
                  onClick={() => setOpen(false)}
                  className="flex items-center gap-2.5 px-3 py-2 text-sm text-foreground/90 transition hover:bg-foreground/5"
                  role="menuitem"
                >
                  <Icon className="h-4 w-4 text-muted-foreground" />
                  {link.label}
                </Link>
              );
            })}
            {whoami.data?.isAdmin && (
              <Link
                href="/admin"
                onClick={() => setOpen(false)}
                className="flex items-center gap-2.5 px-3 py-2 text-sm text-foreground/90 transition hover:bg-foreground/5"
                role="menuitem"
              >
                <ShieldCheck className="h-4 w-4 text-muted-foreground" />
                Moderation
              </Link>
            )}
          </nav>
          <div className="border-t border-border/40 py-1">
            <button
              type="button"
              onClick={handleSignOut}
              className="flex w-full items-center gap-2.5 px-3 py-2 text-left text-sm text-foreground/90 transition hover:bg-foreground/5"
              role="menuitem"
            >
              <LogOut className="h-4 w-4 text-muted-foreground" />
              Sign Out
            </button>
          </div>
        </div>
      ) : null}
    </div>
  );
}

function isActivePath(pathname: string, href: string): boolean {
  if (href === '/') return pathname === '/';
  return pathname.startsWith(href);
}

/**
 * The bar's links below `md`, where the inline row is hidden.
 *
 * Keeps the registry and collections within reach on phones. Download stays
 * visible as a separate header action at every size.
 */
function MobileMenu({ pathname }: { pathname: string }) {
  const [open, setOpen] = useState(false);
  const panelId = useId();
  const wrapRef = useRef<HTMLDivElement | null>(null);

  // A link inside the panel navigates without unmounting the header, so close
  // on the route change rather than relying on each link's onClick.
  // biome-ignore lint/correctness/useExhaustiveDependencies: pathname is the trigger, not an input.
  useEffect(() => {
    setOpen(false);
  }, [pathname]);

  useEffect(() => {
    if (!open) return;
    function onDocClick(e: MouseEvent) {
      if (!wrapRef.current) return;
      if (!wrapRef.current.contains(e.target as Node)) setOpen(false);
    }
    function onKey(e: KeyboardEvent) {
      if (e.key === 'Escape') setOpen(false);
    }
    document.addEventListener('mousedown', onDocClick);
    document.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('mousedown', onDocClick);
      document.removeEventListener('keydown', onKey);
    };
  }, [open]);

  return (
    <div ref={wrapRef} className="md:hidden">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        aria-controls={panelId}
        aria-label={open ? 'Close menu' : 'Open menu'}
        className="flex h-9 w-9 items-center justify-center rounded-lg border border-border/60 text-muted-foreground transition hover:border-crimson/60 hover:text-foreground"
      >
        {open ? (
          <X className="h-4 w-4" aria-hidden="true" />
        ) : (
          <Menu className="h-4 w-4" aria-hidden="true" />
        )}
      </button>

      {open ? (
        <nav
          id={panelId}
          aria-label="Site"
          className="absolute inset-x-0 top-full border-b border-border/40 bg-background shadow-xl"
        >
          <ul className="container mx-auto flex flex-col gap-1 px-6 py-3">
            {navLinks.map((link) => {
              const active = isActivePath(pathname, link.href);
              return (
                <li key={link.href}>
                  <Link
                    href={link.href as Route}
                    aria-current={active ? 'page' : undefined}
                    className={`block rounded-lg px-3 py-2.5 text-base transition-colors ${
                      active
                        ? 'bg-crimson/10 text-parchment'
                        : 'text-muted-foreground hover:bg-foreground/5 hover:text-foreground'
                    }`}
                  >
                    {link.label}
                  </Link>
                </li>
              );
            })}
          </ul>
        </nav>
      ) : null}
    </div>
  );
}

export function Nav() {
  const pathname = usePathname();
  const { data: session, isPending } = useSession();
  const headerRef = useRef<HTMLElement>(null);

  useEffect(() => {
    const header = headerRef.current;
    if (!header) return;
    // Scroll targets must clear the header, including height changes from
    // mobile controls or authentication state. The visual fade adds no height.
    const updateHeight = () => {
      document.documentElement.style.setProperty(
        '--site-header-height',
        `${header.getBoundingClientRect().height}px`,
      );
    };
    updateHeight();
    const observer = new ResizeObserver(updateHeight);
    observer.observe(header, { box: 'border-box' });
    window.addEventListener('resize', updateHeight);
    return () => {
      observer.disconnect();
      window.removeEventListener('resize', updateHeight);
      document.documentElement.style.removeProperty('--site-header-height');
    };
  }, []);

  const isActive = (href: string) => isActivePath(pathname, href);

  return (
    <header ref={headerRef} className="site-header sticky top-0 z-50">
      <div className="container mx-auto flex items-center justify-between gap-3 px-4 py-3 sm:px-6">
        <Link href="/" className="flex items-center gap-2.5 shrink-0">
          <img
            src="/logo.png"
            alt="Ravenswatch Mod Manager"
            className="h-8 w-8 rounded-md object-cover"
          />
          <span className="font-fraktur hidden text-lg text-foreground lg:inline">
            Ravenswatch Mod Manager
          </span>
        </Link>

        <nav className="hidden items-center gap-1 md:flex">
          {navLinks.map((link) => (
            <Link
              key={link.href}
              href={link.href as Route}
              aria-current={isActive(link.href) ? 'page' : undefined}
              className={`rounded-lg px-3 py-1.5 text-sm transition-colors ${
                isActive(link.href)
                  ? 'bg-crimson/10 text-parchment'
                  : 'text-muted-foreground hover:bg-foreground/5 hover:text-foreground'
              }`}
            >
              {link.label}
            </Link>
          ))}
        </nav>

        <div className="flex min-w-0 items-center gap-2 sm:gap-4">
          <Link
            href="/download"
            aria-current={isActive('/download') ? 'page' : undefined}
            className={buttonVariants({ className: 'shrink-0 sm:px-5 sm:text-base' })}
          >
            Download
          </Link>

          {!isPending && !session?.user ? (
            <Link
              href="/auth/signin"
              className="inline-flex h-10 shrink-0 items-center justify-center whitespace-nowrap rounded-lg bg-[#333333] px-4 text-sm font-medium text-zinc-100 transition-colors hover:bg-[#404040] sm:px-5 sm:text-base"
            >
              Sign in
            </Link>
          ) : null}

          {isPending ? (
            <div
              className="h-10 w-10 shrink-0 animate-pulse rounded-full bg-zinc-700"
              aria-hidden
            />
          ) : session?.user ? (
            <>
              <NotificationBell />
              <UserMenu />
            </>
          ) : null}

          <MobileMenu pathname={pathname} />
        </div>
      </div>
    </header>
  );
}
