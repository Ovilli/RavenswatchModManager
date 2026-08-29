/**
 * One-click overlay toggle for a single mod.
 *
 * An overlay was previously reachable only through the command palette
 * (Ctrl+K → "Toggle … overlay") or a list in Settings — both a detour away from
 * the mod that owns the HUD. This puts the control next to the mod itself, and
 * the Settings list is gone: this button plus the palette entry are the paths.
 *
 * Nothing here is hardcoded to a particular mod: it renders only when the mod
 * declares an `[overlay]` block, and renders nothing otherwise, so the library
 * gains a button exactly for the mods that have a HUD.
 *
 * Whether an overlay is open is WINDOW state, not React state. Both queries are
 * shared through React Query, so the library row and the mod detail page agree
 * about the same mod, and a window the user closed with its own X button is
 * noticed on the next poll instead of leaving a stuck "Hide" label.
 */
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { Gauge } from 'lucide-react';
import { useState } from 'react';
import { useT } from '../lib/i18n-react';
import {
  closeOverlay,
  openOverlay,
  openOverlayMods,
  overlayFor,
  resetPosition,
  toggleOverlay,
} from '../lib/overlay-windows';
import { listOverlays } from '../lib/rsmm';
import { Button } from './chrome';
import { useToast } from './toast';

/** Shared with the command palette, which asks the CLI the same question. */
const DECLARED_KEY = ['overlays'] as const;
/** Which overlay windows exist right now. */
const OPEN_WINDOWS_KEY = ['overlay-windows'] as const;

export function useDeclaredOverlays() {
  return useQuery({
    queryKey: DECLARED_KEY,
    queryFn: () => listOverlays(),
    // A stale entry is harmless — a mod's declaration only changes on install.
    staleTime: 30_000,
    // Outside Tauri (or with no game dir yet) this throws; a missing button is
    // the right outcome, so don't retry it on every mounted row.
    retry: false,
  });
}

export function OverlayButton({ modId, className }: { modId: string; className?: string }) {
  const t = useT();
  const toast = useToast();
  const queryClient = useQueryClient();
  const { data: declared } = useDeclaredOverlays();
  const { data: openMods } = useQuery({
    queryKey: OPEN_WINDOWS_KEY,
    queryFn: () => openOverlayMods(),
    // Catches a window closed from its own title bar without a click here.
    refetchInterval: 4_000,
    initialData: [] as string[],
  });
  const [busy, setBusy] = useState(false);

  const record = overlayFor(declared?.overlays, modId);
  if (!record) return null;

  const isOpen = openMods.includes(modId);
  const name = record.title ?? record.modName ?? modId;

  return (
    <Button
      type="button"
      size="sm"
      variant={isOpen ? 'gilt' : 'default'}
      disabled={busy || Boolean(record.error)}
      title={
        record.error
          ? t("This mod's overlay declaration is broken: {error}", { error: record.error })
          : isOpen
            ? t('Close the {name} overlay (shift-click to recentre it)', { name })
            : t(
                'Open the {name} overlay — an always-on-top HUD window (shift-click to open it at the default position)',
                { name },
              )
      }
      aria-pressed={isOpen}
      className={className}
      onClick={(e) => {
        // An overlay reopens where it was left, so a window dragged off a
        // monitor that is now gone comes back off-screen and cannot be
        // grabbed. Shift-click forgets the saved position and reopens it at
        // the default spot — the only recovery, since the window itself is
        // unreachable.
        const recentre = e.shiftKey;
        void (async () => {
          setBusy(true);
          try {
            if (recentre) {
              resetPosition(modId);
              await closeOverlay(modId);
              await openOverlay(modId);
              toast.push(t('{name} overlay recentred.', { name }), 'success');
              return;
            }
            const opened = await toggleOverlay(modId);
            toast.push(
              opened
                ? t('{name} overlay opened.', { name })
                : t('{name} overlay closed.', { name }),
              'success',
            );
          } catch (err) {
            toast.push(
              t('Overlay failed: {error}', {
                error: err instanceof Error ? err.message : String(err),
              }),
              'error',
            );
          } finally {
            setBusy(false);
            await queryClient.invalidateQueries({ queryKey: OPEN_WINDOWS_KEY });
          }
        })();
      }}
    >
      <Gauge className="h-4 w-4" /> {isOpen ? t('Hide overlay') : t('Overlay')}
    </Button>
  );
}
