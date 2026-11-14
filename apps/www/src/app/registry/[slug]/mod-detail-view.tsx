'use client';
import { ApiError, type ModDetailResponse } from '@rsmm/api-client';
import { type ModVersion, hasPrivateOnlyTag, isPrivateOnlyTag } from '@rsmm/schemas';
import { Spinner } from '@rsmm/ui';
import { useQuery } from '@tanstack/react-query';
import { ArrowDownToLine, ArrowLeft, ChevronDown, Download, ExternalLink } from 'lucide-react';
import type { Route } from 'next';
import Link from 'next/link';
import { Fragment } from 'react';
import { api } from '../../../lib/api';
import { getApiUrl } from '../../../lib/api-url';
import {
  formatFileSize,
  formatModDate,
  getDownloadVersion,
  getModMedia,
} from '../../../lib/mod-presentation';
import type { InstallerDownloads } from '../../../lib/releases';
import { useHydrated } from '../../../lib/use-hydrated';
import { FollowButton } from '../../components/follow-button';
import { MDPreview } from '../../components/md-editor';
import { ReportModal } from '../../components/report-modal';
import { ModActions } from './mod-actions';
import { ModGallery } from './mod-gallery';
import { ModPrivateOnlyControls } from './mod-private-only-controls';
import { ModPrivateOnlyTag } from './mod-private-only-tag';
import { ModRatingSummary, ReviewsSection } from './mod-reviews';
import './mod-detail.css';

function registryHref(param: 'category' | 'tags', value: string): Route {
  return `/registry?${new URLSearchParams({ [param]: value })}` as Route;
}

