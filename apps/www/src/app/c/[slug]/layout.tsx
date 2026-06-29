import type { Metadata } from 'next';
import { apiUrl } from './metadata';

const SITE = 'Ravenswatch Mod Manager';

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

export default function Layout({ children }: { children: React.ReactNode }) {
  return children;
}
