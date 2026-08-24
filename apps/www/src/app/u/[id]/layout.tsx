import type { Metadata } from 'next';
import { notFound } from 'next/navigation';
import { type Entity, fetchEntity } from '../../../lib/entity';

const SITE = 'Ravenswatch Mod Manager';

interface Profile {
  user?: { name?: string; handle?: string | null; image?: string };
  mods?: unknown[];
}

// Deduped with generateMetadata within a request.
async function getProfile(id: string): Promise<Entity<Profile>> {
  const res = await fetchEntity<Profile>(`/api/users/${id}`);
  if (res.state !== 'ok') return res;
  return res.data?.user?.name ? res : { state: 'error' };
}

// Own canonical + noindex — the root layout's `canonical: '/'` would otherwise
// claim a dead author URL is the home page.
function fallbackMetadata(id: string): Metadata {
  return {
    title: `Author · ${SITE}`,
    robots: { index: false, follow: false },
    alternates: { canonical: `/u/${id}` },
  };
}

export async function generateMetadata({
  params,
}: { params: Promise<{ id: string }> }): Promise<Metadata> {
  const { id } = await params;
  const res = await getProfile(id);
  if (res.state !== 'ok') return fallbackMetadata(id);
  const { user, mods } = res.data;

  const handle = user?.handle ? ` (@${user.handle})` : '';
  const count = mods?.length ?? 0;
  const title = `${user?.name}${handle} · ${SITE}`;
  const description = `${user?.name} has published ${count} mod${count === 1 ? '' : 's'} for Ravenswatch.`;
  const image = user?.image;

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
      images: image ? [{ url: image, alt: `${user?.name} avatar` }] : undefined,
    },
    twitter: {
      card: 'summary',
      title,
      description,
      images: image ? [image] : undefined,
    },
  };
}

export default async function Layout({
  children,
  params,
}: {
  children: React.ReactNode;
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  const res = await getProfile(id);
  // Real 404 for an author the API does not know; an API blip falls through.
  if (res.state === 'missing') notFound();
  return children;
}
