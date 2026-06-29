import type { Metadata } from 'next';

const apiUrl = process.env.NEXT_PUBLIC_API_URL || 'https://api.rsmm.me';
const SITE = 'Ravenswatch Mod Manager';
const ORIGIN = 'https://rsmm.me';

interface Mod {
  name?: string;
  author?: string | null;
  summary?: string | null;
  imageUrl?: string | null;
  screenshots?: string[];
  rating?: number | null;
  ratingCount?: number | null;
  downloads?: number;
}

// fetch() with identical args is deduped by Next within a request, so
// generateMetadata and the layout component share this one round-trip.
async function getMod(slug: string): Promise<Mod | null> {
  try {
    const res = await fetch(`${apiUrl}/api/mods/${slug}`, { next: { revalidate: 60 } });
    if (!res.ok) return null;
    // GET /api/mods/:slug wraps the record: { mod, versions }.
    const { mod } = await res.json();
    return mod?.name ? mod : null;
  } catch {
    return null;
  }
}

export async function generateMetadata({
  params,
}: { params: Promise<{ slug: string }> }): Promise<Metadata> {
  const { slug } = await params;
  const mod = await getMod(slug);
  if (!mod) return { title: `Mod · ${SITE}` };

  const title = `${mod.name}${mod.author ? ` by ${mod.author}` : ''} · ${SITE}`;
  const description =
    mod.summary ?? `Install ${mod.name} for Ravenswatch in one click with the ${SITE}.`;
  // Prefer the cover image, fall back to the first screenshot.
  const image = mod.imageUrl ?? mod.screenshots?.[0];

  return {
    title,
    description,
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
  const mod = await getMod(slug);
  return (
    <>
      {mod ? (
        <script
          type="application/ld+json"
          // biome-ignore lint/security/noDangerouslySetInnerHtml: JSON-LD must be inlined as a script body; the payload is server-built from our own API, not user HTML.
          dangerouslySetInnerHTML={{ __html: JSON.stringify(modJsonLd(slug, mod)) }}
        />
      ) : null}
      {children}
    </>
  );
}
