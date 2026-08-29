import { useQuery, useQueryClient } from '@tanstack/react-query';
import { Link } from '@tanstack/react-router';
import { ArrowUpCircle, Loader2, RefreshCw } from 'lucide-react';
import { useEffect, useState } from 'react';
import { api, describeApiError, logApiError } from '../lib/api';
import { useT } from '../lib/i18n-react';
import { inTauri } from '../lib/platform';
import { installModFromIndex, listLocalMods } from '../lib/rsmm';
import { outdatedMods, useApp } from '../store';
import { Button, Fleuron, Panel } from './chrome';

/**
 * Library-page widget showing installed mods with available updates.
 * Polls the public registry for latest versions, then offers a
 * one-click bulk update. Reuses the same install-from-index flow as
 * Browse, so update == reinstall the newer version.
 */
export function UpdatesPanel() {
  const t = useT();
  const installed = useApp((s) => s.installed);
  const patchRemoteInfo = useApp((s) => s.patchRemoteInfo);
  const syncLocalMods = useApp((s) => s.syncLocalMods);
  const queryClient = useQueryClient();
  const [updating, setUpdating] = useState<Record<string, boolean>>({});
  const [error, setError] = useState<string | null>(null);

  const remote = useQuery({
    queryKey: ['mods', 'updates-poll'],
    queryFn: () => api.mods.list({ limit: 100, sort: 'recent' }),
    enabled: inTauri() && installed.length > 0,
    staleTime: 5 * 60_000,
  });

  // The poll failing means "updates available" can silently read 0 —
  // at least say so in the console (Browse shows the visible banner
  // when the API is down) and in the panel when it is rendered.
  useEffect(() => {
    if (remote.error) logApiError('updates-panel', remote.error);
  }, [remote.error]);

  // Push remote latestVersion + image into the store so the rest of the
  // UI (mod cards, detail pages) stays consistent without a second poll.
  useEffect(() => {
    if (!remote.data) return;
    const map: Record<
      string,
      {
        latestVersion: string | null;
        image: string | null;
        summary: string | null;
        nsfw: boolean | null;
      }
    > = {};
    for (const m of remote.data.items) {
      map[m.slug] = {
        latestVersion: m.latestVersion,
        image: m.imageUrl ?? null,
        summary: m.summary ?? null,
        nsfw: m.nsfw ?? null,
      };
    }
    patchRemoteInfo(map);
  }, [remote.data, patchRemoteInfo]);

  const outdated = outdatedMods(installed);

  async function updateOne(slug: string) {
    setError(null);
    setUpdating((m) => ({ ...m, [slug]: true }));
    try {
      const result = await installModFromIndex(slug);
      if (!result || !result.ok) {
        throw new Error(result?.error ?? t('update failed'));
      }
      const local = await listLocalMods();
      if (local) syncLocalMods(local);
      await queryClient.invalidateQueries({ queryKey: ['mods'] });
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setUpdating((m) => ({ ...m, [slug]: false }));
    }
  }

  async function updateAll() {
    for (const m of outdated) {
      // eslint-disable-next-line no-await-in-loop
      await updateOne(m.slug);
    }
  }

  if (!inTauri()) return null;
  if (installed.length === 0) return null;
  if (remote.isLoading && outdated.length === 0) return null;
  if (outdated.length === 0) return null;

  // Updates run sequentially, so "any in progress" is the right signal for
  // the bulk button — otherwise it only disables in the brief window where
  // every single item happens to be in-flight at once (never, in practice).
  const anyUpdating = outdated.some((m) => updating[m.slug]);

  return (
    <Panel className="border-gilt/40">
      <header className="flex flex-wrap items-center justify-between gap-3">
        <h3 className="font-fraktur text-xl text-parchment flex items-center gap-2">
          <ArrowUpCircle className="h-5 w-5 text-gilt" aria-hidden />
          {t.n(outdated.length, '{n} update available', '{n} updates available')}
        </h3>
        <div className="flex items-center gap-2">
          <Button
            type="button"
            size="sm"
            onClick={() => {
              void remote.refetch();
            }}
            title={t('Re-check the registry for newer versions')}
          >
            <RefreshCw className="h-3.5 w-3.5" /> {t('Recheck')}
          </Button>
          <Button
            type="button"
            size="sm"
            variant="primary"
            onClick={() => void updateAll()}
            disabled={anyUpdating}
          >
            {anyUpdating ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : null}
            {t('Update all')}
          </Button>
        </div>
      </header>
      <Fleuron />
      <ul className="mt-4 divide-y divide-oxblood/20">
        {outdated.map((m) => {
          const busy = updating[m.slug] === true;
          return (
            <li key={m.id} className="flex items-center justify-between gap-3 py-2">
              <div className="min-w-0">
                <Link
                  to="/mod/$slug"
                  params={{ slug: m.slug }}
                  className="font-serif-italic text-parchment hover:text-gilt"
                >
                  {m.name}
                </Link>
                <p className="font-mono text-[11px] text-ash">
                  v{m.version} → <span className="text-gilt">v{m.latestVersion}</span>
                </p>
              </div>
              <Button
                type="button"
                size="sm"
                onClick={() => void updateOne(m.slug)}
                disabled={busy}
              >
                {busy ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : null}
                {busy ? t('Updating…') : t('Update')}
              </Button>
            </li>
          );
        })}
      </ul>
      {error ? <p className="mt-3 font-mono text-xs text-crimson">{error}</p> : null}
      {remote.isError ? (
        <p className="mt-3 font-mono text-xs text-crimson">
          {t('Registry recheck failed: {error}', { error: describeApiError(remote.error) })}
        </p>
      ) : null}
    </Panel>
  );
}
