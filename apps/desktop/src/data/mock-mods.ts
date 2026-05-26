/**
 * Library-wide type definitions for a mod surfaced in the UI.
 *
 * Previously this module also exported a `MOCK_MODS` array used to
 * pre-populate the library / browse pages before the real index API
 * existed. Now that uploads are live (see `apps/api/src/routes/mods.ts`
 * and `apps/desktop/src/routes/upload.tsx`), the UI sources mods from:
 *
 * 1. the local disk via `listLocalMods()` (rsmm CLI) — held in
 *    `useApp(s => s.localMods)`;
 * 2. the remote index via `api.mods.list()` (React Query).
 *
 * No bundled stand-in data here anymore. `MockMod` keeps its name for
 * back-compat with the store's `localMods: Record<string, MockMod>`
 * shape; the fields it carries are filled in by `toMockMod()` in
 * `store/index.ts` from real `LocalMod` records.
 */

export type ModCategory =
  | 'gameplay'
  | 'balance'
  | 'cosmetic'
  | 'qol'
  | 'audio'
  | 'difficulty'
  | 'speedrun'
  | 'utility';

export interface MockMod {
  id: string;
  slug: string;
  name: string;
  author: string;
  version: string;
  latestVersion: string;       // > version means outdated
  category: ModCategory;
  summary: string;
  description: string;
  changelog: string;
  rating: number;              // 0-5
  downloads: number;
  sizeKb: number;
  tags: string[];
  dependencies: string[];
  /** Cooked file paths this mod writes. Two mods that share a path conflict. */
  writes: string[];
  /** Compatible Ravenswatch build numbers (informational). */
  gameBuild: string;
  /** Store-page hero image. Resolved relative to the mod's asset bundle. */
  image?: string;
  /** Long-form store-page copy in Markdown. Rendered on the mod detail page. */
  markdown: string;
  /** Content rating — true if the mod contains NSFW material. */
  nsfw?: boolean;
}
