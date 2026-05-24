'use client';

import type { ReactNode } from 'react';
import Link from 'next/link';
import { usePathname, useRouter } from 'next/navigation';
import { LogOut, User as UserIcon, Upload, Library, Settings } from 'lucide-react';
import { useEffect, useRef, useState } from 'react';
import { signOut, useSession } from '../lib/auth-client';

const navLinks = [
  { href: '/' as const, label: 'Home' },
  { href: '/registry' as const, label: 'Browse Registry' },
  { href: '/download' as const, label: 'Download' },
];

const userMenuLinks = [
  { href: '/publish' as const, label: 'Publish', icon: Upload },
  { href: '/my-mods' as const, label: 'My Mods', icon: Library },
  { href: '/account' as const, label: 'Account', icon: Settings },
];

function initialsFor(name: string | null | undefined, email: string | null | undefined): string {
  const src = name?.trim() || email?.trim() || '?';
  const parts = src.split(/\s+/).filter(Boolean);
  const first = parts[0];
  if (!first) return '?';
  if (parts.length === 1) return first.slice(0, 2).toUpperCase();
  const second = parts[1];
  return ((first[0] ?? '') + (second?.[0] ?? '')).toUpperCase();
}

function UserMenu() {
  const router = useRouter();
  const { data: session } = useSession();
  const [open, setOpen] = useState(false);
  const wrapRef = useRef<HTMLDivElement | null>(null);

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

  const initials = initialsFor(user.name, user.email);
  const displayName = user.name?.trim() || user.email || 'Account';

  async function handleSignOut() {
    setOpen(false);
    await signOut();
    router.push('/');
    router.refresh();
  }

  return (
    <div ref={wrapRef} className="relative">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-haspopup="menu"
        aria-expanded={open}
        aria-label="Open user menu"
        className="flex h-9 w-9 items-center justify-center overflow-hidden rounded-full border border-border/60 bg-muted text-xs font-semibold text-foreground transition hover:border-crimson/60 hover:bg-foreground/5"
      >
        {user.image ? (
          <img src={user.image} alt={displayName} className="h-full w-full object-cover" />
        ) : (
          <span>{initials}</span>
        )}
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
                <span>{initials}</span>
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

export function Nav({ versionBadge }: { versionBadge?: ReactNode }) {
  const pathname = usePathname();
  const { data: session, isPending } = useSession();

  const isActive = (href: string) => {
    if (href === '/') return pathname === '/';
    return pathname.startsWith(href);
  };

  return (
    <header className="sticky top-0 z-50 border-b border-border/40 bg-background/80 backdrop-blur-xl">
      <div className="container mx-auto flex items-center justify-between px-6 py-3">
        <Link href="/" className="flex items-center gap-2.5 shrink-0">
          <img src="/logo.png" alt="Ravenswatch Mod Manager" className="h-8 w-8 rounded-md object-cover" />
          <span className="hidden text-sm font-medium text-foreground/90 md:inline">
            Ravenswatch Mod Manager
          </span>
        </Link>

        <nav className="hidden items-center gap-1 md:flex">
          {navLinks.map((link) => (
            <Link
              key={link.href}
              href={link.href}
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

        <div className="flex items-center gap-3">
          <a
            href="https://github.com/Ovilli/RavenswatchModManager"
            target="_blank"
            rel="noopener noreferrer"
            className="hidden text-sm text-muted-foreground underline-offset-2 hover:text-foreground hover:underline sm:inline"
          >
            View Source
          </a>

          {versionBadge}

          {isPending ? (
            <div className="h-9 w-9 animate-pulse rounded-full bg-muted" aria-hidden />
          ) : session?.user ? (
            <UserMenu />
          ) : (
            <Link
              href="/auth/signin"
              className="inline-flex items-center gap-1.5 rounded-lg bg-crimson px-3.5 py-1.5 text-sm font-medium text-white transition-colors hover:bg-crimson/90"
            >
              <UserIcon className="h-4 w-4" />
              Sign In
            </Link>
          )}
        </div>
      </div>
    </header>
  );
}
