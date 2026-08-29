import { jsonLd } from '@rsmm/schemas';
import type { Metadata } from 'next';
import { notFound } from 'next/navigation';
import { type Entity, fetchEntity } from '../../../lib/entity';
import { ServerProse } from '../../components/server-prose';

const SITE = 'Ravenswatch Mod Manager';
const ORIGIN = 'https://rsmm.me';

interface Guide {
  title?: string;
  summary?: string | null;
  body?: string;
  imageUrl?: string | null;
  ownerName?: string | null;
  status?: string;
  createdAt?: string;
  updatedAt?: string;
  rating?: number | null;
  reviewCount?: number;
}

// Deduped with generateMetadata's fetch within a request. Unauthenticated, so
// the API only exposes what a crawler may see.
//
// A non-approved guide is deliberately NOT reported as `missing`: its author
// reaches the same URL with a session and the client page renders the draft for
// them, so 404-ing it server-side would hide a guide from the person who wrote
// it. It is kept out of the index by metadata instead.
async function getGuide(slug: string): Promise<Entity<Guide>> {
  const res = await fetchEntity<Guide>(`/api/guides/${slug}`);
  if (res.state !== 'ok') return res;
  return res.data?.title ? res : { state: 'error' };
}

function isPublic(res: Entity<Guide>): res is { state: 'ok'; data: Guide } {
  return res.state === 'ok' && res.data.status === 'approved';
}

// Own canonical + noindex: without `alternates` the root layout's
// `canonical: '/'` leaks onto a dead or unapproved guide URL.
function fallbackMetadata(slug: string): Metadata {
  return {
    title: `Guide · ${SITE}`,
    robots: { index: false, follow: false },
    alternates: { canonical: `/guides/${slug}` },
  };
}

export async function generateMetadata({
  params,
}: { params: Promise<{ slug: string }> }): Promise<Metadata> {
  const { slug } = await params;
  const res = await getGuide(slug);
  if (!isPublic(res)) return fallbackMetadata(slug);
  const g = res.data;

  const title = `${g.title} · Guides · ${SITE}`;
  const description = g.summary ?? `A community guide for Ravenswatch on the ${SITE}.`;
  const image = g.imageUrl ?? undefined;

  return {
    title,
    description,
    alternates: { canonical: `/guides/${slug}` },
    openGraph: {
      type: 'article',
      title,
      description,
      url: `/guides/${slug}`,
      siteName: SITE,
      images: image ? [{ url: image, alt: g.title }] : undefined,
    },
    twitter: {
      card: image ? 'summary_large_image' : 'summary',
      title,
      description,
      images: image ? [image] : undefined,
    },
  };
}

// Same byline the client page rendered: author, then the star average once
// there are real reviews behind it.
function guideByline(g: Guide): string {
  const author = `by ${g.ownerName ?? 'unknown'}`;
  return g.reviewCount && g.reviewCount > 0 && g.rating != null
    ? `${author} · ★ ${g.rating.toFixed(1)} (${g.reviewCount})`
    : author;
}

function guideJsonLd(slug: string, g: Guide) {
  const image = g.imageUrl ?? undefined;
  return {
    '@context': 'https://schema.org',
    '@graph': [
      {
        '@type': 'Article',
        headline: g.title,
        description: g.summary ?? undefined,
        url: `${ORIGIN}/guides/${slug}`,
        ...(image ? { image } : {}),
        ...(g.ownerName ? { author: { '@type': 'Person', name: g.ownerName } } : {}),
        ...(g.createdAt ? { datePublished: g.createdAt } : {}),
        ...(g.updatedAt ? { dateModified: g.updatedAt } : {}),
        // Star rich-result eligibility — only with real reviews.
        ...(g.rating != null && g.reviewCount && g.reviewCount > 0
          ? {
              aggregateRating: {
                '@type': 'AggregateRating',
                ratingValue: g.rating,
                reviewCount: g.reviewCount,
                bestRating: 5,
                worstRating: 1,
              },
            }
          : {}),
        publisher: { '@type': 'Organization', name: SITE, logo: `${ORIGIN}/logo.png` },
      },
      {
        '@type': 'BreadcrumbList',
        itemListElement: [
          { '@type': 'ListItem', position: 1, name: 'Home', item: ORIGIN },
          { '@type': 'ListItem', position: 2, name: 'Guides', item: `${ORIGIN}/guides` },
          { '@type': 'ListItem', position: 3, name: g.title },
        ],
      },
    ],
  };
}

export default async function Layout({
  children,
  params,
}: {
  children: React.ReactNode;
  params: Promise<{ slug: string }>;
}) {
  const { slug } = await params;
  const res = await getGuide(slug);
  // A slug the API does not know is a real 404. A transient API error is not.
  if (res.state === 'missing') notFound();
  return (
    <>
      {isPublic(res) ? (
        <script
          type="application/ld+json"
          // biome-ignore lint/security/noDangerouslySetInnerHtml: JSON-LD must be inlined as a script body. The payload carries the user-submitted guide title/summary, so it goes through jsonLd() — see lib/json-ld.ts.
          dangerouslySetInnerHTML={{ __html: jsonLd(guideJsonLd(slug, res.data)) }}
        />
      ) : null}
      {/* Only an approved guide is rendered here: a draft is visible to its
          author alone, and the API serves it to their session, not to this
          unauthenticated server fetch. The client page still renders the
          title and body itself for the non-approved case. */}
      {isPublic(res) ? (
        <ServerProse
          backHref="/guides"
          backLabel="Back to Guides"
          title={res.data.title ?? slug}
          byline={guideByline(res.data)}
          summary={res.data.summary}
          body={res.data.body}
          containerClassName="container mx-auto max-w-3xl space-y-6 px-6 pt-12"
        />
      ) : null}
      {children}
    </>
  );
}
