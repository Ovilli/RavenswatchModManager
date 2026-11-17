import { Link } from '@tanstack/react-router';
import {
  ChevronUp,
  ExternalLink,
  LogIn,
  LogOut,
  ScrollText,
  Settings,
  Terminal,
  WifiOff,
} from 'lucide-react';
import { type KeyboardEvent, useEffect, useId, useRef, useState } from 'react';
import { signOut, useSession } from '../lib/auth-client';
import { useT } from '../lib/i18n-react';
import { CopyButton } from './chrome';
import { useToast } from './toast';

function initialsFor(name: string | null | undefined, email: string | null | undefined): string {
  const src = name?.trim() || email?.trim() || '?';
  const parts = src.split(/\s+/).filter(Boolean);
  const first = parts[0];
  if (!first) return '?';
  if (parts.length === 1) return first.slice(0, 2).toUpperCase();
  const second = parts[1];
  return ((first[0] ?? '') + (second?.[0] ?? '')).toUpperCase();
}

const WEB_ACCOUNT_URL = 'https://rsmm.me/account';
const MENU_ITEM =
  'flex min-h-11 w-full items-center gap-3 rounded px-3 py-2 text-left text-sm text-parchment transition-colors duration-150 hover:bg-char/60 focus-visible:bg-char/60';

