'use client';

import { Badge, Card, CardContent, CardHeader, CardTitle, Spinner } from '@rsmm/ui';
import { useQuery } from '@tanstack/react-query';
import type { Route } from 'next';
import Link from 'next/link';
import { api } from '../../lib/api';

type Stats = Awaited<ReturnType<typeof api.moderation.stats>>;

const nf = new Intl.NumberFormat();
const fmt = (n: number | null | undefined) => (n == null ? '—' : nf.format(n));

/** Big number + label, with an optional secondary line for the trend. */
function Stat({
  label,
  value,
  sub,
  tone = 'default',
}: {
  label: string;
  value: string | number;
  sub?: string;
  tone?: 'default' | 'warn' | 'bad';
}) {
  const toneClass =
    tone === 'bad' ? 'text-destructive' : tone === 'warn' ? 'text-gilt' : 'text-foreground';
  return (
    <div className="rounded-lg border border-border/70 bg-background/50 px-4 py-3">
      <div className={`text-2xl font-bold tabular-nums leading-tight ${toneClass}`}>{value}</div>
      <div className="mt-0.5 text-xs font-medium text-muted-foreground">{label}</div>
      {sub ? <div className="mt-1 text-[0.7rem] text-muted-foreground/80">{sub}</div> : null}
    </div>
  );
}

/**
 * 30-day sparkline. Inline SVG on a 0..max scale with a flat baseline for an
 * all-zero series, so a quiet month draws a line rather than dividing by zero.
 */
function Spark({ data, label }: { data: { day: string; n: number }[]; label: string }) {
  if (data.length === 0) return null;
  const max = Math.max(...data.map((d) => d.n), 1);
  const w = 100;
  const h = 28;
  const step = data.length > 1 ? w / (data.length - 1) : 0;
  const points = data.map((d, i) => `${(i * step).toFixed(2)},${(h - (d.n / max) * h).toFixed(2)}`);
  const total = data.reduce((s, d) => s + d.n, 0);
  return (
    <div className="rounded-lg border border-border/70 bg-background/50 px-4 py-3">
      <div className="flex items-baseline justify-between">
        <span className="text-xs font-medium text-muted-foreground">{label}</span>
        <span className="text-sm font-semibold tabular-nums">{fmt(total)}</span>
      </div>
      <svg
        viewBox={`0 0 ${w} ${h}`}
        preserveAspectRatio="none"
        className="mt-2 h-8 w-full"
        role="img"
        aria-label={`${label}: ${total} over the last 30 days, peak ${max} in a day`}
      >
        <polyline
          points={points.join(' ')}
          fill="none"
          stroke="currentColor"
          strokeWidth={1.5}
          vectorEffect="non-scaling-stroke"
          className="text-crimson"
        />
      </svg>
      <div className="mt-1 text-[0.7rem] text-muted-foreground/80">
        peak {fmt(max)}/day · last 30 days
      </div>
    </div>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <Card className="grimoire-card">
      <CardHeader className="pb-3">
        <CardTitle className="text-base">{title}</CardTitle>
      </CardHeader>
      <CardContent>{children}</CardContent>
    </Card>
  );
}

/** Ranked list with a right-aligned count — top mods, OS split, version split. */
function Ranked({
  rows,
  href,
}: {
  rows: { key: string; label: string; n: number }[];
  // `typedRoutes` is on, so the builder must yield a Route, not a bare string.
  href?: (key: string) => Route;
}) {
  if (rows.length === 0) return <p className="text-sm text-muted-foreground">No data yet.</p>;
  const max = Math.max(...rows.map((r) => r.n), 1);
  return (
    <ul className="space-y-1.5">
      {rows.map((r) => (
        <li key={r.key} className="relative flex items-center justify-between gap-3 text-sm">
          <span
            aria-hidden="true"
            className="absolute inset-y-0 left-0 rounded bg-crimson/10"
            style={{ width: `${(r.n / max) * 100}%` }}
          />
          <span className="relative truncate px-1.5 py-0.5">
            {href ? (
              <Link href={href(r.key)} className="underline-offset-2 hover:underline">
                {r.label}
              </Link>
            ) : (
              r.label
            )}
          </span>
          <span className="relative shrink-0 px-1.5 font-mono text-xs tabular-nums text-muted-foreground">
            {fmt(r.n)}
          </span>
        </li>
      ))}
    </ul>
  );
}

