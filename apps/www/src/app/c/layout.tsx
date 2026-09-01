import type { Metadata } from 'next';

// Own canonical + title — the list page is a client component and would
// otherwise inherit the root layout's `canonical: '/'`. `/c/[slug]` and
// `/c/new` set their own, so this only covers the index.
export const metadata: Metadata = {
  title: 'Ravenswatch Mod Collections — Curated bundles',
  description:
    'Community-curated bundles of Ravenswatch mods. Install a whole collection at once instead of picking mods one by one.',
  alternates: { canonical: '/c' },
};

export default function Layout({ children }: { children: React.ReactNode }) {
  return children;
}
