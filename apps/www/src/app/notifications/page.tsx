'use client';
import { Button, Spinner } from '@rsmm/ui';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Bell, Check } from 'lucide-react';
import type { Route } from 'next';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { api } from '../../lib/api';
import { useSession } from '../../lib/auth-client';

export default function NotificationsPage() {
  const { data: session, isPending } = useSession();
  const router = useRouter();
  const qc = useQueryClient();

  const q = useQuery({
    queryKey: ['me', 'notifications'],
    queryFn: () => api.me.notifications(),
    enabled: !!session,
  });

  const invalidate = () => qc.invalidateQueries({ queryKey: ['me', 'notifications'] });
  const markRead = useMutation({
    mutationFn: (id?: string) => api.me.markNotificationsRead(id),
    onSuccess: invalidate,
  });

  if (isPending) {
    return (
      <main className="container mx-auto flex justify-center px-6 py-24">
        <Spinner />
      </main>
    );
  }
  if (!session) {
    return (
      <main className="container mx-auto px-6 py-12">
        <p className="text-muted-foreground">
          Please{' '}
          <Link href="/auth/signin" className="underline">
            sign in
          </Link>{' '}
          to see your notifications.
        </p>
      </main>
    );
  }

  const items = q.data?.items ?? [];

  return (
    <main className="container mx-auto max-w-2xl space-y-6 px-6 py-10">
      <div className="flex items-center justify-between">
        <h1 className="flex items-center gap-2 text-3xl font-bold tracking-tight">
          <Bell className="h-6 w-6" /> Notifications
        </h1>
        {(q.data?.unread ?? 0) > 0 && (
          <Button size="sm" variant="outline" onClick={() => markRead.mutate(undefined)}>
            <Check className="mr-1.5 h-4 w-4" /> Mark all read
          </Button>
        )}
      </div>

      {q.isLoading ? (
        <Spinner />
      ) : items.length === 0 ? (
        <p className="text-muted-foreground">Nothing here yet.</p>
      ) : (
        <ul className="space-y-2">
          {items.map((n) => {
            const go = () => {
              if (!n.read) markRead.mutate(n.id);
              if (n.link) router.push(n.link as Route);
            };
            return (
              <li key={n.id}>
                <button
                  type="button"
                  onClick={go}
                  className={`w-full rounded-lg border p-4 text-left transition hover:bg-foreground/5 ${
                    n.read ? 'border-border/50' : 'border-crimson/40 bg-crimson/5'
                  }`}
                >
                  <div className="flex items-center gap-2">
                    {!n.read && <span className="h-2 w-2 rounded-full bg-crimson" />}
                    <span className="font-medium">{n.title}</span>
                    <span className="ml-auto text-xs text-muted-foreground">
                      {new Date(n.createdAt).toLocaleDateString()}
                    </span>
                  </div>
                  {n.body && <p className="mt-1 text-sm text-muted-foreground">{n.body}</p>}
                </button>
              </li>
            );
          })}
        </ul>
      )}
    </main>
  );
}