/** App navigation stays available while signed out, loading, or offline. */
export function AccountStrip({ collapsed = false }: { collapsed?: boolean }) {
  const t = useT();
  const { data: session, isPending, error } = useSession();
  const user = session?.user;
  const [open, setOpen] = useState(false);
  const wrapRef = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const menuRef = useRef<HTMLDivElement>(null);
  const menuId = useId();
  const toast = useToast();

  useEffect(() => {
    if (!open) return;
    menuRef.current?.querySelector<HTMLElement>('[role="menuitem"]')?.focus();
    function onDocClick(e: MouseEvent) {
      if (e.target instanceof Node && !wrapRef.current?.contains(e.target)) setOpen(false);
    }
    function onKey(e: globalThis.KeyboardEvent) {
      if (e.key !== 'Escape') return;
      setOpen(false);
      triggerRef.current?.focus();
    }
    document.addEventListener('mousedown', onDocClick);
    document.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('mousedown', onDocClick);
      document.removeEventListener('keydown', onKey);
    };
  }, [open]);

  const displayName = user ? user.name?.trim() || user.email || t('Account') : t('Sign in');
  const status = isPending ? t('Checking session…') : error ? t('API unavailable') : null;

  function onMenuKeyDown(event: KeyboardEvent<HTMLDivElement>) {
    if (!['ArrowDown', 'ArrowUp', 'Home', 'End'].includes(event.key)) return;
    event.preventDefault();
    const items = Array.from(
      menuRef.current?.querySelectorAll<HTMLElement>('[role="menuitem"]') ?? [],
    );
    if (!items.length) return;
    const current = items.findIndex((item) => item === document.activeElement);
    const next =
      event.key === 'Home'
        ? 0
        : event.key === 'End'
          ? items.length - 1
          : (current + (event.key === 'ArrowDown' ? 1 : -1) + items.length) % items.length;
    items[next]?.focus();
  }

  async function handleSignOut() {
    setOpen(false);
    try {
      const result = await signOut();
      if (result?.error) {
        throw new Error(
          result.error.message ??
            t('sign-out rejected (HTTP {status})', { status: result.error.status ?? '' }),
        );
      }
    } catch (err) {
      console.error('[account] sign-out failed', err);
      toast.push(
        t('Sign out failed: {error}', {
          error: err instanceof Error ? err.message : String(err),
        }),
        'error',
      );
    }
  }

  return (
    <div
      ref={wrapRef}
      className="relative shrink-0 border-t border-border/60 p-3"
      onBlur={(event) => {
        if (!event.currentTarget.contains(event.relatedTarget)) setOpen(false);
      }}
    >
      <button
        type="button"
        ref={triggerRef}
        onClick={() => setOpen((value) => !value)}
        onKeyDown={(event) => {
          if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
            event.preventDefault();
            setOpen(true);
          }
        }}
        aria-label={displayName}
        data-sidebar-tooltip={collapsed ? displayName : undefined}
        aria-haspopup="menu"
        aria-expanded={open}
        aria-controls={menuId}
        className="sidebar-account-action grid h-14 w-full items-center overflow-hidden rounded border border-transparent py-1.5 text-left transition-colors duration-150 hover:bg-char/40"
      >
        <span className="flex h-8 w-8 shrink-0 items-center justify-center overflow-hidden rounded-full border border-border bg-char/60 text-xs font-semibold text-parchment">
          {user?.image ? (
            <img src={user.image} alt="" className="h-full w-full object-cover" />
          ) : user ? (
            <span>{initialsFor(user.name, user.email)}</span>
          ) : (
            <LogIn className="h-4 w-4" aria-hidden />
          )}
        </span>
        <span className="sidebar-expanded-content min-w-0" aria-hidden={collapsed}>
          <span className="block truncate text-base text-parchment">{displayName}</span>
          {status || (user?.email && user.email !== displayName) ? (
            <span className="block truncate text-xs text-ash">{status || user?.email}</span>
          ) : null}
        </span>
        <ChevronUp className="sidebar-expanded-content h-4 w-4 shrink-0 text-ash" aria-hidden />
      </button>

      {open ? (
        <div
          ref={menuRef}
          id={menuId}
          role="menu"
          aria-label={t('Account')}
          onKeyDown={onMenuKeyDown}
          className="grimoire-card grimoire-card--raised animate-fade-in absolute bottom-full left-3 z-50 mb-2 w-64 max-w-[calc(100vw-1.5rem)] p-1.5"
        >
          {error ? (
            <div className="flex items-center gap-2 border-b border-border/60 px-3 py-2 text-xs text-ash">
              <WifiOff className="h-4 w-4 shrink-0" aria-hidden />
              <span className="flex-1">{t('API unavailable')}</span>
              <CopyButton value={t('API session error: {error}', { error: error.message })} />
            </div>
          ) : null}
          {user ? (
            <a
              href={WEB_ACCOUNT_URL}
              target="_blank"
              rel="noopener noreferrer"
              onClick={() => setOpen(false)}
              role="menuitem"
              className={MENU_ITEM}
            >
              <ExternalLink className="h-4 w-4 text-ash" aria-hidden />
              {t('Web account')}
            </a>
          ) : (
            <Link to="/signin" onClick={() => setOpen(false)} role="menuitem" className={MENU_ITEM}>
              <LogIn className="h-4 w-4 text-ash" aria-hidden />
              {t('Sign in')}
            </Link>
          )}
          <div role="separator" className="my-1 border-t border-border/60" />
          <Link to="/settings" onClick={() => setOpen(false)} role="menuitem" className={MENU_ITEM}>
            <Settings className="h-4 w-4 text-ash" aria-hidden />
            {t('Settings')}
          </Link>
          <Link to="/commands" onClick={() => setOpen(false)} role="menuitem" className={MENU_ITEM}>
            <Terminal className="h-4 w-4 text-ash" aria-hidden />
            {t('Commands')}
          </Link>
          <Link to="/log" onClick={() => setOpen(false)} role="menuitem" className={MENU_ITEM}>
            <ScrollText className="h-4 w-4 text-ash" aria-hidden />
            {t('Log')}
          </Link>
          {user ? (
            <>
              <div role="separator" className="my-1 border-t border-border/60" />
              <button type="button" onClick={handleSignOut} role="menuitem" className={MENU_ITEM}>
                <LogOut className="h-4 w-4 text-ash" aria-hidden />
                {t('Sign out')}
              </button>
            </>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
