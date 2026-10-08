import { useCallback } from 'react';
import { useT } from '../lib/i18n-react';
import type { ConfirmDisableHook } from '../lib/rsmm';
import { getMod } from '../store';
import { useDialog } from './toast';

/**
 * The question `uninstallLocalMod` asks before a mod's `on_disable.py` runs.
 *
 * The script exists to undo what the mod wrote into the game's own files (a
 * pinned seed in GameSettings.ini), which is worth running for a mod the user
 * trusts. It is also arbitrary Python from whoever published the mod, so the
 * user decides, and declining still removes the mod.
 */
export function useConfirmDisableHook(): ConfirmDisableHook {
  const dialog = useDialog();
  const t = useT();
  return useCallback(
    (modId: string) =>
      dialog.confirm({
        title: t("Run {name}'s cleanup script?", { name: getMod(modId)?.name ?? modId }),
        body: t(
          "This mod ships a cleanup script (on_disable.py) that undoes changes it made to the game. It runs as you, outside the game, with access to all your files. Run it only if you trust the mod's author. The mod is removed either way.",
        ),
        confirmLabel: t('Run script'),
        cancelLabel: t('Remove without running'),
        destructive: true,
      }),
    [dialog, t],
  );
}
