'use client';

import { Spinner } from '@rsmm/ui';
import { useQuery } from '@tanstack/react-query';
import {
  Activity,
  AlertTriangle,
  BookOpen,
  CheckCircle2,
  Download,
  Flag,
  Library,
  type LucideIcon,
  ShieldAlert,
  ShieldCheck,
  Users,
} from 'lucide-react';
import type { Route } from 'next';
import Link from 'next/link';
import { api } from '../../lib/api';

type Stats = Awaited<ReturnType<typeof api.moderation.stats>>;
type Tone = 'default' | 'warn' | 'bad';

const nf = new Intl.NumberFormat();
const fmt = (n: number | null | undefined) => (n == null ? '—' : nf.format(n));

/** The admin console's shared stats query: the page header reads the same
 *  snapshot for its attention chips, so both share one cache entry. */
export function useAdminStats(enabled = true) {
  return useQuery({
    queryKey: ['admin', 'stats'],
    queryFn: () => api.moderation.stats(),
    enabled,
    // The console is opened to check on things; a minute-old snapshot is fine
    // and keeps a page refresh from re-running eighteen aggregates.
    staleTime: 60_000,
    retry: false,
  });
}

const TONE_EDGE: Record<Tone, string> = {
  default: 'border-l-border/70',
  warn: 'border-l-gilt/70',
  bad: 'border-l-destructive/80',
};
const TONE_TEXT: Record<Tone, string> = {
  default: 'text-parchment',
  warn: 'text-gilt',
  bad: 'text-destructive',
};

/** Big number + label, with an optional secondary line. A coloured left edge
 *  marks a figure that wants attention, so the eye finds it without reading. */
function Stat({
  label,
  value,
  sub,
  tone = 'default',
}: {
  label: string;
  value: string | number;
  sub?: string;
  tone?: Tone;
}) {
  return (
    <div
      className={`rounded-md border border-l-2 border-border/60 ${TONE_EDGE[tone]} bg-background/40 px-4 py-3`}
    >
      <div className="text-[0.68rem] font-semibold uppercase tracking-[0.12em] text-muted-foreground">
        {label}
      </div>
      <div className={`mt-1 font-display text-3xl leading-none tabular-nums ${TONE_TEXT[tone]}`}>
        {value}
      </div>
      {sub ? <div className="mt-2 text-xs text-muted-foreground/90">{sub}</div> : null}
    </div>
  );
}

/**
 * 30-day sparkline. Inline SVG on a 0..max scale with a flat baseline for an
 * all-zero series, so a quiet month draws a line rather than dividing by zero.
 * A soft fill under the line and a dot on today make the shape readable at a
 * glance; the numbers stay in the text for screen readers.
 */
function Spark({
  data,
  label,
  id,
}: { data: { day: string; n: number }[]; label: string; id: string }) {
  if (data.length === 0) return null;
  const max = Math.max(...data.map((d) => d.n), 1);
  const w = 100;
  const h = 32;
  const step = data.length > 1 ? w / (data.length - 1) : 0;
  const pts = data.map((d, i) => [i * step, h - (d.n / max) * (h - 2) - 1] as const);
  const line = pts.map(([x, y]) => `${x.toFixed(2)},${y.toFixed(2)}`).join(' ');
  const area = `0,${h} ${line} ${w},${h}`;
  const total = data.reduce((s, d) => s + d.n, 0);
  const today = data[data.length - 1]?.n ?? 0;
  const last = pts[pts.length - 1];
  return (
    <div className="rounded-md border border-border/60 bg-background/40 px-4 py-3">
      <div className="flex items-baseline justify-between gap-3">
        <span className="text-[0.68rem] font-semibold uppercase tracking-[0.12em] text-muted-foreground">
          {label}
        </span>
        <span className="font-display text-xl tabular-nums text-parchment">{fmt(total)}</span>
      </div>
      <svg
        viewBox={`0 0 ${w} ${h}`}
        preserveAspectRatio="none"
        className="mt-2 h-12 w-full text-crimson"
        role="img"
        aria-label={`${label}: ${total} over the last 30 days, peak ${max} in a day, ${today} today`}
      >
        <defs>
          <linearGradient id={`spark-${id}`} x1="0" x2="0" y1="0" y2="1">
            <stop offset="0%" stopColor="currentColor" stopOpacity={0.35} />
            <stop offset="100%" stopColor="currentColor" stopOpacity={0} />
          </linearGradient>
        </defs>
        <polygon points={area} fill={`url(#spark-${id})`} />
        <polyline
          points={line}
          fill="none"
          stroke="currentColor"
          strokeWidth={1.75}
          vectorEffect="non-scaling-stroke"
          strokeLinejoin="round"
        />
        {last ? (
          <circle
            cx={last[0]}
            cy={last[1]}
            r={1.6}
            className="fill-gilt"
            vectorEffect="non-scaling-stroke"
          />
        ) : null}
      </svg>
      <div className="mt-1 flex justify-between text-xs text-muted-foreground/90">
        <span>last 30 days</span>
        <span className="tabular-nums">
          peak {fmt(max)}/day · {fmt(today)} today
        </span>
      </div>
    </div>
  );
}

