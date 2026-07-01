'use client';
import { Spinner } from '@rsmm/ui';
import { useQuery } from '@tanstack/react-query';
import { BarChart3 } from 'lucide-react';
import { api } from '../../lib/api';

/** Download analytics for a mod (owner/co-author). Renders a lightweight CSS
 *  bar chart over the last 30 days + a per-version breakdown. Data comes from
 *  the already day-bucketed mod_downloads table via GET /api/mods/:slug/stats. */
export function ModStats({ slug }: { slug: string }) {
  const stats = useQuery({
    queryKey: ['mods', 'stats', slug],
    queryFn: () => api.mods.stats(slug, 30),
    retry: false,
  });

  const max = Math.max(1, ...(stats.data?.series.map((s) => s.count) ?? [0]));

  return (
    <section className="grimoire-card space-y-4 p-5">
      <div className="flex items-center gap-2">
        <BarChart3 className="h-4 w-4 text-muted-foreground" />
        <h2 className="text-lg font-semibold">Analytics</h2>
      </div>

      {stats.isLoading ? (
        <Spinner />
      ) : stats.isError ? (
        <p className="text-sm text-muted-foreground">Stats unavailable.</p>
      ) : stats.data ? (
        <>
          <p className="text-sm text-muted-foreground">
            {stats.data.totalDownloads.toLocaleString()} total downloads
          </p>

          <div className="flex h-32 items-end gap-0.5" aria-label="downloads over last 30 days">
            {stats.data.series.length === 0 ? (
              <p className="text-sm text-muted-foreground">No downloads in the last 30 days yet.</p>
            ) : (
              stats.data.series.map((s) => (
                <div
                  key={s.day}
                  className="flex-1 rounded-t bg-primary/70"
                  style={{ height: `${Math.max(2, (s.count / max) * 100)}%` }}
                  title={`${s.day}: ${s.count}`}
                />
              ))
            )}
          </div>

          {stats.data.perVersion.length > 0 && (
            <div className="space-y-1">
              <h3 className="text-sm font-medium">By version</h3>
              <ul className="text-sm text-muted-foreground">
                {stats.data.perVersion.map((v) => (
                  <li key={v.version} className="flex justify-between">
                    <span>{v.version}</span>
                    <span>{v.count.toLocaleString()}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </>
      ) : null}
    </section>
  );
}