export function AdminOverview() {
  const stats = useQuery({
    queryKey: ['admin', 'stats'],
    queryFn: () => api.moderation.stats(),
    // The console is opened to check on things; a minute-old snapshot is fine
    // and keeps a page refresh from re-running eighteen aggregates.
    staleTime: 60_000,
    retry: false,
  });

  if (stats.isLoading) {
    return (
      <div className="flex justify-center py-12">
        <Spinner />
      </div>
    );
  }
  if (stats.error || !stats.data) {
    return <p className="text-sm text-muted-foreground">Could not load statistics.</p>;
  }

  const s: Stats = stats.data;
  const consentTotal =
    s.consent.telemetryOff + s.consent.telemetryAnonymous + s.consent.telemetryLinked;
  const pct = (n: number) => (consentTotal ? `${Math.round((n / consentTotal) * 100)}%` : '—');

  return (
    <div className="space-y-6">
      <p className="text-xs text-muted-foreground">
        Snapshot taken {new Date(s.generatedAt).toLocaleString()}.
      </p>

      <Section title="Audience">
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <Stat
            label="Total accounts"
            value={fmt(s.users.total)}
            sub={`${fmt(s.users.verified)} email-verified`}
          />
          <Stat
            label="New today"
            value={fmt(s.users.new1d)}
            sub={`${fmt(s.users.new7d)} this week · ${fmt(s.users.new30d)} this month`}
          />
          <Stat
            label="Signed in now"
            value={fmt(s.users.active)}
            sub="accounts holding a live session"
          />
          <Stat
            label="Mod authors"
            value={fmt(s.users.creators)}
            sub={`${fmt(s.users.banned)} banned accounts`}
            tone={s.users.banned > 0 ? 'warn' : 'default'}
          />
        </div>
        <div className="mt-3 grid gap-3 sm:grid-cols-2">
          <Spark data={s.series.signups} label="Sign-ups" />
          <Spark data={s.series.downloads} label="Mod downloads" />
        </div>
      </Section>

      <Section title="Catalogue">
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <Stat
            label="Live mods"
            value={fmt(s.mods?.active)}
            sub={`${fmt(s.mods?.total)} total · ${fmt(s.mods?.hidden)} hidden · ${fmt(s.mods?.removed)} removed`}
          />
          <Stat
            label="New mods (30d)"
            value={fmt(s.mods?.new30d)}
            sub={`${fmt(s.mods?.new7d)} in the last week`}
          />
          <Stat
            label="Versions"
            value={fmt(s.versions?.total)}
            sub={`${fmt(s.versions?.new7d)} published this week`}
          />
          <Stat
            label="Awaiting scan"
            value={fmt(s.versions?.awaitingScan)}
            sub={`${fmt(s.versions?.flagged)} flagged · ${fmt(s.versions?.scanErrors)} errored`}
            tone={(s.versions?.awaitingScan ?? 0) > 0 ? 'warn' : 'default'}
          />
        </div>
        <div className="mt-3 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <Stat label="Featured" value={fmt(s.mods?.featured)} />
          <Stat label="NSFW" value={fmt(s.mods?.nsfw)} />
          <Stat
            label="No summary"
            value={fmt(s.mods?.noSummary)}
            sub="noindexed as thin content"
            tone={(s.mods?.noSummary ?? 0) > 0 ? 'warn' : 'default'}
          />
          <Stat
            label="Collections"
            value={fmt(s.collections)}
            sub={`${fmt(s.follows)} mod follows`}
          />
        </div>
      </Section>

      <Section title="Downloads">
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <Stat label="All time" value={fmt(s.downloads?.total)} />
          <Stat label="Last 24h" value={fmt(s.downloads?.d1)} />
          <Stat label="Last 7 days" value={fmt(s.downloads?.d7)} />
          <Stat label="Last 30 days" value={fmt(s.downloads?.d30)} />
        </div>
        <h3 className="mt-4 mb-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
          Top mods
        </h3>
        <Ranked
          rows={s.topMods.map((m) => ({ key: m.slug, label: m.name, n: m.downloads }))}
          href={(slug) => `/registry/${slug}` as Route}
        />
      </Section>

      <Section title="Client health">
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <Stat
            label="Applies (7d)"
            value={fmt(s.client.runs7d)}
            sub={`${fmt(s.client.runs30d)} in 30 days`}
          />
          <Stat
            label="Success rate (7d)"
            value={s.client.successRate7d == null ? '—' : `${s.client.successRate7d}%`}
            sub="share of applies reporting ok"
            tone={s.client.successRate7d != null && s.client.successRate7d < 90 ? 'bad' : 'default'}
          />
          <Stat
            label="Crashes (7d)"
            value={fmt(s.client.crashes7d)}
            sub={`${fmt(s.client.crashes30d)} in 30 days`}
            tone={s.client.crashes7d > 0 ? 'warn' : 'default'}
          />
          <Stat
            label="Reviews"
            value={fmt(s.reviews.total)}
            sub={`avg ${s.reviews.avgRating ?? '—'} ★ · ${fmt(s.reviews.new7d)} this week`}
          />
        </div>
        <div className="mt-4 grid gap-6 sm:grid-cols-2">
          <div>
            <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
              Platform (30d)
            </h3>
            <Ranked rows={s.client.osSplit.map((o) => ({ key: o.os, label: o.os, n: o.n }))} />
          </div>
          <div>
            <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
              Client version (30d)
            </h3>
            <Ranked
              rows={s.client.versionSplit.map((v) => ({
                key: v.version,
                label: v.version,
                n: v.n,
              }))}
            />
          </div>
        </div>
      </Section>

      <Section title="Queues">
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <Stat
            label="Open reports"
            value={fmt(s.reports?.open)}
            sub={`${fmt(s.reports?.reviewing)} in review · ${fmt(s.reports?.new7d)} new this week`}
            tone={(s.reports?.open ?? 0) > 0 ? 'warn' : 'default'}
          />
          <Stat
            label="Guides pending"
            value={fmt(s.guides?.pending)}
            sub={`${fmt(s.guides?.approved)} approved of ${fmt(s.guides?.total)}`}
            tone={(s.guides?.pending ?? 0) > 0 ? 'warn' : 'default'}
          />
          <Stat
            label="Flagged versions"
            value={fmt(s.versions?.flagged)}
            tone={(s.versions?.flagged ?? 0) > 0 ? 'bad' : 'default'}
          />
          <Stat
            label="Scan errors"
            value={fmt(s.versions?.scanErrors)}
            tone={(s.versions?.scanErrors ?? 0) > 0 ? 'warn' : 'default'}
          />
        </div>
      </Section>

      <Section title="Data-sharing consent">
        <p className="mb-3 text-xs text-muted-foreground">
          What accounts have chosen in{' '}
          <Link href="/account" className="underline underline-offset-2">
            Account → Privacy
          </Link>
          . Anonymous rows still count toward every figure above — they simply carry no user id.
        </p>
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <Stat
            label="Telemetry off"
            value={fmt(s.consent.telemetryOff)}
            sub={pct(s.consent.telemetryOff)}
          />
          <Stat
            label="Anonymous"
            value={fmt(s.consent.telemetryAnonymous)}
            sub={pct(s.consent.telemetryAnonymous)}
          />
          <Stat
            label="Linked to account"
            value={fmt(s.consent.telemetryLinked)}
            sub={pct(s.consent.telemetryLinked)}
          />
          <Stat
            label="Announcement opt-in"
            value={fmt(s.consent.announcementOptIn)}
            sub={`of ${fmt(s.users.total)} accounts`}
          />
        </div>
        <div className="mt-3">
          <Badge variant="outline" className="text-[0.7rem]">
            Aggregates only — this console never shows an individual&apos;s telemetry.
          </Badge>
        </div>
      </Section>
    </div>
  );
}
