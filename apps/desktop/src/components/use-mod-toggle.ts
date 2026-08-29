/**
 * Enabling and disabling mods, with the dependency prompts.
 *
 * Extracted from the Library because the mod detail page needs the SAME
 * behaviour: enabling a mod pulls its dependencies in topological order, and
 * disabling one that others depend on asks first. A second, simpler copy on the
 * detail page would let a user break a dependency chain from one screen that
 * the other screen protects.
 */
import { useCallback } from 'react';
import { useT } from '../lib/i18n-react';
import { buildEnablePlan, findBlockingDependents } from '../lib/library-deps';
import { activeProfile, isEnabledIn, useApp } from '../store';
import { useDialog } from './toast';

export interface ModToggle {
  /** Enable `ids` plus their dependencies, prompting if any are missing. */
  enableMods: (ids: string[]) => Promise<void>;
  /** Disable `ids`, prompting when that leaves dependents without a dependency. */
  disableMods: (ids: string[]) => Promise<void>;
  /** Flip one mod, taking whichever of the two paths applies. */
  toggle: (id: string) => void;
}

/**
 * @param onSettled Ran after a completed enable/disable (not after a cancelled
 *   prompt) — the Library uses it to clear its selection.
 */
export function useModToggle(onSettled?: () => void): ModToggle {
  const t = useT();
  const dialog = useDialog();
  const profile = useApp(activeProfile);
  const toggleMod = useApp((s) => s.toggleMod);

  const enableMods = useCallback(
    async (ids: string[]) => {
      const plan = buildEnablePlan(ids);
      if (plan.missing.length > 0) {
        const ok = await dialog.confirm({
          title: t('Missing dependencies'),
          body: t(
            'These dependencies are not installed: {list}. Enable the selected mods anyway?',
            { list: plan.missing.join(', ') },
          ),
          confirmLabel: t('Enable anyway'),
          destructive: true,
        });
        if (!ok) return;
      }
      for (const id of plan.order) {
        if (!isEnabledIn(profile, id)) toggleMod(id);
      }
      onSettled?.();
    },
    [dialog, onSettled, profile, t, toggleMod],
  );

  const disableMods = useCallback(
    async (ids: string[]) => {
      const blocked = findBlockingDependents(ids, profile);
      if (blocked.length > 0) {
        const body = blocked
          .map(([target, dependents]) => `${target}: ${dependents.join(', ')}`)
          .join('\n');
        const ok = await dialog.confirm({
          title: t('Broken dependency chain'),
          body: `${t('Disabling these mods will leave others missing dependencies:')}\n${body}\n${t('Continue?')}`,
          confirmLabel: t('Disable anyway'),
          destructive: true,
        });
        if (!ok) return;
      }
      for (const id of ids) {
        if (isEnabledIn(profile, id)) toggleMod(id);
      }
      onSettled?.();
    },
    [dialog, onSettled, profile, t, toggleMod],
  );

  const toggle = useCallback(
    (id: string) => {
      if (isEnabledIn(profile, id)) void disableMods([id]);
      else void enableMods([id]);
    },
    [disableMods, enableMods, profile],
  );

  return { enableMods, disableMods, toggle };
}
