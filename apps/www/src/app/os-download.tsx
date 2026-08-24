'use client';

import { buttonVariants } from '@rsmm/ui';
import type { Route } from 'next';
import Link from 'next/link';
import { useEffect, useState } from 'react';
import type { LatestRelease } from '../lib/releases';

// RSMM ships for Windows + Linux only. macOS is detected but treated as
// unsupported, so we never promise a Mac build that does not exist.
function detectOS(): 'Windows' | 'Linux' | 'unsupported' {
  if (typeof window === 'undefined') return 'Linux';
  const p = navigator.platform.toLowerCase();
  const ua = navigator.userAgent.toLowerCase();
  if (p.includes('win') || ua.includes('windows')) return 'Windows';
  if (p.includes('mac') || ua.includes('mac os')) return 'unsupported';
  return 'Linux';
}

/**
 * Hero CTA: starts the installer download straight from GitHub.
 *
 * The URLs are resolved on the server (`getLatestRelease`) and passed in —
 * api.github.com is not in the CSP's `connect-src`, so resolving them here
 * would leave the button hrefless. When the release lookup fails, or the
 * visitor is on an unsupported OS, it degrades to `/download`, which explains
 * the platforms and links the release page.
 *
 * GitHub serves release assets with `Content-Disposition: attachment`, so a
 * plain cross-origin href downloads without navigating away; the `download`
 * attribute is ignored cross-origin and is not relied on.
 */
export function OsDownload({
  release,
  fallbackHref = '/download',
}: {
  release: LatestRelease;
  /** Where to send a visitor with no resolvable asset. Defaults to /download —
   *  the download page itself passes the GitHub release page instead, since
   *  falling back to the page you are already on is a dead click. */
  fallbackHref?: string;
}) {
  const [os, setOs] = useState<'Windows' | 'Linux' | 'unsupported'>('Linux');

  useEffect(() => {
    setOs(detectOS());
  }, []);

  const href = os === 'Windows' ? release.windows : os === 'Linux' ? release.linux : null;
  const version = release.tag ? ` · ${release.tag}` : '';
  const className = buttonVariants({ size: 'lg' });

  if (!href) {
    const label = os === 'unsupported' ? 'Download (Windows / Linux)' : `Download for ${os}`;
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
