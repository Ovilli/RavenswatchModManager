import type { Metadata } from 'next';
import { apiUrl } from './metadata';

const SITE = 'Ravenswatch Mod Manager';
const ORIGIN = 'https://rsmm.me';

// Deduped with generateMetadata's fetch (same URL+opts) within a request.
async function getCollection(slug: string): Promise<{ name?: string } | null> {
  try {
    const res = await fetch(`${apiUrl}/api/collections/${slug}`, { next: { revalidate: 60 } });
    if (!res.ok) return null;
    const json = await res.json();
    return json?.name ? json : null;
  } catch {
    return null;
  }
}

export async function generateMetadata({
  params,
}: { params: Promise<{ slug: string }> }): Promise<Metadata> {
  const { slug } = await params;
  try {
    const res = await fetch(`${apiUrl}/api/collections/${slug}`, {
      next: { revalidate: 60 },
    });
    if (!res.ok) return { title: `Collection · ${SITE}` };
    const json = await res.json();
    if (!json?.name) return { title: `Collection · ${SITE}` };

    const title = `${json.name} · Collection · ${SITE}`;
    const description =
      json.summary ?? `A collection of ${json.modCount} mods for Ravenswatch.`;
    const image: string | undefined = json.imageUrl;

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
        images: image ? [{ url: image, alt: `${json.name} collection` }] : undefined,
      },
      twitter: {
        card: image ? 'summary_large_image' : 'summary',
        title,
        description,
        images: image ? [image] : undefined,
      },
    };
  } catch {
    return { title: `Collection · ${SITE}` };
  }
}

export default async function Layout({
  children,
  params,
}: {
  children: React.ReactNode;
  params: Promise<{ slug: string }>;
}) {
  const { slug } = await params;
  const collection = await getCollection(slug);
  return (
    <>
      {collection ? (
        <script
          type="application/ld+json"
          // biome-ignore lint/security/noDangerouslySetInnerHtml: server-built JSON-LD from our own API, not user HTML.
          dangerouslySetInnerHTML={{
            __html: JSON.stringify({
              '@context': 'https://schema.org',
              '@type': 'BreadcrumbList',
              itemListElement: [
                { '@type': 'ListItem', position: 1, name: 'Home', item: ORIGIN },
                { '@type': 'ListItem', position: 2, name: 'Collections', item: `${ORIGIN}/c` },
                { '@type': 'ListItem', position: 3, name: collection.name },
              ],
            }),
          }}
        />
      ) : null}
      {children}
    </>
  );
}
