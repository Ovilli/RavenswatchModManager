'use client';
import { Button, buttonVariants } from '@rsmm/ui';
import Link from 'next/link';
import { useEffect } from 'react';

export default function RouteError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    // Surface the error for diagnostics; Next strips messages from the
    // server-rendered digest in production, so the console is the only
    // place the full error survives.
    console.error('[route error]', error);
  }, [error]);

  return (
    <main className="relative flex min-h-[70vh] items-center justify-center overflow-hidden px-6">
      <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(circle_at_50%_-20%,hsl(var(--crimson)/0.12),transparent_50%)]" />
      <div className="relative mx-auto max-w-md text-center">
        <p className="font-mono text-6xl font-black tracking-tight text-crimson">⚠</p>
        <h1 className="mt-4 text-2xl font-bold tracking-tight">Something broke</h1>
        <p className="mt-2 text-muted-foreground">
          An unexpected error interrupted this page. Try again — if it keeps happening, the issue is
          on our side.
        </p>
        {error.digest ? (
          <p className="mt-3 font-data text-xs text-muted-foreground">ref: {error.digest}</p>
        ) : null}
        <div className="mt-8 flex items-center justify-center gap-3">
          <Button size="lg" onClick={reset}>
            Try again
          </Button>
          <Link href="/" className={buttonVariants({ variant: 'outline', size: 'lg' })}>
            Back home
          </Link>
        </div>
      </div>
    </main>
  );
}
