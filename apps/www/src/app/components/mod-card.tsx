import { type ModListItem, hasPrivateOnlyTag } from '@rsmm/schemas';
import { Download, TriangleAlert } from 'lucide-react';
import type { Route } from 'next';
import Link from 'next/link';
import type { ReactNode } from 'react';
import { REGISTRY_CATEGORIES } from '../../lib/registry-query';
import { ModCover } from './mod-cover';
import './mod-card.css';

interface ModCardProps {
  mod: Pick<
    ModListItem,
    'slug' | 'name' | 'author' | 'summary' | 'imageUrl' | 'downloads' | 'latestVersion' | 'nsfw'
  > & {
    category: string | null;
    rating?: number | null;
    ratingCount?: number;
    tags?: string[];
  };
  /** Mark featured artwork without replacing its category or private-game label. */
  featured?: boolean;
  href?: Route;
  /** Optional actions outside the card link, so links and buttons never nest. */
  footer?: ReactNode;
}

export function ModCard({ mod, featured = false, href, footer }: ModCardProps) {
  const privateOnly = hasPrivateOnlyTag(mod.tags);
  const category = REGISTRY_CATEGORIES.find(({ id }) => id === mod.category)?.label ?? mod.category;
  const hasRating = mod.rating != null && mod.ratingCount !== 0;

  return (
    <div className="mod-card">
      <Link href={href ?? (`/registry/${mod.slug}` as Route)} className="mod-card-link">
        <div className="mod-card-artwork">
          {mod.imageUrl ? (
            <img src={mod.imageUrl} alt={`${mod.name} preview`} loading="lazy" />
          ) : (
            <ModCover seed={mod.slug} name={mod.name} className="h-full w-full" />
          )}
          {featured || mod.nsfw ? (
            <div className="mod-card-status">
              {featured ? <span>★ Featured</span> : null}
              {mod.nsfw ? <span className="mod-card-mature">Mature</span> : null}
            </div>
          ) : null}
        </div>
        <div className="mod-card-body">
          {privateOnly || category ? (
            <div className="mod-card-tags">
              {privateOnly ? (
                <span className="mod-card-tag mod-card-private-tag">
                  <TriangleAlert size={14} aria-hidden />
                  Private games only
                </span>
              ) : null}
              {category ? <span className="mod-card-tag">{category}</span> : null}
            </div>
          ) : null}
          <div className="mod-card-identity">
            <h3>{mod.name}</h3>
          </div>
          {mod.summary ? <p className="mod-card-summary">{mod.summary}</p> : null}
          <p className="mod-card-author">by {mod.author ?? 'unknown'}</p>
          {mod.downloads != null || hasRating ? (
            <div className="mod-card-stats">
              {mod.downloads != null ? (
                <span className="mod-card-downloads">
                  <Download size={16} aria-hidden />
                  {mod.downloads.toLocaleString('en-US')}{' '}
                  <span className="sr-only">{mod.downloads === 1 ? 'download' : 'downloads'}</span>
                </span>
              ) : null}
              {hasRating && mod.rating != null ? (
                <span className="mod-card-rating-group">
                  {mod.downloads != null ? (
                    <span className="mod-card-stat-dot" aria-hidden>
                      ·
                    </span>
                  ) : null}
                  <span
                    className="mod-card-rating"
                    role="img"
                    aria-label={`${mod.rating.toFixed(1)} out of 5 stars${mod.ratingCount != null ? ` from ${mod.ratingCount} ${mod.ratingCount === 1 ? 'rating' : 'ratings'}` : ''}`}
                  >
                    <span className="mod-card-star" aria-hidden>
                      ★
                    </span>
                    <span aria-hidden>
                      <strong>{mod.rating.toFixed(1)}</strong>
                      {mod.ratingCount != null
                        ? ` (${mod.ratingCount.toLocaleString('en-US')})`
                        : ''}
                    </span>
                  </span>
                </span>
              ) : null}
            </div>
          ) : null}
        </div>
      </Link>
      {footer ? <div className="mod-card-footer space-y-3">{footer}</div> : null}
    </div>
  );
}
