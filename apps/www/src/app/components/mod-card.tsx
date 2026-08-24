import type { ModListItem } from '@rsmm/schemas';
import { Badge } from '@rsmm/ui';
import type { Route } from 'next';
import Link from 'next/link';

interface ModCardProps {
  mod: ModListItem;
  /** Featured styling: gilt ring + "★ Featured" badge instead of category/version. */
  featured?: boolean;
}

export function ModCard({ mod, featured = false }: ModCardProps) {
  return (
    <Link
      href={`/registry/${mod.slug}` as Route}
      className={`grimoire-card overflow-hidden group cursor-pointer transition-colors ${
        featured ? 'ring-1 ring-gilt/30 hover:border-gilt/60' : 'hover:border-gilt/40'
      }`}
    >
      {mod.imageUrl ? (
        <div className="aspect-[4/3] w-full overflow-hidden bg-muted">
          <img
            src={mod.imageUrl}
            alt={`${mod.name} preview`}
            className="h-full w-full object-cover"
            loading="lazy"
          />
        </div>
      ) : (
        <div className="aspect-[4/3] w-full bg-muted" />
      )}
      <div className="space-y-2 p-4">
        <div className="flex items-start justify-between gap-2">
          <div className="min-w-0">
            <h3 className="text-sm font-semibold leading-tight text-foreground truncate">
              {mod.name}
            </h3>
            <p className="text-xs text-muted-foreground">by {mod.author ?? 'unknown'}</p>
          </div>
          {featured ? (
            <Badge className="shrink-0 bg-gilt/15 text-[0.6rem] text-gilt border-gilt/30">
              ★ Featured
            </Badge>
          ) : mod.category ? (
            <Badge variant="outline" className="shrink-0 text-[0.6rem]">
              {mod.category}
            </Badge>
          ) : null}
        </div>
        {mod.summary ? (
          <p className="text-xs text-muted-foreground line-clamp-2 leading-relaxed">
            {mod.summary}
          </p>
        ) : null}
        <div className="flex items-center gap-3 text-xs text-muted-foreground">
          {mod.downloads != null ? <span>{mod.downloads.toLocaleString()} downloads</span> : null}
          {mod.rating != null ? <span>★ {mod.rating.toFixed(1)}</span> : null}
          {!featured && mod.latestVersion ? (
            <span className="ml-auto font-mono text-[0.6rem]">v{mod.latestVersion}</span>
          ) : null}
        </div>
      </div>
    </Link>
  );
}
