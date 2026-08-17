/**
 * "Configure" link for a mod that declares config fields.
 *
 * A mod's settings used to be reachable only by flipping the WHOLE library into
 * its config view through an unlabelled toolbar icon — nothing on the mod itself
 * said it had settings at all. This renders next to the mod's own controls, and
 * renders nothing for a mod that ships no schema.
 *
 * `hasConfig` rides along on the mod list payload rather than being asked per
 * mod: the answer is needed for every visible row, and one `rsmm json config
 * get` spawn per installed mod to learn a boolean is not worth it. The real
 * schema (and any parse error in it) is loaded by the panel this links to.
 */
import { Link } from '@tanstack/react-router';
import { SlidersHorizontal } from 'lucide-react';

/** The anchor the mod detail page gives its config panel. */
export const CONFIG_ANCHOR = 'mod-config';

export function ConfigButton({
  slug,
  hasConfig,
  className,
}: {
  slug: string;
  hasConfig?: boolean;
  className?: string;
}) {
  if (!hasConfig) return null;
  // Icon only: a card's action row already carries a switch, the overlay
  // button and uninstall, and a fourth labelled control overflowed the card.
  // The label lives in title + aria-label so it stays reachable.
  return (
    <Link
      to="/mod/$slug"
      params={{ slug }}
      hash={CONFIG_ANCHOR}
      className={`btn-grim shrink-0 px-2 py-1.5 ${className ?? ''}`}
      title="Configure — open this mod's settings"
      aria-label="Configure this mod"
    >
      <SlidersHorizontal className="h-4 w-4" />
    </Link>
  );
}
