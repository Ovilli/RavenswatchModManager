import type { Metadata } from 'next';
import { notFound } from 'next/navigation';
import { fetchEntity } from '../../../lib/entity';
import { noindex } from '../../../lib/noindex';
import { LogActions } from './log-actions';

/**
 * Viewer for a shared diagnostic log.
 *
 * Unlisted, not access-controlled: the id is 72 bits of randomness and IS the
 * capability, which is what lets an anonymous user hand the link to whoever is
 * helping them. `noindex` matters more here than on a private app screen —
 * these URLs are pasted into public support threads, and a crash dump that is
 * merely unlisted must not become a searchable one.
 *
 * Every field renders as a text node. The content is arbitrary text uploaded
 * by an anonymous caller, so it is never fed to a markdown or HTML renderer.
 */

interface SharedLog {
  id: string;
  source: string;
  rsmmVersion: string;
  os: string;
  content: string;
  meta: Record<string, unknown> | null;
  lineCount: number;
  bytes: number;
  createdAt: string;
  expiresAt: string;
}

export const metadata: Metadata = {
  title: 'Shared log · Ravenswatch Mod Manager',
  ...noindex,
};

function formatBytes(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / (1024 * 1024)).toFixed(1)} MB`;
}

export default async function SharedLogPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const res = await fetchEntity<SharedLog>(`/api/logs/${encodeURIComponent(id)}`);

  // An expired share answers 410, which `fetchEntity` folds into `missing` —
  // both are a 404 for the reader, and both must stay a real 404 for crawlers
  // rather than a 200 with an empty shell.
  if (res.state === 'missing') notFound();
  if (res.state === 'error') {
    return (
      <main className="mx-auto max-w-5xl px-4 py-16">
        <h1 className="text-2xl font-semibold">Could not load this log</h1>
        <p className="mt-2 text-sm text-muted-foreground">
          The link is valid but the server did not answer. Try again in a moment.
        </p>
      </main>
    );
  }

  const log = res.data;
  const created = new Date(log.createdAt);
  const expires = new Date(log.expiresAt);

  return (
    <main className="mx-auto max-w-5xl px-4 py-10">
      <h1 className="text-2xl font-semibold">Shared log</h1>
      <p className="mt-1 text-sm text-muted-foreground">
        Uploaded from the Ravenswatch Mod Manager desktop app to make a bug report readable.
      </p>

      <dl className="mt-6 grid grid-cols-2 gap-x-6 gap-y-2 text-sm sm:grid-cols-4">
        <Field label="app version" value={log.rsmmVersion} />
        <Field label="platform" value={log.os} />
        <Field label="kind" value={log.source} />
        <Field label="size" value={`${formatBytes(log.bytes)} · ${log.lineCount} lines`} />
        <Field label="uploaded" value={created.toISOString().replace('T', ' ').slice(0, 16)} />
        <Field label="deleted on" value={expires.toISOString().slice(0, 10)} />
      </dl>

      <LogActions content={log.content} filename={`rsmm-log-${log.id}.txt`} />

      <pre className="mt-4 max-h-[70vh] overflow-auto rounded border bg-muted/40 p-4 font-data text-xs leading-relaxed whitespace-pre">
        {log.content}
      </pre>

      <p className="mt-4 text-xs text-muted-foreground">
        Uploaded by a user, not verified by us. It is deleted automatically on{' '}
        {expires.toISOString().slice(0, 10)}.
      </p>
    </main>
  );
}

function Field({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt className="text-xs uppercase tracking-wider text-muted-foreground">{label}</dt>
      <dd className="font-data">{value}</dd>
    </div>
  );
}
