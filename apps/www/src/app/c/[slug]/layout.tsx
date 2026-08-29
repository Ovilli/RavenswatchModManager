import { jsonLd } from '@rsmm/schemas';
import type { Metadata } from 'next';
import { notFound } from 'next/navigation';
import { type Entity, fetchEntity } from '../../../lib/entity';
import { ServerProse } from '../../components/server-prose';

const SITE = 'Ravenswatch Mod Manager';
const ORIGIN = 'https://rsmm.me';

interface Collection {
  name?: string;
  summary?: string | null;
  description?: string | null;
  modCount?: number;
  imageUrl?: string;
  ownerName?: string | null;
  updatedAt?: string | null;
}

// One helper for both generateMetadata and the layout body (the fetch itself is
// deduped by Next within a request); they used to hand-roll the same request
// twice and disagree about what "not found" meant.
async function getCollection(slug: string): Promise<Entity<Collection>> {
  const res = await fetchEntity<Collection>(`/api/collections/${slug}`);
  if (res.state !== 'ok') return res;
  return res.data?.name ? res : { state: 'error' };
}

// Own canonical + noindex, else the root layout's `canonical: '/'` leaks onto
// a URL that resolves to nothing.
function fallbackMetadata(slug: string): Metadata {
  return {
    title: `Collection · ${SITE}`,
    robots: { index: false, follow: false },
    alternates: { canonical: `/c/${slug}` },
  };
}

export async function generateMetadata({
  params,
}: { params: Promise<{ slug: string }> }): Promise<Metadata> {
  const { slug } = await params;
  const res = await getCollection(slug);
  if (res.state !== 'ok') return fallbackMetadata(slug);
  const collection = res.data;

  const title = `${collection.name} · Collection · ${SITE}`;
  const description =
    collection.summary ?? `A collection of ${collection.modCount} mods for Ravenswatch.`;
  const image = collection.imageUrl;

  return {
    title,
    description,
    alternates: { canonical: `/c/${slug}` },
    openGraph: {
      type: 'article',
      title,
      description,
      url: `/c/${slug}`,
      siteName: SITE,
      images: image ? [{ url: image, alt: `${collection.name} collection` }] : undefined,
    },
    twitter: {
      card: image ? 'summary_large_image' : 'summary',
      title,
      description,
      images: image ? [image] : undefined,
    },
  };
}

// The star average deliberately stays out of this byline: it comes from a
// separate client query and is already rendered by the reviews section.
function collectionByline(c: Collection): string {
  const parts = [`by ${c.ownerName ?? 'unknown'}`];
  if (c.updatedAt) parts.push(`updated ${new Date(c.updatedAt).toLocaleDateString('en-US')}`);
  return parts.join(' · ');
}

export default async function Layout({
  children,
  params,
}: {
  children: React.ReactNode;
  params: Promise<{ slug: string }>;
}) {
  const { slug } = await params;
  const res = await getCollection(slug);
  // Real 404 for a slug the API does not know; an API blip falls through.
  if (res.state === 'missing') notFound();
  return (
    <>
      {res.state === 'ok' ? (
        <script
          type="application/ld+json"
          // biome-ignore lint/security/noDangerouslySetInnerHtml: JSON-LD must be inlined as a script body. The payload carries the user-submitted collection name, so it goes through jsonLd() — see lib/json-ld.ts.
          dangerouslySetInnerHTML={{
            __html: jsonLd({
              '@context': 'https://schema.org',
              '@type': 'BreadcrumbList',
              itemListElement: [
                { '@type': 'ListItem', position: 1, name: 'Home', item: ORIGIN },
                { '@type': 'ListItem', position: 2, name: 'Collections', item: `${ORIGIN}/c` },
                { '@type': 'ListItem', position: 3, name: res.data.name },
              ],
            }),
          }}
        />
      ) : null}
      {/* Server-rendered name, byline, summary and description. The client page
          below keeps the cover image, the owner controls and the mod list. */}
      {res.state === 'ok' ? (
        <ServerProse
          backHref="/c"
          backLabel="Back to Collections"
          title={res.data.name ?? slug}
          byline={collectionByline(res.data)}
          summary={res.data.summary}
          image={{ url: res.data.imageUrl, alt: `${res.data.name ?? slug} cover` }}
          body={res.data.description}
          bodyHeading="About"
          card
        />
      ) : null}
      {children}
    </>
  );
}
