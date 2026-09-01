import type { Metadata } from 'next';

// Own canonical + title: the page is a client component, so it cannot export
// metadata itself and would inherit the root layout's `canonical: '/'` —
// telling Google the registry IS the home page.
export const metadata: Metadata = {
  title: 'Ravenswatch Mod Registry — Browse every mod',
  description:
    'Browse every Ravenswatch mod: textures, custom items, talents, enemies and Lua scripts. Sort by popularity or rating and install any of them in one click.',
  alternates: { canonical: '/registry' },
};

export default function Layout({ children }: { children: React.ReactNode }) {
  return children;
}
