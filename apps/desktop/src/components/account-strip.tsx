import { Link } from '@tanstack/react-router';
import { ExternalLink, LogIn, LogOut, Settings, WifiOff } from 'lucide-react';
import { useEffect, useRef, useState } from 'react';
import { signOut, useSession } from '../lib/auth-client';
import { useT } from '../lib/i18n-react';
import { inTauri } from '../lib/platform';
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

export function AccountStrip() {
  if (!inTauri()) {
    return null;
  }

  return <AccountStripInner />;
}

function AccountStripInner() {
  const t = useT();
  const { data: session, isPending, error } = useSession();

  if (isPending) {
    return (
      <div className="border-t border-border px-4 py-3">
        <p className="font-mono text-xs text-ash">{t('Checking session…')}</p>
      </div>
    );
  }

  if (error) {
    return (
      <div className="border-t border-border px-4 py-3">
        <p className="font-mono text-xs text-ash flex items-center gap-1.5">
          <WifiOff className="h-3 w-3" />
          {t('API unavailable')}
        </p>
        <div className="flex justify-end mt-2">
          <CopyButton value={t('API session error: {error}', { error: error.message })} />
        </div>
      </div>
    );
  }

  if (!session?.user) {
    return (
      <div className="border-t border-border px-4 py-3">
        <Link to="/signin" className="btn-grim w-full justify-center" data-variant="primary">
          <LogIn className="h-4 w-4" /> {t('Sign in')}
        </Link>
      </div>
    );
  }

  return <ProfileMenu user={session.user} />;
}

interface SessionUser {
  name?: string | null;
  email?: string | null;
  image?: string | null;
}

function ProfileMenu({ user }: { user: SessionUser }) {
  const t = useT();
  const [open, setOpen] = useState(false);
  const wrapRef = useRef<HTMLDivElement | null>(null);
  const triggerRef = useRef<HTMLButtonElement | null>(null);
  const toast = useToast();

  useEffect(() => {
    if (!open) return;
    function onDocClick(e: MouseEvent) {
      if (!wrapRef.current) return;
      if (!wrapRef.current.contains(e.target as Node)) setOpen(false);
    }
    function onKey(e: KeyboardEvent) {
      if (e.key !== 'Escape') return;
      setOpen(false);
      // Escape closed the menu but left focus wherever it was, so a keyboard
      // user landed nowhere and had to tab back through the sidebar to reach
      // the trigger again. `profile-popover.tsx` does this correctly two files
      // over.
      triggerRef.current?.focus();
    }
    document.addEventListener('mousedown', onDocClick);
    document.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('mousedown', onDocClick);
      document.removeEventListener('keydown', onKey);
    };
  }, [open]);

  const initials = initialsFor(user.name, user.email);
  const displayName = user.name?.trim() || user.email || t('Account');

  async function handleSignOut() {
    setOpen(false);
    // Surface failures — a silent sign-out failure leaves the user
    // looking signed in with a dead session.
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
    <div ref={wrapRef} className="relative border-t border-border px-4 py-3">
      <button
        type="button"
        ref={triggerRef}
        onClick={() => setOpen((v) => !v)}
        aria-haspopup="menu"
        aria-expanded={open}
        className="flex w-full items-center gap-2.5 rounded border border-transparent px-1 py-1 text-left transition hover:border-oxblood/40 hover:bg-char/40"
      >
        <span className="flex h-8 w-8 shrink-0 items-center justify-center overflow-hidden rounded-full border border-oxblood/40 bg-char/60 text-xs font-semibold text-parchment">
          {user.image ? (
            <img src={user.image} alt={displayName} className="h-full w-full object-cover" />
          ) : (
            <span>{initials}</span>
          )}
        </span>
        <span className="min-w-0 flex-1">
          <span
            className="block truncate font-serif-italic text-parchment"
            title={user.email ?? undefined}
          >
            {displayName}
          </span>
          {user.email && user.email !== displayName ? (
            <span className="block truncate font-data text-[10px] text-ash">{user.email}</span>
          ) : null}
        </span>
      </button>

      {open ? (
        <div
          role="menu"
          className="absolute bottom-full left-2 right-2 z-50 mb-2 overflow-hidden rounded border border-oxblood/50 bg-pitch/95 shadow-xl backdrop-blur-sm"
        >
          <Link
            to="/settings"
            onClick={() => setOpen(false)}
            role="menuitem"
            className="flex items-center gap-2.5 px-3 py-2 font-mono text-xs text-parchment transition hover:bg-char/60"
          >
            <Settings className="h-3.5 w-3.5 text-ash" />
            {t('Settings')}
          </Link>
          <a
            href={WEB_ACCOUNT_URL}
            target="_blank"
            rel="noopener noreferrer"
            onClick={() => setOpen(false)}
            role="menuitem"
            className="flex items-center gap-2.5 px-3 py-2 font-mono text-xs text-parchment transition hover:bg-char/60"
          >
            <ExternalLink className="h-3.5 w-3.5 text-ash" />
            {t('Web account')}
          </a>
          <button
            type="button"
            onClick={handleSignOut}
            role="menuitem"
            className="flex w-full items-center gap-2.5 border-t border-oxblood/40 px-3 py-2 text-left font-mono text-xs text-parchment transition hover:bg-char/60"
          >
            <LogOut className="h-3.5 w-3.5 text-ash" />
            {t('Sign out')}
          </button>
        </div>
      ) : null}
    </div>
  );
}
