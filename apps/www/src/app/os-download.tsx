'use client';

import { buttonVariants } from '@rsmm/ui';
import Link from 'next/link';
import { useEffect, useState } from 'react';

function detectOS(): string {
  if (typeof window === 'undefined') return 'Linux';
  const p = navigator.platform.toLowerCase();
  const ua = navigator.userAgent.toLowerCase();
  if (p.includes('win') || ua.includes('windows')) return 'Windows';
  if (p.includes('mac') || ua.includes('mac os')) return 'macOS';
  return 'Linux';
}

export function OsDownload() {
  const [os, setOs] = useState('Linux');

  useEffect(() => {
    setOs(detectOS());
  }, []);

  return (
    <Link href="/download" className={buttonVariants({ size: 'lg' })}>
      Download for {os}
    </Link>
  );
}
