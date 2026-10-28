'use client';
import { ApiError } from '@rsmm/api-client';
import { Badge, Button, Spinner, buttonVariants } from '@rsmm/ui';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  Ban,
  BarChart3,
  BookOpen,
  Check,
  Eye,
  Flag,
  Inbox,
  RefreshCw,
  RotateCcw,
  ShieldAlert,
  Star,
  Trash2,
  X,
} from 'lucide-react';
import type { Route } from 'next';
import Link from 'next/link';
import { useState } from 'react';
import { api } from '../../lib/api';
import { useSession } from '../../lib/auth-client';
import { AdminOverview, useAdminStats } from './overview';

type Status = 'open' | 'reviewing' | 'resolved' | 'dismissed';

const STATUS_TABS: Status[] = ['open', 'reviewing', 'resolved', 'dismissed'];
const STATUS_LABEL: Record<Status, string> = {
  open: 'Open',
  reviewing: 'In review',
  resolved: 'Resolved',
  dismissed: 'Dismissed',
};
/** A report card's left edge: what still needs a moderator stands out. */
const STATUS_EDGE: Record<Status, string> = {
  open: 'border-l-gilt/80',
  reviewing: 'border-l-crimson/80',
  resolved: 'border-l-border',
  dismissed: 'border-l-border',
};

type Pane = 'inbox' | 'stats';

function Centered({ children }: { children: React.ReactNode }) {
  return <main className="container mx-auto px-6 py-16">{children}</main>;
}