function Section({
  title,
  icon: Icon,
  aside,
  children,
}: {
  title: string;
  icon: LucideIcon;
  aside?: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <section className="grimoire-card p-5 sm:p-6">
      <header className="mb-4 flex flex-wrap items-center justify-between gap-2">
        <h2 className="flex items-center gap-2.5 font-display text-2xl text-parchment">
          <Icon className="h-5 w-5 text-gilt/80" aria-hidden />
          {title}
        </h2>
        {aside}
      </header>
      {children}
    </section>
  );
}

function SubHeading({ children }: { children: React.ReactNode }) {
  return (
    <h3 className="mb-2 text-[0.68rem] font-semibold uppercase tracking-[0.12em] text-muted-foreground">
      {children}
    </h3>
  );
}

/** Ranked list with a right-aligned count and share — top mods, OS, version. */
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
  const sum = rows.reduce((s, r) => s + r.n, 0) || 1;
  return (
    <ol className="space-y-1">
      {rows.map((r, i) => (
        <li
          key={r.key}
          className="relative flex items-center justify-between gap-3 overflow-hidden rounded text-sm"
        >
          <span
            aria-hidden="true"
            className="absolute inset-y-0 left-0 rounded bg-gradient-to-r from-crimson/25 to-crimson/5"
            style={{ width: `${(r.n / max) * 100}%` }}
          />
          <span className="relative flex min-w-0 items-center gap-2 px-2 py-1">
            <span className="w-4 shrink-0 text-right font-mono text-[0.7rem] text-muted-foreground/70">
              {i + 1}
            </span>
            {href ? (
              <Link
                href={href(r.key)}
                className="truncate text-parchment underline-offset-2 hover:underline"
              >
                {r.label}
              </Link>
            ) : (
              <span className="truncate text-parchment">{r.label}</span>
            )}
          </span>
          <span className="relative flex shrink-0 items-baseline gap-2 px-2 font-mono text-xs tabular-nums">
            <span className="text-parchment">{fmt(r.n)}</span>
            <span className="w-9 text-right text-muted-foreground/70">
              {Math.round((r.n / sum) * 100)}%
            </span>
          </span>
        </li>
      ))}
    </ol>
  );
}

/** One queue item that has something waiting; the strip shows only these. */
function Attention({
  icon: Icon,
  label,
  n,
  tone,
  onClick,
}: {
  icon: LucideIcon;
  label: string;
  n: number;
  tone: 'warn' | 'bad';
  onClick?: () => void;
}) {
  const cls =
    tone === 'bad'
      ? 'border-destructive/50 bg-destructive/10 text-destructive'
      : 'border-gilt/40 bg-gilt/10 text-gilt';
  const inner = (
    <>
      <Icon className="h-4 w-4 shrink-0" aria-hidden />
      <span className="font-display text-xl tabular-nums leading-none">{fmt(n)}</span>
      <span className="text-sm text-parchment/90">{label}</span>
    </>
  );
  return onClick ? (
    <button
      type="button"
      onClick={onClick}
      className={`flex items-center gap-2.5 rounded-md border px-3.5 py-2.5 text-left transition-colors hover:brightness-125 ${cls}`}
    >
      {inner}
    </button>
  ) : (
    <div className={`flex items-center gap-2.5 rounded-md border px-3.5 py-2.5 ${cls}`}>
      {inner}
    </div>
  );
}

