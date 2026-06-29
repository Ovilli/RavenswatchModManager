import { buttonVariants } from '@rsmm/ui';
import type { Metadata } from 'next';
import Link from 'next/link';

export const metadata: Metadata = {
  title: 'Not found · Ravenswatch Mod Manager',
};

export default function NotFound() {
  return (
    <main className="relative flex min-h-[70vh] items-center justify-center overflow-hidden px-6">
      <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(circle_at_50%_-20%,hsl(var(--crimson)/0.12),transparent_50%)]" />
      <div className="relative mx-auto max-w-md text-center">
        <p className="font-mono text-7xl font-black tracking-tight text-gilt">404</p>
        <h1 className="mt-4 text-2xl font-bold tracking-tight">Lost in the storm</h1>
        <p className="mt-2 text-muted-foreground">
          That page wandered off. The mod, collection, or link may have been removed or renamed.
        </p>
        <div className="mt-8 flex items-center justify-center gap-3">
          <Link href="/" className={buttonVariants({ size: 'lg' })}>
            Back home
          </Link>
          <Link
            href="/registry"
            className={buttonVariants({ variant: 'outline', size: 'lg' })}
          >
            Browse mods
          </Link>
        </div>
      </div>
    </main>
  );
}
