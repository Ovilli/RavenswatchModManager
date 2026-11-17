import { ProgressBar } from '@rsmm/ui';
import { AlertTriangle, RefreshCw } from 'lucide-react';
import { useEffect, useSyncExternalStore } from 'react';
import {
  type ChannelName,
  describePhase,
  getChannelPhases,
  getLaunchHold,
  setChannelPhase,
  subscribeChannelPhases,
} from '../lib/channel-status';
import { installChannelTriggers } from '../lib/channel-triggers';
import { useT } from '../lib/i18n-react';
import { inTauri } from '../lib/platform';
import { getSkippedMods, setSkippedMods, subscribeSkippedMods } from '../lib/skipped-mods';

const NAMES: ChannelName[] = ['loader', 'cli'];

/**
 * One slim row per CLI / loader update that is checking, downloading, or failed.
 * Successful updates stay quiet here; their status and restart controls live
 * in Settings. Channel triggers stay mounted regardless of which rows are shown.
 */
export function ChannelStatusBanner() {
  const t = useT();
  // Always mounted, so the channels are checked at start whatever route opens.
  useEffect(() => (inTauri() ? installChannelTriggers() : undefined), []);
  const phases = useSyncExternalStore(subscribeChannelPhases, getChannelPhases);
  const hold = useSyncExternalStore(subscribeChannelPhases, getLaunchHold);
  const skipped = useSyncExternalStore(subscribeSkippedMods, getSkippedMods);
  const rows = NAMES.map((name) => ({ name, phase: phases[name] })).filter(
    (r) => r.phase.kind !== 'idle' && r.phase.kind !== 'installed',
  );
  if (rows.length === 0 && !hold && skipped.length === 0) return null;
  return (
    <div className="flex w-full flex-col">
      {hold ? (
        <output className="flex w-full items-center gap-3 border-b border-oxblood/60 bg-oxblood/20 px-4 py-1.5">
          <RefreshCw className="h-4 w-4 shrink-0 animate-spin text-gilt" />
          <span className="flex-1 font-serif-italic text-parchment text-sm">
            {t('Waiting for the game loader update to finish before launching vanilla…')}
          </span>
        </output>
      ) : null}
      {skipped.length > 0 ? (
        <output className="flex w-full items-start gap-3 border-b border-crimson/40 bg-crimson/10 px-4 py-1.5">
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-crimson" />
          <div className="flex-1 font-serif-italic text-crimson text-sm">
            <p>{t('Skipped at launch - the game started without these mods:')}</p>
            <ul>
              {skipped.map((m) => (
                <li key={m.id}>
                  {t('{id} was skipped: {reason}', { id: m.id, reason: m.reason })}
                </li>
              ))}
            </ul>
          </div>
          <button
            type="button"
            onClick={() => setSkippedMods([])}
            className="font-mono text-ash text-xs hover:text-parchment"
          >
            {t('Dismiss')}
          </button>
        </output>
      ) : null}
      {rows.map(({ name, phase }) => {
        const text = describePhase(name, phase);
        const failed = phase.kind === 'failed';
        return (
          <output
            key={name}
            className={`flex w-full items-center gap-3 border-b px-4 py-1.5 ${
              failed ? 'border-crimson/40 bg-crimson/10' : 'border-oxblood/60 bg-oxblood/20'
            }`}
          >
            {failed ? (
              <AlertTriangle className="h-4 w-4 shrink-0 text-crimson" />
            ) : (
              <RefreshCw className="h-4 w-4 shrink-0 animate-spin text-gilt" />
            )}
            <span
              className={`flex-1 font-serif-italic text-sm ${failed ? 'text-crimson' : 'text-parchment'}`}
            >
              {text}
            </span>
            {phase.kind === 'downloading' ? (
              <div className="w-48 max-w-48">
                <ProgressBar
                  value={phase.received}
                  max={phase.total}
                  indeterminate={!phase.total}
                />
              </div>
            ) : null}
            {failed ? (
              <button
                type="button"
                onClick={() => setChannelPhase(name, { kind: 'idle' })}
                className="font-mono text-xs text-ash hover:text-parchment"
              >
                {t('Dismiss')}
              </button>
            ) : null}
          </output>
        );
      })}
    </div>
  );
}
