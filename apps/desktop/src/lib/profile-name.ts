/** Shared validation for profile display names (sidebar, profiles page, browse picker). */
export function validateProfileName(name: string): string | null {
  const trimmed = name.trim();
  if (!trimmed) return 'Name is required.';
  if (trimmed.length > 64) return 'Profile names must be 64 characters or fewer.';
  for (const ch of trimmed) {
    const code = ch.codePointAt(0);
    if (code !== undefined && code < 0x20) {
      return 'Profile names may not contain control characters.';
    }
  }
  return null;
}
