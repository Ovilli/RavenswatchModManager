import type { ModListItem } from '@rsmm/schemas';
import { Badge } from '@rsmm/ui';
import type { Route } from 'next';
import Link from 'next/link';
import type { ReactNode } from 'react';
import { ModCover } from './mod-cover';

interface ModCardProps {
  mod: Pick<
    ModListItem,
    'slug' | 'name' | 'author' | 'summary' | 'imageUrl' | 'downloads' | 'latestVersion' | 'nsfw'
  > & {
    category: string | null;
    rating?: number | null;
  };
  /** Featured styling: gilt ring + "★ Featured" badge instead of category/version. */
  featured?: boolean;
  href?: Route;
  /** Optional actions outside the card link, so links and buttons never nest. */
  footer?: ReactNode;
}

export function ModCard({ mod, featured = false, href, footer }: ModCardProps) {
  return (
    <div
      className={`grimoire-card flex w-full min-w-0 flex-col overflow-hidden transition-colors ${
        featured ? 'ring-1 ring-gilt/30 hover:border-gilt/60' : 'hover:border-gilt/40'
      }`}
    >
      <Link href={href ?? (`/registry/${mod.slug}` as Route)} className="group block flex-1">
        {mod.imageUrl ? (
          <div className="aspect-video w-full overflow-hidden bg-muted">
            <img
              src={mod.imageUrl}
              alt={`${mod.name} preview`}
              className="h-full w-full object-cover"
              loading="lazy"
            />
          </div>
        ) : (
          <ModCover seed={mod.slug} name={mod.name} className="aspect-video w-full" />
        )}
        <div className="space-y-2 p-4">
          <div className="flex items-start justify-between gap-2">
            <div className="min-w-0">
              <h3 className="font-display truncate text-xl leading-tight text-foreground group-hover:text-gilt">
                {mod.name}
              </h3>
              <p className="text-sm text-muted-foreground">by {mod.author ?? 'unknown'}</p>
              {mod.nsfw ? (
                <Badge
                  variant="outline"
                  className="mt-1 border-crimson/40 text-xs text-crimson-text"
                >
                  Mature
                </Badge>
              ) : null}
            </div>
            {featured ? (
              <Badge className="shrink-0 bg-gilt/15 text-xs text-gilt border-gilt/30">
                ★ Featured
              </Badge>
            ) : mod.category ? (
              <Badge variant="outline" className="shrink-0 text-xs">
                {mod.category}
              </Badge>
            ) : null}
          </div>
          {mod.summary ? (
            <p className="line-clamp-2 text-base leading-relaxed text-muted-foreground">
              {mod.summary}
            </p>
          ) : null}
          <div className="flex items-center gap-3 text-sm text-muted-foreground">
            {mod.downloads != null ? <span>{mod.downloads.toLocaleString()} downloads</span> : null}
            {mod.rating != null ? <span>★ {mod.rating.toFixed(1)}</span> : null}
            {!featured && mod.latestVersion ? (
              <span className="ml-auto font-data text-xs">v{mod.latestVersion}</span>
            ) : null}
          </div>
        </div>
      </Link>
      {footer ? <div className="space-y-3 px-4 pb-4">{footer}</div> : null}
    </div>
  );
}
