import type { Metadata } from 'next';

const apiUrl = process.env.NEXT_PUBLIC_API_URL || 'https://api.rsmm.me';
const SITE = 'Ravenswatch Mod Manager';

export async function generateMetadata({
  params,
}: { params: Promise<{ slug: string }> }): Promise<Metadata> {
  const { slug } = await params;
  try {
    const res = await fetch(`${apiUrl}/api/mods/${slug}`, { next: { revalidate: 60 } });
    if (!res.ok) return { title: `Mod · ${SITE}` };
    // GET /api/mods/:slug wraps the record: { mod, versions }.
    const { mod } = await res.json();
    if (!mod?.name) return { title: `Mod · ${SITE}` };

    const title = `${mod.name}${mod.author ? ` by ${mod.author}` : ''} · ${SITE}`;
    const description =
      mod.summary ??
      `Install ${mod.name} for Ravenswatch in one click with the ${SITE}.`;
    // Prefer the cover image, fall back to the first screenshot.
    const image: string | undefined = mod.imageUrl ?? mod.screenshots?.[0];

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
  } catch {
    return { title: `Mod · ${SITE}` };
  }
}

export default function Layout({ children }: { children: React.ReactNode }) {
  return children;
}
