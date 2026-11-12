/**
 * Who "add co-author" means. People type a display name ("Pam"), a handle,
 * "@handle" or a user id; many accounts (Google / Steam sign-ins) have no
 * handle at all, so a handle-only lookup could never find them and answered 404.
 *
 * A user id (exact) wins, then a handle (both unique). Otherwise a display
 * name matches only when it names exactly one account; two "Pam"s ask for the
 * handle instead of picking one. Handles and names ignore case and spaces.
 */

export interface CoAuthorCandidate {
  id: string;
  name: string | null;
  handle: string | null;
}

export type CoAuthorPick =
  | { kind: 'found'; user: CoAuthorCandidate }
  | { kind: 'ambiguous'; count: number }
  | { kind: 'none' };

/** The text to look up: trimmed, without a leading "@". */
export function coAuthorQuery(raw: string): string {
  return raw.trim().replace(/^@+/, '').trim();
}

/** Escape LIKE wildcards so `ilike` compares the text exactly (case-insensitively). */
export function likeExact(text: string): string {
  return text.replace(/[\\%_]/g, (ch) => `\\${ch}`);
}

export function pickCoAuthor(query: string, candidates: CoAuthorCandidate[]): CoAuthorPick {
  const exact = coAuthorQuery(query);
  const q = exact.toLowerCase();
  if (!q) return { kind: 'none' };
  const byId = candidates.find((u) => u.id === exact);
  if (byId) return { kind: 'found', user: byId };
  const byHandle = candidates.find((u) => u.handle?.trim().toLowerCase() === q);
  if (byHandle) return { kind: 'found', user: byHandle };
  const byName = candidates.filter((u) => u.name?.trim().toLowerCase() === q);
  const [only, ...rest] = byName;
  if (only && rest.length === 0) return { kind: 'found', user: only };
  if (only) return { kind: 'ambiguous', count: byName.length };
  return { kind: 'none' };
}
