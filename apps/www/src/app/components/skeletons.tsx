// Loading placeholders shown via route-level loading.tsx while a segment's
// server work (metadata + JSON-LD fetch) resolves. Decorative only.

export function DetailSkeleton() {
  return (
    <main className="container mx-auto animate-pulse px-6 py-12" aria-hidden="true">
      <div className="mx-auto max-w-4xl space-y-6">
        <div className="aspect-[16/9] w-full rounded-lg bg-muted" />
        <div className="space-y-3">
          <div className="h-8 w-2/3 rounded bg-muted" />
          <div className="h-4 w-1/3 rounded bg-muted" />
        </div>
        <div className="space-y-2">
          <div className="h-4 w-full rounded bg-muted" />
          <div className="h-4 w-5/6 rounded bg-muted" />
          <div className="h-4 w-4/6 rounded bg-muted" />
        </div>
      </div>
    </main>
  );
}

export function GridSkeleton({ count = 6 }: { count?: number }) {
  return (
    <main className="container mx-auto animate-pulse px-6 py-12" aria-hidden="true">
      <div className="mb-6 h-9 w-48 rounded bg-muted" />
      <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
        {Array.from({ length: count }, (_, i) => `skeleton-${i}`).map((key) => (
          <div key={key} className="grimoire-card overflow-hidden">
            <div className="aspect-[16/9] w-full bg-muted" />
            <div className="space-y-2 p-4">
              <div className="h-4 w-3/4 rounded bg-muted" />
              <div className="h-3 w-1/2 rounded bg-muted" />
            </div>
          </div>
        ))}
      </div>
    </main>
  );
}
