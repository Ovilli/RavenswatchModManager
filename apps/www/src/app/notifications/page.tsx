'use client';
import { Button, Spinner } from '@rsmm/ui';
import { useInfiniteQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { Bell, Check, Trash2, X } from 'lucide-react';
import type { Route } from 'next';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { api } from '../../lib/api';
import { useSession } from '../../lib/auth-client';

export default function NotificationsPage() {
  const { data: session, isPending } = useSession();
  const router = useRouter();
  const qc = useQueryClient();

  // Own key under the ['me', 'notifications'] prefix: the nav badge holds a
  // plain (non-paged) query at that exact key, and the two shapes can't share.
  const q = useInfiniteQuery({
    queryKey: ['me', 'notifications', 'pages'],
    queryFn: ({ pageParam }) => api.me.notifications(pageParam),
    initialPageParam: undefined as string | undefined,
    getNextPageParam: (last) => (last.hasMore ? last.items.at(-1)?.id : undefined),
    enabled: !!session,
  });

  const invalidate = () => qc.invalidateQueries({ queryKey: ['me', 'notifications'] });
  const markRead = useMutation({
    mutationFn: (id?: string) => api.me.markNotificationsRead(id),
    onSuccess: invalidate,
  });
  const remove = useMutation({
    mutationFn: (id?: string) => api.me.deleteNotifications(id),
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

  const items = q.data?.pages.flatMap((p) => p.items) ?? [];
  const unread = q.data?.pages[0]?.unread ?? 0;

  return (
    <main className="container mx-auto max-w-2xl space-y-6 px-6 py-10">
      <div className="flex items-center justify-between">
        <h1 className="flex items-center gap-2 text-3xl font-bold tracking-tight">
          <Bell className="h-6 w-6" /> Notifications
        </h1>
        <div className="flex gap-2">
          {unread > 0 && (
            <Button size="sm" variant="outline" onClick={() => markRead.mutate(undefined)}>
              <Check className="mr-1.5 h-4 w-4" /> Mark all read
            </Button>
          )}
          {items.length > 0 && (
            <Button
              size="sm"
              variant="outline"
              disabled={remove.isPending}
              onClick={() => {
                if (confirm('Delete all notifications?')) remove.mutate(undefined);
              }}
            >
              <Trash2 className="mr-1.5 h-4 w-4" /> Clear all
            </Button>
          )}
        </div>
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
              <li key={n.id} className="relative">
                <button
                  type="button"
                  onClick={go}
                  className={`w-full rounded-lg border p-4 pr-10 text-left transition hover:bg-foreground/5 ${
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
                <button
                  type="button"
                  aria-label="Delete notification"
                  title="Delete"
                  disabled={remove.isPending}
                  onClick={() => remove.mutate(n.id)}
                  className="absolute right-2 top-2 rounded p-1.5 text-muted-foreground transition hover:bg-foreground/10 hover:text-foreground"
                >
                  <X className="h-4 w-4" />
                </button>
              </li>
            );
          })}
        </ul>
      )}
      {q.hasNextPage ? (
        <div className="flex justify-center">
          <Button
            size="sm"
            variant="outline"
            onClick={() => q.fetchNextPage()}
            disabled={q.isFetchingNextPage}
          >
            {q.isFetchingNextPage ? 'Loading…' : 'Load more'}
          </Button>
        </div>
      ) : null}
    </main>
  );
}
