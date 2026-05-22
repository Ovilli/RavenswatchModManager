import { Link } from '@tanstack/react-router';
import { LogIn, LogOut, User, WifiOff } from 'lucide-react';
import { signOut, useSession } from '../lib/auth-client';
import { inTauri } from '../lib/platform';
import { Button, CopyButton } from './chrome';

export function AccountStrip() {
  if (!inTauri()) {
    return null;
  }

  return <AccountStripInner />;
}

function AccountStripInner() {
  const { data: session, isPending, error } = useSession();

  if (isPending) {
    return (
      <div className="border-t border-border px-4 py-3">
        <p className="font-mono text-xs text-ash">Checking session…</p>
      </div>
    );
  }

  if (error) {
    return (
      <div className="border-t border-border px-4 py-3">
        <p className="font-mono text-xs text-ash flex items-center gap-1.5">
          <WifiOff className="h-3 w-3" />
          API unavailable
        </p>
        <div className="flex justify-end mt-2">
          <CopyButton value={`API session error: ${error.message}`} />
        </div>
      </div>
    );
  }

  if (!session?.user) {
    return (
      <div className="border-t border-border px-4 py-3">
        <Link to="/signin" className="btn-grim w-full justify-center" data-variant="primary">
          <LogIn className="h-4 w-4" /> Sign in
        </Link>
      </div>
    );
  }

  return (
    <div className="border-t border-border px-4 py-3 space-y-2">
      <div className="flex items-center gap-2">
        <User className="h-4 w-4 text-ash" aria-hidden />
        <span className="font-serif-italic truncate text-parchment" title={session.user.email}>
          {session.user.name || session.user.email}
        </span>
      </div>
      <Button
        type="button"
        size="sm"
        onClick={() => {
          void signOut();
        }}
        className="w-full justify-center"
      >
        <LogOut className="h-3.5 w-3.5" /> Sign out
      </Button>
    </div>
  );
}
