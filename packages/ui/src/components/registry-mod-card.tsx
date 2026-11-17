import type { ReactNode } from 'react';
import { Download, TriangleAlert, Users } from 'lucide-react';
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
  ratingCount?: number;
  featured?: boolean;
  nsfw?: boolean;
  tags?: string[];
  role?: 'owner' | 'coauthor';
}

/** Registry presentation shared by the website and the desktop client. */
export function RegistryModCard({
  mod,
  privateOnly = false,
  href,
  onOpen,
  actions,
  active = false,
  headingLevel = 2,
  view = 'grid',
  labels = {},
}: {
  mod: RegistryModCardData;
  privateOnly?: boolean;
  href?: string;
  onOpen?: () => void;
  actions?: ReactNode;
  active?: boolean;
  headingLevel?: 2 | 3;
  view?: 'grid' | 'list';
  labels?: { author?: string; featured?: string; nsfw?: string; privateOnly?: string };
}) {
  const Heading = headingLevel === 3 ? 'h3' : 'h2';
  const hasRating = mod.rating != null && mod.ratingCount !== 0;
  if (view === 'list') {
    const row = (
      <>
        <div className="mod-card-list-art">
          {mod.imageUrl ? (
            <img src={mod.imageUrl} alt="" loading="lazy" />
          ) : (
            <RegistryModCover seed={mod.slug} name={mod.name} size="sm" />
          )}
        </div>
        <div className="mod-card-list-identity">
          <div className="mod-card-list-name">
            <Heading>{mod.name}</Heading>
            {mod.featured ? <span aria-label={labels.featured ?? 'Featured'}>★</span> : null}
            {mod.nsfw ? <span className="mod-card-mature">{labels.nsfw ?? 'Mature'}</span> : null}
            {privateOnly ? (
              <span className="mod-card-private-tag inline-flex items-center gap-1">
                <TriangleAlert size={12} aria-hidden />
                {labels.privateOnly ?? 'Private games only'}
              </span>
            ) : null}
          </div>
          <p>
            {mod.author || labels.author || 'unknown'}
            {mod.latestVersion ? ` · v${mod.latestVersion}` : ''}
            {mod.summary ? ` — ${mod.summary}` : ''}
          </p>
        </div>
        {mod.category ? <span className="mod-card-list-category">{mod.category}</span> : null}
        {hasRating && mod.rating != null ? (
          <span className="mod-card-list-rating">★ {mod.rating.toFixed(1)}</span>
        ) : null}
        {mod.downloads != null ? (
          <span className="mod-card-list-downloads">
            {mod.downloads.toLocaleString('en-US')} dl
          </span>
        ) : null}
        {actions ? (
          <div className="mod-card-list-actions" onClick={(event) => event.stopPropagation()}>
            {actions}
          </div>
        ) : null}
      </>
    );
    if (href)
      return (
        <article className="mod-card mod-card-list">
          <a className="mod-card-list-link" href={href}>
            {row}
          </a>
        </article>
      );
    return (
      <article
        className={`mod-card mod-card-list mod-card-interactive${active ? ' is-active' : ''}`}
        tabIndex={0}
        role="link"
        aria-label={`${mod.name}${mod.author ? ` by ${mod.author}` : ''}`}
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
        {row}
      </article>
    );
  }
  const contents = (
    <>
      <div className="mod-card-artwork">
        {mod.imageUrl ? (
          <img src={mod.imageUrl} alt={`${mod.name} preview`} loading="lazy" />
        ) : (
          <RegistryModCover seed={mod.slug} name={mod.name} className="h-full w-full" />
        )}
        {mod.featured || mod.nsfw || mod.role === 'coauthor' ? (
          <div className="mod-card-status">
            {mod.featured ? <span>★ {labels.featured ?? 'Featured'}</span> : null}
            {mod.nsfw ? <span className="mod-card-mature">{labels.nsfw ?? 'Mature'}</span> : null}
            {mod.role === 'coauthor' ? (
              <span className="inline-flex items-center gap-1">
                <Users size={13} aria-hidden />
                Co-author
              </span>
            ) : null}
          </div>
        ) : null}
        {actions ? (
          <div className="mod-card-actions mod-card-actions--overlay" onClick={(event) => event.stopPropagation()}>
            {actions}
          </div>
        ) : null}
      </div>
      <div className="mod-card-body">
        {privateOnly || mod.category ? (
          <div className="mod-card-tags">
            {privateOnly ? (
              <span className="mod-card-tag mod-card-private-tag">
                <TriangleAlert size={14} aria-hidden />
                {labels.privateOnly ?? 'Private games only'}
              </span>
            ) : null}
            {mod.category ? <span className="mod-card-tag">{mod.category}</span> : null}
          </div>
        ) : null}
        <div className="mod-card-identity">
          <Heading>{mod.name}</Heading>
        </div>
        {mod.summary ? <p className="mod-card-summary">{mod.summary}</p> : null}
        <p className="mod-card-author">by {mod.author || labels.author || 'unknown'}</p>
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
                  aria-label={`${mod.rating.toFixed(1)} out of 5 stars`}
                >
                  <span className="mod-card-star" aria-hidden>
                    ★
                  </span>
                  <strong>{mod.rating.toFixed(1)}</strong>
                  {mod.ratingCount ? ` (${mod.ratingCount.toLocaleString('en-US')})` : ''}
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
      </article>
    );
  return (
    <article
      className={`mod-card mod-card-interactive${active ? ' is-active' : ''}`}
      tabIndex={0}
      role="link"
      aria-label={`${mod.name}${mod.author ? ` by ${mod.author}` : ''}`}
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
    </article>
  );
}
