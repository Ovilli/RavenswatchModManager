'use client';

import type { ReactNode } from 'react';
import type { ModMedia } from '../../../lib/mod-presentation';
import { RegistryDetailLayout } from '@rsmm/ui';
import { MDPreview } from '../md-editor';
import { ListingGallery } from './listing-gallery';

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
    <RegistryDetailLayout
      className={className}
      name={name}
      summary={summary}
      breadcrumb={breadcrumb}
      labels={labels}
      stats={stats}
      media={<ListingGallery media={media} name={name} nsfw={nsfw} />}
      navigation={navigation}
      sidebar={sidebar}
      sidebarLabel={sidebarLabel}
    >
      {children}
    </RegistryDetailLayout>
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
