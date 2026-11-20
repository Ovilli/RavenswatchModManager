import { Download, Layers, Star, TriangleAlert, Users } from 'lucide-react';
import type { ReactNode } from 'react';
import { RegistryModCover } from './registry-mod-cover';

export interface RegistryListingCardData {
  slug: string;
  name: string;
  author?: string | null;
  latestVersion?: string | null;
  summary?: string | null;
  imageUrl?: string | null;
  category?: string | null;
  downloads?: number | null;
  /** Collections show their included mod count instead of download statistics. */
  modCount?: number;
  rating?: number | null;
  ratingCount?: number;
  featured?: boolean;
  nsfw?: boolean;
  tags?: string[];
  role?: 'owner' | 'coauthor';
}

/** Mod and collection presentation shared by the website and the desktop client. */
export function RegistryListingCard({
  listing,
  privateOnly = false,
  href,
  onOpen,
  actions,
  listLeading,
  listBadges,
  listMetadata,
  footer,
  active = false,
  headingLevel = 2,
  view = 'grid',
  labels = {},
  locale = 'en-US',
}: {
  listing: RegistryListingCardData;
  privateOnly?: boolean;
  href?: string;
  onOpen?: () => void;
  actions?: ReactNode;
  /** List-only controls before the thumbnail, e.g. Library load order and enable switch. */
  listLeading?: ReactNode;
  /** List-only status badges beside the title, in addition to the shared scope badge. */
  listBadges?: ReactNode;
  /** Replaces list statistics with contextual metadata. Omit for registry stats. */
  listMetadata?: ReactNode;
  /** Content below the grid card's link, such as management controls or an updated date. */
  footer?: ReactNode;
  active?: boolean;
  headingLevel?: 2 | 3;
  view?: 'grid' | 'list';
  locale?: string;
  labels?: {
    author?: string;
    authorLine?: string;
    card?: string;
    preview?: string;
    featured?: string;
    nsfw?: string;
    privateOnly?: string;
    coauthor?: string;
    downloads?: string;
    downloadUnit?: string;
    rating?: string;
    modCount?: string;
  };
}) {
  const Heading = headingLevel === 3 ? 'h3' : 'h2';
  const hasRating = listing.rating != null && listing.ratingCount !== 0;
  const modCountLabel =
    listing.modCount != null
      ? (labels.modCount ??
        `${listing.modCount.toLocaleString(locale)} ${listing.modCount === 1 ? 'mod' : 'mods'}`)
      : undefined;
  if (view === 'list') {
    const rowActions = actions ? (
      <div className="mod-card-list-actions" onClick={(event) => event.stopPropagation()}>
        {actions}
      </div>
    ) : null;
    const row = (
      <>
        {listLeading ? <div className="mod-card-list-leading">{listLeading}</div> : null}
        <div className="mod-card-list-art">
          {listing.imageUrl ? (
            <img src={listing.imageUrl} alt="" loading="lazy" />
          ) : (
            <RegistryModCover seed={listing.slug} name={listing.name} size="sm" />
          )}
        </div>
        <div className="mod-card-list-identity">
          <div className="mod-card-list-name">
            <Heading>{listing.name}</Heading>
            {listing.featured ? (
              <span aria-label={labels.featured ?? 'Featured'}>
                <Star size={14} aria-hidden />
              </span>
            ) : null}
            {listing.nsfw ? (
              <span className="mod-card-mature">{labels.nsfw ?? 'Mature'}</span>
            ) : null}
            {privateOnly ? (
              <span className="mod-card-private-tag inline-flex items-center gap-1">
                <TriangleAlert size={12} aria-hidden />
                {labels.privateOnly ?? 'Private games only'}
              </span>
            ) : null}
            {listBadges ? <div className="mod-card-list-badges">{listBadges}</div> : null}
          </div>
          <p>
            {listing.author || labels.author || 'unknown'}
            {listing.latestVersion ? ` · v${listing.latestVersion}` : ''}
            {listing.summary ? ` — ${listing.summary}` : ''}
          </p>
        </div>
        {listMetadata !== undefined ? (
          <div className="mod-card-list-controls">
            <div className="mod-card-list-metadata">{listMetadata}</div>
            {rowActions}
          </div>
        ) : (
          <>
            {listing.category ? (
              <span className="mod-card-list-category">{listing.category}</span>
            ) : null}
            {hasRating && listing.rating != null ? (
              <span
                className="mod-card-list-rating inline-flex items-center gap-1"
                aria-label={labels.rating ?? `${listing.rating.toFixed(1)} out of 5 stars`}
              >
                <Star size={14} aria-hidden /> {listing.rating.toFixed(1)}
              </span>
            ) : null}
            {listing.downloads != null ? (
              <span className="mod-card-list-downloads">
                {labels.downloads ?? `${listing.downloads.toLocaleString(locale)} dl`}
              </span>
            ) : null}
            {modCountLabel ? <span className="mod-card-list-count">{modCountLabel}</span> : null}
            {rowActions}
          </>
        )}
      </>
    );
    if (href)
      return (
        <article
          className="mod-card mod-card-list"
          data-list-layout={listMetadata !== undefined ? 'custom' : 'registry'}
        >
          <a className="mod-card-list-link" href={href}>
            {row}
          </a>
        </article>
      );
    return (
      <article
        className={`mod-card mod-card-list${onOpen ? ' mod-card-interactive' : ''}${active ? ' is-active' : ''}`}
        data-list-layout={listMetadata !== undefined ? 'custom' : 'registry'}
        tabIndex={onOpen ? 0 : undefined}
        role={onOpen ? 'link' : undefined}
        aria-label={
          labels.card ?? `${listing.name}${listing.author ? ` by ${listing.author}` : ''}`
        }
        aria-current={active ? 'true' : undefined}
        onClick={
          onOpen
            ? (event) => {
                if (
                  (event.target as HTMLElement).closest(
                    'a, button, input, textarea, select, [role="switch"], [role="tooltip"]',
                  )
                )
                  return;
                onOpen();
              }
            : undefined
        }
        onKeyDown={
          onOpen
            ? (event) => {
                if (event.target !== event.currentTarget) return;
                if (event.key === 'Enter' || event.key === ' ') {
                  event.preventDefault();
                  onOpen();
                }
              }
            : undefined
        }
      >
        {row}
      </article>
    );
  }
  const contents = (
    <>
      <div className="mod-card-artwork">
        {listing.imageUrl ? (
          <img
            src={listing.imageUrl}
            alt={labels.preview ?? `${listing.name} preview`}
            loading="lazy"
          />
        ) : (
          <RegistryModCover seed={listing.slug} name={listing.name} className="h-full w-full" />
        )}
        {listing.featured || listing.nsfw || listing.role === 'coauthor' ? (
          <div className="mod-card-status">
            {listing.featured ? (
              <span className="inline-flex items-center gap-1">
                <Star size={14} aria-hidden /> {labels.featured ?? 'Featured'}
              </span>
            ) : null}
            {listing.nsfw ? (
              <span className="mod-card-mature">{labels.nsfw ?? 'Mature'}</span>
            ) : null}
            {listing.role === 'coauthor' ? (
              <span className="inline-flex items-center gap-1">
                <Users size={13} aria-hidden />
                {labels.coauthor ?? 'Co-author'}
              </span>
            ) : null}
          </div>
        ) : null}
        {actions ? (
          <div
            className="mod-card-actions mod-card-actions--overlay"
            onClick={(event) => event.stopPropagation()}
          >
            {actions}
          </div>
        ) : null}
      </div>
      <div className="mod-card-body">
        {privateOnly || listing.category ? (
          <div className="mod-card-tags">
            {privateOnly ? (
              <span className="mod-card-tag mod-card-private-tag">
                <TriangleAlert size={14} aria-hidden />
                {labels.privateOnly ?? 'Private games only'}
              </span>
            ) : null}
            {listing.category ? <span className="mod-card-tag">{listing.category}</span> : null}
          </div>
        ) : null}
        <div className="mod-card-identity">
          <Heading>{listing.name}</Heading>
        </div>
        {listing.summary ? <p className="mod-card-summary">{listing.summary}</p> : null}
        <p className="mod-card-author">
          {labels.authorLine ?? `by ${listing.author || labels.author || 'unknown'}`}
        </p>
        {modCountLabel || listing.downloads != null || hasRating ? (
          <div className="mod-card-stats">
            {modCountLabel ? (
              <span className="mod-card-downloads">
                <Layers size={16} aria-hidden />
                {modCountLabel}
              </span>
            ) : null}
            {listing.downloads != null ? (
              <span className="mod-card-downloads">
                <Download size={16} aria-hidden />
                {listing.downloads.toLocaleString(locale)}{' '}
                <span className="sr-only">
                  {labels.downloadUnit ?? (listing.downloads === 1 ? 'download' : 'downloads')}
                </span>
              </span>
            ) : null}
            {hasRating && listing.rating != null ? (
              <span className="mod-card-rating-group">
                {listing.downloads != null ? (
                  <span className="mod-card-stat-dot" aria-hidden>
                    ·
                  </span>
                ) : null}
                <span
                  className="mod-card-rating"
                  role="img"
                  aria-label={labels.rating ?? `${listing.rating.toFixed(1)} out of 5 stars`}
                >
                  <Star className="mod-card-star" size={14} aria-hidden />
                  <strong>{listing.rating.toFixed(1)}</strong>
                  {listing.ratingCount ? ` (${listing.ratingCount.toLocaleString(locale)})` : ''}
                </span>
              </span>
            ) : null}
          </div>
        ) : null}
      </div>
    </>
  );

  if (href)
    return (
      <article className="mod-card">
        <a className="mod-card-link" href={href}>
          {contents}
        </a>
        {footer ? <div className="mod-card-footer">{footer}</div> : null}
      </article>
    );
  return (
    <article
      className={`mod-card mod-card-interactive${active ? ' is-active' : ''}`}
      tabIndex={0}
      role="link"
      aria-label={labels.card ?? `${listing.name}${listing.author ? ` by ${listing.author}` : ''}`}
      aria-current={active ? 'true' : undefined}
      onClick={(event) => {
        if (
          (event.target as HTMLElement).closest(
            'a, button, input, textarea, select, [role="switch"], [role="tooltip"]',
          )
        )
          return;
        onOpen?.();
      }}
      onKeyDown={(event) => {
        if (event.target !== event.currentTarget) return;
        if (event.key === 'Enter' || event.key === ' ') {
          event.preventDefault();
          onOpen?.();
        }
      }}
    >
      {contents}
      {footer ? <div className="mod-card-footer">{footer}</div> : null}
    </article>
  );
}
