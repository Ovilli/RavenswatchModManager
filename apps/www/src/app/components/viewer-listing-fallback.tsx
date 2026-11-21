'use client';

import { usePathname } from 'next/navigation';
import type { ReactNode } from 'react';
import { useSession } from '../../lib/auth-client';
import type { InstallerDownloads } from '../../lib/releases';
import { useHydrated } from '../../lib/use-hydrated';
import { CollectionDetailView } from '../c/[slug]/collection-detail-view';
import { ModDetailView } from '../registry/[slug]/mod-detail-view';

const LISTING_PATH = /^\/(registry|c)\/([a-z0-9_-]+)\/?$/;

/**
 * The `[slug]` detail routes are ISR and fetch anonymously, so a private,
 * hidden or removed listing is a 404 on the server (it must be: reading the
 * session cookie in an ISR render throws DYNAMIC_SERVER_USAGE). The API still
 * serves those listings to their owner and to admins, so for a signed-in
 * visitor on a listing URL the 404 page hands over to the normal client detail
 * view, which fetches with the session (`credentials: 'include'`) and shows
 * "not found" itself if the viewer has no access. Everyone else, and crawlers,
 * get the plain 404 — the response status stays 404 either way.
 */
export function ViewerListingFallback({
  managerDownloads,
  children,
}: {
  managerDownloads: InstallerDownloads;
  children: ReactNode;
}) {
  const pathname = usePathname();
  const hydrated = useHydrated();
  const { data: session } = useSession();
  const match = pathname ? LISTING_PATH.exec(pathname) : null;
  if (!hydrated || !session || !match) return <>{children}</>;

  const [, kind, slug] = match as unknown as [string, 'registry' | 'c', string];
  if (kind === 'c') return <CollectionDetailView key={slug} slug={slug} />;
  return (
    <ModDetailView key={slug} slug={slug} descriptionHtml="" managerDownloads={managerDownloads} />
  );
}
