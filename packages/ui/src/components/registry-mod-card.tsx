import type { ReactNode } from 'react';
import { Badge } from './badge';
import { RegistryModCover } from './registry-mod-cover';

export interface RegistryModCardData {
  slug: string;
  name: string;
  author?: string | null;
  latestVersion?: string | null;
  summary?: string | null;
  imageUrl?: string | null;
  category?: string | null;
  downloads?: number | null;
  rating?: number | null;
  featured?: boolean;
  nsfw?: boolean;
}

/**
 * The website registry's shared card for both the grid and scan-friendly row.
 * Apps provide navigation and install controls; the structure and styling
 * remain owned here so the web registry and desktop browse page cannot drift.
 */
export function RegistryModCard({
  mod,
  view = 'grid',
  onOpen,
  actions,
  active = false,
  compact = false,
  labels = {},
}: {
  mod: RegistryModCardData;
  view?: 'grid' | 'list';
  onOpen: () => void;
  actions?: ReactNode;
  active?: boolean;
  compact?: boolean;
  labels?: { author?: string; featured?: string; nsfw?: string };
}) {
  const author = mod.author || labels.author || 'unknown';
  const open = () => onOpen();
  const onCardClick = (event: React.MouseEvent<HTMLDivElement>) => {
    const target = event.target as HTMLElement;
    if (target.closest('a, button, input, textarea, select, [role="switch"]')) return;
    open();
  };
  const onCardKeyDown = (event: React.KeyboardEvent<HTMLDivElement>) => {
    if (event.target !== event.currentTarget) return;
    if (event.key === 'Enter' || event.key === ' ') {
      event.preventDefault();
      open();
    }
  };

  if (view === 'list') {
    return (
      <div
        tabIndex={0}
        role="link"
        aria-label={`${mod.name}${mod.author ? ` by ${mod.author}` : ''}`}
        aria-current={active ? 'true' : undefined}
        onClick={onCardClick}
        onKeyDown={onCardKeyDown}
        className={`grimoire-card flex cursor-pointer items-center gap-3 px-3 py-2 transition-colors duration-150 hover:border-gilt/40 focus:border-gilt/60 ${active ? 'border-gilt/70 bg-gilt/5' : ''}`}
      >
        <div className="hidden h-10 w-16 shrink-0 overflow-hidden rounded sm:block">
          {mod.imageUrl ? (
            <img src={mod.imageUrl} alt="" loading="lazy" className="h-full w-full object-cover" />
          ) : (
            <RegistryModCover seed={mod.slug} name={mod.name} size="sm" className="h-full w-full" />
          )}
        </div>
        <div className="min-w-0 flex-1">
          <div className="flex items-baseline gap-2">
            <button type="button" onClick={open} className="truncate text-left text-base leading-tight transition-colors hover:text-gilt">
              {mod.name}
            </button>
            {mod.featured ? <span className="shrink-0 text-xs text-gilt">★</span> : null}
            {mod.nsfw ? <span className="shrink-0 rounded border border-crimson/40 bg-crimson/10 px-1 font-mono text-[10px] uppercase tracking-widest text-crimson">{labels.nsfw ?? 'NSFW'}</span> : null}
          </div>
          <p className="truncate text-xs text-muted-foreground">
            {author}{mod.latestVersion ? ` · v${mod.latestVersion}` : ''}{mod.summary ? ` — ${mod.summary}` : ''}
          </p>
        </div>
        {!compact ? (
          <>
            <div className="hidden w-24 shrink-0 md:block">{mod.category ? <Badge variant="secondary" className="text-[0.65rem]">{mod.category}</Badge> : null}</div>
            <div className="hidden w-14 shrink-0 text-right font-mono text-xs text-gilt lg:block">{mod.rating != null ? `★ ${mod.rating.toFixed(1)}` : '—'}</div>
            <div className="hidden w-20 shrink-0 text-right font-mono text-xs text-muted-foreground lg:block">{mod.downloads != null ? `${mod.downloads.toLocaleString()} dl` : ''}</div>
          </>
        ) : null}
        {actions ? <div className="flex shrink-0 items-center gap-1">{actions}</div> : null}
      </div>
    );
  }

  return (
    <div
      tabIndex={0}
      role="link"
      aria-label={`${mod.name}${mod.author ? ` by ${mod.author}` : ''}`}
      aria-current={active ? 'true' : undefined}
      onClick={onCardClick}
      onKeyDown={onCardKeyDown}
      className={`grimoire-card cursor-pointer overflow-hidden transition-colors duration-150 hover:border-gilt/40 focus:border-gilt/60 ${active ? 'border-gilt/70 bg-gilt/5' : ''}`}
    >
      <div className="relative">
        {mod.imageUrl ? (
          <div className="aspect-[16/9] w-full overflow-hidden bg-muted">
            <img src={mod.imageUrl} alt={`${mod.name} preview`} className="h-full w-full object-cover" loading="lazy" />
          </div>
        ) : (
          <RegistryModCover seed={mod.slug} name={mod.name} className="aspect-[16/9] w-full" />
        )}
        {mod.featured ? <Badge className="absolute left-2 top-2 border-gilt/40 bg-gilt/15 text-[0.65rem] text-gilt">★ {labels.featured ?? 'Featured'}</Badge> : null}
        {mod.nsfw ? <Badge className="absolute right-2 top-2 border-crimson/40 bg-crimson/15 text-[0.65rem] text-crimson">{labels.nsfw ?? 'NSFW'}</Badge> : null}
      </div>
      <div className="space-y-3 p-4">
        <div className="flex items-start justify-between gap-2">
          <div className="min-w-0">
            <button type="button" onClick={open} className="block max-w-full truncate text-left font-display text-lg leading-tight transition-colors hover:text-gilt">{mod.name}</button>
            <p className="mt-0.5 text-sm text-muted-foreground">{author}{mod.latestVersion ? <Badge variant="outline" className="ml-2 text-[0.6rem]">v{mod.latestVersion}</Badge> : null}</p>
          </div>
          {actions ? <div className="flex shrink-0 items-center gap-1">{actions}</div> : null}
        </div>
        {mod.summary ? <p className="line-clamp-2 text-sm text-muted-foreground">{mod.summary}</p> : null}
        <div className="flex items-center justify-between gap-2 text-xs text-muted-foreground">
          <div className="flex items-center gap-2">{mod.category ? <Badge variant="secondary">{mod.category}</Badge> : null}{mod.downloads != null ? <span>{mod.downloads.toLocaleString()} dl</span> : null}</div>
          {mod.rating != null ? <span>★ {mod.rating.toFixed(1)}</span> : null}
        </div>
      </div>
    </div>
  );
}
