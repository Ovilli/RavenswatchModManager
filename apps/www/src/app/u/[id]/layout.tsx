import type { Metadata } from 'next';
import { getApiUrl } from '../../../lib/api-url';

const SITE = 'Ravenswatch Mod Manager';

export async function generateMetadata({
  params,
}: { params: Promise<{ id: string }> }): Promise<Metadata> {
  const { id } = await params;
  try {
    const res = await fetch(`${getApiUrl()}/api/users/${id}`, { next: { revalidate: 60 } });
    if (!res.ok) return { title: `Author · ${SITE}` };
    const { user, mods } = await res.json();
    if (!user?.name) return { title: `Author · ${SITE}` };

    const handle = user.handle ? ` (@${user.handle})` : '';
    const count = mods?.length ?? 0;
    const title = `${user.name}${handle} · ${SITE}`;
    const description = `${user.name} has published ${count} mod${count === 1 ? '' : 's'} for Ravenswatch.`;
    const image: string | undefined = user.image;

    return {
      title,
      description,
      alternates: { canonical: `/u/${id}` },
      openGraph: {
        type: 'profile',
        title,
        description,
        url: `/u/${id}`,
        siteName: SITE,
        images: image ? [{ url: image, alt: `${user.name} avatar` }] : undefined,
      },
      twitter: {
        card: 'summary',
        title,
        description,
        images: image ? [image] : undefined,
      },
    };
  } catch {
    return { title: `Author · ${SITE}` };
  }
}

export default function Layout({ children }: { children: React.ReactNode }) {
  return children;
}
