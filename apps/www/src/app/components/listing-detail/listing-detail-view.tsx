'use client';

import type { ReactNode } from 'react';
import type { ModMedia } from '../../../lib/mod-presentation';
import { MDPreview } from '../md-editor';
import { ListingGallery } from './listing-gallery';
import './listing-detail.css';

/** One public detail composition; each route supplies its content and actions. */
export function ListingDetailView({
  className = '',
  name,
  summary,
  breadcrumb,
  labels,
  stats,
  media,
  nsfw,
  navigation,
  sidebar,
  sidebarLabel,
  children,
}: {
  className?: string;
  name: string;
  summary?: string | null;
  breadcrumb: ReactNode;
  labels?: ReactNode;
  stats: ReactNode;
  media: ModMedia[];
  nsfw?: boolean;
  navigation: ReactNode;
  sidebar: ReactNode;
  sidebarLabel: string;
  children: ReactNode;
}) {
  return (
    <main className={`mod-detail container ${className}`}>
      <nav aria-label="Breadcrumb" className="mod-breadcrumb">
        {breadcrumb}
      </nav>
      <header className="mod-heading">
        {labels}
        <h1>{name}</h1>
        {summary?.trim() ? <p className="mod-summary">{summary}</p> : null}
        <div className="mod-social-proof">{stats}</div>
      </header>
      <ListingGallery media={media} name={name} nsfw={nsfw} />
      <div className="mod-body">
        <nav className="mod-section-nav" aria-label="On this page">
          {navigation}
        </nav>
        <div className="mod-content-grid">
          <aside className="mod-download-sidebar" aria-label={sidebarLabel}>
            {sidebar}
          </aside>
          <div className="mod-reading">{children}</div>
        </div>
      </div>
    </main>
  );
}

export function ListingDescription({
  description,
  html,
  fallback,
}: {
  description?: string | null;
  html?: string;
  fallback: string;
}) {
  if (!description?.trim()) return <p className="mod-description">{fallback}</p>;
  return html !== undefined ? (
    <article
      data-color-mode="dark"
      className="md-editor-themed prose-invert user-prose mod-description"
      // biome-ignore lint/security/noDangerouslySetInnerHtml: html is rendered and sanitized on the server by renderMarkdown().
      dangerouslySetInnerHTML={{ __html: html }}
    />
  ) : (
    <article data-color-mode="dark" className="md-editor-themed prose-invert mod-description">
      <MDPreview source={description} />
    </article>
  );
}
