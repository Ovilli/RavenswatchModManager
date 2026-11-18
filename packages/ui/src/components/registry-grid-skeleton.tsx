/** Reserve the same responsive tracks and artwork space while listings load. */
export function RegistryGridSkeleton() {
  return (
    <div className="registry-grid" aria-hidden="true">
      {Array.from({ length: 10 }, (_, index) => `registry-skeleton-${index}`).map((key) => (
        <div key={key} className="mod-card animate-pulse">
          <div className="mod-card-artwork" />
          <div className="mod-card-body">
            <div className="h-6 w-3/4 rounded bg-surface-2" />
            <div className="h-4 w-1/2 rounded bg-surface-2" />
            <div className="h-4 w-full rounded bg-surface-2" />
          </div>
        </div>
      ))}
    </div>
  );
}
