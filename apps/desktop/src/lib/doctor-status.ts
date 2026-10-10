/**
 * `rsmm doctor`, read once and shared.
 *
 * The Library's setup banner runs it, and so does the share-log dialog, which
 * puts its findings in the report. Each run is a sidecar start, so both read
 * one result for a minute, keyed on what doctor actually inspects. Anything
 * that writes to the game drops it (see `session-cache.ts`).
 */
import { useApp } from '../store';
import { type DoctorResult, doctor } from './rsmm';
import { cachedFor } from './session-cache';

const ONE_MINUTE = 60_000;

export function doctorStatus(fresh = false): Promise<DoctorResult | null> {
  const { gameDir, modsDir } = useApp.getState().settings;
  const { activeProfileId } = useApp.getState();
  return cachedFor(
    `doctor|${gameDir ?? ''}|${modsDir ?? ''}|${activeProfileId}`,
    ONE_MINUTE,
    () => doctor(),
    fresh,
  );
}
