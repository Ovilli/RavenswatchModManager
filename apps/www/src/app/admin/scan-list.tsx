'use client';

import { Spinner, buttonVariants } from '@rsmm/ui';
import { useQuery } from '@tanstack/react-query';
import {
  AlertTriangle,
  CheckCircle2,
  ExternalLink,
  Loader2,
  type LucideIcon,
  MinusCircle,
  ShieldAlert,
} from 'lucide-react';
import type { Route } from 'next';
import Link from 'next/link';
import { useState } from 'react';
import { api } from '../../lib/api';

type Version = Awaited<ReturnType<typeof api.moderation.versions>>['items'][number];

// Status always ships as icon + word, never colour alone.
const STATUS: Record<string, { label: string; icon: LucideIcon; cls: string; spin?: boolean }> = {
  queued: { label: 'Queued', icon: Loader2, cls: 'text-muted-foreground', spin: true },
  pending: { label: 'Scanning', icon: Loader2, cls: 'text-parchment', spin: true },
  flagged: { label: 'Flagged', icon: ShieldAlert, cls: 'text-crimson' },
  error: { label: 'Scan error', icon: AlertTriangle, cls: 'text-gilt' },
  clean: { label: 'Clean', icon: CheckCircle2, cls: 'text-parchment/80' },
  skipped: { label: 'Not scanned', icon: MinusCircle, cls: 'text-muted-foreground' },
};
const SETTLED = new Set(['clean', 'skipped']);

const ago = (iso: string | null) => {
  if (!iso) return '—';
  const m = Math.round((Date.now() - new Date(iso).getTime()) / 60_000);
  if (m < 1) return 'just now';
  if (m < 60) return `${m} min ago`;
  const h = Math.round(m / 60);
  if (h < 48) return `${h} h ago`;
  return `${Math.round(h / 24)} days ago`;
};
const size = (b: number) =>
  b >= 1_048_576 ? `${(b / 1_048_576).toFixed(1)} MB` : `${Math.max(1, Math.round(b / 1024))} KB`;

/** "3 of 72 engines" from VirusTotal's per-verdict counts. */
function verdict(stats: Version['scanStats']): string | null {
  if (!stats) return null;
  const total = Object.values(stats).reduce((a, b) => a + b, 0);
  if (!total) return null;
  const bad = (stats.malicious ?? 0) + (stats.suspicious ?? 0);
  return `${bad} of ${total} engines flagged it`;
}

/** Mod versions and their VirusTotal scan, for the admin Inbox. */
export function ScanList() {
  const [all, setAll] = useState(false);
  const list = useQuery({
    queryKey: ['admin', 'versions'],
    queryFn: () => api.moderation.versions(),
    // Refresh while something is still scanning so the row settles on its own.
    refetchInterval: (q) =>
      q.state.data?.items.some((v) => v.scanStatus === 'queued' || v.scanStatus === 'pending')
        ? 15_000
        : false,
    retry: false,
  });

  const items = list.data?.items ?? [];
  const open = items.filter((v) => !SETTLED.has(v.scanStatus));
  const shown = all ? items : open;

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap gap-2" role="group" aria-label="Which versions to show">
        <button
          type="button"
          aria-pressed={!all}
          onClick={() => setAll(false)}
          className={`${buttonVariants({ variant: all ? 'outline' : 'default', size: 'sm' })} gap-2`}
        >
          Needs attention
          {open.length ? <span className="tabular-nums opacity-80">{open.length}</span> : null}
        </button>
        <button
          type="button"
          aria-pressed={all}
          onClick={() => setAll(true)}
          className={buttonVariants({ variant: all ? 'default' : 'outline', size: 'sm' })}
        >
          All uploads (30 days)
        </button>
      </div>

      {list.isLoading ? (
        <div className="flex justify-center py-8">
          <Spinner />
        </div>
      ) : list.isError ? (
        <p className="text-sm text-destructive">Could not load the scan list.</p>
      ) : shown.length === 0 ? (
        <div className="grimoire-card p-6 text-center text-sm text-muted-foreground">
          {all
            ? 'No uploads in the last 30 days.'
            : 'Every upload is scanned and clean. Nothing is queued or flagged.'}
        </div>
      ) : (
        <ul className="grimoire-card divide-y divide-border/60">
          {shown.map((v) => {
            const st = STATUS[v.scanStatus] ?? {
              label: v.scanStatus,
              icon: MinusCircle,
              cls: 'text-muted-foreground',
            };
            const Icon = st.icon;
            const result = verdict(v.scanStats);
            return (
              <li
                key={v.id}
                className="flex flex-col gap-2 px-4 py-3 sm:flex-row sm:items-center sm:gap-4"
              >
                <span
                  className={`flex w-28 shrink-0 items-center gap-1.5 text-sm font-medium ${st.cls}`}
                >
                  <Icon className={`h-4 w-4 ${st.spin ? 'animate-spin' : ''}`} aria-hidden />
                  {st.label}
                </span>
                <div className="min-w-0 flex-1">
                  <Link
                    href={`/registry/${v.modSlug}` as Route}
                    className="font-semibold text-parchment underline-offset-4 hover:underline"
                  >
                    {v.modName}
                  </Link>{' '}
                  <span className="text-sm text-muted-foreground">v{v.version}</span>
                  <p className="mt-0.5 text-xs text-muted-foreground">
                    uploaded {ago(v.createdAt)} · {size(v.sizeBytes)}
                    {v.scannedAt ? ` · scanned ${ago(v.scannedAt)}` : ''}
                    {result ? ` · ${result}` : ''}
                  </p>
                  <p className="mt-0.5 truncate font-data text-xs text-muted-foreground/80">
                    sha256 {v.sha256}
                  </p>
                </div>
                <a
                  href={`https://www.virustotal.com/gui/file/${v.sha256}`}
                  target="_blank"
                  rel="noopener noreferrer"
                  className={`${buttonVariants({ variant: 'outline', size: 'sm' })} shrink-0 gap-1.5`}
                >
                  VirusTotal <ExternalLink className="h-3.5 w-3.5" aria-hidden />
                </a>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
