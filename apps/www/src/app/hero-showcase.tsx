import type { ModListItem } from '@rsmm/schemas';
import { Badge } from '@rsmm/ui';
import Link from 'next/link';

export function HeroShowcase({ mods }: { mods: ModListItem[] }) {
  if (mods.length === 0) {
    return (
      <div className="mt-12 overflow-hidden rounded-xl border border-border/50 bg-card/50 backdrop-blur-sm">
        <div className="cover-placeholder aspect-video w-full" />
      </div>
    );
  }

  return (
    <div className="mt-12 grid grid-cols-2 gap-3 sm:grid-cols-4">
      {mods.map((mod) => (
        <Link
          key={mod.id}
          href={`/registry/${mod.slug}`}
          className="group relative overflow-hidden rounded-lg border border-border/40 bg-card/60 backdrop-blur-sm transition-all duration-200 hover:border-gilt/40 hover:bg-card/80 hover:shadow-lg hover:shadow-gilt/5"
        >
          {mod.imageUrl ? (
            <div className="aspect-[16/10] w-full overflow-hidden bg-muted">
              <img
                src={mod.imageUrl}
                alt={mod.name}
                className="h-full w-full object-cover transition-transform duration-300 group-hover:scale-105"
                loading="lazy"
              />
            </div>
          ) : (
            <div className="aspect-[16/10] w-full bg-muted" />
          )}
          <div className="p-2.5">
            <p className="truncate text-xs font-medium text-foreground">{mod.name}</p>
            <div className="mt-1 flex items-center gap-2 text-[0.6rem] text-muted-foreground">
              <span className="truncate">{mod.author ?? 'unknown'}</span>
              {mod.category ? <Badge variant="outline" className="text-[0.5rem] px-1 py-0">{mod.category}</Badge> : null}
            </div>
          </div>
        </Link>
      ))}
    </div>
  );
}
