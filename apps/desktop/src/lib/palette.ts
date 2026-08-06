/**
 * Row assembly for the command palette.
 *
 * Kept out of the component so the ordering rules — which decide what Enter
 * does on an untouched palette — are testable without a DOM.
 */

export interface PaletteAction {
  id: string;
  label: string;
  /** Extra words the query may match, so "quit modding" finds Restore. */
  keywords: string;
  hint: string;
  disabled?: boolean;
  run: () => void;
}

export interface PaletteHit {
  id: string;
  slug: string;
  name: string;
  author: string;
  origin: 'library' | 'remote';
}

export type PaletteRow =
  | { kind: 'action'; action: PaletteAction }
  | { kind: 'mod'; hit: PaletteHit };

/** How many actions to offer before the user has typed anything. */
export const IDLE_ACTION_COUNT = 3;

export function matchesAction(action: PaletteAction, needle: string): boolean {
  if (!needle) return true;
  return (
    action.label.toLowerCase().includes(needle) || action.keywords.toLowerCase().includes(needle)
  );
}

/**
 * Actions rank above mod hits: typing a verb ("launch", "restore") should
 * land on the verb, not on a mod whose description happens to contain it.
 * With an empty query only the first few actions show, so the palette still
 * opens onto recently-installed mods rather than a wall of menu items.
 */
export function buildRows(
  actions: PaletteAction[],
  hits: PaletteHit[],
  query: string,
): PaletteRow[] {
  const needle = query.trim().toLowerCase();
  const matched = needle
    ? actions.filter((a) => matchesAction(a, needle))
    : actions.slice(0, IDLE_ACTION_COUNT);
  return [
    ...matched.map<PaletteRow>((action) => ({ kind: 'action', action })),
    ...hits.map<PaletteRow>((hit) => ({ kind: 'mod', hit })),
  ];
}
