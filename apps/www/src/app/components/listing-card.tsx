import { type Collection, type ModListItem, hasPrivateOnlyTag } from '@rsmm/schemas';
import { Download, Edit2, ExternalLink, Layers, TriangleAlert, Users } from 'lucide-react';
import type { Route } from 'next';
import Link from 'next/link';
import { REGISTRY_CATEGORIES } from '../../lib/registry-query';
import { ModCover } from './mod-cover';
import './mod-card.css';

type CardMod = Pick<
  ModListItem,
  'slug' | 'name' | 'imageUrl' | 'summary' | 'latestVersion' | 'downloads' | 'updatedAt'
> &
  Partial<Pick<ModListItem, 'author' | 'rating' | 'featured' | 'nsfw' | 'tags'>> & {
    category?: string | null;
    ratingCount?: number;
    role?: 'owner' | 'coauthor';
  };

type CardCollection = Pick<
  Collection,
  'slug' | 'name' | 'imageUrl' | 'summary' | 'ownerName' | 'modCount'
>;

type ListingCardProps = { headingLevel?: 2 | 3 } & (
  | { kind: 'mod'; item: CardMod; mode?: 'browse' | 'manage' }
  | { kind: 'collection'; item: CardCollection; mode?: never }
);

/** Shared listing cards using the current registry presentation. */
export function ListingCard(props: ListingCardProps) {
  const { slug, name, imageUrl, summary } = props.item;
  const mod = props.kind === 'mod' ? props.item : null;
  const collection = props.kind === 'collection' ? props.item : null;
  const manage = props.mode === 'manage';
  const href = (
    collection ? `/c/${slug}` : manage ? `/my-mods/${slug}` : `/registry/${slug}`
  ) as Route;
  const Heading = props.headingLevel === 3 ? 'h3' : 'h2';
  const privateOnly = hasPrivateOnlyTag(mod?.tags);
  const category =
    REGISTRY_CATEGORIES.find(({ id }) => id === mod?.category)?.label ?? mod?.category;
  const hasRating = mod?.rating != null && mod.ratingCount !== 0;

  return (
    <div className="mod-card">
      <Link href={href} className="mod-card-link">
        <div className="mod-card-artwork">
          {imageUrl ? (
            <img src={imageUrl} alt={`${name} preview`} loading="lazy" />
          ) : (
            <ModCover seed={slug} name={name} className="h-full w-full" />
          )}
          {mod?.featured || mod?.nsfw || mod?.role === 'coauthor' ? (
            <div className="mod-card-status">
              {mod.featured ? <span>★ Featured</span> : null}
              {mod.nsfw ? <span className="mod-card-mature">Mature</span> : null}
              {mod.role === 'coauthor' ? (
                <span className="inline-flex items-center gap-1">
                  <Users size={13} aria-hidden />
                  Co-author
                </span>
              ) : null}
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
            <Heading>{name}</Heading>
          </div>
          {summary ? <p className="mod-card-summary">{summary}</p> : null}
          <p className="mod-card-author">
            by {(collection ? collection.ownerName : mod?.author) ?? 'unknown'}
          </p>
          {collection || mod?.downloads != null || hasRating ? (
            <div className="mod-card-stats">
              {collection ? (
                <span className="mod-card-downloads">
                  <Layers size={16} aria-hidden />
                  {collection.modCount} {collection.modCount === 1 ? 'mod' : 'mods'}
                </span>
              ) : null}
              {mod?.downloads != null ? (
                <span className="mod-card-downloads">
                  <Download size={16} aria-hidden />
                  {mod.downloads.toLocaleString('en-US')}{' '}
                  <span className="sr-only">{mod.downloads === 1 ? 'download' : 'downloads'}</span>
                </span>
              ) : null}
              {hasRating && mod?.rating != null ? (
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
      {mod && manage ? (
        <div className="mod-card-footer space-y-3">
          <div className="space-y-1 text-xs text-muted-foreground">
            {!mod.latestVersion ? <p className="text-amber-500">No version published yet</p> : null}
            <p>Updated {new Date(mod.updatedAt).toLocaleDateString()}</p>
          </div>
          <div className="flex gap-2">
            <Link
              href={href}
              className="inline-flex flex-1 items-center justify-center gap-1 rounded-md bg-secondary px-3 py-2 text-sm hover:bg-secondary/80"
            >
              <Edit2 className="h-3.5 w-3.5" aria-hidden />
              Manage
            </Link>
            <Link
              href={`/registry/${slug}` as Route}
              className="inline-flex items-center justify-center gap-1 rounded-md border border-input bg-background px-3 py-2 text-sm hover:bg-accent"
              title="View public page"
              aria-label={`View ${name} public page`}
            >
              <ExternalLink className="h-3.5 w-3.5" aria-hidden />
            </Link>
          </div>
        </div>
      ) : null}
    </div>
  );
}
