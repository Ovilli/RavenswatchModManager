import type { Metadata } from 'next';
import { apiUrl } from './metadata';

export async function generateMetadata({
  params,
}: { params: Promise<{ slug: string }> }): Promise<Metadata> {
  const { slug } = await params;
  try {
    const res = await fetch(`${apiUrl}/api/collections/${slug}`, {
      next: { revalidate: 60 },
    });
    if (!res.ok) return { title: 'Collection · Ravenswatch Mod Manager' };
    const json = await res.json();
    return {
      title: `${json.name} · Collection · Ravenswatch Mod Manager`,
      description: json.summary ?? `A collection of ${json.modCount} mods for Ravenswatch.`,
      openGraph: json.imageUrl ? { images: [{ url: json.imageUrl }] } : undefined,
    };
  } catch {
    return { title: 'Collection · Ravenswatch Mod Manager' };
  }
}

export default function Layout({ children }: { children: React.ReactNode }) {
  return children;
}