export default function AdminPage() {
  const { data: session, isPending } = useSession();
  // null until the admin picks a tab: then it opens on the Inbox when
  // anything is waiting, otherwise on Stats.
  const [picked, setPicked] = useState<Pane | null>(null);
  const [tab, setTab] = useState<Status>('open');
  const qc = useQueryClient();
  const stats = useAdminStats(!!session);

  const reports = useQuery({
    queryKey: ['admin', 'reports', tab],
    queryFn: () => api.moderation.reports(tab),
    enabled: !!session,
    retry: false,
  });

  const pendingGuides = useQuery({
    queryKey: ['guides', 'pending'],
    queryFn: () => api.guides.pending(),
    enabled: !!session,
    retry: false,
  });

  const invalidate = () => {
    void qc.invalidateQueries({ queryKey: ['admin', 'reports'] });
    void qc.invalidateQueries({ queryKey: ['admin', 'stats'] });
  };

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
  const guideDecision = useMutation({
    mutationFn: (v: { slug: string; approve: boolean }) =>
      v.approve ? api.guides.approve(v.slug) : api.guides.reject(v.slug),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['guides'] });
      invalidate();
    },
  });
  const ban = useMutation({
    mutationFn: (v: { id: string; banned: boolean; reason?: string }) =>
      api.moderation.banUser(v.id, { banned: v.banned, reason: v.reason ?? null }),
    onSuccess: invalidate,
  });
  const busy =
    resolve.isPending ||
    takedown.isPending ||
    feature.isPending ||
    ban.isPending ||
    guideDecision.isPending;
  const failure = [resolve, takedown, feature, ban, guideDecision].find((m) => m.error)?.error;

  if (isPending) {
    return (
      <Centered>
        <div className="flex justify-center">
          <Spinner />
        </div>
      </Centered>
    );
  }
  if (!session) {
    return (
      <Centered>
        <div className="grimoire-card mx-auto max-w-md p-8 text-center">
          <ShieldAlert className="mx-auto h-8 w-8 text-gilt/80" aria-hidden />
          <h1 className="mt-3 font-display text-3xl text-parchment">Moderators only</h1>
          <p className="mt-2 text-sm text-muted-foreground">
            Please{' '}
            <Link href="/auth/signin" className="underline underline-offset-2">
              sign in
            </Link>{' '}
            to open the admin console.
          </p>
        </div>
      </Centered>
    );
  }
  const forbidden = reports.error instanceof ApiError && reports.error.status === 403;
  if (forbidden) {
    return (
      <Centered>
        <div className="grimoire-card mx-auto max-w-md p-8 text-center">
          <ShieldAlert className="mx-auto h-8 w-8 text-gilt/80" aria-hidden />
          <h1 className="mt-3 font-display text-3xl text-parchment">Moderators only</h1>
          <p className="mt-2 text-sm text-muted-foreground">This account is not a moderator.</p>
        </div>
      </Centered>
    );
  }

  const openCount = stats.data?.reports?.open ?? 0;
  const guides = pendingGuides.data?.items ?? [];
  const scans = {
    flagged: stats.data?.versions?.flagged ?? 0,
    errors: stats.data?.versions?.scanErrors ?? 0,
    waiting: stats.data?.versions?.awaitingScan ?? 0,
  };
  const scanCount = scans.flagged + scans.errors + scans.waiting;
  const waiting = openCount + guides.length + scans.flagged + scans.errors;
  const pane: Pane = picked ?? (waiting > 0 ? 'inbox' : 'stats');
  // Don't pick the opening tab until the counts are in, or it opens on Stats
  // and jumps to the Inbox a moment later.
  const deciding = picked === null && (stats.isLoading || pendingGuides.isLoading);
  const counts: Partial<Record<Status, number>> = {
    open: stats.data?.reports?.open,
    reviewing: stats.data?.reports?.reviewing,
  };
  const refresh = () => {
    void qc.invalidateQueries({ queryKey: ['admin'] });
    void qc.invalidateQueries({ queryKey: ['guides', 'pending'] });
  };
  const confirmThen = (message: string, run: () => void) => {
    if (window.confirm(message)) run();
  };

  return (
    <main className="container mx-auto space-y-10 px-6 py-12">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="font-display text-5xl text-parchment">Admin</h1>
          <p className="mt-1 text-muted-foreground">
            What is waiting on you, and how the site is doing.
            {stats.data ? (
              <> Updated {new Date(stats.data.generatedAt).toLocaleTimeString()}.</>
            ) : null}
          </p>
        </div>
        <Button
          variant="outline"
          size="sm"
          onClick={refresh}
          disabled={stats.isFetching || reports.isFetching}
          className="gap-2"
        >
          <RefreshCw
            className={`h-4 w-4 ${stats.isFetching || reports.isFetching ? 'animate-spin' : ''}`}
            aria-hidden
          />
          Refresh
        </Button>
      </div>

      <div className="flex flex-wrap gap-2" role="tablist" aria-label="Admin sections">
        {(
          [
            ['inbox', 'Inbox', Inbox, waiting],
            ['stats', 'Stats', BarChart3, 0],
          ] as const
        ).map(([id, label, Icon, n]) => (
          <button
            key={id}
            type="button"
            role="tab"
            aria-selected={!deciding && pane === id}
            onClick={() => setPicked(id)}
            className={`${buttonVariants({ variant: !deciding && pane === id ? 'default' : 'outline', size: 'sm' })} gap-2`}
          >
            <Icon className="h-4 w-4" aria-hidden />
            {label}
            {n > 0 ? <span className="tabular-nums opacity-80">{n}</span> : null}
          </button>
        ))}
      </div>

      {deciding ? (
        <div className="flex justify-center py-16">
          <Spinner />
        </div>
      ) : null}

      {!deciding && pane === 'stats' ? <AdminOverview /> : null}

      <div className={!deciding && pane === 'inbox' ? 'space-y-10' : 'hidden'}>
        {failure ? (
          <p className="rounded-md border border-destructive/50 bg-destructive/10 px-4 py-2.5 text-sm text-destructive">
            That action failed: {failure instanceof Error ? failure.message : String(failure)}
          </p>
        ) : null}

        {waiting === 0 && !pendingGuides.isLoading && !stats.isLoading ? (
          <div className="grimoire-card flex flex-col items-center gap-3 p-10 text-center">
            <Check className="h-8 w-8 text-gilt/80" aria-hidden />
            <p className="text-lg font-semibold text-parchment">Nothing is waiting on you</p>
            <p className="text-sm text-muted-foreground">
              No guides to review, no open reports, no failed scans.
            </p>
          </div>
        ) : null}

        {guides.length > 0 ? (
          <section className="space-y-3">
            <h2 className="flex items-center gap-2 text-xl font-semibold tracking-tight">
              <BookOpen className="h-5 w-5 text-gilt/80" aria-hidden />
              Guides awaiting review
              <span className="text-base font-normal text-muted-foreground">{guides.length}</span>
            </h2>
            <ul className="space-y-3">
              {guides.map((g) => (
                <li
                  key={g.id}
                  className="grimoire-card flex flex-col gap-4 p-5 sm:flex-row sm:items-center sm:justify-between"
                >
                  <div className="min-w-0">
                    <Link
                      href={`/guides/${g.slug}` as Route}
                      className="font-semibold text-parchment underline-offset-4 hover:underline"
                    >
                      {g.title}
                    </Link>
                    <p className="mt-0.5 text-xs text-muted-foreground">
                      {g.ownerName ?? 'unknown'} · updated{' '}
                      {new Date(g.updatedAt).toLocaleDateString()}
                    </p>
                    {g.summary ? (
                      <p className="mt-2 line-clamp-2 text-sm text-muted-foreground">{g.summary}</p>
                    ) : null}
                  </div>
                  <div className="flex shrink-0 items-center gap-2">
                    <Link
                      href={`/guides/${g.slug}` as Route}
                      className={buttonVariants({ variant: 'ghost', size: 'sm' })}
                    >
                      Read
                    </Link>
                    <Button
                      size="sm"
                      variant="outline"
                      className="gap-1.5"
                      disabled={busy}
                      onClick={() => guideDecision.mutate({ slug: g.slug, approve: false })}
                    >
                      <X className="h-3.5 w-3.5" aria-hidden /> Reject
                    </Button>
                    <Button
                      size="sm"
                      className="gap-1.5"
                      disabled={busy}
                      onClick={() => guideDecision.mutate({ slug: g.slug, approve: true })}
                    >
                      <Check className="h-3.5 w-3.5" aria-hidden /> Approve
                    </Button>
                  </div>
                </li>
              ))}
            </ul>
          </section>
        ) : null}

        {scanCount > 0 ? (
          <section className="space-y-3">
            <h2 className="flex items-center gap-2 text-xl font-semibold tracking-tight">
              <ShieldAlert className="h-5 w-5 text-gilt/80" aria-hidden />
              Mod scans
            </h2>
            <div className="grimoire-card flex flex-wrap gap-x-8 gap-y-2 p-5 text-sm">
              {scans.flagged > 0 ? (
                <span className="text-destructive">
                  <strong className="font-display text-xl">{scans.flagged}</strong> flagged by the
                  malware scan
                </span>
              ) : null}
              {scans.errors > 0 ? (
                <span className="text-gilt">
                  <strong className="font-display text-xl">{scans.errors}</strong> scans errored
                </span>
              ) : null}
              {scans.waiting > 0 ? (
                <span className="text-muted-foreground">
                  <strong className="font-display text-xl text-parchment">{scans.waiting}</strong>{' '}
                  still scanning
                </span>
              ) : null}
            </div>
          </section>
        ) : null}

        <section className="space-y-3">
          <h2 className="flex items-center gap-2 text-xl font-semibold tracking-tight">
            <Flag className="h-5 w-5 text-gilt/80" aria-hidden />
            Reports
          </h2>
          <div className="flex flex-wrap gap-2" role="tablist" aria-label="Report status">
            {STATUS_TABS.map((s) => (
              <button
                key={s}
                type="button"
                role="tab"
                aria-selected={tab === s}
                onClick={() => setTab(s)}
                className={`${buttonVariants({ variant: tab === s ? 'default' : 'outline', size: 'sm' })} gap-2`}
              >
                {STATUS_LABEL[s]}
                {counts[s] ? <span className="tabular-nums opacity-80">{counts[s]}</span> : null}
              </button>
            ))}
          </div>

          {reports.isLoading ? (
            <div className="flex justify-center py-16">
              <Spinner />
            </div>
          ) : reports.isError ? (
            <p className="text-sm text-destructive">Could not load reports.</p>
          ) : reports.data && reports.data.items.length === 0 ? (
            <div className="grimoire-card p-10 text-center">
              <Check className="mx-auto h-8 w-8 text-gilt/80" aria-hidden />
              <p className="mt-3 text-lg font-semibold text-parchment">
                No {STATUS_LABEL[tab].toLowerCase()} reports
              </p>
              <p className="mt-1 text-sm text-muted-foreground">
                {tab === 'open' ? 'Nothing is waiting for a moderator.' : 'Nothing here yet.'}
              </p>
            </div>
          ) : (
            <ul className="space-y-4">
              {reports.data?.items.map((r) => (
                <li
                  key={r.id}
                  className={`grimoire-card border-l-2 ${STATUS_EDGE[r.status as Status] ?? 'border-l-border'} p-5`}
                >
                  <div className="flex flex-wrap items-start justify-between gap-3">
                    <div className="min-w-0">
                      <Link
                        href={`/registry/${r.modSlug}`}
                        className="text-lg font-semibold text-parchment underline-offset-4 hover:underline"
                      >
                        {r.modName}
                      </Link>
                      <p className="mt-1 text-xs text-muted-foreground">
                        Reported by {r.reporterName ?? 'anonymous'} ·{' '}
                        {new Date(r.createdAt).toLocaleString()}
                      </p>
                    </div>
                    <div className="flex flex-wrap items-center gap-1.5">
                      <Badge variant="outline" className="capitalize">
                        {r.reason}
                      </Badge>
                      <Badge variant={r.status === 'open' ? 'default' : 'secondary'}>
                        {STATUS_LABEL[r.status as Status] ?? r.status}
                      </Badge>
                      {r.takedownStatus !== 'active' && (
                        <Badge variant="destructive" className="capitalize">
                          {r.takedownStatus}
                        </Badge>
                      )}
                    </div>
                  </div>

                  {r.detail && (
                    <blockquote className="mt-4 border-l-2 border-gilt/40 bg-background/40 px-4 py-2.5 text-sm text-parchment/90">
                      {r.detail}
                    </blockquote>
                  )}
                  {r.resolutionNote && (
                    <p className="mt-2 text-xs text-muted-foreground">
                      Moderator note: {r.resolutionNote}
                    </p>
                  )}

                  <div className="mt-5 flex flex-wrap items-center gap-x-6 gap-y-3 border-t border-border/50 pt-4">
                    <ActionGroup label="Triage">
                      <Button
                        size="sm"
                        variant="outline"
                        className="gap-1.5"
                        disabled={busy || r.status === 'reviewing'}
                        onClick={() => resolve.mutate({ id: r.id, status: 'reviewing' })}
                      >
                        <Eye className="h-3.5 w-3.5" aria-hidden /> Review
                      </Button>
                      <Button
                        size="sm"
                        variant="outline"
                        className="gap-1.5"
                        disabled={busy || r.status === 'resolved'}
                        onClick={() => resolve.mutate({ id: r.id, status: 'resolved' })}
                      >
                        <Check className="h-3.5 w-3.5" aria-hidden /> Resolve
                      </Button>
                      <Button
                        size="sm"
                        variant="ghost"
                        className="gap-1.5"
                        disabled={busy || r.status === 'dismissed'}
                        onClick={() => resolve.mutate({ id: r.id, status: 'dismissed' })}
                      >
                        <X className="h-3.5 w-3.5" aria-hidden /> Dismiss
                      </Button>
                    </ActionGroup>

                    <ActionGroup label="Mod">
                      {r.takedownStatus === 'active' ? (
                        <Button
                          size="sm"
                          variant="destructive"
                          className="gap-1.5"
                          disabled={busy}
                          onClick={() =>
                            confirmThen(
                              `Take down “${r.modName}”? It disappears from the site.`,
                              () =>
                                takedown.mutate({
                                  slug: r.modSlug,
                                  status: 'removed',
                                  reason: r.reason,
                                }),
                            )
                          }
                        >
                          <Trash2 className="h-3.5 w-3.5" aria-hidden /> Take down
                        </Button>
                      ) : (
                        <Button
                          size="sm"
                          variant="outline"
                          className="gap-1.5"
                          disabled={busy}
                          onClick={() => takedown.mutate({ slug: r.modSlug, status: 'active' })}
                        >
                          <RotateCcw className="h-3.5 w-3.5" aria-hidden /> Restore
                        </Button>
                      )}
                      <Button
                        size="sm"
                        variant="ghost"
                        className="gap-1.5"
                        disabled={busy}
                        onClick={() => feature.mutate({ slug: r.modSlug, featured: true })}
                      >
                        <Star className="h-3.5 w-3.5" aria-hidden /> Feature
                      </Button>
                    </ActionGroup>

                    {r.reporterId && (
                      <ActionGroup label="Reporter">
                        <Button
                          size="sm"
                          variant="ghost"
                          className="gap-1.5 text-destructive hover:text-destructive"
                          disabled={busy}
                          onClick={() =>
                            confirmThen(
                              `Ban ${r.reporterName ?? 'this reporter'} for abusing reports?`,
                              () =>
                                ban.mutate({
                                  id: r.reporterId as string,
                                  banned: true,
                                  reason: 'abuse',
                                }),
                            )
                          }
                        >
                          <Ban className="h-3.5 w-3.5" aria-hidden /> Ban reporter
                        </Button>
                      </ActionGroup>
                    )}
                  </div>
                </li>
              ))}
            </ul>
          )}
        </section>
      </div>
    </main>
  );
}

/** A labelled cluster of report actions, so destructive ones sit apart. */
function ActionGroup({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex flex-wrap items-center gap-2">
      <span className="text-[0.68rem] font-semibold uppercase tracking-[0.12em] text-muted-foreground/80">
        {label}
      </span>
      {children}
    </div>
  );
}
