import type { Metadata } from 'next';
import { notFound } from 'next/navigation';
import { type Entity, fetchEntity } from '../../../lib/entity';

const SITE = 'Ravenswatch Mod Manager';
const ORIGIN = 'https://rsmm.me';

interface Mod {
  name?: string;
  author?: string | null;
  summary?: string | null;
  description?: string | null;
  imageUrl?: string | null;
  screenshots?: string[];
  rating?: number | null;
  ratingCount?: number | null;
  downloads?: number;
}

// GET /api/mods/:slug wraps the record: { mod, versions }.
// fetch() with identical args is deduped by Next within a request, so
// generateMetadata and the layout component share this one round-trip.
async function getMod(slug: string): Promise<Entity<Mod>> {
  const res = await fetchEntity<{ mod?: Mod }>(`/api/mods/${slug}`);
  if (res.state !== 'ok') return res;
  return res.data?.mod?.name ? { state: 'ok', data: res.data.mod } : { state: 'error' };
}

// A URL that resolves to nothing must never be indexable, and must carry its
// OWN canonical — without `alternates` the root layout's `canonical: '/'` wins
// and the dead URL claims to be the home page.
function fallbackMetadata(slug: string): Metadata {
  return {
    title: `Mod · ${SITE}`,
    robots: { index: false, follow: false },
    alternates: { canonical: `/registry/${slug}` },
  };
}

export async function generateMetadata({
  params,
}: { params: Promise<{ slug: string }> }): Promise<Metadata> {
  const { slug } = await params;
  const res = await getMod(slug);
  if (res.state !== 'ok') return fallbackMetadata(slug);
  const mod = res.data;

  const title = `${mod.name}${mod.author ? ` by ${mod.author}` : ''} · ${SITE}`;
  const description =
    mod.summary ?? `Install ${mod.name} for Ravenswatch in one click with the ${SITE}.`;
  // Prefer the cover image, fall back to the first screenshot.
  const image = mod.imageUrl ?? mod.screenshots?.[0];

  // Thin-content hygiene: a mod with no author-written summary or long
  // description is a near-empty page. Keep it reachable but out of the index so
  // it doesn't drag down the site's overall content quality (matters for ad /
  // search review). It re-enters the index automatically once the author adds a
  // description.
  const thin = !mod.summary?.trim() && (mod.description?.trim().length ?? 0) < 80;

  return {
    title,
    description,
    ...(thin ? { robots: { index: false, follow: true } } : {}),
    alternates: { canonical: `/registry/${slug}` },
    openGraph: {
      type: 'article',
      title,
      description,
      url: `/registry/${slug}`,
      siteName: SITE,
      images: image ? [{ url: image, alt: `${mod.name} preview` }] : undefined,
    },
    twitter: {
      card: image ? 'summary_large_image' : 'summary',
      title,
      description,
      images: image ? [image] : undefined,
    },
  };
}

function modJsonLd(slug: string, mod: Mod) {
  const image = mod.imageUrl ?? mod.screenshots?.[0];
  // Google requires ratingCount/reviewCount alongside ratingValue, else the
  // whole rich result is rejected — only emit aggregateRating when both exist.
  const hasRating = mod.rating != null && mod.ratingCount != null && mod.ratingCount > 0;
  return {
    '@context': 'https://schema.org',
    '@graph': [
      {
        '@type': 'SoftwareApplication',
        name: mod.name,
        description: mod.summary ?? `${mod.name} — a mod for Ravenswatch.`,
        applicationCategory: 'GameApplication',
        operatingSystem: 'Windows, Linux',
        url: `${ORIGIN}/registry/${slug}`,
        ...(image ? { image } : {}),
        ...(mod.author ? { author: { '@type': 'Person', name: mod.author } } : {}),
        offers: { '@type': 'Offer', price: '0', priceCurrency: 'USD' },
        ...(hasRating
          ? {
              aggregateRating: {
                '@type': 'AggregateRating',
                ratingValue: mod.rating,
                ratingCount: mod.ratingCount,
                bestRating: 5,
              },
            }
          : {}),
      },
      {
        '@type': 'BreadcrumbList',
        itemListElement: [
          { '@type': 'ListItem', position: 1, name: 'Home', item: ORIGIN },
          { '@type': 'ListItem', position: 2, name: 'Registry', item: `${ORIGIN}/registry` },
          { '@type': 'ListItem', position: 3, name: mod.name },
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
  const res = await getMod(slug);
  // Deleted / never-existed slug: answer 404 rather than a 200 shell. This only
  // reaches the client as a real 404 because nothing above `[slug]` streams a
  // Suspense fallback first — see the note in `(list)/loading.tsx`.
  //
  // An API blip (state 'error') deliberately falls through to the client page,
  // which retries on its own: an outage must not 404 the whole registry.
  if (res.state === 'missing') notFound();
  return (
    <>
      {res.state === 'ok' ? (
        <script
          type="application/ld+json"
          // biome-ignore lint/security/noDangerouslySetInnerHtml: JSON-LD must be inlined as a script body; the payload is server-built from our own API, not user HTML.
          dangerouslySetInnerHTML={{ __html: JSON.stringify(modJsonLd(slug, res.data)) }}
        />
      ) : null}
      {children}
    </>
  );
}
