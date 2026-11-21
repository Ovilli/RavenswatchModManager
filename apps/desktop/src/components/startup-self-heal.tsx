import { useEffect, useRef } from 'react';
import { useT } from '../lib/i18n-react';
import { appendLauncherLog } from '../lib/launcher-log';
import { inTauri } from '../lib/platform';
import { startupSelfHeal } from '../lib/rsmm';
import { useLaunch } from './launch';
import { useToast } from './toast';

/**
 * Once per app launch: put back an install a modded session left behind.
 *
 * The restore watcher undoes a modded launch when the game exits, but nothing
 * did if the watcher was gone first (the PC shut down mid-game), so every plain
 * Steam launch ran modded until the next modded one. Every safeguard lives in
 * the CLI (`rsmm.cli.self_heal`); this only waits until no launch is in flight,
 * runs it once, and says so when it restored something. Never on focus: an
 * unattended restore is too heavy, and too risky, to repeat.
 */
export function StartupSelfHeal() {
  const t = useT();
  const toast = useToast();
  const { busy } = useLaunch();
  const started = useRef(false);

  useEffect(() => {
    if (started.current || busy || !inTauri()) return;
    started.current = true;
    void startupSelfHeal().then(async (r) => {
      if (!r) return;
      await appendLauncherLog(
        r.action === 'restored' || !r.ok ? 'warn' : 'info',
        `[Self-heal] ${r.action}: ${r.reason}`,
        { detail: r.detail },
      );
      if (r.action !== 'restored') return;
      toast.push(
        r.code === 2
          ? t(
              'Mods from your last session were still in the game, because it or your PC closed before RSMM could remove them. Most original files are back; run Doctor to check the rest.',
            )
          : t(
              'Mods from your last session were still in the game, because it or your PC closed before RSMM could remove them. The original files are back.',
            ),
        r.code === 2 ? 'error' : 'success',
      );
    });
  }, [busy, t, toast]);

  return null;
}
