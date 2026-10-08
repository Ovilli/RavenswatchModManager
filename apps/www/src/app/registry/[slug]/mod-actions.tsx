'use client';
import { ApiError } from '@rsmm/api-client';
import { buttonVariants } from '@rsmm/ui';
import { useQuery } from '@tanstack/react-query';
import { Download, ExternalLink } from 'lucide-react';
import { useEffect, useState } from 'react';
import { api } from '../../../lib/api';
import { getApiUrl } from '../../../lib/api-url';
import { useHydrated } from '../../../lib/use-hydrated';
import { FollowButton } from '../../components/follow-button';
import { ReportModal } from '../../components/report-modal';

type ClientOS = 'windows' | 'linux' | 'other';

// RSMM desktop ships for Windows + Linux only. Non-target platforms (macOS)
// resolve to 'other' so we label the button neutrally instead of promising a
// Mac build. The downloaded mod zip itself is platform-agnostic.
function getClientOS(): ClientOS {
  const p = navigator.platform.toLowerCase();
  const ua = navigator.userAgent.toLowerCase();
  if (p.includes('win') || ua.includes('windows')) return 'windows';
  if (p.includes('linux') || p.includes('x11')) return 'linux';
  return 'other';
}

const OS_LABELS: Record<ClientOS, string> = {
  windows: 'Windows',
  linux: 'Linux',
  other: '',
};

/** The query the page itself runs, so both share one request and one cache entry. */
export function useModDetail(slug: string) {
  return useQuery({
    queryKey: ['mods', 'detail', slug],
    queryFn: () => api.mods.get(slug),
    retry: (count, err) => (err instanceof ApiError && err.status === 404 ? false : count < 1),
  });
}

/**
 * Download, Open in App, Follow and Report for one mod.
 *
 * Rendered by `[slug]/layout.tsx` directly under the title, not by the client
 * page: the page comes after the server-rendered description, so a mod with a
 * long README put its Download button a screen or more below the fold. The
 * download link is built from the server's `latestVersion` and is in the first
 * HTML; Follow needs the viewer's session and waits for the client fetch.
 */
export function ModActions({
  slug,
  latestVersion,
  waitForClient = false,
}: {
  slug: string;
  latestVersion?: string | null;
  /** The server could not load the mod: show nothing until the client has it,
   *  rather than buttons for a mod that may not exist. */
  waitForClient?: boolean;
}) {
  const detail = useModDetail(slug);
  // Ignore the cache until hydrated: the server rendered without it.
  const data = useHydrated() ? detail.data : undefined;
  // Detected after mount: the server cannot know it, and guessing would
  // render a label the client then disagrees with.
  const [os, setOs] = useState<ClientOS>('other');
  useEffect(() => setOs(getClientOS()), []);

  const version = data?.versions[0]?.version ?? latestVersion ?? null;
  const downloadUrl = version
    ? `${getApiUrl().replace(/\/+$/, '')}/api/mods/${slug}/${version}/download`
    : null;
  const mod = data?.mod;
  if (waitForClient && !mod) return null;

  return (
    <div className="flex flex-wrap items-center gap-2">
      {downloadUrl ? (
        <a href={downloadUrl} className={buttonVariants({ variant: 'default', size: 'sm' })}>
          <Download className="mr-1.5 h-4 w-4" aria-hidden="true" />
          {OS_LABELS[os] ? `Download for ${OS_LABELS[os]}` : 'Download'}
        </a>
      ) : null}
      <a
        href={`rsmm://mods/${slug}`}
        className={buttonVariants({ variant: 'outline', size: 'sm' })}
        title="Open in RSMM desktop app"
      >
        <ExternalLink className="mr-1.5 h-4 w-4" aria-hidden="true" />
        Open in App
      </a>
      {mod ? (
        <FollowButton
          slug={slug}
          initialFollowing={mod.isFollowing ?? false}
          followerCount={mod.followerCount ?? 0}
        />
      ) : null}
      <ReportModal slug={slug} />
    </div>
  );
}
