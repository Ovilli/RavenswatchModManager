/**
 * Parse ADMIN_USER_IDS into a list of user ids.
 *
 * Splits on commas, semicolons and any whitespace (newlines included), and
 * strips quotes around each id, because that is how a list ends up in the
 * Vercel env UI: pasted one per line, or `"a", "b"`. Splitting on commas
 * alone turned `a b` or `a\nb` into one id that matched nobody, so only a
 * single admin ever worked.
 */
export function parseAdminUserIds(raw: string | undefined): string[] {
  const ids = (raw ?? '')
    .split(/[\s,;]+/)
    .map((s) => s.replace(/^["'`]+|["'`]+$/g, ''))
    .filter(Boolean);
  return [...new Set(ids)];
}
