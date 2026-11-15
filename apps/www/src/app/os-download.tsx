'use client';

import { buttonVariants } from '@rsmm/ui';
import type { Route } from 'next';
import Link from 'next/link';
import { useEffect, useState } from 'react';
import { type DownloadPlatform, detectDownloadPlatform } from '../lib/download-platform';
import type { LatestRelease } from '../lib/releases';

/**
 * Hero CTA: starts the installer download straight from GitHub.
 *
 * The URLs are resolved on the server (`getLatestRelease`) and passed in —
 * api.github.com is not in the CSP's `connect-src`, so resolving them here
 * would leave the button hrefless. When the release lookup fails, or the
 * visitor is on an unsupported OS, it links to `/download`, where both
 * supported platforms remain available.
 *
 * GitHub serves release assets with `Content-Disposition: attachment`, so a
 * plain cross-origin href downloads without navigating away; the `download`
 * attribute is ignored cross-origin and is not relied on.
 */
export function OsDownload({
  release,
  fallbackHref = '/download',
  showVersion = true,
}: {
  release: LatestRelease;
  /** Where to send a visitor with no resolvable asset. */
  fallbackHref?: string;
  /** Append the release tag to the label. Off where the version is shown beside the button. */
  showVersion?: boolean;
}) {
  const [os, setOs] = useState<DownloadPlatform>('unknown');

  useEffect(() => {
    setOs(detectDownloadPlatform(navigator));
  }, []);

  const href = os === 'Windows' ? release.windows : os === 'Linux' ? release.linux : null;
  const version = showVersion && release.tag ? ` · ${release.tag}` : '';
  const className = buttonVariants({ size: 'lg' });

  if (!href) {
    const label =
      os === 'Windows' || os === 'Linux' ? `Download for ${os}` : 'Download (Windows / Linux)';
    return fallbackHref.startsWith('http') ? (
      <a href={fallbackHref} className={className} target="_blank" rel="noreferrer">
        {label}
      </a>
    ) : (
      <Link href={fallbackHref as Route} className={className}>
        {label}
      </Link>
    );
  }

  return (
    <a href={href} className={className} rel="noreferrer">
      {`Download for ${os}${version}`}
    </a>
  );
}
