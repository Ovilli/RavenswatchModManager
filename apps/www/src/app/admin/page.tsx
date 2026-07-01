'use client';
import { ApiError } from '@rsmm/api-client';
import { Badge, Button, Spinner } from '@rsmm/ui';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import Link from 'next/link';
import { useState } from 'react';
import { api } from '../../lib/api';
import { useSession } from '../../lib/auth-client';

type Status = 'open' | 'reviewing' | 'resolved' | 'dismissed';

const STATUS_TABS: Status[] = ['open', 'reviewing', 'resolved', 'dismissed'];

export default function AdminPage() {
  const { data: session, isPending } = useSession();
  const [tab, setTab] = useState<Status>('open');
  const qc = useQueryClient();

  const reports = useQuery({
    queryKey: ['admin', 'reports', tab],
    queryFn: () => api.moderation.reports(tab),
    enabled: !!session,
    retry: false,
  });

  const invalidate = () => qc.invalidateQueries({ queryKey: ['admin', 'reports'] });

  const resolve = useMutation({
    mutationFn: (v: { id: string; status: Status; note?: string }) =>
      api.moderation.resolveReport(v.id, { status: v.status, resolutionNote: v.note ?? null }),
    onSuccess: invalidate,
  });
  const takedown = useMutation({
    mutationFn: (v: { slug: string; status: 'active' | 'hidden' | 'removed'; reason?: string }) =>
      api.moderation.takedown(v.slug, { takedownStatus: v.status, reason: v.reason ?? null }),
    onSuccess: invalidate,
  });
  const feature = useMutation({
    mutationFn: (v: { slug: string; featured: boolean }) =>
      api.moderation.feature(v.slug, v.featured),
    onSuccess: invalidate,
  });
  const ban = useMutation({
    mutationFn: (v: { id: string; banned: boolean; reason?: string }) =>
      api.moderation.banUser(v.id, { banned: v.banned, reason: v.reason ?? null }),
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
          to access moderation.
        </p>
      </main>
    );
  }
  const forbidden = reports.error instanceof ApiError && reports.error.status === 403;
  if (forbidden) {
    return (
      <main className="container mx-auto px-6 py-12">
        <h1 className="text-2xl font-bold">Moderation</h1>
        <p className="mt-4 text-muted-foreground">You are not a moderator.</p>
      </main>
    );
  }

  return (
    <main className="container mx-auto space-y-6 px-6 py-10">
      <h1 className="text-3xl font-bold tracking-tight">Moderation console</h1>

      <div className="flex gap-2">
        {STATUS_TABS.map((s) => (
          <Button
            key={s}
            variant={tab === s ? 'default' : 'outline'}
            size="sm"
            onClick={() => setTab(s)}
          >
            {s}
          </Button>
        ))}
      </div>

      {reports.isLoading ? (
        <Spinner />
      ) : reports.data && reports.data.items.length === 0 ? (
        <p className="text-muted-foreground">No {tab} reports.</p>
      ) : (
        <ul className="space-y-4">
          {reports.data?.items.map((r) => (
            <li key={r.id} className="rounded-lg border border-border p-4">
              <div className="flex flex-wrap items-center gap-2">
                <Badge variant="outline">{r.reason}</Badge>
                <Badge variant={r.status === 'open' ? 'default' : 'secondary'}>{r.status}</Badge>
                {r.takedownStatus !== 'active' && (
                  <Badge variant="destructive">{r.takedownStatus}</Badge>
                )}
                <Link
                  href={`/registry/${r.modSlug}`}
                  className="font-medium underline underline-offset-2"
                >
                  {r.modName}
                </Link>
                <span className="text-xs text-muted-foreground">
                  by {r.reporterName ?? 'anonymous'} · {new Date(r.createdAt).toLocaleString()}
                </span>
              </div>
              {r.detail && <p className="mt-2 text-sm text-muted-foreground">{r.detail}</p>}
              {r.resolutionNote && (
                <p className="mt-1 text-xs text-muted-foreground">Note: {r.resolutionNote}</p>
              )}

              <div className="mt-3 flex flex-wrap gap-2">
                <Button
                  size="sm"
                  variant="outline"
                  onClick={() => resolve.mutate({ id: r.id, status: 'reviewing' })}
                >
                  Mark reviewing
                </Button>
                <Button
                  size="sm"
                  variant="outline"
                  onClick={() => resolve.mutate({ id: r.id, status: 'resolved' })}
                >
                  Resolve
                </Button>
                <Button
                  size="sm"
                  variant="ghost"
                  onClick={() => resolve.mutate({ id: r.id, status: 'dismissed' })}
                >
                  Dismiss
                </Button>
                {r.takedownStatus === 'active' ? (
                  <Button
                    size="sm"
                    variant="destructive"
                    onClick={() =>
                      takedown.mutate({ slug: r.modSlug, status: 'removed', reason: r.reason })
                    }
                  >
                    Take down
                  </Button>
                ) : (
                  <Button
                    size="sm"
                    variant="outline"
                    onClick={() => takedown.mutate({ slug: r.modSlug, status: 'active' })}
                  >
                    Restore
                  </Button>
                )}
                <Button
                  size="sm"
                  variant="ghost"
                  onClick={() => feature.mutate({ slug: r.modSlug, featured: true })}
                >
                  Feature
                </Button>
                {r.reporterId && (
                  <Button
                    size="sm"
                    variant="ghost"
                    className="text-destructive"
                    onClick={() =>
                      ban.mutate({ id: r.reporterId as string, banned: true, reason: 'abuse' })
                    }
                  >
                    Ban reporter
                  </Button>
                )}
              </div>
            </li>
          ))}
        </ul>
      )}
    </main>
  );
}
