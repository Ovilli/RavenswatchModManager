import type { Metadata } from 'next';
import { getApiUrl } from '../../../lib/api-url';

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

// Deduped with generateMetadata within a request. Unauthenticated, so the API
// only returns approved guides — drafts/pending get the generic fallback and
// are never indexed.
async function getGuide(slug: string): Promise<Guide | null> {
  try {
    const res = await fetch(`${getApiUrl()}/api/guides/${slug}`, { next: { revalidate: 60 } });
    if (!res.ok) return null;
    const g = await res.json();
    return g?.title && g.status === 'approved' ? g : null;
  } catch {
    return null;
  }
}

export async function generateMetadata({
  params,
}: { params: Promise<{ slug: string }> }): Promise<Metadata> {
  const { slug } = await params;
  const g = await getGuide(slug);
  if (!g) return { title: `Guide · ${SITE}` };

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
  const g = await getGuide(slug);
  return (
    <>
      {g ? (
        <script
          type="application/ld+json"
          // biome-ignore lint/security/noDangerouslySetInnerHtml: server-built JSON-LD from our own API, not user HTML.
          dangerouslySetInnerHTML={{ __html: JSON.stringify(guideJsonLd(slug, g)) }}
        />
      ) : null}
      {children}
    </>
  );
}
