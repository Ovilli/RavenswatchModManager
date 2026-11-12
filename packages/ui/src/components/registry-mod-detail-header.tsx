import type { ReactNode } from 'react';

/** Shared top section used on the public mod page and the desktop mod view. */
export function RegistryModDetailHeader({
  name,
  summary,
  byline,
  tags = [],
  matureLabel,
  labels,
  metadata,
  action,
  className = '',
}: {
  name: string;
  summary?: string | null;
  byline?: string;
  tags?: string[];
  matureLabel?: string;
  labels?: ReactNode;
  metadata?: ReactNode;
  action?: ReactNode;
  className?: string;
}) {
  return (
    <header className={`grid min-w-0 gap-3.5 ${className}`}>
      {labels ?? (tags.length > 0 || matureLabel ? (
        <div className="flex min-w-0 flex-wrap items-center gap-2">
          {tags.map((tag) => <span key={tag} className="rounded bg-surface-2 px-2.5 py-1 text-xs text-foreground">{tag}</span>)}
          {matureLabel ? <span className="text-sm text-crimson">{matureLabel}</span> : null}
        </div>
      ) : null)}
      <div className="flex min-w-0 flex-wrap items-start justify-between gap-4">
        <div className="min-w-0 flex-1">
          <h1 className="w-full break-words font-display text-3xl font-bold leading-tight tracking-tight text-foreground sm:text-4xl">{name}</h1>
          {byline ? <p className="mt-1 text-sm text-muted-foreground">{byline}</p> : null}
          {summary?.trim() ? <p className="mt-3 text-lg leading-relaxed text-foreground/90">{summary}</p> : null}
        </div>
        {action ? <div className="shrink-0">{action}</div> : null}
      </div>
      {metadata ? <div className="flex min-w-0 flex-wrap items-center justify-between gap-2 text-sm text-muted-foreground">{metadata}</div> : null}
    </header>
  );
}