export function ModDetailView({
  slug,
  initialData,
  descriptionHtml,
  managerDownloads,
}: {
  slug: string;
  initialData?: ModDetailResponse;
  descriptionHtml: string;
  managerDownloads: InstallerDownloads;
}) {
  const detail = useQuery({
    queryKey: ['mods', 'detail', slug],
    queryFn: () => api.mods.get(slug),
    initialData,
    initialDataUpdatedAt: 0,
    retry: (count, error) =>
      error instanceof ApiError && error.status === 404 ? false : count < 1,
  });
  // Start with the same anonymous snapshot on both sides of hydration, even
  // when the browser already has this mod in its React Query cache.
  const hydrated = useHydrated();
  const data = hydrated ? (detail.data ?? initialData) : initialData;
  if (!data) {
    const notFound = detail.error instanceof ApiError && detail.error.status === 404;
    return (
      <main className="mod-detail container">
        <Link href="/registry" className="mod-back">
          <ArrowLeft size={16} aria-hidden />
          Back to mods
        </Link>
        {detail.isError ? (
          <div className="mod-load-state">
            <h1>{notFound ? 'Mod not found' : 'The mod couldn’t be loaded'}</h1>
            <p>
              {notFound
                ? `No mod matches “${slug}”.`
                : 'The registry may be temporarily unavailable.'}
            </p>
            {!notFound ? (
              <button type="button" className="mod-reveal" onClick={() => detail.refetch()}>
                Try again
              </button>
            ) : null}
          </div>
        ) : (
          <div className="mod-load-state">
            <Spinner />
            <output>Loading mod…</output>
          </div>
        )}
      </main>
    );
  }
  const { mod, versions } = data;
  const latest = getDownloadVersion(versions, mod.latestVersion);
  const media = getModMedia(mod);
  const dependencies = Object.entries(mod.dependencies ?? {});
  const useServerDescription = initialData && mod.description === initialData.mod.description;
  const author = mod.author || 'Unknown author';
  const coAuthors = mod.coAuthors ?? [];
  const privateOnly = hasPrivateOnlyTag(mod.tags);
  const tags = mod.tags.filter((tag) => !isPrivateOnlyTag(tag));

  return (
    <main className="mod-detail container">
      <nav aria-label="Breadcrumb" className="mod-breadcrumb">
        <Link href="/registry" className="mod-back">
          <ArrowLeft size={16} aria-hidden />
          All mods
        </Link>
        {mod.category ? (
          <>
            <span aria-hidden>/</span>
            <Link href={registryHref('category', mod.category)} className="capitalize">
              {mod.category}
            </Link>
          </>
        ) : null}
      </nav>
      <header className="mod-heading">
        {mod.tags.length > 0 || mod.nsfw ? (
          <div className="mod-labels">
            {privateOnly ? <ModPrivateOnlyTag slug={slug} /> : null}
            {tags.length > 0 ? (
              <ul className="mod-tags" aria-label="Mod tags">
                {tags.map((tag) => (
                  <li key={tag}>
                    <Link href={registryHref('tags', tag)} title={`More mods tagged ${tag}`}>
                      {tag}
                    </Link>
                  </li>
                ))}
              </ul>
            ) : null}
            {mod.nsfw ? <span className="mod-mature-label">Mature content</span> : null}
          </div>
        ) : null}
        <h1>{mod.name}</h1>
        {mod.summary?.trim() ? <p className="mod-summary">{mod.summary}</p> : null}
        <div className="mod-social-proof">
          {mod.downloads != null ? (
            <span>
              <Download size={16} aria-hidden />
              {mod.downloads.toLocaleString('en-US')} downloads
            </span>
          ) : null}
          <ModRatingSummary slug={slug} fallbackRating={mod.rating} />
        </div>
      </header>
      <ModGallery key={slug} media={media} name={mod.name} nsfw={mod.nsfw} />
      <div className="mod-body">
        <nav className="mod-section-nav" aria-label="On this page">
          <a href="#about">About this mod</a>
          <a href="#reviews">Reviews</a>
          {/* biome-ignore lint/a11y/useValidAnchor: navigates to the history section and expands its destination. */}
          <a
            href="#version-history"
            onClick={() => {
              const history = document.getElementById('version-history');
              if (history instanceof HTMLDetailsElement) history.open = true;
            }}
          >
            Version history<span>{versions.length}</span>
          </a>
        </nav>
        <div className="mod-content-grid">
          <aside className="mod-download-sidebar" aria-label="Download and mod details">
            <div className="mod-download-card">
              <h2>Get this mod</h2>
              <ModActions slug={slug} version={latest} managerDownloads={managerDownloads} />
              <div className="mod-facts">
                <dl>
                  <div>
                    <dt>Updated</dt>
                    <dd>
                      <time dateTime={mod.updatedAt}>{formatModDate(mod.updatedAt)}</time>
                    </dd>
                  </div>
                  {mod.license ? (
                    <div>
                      <dt>License</dt>
                      <dd>{mod.license}</dd>
                    </div>
                  ) : null}
                </dl>
              </div>
            </div>
            <div className="mod-author-row">
              <span className="mod-author-avatar" aria-hidden>
                {author.slice(0, 2).toUpperCase()}
              </span>
              <div className="mod-author">
                <span>Created by</span>
                <div className="mod-author-names">
                  {mod.ownerId ? (
                    <Link href={`/u/${mod.ownerId}` as Route}>{author}</Link>
                  ) : (
                    <strong>{author}</strong>
                  )}
                  {coAuthors.length > 0 ? (
                    <span className="mod-coauthors">
                      {' '}
                      with{' '}
                      {coAuthors.map((a, i) => (
                        <Fragment key={a.userId}>
                          {i > 0 ? (i === coAuthors.length - 1 ? ' and ' : ', ') : null}
                          <Link href={`/u/${a.userId}` as Route}>
                            {a.name ?? (a.handle ? `@${a.handle}` : 'a co-author')}
                          </Link>
                        </Fragment>
                      ))}
                    </span>
                  ) : null}
                </div>
              </div>
              <FollowButton
                key={`${slug}-${mod.isFollowing}`}
                slug={slug}
                initialFollowing={mod.isFollowing ?? false}
                followerCount={mod.followerCount ?? 0}
              />
            </div>
            <div className="mod-report">
              <ReportModal slug={slug} />
            </div>
            {!privateOnly ? <ModPrivateOnlyControls slug={slug} privateOnly={false} /> : null}
          </aside>
          <div className="mod-reading">
            <section id="about" className="mod-section" aria-labelledby="mod-about-heading">
              <h2 id="mod-about-heading">About this mod</h2>
              {mod.description?.trim() ? (
                useServerDescription ? (
                  <article
                    data-color-mode="dark"
                    className="md-editor-themed prose-invert user-prose mod-description"
                    // biome-ignore lint/security/noDangerouslySetInnerHtml: descriptionHtml is rendered and sanitized on the server by renderMarkdown().
                    dangerouslySetInnerHTML={{ __html: descriptionHtml }}
                  />
                ) : (
                  <article
                    data-color-mode="dark"
                    className="md-editor-themed prose-invert mod-description"
                  >
                    <MDPreview source={mod.description} />
                  </article>
                )
              ) : (
                <p className="mod-description">
                  {mod.summary?.trim() || 'The author hasn’t added a description yet.'}
                </p>
              )}
              {dependencies.length > 0 || mod.gameBuild || mod.sdkVersion ? (
                <div className="mod-requirements">
                  <h3>Before you install</h3>
                  {dependencies.length > 0 ? (
                    <>
                      <p>This mod requires:</p>
                      <ul>
                        {dependencies.map(([dependency, range]) => (
                          <li key={dependency}>
                            <Link href={`/registry/${dependency}` as Route}>{dependency}</Link>
                            <span>{range}</span>
                          </li>
                        ))}
                      </ul>
                    </>
                  ) : null}
                  {mod.gameBuild ? (
                    <p>
                      Game build: <strong>{mod.gameBuild}</strong>
                    </p>
                  ) : null}
                  {mod.sdkVersion ? (
                    <p>
                      RSMM SDK: <strong>{mod.sdkVersion}</strong>
                    </p>
                  ) : null}
                </div>
              ) : null}
              {mod.repoUrl || mod.homepageUrl ? (
                <div className="mod-project-links">
                  {mod.repoUrl ? (
                    <a href={mod.repoUrl} target="_blank" rel="noopener noreferrer">
                      Source code
                      <ExternalLink size={14} aria-hidden />
                    </a>
                  ) : null}
                  {mod.homepageUrl ? (
                    <a href={mod.homepageUrl} target="_blank" rel="noopener noreferrer">
                      Project website
                      <ExternalLink size={14} aria-hidden />
                    </a>
                  ) : null}
                </div>
              ) : null}
            </section>
            <ReviewsSection slug={slug} isAuthor={mod.isAuthor ?? false} />
            <details id="version-history" className="mod-version-history">
              <summary>
                <div>
                  <h2>Version history</h2>
                  <p>Release notes and previous downloads</p>
                </div>
                <span className="mod-version-count">
                  {versions.length} {versions.length === 1 ? 'release' : 'releases'}
                </span>
                <ChevronDown className="mod-disclosure-chevron" size={20} aria-hidden />
              </summary>
              {versions.length > 0 ? (
                <div className="mod-version-list">
                  {versions.map((version) => (
                    <VersionRow
                      key={version.id}
                      version={version}
                      slug={slug}
                      latest={version.id === latest?.id}
                    />
                  ))}
                </div>
              ) : (
                <p className="mod-history-empty">No releases have been published yet.</p>
              )}
            </details>
          </div>
        </div>
      </div>
    </main>
  );
}

function VersionRow({
  version,
  slug,
  latest,
}: { version: ModVersion; slug: string; latest: boolean }) {
  const downloadUrl = `${getApiUrl().replace(/\/+$/, '')}/api/mods/${encodeURIComponent(slug)}/${encodeURIComponent(version.version)}/download`;
  return (
    <div className="mod-version-row">
      <div className="mod-version-summary">
        <div>
          <div className="mod-version-name">
            <h3>Version {version.version}</h3>
            {latest ? <span>Latest</span> : null}
          </div>
          <p>
            <time dateTime={version.createdAt}>{formatModDate(version.createdAt)}</time>
            <span aria-hidden>·</span>
            {formatFileSize(version.sizeBytes)}
          </p>
        </div>
        <a href={downloadUrl} aria-label={`Download version ${version.version}`}>
          <ArrowDownToLine size={17} aria-hidden />
          Download
        </a>
      </div>
      {version.changelog ? (
        <details className="mod-changelog">
          <summary>Release notes</summary>
          <div data-color-mode="dark" className="md-editor-themed prose-invert">
            <MDPreview source={version.changelog} />
          </div>
        </details>
      ) : null}
    </div>
  );
}