export function AdminOverview({ onOpenReports }: { onOpenReports: () => void }) {
  const stats = useAdminStats();

  if (stats.isLoading) {
    return (
      <div className="flex justify-center py-16">
        <Spinner />
      </div>
    );
  }
  if (stats.error || !stats.data) {
    return (
      <div className="grimoire-card flex items-center gap-3 p-6 text-sm text-muted-foreground">
        <AlertTriangle className="h-5 w-5 text-gilt" aria-hidden />
        Could not load statistics. Try the refresh button above.
      </div>
    );
  }

  const s: Stats = stats.data;
  const consentTotal =
    s.consent.telemetryOff + s.consent.telemetryAnonymous + s.consent.telemetryLinked;
  const pct = (n: number) => (consentTotal ? `${Math.round((n / consentTotal) * 100)}%` : '—');

  const attention = [
    {
      key: 'reports',
      icon: Flag,
      label: 'open reports',
      n: s.reports?.open ?? 0,
      tone: 'warn' as const,
      onClick: onOpenReports,
    },
    {
      key: 'flagged',
      icon: ShieldAlert,
      label: 'flagged versions',
      n: s.versions?.flagged ?? 0,
      tone: 'bad' as const,
    },
    {
      key: 'scanErr',
      icon: AlertTriangle,
      label: 'scan errors',
      n: s.versions?.scanErrors ?? 0,
      tone: 'warn' as const,
    },
    {
      key: 'awaiting',
      icon: Activity,
      label: 'awaiting scan',
      n: s.versions?.awaitingScan ?? 0,
      tone: 'warn' as const,
    },
    {
      key: 'guides',
      icon: BookOpen,
      label: 'guides pending',
      n: s.guides?.pending ?? 0,
      tone: 'warn' as const,
    },
  ].filter((a) => a.n > 0);

  return (
    <div className="space-y-6">
      <section aria-label="Needs attention">
        {attention.length ? (
          <div className="flex flex-wrap gap-3">
            {attention.map(({ key, ...a }) => (
              <Attention key={key} {...a} />
            ))}
          </div>
        ) : (
          <div className="flex items-center gap-2.5 rounded-md border border-border/60 bg-background/40 px-4 py-3 text-sm text-muted-foreground">
            <CheckCircle2 className="h-4 w-4 text-gilt/80" aria-hidden />
            All quiet: no open reports, flagged versions or pending scans.
          </div>
        )}
      </section>

      <Section title="Audience" icon={Users}>
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
          <Spark id="signups" data={s.series.signups} label="Sign-ups" />
          <Spark id="downloads" data={s.series.downloads} label="Mod downloads" />
        </div>
      </Section>

      <div className="grid gap-6 xl:grid-cols-2">
        <Section title="Catalogue" icon={Library}>
          <div className="grid gap-3 sm:grid-cols-2">
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

        <Section title="Downloads" icon={Download}>
          <div className="grid gap-3 grid-cols-2">
            <Stat label="All time" value={fmt(s.downloads?.total)} />
            <Stat label="Last 24h" value={fmt(s.downloads?.d1)} />
            <Stat label="Last 7 days" value={fmt(s.downloads?.d7)} />
            <Stat label="Last 30 days" value={fmt(s.downloads?.d30)} />
          </div>
          <div className="mt-5">
            <SubHeading>Top mods</SubHeading>
            <Ranked
              rows={s.topMods.map((m) => ({ key: m.slug, label: m.name, n: m.downloads }))}
              href={(slug) => `/registry/${slug}` as Route}
            />
          </div>
        </Section>
      </div>

      <Section title="Client health" icon={Activity}>
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
        <div className="mt-5 grid gap-6 sm:grid-cols-2">
          <div>
            <SubHeading>Platform (30d)</SubHeading>
            <Ranked rows={s.client.osSplit.map((o) => ({ key: o.os, label: o.os, n: o.n }))} />
          </div>
          <div>
            <SubHeading>Client version (30d)</SubHeading>
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

      <div className="grid gap-6 xl:grid-cols-2">
        <Section title="Queues" icon={Flag}>
          <div className="grid gap-3 sm:grid-cols-2">
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

        <Section title="Data-sharing consent" icon={ShieldCheck}>
          <p className="mb-4 text-xs text-muted-foreground">
            What accounts have chosen in{' '}
            <Link href="/account" className="underline underline-offset-2">
              Account → Privacy
            </Link>
            . Anonymous rows still count toward every figure above — they simply carry no user id.
          </p>
          <div className="grid gap-3 sm:grid-cols-2">
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
          <p className="mt-4 flex items-center gap-2 text-xs text-muted-foreground">
            <ShieldCheck className="h-3.5 w-3.5 text-gilt/70" aria-hidden />
            Aggregates only — this console never shows an individual&apos;s telemetry.
          </p>
        </Section>
      </div>
    </div>
  );
}
