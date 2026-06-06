'use client';

import { buttonVariants } from '@rsmm/ui';
import Link from 'next/link';
import { useEffect, useState } from 'react';

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

export function OsDownload() {
  const [os, setOs] = useState<'Windows' | 'Linux' | 'unsupported'>('Linux');

  useEffect(() => {
    setOs(detectOS());
  }, []);

  const label = os === 'unsupported' ? 'Download (Windows / Linux)' : `Download for ${os}`;

  return (
    <Link href="/download" className={buttonVariants({ size: 'lg' })}>
      {label}
    </Link>
  );
}
