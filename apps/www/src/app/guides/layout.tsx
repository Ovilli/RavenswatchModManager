import type { Metadata } from 'next';

// Own canonical + title — the list page is a client component and would
// otherwise inherit the root layout's `canonical: '/'`. `/guides/[slug]` and
// `/guides/new` set their own, so this only covers the index.
export const metadata: Metadata = {
  title: 'Ravenswatch Modding Guides — Install, build, troubleshoot',
  description:
    'Guides for installing Ravenswatch mods, writing your own, and fixing the common problems — written and rated by the community.',
  alternates: { canonical: '/guides' },
};

export default function Layout({ children }: { children: React.ReactNode }) {
  return children;
}
