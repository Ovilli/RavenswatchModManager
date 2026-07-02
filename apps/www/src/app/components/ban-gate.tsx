'use client';

import { Button } from '@rsmm/ui';
import { useQuery } from '@tanstack/react-query';
import { Ban } from 'lucide-react';
import { api } from '../../lib/api';
import { signOut, useSession } from '../../lib/auth-client';

/**
 * Full-screen ban notice. A banned account keeps a valid Better Auth cookie
 * (the auth handler bypasses the API ban gate), so without this the UI looks
 * signed-in while every action silently 401s. We poll the ban-aware
 * `/api/session` probe and, when banned, block the app with an explanation and
 * a sign-out. Mounted once in the root layout inside the query provider.
 */
export function BanGate() {
  const { data: session } = useSession();
  const q = useQuery({
    queryKey: ['session', 'ban'],
    queryFn: () => api.session(),
    enabled: !!session,
    refetchInterval: 60_000,
    retry: false,
  });

  if (!session || !q.data?.banned) return null;

  return (
    <div className="fixed inset-0 z-[100] flex items-center justify-center bg-pitch/95 p-6 backdrop-blur-sm">
      <div className="grimoire-card w-full max-w-md space-y-4 p-6 text-center">
        <div className="mx-auto flex h-12 w-12 items-center justify-center rounded-full border border-destructive/40 bg-destructive/10">
          <Ban className="h-6 w-6 text-destructive" />
        </div>
        <h1 className="text-xl font-bold tracking-tight">Account suspended</h1>
        <p className="text-sm text-muted-foreground">
          Your account has been suspended by a moderator. You can browse the site while signed out,
          but publishing, reviewing, and other account actions are disabled.
        </p>
        {q.data.reason ? (
          <p className="rounded-md border border-border/50 bg-muted/30 px-3 py-2 text-sm">
            <span className="font-medium">Reason:</span> {q.data.reason}
          </p>
        ) : null}
        <p className="text-xs text-muted-foreground">
          Believe this is a mistake? Reach us via the{' '}
          <a href="/contact" className="underline underline-offset-2">
            contact page
          </a>
          .
        </p>
        <Button
          variant="outline"
          className="w-full"
          onClick={() => {
            void signOut();
          }}
        >
          Sign out
        </Button>
      </div>
    </div>
  );
}
